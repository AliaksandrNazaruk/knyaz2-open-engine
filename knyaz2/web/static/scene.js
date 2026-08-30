// Сборка кадра целиком — порядок мастера VA 0x4288D4.
import { canvas } from "./dom.js";
import { world } from "./world.js";
import { applyDaylight, band, beginSceneLayer, cellVisible, context, endSceneLayer,
         overcast,
         setLayeredFrame, useMainContext, visibleWorld,
         worldTransform } from "./viewport.js";
import { clock } from "./clock.js";
import { daylight } from "./daylight.js";
import { lightActive, nightDarkness, renderLightGlow } from "./light.js";
import { renderShadows } from "./shadows.js";
import { buildingAnchor, drawObject, entitiesBeginPass, entitiesEndPass,
         partyRoofBuildings } from "./entities.js";
import { drawHeroAtDepth, hero, renderHero } from "./hero.js";
import { drawPile, lootDrawList } from "./loot.js";
import { unitSortKey } from "./actor.js";
import { renderBursts, renderFire, renderProjectiles } from "./projectiles.js";
import { renderUnit, renderUnitsOverlay, units } from "./units.js";
import { renderAmbient } from "./ambient.js";
import { renderGroundDebug, renderObjectDebug } from "./debug.js";
import { water, waterRender } from "./water.js";
import { renderGround } from "./ground.js";
import { renderRain, renderStreaks, streaksTick,
         weatherTick } from "./weather.js";
import { drawPlane, withPerspective } from "./perspective.js";
import { probe } from "./profiler.js";

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
  //: пасмурность — такой же уровень канала, как ночной, значит и слои
  //: она обязана включать: иначе тучи затемнят светлые кадры (интерьеры,
  //: bright-юнитов), которые движок держит вне заливки суток.
  const filtered = daylight.levels.some((level) => level !== 0)
    || overcast.level > 0;
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
      //: Подложка — ТА ЖЕ ПЛОСКОСТЬ, что земля, и корёжится так же. Возьми
      //: её спрайтовым правилом (равномерный масштаб по нижнему краю) — и
      //: между плитками разошлись бы швы.
      //: Размер берём НАТУРАЛЬНЫЙ, а не `cell.size`: при выключенном флаге
      //: `drawPlane` вырождается в тот же самый `drawImage(image, x, y)`,
      //: и кадр обязан совпасть с прежним точка в точку.
      drawPlane(context, underlayImage, cell.x, cell.y,
                underlayImage.width, underlayImage.height);
    }
  }

  //: ДОЖДЬ — СРАЗУ ЗА ПОДЛОЖКОЙ И ДО ЗЕМЛИ.
  //:
  //: Кольцо лежит НА ВОДЕ, а вода у нас самый нижний слой: земля кладётся
  //: поверх неё со своей прозрачностью, и сквозь прорехи в земле видна
  //: именно подложка. Значит и кольцо обязано уходить под землю ровно так
  //: же, как уходит вода под ним. Раньше я рисовал его после выпечки земли,
  //: рассудив «кольцо лежит на грунте», — и круги шли поверх берега.
  //:
  //: Такт берём тут же: у него под рукой видимая коробка, по которой кольца
  //: и сеются, а от него зависят и струи, и тучи ниже по кадру.
  weatherTick(visible);
  probe(". дождь", renderRain);

  // ЗЕМЛЯ И НАКЛАДКИ МЕСТНОСТИ — ОДНИМ ИСПЕЧЁННЫМ КУСКОМ (ground.js).
  // Они статичны, а рисовались поклеточно каждый кадр: при отдалении в кадр
  // попадает вся карта, и это тысячи блитов (у Тиграта 7 807 плиток и 378
  // накладок). Порядок сохранён — выпечка ложится поверх живой подложки со
  // своей прозрачностью, как ложились сами плитки.
  probe(". земля", () => renderGround(visible));

  // Земля собрана: закрываем слой и кладём на готовый кадр ауру — она
  // прибавляется к уже затемнённой земле, как ветка света внутри самого
  // прохода земли. Тени идут следом: проход VA 0x440788 делит яркость
  // всего нарисованного, включая освещённые клетки. Дальше — новый слой
  // под объекты; светлые кадры внутри него уходят прямо на холст.
  probe(". снаряды", renderProjectiles);
  probe(". вспышки", renderBursts);

  if (layered) {
    probe(". слой суток", endSceneLayer);
    probe(". аура", () => renderLightGlow(visible));
    probe(". тени", () => renderShadows(visible));
    probe(". слой суток", beginSceneLayer);
  } else {
    probe(". тени", () => renderShadows(visible));
  }

  // Объекты, герой и юниты — одним порядком по глубине (docs/RENDER_DEPTH.md).
  // Ключ юнита даёт `unitSortKey`, ключ постройки посчитан при сборке пака и
  // лежит в `bounds.sort_y`. Непрозрачная копия героя: обычная вставка, либо
  // проход здания при бите 21. При бите 15 поверх всей сцены добавляется
  // полупрозрачная копия (список 0x866F5C).
  const heroMode = !hero.data ? "none"
    : hero.insideBuilding != null ? "building" : "painter";
  const heroSortY = unitSortKey(hero);
  let heroDrawn = heroMode !== "painter";
  let heroInBuildingDrawn = false;
  // Юнита, стоящего в постройке, рисует сама постройка сразу после пола
  // (VA 0x425AA8) — из общего прохода по глубине он исключается, иначе
  // пол лёг бы поверх него.
  // ЧУЖИЕ ИГРОКИ — В ТОТ ЖЕ ПРОХОД. Их заводит опыт с соприсутствием
  // (presence.js), и только он: в обычной игре `world.ghosts` пуст, и эта
  // раскладка ничего не стоит. В список `units` призраки не попадают
  // намеренно — туда смотрят бой, приказы и память карты.
  const pending = [...units.filter((unit) => unit.insideBuilding == null),
                   ...(world.ghosts ?? [])]
    .map((unit) => ({ unit, sortY: unitSortKey(unit) }))
    .sort((a, b) => a.sortY - b.sortY);
  let nextUnit = 0;
  // КУЧИ — В ТОТ ЖЕ ПРОХОД. Ключ глубины у кучи на клетках постройки берётся
  // от самой постройки: в движке её рисует отрисовщик объекта сразу после
  // пола (VA 0x00424514), см. lootDrawList: хозяин решается по КЛЕТКАМ.
  const piles = lootDrawList(visible);
  let nextPile = 0;
  // ГЕРОЙ ИДЁТ В ОБЩЕМ ПОТОКЕ, ПО СВОЕМУ КЛЮЧУ.
  //
  // Здесь он вставлялся на ГРАНИЦАХ ОБЪЕКТОВ: сперва рисовались все юниты до
  // глубины очередной постройки, и лишь потом герой. Стоило ему оказаться
  // ДАЛЬШЕ спутника, а ближайшей постройке — глубже обоих, и спутника рисовали
  // раньше героя: ноги дальнего ложились на ближнего. Снаружи это видно, а в
  // доме нет — там жильцов рисует сама постройка своим порядком.
  //
  // Теперь кучи, юниты и герой сливаются в одну очередь по ключу глубины, как
  // в движке: он раскладывает всех по ТАБЛИЦЕ СТРОК (0x84F53C) и идёт по ней
  // сверху вниз, не разделяя, кто из них игрок.
  const drawUnitsBefore = (sortY) => {
    for (;;) {
      const pileY = nextPile < piles.length ? piles[nextPile].sortY : Infinity;
      const unitY = nextUnit < pending.length ? pending[nextUnit].sortY : Infinity;
      const ownY = (heroMode === "painter" && !heroDrawn) ? heroSortY : Infinity;
      const next = Math.min(pileY, unitY, ownY);
      //: ОЧЕРЕДЬ ПУСТА — ВЫХОД. Здесь стояло только `next > sortY`, и на
      //: последнем вызове с `Infinity` сравнение бесконечности с самой собой
      //: ложно: цикл не кончался вовсе. Поймал стенд tools/scene_depth.js.
      if (!Number.isFinite(next) || next > sortY) return;
      // ОПЫТ С ПЕРСПЕКТИВОЙ (perspective.js, флаг ?perspective).
      //
      // Стоящий спрайт Diablo не растягивает: его якорь проходит через то
      // же преобразование, что земля, а сам он масштабируется РАВНОМЕРНО.
      // Поэтому обёртка ставится вокруг ЦЕЛОЙ отрисовки существа и берёт
      // его собственную точку на земле — так фигура остаётся фигурой, а не
      // вытягивается вслед за квадратичной вертикалью плоскости.
      //
      // Без флага `withPerspective` просто зовёт переданную отрисовку.
      if (ownY === next) {
        probe(".. герой", () => withPerspective(context, hero.x, hero.y,
                                                drawHeroAtDepth));
        heroDrawn = true;
      } else if (pileY <= unitY) {
        const pile = piles[nextPile].pile;
        probe(".. кучи", () => withPerspective(context, pile.x, pile.y,
                                               () => drawPile(pile)));
        nextPile += 1;
      } else {
        const unit = pending[nextUnit].unit;
        probe(".. юниты в кадре", () => withPerspective(context, unit.x, unit.y,
                                                        () => renderUnit(unit)));
        nextUnit += 1;
      }
    }
  };
  // Постройки, чьи крыши сейчас сняты, — набор общий на весь проход
  // (правило целиком в entities.partyRoofBuildings).
  const roofOwners = partyRoofBuildings();
  entitiesBeginPass();
  probe(". объекты и юниты", () => {
    for (const object of world.objects) {
      if (!object.frames?.main) continue;
      //: Героя вставляет сама очередь — отдельной проверки на границе
      //: объекта больше нет, она и путала порядок между ним и спутниками.
      drawUnitsBefore(object.bounds.sort_y);
      const { draw_x: x, draw_y: y, width, height } = object.bounds;
      if (x > visible.right || y > visible.bottom ||
          x + width < visible.left || y + height < visible.top) continue;
      //: Якорь постройки берём ИЗ ОДНОГО МЕСТА (entities.buildingAnchor):
      //: та же точка нужна полосовой укладке кадров, и разойтись им нельзя.
      const anchor = buildingAnchor(object);
      const anchorX = anchor.x;
      const anchorY = anchor.y;
      if (probe(".. постройки",
                () => withPerspective(context, anchorX, anchorY,
                                      () => drawObject(object, roofOwners)))) {
        heroInBuildingDrawn = true;
      }
    }
    drawUnitsBefore(Infinity);
    if (heroMode === "painter" && !heroDrawn) {
      withPerspective(context, hero.x, hero.y, drawHeroAtDepth);
    }
    if (heroMode === "building" && !heroInBuildingDrawn) {
      withPerspective(context, hero.x, hero.y, drawHeroAtDepth);
    }
  });
  entitiesEndPass();
  probe(". амбиент сцены", () => renderAmbient(visible));
  drawSelectionBand();

  if (layered) {
    endSceneLayer();
  } else {
    applyDaylight();
  }
  //: ОГОНЬ — ПОСЛЕ СЛОЯ СУТОК И ПОСЛЕ ЮНИТОВ. Он светит сам: затенять его
  //: нечем, а вспышка в руках обязана лечь НА фигуру, а не под неё. Канонная
  //: стрела при этом осталась внутри сцены, как в движке (projectiles.js).
  probe(". огонь", renderFire);

  //: СТРУИ — ПОВЕРХ ВСЕЙ СЦЕНЫ И В ЭКРАННЫХ КООРДИНАТАХ, как у них: границы
  //: частицы сверяются с шириной и высотой кадра (VA 0x50C270), значит она
  //: живёт перед камерой, а не в мире. Ни перспектива, ни фильтр суток её не
  //: касаются. Кольца при этом лежат на земле и рисуются сразу за землёй.
  streaksTick(canvas.width, canvas.height, clock.elapsed ?? 0);
  probe(". струи", () => renderStreaks(context));


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
