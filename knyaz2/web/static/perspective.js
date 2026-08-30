// ОПЫТ: перспектива поверх нашей изометрии, за флагом в адресной строке.
//
//     ?perspective          — 35 % (в Diablo на 800x600 выходит 32 %)
//     ?perspective=50       — свой разброс в процентах
//     ?perspective=0.2      — то же долей
//
// Без флага модуль не делает НИЧЕГО: все обёртки сразу зовут исходную
// отрисовку, и кадр собирается как собирался.
//
// ЗАКОН СНЯТ С Game.exe, разбор целиком в docs/PERSPECTIVE.md. Коротко:
// у Diablo поверх изометрии включена настоящая камера-обскура, и её
// множитель лежит таблицей обратных величин (VA 0x50DCD0). Из таблицы
// следуют два правила:
//
//     по горизонтали  масштаб растёт ЛИНЕЙНО по экранной строке
//     по вертикали    растяжение равно тому же масштабу В КВАДРАТЕ
//
// Второе — не выдумка, а свойство наклонной плоскости под перспективой, и
// оно даёт замкнутую формулу. Пусть g — строка ПЛОСКОГО кадра относительно
// опорной, k — наклон. Из dp/dg = масштаб² выходит
//
//     масштаб(g) = 1 / (1 − k·g)          строка(g) = g / (1 − k·g)
//
// Опорная строка у нас — середина кадра (там держится герой), у Diablo она
// на 32 точки выше середины; разница в полсотни точек роли не играет.
//
// НАКЛОН ЗАДАН РАЗБРОСОМ ПО КАДРУ, а не числом из exe. У Diablo наклон
// 0.000612 на точку при кадре 600 строк; наш холст бывает и втрое выше, и
// тот же наклон дал бы втрое больше перспективы. Поэтому храним разброс
// «низ к верху» и пересчитываем наклон под текущую высоту:
//
//     k = 2·разброс / ((2 + разброс) · высота_кадра)
//
// КАМЕРА ОТДАЁТ МАТРИЦУ НА СТРОКУ ЯКОРЯ, А НЕ ОДНУ НА КАДР.
//
// Холст 2D перспективу выразить не умеет: `setTransform` только аффинное.
// Зато вся сцена и так рисуется в мировых координатах через одну матрицу
// камеры — значит достаточно давать КАЖДОМУ содержимому свою, посчитанную
// по его собственной точке на земле. Это и есть `cameraApply`, а
// `withPerspective` — она же с save/restore.
//
// Правило деления простое и физическое:
//
//     ПЛОСКОСТЬ (земля, вода, пятна света)  -> `drawPlane`, полосами:
//         горизонталь на масштаб, вертикаль сама выходит квадратом
//     ВСЁ СТОЯЩЕЕ (юниты, постройки, кучи, снаряды, листва, птицы)
//         -> `withPerspective` по своей точке на земле, масштаб РАВНОМЕРНЫЙ
//
// Якорь берётся НА ВСЮ СУЩНОСТЬ, а не на отдельный блит. Постройка — это
// пол, стены и крыша тремя кадрами с разным нижним краем; дай каждому свой
// якорь, и дом развалится. По той же причине птица едет за своей тенью, а
// полупрозрачная копия юнита — за самим юнитом.
//
// Мышь поправлена: `perspectiveUnproject` висит крючком в `screenToWorld`,
// и щелчок попадает туда, куда показывает картинка. Поиск пути и вся игра
// считают в ПЛОСКИХ мировых координатах, как считали, — перспектива живёт
// только в отрисовке.
//
// ЧТО ОСТАЁТСЯ ЗА БОРТОМ:
//
//   * интерфейс, полоса выбора и склейка слоёв — они экранные, и так и надо;
//   * тень едет якорем хозяина, то есть масштабируется как спрайт, а не
//     стелется по плоскости: у ног держится, но у дальнего края форма чуть
//     иная, чем была бы у настоящей;
//   * постройка едет ОДНИМ масштабом, хотя её след тянется на две-три сотни
//     строк, а масштаб на них разный. Дом у нас нарисован тремя кадрами
//     (пол, стены, крыша), но это НЕ три куска геометрии: кадры соосны —
//     общий верх и почти общая рамка (518x427 против 518x472), то есть одна
//     и та же изба, нарисованная трижды. Стоят они на ОДНОМ следе, значит и
//     якорь у них общий; раздай им разные — разъедутся слои, а промах по
//     следу останется. Замер по девяти домам Борья: в среднем 6.1 точки,
//     худший 13.3, и приходится он на дальний угол, закрытый самим домом.
//     Diablo этого не знает: там дом набран мелкой плиткой ПО ГЛУБИНЕ, и
//     каждая едет своей строкой;
//   * снаряд якорится собой, а не точкой под собой: высоту полёта в записи
//     выстрела не хранят. Ошибка меньше двух процентов масштаба.
//
// Всё это чинится только переносом закона в само преобразование камеры —
// но сперва надо посмотреть, стоит ли овчинка выделки.
import { settings, settingsLoad } from "./settings.js";
import { mainContext, setUnproject, setViewExtent,
         view } from "./viewport.js";

//: Разброс по умолчанию: 35 % показались правильными на глаз (у Diablo на
//: 800x600 выходит 32 %).
const SPREAD = 0.35;

// ОТКУДА БЕРЁТСЯ ВКЛЮЧЕНО ИЛИ НЕТ.
//
//   нет параметра в адресе -> галочка из настроек (по умолчанию включена)
//   есть параметр          -> он и решает, настройку перебивает
//
// Адресная строка оставлена для проверок: `?perspective=50` посмотреть
// сильнее, `?perspective=0` выключить, не трогая настройку игрока.
function readFlag() {
  //: ЧИТАЕМ ХРАНИЛИЩЕ САМИ. `settingsLoad()` зовёт app.js, но уже в ходе
  //: запуска, а этот модуль решает «включено или нет» при загрузке — то
  //: есть раньше. Повторный вызов безвреден: он только перекладывает
  //: сохранённое в общий объект.
  try { settingsLoad(); } catch { /* хранилища нет — значения по умолчанию */ }
  let raw = null;
  try {
    raw = new URLSearchParams(window.location.search).get("perspective");
  } catch { return { on: settings.perspective !== false, spread: SPREAD }; }
  if (raw === null) {
    return { on: settings.perspective !== false, spread: SPREAD };
  }
  const text = raw.trim().toLowerCase();
  if (text === "" || text === "1" || text === "on" || text === "true") {
    return { on: true, spread: SPREAD };
  }
  if (text === "0" || text === "off" || text === "false") {
    return { on: false, spread: 0 };
  }
  const value = Number(text);
  if (!Number.isFinite(value) || value <= 0) return { on: false, spread: 0 };
  //: больше единицы читаем как проценты, меньше — как долю
  return { on: true, spread: value > 1 ? value / 100 : value };
}

//: Отдельный тумблер для построек: `&mesh=0` выключает сетку и возвращает
//: дом к одному множителю. По умолчанию включена — ради неё всё и затевалось.
//: Можно щёлкать на ходу из консоли: knyaz2.perspective.mesh = false.
function readMesh() {
  try {
    const raw = new URLSearchParams(window.location.search).get('mesh');
    if (raw === null) return true;
    return !['0', 'off', 'false', 'no'].includes(raw.trim().toLowerCase());
  } catch { return true; }
}

export const perspective = readFlag();

//: Задана ли перспектива АДРЕСОМ. Тогда галочка в настройках её не двигает:
//: параметр ставят для проверки, и он должен держаться, пока страницу не
//: перезагрузят.
export function perspectiveForced() {
  try {
    return new URLSearchParams(window.location.search).get("perspective") !== null;
  } catch { return false; }
}
perspective.mesh = readMesh();
//: `&mesh=all` — сетка всем трём кадрам, как было в первом заходе.
try {
  perspective.meshAll =
    (new URLSearchParams(window.location.search).get('mesh') || '')
      .trim().toLowerCase() === 'all';
} catch { perspective.meshAll = false; }

//: Высота видимого кадра В МИРОВЫХ точках: холст делится на увеличение.
function frameHeight() {
  return Math.max(1, view.height / Math.max(view.zoom, 0.0001));
}

//: ВЫРОЖДЕННЫЙ КАДР — ПЕРСПЕКТИВЫ НЕТ.
//:
//: Наклон обратно пропорционален высоте кадра, поэтому у крошечного холста
//: он улетает в небо: при `view.height == 1` выходит 0.3 на точку, и всё,
//: что дальше трёх точек от камеры, схлопывается в ноль. Поймано замером:
//: свежая вкладка успевает отрисовать кадр ДО того, как `resize()` даст
//: холсту настоящий размер, — там `canvas` был 1x1 при клиентских 1140x720.
//:
//: Ниже этого порога честнее не корёжить вовсе: перспектива на кадре в
//: полсотни точек всё равно ничего не значит.
const MIN_FRAME = 64;

function slope() {
  const height = frameHeight();
  if (height < MIN_FRAME) return 0;
  const spread = perspective.spread;
  return 2 * spread / ((2 + spread) * height);
}

//: Куда уходит плоская строка и во сколько раз там всё крупнее.
//: Знаменатель зажат: на горизонте (g = 1/k) он обращается в ноль, а
//: горизонт лежит втрое дальше края кадра — но зум умеет всякое.
export function perspectiveAt(worldY) {
  const g = worldY - view.cameraY;
  const denominator = Math.max(0.2, 1 - slope() * g);
  const scale = 1 / denominator;
  return { scale, row: view.cameraY + g * scale };
}

//: Обратный ход: какая ПЛОСКАЯ строка попадёт в эту перспективную.
function flatRowOf(worldY) {
  const u = worldY - view.cameraY;
  return view.cameraY + u / Math.max(0.2, 1 + slope() * u);
}

// Спрайт, стоящий на земле: движок Diablo кладёт его якорь через то же
// преобразование, а сам спрайт масштабирует РАВНОМЕРНО — не растягивает.
// Поэтому здесь масштаб один на обе оси, а в квадрате идёт только земля.
//
// ПРЕОБРАЗОВАНИЕ СТАВИТСЯ НА ОБА ХОЛСТА, И ЭТО НЕ ПЕРЕСТРАХОВКА.
//
// У нас светлые кадры идут МИМО слоя сцены, прямо на кадр: интерьер
// постройки (`drawBrightImage`), светлый юнит (`withMainContext` в
// renderUnit), куча на полу. Рисуется такой кадр на `mainContext`, а окно
// под него вырезается из слоя — двумя вызовами с ОДНИМИ координатами.
//
// Пока преобразование лежало на одном лишь слое, эти двое расходились:
// пол и интерьер оставались на плоском месте, а стены и крыша уезжали по
// перспективе. Снаружи это выглядело как «коробки домов уползают».
export function cameraApply(target, anchorX, anchorY) {
  const { scale, row } = perspectiveAt(anchorY);
  target.translate(view.cameraX + (anchorX - view.cameraX) * scale, row);
  target.scale(scale, scale);
  target.translate(-anchorX, -anchorY);
}

export function withPerspective(target, anchorX, anchorY, draw) {
  if (!perspective.on) return draw();
  const targets = target === mainContext ? [target] : [target, mainContext];
  for (const where of targets) {
    where.save();
    cameraApply(where, anchorX, anchorY);
  }
  const result = draw();
  for (const where of targets) where.restore();
  return result;
}

// ОБРАТНЫЙ ХОД: куда на самом деле ткнули. Прямой ход кладёт плоскую точку
// в `camera + (точка − camera)·масштаб`, поэтому обратный делит на тот же
// масштаб — а строку возвращает `flatRowOf`, который для того и написан.
//
// Без этого мышь и картинка расходятся тем сильнее, чем дальше от середины
// кадра: у нижнего края промах доходит до трети клетки.
export function perspectiveUnproject(point) {
  const u = point.y - view.cameraY;
  const scale = Math.max(0.2, 1 + slope() * u);
  return {
    x: view.cameraX + (point.x - view.cameraX) / scale,
    y: flatRowOf(point.y),
  };
}

// СКОЛЬКО МИРА ВЛЕЗАЕТ В КАДР — считаем честно, а не по половине высоты.
//
// Плоская картина: сверху и снизу видно поровну, `высота/2`. С перспективой
// нет. Строка кадра `y` показывает плоскую строку `flatRowOf(y)`, а она
// сжата к середине снизу и растянута сверху:
//
//     вверх  = полвысоты / (1 − k·полвысоты)     видно ДАЛЬШЕ
//     вниз   = полвысоты / (1 + k·полвысоты)     видно БЛИЖЕ
//
// По горизонтали шире всего у ВЕРХНЕГО края, где множитель меньше единицы:
// там в те же точки экрана влезает `полширины / масштаб_верха` мира. Берём
// эту, наибольшую — обрезка обязана держать камеру так, чтобы за край карты
// не заглянуть НИГДЕ в кадре.
export function viewExtent(halfW, halfH) {
  const k = slope();
  if (!k) return { up: halfH, down: halfH, side: halfW };
  const up = halfH / Math.max(0.2, 1 - k * halfH);
  const down = halfH / Math.max(0.2, 1 + k * halfH);
  const topScale = Math.max(0.2, 1 - k * halfH);
  return { up, down, side: halfW / topScale };
}

//: Крючки ставятся ТОЛЬКО под флагом: без него viewport считает по-плоскому,
//: как считал.
if (perspective.on) {
  setUnproject(perspectiveUnproject);
  setViewExtent(viewExtent);
}

//: Высота полосы в мировых точках. Внутри полосы масштаб считается
//: постоянным, и ошибка не превышает k·высота — при четырёх точках это
//: доли процента. Меньше делать незачем, больше — видно ступеньку.
const BAND = 4;

// Кусок ЗЕМЛИ: плоскость, а не спрайт. Идём по строкам НАЗНАЧЕНИЯ и для
// каждой полосы тянем свою строку источника — так вертикаль сама собой
// выходит квадратом, без отдельной формулы.
export function drawPlane(target, image, worldLeft, worldTop, worldW, worldH) {
  drawPlanePart(target, image, 0, 0, image.width, image.height,
                worldLeft, worldTop, worldW, worldH);
}

// То же, но КУСКОМ ЛИСТА: тень юнита лежит прямоугольником на общем листе
// кадров, отдельной картинки у неё нет.
export function drawPlanePart(target, image, srcX, srcY, srcW, srcH,
                              worldLeft, worldTop, worldW, worldH) {
  if (!perspective.on) {
    target.drawImage(image, srcX, srcY, srcW, srcH,
                     worldLeft, worldTop, worldW, worldH);
    return;
  }
  const pixelsY = srcH / worldH;
  const half = frameHeight() / 2;
  //: Полосы гоняем только по СВОИМ строкам, а не по всему кадру: земля
  //: покрывает его целиком, а плитка воды или пятно света — сотню строк, и
  //: холостые витки на каждую плитку складывались бы в тысячи.
  const from = Math.max(view.cameraY - half - BAND,
                        perspectiveAt(worldTop).row - BAND);
  const to = Math.min(view.cameraY + half + BAND,
                      perspectiveAt(worldTop + worldH).row + BAND);
  const centre = view.cameraX;
  for (let y = from; y < to; y += BAND) {
    const topFlat = flatRowOf(y);
    const bottomFlat = flatRowOf(y + BAND);
    if (bottomFlat <= worldTop || topFlat >= worldTop + worldH) continue;
    const sourceY = srcY + (topFlat - worldTop) * pixelsY;
    const sourceH = (bottomFlat - topFlat) * pixelsY;
    if (sourceH <= 0) continue;
    const scale = perspectiveAt((topFlat + bottomFlat) / 2).scale;
    const left = centre + (worldLeft - centre) * scale;
    target.drawImage(image, srcX, sourceY, srcW, sourceH,
                     left, y, worldW * scale, BAND);
  }
}


// ---------------------------------------------------------------- сетка
// ПОСТРОЙКА СТРОИТ СЕТКУ СЕБЕ САМА.
//
// У Diablo есть глобальная сетка плиток, и каждая плитка дома знает свою
// клетку на земле — оттого ближний угол крыши крупнее дальнего на те самые
// пятнадцать процентов. У нас сетки нет: дом лежит в любой точке и приезжает
// одной картинкой. Но след дома мы знаем (`cells.footprint`), а значит можем
// построить сетку ЛОКАЛЬНО, из самого дома.
//
// КЛЮЧЕВОЕ: у дома глубина меняется по СТОЛБЦУ, а не по строке. Землю мы
// режем строками, потому что у плоскости строка и есть глубина. С домом так
// нельзя — одна строка содержит и верх дальней стены, и низ ближней. Зато у
// каждого экранного столбца есть своя точка на земле: там, где стена этого
// столбца упирается в грунт. Это нижняя граница следа, и форма у неё Λ —
// ниже всего в ближнем углу, выше к боковым.
//
// Поэтому режем ВЕРТИКАЛЬНЫМИ полосами, и каждой даём множитель по её
// собственному основанию.
//
// ЩЕЛЕЙ НЕТ ПО ПОСТРОЕНИЮ: края полос берутся из общего непрерывного
// отображения X(x), и правый край полосы i — это в точности левый край
// полосы i+1. Наивное «отмасштабировать каждую полосу отдельно» дало бы
// гребёнку, которую видно на моей картинке сравнения плиток.
const STRIPS = 12;

export function drawMesh(target, image, x, y, w, h, baseAt, anchorX, anchorY) {
  //: снаружи уже стоит преобразование по якорю дома (scene.js), поэтому
  //: рисуем в его ПРООБРАЗЕ: считаем, куда хотим попасть на экране, и
  //: возвращаем это обратно через обратный ход якоря.
  const outer = perspectiveAt(anchorY);
  const back = (bigX, bigY) => ({
    x: view.cameraX + (bigX - view.cameraX) / outer.scale,
    y: anchorY + (bigY - outer.row) / outer.scale,
  });
  //: ГОРИЗОНТАЛЬ СЧИТАЕМ ОТ ЯКОРЯ ДОМА, А НЕ ОТ ОСИ КАМЕРЫ.
  //:
  //: Считал от оси — и постройки у края кадра срезало наискось. Разбор: у
  //: столбцов разный множитель, поэтому в смещении появляется добавка
  //: `(x − осьX)·Δмножителя`, и она растёт вместе с расстоянием до оси. У
  //: дома в полутора тысячах точек от камеры это сотни точек перекоса.
  //:
  //: Формально это схождение к точке схода, и в настоящей проекции оно есть.
  //: Но НАША ЗЕМЛЯ его не имеет: она масштабируется построчно, горизонтали
  //: остаются параллельными, точки схода по горизонтали нет вовсе. Дом
  //: сходился, земля нет — дом и отрывался от земли.
  //:
  //: От своего якоря добавка ограничена полушириной постройки: десяток
  //: точек вместо сотен, и это ровно тот местный эффект, ради которого всё
  //: затевалось. Куда встать дому целиком, по-прежнему решает внешнее
  //: преобразование по якорю.
  const anchorBigX = view.cameraX + (anchorX - view.cameraX) * outer.scale;
  const edge = (worldX) => {
    const base = baseAt(worldX);
    const at = perspectiveAt(base);
    return { at, base, X: anchorBigX + (worldX - anchorX) * at.scale };
  };
  const pixels = image.width / w;
  let left = edge(x);
  for (let i = 0; i < STRIPS; i += 1) {
    const x0 = x + w * i / STRIPS;
    const x1 = x + w * (i + 1) / STRIPS;
    const right = edge(x1);
    const middle = edge((x0 + x1) / 2);
    const scale = middle.at.scale;
    //: верх полосы: основание уезжает в свою строку, а всё над ним
    //: поднимается на тот же множитель
    const topBig = middle.at.row + (y - middle.base) * scale;
    const a = back(left.X, topBig);
    const b = back(right.X, topBig + h * scale);
    const sx = (x0 - x) * pixels;
    const sw = (x1 - x0) * pixels;
    if (sw > 0 && b.x - a.x !== 0) {
      target.drawImage(image, sx, 0, sw, image.height,
                       a.x, a.y, b.x - a.x, b.y - a.y);
    }
    left = right;
  }
}

//: Насколько шире надо испечь землю. Наверху кадра источник лежит ДАЛЬШЕ
//: назначения (плоская строка −529 попадает в перспективную −400), и без
//: запаса у верхнего края открылась бы дыра.
export function planeMargin() {
  if (!perspective.on) return 0;
  const half = frameHeight() / 2;
  return Math.ceil(Math.abs(flatRowOf(view.cameraY - half) -
                            (view.cameraY - half))) + BAND;
}
