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
import { hero } from "./hero.js";
import { units } from "./units.js";
import { loot } from "./loot.js";
import { dialog } from "./dialog.js";
import { daylight } from "./daylight.js";
import { village } from "./village.js";
import { placeAt, worldMap, worldMapSetup } from "./worldmap.js";
import { mapStatePack, mapStateUnpack } from "./mapstate.js";

const KEY = "knyaz2.save.v1";

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
    health: actor.health ?? null,
    maxHealth: actor.maxHealth ?? null,
    experience: actor.experience ?? 0,
    nextLevel: actor.nextLevel ?? 0,
    freeExperience: actor.freeExperience ?? 0,
    level: actor.level ?? 1,
    money: actor.money ?? 0,
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
  };
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
}

export function saveState(mapNumber) {
  return {
    // 3: добавлены поселение, постройки, бродячие отряды и недостающие
    // поля записи юнита. Старые сейвы читаются: всё новое необязательно.
    version: 3,
    map: mapNumber ?? null,
    // АРХЕТИП ЖИВЁТ В СЕЙВЕ, а не в localStorage. В движке он — байт записи
    // героя (+0xFC), запись целиком уходит в сохранение, и другого источника
    // нет: по нему же движок открывает GAME.<N>. Пока номер мира хранился
    // отдельно, загрузка собирала героя из ИСПЕЧЁННОГО В ПАК шаблона мира 0,
    // показывала Ратибора и лишь потом подменяла его сохранённым обликом —
    // отсюда и «два экземпляра героя».
    world: hero.data?.template?.world ?? null,
    // ЗАПИСЬ ОТРЯДА ЦЕЛИКОМ. Движок сохраняет блок отрядов и блок юнитов
    // целиком, поэтому наём переживает загрузку сам собой: боец лежит в
    // срезе отряда игрока. У нас срез — это `party.members`, и без него
    // нанятый пропадал при перезагрузке: расстановка карты берёт список из
    // пака, а там его нет.
    party_members: hero.party?.members ?? null,
    clock: daylight.time,
    hero: packActor(hero),
    // Спутники: только свои, чужие юниты карта расставит сама.
    party: units.filter((unit) => unit.ally).map(packActor),
    // Что уже подобрано: храним, каких куч БОЛЬШЕ НЕТ.
    lootTaken: (world.map?.loot ?? [])
      .map((entry) => entry.id)
      .filter((id) => id != null && !loot.some((pile) => pile.id === id)),
    // В оригинале сохраняется вся таблица куч. Это нужно и при частично
    // разобранной куче: оставшиеся экземпляры несут собственные поля.
    loot: loot.map((pile) => ({
      id: pile.id ?? null,
      items: [...(pile.items ?? [])],
      details: (pile.details ?? []).map((detail) => ({ ...(detail ?? {}) })),
      enchant: [...(pile.enchant ?? [])],
      money: pile.money ?? 0,
      x: pile.x, y: pile.y,
      cell: pile.cell ? { ...pile.cell } : null,
      taken: pile.taken ?? false,
    })),
    quests: [...dialog.quests.entries()],
    // Биты «подойди и заговори» — часть ТОГО ЖЕ блока состояний (0x6A50E8),
    // который движок пишет в сейв целиком (0x423CB8). Без них сохранение
    // взводило бы сюжетные встречи заново: пятеро из шести гасят свой бит
    // действием 61, и после загрузки они снова кидались бы к игроку.
    approach: [...dialog.approach],
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
      order: village.order ?? -1,
      timer: village.timer ?? 0,
      stock: { ...(village.stock ?? {}) },
      lastTime: village.lastTime ?? null,
    } : null,
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
      x: worldMap.x, y: worldMap.y, onMap: worldMap.onMap,
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
  try {
    localStorage.setItem(KEY, JSON.stringify(state));
    return true;
  } catch (error) {
    console.warn("сохранить не вышло:", error);
    return false;
  }
}

export function savedGame() {
  try {
    const text = localStorage.getItem(KEY);
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

export function hasSave() { return Boolean(savedGame()); }

export function dropSave() {
  try { localStorage.removeItem(KEY); return true; } catch { return false; }
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
  if (Array.isArray(saved.loot)) {
    loot.splice(0, loot.length, ...saved.loot.map((pile) => ({
      ...pile,
      items: [...(pile.items ?? [])],
      details: (pile.details ?? []).map((detail) => ({ ...(detail ?? {}) })),
      enchant: [...(pile.enchant ?? [])],
      cell: pile.cell ? { ...pile.cell } : null,
    })));
  } else {
    // Совместимость с v1: там хранились только полностью исчезнувшие кучи.
    const taken = new Set(saved.lootTaken ?? []);
    for (let i = loot.length - 1; i >= 0; i -= 1) {
      if (taken.has(loot[i].id)) loot.splice(i, 1);
    }
  }
  dialog.quests = new Map(saved.quests ?? []);
  // Старые сейвы битов подхода не знают: там их поле отсутствует, и в этом
  // случае оставляем те, что завёл questsReset из пака, — иначе сюжетные
  // встречи пропали бы совсем.
  if (Array.isArray(saved.approach)) dialog.approach = new Set(saved.approach);
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
    village.order = saved.village.order ?? -1;
    village.timer = saved.village.timer ?? 0;
    village.stock = { ...(saved.village.stock ?? {}) };
    village.lastTime = saved.village.lastTime ?? null;
  }
  for (const entry of saved.buildings ?? []) {
    const object = (world.objects ?? [])[entry.index];
    if (!object?.states) continue;
    object.state = entry.state ?? object.state;
    object.timer = entry.timer ?? 0;
  }
  if (Array.isArray(saved.mapState)) mapStateUnpack(saved.mapState);
  if (Array.isArray(saved.wandering)) {
    worldMap.wandering = saved.wandering.map((record) => ({ ...record }));
  }
  if (saved.worldMap?.cells) worldMap.cells = saved.worldMap.cells.map((r) => r.slice());
  // Через placeAt, а не полем: клетка отряда ВЫВОДИТСЯ из точки, и ставить
  // её отдельно нельзя — разъедутся. А выводится она по правилам сетки,
  // которые появляются только в worldMapSetup — boot применяет сохранение
  // раньше, чем заводит карту, поэтому сетку заводим здесь же, как standAt.
  // Клетки из сохранения уже разложены выше: setup их не перетирает.
  if (Number.isFinite(saved.worldMap?.x) && worldMapSetup()) {
    placeAt(saved.worldMap.x, saved.worldMap.y);
  }
  worldMap.onMap = Boolean(saved.worldMap?.onMap);
  if (Number.isFinite(saved.clock)) daylight.time = saved.clock;
  return true;
}
