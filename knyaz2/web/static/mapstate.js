// Что карта помнит между входами.
//
// В движке такой памяти не нужно вовсе: весь мир живёт в массивах GAME.<N>,
// которые никуда не деваются при смене карты, а уход с локации лишь помечает
// текущую карту как −1. Убитый остаётся убитым просто потому, что его запись
// с поднятым битом 0x80 (unit+0x1A) продолжает лежать в отряде, и сохранение
// пишет эти массивы целиком.
//
// Порт устроен иначе: юниты каждой карты пересоздаются из пака при каждом
// входе (unitsSetup), поэтому без отдельной памяти зачищенная карта при
// возвращении снова полна живых. Здесь и хранится то, что переживает уход.
//
// Помнится три вещи: кто убит, что осталось лежать на земле (включая добро,
// высыпавшееся из мёртвых при свёртке по VA 0x43A628) и живы ли отряды карты
// — последнее нужно условию разговора 0 «карта зачищена».
export const mapState = new Map();

//: Спутники сюда не идут: они живут в записи отряда игрока и переезжают с
//: ним, а не принадлежат карте.
function mapDead(units) {
  return units
    .filter((unit) => unit.alive === false && !unit.ally && unit.slot != null)
    .map((unit) => unit.slot);
}

// ПРИЁМЫШИ КАРТЫ — те, кого пак на ней не знает.
//
// В движке этого списка нет и быть не может: запись юнита лежит в общем
// массиве `0x7B3C08` и никуда из него не девается. Оставленный в деревне
// спутник — это ТА ЖЕ запись, которой обработчик 43 переписал сторону и
// вычеркнул из отряда игрока (VA 0x4338B0); свёртка карты (VA 0x43A628)
// удаляет из массива только МЁРТВЫХ, живых не трогает вовсе.
//
// У порта юниты карты пересоздаются из пака при каждом входе, а пак знает
// лишь исходную расстановку — про бывшего спутника в нём нет ни строки.
// Поэтому здесь хранится и запись, по которой его поднять, и то, чем он
// отличается от исходного: сторона, клетка, приказ.
//
// Правило одно: ПАМЯТЬ СИЛЬНЕЕ ПАКА. Если запомненный юнит есть и в пачном
// наборе карты (свой житель, которому сменили сторону), поднимается пачный,
// а память лишь правит ему поля.
function packJoined(record) {
  return {
    slot: record.slot,
    member: record.member ? { ...record.member } : null,
    side: record.side ?? null,
    ally: Boolean(record.ally),
    cell: record.cell ? { ...record.cell } : null,
    orderByte: record.orderByte ?? 0,
  };
}

//: Запомнить, что юнит теперь принадлежит этой карте. `member` — запись, по
//: которой его поднимать (для бывшего спутника это его запись из отряда);
//: у своего жителя карты её нет, и правится только состояние.
export function mapStateJoin(number, unit, member = null) {
  if (!Number.isFinite(Number(number)) || !unit || unit.slot == null) return null;
  const entry = mapState.get(Number(number)) ?? {};
  const joined = (entry.joined ?? []).filter((row) => row.slot !== unit.slot);
  joined.push(packJoined({
    slot: unit.slot, member, side: unit.side, ally: unit.ally,
    cell: unit.cell, orderByte: unit.orderByte,
  }));
  entry.joined = joined;
  mapState.set(Number(number), entry);
  return entry;
}

//: Юнит снова взят в отряд (обработчик 36) — запись приёмыша карты больше
//: не про него: его несёт запись отряда игрока. Оставленная запись
//: поднималась вторым экземпляром — «два Белуна, клон ходит следом».
//: В движке удалять нечего: запись юнита одна в общем массиве 0x7B3C08.
export function mapStateUnjoin(number, slot) {
  const entry = mapState.get(Number(number));
  if (!entry?.joined?.length || slot == null) return false;
  const before = entry.joined.length;
  entry.joined = entry.joined.filter((row) => row.slot !== slot);
  return entry.joined.length !== before;
}

//: Правок карты от скриптов квестов здесь больше НЕТ. Постоянство даёт
//: канонный повтор: вход на карту прокручивает все взведённые квесты и
//: заново исполняет их командные фразы (движок — цикл в загрузчике,
//: донорский 0x4417E0; у нас — dialog.js::questEditsReplay). Отдельный
//: сохранённый список правок удваивал бы XOR клетки и терял квесты,
//: взведённые не на своей карте. Ключ questEdits в старых сейвах просто
//: не читается.

//: Кого карта помнит сверх пака. Ключ — слот юнита.
export function mapStateJoined(number) {
  const joined = mapState.get(Number(number))?.joined ?? [];
  return new Map(joined.map((row) => [row.slot, row]));
}

//: Обновить запомненным клетку и приказ: они ходят по деревне, и вернуться
//: юнит должен туда, где стоял, а не туда, где его оставили.
function refreshJoined(entry, units) {
  if (!entry.joined?.length) return;
  const live = new Map((units ?? []).filter((unit) => unit.slot != null)
    .map((unit) => [unit.slot, unit]));
  entry.joined = entry.joined.map((row) => {
    const unit = live.get(row.slot);
    if (!unit || unit.alive === false) return row;
    // От СОЮЗНИКА запись не освежается: он снова в отряде (наём должен был
    // снять запись вовсе — mapStateUnjoin), и скопировать сюда его ally с
    // битом следования значит поднять на входе клона, который «ходит за
    // мной по деревне». Слот к тому же не глобален: под тем же номером
    // здесь может стоять спутник с другой родной карты.
    if (unit.ally) return row;
    return packJoined({ ...row, side: unit.side, ally: unit.ally,
                        cell: unit.cell, orderByte: unit.orderByte });
  });
}

// СНИМОК ЖИТЕЛЯ КАРТЫ — вся изменяемая часть его записи.
//
// В движке эти поля живут в глобальном массиве юнитов (0x7B3C08) и смену
// карты переживают сами по себе: «карта» — лишь фильтр, а сохранение
// пишет записи целиком. У нас житель пересоздаётся из пака на каждом
// входе, поэтому изменяемое снимается при уходе и накладывается при
// входе. Ровно потерянные здесь поля и давали «квест заново при каждом
// входе»: бит юнита (действие 47), метка времени разговора (67), изъятая
// квестовая вещь (48), снятое снаряжение (50), сменённый облик (59),
// проданный товар и деньги торговца вне деревни. `removed` — «ушёл с
// карты» (действия 44/46/70): такой не поднимается вовсе, но и трупом
// не числится.
function packResident(unit) {
  return {
    slot: unit.slot,
    removed: Boolean(unit.removed),
    alive: unit.alive !== false,
    health: unit.health ?? null,
    poison: unit.poison ?? 0,
    cell: unit.cell ? { ...unit.cell } : null,
    direction: unit.direction ?? 6,
    side: unit.side ?? 0,
    flags: unit.flags ?? 0,
    talkStamp: unit.talkStamp ?? null,
    money: unit.money ?? 0,
    bag: [...(unit.bag ?? [])],
    counter: [...(unit.counter ?? [])],
    equipment: { ...(unit.equipment ?? {}) },
    enchant: { ...(unit.enchant ?? {}) },
    bagStrength: { ...(unit.bagStrength ?? {}) },
    bagCount: { ...(unit.bagCount ?? {}) },
    bagEnchant: { ...(unit.bagEnchant ?? {}) },
    bagPoison: { ...(unit.bagPoison ?? {}) },
    wear: { ...(unit.wear ?? {}) },
    ammoCount: unit.ammoCount ?? null,
    rangedMode: Boolean(unit.rangedMode),
    body: unit.body ?? 0,
    face: unit.face ?? null,
    palette: unit.palette ?? 0,
    level: unit.level ?? 1,
    experience: unit.experience ?? 0,
    freeExperience: unit.freeExperience ?? 0,
    nextLevel: unit.nextLevel ?? 0,
    skills: unit.skills ? [...unit.skills] : null,
    characteristics: unit.characteristics ? [...unit.characteristics] : null,
    baseCharacteristics: unit.baseCharacteristics
      ? [...unit.baseCharacteristics] : null,
    weaponLock: Boolean(unit.weaponLock),
    defendLeader: Boolean(unit.defendLeader),
    healTrigger: unit.healTrigger ?? 0,
  };
}

//: Снимки жителей карты. Ключ — слот (в пределах одной карты он уникален).
export function mapStateResidents(number) {
  const rows = mapState.get(Number(number))?.residents ?? [];
  return new Map(rows.map((row) => [row.slot, row]));
}

// Куча на память: копия, а не ссылка на живую запись — иначе следующая
// карта, переиспользовав список, переписала бы запомненное.
//
// ОДИН УПАКОВЩИК НА ВСЕХ. Ровно этот же список полей нужен сохранению, и
// раньше там лежала вторая, своя копия — с перечислением руками. Она отставала:
// теряла и «спрятана» (тайник после загрузки оказывался на виду), и пару
// «зона, гнездо» (сундук становился обычной кучей на полу).
export function packPile(pile) {
  return {
    id: pile.id ?? null,
    items: [...(pile.items ?? [])],
    details: (pile.details ?? []).map((detail) => ({ ...(detail ?? {}) })),
    enchant: [...(pile.enchant ?? [])],
    money: pile.money ?? 0,
    x: pile.x, y: pile.y,
    cell: pile.cell ? { ...pile.cell } : null,
    //: Спрятанная куча (знак поля +0x0F записи) и уже откопанная.
    ...(pile.buried ? { buried: true } : {}),
    ...(pile.dug ? { dug: true } : {}),
    //: Грядка: чем и когда отрастёт. Метка — движковая, с делением на
    //: записи (0x4136A8: −1 − такт/360); такт сбора рядом — для старых
    //: сейвов, где метки ещё не было.
    ...(pile.regrowItem ? { regrowItem: pile.regrowItem,
                            ...(pile.regrowStamp != null
                                ? { regrowStamp: pile.regrowStamp } : {}),
                            regrowAt: pile.regrowAt ?? 0 } : {}),
    //: Куча в гнезде обстановки помнит своё место: без пары «зона, гнездо»
    //: сундук после возвращения на карту стал бы обычной кучей на полу.
    ...(pile.zone != null ? { zone: pile.zone, nest: pile.nest } : {}),
    //: Подобранная — сохранению она нужна, памяти карты нет: та её
    //: отфильтровывает раньше.
    ...(pile.taken ? { taken: true } : {}),
  };
}

//: Запомнить, что случилось на карте. Зовётся ПЕРЕД уходом с неё — и при
//: переходе в другую локацию, и при выходе на глобальную.
export function mapStateCapture(number, units, piles = null) {
  if (!Number.isFinite(Number(number))) return null;
  const dead = mapDead(units ?? []);
  const entry = mapState.get(Number(number)) ?? {};
  entry.dead = [...new Set([...(entry.dead ?? []), ...dead])];
  // Кучи запоминаются ЦЕЛИКОМ и заменяют прежнее: список живой карты уже
  // включает и те, что приехали из пака, и брошенное игроком, и высыпавшееся
  // из мёртвых. Складывать его со старым нельзя — вышли бы двойники.
  //
  // ПУСТОЙ КОНТЕЙНЕР ОСТАЁТСЯ. Движок удаляет опустевшую кучу только НА
  // ЗЕМЛЕ (всё тело 0x4136A8 стоит под `+0x09 == 0xFF`), а куча в гнезде
  // обстановки — сундук, бочка — переживает опустошение пустым
  // контейнером и переписывается в архив. Прежний фильтр стирал и их —
  // опустевший сундук навсегда переставал ловить курсор.
  if (piles) {
    entry.loot = piles
      .filter((pile) => !pile.taken || pile.zone != null || pile.nest != null)
      .map(packPile);
  }
  // СНИМКИ ЖИТЕЛЕЙ — вся изменяемая часть записей, как «запись целиком»
  // движка: без них флаги веток, метки разговора, мешки торговцев и
  // «ушедшие» возвращались к паку на каждом входе.
  //
  // СТАРОЕ НЕ ВЫБРАСЫВАЕМ, А НАКРЫВАЕМ. Здесь стояла перезапись целиком —
  // `entry.residents = units.map(...)`, — и память теряла ровно тех, ради
  // кого заводилась. Ушедший (действия 44/46/70) на СЛЕДУЮЩЕМ входе не
  // поднимается вовсе, значит в списке `units` его нет; перезапись про него
  // забывала, и третий заход поднимал его из пака.
  //
  // Отсюда семь жалоб тестера одним корнем: «квест со сломанным мечом
  // повторяется, если сходить в другую деревню», покупка дома, купец
  // Лесного лагеря, Белун в яме, охотник, братья в сгоревшем лагере,
  // уведённый наёмник. Со ВТОРОГО круга, а не с первого — потому и
  // выглядело загадочно.
  //
  // Соседний `dead` копился объединением и потому переживал; расхождение
  // двух половин одной памяти и было ошибкой.
  const previous = new Map((entry.residents ?? []).map((snap) => [snap.slot, snap]));
  for (const snap of (units ?? [])
    .filter((unit) => !unit.ally && unit.slot != null)
    .map(packResident)) {
    previous.set(snap.slot, snap);
  }
  entry.residents = [...previous.values()];
  entry.squads = mapSquads(units ?? []);
  refreshJoined(entry, units);
  mapState.set(Number(number), entry);
  return entry;
}

//: Кучи, оставшиеся на карте. Пусто — значит мы там ещё не были, и кучи
//: надо брать из пака.
export function mapStateLoot(number) {
  return mapState.get(Number(number))?.loot ?? null;
}

//: Кто на этой карте уже мёртв. Номера — слоты юнитов, как в паке.
export function mapStateDead(number) {
  return new Set(mapState.get(Number(number))?.dead ?? []);
}

//: ОТРЯДЫ КАРТЫ И ЖИВЫ ЛИ ОНИ — для условия разговора 0 «карта зачищена»
//: (VA 0x4348F8). Движок отвечает по живым записям отрядов; у нас чужих карт
//: в памяти нет, поэтому ответ снимается в миг ухода — единственный момент,
//: когда он мог измениться без нас.
//:
//: Порядок важен: движок идёт по отрядам подряд и берёт (пропустить + 1)-й
//: из тех, что стоят на нужной карте. Номер отряда И ЕСТЬ сторона юнита
//: (записи лежат по `0x71E56C + сторона * 0x100`), поэтому сортировка по
//: стороне и даёт движковый порядок.
export function mapSquads(units) {
  const alive = new Map();
  for (const unit of units ?? []) {
    if (unit.ally) continue;          // отряд игрока движок пропускает
    if (unit.removed || unit.hidden) continue;  // ушедшие с карты не в счёт
    const side = unit.side ?? 0;
    const isAlive = unit.alive !== false;
    alive.set(side, (alive.get(side) ?? false) || isAlive);
  }
  return [...alive.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([side, isAlive]) => ({ side, alive: isAlive }));
}

//: Отряды карты, снятые при уходе. `null` — мы там не были.
export function mapStateSquads(number) {
  return mapState.get(Number(number))?.squads ?? null;
}

export function mapStatePack() {
  return [...mapState.entries()].map(([number, entry]) => ({
    map: number,
    dead: [...(entry.dead ?? [])],
    loot: entry.loot ? entry.loot.map((pile) => ({ ...pile })) : null,
    squads: entry.squads ? entry.squads.map((squad) => ({ ...squad })) : null,
    joined: entry.joined ? entry.joined.map(packJoined) : null,
    residents: entry.residents
      ? entry.residents.map((row) => JSON.parse(JSON.stringify(row))) : null,
    questEdits: entry.questEdits
      ? entry.questEdits.map((row) => ({ kind: row.kind, args: [...row.args] }))
      : null,
  }));
}

export function mapStateUnpack(list) {
  mapState.clear();
  for (const entry of list ?? []) {
    if (!Number.isFinite(Number(entry?.map))) continue;
    mapState.set(Number(entry.map), {
      dead: [...(entry.dead ?? [])],
      loot: Array.isArray(entry.loot) ? entry.loot.map((pile) => ({ ...pile })) : null,
      squads: Array.isArray(entry.squads)
        ? entry.squads.map((squad) => ({ ...squad })) : null,
      joined: Array.isArray(entry.joined) ? entry.joined.map(packJoined) : null,
      residents: Array.isArray(entry.residents)
        ? entry.residents.map((row) => JSON.parse(JSON.stringify(row))) : null,
      questEdits: Array.isArray(entry.questEdits)
        ? entry.questEdits.map((row) => ({ kind: row.kind, args: [...row.args] }))
        : null,
    });
  }
  return mapState;
}

