// Персонаж: клеточное движение движка, кадры и правила видимости.
import { world } from "./world.js";
import { tickSeconds } from "./clock.js";
import { isSelected } from "./orders.js";
import { clampCamera, spriteReady, context, layeredFrame, view,
         withMainContext } from "./viewport.js";
import { actorAttackPose, actorBody, actorItem, actorLayers, actorWeapon,
         drawLayerFrame, heroSheets } from "./actor.js";

// Игровой персонаж: восемь направлений, стойка/ходьба из HEROES.RES.
// Управление — WASD/стрелки и клик по земле; движется в экранных осях, но
// проверяет коллизии по сетке (blocked). Направление кадра выбирается по
// экранному вектору движения.
export const hero = {
  data: null,
  x: 0, y: 0,                 // мировые пиксели (точка у ног)
  cell: { row: 0, col: 0 },   // логическая клетка (назначение текущего шага)
  step: null,                 // активный шаг {fromX, fromY, toX, toY, time, duration}
  direction: 6,
  moving: false,
  frame: 0,
  frameTime: 0,
  // Состояние анимации по правилам движка (см. konung2/heroes.py):
  //   стойка   — бит 0x04 байта unit+0x19: мирная или боевая;
  //   бег      — бит 0x80, его ставит режим движения 1 (VA 0x416641);
  //   поза     — что играем сейчас: stand, walk, idle, run.
  stance: "peace",
  running: false,
  pose: "stand",
  target: null,              // цель клика {x, y}
  goal: null,                // клетка назначения приказа
  path: [],                  // кусок маршрута — СПИСКОМ НАПРАВЛЕНИЙ, как у движка
  goalTarget: null,          // кому позволено стоять на клетке цели (+0x10)
  cells: null,               // сетка занятости 0x5662BC: 0 / 0xFFF / метка юнита
  buildingCells: new Map(),  // "row:col" -> {slot, built, routed}
  brightCells: new Set(),    // бит 22: юнит рисуется статичной палитрой
  roofSlot: null,            // здание, чью крышу прячем (клетка героя)
  insideSlot: null,          // бит 21 без бита 15: рисуем в проходе здания
  overlay: false,            // бит 15: игрок рисуется поверх всей сцены
  bright: false,             // клетка героя несёт бит 22
  grid: null,
  // Экипировка по слотам движка: рука (unit+0x56), вторая рука (unit+0x5E),
  // метательное (unit+0x58). Значение — название класса предмета.
  equipment: { hand: null, off_hand: null, ranged: null },
  bag: [],                   // подобранное, но не надетое
};

//: Кадры шага больше не нужны: время клетки задаёт походка, а не длина
//: цикла анимации. Прежняя формула «кадры/2 / SPEED_SCALE» была подобранной,
//: и именно она давала ход втрое-вдевятеро медленнее оригинала.

// Кадры позы для текущего направления.
export function heroFrames(pose = hero.pose, direction = hero.direction) {
  const sets = hero.data?.animations;
  // Действия общие для обеих стоек: пары у них в таблицах движка нет.
  return sets?.[hero.stance]?.[pose]?.[direction] ??
    sets?.actions?.[pose]?.[direction] ?? null;
}

// Разовое действие: играет до конца и возвращается в стойку. Оружие в кадре
// живёт отдельным слоем экипировки, поэтому отдельных анимаций под меч, лук
// или двуручное у тела нет: ударов и выстрелов ровно пять, и какой играет —
// решает группа предмета в руке (rules.attack_by_item, VA 0x416B50 ближний
// бой и 0x416AC8 стрельба).
export function heroPlayAction(name) {
  if (!hero.data?.animations?.actions?.[name]) return false;
  hero.moving = false;
  hero.step = null;
  hero.path = [];
  hero.goal = null;
  heroSetPose(name);
  return true;
}

// Смерть — жребий ровно из трёх вариантов (VA 0x416A64), и юнит при этом
// уходит из своей клетки, поэтому дальше он стеной для других не считается.
export function heroDie() {
  const variants = hero.data?.rules?.death_variants ?? 3;
  return heroPlayAction(`death_${1 + Math.floor(Math.random() * variants)}`);
}

// Номер варианта смерти сохраняется в позе трупа: движок ставит блок 13 для
// первой смерти и «блок + 3» для остальных, то есть 11->14 и 12->15
// (VA 0x41471E и 0x414727).
function heroCorpseOf(pose) {
  const corpse = `corpse_${pose.slice("death_".length)}`;
  return hero.data?.animations?.actions?.[corpse] ? corpse : "corpse_1";
}

export const keys = new Set();

export function heroCellKey(row, col) { return `${row}:${col}`; }

//: СЕТКА ЗАНЯТОСТИ — ОДНИМ МАССИВОМ, как 0x5662BC у движка: младшие 12 бит
//: клетки это 0 «свободно», 0xFFF «стена или вода», иначе номер стоящего
//: юнита (VA 0x44146C). Метки юнитов кладутся только на время поиска пути.
const CELL_WALL = 0xFFF;
const CELL_UNIT = 1;              // здесь кто-то стоит
const CELL_TARGET = 2;            // здесь стоит тот, к кому мы идём

export function heroSetup(config, map) {
  hero.data = config;
  hero.grid = map.coordinates.navigation_grid;
  const terrain = map.terrain ?? {};
  // Стены раньше лежали в Set со строковыми ключами, а юниты искались
  // перебором всего списка на КАЖДУЮ проверку клетки — волна звала это
  // восемь раз на клетку. Теперь и то и другое читается одним индексом.
  waveSetup(hero.grid.rows, hero.grid.columns);
  hero.cells.fill(0);
  for (const [row, col] of terrain.blocked ?? []) {
    if (row >= 0 && col >= 0 && row < hero.grid.rows && col < hero.grid.columns) {
      hero.cells[row * hero.grid.columns + col] = CELL_WALL;
    }
  }
  // Глухие клетки (бит 0x4000) — не то же самое, что непроходимые: вода и
  // деревья ходить не дают, но стрелу пропускают, а стена и постройка нет.
  hero.solid = new Set(
    (terrain.solid ?? []).map(([row, col]) => heroCellKey(row, col)));
  world.solidAt = (row, col) => hero.solid.has(heroCellKey(row, col));
  // Клетки берутся у самих построек: каждая владеет своим полом, «крыльцом»
  // и маршрутными клетками, поэтому искать их по параллельным спискам больше
  // не нужно.
  hero.buildingCells = new Map();
  // И ПОСТРОЙКИ, И РЕКВИЗИТ СО СВОИМИ КЛЕТКАМИ.
  //
  // Здесь перебирались только `map.buildings`, и достроенная казарма из
  // указателя выпадала: она уезжает в пак реквизитом (постройкой объект
  // считается по стенам его состояния, а у пустой площадки их нет). Из-за
  // этого над ней не пряталась крыша — сокрытие идёт по клетке юнита
  // (VA 0x428282), а её в указателе не было вовсе.
  for (const building of [...(map.buildings ?? []), ...(map.props ?? [])]) {
    if (!building.cells) continue;
    const cells = building.cells ?? {};
    const floor = new Set((cells.floor ?? []).map(([row, col]) => heroCellKey(row, col)));
    const routed = new Set((cells.routed ?? []).map(([row, col]) => heroCellKey(row, col)));
    for (const [row, col] of cells.footprint ?? []) {
      const key = heroCellKey(row, col);
      hero.buildingCells.set(key, {
        building,
        slot: building.record_slot,
        built: floor.has(key),
        routed: routed.has(key),
      });
    }
  }
  hero.brightCells = new Set(
    (terrain.daylit_cells ?? []).map(([row, col]) => heroCellKey(row, col)));
  if (!config) return;
  // Восемь наборов: четыре позы в двух стойках.
  const preload = [];
  // Кадры героя лежат НА ЛИСТАХ — так же, как движок держит HEROES.RES
  // одним куском (VA 0x43C2E8). Тянем листы, а не файл на кадр: их
  // единицы вместо десятков тысяч.
  //
  // НО НЕ ВСЕ СРАЗУ. Здесь стояло `for (const sheet of config.sheets)` — все
  // 72 листа, 121.6 МБ, и загрузка их ДОЖИДАЛАСЬ. Какие листы нужны, знает
  // только расстановка (у каждого актёра своя форма, палитра и снаряжение),
  // а она идёт позже, поэтому список спрашивают у `actorSheetPaths` уже
  // после неё, а остаток тянут фоном. Движок такой беды не знает: у него
  // HEROES.RES лежит на диске.
  for (const poses of Object.values(config.animations ?? {})) {
    for (const directions of Object.values(poses)) {
      for (const frames of directions) {
        for (const frame of frames) {
          if (frame.sheet === undefined) preload.push(frame.path);
          if (frame.shadow?.sheet === undefined && frame.shadow) {
            preload.push(frame.shadow.path);
          }
        }
      }
    }
  }
  const start = map.hero?.start;
  hero.cell = start
    ? { row: start.row, col: start.col }
    : heroCellAt(heroSpawn(map).x, heroSpawn(map).y);
  const anchor = heroAnchor(hero.cell.row, hero.cell.col);
  hero.x = anchor.x;
  hero.y = anchor.y;
  heroUpdateBuilding();
  return preload;
}

// Якорь юнита в клетке — формула движка VA 0x43B974.
export function heroAnchor(row, col) {
  const grid = hero.grid;
  return {
    x: col * grid.cell_width + (row & 1 ? grid.anchor_x_odd : grid.anchor_x_even),
    y: row * grid.cell_height + grid.anchor_y,
  };
}

export function heroSpawn(map) {
  // Канонная точка: клетка отряда игрока из GAME.x для этой карты.
  const start = map.hero?.start;
  if (start) return heroAnchor(start.row, start.col);
  // запасной вариант: середина построек, если стартовой записи нет
  const built = (map.buildings ?? []).flatMap((building) => building.cells?.floor ?? []);
  if (!built.length) return { x: 1900, y: 1700 };
  let sx = 0, sy = 0;
  for (const [row, col] of built) {
    const anchor = heroAnchor(row, col);
    sx += anchor.x;
    sy += anchor.y;
  }
  return { x: sx / built.length, y: sy / built.length };
}

// Клетка по мировой точке (VA 0x43B9B0). Клетки — РОМБЫ, а не кирпичи:
// деление y на 16 и x на 58 только называет полосу, а дальше движок берёт
// вертикальное ребро полосы и двумя перекрёстными произведениями смотрит,
// не лежит ли точка за диагональю. Если лежит — строка на единицу меньше,
// а столбец сдвигается по чётности строки. Без этой поправки половина
// точек экрана попадала в соседнюю клетку.
export function heroCellAt(x, y) {
  const grid = hero.grid;
  const half = grid.anchor_x_odd;                  // 29 — половина клетки
  const width = grid.cell_width;
  const height = grid.cell_height;
  x = Math.trunc(x);
  y = Math.trunc(y);
  let row = Math.trunc(y / height);
  let col;
  let edge;
  if (row & 1) {
    col = Math.trunc(x / width);
    edge = col * width + half;
  } else {
    col = Math.trunc((x - half) / width);
    edge = col * width + width;
  }
  const bottom = (row + 1) * height;
  const top = bottom - height;
  if (x < edge) {
    if ((y - top) * (x - (edge - half)) < (edge - x) * (bottom - y)) {
      row -= 1;
      if (!(row & 1)) col -= 1;
    }
  } else if (x > edge) {
    if ((bottom - y) * (edge - x) < (x - (edge + half)) * (y - top)) {
      if (!(row & 1)) col += 1;                    // правит СТАРАЯ чётность
      row -= 1;
    }
  }
  row = Math.min(Math.max(row, 0), grid.rows - 1);
  col = Math.min(Math.max(col, 0), grid.columns - 1);
  return { row, col };
}

// Свободна ли клетка для ИДУЩЕГО. `mover` нужен, чтобы юнит не считал
// занятой собственную клетку — иначе он не может сделать первый шаг.
export function heroFree(row, col, mover = null) {
  if (row < 0 || col < 0 || row >= hero.grid.rows || col >= hero.grid.columns) {
    return false;
  }
  if (hero.cells[row * hero.grid.columns + col] === CELL_WALL) return false;
  if (mover?.cell && mover.cell.row === row && mover.cell.col === col) return true;
  // Живой юнит занимает свою клетку, как в движке; перед смертью он из неё
  // уходит (VA 0x416A52), поэтому труп дорогу не держит. Проверка приходит
  // колбэком, чтобы модуль врагов не пришлось импортировать сюда.
  return !hero.occupiedBy?.(row, col, mover);
}

// ПЕРЕПЕЧАТАТЬ КЛЕТКИ ПОСТРОЙКИ (VA 0x43F178).
//
// Движок проходит всю сетку, находит клетки этого объекта по метке «номер
// объекта + 1» в битах 16…20 и делает ровно одно из двух:
//
//     состояние 3 или 4 -> младшие 12 бит В НОЛЬ  (клетка проходима)
//     иначе             -> младшие 12 бит 0xFFF   (глухая)
//
// У нас метка уже разобрана сборщиком в `cells.footprint` объекта, поэтому
// вместо прохода по сетке идём по его собственному следу.
//
// Зовётся это в оригинале ТОЛЬКО из загрузчика карты (0x43DF48:226) — то
// есть достроенная при игроке постройка открывается лишь после выхода и
// возвращения. Мы зовём ещё и в миг смены ступени: держать игрока за дверью
// собственной казармы до перезахода — не то поведение, за которое стоит
// держаться, и на канон это не влияет, потому что состояние то же самое.
export function heroStampBuilding(object, ready = 3) {
  const cells = object?.cells?.footprint;
  if (!cells?.length || !hero.cells || !hero.grid) return 0;
  const open = object.state === ready || object.state === ready + 1;
  let touched = 0;
  for (const [row, col] of cells) {
    if (row < 0 || col < 0 || row >= hero.grid.rows || col >= hero.grid.columns) continue;
    hero.cells[row * hero.grid.columns + col] = open ? 0 : CELL_WALL;
    touched += 1;
  }
  return touched;
}

// Соседняя клетка по направлению движка: решётка со сдвигом рядов, вертикаль
// шагает через два ряда (смещения ±4 и ±0x500 таблицы соседей 0x49CF68).
export function heroNeighbor(row, col, direction) {
  const odd = row & 1;
  switch (direction) {
    case 0: return { row, col: col - 1 };                      // запад
    case 4: return { row, col: col + 1 };                      // восток
    case 2: return { row: row - 2, col };                      // север
    case 6: return { row: row + 2, col };                      // юг
    case 1: return { row: row - 1, col: col - (odd ? 1 : 0) }; // СЗ
    case 3: return { row: row - 1, col: col + (odd ? 0 : 1) }; // СВ
    case 5: return { row: row + 1, col: col + (odd ? 0 : 1) }; // ЮВ
    case 7: return { row: row + 1, col: col - (odd ? 1 : 0) }; // ЮЗ
    default: return { row, col };
  }
}

export function heroUpdateBuilding() {
  // Классификация по ЛОГИЧЕСКОЙ клетке — движок ставит юнита на клетку в
  // начале шага (VA 0x423B00), поэтому в дверях переключение идёт на входе
  // в шаг. Правила из движка:
  // - индекс здания в клетке -> крыша этого здания прячется (VA 0x428282);
  // - бит 21: непрозрачная копия юнита рисуется проходом содержимого здания
  //   (классификатор VA 0x42846E, отрисовка внутри 0x425AA8) — стены её
  //   перекрывают, дверной проём показывает; без бита 21 — обычный порядок;
  // - бит 15 (пол постройки): ДОПОЛНИТЕЛЬНО поверх всей сцены рисуется
  //   полупрозрачная копия игрока (отложенный список 0x866F5C, VA 0x428900;
  //   в 16-битном движке — шахматный растр, у нас — альфа 0.5).
  // - бит 22: юнит блитится статичной палитрой (VA 0x425E81), то есть в
  //   ауре света он остаётся дневным, пока сцена затемнена ночью.
  unitUpdateBuilding(hero);
}

// Состояние постройки для ЛЮБОГО юнита. В движке эти правила не про
// игрока: главный такт (VA 0x413894) гоняет один и тот же разбор по всем
// юнитам отряда, а сокрытие крыш (VA 0x428253) прямо перебирает весь
// отряд игрока начиная с него самого. Поэтому состояние считается на
// юнита, а герой — просто первый из них.
export function unitUpdateBuilding(unit) {
  if (!unit?.cell) return unit;
  const key = heroCellKey(unit.cell.row, unit.cell.col);
  const info = hero.buildingCells?.get(key);
  unit.roofSlot = info ? info.slot : null;
  unit.overlay = Boolean(info?.built);
  unit.insideSlot = info?.routed ? info.slot : null;
  unit.bright = Boolean(hero.brightCells?.has(key));
  return unit;
}

//: ЕДИНЫЙ СПИСОК: игрок — нулевой элемент, дальше остальные юниты карты.
//: В движке массив один (0x7B3C08, шаг 0x100), а указатель игрока просто
//: вычисляется как «массив + первый юнит отряда * 0x100» (VA 0x43C252).
//: Пока порт держит их в двух местах, эта функция даёт канонический
//: порядок всем, кому нужен весь состав.
export function roster(rest = []) { return [hero, ...rest]; }

// Направление к соседней клетке: перебираем восемь и берём то, что ведёт
// именно в неё — считать по вектору нельзя, ряды сетки со сдвигом.
export function heroDirectionToCell(cell, from = hero) {
  for (let direction = 0; direction < 8; direction += 1) {
    const next = heroNeighbor(from.cell.row, from.cell.col, direction);
    if (next.row === cell.row && next.col === cell.col) return direction;
  }
  return null;
}

export function heroDirection(dx, dy) {
  // Направления берём из движка: таблицы шага 0x459AD4/0x459D14 задают
  // 0=запад, 1=СЗ, 2=север, 3=СВ, 4=восток, 5=ЮВ, 6=юг, 7=ЮЗ. Выбираем
  // направление, наиболее сонаправленное вектору движения.
  const steps = hero.data?.direction_steps ?? [];
  let best = 0, bestScore = -Infinity;
  for (let i = 0; i < steps.length; i += 1) {
    const [sx, sy] = steps[i];
    const length = Math.hypot(sx, sy) || 1;
    const score = (dx * sx + dy * sy) / length;
    if (score > bestScore) { best = i; bestScore = score; }
  }
  return best;
}

export function heroInputVector() {
  let dx = 0, dy = 0;
  if (keys.has("KeyW") || keys.has("ArrowUp")) dy -= 1;
  if (keys.has("KeyS") || keys.has("ArrowDown")) dy += 1;
  if (keys.has("KeyA") || keys.has("ArrowLeft")) dx -= 1;
  if (keys.has("KeyD") || keys.has("ArrowRight")) dx += 1;
  if (dx || dy) return { dx, dy };
  if (hero.target) {
    const tx = hero.target.x - hero.x;
    const ty = hero.target.y - hero.y;
    // цель достигнута, когда попали в её клетку или почти вплотную
    const targetCell = heroCellAt(hero.target.x, hero.target.y);
    if ((targetCell.row === hero.cell.row && targetCell.col === hero.cell.col) ||
        Math.hypot(tx, ty) < 12) {
      hero.target = null;
      return null;
    }
    return { dx: tx, dy: ty };
  }
  return null;
}

//: Длина куска маршрута. Движок пишет путь в юнита буфером на 16 байт с
//: терминатором 0xFF, то есть НАПРАВЛЕНИЙ туда влезает пятнадцать
//: (VA 0x441DD6), и перестраивает кусок, когда тот кончился.
export const PATH_CHUNK = 15;

//: МЕРА РАССТОЯНИЯ ДВИЖКА (VA 0x43B670): берётся большая из двух разниц,
//: и если меньшая больше единицы, прибавляется единица. По ней движок
//: считает и дальность удара, и зрение, и догон вожака — значит и «сколько
//: осталось идти» надо мерить ею же, а не суммой разниц.
export function cellDistanceCanon(a, b) {
  const rows = Math.abs(a.row - b.row);
  const cols = Math.abs(a.col - b.col);
  if (rows < cols) return rows > 1 ? cols + 1 : cols;
  return cols > 1 ? rows + 1 : rows;
}

// ── поиск пути (VA 0x441441) ──────────────────────────────────────────────
//
// Волна движка — не «лучший первым», а обычная очередь с двумя весами шага.
// Разобрано по декомпиляции FUN_00441441; всё, что ниже, оттуда:
//
//   * очередь — кольцо на 4096 записей (0x58E31C), порядок строго FIFO;
//   * веса: 10 у четырёх шагов «на соседний ряд» и 14 у запада, востока,
//     севера и юга — оттого маршруты и идут «по кирпичу», а не углами;
//   * порядок обхода соседей РАЗНЫЙ по чётности ряда, и это важно: ничьи
//     разрешаются строгим «дешевле», значит порядок и решает, какой из
//     равноценных маршрутов запомнится;
//   * поле [стоимость, направление] (0x59E31C) между поисками НЕ ЧИСТИТСЯ:
//     счётчик эпохи (0x5EE31C) убывает на 0x10000 за вызов, поэтому прошлые
//     значения сами по себе «бесконечны», а полная заливка нужна раз в
//     32639 поисков. Подготовка поиска стоит ноль;
//   * КЛЕТКА ЦЕЛИ ПРИНИМАЕТСЯ БЕЗ ПРОВЕРКИ ПРОХОДИМОСТИ и в очередь не
//     кладётся — этим волна и заканчивается. Прежняя реализация требовала
//     цель свободной, а клетку цели занимает сама цель: условие «дошли» не
//     выполнялось НИКОГДА, и каждый поиск выгребал потолок в 6000 клеток
//     вместо двух десятков;
//   * как только цель задета, новые клетки не добавляются вовсе;
//   * до волны три дешёвых отказа: цель — стена; цель занята не тем, к кому
//     идём (движок сверяет занявшего с полем +0x10 юнита); у цели нет ни
//     одного свободного соседа.
const WAVE_QUEUE = 4096;              // 0x10000 байт по 16 на запись
const WAVE_INF = 0x7f7f7f7f;
const WAVE_EPOCH_START = 0x7f7f0000;
const WAVE_EPOCH_STEP = 0x10000;
//: Стоимость шага по номеру направления — прямо из тела волны.
const STEP_COST = [14, 10, 14, 10, 14, 10, 14, 10];
//: Порядок обхода: сперва четыре дешёвых шага «на ряд», потом четыре по 14.
const WAVE_ORDER_EVEN = [1, 3, 7, 5, 0, 4, 2, 6];
const WAVE_ORDER_ODD = [3, 1, 5, 7, 0, 4, 2, 6];
//: Те же смещения, что у heroNeighbor, но плоскими таблицами: волна зовёт их
//: десятки тысяч раз за поиск и объекта на каждого соседа не потянет.
//: Сдвиг ряда от чётности не зависит, столбца — зависит.
const NB_ROW = [0, -1, -2, -1, 0, 1, 2, 1];
const NB_COL_ODD = [-1, -1, 0, 0, 1, 0, 0, -1];
const NB_COL_EVEN = [-1, 0, 0, 1, 1, 1, 0, 0];

const wave = {
  rows: 0, columns: 0,
  cost: null, dir: null,              // поле 0x59E31C
  epoch: WAVE_EPOCH_START,            // счётчик 0x5EE31C
  queueCell: null, queueCost: null,   // кольцо 0x58E31C
  trail: null,                        // обратный ход перед разворотом
  stamped: null, stampCount: 0,       // куда мы положили метки юнитов
};

function waveSetup(rows, columns) {
  if (wave.rows === rows && wave.columns === columns) return;
  const cells = rows * columns;
  wave.rows = rows;
  wave.columns = columns;
  wave.cost = new Int32Array(cells).fill(WAVE_INF);
  wave.dir = new Uint8Array(cells);
  wave.trail = new Uint8Array(cells);
  wave.queueCell = new Int32Array(WAVE_QUEUE);
  wave.queueCost = new Int32Array(WAVE_QUEUE);
  wave.stamped = new Int32Array(4096);
  wave.epoch = WAVE_EPOCH_START;
  hero.cells = new Uint16Array(cells);
}

//: Юнитов кладём на сетку прямо перед волной и снимаем сразу после. Движок
//: держит их там всегда, но нам дешевле отметить три десятка клеток, чем
//: перебирать весь список на каждую проверку. Своя клетка не метится вовсе —
//: движок так же вычищает её перед поиском и возвращает после (VA 0x416574).
function waveStamp(mover, target) {
  const columns = wave.columns;
  const cells = hero.cells;
  wave.stampCount = 0;
  hero.eachOccupant?.((unit) => {
    if (unit === mover || !unit.cell) return;
    const idx = unit.cell.row * columns + unit.cell.col;
    if (cells[idx] !== 0 || wave.stampCount >= wave.stamped.length) return;
    cells[idx] = unit === target ? CELL_TARGET : CELL_UNIT;
    wave.stamped[wave.stampCount] = idx;
    wave.stampCount += 1;
  });
}

function waveClear() {
  const cells = hero.cells;
  for (let i = 0; i < wave.stampCount; i += 1) cells[wave.stamped[i]] = 0;
  wave.stampCount = 0;
}

//: `target` — тот единственный, кому позволено стоять на клетке цели: поле
//: +0x10 юнита у движка. Без него погоня упирается в собственную цель.
export function heroPlanPath(from, to, mover = null, target = null) {
  const columns = wave.columns, rows = wave.rows;
  if (!columns) return [];
  if (from.row === to.row && from.col === to.col) return [];
  if (to.row < 0 || to.col < 0 || to.row >= rows || to.col >= columns) return [];
  if (from.row < 0 || from.col < 0 || from.row >= rows || from.col >= columns) return [];
  waveStamp(mover, target);
  try {
    return wavePlan(from.row, from.col, to.row, to.col);
  } finally {
    waveClear();
  }
}

function wavePlan(fromRow, fromCol, toRow, toCol) {
  const columns = wave.columns, rows = wave.rows;
  const cells = hero.cells;
  const cost = wave.cost, dir = wave.dir;
  const queueCell = wave.queueCell, queueCost = wave.queueCost;
  const start = fromRow * columns + fromCol;
  const goal = toRow * columns + toCol;

  // 1) цель — стена, либо на ней стоит не тот, к кому идём
  const occupant = cells[goal];
  if (occupant !== 0 && occupant !== CELL_TARGET) return [];
  // 2) у цели должен быть хоть один свободный сосед (своя клетка считается)
  const goalCol = (toRow & 1) ? NB_COL_ODD : NB_COL_EVEN;
  let reachable = false;
  for (let d = 0; d < 8; d += 1) {
    const r = toRow + NB_ROW[d], c = toCol + goalCol[d];
    if (r < 0 || c < 0 || r >= rows || c >= columns) continue;
    const idx = r * columns + c;
    if (cells[idx] === 0 || idx === start) { reachable = true; break; }
  }
  if (!reachable) return [];

  // 3) волна
  wave.epoch -= WAVE_EPOCH_STEP;
  if (wave.epoch <= 0) { cost.fill(WAVE_INF); wave.epoch = WAVE_EPOCH_START; }
  const epoch = wave.epoch;
  let head = 0, tail = 1, found = false;
  cost[start] = epoch;
  queueCell[0] = start;
  queueCost[0] = epoch;
  while (head !== tail) {
    const cell = queueCell[head], base = queueCost[head];
    head = (head + 1) & (WAVE_QUEUE - 1);
    if (base > cost[cell]) continue;              // запись устарела
    const row = (cell / columns) | 0, col = cell - row * columns;
    const odd = row & 1;
    const order = odd ? WAVE_ORDER_ODD : WAVE_ORDER_EVEN;
    const colStep = odd ? NB_COL_ODD : NB_COL_EVEN;
    let overflow = false;
    for (let i = 0; i < 8; i += 1) {
      const d = order[i];
      const r = row + NB_ROW[d], c = col + colStep[d];
      if (r < 0 || c < 0 || r >= rows || c >= columns) continue;
      const idx = r * columns + c;
      const next = base + STEP_COST[d];
      if (idx === goal) {
        // цель берём БЕЗ проверки проходимости и в очередь не кладём
        if (next < cost[idx]) { cost[idx] = next; dir[idx] = d; found = true; }
        continue;
      }
      if (found) continue;                        // цель задета — больше не растём
      if (cells[idx] !== 0) continue;
      if (next >= cost[idx]) continue;
      cost[idx] = next;
      dir[idx] = d;
      queueCell[tail] = idx;
      queueCost[tail] = next;
      tail = (tail + 1) & (WAVE_QUEUE - 1);
      if (tail === head) { overflow = true; break; }   // кольцо кончилось
    }
    if (overflow) break;
  }
  if (!found) return [];

  // 4) назад по сохранённым направлениям. Обратное направление — (d+4)&7 по
  //    таблице ТОГО ряда, в котором стоим.
  const trail = wave.trail;
  let length = 0;
  let r = toRow, c = toCol;
  while (!(r === fromRow && c === fromCol)) {
    const d = dir[r * columns + c];
    trail[length] = d;
    length += 1;
    if (length >= trail.length) return [];
    const back = (d + 4) & 7;
    const colStep = (r & 1) ? NB_COL_ODD : NB_COL_EVEN;
    r += NB_ROW[back];
    c += colStep[back];
  }
  const keep = length < PATH_CHUNK ? length : PATH_CHUNK;
  const path = new Array(keep);
  for (let i = 0; i < keep; i += 1) path[i] = trail[length - 1 - i];
  return path;
}

// НОВЫЙ ПРИКАЗ ПЕРЕТАЙМЛИВАЕТ ХОД НЕМЕДЛЕННО.
//
// Выдача приказа — FUN_00416574. Найдя путь, она выбирает блок хода прямо по
// битам +0x19 (0x80 бег, 0x04 боевая стойка) и зовёт FUN_00416740, а та:
//
//     FUN_00429B2C(юнит, блок);          // +0xFD = база − скорость
//     param_1[0xFB] = '\0';              // счётчик подшагов сброшен
//     FUN_0043B974(+0x36, +0x3E, +0x12, +0x14);   // якорь на клетку юнита
//
// То есть недоигранный шаг НЕ доигрывается: юнит встаёт на свою клетку и
// начинает следующий уже с новой походкой. Отсюда в оригинале двойной щелчок
// даёт бег с первой же клетки.
//
// У нас длительность шага бралась при его начале и не пересматривалась,
// поэтому после двойного щелчка герой доигрывал начатую клетку шагом — на
// ходьбе это до 0.78 с, а на моей прежней неверной модели до 1.09 с.
//
// ОТСТУПЛЕНИЕ ОТ КАНОНА, СДЕЛАННОЕ НАМЕРЕННО.
//
// В движке сброс безусловный, и это его известный изъян: раздача приказа
// (FUN_004240BC) шлёт его каждому выбранному на КАЖДЫЙ щелчок, ничего не
// сверяя с текущей целью, а хвост FUN_00416740 у идущего юнита вдобавок
// сразу сдвигает +0x12/+0x14 в соседнюю клетку. Отсюда «спам щелчками» гонит
// персонажа скачками быстрее такта.
//
// Чиним условием, которое у самого движка стоит строкой выше — там пересчёт
// походки сделан ТОЛЬКО при смене блока:
//
//     if ((база[текущий] < 1) || (текущий != новый)) FUN_00429B2C(юнит, новый);
//
// Распространяем его на сброс и якорь: перетаймливаем, лишь когда блок хода
// действительно сменился. Повторные щелчки в ту же точку блок не меняют — и
// скачков нет; двойной щелчок меняет 0x11 на 0x13 — и бег включается сразу.
export function unitMoveBlock(unit) {
  const stance = unit.stance ?? hero.stance;
  const running = Boolean(unit.running);
  return stance === "combat" ? (running ? 0x07 : 0x01)
                             : (running ? 0x13 : 0x11);
}

export function unitRetime(unit) {
  if (!unit.step) return;
  if (unit.step.block === unitMoveBlock(unit)) return;
  //: Клетка юнита — уже КОНЕЧНАЯ клетка начатого шага (её ставит
  //: unitTryStep, как движок ставит +0x12/+0x14 в FUN_00413894), поэтому
  //: «якорь на свою клетку» и значит «довести шаг до конца сразу».
  unit.x = unit.step.toX;
  unit.y = unit.step.toY;
  unit.step = null;
}

//: Развязка без петли: orders.js перетаймливает ход через `world`.
world.unitRetime = unitRetime;

// Приказ идти в клетку: планируем кусок пути и запоминаем конечную цель,
// чтобы достроить маршрут, когда кусок кончится.
export function heroOrderTo(x, y, running = false) {
  if (!hero.data) return false;
  hero.goal = heroCellAt(x, y);
  //: Перегруженный не бежит: бит бега ставится с проверкой ноши
  //: (VA 0x42F22C, см. unitCanRun).
  hero.running = running && (world.unitCanRun?.(hero) ?? true);
  hero.target = null;
  // Кому позволено стоять на клетке цели — берём из самого приказа: щелчок по
  // врагу, по лежачему и по собеседнику кладёт его в orderTarget ДО вызова
  // (combat.js -> orderUnit), а «просто идти» не кладёт никого.
  hero.goalTarget = hero.orderTarget ?? null;
  hero.path = heroPlanPath(hero.cell, hero.goal, hero, hero.goalTarget);
  //: Перетаймливает ТОЛЬКО удавшийся приказ: FUN_00416740 стоит в ветке
  //: «путь найден» (FUN_00416574, `if (iVar2 == 0) ... else ...`), а на
  //: непроходимую клетку движок вместо этого зовёт остановку 0x416E24.
  if (hero.path.length) unitRetime(hero);
  return hero.path.length > 0;
}

// Шаг ЛЮБОГО юнита. В движке шагают все одинаково (VA 0x41615A), поэтому
// функция берёт юнита, а герой — просто первый из них.
export function unitTryStep(unit, direction, input) {
  //: Паук в паузе не шагает вовсе (VA 0x413894:180, см. units.js).
  if (world.beastPauses?.(unit)) return false;
  // Никогда не шагаем против желаемого вектора (обход стены не пятится).
  const [sx, sy] = hero.data.direction_steps[direction];
  if (sx * input.dx + sy * input.dy <= 0) return false;
  const next = heroNeighbor(unit.cell.row, unit.cell.col, direction);
  if (!heroFree(next.row, next.col, unit)) return false;
  const to = heroAnchor(next.row, next.col);
  unit.step = {
    fromX: unit.x, fromY: unit.y, toX: to.x, toY: to.y,
    direction, time: 0, duration: unitCellTicks(unit) * tickSeconds(),
    //: Блок хода запоминаем при начале шага — по нему unitRetime и видит,
    //: сменился ли режим движения (см. там же).
    block: unitMoveBlock(unit),
  };
  unit.cell = next;                 // юнит на клетке с начала шага (0x423B00)
  unit.direction = direction;
  unitUpdateBuilding(unit);
  return true;
}

// СКОЛЬКО ТАКТОВ ЗАНИМАЕТ КЛЕТКА.
//
// Цепочка движка, снятая по байтам юнита:
//
//   FUN_00416C84   — по битам +0x19 выбирает блок хода: 0x80 бег, 0x04
//                    боевая стойка, отсюда четвёрка 0x11/0x13/0x01/0x07;
//   FUN_00429B2C   — VA 0x429B3E, кладёт ПОХОДКУ:
//                      *(char *)(юнит + 0xFD) = 0x45FE90[блок] − юнит[0x1D];
//   FUN_0041611C   — VA 0x41612B, каждый такт: `inc byte ptr [eax + 0xFB]`;
//   FUN_00413894   — `if (юнит[0xFD] <= юнит[0xFB])` -> обнулить +0xFB и
//                    перейти в следующую клетку.
//
// То есть КЛЕТКА = база_блока − скорость(+0x1D) тактов. База из 0x45FE90:
// ходьба мирная 10, бег мирный 4, ходьба боевая 11, бег боевой 5.
//
// Проверка независимая: таблица подшагов 0x459AD4/0x459D14 индексируется
// самой походкой (VA 0x416157: `shl eax, 5` по байту +0xFD), и смещение,
// умноженное на походку, даёт ровно переход в соседнюю клетку — (±58, 0),
// (±29, ±16), (0, ±32) — для всех восемнадцати походок таблицы.
//
// Число кадров блока (+0xFE) к скорости отношения НЕ имеет: оно крутит
// спрайты, и когда кадры кончаются, FUN_0041611C возвращает ноль, а блок
// заводится заново. Прежняя моя модель «клетка = кадры × такт» давала бегу
// 702 мс вместо 156…312 и потому была неотличима от канонной ходьбы.
//: Имена баз в паке — те же четыре блока, что выбирает FUN_00416C84.
const BLOCK_KEYS = { 0x01: "combat_walk", 0x07: "combat_run",
                     0x11: "walk", 0x13: "run" };

export function unitCellTicks(unit) {
  const base = hero.data?.rules?.move_block_ticks ?? {};
  const running = Boolean(unit.running);
  const key = BLOCK_KEYS[unitMoveBlock(unit)];
  const ticks = base[key] ?? (running ? 4 : 10);
  //: Скорость вычитается «как есть», но клетка короче одного такта не
  //: бывает: счётчик +0xFB прибавляется раз в такт, поэтому даже нулевая
  //: походка означает переход на первом же такте.
  return Math.max(1, ticks - (world.unitSpeed?.(unit) ?? 0));
}

//: ПОДШАГИ мы не рисуем скачками. Движок каждый такт прибавляет к экранной
//: точке готовое смещение `0x459AD4[походка][направление]`, то есть за такт
//: юнит прыгает на `клетка / походка`; на бегу со скоростью 2 это два прыжка
//: по полклетки. Браузер рисует чаще такта, и мы ведём ту же прямую плавно —
//: длительность и мгновенная средняя скорость совпадают с движком до такта.

export function heroTryStep(direction, input) {
  return unitTryStep(hero, direction, input);
}

// Движение движка: юнит идёт клетка -> клетка по восьми направлениям,
// позиция интерполируется подшагами (VA 0x41615A), направление меняется
// только на границе клетки, проходимость проверяется до начала шага.
// ДВИЖЕНИЕ ЛЮБОГО ЮНИТА — одна реализация на всех. В движке шагают все
// одним кодом (VA 0x41615A), маршрут пишется кусками и достраивается по
// мере надобности (VA 0x441441). Раньше у героя была эта реализация, а у
// юнитов — своя упрощённая копия со своей же «скоростью»; отсюда и
// расхождения вроде бега без ускорения.
export function unitMove(unit, dt, { keyboard = false } = {}) {
  let changed = false;
  if (unit.step) {
    const step = unit.step;
    step.time = Math.min(step.time + dt, step.duration);
    const t = step.duration ? step.time / step.duration : 1;
    unit.x = step.fromX + (step.toX - step.fromX) * t;
    unit.y = step.fromY + (step.toY - step.fromY) * t;
    changed = true;
    if (step.time >= step.duration) {
      unit.x = step.toX;
      unit.y = step.toY;
      unit.step = null;
    }
  }
  if (!unit.step) {
    // Сначала спланированный маршрут: он уже обходит стены. Маршрут — это
    // СПИСОК НАПРАВЛЕНИЙ, как буфер байтов в самом юните (VA 0x441DD6):
    // клетку по нему движок считает на шаге, а не хранит.
    if (unit.path?.length) {
      const direction = unit.path[0];
      const next = heroNeighbor(unit.cell.row, unit.cell.col, direction);
      const dx = next.col - unit.cell.col, dy = next.row - unit.cell.row;
      if (unitTryStep(unit, direction, { dx: dx || 1e-6, dy: dy || 1e-6 })) {
        unit.path.shift();
        changed = true;
      } else if (unit.goalTarget && unit.goal &&
                 next.row === unit.goal.row && next.col === unit.goal.col &&
                 unit.goalTarget.cell?.row === next.row &&
                 unit.goalTarget.cell?.col === next.col) {
        // ДОШЛИ, НАСКОЛЬКО МОЖНО. Клетку цели держит она сама, и шаг в неё
        // движок разбирает отдельно (VA 0x415090): для НЕ боевого приказа
        // он возвращает ноль — приказ снимается, а юнит остаётся стоять
        // рядом, откуда разговор уже достаёт (мерка 7 на 4 клетки,
        // VA 0x4115AC).
        //
        // У нас выходил вечный круг: планировщику занявшего передают, и он
        // клетку принимает (0x441441 сверяет её с полем цели), а шаг её
        // отвергает — путь в один шаг строился заново каждый кадр. Пока
        // разбор приказа стоял под «юнит не шевелится», это было незаметно;
        // с гейтом по пустому пути юнит замирал у собеседника навсегда.
        unit.path = [];
        unit.goal = null;
        unit.goalTarget = null;
      } else {
        // Путь перекрыт: перестраиваем к той же цели. Провал заканчивает
        // дело — движок снимает приказ (VA 0x416E24), а не пробует снова.
        unit.path = heroPlanPath(unit.cell, unit.goal ?? next, unit,
                                 unit.goalTarget ?? null);
        if (!unit.path.length) { unit.goal = null; unit.goalTarget = null; }
      }
    }
    // кусок кончился, а цель ещё не достигнута — достраиваем, как движок
    if (!unit.step && !unit.path?.length && unit.goal) {
      if (unit.goal.row === unit.cell.row && unit.goal.col === unit.cell.col) {
        unit.goal = null;
        unit.goalTarget = null;
      } else {
        unit.path = heroPlanPath(unit.cell, unit.goal, unit, unit.goalTarget ?? null);
        if (!unit.path.length) { unit.goal = null; unit.goalTarget = null; }
      }
    }
    // Клавиатура — только у игрока: остальными правит приказ.
    if (!unit.step && keyboard) {
      const input = heroInputVector();
      if (input) {
        const wanted = heroDirection(input.dx, input.dy);
        // клавиши: прямое направление, иначе соседние ±45°
        const started = unitTryStep(unit, wanted, input) ||
          unitTryStep(unit, (wanted + 1) & 7, input) ||
          unitTryStep(unit, (wanted + 7) & 7, input);
        if (!started && unit.target) unit.target = null;
        changed = changed || started;
      }
    }
  }
  // Остановился — походка забывается: следующий выход в путь бросает её
  // заново. Пока идёт, она та же, оттого ход и ровный.
  unit.moving = Boolean(unit.step);
  return changed;
}

export function heroMove(dt) { return unitMove(hero, dt, { keyboard: true }); }

// Поза и кадр по правилам движка. Ходьба и бег — по биту бега; стоя движок
// каждый раз, когда доигрывает стойка, бросает жребий 1 из 10 и уходит в
// простой (VA 0x416D92), а тот по таблице 0x45A0C0 возвращается в стойку.
export function heroTick(now, dt) {
  if (!hero.data) return false;
  const active = heroMove(dt);
  if (hero.moving) heroSetPose(heroMovePose());
  else if (hero.pose === "walk" || hero.pose === "run") heroSetPose("stand");

  const frames = heroFrames();
  if (!frames?.length) return active || hero.moving;
  const step = tickSeconds();
  hero.frameTime += dt;
  const advance = Math.floor(hero.frameTime / step);
  if (advance > 0) {
    hero.frameTime -= advance * step;
    // ЗАМАХ ЖДЁТ НА НУЛЕВОМ КАДРЕ, и это единственное замедление во всём
    // движке: случаи 5/8/9 разбора такта либо убавляют отсчёт +0xFD, либо
    // двигают кадр (0x413894:365,471). Правило живёт в units.js/attackWait,
    // здесь только проедаем счётчик. Вне блока действия он не нужен — иначе
    // недоеденное ожидание застопорило бы ходьбу.
    if (!world.isMeleePose?.(hero.pose)) hero.attackWait = 0;
    let ticks = advance;
    if (hero.attackWait > 0) {
      const spent = Math.min(ticks, hero.attackWait);
      hero.attackWait -= spent;
      ticks -= spent;
    }
    if (ticks <= 0) return active || hero.moving || hero.pose === "idle";
    const next = hero.frame + ticks;
    if (next < frames.length) {
      hero.frame = next;
    } else if (hero.moving) {
      hero.frame = next % frames.length;          // ходьба и бег зациклены
    } else if (hero.pose.startsWith("corpse_")) {
      hero.frame = 0;                             // труп лежит и не встаёт
    } else if (hero.pose === "idle" || hero.data.animations.actions?.[hero.pose]) {
      // простой и разовые действия доигрывают и возвращаются в стойку
      heroSetPose(hero.pose.startsWith("death_") ? heroCorpseOf(hero.pose) : "stand");
    } else {
      hero.frame = 0;
      // жребий движка: пока стоим, шанс уйти в простой
      const chance = hero.data.rules?.idle_chance ?? 10;
      if (chance > 0 && Math.floor(Math.random() * chance) === 0) heroSetPose("idle");
    }
  }
  return active || hero.moving || hero.pose === "idle";
}

export function heroCurrentFrame() {
  if (!hero.data) return null;
  const frames = heroFrames();
  if (!frames?.length) return null;
  return frames[Math.min(hero.frame, frames.length - 1)] ?? null;
}

// КАДР ТЕЛА ГЕРОЯ — С ЕГО ФОРМОЙ И ПАЛИТРОЙ.
//
// Отдельной отрисовки героя в движке НЕТ: VA 0x425DB4 рисует любого юнита
// одинаково — сперва ставит палитру из его записи (+0x2E), потом рисует слой
// тела `0x30 + (+0xFC)`. Игрок такой же юнит, и правило то же.
//
// Здесь же герой много лет рисовался СЫРЫМ кадром анимации: `renderHero`
// брал `heroCurrentFrame()` и клал его прямо на холст, минуя `actorBody`.
// Форма и палитра к нему не применялись вовсе — оттого за любого из шести
// героев на карте стоял один и тот же болванчик в базовой раскраске, тогда
// как жители красились верно: их рисует общий `drawActor`, а он `actorBody`
// зовёт. Данные при этом были правильные, и потому проверка «какой кадр
// ВЫБРАН» ничего не показывала — выбранный кадр просто не доходил до холста.
export function heroBodyFrame() {
  const frame = heroCurrentFrame();
  if (!frame) return null;
  return actorBody(hero.data, hero, frame) ?? frame;
}

// Поза по состоянию — тот же выбор, что в движке (VA 0x4166A5): идём ли мы,
// и стоит ли бит бега. Стойка и простой добавляются в heroTick.
export function unitMovePose(unit) {
  return unit.running ? "run" : "walk";
}

function heroMovePose() { return unitMovePose(hero); }

//: `force` — как 0x416740: поставить блок ЗАНОВО поверх себя, со сбросом
//: кадра и подшага. Нужно сбиву (поза 2): повторное попадание начинает
//: реакцию сначала, что видно в замере — кадр 7→0, 5→0, 3→0.
export function heroSetPose(pose, force = false) {
  if (hero.pose === pose && !force) return;
  hero.pose = pose;
  hero.frame = 0;
  hero.frameTime = 0;
}

// ── экипировка ────────────────────────────────────────────────────────────
// Предмет в кадре — тот же кадр, но другой слой записи: номер слоя лежит в
// классе предмета (konung2/items.py), а порядок слоёв задаёт таблица движка
// 0x4627D0 — снаряжение уходит ЗА тело, когда персонаж повёрнут спиной в
// боевой стойке (направления 0…4) или лицом в мирной (5…7), иначе рисуется
// поверх. Метательное, когда им не стреляют, висит соседним слоем (лук
// 19 -> 20) и всегда идёт за телом.
export function heroItem(name) {
  return actorItem(name);
}

// Кадры слоёв экипировки — отдельным списком: их тысячи, и держать старт
// заложником оружия, которое ещё никто не поднял, незачем. Клиент грузит их
// фоном сразу после карты, а рисует то, что уже приехало.
// Кадры слоёв экипировки.
//
// ЗДЕСЬ ПОРТ РАСХОДИТСЯ С ДВИЖКОМ, и это видно по времени загрузки. Движок
// читает HEROES.RES ОДНИМ КУСКОМ в одну арену и держит таблицу указателей
// на 1399 записей (VA 0x43C2E8: размер файла -> одно выделение -> таблица
// смещений 0x49C0 -> цикл чтения кусков подряд). Ни отдельных файлов, ни
// дозагрузки там нет вовсе.
//
// Пак же разворачивает те же кадры в 33 426 отдельных PNG, и браузер делает
// 33 426 запросов. Правильное решение — упаковать кадры так же, как в
// оригинале: один блок плюс указатель, а не файл на кадр. Пока этого нет,
// список честно отдаётся целиком и грузится фоном.
// Кадры экипировки лежат на тех же листах, что и тело, — отдельно тянуть
// нечего. Функция осталась для кадров, которые почему-то не попали на лист.
export function heroEquipmentAssets() {
  const paths = [];
  for (const set of Object.values(hero.data?.equipment ?? {})) {
    for (const frame of Object.values(set.frames ?? {})) {
      if (frame.sheet === undefined) paths.push(frame.path);
    }
  }
  for (const set of Object.values(hero.data?.bodies ?? {})) {
    for (const frame of Object.values(set.frames ?? {})) {
      if (frame.sheet === undefined) paths.push(frame.path);
    }
  }
  return paths;
}

export function heroEquip(name) {
  const item = heroItem(name);
  if (!item) return false;
  const slot = item.slot === "bag" ? null : item.slot;
  if (!slot || !(slot in hero.equipment)) {
    hero.bag.push(name);
    return true;
  }
  if (hero.equipment[slot]) hero.bag.push(hero.equipment[slot]);
  hero.equipment[slot] = name;
  // Двуручное занимает обе руки — щит уходит в мешок (VA 0x416BC2: удар
  // двуручным не смотрит на вторую руку вовсе).
  if (slot === "hand" && item.layer >= 13 && item.layer <= 17 && hero.equipment.off_hand) {
    hero.bag.push(hero.equipment.off_hand);
    hero.equipment.off_hand = null;
  }
  return true;
}

export function heroUnequip(slot) {
  const name = hero.equipment[slot];
  if (!name) return false;
  hero.equipment[slot] = null;
  hero.bag.push(name);
  return true;
}

export function heroWeapon() {
  return actorWeapon(hero);
}

export function heroAttackPose() {
  return actorAttackPose(hero.data, hero);
}

function equipmentFor(frame) {
  return actorLayers(hero.data, hero, frame?.record);
}

// Круг под выбранным: цвет по здоровью (VA 0x425DB4). Общий для героя и
// спутников — рисуется одинаково, поэтому живёт здесь, а units.js зовёт
// его же.
export function drawSelectionCircle(actor, baseX, baseY) {
  const set = hero.data?.rules?.orders?.selection?.circle;
  const sprites = world.map?.interface?.selection_circle;
  if (!set || !sprites) return false;
  const [hurt, half] = set.health_steps ?? [401, 801];
  const health = actor.health ?? 0;
  const name = health < hurt ? "hurt" : health < half ? "half" : "whole";
  const circle = sprites[name];
  const image = circle && world.images.get(circle.path);
  if (!image) return false;
  // Смещение кадра — минус якорь ног (127, 144): кольцо уже лежит в своём
  // холсте на нужном месте, как и тело юнита.
  context.drawImage(image, baseX + (circle.offset_x ?? -127),
                    baseY + (circle.offset_y ?? -144));
  // ДЫМКА СВЕЧЕНИЯ (В11): пока горит Факел или Чистая слеза (флаг
  // 0x849610), проходы кругов (0x424514, 0x424FD8) рисуют вокруг круга
  // маску-осветление 64×43 из LIGHTS.RES с центром круга минус (32, 21).
  // Точный спановый светорезолвер не воспроизводится — режим lighter.
  if (world.glow) {
    const glow = world.map?.interface?.glow;
    const halo = glow && world.images.get(glow.path);
    if (halo) {
      const centreX = baseX + (circle.offset_x ?? -127) + image.width / 2;
      const centreY = baseY + (circle.offset_y ?? -144) + image.height / 2;
      context.save();
      context.globalCompositeOperation = "lighter";
      context.drawImage(halo,
                        Math.round(centreX + (glow.offset?.[0] ?? -32)),
                        Math.round(centreY + (glow.offset?.[1] ?? -21)));
      context.restore();
    }
  }
  return true;
}

export function renderHero(alpha = 1, fallbackShadow = alpha >= 1) {
  // Кадр тела — со своей формой и палитрой, как у любого юнита (0x425DB4).
  // Слои снаряжения берутся по НОМЕРУ ЗАПИСИ, а он у формы тот же, поэтому
  // оружие и доспех остаются на месте.
  const frame = heroBodyFrame();
  if (!frame) return;
  // Кадр лежит на ЛИСТЕ, и своего пути у него нет: проверять надо через
  // общий spriteReady, иначе функция выходит здесь и герой не рисуется
  // вовсе — ровно это и случилось, когда кадры переехали на листы.
  if (!spriteReady(world.images, heroSheets(), frame)) return;
  // Целочисленные координаты: drawImage на дробных смещениях мылит и дрожит.
  const baseX = Math.round(hero.x);
  const baseY = Math.round(hero.y);
  // Круг выбора ложится ДО тела, как и у прочих юнитов (VA 0x425DB4):
  // герой такой же член отряда, и круг под ним появляется, только пока он
  // ВЫБРАН, — щёлкнув по спутнику, игрок снимает выделение с героя.
  if (alpha >= 1 && isSelected(hero)) drawSelectionCircle(hero, baseX, baseY);
  // Тень кадра рисует общий проход теней (renderShadows) — тем же правилом,
  // что и тени построек. Здесь остаётся только запасной эллипс, если у кадра
  // теневого слоя нет.
  if (fallbackShadow && !frame.shadow) {
    context.fillStyle = "rgba(10, 10, 12, 0.28)";
    context.beginPath();
    context.ellipse(baseX, baseY - 3, frame.width * 0.32, 6, 0, 0, Math.PI * 2);
    context.fill();
  }
  context.globalAlpha = alpha;
  const { behind, front } = equipmentFor(frame);
  for (const layer of behind) drawLayerFrame(layer, baseX, baseY);
  drawLayerFrame(frame, baseX, baseY);
  for (const layer of front) drawLayerFrame(layer, baseX, baseY);
  context.globalAlpha = 1;
}

// Герой в свою очередь по глубине. На клетке с битом 22 движок блитит юнита
// статичной палитрой (VA 0x425E81), то есть мимо фильтра суток: такой герой
// идёт прямо на кадр, а из слоя сцены вырезается его силуэт. Рисовать его
// раньше слоя нельзя — тогда кадры построек, которые тоже идут мимо фильтра,
// лягут поверх него.
export function drawHeroAtDepth() {
  if (!(layeredFrame && hero.bright)) {
    renderHero();
    return;
  }
  withMainContext(renderHero);
  punchHeroSilhouette();
}

// Вырезать силуэт героя из слоя сцены, чтобы проступила копия, лежащая на
// кадре. Объекты переднего плана рисуются позже и закрашивают вырез, поэтому
// глубина не ломается.
export function punchHeroSilhouette() {
  // Силуэт вырезается по ТОМУ ЖЕ кадру, что рисуется, иначе форма героя и
  // его вырез разъезжаются.
  const frame = heroBodyFrame();
  if (!frame) return;
  if (!spriteReady(world.images, heroSheets(), frame)) return;
  const baseX = Math.round(hero.x);
  const baseY = Math.round(hero.y);
  context.save();
  context.globalCompositeOperation = "destination-out";
  context.globalAlpha = 1;
  drawLayerFrame(frame, baseX, baseY);
  // Оружие и щит вырезаем тоже — иначе на клетке с битом 22 они остались бы
  // в слое сцены и потемнели бы отдельно от хозяина.
  const { behind, front } = equipmentFor(frame);
  for (const layer of [...behind, ...front]) drawLayerFrame(layer, baseX, baseY);
  context.restore();
}

// НАВЕСТИ камеру на героя (VA 0x4291B4). В движке это ЦЕНТРИРОВАНИЕ, и
// зовут его ровно три места: загрузка карты, переход и главный цикл сразу
// после загрузки. В обычном кадре камеру не трогает никто — идущий юнит
// её за собой НЕ тянет. Поэтому функция называется «навести», а не
// «следовать», и вызывать её на каждом шаге нельзя.
export function centreOnHero() { centreOn(hero); }

// Навести камеру на ЛЮБОГО юнита. Канон знает только наведение на игрока
// (указатель 0x84951C пишется один раз при загрузке и не меняется, а все
// четыре вызова 0x4291B4 передают именно его). Наведение на выбранного —
// НАШЕ добавление для окна браузера: в оригинале до спутника доходят
// краевой прокруткой, что мышью в окне неудобно.
export function centreOn(unit) {
  if (!unit) return false;
  view.cameraX = unit.x;
  view.cameraY = unit.y;
  clampCamera();
  return true;
}

// Прокрутка курсором у края окна (VA 0x437CD0). Шаги разные по осям:
// 57 по горизонтали (почти клетка) и 32 по вертикали (две строки).
export const EDGE_SCROLL = { x: 0x39, y: 0x20 };

export function edgeScroll(pointerX, pointerY, width, height) {
  let moved = false;
  if (pointerX <= 0) { view.cameraX -= EDGE_SCROLL.x; moved = true; }
  else if (pointerX >= width - 1) { view.cameraX += EDGE_SCROLL.x; moved = true; }
  if (pointerY <= 0) { view.cameraY -= EDGE_SCROLL.y; moved = true; }
  else if (pointerY >= height - 1) { view.cameraY += EDGE_SCROLL.y; moved = true; }
  // В движке проверка границы стоит ЕЩЁ ДО сдвига (VA 0x437CD0), то есть у
  // края камера не пытается ехать вовсе; здесь то же самое достигается
  // клампом сразу после шага.
  if (moved) clampCamera();
  return moved;
}
