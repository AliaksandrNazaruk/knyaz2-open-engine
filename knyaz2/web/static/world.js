// Мир карты в рантайме: земля, сущности, картинки.
//
// Пак 0.2 отдаёт сущности целиком (постройки со своими клетками и кадрами),
// поэтому здесь только раскладка по спискам и порядок отрисовки — правила
// живут в konung2.world на стороне сборщика.
export const world = {
  map: null,
  images: new Map(),
  ground: [],
  groundByKey: new Map(),
  underlay: [],
  underlayVisual: null,
  terrainOverlays: [],
  objects: [],
  missingAssets: new Set(),
  litCells: [],
  brightObjects: 0,          // постройки с исходной палитрой кадра main
};

export function mapBounds(map) {
  const xs = [];
  const ys = [];
  for (const cell of world.ground) {
    xs.push(cell.x, cell.x + map.coordinates.ground_grid.tile_width);
    ys.push(cell.y, cell.y + map.coordinates.ground_grid.tile_height);
  }
  for (const overlay of world.terrainOverlays) {
    if (!overlay.frame) continue;
    xs.push(overlay.position.x, overlay.position.x + overlay.frame.width);
    ys.push(overlay.position.y, overlay.position.y + overlay.frame.height);
  }
  for (const object of world.objects) {
    const { draw_x: x, draw_y: y, width, height } = object.bounds;
    if (!width) continue;
    xs.push(x, x + width);
    ys.push(y, y + height);
  }
  return {
    left: Math.min(...xs),
    right: Math.max(...xs),
    top: Math.min(...ys),
    bottom: Math.max(...ys),
  };
}

// Разложить документ карты пака 0.2 по рабочим спискам. Правила уже применены
// сборщиком (konung2.world), здесь только порядок и индексы для рантайма.
//: ОБЩЕЕ НА ВЕСЬ ПАК: кадры героя, слои снаряжения и наборы тварей. Они
//: одинаковы на всех картах, поэтому лежат в одном shared.json и тянутся
//: РАЗ ЗА СЕАНС. Раньше эти же девять мегабайт ехали в каждом map.json, и
//: каждый переход между картами стоил игроку двадцати пяти мегабайт.
export const shared = { hero: null, creatures: null };

export function loadShared(document) {
  shared.hero = document?.hero ?? null;
  shared.creatures = document?.creatures ?? null;
  return shared;
}

export function loadMap(map) {
  // Подмешиваем общее: карта несёт только своё место прихода героя.
  if (shared.hero) map.hero = { ...shared.hero, ...(map.hero ?? {}) };
  if (shared.creatures && !map.creatures) map.creatures = shared.creatures;
  // ПОСЕЛЕНИЕ — ЗАПИСЬ СВОЕГО МИРА, как и отряды (см. warband.js). Пятёрка
  // должностных лиц деревни в каждом GAME.N своя, а на ней держится
  // маршрутизация разговора: корневая ветвь спрашивает обработчиком 30, кто
  // из собеседников какую должность занимает. С чужими номерами не совпадает
  // ни одна ветвь, и разговор сваливается в безусловную — «Я отдохнул и готов
  // идти за тобой». Подменяем здесь, одним местом на всех читателей.
  const worldId = String(map.hero?.template?.world ?? 0);
  const own = map.village_by_world?.[worldId];
  if (own) map.village = own;
  world.map = map;
  const terrain = map.terrain ?? {};
  world.ground = [...(terrain.ground ?? [])].sort((a, b) => a.row - b.row || a.col - b.col);
  world.groundByKey = new Map(world.ground.map((cell) => [`${cell.row}:${cell.col}`, cell]));
  world.litCells = world.ground.filter((cell) => cell.light?.glow);
  const underlay = terrain.underlay ?? {};
  const underlaySize = underlay.cell_size ?? 256;
  world.underlayVisual = underlay.visual ?? null;
  world.underlay = (underlay.cells ?? []).map(([row, col, value]) => ({
    row,
    col,
    value,
    size: underlaySize,
    x: col * underlaySize,
    y: row * underlaySize,
  }));
  // Порядок исходника сохраняется: этот проход движок глубиной не сортирует.
  world.terrainOverlays = [...(terrain.overlays ?? [])].sort((a, b) =>
    a.record_slot - b.record_slot);
  // Постройки и реквизит рисуются одним списком по глубине: ключ уже посчитан
  // при сборке пака (высота main/walls минус bias за бит 0x08).
  world.objects = [...(map.buildings ?? []), ...(map.props ?? [])].sort((a, b) =>
    a.bounds.sort_y - b.bounds.sort_y ||
    a.bounds.draw_x - b.bounds.draw_x ||
    a.record_slot - b.record_slot);
  world.objects.forEach((object, index) => { object.draw_order = index; });
  world.buildings = map.buildings ?? [];
  // Постройки, чей кадр main идёт исходной палитрой (бит 0x04 hdr+0xFE):
  // из-за них кадр приходится собирать послойно в любое тёмное время суток.
  world.brightObjects = world.objects.filter(
    (object) => object.lighting?.main_static_palette).length;
  return underlay;
}

// Всё, что нужно догрузить для этой карты.
//
// РАДИУСА ЗДЕСЬ НЕТ И НЕ БУДЕТ. Он тут был — `mapAssetsByRadius` делил землю
// и постройки на «близко» и «потом». Замер показал, что делить нечего: вся
// земля с домами на худшей карте это 7.9 МБ, а листы актёров — 34 МБ. Радиус
// экономил бы единицы процентов ценой дыр в земле, поэтому живёт он теперь
// только в очереди листов (app.js) и только для актёров.
export function mapAssets(heroAssets = []) {
  return [
    ...heroAssets,
    ...world.ground.map((cell) => cell.asset),
    ...world.litCells.map((cell) => cell.light?.glow),
    world.underlayVisual?.path,
    world.underlayVisual?.animation?.source,
    ...world.terrainOverlays.map((overlay) => overlay.frame?.asset),
    ...world.objects.flatMap((object) =>
      Object.values(object.frames ?? {}).map((frame) => frame.asset)),
    // Круги под выбранными: их всего три, и нужны они с первого кадра —
    // герой выбран сразу.
    ...Object.values(world.map?.interface?.selection_circle ?? {})
      .map((circle) => circle?.path),
    // дымка свечения Факела и Чистой слезы (В11)
    world.map?.interface?.glow?.path,
  ];
}

// Списка кадров тварей здесь больше нет: их 83 листа на 43.4 МБ, а на карте
// встречается горстка пород. Нужный лист заказывает `spriteReady`, когда
// тварь попадает в кадр, — так же, как листы людей.
