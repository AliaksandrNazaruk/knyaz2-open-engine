// Хозяйство деревни: казна владения и мастерская.
//
// КАЗНА (VA 0x41D530…0x41D745, формула снята дизасмом). Раз в 0x2760
// единиц игрового времени и только при СНЯТОМ бите 0x10 во flags в казну
// владения капает доход — это поле +0x10 записи поселения, по ненулевости
// которого обработчик 27 отвечает «деревня чья-то» (VA 0x435438):
//
//     round(богатство · 50 · sqrt(навык «Управление деревней» ГЕРОЯ)
//           + жители · 10 + 1)
//
// порезанный делителем сетки «статус × байт-владелец» (усечение к нулю):
// статус 0 — /4 /2 /1, статус 1 — /8 /4 /2, статус 2 — /16 /8 /4.
//
// МАСТЕРСКАЯ (VA 0x417BD8, мировой такт зовёт её раз за тик). Мастер —
// юнит из +0x3D6, куёт по навыку «Кузнечное дело»: 39 видов — стрелы
// (классы 202…204), болты (206…207) и снаряжение культуры старейшины
// (класс = культура·34 + 100 + вид − 5). Порог доступности вида и
// прочность откованного — durability его класса; свободный вид с порогом
// не выше навыка берётся в заказ на срок
//
//     round(порог · 60 / sqrt(навык/10 + 1))          (fsqrt 0x442C6C)
//
// готовое лежит в запасе вида, после отковки мастер растёт: навык =
// round(sqrt(порог·2 + навык² + 10)), кап 100. Когда всё доступное
// отковано — раздача жителям жребием rand % 8 не меньше порога сетки
// статусов, и только пока на карте нет живого отряда события (0x435214):
// стрелы кладутся в пустой боеприпас стрелка, снаряжение — в слот вида,
// если тот пуст или защита класса хуже (старая вещь пропадает); требования
// проверяет 0x418648. Один предмет за такт, как и в движке.
import { shared, world } from "./world.js";
import { hero } from "./hero.js";
import { units } from "./units.js";
import { clock } from "./clock.js";
import { levelThreshold, raiseCharacteristic, raiseSkill } from "./progress.js";
import { placeStep } from "./buildings.js";
import { mapStateResidents } from "./mapstate.js";
import { roundHalfEven } from "./round.js";

export const village = {
  data: null,        // блок поселения из пака (map.village)
  incomeStamp: 0,    // метка последней выплаты (+0x14)
  order: -1,         // какой вид куётся (+0x49F), -1 — никакой
  timer: 0,          // тиков до готовности (+0x08)
  stock: {},         // запасы по видам (+0x44E): вид -> имя готовой вещи
  trainTimer: 0,     // тактов деревни до занятия у воеводы (+0x0C)
  lastTime: null,    // прошлое игровое время — для счёта тиков
  //: Сколько рук считалось на этой карте в последний раз. Движку такое поле
  //: не нужно — у него все юниты всех карт живут весь сеанс, и работников он
  //: пересчитывает по отряду поселения где угодно. У нас юниты чужих карт из
  //: памяти уходят, поэтому число запоминаем, пока мы там стоим.
  workers: 0,
};

function treasuryRules() {
  return world.map?.hero?.rules?.buildings?.treasury ?? null;
}

function workshopRules() {
  return world.map?.hero?.rules?.buildings?.workshop ?? null;
}

// СКЛАД ПОСЕЛЕНИЙ — на всю игру, а не на один вход.
//
// В движке массив поселений 0x83D408 (12 записей по 0x4A1) читается ОДИН РАЗ:
// при новой игре (0x43D898) или из сейва (0x4236E0) — и целиком пишется в сейв
// (0x423CB8). Вход на карту его НЕ перезагружает: 0x43DF48 лишь находит запись
// своей карты (байт +3 равен номеру карты) и по ней переставляет картинки
// объектов. У нас карта читается из пака при КАЖДОМ входе, и вместе с ней
// возвращалась нетронутая деревня — отсюда «в Борье пропали постройки и мой
// чувак, которого я оставил воеводой» в отчёте тестера.
const settlements = new Map();     // номер карты -> запись поселения и хозяйство
let current = null;                // чьё поселение сейчас живое

function mapNumber(map) {
  const number = Number(map?.legacy?.map_number);
  return Number.isFinite(number) ? number : null;
}

export function villageSetup(map) {
  const number = mapNumber(map);
  current = number;
  const kept = number === null ? null : settlements.get(number);
  // ЗАГЛУШКА ДОЖДАЛАСЬ СВОЕЙ ЗАПИСИ. Она поднялась из сейва без пака и
  // всё это время считала дань и стройку; теперь пришла настоящая запись
  // карты — со жителями, местами работы и прилавками, — а нажитое
  // заглушкой переливаем в неё. Порядок именно такой: пак даёт статику,
  // заглушка — то, что игра успела изменить.
  if (kept?.stub) {
    const packed = map?.village ?? null;
    kept.data = packed ? villageCarry(packed, kept.data) : kept.data;
    kept.stub = false;
    if (map) map.village = kept.data;
    Object.assign(village, kept);
    delete village.stub;
    return;
  }
  if (kept) {
    //: Вернулись на свою карту — берём СВОЮ запись, а копию из пака
    //: отставляем. Подменяем и `map.village`: на неё смотрят разговоры,
    //: торговля и постройки через `world.map.village`.
    if (map) map.village = kept.data;
    Object.assign(village, kept);
    return;
  }
  village.data = map?.village ?? null;
  village.incomeStamp = clock.ticks;
  //: Полей `order`/`timer`/`stock` больше нет: кузница живёт в shops.js и
  //: держит заказ на самой записи поселения (forgeOrder/forgeLeft) — как
  //: движок в полях +0x49F/+0x08 той же записи.
  village.trainTimer = 0;
  village.lastTime = null;
  if (number === null || !village.data) return;
  const entry = { ...village };
  settlements.set(number, entry);
  //: ПЕРВЫЙ ВИЗИТ ПОСЛЕ ЗАГРУЗКИ. Сохранение помнит деревни, куда игрок уже
  //: заходил, но их записи приезжают из пака только сейчас — вот и время
  //: наложить сохранённое. Без этого сейв восстанавливал лишь ту деревню,
  //: которая была загружена в память в миг загрузки.
  if (villageApply(number, entry)) Object.assign(village, entry);
}

// Уходим с карты — дописать в склад то, что изменилось за визит. Сама запись
// поселения (`data`) общая по ссылке и правится на месте, а хозяйство
// мастерской и метки живут полями, их надо переложить.
export function villageCapture() {
  if (current === null || !settlements.has(current)) return false;
  settlements.set(current, { ...village });
  return true;
}

// СТРОЙКА ИДЁТ И БЕЗ ИГРОКА — во всех поселениях сразу.
//
// В движке фаза деревень (0x41C944:356, раз в 16 тактов) проходит по ВСЕМ
// двенадцати записям массива 0x83D408 независимо от того, на какой карте
// стоит игрок: записи глобальны, а карта — только картинка над ними.
//
// У нас же такт ходил по объектам ТЕКУЩЕЙ карты, и стоило уйти из деревни,
// как её стройка замирала до возвращения. Тестер это и увидел: «стройка
// кузницы в Беглом встала». Теперь места чужих поселений тикают из склада —
// той же лестницей (`placeStep`), что и видимые.
//
// Текущее поселение здесь пропускаем: его места уже двигает buildingsTick
// через объекты карты, и второй проход считал бы такты дважды.
//: Возвращает НАБОР карт, где стройка сдвинулась: по этому же признаку
//: движок решает, будет ли в этой фазе учёба (0x41C944: `local_38`).
//: Изменилось ли что-нибудь вообще — спрашивать не надо: заочная фаза
//: всё равно идёт следом, и кадр она не рисует.
export function villageTickAway(hits = 1) {
  const set = world.map?.hero?.rules?.buildings;
  const built = new Set();
  if (hits < 1) return built;
  const kinds = set?.kinds ?? {};
  const now = clock.ticks;
  for (const [map, kept] of settlements) {
    if (map === current) continue;
    // КАЗНА ИДЁТ И ЗАОЧНО. В движке доход считается в том же цикле по всем
    // двенадцати записям и карты не спрашивает вовсе (VA 0x41C944 -> 0x41D559).
    // У нас он висел на «текущей деревне», и стоило уйти с её карты, как
    // дань переставала копиться — ровно то, на что жаловался тестер.
    //
    //: Жителей дальней деревни считать не по чему: её юнитов в памяти нет.
    //: Берём число, запомненное прошлым визитом (`workers` — им же считает
    //: стройка), а без визита — счётчик отряда поселения из записи.
    const people = kept.workers ?? kept.data?.squad_people ?? 0;
    treasuryFor(kept, now, people);
    if (!set?.states) continue;
    const places = kept.data?.buildings ?? [];
    if (!places.length) continue;
    for (const place of places) {
      const kind = kinds[String(place.kind)] ?? null;
      for (let hit = hits; hit > 0; hit -= 1) {
        if (!placeStep(place, kind, kept.workers ?? 0, set)) break;
        place.built = Boolean(place.state || place.timer);
        built.add(map);
      }
    }
  }
  return built;
}

// ДАЛЬНИЕ ПОСЕЛЕНИЯ: все, кроме той карты, где стоит игрок. Их хозяйство
// движок считает наравне со здешним (VA 0x41C944 идёт по всем двенадцати
// записям), поэтому список нужен наружу — им пользуется фаза в effects.js.
export function villagesAway() {
  return [...settlements.entries()].filter(([map]) => map !== current);
}

// КОМАНДА ПОСЕЛЕНИЯ — те, над кем работает его хозяйство: должностной варит
// и кует, воевода учит, кузница раздаёт откованное.
//
// В движке это всегда одно и то же — бойцы отряда поселения в общем массиве
// юнитов, где бы игрок ни стоял. У нас юниты живут только на текущей карте,
// а жители остальных лежат СНИМКАМИ в памяти карт (mapstate.js). Снимок —
// не подделка, а та же запись: именно из него житель и поднимается при
// следующем входе, и units.js применяет из снимка и навыки, и снаряжение, и
// прилавок. Поэтому заочная работа правит снимки, и нажитое видно на месте.
export function villageCrew(map) {
  if (map === current) return units;
  return [...mapStateResidents(map).values()];
}

// Должностной поселения по МЕСТУ в пятёрке +0x3D0 (VA 0x415190 отдаёт
// «место + 1», отсюда у знахаря роль 2, у кузнеца 4, у воеводы 5).
// Мёртвый и ушедший должности не несут.
export function villageOfficial(data, crew, post) {
  const slot = (data?.officials ?? [])[post] ?? 0;
  if (!slot) return null;
  const who = crew.find((unit) => unit?.slot === slot);
  if (!who || who.alive === false || who.removed) return null;
  return who;
}

// Всё, что игра изменила в поселениях, — для сейва. Движок пишет блок целиком
// (0x423CB8), мы пишем поля, которые вообще меняются.
export function villagePack() {
  villageCapture();
  return [...settlements.entries()].map(([map, kept]) => ({
    map,
    flags: kept.data?.flags ?? 0,
    status: kept.data?.status ?? 0,
    owner: kept.data?.owner ?? 0,
    owned: kept.data?.owned ?? 0,
    treasury: kept.data?.treasury ?? 0,
    officials: [...(kept.data?.officials ?? [])],
    squadPeople: kept.data?.squad_people ?? 0,
    // ПРИЛАВКИ — поля той же записи (`+0x3E0`, `+0x40E`, `+0x44E`), поэтому
    // и в сохранение они едут вместе с ней. Ключ — роль торговца, значение —
    // места и подробности выложенного (shops.js).
    counters: kept.data?.counters
      ? JSON.parse(JSON.stringify(kept.data.counters)) : null,
    // Ступень и счётчик каждого МЕСТА — это и есть стройка.
    //: ВИД ВОЗИМ ТОЖЕ. Заочная стройка идёт по лестнице вида (`placeStep`
    //: берёт из него сроки ступеней), а поселение, поднятое из сейва без
    //: визита, паковой записи ещё не видело — взять вид было неоткуда, и
    //: стройка там стояла.
    places: (kept.data?.buildings ?? []).map((place) => ({
      slot: place.slot, kind: place.kind, state: place.state ?? 0,
      timer: place.timer ?? 0, built: Boolean(place.built),
    })),
    incomeStamp: kept.incomeStamp ?? 0,
    trainTimer: kept.trainTimer ?? 0,
    lastTime: kept.lastTime ?? null,
    // Кузница и варка живут на самой записи поселения, как поля движка
    // +0x49F/+0x08 (заказ и срок) и +0x04 (часы варки) — едут с ней же.
    forgeOrder: kept.data?.forgeOrder ?? -1,
    forgeLeft: kept.data?.forgeLeft ?? 0,
    brewTimer: kept.data?.brewTimer ?? null,
    brewTokens: kept.data?.brewTokens ? [...kept.data.brewTokens] : null,
  }));
}

// Обратно в склад. Записи поселений сами приедут из пака при первом входе на
// карту, поэтому здесь держим отложенные правки и накладываем их тогда же.
const pending = new Map();

// СОСТОЯНИЕ ПОСЕЛЕНИЯ, ГДЕ ИГРОК ЕЩЁ НЕ БЫЛ.
//
// В движке блок записей загружен весь и с начала партии, поэтому разговор
// вправе спросить про дальнюю деревню — «Продолжение легенды» так и делает
// (его обработчик 35 ищет поселение по номеру карты среди двадцати,
// FUN_0043f670, и смотрит флаги). У нас же запись приезжала только вместе
// со своей картой, и про непосещённую ответить было нечем.
//
// Порядок такой: живая запись, если игрок туда заходил; иначе отложенная
// правка из сейва; иначе скалярное состояние из `shared.settlements`.
// Скалярное — потому что постройки и жители весят девять килобайт на запись
// и спрашивают их только на своей карте.
export function villageState(number) {
  const map = Number(number);
  if (!Number.isFinite(map)) return null;
  const live = settlements.get(map);
  if (live?.data) return live.data;
  const worldId = String(world.map?.hero?.template?.world ?? 0);
  const list = shared.settlements?.[worldId] ?? shared.settlements?.["0"] ?? [];
  const start = list.find((entry) => Number(entry?.map) === map) ?? null;
  if (!start) return null;
  const saved = pending.get(map);
  return saved ? { ...start, ...saved } : start;
}

// НОВАЯ ИГРА чистит склад целиком: в движке блок поселений перечитывается из
// GAME.x (0x43D898), то есть от прошлой партии не остаётся ничего.
export function villageReset() {
  settlements.clear();
  pending.clear();
  current = null;
}

export function villageUnpack(list) {
  pending.clear();
  for (const entry of list ?? []) {
    const number = Number(entry?.map);
    if (Number.isFinite(number)) pending.set(number, entry);
  }
  //: Загрузка заменяет ВЕСЬ блок поселений (0x4236E0 читает 0x378C байт), так
  //: что записи чужой партии в складе оставаться не должны.
  if (pending.size) {
    for (const number of [...settlements.keys()]) {
      if (!pending.has(number)) settlements.delete(number);
    }
  }
  //: Уже загруженные записи правим сразу — на текущей карте пак уже прочитан.
  for (const [number, kept] of settlements) villageApply(number, kept);
  // ПОСЕЛЕНИЯ ЖИВУТ С ЗАГРУЗКИ, А НЕ С ПЕРВОГО ВИЗИТА.
  //
  // Движок читает блок 0x83D408 целиком (0x4236E0) и с этого мига считает
  // все двенадцать записей каждую фазу. У нас запись приезжала только со
  // своей картой, и после загрузки в складе оставалась одна текущая: дань
  // в остальных не капала, стройка стояла — пока туда не зайдёшь.
  //
  // Поднимаем их прямо из сохранённого. Такая запись — заглушка: в ней
  // только то, что игра меняет, без жителей, мест работы и товара. Своей
  // паковой записи она дождётся при визите (villageSetup), а нажитое
  // заочно перейдёт в неё.
  for (const [number, saved] of pending) {
    if (settlements.has(number)) continue;
    settlements.set(number, villageStub(number, saved));
  }
  if (current !== null) {
    const kept = settlements.get(current);
    if (kept) Object.assign(village, kept);
  }
}

//: Скалярное состояние поселения из пака — по нему заглушка узнаёт
//: богатство и сторону, которых сейв не возит: игра их не меняет.
function villageStatic(number) {
  const worldId = String(world.map?.hero?.template?.world ?? 0);
  const list = shared.settlements?.[worldId] ?? shared.settlements?.["0"] ?? [];
  return list.find((entry) => Number(entry?.map) === Number(number)) ?? null;
}

//: Заглушка поселения из сохранённого: те же имена полей, что у паковой
//: записи, — чтобы её потом можно было перелить в настоящую одной функцией.
function villageStub(number, saved) {
  const base = villageStatic(number) ?? {};
  return {
    stub: true,
    data: {
      map: Number(number),
      wealth: base.wealth ?? 0, side: base.side, culture: base.culture ?? 0,
      flags: saved.flags ?? base.flags ?? 0,
      status: saved.status ?? base.status ?? 0,
      owner: saved.owner ?? base.owner ?? 0,
      owned: saved.owned ?? base.owned ?? 0,
      treasury: saved.treasury ?? base.treasury ?? 0,
      officials: [...(saved.officials ?? base.officials ?? [])],
      squad_people: saved.squadPeople ?? base.squad_people ?? 0,
      counters: saved.counters ? JSON.parse(JSON.stringify(saved.counters)) : null,
      buildings: (saved.places ?? []).map((place) => ({ ...place })),
      forgeOrder: saved.forgeOrder ?? -1,
      forgeLeft: saved.forgeLeft ?? 0,
      brewTimer: saved.brewTimer ?? null,
      brewTokens: saved.brewTokens ? [...saved.brewTokens] : null,
    },
    incomeStamp: saved.incomeStamp ?? 0,
    trainTimer: saved.trainTimer ?? 0,
    lastTime: saved.lastTime ?? null,
    // РУКИ — СЧЁТЧИК ОТРЯДА ПОСЕЛЕНИЯ (+0x1C). Движок считает их по самому
    // отряду в общем массиве юнитов, и для дальней деревни это ровно тот же
    // счёт (VA 0x41C944:358-386). У нас юнитов чужой карты в памяти нет, и
    // до первого визита ближе всего — сохранённое число бойцов отряда.
    // Ноль здесь означал бы «работать некому»: стройка стоит без рук, и
    // поселение, поднятое из сейва, так и не начинало строить.
    workers: saved.squadPeople ?? base.squad_people ?? 0,
  };
}

//: Перелить нажитое заглушкой в настоящую паковую запись. Список полей тот
//: же, что накладывает `villageApply` из сейва, — только источник свежее:
//: заглушка с загрузки успела и построить, и накопить дань.
function villageCarry(data, stub) {
  if (!data || !stub) return data;
  for (const field of ["flags", "status", "owner", "owned", "treasury",
                       "squad_people", "forgeOrder", "forgeLeft", "brewTimer"]) {
    if (stub[field] !== undefined && stub[field] !== null) data[field] = stub[field];
  }
  if (Array.isArray(stub.officials)) data.officials = [...stub.officials];
  if (Array.isArray(stub.brewTokens)) data.brewTokens = [...stub.brewTokens];
  for (const [role, box] of Object.entries(stub.counters ?? {})) {
    data.counters = data.counters ?? {};
    const live = data.counters[role] ??
      (data.counters[role] = { slots: [], details: {} });
    live.slots = live.slots ?? [];
    live.slots.length = 0;
    live.slots.push(...(box?.slots ?? []));
    live.details = { ...(box?.details ?? {}) };
  }
  for (const place of stub.buildings ?? []) {
    const found = (data.buildings ?? []).find((row) => row.slot === place.slot);
    if (!found) continue;
    found.state = place.state ?? 0;
    found.timer = place.timer ?? 0;
    found.built = Boolean(place.built);
  }
  return data;
}

function villageApply(number, kept) {
  const saved = pending.get(number);
  if (!saved || !kept?.data) return false;
  const data = kept.data;
  data.flags = saved.flags ?? data.flags ?? 0;
  data.status = saved.status ?? data.status ?? 0;
  data.owner = saved.owner ?? data.owner ?? 0;
  data.owned = saved.owned ?? data.owned ?? 0;
  data.treasury = saved.treasury ?? data.treasury ?? 0;
  if (Array.isArray(saved.officials)) data.officials = [...saved.officials];
  if (Number.isFinite(saved.squadPeople)) data.squad_people = saved.squadPeople;
  // ПРИЛАВКИ НАКЛАДЫВАЕМ В СУЩЕСТВУЮЩИЕ СПИСКИ, а не подменяем объект: на
  // список мест торговцу выдана ССЫЛКА (shops.js), и подмена оставила бы его
  // с отвязанной копией — покупка правила бы её, а поселение хранило старое.
  for (const [role, box] of Object.entries(saved.counters ?? {})) {
    data.counters = data.counters ?? {};
    const live = data.counters[role] ??
      (data.counters[role] = { slots: [], details: {} });
    live.slots = live.slots ?? [];
    live.slots.length = 0;
    live.slots.push(...(box?.slots ?? []));
    live.details = { ...(box?.details ?? {}) };
  }
  for (const place of saved.places ?? []) {
    const found = (data.buildings ?? []).find((row) => row.slot === place.slot);
    if (!found) continue;
    found.state = place.state ?? 0;
    found.timer = place.timer ?? 0;
    found.built = Boolean(place.built);
  }
  //: Метка выплаты теперь в мировых тактах, а сейвы до этой правки несут
  //: её в часах суток. Пересчитать неоткуда, и разбирать нечего: чужое
  //: число даст самое большее одну лишнюю выплату сразу после обновления,
  //: дальше метку ставит сам `treasuryTick` уже в тактах.
  kept.incomeStamp = saved.incomeStamp ?? kept.incomeStamp ?? 0;
  kept.trainTimer = saved.trainTimer ?? 0;
  kept.lastTime = saved.lastTime ?? null;
  if (Number.isFinite(saved.forgeOrder)) data.forgeOrder = saved.forgeOrder;
  if (Number.isFinite(saved.forgeLeft)) data.forgeLeft = saved.forgeLeft;
  if (Number.isFinite(saved.brewTimer)) data.brewTimer = saved.brewTimer;
  if (Array.isArray(saved.brewTokens)) data.brewTokens = [...saved.brewTokens];
  return true;
}

// ЧАСЫ КАЗНЫ — МИРОВОЙ ТАКТ, А НЕ ВРЕМЯ СУТОК.
//
// В движке метка выплаты (+0x14 записи поселения) хранит `_DAT_0084962C` —
// монотонный счётчик тактов, — и срок проверяется так (VA 0x41D559):
//
//     iVar3 = abs(_DAT_0084962c - поселение[+0x14]);
//     if (0x275f < iVar3) { ... доход ...; поселение[+0x14] = _DAT_0084962c; }
//
// Здесь метка лежала в СУТОЧНЫХ часах (0…21599), а разница бралась по
// кругу — `min(|now−then|, 21600−|now−then|)`, то есть не больше 10800 при
// периоде 10080. Условие выполнялось лишь в окне 1441 такт из 21600 (6,7 %
// суток): прозевал — жди следующих суток, а «прозевать» значило всего лишь
// выйти из деревни, потому что тикает она, только пока её карта текущая.
// Отсюда «сходил на глобальную и обратно — дани нет, а пересидел сутки в
// деревне — есть». Монотонный счётчик такой щели не оставляет.

// Житель деревни — юнит той же стороны, что и её люди.
function villageSide() {
  const first = (village.data?.people ?? [])[0];
  const official = units.find((unit) => unit.slot === first);
  return official?.side;
}

function villagePeople(side) {
  if (side === undefined) return 0;
  return units.filter((unit) => unit.alive && unit.side === side).length;
}

// Есть ли на карте живой отряд события: при нём раздача товара стоит
// (VA 0x417BD8 зовёт 0x435214 — ту же проверку, что обработчик 23).
// Экспорт — для кузницы (shops.js), у неё тот же гейт раздачи.
//
// БОЙЦЫ ЛЕЖАТ В `units`, А НЕ В `members`. Здесь читалось несуществующее
// поле, и `[].some(...)` давал ложь ВСЕГДА: раздача у кузнеца не тормозилась
// ни разу. Не совпадали и поля внутри — ждали `type`, а поза юнита это
// `pose` (+0x17). Правило движка (0x435214): жив тот, у кого снят бит 0x80
// в +0x1A и поза не 3, не 0xB и не 0xC.
export function eventAlive() {
  return (world.map?.events ?? []).some((event) => {
    if (!event.active) return false;
    return (event.units ?? []).some(eventFighterAlive);
  });
}

//: Одна мерка на оба места — сюда и в условие разговора 23.
export function eventFighterAlive(unit) {
  return !((unit?.flags ?? 0) & 0x80) &&
    ![3, 0x0B, 0x0C].includes(unit?.pose ?? 0);
}

const roll = (limit) => Math.floor(Math.random() * limit);
//: Кузница переехала в shops.js ЦЕЛИКОМ (villageForge): здесь жил её дубль
//: с верной механикой, но складом `village.stock`, которого не читал ни
//: один торговый экран. Подробности — комментарий у villageForge.

// Недельный доход казны владения — ОДНОЙ записи поселения.
//
// Запись, а не глобальная «текущая деревня»: в движке фаза деревень
// (VA 0x41C944, ветка `(такт + 7) & 0xF`) идёт по ВСЕМ двенадцати записям
// блока 0x83D408, и по текущей карте отфильтрованы ровно две отрисовочные
// ветки — расстановка (0x415B20) и перерисовка постройки (0x4171CC). Ни
// казна, ни стройка, ни варка, ни кузница карты не спрашивают вовсе.
//
// `people` приходит доводом по той же причине: у своей деревни жителей
// видно на карте, у дальней их считает не карта, а память прошлого визита.
function treasuryFor(kept, now, people) {
  const set = treasuryRules();
  const data = kept?.data;
  if (!set || !data) return false;
  if ((data.flags ?? 0) & (set.block_bit ?? 0x10)) return false;
  if (Math.abs(now - (kept.incomeStamp ?? 0)) <= (set.period ?? 0x2760) - 1) {
    return false;
  }
  const names = world.map?.hero?.rules?.progression?.skills?.names ?? [];
  const index = names.indexOf("Управление деревней");
  const skill = index >= 0 ? hero.skills?.[index] ?? 0 : 0;
  let income = roundHalfEven(
    (data.wealth ?? 0) * (set.wealth_scale ?? 50) * Math.sqrt(skill) +
    people * (set.per_person ?? 10) + 1);
  const row = (set.dividers ?? [])[Math.min(data.status ?? 0, 2)] ?? [1, 1, 1];
  income = Math.trunc(income / (row[Math.min(data.owner ?? 0, 2)] ?? 1));
  data.owned = (data.owned ?? 0) + income;
  kept.incomeStamp = now;
  return true;
}

//: Казна СВОЕЙ деревни: жителей видно на карте, их и считаем.
function treasuryTick(now) {
  if (!treasuryFor(village, now, villagePeople(villageSide()))) return false;
  //: `village` и запись склада — два объекта с общими полями. Метку кладём
  //: в обе, иначе уход с карты вернул бы из склада прежнюю.
  const kept = current === null ? null : settlements.get(current);
  if (kept) kept.incomeStamp = village.incomeStamp;
  return true;
}

// Такт хозяйства: зовётся из мирового цикла. Возвращает, поменялось ли
// что-нибудь заметное. Мастерская отсюда переехала в shops.js
// (villageForge) — она работает с настоящим прилавком кузнеца, а здешний
// дубль ковал в невидимый `village.stock`.
export function villageTick() {
  if (!village.data) return false;
  //: Счёт по тому же мировому такту: раз за такт, не чаще. Прежний гейт
  //: смотрел на часы суток и при выключенных сутках («вечное утро»,
  //: настройка daynight) не пропускал казну ВОВСЕ.
  const now = clock.ticks;
  if (village.lastTime === now) return false;
  village.lastTime = now;
  return treasuryTick(now);
}

// ОБУЧЕНИЕ У ВОЕВОДЫ (VA 0x4181E8) — ОДНА ИЗ ДВУХ механик казармы.
//
// Вторая — тренировка на рабочих местах (units.js, sparringTick): она видна
// глазом, но жителей не растит. Растит их эта, и она невидима. Обе разобраны
// в docs/VILLAGE_TRAINING_SPEC.md; путать их нельзя, потому что жалобы
// «никто не машет» и «опыт не идёт» — про разные.
//
// Движок раз в 1200 тактов деревни проходит по
// бойцам её отряда и даёт каждому, чей уровень не выше уровня воеводы, СТО
// опыта; дошедшему до порога — уровень, 25 свободных очков и ДВЕ попытки
// роста: Выносливость, Сила, Ловкость и одиннадцать навыков. Такт деревни
// идёт раз в шестнадцать мировых, значит занятие случается раз в 19200
// тактов — это около игровых суток.
//
// Условий два, и оба нежданные:
//
//   * должность ВОЕВОДЫ занята — слово поселения +0x3D8, место 4. Пусто —
//     функция выходит первой строкой, и казарма стоит без толку;
//   * в этот же такт деревня НИЧЕГО не заложила и не сменила ступень
//     (0x41C944:513 зовёт обучение только при нулевом флаге стройки).
//
// Счётчик занятий лежит в поселении по +0x0C и сбрасывается в 0x4B0. Это
// поле мы звали «казной» — неверно: доход капает в +0x10 (0x41C944:250,442),
// а +0x0C не трогает больше никто.
const TRAIN_PERIOD = 0x4B0;
const TRAIN_XP = 100;
//: Выносливость, Сила, Ловкость — в порядке движка.
const TRAIN_CHARACTERISTICS = [5, 4, 1];
const TRAIN_ROUNDS = 2;
const TRAIN_SKILLS = 11;
const TRAIN_POST = 4;

//: `kept` — чья казарма (по умолчанию своя деревня), `crew` — над кем
//: работает (живые юниты дома, снимки жителей у дальней). Счётчик занятий
//: живёт на самой записи склада, как поле +0x0C у движка.
export function villageTraining(phases = 1, kept = village, crew = units) {
  const data = kept?.data;
  if (!data || phases < 1) return false;
  const warlord = (data.officials ?? [])[TRAIN_POST] ?? 0;
  if (!warlord) return false;
  let changed = false;
  for (let phase = 0; phase < phases; phase += 1) {
    kept.trainTimer = (kept.trainTimer ?? TRAIN_PERIOD) - 1;
    if (kept.trainTimer > 0) continue;
    kept.trainTimer = TRAIN_PERIOD;
    if (trainOnce(warlord, data, crew)) changed = true;
  }
  return changed;
}

function trainOnce(warlord, data, crew) {
  const teacher = crew.find((unit) => unit.slot === warlord);
  if (!teacher || teacher.alive === false) return false;
  const ceiling = teacher.level ?? 1;
  let changed = false;
  for (const unit of crew) {
    if (unit === teacher || unit.side !== data.side) continue;
    //: У снимка жителя поля `beast` нет — там работает канонная мерка
    //: самого движка: человек это облик меньше шести (VA 0x41C944:359).
    if (unit.alive === false || (unit.beast ?? (unit.body ?? 0) >= 6)) continue;
    if ((unit.level ?? 1) > ceiling) continue;
    // Опыт кладётся НАПРЯМУЮ, минуя 0x413110: множителя сложности здесь нет,
    // это учёба жителей, а не награда игроку.
    unit.experience = (unit.experience ?? 0) + TRAIN_XP;
    changed = true;
    if (unit.experience < levelThreshold(unit.level ?? 1)) continue;
    unit.level = (unit.level ?? 1) + 1;
    unit.freeExperience = (unit.freeExperience ?? 0)
      + (world.map?.hero?.rules?.progression?.free_xp_per_level ?? 25);
    unit.nextLevel = levelThreshold(unit.level);
    for (let round = 0; round < TRAIN_ROUNDS; round += 1) {
      for (const index of TRAIN_CHARACTERISTICS) raiseCharacteristic(index, unit);
      for (let skill = 0; skill < TRAIN_SKILLS; skill += 1) raiseSkill(skill, unit);
    }
  }
  return changed;
}

// РОЛЬ ВЫВОДИТСЯ ИЗ ДОЛЖНОСТЕЙ, А НЕ ХРАНИТСЯ (VA 0x00415190).
//
// Движок перебирает пятёрку с +0x3D0 записи поселения и возвращает «место + 1»,
// то есть у знахаря 2, у купца 3, у кузнеца 4. Поле `role` в паке проставлено
// по МИРУ 0, а запись поселения мы теперь берём мира своего героя, и у любого
// другого героя эти два источника расходятся: житель числится должностным, а
// поле у него пустое. Верен только вывод из списка.
export function officialRole(unit) {
  const officials = world.map?.village?.officials ?? [];
  const number = unit?.slot ?? Number(String(unit?.id ?? "").replace("unit_", ""));
  const place = officials.indexOf(number);
  return place < 0 ? 0 : place + 1;
}
