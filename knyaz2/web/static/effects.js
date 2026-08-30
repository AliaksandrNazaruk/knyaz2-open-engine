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
import { profiler } from "./profiler.js";
import { hero } from "./hero.js";
import { actorItem, actorReclassItemRef } from "./actor.js";
import { units } from "./units.js";
import { buildingsTick } from "./buildings.js";
import { unitFighting } from "./warband.js";
import { grantExperience } from "./progress.js";
// движковый ROUND (0x442BF0) — fistp, округление к чётному
import { roundHalfEven } from "./round.js";
import { clockPhaseHits } from "./clock.js";
import { village, villageCrew, villageOfficial, villagesAway, villageTickAway,
         villageTraining } from "./village.js";
import { villageBrew, villageForge } from "./shops.js";

function rules() { return world.map?.hero?.rules?.effects ?? null; }

export function poisonTickEvery() { return rules()?.poison?.tick_every ?? 16; }
export function healthMax() { return rules()?.health?.max ?? 1600; }

// ОДНА ТОЧКА ИЗМЕНЕНИЯ ЗДОРОВЬЯ.
//
// В движке второго хранилища здоровья нет: полоску рисует FUN_004305A4
// прямо из `+0x4E` записи, а высота считается как
// `(0x640 − здоровье) * 0x3E / 0x640`. Синхронизировать нечего — зато эту
// перерисовку зовут ИЗ КАЖДОГО места, где здоровье изменилось: такт мира
// (0x41C944, дважды), ближний бой (0x414DF0), прилёт снаряда (0x41FDD0),
// выпитое снадобье (0x41D954), ход по глобальной (0x4277F4), такт NPC
// (0x413894) и действия разговора (0x4345A4, 0x434630, 0x43473C).
//
// У нас панель обновлялась по своему расписанию, и выходил рассинхрон:
// в игре юнит уже мёртв, а на портрете ещё жив. Поэтому все правки
// здоровья идут через эту функцию, а она сообщает интерфейсу.
export function healthSet(target, value) {
  if (!target) return 0;
  const было = target.health ?? 0;
  //: Отладочная неуязвимость (knyaz2.profiler.invulnerable). Стоит именно тут,
  //: потому что через эту точку идут ВСЕ пути урона — ближний бой, снаряд,
  //: отрава и ход по глобальной. Лечение при этом работает как обычно.
  if (profiler.invulnerable && target === hero && value < было) return было;
  const стало = Math.max(0, Math.min(healthMax(), Math.round(value)));
  target.health = стало;
  if (стало !== было) world.onHealth?.(target, стало, было);
  return стало;
}
//: Развязка без петли: dialog.js и units.js зовут точку через `world` —
//: напрямую нельзя, effects.js сам тянет units.js.
world.healthSet = healthSet;

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


// Мировой такт: у отравы и у построек РАЗНЫЕ фазы одного счётчика МИРОВЫХ
// ТАКТОВ (VA 0x41C944). Отрава бьёт, когда `такт & 0xF == 0`, а стройка и
// пожар — в else-ветке, когда `(такт + 7) & 0xF == 0`. Период у обоих
// шестнадцать, но совпасть они не могут никогда, и это не мелочь: постройка,
// догоревшая в том же такте, в котором отрава добила её работника, вела бы
// себя иначе.
export function effectsTick() {
  let changed = false;
  // СЧИТАЕМ ТАКТЫ, А НЕ КАДРЫ. Здесь стоял собственный счётчик кадров rAF, и
  // фаза сходилась каждый шестнадцатый КАДР вместо каждого шестнадцатого
  // мирового такта. Мировой такт — 78 мс (12,82 в секунду), кадров же 60 в
  // секунду, а на быстром мониторе и 144: деревня жила в 4,7…11 раз быстрее
  // канона. Отсюда и жалоба «казарма строится мгновенно» — двадцать четыре
  // единицы счётчика проходили за шесть секунд вместо тридцати.
  //
  // `clockPhaseHits` считает ПОПАДАНИЯ фазы за кадр, поэтому догон не теряет
  // тактов, а стоящий счётчик не срабатывает по кругу. Функция чистая, звать
  // её можно из нескольких мест (то же делает village.js).
  const mask = poisonTickEvery() - 1;
  for (let hit = clockPhaseHits(mask, 0); hit > 0; hit -= 1) {
    if (poisonRound()) changed = true;
  }
  const попаданий = clockPhaseHits(mask, BUILD_PHASE_SHIFT);
  //: РУКИ ЗАПОМИНАЕМ, пока стоим на карте: у чужих поселений юнитов в памяти
  //: нет, а стройка там идти обязана (village.js, villageTickAway).
  if (попаданий > 0) village.workers = workersOf();
  //: Чужие поселения — тем же числом тактов, что и своё. Казну и стройку
  //: они считают тут же, а набор карт со сдвинувшейся стройкой нужен ниже:
  //: по нему решается учёба, как флаг `local_38` у движка.
  const строили = villageTickAway(попаданий);
  for (let hit = попаданий; hit > 0; hit -= 1) {
    // Стройка и учёба в один такт не сходятся: 0x41C944:513 зовёт обучение
    // только когда флаг «стройка сдвинулась» пуст.
    const стройка = buildingsTick(village.workers);
    if (стройка) changed = true;
    else if (villageTraining(1)) changed = true;
    // ВАРКА У ЗНАХАРЯ — та же фаза деревень, безусловно: 0x41C944 зовёт
    // FUN_004176C8 (строка 509) рядом с обучением, и на флаг стройки она,
    // в отличие от обучения, не смотрит.
    if (villageBrew(1)) changed = true;
    // Мастерская кузнеца — там же (0x41C944 зовёт FUN_00417BD8 рядом).
    if (villageForge(1)) changed = true;
  }
  // ТО ЖЕ ХОЗЯЙСТВО — И В ДАЛЬНИХ ДЕРЕВНЯХ.
  //
  // В движке фаза идёт по всем двенадцати записям подряд, и ни варка, ни
  // кузница, ни учёба карты не спрашивают: 0x4176C8 и 0x417BD8 зовутся
  // безусловно, 0x4181E8 — когда в этой фазе стройка не сдвинулась. У нас
  // всё это висело на живых юнитах текущей карты, и у брошенной деревни
  // знахарь переставал варить, кузнец ковать, а воевода учить.
  //
  // Должностной дальней деревни — снимок жителя из памяти карт: та же
  // запись, из которой он поднимется при входе (village.js, villageCrew).
  //: Склад и снимки за одну фазу не меняются — собираем их один раз, а не
  //: на каждое попадание: разбор снимков карты не бесплатный.
  const дальние = попаданий > 0
    ? villagesAway().map(([map, kept]) => ({ map, kept, crew: villageCrew(map) }))
    : [];
  for (let hit = попаданий; hit > 0; hit -= 1) {
    for (const { map, kept, crew } of дальние) {
      const data = kept.data;
      if (!data) continue;
      if (!строили.has(map)) villageTraining(1, kept, crew);
      villageBrew(1, data, villageOfficial(data, crew, HEALER_POST));
      villageForge(1, data, villageOfficial(data, crew, SMITH_POST), crew);
    }
  }
  return changed;
}

//: Места должностных в пятёрке +0x3D0: роль движка — «место + 1», отсюда у
//: знахаря 2, у кузнеца 4 (VA 0x415190).
const HEALER_POST = 1;
const SMITH_POST = 3;

// ОДИН КРУГ ОТРАВЫ И СРОКОВ по всему отряду: здоровье убавляется на поле
// отравы, а счётчик временного зелья идёт вниз. Круг вынесен отдельно, потому
// что зовут его ДВА разных места движка одним и тем же кодом:
//
//     мировой такт  (VA 0x41C944) — раз в шестнадцать тактов, где бы отряд
//                    ни был: фильтра по карте у этой ветки нет;
//     ШАГ ПО ГЛОБАЛЬНОЙ (VA 0x4277F4) — на КАЖДЫЙ шаг похода:
//
//         if (юнит[+0x52] != 0) {              // отрава
//             юнит[+0x4E] -= юнит[+0x52];      // здоровье
//             FUN_0041C494(юнит);              // пересчёт
//             if (юнит[+0x4C]>>0x10 < 1) { ... смерть ... }
//             FUN_004305A4(юнит);              // перерисовать портрет
//         }
//         if (юнит[+0x4A] != 0 && --юнит[+0x4A] == 0) {
//             юнит[0xF8] = 0;
//             memcpy(юнит+0xC0, юнит+0xC6, 6);  // вернуть характеристики
//         }
//
// Второго вызова у порта не было вовсе, и поход по глобальной травил в
// шестнадцать раз медленнее оригинала — то есть на глаз не травил совсем.
function poisonRound() {
  let changed = false;
  for (const unit of [hero, ...units]) {
    if (expireTemporary(unit)) changed = true;
    const poison = unit.poison ?? 0;
    if (!poison || unit.alive === false) continue;
    changed = true;
    world.onPoisonDamage?.(unit, poison);
  }
  return changed;
}

//: Шаг похода по глобальной карте — тот же круг, но РОВНО ОДИН и без фазы.
//: Зовёт его ход по карте мира, на каждый принятый шаг.
export function effectsTravelStep() { return poisonRound(); }

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

// РАБОТНИКИ СЧИТАЮТСЯ ПО ОТРЯДУ ДЕРЕВНИ, а не по всей карте (VA 0x41C944,
// строки 358-386). Движок идёт по бойцам отряда поселения и берёт тех, у кого
//
//     облик (+0xFC) меньше шести        — человек, а не зверь и не тварь
//     не труп (+0x1A & 0x80 == 0)
//     порода (+0x17) не 3, не 0xB, не 0xC
//
// затем вычитает занятых должностями: пять слов поселения +0x3D0, сколько их
// непусто. А если отряд деревни в бою (+0x1D == 1), работников НОЛЬ — стройка
// на время боя стоит.
//
// Здесь считались ВСЕ живые юниты карты минус занятые: в делителе
// `(время_вида * 60) / работники` это давало вчетверо больший знаменатель и
// вместе с кадровым счётчиком превращало стройку в мгновенную.
function workersOf() {
  const data = world.map?.village;
  if (!data) return 0;
  const locals = units.filter((unit) => unit.side === data.side
    && unit.alive !== false && !unit.hidden && (unit.body ?? 0) < 6);
  //: «Отряд в бою» у нас поля нет — берём признак по самим жителям.
  if (locals.some((unit) => unitFighting(unit))) return 0;
  const posted = (data.officials ?? []).filter(Boolean).length;
  return Math.max(0, locals.length - posted);
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
      healthSet(target, Math.max(1, Math.floor(target.health / 2)));
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
      // Порядок движка: сложить, ОКРУГЛИТЬ (0x442BF0), потом кламп 1600 и
      // запись (0x41DA44…0x41DA55). `healthSet` делает две последние
      // операции, округление остаётся здесь — иначе потеряется округление
      // к чётному, а `Math.round` в самой точке уже получает целое и
      // ничего не меняет.
      healthSet(target, roundHalfEven(health + cost * (numbers.heal_gain ?? 160)));
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

// ЛЕЧЕБНЫЕ СМЕСИ — ТРИГГЕР ЗДОРОВЬЯ (VA 0x414DF0). Третий тумблер окна
// персонажа (биты +0x19: 0x01 «Здр<50», 0x02 «Здр<75») велит юниту САМОМУ
// пить Лечебный бальзам (класс 0x55) после попадания по нему. Пороги
// АБСОЛЮТНЫЕ — 800 и 1200 сырых (на экране, делённом на 16, это 50 и 75).
// Движок пьёт из мешка по банке, пока здоровье ниже порога и банки
// находятся, и делает это МОЛЧА (в 0x414DF0 нет ни одного вызова 0x42D660).
// Зовут его оба пути урона — ближний бой (0x413894) и прилёт снаряда
// (0x41FDD0); отрава триггер не дёргает.
const HEAL_TRIGGER_LOW = 800;      // «Здр<50», бит 0x01
const HEAL_TRIGGER_HIGH = 0x4B0;   // «Здр<75», бит 0x02

export function healTriggerTick(unit) {
  const mode = unit?.healTrigger ?? 0;
  if (!mode || unit.alive === false) return 0;
  const threshold = mode === 1 ? HEAL_TRIGGER_LOW : HEAL_TRIGGER_HIGH;
  const heal = potionClasses()?.heal ?? 85;
  let drunk = 0;
  while ((unit.health ?? 0) < threshold) {
    const bag = unit.bag ?? [];
    const at = bag.findIndex((name) => name && actorItem(name)?.index === heal);
    if (at < 0) break;
    const name = bag[at];
    const item = actorItem(name);
    if (!item) break;
    // Крепость банки — экземплярная, как у ручного питья из мешка.
    const state = { strength: unit.bagStrength?.[name] ?? item.durability ?? 0 };
    const became = potionDrink(item, unit, state);
    drunk += 1;
    if (became !== null) {
      // Банка опустела — класс меняется на месте (пустая банка), крепость
      // прежнего зелья ей больше не принадлежит.
      const next = classRefByIndex(became);
      bag[at] = next ? actorReclassItemRef(name, next) : null;
      if (unit.bagStrength) delete unit.bagStrength[name];
    } else if (typeof state.strength === "number") {
      unit.bagStrength = unit.bagStrength ?? {};
      unit.bagStrength[name] = state.strength;
    }
  }
  return drunk;
}

//: Имя класса по номеру — как classRef в carry.js: у модулей нет общего
//: владельца этой мелочи, а тянуть carry.js сюда — петля импортов.
function classRefByIndex(index) {
  return Object.entries(world.map?.items ?? {})
    .find(([, item]) => item?.index === index)?.[0] ?? null;
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
    //: Тот же порядок, что у бальзама: сложить, округлить, потом кламп и
    //: запись — их берёт на себя healthSet (VA 0x41DD57…0x41DD7D).
    healthSet(target,
      roundHalfEven(strength * (numbers.heal_gain ?? 160) + (target.health ?? 0)));
  }
  if (kind === codes.wisdom) {
    const drop = power * (set.wisdom_health_drain ?? 160);
    const floor = set.wisdom_health_floor ?? 160;
    healthSet(target, Math.max(floor, (target.health ?? 0) - drop));
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
