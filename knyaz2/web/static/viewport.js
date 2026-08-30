// Поверхность кадра: холст, слои, камера и фильтр времени суток.
//
// Движок пересчитывает палитры при смене уровня, а браузер так не умеет:
// фильтр суток — это заливка целого слоя. Поэтому кадр собирается послойно,
// и всё, что движок рисует ИСХОДНОЙ палитрой (интерьеры построек, юнит на
// клетке с битом 22), уходит прямо на холст мимо заливки. Здесь живёт вся
// механика этих слоёв; остальные модули только просят текущий контекст.
import { canvas, zoomNode } from "./dom.js";
import { daylight } from "./daylight.js";
import { mapBounds, world } from "./world.js";

export const mainContext = canvas.getContext("2d", { alpha: false });

// Слой сцены: то, что затемняется фильтром дня и ночи. Прозрачность после
// сплошной заливки нужно вернуть по этой копии альфы, иначе сама заливка
// становится изображением и полупрозрачные пиксели светлеют вместо затемнения.
const sceneLayer = {
  canvas: document.createElement("canvas"),
  context: null,
  alpha: document.createElement("canvas"),
  alphaContext: null,
};
sceneLayer.context = sceneLayer.canvas.getContext("2d");
sceneLayer.alphaContext = sceneLayer.alpha.getContext("2d");

//: Текущая цель рисования. Живая привязка модуля: `beginSceneLayer` и
//: `withMainContext` её переключают, импортирующие модули видят новое значение.
export let context = mainContext;

//: Рамка выбора: мировые координаты протяжки. Живёт здесь, потому что её
//: рисует сцена, а тянет обработчик мыши.
// КАДР С ЛИСТА. Движок держит спрайты одной ареной и берёт их по
// смещению (VA 0x43C2E8), а не файлами; пак повторяет это листами, и кадр
// приносит с собой прямоугольник на листе вместо своего пути. Здесь одна
// точка, через которую рисуются оба вида: старый кадр-файл и кадр с листа.
export function drawSprite(images, sheets, frame, x, y, target = null) {
  if (!frame) return false;
  const where = target ?? context;
  if (frame.sheet !== undefined) {
    const sheet = sheets?.[frame.sheet];
    const image = sheet && images.get(sheet.path);
    if (!image) return false;
    where.drawImage(image, frame.x, frame.y, frame.width, frame.height,
                    x, y, frame.width, frame.height);
    return true;
  }
  const image = images.get(frame.path);
  if (!image) return false;
  where.drawImage(image, x, y);
  return true;
}

// Готов ли кадр к отрисовке — тем же правилом для обоих видов.
// ЛИСТ ТЯНЕТСЯ, КОГДА ПОНАДОБИЛСЯ.
//
// Кадры лежат на 72 листах общим весом 121.6 МБ. Ждать их все до первого
// кадра нельзя (это были минуты белого экрана), но и тянуть фоном «всё
// остальное» тоже нельзя: заход всё равно стоил бы сто с лишним мегабайт,
// причём за листы, которых игрок в этой локации не увидит.
//
// Поэтому здесь, в единственном месте, где спрашивают «картинка готова?»,
// недостающий лист заказывается — один раз, дальше заявку гасит дедупликация
// в `world.requestAsset`. Пока лист едет, юнит рисуется базовым телом: это
// уже заложено в actorBody и drawActor.
export function spriteReady(images, sheets, frame) {
  if (!frame) return false;
  if (frame.sheet !== undefined) {
    const sheet = sheets?.[frame.sheet];
    if (!sheet) return false;
    if (images.has(sheet.path)) return true;
    world.requestAsset?.(sheet.path);
    return false;
  }
  if (images.has(frame.path)) return true;
  world.requestAsset?.(frame.path);
  return false;
}

export const band = {
  active: false, addMode: false,
  fromX: 0, fromY: 0, toX: 0, toY: 0,
};

export const view = {
  //: ЗАКАЗ ПЕРЕРИСОВКИ, А НЕ САМА ПЕРЕРИСОВКА. Протяжка мыши и колесо звали
  //: `render()` прямо из обработчика, поверх той, что уже идёт из кадра:
  //: в замере игрока 579 отрисовок на 425 кадров — треть работы впустую.
  //: Теперь обработчик поднимает флаг, а рисует кадровый цикл, один раз.
  dirty: false,
  width: 1,
  height: 1,
  dpr: Math.max(1, window.devicePixelRatio || 1),
  cameraX: 0,
  cameraY: 0,
  zoom: 0.45,
  dragging: false,
  pointerX: 0,
  pointerY: 0,
  //: Камера привязана к выбранному лицу — настройка игрока, не канон.
  //: Ставится из settings.js, по умолчанию выключена.
  follow: false,
};

// КАМЕРА НЕ ВЫЕЗЖАЕТ ЗА КРАЙ КАРТЫ (VA 0x4291B4 и 0x437CD0 — там дословно
// один и тот же кусок, и наведение, и краевая прокрутка). Рамку считает
// загрузчик карты по крайним непустым клеткам сетки (VA 0x43DF48), она
// приезжает в паке как `coordinates.camera`.
//
// Движок держит ЛЕВЫЙ ВЕРХ камеры и окно 884x708:
//     если x < лево         -> x = лево
//     иначе если право < x + 884 -> x = право − 884
//     если y < 32           -> y = 32
//     иначе если низ < y + 708   -> y = низ − 708
//
// У нас камера — ЦЕНТР вида, а окно резиновое и с зумом, поэтому то же
// правило пересчитано в центровую форму: видимая половина = width/2/zoom.
// Порядок веток сохранён: когда карта уже окна, выигрывает первая, и камера
// прижимается к левому верхнему углу, а не дёргается между границами.
//: Предел приближения — наш, отрисовочный: движок масштаба не знал вовсе.
export const ZOOM_LIMIT = { min: 0.1, max: 2.5 };

// НИЖНИЙ ПРЕДЕЛ МАСШТАБА СЧИТАЕТСЯ ПО САМОЙ КАРТЕ.
//
// Одному клампу камеры за край не удержать: когда видимая область СТАНОВИТСЯ
// ШИРЕ КАРТЫ, двигать её уже некуда — как ни ставь, с одной стороны останется
// пустота. Значит, предел должен стоять на масштабе: видимая ширина
// `width / zoom` не смеет превысить ширину рамки карты, и так же по высоте.
// Отсюда пол — наибольшее из двух отношений, но не ниже общего предела.
//
// Рамку считает загрузчик карты по крайним непустым клеткам (VA 0x43DF48), и
// приезжает она в паке как `coordinates.camera` — та же, по которой движок
// держит камеру.
export function zoomFit() {
  const bounds = world.map?.coordinates?.camera ?? null;
  if (!bounds) return ZOOM_LIMIT.min;
  const width = (bounds.right ?? 0) - (bounds.left ?? 0);
  const height = (bounds.bottom ?? 0) - (bounds.top ?? 0x20);
  if (width <= 0 || height <= 0) return ZOOM_LIMIT.min;
  return Math.max(ZOOM_LIMIT.min, view.width / width, view.height / height);
}

export function zoomClamp(value) {
  return Math.max(zoomFit(), Math.min(ZOOM_LIMIT.max, value));
}

export function clampCamera() {
  const bounds = world.map?.coordinates?.camera ?? null;
  if (!bounds) return false;
  const before = `${view.cameraX},${view.cameraY},${view.zoom}`;
  // Масштаб поджимаем ПЕРВЫМ: половины вида считаются уже от него, и после
  // этого «карта уже окна» стать не может — обе ветки ниже работают как
  // задумано, а не прижимают камеру к углу.
  const zoomWas = view.zoom;
  view.zoom = zoomClamp(view.zoom);
  //: Поджали сами — значит и подпись с процентами обязана это показать.
  if (view.zoom !== zoomWas) updateZoom();
  const halfW = view.width / 2 / view.zoom;
  const halfH = view.height / 2 / view.zoom;
  //: С перспективой половины разные: вверх дальше, вниз ближе. Без этого
  //: камеру держало по плоской мерке — сверху открывались лишние три клетки,
  //: а нижний край карты становился недостижим, и с него нельзя было выйти
  //: на карту мира.
  const reach = extent?.(halfW, halfH) ??
    { up: halfH, down: halfH, side: halfW };
  const left = bounds.left ?? 0, right = bounds.right ?? 0;
  const top = bounds.top ?? 0x20, bottom = bounds.bottom ?? 0;
  if (view.cameraX - reach.side < left) view.cameraX = left + reach.side;
  else if (view.cameraX + reach.side > right) view.cameraX = right - reach.side;
  if (view.cameraY - reach.up < top) view.cameraY = top + reach.up;
  else if (view.cameraY + reach.down > bottom) view.cameraY = bottom - reach.down;
  return before !== `${view.cameraX},${view.cameraY},${view.zoom}`;
}

// КАМЕРА ЗА ВЫБРАННЫМ ЛИЦОМ — НАША НАСТРОЙКА, А НЕ КАНОН.
//
// В движке камеру двигают ровно два места: курсор у края экрана (VA 0x437CD0)
// и наведение при загрузке карты (VA 0x4291B4). Сама за героем она не ходит
// никогда — идущий персонаж спокойно уходит за край окна.
//
// На телефоне не работает ни то, ни другое: курсора у края не бывает, средней
// кнопки — нашей замены краевой прокрутке — тоже нет. Поэтому по желанию
// игрока камера просто держит выбранного в середине окна, как в Diablo II.
// Плавность берётся даром: юнит и так едет между клетками по долям такта, а
// кламп не пускает камеру за край карты — тем же правилом, что и в движке.
export function cameraFollow(target) {
  if (!view.follow) return false;
  const x = target?.x, y = target?.y;
  if (!Number.isFinite(x) || !Number.isFinite(y)) return false;
  const before = `${view.cameraX},${view.cameraY}`;
  view.cameraX = x;
  view.cameraY = y;
  clampCamera();
  return before !== `${view.cameraX},${view.cameraY}`;
}

// Кадр сейчас собирается послойно (см. render): «дневное» рисуется прямо на
// холст, а из слоя сцены вырезается силуэт, чтобы оно проступило.
export let layeredFrame = false;

export function setLayeredFrame(value) {
  layeredFrame = value;
}

//: `target` — куда обводить. По умолчанию текущий кадр, но выпечка земли
//: (ground.js) рисует метку недогруженной плитки в свой холст.
export function traceDiamond(x, y, target = context) {
  const grid = world.map.coordinates.ground_grid;
  target.beginPath();
  target.moveTo(x + grid.tile_width / 2, y);
  target.lineTo(x + grid.tile_width, y + grid.tile_height / 2);
  target.lineTo(x + grid.tile_width / 2, y + grid.tile_height);
  target.lineTo(x, y + grid.tile_height / 2);
  target.closePath();
}

export function cellVisible(x, y, visible) {
  const grid = world.map.coordinates.ground_grid;
  return !(x > visible.right || y > visible.bottom ||
    x + grid.tile_width < visible.left || y + grid.tile_height < visible.top);
}


// Вернуть рисование на сам кадр: с этого начинается каждый кадр и этим
// заканчивается сборка слоя.
export function useMainContext() {
  context = mainContext;
  return context;
}

// Нарисовать что-то мимо слоя сцены — прямо на кадр, минуя фильтр суток.
//
//: Подмены цели здесь больше нет. Она была нужна выпечке построек: та
//: печатала светлые кадры интерьера в свой холст, а не на экран. Кэш
//: выпечки (props.js) не воспроизводил картинку и лежал выключенным —
//: удалён вместе с этой подменой.
export function withMainContext(draw) {
  const previous = context;
  context = mainContext;
  draw();
  context = previous;
}

// СВЕТЛЫЙ КАДР: на сам кадр, мимо фильтра суток, плюс окно в слое сцены.
//
// Так рисуется интерьер постройки (VA 0x425B0C блитит main исходной
// палитрой). Вырез здесь НЕМЕДЛЕННЫЙ, и это правильно ровно потому, что всё,
// что должно закрыть интерьер, — стены, крыша, фигуры снаружи — ложится в
// слой ПОЗЖЕ и закрашивает окно обратно.
//
// У светлого ЮНИТА так нельзя: его рисуют посреди прохода по глубине, и слой
// под ним ещё не собран. Его окно откладывается до конца прохода —
// units.renderBrightCuts, docs/RENDER_DEPTH.md.
export function drawBrightImage(image, x, y) {
  withMainContext(() => context.drawImage(image, x, y));
  context.save();
  context.globalCompositeOperation = "destination-out";
  context.globalAlpha = 1;
  context.drawImage(image, x, y);
  context.restore();
}

// Тот же светлый кадр, но КУСКОМ: нужен полосовой укладке построек
// (perspective.drawMesh). Правило то же — на кадр мимо фильтра плюс
// немедленный вырез из слоя ровно теми же координатами.
export function drawBrightPart(image, sx, sy, sw, sh, dx, dy, dw, dh) {
  withMainContext(() => context.drawImage(image, sx, sy, sw, sh, dx, dy, dw, dh));
  context.save();
  context.globalCompositeOperation = "destination-out";
  context.globalAlpha = 1;
  context.drawImage(image, sx, sy, sw, sh, dx, dy, dw, dh);
  context.restore();
}

// ПАСМУРНОСТЬ. Наша добавка (у Diablo дождь свет не трогает, у Князя
// погоды нет вовсе), но сделана КАНОННОЙ механикой: это обычный уровень
// канала 0…100, который складывается с суточным. Кладёт сюда значение
// weather.js — так модуль погоды не попадает в зависимости камеры.
export const overcast = { level: 0 };

export function applyDaylight() {
  // Раскладка каналов из цикла пересчёта палитр (VA 0x441E47): таблица c8
  // применяется к младшим битам слова (синий), c9 — к средним (зелёный),
  // c10 — к старшим (красный).
  //: ТУЧИ ГАСЯТ ТРИ КАНАЛА ПОРОВНУ и складываются с суточным уровнем;
  //: сумма зажата в канонные −100…100, иначе множитель уходит в минус.
  const тучи = Math.max(0, overcast.level || 0);
  const [b, g, r] = daylight.levels.map(
    (level) => Math.max(-100, Math.min(100, level - тучи)));
  if (!r && !g && !b) return;
  const multiply = [r, g, b].map((level) =>
    Math.round(255 * (100 - Math.abs(level)) / 100));
  const additive = [r, g, b].map((level) =>
    level > 0 ? Math.round(255 * level / 100) : 0);
  context.save();
  context.setTransform(1, 0, 0, 1, 0, 0);
  context.globalCompositeOperation = "multiply";
  context.fillStyle = `rgb(${multiply[0]}, ${multiply[1]}, ${multiply[2]})`;
  context.fillRect(0, 0, canvas.width, canvas.height);
  if (additive.some(Boolean)) {
    context.globalCompositeOperation = "lighter";
    context.fillStyle = `rgb(${additive[0]}, ${additive[1]}, ${additive[2]})`;
    context.fillRect(0, 0, canvas.width, canvas.height);
  }
  context.restore();
}


// Перерисовку после изменения размера заказывает точка входа: слой камеры
// ничего не знает про сборку кадра, поэтому граф модулей остаётся без петель.
export function resize() {
  const rect = canvas.getBoundingClientRect();
  view.width = Math.max(1, rect.width);
  view.height = Math.max(1, rect.height);
  view.dpr = Math.max(1, window.devicePixelRatio || 1);
  canvas.width = Math.round(view.width * view.dpr);
  canvas.height = Math.round(view.height * view.dpr);
  //: Окно выросло — прежний масштаб мог стать слишком мелким для карты.
  //: Сюда же приходит поворот телефона и вход в полный экран.
  clampCamera();
}

export function visibleWorld() {
  const halfW = view.width / (2 * view.zoom);
  const halfH = view.height / (2 * view.zoom);
  return {
    left: view.cameraX - halfW - 256,
    right: view.cameraX + halfW + 256,
    top: view.cameraY - halfH - 256,
    bottom: view.cameraY + halfH + 256,
  };
}

export function worldTransform(target) {
  target.setTransform(
    view.dpr * view.zoom, 0, 0, view.dpr * view.zoom,
    view.dpr * (view.width / 2 - view.cameraX * view.zoom),
    view.dpr * (view.height / 2 - view.cameraY * view.zoom),
  );
  target.imageSmoothingEnabled = false;
}

export function beginSceneLayer() {
  if (sceneLayer.canvas.width !== canvas.width ||
      sceneLayer.canvas.height !== canvas.height) {
    sceneLayer.canvas.width = canvas.width;
    sceneLayer.canvas.height = canvas.height;
    sceneLayer.alpha.width = canvas.width;
    sceneLayer.alpha.height = canvas.height;
  }
  sceneLayer.context.setTransform(1, 0, 0, 1, 0, 0);
  sceneLayer.context.globalCompositeOperation = "source-over";
  sceneLayer.context.globalAlpha = 1;
  sceneLayer.context.clearRect(0, 0, canvas.width, canvas.height);
  worldTransform(sceneLayer.context);
  context = sceneLayer.context;
}

// Фильтр дня и ночи заливает весь слой, поэтому пустые места сначала
// запоминаем и после заливки возвращаем им прозрачность: иначе заливка
// сама становится изображением и вместо тени получается светлое пятно.
export function endSceneLayer(alpha = 1) {
  sceneLayer.alphaContext.setTransform(1, 0, 0, 1, 0, 0);
  sceneLayer.alphaContext.globalCompositeOperation = "source-over";
  sceneLayer.alphaContext.clearRect(0, 0, canvas.width, canvas.height);
  sceneLayer.alphaContext.drawImage(sceneLayer.canvas, 0, 0);
  applyDaylight();
  context.setTransform(1, 0, 0, 1, 0, 0);
  context.globalCompositeOperation = "destination-in";
  context.globalAlpha = 1;
  context.drawImage(sceneLayer.alpha, 0, 0);
  context.globalCompositeOperation = "source-over";
  context = mainContext;
  context.setTransform(1, 0, 0, 1, 0, 0);
  context.globalCompositeOperation = "source-over";
  context.globalAlpha = alpha;
  context.drawImage(sceneLayer.canvas, 0, 0);
  context.globalAlpha = 1;
  worldTransform(context);
}

//: ОБРАТНЫЙ ХОД ЭКРАН -> МИР ставится СНАРУЖИ. Опыт с перспективой
//: (perspective.js) искажает кадр, и без такой же поправки на мышь щелчок
//: у края кадра промахивался бы мимо клетки. Формула живёт там же, где
//: прямой ход, — сюда её копировать нельзя, две копии молча разойдутся.
//: Импортировать perspective.js отсюда тоже нельзя: он импортирует нас, и
//: вышел бы цикл (tests/test_client_imports.py его ловит).
let unproject = null;
export function setUnproject(fn) { unproject = fn; }

//: ПОЛОВИНЫ ВИДА ТОЖЕ СТАВЯТСЯ СНАРУЖИ. С перспективой они перестают быть
//: симметричными: вверх кадр захватывает дальше, вниз ближе. Формула живёт
//: в perspective.js, импортировать его отсюда нельзя (цикл), поэтому он сам
//: кладёт сюда счётчик.
let extent = null;
export function setViewExtent(fn) { extent = fn; }

export function screenToWorld(clientX, clientY) {
  const rect = canvas.getBoundingClientRect();
  const x = clientX - rect.left;
  const y = clientY - rect.top;
  const flat = {
    x: view.cameraX + (x - view.width / 2) / view.zoom,
    y: view.cameraY + (y - view.height / 2) / view.zoom,
  };
  return unproject ? unproject(flat) : flat;
}

export function updateZoom() {
  zoomNode.textContent = `${Math.round(view.zoom * 100)}%`;
}
