// Украшения — второй набор гнёзд.
//
// В юните это пять слов с +0xB6, сразу за мешком, и кладут туда по виду
// записи: вид 6 ожерелье (одно гнездо), вид 7 браслет (два), вид 8 кольцо
// (два) — VA 0x41E8D8.
//
// Носят их ради прибавок. В записи предмета есть слово +0x0E: пять
// значений по три бита, каждое — уровень от одного до шести, а величину
// берут из таблицы (VA 0x41C494). Характеристикам достаётся от +1 до +6,
// урону от +4 до +48. Старший бит слова означает, что магия НЕ ОПОЗНАНА:
// пока он стоит, прибавок нет вовсе.
import { world } from "./world.js";
import { hero } from "./hero.js";

function rules() { return world.map?.hero?.rules?.jewellery ?? null; }
function enchant() { return rules()?.enchant ?? null; }

export function jewelSlots() {
  return (rules()?.slots ?? []).map((slot) => slot.name);
}

// В какие гнёзда годится вещь этого вида.
export function slotsForKind(kind) {
  return rules()?.kinds?.[String(kind)] ?? [];
}

// Что даёт слово прибавок: поле -> величина. Неопознанное молчит.
export function enchantBonuses(word) {
  const set = enchant();
  if (!set || !word || (word & set.dormant)) return {};
  const out = {};
  for (const { shift, section } of set.groups) {
    const level = (word >> shift) & 0x7;
    // Отсева по верхней границе в движке нет — только «уровень не ноль».
    if (!level) continue;
    const row = set.table[section + level - 1];
    if (!row) continue;
    out[row.field] = (out[row.field] ?? 0) + row.value;
  }
  return out;
}

// Все прибавки надетого: движок складывает их со всех пяти гнёзд
// снаряжения и всех пяти украшений.
export function wornBonuses(actor = hero) {
  const total = {};
  for (const [, word] of Object.entries(actor.enchant ?? {})) {
    for (const [field, value] of Object.entries(enchantBonuses(word))) {
      total[field] = (total[field] ?? 0) + value;
    }
  }
  return total;
}

// Текущие характеристики: база плюс прибавка. В движке они лежат
// отдельным блоком (+0xCC), а не поверх базы (+0xC0).
export function currentCharacteristics(actor = hero) {
  const base = [...(actor.characteristics ?? [])];
  const bonus = wornBonuses(actor);
  for (const [field, value] of Object.entries(bonus)) {
    const index = Number(field) - 1;               // поля считаются с единицы
    if (index >= 0 && index < base.length) base[index] += value;
  }
  return base;
}

// Три поля юнита: броня (+0x42), сила удара (+0x44), точность (+0x46).
// Читают их те же расчёты, что и всё остальное, и у каждого свой бит
// байта +0xFA: стоит — прибавить, снят — заменить. В таблице все маски
// единичные, так что в игре прибавки складываются.
function fieldBonus(actor, name, fallback) {
  const fields = enchant()?.fields;
  return wornBonuses(actor)[String(fields?.[name] ?? fallback)] ?? 0;
}

export function bonusArmour(actor = hero) { return fieldBonus(actor, "armour", 7); }
export function bonusStrike(actor = hero) { return fieldBonus(actor, "strike", 8); }
export function bonusAccuracy(actor = hero) { return fieldBonus(actor, "accuracy", 9); }

// Цена вещи с её зачарованием: прибавки стоят денег, но только у
// опознанной (VA 0x41ABBC).
export function enchantPrice(word) {
  const set = enchant();
  if (!set || !word || (word & set.dormant)) return 0;
  let total = 0;
  for (const { shift, section } of set.groups) {
    const level = (word >> shift) & 0x7;
    // Верхней границы у движка нет: уровень 7 честно читает соседний
    // раздел таблицы (VA 0x41ABBC).
    if (level) total += set.table[section + level - 1]?.price ?? 0;
  }
  return total;
}

// Опознать всё, что при юните: движок снимает у вещей старший бит и за
// каждую поднимает навык «Идентификация предметов», но не выше сотни
// (VA 0x41B7C0).
export function identifyAll(actor = hero) {
  const set = enchant();
  if (!set) return 0;
  let opened = 0;
  // Движок обходит ЧЕТЫРЕ набора (VA 0x41B7C0): пять гнёзд снаряжения,
  // боеприпас, все сорок две ячейки мешка и пять украшений — и растит
  // навык за каждую открытую вещь. Гнёзда и украшения у нас в actor.enchant,
  // а слова вещей мешка живут отдельной картой по номеру ячейки.
  for (const [slot, word] of Object.entries(actor.enchant ?? {})) {
    if (!(word & set.dormant)) continue;
    actor.enchant[slot] = word & ~set.dormant;
    opened += 1;
  }
  const bag = actor.bagEnchant;
  if (bag) {
    for (const key of Object.keys(bag)) {
      const word = bag[key];
      if (!(word & set.dormant)) continue;
      bag[key] = word & ~set.dormant;
      opened += 1;
    }
  }
  return raiseSkill(actor, opened);
}

// Опознание у кучи: движок бросает по каждой неопознанной вещи и
// сравнивает с навыком (VA 0x4115AC). Удача открывает вещь и растит навык.
export function identifyRoll(actor = hero, word = 0,
                             roll = Math.floor(Math.random() * 100)) {
  const set = enchant();
  if (!set || !(word & set.dormant)) return word;
  const skill = actor.skills?.[set.identify.skill] ?? 0;
  if (roll >= skill) return word;
  raiseSkill(actor, 1);
  return word & ~set.dormant;
}

function raiseSkill(actor, opened) {
  const set = enchant();
  if (!opened || !set || !actor.skills) return opened;
  const at = set.identify.skill;
  actor.skills[at] = Math.min(set.identify.cap, (actor.skills[at] ?? 0) + opened);
  return opened;
}
