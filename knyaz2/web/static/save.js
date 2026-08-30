// Сохранение игры в браузере.
//
// ФОРМАТ наш, а вот СОСТАВ должен повторять движок. Он пишет мир блоками
// целиком (VA 0x423CB8, файл KONUNG2.SA<N>): записи юнитов 0x7B3C08 на
// 0x7D000 байт, поселения 0x83D408 на 0x378C, предметы 0x6F956C на 0x20000,
// отряды 0x71E56C на 0xC800, кучи и предметы на земле. Всё, что игра
// меняет, там сохраняется по построению — и потерять поле невозможно.
//
// Здесь блоки разобраны на поля, поэтому потерять поле МОЖНО, и каждая
// потеря — это дыра в игре: без квестовых флагов героя (+0xF9) закрывались
// ветки разговоров, без базовых характеристик (+0xC0) пропадало купленное
// за свободный опыт, без записи поселения повторный залог давал +1000 за
// каждый цикл «заложить — перезагрузиться». Поэтому состав сейва накрыт
// контрактным тестом SaveCoverageContractTest: упакованное обязано и
// восстанавливаться.
//
// Чего сознательно НЕ сохраняем: расположение жителей по деревне, недобитых
// тварей, начатые шаги и приказы. Первые два — упрощение без доказательства
// и числятся в TODO ревью; шаги и приказы движок тоже держит, но игрок
// продолжает с места стоя, и это заметно только в бою.
import { shared, world } from "./world.js";
import { hero, heroStampBuilding } from "./hero.js";
import { preload } from "./content.js";
import { units } from "./units.js";
import { loot, lootReattachTalk } from "./loot.js";
import { dialog } from "./dialog.js";
import { daylight } from "./daylight.js";
import { village, villagePack, villageUnpack } from "./village.js";
import { cellsRestore, knownPack, knownUnpack, placeAt, pointRestore,
         worldMap, worldMapSetup } from "./worldmap.js";
import { mapStateCapture, mapStatePack, mapStateUnpack, packPile }
  from "./mapstate.js";
import { warbandsApply, warbandsPack } from "./warband.js";
import { clock } from "./clock.js";

const KEY = "knyaz2.save.v1";
//: Предыдущее сохранение. Пишется перед каждой удачной записью, читается
//: только если основное пропало или испортилось.
const BACKUP = "knyaz2.save.v1.prev";

//: Что берём у любого члена отряда — героя и спутников одинаково: в движке
//: они и есть одна сущность.
function packActor(actor) {
  return {
    id: actor.id ?? null,
    name: actor.name ?? null,
    slot: actor.slot ?? 0,
    side: actor.side ?? 0,
    cell: actor.cell ? { ...actor.cell } : null,
    x: actor.x, y: actor.y,
    direction: actor.direction ?? 6,
    stance: actor.stance ?? "peace",
    // ПАВШИЙ ДОЛЖЕН ОСТАТЬСЯ ПАВШИМ. В движке сохранять тут нечего: сейв
    // пишет весь массив юнитов (0x423CB8), и бит смерти +0x1A|0x80 едет в
    // нём сам собой, вместе с позой трупа. У нас спутники поднимаются из
    // записи отряда, а расстановка ставит `alive: true` безусловно, —
    // поэтому смерть надо возить явно, как это уже делает packFoe.
    //
    // Из отряда павшего вычёркивает СВЁРТКА КАРТЫ, а не сама смерть: движок
    // проходит по бойцам начиная со второго, у кого поднят бит смерти —
    // раздаёт добро, убавляет счёт отряда +0x1C и сдвигает хвост записей
    // (VA 0x43A628:157-168). До ухода с карты труп лежит на месте — это и
    // повторяет `partyCapture` на выходе. А вот сейв, снятый ДО ухода,
    // воскрешал его живым с нулём здоровья.
    alive: actor.alive !== false,
    //: Поза трупа несёт номер варианта смерти (жребий из трёх, VA 0x416A5D),
    //: и без неё лежачий встал бы в стойку. Живым позу не возим: она
    //: доигрывается сама, а снятая посреди замаха только мешала бы.
    pose: actor.pose ?? "stand",
    //: Тело 15 трупа не оставляет вовсе (VA 0x416A15): бит породы и пустая
    //: клетка. Признак едет вместе со смертью.
    hidden: Boolean(actor.hidden),
    health: actor.health ?? null,
    maxHealth: actor.maxHealth ?? null,
    experience: actor.experience ?? 0,
    nextLevel: actor.nextLevel ?? 0,
    freeExperience: actor.freeExperience ?? 0,
    level: actor.level ?? 1,
    money: actor.money ?? 0,
    // РЕПУТАЦИЯ — счёт «Продолжения легенды» (0x87F410). Движок пишет его в
    // сохранение отдельным числом (0x425158), рядом с прочими глобальными.
    reputation: actor.reputation ?? 0,
    equipment: { ...(actor.equipment ?? {}) },
    bag: [...(actor.bag ?? [])],
    enchant: { ...(actor.enchant ?? {}) },
    bagEnchant: { ...(actor.bagEnchant ?? {}) },
    bagStrength: { ...(actor.bagStrength ?? {}) },
    bagCount: { ...(actor.bagCount ?? {}) },
    bagPoison: { ...(actor.bagPoison ?? {}) },
    itemOiled: { ...(actor.itemOiled ?? {}) },
    wear: { ...(actor.wear ?? {}) },
    wearMax: { ...(actor.wearMax ?? {}) },
    poisonOn: { ...(actor.poisonOn ?? {}) },
    poison: actor.poison ?? 0,
    ammoCount: actor.ammoCount ?? null,
    ammoPoison: actor.ammoPoison ?? 0,
    rangedMode: actor.rangedMode ?? false,
    skills: actor.skills ? JSON.parse(JSON.stringify(actor.skills)) : null,
    // ТРИ БЛОКА ХАРАКТЕРИСТИК, а не один. В записи юнита их именно три:
    // базовые +0xC0, спрятанные «до модификаторов» +0xC6 и текущие +0xCC
    // (konung2/gamefile.py), и движок сохраняет запись целиком.
    //
    // Без базовых купленное за свободный опыт пропадало: на загрузке база
    // пересобиралась из шаблона, а первое же временное зелье прятало её
    // (savedCharacteristics = [...baseCharacteristics]) и по истечении
    // срока откатывало текущие к шаблонным. Без спрятанных сейв во время
    // действия зелья делал бафф вечным.
    characteristics: actor.characteristics
      ? JSON.parse(JSON.stringify(actor.characteristics)) : null,
    baseCharacteristics: actor.baseCharacteristics
      ? JSON.parse(JSON.stringify(actor.baseCharacteristics)) : null,
    savedCharacteristics: actor.savedCharacteristics
      ? JSON.parse(JSON.stringify(actor.savedCharacteristics)) : null,
    // Счётчик временного зелья (+0x4A) и замок прокачки: пока не ноль,
    // поднять ничего нельзя. Без них отравленный и раскачанный зельем
    // герой лечился перезагрузкой.
    potionTicks: actor.potionTicks ?? 0,
    progressLock: actor.progressLock ?? false,
    // Тумблеры окна персонажа — биты +0x19 (0x20 выбор оружия, 0x10
    // защита вожака, 0x01/0x02 лечебные смеси): движок хранит их в самой
    // записи юнита, значит и сейв обязан.
    weaponLock: actor.weaponLock ?? false,
    defendLeader: actor.defendLeader ?? false,
    healTrigger: actor.healTrigger ?? 0,
    // Облик/точность (+0xF8) — его гасит истечение временного зелья.
    look: actor.look ?? null,
    // КВЕСТОВЫЕ ФЛАГИ ИГРОКА — байт героя +0xF9. Их ставит обработчик
    // разговора 34, снимает 42, а читает условие 2: это хребет квестовой
    // логики. Без них после загрузки условие 2 всегда ложно, и всякая
    // ветка, открытая ранее поставленным флагом, закрыта навсегда.
    flags: actor.flags ?? 0,
    stats: actor.stats ? { ...actor.stats } : null,
    orderByte: actor.orderByte ?? 0,
    ally: actor.ally ?? false,
    breed: actor.breed ?? 0,
    body: actor.body ?? 0,
    palette: actor.palette ?? 0,
    // лицо (+0xEF) — тоже поле записи юнита: по нему берётся портрет
    face: actor.face ?? 0,
    // ЧЬЯ ИГРА В СЕЙВ НЕ ПИШЕТСЯ. Это ПРОИЗВОДНОЕ облика, а не состояние:
    // герою её ставит шаблон выбранного мира (progressSetup), юнитам — пак
    // карты и записи отряда. Сейв её и писал, и восстанавливал — и битые
    // сохранения (залипший «legend» у канонного героя, см. progress.js)
    // воскрешали палатку с Иззарком после каждой загрузки, хотя новая игра
    // была уже здорова. Прежний страх «загруженный Драгомир показывался
    // Эйнаром» закрыт шаблоном: он восстанавливается по saved.world ДО
    // применения сейва.
  };
}

// ЧУЖОЙ ЮНИТ В СЕЙВЕ. Мешок, навыки и характеристики ему не нужны: их никто
// не менял, карта отдаст их из пака теми же. Нужно то, что меняет ИГРА, —
// в записи движка это поля +0x12/+0x14 (клетка), +0x13/+0x15 (куда идёт),
// +0x16 (занятие), +0x10 (кого бьёт), +0x17 (поза), +0x18 (направление),
// +0x19 (стойка), +0x1B (сторона), +0x4E (здоровье), +0x52 (отрава).
// Буфер шагов +0x00 не храним намеренно: путь перестроится из занятия и
// клетки назначения, а в сейве от него пользы нет.
//: Пометка игрока в поле цели: своего `id` у героя нет, он живёт вне списка.
const HERO_MARK = "hero";

function packFoe(unit) {
  return {
    id: unit.id ?? null,
    slot: unit.slot ?? 0,
    side: unit.side ?? 0,
    cell: unit.cell ? { ...unit.cell } : null,
    x: unit.x, y: unit.y,
    direction: unit.direction ?? 6,
    pose: unit.pose ?? "stand",
    stance: unit.stance ?? "peace",
    health: unit.health ?? null,
    alive: unit.alive !== false,
    poison: unit.poison ?? 0,
    orderByte: unit.orderByte ?? 0,
    orderRow: unit.orderRow ?? null,
    orderCol: unit.orderCol ?? null,
    // Кого бьёт (+0x10) — по `id`, ссылками сейв не хранит. У движка игрок —
    // такой же юнит с номером записи, а у нас он живёт отдельно и `id` не
    // имеет вовсе; поэтому ему отдельная пометка. Без неё терялся ровно тот
    // случай, ради которого всё и затевалось: «за мной гонятся».
    target: unit.target ? (unit.target === hero ? HERO_MARK : unit.target.id ?? null) : null,
    workRest: unit.workRest ?? 0,
    ally: Boolean(unit.ally),
  };
}

//: Разложить обратно. Юниты к этому мигу уже расставлены картой, ищем по id.
function applyFoes(saved) {
  for (const record of saved ?? []) {
    const unit = units.find((live) => live.id != null && live.id === record.id);
    if (!unit) continue;
    if (record.cell) unit.cell = { ...record.cell };
    if (Number.isFinite(record.x)) unit.x = record.x;
    if (Number.isFinite(record.y)) unit.y = record.y;
    unit.direction = record.direction ?? unit.direction;
    unit.pose = record.pose ?? unit.pose;
    unit.frame = 0;
    unit.frameTime = 0;
    unit.stance = record.stance ?? unit.stance;
    if (record.health != null) unit.health = record.health;
    unit.alive = record.alive !== false;
    unit.poison = record.poison ?? 0;
    if (Number.isFinite(record.side)) unit.side = record.side;
    unit.orderByte = record.orderByte ?? 0;
    unit.orderKind = (record.orderByte ?? 0) & 0x0F;
    if (record.orderRow != null) unit.orderRow = record.orderRow;
    if (record.orderCol != null) unit.orderCol = record.orderCol;
    unit.workRest = record.workRest ?? 0;
    if (record.ally) unit.ally = true;
    // Путь перестроится сам: держать его в сейве незачем, а вот стоячие
    // остатки прошлого хода мешают — юнит поехал бы к старой клетке.
    // ПУСТОЙ СПИСОК, А НЕ null: буфер шагов у движка всегда есть (+0x00,
    // пустой помечается 0xFF), и весь тик ходьбы читает `path.length` без
    // оглядки. С `null` первый же кадр падал на «Cannot read length of null».
    unit.path = [];
    unit.step = null;
    unit.moving = false;
  }
  // Цели ставим ВТОРЫМ проходом: тот, кого бьют, мог сам ещё не найтись.
  const byId = new Map(units
    .filter((unit) => unit?.id != null)
    .map((unit) => [unit.id, unit]));
  byId.set(HERO_MARK, hero);
  for (const record of saved ?? []) {
    if (!record.target) continue;
    const unit = units.find((live) => live.id != null && live.id === record.id);
    if (unit) unit.target = byId.get(record.target) ?? null;
  }
  return true;
}

function applyActor(actor, saved) {
  if (!actor || !saved) return;
  // Сторона (+0x1B) — часть записи юнита, и она меняется в игре: наём
  // переписывает её на сторону игрока. Без восстановления нанятый после
  // загрузки снова оказывался чужим.
  if (Number.isFinite(saved.side)) actor.side = saved.side;
  // ОБЛИК ВОССТАНАВЛИВАЕТСЯ. В движке форма тела (+0xFC), палитра (+0x2E) и
  // лицо (+0xEF) — поля самой записи юнита, и сейв пишет её целиком, поэтому
  // рассинхронизироваться там нечему. `packActor` эти поля клал давно, а
  // `applyActor` их не читал: после загрузки внешность заново выводилась из
  // шаблона, и своя Велиславна продолжалась Ратибором.
  if (Number.isFinite(saved.body)) actor.body = saved.body;
  if (Number.isFinite(saved.palette)) actor.palette = saved.palette;
  if (Number.isFinite(saved.face)) actor.face = saved.face;
  //: МЕТКА ИГРЫ ИЗ СЕЙВА НЕ ЧИТАЕТСЯ — даже если старое сохранение её
  //: несёт. Она производная: герою её даёт шаблон мира (progressSetup до
  //: applySave), юниту — пак его карты. Чтение отсюда возвращало залипший
  //: «legend» канонному герою из сейвов, записанных до правки progress.js:
  //: жалоба «сначала аватарки нормальные, а потом обратно палатка».
  if (Number.isFinite(saved.breed)) actor.breed = saved.breed;
  if (saved.cell) actor.cell = { ...saved.cell };
  if (Number.isFinite(saved.x)) actor.x = saved.x;
  if (Number.isFinite(saved.y)) actor.y = saved.y;
  actor.direction = saved.direction ?? actor.direction;
  actor.stance = saved.stance ?? actor.stance;
  if (saved.health != null) actor.health = saved.health;
  if (saved.maxHealth != null) actor.maxHealth = saved.maxHealth;
  actor.experience = saved.experience ?? actor.experience;
  actor.nextLevel = saved.nextLevel ?? actor.nextLevel;
  actor.freeExperience = saved.freeExperience ?? actor.freeExperience;
  actor.level = saved.level ?? actor.level;
  actor.money = saved.money ?? actor.money;
  actor.reputation = saved.reputation ?? actor.reputation ?? 0;
  if (saved.equipment) actor.equipment = { ...saved.equipment };
  if (saved.bag) actor.bag = [...saved.bag];
  if (saved.enchant) actor.enchant = { ...saved.enchant };
  if (saved.bagEnchant) actor.bagEnchant = { ...saved.bagEnchant };
  if (saved.bagStrength) actor.bagStrength = { ...saved.bagStrength };
  if (saved.bagCount) actor.bagCount = { ...saved.bagCount };
  if (saved.bagPoison) actor.bagPoison = { ...saved.bagPoison };
  actor.itemOiled = { ...(saved.itemOiled ?? {}) };
  if (saved.wear) actor.wear = { ...saved.wear };
  if (saved.wearMax) actor.wearMax = { ...saved.wearMax };
  if (saved.poisonOn) actor.poisonOn = { ...saved.poisonOn };
  actor.poison = saved.poison ?? actor.poison ?? 0;
  actor.ammoCount = saved.ammoCount ?? actor.ammoCount ?? null;
  actor.ammoPoison = saved.ammoPoison ?? actor.ammoPoison ?? 0;
  actor.rangedMode = saved.rangedMode ?? actor.rangedMode ?? false;
  if (saved.skills) actor.skills = saved.skills;
  if (saved.characteristics) actor.characteristics = saved.characteristics;
  // Базовые ставим ПОСЛЕ текущих и только из сейва: progressSetup при входе
  // на карту пересобирает их из шаблона, и без этой строки купленные очки
  // теряются на первом же зелье.
  if (saved.baseCharacteristics) actor.baseCharacteristics = saved.baseCharacteristics;
  // Спрятанные восстанавливаем ровно как были: их отсутствие означает, что
  // временного зелья на герое не было, и поле должно остаться пустым.
  actor.savedCharacteristics = saved.savedCharacteristics ?? null;
  actor.potionTicks = saved.potionTicks ?? 0;
  actor.progressLock = saved.progressLock ?? false;
  // тумблеры окна персонажа (биты +0x19)
  actor.weaponLock = saved.weaponLock ?? false;
  actor.defendLeader = saved.defendLeader ?? false;
  actor.healTrigger = saved.healTrigger ?? 0;
  if (saved.look !== undefined) actor.look = saved.look;
  actor.flags = saved.flags ?? actor.flags ?? 0;
  if (saved.stats) actor.stats = { ...actor.stats, ...saved.stats };
  actor.orderByte = saved.orderByte ?? 0;
  // Приказ и начатый шаг не переносим: игрок продолжает с места, стоя.
  actor.orderKind = 0;
  actor.orderTarget = null;
  actor.path = [];
  actor.step = null;
  actor.goal = null;
  // СМЕРТЬ — ПОСЛЕДНЕЙ, поверх всего: расстановка подняла спутника живым
  // (`alive: true` там безусловно), и вернуть ему бит смерти надо после
  // того, как разложены здоровье и снаряжение. Порядок тот же, что у чужих
  // в applyFoes. Старые сейвы поля не несут — `!== false` оставляет их
  // живыми, как было.
  actor.alive = saved.alive !== false;
  if (!actor.alive) {
    actor.pose = saved.pose ?? actor.pose;
    actor.frame = 0;
    actor.frameTime = 0;
    actor.moving = false;
    //: Исчезающее тело клетки не занимает (VA 0x416A15).
    if (saved.hidden) { actor.hidden = true; actor.cell = null; }
  }
}

export function saveState(mapNumber) {
  // СНИМОК ТЕКУЩЕЙ КАРТЫ — ДО УПАКОВКИ ПАМЯТИ КАРТ. Движок пишет массив
  // юнитов целиком (VA 0x423CB8), поэтому сейв, снятый стоя на карте, не
  // теряет ничего. Наша память карты снималась только при УХОДЕ, и сейв на
  // карте нёс устаревший (или пустой) снимок её жителей: после загрузки
  // ушедший квестодатель воскресал из пака с квестом (Микула, Никифор), а
  // мешок торговца-нежителя откатывался (волхв карты 17). villagePack так
  // уже делает — зовёт villageCapture первым.
  mapStateCapture(mapNumber, units, loot);
  return {
    // 3: добавлены поселение, постройки, бродячие отряды и недостающие
    // поля записи юнита. Старые сейвы читаются: всё новое необязательно.
    // 4: мировой такт `ticks` и свежий снимок текущей карты в mapState.
    version: 4,
    map: mapNumber ?? null,
    // АРХЕТИП ЖИВЁТ В СЕЙВЕ, а не в localStorage. В движке он — байт записи
    // героя (+0xFC), запись целиком уходит в сохранение, и другого источника
    // нет: по нему же движок открывает GAME.<N>. Пока номер мира хранился
    // отдельно, загрузка собирала героя из ИСПЕЧЁННОГО В ПАК шаблона мира 0,
    // показывала Ратибора и лишь потом подменяла его сохранённым обликом —
    // отсюда и «два экземпляра героя».
    world: hero.data?.template?.world ?? null,
    //: У своего персонажа мир чужой, поэтому его самого узнаём по слоту:
    //: без этого загрузка сейва поднимала бы канонного героя того же мира.
    slot: hero.data?.template?.slot ?? null,
    // ЗАПИСЬ ОТРЯДА ЦЕЛИКОМ. Движок сохраняет блок отрядов и блок юнитов
    // целиком, поэтому наём переживает загрузку сам собой: боец лежит в
    // срезе отряда игрока. У нас срез — это `party.members`, и без него
    // нанятый пропадал при перезагрузке: расстановка карты берёт список из
    // пака, а там его нет.
    party_members: hero.party?.members ?? null,
    clock: daylight.time,
    // МИРОВОЙ ТАКТ — наш `0x84962C`. Движок пишет его в сейв первым же
    // блоком (VA 0x423CB8:22) и восстанавливает при загрузке (0x4236E0:36).
    // В его единицах живут метки отрастания грядок (pile.regrowAt): без
    // него каждый запуск страницы начинал счёт с нуля, разность
    // `clock.ticks - regrowAt` уходила глубоко в минус, и сорванная трава
    // не отрастала никогда.
    ticks: clock.ticks,
    hero: packActor(hero),
    // Спутники — своим упаковщиком: у них есть мешок, навыки и нажитое.
    party: units.filter((unit) => unit.ally).map(packActor),
    // ЧУЖИЕ ЮНИТЫ И ФЛАГИ ОТРЯДОВ. Здесь стояло «чужих карта расставит сама»,
    // и это прямо против движка: сейв пишет память БЛОКАМИ (VA 0x423CB8), и
    // среди них весь массив юнитов `0x7B3C08` размером 0x7D000 — две тысячи
    // записей по 0x100 — и весь массив отрядов `0x71E56C` (0xC800, двести
    // записей). То есть сохраняется ВСЁ: где стоит враг, куда он шёл, кого
    // бьёт, сколько у него здоровья, и поднят ли у отряда флаг боя `+0x1D`
    // с флагами войны `+0x1E`/`+0x1F`. Порт же расставлял чужих заново из
    // пака — и погоня после загрузки распадалась: преследователи возвращались
    // по своим местам и забывали про игрока.
    foes: units.filter((unit) => !unit.ally).map(packFoe),
    warbands: warbandsPack(),
    // Что уже подобрано: храним, каких куч БОЛЬШЕ НЕТ.
    lootTaken: (world.map?.loot ?? [])
      .map((entry) => entry.id)
      .filter((id) => id != null && !loot.some((pile) => pile.id === id)),
    // В оригинале сохраняется вся таблица куч. Это нужно и при частично
    // разобранной куче: оставшиеся экземпляры несут собственные поля.
    // Упаковщик кучи ОДИН и живёт в памяти карт: здесь была вторая копия с
    // перечислением полей руками, и она отставала — теряла «спрятана» (тайник
    // после загрузки оказывался на виду) и пару «зона, гнездо» (сундук
    // становился обычной кучей на полу).
    loot: loot.map(packPile),
    quests: [...dialog.quests.entries()],
    // Биты «подойди и заговори» — часть ТОГО ЖЕ блока состояний (0x6A50E8),
    // который движок пишет в сейв целиком (0x423CB8). Без них сохранение
    // взводило бы сюжетные встречи заново: пятеро из шести гасят свой бит
    // действием 61, и после загрузки они снова кидались бы к игроку.
    //: Только ПРАВКИ набора «подойди и заговори». Сам набор — из пака
    //: (см. dialog.approachEdits): плоский список пережил бы правку
    //: данных и вернул отменённое.
    approachEdits: [...dialog.approachEdits],
    flags: [...dialog.flags.entries()],
    // ПОСЕЛЕНИЕ. Движок пишет весь блок поселений целиком (0x83D408, 0x378C
    // байт), а здесь — те поля, которые игра меняет: залог и прочие флаги
    // +0x49C, статус +0x49D, владелец +0x4A0, казна +0x0C и доход владения
    // +0x10, плюс живой заказ мастерской. Без этого повторный залог давал
    // +1000 за каждый цикл «заложить — перезагрузиться»: бит 0x20 слетал, а
    // деньги оставались.
    village: village.data ? {
      flags: village.data.flags ?? 0,
      status: village.data.status ?? 0,
      owner: village.data.owner ?? 0,
      owned: village.data.owned ?? 0,
      treasury: village.data.treasury ?? 0,
      incomeStamp: village.incomeStamp ?? 0,
      // Заказ кузницы и часы варки живут на самой записи поселения
      // (shops.js), как движковые +0x49F/+0x08 и +0x04.
      forgeOrder: village.data.forgeOrder ?? -1,
      forgeLeft: village.data.forgeLeft ?? 0,
      brewTimer: village.data.brewTimer ?? null,
      brewTokens: village.data.brewTokens ? [...village.data.brewTokens] : null,
      lastTime: village.lastTime ?? null,
      // ДОЛЖНОСТИ (+0x3D0, пять слов) и СЧЁТЧИК ОТРЯДА ДЕРЕВНИ (+0x1C).
      // Первое ставит действие 74, второе растёт при каждом «Останься
      // здесь» (0x4338B0) и решает, примут ли следующего. Без них
      // назначенный староста и оставленный спутник откатывались бы
      // загрузкой, а место в деревне освобождалось само собой.
      officials: [...(village.data.officials ?? [])],
      squadPeople: village.data.squad_people ?? 0,
    } : null,
    // ВСЕ ПОСЕЛЕНИЯ, А НЕ ТОЛЬКО ЗДЕШНЕЕ. Движок пишет блок 0x83D408 целиком
    // (0x423CB8, 0x378C байт) — двенадцать записей разом, потому что деревня
    // живёт независимо от того, где сейчас игрок. Поле `village` выше
    // оставлено ради старых сохранений.
    villages: villagePack(),
    // ПОСТРОЙКИ: ступень и счётчик. Стройка, пожар и пепелище — состояние
    // мира, а не карты, и после загрузки не должны откатываться к тому, что
    // лежит в паке.
    buildings: (world.objects ?? [])
      .map((object, index) => (object?.states
        ? { index, state: object.state ?? 0, timer: object.timer ?? 0 }
        : null))
      .filter(Boolean),
    // БРОДЯЧИЕ ОТРЯДЫ глобальной карты: без них каждая загрузка объявляла
    // их мёртвыми.
    // ЧТО ПОМНЯТ КАРТЫ: пока только смерть. В движке такой памяти нет,
    // потому что записи юнитов лежат в массивах GAME.<N> и сохраняются
    // целиком; здесь юниты пересоздаются из пака, и без этого списка
    // зачищенная карта оживала бы при каждом возвращении.
    mapState: mapStatePack(),
    wandering: worldMap.wandering
      ? worldMap.wandering.map((record) => ({ ...record })) : null,
    worldMap: {
      cells: worldMap.cells ? worldMap.cells.map((row) => row.slice()) : null,
      // Угол сетки внутри картинки: по нему загрузка узнаёт, на канонной
      // карте сохранялись или на расширенной, и пересчитывает место отряда.
      // У сохранений, сделанных до расширения, его нет — там канонный.
      origin: worldMap.rules?.origin ? [...worldMap.rules.origin] : null,
      x: worldMap.x, y: worldMap.y, onMap: worldMap.onMap,
      // Корабельное право (0x84960C): движок пишет его в сейв четырьмя
      // байтами (0x4236E0), иначе после загрузки с корабля не уплыть.
      ship: worldMap.ship ?? 0,
      // ЧТО ИГРОК УЗНАЛ О МЕСТАХ — наш `0x8442A0`. Туман над значком и знание
      // имени в движке ставятся вместе (0x436908), но живут порознь, поэтому
      // и сохранять надо оба: без этого после загрузки все места снова
      // становятся «Неизвестное место».
      known: knownPack(),
    },
  };
}

// ПРИГОДЕН ЛИ СЕЙВ. Пока пак собирался без hero.template (регрессия Б1),
// бут заводил героя-пустышку — навыки нулями, характеристики по 10,
// здоровье 600 из DEFAULT_STATS — и самосохранение КРЕПИЛО её в хранилище.
// Дальше пустышка жила сама: applySave затирал ею настоящего героя, а
// каждый вход в карту пересохранял. Поэтому одна и та же проверка стоит на
// обеих дверях: и перед записью, и при чтении.
//
// Отпечаток меряется ПРОТИВ шаблона пака, а не константами: навыки в игре
// не опускаются, поэтому «все нули» при ненулевых навыках шаблона — это не
// «слабый герой», а герой, собранный вовсе без шаблона.
export function saveUsable(saved) {
  if (!saved || typeof saved !== "object") return false;
  if (!Number.isFinite(Number(saved.map))) return false;
  const actor = saved.hero;
  if (!actor) return false;
  // Мёртвого или несобранного героя (health null — packActor успел раньше
  // combatSetup) сохранять и применять нельзя: боту не с чего продолжать.
  if (!(actor.health > 0)) return false;
  const template = shared.hero?.template ?? null;
  const skills = Array.isArray(actor.skills) ? actor.skills : null;
  if (template && skills?.length && skills.every((value) => !value) &&
      Object.values(template.skills ?? {}).some((value) => value > 0)) {
    return false;
  }
  return true;
}

export function saveGame(mapNumber) {
  // Герой ещё не собран из шаблона — писать нечего: такой автосейв и
  // закрепил пустышку Б1. Шаблон приезжает в shared.json и подмешивается в
  // hero.data при loadMap, поэтому его отсутствие — признак недогруза.
  if (!hero.data?.template) {
    console.warn("сохранение пропущено: герой ещё без шаблона пака");
    return false;
  }
  const state = saveState(mapNumber);
  if (!saveUsable(state)) {
    console.warn("сохранение пропущено: состояние не прошло проверку", state);
    return false;
  }
  return savePut(state);
}

// Положить ГОТОВОЕ состояние в слот «Продолжить» — тот же путь записи, что
// у saveGame, только состояние собирает вызывающий. Нужен респавну
// (respawn.js): он кладёт якорный сейв с перенесёнными деньгами и сумкой,
// и перезагрузка подхватывает его обычной дорогой загрузки.
export function savePut(state) {
  if (!saveUsable(state)) {
    console.warn("запись пропущена: состояние не прошло проверку", state);
    return false;
  }
  const text = JSON.stringify(state);
  // ЗАПАСНАЯ КОПИЯ ПЕРЕД ЗАПИСЬЮ. Хранилище одно, и неудачная запись сверху
  // прежде оставляла игрока вообще без сохранения. Теперь предыдущее уходит
  // во второй ключ, и одна сорвавшаяся запись больше не стоит всей партии.
  try {
    const прежнее = localStorage.getItem(KEY);
    if (прежнее && прежнее !== text) localStorage.setItem(BACKUP, прежнее);
  } catch { /* места нет — тем важнее записать САМО сохранение, идём дальше */ }
  try {
    localStorage.setItem(KEY, text);
    saveTrouble = null;
    return true;
  } catch (error) {
    // МОЛЧА ТЕРЯТЬ СОХРАНЕНИЕ НЕЛЬЗЯ. Здесь стояло только `console.warn`, и
    // игрок ни о чём не узнавал: жмёшь «сохранить», тебе ничего не говорят, а
    // записи нет. Хранилище могло быть переполнено, данные сайта запрещены,
    // окно открыто в приватном режиме — причин много, и все молчаливые.
    saveTrouble = describeTrouble(error);
    console.warn("сохранить не вышло:", error);
    world.onSaveTrouble?.(saveTrouble);
    return false;
  }
}

//: Последняя беда с записью — её показывает меню. Пусто, пока всё хорошо.
let saveTrouble = null;
function describeTrouble(error) {
  const имя = error?.name || "";
  if (имя === "QuotaExceededError" || имя === "NS_ERROR_DOM_QUOTA_REACHED") {
    return "хранилище браузера переполнено — сохранение НЕ записано";
  }
  if (имя === "SecurityError") {
    return "браузер запретил данные сайта — сохранение НЕ записано "
      + "(приватное окно или блокировка хранилища)";
  }
  return `сохранение НЕ записано: ${error?.message || имя || "неизвестная беда"}`;
}

export function savedGame() {
  try {
    let text = localStorage.getItem(KEY);
    // ОСНОВНОЕ ИСПОРЧЕНО ИЛИ ПРОПАЛО — БЕРЁМ ЗАПАСНОЕ. Прежде такая пропажа
    // означала конец партии; теперь у нас есть копия предыдущей записи, и
    // терять всё из-за одной сорвавшейся записи больше не нужно.
    if (!usableText(text)) {
      const запас = localStorage.getItem(BACKUP);
      if (usableText(запас)) {
        console.warn("основное сохранение не годится — беру запасную копию");
        world.onSaveTrouble?.("основное сохранение пропало, "
          + "загружена предыдущая запись");
        text = запас;
      }
    }
    const saved = text ? JSON.parse(text) : null;
    if (saved && !saveUsable(saved)) {
      // Не удаляем сами: бут, не получив сейва, доедет до конца и запишет
      // поверх НАСТОЯЩЕГО героя — хранилище выздоравливает без ручной чистки.
      console.warn("сохранение отброшено: герой-пустышка без шаблона (Б1)");
      return null;
    }
    return saved;
  } catch (error) {
    console.warn("сохранение не читается:", error);
    return null;
  }
}

//: Для самопроверки: лежит ли в хранилище сейв и проходит ли он проверку.
export function saveHealth() {
  try {
    const text = localStorage.getItem(KEY);
    if (!text) return { present: false, usable: null };
    return { present: true, usable: saveUsable(JSON.parse(text)) };
  } catch {
    return { present: true, usable: false };
  }
}

function usableText(text) {
  if (!text) return false;
  try { return saveUsable(JSON.parse(text)); } catch { return false; }
}

// Разложить сохранение по уже загруженной карте. Карту переключает тот, кто
// зовёт: здесь только состояние.
export function applySave(saved) {
  if (!saved) return false;
  applyActor(hero, saved.hero);
  hero.moving = false;
  for (const mate of saved.party ?? []) {
    // Сперва среди своих, потом СРЕДИ ВСЕХ. Нанятый разговором житель
    // (обработчик 36 ставит unit.ally) на новой карте поднимается обычным
    // жителем с ally = false, и поиск только по ally его не находил —
    // запись из сейва молча выбрасывалась, а рекрут оставался в деревне со
    // старым диалогом и без нажитого. В движке наём переживает загрузку
    // сам собой: он дописывает запись в срез отряда игрока, а блоки отрядов
    // и юнитов сохраняются целиком.
    //
    // Ищем по id — он у юнита стабилен; slot и имя берём запасными, как и
    // раньше, но только среди своих: у чужих они не уникальны.
    const live = units.find((unit) => unit.id != null && unit.id === mate.id)
      ?? units.find((unit) => unit.ally &&
        (unit.slot === mate.slot || unit.name === mate.name));
    if (!live) continue;
    applyActor(live, mate);
    // Найденный вне отряда — это и есть нанятый: возвращаем ему сторону и
    // признак своего, иначе он останется чужим и снова заговорит о найме.
    live.ally = true;
    live.side = mate.side ?? hero.side ?? live.side;
    live.hostile = false;
  }
  // ЧУЖИЕ — ПОСЛЕ СВОИХ. Порядок не косметика: цель врага может указывать на
  // спутника, а тот к этому мигу должен быть уже разложен. Флаги отрядов
  // поднимаем следом: на них смотрит и рассудок твари (гейт `+0x1D` в
  // 0x410010), и удержание боя.
  applyFoes(saved.foes);
  warbandsApply(saved.warbands);
  if (Array.isArray(saved.loot)) {
    loot.splice(0, loot.length, ...saved.loot.map((pile) => ({
      ...pile,
      items: [...(pile.items ?? [])],
      details: (pile.details ?? []).map((detail) => ({ ...(detail ?? {}) })),
      enchant: [...(pile.enchant ?? [])],
      cell: pile.cell ? { ...pile.cell } : null,
    })));
    // Разговорные деревья куч — данные пака, в сейве их нет и не будет:
    // подшиваются заново по id (loot.js, lootReattachTalk).
    lootReattachTalk(world.map);
  } else {
    // Совместимость с v1: там хранились только полностью исчезнувшие кучи.
    const taken = new Set(saved.lootTaken ?? []);
    for (let i = loot.length - 1; i >= 0; i -= 1) {
      if (taken.has(loot[i].id)) loot.splice(i, 1);
    }
  }
  // СТАРЫЕ СОХРАНЕНИЯ: донорские квесты переехали со 128 на 152. База
  // считалась по занятым квестам канона (0…102), а индексом той же таблицы
  // служит НОМЕР РАЗГОВОРА, и канонных разговоров 151 — донорские заявки
  // ложились на канонных жителей. Ключ 128 и выше в сохранении может быть
  // только донорским: канон выше 102 не пишет ничего.
  const WAS_BASE = 128, NOW_BASE = 152, THEIR_LAST = 161;
  dialog.quests = new Map((saved.quests ?? []).map(([key, value]) => {
    const number = Number(key);
    const theirs = number >= WAS_BASE && number <= WAS_BASE + THEIR_LAST;
    return [theirs ? number - WAS_BASE + NOW_BASE : number, value];
  }));
  // НАБОР «ПОДОЙДИ И ЗАГОВОРИ» БЕРЁТСЯ ИЗ ПАКА, из сейва — только правки.
  // Прежде сохранялся весь набор целиком, и он затирал паковый: правка
  // данных до начатой игры не доезжала. Так Фёдора продолжала сама
  // заговаривать после того, как бит у неё сняли.
  //
  // У сейвов до этой правки списка правок нет, и восстановить его не из
  // чего: там лежал только итог. Такие сейвы получают паковый набор —
  // то есть разово теряют то, что успели навзводить действия 61 и 62.
  for (const [number, armed] of saved.approachEdits ?? []) {
    dialog.approachEdits.set(Number(number), Boolean(armed));
    if (armed) dialog.approach.add(Number(number));
    else dialog.approach.delete(Number(number));
  }
  dialog.flags = new Map(saved.flags ?? []);
  // Поселение: пишем прямо в блок пака — по нему и работают обработчики
  // разговора, казна и мастерская.
  if (saved.village && village.data) {
    village.data.flags = saved.village.flags ?? village.data.flags ?? 0;
    village.data.status = saved.village.status ?? village.data.status ?? 0;
    village.data.owner = saved.village.owner ?? village.data.owner ?? 0;
    village.data.owned = saved.village.owned ?? village.data.owned ?? 0;
    village.data.treasury = saved.village.treasury ?? village.data.treasury ?? 0;
    village.incomeStamp = saved.village.incomeStamp ?? village.incomeStamp ?? 0;
    if (Number.isFinite(saved.village.forgeOrder)) {
      village.data.forgeOrder = saved.village.forgeOrder;
    }
    if (Number.isFinite(saved.village.forgeLeft)) {
      village.data.forgeLeft = saved.village.forgeLeft;
    }
    if (Number.isFinite(saved.village.brewTimer)) {
      village.data.brewTimer = saved.village.brewTimer;
    }
    if (Array.isArray(saved.village.brewTokens)) {
      village.data.brewTokens = [...saved.village.brewTokens];
    }
    village.lastTime = saved.village.lastTime ?? null;
    if (Array.isArray(saved.village.officials)) {
      village.data.officials = [...saved.village.officials];
    }
    if (Number.isFinite(saved.village.squadPeople)) {
      village.data.squad_people = saved.village.squadPeople;
    }
  }
  //: Новый формат — все поселения разом; старый (`village`) разобран выше и
  //: описывает только ту деревню, где игрок сохранился.
  if (Array.isArray(saved.villages)) villageUnpack(saved.villages);
  // СТУПЕНЬ ИЗ СОХРАНЕНИЯ — НЕ ПРОСТО ЧИСЛО.
  //
  // Стройка меняет ступень через `buildingsTick`, и та делает ещё две
  // вещи: переставляет клетки постройки (`heroStampBuilding` — готовая
  // пускает внутрь, недострой стоит стеной) и ДОГРУЖАЕТ картинки новой
  // ступени. Карта тянет кадры только того состояния, в котором постройка
  // приехала из пака, и у казармы это пустая площадка.
  //
  // Здесь ступень ставилась голым присваиванием, и обе вещи пропускались.
  // Отсюда «построил, сохранил, загрузил — казармы нет»: в данных стоит
  // тройка, а картинок достроенной ступени никто не запрашивал, и
  // `buildingFrames` честно откатывался на плоскую площадку; клетки при
  // этом оставались стеной, и внутрь никто не заходил.
  const rebuilt = [];
  for (const entry of saved.buildings ?? []) {
    const object = (world.objects ?? [])[entry.index];
    if (!object?.states) continue;
    object.state = entry.state ?? object.state;
    object.timer = entry.timer ?? 0;
    rebuilt.push(object);
  }
  if (rebuilt.length) {
    const ready = world.map?.hero?.rules?.buildings?.states?.ready ?? 3;
    const assets = [];
    for (const object of rebuilt) {
      heroStampBuilding(object, ready);
      for (const frame of Object.values(object.states[String(object.state)] ?? {})) {
        if (frame?.asset) assets.push(frame.asset);
      }
    }
    //: Не ждём: до готовности картинок постройка рисуется прежними
    //: кадрами — ровно так же, как во время стройки.
    preload(assets);
  }
  if (Array.isArray(saved.mapState)) mapStateUnpack(saved.mapState);
  if (Array.isArray(saved.wandering)) {
    worldMap.wandering = saved.wandering.map((record) => ({ ...record }));
  }
  // Сетка раскладывается ЧЕРЕЗ cellsRestore, а не присваиванием: размер
  // карты мира зависит от того, канон в паке или расширение, и старое
  // сохранение надо вложить на место канона, а не класть с нулевого угла.
  if (saved.worldMap?.cells) cellsRestore(saved.worldMap.cells);
  if (Array.isArray(saved.worldMap?.known)) knownUnpack(saved.worldMap.known);
  // Через placeAt, а не полем: клетка отряда ВЫВОДИТСЯ из точки, и ставить
  // её отдельно нельзя — разъедутся. А выводится она по правилам сетки,
  // которые появляются только в worldMapSetup — boot применяет сохранение
  // раньше, чем заводит карту, поэтому сетку заводим здесь же, как standAt.
  // Клетки из сохранения уже разложены выше: setup их не перетирает.
  if (Number.isFinite(saved.worldMap?.x) && worldMapSetup()) {
    // Место отряда — в пикселях КАРТИНКИ, а картинки у канона и расширения
    // разные: пересчитываем по углу, записанному вместе с сохранением.
    const point = pointRestore(saved.worldMap.x, saved.worldMap.y,
                               saved.worldMap.origin ?? null);
    placeAt(point.x, point.y);
  }
  worldMap.onMap = Boolean(saved.worldMap?.onMap);
  // Старые сохранения права не знают — у них корабля нет (ноль движка).
  worldMap.ship = Number.isFinite(saved.worldMap?.ship)
    ? saved.worldMap.ship : 0;
  if (Number.isFinite(saved.clock)) daylight.time = saved.clock;
  // Мировой такт — тем же движением: с ним сравниваются метки грядок.
  // Бут восстанавливает его и РАНЬШЕ, до lootSetup (см. boot), но пути
  // загрузки бывают разные, и контракт «упаковано — восстанавливается»
  // держит эта строка.
  if (Number.isFinite(saved.ticks)) clock.ticks = saved.ticks;
  return true;
}
