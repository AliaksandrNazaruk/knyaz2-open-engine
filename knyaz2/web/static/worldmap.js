// Глобальная карта: сетка 24x32, туман, значки локаций и путь отряда.
//
// Всё по движку (VA 0x4277F4 рисует, 0x437ABC открывает клетки, 0x436908
// открывает локацию, 0x437EA8 ставит отряд в середину клетки):
//
//     клетка   dword: локация | вид местности | сцена боя | флаги тумана
//     флаги    0x20 «отряд здесь был», 0x40 «видно от соседа»,
//              0x80 «значок локации ещё закрыт по сюжету»
//     сетка    рисуется с (0xA7, 0x19) шагом 0x1A на 0x1C
//     отряд    стоит в середине клетки: +0xD и +0xE от её угла
//
// Ходить можно там, где маска движка даёт бит 1 посуху (бит 2 — морем,
// под кораблём). Маска посчитана при сборке пака и лежит рядом с сеткой.
import { world } from "./world.js";
import { contentUrl } from "./content.js";

//: Состояние глобальной карты живёт дольше карты локации: отряд
//: возвращается на неё туда же, откуда ушёл.
export const worldMap = {
  open: false,
  // НА КАРТЕ ЛИ ОТРЯД. В движке это одно число: текущая карта 0x8496C8,
  // и «отряд на глобальной» значит, что она равна −1. Обе ветки щелчка по
  // карте начинаются с этой проверки — и поход (VA 0x42227F), и вход в
  // локацию по её значку (VA 0x421FB8). Пока мы ВНУТРИ локации, её номер
  // там обычный, поэтому карта из боковой панели только СМОТРИТСЯ: ни
  // идти, ни входить с неё нельзя. На карту выходят краем локации.
  onMap: false,
  cells: null,      // сетка со снятым туманом
  // ПОЛОЖЕНИЕ ОТРЯДА — В ПИКСЕЛЯХ, и это главное. Движок держит его в двух
  // числах с плавающей точкой (0x84956C и 0x849570), а строку и столбец
  // только ВЫВОДИТ из них делением (VA 0x4277F4). Поэтому отряд и может
  // стоять посреди клетки: своей клетки у него нет вовсе, есть точка.
  x: null, y: null,
  row: null, col: null,     // производные от x, y — держим для удобства
  rules: null,
  trip: null,       // идущий поход: цель, шаг и сколько кадров осталось
  wandering: null,  // бродячие отряды: живое состояние поверх хвоста GAME.0
};

//: Пересчитать клетку из точки — как это делает движок каждый кадр.
function syncCell() {
  if (worldMap.x === null) return;
  const place = cellOf(worldMap.x, worldMap.y);
  worldMap.row = place.row;
  worldMap.col = place.col;
}

//: Поставить отряд в точку картинки.
export function placeAt(x, y) {
  worldMap.x = x;
  worldMap.y = y;
  syncCell();
  return { row: worldMap.row, col: worldMap.col };
}

function rulesOf() {
  return world.map?.hero?.rules?.world_map ?? null;
}

//: Завести сетку один раз за сеанс: туман — это накопленное знание.
export function worldMapSetup() {
  const rules = rulesOf();
  if (!rules) return false;
  worldMap.rules = rules;
  if (!worldMap.cells) {
    worldMap.cells = rules.grid.map((row) => row.slice());
  }
  // Бродячие отряды: в файле лежат только порог возрождения и домашняя
  // клетка — живыми их делает игра (VA 0x41C944), и состояние живёт здесь.
  if (!worldMap.wandering) {
    worldMap.wandering = (rules.wandering?.records ?? []).map((record) => ({
      ...record, alive: false, role: null, row: null, col: null,
    }));
  }
  return true;
}

//: Счётчик жребиев бродячих: движок бросает их каждый 16-й тик игрового
//: времени (VA 0x41C944 и 0x4277F4, маска 0xF), у нас — каждый 16-й шаг
//: похода: вне похода глобальная карта в порте не тикает.
let wanderClock = 0;

// Жребии бродячих отрядов. Возвращает встречу, если отряд навязал бой.
//
// Возрождение (VA 0x41C944): запись пуста и rand % 10000 БОЛЬШЕ порога —
// отряд оживает на домашней клетке со случайной СВОБОДНОЙ ролью из семи
// (обход по кругу от жребия, как в движке); состав боя — отряд-шаблон с
// «картой» role_first + роль. Столкновение (VA 0x4277F4): сцена не
// назначена, клетка отряда совпала с клеткой игрока и Следопыт ГЕРОЯ
// меньше rand % 100 — бой; иначе отряд остаётся, и жребий повторится.
function wanderingTick(pathfinder = 0) {
  const set = worldMap.rules?.wandering;
  const records = worldMap.wandering;
  if (!set || !records?.length) return null;
  wanderClock = (wanderClock + 1) & (set.check_mask ?? 0xF);
  if (wanderClock !== 0) return null;
  const taken = new Set(records.filter((r) => r.alive).map((r) => r.role));
  for (const record of records) {
    if (!record.alive) {
      if (record.threshold < roll(set.respawn_die ?? 10000)) {
        const total = set.roles ?? 7;
        let role = roll(total);
        let looked = 0;
        while (looked < total && taken.has(role)) {
          role = (role + 1) % total;
          looked += 1;
        }
        if (looked >= total) continue;          // свободных ролей нет
        taken.add(role);
        record.alive = true;
        record.role = role;
        record.row = record.home_row;
        record.col = record.home_col;
      }
      continue;
    }
    if (record.row === worldMap.row && record.col === worldMap.col &&
        pathfinder < roll(set.evade_die ?? 100)) {
      // Бой назначен: движок пишет отряду сцену и переносит его на карту
      // боя — запись глобальной карты пустеет до нового возрождения.
      const role = record.role ?? 0;
      record.alive = false;
      record.role = null;
      const scene = encounterScene(worldMap.row, worldMap.col);
      if (!scene) continue;
      return { group: (set.role_first ?? 0x8C) + role, scene, wandering: true };
    }
    // ДВИЖЕНИЕ (0x41C9B3, В9): раз в rand%60 == 0 отряд пробует до восьми
    // направлений от случайного и шагает на соседнюю клетку. Не годятся:
    // закрытые (бит 0x10 флагов), клетка героя и клетки других бродячих.
    // Клетка с локацией у движка начинает НАБЕГ на поселение — набеги не
    // смоделированы, поэтому локации отряд обходит стороной (честный
    // остаток В9). Неудачная проба у движка сдвигает направление на
    // единицу — здесь так на каждой пробе.
    if (roll(set.move_die ?? 60) === 0) {
      const steps = set.steps ?? [[0, -1], [-1, -1], [-1, 0], [-1, 1],
                                  [0, 1], [1, 1], [1, 0], [1, -1]];
      let dir = roll(steps.length);
      for (let tries = 0; tries < steps.length; tries += 1) {
        const row = record.row + steps[dir][0];
        const col = record.col + steps[dir][1];
        dir = (dir + 1) % steps.length;
        if (row < 0 || col < 0 ||
            row >= (worldMap.rules?.rows ?? 24) ||
            col >= (worldMap.rules?.cols ?? 32)) continue;
        const cell = worldMap.cells?.[row]?.[col] ?? 0;
        if ((cell >>> 24) & (set.block_flag ?? 0x10)) continue;
        if (cell & 0xFF) continue;                    // локация: без набегов
        if (row === worldMap.row && col === worldMap.col) continue;
        if (records.some((other) => other !== record && other.alive &&
            other.row === row && other.col === col)) continue;
        record.row = row;
        record.col = col;
        break;
      }
    }
  }
  return null;
}


//: Отряд вошёл в клетку (VA 0x437ABC): своя становится пройденной,
//: восемь соседних — видимыми.
export function reveal(row, col) {
  const { cells, rules } = worldMap;
  if (!cells) return;
  const { explored, seen } = rules.flags;
  cells[row][col] |= explored << 24;
  for (let dr = -1; dr <= 1; dr += 1) {
    for (let dc = -1; dc <= 1; dc += 1) {
      const r = row + dr;
      const c = col + dc;
      if ((dr || dc) && r >= 0 && r < rules.rows && c >= 0 && c < rules.cols) {
        cells[r][c] |= seen << 24;
      }
    }
  }
}

// ЧТО ИГРОК ЗНАЕТ О МЕСТЕ — отдельная таблица, а не флаг клетки.
//
// `FUN_00436908(номер)` делает ДВЕ вещи, и это разные вещи:
//
//     *(u8 *)(0x8442A0 + номер) = 1;      // «место мне известно»
//     ... найти клетку с этим номером, поднять бит 0x40, снять 0x80 ...
//
// Первое — таблица знания, второе — туман над значком. Подпись под курсором
// смотрит именно ПЕРВОЕ (VA 0x420E88, код попадания 0x42):
//
//     if (*(char *)(место + 0x8442A0) == '\0')  «Неизвестное место»
//     else                                       имя из 0x4616D4[место]
//
// Порт знал только про туман, а имя брал из номера клетки без всяких
// проверок — и на глобальной карте писалось «Черный Бор» над местом, где
// игрок ни разу не был и куда его ещё не пустил сюжет.
export const UNKNOWN_PLACE = "Неизвестное место";

//: Наш `0x8442A0`. Заполняется тем же, чем в движке, — открытием локации.
const known = new Set();

export function locationKnown(number) { return known.has(Number(number)); }

// Имя места для показа. Единственное место, где решается «называть или нет»:
// его зовут и подпись карты, и наведение на значок, и приход в клетку.
export function locationName(number) {
  const n = Number(number);
  if (!n) return UNKNOWN_PLACE;
  if (!known.has(n)) return UNKNOWN_PLACE;
  return worldMap.rules?.names?.[n] || UNKNOWN_PLACE;
}

export function knownPack() { return [...known]; }

export function knownUnpack(list) {
  known.clear();
  for (const n of list ?? []) known.add(Number(n));
  return known;
}

//: Новая игра забывает всё: в движке таблица знания лежит в блоке состояния
//: и перечитывается вместе с ним.
export function knownReset() { known.clear(); }

//: Открыть локацию по сюжету (VA 0x436908): пометить её известной и снять с
//: её значка туман.
export function openLocation(location) {
  const { cells, rules } = worldMap;
  known.add(Number(location));
  if (!cells) return null;
  for (let row = 0; row < rules.rows; row += 1) {
    for (let col = 0; col < rules.cols; col += 1) {
      if ((cells[row][col] & 0xFF) === location) {
        cells[row][col] |= rules.flags.seen << 24;
        cells[row][col] &= ~(rules.flags.hidden << 24);
        return { row, col };
      }
    }
  }
  return null;
}

//: Виден ли значок локации (VA 0x4277F4).
export function markerVisible(cell) {
  const { flags } = worldMap.rules;
  const byte = (cell >>> 24) & 0xFF;
  return !(byte & flags.hidden) && !!(byte & (flags.explored | flags.seen))
         && !!(cell & 0xFF);
}

//: Где на сетке стоит эта локация.
export function locationCell(location) {
  const { cells, rules } = worldMap;
  if (!cells || !location) return null;
  for (let row = 0; row < rules.rows; row += 1) {
    for (let col = 0; col < rules.cols; col += 1) {
      if ((cells[row][col] & 0xFF) === location) return { row, col };
    }
  }
  return null;
}

//: Поставить отряд в клетку локации и открыть вокруг туман.
export function standAt(location) {
  if (!worldMapSetup()) return false;
  const place = locationCell(location);
  if (!place) return false;
  // Движок ставит отряд в СЕРЕДИНУ клетки локации (VA 0x437EA8) — но
  // ставит именно точку, а не «клетку», и дальше она живёт сама по себе.
  const spot = centre(place.row, place.col);
  placeAt(spot.x, spot.y);
  openLocation(location);
  reveal(place.row, place.col);
  return true;
}

// Открыть карту целиком — та же отладочная клавиша, что и в игре
// (VA 0x437FF8, код 0x4F): каждой клетке ставится 0x60 и снимается 0x80.
// В обычной игре локации открывает сюжет, по одной.
export function revealAll() {
  const { cells, rules } = worldMap;
  if (!cells) return false;
  const on = (rules.flags.explored | rules.flags.seen) << 24;
  for (let row = 0; row < rules.rows; row += 1) {
    for (let col = 0; col < rules.cols; col += 1) {
      cells[row][col] |= on;
      cells[row][col] &= ~(rules.flags.hidden << 24);
    }
  }
  return true;
}

//: Пройдёт ли отряд по клетке: бит 1 маски посуху, бит 2 морем.
export function walkable(row, col, ship = false) {
  const rules = worldMap.rules;
  const value = rules?.walk?.[row]?.[col] ?? 0;
  return !!(value & (ship ? rules.mask.sea : rules.mask.land));
}

// Середина клетки в пикселях картинки: там и стоит отряд (VA 0x437EA8).
function centre(row, col) {
  const r = worldMap.rules;
  return { x: r.origin[0] + col * r.cell[0] + r.centre[0],
           y: r.origin[1] + row * r.cell[1] + r.centre[1] };
}

// Клетка по точке. Множители те же, что у движка (0x452430…0x45243C:
// −25, 1/28, −167, 1/26), но главное — КАК он превращает дробь в целое.
//
// Перед каждым fistp движок зовёт 0x442BF0, а та кладёт в управляющее слово
// FPU байт 0x1F: биты 10–11 (режим округления) становятся 11 — «к нулю».
// То есть frndint там ОТБРАСЫВАЕТ дробную часть, а не округляет к
// ближайшему.
//
// Это не мелочь. Отряд стоит ровно в середине клетки (угол + 13 и + 14 из
// 26 и 28), поэтому деление всегда даёт «номер клетки плюс ровно половина».
// Отбрасывание даёт номер, а округление к ближайшему — номер ПЛЮС ОДИН, и
// по обеим осям сразу: отсюда и был ход «только вниз и вправо».
function cellOf(x, y) {
  const r = worldMap.rules;
  return { row: Math.trunc((y - r.origin[1]) / r.cell[1]),
           col: Math.trunc((x - r.origin[0]) / r.cell[0]) };
}

// Тронуться в путь (VA 0x421690, код мыши 0x42). Длина пути считается в
// ПИКСЕЛЯХ, а не в клетках, и на каждый кадр приходится свой бросок
// жребия встречи — поэтому поход и опасен: чем дальше, тем больше бросков.
//
//     кадров = ((100 - прыть) * 0.01 + 1) * max(|dx|, |dy|)
//
// «Прыть» — наибольший байт +0xDF в отряде: он же уменьшает и шанс
// нарваться (VA 0x4277F4).
// Идти в ТОЧКУ картинки. Движок ведёт отряд именно туда, куда щёлкнули, а
// не в середину клетки: цель — сами координаты мыши (VA 0x421690, код 0x42
// пишет их в 0x849758 и 0x849774).
export function startTravelTo(toX, toY, { speed = 0, ship = false } = {}) {
  if (worldMap.x === null || !worldMap.rules) return null;
  // Идём ОТ ТЕКУЩЕЙ ТОЧКИ отряда, где бы она ни была: движок другой и не
  // знает. Новый щелчок посреди похода просто задаёт новую цель отсюда.
  const dx = Math.trunc(toX - worldMap.x);
  const dy = Math.trunc(toY - worldMap.y);
  const distance = Math.max(Math.abs(dx), Math.abs(dy));
  if (!distance) return null;
  const scale = worldMap.rules.travel?.scale ?? 0.01;
  // Кадров тоже целое число, и тоже отбрасыванием.
  const frames = Math.max(1, Math.trunc(((100 - speed) * scale + 1) * distance));
  worldMap.trip = {
    toX, toY, dx: dx / frames, dy: dy / frames, left: frames, ship,
  };
  return worldMap.trip;
}

// Идти в клетку — тот же поход, но целью взята её середина. Так уходят по
// значку локации, где цель названа клеткой, а не точкой.
export function startTravel(row, col, options = {}) {
  const to = centre(row, col);
  return startTravelTo(to.x, to.y, options);
}

export function travelling() { return !!worldMap.trip; }

export function stopTravel() { worldMap.trip = null; }

// Один кадр похода. Возвращает, что случилось: «идём», «пришли», «стоп»
// (маска не пустила) или «встреча» — тогда в поле лежат отряд и место боя.
export function travelTick(hero = {}) {
  const trip = worldMap.trip;
  if (!trip) return null;
  // Точка, с которой шагнули: движок запоминает её ЦЕЛОЙ (fistp перед
  // ходом) и именно к ней возвращает отряд, если маска не пустила.
  const backX = Math.trunc(worldMap.x);
  const backY = Math.trunc(worldMap.y);
  trip.left -= 1;
  if (trip.left <= 0) { worldMap.x = trip.toX; worldMap.y = trip.toY; }
  else { worldMap.x += trip.dx; worldMap.y += trip.dy; }
  const place = cellOf(worldMap.x, worldMap.y);
  const r = worldMap.rules;
  if (place.row < 0 || place.col < 0 || place.row >= r.rows || place.col >= r.cols
      || !walkable(place.row, place.col, trip.ship)) {
    // Не пустило: поход обрывается, отряд возвращается на прежнюю точку
    // (VA 0x427A80). Никакого «туда не пройти» заранее движок не говорит —
    // отряд идёт, сколько может, и встаёт у преграды.
    worldMap.trip = null;
    placeAt(backX, backY);
    return { kind: "blocked", row: worldMap.row, col: worldMap.col };
  }
  worldMap.row = place.row;
  worldMap.col = place.col;
  reveal(place.row, place.col);
  // Сначала бродячие (их цикл в кадре идёт раньше терраинового жребия,
  // VA 0x4277F4), потом случайная встреча местности.
  const met = wanderingTick(hero.pathfinder ?? 0)
    ?? rollEncounter(place.row, place.col, hero);
  if (met) { worldMap.trip = null; return { kind: "encounter", ...met, ...place }; }
  if (trip.left <= 0) { worldMap.trip = null; return { kind: "arrived", ...place }; }
  return { kind: "walking", ...place };
}

//: Бросок движка: целое от нуля (VA 0x442B93 — обычный rand).
function roll(limit) { return Math.floor(Math.random() * limit); }

// Жребий встречи на клетке (VA 0x4360A8). Сначала «спокойствие» местности:
// если бросок из тысячи меньше него, ничего не случилось. Иначе по телу
// героя выбирается класс опасности, из него — отряд, а из местности —
// место боя.
export function rollEncounter(row, col, hero = {}) {
  const r = worldMap.rules;
  const cell = worldMap.cells[row][col];
  const kind = (cell >> 8) & 0xFF;
  const terrain = r.terrain?.[kind];
  if (!terrain) return null;
  if (roll(1000) < terrain.calm) return null;
  const danger = terrain.parties[Math.min(hero.body ?? 0, terrain.parties.length - 1)];
  const group = danger?.[roll(danger.length)] ?? 0;
  const scene = encounterScene(row, col);
  if (!group || !scene) return null;
  return { group, scene, terrain: kind };
}

// Сцена боя по местности клетки: жребий из пятнадцати сцен записи
// (0x45FC81 + местность*0x17 + rand % 15) — общий для случайной встречи
// и для столкновения с бродячим отрядом (VA 0x4360A8 и 0x4277F4).
function encounterScene(row, col) {
  const r = worldMap.rules;
  const terrain = r.terrain?.[(worldMap.cells[row][col] >> 8) & 0xFF];
  if (!terrain?.scenes?.length) return 0;
  let scene = terrain.scenes[roll(terrain.scenes.length)] ?? 0;
  // Море дерётся не на берегу: сцена 26 переводится в бой на корабле.
  if (scene === r.scenes.sea) scene = r.scenes.sea_battle;
  return scene;
}

// Расстановка встречного отряда вокруг вожака: таблица движка 0x461BC0,
// свой набор на чётность строки и на направление (VA 0x415238). Занятые
// клетки пропускаются, как и в движке.
export function formationCells(row, col, direction = 0, count = 0, free = () => true) {
  const table = worldMap.rules?.formation;
  const out = [{ row, col }];
  if (!table) return out;
  const slots = table[row & 1]?.[direction & 7] ?? [];
  for (const [dr, dc] of slots) {
    if (out.length > count) break;
    const place = { row: row + dr, col: col + dc };
    if (free(place.row, place.col)) out.push(place);
  }
  return out;
}
