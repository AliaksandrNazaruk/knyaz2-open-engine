// Бой по правилам движка.
//
// Формула снята с кода, а не придумана. Удар считается в 0x41BF54:
//
//   1. промах:      rand() % 101 > точность атакующего (unit+0x1F)
//   2. парирование: rand() % 101 <= Ловкость цели (unit+0xCD) * 0.1
//   3. броня цели:  своя (unit+0xF4) плюс сила одежды, доспеха и щита
//                   (VA 0x41A414: поля +0x5A, +0x5C и +0x5E)
//   4. урон:        max(0, сила * 0.7 - броня) + сила * 0.3
//   5. итог:        ТРУНК( (урон / выносливость(unit+0xD1) + 1) * 16 )
//   6. здоровье:    i16 unit+0x4E; если здоровья не больше урона — смерть
//
// ПОРЯДОК В ПЯТОМ ШАГЕ ВАЖЕН, и раньше он был записан здесь неверно («round
// (...) * 16»). Дизассемблер 0x41C02C-0x41C05C: `fdivp; fld1; faddp; fmul
// qword [0x450150]; call 0x442BF0; fistp` — сперва делят на выносливость,
// прибавляют единицу, УМНОЖАЮТ на шестнадцать и лишь в самом конце усекают к
// нулю. Итог поэтому шестнадцати НЕ кратен: живой замер дал 24, 25, 26, 54,
// 56, 63, 68, 71, 76, 79, 89, 95, 99 — и все они больше или равны 16, как и
// требует формула при нулевом уроне. Сам код (ниже) всегда считал верно.
// Константы прочитаны из exe: 0x450138 = 0.1, 0x450140 = 0.7, 0x450148 = 0.3,
// 0x450150 = 16.
//
// Сила удара — поле +0x04 класса предмета (VA 0x41A59E), дальность боя —
// поле +0x10 (VA 0x414C01): у ближнего оружия 1 клетка, у составного лука
// 15, у длинного 18. Поэтому лучник и должен доставать издалека.
//
// Наше здесь только одно: значения характеристик юнитов. Они живут не в exe,
// а в состоянии игры (SAVE.RES), поэтому берутся из расстановки карты.
import { world } from "./world.js";
import { actorAttackPose, actorFrames, actorItem, actorItemName, actorReach,
         actorWeapon } from "./actor.js";
import { hero, heroAnchor, heroCellAt, heroFree, heroOrderTo,
         heroPlayAction, heroSetPose, heroDie } from "./hero.js";
import { actorInstanceMaps, cellRange, unitAt, unitDamage,
         units } from "./units.js";
import { unitFighting, warbandDeclare, warbandPlayerAttacks,
         warbandSwing, warbands } from "./warband.js";
import { isSelected, orderArrived, orderKinds, orderSelected,
         orderWaitTalk, selectionFallback,
         orderUnit, select, selection } from "./orders.js";
import { burstSpawn, burstsTick, projectileFire, projectilesTick } from "./projectiles.js";
import { roundHalfEven } from "./round.js";
import { loot, lootHidden, lootInNest, lootNear, lootSpeaker } from "./loot.js";
import { furnitureAt } from "./furniture.js";
import { tradeOpen } from "./trade.js";
//: Округление сопроцессора здесь больше не нужно: все расчёты боя движок
//: заканчивает усечением (0x442BF0), см. docs/COMBAT_SPEC.md, раздел 9б.
//: `roundHalfEven` остаётся верным для торговли, зелий и сроков работ.
import { identifyRoll } from "./jewels.js";
import { reputationKill, reputationValue } from "./reputation.js";
import { ammoSpend, ammoStack, weaponModeRefresh } from "./inventory.js";
import { healTriggerTick, healthMax, healthSet, poisonAdd,
         weaponPoison } from "./effects.js";
import { buildingAtCell, buildingIgnite } from "./buildings.js";
import { carryDrop, carrying } from "./carry.js";
import { bonusAccuracy, bonusArmour, bonusStrike,
         currentCharacteristics } from "./jewels.js";
import { dialogStart, hasTalk } from "./dialog.js";
import { grantExperience, heroCombatStats, killExperience, killShare,
         progressSetup } from "./progress.js";
import { sfxDeathCry, sfxHit, sfxHurtCry, sfxSwing } from "./sfx.js";

//: Константы формулы — из самого движка (0x450138, 0x450140, 0x450148, 0x450150).
const PARRY_SCALE = 0.1;
const ARMOUR_PART = 0.7;
const DIRECT_PART = 0.3;
const DAMAGE_SCALE = 16;

//: ОТДЕЛЬНОГО ТАКТА УДАРОВ У ГЕРОЯ НЕТ — он такой же юнит. Темп задаёт блок
//: замаха: 12 кадров по одному за такт плюс обратный отсчёт +0xFD на нулевом
//: кадре (0x413894:365,471 и 0x416B50, владелец правила — attackWait в
//: units.js). Мид-замах и без того закрыт проверкой `acting`, так что стоявшая
//: здесь HERO_COOLDOWN = 0.7 просто добавляла паузу поверх канонной.

export const combat = {
  target: null,        // враг, к которому идём
  pendingHit: null,
  pendingCast: null,   // намерение кастовать, ждёт кадра выстрела
  log: [],             // последние события боя, для отладки
};
//: Поля `pickup` больше нет: в него только писали, читателей не было —
//: подход к куче давно живёт приказом (orderKind take + walkToOrder).

// Характеристики по умолчанию — поля юнита движка, значения наши.
export const DEFAULT_STATS = {
  health: 600,        // +0x4E
  accuracy: 70,       // +0x1F точность, шанс не промахнуться
  parry: 20,          // +0xCD стойкость, из неё считается парирование
  toughness: 40,      // +0xD1 выносливость, делит урон
  armour: 4,          // +0xF4 своя броня, без экипировки
};

// Точность по VA 0x41ADD8. Порядок в движке жёсткий: навык оружия, потом
// штраф за дальность при стрельбе, потом прибавка зачарования — и ТОЛЬКО
// в самом конце зажим в [5, 95]. Клемп раньше времени съедал бы и штраф,
// и прибавку. Рука выбирается режимом (тот же параметр идёт в 0x41B4CC):
// "main" — основная, "off" — щитовое гнездо (слот 4 удара двумя руками).
export function statsOf(actor, distance = 0, hand = "main") {
  const rules = hero.data?.rules?.accuracy;
  const stats = { ...DEFAULT_STATS, ...(actor.stats ?? {}) };
  // Парирование и стойкость движок читает БАЙТАМИ ТЕКУЩЕГО блока на
  // каждый удар: +0xCD Ловкость (0x41C1F7, 0x41BFB7) и +0xD1 Выносливость
  // (0x41C03C) — с прибавками надетого, не снимок бута. У юнитов без
  // массива характеристик остаётся снимок пака (+0xCD/+0xD1 из GAME.x).
  if (actor.characteristics) {
    const current = currentCharacteristics(actor);
    if (current[1] != null) stats.parry = current[1];
    if (current[5] != null) stats.toughness = current[5];
  }
  // У зверей навыков нет: точность считается из Ловкости и под клемп
  // не попадает (VA 0x41ADED).
  if (actor.beast) {
    const beast = rules?.beast_accuracy ?? { factor: 0.5, base: 100 };
    const dexterity = stats.parry ?? 0;
    // ТРУНК, А НЕ ОКРУГЛЕНИЕ (VA 0x41AE16). Движок перед `fistp` зовёт
    // 0x442BF0, а тот ставит режим сопроцессора «к нулю» (старший байт
    // контрольного слова 0x1F, RC=11) и делает `frndint` — то есть отсекает
    // дробную часть. См. docs/COMBAT_SPEC.md, раздел 9б.
    stats.accuracy = Math.trunc(
      beast.base - (beast.base - dexterity * beast.factor) * beast.factor);
    return stats;
  }
  const skill = hand === "off"
    ? offHandAccuracy(actor)
    : weaponAccuracy(actor, distance);
  if (skill != null) stats.accuracy = skill;
  else if (!stats.accuracy) stats.accuracy = DEFAULT_STATS.accuracy;
  // Пока тикает зелье (+0x4A), прибавляется знаковый байт +0xF8
  // (VA 0x41ADF9): его пишут сами зелья — все ноль, Чистая слеза
  // round(sqrt(k)·0.1). Стоит В ЭТОМ месте: до чар, после навыка.
  if ((actor.potionTicks ?? 0) > 0) stats.accuracy += actor.look ?? 0;
  // прибавка зачарования — своим полем (unit+0x46)
  stats.accuracy += bonusAccuracy(actor);
  stats.accuracy = Math.min(rules?.cap ?? 0x5F,
    Math.max(rules?.floor ?? 5, stats.accuracy));
  return stats;
}

// Какой навык отвечает за оружие в руке — правило движка приезжает в паке.
// При стрельбе движок вычитает из навыка штраф `дистанция * 0.3 / дальность
// оружия` (VA 0x41AE7F), и только когда цель не вплотную. Возвращаем число
// БЕЗ зажима — его накладывает statsOf после всех прибавок.
export function weaponAccuracy(actor, distance = 0) {
  const rules = hero.data?.rules?.accuracy;
  const skills = actor === hero ? hero.skills : actor.skills;
  if (!rules || !skills) return null;
  const weapon = actorWeapon(actor);
  const ranged = Boolean(actor.rangedMode) && Boolean(actor.equipment?.ranged);
  const names = rules.skill;
  let index = names.hand;
  if (ranged) {
    index = weapon?.layer === rules.crossbow_layer ? names.crossbow : names.bow;
  } else if (weapon?.layer) {
    const two = weapon.layer >= rules.two_hand_from_layer;
    if (weapon.ground_sprite === rules.ground.blade) index = two ? names.two_sword : names.sword;
    else if (weapon.ground_sprite === rules.ground.axe) index = two ? names.two_axe : names.axe;
    else index = two ? names.two_club : names.club;
  }
  let value = skills[index] ?? 0;
  const reach = weapon?.range_cells ?? 0;
  if (ranged && distance && reach) {
    //: Тоже трунк (VA 0x41AEA7), а не округление — тот же 0x442BF0.
    value = Math.trunc(value - distance * (rules.range_penalty ?? 0.3) / reach);
  }
  return value;
}

// Точность ВТОРОЙ руки — третий режим 0x41B4CC: одноручный навык по
// семейству предмета щитового гнезда (пустое гнездо или предмет без атаки —
// рукопашный), умноженный на «Бой двумя руками» (unit+0xD3) и делённый на
// сто целочисленно. Клампы и чару накладывает общий statsOf, как 0x41ADD8.
export function offHandAccuracy(actor) {
  const rules = hero.data?.rules?.accuracy;
  const skills = actor === hero ? hero.skills : actor.skills;
  if (!rules || !skills) return null;
  const names = rules.skill;
  const item = actorItem(actor.equipment?.off_hand);
  let index = names.hand;
  if (item?.layer && (item.kind ?? 0) === 0) {
    if (item.ground_sprite === rules.ground.blade) index = names.sword;
    else if (item.ground_sprite === rules.ground.axe) index = names.axe;
    else index = names.club;
  }
  const both = skills[hero.data?.rules?.attack_by_item?.melee?.skill ?? 1] ?? 0;
  return Math.trunc(both * (skills[index] ?? 0) / 100);
}

// БОЙ НЕ ПЕРЕЕЗЖАЕТ С КАРТЫ НА КАРТУ. Здесь лежат прямые ссылки на юнитов:
// цель, начатый замах и намеченная куча. Юниты новой карты — другие объекты,
// и без сброса первый же кадр доводил бы удар по тому, кого мы покинули, а
// герой бежал бы к его прежним пикселям.
//
// В движке отдельного сброса не нужно: цель боя живёт в тех же полях приказа
// (`+0x10` и младшая половина `+0x16`), а расстановка отряда на новой карте
// гасит их всем — и вожаку тоже (`юнит[+0x16] &= 0xF0`, VA 0x415238:67 и 133).
// У нас эти поля разнесены по двум модулям, поэтому и сброса два: приказ
// чистит `partyRegroup`, ссылки боя — эта функция.
export function combatDropTargets() {
  combat.target = null;
  combat.pendingHit = null;
}

export function combatSetup() {
  progressSetup();
  // Список выбора пустым не бывает: сняв ПОСЛЕДНЕГО, движок кладёт туда
  // самого игрока (VA 0x43AE5C). Это правило только про опустевший список
  // — «герой выбран всегда» из него не следует: щелчок по спутнику
  // оставляет выбранным одного спутника, и приказы идут только ему.
  selectionFallback(hero);
  select(hero);
  // Характеристики героя — настоящие, из стартового мира GAME.0.
  const stats = { ...statsOf(hero), ...heroCombatStats() };
  hero.stats = stats;
  hero.health = stats.health;
  // ПОТОЛОК ЗДОРОВЬЯ ОДИН НА ВСЕХ — 0x640, то есть 1600. Движок жёстко
  // обрезает им любой пересчёт: `if (значение < 0x641) +0x4E = значение;
  // else +0x4E = 0x640` (VA 0x41C494), и такое же присваивание стоит в
  // лечении (0x4347D8). Персонального максимума в записи юнита нет.
  //
  // Раньше здесь стояло `maxHealth = stats.health`, и стартовое здоровье
  // становилось заодно и потолком. На Ратиборе это совпадало (у него ровно
  // 1600), а вот ЭЙНАР В GAME.2 НАЧИНАЕТ С 640 — раненым, — и порт показывал
  // его «полностью здоровым» 640 из 640.
  hero.maxHealth = healthMax();
  hero.alive = true;
  combatDropTargets();
  combat.log = [];
  world.armourOf = armourOf;
  // Приход по приказу — общий путь для героя и спутников (VA 0x4115AC).
  world.onUnitArrived = (unit) => unitArrived(unit);
  // Тревога: деревня ополчается на сторону поджигателя. Это ровно тот же
  // путь, что и обычный удар — отряду пишут врага и флаг боя (VA 0x4333A4),
  // а не каждому жителю по отдельности.
  world.onVillageAlarm = (culprit) => {
    // Ополчается ОДИН отряд — сторона деревни из байта +0x02 её записи, и
    // через общий путь объявления войны:
    //   FUN_004159dc(&DAT_0071e56c + village[2] * 0x80, стрелок+0x1B)
    //   (VA 0x41FDD0)
    // Перебор всех отрядов карты поднимал и нейтральных, и зверей на другом
    // конце карты, минуя гейт по боевым битам 0x4F внутри warbandDeclare.
    const side = world.map?.village?.side;
    if (side === undefined || side === null) return;
    const band = warbands.get(side);
    if (!band) return;
    if (warbandDeclare(band, culprit?.side ?? 0, units)) {
      combat.log.push("деревня подняла тревогу");
    }
  };
  // Отрава бьёт в мировом такте: просто убавляет здоровье, без отдачи —
  // движок только пересчитывает юнита и смотрит, не умер ли он.
  world.onPoisonDamage = (unit, poison) => {
    if (unit === hero) {
      healthSet(hero, hero.health - poison);
      if (hero.health <= 0) { hero.alive = false; heroDie(); }
      combat.log.push(`отрава: герой теряет ${poison}`);
      return;
    }
    unitDamage(unit, poison);
  };
  // Стартовое снаряжение героя — тоже из GAME.0.
  const template = hero.data?.template;
  if (template?.equipment && !hero.equipment?.hand) {
    for (const [slot, name] of Object.entries(template.equipment)) {
      if (!name) continue;
      const target = slot === "shield" ? "off_hand" : slot;
      if (target in hero.equipment) hero.equipment[target] = name;
    }
    // и чем он бьётся на старте — байт unit+0xEE того же юнита
    hero.rangedMode = Boolean(template.ranged_mode) && Boolean(hero.equipment.ranged);
  }
  if (template?.bag && !hero.bag?.some(Boolean)) hero.bag = [...template.bag];
  if (template) Object.assign(hero, actorInstanceMaps(template));
  // Поза трупа держится вечно и считается «занят действием», поэтому
  // поднимать героя, не сбросив её, — значит оставить его без ударов.
  if (!hero.data?.animations?.[hero.stance]?.[hero.pose]) heroSetPose("stand");
  // Юнит бьёт свою цель: чужой — героя или спутника, свой — врага.
  // РУКА ПРИХОДИТ ОТ КАДРА. Таблица 0x45FE90 у одноручного замаха даёт два
  // кадра: 7 — гнездо 0, 9 — гнездо 4. Бить обеими руками разом, как делал
  // `meleeStrikes`, теперь нельзя — вышло бы по четыре удара за замах.
  world.onUnitStrike = (unit, hand = "main") => {
    // Цель — из самого юнита. Запасной ход «бей героя» оставлен ТОЛЬКО
    // чужим: герой теперь бьёт этим же путём, и фолбэк на самого себя
    // означал бы самоудар.
    const target = unit.target ?? (unit === hero ? null : hero);
    if (!target) return "нет цели";
    // БРОСОК КИКИМОРЫ (VA 0x41BB10, ветка породы 0x53). Она единственная,
    // кому оружие для снаряда не нужно вовсе: условие запуска — «порода 0x53
    // ИЛИ в руке что-то есть». Её снаряд собирается по своим правилам:
    //
    //     отрава  = её собственная (+0xF6)
    //     точность = ЛОВКОСТЬ как есть (+0xCD), а не расчёт 0x41ADD8
    //     дальность = 0x28, константой, а не из таблицы классов
    //     сила    = ROUND(Сила(+0xD0) * 0.04 * здоровье(+0x4E) * 0.0625)
    //
    // Формулу силы Ghidra съела (FPU), снята дизассемблером 0x41BC21-0x41BC3D:
    // fild [Сила]; fmul 0.04; fild [здоровье]; fmulp; fmul 0.0625; fistp.
    // При полном здоровье 1600 это ровно «Сила × 4», а раненая кидает слабее.
    //
    // Движок пускает снаряд на кадре 8 её анимации, у нас — в общий миг
    // удара (кадр «всего − 2»): разница в пару кадров и не видна.
    if (kikimoraSpits(unit) && target) {
      const current = currentCharacteristics(unit);
      projectileFire(unit, target, current[1] ?? 0,
        { range_cells: KIKIMORA_RANGE },
        { strength: kikimoraStrength(unit, current), venom: unit.venom ?? 0,
          side: unit.side ?? 0 });
      combat.log.push(`${unit.name} кидается`);
      return "бросок";
    }
    // Стрельба: удар не приходит мгновенно — сначала летит стрела
    // (VA 0x41BB10 создаёт снаряд, а урон считается, когда он долетел).
    if (unit.rangedMode && unit.equipment?.ranged && target) {
      // Без боеприпаса выстрела НЕТ: запуск снаряда возвращает ноль, и
      // только при успехе такт вычитает стрелу (VA 0x4148E5: `call
      // 0x41bb10; test eax,eax; je ...`). Режим оружия при этом
      // пересчитывается — стрелок берётся за оружие руки (VA 0x412FF4).
      if (!unit.equipment.ammo) {
        weaponModeRefresh(unit);
        return "нечем стрелять";
      }
      const bow = actorItem(unit.equipment.ranged);
      projectileFire(unit, target,
        statsOf(unit, distanceCells(unit, target)).accuracy, bow,
        shotSnapshot(unit));
      // Стрелу тратит ЛЮБОЙ стрелок: расход лежит в такте анимации
      // (VA 0x413894, блоки лука и самострела), а не в геройской ветке.
      ammoSpend(unit);
      wearRanged(unit);
      combat.log.push(`${unit.name} стреляет`);
      return "выстрел";
    }
    const result = strike(unit, target, { hand });
    combat.log.push(`${unit.name} -> ${target === hero ? "герой" : target.name}: ${result}`);
    if (target !== hero && !target.alive) combat.log.push(`${target.name} убит`);
    return result;
  };
}

// Броня цели: своя плюс сила надетого — VA 0x41A414 складывает одежду,
// доспех и щит, каждый своим полем +0x04 класса предмета.
export function armourOf(actor) {
  const stats = statsOf(actor);
  let armour = stats.armour;
  for (const slot of ["body", "head"]) {
    armour += actorItem(actor.equipment?.[slot])?.power ?? 0;
  }
  // Второе гнездо прибавляется, ТОЛЬКО если там настоящий щит: движок
  // сверяет вид записи с четвёркой (VA 0x41A414), одежду и доспех — нет.
  // Порт сам разрешает одноручное оружие во второй руке при навыке «Бой
  // двумя руками», и без этой проверки меч силой 144 давал +144 брони.
  const second = actorItem(actor.equipment?.off_hand);
  const shieldKind = hero.data?.rules?.accuracy?.shield_kind ?? 4;
  if (second && (second.kind ?? -1) === shieldKind) armour += second.power ?? 0;
  // Зачарование добавляет броню отдельным полем (unit+0x42).
  return armour + bonusArmour(actor);
}

// Сила удара: поле +0x04 предмета, которым бьёмся. Чем именно — решает
// режим оружия (байт unit+0xEE), тот же, что выбирает и позу удара.
//
// У стрельбы сила считается иначе: запись снаряда несёт силу МЕТАТЕЛЬНОГО
// (+0x18), а расчёт умножает на неё силу БОЕПРИПАСА (VA 0x41A52C). Поэтому
// стрелы и стоят по единице силы: железная стрела 3 на составной лук 104
// даёт 312 — как удар топором.
// Прибавка от ТЕКУЩЕЙ Силы (+0xD0) и здоровья (0x41A7D0, В8): с оружием
// и у зверя round(Сила·0.04·здоровье·0.0625), голым кулаком сила =
// round(Сила·0.02·здоровье·0.0625) — вдвое слабее. Раненый бьёт слабее.
// У стрельбы члена НЕТ (0x41A52C: power снаряда × power метательного).
function mightTerm(actor, scale) {
  const set = hero.data?.rules?.accuracy?.strength_term;
  const strength = actor.characteristics
    ? (currentCharacteristics(actor)[4] ?? 0)
    : (actor.stats?.strength ?? 0);
  //: Трунк (VA 0x41A82D, 0x41A930, 0x41A96F — все три ветки силы). Здесь
  //: стоял roundHalfEven: он верен для голого `fistp`, но в бою перед ним
  //: идёт 0x442BF0 с режимом «к нулю».
  return Math.trunc(strength * scale * (actor.health ?? 0) *
    (set?.health ?? 0.0625));
}

export function strengthOf(actor, hand = "main") {
  const set = hero.data?.rules?.accuracy?.strength_term;
  const weaponScale = set?.weapon ?? 0.04;
  const fistScale = set?.fist ?? 0.02;
  // Зверь: сила целиком из Силы и здоровья оружейной мерой (0x41A808),
  // прибавка чар (+0x44) и кламп нулём — общие.
  if (actor.beast) {
    return Math.max(0, mightTerm(actor, weaponScale) + bonusStrike(actor));
  }
  // Удар второй рукой — сила предмета щитового гнезда: движок зовёт
  // 0x41A7D0 со слотом 4; пустое гнездо бьёт кулаком.
  if (hand === "off") {
    const shield = actorItem(actor.equipment?.off_hand);
    if (!shield) return Math.max(0, mightTerm(actor, fistScale) + bonusStrike(actor));
    return Math.max(0,
      (shield.power ?? 0) + mightTerm(actor, weaponScale) + bonusStrike(actor));
  }
  const weapon = actorWeapon(actor);
  if (actor.rangedMode && actor.equipment?.ranged) {
    const ammo = actorItem(actor.equipment?.ammo);
    return (ammo?.power ?? 0) * (weapon?.power ?? 0) + bonusStrike(actor);
  }
  // Пустая рука — кулак; с оружием прибавка ложится поверх power класса.
  if (!weapon) return Math.max(0, mightTerm(actor, fistScale) + bonusStrike(actor));
  return Math.max(0,
    (weapon.power ?? 0) + mightTerm(actor, weaponScale) + bonusStrike(actor));
}

// Дальность боя — из того же предмета: 1 клетка мечом, 15 составным луком.
// Разбор общий с юнитами и живёт в actor.js, чтобы обе стороны боя мерили
// дальность одинаково (в движке это один код для всех, VA 0x414AF8).
//: Порода Кикиморы и дальность её броска — константа 0x28 из 0x41BB10.
const BREED_KIKIMORA = 0x53;
const KIKIMORA_RANGE = 0x28;

//: Кидается ли эта тварь: только Кикимора, и оружие ей не нужно.
function kikimoraSpits(unit) {
  return ((unit?.breed ?? 0) & 0x7F) === BREED_KIKIMORA;
}

//: Сила её броска (0x41BC21: Сила * 0.04 * здоровье * 0.0625, округление
//: движковым ROUND к чётному).
function kikimoraStrength(unit, current) {
  const strength = current[4] ?? 0;
  return roundHalfEven(strength * 0.04 * (unit.health ?? 0) * 0.0625);
}

export function reachOf(actor) { return actorReach(actor); }

// Снять прочность с надетой вещи и, если она кончилась, сломать её.
//
// Прочность — float32 поле +0x04 записи предмета, поэтому результат
// прогоняется через Math.fround: иначе накопленная ошибка двойной точности
// уводит момент поломки. На нуле движок метит запись пустой и обнуляет
// гнездо (VA 0x41C194: `(&DAT_006f956c)[iVar2] = -1;` и `*(undefined2 *)
// (local_1c * 2 + param_1 + 0x58) = 0;`).
//
// Возвращает true, если вещь сломалась.
function wearSlot(actor, slot, amount) {
  const ref = actor.equipment?.[slot];
  const item = actorItem(ref);
  if (!ref || !item || !(amount > 0)) return false;
  actor.wear = actor.wear ?? {};
  const left = Math.fround((actor.wear[ref] ?? item.durability ?? 0) - amount);
  actor.wear[ref] = left;
  if (left > 0) return false;
  actor.equipment[slot] = null;
  delete actor.wear[ref];
  combat.log.push(`${actor === hero ? "У героя" : `У ${actor.name}`} сломалось: ${actorItemName(ref)}`);
  return true;
}

// Каждый выстрел изнашивает оружие на 0.1, и на нуле прочности оно
// ломается: движок помечает запись предмета и очищает слот (VA 0x41BB94).
function wearRanged(actor) {
  const rules = hero.data?.rules?.accuracy?.projectiles;
  if (!rules || !actorItem(actor.equipment?.ranged)) return;
  if (wearSlot(actor, "ranged", rules.wear ?? 0.1)) actor.rangedMode = false;
}

// Износ снаряжения ЖЕРТВЫ: три гнезда, те же, что дают броню (VA 0x41C194
// `for (local_1c = 2; local_1c < 5; ...)`, то же в стрелковом 0x41BF54).
// Снимается `доля * сила_класса * 0.001`, где доля — min(1, сила/броня), а
// при нулевой броне единица. Считается как в движке: отношение во float32,
// произведение в двойной точности.
function wearDefence(defender, strength, armour) {
  const set = hero.data?.rules?.accuracy?.wear;
  const scale = set?.armour ?? 0.001;
  const part = armour > 0 ? Math.min(1, Math.fround(strength / armour)) : 1;
  for (const slot of set?.slots ?? ["body", "head", "off_hand"]) {
    const item = actorItem(defender.equipment?.[slot]);
    if (item) wearSlot(defender, slot, part * (item.power ?? 0) * scale);
  }
}

// Износ ОРУЖИЯ атакующего в ближнем бою: `сила * 0.00025`, и тем же ударом
// на единицу убавляется заряд намазанной отравы (u16 +0x0C записи), если он
// не нулевой. У стрелкового резолвера этого нет — лук стачивает выстрел.
function wearWeapon(attacker, strength, hand) {
  const set = hero.data?.rules?.accuracy?.wear;
  const slot = hand === "off" ? "off_hand" : "hand";
  if (!actorItem(attacker.equipment?.[slot])) return;
  const on = attacker.poisonOn;
  if (on && on.hand) on.hand = Math.max(0, on.hand - 1);
  wearSlot(attacker, slot, strength * (set?.weapon ?? 0.00025));
}

// Снимок выстрела: сила и отрава кладутся в САМ снаряд, потому что бьют они
// в миг прилёта, а к тому времени у стрелка всё могло поменяться. Движок
// держит это в записи снаряда и считает урон из неё (VA 0x41A52C).
function shotSnapshot(shooter) {
  return {
    strength: strengthOf(shooter, "main"),
    venom: weaponPoison(shooter, true),
    side: shooter.side ?? 0,
  };
}

const chance = () => Math.floor(Math.random() * 101);

// Опыт за убитого — четверть ЛЮБОМУ убийце в миг смерти жертвы: и герою,
// и спутнику, и стрелку долетевшей стрелы (VA 0x413894 ближний бой,
// 0x41FDD0 стрела; сумма 0x41B044, доля 0x414150, начисление 0x413110).
function killReward(attacker, defender) {
  if (defender.alive !== false || !attacker) return;
  const { gained, levels } =
    grantExperience(attacker, killShare(killExperience(defender)));
  if (attacker === hero) {
    combat.log.push(`опыт +${gained}${levels ? `, уровень ${hero.level}` : ""}`);
  }
  // РЕПУТАЦИЯ ИДЁТ ТЕМ ЖЕ МИГОМ И ЗА ЛЮБОГО НАШЕГО УБИЙЦУ (VA 0x418554),
  // а не только за героя: движок сверяет сторону убийцы со стороной
  // игрока. Правила и цены — reputation.js.
  const was = reputationValue(hero);
  if (reputationKill(attacker, defender, hero)) {
    const delta = reputationValue(hero) - was;
    combat.log.push(`репутация ${delta > 0 ? "+" : ""}${delta}`);
  }
}

// Один удар по правилам 0x41BF54 (стрелковый) и 0x41C194 (ближний).
// Возвращает, что случилось. hand — какой рукой бьём: "off" это второй
// удар блока «двумя руками» (слот 4, VA 0x412480).
export function strike(attacker, defender,
                       { ranged = false, hand = "main", shot = null } = {}) {
  if (defender.alive === false) return "мимо";
  // Долетевшая стрела бьёт по СНИМКУ, снятому в миг выстрела: движок и
  // силу, и точность берёт из записи снаряда, а не у стрелка (VA 0x41FDD0
  // → 0x41A52C → 0x41BF54). У стрелка к этому времени может смениться
  // оружие — или его самого может уже не быть.
  const defenderStats = statsOf(defender);
  const accuracy = shot ? shot.accuracy : statsOf(attacker, 0, hand).accuracy;
  if (chance() > accuracy) {
    sfxHit(defender, "miss");
    return "промах";
  }
  // Парирование. Ближний удар отбивается только «в лицо»: пара направлений
  // жертвы и атакующего должна стоять в таблице 0x459F94, а порог —
  // ROUND(Ловкость × 0.5) к чётному (double 0x450160) против rand % 101;
  // удар со спины не парируется вовсе (VA 0x41C1E8…0x41C230). Стрела
  // парируется с любой стороны порогом Ловкость × 0.1 без округления
  // (VA 0x41BF75, double 0x450138).
  const parryRules = hero.data?.rules?.accuracy?.parry;
  if (ranged) {
    if (chance() <= defenderStats.parry * (parryRules?.ranged_scale ?? PARRY_SCALE)) {
      sfxHit(defender, "parry");
      return "парировано";
    }
  } else {
    const open = parryRules?.directions
      ?.[defender.direction ?? 0]?.[attacker.direction ?? 0];
    if ((open === undefined || open !== 0) &&
        chance() <= Math.trunc(
          defenderStats.parry * (parryRules?.melee_scale ?? 0.5))) {
      sfxHit(defender, "parry");
      return "парировано";
    }
  }
  // «Смертельный удар» (навык 2): ближний резолвер 0x41C194 после
  // парирования бросает rand % 100 против навык/10 атакующего — не больше
  // порога значит смерть, минуя урон, броню, отраву и износ. У стрелкового
  // резолвера 0x41BF54 этой проверки нет; у зверей навыков нет вовсе.
  if (!ranged && !attacker.beast) {
    const rules = hero.data?.rules?.accuracy?.deadly ?? { skill: 2, divisor: 10 };
    const deadly = attacker.skills?.[rules.skill ?? 2] ?? 0;
    if (deadly !== 0 &&
        Math.floor(Math.random() * 100) <= Math.trunc(deadly / (rules.divisor ?? 10))) {
      applyDamage(defender, Math.max(1, defender.health ?? 0), attacker);
      killReward(attacker, defender);
      return "смертельный удар";
    }
  }
  const strength = shot ? shot.strength : strengthOf(attacker, hand);
  const armour = armourOf(defender);
  const raw = Math.max(0, strength * ARMOUR_PART - armour) + strength * DIRECT_PART;
  // ТРУНК (VA 0x41C2DC у ближнего, 0x41C057 у выстрела). Формула и все три
  // константы сверены с командами: `fmul 0.7 / fsub броня / fcompp -> 0`,
  // затем `+ сила*0.3`, `/ стойкость`, `+1`, `*16` и 0x442BF0.
  const damage = Math.trunc((raw / Math.max(1, defenderStats.toughness) + 1) * DAMAGE_SCALE);
  sfxHit(defender, "hit");
  applyDamage(defender, damage, attacker);
  // Отрава прибавляется к цели тем же ударом: движок кладёт её в глобаль
  // при расчёте силы и складывает с цель+0x52 (VA 0x41BF54). У второй руки
  // своей отравы в паке нет — поле poison_on несёт только руку и боеприпас.
  const venom = shot ? shot.venom
    : (hand === "off" ? 0 : weaponPoison(attacker, Boolean(attacker.rangedMode)));
  if (venom) poisonAdd(defender, venom);
  // Износ идёт тем же ударом и только по попаданию: промах, парирование и
  // «смертельный удар» до него не доходят (VA 0x41C194, 0x41BF54).
  wearDefence(defender, strength, armour);
  if (!ranged) wearWeapon(attacker, strength, hand);
  killReward(attacker, defender);
  // ЛЕЧЕБНЫЕ СМЕСИ — ПОСЛЕ ПОПАДАНИЯ (VA 0x414DF0). Оба пути урона —
  // ближний (0x413894) и прилёт снаряда (0x41FDD0) — дают жертве выпить
  // бальзам, если её тумблер это велит. Отрава триггер не дёргает, поэтому
  // вызов стоит здесь, а не в unitDamage.
  healTriggerTick(defender);
  return venom ? `урон ${damage}, отрава +${venom}` : `урон ${damage}`;
}

//: РАЗМЕНА «ОБЕИМИ РУКАМИ РАЗОМ» БОЛЬШЕ НЕТ. Стоявший здесь `meleeStrikes`
//: наносил оба удара в одной точке анимации, и правило «блок 9 бьёт дважды»
//: жило ВТОРЫМ владельцем — рядом с таблицей кадров. Теперь рука приходит от
//: кадра (STRIKE_FRAME в units.js): 7 — гнездо 0, 9 — гнездо 4, и вызывающий
//: сам зовёт `strike` нужной рукой. Замер подтвердил разнос по кадрам, а не
//: одновременность: между двумя ударами одного замаха ровно два такта.

// Порог реакции на удар (В6 разгадан): 0x41C194 возвращает −1 при уроне
// меньше 0x30 («слабый»), 0 при обычном и 1 при смертельном; вызывающий
// 0x413894 ставит жертве набор анимации 2 («вздрогнуть», 0x416740) ТОЛЬКО
// при коде 0 — слабый удар наносит урон, но жертву не прерывает. Тот же
// гейт у юнитов — units.js unitDamage.
const HIT_REACTION = 0x30;

function applyDamage(defender, damage, attacker = null) {
  if (defender === hero) {
    healthSet(hero, hero.health - damage);
    if (hero.health <= 0) {
      hero.alive = false;
      // крик смерти (0x429B2C, наборы 3/0xB/0xC) — герой мимо units.setPose
      sfxDeathCry(hero);
      heroDie();
    } else if (damage >= HIT_REACTION && hero.data?.animations?.actions?.hit) {
      // СБИВАЕТ И ПОСРЕДИ ЗАМАХА. Здесь стояло условие «только если герой
      // ничем не занят», и оттого замах героя не прерывался НИКОГДА. В
      // движке 0x413894:442 зовёт 0x416740(жертва, 2) без единой проверки:
      // код 0 из 0x41C194 — и реакция ставится поверх чего угодно, со
      // сбросом кадра. Замер: 23 сбива из 27 оборвали замах на кадре 5-6.
      heroSetPose("hit", true);
      sfxHurtCry(hero);          // реакция на удар (набор 2)
    }
    return;
  }
  unitDamage(defender, damage, attacker);
}

// CTRL ПО СВОЕМУ — «ПОДОЙТИ И ЗАГОВОРИТЬ».
//
// Разбор щелчка смотрит на флаг 0x8495AC, и это Ctrl: главный цикл ставит
// его по виртуальной клавише 0x11, а Shift (0x10) поднимает другой флаг,
// 0x849608 — «добавить к выбору» (VA 0x438A00:44). С зажатым Ctrl движок
// вместо выбора пишет ИГРОКУ приказ 0x22 и номер этого юнита целью, то есть
// игрок идёт к нему разговаривать.
//
// ДВЕ ДОРОГИ, ОДИН КОД. В движке это две ветки одной функции разбора
// щелчка, и обе пишут одно и то же:
//
//     щелчок по юниту В МИРЕ (VA 0x421690:279)
//         if (0x8495AC) { игрок[+0x16] = 0x22; игрок[+0x10] = номер; }
//     щелчок по ПОРТРЕТУ на панели (VA 0x421690:349)
//         if (0x8495AC) { игрок[+0x16] = 0x22; игрок[+0x10] = номер; }
//
// Портрет доходит сюда так: попадание ищется по таблице прямоугольников
// панели (VA 0x43AEF0 -> 0x43B5F8 по таблице 0x460EB4, шестнадцать записей),
// и портрет отряда даёт код `место * 0x100 + 1`, а пустое место — −1
// (сверка с числом бойцов отряда, +0x1C). Младший байт кода меньше двух —
// это и есть «портрет», дальше ветка та же.
//
// Через этот разговор спутника и назначают на должность в деревне: действие
// 74 работает с собеседником.
//
// САМ С СОБОЙ — ТА ЖЕ ДВЕРЬ. Гейт в движке один: «щёлкнутый на моей
// стороне» (`0x849528[0x1b] != 0x84951c[0x1b]` — выход), и игрока он не
// отсекает. Ctrl по себе пишет тот же приказ 0x22 со СВОИМ номером, а
// разбор приказа (0x4115AC, случай 2) видит клетку цели равной своей и
// сразу зовёт 0x4369A0 — открывается разговор 138 (у донора 14), тот самый
// HERO.QST с ремонтом и лечением. Здесь стояло `who === hero` в отказе, и
// единственная дверь к росту своего Знахарства и Кузнечного дела была
// закрыта.
export function orderTalkTo(who, running = false) {
  if (!who || !hero.alive) return false;
  if (!(who === hero || who.ally || who.side === hero.side)) return false;
  // СТОЙКА ЗДЕСЬ НИ ПРИ ЧЁМ. Ветка Ctrl в движке спрашивает РОВНО одно —
  // «щёлкнутый на моей стороне» (0x421690:276), — а гейт разговора
  // (FUN_004369A0) знает единственное правило: мёртвый с номером разговора
  // от восьми молчит. Ни оружия, ни боя там нет: с вынутым оружием игрок
  // спокойно говорит со своими и в оригинале. Наша проверка запирала и
  // разговор с самим собой, и назначение спутника на должность в деревне,
  // если оружие оказалось наголо. Для ЧУЖИХ правило остаётся — оно живёт
  // отдельной веткой в orderAt.
  if (!hasTalk(who)) return false;
  orderUnit(hero, who.cell?.row, who.cell?.col, orderKinds().talk, who);
  //: Идти некуда и останавливать некого: `withinTalk` с самим собой сходится
  //: всегда, и ближайший такт разберёт приказ (units.js зовёт onUnitArrived
  //: каждый такт, пока приказ «заговорить»). Приказ ожидания здесь был бы
  //: вреден — он ставит байт 0x0C поверх нашего же 0x22.
  if (who === hero) { hero.orderByte = 0x22; return true; }
  // Байт приказа движок пишет ЦЕЛИКОМ: 0x22, а не одну младшую половину
  // (VA 0x421690:280). Старший разряд 0x20 значит «иду по приказу».
  hero.orderByte = 0x22;
  orderWaitTalk(who);
  // ИДЁМ В КЛЕТКУ СОБЕСЕДНИКА, а не рядом с ней. Здесь во всех трёх
  // подходах — разговор со своим, обыск лежачего и разговор с чужим —
  // стояло `who.y + 40`, то есть точка на сорок пикселей ниже. Она
  // бывает непроходимой, и тогда пути нет вовсе: замер на карте 23 дал
  // 0 шагов к точке `+40` при 10 шагах в саму клетку.
  //
  // Движок целится именно в клетку: приказ 0x22 несёт номер цели в
  // `+0x10`, путь строит `0x416574`, а занятую клетку пропускает
  // `0x441441` по сверке с этим полем. Остановка выходит сама собой —
  // шаг в занятую клетку разбирает `0x415090`, и для приказа НЕ боевого
  // вида он возвращает ноль: приказ снимается, юнит встаёт рядом.
  heroOrderTo(who.x, who.y, running);
  return true;
}

// Приказ по клику: враг — бить, лежащий предмет — поднять, иначе идти.
// Щелчок по миру. Порядок проверок — из движка (VA 0x421690, ветка кода
// 0): несомая вещь, свой, лежачий, чужой, куча, пустая клетка. Ничего
// своего в этом порядке нет.
export function orderAt(x, y, running = false, add = false, talk = false) {
  if (!hero.alive) return false;
  const kinds = orderKinds();
  // Несём вещь: щелчок по миру её роняет, и ложится она в клетку самого
  // героя, а не под мышь (VA 0x421690 -> 0x423360).
  if (carrying()) {
    if (!carryDrop()) world.onStatus?.("это бросить нельзя");
    return true;
  }
  const cell = heroCellAt(x, y);
  const who = unitAt(x, y, true);
  if (who) {
    // CTRL ПО СВОЕМУ — ЗАГОВОРИТЬ, А НЕ ВЫБРАТЬ (VA 0x421690:279).
    // Та же ветка ловит и щелчок по портрету на панели — см. orderTalkTo.
    if (talk && orderTalkTo(who, running)) return true;
    // Свой — это ВЫБОР, а не приказ (VA 0x41ECB8 -> 0x423F80).
    if (who === hero || who.ally) {
      select(who, add);
      return true;
    }
    // Дальше приказ получают РОВНО выбранные (VA 0x4240BC). Герой идёт
    // только если он в списке — иначе он снова «никогда не терял цель».
    // Лежачий: подойти и обыскать.
    if (who.alive === false) {
      for (const unit of selection) {
        if (unit.alive === false) continue;
        orderUnit(unit, who.cell?.row, who.cell?.col, kinds.take, who);
      }
      if (!isSelected(hero)) return true;
      heroOrderTo(who.x, who.y, running);
      return true;
    }
    // Чужой с разговором — подойти и заговорить. Разговор в движке ведёт
    // ВСЕГДА игрок: щелчок по такому NPC ставит приказ 0x22 именно ему
    // (VA 0x4217C0 пишет в _DAT_0084951c), а не выбранным. Поэтому здесь
    // выбор ни при чём — идёт главный, даже если выбран спутник.
    if (hasTalk(who) && !unitFighting(who) && hero.stance !== "combat") {
      orderUnit(hero, who.cell?.row, who.cell?.col, kinds.talk, who);
      // Собеседник останавливается СРАЗУ, а не когда игрок дойдёт: движок
      // кладёт ему приказ 0x0C в тот же миг (VA 0x410A08, случай 2).
      orderWaitTalk(who);
      heroOrderTo(who.x, who.y, running);
      return true;
    }
    // Иначе это враг: бьют все выбранные, и герой среди них — только если
    // выбран. Отряд игрока входит в бой уже здесь, в миг ПРИКАЗА: движок
    // пишет ему врага в +0x06 и единицу в +0x1D до раздачи приказов
    // (VA 0x421690). Отряд ЖЕРТВЫ поднимется позже — на замахе.
    warbandPlayerAttacks(who);
    for (const unit of selection) {
      if (unit.alive === false) continue;
      orderUnit(unit, who.cell?.row, who.cell?.col, kinds.target, who);
      if (unit !== hero) unit.target = who;
    }
    if (isSelected(hero)) {
      combat.target = who;
      hero.stance = "combat";
    }
    return true;
  }
  // Поджог: движок даёт особый приказ, только когда у стрелка есть и лук,
  // и боеприпас, и боеприпас намаслен (VA 0x421690).
  if (hero.itemOiled?.[hero.equipment?.ammo] && hero.rangedMode &&
      hero.equipment?.ranged && hero.equipment?.ammo) {
    const building = cell && buildingAtCell(cell.row, cell.col);
    if (building) {
      combat.target = { x, y, building, alive: true, name: "постройка" };
      hero.stance = "combat";
      return true;
    }
  }
  // СУНДУК ПОД МЫШЬЮ. Гнездо обстановки с кучей — тот же приказ «обыскать»,
  // только цель у него ОТРИЦАТЕЛЬНАЯ (номер кучи), а клетка берётся из самой
  // записи кучи (VA 0x421690:213 -> 0x41F518). Проверка стоит здесь же, где
  // в движке: после несомой вещи и до разбора пустой клетки.
  const chest = furnitureAt(x, y);
  if (chest?.pile?.cell) {
    combat.target = null;
    orderSelected(chest.pile.cell.row, chest.pile.cell.col, kinds.take, running);
    if (!isSelected(hero)) return true;
    orderUnit(hero, chest.pile.cell.row, chest.pile.cell.col, kinds.take,
              chest.pile);
    const at = heroAnchor(chest.pile.cell.row, chest.pile.cell.col);
    return heroOrderTo(at.x, at.y, running);
  }
  // Куча под мышью — идём к ней и обыскиваем.
  const pile = lootNear(x, y);
  if (pile) {
    combat.target = null;
    orderSelected(pile.cell?.row, pile.cell?.col, kinds.take, running);
    if (!isSelected(hero)) return true;
    orderUnit(hero, pile.cell?.row, pile.cell?.col, kinds.take, pile);
    // ИДЁМ В КЛЕТКУ КУЧИ, А НЕ В ЕЁ ПИКСЕЛИ. Приказ несёт клетку (+0x13 и
    // +0x15), и путь движок строит именно к ней (0x416574) — пиксели кучи в
    // расчёт не идут вовсе.
    //
    //: Проверено: сегодня это ничего не меняет. Сборщик кладёт куче
    //: `position` РОВНО якорем её клетки (builder.py, `piles_of`), и на всех
    //: 1960 кучах пака пересчёт пикселей обратно в клетку даёт ту же клетку.
    //: Правка снимает зависимость от этого совпадения: разойдись они хоть
    //: раз — и герой доходил бы до соседней клетки, а куча всё равно
    //: открывалась.
    const at = heroAnchor(pile.cell.row, pile.cell.col);
    return heroOrderTo(at.x, at.y, running);
  }
  // ПУСТАЯ КЛЕТКА. Приказ «идти» уходит только на клетку, младшие 12 бит
  // которой нулевые: там либо номер стоящего юнита, либо 0xFFF «глухая».
  // Ровно на таких клетках движок показывает перечёркнутый курсор
  // (VA 0x428B88), поэтому щелчок по нему не делает НИЧЕГО — приказа нет.
  //
  //: Движок отсекает ещё и щелчок по постройке (`_DAT_00849534 == 0` перед
  //: вызовом 0x4240BC), но там это постройка ПОД СПРАЙТОМ мыши, а не под
  //: клеткой: по клетке пола внутри дома ходить можно и нужно. Попиксельной
  //: пробы построек в клиенте пока нет, поэтому этой отсечки здесь нет —
  //: щелчок по крыше сейчас уводит героя к клетке под ней.
  combat.target = null;
  if (!cell || !heroFree(cell.row, cell.col)) return false;
  orderSelected(cell.row, cell.col, kinds.go, running);
  if (!isSelected(hero)) return true;
  orderUnit(hero, cell?.row, cell?.col, kinds.go);
  return heroOrderTo(x, y, running);
}

function heroStrike(unit) {
  hero.stance = "combat";
  const pose = actorAttackPose(hero.data, hero);
  if (!heroPlayAction(pose)) return false;
  sfxSwing(hero);              // звук замаха ставится с анимацией (0x429B2C)
  // Стрельбе отсчёт не положен — у неё свой случай разбора такта, без +0xFD.
  hero.attackWait = pose.startsWith("shoot") ? 0 : (world.attackWait?.(hero) ?? 1);
  combat.pendingHit = { unit, pose, declared: false };
  return true;
}

// Урон проходит серединой анимации — тогда же, когда в кадре идёт рука.
function resolvePendingHit() {
  const pending = combat.pendingHit;
  if (!pending) return;
  if (hero.pose !== pending.pose) { combat.pendingHit = null; return; }
  const frames = actorFrames(hero.data, hero);
  if (!frames?.length) return;
  // ЗАМАХ ПОДНИМАЕТ ОТРЯД ЖЕРТВЫ РАНЬШЕ УРОНА. Движок сверяет номер кадра
  // (unit+0x1C) с двойкой и объявляет войну прямо там (VA 0x413894), ещё
  // не зная, попадёт удар или нет. Поэтому промах по жителю поднимает
  // деревню точно так же, как попадание.
  if (!pending.declared && hero.frame >= 2) {
    pending.declared = true;
    warbandSwing(hero, pending.unit, units);
  }
  // КАДР УДАРА — ТАБЛИЦА ДВИЖКА (0x45FE90 + блок позы, см. STRIKE_FRAME в
  // units.js), а не середина анимации: у замаха с щитом это кадр 5, у
  // двуручного и одноручного — 7, у выстрела «всего − 6». Середина блока из
  // двенадцати кадров дала бы шестой, и удар уходил бы позже, чем в
  // оригинале. Незнакомую позу по-прежнему бьём серединой.
  //
  // РУК У ЗАМАХА МОЖЕТ БЫТЬ ДВЕ, и каждая бьёт СВОИМ кадром: у одноручного
  // это 7 (гнездо 0) и 9 (гнездо 4). Поэтому замах не закрывается первым же
  // ударом — он ведёт список уже отработавших рук и кончается, когда отдали
  // все. Замер: такт 543611 «#424 −97» на кадре 7 и 543613 «#424 −25» на
  // кадре 9 — один замах, одна жертва, две руки.
  const hits = world.strikeFrames?.(hero.pose, frames.length) ?? [];
  const plan = hits.length ? hits
    : [{ frame: Math.floor(frames.length / 2), hand: "main" }];
  pending.done = pending.done ?? [];
  for (const step of plan) {
    if (hero.frame < step.frame || pending.done.includes(step.hand)) continue;
    pending.done.push(step.hand);
    heroStrikeWith(pending, step.hand);
  }
  if (pending.done.length >= plan.length) combat.pendingHit = null;
}

// Один удар одной рукой — тело прежнего resolvePendingHit.
function heroStrikeWith(pending, hand) {
  if (pending.unit.alive) {
    if (hero.rangedMode && hero.equipment?.ranged) {
      // Без стрел выстрела нет: движок тратит по одной на кадр выстрела
      // и на пустой пачке лезет за следующей (VA 0x413894).
      if (!hero.equipment.ammo) {
        combat.log.push("нечем стрелять");
        return;
      }
      const bow = actorItem(hero.equipment.ranged);
      projectileFire(hero, pending.unit,
        statsOf(hero, distanceCells(hero, pending.unit)).accuracy, bow,
        shotSnapshot(hero));
      ammoSpend(hero);
      wearRanged(hero);
      combat.log.push(`герой стреляет, стрел ${hero.ammoCount ?? 0}`);
      return;
    }
    const result = strike(hero, pending.unit, { hand });
    combat.log.push(`герой -> ${pending.unit.name}: ${result}`);
    // Опыт за убитого начисляет сам strike — убийце, в миг смерти.
    if (combat.log.length > 40) combat.log.shift();
  }
}

// Расстояние до цели — КАНОНИЧНОЙ меркой клеток (VA 0x43B670), той же, что
// у всех прочих юнитов: большая из разниц, плюс единица, если меньшая
// больше единицы.
//
// Раньше здесь стояла своя мерка — длина вектора в пикселях, делённая на
// 58 и 32. Она НЕ совпадает с клеточной: по диагонали давала около 1.41
// там, где движок считает единицу, и удар с дальностью 1 не проходил.
// Оттого и приходилось выискивать точку впритык к врагу.
function distanceCells(a, b) {
  return cellRange(a, b);
}

function directionTo(from, to) {
  const steps = hero.data?.direction_steps ?? [];
  let best = from.direction;
  let bestScore = -Infinity;
  for (let i = 0; i < steps.length; i += 1) {
    const [sx, sy] = steps[i];
    const length = Math.hypot(sx, sy) || 1;
    const score = ((to.x - from.x) * sx + (to.y - from.y) * sy) / length;
    if (score > bestScore) { bestScore = score; best = i; }
  }
  return best;
}

//: ФАЕРБОЛ СВОЕГО ГЕРОЯ-ЧАРОДЕЯ.
//:
//: Оружия ему не нужно — ровно как Кикиморе, которая плюётся без лука
//: (kikimoraSpits выше): дальность берётся константой, потому что в классе
//: предмета её взять неоткуда, снаряд несёт своё имя набора, а долетевший
//: разрешается тем же `strike`, что и стрела. Своей боевой математики здесь
//: нет вовсе — только повод пустить снаряд.
const CAST_RANGE = KIKIMORA_RANGE;
const CAST_SPRITE = "fireball";
const CAST_FLASH = "firecast";
//: Во сколько раз быстрее такта крутится вспышка в руках. Двойка оказалась
//: резковата, полтора — в самый раз под жест.
const CAST_FLASH_SPEED = 1.5;

export function heroCast(target) {
  if (!target || target.alive === false) return "некого жечь";
  const distance = distanceCells(hero, target);
  if (distance > CAST_RANGE) return "далеко";
  //: РАЗВОРОТ К ЦЕЛИ — до позы. Движок поворачивает стрелка на цель, и
  //: снаряд летит по его же направлению (0x41BB10). Без этого волшебница
  //: кастовала, глядя туда, куда шла, а огонь брал спрайт её взгляда.
  hero.direction = directionTo(hero, target);
  //: Позу ставим ПОСЛЕ проверок: иначе герой машет руками впустую, а шаг
  //: ему при этом сбрасывают (heroPlayAction чистит путь и цель).
  if (!heroPlayAction("cast")) return "нечем кастовать";
  //: ОГОНЬ В РУКАХ ЗАЖИГАЕТСЯ С НАЧАЛОМ ЖЕСТА, а не в миг выстрела: иначе
  //: он вспыхивает, когда рука уже опустилась, и потом секунду догорает на
  //: стоящей фигуре. Крутится быстрее такта — жест короткий.
  burstSpawn(hero.x, hero.y, CAST_FLASH, hero.direction ?? 0, CAST_FLASH_SPEED);
  //: ВЫСТРЕЛ НЕ НА ПЕРВОМ КАДРЕ И НЕ В КОНЦЕ. Движок пускает снаряд в миг
  //: замаха, а не когда рука уже опустилась: у кикиморы это кадр 8 из её
  //: анимации. Берём середину раскадровки (см. `castRelease`), а пока
  //: анимация играет — держим намерение.
  combat.pendingCast = { target };
  return "каст";
}

//: КАСТ ПО ТОЧКЕ — как в Diablo: огонь летит, куда послали, и жжёт первого
//: встречного. Цели заранее нет; дальность даёт жизнь снаряда, а кого задело
//: — решает такт (projectiles.js freeHit).
export function heroCastAt(x, y) {
  const point = { x, y };
  if (!Number.isFinite(x) || !Number.isFinite(y)) return "некуда";
  hero.direction = directionTo(hero, point);
  if (!heroPlayAction("cast")) return "нечем кастовать";
  burstSpawn(hero.x, hero.y, CAST_FLASH, hero.direction ?? 0, CAST_FLASH_SPEED);
  combat.pendingCast = { point };
  return "каст";
}

//: Отпустить огонь, когда анимация каста дошла до кадра удара.
function castRelease() {
  const pending = combat.pendingCast;
  if (!pending) return;
  //: Позу сбили — сбили и каст: получив удар, герой уходит в «вздрогнуть»,
  //: и доигрывать ему уже нечего.
  if (hero.pose !== "cast") { combat.pendingCast = null; return; }
  const frames = actorFrames(hero.data, hero, "cast", hero.direction);
  const total = frames?.length ?? 0;
  //: СЕРЕДИНА РАСКАДРОВКИ. На «всего − 2» огонь уходил, когда жест уже
  //: кончался, и выглядело это как выстрел вдогонку.
  if (!total || hero.frame < Math.floor(total / 2)) return;
  combat.pendingCast = null;
  //: Цель может быть юнитом (щёлкнули по нему) или просто точкой на земле
  //: (послали в сторону). Для точки дальность считать не по кому.
  const target = pending.target ?? pending.point;
  if (!target || target.alive === false) return;
  const distance = pending.target ? distanceCells(hero, target) : 0;
  //: ВЫСОТУ ДАЁТ САМ КАДР, а не код: у нашего шара диабловская привязка к
  //: земле, и он нарисован уже поднятым на 54 точки — по плечо. Пустим его
  //: канонными «минус тридцать», и огонь уйдёт выше головы.
  const shot = projectileFire(hero, target, statsOf(hero, distance).accuracy,
                              { range_cells: CAST_RANGE }, shotSnapshot(hero), 0);
  if (!shot) return;
  shot.sprite = CAST_SPRITE;
  if (!pending.target) {
    //: Свободный выстрел: цели у снаряда нет, попадание ищет такт.
    shot.target = null;
    shot.free = true;
  }
  //: Спрайт снаряда берётся по НАПРАВЛЕНИЮ ПОЛЁТА, а не по взгляду стрелка:
  //: `projectileFire` кладёт туда стрелка, потому что у канонной стрелы кадр
  //: и есть его направление (запись снаряда +0x1A).
  shot.direction = directionTo(hero, target);
  combat.log.push(`герой жжёт ${target.name ?? "цель"}`);
  if (combat.log.length > 40) combat.log.shift();
}

export function combatTick(dt) {
  // Долетевшая стрела бьёт цель по тем же правилам, что и рука.
  if (projectilesTick(dt, (shot) => {
    // Зажигательная стрела не бьёт, а поджигает — и деревня в любом случае
    // поднимает тревогу против стрелка (VA 0x41FDD0).
    if (shot.target?.building) {
      const lit = buildingIgnite(shot.target.building);
      combat.log.push(lit ? "постройка занялась" : "стрела не подожгла");
      world.onVillageAlarm?.(shot.shooter);
      return;
    }
    // Опыт за убитого стрелой начисляет сам strike — СТРЕЛКУ, а не герою
    // за чужой выстрел (VA 0x41FDD0 даёт четверть владельцу стрелы).
    // Стрела идёт стрелковым резолвером: без «Смертельного удара».
    const result = strike(shot.shooter, shot.target, { ranged: true, shot });
    combat.log.push(`стрела ${shot.shooter.name} -> ${
      shot.target === hero ? "герой" : shot.target.name}: ${result}`);
  })) { /* полёт сам по себе перерисовки не требует: кадр и так идёт */ }
  burstsTick(dt);
  castRelease();
  resolvePendingHit();
  if (!hero.alive) return false;

  // ГЕРОЙ ЖИВЁТ В ОБЩЕМ ТАКТЕ (units.js): рассудок, приказы, движение,
  // кадры и удары идут тем же кодом, что у любого юнита отряда №0, — как в
  // движке, где 0x413894 перебирает все отряды и игрок лишь первая запись.
  // Прежняя геройская машинерия (свой выбор цели, свой замах pendingHit,
  // свой разбор прибытия) отсюда ушла; остались две вещи вне юнитского
  // цикла:
  //   1) зеркало combat.target для интерфейса — из боевого приказа героя;
  //   2) поджог постройки: цель — не юнит, общий тик её не берёт.
  const kinds = orderKinds();
  if (!combat.target?.building) {
    combat.target = (hero.orderKind === (kinds.target ?? 1) &&
        hero.orderTarget && hero.orderTarget.alive !== false)
      ? hero.orderTarget : null;
  }
  const target = combat.target;
  if (!target?.building) return false;

  // --- поджог постройки: единственный потребитель старого замаха ---
  if (!hero.rangedMode || !hero.equipment?.ranged || !hero.equipment?.ammo) {
    combat.target = null;               // жечь больше нечем
    return false;
  }
  const acting = Boolean(hero.data?.animations?.actions?.[hero.pose]);
  // Дальность — по пикселям сетки (58 на клетку): у цели-постройки нет
  // клетки, и мерка 0x43B670 к ней неприменима.
  const cells = Math.round(Math.hypot(target.x - hero.x,
                                      (target.y - hero.y) * 1.8) / 58);
  if (cells > reachOf(hero)) {
    if (!acting && !hero.moving) { heroOrderTo(target.x, target.y, true); return true; }
    return false;
  }
  if (!acting) {
    hero.direction = directionTo(hero, target);
    heroStrike(target);
    return true;
  }
  return false;
}

// Куча: сперва опознание бросками против навыка, потом деньги, потом обмен.
// Обыск кучи. Обыскивает ТОТ, кто дошёл: движок ставит 0x849514 на этого
// юнита (VA 0x4115AC, случай 3), то есть вещи ложатся в ЕГО мешок. Деньги
// при этом идут в общий кошелёк игрока (0x84951C+0x26), а опознание
// считается по навыку игрока (+0xE1) — это в движке отдельные поля.
// Приказ дошёл — для ЛЮБОГО юнита, не только для героя. В движке это одна
// функция на всех (VA 0x4115AC берёт юнита аргументом), поэтому спутник
// умеет и обыскивать, и заговаривать.
export function unitArrived(unit) {
  return orderArrived(unit, {
    talk: (_, target) => { dialogStart(target); world.onTalk?.(target); },
    take: (who, target, at) => {
      // РАЗГОВОРНАЯ КУЧА — раньше обмена: донорский разборщик прибытия
      // (0x411BC6) сперва смотрит байт диалога записи и лишь при 0xFE/0xFF
      // идёт веткой обыска. Разговор открывается БЕЗ собеседника — так
      // устроены семь чанов с маслом в Ущелье возле Угорья.
      const spoken = at ? talkPileAtCell(at.row, at.col) : null;
      if (spoken) {
        dialogStart(lootSpeaker(spoken));
        world.onTalk?.(spoken);
        return;
      }
      // КУЧА ИЩЕТСЯ ПО КЛЕТКЕ, как в движке (VA 0x4149F8): в приказе её не
      // хранят вовсе — раздача приказа обнуляет `+0x10` (0x4240BC), — и дойдя,
      // юнит перебирает кучи, сравнивая строку и столбец со своими.
      //
      // Здесь стояло `target ?? поиск по клетке`, то есть ровно наоборот:
      // сохранённая цель ПЕРЕБИВАЛА поиск. Пока клетка сходилась, разницы не
      // было, но стоило приказу дожить до разбора с чужой клеткой — и куча
      // открывалась с любого расстояния. Теперь клетка решает, а цель годится
      // только своя: до сундука и бочки по клетке не добраться (у них
      // `+0x09 != 0xFF`, см. pileAtCell), поэтому для них цель и оставлена —
      // но лишь тогда, когда она лежит В ТОЙ ЖЕ клетке, куда шли.
      const byCell = at ? pileAtCell(at.row, at.col) : null;
      const sameCell = target?.cell && at
        && target.cell.row === at.row && target.cell.col === at.col;
      const found = byCell ?? (sameCell ? target : null);
      if (!found) return;
      if (found.items) openPile(found, who);
      else openBody(found, who);
    },
  });
}

// Куча в клетке — перебор куч со сравнением строки и столбца (VA 0x4149F8).
//
// СПРЯТАННУЮ отдаём только с ЛОПАТОЙ. В движке (VA 0x4115AC) ветка обыска
// по клетке отказывает так:
//
//     если клетка помечена (бит 0x20) и куча спрятана (+0x0F < 0)
//        и FUN_00434F8C(0x20) == 0     // Лопаты в мешке нет
//     -> контейнер «не найден»
//
// Класс 0x20 — «Лопата». Без неё тайник не откапывается, даже если игрок
// стоит ровно на нём.
//: Разговорная куча в клетке. Отдельно от pileAtCell: у той обязательны
//: вещи, у этой их не бывает; лопата и «спрятана» её тоже не касаются.
function talkPileAtCell(row, col) {
  if (row == null || col == null) return null;
  return loot.find((pile) => !pile.taken && pile.dialog &&
    pile.cell?.row === row && pile.cell?.col === col) ?? null;
}

function pileAtCell(row, col) {
  if (row == null || col == null) return null;
  //: Куча в гнезде обстановки по клетке НЕ находится: `FUN_004149F8` сверяет
  //: `+0x09 == 0xFF` и берёт только напольные. До сундука добираются щелчком
  //: по нему самому, и его номер приезжает целью приказа.
  const found = loot.find((pile) => !pile.taken && pile.items?.length &&
    !lootInNest(pile) &&
    pile.cell?.row === row && pile.cell?.col === col) ?? null;
  if (found && lootHidden(found) && !hasShovel()) return null;
  return found;
}

//: Есть ли Лопата в мешке — перенос FUN_00434F8C(0x20): движок перебирает
//: сорок две ячейки и сравнивает КЛАСС вещи с заданным.
function hasShovel(actor = hero) {
  const shovel = hero.data?.rules?.craft?.shovel_class ?? 32;
  return (actor.bag ?? []).some((name) => actorItem(name)?.index === shovel);
}

export function openPile(pile, finder = hero) {
  for (let index = 0; index < pile.items.length; index += 1) {
    const word = pile.enchant?.[index] ?? 0;
    if (!word) continue;
    pile.enchant[index] = identifyRoll(hero, word);
  }
  if (pile.money) {
    // ДЕНЬГИ БЕРУТСЯ ПО МОДУЛЮ. В движке (VA 0x4115AC) это
    //
    //     iVar3 = FUN_00442B7E(контейнер[+0x0F]);   // а FUN_00442B7E — abs()
    //     *(int *)(_DAT_0084951C + 0x26) += iVar3;  // деньги игроку
    //
    // Отрицательное число в поле денег значит «клад зарыт»: обыскать такой
    // можно только с Лопатой в мешке (класс 0x20, проверка FUN_00434F8C).
    // Без модуля клад отнимал бы монеты.
    //
    // ОГОВОРКА ЧЕСТНАЯ: в поставочных данных отрицательных денег НЕТ ни в
    // одной из 2052 записей всех шести миров, так что это защита от чужих
    // сейвов и правок, а не починка видимой ошибки.
    const taken = Math.abs(pile.money);
    hero.money = (hero.money ?? 0) + taken;
    combat.log.push(`из кучи: ${taken} монет`);
    pile.money = 0;
  }
  // ОБЫСК СНИМАЕТ ЗНАК «ЗАКОПАНА»: движок обнуляет слово денег ВМЕСТЕ СО
  // ЗНАКОМ безусловно (0x4115AC:65) — раскопанный схрон дальше живёт
  // обычной видимой кучей и лопаты больше не просит. Без этого частично
  // разобранный тайник пропадал с глаз навсегда (lootHidden).
  if (pile.buried) pile.dug = true;
  //: МОЛЧА. Обыск в движке голоса не подаёт: 0x4115AC кладёт дошедшего в
  //: `_DAT_00849514` и зовёт 0x424128, а тот только перекладывает мешок в
  //: столбец обмена — ни выбора (0x423F80), ни проигрывателя там нет.
  //: Выбор здесь стоит лишь затем, чтобы обмен взял мешок дошедшего.
  select(finder, false, { silent: true });
  tradeOpen(pile, pile.items, false);
  world.onTrade?.(pile);
  return true;
}

// Обыск лежачего: движок ссыпает всё его снаряжение в его же мешок,
// забирает деньги и открывает тот же обмен (VA 0x4115AC).
// Обыск тела — тем же правилом: вещи достаются дошедшему, деньги общие.
export function openBody(body, finder = hero) {
  const bag = [...(body.bag ?? [])];
  for (const slot of Object.keys(body.equipment ?? {})) {
    const name = body.equipment[slot];
    if (!name) continue;
    body.equipment[slot] = null;
    bag.push(name);
    // слово чар надетого едет в мешок вместе с вещью (В10)
    const word = body.enchant?.[slot];
    if (word) {
      body.bagEnchant = body.bagEnchant ?? {};
      body.bagEnchant[name] = word;
      delete body.enchant[slot];
    }
    const poison = body.poisonOn?.[slot];
    if (poison) {
      body.bagPoison = body.bagPoison ?? {};
      body.bagPoison[name] = poison;
      delete body.poisonOn[slot];
    }
    if (slot === "ammo") {
      body.bagCount = body.bagCount ?? {};
      body.bagCount[name] = body.ammoCount ?? ammoStack(body);
      body.ammoCount = null;
    }
  }
  body.bag = bag;
  if (body.money) {
    hero.money = (hero.money ?? 0) + body.money;
    combat.log.push(`с тела: ${body.money} монет`);
    body.money = 0;
  }
  select(finder, false, { silent: true });   //: обыск немой, как и у кучи
  tradeOpen(body, bag, false);
  world.onTrade?.(body);
  return true;
}

export { units };
