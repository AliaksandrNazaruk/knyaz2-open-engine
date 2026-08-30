// Враги на карте: те же кадры, что у героя, только палитра тела другая и
// приказы отдаёт не игрок, а простой рассудок — заметил, подошёл, ударил.
//
// В движке юниты и герой — одна сущность: общий набор анимаций, слоты
// предметов (рука unit+0x58, вторая рука unit+0x60, метательное unit+0x5A) и
// один список приказов в unit+0x16. Здесь повторяется то, что нужно для боя:
// выбор анимации удара по предмету, смерть жребием из трёх вариантов и уход
// из клетки перед смертью (VA 0x416A52), чтобы труп не работал стеной.
import { world } from "./world.js";
import { clock, clockPhaseHits, tickSeconds } from "./clock.js";

// СКОЛЬКО ПОИСКОВ ПУТИ ПОЗВОЛЕНО ЗА ОДИН МИРОВОЙ ТАКТ.
//
// Замер на карте 23 (сетка 7556 клеток): один поиск — 2.4…3.4 мс. Движок
// правит курс каждому преследователю каждый такт, но его волна была на
// порядок дешевле и считалась на машине игрока. У нас же сорок врагов дали
// бы 512 поисков в секунду — полторы секунды счёта на секунду игры, да ещё
// и на общем сервере, а не у каждого дома.
//
// Двойка держит цену около 77 мс на секунду игры (порядка восьми процентов
// ядра) и оставляет погоню сходящейся: при ходьбе цель успевает уйти на
// клетку-другую, а не на пол-карты. Число вынесено сюда, чтобы его можно
// было подкрутить под нагрузку сервера, не трогая логику.
const REPLAN_PER_TICK = 2;
let replanBudget = 0;
import { grantExperience } from "./progress.js";
import { isNight } from "./daylight.js";
import { actorAttackPose, actorBody, actorFrames, actorItem, actorReach,
         drawActor, isBeast, sheetsFor, unitSortKey } from "./actor.js";
import { context, layeredFrame, withMainContext } from "./viewport.js";
import { drawSelectionCircle, hero, heroAnchor, heroCellKey,
         heroDirectionToCell, heroNeighbor,
         heroPlanPath, heroFree, roster, unitMove, unitMovePose,
         unitUpdateBuilding } from "./hero.js";
import { withPerspective } from "./perspective.js";
import { KEEP_RANGE, adjacentEnemy, enemyFor, membersOf, warbandOf,
         warbandSwing, warbandsSetup, warbandsTick } from "./warband.js";
import { weaponModeRefresh } from "./inventory.js";
import { mapStateDead, mapStateJoined, mapStateResidents } from "./mapstate.js";
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
//: ПАУЗЫ МЕЖДУ УДАРАМИ КАК ОТДЕЛЬНОЙ ВЕЛИЧИНЫ В ДВИЖКЕ НЕТ. Темп боя задаёт
//: сам блок замаха: 12 кадров по одному за такт плюс обратный отсчёт +0xFD
//: на нулевом кадре — см. attackWait. Стоявшая здесь ATTACK_COOLDOWN = 1.1
//: была нашей выдумкой без адреса и считала темп ВТОРОЙ раз.

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

// СОСЕД — ЭТО НЕ «РАССТОЯНИЕ ЕДИНИЦА».
//
// Сетка изометрическая, строки идут вполовину, и сосед с севера отличается
// на ДВЕ строки: `heroNeighbor(9,27, 2)` даёт (7,27). Мерка движка
// (VA 0x43B670, наш `cellRange`) для этой пары честно возвращает двойку —
// она меряет клетки, а не соседство.
//
// Ближний бой на ней ломался молча: юнит, вставший строго севернее или южнее
// цели, получал «две клетки» и удара не начинал, а шагнуть в занятую клетку
// не мог — и замирал навсегда. Стоящие слева-справа дрались нормально,
// поэтому со стороны это выглядело как «некоторые враги застыли».
//
// Движок так не считает вовсе: ближнюю цель он берёт ПЕРЕБОРОМ ВОСЬМИ
// НАПРАВЛЕНИЙ (VA 0x4107EC зовёт 0x441344 для каждого), а дальность в
// клетках у него нужна только стрельбе (VA 0x414AF8).
export function adjacentCell(one, other) {
  if (!one?.cell || !other?.cell) return false;
  for (let direction = 0; direction < 8; direction += 1) {
    const next = heroNeighbor(one.cell.row, one.cell.col, direction);
    if (next.row === other.cell.row && next.col === other.cell.col) return true;
  }
  return false;
}

//: Достал ли юнит до цели: рукой — по соседству, метательным — по дальности.
export function withinReach(unit, target, distance, reach) {
  return reach <= 1 ? adjacentCell(unit, target) : distance <= reach;
}

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
import { followDistance, follows, isSelected, orderClear,
         orderKinds, orderUnit } from "./orders.js";

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
    // РОДНАЯ КАРТА — вторая половина идентичности. В движке слот уникален
    // глобально (один массив юнитов на игру), а в паке слоты РАЗНЫХ карт
    // пересекаются: донорские карты несут номера своего мира (unit_337 на
    // 18 — Белун, на 186 — чужой житель). Без пары (карта, слот) запись
    // отряда прятала пачного юнита ЛЮБОЙ карты с тем же слотом — «Ярл
    // превращается в Белуна», клоны и невозвращаемые спутники.
    home: unit.homeMap ?? null,
    face: unit.face ?? 0, body: unit.body ?? 0, palette: unit.palette ?? 0,
    // Чья игра — часть облика: кадры и портреты двух игр под разными
    // ключами (см. bodyKey и portraitPath).
    game: unit.game ?? null,
    breed: unit.breed ?? 0, side: unit.side ?? 0,
    level: unit.level ?? 1,
    health: unit.health, armour: unit.stats?.armour,
    accuracy: unit.stats?.accuracy,
    order: unit.orderByte ?? ORDER_FOLLOW,
    // Тумблеры окна персонажа — биты +0x19 (0x20 выбор оружия, 0x10
    // защита вожака, 0x01/0x02 лечебные смеси); едут с бойцом.
    weapon_lock: Boolean(unit.weaponLock),
    defend_leader: Boolean(unit.defendLeader),
    heal_trigger: unit.healTrigger ?? 0,
    dialog: unit.dialogNumber ?? unit.dialog?.number ?? null,
    // ДЕРЕВО РАЗГОВОРА ПЕРЕЕЗЖАЕТ ВМЕСТЕ С НИМ. Номера мало: на новой карте
    // спутник пересоздаётся из этой записи, а его дерево лежало у юнита той
    // карты, где его наняли, и там же оставалось. Наёмник терял способность
    // говорить на первом же переходе — а значит и назначить его на должность
    // в деревне было нельзя, назначение идёт через разговор (действие 74).
    // У стартовой пары дерево кладёт сборщик, у нанятых — этот перенос.
    dialog_tree: unit.dialog ?? null,
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

// ЧТО НАЖИЛ СПУТНИК — ОБРАТНО В ЗАПИСЬ ОТРЯДА, при уходе с карты.
//
// В движке помнить нечего: запись бойца лежит в отряде игрока (0x71E56C),
// живёт весь сеанс, и свёртка карты (0x43A628) удаляет из общего массива
// ТОЛЬКО мёртвых. У нас спутник пересоздаётся из `party.members` при каждом
// входе — значит эта запись и есть наша долгая память, — а писалась она
// РОВНО ОДИН РАЗ, при найме (`partyHire`). Отсюда и «здоровье
// восстанавливается в путешествии»: поход всегда кончается входом в
// локацию, а вход возвращал спутнику здоровье, опыт и мешок того дня, когда
// он к нам присоединился.
//
// ПАВШИЙ ВЫЧЁРКИВАЕТСЯ ИЗ ОТРЯДА НАВСЕГДА — обе ветки свёртки 0x43A628
// вырезают мёртвого из массива юнитов при КАЖДОМ уходе с карты (счёт
// отряда −1, хвост сдвигается на 0x100 вниз, :80-84 и :156-169), и у
// отряда игрока это делается безусловно, даже с именными. Второго массива,
// откуда его можно поднять, в движке нет. Здесь стояло «павшего не
// трогаем» — и старая запись поднимала его на следующей карте живым и с
// полным здоровьем дня найма. Добро павшего сыплется кучей в его клетку
// раньше, в mapTeardown (там же, где у движка, — :39-66).
export function partyCapture() {
  const party = hero.party ?? hero.data?.template?.party ?? null;
  const members = party?.members;
  if (!members?.length) return false;
  let saved = 0;
  const kept = [];
  for (const member of members) {
    const live = units.find((unit) => unit.ally && unit.slot === member.index);
    if (live && live.alive === false) continue;     // павший — вычеркнут
    if (live) {
      kept.push(memberFromUnit(live));
      saved += 1;
    } else {
      // Первый в списке — сам герой, его живой юнит не в units; записи
      // без живого двойника (глава отряда, чужая карта) едут как есть.
      kept.push(member);
    }
  }
  party.members = kept;
  return saved > 0;
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

// Вычеркнуть из отряда. Обратное partyHire: в движке запись должностного
// КОПИРУЕТСЯ в отряд деревни (FUN_004338B0), и в отряде игрока ей больше не
// место — потому назначенный и «остаётся здесь», как обещает реплика.
export function partyRelease(unit) {
  const party = hero.party ?? hero.data?.template?.party ?? null;
  if (!party || !unit) return false;
  const before = (party.members ?? []).length;
  party.members = (party.members ?? []).filter((member) => member.index !== unit.slot);
  return party.members.length !== before;
}

function spawnCompanion(member, map, index) {
  const hand = actorItem(member.equipment?.hand, map.items);
  const anchor = heroAnchor(hero.cell.row, hero.cell.col + 1 + index);
  return {
    id: `mate_${member.index}`,
    // Номер слота юнита: по нему движок держит список выбора в порядке
    // адресов записей (VA 0x423F80), они лежат подряд через 0x100.
    slot: member.index ?? 0,
    // родная карта — половина идентичности юнита (см. memberFromUnit)
    homeMap: member.home ?? null,
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
    // Спутник донорского героя приезжает из ЕГО игры — и рисуется её кадрами.
    game: member.game ?? hero.game ?? null,
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
    // тумблеры окна персонажа (биты +0x19) — из записи бойца
    weaponLock: Boolean(member.weapon_lock),
    defendLeader: Boolean(member.defend_leader),
    healTrigger: member.heal_trigger ?? 0,
    // ДЕРЕВО РАЗГОВОРА У СПУТНИКА ТОЖЕ ЕСТЬ. Здесь стоял `null`, и со своими
    // спутниками нельзя было заговорить вовсе — а через разговор их и
    // назначают на должность в деревне (действие 74). Номер диалога у них
    // свой (+0xF2): 118 у Путяты, 144 у Тура, и на картах эти номера не
    // встречаются, так что дерево приходит из отряда, а не с карты.
    dialog: member.dialog_tree ?? null,
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
    // Сеется БАЗА: прибавки надетого досчитывает currentCharacteristics
    // на лету, иначе чары считались бы дважды (см. progressSetup).
    characteristics: characteristicList(member.characteristics ?? member.current),
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
    speed: 2,
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
  // КЛЮЧ — ПАРА «РОДНАЯ КАРТА : СЛОТ». Слот уникален только в пределах
  // одной игры (глобальный массив GAME.x), а донорские карты несут номера
  // СВОЕГО мира — по паку 543 из 917 слотов мира 0 живут на двух и более
  // картах. Пока сверка шла голым слотом, боец отряда прятал пачного
  // юнита ЛЮБОЙ карты с тем же номером: на его месте вставал спутник —
  // «Ярл превращается в Белуна». Запись без родной карты (старый сейв)
  // прячет по-старому, на любой карте.
  const mapNumber = Number(map?.legacy?.map_number);
  const inParty = new Set((party?.members ?? [])
    .map((member) => `${member.home ?? mapNumber}:${member.index}`));
  // УБИТЫЕ ОСТАЮТСЯ УБИТЫМИ. В движке отдельной памяти не нужно: запись
  // юнита с поднятым битом 0x80 (unit+0x1A) продолжает лежать в отряде и
  // уезжает в сохранение вместе с ним. Здесь юниты карты пересоздаются из
  // пака при каждом входе, поэтому зачищенная карта оживала целиком.
  const fallen = mapStateDead(map.legacy?.map_number);
  // ПРИЁМЫШИ КАРТЫ — те, кого пак на ней не знает, и правки тем, кого знает.
  // Память сильнее пака: пачную запись поднимаем как обычно, а поля правим
  // по запомненному; кого в паке нет вовсе — поднимаем из его собственной
  // записи отряда. Подробности и канон — в mapstate.js.
  const joined = mapStateJoined(map.legacy?.map_number);
  // СНИМКИ ЖИТЕЛЕЙ (mapstate): вся изменяемая часть записи — движок держит
  // её в глобальном массиве и не перечитывает. `removed` — ушёл с карты
  // (действия 44/46/70), такой не поднимается; мёртвый — как и раньше.
  const kept = mapStateResidents(map.legacy?.map_number);
  for (const entry of roster) {
    const slot = Number(String(entry.id ?? "").replace(/\D+/g, ""));
    if (inParty.has(`${mapNumber}:${slot}`)) continue;
    const snap = kept.get(slot);
    if (snap && (snap.removed || snap.alive === false)) continue;
    if (!snap && fallen.has(slot)) continue;
    unitSpawn(entry, map);
    if (snap) applyResident(units[units.length - 1], snap);
    const remembered = joined.get(slot);
    if (remembered) {
      applyJoined(units[units.length - 1], remembered);
      joined.delete(slot);
    }
  }
  // Остались те, кого в пачном наборе карты нет: бывшие спутники.
  let extra = 0;
  for (const remembered of joined.values()) {
    if (!remembered.member || fallen.has(remembered.slot)) continue;
    // СНОВА НАНЯТЫЙ уже приехал бойцом отряда (обработчик 36 снимает
    // запись, но старые сейвы её ещё несут): поднять его и из памяти —
    // выпустить клона, «два Белуна». Ключ тот же, что у пачного набора:
    // пара «родная карта : слот».
    if (inParty.has(`${remembered.member.home ?? mapNumber}:${remembered.slot}`)) {
      continue;
    }
    const unit = spawnCompanion(remembered.member, map, extra);
    extra += 1;
    applyJoined(unit, remembered);
    units.push(unit);
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

// НАЛОЖИТЬ СНИМОК ЖИТЕЛЯ (mapstate.packResident): изменяемая часть записи
// поверх пачной. В движке этого шага нет — запись юнита глобальна и
// никогда не перечитывается из данных карты.
function applyResident(unit, snap) {
  if (!unit || !snap) return unit;
  if (snap.cell) {
    unit.cell = { ...snap.cell };
    unit.home = { ...snap.cell };
    const anchor = heroAnchor(snap.cell.row, snap.cell.col);
    unit.x = anchor.x;
    unit.y = anchor.y;
  }
  unit.direction = snap.direction ?? unit.direction;
  unit.side = snap.side ?? unit.side;
  if (snap.health != null) unit.health = snap.health;
  unit.poison = snap.poison ?? 0;
  unit.flags = snap.flags ?? 0;
  unit.talkStamp = snap.talkStamp ?? null;
  unit.money = snap.money ?? 0;
  unit.bag = [...(snap.bag ?? [])];
  unit.counter = [...(snap.counter ?? [])];
  unit.equipment = { ...(snap.equipment ?? {}) };
  unit.enchant = { ...(snap.enchant ?? {}) };
  unit.bagStrength = { ...(snap.bagStrength ?? {}) };
  unit.bagCount = { ...(snap.bagCount ?? {}) };
  unit.bagEnchant = { ...(snap.bagEnchant ?? {}) };
  unit.bagPoison = { ...(snap.bagPoison ?? {}) };
  unit.wear = { ...(snap.wear ?? {}) };
  unit.ammoCount = snap.ammoCount ?? null;
  unit.rangedMode = Boolean(snap.rangedMode);
  unit.body = snap.body ?? unit.body;
  if (snap.face != null) unit.face = snap.face;
  unit.palette = snap.palette ?? unit.palette;
  unit.level = snap.level ?? unit.level;
  unit.experience = snap.experience ?? 0;
  unit.freeExperience = snap.freeExperience ?? 0;
  unit.nextLevel = snap.nextLevel ?? 0;
  if (snap.skills) unit.skills = [...snap.skills];
  if (snap.characteristics) unit.characteristics = [...snap.characteristics];
  if (snap.baseCharacteristics) {
    unit.baseCharacteristics = [...snap.baseCharacteristics];
  }
  unit.weaponLock = Boolean(snap.weaponLock);
  unit.defendLeader = Boolean(snap.defendLeader);
  unit.healTrigger = snap.healTrigger ?? 0;
  return unit;
}

// Наложить на поднятого юнита то, чем он отличается от исходного. Полей
// ровно столько, сколько меняет обработчик 43 (VA 0x4338B0): сторона, место
// в отряде игрока, клетка и байт приказа.
function applyJoined(unit, remembered) {
  if (!unit || !remembered) return unit;
  if (remembered.side != null) unit.side = remembered.side;
  unit.ally = Boolean(remembered.ally);
  unit.orderByte = remembered.orderByte ?? 0;
  unit.orderKind = (remembered.orderByte ?? 0) & 0x0F;
  if (remembered.cell) {
    unit.cell = { ...remembered.cell };
    unit.home = { ...remembered.cell };
    const anchor = heroAnchor(remembered.cell.row, remembered.cell.col);
    unit.x = anchor.x;
    unit.y = anchor.y;
  }
  return unit;
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
      // РОДНАЯ КАРТА — вторая половина идентичности: слоты разных карт
      // пересекаются (донор), и все глобальные склады ключуются парой.
      homeMap: Number(map?.legacy?.map_number ?? NaN) || null,
      name: entry.name,
      x: position.x,
      y: position.y,
      cell: { ...cell },
      home: { ...cell },
      // ПОВОРОТ ИЗ РАССТАНОВКИ (+0x18 записи юнита, konung2/gamefile.py).
      // Здесь стояла голая шестёрка, и вся деревня встречала игрока лицом
      // вниз: направление менялось только у того, кто пошёл или заговорил.
      // Шестёрка осталась запасной — для юнитов, заведённых не расстановкой.
      direction: entry.direction ?? 6,
      stance: "peace",
      // ПОЗА РАССТАНОВКИ (+0x17). Скелеты, ичетики и кикиморы лежат в позе 4
      // и доигрывают свою анимацию, прежде чем начать действовать: разбор
      // занятия (0x410010) начинается с проверки «поза 4 и кадр 0».
      //
      // ЗАКАПЫВАЮТСЯ ТОЛЬКО ЗАКАПЫВАЮЩИЕСЯ. Здесь стояло «поза 4 — значит
      // из земли» без разбора породы, и под правило попал живой человек.
      // Замер по всему паку: в каноне позу 4 несут РОВНО три породы —
      // ичетик (5 юнитов), скелет (71) и кикимора (16); у донора те же три
      // и ещё одна, ровно один юнит на всю игру — Позвизд, порода 90, в
      // Дубках у пещеры. Он висел в позе подъёма и не двигался, пока на
      // него не нападут; тестер записал его как «чародей забаговался».
      //
      // Что он не тварь, говорит он сам: разговор 29, тринадцать узлов,
      // «Ты ответишь за это оскорбление — я человек, а не зверь!».
      pose: entry.pose === CREATURE_RISE_POSE && BURROWING.has((entry.breed ?? 0) & 0x7F)
        ? "rise" : "stand",
      breedCounter: entry.breed_counter ?? 0,
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
      // ШЕСТЬ ХАРАКТЕРИСТИК ЕСТЬ У КАЖДОГО ЮНИТА, а не только у отряда игрока:
      // в записи это байты +0xC0 (свои) и +0xCC (с прибавками вещей). Учёба у
      // воеводы поднимает их ЖИТЕЛЮ — 0x4181E8 после каждого повышения зовёт
      // 0x4131FC(житель, 5/4/1) и сам прибавляет единицу к +0xC5, +0xC4, +0xC1,
      // а затем пересчитывает текущие через 0x41C494. Пока порт вёз эти два
      // списка только герою и спутникам, первое же занятие в казарме падало на
      // `characteristics[5]` жителя и обрывало ВЕСЬ тик игры.
      // Сев БАЗЫ (+0xC0): текущие (+0xCC) — это база плюс чары надетого,
      // и их порт считает на лету (currentCharacteristics); сев current
      // удваивал бы прибавки зачарованных вещей записи.
      characteristics: characteristicList(entry.characteristics ?? entry.current),
      baseCharacteristics: characteristicList(entry.characteristics),
      face: entry.face ?? null,
      level: entry.level ?? 1,
      //: ЗЛОЙ ИЛИ ДОБРЫЙ — РЕШАЕТ ОТРЯД, А НЕ ЮНИТ. Поле бралось как
      //: «враждебен, если пак прямо не сказал обратного», а пак его
      //: жителям не пишет вовсе — и мирный житель, поставленный
      //: редактором в мирный отряд, числился врагом. Бой это не решало
      //: (цель выбирает отряд, warband.js), но всё, что читает флаг —
      //: снимок для агента, правила разговора, — врало. Берём
      //: враждебность ОТРЯДА: бит 0x01 его байта +0x1F (on_player).
      hostile: entry.hostile ?? Boolean(
        (map?.warbands ?? []).find(
          (band) => Number(band.side) === Number(entry.side ?? 0))?.on_player),
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
      // ЧЬЯ ИГРА. Пак ставит это поле каждому жителю донорской карты, а
      // клиент его терял — и в Тиграте 52 юнита из 57 искали набор кадров
      // `6:162` вместо `legend:6:162` и оставались чёрными.
      game: entry.game ?? null,
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
      // Скорость записи (+0x1D). Формулу из характеристик движок считает
      // ТОЛЬКО отряду игрока (0x41C944:305); NPC живут с этим полем, и в
      // стартовых мирах оно ноль у всех — потому и умолчание ноль.
      speed: entry.speed ?? 0,
      //: Поля `sight` здесь больше нет: радиуса обзора в движке не существует,
      //: см. комментарий у `sees` в unitsTick. Из сборщика пака `sight_cells`
      //: убран тем же заходом.
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

//: ПОЗУ МОЖНО ПОСТАВИТЬ ЗАНОВО ПОВЕРХ СЕБЯ. 0x416740 не спрашивает, чем юнит
//: занят и что на нём сейчас: он сбрасывает подшаг (`param_1[0xfb] = '\0'`),
//: заводит блок с начала и играет звук набора. Нужно это сбиву: повторный
//: удар в уже сбитого начинает его реакцию сначала. Замер оригинала —
//: кадр 7→0, 5→0, 3→0, 2→0, и подшаг вместе с ним.
function setPose(unit, pose, force = false) {
  if (unit.pose === pose && !force) return;
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
//: Бит дневного места и порог боевых видов (konung2/gamefile.py, 0x412C0C).
const WORKPLACE_NIGHT_BIT = 0x10;
const WORKPLACE_COMBAT_FROM = 0x70;

// ТАБЛИЦА МЕСТ — У КАЖДОГО ОТРЯДА СВОЯ. Числа в записи жителя это номера
// слотов ЕГО отряда, а не общей деревенской таблицы. На Морском лагере
// отрядов три, и знахарь с купцом, старостой и кузнецом (слоты 0…2 деревни)
// уходили работать на клетки Хрофта, Хрорара и Эгиля — то есть кучковались
// у Хрофта. Деревенская таблица остаётся запасной: для тех, чей отряд
// не назван, и для паков, собранных до этой правки.
function workplaceTable(unit = null) {
  const own = unit?.party != null
    ? world.map?.workplaces_by_party?.[String(unit.party)]
    : null;
  return own ?? world.map?.village?.workplaces ?? null;
}

// «СТОЙ, С ТОБОЙ ГОВОРЯТ» ОТПУСКАЕТ (VA 0x413894, случай 0x0C).
//
// Приказ 0x0C держится РОВНО ПОКА идёт разговор:
//
//     если экран разговора открыт с ним ИЛИ игрок идёт к нему с приказом
//     «заговорить» (младшая половина 2, цель — он) -> повернуться к игроку;
//     иначе -> FUN_00416E24: цель в ноль, занятие снимается маской 0xB0.
//
// У нас счётчик `waitTalk` ставился и НЕ УБИРАЛСЯ НИКЕМ: собеседник навсегда
// оставался с занятием 0x0C — не работал, не ходил, а разговор с ним считался
// идущим. Отсюда и «спутник стоит как вкопанный», и «после разговора не
// поговорить со старостой».
//
// САМ СЧЁТЧИК УБРАН 20.08: его ставили из правил пака и обнуляли здесь, а
// уменьшать и спрашивать было некому — решает всё байт приказа. Никакого
// отсчёта в движке и нет: удержание чисто условное, одно из двух, как
// написано выше. Нашло средство tools/write_only_fields.js.
function waitTalkTick(unit) {
  const kinds = orderKinds();
  const wait = kinds.wait_talk ?? 0x0C;
  if (((unit.orderByte ?? 0) & 0x0F) !== wait) return false;
  const talkKind = kinds.talk ?? 2;
  const held = world.talking?.unit === unit ||
    (((hero.orderByte ?? 0) & 0x0F) === talkKind && hero.orderTarget === unit);
  if (held) {
    // Повернуться лицом к игроку, пока он подходит или говорит.
    const facing = unit.cell && hero.cell
      ? heroDirectionToCell(unit.cell, hero) : null;
    if (facing != null) unit.direction = (facing + 4) & 7;
    return true;
  }
  orderClear(unit);
  return false;
}

// ОТПРАВИТЬ ЮНИТА НА КЛЕТКУ С ЗАНЯТИЕМ (VA 0x416574).
//
// Движок пишет цель в +0x13/+0x15, ставит младшую половину приказа и зовёт
// поиск пути. Здесь то же: цель, занятие, маршрут — и юнит идёт сам обычным
// тактом.
export function unitSendTo(unit, row, col, order) {
  if (!unit || unit.alive === false) return false;
  unit.home = { row, col };
  unit.orderByte = ((unit.orderByte ?? 0) & 0xF0) | (order & 0x0F);
  if (unit.cell?.row === row && unit.cell?.col === col) {
    unit.path = [];
    unit.goal = null;
    return true;
  }
  unit.path = heroPlanPath(unit.cell, { row, col }, unit) ?? [];
  unit.goal = unit.path.length ? { row, col } : null;
  unit.goalTarget = null;
  return unit.path.length > 0;
}

//: РАЗОВЫЕ ПОЗЫ, КОТОРЫХ НЕТ В ТАБЛИЦЕ ДЕЙСТВИЙ. `actions` описывает кадры
//: HEROES.RES, а эти приходят из набора твари: подъём из земли и каст своего
//: героя. Доигравшая поза, не попавшая в разбор действий, сваливается в
//: запасной ход `frame = 0` и начинается заново — так тварь бесконечно лезла
//: из земли, а волшебница бесконечно кастовала.
const SET_ACTIONS = new Set(["rise", "cast"]);

//: Блок анимации, в котором лежат «встающие» твари (выпечка: CREATURE_POSES).
const CREATURE_RISE_POSE = 4;
//: Кто вылезает из земли: ичетик, скелет, кикимора. Список снят замером по
//: всем картам обеих игр, а не выписан из головы (см. unitSpawn).
const BURROWING = new Set([0x46, 0x4C, 0x53]);
//: Порода Скелета — единственная, кто встаёт после смерти (0x413894:275).
const BREED_SKELETON = 0x4C;
//: Пауки: обычный и ядовитый. Ходят дёргано — см. beastPauses.
const BREED_SPIDERS = new Set([0x4D, 0x4F]);

// ДЁРГАНАЯ ПОХОДКА ПАУКОВ (VA 0x413894:180). В ветке ходьбы у пород 0x4D и
// 0x4F движок держит паузу в том же байте +0xEE:
//
//     счётчик пуст -> назначить паузу:
//         сколько = кадров < 2 ? 0 : rand() % кадров
//         счётчик = (rand() % 2) * сколько + 1     // половину раз просто 1
//         кадр придержать
//     счётчик не пуст -> кадр придержать, счётчик -= 1,
//         и пока он не дошёл до нуля — ШАГА НЕТ ВОВСЕ
//
// Отсюда и повадка: паук то замирает, то перебегает. Возвращаем «пауза
// идёт», и шаг не начинается.
function beastPauses(unit) {
  if (!BREED_SPIDERS.has((unit?.breed ?? 0) & 0x7F)) return false;
  if ((unit.breedCounter ?? 0) > 0) {
    unit.breedCounter -= 1;
    return unit.breedCounter > 0;
  }
  //: Длину берём ПРЯМО ИЗ НАБОРА, а не через actorFrames: та отдаёт кадр
  //: по стойке живого юнита и на только что расставленной твари молчит.
  const sets = world.map?.creatures?.sets?.[String(unit.body)]
    ?.[String(unit.palette ?? 0)];
  const frames = sets?.walk?.[unit.direction ?? 0]?.length ?? 0;
  const span = frames < 2 ? 0 : Math.floor(Math.random() * frames);
  unit.breedCounter = Math.floor(Math.random() * 2) * span + 1;
  return false;
}
//: Правило зовут из шага (hero.js), а тот нас импортировать не может —
//: units.js уже тянет его. Отдаём через мир, как unitSpeed и unitCanRun.
world.beastPauses = beastPauses;

const SPARRING_ORDER = 9;      // места 0x90/0xA0 — бьются в паре
const DRILL_ORDER = 10;        // места 0x70/0x80 — машут в одиночку
const SPARRING_PHASE = 0x3FF;
//: Взгляд лежит в МЛАДШЕЙ половине вида места (0x413894:66). Отдельного
//: поля направления у места нет вовсе: `kind` несёт занятие старшей
//: половиной, а сторону, куда встать, — младшей.
const WORKPLACE_FACING = 0x0F;
//: Приказ «идти на место» — движковый param_4 функции 0x416574: боевому
//: месту 4, обычному 0xB. Своего смысла у чисел нет, важно лишь, что
//: девятка на время дороги СНИМАЕТСЯ, — иначе боец машет по пути.
const WALK_TO_COMBAT_ORDER = 4;
const WALK_TO_WORK_ORDER = 0x0B;

// ТРЕНИРОВКА — НЕ БОЙ, И УДАРА В НЕЙ НЕТ ВОВСЕ.
//
// В движке удар висит на боевом приказе с целью в +0x10, а тренировка
// цель обнуляет (0x413894:84) — бьют воздух. У нас удар висит на КАДРЕ
// анимации, и одного обнуления цели мало: `onUnitStrike` подставляет
// героя запасным ходом любому чужому юниту, ПРИЧЁМ БЕЗ ПРОВЕРКИ
// РАССТОЯНИЯ, — так что замах в казарме бьёт игрока через всю карту.
//
// МЕТИТЬ НАДО ЗАМАХ, А НЕ ПРИКАЗ. Здесь стояла проверка приказа 9/10, и
// она пропускала половину случаев: спаррингующий ставит замах и НАПАРНИКУ
// (так в движке — 0x413894:113), а у того приказ свой, хоть нулевой. Такой
// сосед под гейт не попадал и честно лупил героя: «Ослябя -> герой: урон
// 150» при 1600 здоровья. Поэтому флаг живёт на самом юните и снимается
// первым же настоящим ударом — `attack` зовёт `swing` без него.
function unitTraining(unit) {
  return unit?.trainingSwing === true;
}

//: Занят ли юнит тренировкой — по приказу, а не по позе.
function unitSparring(unit) {
  const kind = (unit?.orderByte ?? 0) & 0x0F;
  return kind === SPARRING_ORDER || kind === DRILL_ORDER;
}
//: Ходячие позы. В движке это таблица 0x45FE90 — такты на клетку, и
//: положительные значения там ровно у четырёх записей: walk и run в обеих
//: стойках (11, 5, 10, 4). Ею же он проверяет, не идёт ли напарник.
const POSE_WALKS = new Set(["walk", "run"]);

// ЗАМАХ (VA 0x416B50) — общий для боя и для тренировки.
//
// Движок ставит боевую стойку (бит 4 байта +0x19), сбрасывает «бьётся
// метательным» и выбирает блок по оружию и щиту: двуручное — 8, нулевой
// навык боя двумя руками или щит во второй руке — 5, иначе 9. Последней
// строкой кладёт походку удара (+0xFD). Ровно это же делал `attack`, и
// держать две копии было бы враньём: удар в бою и удар по воздуху в
// казарме — одно движение, разная причина.
function swing(unit, { melee = false, training = false, pace = null } = {}) {
  // ТРЕТЬЯ КОМАНДА ЗАМАХА (0x416B50): `+0xEE = 0` — «бьётся не
  // метательным», безусловно. Без неё лучник в казарме «тренировался
  // луком» со звуком выстрела: слой оружия и звук замаха выбирались по
  // режиму стрельбы, а тренировка — всегда ближний бой. Обратно режим
  // возвращает задумывание боя (наш перенос 0x412FF4 в боевой ветке).
  if (melee) unit.rangedMode = false;
  drawWeapons(unit);
  const поза = actorAttackPose(data(), unit, { melee });
  const сменилась = unit.pose !== поза;
  setPose(unit, поза);
  //: ПОХОДКУ УДАРА (+0xFD) КЛАДЁТ ВЫЗЫВАЮЩИЙ. `0x416B50` ставит её сама,
  //: но обе ветки тренировки тут же ПЕРЕЗАПИСЫВАЮТ — и по-разному:
  //:
  //:     приказ 9, себе       0x413B4C   +0xFD = 0
  //:     приказ 9, напарнику  0x413CBC   +0xFD = кадры / 2
  //:     приказ 10            0x413C71   +0xFD = rand() % (кадры / 2)
  //:
  //: Снято дизассемблером, не декомпилятом: у Ghidra эти три строки
  //: сливаются в одну ветку.
  //: ТОЛЬКО НА НОВЫЙ ЗАМАХ. Тренировка зовёт замах каждые шестнадцать
  //: тактов, и переустановка счётчика на прежней позе не давала кадру
  //: сдвинуться: он топтался на нуле, счётчик тикал 3-2-1, приходил
  //: новый замах — и снова 3-2-1. В движке `+0xFD` кладётся при СМЕНЕ
  //: блока (0x416740 заводит его с начала), а не каждый вызов.
  if (сменилась) {
    unit.attackWait = pace !== null ? pace
      : (isShootingPose(unit.pose) ? 0 : attackWait(unit));
  }
  //: Пометка снимается сама: настоящий удар идёт этим же путём и кладёт
  //: сюда ложь, поэтому «застрять безоружным» юнит не может.
  unit.trainingSwing = training;
}

//: Половина кадров нынешней анимации — из неё обе ветки берут походку.
function swingHalf(unit) {
  const набор = actorFrames(data(), unit, unit.pose, unit.direction ?? 0);
  return Math.trunc((Array.isArray(набор) ? набор.length : 0) / 2);
}

// ТРЕНИРОВКА У КАЗАРМЫ (VA 0x413894, приказы 9 и 10).
//
// Полный разбор — docs/VILLAGE_TRAINING_SPEC.md; здесь только то, что
// нужно, чтобы читать этот код:
//
//   * поворот по взгляду места (младшая половина вида места);
//   * приказ 9 — пара через клетку, приказ 10 — удары в одиночку;
//   * цель обнуляется (+0x10), потому удар и уходит в воздух;
//   * опыт даётся ТОЛЬКО напарнику стороны игрока, раз в 0x3FF тактов;
//     в ветке приказа 10 начисления нет вовсе (проверено по всем вызовам
//     0x413110: в девятке один, в десятке ни одного).
function sparringTick(unit) {
  const kind = (unit.orderByte ?? 0) & 0x0F;
  if (kind !== SPARRING_ORDER && kind !== DRILL_ORDER) return false;
  if (!unit.cell) return false;
  const place = (workplaceTable(unit) ?? []).find(
    (row) => row.slot === (unit.workplaces ?? [])[0]);
  const facing = (place?.kind ?? 0) & WORKPLACE_FACING;
  if (facing < 8) unit.direction = facing;
  unit.target = null;
  //: Замах СЕБЕ — только из стойки (0x413894:88). Иначе анимация удара
  //: сбрасывалась бы в первый кадр каждые шестнадцать тактов и не
  //: доигрывала никогда: боец дёргался бы, а не бил.
  const свой = unit.pose === "stand";
  if (kind === DRILL_ORDER) {
    //: БЕЗ ПРОВЕРКИ ПОЗЫ. У девятки движок спрашивает, стоит ли боец
    //: (0x413B2x), а у десятки — нет: `cmp [ebp-8], 0xa` и сразу
    //: `call 0x416B50` (0x413C56). Здесь стояло моё «только из стойки»,
    //: и одиночки у бочек махали втрое реже, чем должны.
    const прежняя = unit.pose;
    swing(unit, { melee: true, training: true });
    if (unit.pose !== прежняя) {
      const половина = swingHalf(unit);
      unit.attackWait = половина < 2 ? 0
        : Math.floor(Math.random() * половина);
    }
    return true;
  }
  // Два шага в свою сторону — там стоит напарник.
  //
  // НАПАРНИКОМ МОЖЕТ БЫТЬ КТО УГОДНО, И ГЕРОЙ ТОЖЕ. Движок берёт юнита из
  // клетки по общей карте `DAT_005662BC` (0x413894:82), где лежат все без
  // разбора; своей записи у игрока там нет. Приказ 9 ставит ТОЛЬКО жизнь
  // деревни (0x412C0C — единственное место во всём exe, где пишется
  // девятка), значит зачинщик всегда житель, а игрок и его спутник
  // попадают в спарринг второй стороной — им ставят замах и им же капает
  // опыт. Оттого движок и сверяет сторону напарника с игроковой.
  //
  // У нас герой живёт ОТДЕЛЬНО от массива `units`, и поиск его не видел:
  // игрок вставал на вторую клетку казармы — и просто стоял.
  let spot = heroNeighbor(unit.cell.row, unit.cell.col, unit.direction ?? 0);
  spot = heroNeighbor(spot.row, spot.col, unit.direction ?? 0);
  const наКлетке = (кто) => кто?.alive !== false &&
    кто?.cell?.row === spot.row && кто?.cell?.col === spot.col;
  const mate = units.find((other) => other !== unit && наКлетке(other))
    ?? (наКлетке(hero) ? hero : null);
  if (!mate) return false;
  if (свой) swing(unit, { melee: true, training: true, pace: 0 });
  //: Идущего напарника движок не трогает вовсе — ни разворотом, ни опытом.
  if (POSE_WALKS.has(mate.pose)) return true;
  //: СТОРОНА ИГРОКА, А НЕ СВОЯ. Движок сверяет напарника с записью игрока
  //: (`[0x1B]` обоих), и разворот с опытом достаются только своим; чужой
  //: на соседней клетке всё равно машет, просто впустую. Здесь стояло
  //: `mate.side !== unit.side`, и у деревенской пары это совпадало
  //: случайно — сторона у жителей одна.
  if ((mate.side ?? 0) === (hero.side ?? 0)) {
    mate.direction = ((unit.direction ?? 0) + 4) & 7;
    if (clockPhaseHits(SPARRING_PHASE)) grantExperience(mate, 1);
  }
  mate.target = null;
  swing(mate, { melee: true, training: true, pace: swingHalf(unit) });
  return true;
}

//: Занятие по виду рабочего места (VA 0x412C0C): решает СТАРШАЯ половина.
function orderFromWorkplace(previous, workplace) {
  const high = (workplace?.kind ?? 0) & 0xF0;
  const kind = (high === 0x90 || high === 0xA0) ? 9
    : (high === 0x70 || high === 0x80) ? 10 : 7;
  return (previous & 0xF0) | kind;
}

function pickWorkplace(unit) {
  const table = workplaceTable(unit);
  const mine = unit.workplaces ?? [];
  if (!table || mine.length < 1) return null;
  const atNight = isNight();
  //: Воевода (должность 4) открывает БОЕВЫЕ места. Без него житель на клетку
  //: спарринга не встанет, и казарма стоит без толку — 0x412C0C:45.
  const warlord = (world.map?.village?.officials ?? [])[4] ?? 0;
  const fitting = [];
  for (const number of mine) {
    const place = table.find((row) => row.slot === number);
    if (!place) continue;
    const kind = place.kind ?? 0;
    // ОБЫЧНАЯ РАБОТА (старшая половина вида ноль) годится ВСЕГДА — ни времени
    // суток, ни воеводы движок у неё не спрашивает (0x412C0C:33). Здесь стояла
    // общая проверка на всех, и ночью жителям не оставалось ни одного места.
    if ((kind & 0xF0) === 0) { fitting.push(place); continue; }
    // Днём годятся места С битом 0x10, ночью — БЕЗ него (0x412C0C:39-44).
    // Поле `night` пака — это и есть тот бит, поэтому сравнение прямое, а не
    // обратное: раньше здесь стояло `night !== ночь`, то есть наоборот.
    if (atNight === Boolean(kind & WORKPLACE_NIGHT_BIT)) continue;
    if ((kind & 0xF0) >= WORKPLACE_COMBAT_FROM && !warlord) continue;
    fitting.push(place);
  }
  if (!fitting.length) return null;
  // Выбор с весом: складываем веса и бросаем по сумме. Нижней границы у веса
  // нет — место с нулём просто не выпадает.
  let total = 0;
  const thresholds = fitting.map((place) => (total += place.weight ?? 0));
  const roll = total < 2 ? 0 : Math.floor(Math.random() * total);
  const workplace = fitting[thresholds.findIndex((edge) => roll < edge)] ?? fitting[0];
  const stayFor = workplace.long
    ? Math.floor(Math.random() * 180) + 60
    : Math.floor(Math.random() * Math.max(1, workplace.stay * 2)) + 15;
  return { ...workplace, stayFor };
}

function followRules() { return data()?.rules?.orders?.follow ?? null; }

// Куда встать возле вожака (VA 0x41209C). Движок берёт клетку из таблицы
// построения: направление — ОТ СПУТНИКА К ВОЖАКУ, чётность — строки
// вожака, место — со случайного из двенадцати по кругу. Годится клетка в
// пределах карты, проходимая и по ту же сторону стены, что вожак. Не
// нашлось за двенадцать — направление сдвигается, и так четыре захода.
function formationSpot(unit, leader, options = {}) {
  const set = followRules();
  const table = set?.formation;
  if (!table || !leader?.cell) return null;
  const parity = leader.cell.row & 1;
  const rows = table[parity];
  if (!rows) return null;
  let direction = options.direction ?? directionTo(unit, leader);
  const tries = options.tries ?? set.tries ?? 4;
  const inside = hero.buildingCells?.get(heroCellKey(leader.cell.row, leader.cell.col));
  for (let attempt = 0; attempt < tries; attempt += 1) {
    const all = rows[direction % rows.length] ?? [];
    // ДВА КОЛЬЦА В ОДНОЙ ТАБЛИЦЕ. На направление в ней двенадцать мест, но
    // берут их по-разному: догон вожака перебирает все двенадцать
    // (VA 0x41209C), а расстановка отряда по приходу на карту — только
    // первые ШЕСТЬ, ближнее кольцо (VA 0x415238: `rand() % 6`, и счёт по
    // кругу возвращается на ноль с шестёрки).
    const slots = options.slots ? all.slice(0, options.slots) : all;
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



//: Встаёт ли эта тварь снова: только Скелет, только пока счётчик не пуст и
//: только если её набор кадров вообще знает позу подъёма (блок 4).
function skeletonRises(unit) {
  if (((unit.breed ?? 0) & 0x7F) !== BREED_SKELETON) return false;
  if ((unit.breedCounter ?? 0) < 1) return false;
  const sets = world.map?.creatures?.sets?.[String(unit.body)]
    ?.[String(unit.palette ?? 0)];
  return Boolean(sets?.rise);
}

//: Потолок здоровья — 0x640 на всех (VA 0x41C494).
function healthCap() {
  return data()?.rules?.effects?.health?.max ?? 1600;
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
  world.healthSet?.(unit, 0);
}

export function unitDamage(unit, amount, attacker = null) {
  if (!unit.alive) return false;
  // Отряд жертвы поднимает не урон, а ЗАМАХ (см. warbandSwing) — здесь
  // объявление нужно только для урона, пришедшего мимо замаха: долетевшая
  // стрела поднимает отряд жертвы в миг попадания (VA 0x41FDD0).
  //
  // НО НЕ ОТРЯД ИГРОКА: стрельба по юниту стороны игрока войну ему НЕ
  // объявляет — 0x41FDD0:72 явно пропускает такую жертву
  // (`if ((&DAT_007b3b23)[жертва] != _DAT_0084951C[0x1B]) 0x4159DC(...)`).
  // На обстрел издалека отряд в оригинале сам не отвечает — только на
  // ближний замах (0x413894, кадр 2) и на приказ игрока.
  if (attacker && (attacker.side ?? 0) !== (unit.side ?? 0) &&
      !unit.ally && (unit.side ?? 0) !== (hero.side ?? 0)) {
    warbandSwing(attacker, unit, units);
  }
  unit.health -= amount;
  unit.hurt = 0.25;
  if (unit.health <= 0) {
    world.healthSet?.(unit, 0);
    die(unit);
    return true;
  }
  // Реакция на удар — блок 2, короткая и общая для всех стоек. СЛАБЫЙ
  // удар (урон меньше 0x30 = 48, код −1 из 0x41C194) жертву НЕ
  // прерывает: движок зовёт 0x416740(жертва, 2) только при коде 0
  // (0x413894: `if (local_20 == 0) FUN_00416740(puVar5, 2)`).
  //
  //: СБИВАЕТ И ПОСРЕДИ ЗАМАХА, И ПОВЕРХ УЖЕ ИДУЩЕГО СБИВА. Никакой проверки
  //: «занят ли юнит» в движке нет. Замер боя Настасьи: 23 сбива из 27
  //: оборвали её замах на кадре 5-6, до кадра удара она не дошла почти ни
  //: разу — двое противников держали её реакцией. Отсюда и «удар не
  //: проходит»: он и не должен, если тебя бьют чаще, чем ты машешь.
  if (amount >= 0x30 && data()?.animations?.actions?.hit) {
    setPose(unit, "hit", true);
  }
  return false;
}

// Попадание по юниту: точка ног внизу, тело уходит вверх примерно на 90
// пикселей и вширь на 28 — это габариты кадра на холсте 256x150. Клик по
// ногам, по груди и по голове должны попадать одинаково.
//: ПРЯМОУГОЛЬНИК ПОД МЫШЬЮ — НАШ, адресов за этими числами нет. Движок
// Попадание в юнита — ПОПИКСЕЛЬНО, по маске нарисованного кадра, как в
// движке: отрисовка юнита пишет его номер в буфер попаданий по
// непрозрачным пикселям (VA 0x425DB4 в конце блита зовёт 0x442260), и
// щелчок просто читает буфер. Прозрачное не пишет ничего — потому в
// оригинале клик «между ног» героя проваливается к куче за ним, а наша
// прежняя рамка 60x106 глотала его: при строке сетки в 16 точек она
// накрывала пять строк вверх, и чан рядом с героем не кликался вовсе
// («факел не работает», жалоба 23.08).
//
// Рамка осталась первым, дешёвым отсевом — и запасным ответом, пока кадр
// или его лист ещё не приехали: лучше лишний выбор, чем клик сквозь
// невидимого юнита.
const BODY_HALF_WIDTH = 30;
const BODY_HEIGHT = 92;
const BODY_BELOW = 14;

//: Холст в один пиксель — проба альфы кадра на месте буфера попаданий.
const probeCanvas = typeof document !== "undefined"
  ? document.createElement("canvas") : null;
if (probeCanvas) { probeCanvas.width = 1; probeCanvas.height = 1; }
const probeContext = probeCanvas
  ? probeCanvas.getContext("2d", { willReadFrequently: true }) : null;

//: Ответ пробы: true попал, false мимо, null — кадра или листа ещё нет.
function unitPixelHit(unit, x, y) {
  if (!probeContext) return null;
  const frames = actorFrames(data(), unit);
  const frame = frames?.length
    ? frames[Math.min(unit.frame ?? 0, frames.length - 1)] : null;
  if (!frame) return null;
  // Мерка по ТЕЛУ: слои снаряжения уже общего силуэта, и движок пишет в
  // буфер каждый блит, но тела достаточно — оружие лишь чуть шире.
  const body = actorBody(data(), unit, frame) ?? frame;
  const lx = Math.floor(x) - (Math.round(unit.x) + (body.offset_x ?? 0));
  const ly = Math.floor(y) - (Math.round(unit.y) + (body.offset_y ?? 0));
  if (body.width && body.height &&
      (lx < 0 || ly < 0 || lx >= body.width || ly >= body.height)) {
    return false;                     // вне прямоугольника кадра — мимо
  }
  let image = null;
  let sx = lx;
  let sy = ly;
  if (body.sheet !== undefined) {
    const sheet = sheetsFor(unit)?.[body.sheet];
    image = sheet ? world.images.get(sheet.path) : null;
    sx = (body.x ?? 0) + lx;
    sy = (body.y ?? 0) + ly;
  } else if (body.path) {
    image = world.images.get(body.path);
  }
  if (!image) return null;            // лист не доехал — решает рамка
  probeContext.clearRect(0, 0, 1, 1);
  probeContext.drawImage(image, sx, sy, 1, 1, 0, 0, 1, 1);
  return probeContext.getImageData(0, 0, 1, 1).data[3] >= 128;
}

export function unitAt(x, y, withDead = false) {
  // Герой — такой же юнит отряда (в движке он просто нулевая запись того
  // же массива), поэтому щелчок по его ТЕЛУ обязан выбирать его так же,
  // как щелчок по портрету. Раньше он в переборе не участвовал вовсе.
  let best = null;                    // попавший пикселем, самый ближний
  let bestDepth = -Infinity;
  let backup = null;                  // без кадра: старая рамка со счётом
  let backupScore = Infinity;
  for (const unit of roster(units)) {
    if (unit.hidden) continue;        // ушедшие и исчезнувшие не кликаются
    if (!unit.alive && !withDead) continue;
    const dx = Math.abs(unit.x - x);
    const dy = y - unit.y;                 // положительное — ниже ног
    if (dx > BODY_HALF_WIDTH || dy > BODY_BELOW || dy < -BODY_HEIGHT) continue;
    const hit = unitPixelHit(unit, x, y);
    if (hit === false) continue;      // кадр есть, пиксель прозрачный
    if (hit === true) {
      // Из попавших побеждает нарисованный ПОЗЖЕ: движок пишет буфер в
      // порядке отрисовки, и последний блит перекрывает прежние.
      const depth = unitSortKey(unit);
      if (depth >= bestDepth) { best = unit; bestDepth = depth; }
      continue;
    }
    const score = dx + Math.abs(dy + BODY_HEIGHT / 2) * 0.4;
    if (score < backupScore) { backup = unit; backupScore = score; }
  }
  return best ?? backup;
}

// Кого юнит считает врагом. Разбор целиком канонический и живёт в
// warband.js: врага выбирает не юнит, а его ОТРЯД (VA 0x415B20 объявляет
// бой по зоне, 0x4107EC берёт соседа, 0x410010 — дальнюю цель). Поля
// «злой/добрый» в движке нет вовсе, поэтому и здесь его больше нет.
function enemyOf(unit) {
  return enemyFor(unit, units, (row, col, direction) =>
    heroNeighbor(row, col, direction), rangedTargetPick);
}

// СОСЕД — И БОЛЬШЕ НИКТО (VA 0x4107EC). Юниту, которым распоряжается игрок
// (бит +0x19 & 0x40, у нас `busy`), цель достаётся единственным путём: весь
// рассудок 0x4111E8 заперт условием `(+0x19 & 0x40) == 0`, а обработчик
// приказа 0x410A08 в случае 1 при пустой цели зовёт для такого юнита ровно
// 0x4107EC — обход восьми соседних клеток — и, не найдя соседа, снимает
// приказ (0x416E24). Дальнего выбора 0x410010 для него не существует.
function adjacentFoe(unit) {
  return adjacentEnemy(unit, units, (row, col, direction) =>
    heroNeighbor(row, col, direction));
}

// ВЫБОР ЦЕЛИ СТРЕЛКА (VA 0x411F28). Гейты движка: не тварь, метательное
// гнездо и боеприпас заняты, режим стрельбы взведён ЛИБО самопереключение
// не запрещено тумблером «Выбор оружия» (0x410A08:33). Дальше — юниты
// ВРАЖЬЕГО отряда В ПОРЯДКЕ ЗАПИСЕЙ (не ближайший!): живой, не лежит, и
// выстрел до него возможен (0x414AF8: не в упор, в дальности оружия,
// трасса чиста). Первый подошедший становится целью, и юнит входит в
// стрельбу (0x416AC8 взводит режим).
function rangedTargetPick(unit) {
  if (isBeast(unit)) return null;
  if (!unit.equipment?.ranged || !unit.equipment?.ammo) return null;
  if (!unit.rangedMode && unit.weaponLock) return null;
  const band = warbandOf(unit);
  if (!band?.fighting) return null;
  const bow = actorItem(unit.equipment.ranged);
  const reach = bow?.range_cells ?? 0;
  if (!reach) return null;
  const set = hero.data?.rules?.accuracy;
  const min = set?.ranged_min_cells ?? 3;
  for (const other of membersOf(band.enemySide, units)) {
    if (other === unit || other.alive === false || other.hidden) continue;
    if (!other.cell) continue;
    const dist = cellRange(unit, other);
    if (dist < min || dist > reach) continue;
    if (!lineOfFire(unit.cell, other.cell)) continue;
    // Вход в стрельбу: движок здесь же ставит режим (+0xEE = 1).
    unit.rangedMode = true;
    return other;
  }
  return null;
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

// ПОХОДКА УДАРА — вот чем движок задаёт темп, а не «перезарядкой».
//
// `FUN_00416B50` кладёт позу удара и последней строкой ставит байт +0xFD —
// сколько ТАКТОВ держится каждый кадр анимации:
//
//     если зверь (+0x1A & 0x40):      +0xFD = 1
//     иначе если 4 − скорость < 2:    +0xFD = 1
//     иначе:                          +0xFD = 1 + rand() % (4 − скорость)
//
// ПАУЗА ЗАМАХА СИДИТ НА НУЛЕВОМ КАДРЕ, а сам замах всегда идёт по кадру за
// такт. Байт +0xFD — не делитель темпа, а ОБРАТНЫЙ ОТСЧЁТ: разбор такта
// (VA 0x413894, случаи 5/8/9) на каждом такте либо убавляет его на единицу и
// не делает больше НИЧЕГО, либо, когда он ноль, двигает кадр:
//
//     else if (+0xFD == '\0') { ... FUN_0041611C ... }   (0x413894:365)
//     else                    { +0xFD = +0xFD + -1; }    (0x413894:471)
//
// Сам 0x41611C замедлений не знает вовсе: +0x1C растёт на единицу за вызов, а
// блок кончается по +0x1C >= +0xFE (0x41611C:22 и :32). Новый отсчёт бросает
// 0x416B50 на КОНЦЕ блока (0x413894:412-415) — оттого пауза и приходится на
// начало следующего замаха, а не на его хвост.
//
// Замер на живом движке (tools/livepeek.py, 253 такта подряд без пропусков)
// показывает ровно это: к0/п2 к0/п1 к0/п0 к1/п0 к2/п0 … к11/п0. Блок позы 9 —
// 12 кадров (+0xFE = 12), кадры идут по одному за такт, на нуле юнит стоит
// 1..3 такта, а между началами замахов 13, 14, 14, 13, 14 тактов, то есть
// 1,01…1,17 с.
//
// Порт же растягивал ВЕСЬ замах в 1..3 раза, и цикл выходил 12..36 тактов
// вместо 13..15.
function attackWait(unit) {
  if (isBeast(unit)) return 1;
  const room = 4 - (world.unitSpeed?.(unit) ?? 0);
  if (room < 2) return 1;
  return 1 + Math.floor(Math.random() * room);
}
world.attackWait = attackWait;

function attack(unit) {
  unit.direction = directionTo(unit, unit.target ?? hero);
  swing(unit);
  unit.struck = false;
  return unit;
}

// ВЗЯТЬ БОЕВОЙ ПРИКАЗ (вид 1) НА СЕБЯ. В движке автобой — это тоже приказ:
// рассудок пишет юниту 0x21 (VA 0x4111E8), а сосед-враг — прямо единицу с
// целью в +0x10 (VA 0x4107EC). На этом виде держатся сразу четыре
// механизма: перехват «кто бьёт МЕНЯ» у соседей (0x4107EC, ветка а),
// «стая» и «свободный» у тварей (0x41F0D0/0x41F340 смотрят чужой приказ и
// цель) и ВЫХОД ОТРЯДА ИГРОКА ИЗ БОЯ — война гаснет, только когда ни у
// кого из его юнитов нет вида 1 (VA 0x415B20:147-156). Пока порт дрался
// без приказа, всё это было мертво: ветки не срабатывали никогда, а война
// игрока гасла посреди боя за шестнадцать тактов.
//
// Путь НАРОЧНО не сбрасывается: это не выдача приказа игроком (0x4240BC),
// а каждотактное удержание боевого вида, как случай 1 в 0x410A08.
function combatOrder(unit, target) {
  const kind = orderKinds().target ?? 1;
  if ((unit.orderKind ?? 0) === kind && unit.orderTarget === target) return;
  unit.orderKind = kind;
  unit.orderTarget = target;
  unit.orderByte = ((unit.orderByte ?? 0) & 0xF0) | (kind & 0x0F);
}

// КАДР УДАРА В БЛИЖНЕМ БОЮ — ТАБЛИЦА ДВИЖКА, а не «предпоследний кадр».
// Каждый такт после сдвига кадра зовётся FUN_00412480 (0x413894:416), и он
// возвращает номер гнезда оружия, только когда кадр совпал с числом из
// таблицы у 0x45FE90 + номер блока позы; иначе −1, и урона нет вовсе. Байты
// там ЗНАКОВЫЕ и читаются со сменой знака (в декомпиляте так и стоит унарный
// минус), поэтому 0xFB читается как 5, а 0xF9 как 7.
//
// Позу 9 движок разбирает отдельной веткой: байт 0x45FE98 = 0xF9 делится на
// половинки — на кадре `(0xF9 & 0x70) >> 4` = 7 бьёт гнездо 0 (основная
// рука), на кадре `0xF9 & 0x0F` = 9 гнездо 4 (вторая рука). Отсюда и два
// клинка: второй меч бьёт своим кадром того же замаха.
//
// ЗАМЕРОМ ПОДТВЕРЖДЕНА ПОЗА 5: из 24 попаданий по игроку 12 пришлись ровно на
// кадр 5 отслеживаемого противника, остальные — от второго нападавшего, за
// которым трасса не следила. Это же подтверждает и знаковое чтение таблицы:
// «предпоследний кадр» дал бы 5 из 6 у блока в шесть кадров, а не 5 из 12.
// ЗАМЕР ПОДТВЕРДИЛ И ВТОРУЮ РУКУ. Бой один на один, 47 попаданий: 46 из них
// легли ровно на кадры 7 и 9, и внутри ОДНОГО замаха по ОДНОЙ жертве видно
// обе руки — такт 543611 «#424 −97» на кадре 7 и такт 543613 «#424 −25» на
// кадре 9. Вторая рука бьёт ВСЕГДА: с мечом в среднем 79 (71…89), с пустой
// рукой 25 (24…26) — то есть кулаком. Отсюда и смысл двух клинков.
const STRIKE_FRAME = {
  // блок 5, байт 0x45FE95 = 0xFB → кадр 5 (замер: 12 попаданий из 12)
  attack_shield: [{ frame: 5, hand: "main" }],
  // блок 8, байт 0x45FE98 = 0xF9 → кадр 7
  attack_two_hand: [{ frame: 7, hand: "main" }],
  // блок 9, половинки того же 0xF9: 7 — гнездо 0, 9 — гнездо 4
  attack_one_hand: [{ frame: 7, hand: "main" }, { frame: 9, hand: "off" }],
};

//: Герою нужны те же кадры. Импортировать units.js в combat.js можно, но
//: правило одно на всех, и владелец у него здесь — отдаём через мир, как
//: attackWait и isStrikePose.
world.strikeFrames = (pose, total) => {
  // Выстрел привязан не к таблице, а к концу блока: 0x413894:321 сверяет кадр
  // с «всего − 6». Оттого лук и виден натянутым дольше, чем меч занесённым.
  if (isShootingPose(pose)) {
    const set = data()?.rules?.accuracy?.projectiles;
    return [{ frame: Math.max(0, total - (set?.shot_frame_from_end ?? 6)),
              hand: "main" }];
  }
  return (STRIKE_FRAME[pose] ?? []).filter((hit) => hit.frame < total);
};

// Какой рукой бьёт этот кадр — или ничего, если удара на нём нет.
function strikeHand(unit, before, after) {
  const frames = actorFrames(data(), unit);
  if (!frames?.length) return null;
  // Незнакомую позу замаха не угадываем: удар не пропадёт — его добьёт
  // запасной ход в конце блока (см. ниже).
  const hit = world.strikeFrames(unit.pose, frames.length)
    .find((step) => before < step.frame && after >= step.frame);
  return hit?.hand ?? null;
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
//: Герою правило нужно так же, но импортировать units.js в hero.js нельзя —
//: получится кольцо. Отдаём через мир, как unitSpeed и attackWait.
world.isStrikePose = isStrikePose;

// ОТСЧЁТ ЕСТЬ ТОЛЬКО У БЛИЖНЕГО БОЯ. Разбор такта держит стрельбу и рубку
// в РАЗНЫХ случаях: блоки лука и самострела это case 4 и case 0x0A
// (0x413894:312-350), и байта +0xFD там нет ни разу — блок просто играется.
// Отсчёт живёт в case 5/8/9, у ближнего боя (:351-473).
//
// Замер стрельбы это подтвердил: 18 выстрелов подряд, походка всё время 254,
// а между выстрелами ровно 15 тактов — длина блока, без единого лишнего.
function isMeleePose(pose) {
  return isStrikePose(pose) && !isShootingPose(pose);
}
world.isMeleePose = isMeleePose;

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
  const workPhase = clockPhaseHits(0xF);
  if (workPhase) warbandsTick(units);
  // БЮДЖЕТ ПЕРЕСЧЁТА МАРШРУТА НА ЭТОТ КАДР. Считается от МИРОВЫХ тактов, а не
  // от кадров браузера: на 144 Гц кадров втрое больше, а игры — столько же.
  // Обычно `clock.elapsed` равен нулю или единице, поэтому и бюджет либо
  // пуст, либо равен REPLAN_PER_TICK.
  replanBudget = REPLAN_PER_TICK * clock.elapsed;
  let active = false;
  // ГЕРОЙ — ПЕРВЫЙ ЮНИТ ЭТОГО ЖЕ ЦИКЛА. В движке отдельного «тика героя»
  // не существует: 0x413894 перебирает все отряды, и игрок — просто первая
  // запись отряда №0. Его рассудок, движение, кадры и удары идут этим же
  // кодом; особых веток у него три — клавиатура (ввод вместо приказа),
  // отсутствие деревенских дел и зеркало combat.target для интерфейса.
  for (const unit of roster(units)) {
    const isHero = unit === hero;
    // Скрытый — исчезнувшая тварь или ушедший с карты (removed): он лежит
    // в массиве только ради снимка карты, жить ему нечем.
    if (unit.hidden) continue;
    if (unit.hurt > 0) unit.hurt = Math.max(0, unit.hurt - dt);
    if (unit.cooldown > 0) unit.cooldown = Math.max(0, unit.cooldown - dt);

    if (unit.alive) {
      // Разговор кончился — «стой, с тобой говорят» снимается (0x413894:140).
      waitTalkTick(unit);
      const acting = Boolean(data().animations.actions?.[unit.pose]);
      // ТРЕНИРОВКА ТИКАЕТ И В АНИМАЦИИ УДАРА.
      //
      // Гейт `acting` ниже поставлен против дребезга ВЫБОРА ЦЕЛИ, и к
      // приказам 9 и 10 он отношения не имеет: цели у них нет вовсе, а в
      // движке их такт (0x413894) идёт раз в 16 мировых тактов независимо
      // от того, что юнит играет. Играет же тренирующийся почти всегда
      // удар — и получал оттого один такт из двадцати: махал, но опыт не
      // капал и с места не уходил. Замер: три такта из шестидесяти трёх.
      //
      // Здесь же убывает и срок пребывания (+0xF5): в движке он стоит в
      // той же ветке приказа, а не в рассудке.
      if (unit.alive && workPhase && unitSparring(unit)) {
        unit.workRest = Math.max(0, (unit.workRest ?? 0) - workPhase);
        sparringTick(unit);
      }
      // РЕШЕНИЯ ПРИНИМАЮТСЯ РАЗ В МИРОВОЙ ТАКТ, а не на каждый кадр браузера.
      //
      // В движке весь такт юнита (0x413894) идёт один раз за такт мира, и
      // рассудок внутри него заперт байтом приказа:
      //
      //     if ((local_3c[0x16] & 0xfU) == 0) FUN_004111e8(...);   (:50)
      //
      // У нас `unitsTick` зовётся из кадра отрисовки, и вся эта цепочка
      // крутилась шестьдесят раз в секунду вместо двенадцати с половиной.
      // Отсюда дребезг: юнит перерешал по нескольку раз внутри одного такта,
      // а журнал игрока показал это в чистом виде — замах начинался заново
      // каждые 12-22 мс. Сюда же перенесён и ВЫБОР ЦЕЛИ: он тоже часть
      // рассудка и по кадрам крутиться не должен.
      //
      // Ниже по циклу движение и анимация остаются ПОКАДРОВЫМИ: рисовать
      // рывками нельзя, а решать — только по тактам.
      if (!acting && clock.elapsed) {
        // ЦЕЛЬ БОЯ ЛИПКАЯ (0x410A08, случай 1): однажды выбранная — приказом
        // игрока (0x61) или рассудком (0x21) — держится в +0x10 до смерти
        // или сброса (0x416E24), и обработчик приказа каждый такт лишь
        // обновляет клетку цели. Перевыбор — только когда цели нет: тогда
        // рассудок берёт соседа (0x4107EC) либо дальнюю (0x410010).
        const kindTarget = orderKinds().target ?? 1;
        let target = null;
        if ((unit.orderKind ?? 0) === kindTarget) {
          const held = unit.orderTarget;
          if (held && held.alive !== false && !held.hidden) target = held;
          else orderClear(unit);              // цель кончилась — 0x416E24
        }
        // ПОД РУКОЙ ИГРОКА ЦЕЛЬ НЕ ИЩУТ. Разница между `adjacentFoe` и
        // `enemyOf` — это и есть разница между двумя состояниями движка:
        //
        //   бит +0x19 & 0x40 стоит  — приказ игрока; рассудок не зовётся
        //                             вовсе, берётся только сосед (0x4107EC)
        //   бит снят                — рассудок ищет дальнюю жертву (0x410010)
        //                             и гонит юнита к ней
        //
        // Бит ставит КАЖДЫЙ приказ игрока мышью (0x4240BC и ветка 0x26 в
        // 0x421690) и снимают ровно три события: щелчок по врагу (0x61),
        // «Все ко мне» (0x420BFC) и подъём по разговору (0x4333A4). Завершение
        // приказа его НЕ снимает — 0x416E24 пишет только +0x10 и +0x16.
        if (!target) target = unit.busy ? adjacentFoe(unit) : enemyOf(unit);
        const distance = target ? cellDistance(unit, target) : Infinity;
        // ПОДОШЛИ ВПЛОТНУЮ — БЕРЁМСЯ ЗА РУКУ (VA 0x416B50, третья команда:
        // `+0xEE = 0`): движок, начиная ближний удар, сбрасывает режим
        // стрельбы безусловно. Порог — тот же, что запрещает выстрел
        // (VA 0x414AF8): ближе него держаться за метательное незачем.
        const closeCells = hero.data?.rules?.accuracy?.ranged_min_cells ?? 3;
        if (unit.rangedMode && target && distance < closeCells) unit.rangedMode = false;
        // ...И ОБРАТНО: задумывание пересчитывает режим стрельбы заново
        // (VA 0x412FF4 — стреляет тот, у кого есть И метательное, И
        // боеприпас). Без подъёма лучник, сбитый в рукопашную (близким
        // врагом или тренировочным замахом 0x416B50), не стрелял бы уже
        // никогда.
        else if (!unit.rangedMode && target && distance >= closeCells &&
                 unit.equipment?.ranged && unit.equipment?.ammo) {
          unit.rangedMode = true;
        }
        // РАДИУСА ОБЗОРА В ДВИЖКЕ НЕТ. Здесь стояло `distance <= unit.sight`,
        // и само поле `sight` было нашей выдумкой. Движок решает ОТРЯДОМ:
        //   0x415B20  война объявляется по прямоугольнику отряда
        //   0x410010  юнит воюющего отряда идёт к цели без предела расстояния
        //   0x41F234  цель — ближайший живой враг, верхней границы нет
        //   0x410784  война держится, пока есть пара ближе 840 пикселей
        // Обе половины живут в warband.js (`insideZone` и `engaged`).
        const sees = Boolean(target);
        unit.target = sees ? target : null;
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
        } else if ((unit.orderKind ?? 0) === (orderKinds().talk ?? 2) &&
                   world.onUnitArrived?.(unit)) {
          // РАЗГОВОР МЕРИТСЯ КАЖДЫЙ ТАКТ прямоугольником 7×4 (VA 0x4115AC),
          // а не равенством клеток: на клетку собеседника не встать — её
          // держит он сам, и точного прибытия у talk-приказа НЕ БЫВАЕТ.
          // Ветка «дошли, насколько можно» в unitMove честно ставила юнита
          // рядом, но прибытие после этого никто не разбирал: walkToOrder
          // строил путь в занятую клетку, шаг его отвергал — и так каждый
          // такт, вечно. Разговор по приказу не открывался ни на одной
          // карте; кликом в упор — тем же кругом. orderArrived сам мерит
          // withinTalk: не достаёт — вернёт null, и ниже идёт ходьба.
        } else if (unit.orderKind && unit.orderKind !== kindTarget &&
                   walkToOrder(unit)) {
          // ПРИКАЗ ИГРОКА СИЛЬНЕЕ СОБСТВЕННЫХ ДЕЛ (VA 0x413894: рассудок
          // только при нулевой младшей половине приказа) — но БОЕВОЙ приказ
          // (вид 1) сюда не входит: движок ведёт его тем же случаем 1
          // обработчика 0x410A08, что и рассудочный 0x21, — это общая
          // боевая ветка ниже, с погоней за ТЕКУЩЕЙ клеткой цели. Раньше
          // приказ «бей» шёл этой веткой в клетку, где враг стоял в миг
          // клика, а не за самим врагом.
        } else if (sees &&
                   withinReach(unit, target, distance, actorReach(unit)) &&
                   canStrike(unit, target, distance)) {
          // Враг вплотную — боевой приказ на себя, как 0x4107EC пишет
          // `+0x16 = 1` и цель в +0x10 перед самым ударом.
          combatOrder(unit, target);
          unit.path = [];
          unit.goal = null;
          unit.goalTarget = null;
          //: ПОКА БЛОК ДЕЙСТВИЯ НЕ ДОИГРАН, ЗАНОВО НИЧЕГО НЕ РЕШАЕТСЯ. В
          //: движке поза держится сама: случаи 5/8/9 крутят замах до конца
          //: блока и лишь тогда зовут 0x416B50 за новым отсчётом. Раньше эту
          //: роль играла выдуманная ATTACK_COOLDOWN — она же задавала темп.
          //:
          //: СЧИТАЕТСЯ ЛЮБОЙ БЛОК ДЕЙСТВИЯ, А НЕ ТОЛЬКО ЗАМАХ. Сбитый удар
          //: (поза 2, «hit») — это тоже блок, и он ОБЯЗАН доиграться: пока он
          //: идёт, юнит в разбор боя не попадает вовсе (у позы 2 свой случай,
          //: не 5/8/9). Проверка на один лишь замах отменяла сбив следующим
          //: же тактом, и удар по бойцу переставал его прерывать.
          //:
          //: Замер оригинала: сбив держится 9 тактов (18 раз из 27), и за
          //: время боя он оборвал 23 замаха из 27 — двое противников не дали
          //: Настасье довести до конца почти ни одного удара.
          const playing = data().animations.actions?.[unit.pose] &&
            actorFrames(data(), unit)?.length;
          if (playing) { active = true; }
          else { attack(unit); active = true; }
        } else if (sees && unit.busy) {
          // ДАЛЬНЯЯ ЦЕЛЬ ПОД РУКОЙ ИГРОКА ПРОСТО ОТБРАСЫВАЕТСЯ. Тот же бит
          // запирает и шаг к цели, причём у движка там не «стоять с целью в
          // руках», а именно снятие приказа (0x410A08, случай 1, цель жива):
          //
          //     if ((…) && ((param_1[0x19] & 0x40) == 0))
          //          FUN_00416574(param_1, клеткаЦели…, 1);   // идти
          //     else FUN_00416e24(param_1);                   // снять приказ
          //
          // И это не мелочь. Держать цель — значит держать вид приказа 1, а
          // отряд игрока выходит из боя ровно тогда, когда единицы нет ни у
          // кого (warband.js, ветка `band.player`). Оставь мы цель в руке —
          // война не кончилась бы никогда, то самое «агро висит».
          //
          // Вплотную подошедшего бьём веткой ВЫШЕ: этот случай — только про
          // недосягаемого, за которым пришлось бы идти.
          orderClear(unit);
          unit.target = null;
          unit.path = [];
          unit.goal = null;
          unit.goalTarget = null;
          unit.chaseAt = null;
          if (!unit.step) setPose(unit, "stand");
        } else if (sees) {
          // Дальняя цель — тот же боевой приказ: рассудок ставит 0x21, и
          // случай 1 в 0x410A08 ведёт юнита за ТЕКУЩЕЙ клеткой цели.
          combatOrder(unit, target);
          drawWeapons(unit);
          // НА ВРАГА ИДУТ БЕГОМ (VA 0x416574). Постановка приказа поднимает
          // бит бега `+0x19 |= 0x80` безусловно, как только вид приказа равен
          // единице (бой) — при двух оговорках: скорость не отрицательна и
          // юнит НЕ ТВАРЬ:
          //
          //     if ((вид == 1) && (-1 < скорость(+0x1D)) && ((+0x1A & 0x40) == 0))
          //         +0x19 |= 0x80;
          //
          // Скорость здесь ТЕКУЩАЯ по канону (carry.js): у NPC — из записи,
          // формула из характеристик — только отряду игрока.
          unit.running = !isBeast(unit) && (world.unitSpeed?.(unit) ?? 0) >= 0;
          // Идём В САМУ КЛЕТКУ ЦЕЛИ: движок принимает её занятой, потому что
          // на ней стоит именно тот, к кому мы идём (VA 0x441441 сверяет
          // занявшего с полем +0x10). Дойдя вплотную, шагнуть туда не выйдет
          // — и это не тупик, а вход в удар: занятую клетку разбирает
          // VA 0x415090 и переводит юнита в бой.
          // ЦЕЛЬ УШЛА С КЛЕТКИ — МАРШРУТ УСТАРЕЛ.
          //
          // Раньше путь строился ТОЛЬКО когда кончился прежний, и погоня шла
          // в точку, где враг был минуту назад: добежал — осмотрелся — побежал
          // дальше. Движок так не делает: `0x410010` ставит путь и тут же
          // гасит младшую половину байта приказа (`+0x16 &= 0xB0`), поэтому
          // рассудок отрабатывает СНОВА на следующем мировом такте и строит
          // маршрут в текущую клетку цели. То есть курс правится каждые 78 мс.
          //
          // Буквально повторить нельзя, и это вопрос не аккуратности, а
          // арифметики. Замер на карте 23 (сетка 7556 клеток, путь кусками по
          // 15 шагов): один поиск стоит 2.4…3.4 мс. Сорок преследователей ×
          // 12.8 такта в секунду = 512 поисков, то есть полторы секунды
          // счёта на секунду игры. У авторов игры этой беды не было: их волна
          // считалась на месте и на порядок дешевле, а нам это же считать в
          // сети и на общем сервере.
          //
          // Поэтому: ПОВОД канонный (цель сменила клетку), а ЧАСТОТА под
          // бюджетом. Бюджет привязан к мировым тактам, а не к кадрам
          // браузера, — иначе на быстром мониторе цена вырастет втрое ни за
          // что. Кому бюджета не хватило, тот идёт по прежнему маршруту и
          // попробует на следующем такте: цель за это время сдвинется на
          // клетку-другую, и погоня всё равно сходится.
          let stale = !unit.chaseAt || unit.chaseAt.row !== target.cell.row ||
            unit.chaseAt.col !== target.cell.col;
          // ОБРЕЗКА ХВОСТА ВМЕСТО ПОИСКА. Цель часто сходит на клетку, которая
          // и так лежит на нашем маршруте — она же от нас убегает по той же
          // земле. Тогда искать нечего: путь уже ведёт туда, лишнее надо
          // просто отрезать.
          //
          // Проход по направлениям от своей клетки стоит пятнадцать сложений
          // (длина куска пути), поиск волной — 2.4…3.4 мс. Разница в тысячу
          // раз, поэтому пробуем это ПЕРЕД тем, как тратить бюджет.
          if (stale && unit.path.length) {
            let row = unit.cell.row, col = unit.cell.col;
            for (let step = 0; step < unit.path.length; step += 1) {
              const next = heroNeighbor(row, col, unit.path[step]);
              row = next.row; col = next.col;
              if (row === target.cell.row && col === target.cell.col) {
                unit.path.length = step + 1;
                unit.chaseAt = { row, col };
                stale = false;
                break;
              }
            }
          }
          // АКТИВНАЯ ЗОНА. Дальше 840 пикселей отряд всё равно выйдет из боя
          // (VA 0x410784, тот же порог держит войну), поэтому обновлять курс
          // тому, кто уже за этой чертой, незачем: он либо вот-вот бросит
          // погоню, либо снова войдёт в зону и обновится тогда. На сервере с
          // сорока врагами это снимает основную массу заявок, а канон не
          // трогает вовсе — за той же чертой бой и так кончается.
          const inZone = Math.abs(unit.x - target.x) < KEEP_RANGE &&
            Math.abs(unit.y - target.y) < KEEP_RANGE;
          // ПРОВАЛ ПОИСКА НЕ ЗАПОМИНАЕТСЯ — ПОВТОР КАЖДЫЙ ТАКТ, ПОД БЮДЖЕТОМ.
          //
          // Движок на неудаче снимает приказ (VA 0x416E24: цель в ноль,
          // младшая половина погашена) — и на СЛЕДУЮЩЕМ такте рассудок
          // ставит 0x21 заново, путь прокладывается снова. Так он долбит
          // 12.5 раз в секунду, пока кольцо вокруг цели не освободится, — и
          // юнит занимает освободившуюся клетку сразу.
          //
          // Стоявшая здесь памятка провала (`chaseFail`) хранила пару «моя
          // клетка × клетка цели» и не пускала к поиску, пока обе не
          // сменятся. Освобождение соседней клетки ТРЕТЬИМ юнитом (умер,
          // отошёл) пары не меняет — юнит замирал навсегда: «враг завис,
          // пока я не сменю позицию» и «отряд не может навалиться на
          // одного». Это было прямо против канона.
          //
          // Цену держит общий бюджет: ПОВТОРНЫЙ поиск после провала (путь
          // пуст, клетка цели та же) идёт из REPLAN_PER_TICK наравне с
          // обновлением курса — при толпе застрявших каждый пробует раз в
          // несколько тактов, и сходимость остаётся, а цена ограничена.
          // Свежая цель (клетка сменилась) планируется без бюджета, как и
          // раньше, — иначе приказ игрока отзывался бы с задержкой.
          const retry = !unit.path.length && !stale;
          const need = !unit.path.length || (stale && inZone);
          if (need && (!retry || replanBudget > 0)) {
            if (retry || unit.path.length) replanBudget -= 1;
            unit.path = heroPlanPath(unit.cell, target.cell, unit, target) ?? [];
            unit.chaseAt = { row: target.cell.row, col: target.cell.col };
            // ПРОВАЛ ПОИСКА СНИМАЕТ ЦЕЛЬ, А НЕ МОРОЗИТ ЮНИТА (VA 0x416E24):
            //
            //     *(short *)(+0x10) = 0;          // цель обнуляется
            //     *(byte *)(+0x16) &= 0xB0;       // младшая половина приказа
            //     FUN_00416CF0(...);              // и юнит встаёт
            //
            // Рассудок отработает на следующем такте: перевыберет цель и
            // попробует путь снова — уже из бюджета (см. `retry`).
            if (!unit.path.length) {
              unit.target = null;
              orderClear(unit);
              unit.goal = null;
              unit.goalTarget = null;
              if (!unit.step) setPose(unit, "stand");
            }
          }
          if (unit.path.length) {
            unit.goal = { ...target.cell };
            unit.goalTarget = target;
          } else {
            unit.goal = null;
            unit.goalTarget = null;
          }
        } else if (isHero) {
          // Герою деревенские дела не положены: без цели и приказа он
          // просто стоит — как юнит отряда игрока без наряда (+0xE3 < 0)
          // и вне прямоугольника чужого отряда.
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
              // Далеко — бежать (VA 0x4120C6), но перегруженному бит бега
              // не достаётся и на догоне (VA 0x42F22C, см. unitCanRun).
              unit.running = away > (followRules()?.run_cells ?? 15)
                && (world.unitCanRun?.(unit) ?? true);
            }
          } else if (!unit.step) {
            unit.stance = hero.stance === "combat" ? "combat" : "peace";
            unit.running = false;         // догнал — бег гаснет (0x416740)
            unit.path = [];
            unit.goal = null;
            unit.goalTarget = null;
          }
        } else if (!unit.step && !unit.path.length) {
          // ДЕЛ НЕТ — ОРУЖИЕ УБИРАЕТСЯ (VA 0x411448, рассудок юнита):
          //
          //     test byte [eax+0x1a], 0x40   ; зверю бит не трогают
          //     test byte [eax+0x19], 4      ; стойка боевая?
          //     xor  byte [eax+0x19], 4      ; снять
          //     push 0x10 / call 0x416740    ; и встать в блок 16 — мирный
          //
          // Отсюда и повадка: житель входит в казарму нейтральным,
          // тренируется в боевой стойке и уходит снова нейтральным.
          //
          // ТРЕНИРУЮЩЕГОСЯ НЕ ТРОГАЕМ: у него дело есть, и рассудок до
          // этой ветки не доходит вовсе — он заперт ненулевым приказом
          // (0x413894:50 зовёт 0x4111E8 только при нулевой младшей
          // половине). Без оговорки сброс боролся с замахом каждый кадр, и
          // боец мигал между мирной стойкой и ударом.
          //
          // Снятий бита в движке четыре, и искать их надо ВСЕМИ формами:
          // `and 0xfb` (0x410DCA, разговор) и `xor 4` (0x41145F — вот
          // это, 0x420577, 0x420D0F). По одной форме поиск лжёт.
          if (!unitSparring(unit)) unit.stance = "peace";
          // Бит бега гаснет вместе с боем: движок снимает его при любом
          // не-беговом блоке (VA 0x416740: `if (блок != 7 && блок != 0x13)
          // +0x19 &= 0x7F`). Без этого житель после погони бегал на работу.
          unit.running = false;
          // Житель занят делом: ждёт свой срок на месте, потом выбирает
          // следующее и идёт туда (VA 0x412C0C).
          //
          // Срок убывает РАЗ В 16 МИРОВЫХ ТАКТОВ, а не каждый кадр браузера:
          // VA 0x413894:72 «if ((_DAT_0084962c & 0xf) == 0) local_3c[0xf5]--».
          // По кадрам счётчик шёл примерно в 50 раз быстрее, и жители
          // метались между рабочими местами.
          if (unit.workRest > 0) {
            // ПРИШЁЛ — БЕРЁТСЯ ЗА ДЕЛО СРАЗУ, А НЕ ПО ИСТЕЧЕНИИ СРОКА.
            //
            // Занятие ставится по прибытии: движок отправляет юнита в путь
            // приказом 4/0xB (0x416574) и переставляет приказ на рабочий,
            // когда клетка совпала (0x412C0C:112 -> 0x416CF0). У нас это
            // делала ТОЛЬКО ветка выбора места, а она заперта сроком
            // пребывания — и тот ставится ещё при отправке в путь, на
            // 60…240 тактов деревни. Боец доходил до бочки и стоял минуту,
            // а то и три, прежде чем взяться за меч.
            const место = (workplaceTable(unit) ?? []).find(
              (row) => row.slot === (unit.workplaces ?? [])[0]);
            if (место && unit.cell.row === место.row
                && unit.cell.col === место.col
                && ((unit.orderByte ?? 0) & 0x0F) !== 7 && !unitSparring(unit)) {
              unit.orderByte = orderFromWorkplace(unit.orderByte ?? 0, место);
            }
            //: Тренирующийся оттикал выше, до гейта анимации, — второй раз
            //: срок убавлять нельзя, иначе он уйдёт с места вдвое раньше.
            if (!unitSparring(unit)) {
              unit.workRest = Math.max(0, unit.workRest - workPhase);
            }
          } else {
            //: ОРУЖИЕ УБИРАЕТСЯ ДО ВЫБОРА НОВОГО ДЕЛА. В движке снятие
            //: стойки — САМО ПО СЕБЕ действие рассудка: ветка 0x411448
            //: снимает бит, ставит блок 16 и тут же возвращает «сделано»,
            //: не доходя до выбора работы. Значит доработавший боец сперва
            //: убирает меч и лишь следующим тактом идёт дальше — потому и
            //: уходит из казармы нейтральным, а не с оружием наперевес.
            if (!unit.beast) unit.stance = "peace";
            const workplace = pickWorkplace(unit);
            if (workplace) {
              //: Выбранное место движок переставляет в начало списка жителя
              //: (+0xE6): по первому байту такт поведения берёт направление
              //: взгляда, а спарринг — сторону, куда искать напарника.
              unit.workplaces = [workplace.slot,
                ...(unit.workplaces ?? []).filter((slot) => slot !== workplace.slot)];
              if (unit.cell.row === workplace.row && unit.cell.col === workplace.col) {
                unit.workRest = workplace.stayFor;      // пришёл — работает
                //: Занятие — из старшей половины вида места (0x412C0C:112),
                //: разбор всей казармы в docs/VILLAGE_TRAINING_SPEC.md.
                unit.orderByte = orderFromWorkplace(unit.orderByte ?? 0, workplace);
              } else {
                unit.path = heroPlanPath(unit.cell,
                  { row: workplace.row, col: workplace.col }, unit) ?? [];
                unit.goal = { row: workplace.row, col: workplace.col };
                unit.goalTarget = null;       // рабочее место занимать некому
                unit.workRest = workplace.stayFor;
                // ПРИКАЗ НА ВРЕМЯ ДОРОГИ (VA 0x412C0C:127 -> 0x416574): у
                // движка это param_4, и он ЗАТИРАЕТ младшую половину. Без
                // него прежняя девятка ехала с бойцом дальше, и тот махал
                // мечом всю дорогу до следующего места — тренировка должна
                // идти только на своей клетке.
                const шаг = ((workplace.kind ?? 0) & 0xF0) >= WORKPLACE_COMBAT_FROM
                  ? WALK_TO_COMBAT_ORDER : WALK_TO_WORK_ORDER;
                unit.orderByte = ((unit.orderByte ?? 0) & 0xF0) | шаг;
              }
            }
          }
          if (!unit.path.length) { unit.goal = null; unit.goalTarget = null; }
        }
      }

      // ОДНО движение на всех: та же функция, что двигает игрока.
      // Клавиатура — ввод самого игрока (WASD/стрелки), остальными правят
      // приказы; в unitMove это тот же аргумент, что был у heroMove.
      if (unitMove(unit, dt, { keyboard: isHero })) active = true;
      // ХОДЬБА НЕ СБИВАЕТ НАЧАТЫЙ БЛОК ДЕЙСТВИЯ. Здесь стояло безусловное
      // `if (unit.moving) setPose(...)`, и поза бега возвращалась поверх
      // только что начатого замаха — пока юнит доводил шаг по клетке.
      //
      // Круг выходил такой: кадр N — поза «бег», решения не заперты, ветка
      // удара зовёт attack(), поза становится замахом И ИГРАЕТ ЗВУК; тот же
      // кадр, эта строка — поза обратно в «бег»; кадр N+1 — всё сначала.
      // По журналу игрока (убегал от одного врага) это давало замах с
      // НУЛЕВОГО кадра каждые 12-22 мс, то есть на каждый кадр браузера:
      //
      //     ⚔ замах Асбад  поза attack_shield  кадр 0
      //         setPose ← attack ← unitsTick (units.js:1314)
      //
      // Отсюда и «звук удара по четыре-пять раз за раз», и тридцать четыре
      // одновременных источника при пределе сорок пять — а сверх предела
      // playEffect молча возвращает null, и настоящие звуки пропадают.
      //
      // Позу СЕЙЧАС проверяем заново: `acting` считался в начале кадра, до
      // того как ветка удара её сменила.
      const blocked = Boolean(data().animations.actions?.[unit.pose]);
      if (unit.moving && !blocked) setPose(unit, unitMovePose(unit));
      else if (!acting && (unit.pose === "walk" || unit.pose === "run")) {
        setPose(unit, "stand");
      }
    }


    // тик кадра — тот же, что у героя: ~18 кадров в секунду
    const frames = actorFrames(data(), unit);
    if (!frames?.length) continue;
    // СИДЯЩИЙ В ЗЕМЛЕ НЕ ШЕВЕЛИТСЯ. Расстановка кладёт скелетов, кикимор и
    // ичетиков в позу 4 (в мире 0 таких 92: 71 скелет, 16 кикимор, 5
    // ичетиков), и держит их там сам движок — не особой веткой, а гейтом
    // рассудка: `FUN_00410010` первым делом смотрит `+0x1D` записи отряда и,
    // если тот НЕ в бою, снимает приказ и выходит (VA 0x410010:36). Без
    // приказа тварь никуда не идёт и позы не меняет, поэтому и остаётся в
    // земле, пока отряд не разбудит зона (VA 0x415B20).
    //
    // У нас анимация подъёма проигрывалась сразу при входе на карту, и к
    // приходу игрока все уже стояли в полный рост.
    if (unit.pose === "rise" && !warbandOf(unit)?.fighting) {
      unit.frame = 0;
      continue;
    }
    //: КАДР ИДЁТ ПО ОДНОМУ ЗА ТАКТ ВСЕГДА (0x41611C), замедлений нет ни у
    //: одного блока. Ждать умеет только замах — и ждёт он на нулевом кадре,
    //: проедая обратный отсчёт +0xFD (см. attackWait).
    const step = tickSeconds();
    unit.frameTime += dt;
    const advance = Math.floor(unit.frameTime / step);
    if (advance <= 0) continue;
    unit.frameTime -= advance * step;
    //: Такт в движке делает ЛИБО убавление отсчёта, ЛИБО шаг кадра, поэтому
    //: накопленные такты сперва уходят в ожидание и лишь остаток — в кадры.
    let ticks = advance;
    if (isMeleePose(unit.pose) && unit.attackWait > 0) {
      const spent = Math.min(ticks, unit.attackWait);
      unit.attackWait -= spent;
      ticks -= spent;
      if (ticks <= 0) continue;
    }
    const before = unit.frame;
    const next = unit.frame + ticks;
    if (next < frames.length) {
      unit.frame = next;
      // Замах поднимает отряд жертвы РАНЬШЕ урона — на втором кадре.
      if (unit.alive && unit.pose.startsWith("attack") && unit.target &&
          swingDeclares(before, next)) {
        warbandSwing(unit, unit.target, units);
      }
      //: РУКА У КАЖДОГО КАДРА СВОЯ, и бить надо именно ею: кадр 7 — гнездо 0,
      //: кадр 9 — гнездо 4. Раньше сюда уходил один общий удар, а обе руки
      //: разом наносил уже `meleeStrikes`; с таблицей из двух кадров это дало
      //: бы четыре удара за замах вместо двух.
      const hand = unit.alive && !unitTraining(unit) &&
        data().animations.actions?.[unit.pose] &&
        isStrikePose(unit.pose) ? strikeHand(unit, before, next) : null;
      if (hand) {
        unit.struck = true;
        world.onUnitStrike?.(unit, hand);
      }
    } else if (unit.step && !data().animations.actions?.[unit.pose]) {
      // ПО КРУГУ ХОДЯТ ТОЛЬКО ПОЗЫ СТОЙКИ. Проверка «юнит шагает» стояла
      // здесь ПЕРВОЙ и ловила заодно все действия: получив удар на бегу,
      // герой вечно отыгрывал «вздрогнуть» и к бегу не возвращался, потому
      // что разбор действий ниже до него не доходил. Сюда же попадали смерть
      // и труп, если шаг не успели снять.
      unit.frame = next % frames.length;
    } else if (unit.pose.startsWith("corpse_")) {
      unit.frame = 0;
    } else if (unit.pose.startsWith("death_")) {
      // У ЧЕЛОВЕКА труп — отдельный блок в один кадр: смерть 3, 11, 12
      // переходит в 13, 14, 15. У ТВАРИ таблица анимаций всего из шести
      // блоков (0…5), блоков трупа в ней нет вовсе — поэтому труп твари
      // это удержанный последний кадр самой смерти.
      // ПОДЪЁМ СКЕЛЕТА (0x413894:275). Движок делает это на кадре «всего − 2»
      // предсмертной анимации: если порода 0x4C и счётчик не пуст — здоровье
      // возвращается ПОЛНЫМ, приказ становится единицей, счётчик убавляется,
      // поза снова 4, и смерть отменяется. У нас проверка стоит на конце
      // анимации, а не за два кадра до него: разница в две сотых секунды и
      // невидима, зато не нужно лезть в счётчик кадров.
      if (skeletonRises(unit)) {
        unit.breedCounter -= 1;
        unit.alive = true;
        unit.orderByte = 1;
        unit.orderKind = 1;
        world.healthSet?.(unit, healthCap());
        setPose(unit, "rise");
      } else if (isBeast(unit)) {
        unit.frame = frames.length - 1;
      } else {
        const variant = unit.pose.slice("death_".length);
        setPose(unit, data().animations.actions?.[`corpse_${variant}`]
          ? `corpse_${variant}` : "corpse_1");
      }
    } else if (data().animations.actions?.[unit.pose] || SET_ACTIONS.has(unit.pose)) {
      // УДАРЫ СЧИТАЕТ ТАБЛИЦА КАДРОВ (`strikeHand`): у выстрела это «всего −
      // 6», у ближнего боя — числа из 0x45FE90, и у одноручного замаха их
      // ДВА, по руке на кадр. Раньше здесь стоял ЕЩЁ ОДИН безусловный удар в
      // конце анимации, и почти каждый замах бил дважды одной рукой — вот
      // откуда «стреляют как из автомата».
      //
      // Запасной ход всё же нужен: у короткой анимации (кадров не больше
      // шести у выстрела) «всего − 6» уходит в ноль, и кадр удара не
      // пересекается никогда. Поэтому бьём в конце ТОЛЬКО если ни на одном
      // своём кадре не ударили, и только основной рукой.
      if (unit.alive && !unitTraining(unit) && isStrikePose(unit.pose)
          && !unit.struck) {
        world.onUnitStrike?.(unit, "main");
      }
      unit.struck = false;
      // ПОДЪЁМ ИЗ ЗЕМЛИ ДОИГРЫВАЕТСЯ ОДИН РАЗ И КОНЧАЕТСЯ СТОЙКОЙ.
      //
      // «rise» — это не действие, а БЛОК ПОЗЫ (номер 4 байта +0x17), и в
      // списке `actions` его нет. Поэтому доигравшая анимация сваливалась в
      // общий запасной ход `frame = 0` и начиналась заново: тварь бесконечно
      // лезла из-под земли. Кончаться она должна стойкой — дальше юнитом
      // распоряжается разбор занятия, а он позу подъёма не ставит.
      setPose(unit, "stand");
    } else if (unit.pose === "idle") {
      // простой доигрывает и возвращается в стойку (таблица 0x45A0C0)
      setPose(unit, "stand");
    } else {
      unit.frame = 0;
      // ЖРЕБИЙ ПРОСТОЯ (VA 0x416D92): каждый раз, когда доигрывает стойка,
      // бросается 1 из N — и юнит уходит в простой. Правило общее: в
      // движке жребий бросает разбор такта для любого стоящего, раньше он
      // жил только у героя в heroTick.
      const chance = data().rules?.idle_chance ?? 10;
      if (!unit.beast && unit.alive && unit.pose === "stand" && chance > 0 &&
          Math.floor(Math.random() * chance) === 0 &&
          data().animations?.[unit.stance ?? "peace"]?.idle) {
        setPose(unit, "idle");
      }
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

// СВЕТЛЫЕ ЮНИТЫ И ОКНА К НИМ. Правило целиком — в docs/RENDER_DEPTH.md,
// здесь только его исполнение.
//
// Клетка с битом 22: движок блитит ЛЮБОГО юнита статичной палитрой
// (VA 0x425E81), мимо пересчёта под сутки, — не только игрока. У нас фильтр
// суток — сплошная заливка слоя сцены, поэтому такой юнит рисуется на сам
// кадр, ПОД слоем, а из слоя вырезается окно, через которое он виден.
//
export function renderUnit(unit) {
  if (unit.hidden) return;            // ушедший с карты не рисуется
  // Круг ложится ДО тела и только под выбранными своими.
  if (selectionCircle(unit)) {
    drawSelectionCircle(unit, Math.round(unit.x), Math.round(unit.y));
  }
  if (layeredFrame && unit.bright) {
    withMainContext(() => drawActor(data(), unit));
    //: ОКНО РЕЖЕМ СРАЗУ, КАК ГЕРОЮ. Раньше юнит становился в очередь
    //: `brightCuts`, а та в конце прохода спрашивала `coveredLater` — и по
    //: РАМКЕ соседнего объекта отменяла вырез. Юнит при этом уже нарисован
    //: ПОД слоем сцены, и без окна он оставался под домом: у тестеров это
    //: выглядело как «спутнику полтела срезало зданием», причём у героя того
    //: же не случалось никогда — он всегда режет сразу
    //: (hero.drawHeroAtDepth → punchHeroSilhouette).
    //:
    //: Глубину это не ломает по той же причине, что и у героя: объекты
    //: переднего плана рисуются ПОЗЖЕ и закрашивают вырез сами.
    punchSilhouette(unit);
    return;
  }
  drawActor(data(), unit);
}

//: Вырезать силуэт юнита из слоя сцены — тем же приёмом, что
//: `punchHeroSilhouette`, только кадр берётся общий для любого актёра.
function punchSilhouette(unit) {
  context.save();
  context.globalCompositeOperation = "destination-out";
  context.globalAlpha = 1;
  drawActor(data(), unit, { silhouette: true });
  context.restore();
}

//: Прорезать окна к отложенным светлым юнитам — зовёт сцена, когда все
//: объекты уже легли в слой. Резать по ходу прохода нельзя: юниты
//: чередуются с объектами по глубине, и слой под ними ещё не готов.
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
    //: Полупрозрачная копия едет тем же якорем, что и сам юнит, — иначе она
    //: отвяжется от него ровно на величину перспективы.
    withPerspective(context, unit.x, unit.y,
                    () => drawActor(data(), unit, { alpha }));
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

// СВИСТОК РАЗГОНЯЕТ ЗВЕРЕЙ (VA 0x436C48, случаи класса 31 и 38).
//
// Движок ищет отряд в прямоугольнике вокруг вожака игрока (FUN_0041ED18:
// ±0x27 строк, ±0x10 столбцов) и каждому его ЗВЕРЮ пишет цель 0 и байт
// приказа 0x28. Приказ 8 — бегство (VA 0x410A08, случай 8): бросок из
// четырёх сторон, и зверь уходит на 0x34 строк вверх или вниз, либо на 0x16
// столбцов вбок; вдоль края ищется свободная клетка (до 0x1A шагов по
// строкам, 0x0B по столбцам), не нашлось — приказ снимается.
//
// Не бегут трое: 0x44 Цветок-людоед (он вовсе не ходит), 0x52 Дракон и 0x56.
const WHISTLE_ROWS = 0x27;
const WHISTLE_COLS = 0x10;
const FLEE_ROWS = 0x34;
const FLEE_COLS = 0x16;
const FLEE_ROW_TRIES = 0x1A;
const FLEE_COL_TRIES = 0x0B;
const FLEE_DEAF = new Set([0x44, 0x52, 0x56]);
const CORPSE_POSES = new Set([3, 0x0B, 0x0C]);

//: Куда бежать: жребий из четырёх сторон, вдоль края ищется свободная клетка.
function fleeSpot(unit) {
  const row = unit.cell?.row ?? 0;
  const col = unit.cell?.col ?? 0;
  const roll = Math.floor(Math.random() * 4);
  if (roll < 2) {
    const drow = roll === 0 ? -FLEE_ROWS : FLEE_ROWS;
    for (let dcol = -FLEE_COL_TRIES; dcol < FLEE_COL_TRIES; dcol += 1) {
      if (heroFree(row + drow, col + dcol, unit)) return { row: row + drow, col: col + dcol };
    }
    return null;
  }
  const dcol = roll === 2 ? -FLEE_COLS : FLEE_COLS;
  for (let drow = -FLEE_ROW_TRIES; drow < FLEE_ROW_TRIES; drow += 1) {
    if (heroFree(row + drow, col + dcol, unit)) return { row: row + drow, col: col + dcol };
  }
  return null;
}

// Разогнать зверей вокруг игрока. Возвращает, скольких проняло.
export function scareBeasts() {
  let scared = 0;
  for (const unit of units) {
    if (unit.ally || unit.alive === false) continue;
    if (!unit.beast && !(unit.breed & 0x40)) continue;
    if (FLEE_DEAF.has((unit.breed ?? 0) & 0x7F)) continue;
    if (CORPSE_POSES.has(unit.type ?? 0)) continue;
    if (!unit.cell || !hero.cell) continue;
    if (Math.abs(unit.cell.row - hero.cell.row) > WHISTLE_ROWS) continue;
    if (Math.abs(unit.cell.col - hero.cell.col) > WHISTLE_COLS) continue;
    const spot = fleeSpot(unit);
    unit.orderTarget = null;
    if (!spot) { orderClear(unit); continue; }
    orderUnit(unit, spot.row, spot.col, orderKinds().go);
    unit.orderByte = 0x28;                    // приказ 8 с меткой «по приказу»
    scared += 1;
  }
  return scared;
}

//: Ближнее кольцо расстановки и полный круг заходов (VA 0x415238).
const ARRIVAL_SLOTS = 6;
const ARRIVAL_TRIES = 8;
const DIRECTIONS = 8;

// ПОСТАВИТЬ ОТРЯД ВОКРУГ ВОЖАКА — перенос FUN_00415238 («поставить отряд на
// карту»). Загрузчик карты зовёт её безусловно, последней строкой
// (VA 0x43DF48:294), и главный цикл — при переходе внутри той же карты
// (VA 0x438A00:210). Вожак встаёт на клетку прибытия сам, остальные ищут
// себе место по кольцу вокруг него:
//
//     сторона = направление отряда < 4 ? +4 : −4     // ПРОТИВОПОЛОЖНАЯ взгляду
//     жребий: та сторона или соседняя слева (сторона − 1)
//     восемь заходов по кругу, в каждом шесть ближних мест со случайного
//     годится клетка в пределах карты и с пустыми младшими битами
//
// Направление отряда движок берёт из его записи (+0x18) и оттуда же
// переписывает вожаку, поэтому у нас его роль играет направление героя.
//
// ПРИКАЗ ГАСНЕТ, А РЕЖИМ ОСТАЁТСЯ. Расстановка чистит только младшую половину
// байта приказа — `юнит[+0x16] &= 0xF0` — и делает это ОБОИМ: вожаку в строке
// 67, остальным в строке 133. Значит «за вожаком» и прочие биты старшей
// половины переезд переживают, а недошедший приказ — нет. Заодно клетка
// назначения приравнивается к клетке, где юнит встал (`+0x13 = +0x12`,
// `+0x15 = +0x14`), и обнуляется буфер шагов (`юнит[+0x00] = 0xFF`) — идти
// после переезда некуда и не по чему.
function arrivalReset(unit, cell) {
  unit.path = [];
  unit.step = null;
  unit.orderByte = (unit.orderByte ?? 0) & 0xF0;
  unit.orderKind = orderKinds().none;
  unit.orderRow = cell.row;
  unit.orderCol = cell.col;
  unit.orderTarget = null;
  unit.goal = null;
  unit.goalTarget = null;
  unit.busy = false;
}

export function partyRegroup() {
  let moved = 0;
  const facing = hero.direction ?? 0;
  // ВОЖАК — ТА ЖЕ ФУНКЦИЯ, ПЕРВАЯ ЕЁ ПОЛОВИНА. Ставит его на клетку отряда
  // сам загрузчик (app.js берёт её из записи двери или таблицы прибытия
  // 0x460028), а поля приказа гасятся здесь — иначе на новую карту приезжает
  // цель со старой, и герой с порога убегает к клетке, которой тут нет.
  // Ровно это тестер и описал как «после перехода герой куда-то бежит»:
  // замер на живом клиенте — приказ 6 на клетку (52,36) карты 33 пережил
  // дверь, и на карте 17 герой вместо клетки прихода (88,33) оказался на
  // (58,36) и продолжал идти.
  if (hero.cell) arrivalReset(hero, hero.cell);
  // Позади вожака: та же клетка ± полкруга (VA 0x415238:97-102).
  const behind = facing < DIRECTIONS / 2
    ? facing + DIRECTIONS / 2
    : facing - DIRECTIONS / 2;
  const mates = units.filter((unit) => unit.ally);
  mates.forEach((unit, index) => {
    //: Жребий из двух сторон — «чёт-нечет» броска (VA 0x415238:108-111).
    const side = Math.floor(Math.random() * 2)
      ? (behind + DIRECTIONS - 1) % DIRECTIONS
      : behind;
    const spot = formationSpot(unit, hero,
                               { direction: side, slots: ARRIVAL_SLOTS,
                                 tries: ARRIVAL_TRIES }) ??
      { row: hero.cell.row, col: hero.cell.col + 1 + index };
    unit.cell = { ...spot };
    unit.home = { ...spot };
    const anchor = heroAnchor(spot.row, spot.col);
    unit.x = anchor.x;
    unit.y = anchor.y;
    arrivalReset(unit, spot);
    moved += 1;
  });
  return moved;
}

//: Свисток зовут из разбора диковин (carry.js) — тем же путём, что и
//: раскрытие тайников зеркалом.
world.scareBeasts = scareBeasts;

//: Список живых для тех, кому нельзя нас импортировать. Свободный снаряд
//: (projectiles.js) ищет, в кого попал, перебором — цели у него нет.
world.unitsInPlay = () => units;
