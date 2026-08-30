// Земля кадра: испечённый кусок вместо тысяч плиток каждый кадр.
//
// ЗАЧЕМ. Земля статична: плитки и накладки местности не меняются, пока карта
// та же. Рисовались они поклеточно каждый кадр, и отсечение по видимости
// спасало только вблизи — при отдалении в кадр попадает вся карта разом:
// у Тиграта это 7 807 плиток и 378 накладок, у Кирингхольма 6 603 и 931.
// Столько блитов в кадре не тянет никакой браузер, и игра вставала.
//
// КАК. Кэш размером С ЭКРАН, а не с карту: сколько ни отдаляй, пикселей на
// экране столько же, поэтому холст всегда мал. Он покрывает видимую коробку
// с запасом и перепекается только когда камера уходит за этот запас или
// меняется масштаб — то есть раз в несколько секунд ходьбы вместо
// шестидесяти раз в секунду.
//
// ЧЕГО ЗДЕСЬ НЕТ. Подложка (вода) не печётся: она живая, кадр её меняется
// каждый такт. Порядок сохраняется — подложка рисуется до земли, а земля
// ложится поверх со своей прозрачностью, как и раньше: базовая мозаика
// нарочно неполная, и вода видна в её прорехах.
import { world } from "./world.js";
import { drawPlane, perspective, planeMargin } from "./perspective.js";
import { context, traceDiamond, view } from "./viewport.js";

//: Запас вокруг видимой коробки, в пикселях ЭКРАНА. Чем он больше, тем реже
//: перепечка и тем больше холст; половина экрана — та середина, при которой
//: обычная ходьба почти не задевает край.
const MARGIN = 256;

//: Габариты плитки земли для отсечения — те же числа, что стояли в проходе
//: сцены до кэша (плитка 114x64, с запасом на округление).
const TILE_W = 120, TILE_H = 70;

const cache = {
  canvas: document.createElement("canvas"),
  context: null,
  //: Чем испечено: при расхождении с текущим кадром печём заново.
  map: null, zoom: 0, dpr: 0,
  //: Мировая коробка, которую покрывает холст.
  left: 0, top: 0, right: 0, bottom: 0,
  //: Сколько картинок не доехало на момент выпечки. Пока не ноль, печём
  //: заново: иначе дырка от недогруженной плитки осталась бы навсегда.
  missing: 0,
  //: Диагностика: её читает selfcheck и живой замер.
  baked: 0, tiles: 0, overlays: 0,
};
cache.context = cache.canvas.getContext("2d");

//: Чем опознаётся карта. Номер карты лежит в её описании; на всякий случай
//: берём и длину списка земли — если карту подменили той же длины, но
//: другой, различие всплывёт по номеру.
function mapKey() {
  return `${world.map?.id ?? world.map?.name ?? "?"}:${(world.ground ?? []).length}`;
}

function stale(visible) {
  return cache.map !== mapKey() || cache.zoom !== view.zoom
    || cache.dpr !== view.dpr || cache.missing > 0
    || visible.left < cache.left || visible.right > cache.right
    || visible.top < cache.top || visible.bottom > cache.bottom;
}

//: Испечь кусок земли вокруг видимой коробки.
function bake(visible) {
  const scale = view.dpr * view.zoom;
  const margin = MARGIN / view.zoom;           // запас в мировых единицах
  cache.left = visible.left - margin;
  cache.top = visible.top - margin;
  cache.right = visible.right + margin;
  cache.bottom = visible.bottom + margin;
  const width = Math.ceil((cache.right - cache.left) * scale);
  const height = Math.ceil((cache.bottom - cache.top) * scale);
  if (cache.canvas.width !== width || cache.canvas.height !== height) {
    cache.canvas.width = width;
    cache.canvas.height = height;
  }
  const target = cache.context;
  target.setTransform(1, 0, 0, 1, 0, 0);
  target.clearRect(0, 0, width, height);
  //: Мир кладётся так, чтобы левый верхний угол коробки пришёлся в ноль
  //: холста. Масштаб тот же, что у кадра, — значит выпечка ляжет обратно
  //: пиксель в пиксель.
  target.setTransform(scale, 0, 0, scale,
                      -cache.left * scale, -cache.top * scale);
  target.imageSmoothingEnabled = false;

  let missing = 0, tiles = 0, overlays = 0;
  for (const cell of world.ground) {
    if (!cell.asset || cell.x > cache.right || cell.y > cache.bottom ||
        cell.x + TILE_W < cache.left || cell.y + TILE_H < cache.top) continue;
    const image = world.images.get(cell.asset);
    if (image) {
      target.drawImage(image, cell.x, cell.y);
      tiles += 1;
    } else {
      //: Картинки ещё нет: рисуем метку, как и раньше, и просим перепечь.
      missing += 1;
      traceDiamond(cell.x, cell.y, target);
      target.fillStyle = "#d3009e";
      target.fill();
    }
  }
  // konung2.exe VA 0x42543D..0x4254A5: первая 12-байтовая таблица KN2
  // рисуется в порядке слотов сразу после земли — берега, кувшинки,
  // камыши и прочее, чем прикрыта нарочно неполная базовая мозаика.
  for (const overlay of world.terrainOverlays) {
    const frame = overlay.frame;
    if (!frame) continue;
    const x = overlay.position.x;
    const y = overlay.position.y;
    if (x > cache.right || y > cache.bottom ||
        x + frame.width < cache.left || y + frame.height < cache.top) continue;
    const image = world.images.get(frame.asset);
    if (image) {
      target.drawImage(image, x, y);
      overlays += 1;
    } else {
      missing += 1;
      target.fillStyle = "rgba(211, 0, 158, .65)";
      target.fillRect(x, y, frame.width, frame.height);
    }
  }
  cache.map = mapKey();
  cache.zoom = view.zoom;
  cache.dpr = view.dpr;
  cache.missing = missing;
  cache.baked += 1;
  cache.tiles = tiles;
  cache.overlays = overlays;
}

//: Редактор подвинул оверлей или тайл: слой земли испечён заново при
//: следующем кадре. Дешевле, чем тащить сюда знание о правках.
export function groundInvalidate() {
  cache.map = null;
}

//: Положить землю в кадр. Возвращает, пришлось ли печь заново.
export function renderGround(visible) {
  if (!world.ground || !world.images) return false;
  //: ОПЫТ С ПЕРСПЕКТИВОЙ ТЯНЕТ ВЕРХНИЕ СТРОКИ ИЗДАЛЕКА. Верх кадра он берёт
  //: не со своей строки, а с той, что ДАЛЬШЕ от опорной (плоская −529 в
  //: перспективную −400), и без добавки к выпечке у верхнего края открылась
  //: бы полоса пустоты. Сколько добавить, считает сам модуль.
  const grown = perspective.on
    ? { ...visible, top: visible.top - planeMargin(),
        bottom: visible.bottom + planeMargin() }
    : visible;
  const rebaked = stale(grown);
  if (rebaked) bake(grown);
  //: Кладём МИРОВЫМ преобразованием, а не по экранным координатам: масштаб
  //: у выпечки тот же, поэтому это блит один в один, и земля садится ровно
  //: туда же, куда садились сами плитки. По экранным пришлось бы округлять,
  //: и земля дрожала бы на пиксель относительно всего остального.
  //:
  //: С флагом перспективы тот же кусок кладётся полосами, каждая со своим
  //: масштабом; без флага `drawPlane` делает ровно прежний один блит.
  drawPlane(context, cache.canvas, cache.left, cache.top,
            cache.right - cache.left, cache.bottom - cache.top);
  return rebaked;
}
