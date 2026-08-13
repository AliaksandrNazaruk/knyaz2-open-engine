// Сборка кадра целиком — порядок мастера VA 0x4288D4.
import { canvas } from "./dom.js";
import { world } from "./world.js";
import { applyDaylight, band, beginSceneLayer, cellVisible, context, endSceneLayer,
         setLayeredFrame, traceDiamond, useMainContext, visibleWorld,
         worldTransform } from "./viewport.js";
import { daylight } from "./daylight.js";
import { lightActive, nightDarkness, renderLightGlow } from "./light.js";
import { renderShadows } from "./shadows.js";
import { drawObject } from "./entities.js";
import { drawHeroAtDepth, hero, renderHero } from "./hero.js";
import { drawPile, lootDrawList } from "./loot.js";
import { UNIT_SORT_BIAS } from "./actor.js";
import { renderProjectiles } from "./projectiles.js";
import { renderUnit, renderUnitsOverlay, units } from "./units.js";
import { renderAmbient } from "./ambient.js";
import { renderGroundDebug, renderObjectDebug } from "./debug.js";
import { water, waterRender } from "./water.js";

// Рамка выбора поверх сцены. Оформление наше: в движке она рисуется
// средствами DirectDraw, здесь — обычной пунктирной обводкой.
function drawSelectionBand() {
  if (!band.active) return;
  const left = Math.min(band.fromX, band.toX);
  const top = Math.min(band.fromY, band.toY);
  const width = Math.abs(band.toX - band.fromX);
  const height = Math.abs(band.toY - band.fromY);
  if (width < 2 && height < 2) return;
  context.save();
  context.strokeStyle = "rgba(0, 255, 0, 0.9)";
  context.lineWidth = 1;
  context.setLineDash([4, 3]);
  context.strokeRect(left, top, width, height);
  context.restore();
}

export function render() {
  useMainContext();
  context.setTransform(1, 0, 0, 1, 0, 0);
  context.globalCompositeOperation = "source-over";
  context.globalAlpha = 1;
  context.fillStyle = "#14130f";
  context.fillRect(0, 0, canvas.width, canvas.height);
  if (!world.map) return;

  worldTransform(context);
  const visible = visibleWorld();

  // Порядок кадра — как в мастере VA 0x4288D4: земля со светом (0x424FD8),
  // затем сцена (0x4267B8), которая начинается с затемнения фона под
  // тенями (0x440788), затем отложенные юниты поверх всего (0x428900).
  // В браузере фильтр суток — заливка целого слоя, а движок часть кадров
  // блитит ИСХОДНОЙ палитрой (интерьеры построек, юнит на клетке с битом 22)
  // и вдобавок кладёт локальный свет мимо палитр. Всё это должно остаться
  // вне заливки, поэтому кадр собирается послойно:
  //   [земля и оверлеи + фильтр] -> аура -> тени ->
  //   [объекты и герой + фильтр, светлые кадры на холст] -> призрак игрока
  const filtered = daylight.levels.some((level) => level !== 0);
  const layered = filtered &&
    (lightActive() || world.brightObjects || Boolean(hero.data && hero.bright));
  setLayeredFrame(layered);
  if (layered) beginSceneLayer();

  // konung2.exe VA 0x428505..0x4288D4: maps with a non-zero dword at
  // .KN2+0x3D180 draw a masked 256x256 animated underlay before ground.
  // With animation data the frame is warped live; otherwise the pack's
  // exact first rendered phase is used.
  const underlayImage = water.enabled
    ? water.canvas
    : (world.underlayVisual ? world.images.get(world.underlayVisual.path) : null);
  if (underlayImage) {
    for (const cell of world.underlay) {
      if (cell.x > visible.right || cell.y > visible.bottom ||
          cell.x + cell.size < visible.left || cell.y + cell.size < visible.top) continue;
      context.drawImage(underlayImage, cell.x, cell.y);
    }
  }

  for (const cell of world.ground) {
    if (!cell.asset || cell.x > visible.right || cell.y > visible.bottom ||
        cell.x + 120 < visible.left || cell.y + 70 < visible.top) continue;
    const image = world.images.get(cell.asset);
    if (image) {
      context.drawImage(image, cell.x, cell.y);
    } else if (cell.asset) {
      traceDiamond(cell.x, cell.y);
      context.fillStyle = "#d3009e";
      context.fill();
    }
  }

  // konung2.exe VA 0x42543D..0x4254A5: the first 12-byte KN2 table is
  // rendered in record-slot order immediately after the ground. These
  // GRAPH.RES frames are river banks, lilies, reeds and other terrain
  // overlays which cover the deliberately incomplete base-cell mosaic.
  for (const overlay of world.terrainOverlays) {
    const frame = overlay.frame;
    if (!frame) continue;
    const x = overlay.position.x;
    const y = overlay.position.y;
    if (x > visible.right || y > visible.bottom ||
        x + frame.width < visible.left || y + frame.height < visible.top) continue;
    const image = world.images.get(frame.asset);
    if (image) {
      context.drawImage(image, x, y);
    } else {
      context.fillStyle = "rgba(211, 0, 158, .65)";
      context.fillRect(x, y, frame.width, frame.height);
    }
  }

  // Земля собрана: закрываем слой и кладём на готовый кадр ауру — она
  // прибавляется к уже затемнённой земле, как ветка света внутри самого
  // прохода земли. Тени идут следом: проход VA 0x440788 делит яркость
  // всего нарисованного, включая освещённые клетки. Дальше — новый слой
  // под объекты; светлые кадры внутри него уходят прямо на холст.
  renderProjectiles();

  if (layered) {
    endSceneLayer();
    renderLightGlow(visible);
    renderShadows(visible);
    beginSceneLayer();
  } else {
    renderShadows(visible);
  }

  // Объекты и герой в общем порядке по глубине. Ключ юнита в движке —
  // нижняя строка холста 256x150, то есть ноги + 6 (VA 0x426D45); ключ
  // здания уже понижен на sort_bias при сборке пака. Непрозрачная копия
  // героя: обычная вставка, либо проход здания при бите 21. При бите 15
  // поверх всей сцены добавляется полупрозрачная копия (список 0x866F5C).
  const heroMode = !hero.data ? "none"
    : hero.insideSlot != null ? "building" : "painter";
  const heroSortY = Math.round(hero.y) + UNIT_SORT_BIAS;
  let heroDrawn = heroMode !== "painter";
  let heroInBuildingDrawn = false;
  // Ключ глубины юнита — тот же, что у героя: ноги + 6 (VA 0x426D45).
  // Юнита, стоящего в постройке, рисует сама постройка сразу после пола
  // (VA 0x425AA8) — из общего прохода по глубине он исключается, иначе
  // пол лёг бы поверх него.
  // ЧУЖИЕ ИГРОКИ — В ТОТ ЖЕ ПРОХОД. Их заводит опыт с соприсутствием
  // (presence.js), и только он: в обычной игре `world.ghosts` пуст, и эта
  // раскладка ничего не стоит. В список `units` призраки не попадают
  // намеренно — туда смотрят бой, приказы и память карты.
  const pending = [...units.filter((unit) => unit.insideSlot == null),
                   ...(world.ghosts ?? [])]
    .map((unit) => ({ unit, sortY: Math.round(unit.y) + UNIT_SORT_BIAS }))
    .sort((a, b) => a.sortY - b.sortY);
  let nextUnit = 0;
  // КУЧИ — В ТОТ ЖЕ ПРОХОД. Ключ глубины у кучи на клетках постройки берётся
  // от самой постройки: в движке её рисует отрисовщик объекта сразу после
  // пола (VA 0x00424514), см. lootDrawList.
  // Хозяин кучи ищется ПО ПЕРЕКРЫТИЮ, а не по номеру места: у объектов
  // сцены своего номера нет, и связать их с `buildingCells` не через что.
  // Берём наибольший ключ среди объектов, чья рамка накрывает точку кучи, —
  // тогда куча ложится сразу за самым «поздним» из них, как её рисует сама
  // постройка в движке (VA 0x00424514).
  const coverSortY = (x, y) => {
    let key = null;
    for (const object of world.objects ?? []) {
      const b = object.bounds;
      if (!b) continue;
      if (x < b.draw_x || x > b.draw_x + b.width) continue;
      if (y < b.draw_y || y > b.draw_y + b.height) continue;
      if (key == null || b.sort_y > key) key = b.sort_y;
    }
    return key;
  };
  const piles = lootDrawList(visible, null, coverSortY);
  let nextPile = 0;
  const drawUnitsBefore = (sortY) => {
    while (nextPile < piles.length && piles[nextPile].sortY <= sortY) {
      drawPile(piles[nextPile].pile);
      nextPile += 1;
    }
    while (nextUnit < pending.length && pending[nextUnit].sortY <= sortY) {
      renderUnit(pending[nextUnit].unit);
      nextUnit += 1;
    }
  };
  for (const object of world.objects) {
    if (!object.frames?.main) continue;
    drawUnitsBefore(object.bounds.sort_y);
    if (object.bounds.sort_y > heroSortY && !heroDrawn) {
      drawHeroAtDepth();
      heroDrawn = true;
    }
    const { draw_x: x, draw_y: y, width, height } = object.bounds;
    if (x > visible.right || y > visible.bottom ||
        x + width < visible.left || y + height < visible.top) continue;
    if (drawObject(object)) heroInBuildingDrawn = true;
  }
  drawUnitsBefore(Infinity);
  if (heroMode === "painter" && !heroDrawn) drawHeroAtDepth();
  if (heroMode === "building" && !heroInBuildingDrawn) drawHeroAtDepth();
  renderAmbient(visible);
  drawSelectionBand();

  if (layered) {
    endSceneLayer();
  } else {
    applyDaylight();
  }

  // Отложенный список 0x866F5C: движок рисует эти копии юнитов ПОСЛЕ всей
  // сцены (VA 0x428900), безусловно — в оригинале шахматным полупрозрачным
  // растром, у нас альфой 0.5. Именно эта копия и показывает персонажа
  // сквозь стену дома, в который он вошёл, поэтому она нужна всегда, а не
  // только когда клетка не светлая. Полупрозрачную копию нельзя рисовать
  // внутрь слоя сцены: заливка фильтра поверх альфы < 1 сама становится
  // изображением и копия светлеет — поэтому у неё отдельный слой.
  if (hero.data && hero.overlay) {
    if (layered && hero.bright) {
      renderHero(0.5, false);
    } else {
      beginSceneLayer();
      renderHero(1, false);
      endSceneLayer(0.5);
    }
  }
  // Спутники и жители, зашедшие в постройку, идут тем же отложенным
  // списком: без этой копии стена закрывает их целиком.
  if (hero.data) {
    // Копия юнита на клетке с битом 22 — как копия героя выше: статичная
    // палитра (VA 0x425E81), прямо на кадр мимо заливки фильтра. Иначе
    // спутник в доме темнел ночью в своей просвечивающей копии.
    if (layered) renderUnitsOverlay(0.5, true);
    beginSceneLayer();
    const shown = renderUnitsOverlay(1, layered ? false : null);
    endSceneLayer(shown ? 0.5 : 0);
  }

  renderGroundDebug(visible);
  renderObjectDebug(visible);
}
