// Отрава и зелья.
//
// В движке отрава — не состояние «отравлен», а ЧИСЛО в юните (unit+0x52).
// Приходит оно от оружия: у предмета своя отрава в записи (+0x0C), у стрел
// она едет в снаряде (+0x16), у твари это её собственная (unit+0xF6). При
// удачном попадании расчёт урона просто прибавляет её цели.
//
// Действует отрава в мировом такте (VA 0x41C944): у кого число не ноль,
// тот каждый такт теряет столько же здоровья, и на нуле умирает. Такт не
// каждый кадр — тело функции работает при `счётчик кадров & 0x0F == 0`,
// то есть каждый шестнадцатый.
//
// Сама она не проходит: во всём коде отраву только прибавляют. Снимает
// единственно противоядие (класс 88).
import { world } from "./world.js";
import { hero } from "./hero.js";
import { units } from "./units.js";
import { buildingsTick } from "./buildings.js";
import { unitFighting } from "./warband.js";
import { grantExperience } from "./progress.js";
// движковый ROUND (0x442BF0) — fistp, округление к чётному
import { roundHalfEven } from "./round.js";

function rules() { return world.map?.hero?.rules?.effects ?? null; }

export function poisonTickEvery() { return rules()?.poison?.tick_every ?? 16; }
export function healthMax() { return rules()?.health?.max ?? 1600; }
export function potionClasses() { return rules()?.potions ?? {}; }

// Отравить: число складывается с тем, что уже есть.
export function poisonAdd(target, amount) {
  if (!amount || target?.alive === false) return false;
  target.poison = (target.poison ?? 0) + amount;
  return true;
}

// Чем отравлено оружие. Записей предметов у нас нет — есть надетое, и
// отраву на нём держим рядом со слотом, как её держит запись предмета.
export function weaponPoison(actor, ranged = false) {
  if (actor.venom) return actor.venom;                  // своя отрава твари
  const on = actor.poisonOn ?? {};
  return (ranged ? on.ammo : on.hand) ?? 0;
}

//: Счётчик кадров главного цикла — тот самый, по которому движок решает,
//: пора ли миру шевелиться.
let frames = 0;

// Мировой такт: у отравы и у построек РАЗНЫЕ фазы одного счётчика кадров
// (VA 0x41C944). Отрава бьёт, когда `счётчик & 0xF == 0`, а стройка и
// пожар — в else-ветке, когда `(счётчик + 7) & 0xF == 0`, то есть на
// кадрах, сдвинутых на девять. Период у обоих шестнадцать, но совпасть
// они не могут никогда, и это не мелочь: постройка, догоревшая в том же
// кадре, в котором отрава добила её работника, вела бы себя иначе.
export function effectsTick() {
  frames += 1;
  let changed = false;
  const period = poisonTickEvery();
  if (frames % period === 0) {
    for (const unit of [hero, ...units]) {
      if (expireTemporary(unit)) changed = true;
      const poison = unit.poison ?? 0;
      if (!poison || unit.alive === false) continue;
      changed = true;
      world.onPoisonDamage?.(unit, poison);
    }
  } else if ((frames + BUILD_PHASE_SHIFT) % period === 0) {
    if (buildingsTick(workersOf())) changed = true;
  }
  return changed;
}

// Срок временного зелья: счётчик unit+0x4A тикает вниз, и на нуле движок
// возвращает шесть спрятанных характеристик из unit+0xC6 обратно в +0xC0.
// Пока он не ноль, прокачка заперта — та же проверка стоит первой в обеих
// функциях роста (VA 0x4131FC и 0x413268).
function expireTemporary(unit) {
  if (!unit.potionTicks) return false;
  unit.potionTicks -= 1;
  unit.progressLock = unit.potionTicks > 0;
  if (unit.potionTicks > 0) return false;
  const saved = unit.savedCharacteristics;
  if (saved) {
    unit.baseCharacteristics = [...saved];
    if (unit.characteristics) unit.characteristics = [...saved];
    unit.savedCharacteristics = null;
  }
  return true;
}

//: Сдвиг фазы построек относительно отравы (VA 0x41C944: `+ 7 & 0xF`).
const BUILD_PHASE_SHIFT = 7;

//: Сколько СВОБОДНЫХ рук на стройке (VA 0x41C944): жители поселения минус
//: те, кто уже занят на другой работе. Нижней границы у движка нет — при
//: нуле работа просто стоит, поэтому Math.max(1, …) здесь был бы враньём.
function workersOf() {
  const living = units.filter((unit) => unit.alive !== false && !unitFighting(unit));
  const busy = living.filter((unit) => unit.working).length;
  return living.length - busy;
}

// Крепость зелья — поле +0x04 его ЗАПИСИ, и это она тратится, а не «выпил
// и пусто». Клиент держит её при самой банке; когда её нет, берётся полная
// прочность класса.
function strengthOf(item, state) {
  if (state && typeof state.strength === "number") return state.strength;
  return item?.durability ?? 0;
}

// Выпить зелье (VA 0x41D954). Возвращает, чем оно стало: пустой банкой —
// или ничем, если действия у класса нет. `state` — запись самой банки,
// в неё же пишется остаток крепости.
export function potionDrink(item, target = hero, state = null) {
  const codes = potionClasses();
  const numbers = codes.numbers ?? {};
  const kind = item?.index;
  if (!kind || kind < (codes.first ?? 84)) return null;
  let strength = strengthOf(item, state);
  let spent = 0;                    // порог, ниже которого банка пустеет
  switch (kind) {
    case codes.halve:                                   // Непонятная смесь
      target.health = Math.max(1, Math.floor(target.health / 2));
      return codes.empty ?? 83;                         // тратится целиком
    case codes.heal: {                                  // Лечебный бальзам
      // Цена лечения растёт с раной: (100 − здоровье/16) * 0.1, но не
      // больше остатка крепости. Каждая единица даёт 160 здоровья.
      // Движок хранит цену ОДИНАРНОЙ точностью (0x41DA19 fstp dword) —
      // повторяем fround; округление итога — ПОСЛЕ сложения, кламп 1600
      // ПОСЛЕ округления (0x41DA44…0x41DA55), крепость убывает на цену.
      const health = target.health ?? 0;
      const divisor = codes.heal_divisor ?? 16;
      let cost = Math.fround(
        ((numbers.heal_base ?? 100) - Math.trunc(health / divisor)) *
        (numbers.heal_step ?? 0.1));
      if (cost > strength) cost = strength;
      target.health = Math.min(healthMax(),
        roundHalfEven(health + cost * (numbers.heal_gain ?? 160)));
      strength -= cost;
      spent = numbers.heal_spent ?? 0.01;
      break;
    }
    case codes.poison:                                  // Яд, выпитый сам
      // Ветка без предмета-цели пишет unit+0x52 напрямую: округлённую
      // крепость самой бутылки, не силу класса и не сумму со старым ядом.
      target.poison = roundHalfEven(strength);
      return codes.empty ?? 83;
    case codes.antidote: {                              // Противоядие
      // Снимает долю отравы: отрава * 0.1, но не больше остатка крепости;
      // единица крепости стоит десяти отравы.
      const poison = target.poison ?? 0;
      let cost = poison * (numbers.antidote_step ?? 0.1);
      if (cost > strength) cost = strength;
      const left = roundHalfEven(poison - cost * (numbers.antidote_gain ?? 10));
      target.poison = left < 0 ? 0 : left;
      strength -= cost;
      spent = numbers.antidote_spent ?? 0.01;
      break;
    }
    case codes.booze:
    case codes.brew:
    case codes.tear:
    case codes.wisdom:
      // Временные зелья тратятся целиком и работают по общему кругу.
      return temporaryPotion(kind, target, strength) ? (codes.empty ?? 83) : null;
    default:
      return null;                                      // остальные ещё не читаны
  }
  if (state) state.strength = strength;
  // Пустой банка становится ТОЛЬКО когда крепости не осталось.
  return strength <= spent ? (codes.empty ?? 83) : null;
}

// Временные зелья 89…92 (VA 0x41DC14…0x41DE20). Все четверо устроены
// одинаково: пока у юнита тикает прежнее зелье (unit+0x4A не ноль), новое
// не действует; перед первым движок прячет шесть базовых характеристик в
// unit+0xC6, ставит срок и правит характеристики на «силу действия»,
// которая равна округлённой крепости.
function temporaryPotion(kind, target, strength) {
  const codes = potionClasses();
  const set = codes.temporary;
  const numbers = codes.numbers ?? {};
  if (!set) return false;
  let power = roundHalfEven(strength);
  if (kind === codes.booze) {
    // У Браги сила берётся из Ловкости, но не больше крепости.
    const dexterity = target.baseCharacteristics?.[1] ?? target.characteristics?.[1] ?? 0;
    power = Math.trunc(dexterity / (set.booze_divisor ?? 3));
    if (power > strength) power = roundHalfEven(strength);
  }
  if (kind === codes.wisdom && power < (set.wisdom_min ?? 6)) return false;
  // Брага и Зелье при уже идущем зелье отказывают вовсе, а Слеза и Мудрость
  // просто не перезаписывают спрятанные характеристики.
  const running = (target.potionTicks ?? 0) > 0;
  const strict = kind === codes.booze || kind === codes.brew;
  if (running && strict) return false;
  if (!running) target.savedCharacteristics = [...(target.baseCharacteristics ?? [])];
  const long = kind === codes.wisdom;
  target.potionTicks = power * (long ? (set.ticks_long ?? 60) : (set.ticks ?? 30));
  // Байт +0xF8 — временный бонус точности (его читает 0x41ADD8, пока
  // тикает +0x4A): все зелья кладут ноль, и только Чистая слеза —
  // round(sqrt(k) · 0.1); она же зажигает общее свечение (флаг 0x849610).
  if (kind === codes.tear) {
    target.look = roundHalfEven(Math.sqrt(power) * (set.tear_accuracy_scale ?? 0.1));
    world.glow = true;
  } else {
    target.look = 0;
  }
  const effect = set.effects?.[String(kind)] ?? {};
  for (const [index, per] of Object.entries(effect)) {
    const at = Number(index);
    const base = target.baseCharacteristics ?? target.characteristics;
    if (!base) continue;
    let value = (base[at] ?? 0) + per * power;
    // Пол «не ниже единицы» в движке есть ТОЛЬКО у Силы Эликсира
    // (0x41DE44: if < 1 -> 1); Брага роняет Ловкость без пола.
    if (kind === codes.wisdom && per < 0 && value < 1) value = 1;
    base[at] = value;
    if (target.characteristics && target.characteristics !== base) {
      target.characteristics[at] = value;
    }
  }
  if (kind === codes.brew) {
    target.health = Math.min(healthMax(),
      roundHalfEven(strength * (numbers.heal_gain ?? 160) + (target.health ?? 0)));
  }
  if (kind === codes.wisdom) {
    const drop = power * (set.wisdom_health_drain ?? 160);
    const floor = set.wisdom_health_floor ?? 160;
    target.health = Math.max(floor, (target.health ?? 0) - drop);
    // Опыт Эликсира — round(sqrt(k − 5) · 100): снято дизасмом хвоста ветки
    // (0x41DEAE: fild k−5; fsqrt-хелпер 0x442C6C; fmul double 100.0 по
    // 0x450243; ROUND) и идёт через общее ядро 0x413110 с его множителем.
    grantExperience(target, roundHalfEven(
      Math.sqrt(power - (set.wisdom_xp_shift ?? 5)) * (set.wisdom_xp_scale ?? 100)));
  }
  return true;
}

// ВИНО (класс 30, группа 11 — квестовый предмет): ветка 0x1E в 0x436C48 —
// Брага без крепости. Сила действия = trunc(Ловкость / 3), но не больше
// пяти; Ловкость падает втрое от силы, Харизма, Сила и Выносливость растут
// на силу, срок обычный (×30), бонус точности нулевой. При уже идущем
// зелье НЕ отказывает (в отличие от Браги) — просто не прячет
// характеристики второй раз. Полов у падения нет — байт как есть.
export function drinkWine(target = hero) {
  const codes = potionClasses();
  const set = codes.temporary;
  if (!set) return false;
  const wine = codes.wine ?? {};
  const base = target.baseCharacteristics ?? target.characteristics;
  if (!base) return false;
  let power = Math.trunc((base[1] ?? 0) / (set.booze_divisor ?? 3));
  if (power > (wine.power_cap ?? 5)) power = wine.power_cap ?? 5;
  const running = (target.potionTicks ?? 0) > 0;
  if (!running) target.savedCharacteristics = [...(target.baseCharacteristics ?? [])];
  target.potionTicks = power * (set.ticks ?? 30);
  target.look = 0;
  // прибавки те же, что у Браги: Ловкость −3, Харизма/Сила/Выносливость +1
  const effect = set.effects?.[String(codes.booze)] ?? { 0: 1, 1: -3, 4: 1, 5: 1 };
  for (const [index, per] of Object.entries(effect)) {
    const at = Number(index);
    const value = (base[at] ?? 0) + per * power;
    base[at] = value;
    if (target.characteristics && target.characteristics !== base) {
      target.characteristics[at] = value;
    }
  }
  return true;
}

// Намазать МАСЛОМ стрелы (VA 0x41D954, класс 87). Движок требует крепости
// не меньше десяти и цели-БОЕПРИПАСА (вид записи 0x0C), ставит ноль в поле
// +0x02 его записи — там, где у чистых стрел 0xFF, — и опустошает банку.
// Урона это не меняет: ноль читают только прицел и поджог (VA 0x428B88,
// 0x421690).
export function potionOil(item, ammoState = null, state = null) {
  const codes = potionClasses();
  const numbers = codes.numbers ?? {};
  if (item?.index !== codes.oil) return false;
  if (!ammoState) return false;
  if (strengthOf(item, state) < (numbers.oil_needs ?? 10)) return false;
  if (ammoState.kind !== (codes.ammo_kind ?? 0x0C)) return false;
  // Метка живёт в записи стрел и умирает вместе со стопкой.
  ammoState.oiled = true;
  return codes.empty ?? 83;
}

// Намазать ядом предмет (VA 0x41D954, класс 86 с указанной целью). Движок
// пишет отраву в запись ПРЕДМЕТА, годятся вид 0 (оружие) и 0x0C (стрелы),
// и опустошает банку. Если округление дало ноль, а крепости хватало, в
// запись всё равно идёт единица — намазанное не бывает бесполезным.
export function potionSmear(item, targetState, state = null) {
  const codes = potionClasses();
  const numbers = codes.numbers ?? {};
  if (item?.index !== codes.poison) return false;
  if (!targetState) return false;
  if (targetState.kind !== 0 && targetState.kind !== (codes.ammo_kind ?? 0x0C)) {
    return false;
  }
  const strength = strengthOf(item, state);
  let poison = roundHalfEven(strength);
  if (poison === 0 && strength >= (numbers.smear_spent ?? 0.01)) poison = 1;
  targetState.poison = poison;
  return codes.empty ?? 83;
}
