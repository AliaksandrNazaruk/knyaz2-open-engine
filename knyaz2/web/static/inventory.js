// Инвентарь по устройству движка.
//
// У юнита пять слотов экипировки подряд и мешок следом (konung2/items.py):
//
//     unit+0x58 рука   +0x5A метательное  +0x5C доспех
//     unit+0x5E шлем   +0x60 щит          +0x62 мешок, 42 ячейки u16
//
// Куда предмет ложится, решает не наш вкус, а его «вид» — байт +0 записи
// предмета, и это ровно номер слота: 0 рука, 1 метательное, 2 доспех,
// 3 шлем, 4 щит (раздача снаряжения VA 0x4394BA). Вид приезжает в паке
// полем `kind` класса предмета.
import { world } from "./world.js";
import { actorItem } from "./actor.js";
import { hero } from "./hero.js";
import { currentCharacteristics, slotsForKind } from "./jewels.js";

export const SLOTS = ["hand", "ranged", "body", "head", "off_hand", "ammo",
                      "necklace", "bracelet_1", "bracelet_2", "ring_1", "ring_2"];
//: Второй набор — украшения: вид 6 ожерелье, 7 браслет, 8 кольцо
//: (VA 0x41E8D8). Гнёзд у них пять, и лежат они в юните с +0xB6.
export const JEWEL_SLOTS = ["necklace", "bracelet_1", "bracelet_2", "ring_1", "ring_2"];
//: Боеприпас: вид 0x0C, лежит отдельным полем unit+0x50, и движок сам
//: находит в мешке подходящий (VA 0x41291C перебирает 42 ячейки).
export const AMMO_KIND = 0x0C;
export const SLOT_TITLES = {
  hand: "рука", ranged: "метательное", body: "доспех",
  head: "шлем", off_hand: "щит", ammo: "боеприпас",
};

export function bagSize() {
  return hero.data?.rules?.inventory?.bag_slots ?? 42;
}

// ИНВЕНТАРЬ — НЕ ГЕРОЙСКИЙ. В движке мешок это поле ЮНИТА (+0x62, сорок
// два слова), гнёзда — его же слоты, второй набор — +0xB6, а экран
// работает с тем юнитом, на который смотрит указатель 0x849514, то есть с
// ПЕРВЫМ ВЫБРАННЫМ (VA 0x4292DC). Поэтому все эти функции берут юнита
// аргументом; герой — просто значение по умолчанию.
export function inventorySetup(actor = hero) {
  actor.equipment = { hand: null, ranged: null, body: null, head: null,
                      off_hand: null, ammo: null,
                      necklace: null, bracelet_1: null, bracelet_2: null,
                      ring_1: null, ring_2: null };
  // Слова прибавок надетого: у каждой вещи своё, живёт в её записи.
  actor.enchant = actor.enchant ?? {};
  actor.bag = new Array(bagSize()).fill(null);
  // Чем бьёмся: ложь — тем, что в руке, истина — метательным. В движке это
  // байт unit+0xEE, и по умолчанию он нулевой.
  actor.rangedMode = false;
}

function normalizeBag(actor = hero) {
  const size = bagSize();
  if (!Array.isArray(actor.bag)) actor.bag = [];
  // В GAME.x мешок — уплотнённый список: удаление 0x420B7C сдвигает весь
  // хвост. Заодно лечим дырки старых pack/save, где порт оставлял null.
  const compact = actor.bag.filter(Boolean).slice(0, size);
  while (compact.length < size) compact.push(null);
  actor.bag = compact;
}

export function bagFreeIndex(actor = hero) {
  normalizeBag(actor);
  return actor.bag.indexOf(null);
}

// Положить в мешок. Возвращает номер ячейки или -1, если места нет.
export function bagPut(name, index = -1, actor = hero) {
  normalizeBag(actor);
  const spot = index >= 0 ? index : actor.bag.indexOf(null);
  if (spot < 0 || spot >= actor.bag.length || actor.bag[spot]) return -1;
  actor.bag[spot] = name;
  return spot;
}

// Вставка FUN_00423538: освободить место сдвигом хвоста вправо и положить
// запись в указанный слот. При index < 0 движок использует первый свободный.
export function bagInsert(name, index = 0, actor = hero) {
  normalizeBag(actor);
  const free = actor.bag.indexOf(null);
  if (!name || free < 0) return -1;
  const spot = index < 0 ? free : Math.min(Math.max(0, index), free);
  for (let at = free; at > spot; at -= 1) actor.bag[at] = actor.bag[at - 1];
  actor.bag[spot] = name;
  return spot;
}

export function bagTake(index, actor = hero) {
  normalizeBag(actor);
  const name = actor.bag[index] ?? null;
  if (!name) return null;
  actor.bag.splice(index, 1);
  actor.bag.push(null);
  return name;
}

// СЛОВО ПРИБАВОК ЕДЕТ С ВЕЩЬЮ. В движке оно лежит в самой записи предмета
// (+0x0E, VA 0x41C494) и переезжает вместе с ней само собой. У нас записи
// нет: в мешке слово живёт по имени (bagEnchant), у надетого — по гнезду
// (enchant), поэтому каждый перенос вещи обязан перекладывать и слово.
// На земле слово теряется — кучи хранят одни имена (см. В10 в аудите).
export function enchantFromBag(name, actor = hero) {
  const word = actor.bagEnchant?.[name] ?? 0;
  if (actor.bagEnchant) delete actor.bagEnchant[name];
  return word;
}

export function enchantToBag(name, word, actor = hero) {
  if (!name || !word) return;
  actor.bagEnchant = actor.bagEnchant ?? {};
  actor.bagEnchant[name] = word;
}

export function enchantFromSlot(slot, actor = hero) {
  const word = actor.enchant?.[slot] ?? 0;
  if (actor.enchant) delete actor.enchant[slot];
  return word;
}

export function enchantToSlot(slot, word, actor = hero) {
  actor.enchant = actor.enchant ?? {};
  if (word) actor.enchant[slot] = word;
  else delete actor.enchant[slot];
}

export function poisonFromBag(name, actor = hero) {
  const poison = actor.bagPoison?.[name] ?? 0;
  if (actor.bagPoison) delete actor.bagPoison[name];
  return poison;
}

export function poisonToBag(name, poison, actor = hero) {
  if (!name || !poison) return;
  actor.bagPoison = actor.bagPoison ?? {};
  actor.bagPoison[name] = poison;
}

export function poisonFromSlot(slot, actor = hero) {
  const poison = actor.poisonOn?.[slot] ?? 0;
  if (actor.poisonOn) delete actor.poisonOn[slot];
  if (slot === "ammo") actor.ammoPoison = 0;
  return poison;
}

export function poisonToSlot(slot, poison, actor = hero) {
  actor.poisonOn = actor.poisonOn ?? {};
  if (poison) actor.poisonOn[slot] = poison;
  else delete actor.poisonOn[slot];
  if (slot === "ammo") actor.ammoPoison = poison || 0;
}

export function countFromBag(name, actor = hero) {
  const item = actorItem(name);
  if (!item?.ammo) return null;
  const count = actor.bagCount?.[name] ?? ammoStack(actor);
  if (actor.bagCount) delete actor.bagCount[name];
  return count;
}

export function countToBag(name, count, actor = hero) {
  if (!name || !actorItem(name)?.ammo || typeof count !== "number") return;
  actor.bagCount = actor.bagCount ?? {};
  actor.bagCount[name] = count;
}

// Подходит ли предмет слоту: сравниваем вид предмета с номером слота.
export function fitsSlot(name, slot) {
  const item = actorItem(name);
  if (!item) return false;
  return item.slot === slot;
}

// Хватает ли характеристик, чтобы взять предмет: движок сравнивает
// характеристику юнита с требованием предмета и не даёт надеть, если она
// меньше (VA 0x418648, поля класса +0x0C и +0x0E).
export function requirementMet(name, actor = hero, enchantWord = 0) {
  const item = actorItem(name);
  // Самая первая проверка движка — НЕ характеристика, а опознание:
  // у неопознанной вещи поднят старший бит слова чар (+0x0F & 0x80), и
  // надеть её нельзя вовсе (VA 0x418654).
  const dormant = actor.data?.rules?.enchant?.dormant ?? 0x8000;
  const word = enchantWord || actor.bagEnchant?.[name] || 0;
  if (word & dormant) return false;
  if (!item?.requires || !item.requirement) return true;
  const names = actor.data?.rules?.progression?.characteristics?.names ?? [];
  const index = names.indexOf(item.requires);
  if (index < 0) return true;
  // Сравнивается ТЕКУЩАЯ характеристика: украшения её поднимают, и с
  // ними надевается то, что без них не по силам.
  return (currentCharacteristics(actor)[index] ?? 0) >= item.requirement;
}

// Надеть из мешка. Что было надето — обратно в мешок, в освободившуюся
// ячейку, поэтому обмен всегда возможен.
export function equipFromBag(index, slot = null, actor = hero) {
  normalizeBag(actor);
  const name = actor.bag[index];
  const item = actorItem(name);
  if (!item) return false;
  const target = slot ?? (item.ammo ? "ammo" : item.slot);
  if (!SLOTS.includes(target)) return false;
  if (target !== "ammo" && !fitsSlot(name, target)) return false;
  if (!requirementMet(name, actor)) {
    // Сообщение — строка самого движка (VA 0x45024C), а не наша выдумка.
    world.onStatus?.(hero.data?.rules?.carry?.messages?.requirement
      ?? "Предмет не доступен для использования");
    return false;
  }
  const previous = actor.equipment[target] ?? null;
  const previousCount = target === "ammo" ? actor.ammoCount : null;
  actor.equipment[target] = name;
  actor.bag[index] = previous;
  // слово прибавок меняется местами вместе с вещами
  const wornWord = enchantFromSlot(target, actor);
  enchantToSlot(target, enchantFromBag(name, actor), actor);
  enchantToBag(previous, wornWord, actor);
  const wornPoison = poisonFromSlot(target, actor);
  poisonToSlot(target, poisonFromBag(name, actor), actor);
  poisonToBag(previous, wornPoison, actor);
  if (target === "ammo") {
    actor.ammoCount = countFromBag(name, actor);
    countToBag(previous, previousCount, actor);
  }
  // Двуручное занимает обе руки: щит уходит в мешок (VA 0x416BC2 —
  // удар двуручным на вторую руку не смотрит вовсе).
  const twoHanded = item.two_handed ?? (item.layer >= 13 && item.layer <= 17);
  if (target === "hand" && twoHanded) {
    const shield = actor.equipment.off_hand;
    if (shield) {
      actor.equipment.off_hand = null;
      const shieldWord = enchantFromSlot("off_hand", actor);
      const shieldPoison = poisonFromSlot("off_hand", actor);
      if (bagPut(shield, -1, actor) < 0) dropOnGround(shield, actor);
      else {
        enchantToBag(shield, shieldWord, actor);
        poisonToBag(shield, shieldPoison, actor);
      }
    }
  }
  // Метательное надели — движок ищет к нему боеприпас и пересчитывает режим
  // оружия: единица встаёт в unit+0xEE, только когда заняты ОБА гнезда
  // (VA 0x420704 ставит, VA 0x412FF4 сверяет +0x50 и +0x5A).
  if (target === "ranged") { ammoPick(null, 0, actor); }
  weaponModeRefresh(actor);
  return true;
}

// Найти в мешке боеприпас и положить в свой слот (VA 0x41291C). Движок
// перебирает мешок в ДВА круга и берёт не первое попавшееся:
//
//   1. точное совпадение с кончившейся пачкой — тот же класс И та же
//      отрава; такую он подхватывает сразу;
//   2. иначе первое подходящее ОРУЖИЮ: самострелу (слой 0x15) годятся
//      только классы больше 0xCD (болты), всем прочим — только 0xCD и
//      ниже (стрелы).
//
// Без второго правила самострел заряжался стрелами.
export function ammoPick(previous = null, previousPoison = 0, actor = hero) {
  normalizeBag(actor);
  if (actor.equipment.ammo) return actor.equipment.ammo;
  const set = hero.data?.rules?.carry;
  const boltFrom = set?.bolt_class_from ?? 0xCD;
  const crossbow = actorItem(actor.equipment?.ranged)?.layer === set?.crossbow_layer;
  const previousItem = previous ? actorItem(previous) : null;
  let fallback = -1;
  for (let index = 0; index < actor.bag.length; index += 1) {
    const item = actorItem(actor.bag[index]);
    if (!item?.ammo) continue;
    // круг первый: ровно такая же пачка, как кончившаяся
    if (previousItem && item.index === previousItem.index &&
        (actor.bagPoison?.[actor.bag[index]] ?? 0) === previousPoison) {
      fallback = index;
      break;
    }
    if (fallback >= 0) continue;
    // круг второй: годится ли оружию
    const bolt = item.index > boltFrom;
    if (bolt === crossbow) fallback = index;
  }
  if (fallback < 0) return null;
  actor.equipment.ammo = actor.bag[fallback];
  actor.bag[fallback] = null;
  poisonToSlot("ammo", poisonFromBag(actor.equipment.ammo, actor), actor);
  actor.ammoCount = countFromBag(actor.equipment.ammo, actor);
  return actor.equipment.ammo;
}

//: Сколько стрел в пачке — в стартовых мирах у всех тридцать.
export function ammoStack(actor = hero) {
  return hero.data?.rules?.accuracy?.projectiles?.ammo_stack ?? 30;
}

// Потратить стрелу: счётчик пачки минус один, кончилась — движок ищет в
// мешке следующую (VA 0x413894 и 0x41291C).
// Режим оружия (unit+0xEE): стрелять можно, ТОЛЬКО когда заняты оба гнезда
// — и метательное (+0x5A), и боеприпас (+0x50). Иначе байт обнуляется, и
// юнит переходит в ближний бой (VA 0x412FF4:
//   `if ((*(short *)(param_1 + 0x50) == 0) || (*(short *)(param_1 + 0x5a) ==
//    0)) { *(undefined1 *)(param_1 + 0xee) = 0; } else { ... = 1; }`).
//
// Пересчитывать надо после каждой смены снаряжения и после того, как вышла
// последняя стрела: иначе стрелок остаётся в режиме стрельбы с пустым
// гнездом и стоит без дела, вместо того чтобы взяться за оружие руки.
//: Пять надетых гнёзд по порядку движка: номер гнезда И ЕСТЬ вид записи
//: вещи, которая в него годится (konung2/items.py: SLOT_BY_KIND).
const REFIT_SLOTS = [["hand", 0], ["ranged", 1], ["body", 2],
                     ["head", 3], ["off_hand", 4]];

// ДОСНАРЯЖЕНИЕ ИЗ МЕШКА (VA 0x412AF4). Пустое гнездо заполняется ПЕРВОЙ
// подходящей вещью мешка: вид записи равен номеру гнезда и требования
// проходят. Отдельное правило у щита: двуручному он не положен — движок
// смотрит слой вещи в руке и отказывает, если он больше 0x0C.
//
// Требования проверяются ЗДЕСЬ, а не внутри equipFromBag: та на отказе
// показывает строку движка «Предмет не доступен для использования», а
// доснаряжение молчит — оно идёт само, без участия игрока.
function refitSlot(actor, slot, kind) {
  if (actor.equipment?.[slot]) return true;
  if (slot === "off_hand") {
    const hand = actorItem(actor.equipment?.hand);
    if (hand && (hand.layer ?? 0) > 0x0C) return false;
  }
  const bag = actor.bag ?? [];
  for (let index = 0; index < bag.length; index += 1) {
    const name = bag[index];
    if (!name) continue;
    const item = actorItem(name);
    if (!item || item.kind !== kind) continue;
    if (!requirementMet(name, actor)) continue;
    return equipFromBag(index, slot, actor);
  }
  return false;
}

// ПЕРЕСЧЁТ РЕЖИМА ОРУЖИЯ ЦЕЛИКОМ (VA 0x412FF4): сперва боеприпас, потом
// пять надетых гнёзд, и только потом сам режим.
//
// Раньше здесь стояла одна последняя строка — флаг из двух гнёзд, — а
// доснаряжения не было вовсе. Из-за этого юнит с луком В МЕШКЕ лучником не
// становился никогда: выбор цели для выстрела (VA 0x411F28) требует
// ЗАНЯТОГО метательного гнезда и боеприпаса, а заполнить их было некому.
export function weaponModeRefresh(actor = hero) {
  refitSlot(actor, "ammo", AMMO_KIND);
  for (const [slot, kind] of REFIT_SLOTS) refitSlot(actor, slot, kind);
  actor.rangedMode = Boolean(actor.equipment?.ammo) &&
    Boolean(actor.equipment?.ranged);
  return actor.rangedMode;
}

export function ammoSpend(actor = hero) {
  if (!actor.equipment?.ammo) return false;
  actor.ammoCount = (actor.ammoCount ?? ammoStack(actor)) - 1;
  if (actor.ammoCount > 0) return true;
  // Какая пачка кончилась — движок помнит: следующую он ищет прежде всего
  // ровно такую же, по классу и отраве.
  const spent = actor.equipment.ammo;
  const spentPoison = actor.ammoPoison ?? 0;
  actor.equipment.ammo = null;
  actor.ammoCount = 0;
  poisonFromSlot("ammo", actor);
  // Нулевая стопка освобождает саму запись предмета (0x41BB10); вместе с
  // ней обязана исчезнуть и метка масла из байта +2.
  for (const field of ["bagStrength", "bagCount", "bagEnchant", "bagPoison",
                       "wear", "wearMax", "itemOiled"]) {
    if (actor[field]) delete actor[field][spent];
  }
  ammoPick(spent, spentPoison, actor);
  // Пачка кончилась — режим оружия пересчитывается: не нашлось замены,
  // значит стрелок берётся за оружие руки (VA 0x412FF4).
  return weaponModeRefresh(actor);
}

export function unequip(slot, actor = hero) {
  const name = actor.equipment[slot];
  if (!name) return false;
  if (bagPut(name, -1, actor) < 0) return false;
  actor.equipment[slot] = null;
  enchantToBag(name, enchantFromSlot(slot, actor), actor);
  poisonToBag(name, poisonFromSlot(slot, actor), actor);
  if (slot === "ammo") {
    countToBag(name, actor.ammoCount ?? ammoStack(actor), actor);
    actor.ammoCount = null;
  }
  weaponModeRefresh(actor);
  return true;
}

// Выбросить: предмет ложится на землю там, где стоит персонаж.
export function dropOnGround(name, actor = hero, state = null) {
  if (!name) return false;
  const detail = state ?? {
    ...(typeof actor.bagStrength?.[name] === "number"
      ? { strength: actor.bagStrength[name] } : {}),
    ...(typeof actor.wearMax?.[name] === "number"
      ? { max: actor.wearMax[name] } : {}),
    ...(actor.bagEnchant?.[name] ? { enchant: actor.bagEnchant[name] } : {}),
    ...(actor.bagPoison?.[name] ? { poison: actor.bagPoison[name] } : {}),
    ...(typeof actor.bagCount?.[name] === "number"
      ? { count: actor.bagCount[name] } : {}),
    ...(actor.itemOiled?.[name] ? { oiled: true } : {}),
  };
  // Вещь ложится в клетку ТОГО, кто её бросил (VA 0x423360), а не героя.
  const dropped = world.onDrop?.(name, actor.x, actor.y, detail);
  if (!dropped) return false;
  for (const field of ["bagStrength", "bagCount", "bagEnchant", "bagPoison",
                       "wear", "wearMax", "itemOiled"]) {
    if (actor[field]) delete actor[field][name];
  }
  return true;
}

export function dropFromBag(index, actor = hero) {
  const name = bagTake(index, actor);
  if (!name) return false;
  if (dropOnGround(name, actor)) return true;
  bagInsert(name, index, actor);
  return false;
}

export function dropFromSlot(slot, actor = hero) {
  const name = actor.equipment[slot];
  if (!name) return false;
  actor.equipment[slot] = null;
  enchantToBag(name, enchantFromSlot(slot, actor), actor);
  poisonToBag(name, poisonFromSlot(slot, actor), actor);
  if (slot === "ammo") {
    countToBag(name, actor.ammoCount ?? ammoStack(actor), actor);
    actor.ammoCount = null;
  }
  weaponModeRefresh(actor);
  if (dropOnGround(name, actor)) return true;
  actor.equipment[slot] = name;
  enchantToSlot(slot, enchantFromBag(name, actor), actor);
  poisonToSlot(slot, poisonFromBag(name, actor), actor);
  if (slot === "ammo") actor.ammoCount = countFromBag(name, actor);
  weaponModeRefresh(actor);
  return false;
}

// Подобранное идёт в мешок, а не сразу в руки: надеть — отдельное действие,
// как в игре.
export function pickUp(name, actor = hero) {
  if (bagPut(name, -1, actor) >= 0) return "мешок";
  return "мешок полон";
}

// Вес — в граммах (поле класса +0x14), наружу отдаём килограммы.
export function inventoryWeight(actor = hero) {
  normalizeBag(actor);
  let grams = 0;
  for (const name of actor.bag) {
    const item = actorItem(name);
    grams += (item?.weight ?? 0) *
      (item?.ammo ? (actor.bagCount?.[name] ?? ammoStack(actor)) : 1);
  }
  for (const slot of SLOTS) {
    const item = actorItem(actor.equipment[slot]);
    grams += (item?.weight ?? 0) *
      (slot === "ammo" && item ? (actor.ammoCount ?? ammoStack(actor)) : 1);
  }
  return grams / 1000;
}
