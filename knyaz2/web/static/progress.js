// Опыт, уровни и прокачка — правила движка, приехавшие в паке.
//
// Опыт копится в юните (unit+0x22), порог следующего уровня в unit+0x2A,
// уровень — байт unit+0xF3. Порог уровня N это сумма i*100 (VA 0x41AA34),
// за уровень дают 25 свободного опыта (unit+0x48, VA 0x413157), и он же
// тратится на характеристики и навыки: характеристика стоит 2 и растёт до
// 150 (VA 0x4131FC), навык стоит 1 и растёт до предела «Обучаемость/4 плюс
// профильные слагаемые», но не выше 100 (VA 0x413268).
//
// За убитого дают взвешенную сумму его характеристик и брони (VA 0x41B044),
// а убийце достаётся её четверть (VA 0x414150).
import { hero } from "./hero.js";
import { world } from "./world.js";
import { actorItem } from "./actor.js";

function rules() { return hero.data?.rules?.progression ?? null; }

// Стартовый герой — настоящий, из GAME.0: характеристики, навыки, здоровье,
// свободный опыт и снаряжение это запись юнита №0 стартового мира. NEWHERO.RES
// к этому отношения не имеет — там лежит только картинка экрана выбора.
export function progressSetup() {
  const config = rules();
  const names = config?.characteristics?.names ?? [];
  const skillNames = config?.skills?.names ?? [];
  const template = hero.data?.template ?? null;
  hero.level = template?.level ?? hero.level ?? 1;
  hero.experience = template?.experience ?? hero.experience ?? 0;
  hero.freeExperience = template?.free_xp ?? hero.freeExperience ?? 0;
  // Два массива, как в юните движка: базовые (+0xC0) сверяет потолок
  // прокачки (VA 0x413214), текущие (+0xCC) читают пределы навыков и вся
  // арифметика боя; расходятся они на прибавках надетых чар (VA 0x41C494).
  hero.characteristics = template?.current
    ? [...template.current]
    : template?.characteristics
      ? [...template.characteristics]
      : hero.characteristics ?? new Array(names.length || 6).fill(10);
  hero.baseCharacteristics = template?.characteristics
    ? [...template.characteristics]
    : hero.baseCharacteristics ?? null;
  hero.skills = skillNames.map((name, index) =>
    template?.skills?.[name] ?? hero.skills?.[index] ?? 0);
  hero.nextLevel = levelThreshold(hero.level);
  // ОБЛИК — из того же шаблона: лицо (+0xF0 портрета), тело (+0x17) и
  // палитра (+0x2E). Стартовых героев шесть, и у каждого свой набор; без
  // этих трёх полей клиент искал слои тела по `undefined` и рисовал
  // болванчика, а панель показывала лицо героя мира 0.
  hero.face = template?.face ?? hero.face ?? 0;
  hero.body = template?.body ?? hero.body ?? 0;
  hero.palette = template?.palette ?? hero.palette ?? 0;
  // Деньги — кошелёк героя (+0x26 его записи), общий на весь отряд.
  hero.money = template?.money ?? hero.money ?? 0;
  // Отряд: герой первым, дальше спутники; вместимость — из записи отряда.
  hero.party = template?.party ?? hero.party ?? null;
}

// Характеристики движка в боевые поля: Ловкость даёт парирование, а
// Выносливость делит урон (VA 0x41BFB2 и 0x41C03C).
//
// Точности здесь нет намеренно: в движке это не поле юнита, а результат
// VA 0x41ADD8, который считается на каждый удар из навыка владения тем, что
// сейчас в руке. Считает её statsOf в combat.js.
export function heroCombatStats() {
  const template = hero.data?.template ?? null;
  const names = rules()?.characteristics?.names ?? [];
  const value = (name) => hero.characteristics?.[names.indexOf(name)] ?? 10;
  const stats = {
    parry: value("Ловкость"),
    toughness: value("Выносливость"),
  };
  // Здоровье и своя броня — поля юнита (+0x4E и +0xF4) из GAME.0. Если
  // шаблона нет, оставляем то, что уже посчитал statsOf, а не выдумываем.
  if (template?.health != null) stats.health = template.health;
  if (template?.armour != null) stats.armour = template.armour;
  return stats;
}

export function levelThreshold(level) {
  const table = rules()?.level_thresholds ?? [];
  if (level <= table.length) return table[level - 1];
  let total = 0;
  for (let i = 1; i <= level; i += 1) total += i * 100;
  return total;
}

// Навыки жертвы по её же предметам (VA 0x41B4CC, режимы 0 и 1): ближний —
// по семейству «вида на земле» и слою предмета основной руки (двуручность
// со слоя 0x0D), пустая рука — рукопашный; стрелковый — арбалет по слою
// 0x15, иначе лук, и с пустым метательным гнездом тоже лук.
function victimSkills(unit) {
  const accuracy = hero.data?.rules?.accuracy;
  const names = accuracy?.skill ?? {};
  const skills = unit.skills ?? [];
  const weapon = actorItem(unit.equipment?.hand);
  let melee = names.hand ?? 0;
  if (weapon?.layer) {
    const two = weapon.layer >= (accuracy?.two_hand_from_layer ?? 13);
    if (weapon.ground_sprite === accuracy?.ground?.blade) {
      melee = two ? names.two_sword : names.sword;
    } else if (weapon.ground_sprite === accuracy?.ground?.axe) {
      melee = two ? names.two_axe : names.axe;
    } else {
      melee = two ? names.two_club : names.club;
    }
  }
  const thrown = actorItem(unit.equipment?.ranged);
  const ranged = thrown?.layer === accuracy?.crossbow_layer
    ? (names.crossbow ?? 9) : (names.bow ?? 10);
  return { melee: skills[melee] ?? 0, ranged: skills[ranged] ?? 0 };
}

// Опыт за убитого (VA 0x41B044). Ветки две и они разные: у зверя
// (unit+0x1A & 0x40) считаются только характеристики и броня, у человека
// добавляются владение оружием ближнего боя (×1.2, выбор навыка по предмету
// в руке ЖЕРТВЫ), стрелковый навык (×1.8) и — вне режима стрельбы, с
// занятой рукой — 0.2 защиты класса предмета руки (VA 0x41B188).
export function killExperience(unit) {
  const config = rules();
  const beast = Boolean(unit.beast);
  const weights = (beast ? config?.kill_xp_weights : config?.kill_xp_weights_human)
    ?? { parry: 0.2, strength: 0.3, endurance: 0.3, armour: 0.1,
         melee_skill: 1.2, ranged_skill: 1.8 };
  const stats = unit.stats ?? {};
  let total = (stats.parry ?? 0) * weights.parry +
    (stats.strength ?? stats.power ?? 0) * weights.strength +
    (stats.toughness ?? 0) * weights.endurance;
  if (!beast) {
    const held = victimSkills(unit);
    total += held.melee * (weights.melee_skill ?? 1.2) +
      held.ranged * (weights.ranged_skill ?? 1.8);
  }
  total += (world.armourOf?.(unit) ?? stats.armour ?? 0) * weights.armour;
  if (!beast && !unit.rangedMode) {
    const hand = actorItem(unit.equipment?.hand);
    if (hand) total += (hand.power ?? 0) * (config?.kill_xp_weapon_weight ?? 0.2);
  }
  // fistp округляет к ближайшему; нижней границы в движке нет.
  return Math.round(total);
}

// Начислить опыт и поднять уровни, пока хватает порога (VA 0x413110).
// Это ОБЩЕЕ ядро всех источников опыта: убийств, наград разговора
// (обработчик 51, VA 0x434504 зовёт его напрямую), зелий и порошков.
// Сумма не больше 2000 умножается на «настройка + 2» из KONUNG2.CFG;
// четверти убийцы здесь нет — она живёт только в путях убийства
// (killShare) и берётся ДО множителя.
export function grantExperience(unit, amount) {
  const config = rules();
  // Фолбэк настройки — 0: столько ставит движок, когда KONUNG2.CFG нет
  // (VA 0x42EBD0), то есть минимальный множитель «настройка + 2» = 2.
  const multiplier = config?.xp_multiplier ?? { at_most: 2000, setting: 0 };
  let gained = Math.trunc(amount);
  if (gained <= (multiplier.at_most ?? 2000)) {
    gained *= (multiplier.setting ?? 0) + 2;
  }
  unit.experience = (unit.experience ?? 0) + gained;
  let levels = 0;
  while (unit.experience >= levelThreshold(unit.level ?? 1)) {
    unit.level = (unit.level ?? 1) + 1;
    unit.freeExperience = (unit.freeExperience ?? 0) +
      (config?.free_xp_per_level ?? 25);
    levels += 1;
  }
  unit.nextLevel = levelThreshold(unit.level ?? 1);
  // Фанфара уровня — сигнал из самого ядра, как в движке: 0x413110 после
  // цикла уровней играет звук (слот 14) ТОЛЬКО когда юнит одной стороны с
  // игроком (сравнение байтов +0x1B, VA 0x41319C).
  if (levels > 0 && (unit.side ?? 0) === (hero.side ?? 0)) {
    world.onLevelUp?.(unit, levels);
  }
  return { gained, levels };
}

// Доля убийцы: четверть с усечением к нулю и БЕЗ минимума (VA 0x414150,
// идиома sar eax,2 внутри 0x413894 и 0x41FDD0).
export function killShare(amount) {
  return Math.trunc(amount / (rules()?.kill_xp_share ?? 4));
}

export function characteristicCost() { return rules()?.characteristics?.cost ?? 2; }
export function skillCost() { return rules()?.skills?.cost ?? 1; }

// Замок прокачки: пока unit+0x4A не ноль, ничего поднять нельзя — это первая
// же проверка обеих функций (VA 0x4131FC и 0x413268).
function progressLocked(unit) { return Boolean(unit.progressLock); }

// ПРОКАЧИВАЕТСЯ ТОТ, КТО НА ЭКРАНЕ. В движке обе функции получают юнита
// указателем 0x849514 (первый выбранный, VA 0x42A8F4 зовёт их с ним же),
// и свободный опыт у каждого юнита свой (+0x48). Герой — лишь значение
// по умолчанию, как в inventory.js.

// Потолок характеристики движок сверяет с БАЗОВЫМ значением (unit+0xC0+i),
// а не с текущим, которое показывает панель (VA 0x413214).
export function canRaiseCharacteristic(index, unit = hero) {
  if (progressLocked(unit)) return false;
  const config = rules()?.characteristics;
  const cap = config?.cap ?? 150;
  const base = unit.baseCharacteristics?.[index] ?? unit.characteristics?.[index] ?? 0;
  return (unit.freeExperience ?? 0) >= characteristicCost() && base < cap;
}

// `creation` — поднимаем на экране СОЗДАНИЯ героя. Только там движок ведёт
// счётчики прибавок (0x8442D8) и только там разрешён откат: игровой
// обработчик 0x421690 знает лишь ветку поднятия и счётчиков не касается,
// поэтому поднятое в игре окончательно.
export function raiseCharacteristic(index, unit = hero, { creation = false } = {}) {
  if (!canRaiseCharacteristic(index, unit)) return false;
  unit.characteristics[index] += 1;
  if (unit.baseCharacteristics) unit.baseCharacteristics[index] += 1;
  unit.freeExperience -= characteristicCost();
  if (creation) {
    unit.raisedCharacteristics = unit.raisedCharacteristics ?? new Array(6).fill(0);
    unit.raisedCharacteristics[index] += 1;
  }
  return true;
}

// ОТКАТ ПОДНЯТОГО. Движок помнит, сколько раз характеристику и навык
// подняли «в этом заходе» (байтовые счётчики 0x8442D8[6] и 0x8442E0[20]),
// и знак «−» отдаёт шаг назад: значение −1, опыт обратно, счётчик −1
// (VA 0x438A00, ветки кодов 0x0C…0x11 и 0x26…0x39).
export function canLowerCharacteristic(index, unit = hero) {
  return (unit.raisedCharacteristics?.[index] ?? 0) > 0;
}

export function lowerCharacteristic(index, unit = hero) {
  if (!canLowerCharacteristic(index, unit)) return false;
  unit.characteristics[index] -= 1;
  if (unit.baseCharacteristics) unit.baseCharacteristics[index] -= 1;
  unit.freeExperience = (unit.freeExperience ?? 0) + characteristicCost();
  unit.raisedCharacteristics[index] -= 1;
  // Понижение роняет пределы: движок сразу срезает навыки, переросшие
  // свой потолок (VA 0x438A00:487 -> 0x437C48).
  trimOvergrownSkills(unit);
  return true;
}

export function canLowerSkill(index, unit = hero) {
  return (unit.raisedSkills?.[index] ?? 0) > 0;
}

export function lowerSkill(index, unit = hero) {
  if (!canLowerSkill(index, unit)) return false;
  unit.skills[index] -= 1;
  unit.freeExperience = (unit.freeExperience ?? 0) + skillCost();
  unit.raisedSkills[index] -= 1;
  return true;
}

// Автосброс переросших навыков (VA 0x437C48): для каждого навыка, пока
// есть поднятия «этого захода», шаг назад с возвратом опыта; как только
// поднять снова МОЖНО (навык упал ниже предела), последний шаг
// возвращается — навык остаётся ровно на пределе, счётчик хранит
// несрезанный остаток.
export function trimOvergrownSkills(unit = hero) {
  const raised = unit.raisedSkills;
  if (!raised) return 0;
  let trimmed = 0;
  for (let index = 0; index < raised.length; index += 1) {
    while ((raised[index] ?? 0) > 0) {
      unit.freeExperience = (unit.freeExperience ?? 0) + skillCost();
      unit.skills[index] -= 1;
      if (canRaiseSkill(index, unit)) {
        unit.freeExperience -= skillCost();
        unit.skills[index] += 1;
        break;
      }
      raised[index] -= 1;
      trimmed += 1;
    }
  }
  return trimmed;
}

// Предел роста навыка (VA 0x413268). Основа у всех одна — Обучаемость >> 2,
// дальше вид выражения из таблицы пака: среднее характеристик прибавляется
// к основе (avg), «Смертельный удар» берёт половину суммы с основой (half),
// а умственные навыки — удвоенную (double). Все деления целочисленные,
// характеристики читаются ТЕКУЩИЕ (+0xCC…+0xD1).
export function skillLimit(index, unit = hero) {
  const config = rules()?.skills;
  const rule = config?.limits?.[index];
  if (!config || !rule) return 0;
  const skills = unit.skills ?? [];
  const prereq = rule.prereq;
  // Пока ни один из перечисленных навыков не дорос до порога — отказ.
  if (prereq && prereq.skills.every((i) => (skills[i] ?? 0) < prereq.threshold)) {
    return 0;
  }
  const learning = config.learning ?? { index: 3, divisor: 4 };
  const base = Math.floor((unit.characteristics?.[learning.index] ?? 0) / learning.divisor);
  const chars = rule.chars ?? [];
  const total = chars.reduce((sum, i) => sum + (unit.characteristics?.[i] ?? 0), 0);
  let limit;
  if (rule.kind === "half") limit = Math.floor((total + base) / 2);
  else if (rule.kind === "double") limit = (total + base) * 2;
  else limit = base + Math.floor(total / (chars.length || 1));
  return Math.min(limit, config.cap ?? 100);
}

export function canRaiseSkill(index, unit = hero) {
  if (progressLocked(unit)) return false;
  return (unit.freeExperience ?? 0) >= skillCost() &&
    (unit.skills?.[index] ?? 0) < skillLimit(index, unit);
}

// `creation` — то же, что у характеристики: счётчик 0x8442E0 ведётся только
// на экране создания героя.
export function raiseSkill(index, unit = hero, { creation = false } = {}) {
  if (!canRaiseSkill(index, unit)) return false;
  unit.skills[index] += 1;
  unit.freeExperience -= skillCost();
  if (creation) {
    unit.raisedSkills = unit.raisedSkills ?? new Array(20).fill(0);
    unit.raisedSkills[index] += 1;
  }
  return true;
}

// Начать «заход» создания героя: счётчики прибавок обнуляются, как это
// делает выбор архетипа (0x4387CC обнуляет 0x8442D8 на шесть байт и
// 0x8442E0 на двадцать). Двадцать — ровно столько навыков перебирает
// каскадный возврат 0x437C48, поэтому длину задаём явно.
export function creationReset(unit = hero) {
  unit.raisedCharacteristics = new Array(6).fill(0);
  unit.raisedSkills = new Array(20).fill(0);
  // СНАРЯЖЕНИЕ ОЧИЩАЕТСЯ. Та же 0x4387CC следом за счётчиками обнуляет
  // десять байт по +0x58 — это гнёзда экипировки юнита:
  //     FUN_00442c10(_DAT_0084951c + 0x58, 0, 10);
  // То есть выбранный герой начинает БЕЗ ВЕЩЕЙ, что бы ни лежало в его
  // записи GAME.x. Снаряжение, которое рисует экран создания, движок пишет
  // отдельно, прямо в таблицу предметов (0x6F957C…), — это витрина, а не
  // карманы героя.
  if (unit.equipment) {
    for (const slot of Object.keys(unit.equipment)) unit.equipment[slot] = null;
  }
  unit.ammoCount = null;
  return unit;
}
