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
  width: 1,
  height: 1,
  dpr: Math.max(1, window.devicePixelRatio || 1),
  cameraX: 0,
  cameraY: 0,
  zoom: 0.45,
  dragging: false,
  pointerX: 0,
  pointerY: 0,
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
export function clampCamera() {
  const bounds = world.map?.coordinates?.camera ?? null;
  if (!bounds) return false;
  const before = `${view.cameraX},${view.cameraY}`;
  const halfW = view.width / 2 / view.zoom;
  const halfH = view.height / 2 / view.zoom;
  const left = bounds.left ?? 0, right = bounds.right ?? 0;
  const top = bounds.top ?? 0x20, bottom = bounds.bottom ?? 0;
  if (view.cameraX - halfW < left) view.cameraX = left + halfW;
  else if (view.cameraX + halfW > right) view.cameraX = right - halfW;
  if (view.cameraY - halfH < top) view.cameraY = top + halfH;
  else if (view.cameraY + halfH > bottom) view.cameraY = bottom - halfH;
  return before !== `${view.cameraX},${view.cameraY}`;
}

// Кадр сейчас собирается послойно (см. render): «дневное» рисуется прямо на
// холст, а из слоя сцены вырезается силуэт, чтобы оно проступило.
export let layeredFrame = false;

export function setLayeredFrame(value) {
  layeredFrame = value;
}

export function traceDiamond(x, y) {
  const grid = world.map.coordinates.ground_grid;
  context.beginPath();
  context.moveTo(x + grid.tile_width / 2, y);
  context.lineTo(x + grid.tile_width, y + grid.tile_height / 2);
  context.lineTo(x + grid.tile_width / 2, y + grid.tile_height);
  context.lineTo(x, y + grid.tile_height / 2);
  context.closePath();
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
export function withMainContext(draw) {
  const previous = context;
  context = mainContext;
  draw();
  context = previous;
}

// Светлый кадр (интерьер постройки, юнит на клетке бита 22) ложится на кадр,
// а из слоя вырезается его силуэт: объекты переднего плана рисуются позже и
// закрашивают вырез, поэтому глубина не ломается.
export function drawBrightImage(image, x, y) {
  withMainContext(() => context.drawImage(image, x, y));
  context.save();
  context.globalCompositeOperation = "destination-out";
  context.globalAlpha = 1;
  context.drawImage(image, x, y);
  context.restore();
}

export function applyDaylight() {
  // Раскладка каналов из цикла пересчёта палитр (VA 0x441E47): таблица c8
  // применяется к младшим битам слова (синий), c9 — к средним (зелёный),
  // c10 — к старшим (красный).
  const [b, g, r] = daylight.levels;
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

export function screenToWorld(clientX, clientY) {
  const rect = canvas.getBoundingClientRect();
  const x = clientX - rect.left;
  const y = clientY - rect.top;
  return {
    x: view.cameraX + (x - view.width / 2) / view.zoom,
    y: view.cameraY + (y - view.height / 2) / view.zoom,
  };
}

export function updateZoom() {
  zoomNode.textContent = `${Math.round(view.zoom * 100)}%`;
}
