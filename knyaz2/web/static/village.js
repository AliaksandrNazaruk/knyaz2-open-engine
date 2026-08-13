// Хозяйство деревни: казна владения и мастерская.
//
// КАЗНА (VA 0x41D530…0x41D745, формула снята дизасмом). Раз в 0x2760
// единиц игрового времени и только при СНЯТОМ бите 0x10 во flags в казну
// владения капает доход — это поле +0x10 записи поселения, по ненулевости
// которого обработчик 27 отвечает «деревня чья-то» (VA 0x435438):
//
//     round(богатство · 50 · sqrt(навык «Управление деревней» ГЕРОЯ)
//           + жители · 10 + 1)
//
// порезанный делителем сетки «статус × байт-владелец» (усечение к нулю):
// статус 0 — /4 /2 /1, статус 1 — /8 /4 /2, статус 2 — /16 /8 /4.
//
// МАСТЕРСКАЯ (VA 0x417BD8, мировой такт зовёт её раз за тик). Мастер —
// юнит из +0x3D6, куёт по навыку «Кузнечное дело»: 39 видов — стрелы
// (классы 202…204), болты (206…207) и снаряжение культуры старейшины
// (класс = культура·34 + 100 + вид − 5). Порог доступности вида и
// прочность откованного — durability его класса; свободный вид с порогом
// не выше навыка берётся в заказ на срок
//
//     round(порог · 60 / sqrt(навык/10 + 1))          (fsqrt 0x442C6C)
//
// готовое лежит в запасе вида, после отковки мастер растёт: навык =
// round(sqrt(порог·2 + навык² + 10)), кап 100. Когда всё доступное
// отковано — раздача жителям жребием rand % 8 не меньше порога сетки
// статусов, и только пока на карте нет живого отряда события (0x435214):
// стрелы кладутся в пустой боеприпас стрелка, снаряжение — в слот вида,
// если тот пуст или защита класса хуже (старая вещь пропадает); требования
// проверяет 0x418648. Один предмет за такт, как и в движке.
import { world } from "./world.js";
import { hero } from "./hero.js";
import { units } from "./units.js";
import { actorItem, actorNewItemRef } from "./actor.js";
import { daylight } from "./daylight.js";
import { clockPhaseHits } from "./clock.js";
import { SLOTS, requirementMet } from "./inventory.js";
import { levelThreshold, raiseCharacteristic, raiseSkill } from "./progress.js";
import { roundHalfEven } from "./round.js";

export const village = {
  data: null,        // блок поселения из пака (map.village)
  incomeStamp: 0,    // метка последней выплаты (+0x14)
  order: -1,         // какой вид куётся (+0x49F), -1 — никакой
  timer: 0,          // тиков до готовности (+0x08)
  stock: {},         // запасы по видам (+0x44E): вид -> имя готовой вещи
  trainTimer: 0,     // тактов деревни до занятия у воеводы (+0x0C)
  lastTime: null,    // прошлое игровое время — для счёта тиков
};

function treasuryRules() {
  return world.map?.hero?.rules?.buildings?.treasury ?? null;
}

function workshopRules() {
  return world.map?.hero?.rules?.buildings?.workshop ?? null;
}

// СКЛАД ПОСЕЛЕНИЙ — на всю игру, а не на один вход.
//
// В движке массив поселений 0x83D408 (12 записей по 0x4A1) читается ОДИН РАЗ:
// при новой игре (0x43D898) или из сейва (0x4236E0) — и целиком пишется в сейв
// (0x423CB8). Вход на карту его НЕ перезагружает: 0x43DF48 лишь находит запись
// своей карты (байт +3 равен номеру карты) и по ней переставляет картинки
// объектов. У нас карта читается из пака при КАЖДОМ входе, и вместе с ней
// возвращалась нетронутая деревня — отсюда «в Борье пропали постройки и мой
// чувак, которого я оставил воеводой» в отчёте тестера.
const settlements = new Map();     // номер карты -> запись поселения и хозяйство
let current = null;                // чьё поселение сейчас живое

function mapNumber(map) {
  const number = Number(map?.legacy?.map_number);
  return Number.isFinite(number) ? number : null;
}

export function villageSetup(map) {
  const number = mapNumber(map);
  current = number;
  const kept = number === null ? null : settlements.get(number);
  if (kept) {
    //: Вернулись на свою карту — берём СВОЮ запись, а копию из пака
    //: отставляем. Подменяем и `map.village`: на неё смотрят разговоры,
    //: торговля и постройки через `world.map.village`.
    if (map) map.village = kept.data;
    Object.assign(village, kept);
    return;
  }
  village.data = map?.village ?? null;
  village.incomeStamp = daylight.time ?? 0;
  village.order = -1;
  village.timer = 0;
  village.trainTimer = 0;
  village.stock = {};
  village.lastTime = null;
  if (number === null || !village.data) return;
  const entry = { ...village };
  settlements.set(number, entry);
  //: ПЕРВЫЙ ВИЗИТ ПОСЛЕ ЗАГРУЗКИ. Сохранение помнит деревни, куда игрок уже
  //: заходил, но их записи приезжают из пака только сейчас — вот и время
  //: наложить сохранённое. Без этого сейв восстанавливал лишь ту деревню,
  //: которая была загружена в память в миг загрузки.
  if (villageApply(number, entry)) Object.assign(village, entry);
}

// Уходим с карты — дописать в склад то, что изменилось за визит. Сама запись
// поселения (`data`) общая по ссылке и правится на месте, а хозяйство
// мастерской и метки живут полями, их надо переложить.
export function villageCapture() {
  if (current === null || !settlements.has(current)) return false;
  settlements.set(current, { ...village });
  return true;
}

// Всё, что игра изменила в поселениях, — для сейва. Движок пишет блок целиком
// (0x423CB8), мы пишем поля, которые вообще меняются.
export function villagePack() {
  villageCapture();
  return [...settlements.entries()].map(([map, kept]) => ({
    map,
    flags: kept.data?.flags ?? 0,
    status: kept.data?.status ?? 0,
    owner: kept.data?.owner ?? 0,
    owned: kept.data?.owned ?? 0,
    treasury: kept.data?.treasury ?? 0,
    officials: [...(kept.data?.officials ?? [])],
    squadPeople: kept.data?.squad_people ?? 0,
    // ПРИЛАВКИ — поля той же записи (`+0x3E0`, `+0x40E`, `+0x44E`), поэтому
    // и в сохранение они едут вместе с ней. Ключ — роль торговца, значение —
    // места и подробности выложенного (shops.js).
    counters: kept.data?.counters
      ? JSON.parse(JSON.stringify(kept.data.counters)) : null,
    // Ступень и счётчик каждого МЕСТА — это и есть стройка.
    places: (kept.data?.buildings ?? []).map((place) => ({
      slot: place.slot, state: place.state ?? 0,
      timer: place.timer ?? 0, built: Boolean(place.built),
    })),
    incomeStamp: kept.incomeStamp ?? 0,
    order: kept.order ?? -1,
    timer: kept.timer ?? 0,
    trainTimer: kept.trainTimer ?? 0,
    stock: { ...(kept.stock ?? {}) },
    lastTime: kept.lastTime ?? null,
  }));
}

// Обратно в склад. Записи поселений сами приедут из пака при первом входе на
// карту, поэтому здесь держим отложенные правки и накладываем их тогда же.
const pending = new Map();

// НОВАЯ ИГРА чистит склад целиком: в движке блок поселений перечитывается из
// GAME.x (0x43D898), то есть от прошлой партии не остаётся ничего.
export function villageReset() {
  settlements.clear();
  pending.clear();
  current = null;
}

export function villageUnpack(list) {
  pending.clear();
  for (const entry of list ?? []) {
    const number = Number(entry?.map);
    if (Number.isFinite(number)) pending.set(number, entry);
  }
  //: Загрузка заменяет ВЕСЬ блок поселений (0x4236E0 читает 0x378C байт), так
  //: что записи чужой партии в складе оставаться не должны.
  if (pending.size) {
    for (const number of [...settlements.keys()]) {
      if (!pending.has(number)) settlements.delete(number);
    }
  }
  //: Уже загруженные записи правим сразу — на текущей карте пак уже прочитан.
  for (const [number, kept] of settlements) villageApply(number, kept);
  if (current !== null) {
    const kept = settlements.get(current);
    if (kept) Object.assign(village, kept);
  }
}

function villageApply(number, kept) {
  const saved = pending.get(number);
  if (!saved || !kept?.data) return false;
  const data = kept.data;
  data.flags = saved.flags ?? data.flags ?? 0;
  data.status = saved.status ?? data.status ?? 0;
  data.owner = saved.owner ?? data.owner ?? 0;
  data.owned = saved.owned ?? data.owned ?? 0;
  data.treasury = saved.treasury ?? data.treasury ?? 0;
  if (Array.isArray(saved.officials)) data.officials = [...saved.officials];
  if (Number.isFinite(saved.squadPeople)) data.squad_people = saved.squadPeople;
  // ПРИЛАВКИ НАКЛАДЫВАЕМ В СУЩЕСТВУЮЩИЕ СПИСКИ, а не подменяем объект: на
  // список мест торговцу выдана ССЫЛКА (shops.js), и подмена оставила бы его
  // с отвязанной копией — покупка правила бы её, а поселение хранило старое.
  for (const [role, box] of Object.entries(saved.counters ?? {})) {
    data.counters = data.counters ?? {};
    const live = data.counters[role] ??
      (data.counters[role] = { slots: [], details: {} });
    live.slots = live.slots ?? [];
    live.slots.length = 0;
    live.slots.push(...(box?.slots ?? []));
    live.details = { ...(box?.details ?? {}) };
  }
  for (const place of saved.places ?? []) {
    const found = (data.buildings ?? []).find((row) => row.slot === place.slot);
    if (!found) continue;
    found.state = place.state ?? 0;
    found.timer = place.timer ?? 0;
    found.built = Boolean(place.built);
  }
  kept.incomeStamp = saved.incomeStamp ?? kept.incomeStamp ?? 0;
  kept.order = saved.order ?? -1;
  kept.timer = saved.timer ?? 0;
  kept.trainTimer = saved.trainTimer ?? 0;
  kept.stock = { ...(saved.stock ?? {}) };
  kept.lastTime = saved.lastTime ?? null;
  return true;
}

//: Игровое время суточное (0…21599), поэтому и разница, и сравнение с
//: периодом идут по модулю — движок берёт |время − метка| (0x442B7E).
function timeGap(now, then) {
  const day = 21600;
  const raw = Math.abs(now - then);
  return Math.min(raw, day - raw);
}

// Житель деревни — юнит той же стороны, что и её люди.
function villageSide() {
  const first = (village.data?.people ?? [])[0];
  const official = units.find((unit) => unit.slot === first);
  return official?.side;
}

function villagePeople(side) {
  if (side === undefined) return 0;
  return units.filter((unit) => unit.alive && unit.side === side).length;
}

// Есть ли на карте живой отряд события: при нём раздача товара стоит
// (VA 0x417BD8 зовёт 0x435214 — ту же проверку, что обработчик 23).
function eventAlive() {
  return (world.map?.events ?? []).some((event) => {
    if (!event.active) return false;
    return (event.members ?? []).some((member) =>
      !(member.flags & 0x80) && ![3, 0x0B, 0x0C].includes(member.type ?? 0));
  });
}

const roll = (limit) => Math.floor(Math.random() * limit);

//: Класс продукции вида: 0…4 — боеприпас, дальше снаряжение культуры.
function goodClass(index, shop) {
  const ammo = shop.ammo_classes ?? [202, 203, 204, 206, 207];
  if (index < ammo.length) return ammo[index];
  return (shop.culture_base ?? 100) +
    (village.data?.culture ?? 0) * (shop.culture_step ?? 34) +
    index - (shop.gear_shift ?? 5);
}

function nameOfClass(number) {
  const items = world.map?.items ?? {};
  for (const [name, item] of Object.entries(items)) {
    if (item.index === number) return name;
  }
  return null;
}

// Навык мастера. Мастер — обычный житель: его навык растёт прямо в юните.
function master() {
  const number = village.data?.master;
  if (!number) return null;
  return units.find((unit) => unit.slot === number && unit.alive) ?? null;
}

function smithSkill(unit) {
  const names = world.map?.hero?.rules?.progression?.skills?.names ?? [];
  const index = names.indexOf("Кузнечное дело");
  return index >= 0 ? unit.skills?.[index] ?? 0 : 0;
}

function setSmithSkill(unit, value) {
  const names = world.map?.hero?.rules?.progression?.skills?.names ?? [];
  const index = names.indexOf("Кузнечное дело");
  if (index >= 0 && unit.skills) unit.skills[index] = value;
}

// Недельный доход казны владения.
function treasuryTick(now) {
  const set = treasuryRules();
  const data = village.data;
  if (!set || !data) return false;
  if ((data.flags ?? 0) & (set.block_bit ?? 0x10)) return false;
  if (timeGap(now, village.incomeStamp) <= (set.period ?? 0x2760) - 1) {
    return false;
  }
  const names = world.map?.hero?.rules?.progression?.skills?.names ?? [];
  const index = names.indexOf("Управление деревней");
  const skill = index >= 0 ? hero.skills?.[index] ?? 0 : 0;
  let income = roundHalfEven(
    (data.wealth ?? 0) * (set.wealth_scale ?? 50) * Math.sqrt(skill) +
    villagePeople(villageSide()) * (set.per_person ?? 10) + 1);
  const row = (set.dividers ?? [])[Math.min(data.status ?? 0, 2)] ?? [1, 1, 1];
  income = Math.trunc(income / (row[Math.min(data.owner ?? 0, 2)] ?? 1));
  data.owned = (data.owned ?? 0) + income;
  village.incomeStamp = now;
  return true;
}

//: Срок ПЕРВОГО заказа (0x417CF9): round(нужда·60 / sqrt(навык/10 + 1)) —
//: единица стоит ПОД корнем, ноль в корне невозможен.
function orderTicks(need, skillTenth, shop) {
  const root = Math.sqrt(skillTenth);
  if (!root) return 0;
  return roundHalfEven(need * (shop.minute ?? 60) / root);
}

//: Срок ПЕРЕЗАКАЗА после выдачи (0x417F22 и 0x41800A): формула ДРУГАЯ —
//: round(нужда·60 / (sqrt(навык/10) + 1)): единица прибавляется ПОСЛЕ
//: корня, нужда — та же прочность класса (0x45DAF8 = база классов + 8).
function reorderTicks(need, skill, shop) {
  const root = Math.sqrt(Math.trunc(skill / (shop.skill_divisor ?? 10))) + 1;
  return roundHalfEven(need * (shop.minute ?? 60) / root);
}

// Выбрать мастеру новый заказ. Возвращает, вышло ли.
function takeOrder(smith, shop) {
  const skill = smithSkill(smith);
  for (let index = 0; index < (shop.goods ?? 39); index += 1) {
    if (village.stock[index]) continue;
    const name = nameOfClass(goodClass(index, shop));
    const need = actorItem(name)?.durability ?? Infinity;
    if (need > skill) continue;
    village.order = index;
    village.timer = orderTicks(
      need, Math.trunc(skill / (shop.skill_divisor ?? 10)) + 1, shop);
    return true;
  }
  return false;
}

// Раздать один готовый предмет жителю. Возвращает, вышло ли.
function giveGoods(shop) {
  const data = village.data;
  const thresholds = (data.status ?? 0) === 1
    ? (shop.give_thresholds?.["1"] ?? [7, 6, 4])
    : (shop.give_thresholds?.other ?? [6, 4, 0]);
  const bar = thresholds[Math.min(data.owner ?? 0, 2)] ?? 0;
  if (roll(shop.give_die ?? 8) < bar) return false;
  const side = villageSide();
  const ammoKinds = (shop.ammo_classes ?? []).length;
  for (const [key, name] of Object.entries(village.stock)) {
    if (!name) continue;
    const index = Number(key);
    const item = actorItem(name);
    if (!item) continue;
    for (const unit of units) {
      if (!unit.alive || unit.side !== side) continue;
      // зверям мастерская не раздаёт (0x417BD8: бит 0x40 породы)
      if (unit.beast) continue;
      if (index < ammoKinds && !unit.equipment?.ranged) continue;
      if (!requirementMet(name, unit)) continue;
      if (index < ammoKinds) {
        if (unit.equipment.ammo) continue;
        unit.equipment.ammo = name;
      } else {
        const slot = SLOTS[item.kind ?? 0];
        if (!slot || !(slot in (unit.equipment ?? {}))) continue;
        const worn = actorItem(unit.equipment[slot]);
        if (worn && (worn.power ?? 0) >= (item.power ?? 0)) continue;
        // старая вещь пропадает: движок помечает её запись пустой
        unit.equipment[slot] = name;
      }
      village.stock[index] = null;
      // Выдав, движок ТУТ ЖЕ куёт то же самое снова (0x417EFF/0x418...):
      // сток обнулён, заказ — этот же товар, срок — формулой перезаказа.
      village.order = index;
      village.timer = reorderTicks(item.durability ?? 0,
                                   smithSkill(master() ?? {}), shop);
      return true;
    }
  }
  return false;
}

// Мастерская: один канонный такт. `фазы` — сколько раз за этот кадр сошлась
// ФАЗА ПОСТРОЕК; таймер заказа убывает ровно на единицу за фазу.
function workshopTick(phases) {
  const shop = workshopRules();
  const data = village.data;
  if (!shop || !data) return false;
  const smith = master();
  if (!smith) return false;
  if (village.order < 0) {
    if (takeOrder(smith, shop)) return false;
    // всё доступное отковано — раздача, но не при живом отряде события
    if (!eventAlive()) return giveGoods(shop);
    return false;
  }
  // Канон: `*(int *)(param_1 + 8) = *(int *)(param_1 + 8) + -1` (VA
  // 0x417BD8:138) — минус ЕДИНИЦА за вызов, а единственный вызывающий это
  // фаза построек мирового такта (VA 0x41C944:510, ветка `+7 & 0xF`).
  // Раньше вычиталась разница игрового времени, и заказ поспевал в 16 раз
  // быстрее канона.
  if (!phases) return false;
  village.timer -= phases;
  if (village.timer > 0) return false;
  const classRef = nameOfClass(goodClass(village.order, shop));
  const name = classRef ? actorNewItemRef(classRef, "workshop") : null;
  if (name) {
    village.stock[village.order] = name;
    const need = actorItem(name)?.durability ?? 0;
    const skill = smithSkill(smith);
    // рост мастера: sqrt-формула хвоста 0x417BD8, кап 100
    setSmithSkill(smith, Math.min(100,
      roundHalfEven(Math.sqrt(need * 2 + skill * skill + 10))));
  }
  village.order = -1;
  village.timer = 0;
  return Boolean(name);
}

// Такт хозяйства: зовётся из мирового цикла. Возвращает, поменялось ли
// что-нибудь заметное.
export function villageTick() {
  if (!village.data) return false;
  const now = daylight.time ?? 0;
  if (village.lastTime === null) village.lastTime = now;
  // Фаза построек движка: `(_DAT_0084962c + 7 & 0xf) == 0` (VA 0x41C944:356).
  // Мастерская висит на ней, казна — на метке времени, поэтому считаем их
  // отдельно и НЕ выходим раньше времени по «время не сдвинулось».
  const phases = clockPhaseHits(0xF, 7);
  const ticks = Math.round(timeGap(now, village.lastTime));
  if (ticks < 1 && !phases) return false;
  if (ticks >= 1) village.lastTime = now;
  let changed = false;
  if (treasuryTick(now)) changed = true;
  if (workshopTick(phases)) changed = true;
  return changed;
}

// ОБУЧЕНИЕ У ВОЕВОДЫ (VA 0x4181E8) — то, чего тестер не нашёл в казарме.
//
// Спарринга здесь нет вовсе. Движок раз в 1200 тактов деревни проходит по
// бойцам её отряда и даёт каждому, чей уровень не выше уровня воеводы, СТО
// опыта; дошедшему до порога — уровень, 25 свободных очков и ДВЕ попытки
// роста: Выносливость, Сила, Ловкость и одиннадцать навыков. Такт деревни
// идёт раз в шестнадцать мировых, значит занятие случается раз в 19200
// тактов — это около игровых суток.
//
// Условий два, и оба нежданные:
//
//   * должность ВОЕВОДЫ занята — слово поселения +0x3D8, место 4. Пусто —
//     функция выходит первой строкой, и казарма стоит без толку;
//   * в этот же такт деревня НИЧЕГО не заложила и не сменила ступень
//     (0x41C944:513 зовёт обучение только при нулевом флаге стройки).
//
// Счётчик занятий лежит в поселении по +0x0C и сбрасывается в 0x4B0. Это
// поле мы звали «казной» — неверно: доход капает в +0x10 (0x41C944:250,442),
// а +0x0C не трогает больше никто.
const TRAIN_PERIOD = 0x4B0;
const TRAIN_XP = 100;
//: Выносливость, Сила, Ловкость — в порядке движка.
const TRAIN_CHARACTERISTICS = [5, 4, 1];
const TRAIN_ROUNDS = 2;
const TRAIN_SKILLS = 11;
const TRAIN_POST = 4;

export function villageTraining(phases = 1) {
  const data = village.data;
  if (!data || phases < 1) return false;
  const warlord = (data.officials ?? [])[TRAIN_POST] ?? 0;
  if (!warlord) return false;
  let changed = false;
  for (let phase = 0; phase < phases; phase += 1) {
    village.trainTimer = (village.trainTimer ?? TRAIN_PERIOD) - 1;
    if (village.trainTimer > 0) continue;
    village.trainTimer = TRAIN_PERIOD;
    if (trainOnce(warlord, data)) changed = true;
  }
  return changed;
}

function trainOnce(warlord, data) {
  const teacher = units.find((unit) => unit.slot === warlord);
  if (!teacher || teacher.alive === false) return false;
  const ceiling = teacher.level ?? 1;
  let changed = false;
  for (const unit of units) {
    if (unit === teacher || unit.side !== data.side) continue;
    if (unit.alive === false || unit.beast) continue;
    if ((unit.level ?? 1) > ceiling) continue;
    // Опыт кладётся НАПРЯМУЮ, минуя 0x413110: множителя сложности здесь нет,
    // это учёба жителей, а не награда игроку.
    unit.experience = (unit.experience ?? 0) + TRAIN_XP;
    changed = true;
    if (unit.experience < levelThreshold(unit.level ?? 1)) continue;
    unit.level = (unit.level ?? 1) + 1;
    unit.freeExperience = (unit.freeExperience ?? 0)
      + (world.map?.hero?.rules?.progression?.free_xp_per_level ?? 25);
    unit.nextLevel = levelThreshold(unit.level);
    for (let round = 0; round < TRAIN_ROUNDS; round += 1) {
      for (const index of TRAIN_CHARACTERISTICS) raiseCharacteristic(index, unit);
      for (let skill = 0; skill < TRAIN_SKILLS; skill += 1) raiseSkill(skill, unit);
    }
  }
  return changed;
}

// РОЛЬ ВЫВОДИТСЯ ИЗ ДОЛЖНОСТЕЙ, А НЕ ХРАНИТСЯ (VA 0x00415190).
//
// Движок перебирает пятёрку с +0x3D0 записи поселения и возвращает «место + 1»,
// то есть у знахаря 2, у купца 3, у кузнеца 4. Поле `role` в паке проставлено
// по МИРУ 0, а запись поселения мы теперь берём мира своего героя, и у любого
// другого героя эти два источника расходятся: житель числится должностным, а
// поле у него пустое. Верен только вывод из списка.
export function officialRole(unit) {
  const officials = world.map?.village?.officials ?? [];
  const number = unit?.slot ?? Number(String(unit?.id ?? "").replace("unit_", ""));
  const place = officials.indexOf(number);
  return place < 0 ? 0 : place + 1;
}
