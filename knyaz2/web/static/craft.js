// Варка снадобий и зачарование камнями.
//
// Место для этого — двенадцатое гнездо окна снаряжения (код мыши 0x1C).
// Подсказка у него своя: «Здесь можно смешивать волшебные снадобья и
// вкладывать волшебные камни в оружие или доспехи». Кладут туда вещь, а
// потом роняют на неё вторую.
//
// Камень (вид 0x0B, классы 52…56) поднимает свою группу прибавок на
// «навык Волхование, делённый на 16», но не выше шестого уровня, и только
// у ОПОЗНАННОЙ носимой вещи (VA 0x436C48). Зелье, вылитое на зелье,
// ищется в таблице рецептов, а не нашлось — выходит «Непонятная смесь»
// (VA 0x41B930).
import { world } from "./world.js";
import { hero } from "./hero.js";
import { actorItem, actorReclassItemRef } from "./actor.js";

function rules() { return world.map?.hero?.rules?.craft ?? null; }

export function mixingSlot() { return rules()?.slot ?? null; }

// Найти класс предмета по имени — рецепты записаны номерами классов.
function classOf(name) { return actorItem(name)?.index ?? null; }

function nameOfClass(number) {
  const items = world.map?.items ?? {};
  for (const [name, item] of Object.entries(items)) {
    if (item.index === number) return name;
  }
  return null;
}

// Камень ли это и какую группу он поднимает.
export function stoneGroup(name) {
  const set = rules()?.stones;
  const index = classOf(name);
  if (!set || index == null) return null;
  const shift = set.groups[String(index)];
  return shift === undefined ? null : shift;
}

// Вложить камень в надетую вещь. Возвращает новое слово прибавок или null.
// Цель камня — ЛЮБАЯ запись предмета, а не только надетая вещь: в движке
// камень кладут на вещь в гнезде смешивания (VA 0x436C48 принимает запись
// от щелчка в 0x421690). Условий всего два: вид записи не больше восьми и
// вещь опознана. Поэтому `slot` может называть и гнездо, и ячейку мешка.
export function craftStone(slot, stoneName, actor = hero, target = null) {
  const set = rules()?.stones;
  const enchant = world.map?.hero?.rules?.jewellery?.enchant;
  const shift = stoneGroup(stoneName);
  if (!set || !enchant || shift === null) return null;
  const word = target?.enchant ?? actor.enchant?.[slot] ?? 0;
  if (word & enchant.dormant) return null;              // неопознанное не берёт
  const item = target?.item ?? actorItem(actor.equipment?.[slot]);
  if (!item || (item.kind ?? 99) > set.wearable_kind_max) return null;
  const level = (word >> shift) & 0x7;
  if (level >= set.level_max) return null;              // выше шестого не поднять
  const step = Math.floor((actor.skills?.[set.skill] ?? 0) / set.divisor);
  const raised = Math.min(set.level_max, level + step);
  const next = (word & ~(0x7 << shift)) | (raised << shift);
  if (target) target.enchant = next;
  else {
    actor.enchant = actor.enchant ?? {};
    actor.enchant[slot] = next;
  }
  return next;
}

// Точильный камень (класс 51, VA 0x432DE0): работает по всем пяти носимым
// видам записи. Потолок кузнеца = навык «Кузнечное дело» × 2; максимум
// прочности выше потолка деградирует к нему на 30 % разницы за одно
// применение; прочность чинится до максимума, удачная починка учит: навык
// +1, пока рост был и навык меньше ста. Прочность вещи живёт в
// actor.wear[имя], её максимум — в actor.wearMax[имя] (изначально —
// durability класса из пака).
// ``owner`` отделён от ``actor`` не для удобства: в движке прочность живёт в
// САМОЙ записи вещи (массив 0x6F956C), поэтому чинящий и владелец — разные
// юниты, и это видно в разговорном действии 65 (VA 0x4358BC зовёт
// repairweapon(собеседник, вещь бойца)). У нас прочность лежит у владельца,
// так что владельца приходится передавать отдельно; по умолчанию это сам
// чинящий — точильный камень в своих руках.
export function craftWhetstone(targetName, actor = hero, owner = actor) {
  const set = rules()?.whetstone;
  const item = actorItem(targetName);
  if (!set || !item) return false;
  if ((item.kind ?? 99) >= (set.target_kinds ?? 5)) return false;
  owner.wear = owner.wear ?? {};
  owner.wearMax = owner.wearMax ?? {};
  const skills = actor.skills ?? [];
  const skill = skills[set.skill ?? 17] ?? 0;
  const before = owner.wear[targetName] ?? item.durability ?? 0;
  let max = owner.wearMax[targetName] ?? item.durability ?? 0;
  const ceiling = skill * (set.ceiling_per_skill ?? 2);
  if (ceiling < max) max = ceiling + (max - ceiling) * (set.decay ?? 0.7);
  owner.wearMax[targetName] = max;
  owner.wear[targetName] = max;
  if (skill !== 0 && max - before > 0 && skill < 100) {
    skills[set.skill ?? 17] = skill + 1;
  }
  return true;
}

// Точило ли это.
export function isWhetstone(name) {
  return classOf(name) === (rules()?.whetstone?.class ?? 51);
}

// Сварить: что выйдет, если вылить одно зелье в другое.
export function craftMix(targetName, pouredName, actor = hero) {
  const set = rules()?.brew;
  if (!set) return null;
  const target = classOf(targetName);
  const poured = classOf(pouredName);
  if (target == null || poured == null) return null;
  const recipe = set.recipes.find(
    (row) => row.target === target && row.poured === poured);
  if (!recipe) {
    // Пары нет — выходит «Непонятная смесь», а посуда пропадает.
    return { result: nameOfClass(set.failed), left: null, skill: 0,
             how: null, failed: true };
  }
  if (recipe.skill && actor.skills) {
    actor.skills[set.skill] = Math.min(set.cap,
      (actor.skills[set.skill] ?? 0) + recipe.skill);
  }
  return {
    result: nameOfClass(recipe.result),
    left: recipe.left === null ? null : nameOfClass(recipe.left),
    skill: recipe.skill,
    // способ расчёта крепости — вызывающему (крепость до прибавки навыка)
    how: recipe.strength,
    failed: false,
  };
}

// Смешать две КОНКРЕТНЫЕ записи зелий. В отличие от craftMix, который
// выбирает только рецепт, этот слой сохраняет идентичность обеих записей и
// считает крепость до прибавки навыка (VA 0x41B930 из 0x41D954).
export function potionMix(targetName, pouredName, actor = hero,
                          targetStrength = null, pouredStrength = null) {
  const target = actorItem(targetName);
  const poured = actorItem(pouredName);
  const potionKind = world.map?.hero?.rules?.trade?.item_kinds?.potion ?? 9;
  const potions = world.map?.hero?.rules?.effects?.potions;
  const isPotion = (value) => value?.kind === potionKind ||
    (value?.index >= (potions?.empty ?? 83) && value?.index <= (potions?.wisdom ?? 92));
  if (!isPotion(target) || !isPotion(poured)) return null;
  const set = rules()?.brew;
  if (!set) return null;
  const skill = actor.skills?.[set.skill ?? 12] ?? 0;
  const mine = typeof targetStrength === "number"
    ? targetStrength : (target.durability ?? 0);
  const other = typeof pouredStrength === "number"
    ? pouredStrength : (poured.durability ?? 0);
  const mix = craftMix(targetName, pouredName, actor);
  if (!mix?.result) return null;
  return {
    kind: "brew",
    result: actorReclassItemRef(targetName, mix.result),
    left: mix.left ? actorReclassItemRef(pouredName, mix.left) : null,
    strength: mix.failed ? mine : brewStrength(mix.how, mine, other, skill),
    failed: mix.failed,
  };
}

// ГНЕЗДО СМЕШИВАНИЯ (двенадцатое гнездо окна, код мыши 0x1C). В него
// кладут вещь, а потом роняют вторую НА неё: камень 52…56 вкладывается в
// носимое (VA 0x436C48, случаи «4»…«8»), зелье варится с зельем
// (VA 0x41B930 из хвоста 0x41D954), точило чинит носимое (VA 0x432DE0).
// Слово чар цели живёт по имени вещи (bagEnchant), крепость зелья — здесь.
export const mixing = { name: null, strength: null };

export function mixingPlace(name, strength = null) {
  if (mixing.name || !name) return false;
  mixing.name = name;
  mixing.strength = strength;
  return true;
}

export function mixingTake() {
  if (!mixing.name) return null;
  const held = { name: mixing.name, strength: mixing.strength };
  mixing.name = null;
  mixing.strength = null;
  return held;
}

// Уронить вторую вещь на лежащую. Возвращает исход или null — пара не
// подошла, и вещь НЕ тратится (движок в этих ветках выходит нулём).
//
//     { kind: "stone", word }   камень вложен и съеден
//     { kind: "repair" }        точило сработало и съедено
//     { kind: "brew", result, left, failed }
//                               сварено: в гнезде результат, остаток
//                               (пустая банка) возвращается в руку
export function mixingApply(droppedName, actor = hero, droppedStrength = null) {
  if (!mixing.name) return null;
  const target = actorItem(mixing.name);
  if (!target) return null;
  if (stoneGroup(droppedName) !== null) {
    const holder = { item: target,
                     enchant: actor.bagEnchant?.[mixing.name] ?? 0 };
    const word = craftStone(null, droppedName, actor, holder);
    if (word === null) return null;
    actor.bagEnchant = actor.bagEnchant ?? {};
    actor.bagEnchant[mixing.name] = word;
    return { kind: "stone", word };
  }
  if (isWhetstone(droppedName)) {
    return craftWhetstone(mixing.name, actor) ? { kind: "repair" } : null;
  }
  const potionKind = world.map?.hero?.rules?.trade?.item_kinds?.potion ?? 9;
  const dropped = actorItem(droppedName);
  if (target.kind === potionKind && dropped?.kind === potionKind) {
    const mix = potionMix(mixing.name, droppedName, actor,
                          mixing.strength, droppedStrength);
    if (!mix) return null;
    mixing.name = mix.result;
    mixing.strength = mix.strength;
    return mix;
  }
  return null;
}

// Крепость сваренного — пятью способами, и выше пятнадцати не бывает.
export function brewStrength(how, mine, other, skill) {
  const set = rules()?.brew;
  if (!set) return mine;
  const kinds = set.how;
  let value = mine;
  if (how === kinds.from_skill) value = skill * set.step;
  else if (how === kinds.add_skill) value = mine + skill * set.step;
  else if (how === kinds.sum) value = mine + other;
  else if (how === kinds.min) value = Math.min(mine, other);
  else if (how === kinds.other_plus_skill) value = other + skill * set.step;
  // Результат каждого пути записывается обратно в `float` поля +4 записи
  // предмета (fstp dword в 0x41B930), поэтому двойную точность JS здесь
  // нельзя оставлять до следующего действия.
  return Math.fround(Math.min(set.max, value));
}

// ВЕЩЬ В ГНЕЗДЕ НЕ ВИДНА В МЕШКЕ (VA 0x420890 и 0x420E88).
//
// Гнездо смешивания вещь себе не забирает — она остаётся лежать в мешке, а
// гнездо только помечает её словом 0x849668. Чтобы она при этом не была в
// двух местах разом, движок везде считает её ячейку ПУСТОЙ: и предикат
// прокрутки пояса, и подсказка сравнивают запись с этим словом наравне с
// нулём.
//
// Без этого правила бета-тестер положил единственную банку в гнездо, увидел
// её же в поясе, взял оттуда и смешал саму с собой — банка застряла в гнезде
// навсегда.
//
// Сравниваем по ссылке на вещь. У движка это номер записи, то есть отдельный
// экземпляр; у нас две одинаковые неинстанцированные вещи делят одну ссылку,
// и такая пара спрячется целиком. Для этого нужны экземплярные ссылки на всё,
// а не только на переклассенное, — отдельная работа.
export function mixingHides(name) {
  return Boolean(name) && name === mixing.name;
}
