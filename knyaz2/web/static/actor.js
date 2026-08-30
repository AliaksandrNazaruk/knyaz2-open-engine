// Актёр: тело из HEROES.RES плюс слои экипировки. Общий код героя и врагов —
// в движке они и есть одно и то же: один набор кадров на всех, а различают
// юнитов палитра тела ([0x8A7318]) и надетые предметы, каждый из которых
// рисуется своим слоем той же записи (VA 0x426698).
//
// Актёр — это объект с полями:
//   x, y        мировые пиксели, точка ног
//   direction   0…7 (W, NW, N, NE, E, SE, S, SW)
//   stance      "peace" | "combat"
//   pose        stand / walk / idle / run или действие
//   frame       номер кадра позы
//   palette     палитра тела: 0 — герой, иначе набор из data.bodies
//   equipment   { hand, off_hand, ranged } — ссылки конкретных экземпляров
//                 instance:<класс>:<источник>; старые class:<номер> читаются
import { world } from "./world.js";
import { drawSprite, spriteReady, context } from "./viewport.js";

// КЛЮЧ ГЛУБИНЫ ЮНИТА — НИЗ ЕГО ХОЛСТА.
//
//     ключ = юнит[+0x3A] + (юнит[+0x54] >> 16)      (VA 0x4267B8:84,93)
//
// Оба слагаемых прочитаны из живой памяти, и у человека со зверем они
// значат РАЗНОЕ (замер на восьми юнитах Борья, docs/RENDER_DEPTH.md):
//
//   человек — `+0x3A` лежит на 144 точки ВЫШЕ якоря ног (верхний угол
//     холста 256×150 с якорем (127, 144)), `+0x54` = 150. Итого ключ =
//     ноги − 144 + 150 = НОГИ ПЛЮС ШЕСТЬ;
//   тварь — `+0x3A` равен самому якорю, `+0x54` — высота её кадра (67…75 у
//     разных пород), а перед ключом движок добавляет ещё и смещение кадра
//     (VA 0x4267B8:85-88). Итого ключ = НИЗ ЕЁ КАДРА.
//
// Правило одно на обоих: ключ — нижний край того прямоугольника, которым
// юнит нарисован. Просто у человека этот прямоугольник фиксированный, а у
// твари свой на каждый кадр.
//
// ШЕСТЁРКУ ОТСЮДА УЖЕ УБИРАЛИ. Поле `+0x54` замерили на тварях, где
// `+0x3A` совпадает с якорем, и перенесли вывод на людей — ключ уехал на
// 144 точки вниз, и всякий, кто стоял ЗА домом, оказывался на крыше.
// Проверять такие поля надо на том виде юнита, о котором идёт речь.
//
// Владелец правила ОДИН — эта функция; ключ построек считает пак
// (konung2/world/geometry.py, `Bounds.sort_key`).
const HUMAN_CANVAS_BOTTOM = 6;

export function unitSortKey(actor) {
  const y = Math.round(actor.y);
  if (isBeast(actor)) {
    const frames = creatureFrames(actor);
    const frame = frames?.[Math.min(actor.frame ?? 0, frames.length - 1)];
    if (frame) return y + frame.offset_y + frame.height;
  }
  return y + HUMAN_CANVAS_BOTTOM;
}

// Ключ набора кадров тела: игра, форма и палитра. Игру юнит несёт в поле
// `game` (его кладёт выпечка карты), у канонных его нет.
export function bodyKey(actor) {
  const body = actor?.body ?? 0, palette = actor?.palette ?? 0;
  return actor?.game ? `${actor.game}:${body}:${palette}` : `${body}:${palette}`;
}

export function actorClassRef(ref, items = world.map?.items) {
  if (!ref || !items) return null;
  if (items[ref]) return ref;
  const match = /^instance:(\d+):/.exec(String(ref));
  if (match) {
    const classRef = `class:${match[1]}`;
    if (items[classRef]) return classRef;
  }
  // Старый pack мог использовать имя и как ссылку, и как ключ словаря.
  return Object.entries(items).find(([, item]) => item?.name === ref)?.[0] ?? null;
}

export function actorItem(ref, items = world.map?.items) {
  if (!ref || !items) return null;
  const classRef = actorClassRef(ref, items);
  return classRef ? items[classRef] ?? null : null;
}

export function actorItemName(ref, items = world.map?.items) {
  return actorItem(ref, items)?.name ?? ref ?? "";
}

let itemSerial = 0;

// Создание предмета runtime соответствует выделению новой записи предмета
// оригиналом. Класс механики зашит в ссылке, а хвост только различает записи.
export function actorNewItemRef(classRef, source = "runtime",
                                items = world.map?.items) {
  const item = actorItem(classRef, items);
  if (!item || !Number.isInteger(item.index)) return classRef ?? null;
  itemSerial += 1;
  const stamp = Date.now().toString(36);
  return `instance:${item.index}:${source}:${stamp}:${itemSerial.toString(36)}`;
}

// Некоторые канонические действия меняют байт класса В ТОЙ ЖЕ записи
// (пустая банка, результат смешивания), поэтому хвост идентичности остаётся.
export function actorReclassItemRef(ref, nextClassRef,
                                    items = world.map?.items) {
  const item = actorItem(nextClassRef, items);
  if (!item || !Number.isInteger(item.index)) return nextClassRef ?? ref ?? null;
  const match = /^instance:\d+:(.+)$/.exec(String(ref ?? ""));
  return match
    ? `instance:${item.index}:${match[1]}`
    : actorNewItemRef(nextClassRef, "reclass", items);
}

// Тварь рисуется не слоями, а СВОИМ набором кадров: движок берёт блок по
// байту unit+0xFC, а масть — по палитре unit+0x2E (VA 0x4267B8). Стоек у
// неё нет, только позы.
export function creatureFrames(actor, pose = actor.pose,
                               direction = actor.direction) {
  if (!isBeast(actor)) return null;
  // Тело 15 блиттер не рисует вовсе, если ему подняли бит «спрятан» или
  // если оно в одной из трёх особых поз (VA 0x425DC0).
  const vanishing = world.map?.hero?.rules?.creatures?.vanishing;
  if (vanishing && actor.body === vanishing.body) {
    if (actor.hidden) return null;
    if (vanishing.hidden_poses.includes(actor.poseBlock ?? -1)) return null;
  }
  // Наборы тварей лежат под .sets, а листы кадров — под .sheets: кадры
  // упакованы так же, как у героя (движок держит OBJECTS.RES одним куском).
  const sets = world.map?.creatures?.sets?.[String(actor.body)]
    ?.[String(actor.palette ?? 0)];
  if (!sets) return null;
  const named = sets[pose] ?? sets[pose === "walk" ? "walk" : "stand"] ?? sets.stand;
  return named?.[direction] ?? null;
}

//: Несёт ли набор именно эту позу. `creatureFrames` откатывается к `stand`,
//: и по нему нельзя спросить «а есть ли такая поза вообще» — а спрашивать
//: надо: разовое действие героя пускать без своих кадров бессмысленно.
export function actorPoseKnown(actor, pose) {
  const sets = world.map?.creatures?.sets?.[String(actor?.body)]
    ?.[String(actor?.palette ?? 0)];
  return Boolean(sets?.[pose]?.length);
}

export function isBeast(actor) {
  const bit = world.map?.hero?.rules?.creatures?.beast_bit ?? 0x40;
  return Boolean((actor?.breed ?? 0) & bit);
}

// ЛИСТЫ, БЕЗ КОТОРЫХ НЕ БУДЕТ ПЕРВОГО КАДРА.
//
// Кадры героя и юнитов лежат на листах, и раньше `heroSetup` ставил в
// очередь ВСЕ до единого, а загрузка их дожидалась: 72 листа, 121.6 МБ до
// первого кадра. На диске это незаметно, из сети — минуты белого экрана.
//
// Нужно же карте немного: сами кадры анимации весят 1.9 МБ на двух листах,
// а всё остальное — варианты тел (34 набора) и снаряжения (13), из которых
// на карте заняты единицы. По замеру: карта 1 — пять листов и 8.2 МБ,
// карта 19 — шесть и 10.4, карта 33 — семь и 12.3.
//
// Правило выбора здесь ПОВТОРЯЕТ отрисовку: тело берётся ключом
// «форма:палитра» с откатом на форму и на набор палитр, снаряжение — ключом
// «слой:палитра» с откатом на слой. Если правило в `actorBody`/`layerFrame`
// поменяется, поменять и здесь, иначе первый кадр останется без картинки.
function addSheetsOf(set, records, into) {
  if (!set?.frames) return;
  for (const record of records) {
    const frame = set.frames[record];
    if (frame?.sheet !== undefined) into.add(frame.sheet);
    if (frame?.shadow?.sheet !== undefined) into.add(frame.shadow.sheet);
  }
}

//: Записи кадров стойки — их рисует первый кадр в любом направлении.
function standRecords(data) {
  const out = new Set();
  for (const poses of Object.values(data?.animations ?? {})) {
    for (const directions of poses?.stand ?? []) {
      for (const frame of directions ?? []) out.add(String(frame.record));
    }
  }
  return out;
}

export function actorSheetPaths(data, actors) {
  const sheets = data?.sheets ?? [];
  if (!sheets.length) return [];
  const records = standRecords(data);
  const used = new Set();
  // Кадры самой анимации — общие для всех.
  for (const poses of Object.values(data?.animations ?? {})) {
    for (const directions of Object.values(poses ?? {})) {
      for (const frames of directions ?? []) {
        for (const frame of frames ?? []) {
          if (frame?.sheet !== undefined) used.add(frame.sheet);
          if (frame?.shadow?.sheet !== undefined) used.add(frame.shadow.sheet);
        }
      }
    }
  }
  for (const actor of actors ?? []) {
    if (!actor || isBeast(actor)) continue;      // у тварей свои листы
    const body = actor.body ?? 0, palette = actor.palette ?? 0;
    addSheetsOf(body
      ? (data.body_layers?.[bodyKey(actor)] ??
         data.body_layers?.[`${body}:${palette}`] ??
         data.body_layers?.[String(body)])
      : (palette ? data.bodies?.[String(palette)] : null), records, used);
    for (const reference of Object.values(actor.equipment ?? {})) {
      const item = reference ? actorItem(reference) : null;
      if (!item?.layer) continue;
      addSheetsOf(data.equipment?.[`${item.layer}:${item.palette}`] ??
                  data.equipment?.[String(item.layer)], records, used);
    }
  }
  return [...used].map((index) => sheets[index]?.path).filter(Boolean);
}


export function actorFrames(data, actor, pose = actor.pose,
                            direction = actor.direction) {
  const beast = creatureFrames(actor, pose, direction);
  if (beast) return beast;
  const sets = data?.animations;
  // Действия общие для обеих стоек: пары у них в таблицах движка нет.
  return sets?.[actor.stance]?.[pose]?.[direction] ??
    sets?.actions?.[pose]?.[direction] ?? null;
}

export function actorFrame(data, actor) {
  const frames = actorFrames(data, actor);
  if (!frames?.length) return null;
  return frames[Math.min(actor.frame, frames.length - 1)] ?? null;
}

// Активное оружие: во время выстрела в руке лук или самострел, иначе то, что
// в основной руке — один и тот же шаг отрисовки берёт либо unit+0x58, либо
// unit+0x5A (VA 0x4261D8 против 0x426291). Чем биться, когда надето и то и
// другое, решает байт unit+0xEE (VA 0x420704): у нас это actor.rangedMode.
export function actorWeapon(actor) {
  const shooting = actor.pose === "shoot_bow" || actor.pose === "shoot_crossbow";
  const ranged = actorItem(actor.equipment?.ranged);
  if ((shooting || actor.rangedMode) && ranged) return ranged;
  return actorItem(actor.equipment?.hand) ?? ranged;
}

// Дальность боя — поле +0x10 класса ТОГО ЖЕ предмета, которым бьёмся:
// проверка выстрела читает его из класса предмета метательного гнезда
// (VA 0x414AF8: `*(int *)(&DAT_0045dafe + ... (*(int *)(param_1 + 0x58) >>
// 0x10) ...) >> 0x10`), а в ближнем бою достаёт оружие руки.
//
// Считать надо КАЖДЫЙ РАЗ, а не замораживать полем при спавне: режим оружия
// (unit+0xEE) меняется на ходу. У спутника-лучника замороженная дальность
// бралась из пустой руки и давала единицу, а гейт выстрела требует не ближе
// трёх клеток — вместе это не выполнимо, и лучник не мог атаковать вообще.
export function actorReach(actor) {
  return Math.max(1, actorWeapon(actor)?.range_cells || 1);
}

// Какую анимацию удара играть (ближний бой VA 0x416B50, стрельба 0x416AC8).
//
// Двуручное решается слоем, а вот одноручное — НЕ просто «занята ли вторая
// рука». Сначала движок смотрит навык «Бой двумя руками» (unit+0xD3): если
// он нулевой, всегда играется удар со щитом, даже когда левая рука пуста.
// И только при ненулевом навыке он смотрит, ЧТО в левой руке: пусто или
// второе оружие (вид записи 0) — удар одной рукой, щит — удар со щитом.
// ДВЕ ФУНКЦИИ ДВИЖКА, А НЕ ОДНА. Ближний замах ставит `FUN_00416B50`
// (позы 5, 8, 9 по руке и щиту), выстрел — `FUN_00416AC8` (4 или 10), и
// вторую движок зовёт ТОЛЬКО после проверки цели (0x414AF8). У нас они
// сведены сюда, и обычно это верно: в бою «стрелять или бить» решено
// раньше, полем `rangedMode`.
//
// Но тренировке у казармы цели нет вовсе — там зовётся ровно 0x416B50, —
// и лучник с пустой рукой вставал стрелять в напарника вместо того,
// чтобы махать. Для таких мест зовите с `melee`.
export function actorAttackPose(data, actor, { melee = false } = {}) {
  const rules = data?.rules?.attack_by_item;
  const hand = actor.rangedMode ? null : actorItem(actor.equipment?.hand);
  const ranged = actorItem(actor.equipment?.ranged);
  if (!melee && !hand && ranged) {
    return ranged.layer === rules?.crossbow_group
      ? rules.ranged.crossbow : rules?.ranged?.other ?? "shoot_bow";
  }
  if (hand && hand.layer >= (rules?.two_hand_from_group ?? 13)) {
    return rules.melee.two_hand;
  }
  const shieldPose = rules?.melee?.second_hand_busy ?? "attack_shield";
  const onePose = rules?.melee?.second_hand_free ?? "attack_one_hand";
  const skill = actor === undefined ? 0 : (actor.skills?.[rules?.melee?.skill ?? 1] ?? 0);
  if (!skill) return shieldPose;
  const off = actorItem(actor.equipment?.off_hand);
  if (!off || (off.kind ?? 0) === 0) return onePose;
  return shieldPose;
}

// ПАЛИТРА У СЛОЯ БЕРЁТСЯ ИЗ ПРЕДМЕТА. Движок переставляет её перед каждым
// слоем и читает из записи класса — `[0x8A7318] = [0x45DB0C + вид*0x20]`
// (VA 0x425DB4), а не из юнита. Один слой делят предметы разных цветов:
// слой 23 — кожаные доспехи (палитра 3) и ДОСПЕХ ВОИНА ПОВЕЛИТЕЛЯ (9),
// слой 28 — длинные щиты (7) и щит воина Повелителя (6). Пока набор кадров
// был один на слой, чёрную броню красило палитрой кожанки.
//
// Ключ «слой:палитра» кладёт сборщик; ключ без палитры остался как запасной,
// чтобы паки, собранные раньше, продолжали работать.
function layerFrame(data, layer, record, palette = null) {
  if (layer == null) return null;
  const sets = data?.equipment;
  if (!sets) return null;
  const exact = palette == null ? null : sets[`${layer}:${palette}`];
  const set = exact ?? sets[String(layer)];
  return set?.frames?.[String(record)] ?? null;
}

// У оружия два слоя: рабочий (нечётный) и «в покое» (чётный сосед). Кадры
// мирной стойки несут только чётные, кадры ударов — только нечётные, поэтому
// слой выбирает состояние оружия, а не наш вкус.
// У ОРУЖИЯ ПАЛИТРА ЗАШИТА ЧИСЛОМ. Движок не спрашивает запись предмета, а
// кладёт `[0x8A7318] = 0x400` (VA 0x425DB4) — это байтовое смещение, палитра
// с индексом 0x400 / 512 = 2. Доспеху, шлему и щиту палитра достаётся из их
// записи, оружию — никогда.
const WEAPON_PALETTE = 2;

function weaponLayerFrame(data, item, record, active) {
  if (!item) return null;
  const at = (layer) => layerFrame(data, layer, record, WEAPON_PALETTE);
  return at(active ? item.layer : item.rest_layer ?? item.layer) ??
    at(active ? item.rest_layer : item.layer);
}

function weaponActive(data, actor) {
  return actor.stance === "combat" ||
    Boolean(data?.animations?.actions?.[actor.pose]);
}

// Условия шагов сценария — те же, что в движке: «в руке» рисуется только с
// достанным оружием и в своём режиме, «убрано» — во всех прочих случаях.
function stepAllowed(when, { armed, shooting }) {
  switch (when) {
    case "in_hand": return armed && !shooting;      // щит в руке
    case "melee": return armed && !shooting;        // оружие ближнего боя
    case "shooting": return armed && shooting;      // лук в руках
    case "not_shooting": return !(armed && shooting);
    case "at_rest": return !armed || shooting;      // убранное
    default: return true;
  }
}

// Слои снаряжения для кадра — сценарий отрисовки движка (VA 0x425DB4).
// Порядок там ровно такой: тело, доспех, затем пять шагов своего
// направления из таблицы 0x4627D0. За телом не рисуется ничего: у кадров
// каждое направление своё, и порядок сценария разводит только само
// снаряжение — со спины щит в руке уходит под оружие, а щит за спиной
// ложится последним, лицом к зрителю наоборот.
export function actorLayers(data, actor, record) {
  const behind = [];
  const front = [];
  if (record == null || !data?.equipment) return { behind, front };
  const rules = data.rules?.equipment_draw;
  const script = rules?.script?.[actor.direction] ?? null;
  const state = {
    armed: weaponActive(data, actor),
    shooting: Boolean(actor.rangedMode) || actor.pose === "shoot_bow" ||
      actor.pose === "shoot_crossbow",
  };

  const push = (target, step) => {
    const item = actorItem(actor.equipment?.[step.slot]);
    if (!item) return;
    if (step.kind !== undefined && item.kind !== step.kind) return;
    if (step.not_kind !== undefined && item.kind === step.not_kind) return;
    if (!stepAllowed(step.when, state)) return;
    const found = layerFrame(data, item.layer + (step.offset ?? 0), record,
                             item.palette);
    if (found) target.push(found);
  };

  if (!script) {
    // без правил в паке — хотя бы оружие и щит, как раньше
    const weapon = actorWeapon(actor);
    const found = weaponLayerFrame(data, weapon, record, state.armed);
    if (found) front.push(found);
    return { behind, front };
  }

  // доспех кладётся сразу за телом, до сценария
  for (const step of rules.before ?? []) {
    if (step.step === "layer") push(front, step);
  }
  for (const code of script) {
    for (const step of rules.steps?.[String(code)] ?? []) push(front, step);
  }
  return { behind, front };
}

// Тело в палитре актёра: у героя это сам кадр, у крашеного юнита — тот же
// кадр из набора bodies (движок подставляет палитру перед блиттером).
export function actorBody(data, actor, frame) {
  if (!frame) return null;
  // ФОРМА И ПАЛИТРА НЕЗАВИСИМЫ. Байт unit+0xFC выбирает СЛОЙ записи
  // (0x30 + число) — женская фигура, монах, воин (VA 0x424200), а палитра
  // юнита ставится ПЕРЕД отрисовкой этого слоя (VA 0x425DB4):
  //     [0x8A7318] = юнит+0x2E;  слой = 0x30 + форма;  рисуем(юнит, слой);
  // То есть палитра не «слабее» формы, она красит её.
  //
  // Раньше здесь стояло «или форма, или палитра», и при заданной форме до
  // палитры дело не доходило вовсе. Из шести стартовых героев форму имеют
  // пятеро — все они выходили в базовой раскраске, отсюда «одинаковый
  // болванчик» у Велиславны, Эйнара, Хельги, Александра и Анастасии.
  //
  // Кадр твари уже пришёл из её набора — подменять нечем.
  if (isBeast(actor)) return frame;
  if (actor.body) {
    const sets = data?.body_layers ?? {};
    // Сперва форма СВОЕЙ ИГРЫ в своей палитре, затем общий ключ, и лишь
    // потом форма как есть. Игра в ключе нужна потому, что из 256 палитр
    // у двух игр совпадают 218, а форм у «Продолжения легенды» больше:
    // без этого его жители выходили красными с шумом, а Иззарк — чёрным.
    const shaped = (actor.palette
      ? (sets[bodyKey(actor)]?.frames?.[String(frame.record)]
         ?? sets[`${actor.body}:${actor.palette}`]?.frames?.[String(frame.record)])
      : null) ?? sets[String(actor.body)]?.frames?.[String(frame.record)];
    // Своё тело приезжает фоном, как и крашеные кадры: пока картинки нет,
    // юнит должен стоять базовым телом, а не пропадать совсем.
    if (spriteReady(world.images, heroSheets(), shaped)) {
      return { ...frame, ...shaped, record: frame.record };
    }
  }
  if (!actor.palette) return frame;
  const painted = data?.bodies?.[String(actor.palette)]?.frames?.[String(frame.record)];
  // Крашеные кадры приезжают фоном, и пока их нет, юнит должен остаться на
  // месте, а не мигать: показываем то же тело базовой палитрой.
  //
  // ПОДМЕНЯЕТСЯ ТОЛЬКО КАРТИНКА, ОСТАЛЬНОЕ БЕРЁТСЯ У БАЗОВОГО КАДРА. В паке у
  // крашеного кадра лежит одна геометрия — лист и прямоугольник; ни номера
  // записи, ни тени в нём нет, они есть только у базового. Возвращая
  // `painted` голым, мы теряли и то и другое: `actorLayers` без `record`
  // отдаёт пустые списки, а отрисовщик без `shadow` не рисует тень.
  //
  // Видно это было на ОДНОМ Ратиборе, и не случайно: своя форма тела есть у
  // пятерых стартовых героев, они уходят веткой выше, где базовый кадр
  // сохраняется. У Ратибора форма нулевая — он единственный, кто доходил
  // сюда, и потому единственный ходил без снаряжения и без тени.
  return spriteReady(world.images, heroSheets(), painted)
    ? { ...frame, ...painted, record: frame.record }
    : frame;
}

//: Листы кадров героя — общая «арена» пака (см. viewport.drawSprite).
export function heroSheets() { return world.map?.hero?.sheets ?? null; }

//: Листы кадров тварей — своя «арена», отдельная от геройской.
// ЛИСТЫ ТВАРЕЙ, КОТОРЫЕ ЕСТЬ НА ЭТОЙ КАРТЕ.
//
// Скопом их тянуть нельзя — 83 листа на 43.4 МБ, — а лениво, по первому
// обращению, тварь проявляется уже ПОСЛЕ того, как экран загрузки погас:
// игрок входит в локацию и видит, как из пустоты возникают волки. Поэтому
// берём ровно те наборы, что нужны стоящим тут породам: их горстка.
export function creatureSheetPaths(actors) {
  const sets = world.map?.creatures?.sets;
  const sheets = world.map?.creatures?.sheets ?? [];
  if (!sets || !sheets.length) return [];
  const used = new Set();
  for (const actor of actors ?? []) {
    if (!actor || !isBeast(actor)) continue;
    const own = sets[String(actor.body)]?.[String(actor.palette ?? 0)];
    if (!own) continue;
    for (const poses of Object.values(own)) {
      for (const directions of Object.values(poses ?? {})) {
        for (const frame of directions ?? []) {
          if (frame?.sheet !== undefined) used.add(frame.sheet);
          if (frame?.shadow?.sheet !== undefined) used.add(frame.shadow.sheet);
        }
      }
    }
  }
  return [...used].map((index) => sheets[index]?.path).filter(Boolean);
}

export function creatureSheets() { return world.map?.creatures?.sheets ?? null; }

//: Чьи листы у этого юнита: у твари свой набор из OBJECTS.RES, у человека
//: — кадры HEROES.RES. В движке это тоже разные ресурсы.
export function sheetsFor(actor) {
  return isBeast(actor) ? creatureSheets() : heroSheets();
}

export function drawLayerFrame(frame, baseX, baseY, sheets = null) {
  if (!frame) return;
  const set = sheets ?? heroSheets();
  // ЛИСТ СЛОЯ ЗАКАЗЫВАЕТСЯ ТАК ЖЕ, КАК ЛИСТ ТЕЛА.
  //
  // Листы тянутся по требованию, и заказывает их РОВНО ОДНО место —
  // `spriteReady` (viewport.js). Слои снаряжения шли мимо неё, прямо в
  // `drawSprite`, а тот на отсутствующей картинке молча возвращает false и
  // никого ни о чём не просит. Поэтому оружие и щиты, чьи листы не попали в
  // предзагрузку карты, не появлялись НИКОГДА — сколько ни смотри.
  //
  // Замер на Ратиборе в Борье: из четырёх слоёв кадра два листа были на
  // месте (82 доспех, 107 шлем), а два — нет (64 топор, 104 щит), и рендер
  // их не заказывал ни через секунду, ни через десять.
  if (!spriteReady(world.images, set, frame)) return;
  drawSprite(world.images, set, frame,
             baseX + frame.offset_x, baseY + frame.offset_y);
}

// Нарисовать актёра целиком: снаряжение за телом, тело, снаряжение поверх.
// Возвращает false, если кадр или картинка ещё не приехали.
export function drawActor(data, actor, { alpha = 1, silhouette = false } = {}) {
  const frame = actorFrame(data, actor);
  const body = actorBody(data, actor, frame);
  const sheets = sheetsFor(actor);
  if (!spriteReady(world.images, sheets, body)) return false;
  const baseX = Math.round(actor.x);
  const baseY = Math.round(actor.y);
  // У твари слоёв нет: движок рисует её одним кадром целиком.
  const { behind, front } = isBeast(actor)
    ? { behind: [], front: [] }
    : actorLayers(data, actor, frame.record);
  context.globalAlpha = alpha;
  if (silhouette) {
    // вырезаем силуэт целиком, вместе с оружием
    for (const layer of [...behind, ...front]) drawLayerFrame(layer, baseX, baseY);
    drawLayerFrame(body, baseX, baseY, sheets);
  } else {
    for (const layer of behind) drawLayerFrame(layer, baseX, baseY);
    drawLayerFrame(body, baseX, baseY, sheets);
    for (const layer of front) drawLayerFrame(layer, baseX, baseY);
  }
  context.globalAlpha = 1;
  return true;
}
