// Враги на карте: те же кадры, что у героя, только палитра тела другая и
// приказы отдаёт не игрок, а простой рассудок — заметил, подошёл, ударил.
//
// В движке юниты и герой — одна сущность: общий набор анимаций, слоты
// предметов (рука unit+0x58, вторая рука unit+0x60, метательное unit+0x5A) и
// один список приказов в unit+0x16. Здесь повторяется то, что нужно для боя:
// выбор анимации удара по предмету, смерть жребием из трёх вариантов и уход
// из клетки перед смертью (VA 0x416A52), чтобы труп не работал стеной.
import { world } from "./world.js";
import { clockPhaseHits, tickSeconds } from "./clock.js";
import { isNight } from "./daylight.js";
import { actorAttackPose, actorFrames, actorItem, actorReach, drawActor,
         isBeast } from "./actor.js";
import { context, layeredFrame, withMainContext } from "./viewport.js";
import { drawSelectionCircle, hero, heroAnchor, heroCellKey, heroNeighbor,
         heroPlanPath, heroFree, roster, unitMove, unitMovePose,
         unitUpdateBuilding } from "./hero.js";
import { enemyFor, warbandSwing, warbandsSetup, warbandsTick } from "./warband.js";
import { weaponModeRefresh } from "./inventory.js";
import { mapStateDead } from "./mapstate.js";
import { sfxHumanPose, sfxPose, sfxSwing } from "./sfx.js";

export const units = [];

//: ЭТО ЧИСЛО — НАШЕ, адреса за ним нет. Движок пауз в секундах не знает
//: вовсе: он отмеряет их кадрами анимации (VA 0x413894 крутит счётчик
//: +0xFB и сравнивает с числом кадров блока), а сколько длится кадр,
//: решает частота главного цикла. Пока бой переносится покадрово, здесь
//: стоят подобранные на глаз секунды.
//: Дальность боя, в отличие от него, настоящая: поле +0x10 класса
//: предмета (VA 0x414C01) — лучник достаёт на 15 клеток, мечник на одну.
//:
//: ШАГА здесь больше нет: длительность шага считает общая unitMove по
//: числу кадров походки, как в движке, — оттого бег и быстрее ходьбы.
const ATTACK_COOLDOWN = 1.1;      // секунды между ударами

// Навыки приезжают именами; в бою нужен массив по номерам, как в юните.
function skillList(named) {
  const names = hero.data?.rules?.progression?.skills?.names ?? [];
  return names.map((name) => named?.[name] ?? 0);
}

// То же для характеристик: панель и правила ждут массив по номерам.
function characteristicList(named) {
  const names = hero.data?.rules?.progression?.characteristics?.names ?? [];
  return names.map((name) => named?.[name] ?? 0);
}

// Расстояние в клетках — по мерке движка (VA 0x43B670): берётся большая
// из разниц, и если меньшая больше единицы, прибавляется единица. По этой
// же мерке считаются дальность удара, зрение и догон вожака.
export function cellRange(a, b) {
  if (!a?.cell || !b?.cell) return Infinity;
  const rows = Math.abs(a.cell.row - b.cell.row);
  const cols = Math.abs(a.cell.col - b.cell.col);
  if (rows < cols) return rows > 1 ? cols + 1 : cols;
  return cols > 1 ? rows + 1 : rows;
}

function cellDistance(a, b) { return cellRange(a, b); }

// Спутник — такой же юнит, только своей стороны. Приказ лежит в самом
// юните байтом +0x16, и значения оттуда же:
//
//     0x10  ждать на месте — с ним спутники и стоят в GAME.0, и его же
//           ставит новичку наём (VA 0x433070)
//     0x30  следовать за вожаком — его ставит всему отряду кнопка
//           «Все ко мне» (VA 0x420BFC)
//
// Сам по себе спутник за героем НЕ ходит: приказ на движение получают
// только ВЫБРАННЫЕ юниты (VA 0x4240BC перебирает список выбора 0x840B94),
// а выбор делается кликом по портрету (VA 0x423F80).
//: Байт приказа целиком: старшая половина — БИТЫ режима, младшая —
//: действие (konung2/orders.py). Бит 0x10 и есть «держаться за вожаком»,
//: и других состояний у спутника нет: сняли бит — стоит на месте.
export const ORDER_FOLLOW = 0x10;

//: Список выбранных: до девяти юнитов, как в движке.
// Выбор отряда живёт в orders.js — он общий для панели, щелчков и
// приказов, как список 0x840B94 в движке.
export { isSelected, select as selectUnit, selection } from "./orders.js";
import { followDistance, follows, isSelected, orderClear } from "./orders.js";

// Обратный перевод: живой юнит -> запись бойца отряда.
//
// В движке наём (VA 0x433070) копирует ЗАПИСЬ юнита в слот отряда игрока:
// `слот = (первый + число бойцов) * 0x100`, счётчик +0x1C растёт на единицу,
// сторона становится игроковой, приказ 0x16 = 0x10 «за вожаком», рабочие
// места +0xE6 забиваются 0xFF, младшие три бита породы гаснут. Дальше боец
// живёт В ЗАПИСИ ОТРЯДА — а она сохраняется целиком и переезжает с игроком.
//
// Порт же только ставил юниту карты `ally = true`. Отряд при этом брался из
// статического списка пака, поэтому наёмник не показывался в панели и
// пропадал на первой же смене карты: на новой карте его попросту нет.
function namedFrom(kind, list) {
  const names = hero.data?.rules?.progression?.[kind]?.names ?? [];
  const out = {};
  names.forEach((name, at) => { out[name] = list?.[at] ?? 0; });
  return out;
}

export function memberFromUnit(unit) {
  return {
    index: unit.slot, name: unit.name,
    face: unit.face ?? 0, body: unit.body ?? 0, palette: unit.palette ?? 0,
    breed: unit.breed ?? 0, side: unit.side ?? 0,
    level: unit.level ?? 1,
    health: unit.health, armour: unit.stats?.armour,
    accuracy: unit.stats?.accuracy,
    order: unit.orderByte ?? ORDER_FOLLOW,
    dialog: unit.dialogNumber ?? unit.dialog?.number ?? null,
    skills: namedFrom("skills", unit.skills),
    characteristics: namedFrom("characteristics", unit.baseCharacteristics),
    current: namedFrom("characteristics", unit.characteristics),
    equipment: { ...(unit.equipment ?? {}) },
    bag: [...(unit.bag ?? [])],
    money: unit.money ?? 0,
    experience: unit.experience ?? 0,
    next_level: unit.nextLevel ?? 0,
    free_xp: unit.freeExperience ?? 0,
    progress_lock: Boolean(unit.progressLock),
    // Нажитое вещами (крепость, чары, заряды) уже разобрано в живом юните —
    // проносим как есть, иначе наёмник растерял бы его при переезде.
    runtime: {
      enchant: { ...(unit.enchant ?? {}) },
      bagEnchant: { ...(unit.bagEnchant ?? {}) },
      bagStrength: { ...(unit.bagStrength ?? {}) },
      bagCount: { ...(unit.bagCount ?? {}) },
      bagPoison: { ...(unit.bagPoison ?? {}) },
    },
  };
}

// НАЁМ: дописать бойца в запись отряда игрока (аналог 0x433070).
export function partyHire(unit) {
  const party = hero.party ?? hero.data?.template?.party ?? null;
  if (!party || !unit) return false;
  party.members = party.members ?? [];
  const already = party.members.some((member) => member.index === unit.slot);
  if (!already) party.members.push(memberFromUnit(unit));
  return !already;
}

function spawnCompanion(member, map, index) {
  const hand = actorItem(member.equipment?.hand, map.items);
  const anchor = heroAnchor(hero.cell.row, hero.cell.col + 1 + index);
  return {
    id: `mate_${member.index}`,
    // Номер слота юнита: по нему движок держит список выбора в порядке
    // адресов записей (VA 0x423F80), они лежат подряд через 0x100.
    slot: member.index ?? 0,
    name: member.name,
    x: anchor.x, y: anchor.y,
    cell: { row: hero.cell.row, col: hero.cell.col + 1 + index },
    home: { row: hero.cell.row, col: hero.cell.col + 1 + index },
    direction: 6, stance: "peace", pose: "stand", frame: 0, frameTime: 0,
    // Палитра спутника — его собственная (+0x2E), а не ноль: движок красит
    // каждого юнита его палитрой (VA 0x425DB4). С нулём спутник не мог быть
    // покрашен в принципе.
    palette: member.palette ?? 0,
    side: hero.side ?? 0,
    face: member.face ?? 0,
    // тело = актёр голоса: свои отклики на выбор и свои приветствия
    body: member.body ?? 0,
    level: member.level ?? 1,
    hostile: false,
    ally: true,
    // Приказ из самой записи юнита (+0x16). ВАЖНО: спутники стоят там, где
    // их оставили, и сами за игроком НЕ ходят — за вожаком их посылает
    // только кнопка «Все ко мне» (VA 0x420BFC ставит всему отряду 0x30).
    // В коде движка бит 0x10 включает догон (VA 0x411355), но в игре отряд
    // без зова не бродит, и игрок на этом настоял; поэтому на старте бит
    // снят, а кнопка его ставит.
    orderByte: (member.order ?? 0) & ~ORDER_FOLLOW,
    dialog: null,
    // номер диалога — «голос» для питча реплик и откликов (_VOICES)
    dialogNumber: member.dialog ?? null,
      equipment: {
        hand: member.equipment?.hand ?? null,
        off_hand: member.equipment?.shield ?? member.equipment?.off_hand ?? null,
        ranged: member.equipment?.ranged ?? null,
        body: member.equipment?.body ?? null,
        head: member.equipment?.head ?? null,
        ammo: member.equipment?.ammo ?? null,
        necklace: member.equipment?.necklace ?? null,
        bracelet_1: member.equipment?.bracelet_1 ?? null,
        bracelet_2: member.equipment?.bracelet_2 ?? null,
        ring_1: member.equipment?.ring_1 ?? null,
        ring_2: member.equipment?.ring_2 ?? null,
    },
    // Чем бьётся спутник — тот же байт unit+0xEE и то же правило, что у
    // юнитов карты: стреляет тот, у кого есть И метательное, И боеприпас
    // (VA 0x412FF4). Оружие в руке этому не мешает.
    rangedMode: Boolean(member.equipment?.ranged) && Boolean(member.equipment?.ammo),
    skills: skillList(member.skills),
    // У спутника всё СВОЁ: панель персонажа в движке работает с тем
    // юнитом, который выбран (0x849514, VA 0x4292DC), а не с героем.
    characteristics: characteristicList(member.current),
    baseCharacteristics: characteristicList(member.characteristics),
    bag: [...(member.bag ?? [])],
    // экземплярные поля вещей (В10): крепость и слово чар по имени
    ...instanceMaps(member),
    // Нажитое наёмником уже разобрано — оно приезжает в записи готовым.
    ...(member.runtime ?? {}),
    money: member.money ?? 0,
    experience: member.experience ?? 0,
    nextLevel: member.next_level ?? 0,
    freeExperience: member.free_xp ?? 0,
    progressLock: Boolean(member.progress_lock),
    stats: {
      health: member.health, armour: member.armour,
      accuracy: member.accuracy ?? 60,
      parry: member.current?.["Ловкость"] ?? 10,
      toughness: member.current?.["Выносливость"] ?? 10,
      strength: member.current?.["Сила"] ?? 10,
    },
    // Потолок здоровья один на всех — 0x640 (VA 0x41C494), а не текущее
    // здоровье бойца: иначе раненый спутник выглядел бы целым.
    health: member.health, maxHealth: healthMax(),
    // своя отрава твари (unit+0xF6): у людей ноль
    venom: member.venom ?? 0,
    poison: 0,
    speed: 2, sight: 10,
    // Дальности здесь НЕТ: она считается по активному оружию каждый раз
    // (actorReach), потому что режим оружия меняется на ходу.
    alive: true, cooldown: 0, path: [], step: null, hurt: 0,
  };
}

export function unitsSetup(map) {
  units.length = 0;
  // Отряды карты: враждебность принадлежит им, а не юнитам.
  warbandsSetup(map);
  hero.occupiedBy = (row, col, mover) => unitBlocks(row, col, mover);
  hero.eachOccupant = eachOccupant;
  // Спутники отряда идут в мир вместе с героем: первый в списке — он сам.
  const party = map.hero?.template?.party ?? hero.party;
  (party?.members ?? []).slice(1).forEach((member, index) => {
    units.push(spawnCompanion(member, map, index));
  });
  // ЖИТЕЛИ БЕРУТСЯ ИЗ МИРА ВЫБРАННОГО ГЕРОЯ. Наборы разные: в мире Ратибора
  // Велиславна — обычная жительница Чёрного Бора, а в её собственном мире её
  // среди жителей нет вовсе (первая запись карты 19 в GAME.1 — сам герой).
  // Пока набор брался всегда из мира 0, за Велиславну на карте стоял её
  // двойник, с которым можно было заговорить.
  const world = map.hero?.template?.world ?? hero.data?.template?.world ?? 0;
  const roster = map.units_by_world?.[String(world)] ?? map.units ?? [];
  // Нанятый разговором житель уже приехал бойцом отряда — вторым
  // экземпляром на своей родной карте его поднимать нельзя.
  //
  // Сверяем по `id`: поля `index` у записей пака НЕТ вовсе, номер слота
  // зашит в строку вида `unit_333`, и `unitSpawn` достаёт его оттуда.
  // Сверка по `entry.index` не срабатывала никогда — на родной карте
  // наёмник поднимался дважды.
  const вотряде = new Set((party?.members ?? [])
    .map((member) => `unit_${member.index}`));
  // УБИТЫЕ ОСТАЮТСЯ УБИТЫМИ. В движке отдельной памяти не нужно: запись
  // юнита с поднятым битом 0x80 (unit+0x1A) продолжает лежать в отряде и
  // уезжает в сохранение вместе с ним. Здесь юниты карты пересоздаются из
  // пака при каждом входе, поэтому зачищенная карта оживала целиком.
  const мёртвые = mapStateDead(map.legacy?.map_number);
  for (const entry of roster) {
    if (вотряде.has(entry.id)) continue;
    const slot = Number(String(entry.id ?? "").replace(/\D+/g, ""));
    if (мёртвые.has(slot)) continue;
    unitSpawn(entry, map);
  }
  // Состояние постройки — СРАЗУ, а не после первого шага. Движок держит
  // клетку и её биты в самой записи юнита и смотрит их при отрисовке
  // (VA 0x425AA8), поэтому для стоящего на месте они значат ровно то же,
  // что для идущего. Без этого жители при должности — купец, староста,
  // воевода, знахарь — никуда не ходят, бита «внутри» не получают и
  // уезжают под пол собственного дома.
  for (const unit of units) unitUpdateBuilding(unit);
  return units;
}

// Поставить одного юнита из описания пака. Тем же путём приходят и жители
// карты, и встречный отряд с глобальной: описание у них одинаковое.
export function unitSpawn(entry, map = world.map) {
  {
    const hand = actorItem(entry.equipment?.hand, map?.items);
    const ranged = actorItem(entry.equipment?.ranged, map?.items);
    // Встречный отряд приходит без готовых координат: место названо
    // клеткой, а пиксели считаются якорем сетки, как у всех.
    const cell = entry.cell ?? { row: 0, col: 0 };
    const position = entry.position ?? heroAnchor(cell.row, cell.col);
    units.push({
      id: entry.id,
      // тот же номер слота, что у спутников: он зашит в id (unit_NNN)
      slot: entry.slot ?? (Number(String(entry.id ?? "").replace(/\D+/g, "")) || 0),
      name: entry.name,
      x: position.x,
      y: position.y,
      cell: { ...cell },
      home: { ...cell },
      direction: 6,
      stance: "peace",
      pose: "stand",
      frame: 0,
      frameTime: 0,
      palette: entry.palette ?? 0,
      // Сторона юнита — байт unit+0x1B: у жителей Черного Бора она своя (55),
      // у героя ноль. Правила «кто кому враг» в движке мы ещё не нашли,
      // поэтому нападают только те, кого расстановка объявила враждебными,
      // и те, кого ударили.
      side: entry.side ?? 0,
      // навыки юнита: по ним считается точность его ударов
      skills: skillList(entry.skills),
      face: entry.face ?? null,
      level: entry.level ?? 1,
      hostile: entry.hostile !== false,
      // Рабочие места жителя и сколько ему ещё стоять на текущем.
      workplaces: entry.workplaces ?? [],
      workRest: 0,
      dialog: entry.dialog ?? null,
      // номер разговора (unit+0xF2): по нему курсор решает, можно ли
      // заговорить с лежачим (VA 0x428B88)
      dialogNumber: entry.dialog_number ?? 0xFF,
      equipment: {
        hand: entry.equipment?.hand ?? null,
        off_hand: entry.equipment?.off_hand ?? null,
        ranged: entry.equipment?.ranged ?? null,
        body: entry.equipment?.body ?? null,
        head: entry.equipment?.head ?? null,
        // боеприпас — отдельное поле юнита (+0x50), не ячейка мешка
        ammo: entry.equipment?.ammo ?? null,
      },
      // Чем бьётся — байт unit+0xEE. Движок пересчитывает его, когда юнит
      // впервые задумывается: стреляет тот, у кого есть И метательное, И
      // боеприпас (VA 0x412FF4). Меч в руке этому не мешает.
      rangedMode: entry.ranged_mode ?? (Boolean(ranged) && Boolean(entry.equipment?.ammo)),
      // ЗАПАСНОЕ — ПОЛНОЕ ЗДОРОВЬЕ, А НЕ СОТНЯ. Сто — это число из шкалы
      // ПОКАЗА (движок печатает health/16, VA 0x42A8F4), и в сыром поле оно
      // значит 100 из 1600, то есть шесть процентов и почти пустая полоска.
      // Сейчас запасное не срабатывает — у всех юнитов пака здоровье есть, —
      // но ошибка та же самая «1600 против 100», только с другой стороны.
      stats: { ...(entry.stats ?? {}),
               health: entry.health ?? entry.stats?.health ?? healthMax() },
      health: entry.health ?? entry.stats?.health ?? healthMax(),
      // тот же общий потолок 0x640, а не «сколько было при появлении»
      maxHealth: healthMax(),
      // порода и тело: по ним юнит и выглядит собой (VA 0x424200)
      breed: entry.breed ?? 0,
      // зверь — бит 0x40 той же породы (+0x1A): у него своя точность
      // (VA 0x41ADED) и своя, короткая, формула опыта за убийство
      // (VA 0x41B044, ветка else)
      beast: Boolean((entry.breed ?? 0) &
        (map?.hero?.rules?.progression?.beast_flag?.mask ?? 0x40)),
      body: entry.body ?? 0,
      venom: entry.venom ?? 0,
      // отрава на вещах юнита: у Славуна болты, у Святовита стрелы
      poisonOn: entry.poison_on ?? {},
      poison: 0,
      // чем торговать: свои деньги, свой мешок, а у должностей 2, 3 и 4 —
      // ещё и прилавок деревни (VA 0x43346C)
      money: entry.money ?? 0,
      bag: [...(entry.bag ?? [])],
      // экземплярные поля вещей (В10): крепость и слово чар по имени
      ...instanceMaps(entry),
      role: entry.role ?? 0,
      counter: [...(entry.counter ?? [])],
      speed: entry.speed ?? 2,
      sight: entry.sight_cells ?? 10,
      // Дальности здесь НЕТ: её считает actorReach по АКТИВНОМУ оружию.
      // Раньше рука была приоритетнее лука, и стрелок с мечом мерил
      // дальность мечом — то есть не мог выстрелить никогда.
      alive: true,
      cooldown: 0,
      path: [],
      step: null,
      hurt: 0,                    // время подсветки после попадания
    });
  }
  // Юнит может прийти и после расстановки — встречным отрядом с глобальной
  // карты; клетка у него уже есть, значит и биты постройки считаются сразу.
  return unitUpdateBuilding(units[units.length - 1]);
}

// Кадры юнита берутся из того же документа, что и у героя.
function data() { return hero.data; }

// Потолок здоровья — 0x640 на всех (VA 0x41C494). Читаем правило пака прямо,
// а не через effects.js: тот сам импортирует units.js, и вышла бы петля.
function healthMax() {
  return world.map?.hero?.rules?.effects?.health?.max ?? 1600;
}

// ЭКЗЕМПЛЯРНЫЕ поля вещей юнита из пака (В10): крепость/износ и слово
// чар живут в ЗАПИСИ предмета (+0x04/+0x0E), пак несёт их параллельно
// мешку (bag_details) и по гнёздам (equipment_details); в порте они
// ложатся в карты по ССЫЛКЕ ЭКЗЕМПЛЯРА: два одинаковых класса больше не
// делят крепость, чары или отраву.
export function actorInstanceMaps(entry) {
  const out = { bagStrength: {}, bagCount: {}, bagEnchant: {}, bagPoison: {}, enchant: {},
                poisonOn: { ...(entry.poison_on ?? {}) }, wear: {}, wearMax: {},
                itemOiled: {} };
  const carried = (names, details) => {
    (details ?? []).forEach((detail, at) => {
      const name = names?.[at];
      if (!name || !detail) return;
      if (typeof detail.strength === "number") {
        out.bagStrength[name] = detail.strength;
        out.wear[name] = detail.strength;
        if (typeof detail.max === "number") out.wearMax[name] = detail.max;
      }
      if (typeof detail.count === "number") out.bagCount[name] = detail.count;
      if (detail.enchant) out.bagEnchant[name] = detail.enchant;
      if (detail.poison) out.bagPoison[name] = detail.poison;
      if (detail.oiled) out.itemOiled[name] = true;
    });
  };
  carried(entry.bag ?? [], entry.bag_details ?? []);
  carried(entry.counter ?? [], entry.counter_details ?? []);
  for (const [slot, detail] of Object.entries(entry.equipment_details ?? {})) {
    if (!detail) continue;
    const target = slot === "shield" ? "off_hand" : slot;
    if (detail.enchant) out.enchant[target] = detail.enchant;
    if (detail.poison) out.poisonOn[target] = detail.poison;
    if (target === "ammo" && typeof detail.count === "number") {
      out.ammoCount = detail.count;
    }
    const name = entry.equipment?.[slot] ?? entry.equipment?.[target];
    if (name && detail.oiled) out.itemOiled[name] = true;
    if (name && typeof detail.strength === "number") {
      out.wear[name] = detail.strength;
      if (typeof detail.max === "number") out.wearMax[name] = detail.max;
    }
  }
  out.ammoPoison = out.poisonOn.ammo ?? 0;
  return out;
}

const instanceMaps = actorInstanceMaps;

function setPose(unit, pose) {
  if (unit.pose === pose) return;
  unit.pose = pose;
  unit.frame = 0;
  unit.frameTime = 0;
  // Озвучка смены анимации — как 0x429B2C: звери по виду с шансами движка,
  // люди — крики боли и смерти, замах и выстрел по оружию.
  sfxPose(unit, pose);
  sfxHumanPose(unit, pose);
  if (!unit.beast && pose.startsWith("attack")) sfxSwing(unit);
}

// РАЗГОВОР ОСТАНАВЛИВАЕТ СОБЕСЕДНИКА (VA 0x413894, случай 0x0C). Пока
// игрок идёт заговорить или окно разговора открыто, NPC поворачивается к
// нему и стоит; как только разговор кончился — приказ снимается, и он
// идёт своей дорогой дальше. Игрок при этом тоже поворачивается к
// собеседнику.
//
// Направление даёт VA 0x43B7D0, и порядок у неё обратный: первая пара —
// откуда смотрят, вторая — на кого, а возвращает она направление ОТ
// ВТОРОГО К ПЕРВОМУ. Поэтому «повернуться к игроку» — это направление,
// посчитанное от игрока к юниту.
function talkingWith(unit) {
  const talk = world.talking;
  if (talk?.unit === unit) return true;
  // игрок ещё идёт: приказ «заговорить» нацелен на этого юнита
  const kinds = data()?.rules?.orders?.kind ?? { talk: 2 };
  return hero.orderKind === kinds.talk && hero.orderTarget === unit;
}

function faceEachOther(unit) {
  // Направление меняем, только когда юнит не в шаге: начатый шаг движок
  // тоже не обрывает, а разворот посреди него выглядел бы рывком.
  if (!unit.step) unit.direction = directionTo(unit, hero);
  unit.path = [];
  unit.goal = null;
  unit.workRest = 0;
  if (world.talking?.unit === unit) hero.direction = directionTo(hero, unit);
}

// Держится ли приказ «стой, с тобой говорят» (VA 0x413894, случай 0x0C).
// Условие ровно одно из двух: открыто окно разговора и это его собеседник,
// либо у игрока приказ «заговорить» нацелен на этого юнита. Отпало —
// приказ снимается (VA 0x416E24), и юнит идёт своей дорогой дальше.
function waitingToTalk(unit) {
  const kinds = data()?.rules?.orders?.kind ?? { wait_talk: 0x0C };
  if ((unit.orderKind ?? 0) !== (kinds.wait_talk ?? 0x0C)) return false;
  if (talkingWith(unit)) return true;
  orderClear(unit);
  return false;
}

// ЖИЗНЬ ДЕРЕВНИ (VA 0x412C0C). Житель не стоит столбом: у него список
// рабочих мест (до восьми номеров в unit+0xE6), а у отряда — таблица этих
// мест с клеткой, весом выбора и сроком. Из подходящих времени суток мест
// выбирается одно случайно с весом старшей половины байта, житель идёт
// туда и остаётся на срок из младшей. У видов 0x70…0xA0 работа долгая
// (rand()%180 + 60), у прочих короткая (rand()%(срок*2) + 15).
function workplaceTable() { return world.map?.village?.workplaces ?? null; }

function pickWorkplace(unit) {
  const table = workplaceTable();
  const mine = unit.workplaces ?? [];
  if (!table || mine.length < 1) return null;
  const ночь = isNight();
  const годные = [];
  for (const number of mine) {
    const place = table.find((row) => row.slot === number);
    if (!place) continue;
    // Признак 0x10 делит места на дневные и ночные.
    if (Boolean(place.night) !== ночь) continue;
    годные.push(place);
  }
  if (!годные.length) return null;
  // Выбор с весом: складываем веса и бросаем по сумме.
  let сумма = 0;
  const пороги = годные.map((place) => (сумма += Math.max(1, place.weight)));
  const бросок = сумма < 2 ? 0 : Math.floor(Math.random() * сумма);
  const место = годные[пороги.findIndex((край) => бросок < край)] ?? годные[0];
  const срок = место.long
    ? Math.floor(Math.random() * 180) + 60
    : Math.floor(Math.random() * Math.max(1, место.stay * 2)) + 15;
  return { ...место, срок };
}

function followRules() { return data()?.rules?.orders?.follow ?? null; }

// Куда встать возле вожака (VA 0x41209C). Движок берёт клетку из таблицы
// построения: направление — ОТ СПУТНИКА К ВОЖАКУ, чётность — строки
// вожака, место — со случайного из двенадцати по кругу. Годится клетка в
// пределах карты, проходимая и по ту же сторону стены, что вожак. Не
// нашлось за двенадцать — направление сдвигается, и так четыре захода.
function formationSpot(unit, leader) {
  const set = followRules();
  const table = set?.formation;
  if (!table || !leader?.cell) return null;
  const parity = leader.cell.row & 1;
  const rows = table[parity];
  if (!rows) return null;
  let direction = directionTo(unit, leader);
  const inside = hero.buildingCells?.get(heroCellKey(leader.cell.row, leader.cell.col));
  for (let attempt = 0; attempt < (set.tries ?? 4); attempt += 1) {
    const slots = rows[direction % rows.length] ?? [];
    let slot = Math.floor(Math.random() * slots.length);
    for (let step = 0; step < slots.length; step += 1) {
      const [drow, dcol] = slots[slot] ?? [0, 0];
      const row = leader.cell.row + drow;
      const col = leader.cell.col + dcol;
      if (row > 0 && row < 0xFF && col > 0 && col < 0x9F && heroFree(row, col)) {
        // «по ту же сторону стены»: клетка внутри постройки годится
        // только тому, чей вожак тоже внутри неё.
        const here = hero.buildingCells?.get(heroCellKey(row, col));
        if (Boolean(here) === Boolean(inside)) return { row, col };
      }
      slot = (slot + 1) % slots.length;
    }
    direction = (direction + 1) % rows.length;
  }
  return null;
}

function directionTo(unit, target) {
  const steps = data()?.direction_steps ?? [];
  let best = unit.direction;
  let bestScore = -Infinity;
  const dx = target.x - unit.x;
  const dy = target.y - unit.y;
  for (let i = 0; i < steps.length; i += 1) {
    const [sx, sy] = steps[i];
    const length = Math.hypot(sx, sy) || 1;
    const score = (dx * sx + dy * sy) / length;
    if (score > bestScore) { bestScore = score; best = i; }
  }
  return best;
}



// Смерть: жребий из трёх вариантов, номер сохраняется в позе трупа
// (VA 0x416A5D и 0x41471E), и юнит уходит из своей клетки.
function die(unit) {
  unit.alive = false;
  unit.step = null;
  unit.path = [];
  // Тело 15 не оставляет трупа: движок поднимает ему бит 0x80 породы и
  // тут же очищает клетку (VA 0x416A15). Такой зверь просто исчезает.
  const vanishing = data()?.rules?.creatures?.vanishing;
  if (vanishing && unit.body === vanishing.body) {
    unit.hidden = true;
    unit.cell = null;
    return;
  }
  // ЖРЕБИЙ ТОЛЬКО У ЛЮДЕЙ (VA 0x416A00). Функция смерти начинается с
  // проверки бита 0x40 породы: человеку она бросает остаток от деления на
  // три и берёт блок 3, 11 или 12, а ТВАРИ кладёт блок 3 без всякого
  // жребия — второй и третьей анимации смерти у неё просто нет.
  //
  // Отсюда и «убитая тварь продолжает стоять»: мы бросали жребий всем, и
  // на death_2/death_3 набор твари откатывался к позе «стоять».
  const rules = data()?.rules ?? {};
  const variants = isBeast(unit)
    ? (rules.beast_death_variants ?? 1)
    : (rules.death_variants ?? 3);
  setPose(unit, `death_${1 + Math.floor(Math.random() * variants)}`);
  // Смерть снимает приказ и обнуляет здоровье (VA 0x416A00, хвост).
  unit.orderKind = 0;
  unit.orderByte = 0;
  unit.orderTarget = null;
  unit.health = 0;
}

export function unitDamage(unit, amount, attacker = null) {
  if (!unit.alive) return false;
  // Отряд жертвы поднимает не урон, а ЗАМАХ (см. warbandSwing) — здесь
  // объявление нужно только для урона, пришедшего мимо замаха: долетевшая
  // стрела поднимает отряд жертвы в миг попадания (VA 0x41FDD0).
  if (attacker && (attacker.side ?? 0) !== (unit.side ?? 0)) {
    warbandSwing(attacker, unit, units);
  }
  unit.health -= amount;
  unit.hurt = 0.25;
  if (unit.health <= 0) {
    unit.health = 0;
    die(unit);
    return true;
  }
  // Реакция на удар — блок 2, короткая и общая для всех стоек. СЛАБЫЙ
  // удар (урон меньше 0x30 = 48, код −1 из 0x41C194) жертву НЕ
  // прерывает: движок зовёт 0x416740(жертва, 2) только при коде 0
  // (0x413894: `if (local_20 == 0) FUN_00416740(puVar5, 2)`).
  if (amount >= 0x30 && data()?.animations?.actions?.hit) setPose(unit, "hit");
  return false;
}

// Попадание по юниту: точка ног внизу, тело уходит вверх примерно на 90
// пикселей и вширь на 28 — это габариты кадра на холсте 256x150. Клик по
// ногам, по груди и по голове должны попадать одинаково.
//: ПРЯМОУГОЛЬНИК ПОД МЫШЬЮ — НАШ, адресов за этими числами нет. Движок
//: ищет юнита под курсором ПОПИКСЕЛЬНО, по маске нарисованного кадра
//: (VA 0x425DB4 в конце отрисовки зовёт 0x442260 и запоминает попавшего),
//: то есть точность у него ровно по силуэту. Пока маски кадров в клиенте
//: не заведены, здесь стоит грубая рамка по размеру тела.
const BODY_HALF_WIDTH = 30;
const BODY_HEIGHT = 92;
const BODY_BELOW = 14;

export function unitAt(x, y, withDead = false) {
  let best = null;
  let bestScore = Infinity;
  // Герой — такой же юнит отряда (в движке он просто нулевая запись того
  // же массива), поэтому щелчок по его ТЕЛУ обязан выбирать его так же,
  // как щелчок по портрету. Раньше он в переборе не участвовал вовсе.
  for (const unit of roster(units)) {
    if (!unit.alive && !withDead) continue;
    const dx = Math.abs(unit.x - x);
    const dy = y - unit.y;                 // положительное — ниже ног
    if (dx > BODY_HALF_WIDTH || dy > BODY_BELOW || dy < -BODY_HEIGHT) continue;
    const score = dx + Math.abs(dy + BODY_HEIGHT / 2) * 0.4;
    if (score < bestScore) { best = unit; bestScore = score; }
  }
  return best;
}

// Кого юнит считает врагом. Разбор целиком канонический и живёт в
// warband.js: врага выбирает не юнит, а его ОТРЯД (VA 0x415B20 объявляет
// бой по зоне, 0x4107EC берёт соседа, 0x410010 — дальнюю цель). Поля
// «злой/добрый» в движке нет вовсе, поэтому и здесь его больше нет.
function enemyOf(unit) {
  return enemyFor(unit, units, (row, col, direction) =>
    heroNeighbor(row, col, direction));
}

// ДОСТАЛ ОРУЖИЕ — ДОСНАРЯДИЛСЯ (VA 0x4111E8 -> 0x412FF4). Движок делает это
// РОВНО ОДИН РАЗ за бой: пересчёт зовётся, пока не взведён бит 0x04 байта
// +0x19 (боевая стойка), и сразу после него бит ставится. У нас та же стойка
// — поле stance, и переход в неё и есть тот самый момент.
//
// Без этого юнит с луком В МЕШКЕ лучником не становился: гнездо метательного
// оставалось пустым, а выбор цели для выстрела (VA 0x411F28) требует занятого.
function drawWeapons(unit) {
  if (unit.stance === "combat") return;
  unit.stance = "combat";
  weaponModeRefresh(unit);
}

function attack(unit) {
  drawWeapons(unit);
  unit.direction = directionTo(unit, unit.target ?? hero);
  setPose(unit, actorAttackPose(data(), unit));
  unit.cooldown = ATTACK_COOLDOWN;
  return unit;
}

// Урон наносится в середине анимации — тогда же, когда в кадре проходит рука.
// На каком кадре анимации приходит урон (VA 0x413894). Движок сверяет
// номер кадра с «число кадров − 2», то есть удар ложится на ПРЕДПОСЛЕДНЕМ
// кадре, а не в середине замаха. Выстрел для сравнения срывается на шестом
// с конца — оттого лук и виден натянутым дольше, чем меч занесённым.
function strikeLands(unit, before, after) {
  const frames = actorFrames(data(), unit);
  if (!frames?.length) return false;
  const set = data()?.rules?.accuracy?.projectiles;
  const fromEnd = isShootingPose(unit.pose)
    ? (set?.shot_frame_from_end ?? 6)
    : (set?.melee_hit_frame_from_end ?? 2);
  const hit = Math.max(0, frames.length - fromEnd);
  return before < hit && after >= hit;
}

// Позы, на которых юнит наносит удар. Стрельба сюда входит наравне с ближним
// боем: в движке это ОДИН И ТОТ ЖЕ разбор такта анимации (VA 0x413894), где
// блоки лука и самострела (case 4 и 0x0A) на кадре «всего − 6» зовут
// 0x41BB10 — запуск снаряда — и вычитают стрелу из пачки.
//
// Раньше здесь стоял голый `pose.startsWith("attack")`, а поза стрельбы
// зовётся shoot_bow/shoot_crossbow — условие не выполнялось никогда, и
// стрелки-NPC бесконечно тянули тетиву: ни снаряда, ни расхода стрел, ни
// урона.
export function isShootingPose(pose) {
  return pose === "shoot_bow" || pose === "shoot_crossbow";
}

function isStrikePose(pose) {
  return Boolean(pose) && (pose.startsWith("attack") || isShootingPose(pose));
}

//: На каком кадре замах «объявляет войну» (VA 0x413894 сверяет unit+0x1C,
//: номер кадра анимации, с двойкой). Это РАНЬШЕ урона: отряд жертвы
//: поднимается уже на замахе, независимо от того, попадёт удар или нет.
const SWING_DECLARES_AT = 2;

function swingDeclares(before, after) {
  return before < SWING_DECLARES_AT && after >= SWING_DECLARES_AT;
}

// Спутник идёт туда, куда ему велели: приказ ему уже выдал orders.js, а
// здесь только прокладывается путь.
function walkToOrder(unit) {
  if (unit.orderRow === undefined || unit.orderRow === null) return false;
  if (unit.cell.row === unit.orderRow && unit.cell.col === unit.orderCol) {
    // Дошёл — движок разбирает приказ той же функцией, что и у героя
    // (VA 0x4115AC берёт юнита аргументом), поэтому спутник умеет
    // обыскивать кучи и заговаривать.
    world.onUnitArrived?.(unit);
    return false;
  }
  if (!unit.path.length) {
    // Кому позволено стоять на клетке приказа — тот, ради кого приказ и дан:
    // враг, лежачий или собеседник лежит в orderTarget (поле +0x10 движка).
    unit.goal = { row: unit.orderRow, col: unit.orderCol };
    unit.goalTarget = unit.orderTarget ?? null;
    unit.path = heroPlanPath(unit.cell, unit.goal, unit, unit.goalTarget) ?? [];
    if (!unit.path.length) {
      unit.goal = null;
      unit.goalTarget = null;
      // Дойти некуда: клетка занята или отрезана. Приказ на этом кончается
      // — иначе юнит навсегда остаётся «занят» (бит 0x40) и больше не
      // слушается ни вожака, ни собственного рассудка. Завершение приказа
      // снимает и вид, и бит (VA 0x416E24, маска 0xB0).
      orderClear(unit);
      return false;
    }
  }
  return unit.path.length > 0;
}

// Может ли юнит ударить прямо сейчас (VA 0x414AF8). Для стрельбы движок
// требует трёх вещей: до цели не меньше ТРЁХ клеток (в упор не стреляют),
// не дальше дальности оружия, и чистой траектории — он шагает от стрелка
// к цели и на первой же клетке с битом 0x4000 («стена или постройка»)
// выстрел отменяет. Ближний бой ничем из этого не ограничен.
export function canStrike(unit, target, distance) {
  if (!unit.rangedMode || !unit.equipment?.ranged || !target) return true;
  const set = hero.data?.rules?.accuracy;
  if (distance < (set?.ranged_min_cells ?? 3)) return false;
  return lineOfFire(unit.cell, target.cell);
}

// Трассировка выстрела по клеткам. Идём от стрелка к цели и смотрим, не
// встала ли на пути глухая клетка.
function lineOfFire(from, to) {
  if (!from || !to) return true;
  const steps = Math.max(Math.abs(to.row - from.row), Math.abs(to.col - from.col));
  if (steps <= 1) return true;
  for (let step = 1; step < steps; step += 1) {
    const row = Math.round(from.row + (to.row - from.row) * step / steps);
    const col = Math.round(from.col + (to.col - from.col) * step / steps);
    if (row === to.row && col === to.col) return true;
    if (world.solidAt?.(row, col)) return false;
  }
  return true;
}

export function unitsTick(now, dt) {
  if (!data() || !world.map) return false;
  // Отряды решают вражду ДО того, как юниты начнут выбирать цели: в движке
  // это тоже отдельный проход мирового такта (VA 0x41C944 -> 0x415B20).
  // Идёт он не каждый кадр браузера, а раз в 16 мировых тактов — счётчик
  // один на всю игру (clock.js, аналог _DAT_0084962c).
  const рабочаяФаза = clockPhaseHits(0xF);
  if (рабочаяФаза) warbandsTick(units);
  let active = false;
  for (const unit of units) {
    if (unit.hurt > 0) unit.hurt = Math.max(0, unit.hurt - dt);
    if (unit.cooldown > 0) unit.cooldown = Math.max(0, unit.cooldown - dt);

    if (unit.alive) {
      // Цель: ближайший из враждебных (см. оговорку у enemyOf).
      const target = enemyOf(unit);
      const distance = target ? cellDistance(unit, target) : Infinity;
      const sees = Boolean(target) && distance <= unit.sight;
      const acting = Boolean(data().animations.actions?.[unit.pose]);
      unit.target = sees ? target : null;
      if (!acting) {
        // Ветки решают ТОЛЬКО «куда идти»; сам шаг делает общая для всех
        // unitMove — в движке шагают все одним кодом (VA 0x41615A).
        //
        // ПЕРВЫМ — приказ «стой, с тобой говорят». Он сильнее всего
        // остального не по нашему выбору, а по устройству движка: рассудок
        // юнита (VA 0x4111E8 — цель, строй, работа) зовётся только при
        // НУЛЕВОЙ младшей половине байта приказа, а здесь она 0x0C.
        if (waitingToTalk(unit)) {
          faceEachOther(unit);
          if (!unit.step) setPose(unit, "stand");
        } else if (unit.orderKind && walkToOrder(unit)) {
          // ПРИКАЗ ИГРОКА СИЛЬНЕЕ СОБСТВЕННЫХ ДЕЛ, и это не наш выбор, а
          // устройство движка: рассудок юнита — цель, строй, работа — живёт
          // в VA 0x4111E8, а главный такт зовёт его ТОЛЬКО при нулевой
          // младшей половине байта приказа (VA 0x413894: `if ((+0x16 & 0xF)
          // == 0)`). Есть приказ — юнит его и выполняет.
          //
          // Раньше бой стоял ВЫШЕ приказа, и дерущимся спутником нельзя
          // было ни командовать, ни увести: он всё равно шёл на врага.
        } else if (sees && distance <= actorReach(unit) &&
                   canStrike(unit, target, distance)) {
          unit.path = [];
          unit.goal = null;
          unit.goalTarget = null;
          unit.chaseFail = null;
          if (unit.cooldown <= 0) { attack(unit); active = true; }
          else if (!unit.step) { drawWeapons(unit); setPose(unit, "stand"); }
        } else if (sees) {
          drawWeapons(unit);
          unit.running = false;
          // Идём В САМУ КЛЕТКУ ЦЕЛИ: движок принимает её занятой, потому что
          // на ней стоит именно тот, к кому мы идём (VA 0x441441 сверяет
          // занявшего с полем +0x10). Дойдя вплотную, шагнуть туда не выйдет
          // — и это не тупик, а вход в удар: занятую клетку разбирает
          // VA 0x415090 и переводит юнита в бой.
          //
          // ПРОВАЛ ПОИСКА НЕ ПОВТОРЯЕМ КАЖДЫЙ КАДР. Движок на неудаче снимает
          // приказ (VA 0x416E24) и к той же клетке больше не идёт. Без этой
          // памяти недостижимый враг — например, лучник, которому нельзя
          // стрелять в упор, — заставлял перестраивать маршрут в КАЖДОМ
          // кадре, а один поиск стоит дороже целого кадра.
          const failed = unit.chaseFail;
          const same = failed && failed.row === target.cell.row &&
            failed.col === target.cell.col && failed.fromRow === unit.cell.row &&
            failed.fromCol === unit.cell.col;
          if (!unit.path.length && !same) {
            unit.path = heroPlanPath(unit.cell, target.cell, unit, target) ?? [];
            unit.chaseFail = unit.path.length ? null
              : { row: target.cell.row, col: target.cell.col,
                  fromRow: unit.cell.row, fromCol: unit.cell.col };
          }
          if (unit.path.length) {
            unit.goal = { ...target.cell };
            unit.goalTarget = target;
          } else {
            unit.goal = null;
            unit.goalTarget = null;
          }
        } else if (unit.ally && follows(unit) && !unit.busy) {
          // Бит «за вожаком» — единственное, по чему спутник идёт следом,
          // но САМОСТОЯТЕЛЬНОСТЬ юнита целиком заперта битом «занят
          // приказом» (VA 0x4111E8: вся ветка под `(+0x19 & 0x40) == 0`).
          // Догонять начинает, отойдя на десять клеток (VA 0x41209C).
          const away = cellDistance(unit, hero);
          if (away >= followDistance(true)) {
            // Спутник идёт НЕ в клетку вожака (она занята им самим), а в
            // одну из двенадцати клеток ВОКРУГ него — из таблицы
            // построения 0x461BC4. Отсюда и строй отряда.
            if (!unit.path.length) {
              const spot = formationSpot(unit, hero);
              // Клетка строя выбрана СВОБОДНОЙ, стоять там некому — цели,
              // которой позволено занимать клетку прихода, здесь нет.
              unit.path = spot ? heroPlanPath(unit.cell, spot, unit) ?? [] : [];
              unit.goal = spot && unit.path.length ? { ...spot } : null;
              unit.goalTarget = null;
              // Далеко — бежать (VA 0x4120C6).
              unit.running = away > (followRules()?.run_cells ?? 15);
            }
          } else if (!unit.step) {
            unit.stance = hero.stance === "combat" ? "combat" : "peace";
            unit.path = [];
            unit.goal = null;
            unit.goalTarget = null;
          }
        } else if (!unit.step && !unit.path.length) {
          unit.stance = "peace";
          // Житель занят делом: ждёт свой срок на месте, потом выбирает
          // следующее и идёт туда (VA 0x412C0C).
          //
          // Срок убывает РАЗ В 16 МИРОВЫХ ТАКТОВ, а не каждый кадр браузера:
          // VA 0x413894:72 «if ((_DAT_0084962c & 0xf) == 0) local_3c[0xf5]--».
          // По кадрам счётчик шёл примерно в 50 раз быстрее, и жители
          // метались между рабочими местами.
          if (unit.workRest > 0) {
            unit.workRest = Math.max(0, unit.workRest - рабочаяФаза);
          } else {
            const место = pickWorkplace(unit);
            if (место) {
              if (unit.cell.row === место.row && unit.cell.col === место.col) {
                unit.workRest = место.срок;      // пришёл — работает
              } else {
                unit.path = heroPlanPath(unit.cell,
                  { row: место.row, col: место.col }, unit) ?? [];
                unit.goal = { row: место.row, col: место.col };
                unit.goalTarget = null;       // рабочее место занимать некому
                unit.workRest = место.срок;
              }
            }
          }
          if (!unit.path.length) { unit.goal = null; unit.goalTarget = null; }
        }
      }

      // ОДНО движение на всех: та же функция, что двигает игрока.
      if (unitMove(unit, dt)) active = true;
      if (unit.moving) setPose(unit, unitMovePose(unit));
      else if (!acting && (unit.pose === "walk" || unit.pose === "run")) {
        setPose(unit, "stand");
      }
    }


    // тик кадра — тот же, что у героя: ~18 кадров в секунду
    const frames = actorFrames(data(), unit);
    if (!frames?.length) continue;
    const step = tickSeconds();
    unit.frameTime += dt;
    const advance = Math.floor(unit.frameTime / step);
    if (advance <= 0) continue;
    unit.frameTime -= advance * step;
    const before = unit.frame;
    const next = unit.frame + advance;
    if (next < frames.length) {
      unit.frame = next;
      // Замах поднимает отряд жертвы РАНЬШЕ урона — на втором кадре.
      if (unit.alive && unit.pose.startsWith("attack") && unit.target &&
          swingDeclares(before, next)) {
        warbandSwing(unit, unit.target, units);
      }
      if (unit.alive && strikeLands(unit, before, next) &&
          data().animations.actions?.[unit.pose] && isStrikePose(unit.pose)) {
        world.onUnitStrike?.(unit);
      }
    } else if (unit.step) {
      unit.frame = next % frames.length;
    } else if (unit.pose.startsWith("corpse_")) {
      unit.frame = 0;
    } else if (unit.pose.startsWith("death_")) {
      // У ЧЕЛОВЕКА труп — отдельный блок в один кадр: смерть 3, 11, 12
      // переходит в 13, 14, 15. У ТВАРИ таблица анимаций всего из шести
      // блоков (0…5), блоков трупа в ней нет вовсе — поэтому труп твари
      // это удержанный последний кадр самой смерти.
      if (isBeast(unit)) {
        unit.frame = frames.length - 1;
      } else {
        const variant = unit.pose.slice("death_".length);
        setPose(unit, data().animations.actions?.[`corpse_${variant}`]
          ? `corpse_${variant}` : "corpse_1");
      }
    } else if (data().animations.actions?.[unit.pose]) {
      if (unit.alive && isStrikePose(unit.pose)) world.onUnitStrike?.(unit);
      setPose(unit, "stand");
    } else {
      unit.frame = 0;
    }
    active = true;
  }
  return active;
}

// Круг под выбранным (VA 0x425DB4, строки 41…52). Условий сразу
// несколько: юнит не зверь, его сторона совпадает со стороной игрока и он
// есть в списке выбора. Цвет круга — ЗДОРОВЬЕ: полное даёт зелёный,
// меньше 801 жёлтый, меньше 401 красный. Это не тень: тень рисуется
// другим проходом, а круг бывает только под выбранными.
export function selectionCircle(unit) {
  const sprites = world.map?.interface?.selection_circle;
  if (!sprites) return null;
  if (isBeast(unit)) return null;
  if ((unit.side ?? 0) !== (hero.side ?? 0)) return null;
  return isSelected(unit) ? sprites : null;
}

export function renderUnit(unit) {
  // Круг ложится ДО тела и только под выбранными своими.
  if (selectionCircle(unit)) {
    drawSelectionCircle(unit, Math.round(unit.x), Math.round(unit.y));
  }
  // Клетка с битом 22: движок блитит ЛЮБОГО юнита статичной палитрой
  // (VA 0x425E81), мимо пересчёта под сутки, — не только игрока. Как и
  // герой, такой юнит идёт прямо на кадр, а из слоя сцены вырезается его
  // силуэт. Иначе житель в доме темнел ночью на дневном полу.
  if (layeredFrame && unit.bright) {
    withMainContext(() => drawActor(data(), unit));
    context.save();
    context.globalCompositeOperation = "destination-out";
    drawActor(data(), unit, { silhouette: true });
    context.restore();
    return;
  }
  drawActor(data(), unit);
}

//: Юнит стоит на полу постройки (бит 15 клетки). Движок кладёт таких в
//: отложенный список 0x866F5C и рисует ПОСЛЕ всей сцены полупрозрачной
//: копией (VA 0x428900) — иначе стена закрывает их целиком. У героя это
//: уже сделано, а спутники пропадали в домах.
export function unitOverlay(unit) {
  if (!unit?.cell) return false;
  // Условий ДВА (VA 0x425DC8): клетка юнита несёт бит 15 (пол постройки)
  // И сторона юнита совпадает со стороной игрока. Чужие сквозь крышу не
  // просвечивают — староста деревни своей стороны, а не нашей.
  if ((unit.side ?? 0) !== (hero.side ?? 0)) return false;
  return Boolean(unit.overlay);
}

// Полупрозрачные копии всех юнитов, зашедших в постройку.
// bright: null — все; true/false — только юниты с битом 22 клетки и без.
// Светлые копии при послойном кадре рисуются отдельным проходом мимо
// заливки фильтра — той же статичной палитрой, что и сам юнит (VA 0x425E81).
export function renderUnitsOverlay(alpha = 0.5, bright = null) {
  let drawn = 0;
  for (const unit of units) {
    if (!unitOverlay(unit)) continue;
    if (bright !== null && Boolean(unit.bright) !== bright) continue;
    drawActor(data(), unit, { alpha });
    drawn += 1;
  }
  return drawn;
}

//: Живые враги стоят в своей клетке и мешают пройти — как в движке, где
//: юнит лежит в клетке навигационной сетки, а перед смертью из неё уходит.
// Поиску пути нужен не ответ «занято ли», а сами занятые клетки: он
// раскладывает их по сетке разом, как движок держит юнитов в 0x5662BC, и
// дальше читает клетку одним индексом вместо перебора списка.
//
// Живёт ЗДЕСЬ, а не внутри unitsSetup: там своя `const roster` со списком
// жителей карты, и замыкание ловило её вместо общей функции отряда.
export function eachOccupant(visit) {
  for (const unit of roster(units)) if (unit.alive && unit.cell) visit(unit);
}

export function unitBlocks(row, col, mover = null) {
  // ИГРОК ДЕРЖИТ КЛЕТКУ НАРАВНЕ СО ВСЕМИ. В движке он просто элемент того
  // же массива юнитов, и его номер ложится в младшие 12 бит слова клетки
  // тем же кодом, что у прочих (VA 0x413894 чистит старую клетку и пишет
  // себя в новую), а шагнуть можно лишь туда, где эти биты нулевые.
  // Здесь его в переборе не было вовсе — оттого жители и звери свободно
  // вставали на него, и объёма у героя как будто не было.
  for (const unit of roster(units)) {
    if (unit === mover) continue;          // сам себе дорогу не держит
    if (unit.alive && unit.cell &&
        unit.cell.row === row && unit.cell.col === col) return true;
  }
  return false;
}

// Кадры СВОИХ ТЕЛ для тех тел, что реально есть на карте. Всех тел в паке
// пять по 1365 кадров — тянуть их целиком незачем; берём только записи,

// Поставить отряд рядом с вожаком. Нужна при переходе на другую карту:
// расстановка юнитов идёт РАНЬШЕ, чем герой встаёт на клетку прибытия,
// поэтому без пересборки спутники оставались у прежней клетки — то есть
// в другом конце новой карты.
export function partyRegroup() {
  let moved = 0;
  const mates = units.filter((unit) => unit.ally);
  mates.forEach((unit, index) => {
    const spot = formationSpot(unit, hero) ??
      { row: hero.cell.row, col: hero.cell.col + 1 + index };
    unit.cell = { ...spot };
    unit.home = { ...spot };
    const anchor = heroAnchor(spot.row, spot.col);
    unit.x = anchor.x;
    unit.y = anchor.y;
    unit.path = [];
    unit.step = null;
    moved += 1;
  });
  return moved;
}


