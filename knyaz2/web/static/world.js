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

// КЛЮЧ ГЛУБИНЫ САМОГО «ПОЗДНЕГО» ОБЪЕКТА НАД ТОЧКОЙ, или null, если её не
// накрывает ничей кадр.
//
// Хозяин точки ищется ПО ПЕРЕКРЫТИЮ РАМКИ, а не по номеру: у объектов сцены
// своего номера нет, и связать их с `hero.buildingCells` не через что.
// Спрашивают об этом двое — куча на полу постройки (ей нужен ключ хозяина,
// чтобы лечь сразу за ним, VA 0x00424514) и вырез окна к светлому юниту
// (ему нужно знать, не закроет ли его тот, кто рисуется позже). Раньше
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
export const shared = { hero: null, creatures: null, settlements: null,
                        reputation: null, effects: null, projectiles: null,
                        weather: null };

export function loadShared(document) {
  shared.hero = document?.hero ?? null;
  shared.creatures = document?.creatures ?? null;
  //: Свои снаряды (project/projectiles): у канонной стрелы кадры лежат в
  //: интерфейсе карты, а у этих — свой набор на весь пак, как у тварей.
  shared.projectiles = document?.projectiles ?? null;
  //: Погода (project/weather): у канона её нет вовсе, закон снят с
  //: Diablo II — разбор в docs/RAIN.md.
  shared.weather = document?.weather ?? null;
  //: СОСТОЯНИЕ ВСЕХ ПОСЕЛЕНИЙ, а не только тех, где игрок побывал. Движок
  //: держит блок записей целиком и читает его один раз, поэтому разговор
  //: может спросить про дальнюю деревню: обработчик 35 «Продолжения
  //: легенды» ищет поселение по номеру карты и смотрит его флаги. У нас
  //: запись приезжала вместе со своей картой, и ответить было нечем.
  shared.settlements = document?.settlements ?? null;
  //: ЦЕНЫ УБИЙСТВА ДЛЯ РЕПУТАЦИИ. Одна таблица на всю игру, как и всё
  //: прочее из exe: держать её у карты незачем, а искать в двух местах
  //: вредно (konung2/reputation.py).
  shared.reputation = document?.reputation ?? null;
  //: Кадры огней на объектах (konung2/objectanim.py): семь анимаций,
  //: общих для обеих игр.
  shared.effects = document?.effects ?? null;
  return shared;
}

export function loadMap(map) {
  // Подмешиваем общее: карта несёт только своё место прихода героя.
  if (shared.hero) map.hero = { ...shared.hero, ...(map.hero ?? {}) };
  if (shared.creatures && !map.creatures) map.creatures = shared.creatures;
  if (shared.projectiles && !map.projectiles) map.projectiles = shared.projectiles;
  if (shared.weather && !map.weather) map.weather = shared.weather;
  // ПОСЕЛЕНИЕ — ЗАПИСЬ СВОЕГО МИРА, как и отряды (см. warband.js). Пятёрка
  // должностных лиц деревни в каждом GAME.N своя, а на ней держится
  // маршрутизация разговора: корневая ветвь спрашивает обработчиком 30, кто
  // из собеседников какую должность занимает. С чужими номерами не совпадает
  // ни одна ветвь, и разговор сваливается в безусловную — «Я отдохнул и готов
  // идти за тобой». Подменяем здесь, одним местом на всех читателей.
  const worldId = String(map.hero?.template?.world ?? 0);
  const own = map.village_by_world?.[worldId];
  if (own) map.village = own;
  //: Слоты событий — той же подменой и по той же причине: таблицы у GAME.N
  //: разные (в нулевом семь занятых, в первом пять, дальше четыре).
  const ourEvents = map.events_by_world?.[worldId];
  if (ourEvents) map.events = ourEvents;
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
    // Кадры огней — только тех анимаций, что есть на этой карте: у костра
    // и большого пожара наборы разные, и тянуть все 74 кадра незачем.
    ...[...new Set(world.objects.flatMap((object) =>
        (object.fire ?? []).map((point) => point.anim)))]
      .flatMap((anim) =>
        shared.effects?.object_anims?.[anim]?.frames ?? []),
  ];
}

// Списка кадров тварей здесь больше нет: их 83 листа на 43.4 МБ, а на карте
// встречается горстка пород. Нужный лист заказывает `spriteReady`, когда
// тварь попадает в кадр, — так же, как листы людей.
