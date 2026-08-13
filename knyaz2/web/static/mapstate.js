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
    return packJoined({ ...row, side: unit.side, ally: unit.ally,
                        cell: unit.cell, orderByte: unit.orderByte });
  });
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
  if (piles) entry.loot = piles.filter((pile) => !pile.taken).map(packPile);
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
    });
  }
  return mapState;
}

export function mapStateReset() { mapState.clear(); }
