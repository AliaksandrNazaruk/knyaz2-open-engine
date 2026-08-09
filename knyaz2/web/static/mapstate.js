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

//: Куча на память: копия, а не ссылка на живую запись — иначе следующая
//: карта, переиспользовав список, переписала бы запомненное.
function packPile(pile) {
  return {
    id: pile.id ?? null,
    items: [...(pile.items ?? [])],
    details: (pile.details ?? []).map((detail) => ({ ...(detail ?? {}) })),
    enchant: [...(pile.enchant ?? [])],
    money: pile.money ?? 0,
    x: pile.x, y: pile.y,
    cell: pile.cell ? { ...pile.cell } : null,
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
    const живой = unit.alive !== false;
    alive.set(side, (alive.get(side) ?? false) || живой);
  }
  return [...alive.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([side, живой]) => ({ side, alive: живой }));
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
    });
  }
  return mapState;
}

export function mapStateReset() { mapState.clear(); }
