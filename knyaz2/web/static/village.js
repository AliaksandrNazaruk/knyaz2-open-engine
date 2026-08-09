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
import { roundHalfEven } from "./round.js";

export const village = {
  data: null,        // блок поселения из пака (map.village)
  incomeStamp: 0,    // метка последней выплаты (+0x14)
  order: -1,         // какой вид куётся (+0x49F), -1 — никакой
  timer: 0,          // тиков до готовности (+0x08)
  stock: {},         // запасы по видам (+0x44E): вид -> имя готовой вещи
  lastTime: null,    // прошлое игровое время — для счёта тиков
};

function treasuryRules() {
  return world.map?.hero?.rules?.buildings?.treasury ?? null;
}

function workshopRules() {
  return world.map?.hero?.rules?.buildings?.workshop ?? null;
}

export function villageSetup(map) {
  village.data = map?.village ?? null;
  village.incomeStamp = daylight.time ?? 0;
  village.order = -1;
  village.timer = 0;
  village.stock = {};
  village.lastTime = null;
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
function workshopTick(фазы) {
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
  if (!фазы) return false;
  village.timer -= фазы;
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
  const фазы = clockPhaseHits(0xF, 7);
  const ticks = Math.round(timeGap(now, village.lastTime));
  if (ticks < 1 && !фазы) return false;
  if (ticks >= 1) village.lastTime = now;
  let changed = false;
  if (treasuryTick(now)) changed = true;
  if (workshopTick(фазы)) changed = true;
  return changed;
}
