// Перенос вещей.
//
// В движке вещь не «перекладывается щелчком», а берётся В РУКУ: курсор
// переходит в режим 8 и рисуется иконкой самой вещи (VA 0x41DFE0), а
// следующий щелчок решает, куда она ляжет. Откуда взяли — движок помнит
// вместе с копией всего списка, чтобы вернуть на место при отмене
// (VA 0x42944C).
//
// Здесь то же самое: взяли, несём, положили. Правила гнёзд, вес и запрет
// на квестовые вещи — из VA 0x41E280, 0x423218 и 0x421690.
import { world } from "./world.js";
import { hero } from "./hero.js";
import { actorItem, actorReclassItemRef } from "./actor.js";
import { JEWEL_SLOTS, SLOTS, bagInsert, bagPut, bagTake, dropOnGround, enchantFromBag,
         enchantFromSlot, enchantToBag, enchantToSlot, equipFromBag,
         ammoStack, countFromBag, countToBag,
         poisonFromBag, poisonFromSlot, poisonToBag, poisonToSlot,
         requirementMet, unequip } from "./inventory.js";
import { currentCharacteristics, slotsForKind } from "./jewels.js";
import { selectionLead } from "./orders.js";
import { mixing, mixingApply, mixingPlace, mixingTake, potionMix } from "./craft.js";
import { potionDrink, potionOil, potionSmear } from "./effects.js";
import { playEffect } from "./sound.js";

// enchant — слово прибавок несомой вещи: в движке оно сидит в её записи
// (+0x0E) и потому «в руке» вместе с нею (VA 0x41DFE0).
export const carry = { item: null, from: null, index: -1, owner: null,
                       enchant: 0, poison: 0, count: null,
                       strength: null, wear: null, max: null, oiled: false };

//: ЧЬИ вещи мы перекладываем. В движке экран работает с юнитом, на который
//: смотрит указатель 0x849514, то есть с ПЕРВЫМ ВЫБРАННЫМ (VA 0x4292DC), —
//: значит и мешок, и гнёзда, и предел веса берутся у него, а не у героя.
export function carryActor() { return selectionLead() ?? hero; }

// Источник переноса не обязан оставаться выбранным: движок держит его в
// отдельном глобале 0x8449D8 и именно ему возвращает вещь при отмене.
function carryOwner() { return carry.owner ?? carryActor(); }

function takeInstanceState(name, actor) {
  carry.strength = typeof actor.bagStrength?.[name] === "number"
    ? actor.bagStrength[name] : null;
  carry.wear = typeof actor.wear?.[name] === "number" ? actor.wear[name] : null;
  carry.max = typeof actor.wearMax?.[name] === "number" ? actor.wearMax[name] : null;
  carry.oiled = Boolean(actor.itemOiled?.[name]);
  for (const field of ["bagStrength", "wear", "wearMax", "itemOiled"]) {
    if (actor[field]) delete actor[field][name];
  }
}

function putInstanceState(name, actor) {
  if (typeof carry.strength === "number") {
    actor.bagStrength = actor.bagStrength ?? {};
    actor.bagStrength[name] = carry.strength;
  }
  if (typeof carry.wear === "number") {
    actor.wear = actor.wear ?? {};
    actor.wear[name] = carry.wear;
  }
  if (typeof carry.max === "number") {
    actor.wearMax = actor.wearMax ?? {};
    actor.wearMax[name] = carry.max;
  }
  if (carry.oiled) {
    actor.itemOiled = actor.itemOiled ?? {};
    actor.itemOiled[name] = true;
  }
}

function classRef(index) {
  return Object.entries(world.map?.items ?? {})
    .find(([, item]) => item?.index === index)?.[0] ?? null;
}

function isPotionItem(value) {
  const potions = world.map?.hero?.rules?.effects?.potions;
  const potionKind = world.map?.hero?.rules?.trade?.item_kinds?.potion ?? 9;
  return Boolean(value && (value.kind === potionKind ||
    (value.index >= (potions?.empty ?? 83) && value.index <= (potions?.wisdom ?? 92))));
}

function rekeyInstanceState(actor, previous, next) {
  if (!previous || !next || previous === next) return;
  for (const field of ["bagStrength", "bagCount", "bagEnchant", "bagPoison",
                       "wear", "wearMax", "itemOiled"]) {
    const values = actor[field];
    if (!values || !Object.prototype.hasOwnProperty.call(values, previous)) continue;
    values[next] = values[previous];
    delete values[previous];
  }
}

function returnCarriedToOwner() {
  if (!carry.item) { clear(); return true; }
  const actor = carryOwner();
  const name = carry.item;
  // Возврат из 0x41D954 вызывает FUN_00423538(..., 0) и не оставляет
  // бутылку на курсоре. В обычном пути место гарантировано взятием из мешка.
  if (bagInsert(name, 0, actor) >= 0) {
    enchantToBag(name, carry.enchant, actor);
    poisonToBag(name, carry.poison, actor);
    countToBag(name, carry.count, actor);
    putInstanceState(name, actor);
  }
  clear();
  return true;
}

function finishPotion(became, state) {
  carry.strength = typeof state.strength === "number" ? state.strength : null;
  if (became !== null) {
    const next = classRef(became);
    if (!next) return false;
    carry.item = actorReclassItemRef(carry.item, next);
    // Класс 83 — пустая банка; прежняя крепость больше не принадлежит ей.
    carry.strength = null;
    carry.wear = null;
    carry.max = null;
    carry.oiled = false;
  }
  playEffect(0x11);
  return returnCarriedToOwner();
}

function carryPotionOnTarget(targetName, actor, targetStrength, replaceTarget) {
  const item = actorItem(carry.item);
  const target = actorItem(targetName);
  const potions = world.map?.hero?.rules?.effects?.potions;
  if (!potions || !isPotionItem(item) || !target) return false;

  // Зелье на зелье — не питьё, а таблица рецептов W_SFLB_mixmagics.
  if (isPotionItem(target)) {
    const mixed = potionMix(targetName, carry.item, carryOwner(),
      targetStrength, carry.strength);
    if (!mixed) return false;
    rekeyInstanceState(actor, targetName, mixed.result);
    actor.bagStrength = actor.bagStrength ?? {};
    if (typeof mixed.strength === "number") {
      actor.bagStrength[mixed.result] = mixed.strength;
    } else {
      delete actor.bagStrength[mixed.result];
    }
    replaceTarget(mixed.result, mixed.strength);
    carry.item = mixed.left;
    carry.strength = null;
    carry.wear = null;
    carry.max = null;
    carry.oiled = false;
    playEffect(0x11);
    return mixed.left ? returnCarriedToOwner() : (clear(), true);
  }

  const state = { strength: carry.strength };
  const targetState = {
    kind: target.kind,
    poison: actor.bagPoison?.[targetName] ?? 0,
    oiled: Boolean(actor.itemOiled?.[targetName]),
  };
  if (item.index === potions.poison) {
    const became = potionSmear(item, targetState, state);
    if (became === false) return false;
    actor.bagPoison = actor.bagPoison ?? {};
    actor.bagPoison[targetName] = targetState.poison;
    return finishPotion(became, state);
  }
  if (item.index === potions.oil) {
    const became = potionOil(item, targetState, state);
    if (became === false) return false;
    actor.itemOiled = actor.itemOiled ?? {};
    actor.itemOiled[targetName] = Boolean(targetState.oiled);
    return finishPotion(became, state);
  }

  const before = state.strength;
  const became = potionDrink(item, carryOwner(), state);
  const alwaysActs = item.index === potions.halve || item.index === potions.heal
    || item.index === potions.antidote;
  const acted = became !== null || alwaysActs || state.strength !== before;
  return acted ? finishPotion(became, state) : false;
}

function carryPotionOnBag(targetName, index, actor) {
  return carryPotionOnTarget(targetName, actor,
    actor.bagStrength?.[targetName] ?? null,
    (next) => { actor.bag[index] = next; });
}

function rules() { return world.map?.hero?.rules?.carry ?? null; }

export function carrying() { return carry.item; }

function say(key) {
  const text = rules()?.messages?.[key];
  if (text) world.onStatus?.(text);
  return false;
}

// Вес ОДНОЙ ЗАПИСИ: у стопки (вид 0x0C) он умножается на количество —
// и в мешке (VA 0x41B218), и у несомой вещи (VA 0x41AA78). Правило одно,
// а порт применял его только к надетому боеприпасу.
export function itemWeight(name, count = null) {
  const item = actorItem(name);
  if (!item) return 0;
  const stack = rules()?.item_kinds?.stack ?? 0x0C;
  if (item.kind !== stack) return item.weight ?? 0;
  return (item.weight ?? 0) * (count ?? rules()?.ammo_stack ?? 30);
}

// Сколько юнит несёт: в движке считаются и гнёзда, и второй набор, и
// мешок, причём у стопок вес умножается на количество (VA 0x41B218).
export function carriedWeight(actor = hero) {
  let grams = 0;
  for (const slot of SLOTS) grams += actorItem(actor.equipment?.[slot])?.weight ?? 0;
  for (const name of actor.bag ?? []) {
    grams += itemWeight(name, actor.bagCount?.[name] ?? null);
  }
  const ammo = actorItem(actor.equipment?.ammo);
  if (ammo) grams += ammo.weight * Math.max(0, (actor.ammoCount ?? 1) - 1);
  return grams;
}

// Предел: ТЕКУЩАЯ Выносливость в свою меру плюс двадцать килограммов —
// движок берёт байт +0xD1, то есть с прибавками надетого (VA 0x423218,
// `*(byte *)(param_1 + 0xd1)`). Деление ЦЕЛОЧИСЛЕННОЕ и беззнаковое —
// усечение, не округление: при выносливости 11 это 3666, а не 3667.
export function weightLimit(actor = hero) {
  const set = rules()?.weight;
  const stamina = currentCharacteristics(actor)[5] ?? 10;
  if (!set) return 20000 + Math.trunc(stamina * 1000 / 3);
  return Math.trunc(stamina * set.per_stamina / set.divisor) + set.base;
}

// ГНЕЗДО СМЕШИВАНИЯ (двенадцатое, код мыши 0x1C): щелчок с вещью в руке
// кладёт её в пустое гнездо или роняет НА лежащую — камень вкладывается,
// зелья варятся, точило чинит (VA 0x436C48); пустой рукой лежащее
// забирается обратно. Удачное применение движок озвучивает слотом 0x12
// (хвост 0x436C48); неподходящая пара проходит общий отказ 0x421690 —
// сообщение 0x4504A2 и немедленная отмена переноса.
//: ГДЕ ВЕЩЬ ЛЕЖИТ НА САМОМ ДЕЛЕ. Гнездо смешивания её не хранит, поэтому,
//: чтобы вынуть, надо сперва найти. Движок перебирает ровно эти места и в
//: таком порядке: боеприпас (+0x50), пять надетых (+0x58), пять украшений
//: (+0xB6) и мешок (+0x62) — VA 0x41EAB8.
function whereIs(name, actor) {
  if (!name) return null;
  for (const slot of SLOTS) {
    if (actor.equipment?.[slot] === name) return { from: slot, index: -1 };
  }
  const at = (actor.bag ?? []).indexOf(name);
  return at >= 0 ? { from: "bag", index: at } : null;
}

export function carryMixing() {
  const actor = carryActor();
  if (!carry.item) {
    // ВЫНУТЬ ИЗ ГНЕЗДА. Вещь всё это время лежала на своём месте — значит и
    // берём её оттуда, как движок: он ищет её среди четырёх блоков и зовёт
    // общий перенос 0x41DFE0 с кодом того блока, где нашлась.
    if (!mixing.name) return false;
    const found = whereIs(mixing.name, actor);
    if (!found || !carryTake(found.from, found.index)) return false;
    mixingTake();
    return true;
  }
  if (!mixing.name) {
    // ПОЛОЖИТЬ В ГНЕЗДО. Вещь ВОЗВРАЩАЕТСЯ на своё место, а гнездо только
    // помечает её словом _DAT_00849668 — так в движке и устроено: снимки
    // блоков, которые делает 0x41DFE0, существуют ровно ради этого возврата.
    //
    // Раньше гнездо ЗАБИРАЛО вещь себе. Из-за этого она переставала быть
    // надетой и нести вес, а главное — `mixing` не попадает в сохранение, и
    // оставленная в гнезде вещь пропадала насовсем.
    const name = carry.item;
    const strength = carry.strength ?? null;
    if (!carryCancel()) return false;
    mixingPlace(name, strength);
    return true;
  }
  if (carryPotionOnTarget(mixing.name, actor, mixing.strength,
      (next, strength) => {
        mixing.name = next;
        mixing.strength = strength;
      })) return true;
  // Что лежало в гнезде ДО применения: варка меняет пометку на класс
  // результата, а сама вещь остаётся там же, где лежала, и её надо
  // переклассить на месте.
  const before = mixing.name;
  const done = mixingApply(carry.item, actor, carry.strength);
  if (!done) return refuse();
  if (done.kind === "brew" && mixing.name && mixing.name !== before) {
    // Движок меняет БАЙТ КЛАССА в той же записи предмета (VA 0x41B930:
    // `цель+3 = таблица[i][2]`), то есть вещь не подменяется другой, а
    // становится другой. У нас это actorReclassItemRef — хвост ссылки,
    // а с ним крепость, чары и износ, остаётся прежним.
    const next = actorReclassItemRef(before, mixing.name);
    const at = whereIs(before, actor);
    if (at?.from === "bag") actor.bag[at.index] = next;
    else if (at) actor.equipment[at.from] = next;
    mixing.name = next;
  }
  playEffect(done.kind === "brew" ? 0x11 : 0x12);
  // применяемая вещь съедена; после варки в руке остаётся остаток
  carry.item = done.kind === "brew" ? (done.left ?? null) : null;
  carry.strength = null;
  carry.wear = null;
  carry.max = null;
  carry.enchant = 0;
  carry.poison = 0;
  carry.count = null;
  if (!carry.item) {
    clear();
  } else if (done.kind === "brew") {
    return returnCarriedToOwner();
  }
  return true;
}

// Взять вещь в руку. Из мешка — по номеру ячейки, из гнезда — по имени.
export function carryTake(from, index) {
  if (carry.item) return false;
  const actor = carryActor();
  if (from === "bag") {
    const name = bagTake(index, actor);
    if (!name) return false;
    carry.item = name;
    carry.enchant = enchantFromBag(name, actor);
    carry.poison = poisonFromBag(name, actor);
    carry.count = countFromBag(name, actor);
    takeInstanceState(name, actor);
  } else {
    const name = actor.equipment?.[from];
    if (!name) return false;
    actor.equipment[from] = null;
    if (from === "ranged") actor.rangedMode = false;
    carry.item = name;
    carry.enchant = enchantFromSlot(from, actor);
    carry.poison = poisonFromSlot(from, actor);
    if (from === "ammo") {
      carry.count = actor.ammoCount ?? ammoStack(actor);
      actor.ammoCount = null;
    }
    takeInstanceState(name, actor);
  }
  carry.from = from;
  carry.index = index;
  carry.owner = actor;
  return true;
}

// Отменить перенос (VA 0x42944C). Вещь из мешка возвращается НЕ в свою
// прежнюю ячейку: движок кладёт её в ячейку 0, а сохранённый уплотнённый
// список — начиная с первой. Прежней дырки в мешке уже нет, восстанавливать
// индекс не по чему.
export function carryCancel() {
  if (!carry.item) return false;
  const actor = carryOwner();
  if (carry.from === "bag") {
    if (bagInsert(carry.item, 0, actor) < 0) return false;
    enchantToBag(carry.item, carry.enchant, actor);
    poisonToBag(carry.item, carry.poison, actor);
    countToBag(carry.item, carry.count, actor);
    putInstanceState(carry.item, actor);
  } else {
    // Ветки "mixing" здесь больше нет и быть не может: гнездо смешивания
    // вещь не хранит, поэтому взять её ОТТУДА нельзя — берут всегда из того
    // блока, где она лежит, и carry.from несёт имя этого блока.
    actor.equipment[carry.from] = carry.item;
    enchantToSlot(carry.from, carry.enchant, actor);
    poisonToSlot(carry.from, carry.poison, actor);
    if (carry.from === "ammo") {
      actor.ammoCount = carry.count ?? ammoStack(actor);
    }
    putInstanceState(carry.item, actor);
  }
  clear();
  return true;
}

function clear() {
  carry.item = null;
  carry.from = null;
  carry.index = -1;
  carry.owner = null;
  carry.enchant = 0;
  carry.poison = 0;
  carry.count = null;
  carry.strength = null;
  carry.wear = null;
  carry.max = null;
  carry.oiled = false;
}

// Отказ: сообщение движка и немедленный возврат вещи на место.
function refuse(message = "requirement") {
  say(message);
  carryCancel();
  return false;
}

// Подходит ли боеприпас метательному: самострелу болты, луку стрелы, а
// различаются они номером класса (VA 0x41E280).
export function ammoFits(weapon, ammo) {
  const set = rules();
  if (!set || !weapon || !ammo) return true;
  const bolt = ammo.index > set.bolt_class_from;
  return bolt === (weapon.layer === set.crossbow_layer);
}

// Положить в гнездо — со всеми проверками движка.
export function carryPlaceSlot(slot) {
  if (!carry.item) return false;
  const actor = carryActor();
  const set = rules();
  const item = actorItem(carry.item);
  if (!item) return false;
  // слово несомой вещи — в руке, а не в мешке: передаём его проверке само
  if (!requirementMet(carry.item, carryActor(), carry.enchant)) {
    return refuse();
  }
  // Двуручное — это ТОЛЬКО «слой больше 0x0C» (VA 0x41E2CE и 0x41E6D8).
  // Верхней границы в движке нет; прежнее `layer <= 17` было выдумано.
  const twoHanded = item.two_handed ??
    (item.layer >= (set?.two_hand_from_layer ?? 13));
  // Щит терпит и одноручное оружие, но только по навыку (unit+0xD3).
  const offHandWeapon = slot === "off_hand" && item.slot === "hand" && !twoHanded &&
    Boolean(carryActor().skills?.[1]);
  // Украшение годится только в гнёзда своего вида: ожерелье в одно,
  // браслет в любое из двух, кольцо в любое из двух (VA 0x41E8D8).
  const jewel = JEWEL_SLOTS.includes(slot) && slotsForKind(item.kind).includes(slot);
  if (JEWEL_SLOTS.includes(slot) && !jewel) return refuse();
  if (!jewel && item.slot !== slot && !(slot === "ammo" && item.ammo) &&
      !offHandWeapon) return refuse();
  if (slot === "ammo" && !ammoFits(actorItem(carryActor().equipment?.ranged), item)) {
    return refuse();
  }
  if (slot === "ranged" && !ammoFits(item, actorItem(carryActor().equipment?.ammo))) {
    // Не тот боеприпас — движок сгоняет его из гнезда.
    const spare = carryActor().equipment.ammo;
    carryActor().equipment.ammo = null;
    const spareWord = enchantFromSlot("ammo", carryActor());
    const sparePoison = poisonFromSlot("ammo", carryActor());
    const spareCount = carryActor().ammoCount ?? ammoStack(carryActor());
    carryActor().ammoCount = null;
    if (spare && bagPut(spare, -1, carryActor()) < 0) {
      if (!dropOnGround(spare, carryActor(), {
        ...(spareWord ? { enchant: spareWord } : {}),
        ...(sparePoison ? { poison: sparePoison } : {}),
        ...(carryActor().itemOiled?.[spare] ? { oiled: true } : {}),
        count: spareCount,
      })) {
        carryActor().equipment.ammo = spare;
        enchantToSlot("ammo", spareWord, carryActor());
        poisonToSlot("ammo", sparePoison, carryActor());
        carryActor().ammoCount = spareCount;
        return refuse();
      }
    } else {
      enchantToBag(spare, spareWord, carryActor());
      poisonToBag(spare, sparePoison, carryActor());
      countToBag(spare, spareCount, carryActor());
    }
  }
  // Сгон работает В ОБЕ СТОРОНЫ (VA 0x41E2C4 и 0x41E6D0): двуручное в
  // правой руке выгоняет щит, а щит или оружие в левую — выгоняет
  // двуручное. Если вытесненному не нашлось места ни в мешке, ни на
  // земле, движок отменяет всю укладку.
  const evict = (from) => {
    const spare = carryActor().equipment[from];
    if (!spare) return true;
    carryActor().equipment[from] = null;
    const spareWord = enchantFromSlot(from, carryActor());
    const sparePoison = poisonFromSlot(from, carryActor());
    const inBag = bagPut(spare, -1, carryActor()) >= 0;
    if (!inBag && !dropOnGround(spare, carryActor(), {
      ...(spareWord ? { enchant: spareWord } : {}),
      ...(sparePoison ? { poison: sparePoison } : {}),
    })) {
      carryActor().equipment[from] = spare;               // некуда — укладки не будет
      enchantToSlot(from, spareWord, carryActor());
      poisonToSlot(from, sparePoison, carryActor());
      return false;
    }
    if (inBag) {
      enchantToBag(spare, spareWord, carryActor());
      poisonToBag(spare, sparePoison, carryActor());
    }
    return true;
  };
  if (slot === "hand" && twoHanded && carryActor().equipment.off_hand) {
    if (!evict("off_hand")) return refuse();
  }
  if (slot === "off_hand" && carryActor().equipment.hand) {
    const inHand = actorItem(carryActor().equipment.hand);
    const handTwoHanded = inHand?.two_handed ??
      (inHand?.layer >= (set?.two_hand_from_layer ?? 13));
    if (handTwoHanded && !evict("hand")) return refuse();
  }
  const previous = carryActor().equipment[slot] ?? null;
  const previousWord = previous ? enchantFromSlot(slot, carryActor()) : 0;
  const previousPoison = previous ? poisonFromSlot(slot, carryActor()) : 0;
  const previousCount = slot === "ammo" && previous
    ? (carryActor().ammoCount ?? ammoStack(carryActor())) : null;
  actor.equipment[slot] = carry.item;
  enchantToSlot(slot, carry.enchant, actor);
  poisonToSlot(slot, carry.poison, actor);
  if (slot === "ammo") actor.ammoCount = carry.count ?? ammoStack(actor);
  if (slot === "ranged") actor.rangedMode = true;
  putInstanceState(carry.item, actor);
  clear();
  // Что стояло в гнезде — в мешок, а некуда, так на землю. У УКРАШЕНИЙ
  // иначе: движок там результат укладки не проверяет и на землю ничего не
  // роняет (VA 0x41E8D8) — при полном мешке прежнее украшение пропадает.
  if (previous) {
    enchantToBag(previous, previousWord, carryActor());
    poisonToBag(previous, previousPoison, carryActor());
    countToBag(previous, previousCount, carryActor());
    if (JEWEL_SLOTS.includes(slot)) bagPut(previous, -1, carryActor());
    else if (bagPut(previous, -1, carryActor()) < 0) dropOnGround(previous, carryActor());
  }
  return true;
}

// Положить в мешок: сперва вес, потом место.
export function carryPlaceBag(index = -1) {
  if (!carry.item) return false;
  const actor = carryActor();
  const item = actorItem(carry.item);
  // Цена 0 — квестовая вещь. FUN_00423218 разрешает положить её только
  // главному герою; передача выбранному спутнику молча отменяет перенос.
  if ((item?.price ?? 0) === (rules()?.quest_price ?? 0) && actor !== hero) {
    return carryCancel();
  }
  const target = index >= 0 ? actor.bag?.[index] : null;
  if (target) {
    if (carryPotionOnBag(target, index, actor)) return true;
    const result = carryOntoStack(
      actor.bagCount?.[target] ?? ammoStack(actor), actorItem(target),
      actor.bagPoison?.[target] ?? 0, carry.poison,
      carry.count ?? ammoStack(actor));
    if (!result) return false;
    actor.bagCount = actor.bagCount ?? {};
    actor.bagCount[target] = result[0];
    return true;
  }
  // Вес несомой вещи движок берёт через 0x41AA78, а там у стопки он
  // умножается на количество — считаем так же.
  if (carriedWeight(actor) + itemWeight(carry.item, carry.count) >
      weightLimit(actor)) return refuse("weight");
  const word = carry.enchant;
  const poison = carry.poison;
  const count = carry.count;
  const name = carry.item;
  if (bagInsert(carry.item, index, actor) < 0) return refuse("bag_full");
  putInstanceState(name, actor);
  clear();
  enchantToBag(name, word, carryActor());
  poisonToBag(name, poison, carryActor());
  countToBag(name, count, carryActor());
  return true;
}

// Бросить на землю. Вещь без цены — квестовая, её движок бросить не даёт,
// и ложится она в клетку самого героя, а не под мышь (VA 0x421690).
export function carryDrop() {
  if (!carry.item) return false;
  const item = actorItem(carry.item);
  // Отказ в движке НЕ оставляет вещь в руке: он зовёт отмену переноса, и
  // вещь тут же возвращается на место (VA 0x421690 -> 0x42944C).
  if ((item?.price ?? 0) === (rules()?.quest_price ?? 0)) return carryCancel();
  const name = carry.item;
  const word = carry.enchant;
  const poison = carry.poison;
  const actor = carryOwner();
  const strength = typeof carry.strength === "number"
    ? carry.strength : carry.wear;
  const detail = {
    ...(typeof strength === "number" ? { strength } : {}),
    ...(typeof carry.max === "number" ? { max: carry.max } : {}),
    ...(word ? { enchant: word } : {}),
    ...(poison ? { poison } : {}),
    ...(typeof carry.count === "number" ? { count: carry.count } : {}),
    ...(carry.oiled ? { oiled: true } : {}),
  };
  if (!dropOnGround(name, actor, detail)) return carryCancel();
  clear();
  return true;
}

// Уронить на другую вещь: две пачки боеприпаса складываются, если совпали
// и класс, и отрава, а в пачке не больше тридцати (VA 0x421690).
//
// Остаток сверх тридцати в руке НЕ остаётся: движок кладёт его в мешок и
// на этом перенос заканчивает — курсор возвращается в обычный режим в
// обоих исходах (VA 0x4217xx, `_DAT_00849650 = 2`).
export function carryOntoStack(targetCount, targetItem, targetPoison = 0,
                               carriedPoison = 0, carriedCount = 0) {
  const set = rules();
  const item = actorItem(carry.item);
  // Не сложилось — движок печатает «Предмет не доступен для использования»
  // и отменяет перенос, а не держит вещь в руке (VA 0x421690).
  if (!item?.ammo || !targetItem?.ammo) { refuse(); return null; }
  if (item.index !== targetItem.index || targetPoison !== carriedPoison) {
    refuse();
    return null;
  }
  const max = set?.stack_max ?? 30;
  const moving = carriedCount || carry.count || 0;
  const total = targetCount + moving;
  if (total <= max) { clear(); return [total, 0]; }
  const left = total - max;
  const spare = carry.item;
  const word = carry.enchant;
  const poison = carry.poison;
  const owner = carryOwner();
  if (bagInsert(spare, 0, owner) < 0) {
    refuse();
    return null;
  }
  enchantToBag(spare, word, owner);
  poisonToBag(spare, poison, owner);
  countToBag(spare, left, owner);
  putInstanceState(spare, owner);
  clear();
  return [max, left];
}
