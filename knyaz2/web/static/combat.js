// Бой по правилам движка.
//
// Формула снята с кода, а не придумана. Удар считается в 0x41BF54:
//
//   1. промах:      rand() % 101 > точность атакующего (unit+0x1F)
//   2. парирование: rand() % 101 <= стойкость цели (unit+0xCD) * 0.1
//   3. броня цели:  своя (unit+0xF4) плюс сила одежды, доспеха и щита
//                   (VA 0x41A414: поля +0x5A, +0x5C и +0x5E)
//   4. урон:        max(0, сила * 0.7 - броня) + сила * 0.3
//   5. итог:        round(урон / выносливость(unit+0xD1) + 1) * 16
//   6. здоровье:    i16 unit+0x4E; если здоровья не больше урона — смерть
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
import { hero, heroCellAt, heroFree, heroOrderTo, heroPlayAction, heroSetPose,
         heroDie } from "./hero.js";
import { actorInstanceMaps, canStrike, cellRange, unitAt, unitDamage,
         units } from "./units.js";
import { unitFighting, warbandDeclare, warbandPlayerAttacks, warbandSwing,
         warbands } from "./warband.js";
import { isSelected, orderArrived, orderClear, orderKinds, orderSelected,
         orderWaitTalk, selectionFallback,
         orderUnit, select, selection, withinTalk } from "./orders.js";
import { projectileFire, projectilesTick } from "./projectiles.js";
import { loot, lootNear, lootTake } from "./loot.js";
import { tradeOpen } from "./trade.js";
import { roundHalfEven } from "./round.js";
import { identifyRoll } from "./jewels.js";
import { ammoSpend, ammoStack, weaponModeRefresh } from "./inventory.js";
import { healthMax, poisonAdd, weaponPoison } from "./effects.js";
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

//: Такт ударов — наш: движок отмеряет его тиками анимации, а не секундами.
const HERO_COOLDOWN = 0.7;

export const combat = {
  target: null,        // враг, к которому идём
  cooldown: 0,
  pickup: null,        // предмет, к которому идём
  pendingHit: null,
  log: [],             // последние события боя, для отладки
};

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
    stats.accuracy = Math.round(
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
    value = Math.round(value - distance * (rules.range_penalty ?? 0.3) / reach);
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
  combat.target = null;
  combat.pickup = null;
  combat.cooldown = 0;
  combat.pendingHit = null;
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
      hero.health = Math.max(0, hero.health - poison);
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
  world.onUnitStrike = (unit) => {
    const target = unit.target ?? hero;
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
    const result = meleeStrikes(unit, target);
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
  return roundHalfEven(strength * scale * (actor.health ?? 0) *
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
        chance() <= roundHalfEven(
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
  const damage = Math.round((raw / Math.max(1, defenderStats.toughness) + 1) * DAMAGE_SCALE);
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
  return venom ? `урон ${damage}, отрава +${venom}` : `урон ${damage}`;
}

// Ближний размен за одну анимацию. Блок 9 «удар двумя руками» бьёт ДВАЖДЫ:
// основной рукой на кадре 7 и второй на кадре 9 (VA 0x412480, оба полубайта
// константы 0x45FE98); у остальных блоков ударный кадр один (0x45FE90).
// Порт резолвит оба удара в своей точке анимации, второй — своим броском
// точности (offHandAccuracy) и силой предмета щитового гнезда.
export function meleeStrikes(attacker, defender) {
  const first = strike(attacker, defender);
  if (defender.alive === false) return first;
  if (actorAttackPose(hero.data, attacker) !==
      (hero.data?.rules?.attack_by_item?.melee?.second_hand_free ?? "attack_one_hand")) {
    return first;
  }
  const second = strike(attacker, defender, { hand: "off" });
  return `${first}; второй рукой: ${second}`;
}

// Порог реакции на удар (В6 разгадан): 0x41C194 возвращает −1 при уроне
// меньше 0x30 («слабый»), 0 при обычном и 1 при смертельном; вызывающий
// 0x413894 ставит жертве набор анимации 2 («вздрогнуть», 0x416740) ТОЛЬКО
// при коде 0 — слабый удар наносит урон, но жертву не прерывает. Тот же
// гейт у юнитов — units.js unitDamage.
const HIT_REACTION = 0x30;

function applyDamage(defender, damage, attacker = null) {
  if (defender === hero) {
    hero.health = Math.max(0, hero.health - damage);
    if (hero.health <= 0) {
      hero.alive = false;
      // крик смерти (0x429B2C, наборы 3/0xB/0xC) — герой мимо units.setPose
      sfxDeathCry(hero);
      heroDie();
    } else if (damage >= HIT_REACTION && hero.data?.animations?.actions?.hit &&
               !hero.data.animations.actions[hero.pose]) {
      heroSetPose("hit");
      sfxHurtCry(hero);          // реакция на удар (набор 2)
    }
    return;
  }
  unitDamage(defender, damage, attacker);
}

// Приказ по клику: враг — бить, лежащий предмет — поднять, иначе идти.
// Щелчок по миру. Порядок проверок — из движка (VA 0x421690, ветка кода
// 0): несомая вещь, свой, лежачий, чужой, куча, пустая клетка. Ничего
// своего в этом порядке нет.
export function orderAt(x, y, running = false, add = false) {
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
      heroOrderTo(who.x, who.y + 40, running);
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
      heroOrderTo(who.x, who.y + 40, running);
      return true;
    }
    // Иначе это враг: бьют все выбранные, и герой среди них — только если
    // выбран. Отряд игрока входит в бой уже здесь, в миг ПРИКАЗА: движок
    // пишет ему врага в +0x06 и единицу в +0x1D до раздачи приказов
    // (VA 0x421690). Отряд ЖЕРТВЫ поднимется позже — на замахе.
    combat.pickup = null;
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
      combat.pickup = null;
      hero.stance = "combat";
      return true;
    }
  }
  // Куча под мышью — идём к ней и обыскиваем.
  const pile = lootNear(x, y);
  if (pile) {
    combat.target = null;
    orderSelected(pile.cell?.row, pile.cell?.col, kinds.take, running);
    if (!isSelected(hero)) return true;
    orderUnit(hero, pile.cell?.row, pile.cell?.col, kinds.take, pile);
    return heroOrderTo(pile.x, pile.y, running);
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
  combat.pickup = null;
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
  combat.cooldown = HERO_COOLDOWN;
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
  if (hero.frame < Math.floor(frames.length / 2)) return;
  combat.pendingHit = null;
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
    const result = meleeStrikes(hero, pending.unit);
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

export function combatTick(dt) {
  if (combat.cooldown > 0) combat.cooldown = Math.max(0, combat.cooldown - dt);
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
  resolvePendingHit();
  if (!hero.alive) return false;

  // Приказ дошёл: движок смотрит младшую половину байта приказа и решает
  // — заговорить, обыскать или ничего (VA 0x4115AC).
  if (hero.orderKind && !hero.moving) {
    // Разговор начинается из игрового цикла, а не из щелчка, поэтому
    // интерфейс будит сам обработчик прихода.
    unitArrived(hero);
  }

  const target = combat.target;
  if (!target) return false;
  if (!target.alive) { combat.target = null; return false; }

  const distance = distanceCells(hero, target);
  const acting = Boolean(hero.data?.animations?.actions?.[hero.pose]);
  if (distance <= reachOf(hero)) {
    if (hero.moving) heroOrderTo(hero.x, hero.y);
    // Стрелять можно НЕ ВСЕГДА: движок проверяет одно и то же для всех —
    // не ближе трёх клеток и чистая линия огня (VA 0x414AF8: `if (iVar2 < 3)
    // return 0xffffffff` и марш по клеткам траектории с отказом на глухой).
    // Приказ атаки игрока идёт тем же путём юнитов, поэтому герой не
    // исключение: раньше он стрелял в упор и сквозь стены, тратя стрелы.
    if (!canStrike(hero, target, distance)) return false;
    if (!acting && combat.cooldown <= 0) {
      hero.direction = directionTo(hero, target);
      heroStrike(target);
      return true;
    }
    return false;
  }
  // Далеко — идём к цели. Целимся не в саму клетку врага: живой юнит её
  // занимает, и маршрут туда не строится в принципе.
  if (!acting && !hero.moving) {
    const dx = hero.x - target.x;
    const dy = hero.y - target.y;
    const length = Math.hypot(dx, dy) || 1;
    heroOrderTo(target.x + (dx / length) * 52, target.y + (dy / length) * 52, true);
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
      // Куча ищется ПО КЛЕТКЕ, как в движке (VA 0x4149F8): в приказе её
      // не хранят, поэтому полагаться на сохранённую цель нельзя.
      const found = target ?? (at ? pileAtCell(at.row, at.col) : null);
      if (!found) return;
      if (found.items) openPile(found, who);
      else openBody(found, who);
    },
  });
}

// Куча в клетке — перебор куч со сравнением строки и столбца (VA 0x4149F8).
function pileAtCell(row, col) {
  if (row == null || col == null) return null;
  return loot.find((pile) => !pile.taken && pile.items?.length &&
    pile.cell?.row === row && pile.cell?.col === col) ?? null;
}

export function openPile(pile, finder = hero) {
  for (let index = 0; index < pile.items.length; index += 1) {
    const word = pile.enchant?.[index] ?? 0;
    if (!word) continue;
    pile.enchant[index] = identifyRoll(hero, word);
  }
  if (pile.money) {
    hero.money = (hero.money ?? 0) + pile.money;
    combat.log.push(`из кучи: ${pile.money} монет`);
    pile.money = 0;
  }
  select(finder);
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
  select(finder);
  tradeOpen(body, bag, false);
  world.onTrade?.(body);
  return true;
}

export { units };
