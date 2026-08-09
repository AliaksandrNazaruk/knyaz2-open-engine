// Отряды и вражда: кто на кого бросается.
//
// ГЛАВНОЕ: враждебность в движке принадлежит НЕ ЮНИТУ, А ОТРЯДУ. Поля
// «злой/добрый» у юнита нет вовсе. Есть запись отряда (0x71E56C, шаг
// 0x100), в ней прямоугольник и флаги, и один проход по всем отрядам карты
// (VA 0x415B20), который решает, объявлять ли бой:
//
//     +0x1E бит 0x01  это отряд игрока (стоит ровно у одного, №0)
//     +0x1E бит 0x04  на этот отряд могут нападать другие
//     +0x1F бит 0x01  нападать на игрока
//     +0x1F бит 0x04  нападать на другие отряды
//     +0x1F бит 0x08  но только если игрок УЖЕ в бою
//     +0x1F бит 0x80  нападать на особый отряд ([0x849538])
//     +0x1F маска 0x4F — без единого её бита бой не объявляется вовсе
//     +0x06 сторона врага      +0x1D  «отряд в бою»
//
// Условие нападения одно на все ветки: хоть один юнит цели стоит ВНУТРИ
// прямоугольника отряда — того самого, по которому отряд рассыпают при
// входе на карту. Зона появления и зона агрессии в движке ОДНА И ТА ЖЕ.
//
// Сторона юнита (+0x1B) равна НОМЕРУ его отряда, поэтому отряд находится
// прямо по стороне.
import { world } from "./world.js";
import { hero, roster } from "./hero.js";
import { orderClear, orderUnit } from "./orders.js";

//: Сторона -> отряд. Заполняется из пака при входе на карту.
export const warbands = new Map();

//: Бой держится, пока враг ближе 840 пикселей по КАЖДОЙ оси в отдельности
//: (VA 0x410784) — не по прямой, а по обеим сразу.
const KEEP_RANGE = 0x348;

//: Породы: бит 0x40 в +0x1A значит «тварь», бит 0x80 — «мёртв».
export const BREED_BEAST = 0x40;
export const BREED_DEAD = 0x80;

//: Как тварь выбирает жертву — разбор по породе из VA 0x410010. Породы,
//: которых здесь нет, идут общим путём: ближайший живой враг.
//:   стая      — бить того, кого уже бьёт сородич        (VA 0x41F0D0)
//:   свободный — ближайшего, кого ещё никто не бьёт      (VA 0x41F340)
const BREED_HUNT = new Map([
  [0x41, "стая"], [0x4D, "стая"], [0x4F, "стая"],
  [0x43, "свободный"], [0x45, "свободный"],
  [0x46, "свободный"], [0x4C, "свободный"],
]);

export function warbandsSetup(map = world.map) {
  warbands.clear();
  for (const entry of map?.warbands ?? []) {
    warbands.set(entry.side, {
      ...entry,
      // Бой начинается снятым: в стартовом мире +0x1D у всех ноль.
      fighting: Boolean(entry.fighting),
      enemySide: entry.enemy_side ?? 0,
      warFlags: entry.war_flags ?? 0,
      // Байт +0x1E: бит 0x01 «отряд игрока», бит 0x04 «на него нападают».
      flags: entry.zone?.flags ?? 0,
    });
  }
  return warbands;
}

export function warbandOf(unit) {
  return warbands.get(unit?.side ?? 0) ?? null;
}

// Отряд, приехавший на карту вместе с боем: движок так и делает — копирует
// запись отряда на карту-местность (VA 0x4277F4). Засада приезжает уже в
// бою, поэтому флаг боя и сторона врага ставятся сразу.
export function warbandJoin(side, enemySide) {
  let band = warbands.get(side);
  if (!band) {
    band = { side, player: false, flags: 0, warFlags: WAR_ON_PLAYER,
             on_player: true, on_parties: false, only_if_fighting: false,
             zone: null, enemySide, fighting: true };
    warbands.set(side, band);
  }
  band.enemySide = enemySide;
  band.fighting = true;
  return band;
}

const WAR_ON_PLAYER = 0x01;

function playerBand() {
  for (const band of warbands.values()) if (band.player) return band;
  return null;
}

//: Все живые юниты стороны. Игрок и спутники живут отдельным списком,
//: поэтому сторона героя собирается из общего состава.
function membersOf(side, units) {
  const out = [];
  for (const unit of roster(units)) {
    if ((unit.side ?? 0) !== side) continue;
    if (unit.alive === false || unit.hidden) continue;
    out.push(unit);
  }
  return out;
}

function insideZone(unit, zone) {
  if (!zone || !unit?.cell) return false;
  return unit.cell.row >= zone.row_from && unit.cell.row <= zone.row_to &&
         unit.cell.col >= zone.col_from && unit.cell.col <= zone.col_to;
}

// Враг ещё рядом (VA 0x410784): по каждой оси в отдельности.
function engaged(one, two) {
  return Math.abs(one.x - two.x) < KEEP_RANGE && Math.abs(one.y - two.y) < KEEP_RANGE;
}

// Объявление боя (VA 0x4159DC). Без битов 0x4F бой не объявляется вовсе;
// повторное объявление тому же врагу ничего не меняет.
export function warbandDeclare(band, enemySide, units) {
  // Без битов 0x4F отряд не воюет НИКОГДА: двенадцать отрядов мира с нулём
  // в +0x1F не поднимаются, что бы с ними ни делали.
  if (!band || !(band.warFlags & 0x4F)) return false;
  const enemy = warbands.get(enemySide);
  // ОТРЯД ЗАПОМИНАЕТ ОБИДЧИКА. В свои боевые биты (+0x1F) подмешивается
  // байт +0x1E ВРАГА по маске 0x4F — и делается это до всякой проверки,
  // даже когда бой с этим врагом уже идёт. У отряда игрока +0x1E равен
  // единице, то есть деревня, которую однажды тронули, навсегда получает
  // бит «нападать на игрока» и будет бросаться на него при каждом входе в
  // свою зону, даже когда этот бой давно кончился.
  if (enemy) band.warFlags |= (enemy.flags ?? 0) & 0x4F;
  if (band.fighting && band.enemySide === enemySide) return false;
  band.enemySide = enemySide;
  band.fighting = true;
  // Отряду игрока приказы не сбрасывают — только чужим.
  if (!band.player) for (const unit of membersOf(band.side, units)) orderClear(unit);
  return true;
}

// Один проход по отряду (VA 0x415B20). Зовётся каждый такт для каждого
// отряда карты, как в мировом такте движка (VA 0x41C944).
export function warbandTick(band, units) {
  if (!band) return;
  if (band.player) {
    // Отряд игрока сам не нападает: он выходит из боя, когда никто из его
    // юнитов больше не бьётся.
    if (!band.fighting) return;
    for (const unit of membersOf(band.side, units)) {
      if ((unit.orderKind ?? 0) === 1) return;
    }
    band.fighting = false;
    return;
  }

  const player = playerBand();
  if (band.on_player) {
    // Бит 0x08: нападают только на того, кто уже ввязался в драку.
    if (!(band.only_if_fighting && !player?.fighting)) {
      for (const unit of membersOf(player?.side ?? hero.side ?? 0, units)) {
        if (insideZone(unit, band.zone)) {
          warbandDeclare(band, player?.side ?? hero.side ?? 0, units);
          return;
        }
      }
    }
  }

  if (band.on_parties) {
    for (const other of warbands.values()) {
      // Движок перебирает отряды с первого, пропуская отряд игрока, и
      // берёт только тех, у кого поднят бит 0x04 в +0x1E.
      if (other === band || other.player) continue;
      if (!(other.flags & 0x04)) continue;
      for (const unit of membersOf(other.side, units)) {
        if (insideZone(unit, band.zone)) {
          warbandDeclare(band, other.side, units);
          return;
        }
      }
    }
  }

  // Бой кончился? Ищем хоть одну пару «свой — чужой» в пределах 840
  // пикселей; не нашлось — отряд выходит из боя и чистит приказы.
  if (!band.fighting) return;
  const mine = membersOf(band.side, units);
  const theirs = membersOf(band.enemySide, units);
  for (const one of mine) {
    for (const two of theirs) if (engaged(two, one)) return;
  }
  band.fighting = false;
  for (const unit of mine) orderClear(unit);
}

export function warbandsTick(units) {
  for (const band of warbands.values()) warbandTick(band, units);
}

// Метрика клеток из движка (VA 0x43B670): большая разница, плюс единица,
// если меньшая больше одной.
function cellRange(a, b) {
  if (!a?.cell || !b?.cell) return Infinity;
  const rows = Math.abs(a.cell.row - b.cell.row);
  const cols = Math.abs(a.cell.col - b.cell.col);
  const large = Math.max(rows, cols);
  const small = Math.min(rows, cols);
  return large + (small > 1 ? 1 : 0);
}

// Ближайший живой враг (VA 0x41F234).
function nearestEnemy(enemySide, unit, units) {
  let best = null, bestRange = Infinity;
  for (const other of membersOf(enemySide, units)) {
    const range = cellRange(other, unit);
    if (range < bestRange) { best = other; bestRange = range; }
  }
  return best;
}

// Цель сородича (VA 0x41F0D0): кто-то из своих уже бьётся — навались на
// того же. Возвращает ЕГО цель, а не его самого.
function packTarget(band, units) {
  for (const mate of membersOf(band.side, units)) {
    if ((mate.orderKind ?? 0) !== 1) continue;
    const target = mate.orderTarget;
    if (target && target.alive !== false && !target.hidden) return target;
  }
  return null;
}

// Ближайший враг, которого ЕЩЁ НИКТО из своих не бьёт (VA 0x41F340) —
// стая разбирает цели по одной, а не наваливается всей толпой на одного.
function unclaimedEnemy(band, enemySide, unit, units) {
  const mine = membersOf(band.side, units);
  let best = null, bestRange = Infinity;
  for (const other of membersOf(enemySide, units)) {
    const taken = mine.some((mate) => (mate.orderKind ?? 0) === 1 &&
                                      mate.orderTarget === other);
    if (taken) continue;
    const range = cellRange(other, unit);
    if (range < bestRange) { best = other; bestRange = range; }
  }
  return best;
}

// Враг на соседней клетке (VA 0x4107EC). Перебираются ВОСЕМЬ соседних
// клеток, и только они: дальше этой функции юнит не смотрит. Тот, кто бьёт
// МЕНЯ, забирается сразу; прочие годятся, только если их отряд воюет с моей
// стороной.
export function adjacentEnemy(unit, units, neighbour) {
  if (!unit?.cell) return null;
  let found = null;
  for (let direction = 0; direction < 8; direction += 1) {
    const cell = neighbour(unit.cell.row, unit.cell.col, direction);
    if (!cell) continue;
    for (const other of roster(units)) {
      if (other === unit || other.alive === false || other.hidden) continue;
      if (!other.cell || other.cell.row !== cell.row || other.cell.col !== cell.col) continue;
      if ((other.side ?? 0) === (unit.side ?? 0)) continue;
      // Он бьёт меня — беру его немедленно и перебор прекращаю.
      if ((other.orderKind ?? 0) === 1 && other.orderTarget === unit) return other;
      const band = warbandOf(other);
      if (band?.fighting && band.enemySide === (unit.side ?? 0)) found = other;
    }
  }
  return found;
}

// Выбор жертвы (VA 0x410010). Отряд не в бою — приказ снимается, и юнит
// возвращается к своим делам.
export function pickEnemy(unit, units) {
  const band = warbandOf(unit);
  if (!band?.fighting) return null;
  const enemySide = band.enemySide;
  const breed = unit.breed ?? 0;

  if (!(breed & BREED_BEAST)) {
    // Человек с битом «за вожаком» сперва защищает вожака: ищет того, кто
    // бьёт первого юнита отряда, и берёт из таких ближайшего.
    if ((unit.orderByte ?? 0) & 0x10) {
      const leader = membersOf(band.side, units)[0] ?? null;
      let best = null, bestRange = Infinity;
      for (const other of membersOf(enemySide, units)) {
        if ((other.orderKind ?? 0) !== 1 || other.orderTarget !== leader) continue;
        const range = cellRange(other, unit);
        if (range < bestRange) { best = other; bestRange = range; }
      }
      if (best) return best;
    }
    return nearestEnemy(enemySide, unit, units);
  }

  const style = BREED_HUNT.get(breed);
  let found = null;
  if (style === "стая") found = packTarget(band, units);
  else if (style === "свободный") found = unclaimedEnemy(band, enemySide, unit, units);
  // Ничего не выбрала порода — общий путь: ближайший живой враг.
  return found ?? nearestEnemy(enemySide, unit, units);
}

// Кого юнит считает врагом прямо сейчас. Соседняя клетка сильнее любого
// дальнего выбора: движок зовёт 0x4107EC раньше, чем 0x410010.
export function enemyFor(unit, units, neighbour) {
  const near = adjacentEnemy(unit, units, neighbour);
  if (near) return near;
  return pickEnemy(unit, units);
}

// ЗАМАХ ПОДНИМАЕТ ВСЮ ДЕРЕВНЮ. В движке это делает не урон, а САМ ЗАМАХ:
// на втором кадре анимации удара (unit+0x1C == 2, то есть номер кадра)
// главный такт зовёт объявление войны отряду ЦЕЛИ против стороны бьющего
// (VA 0x413894). Попал удар или прошёл мимо — уже неважно, отряд поднят.
//
// Выстрел делает то же при попадании: снаряд несёт сторону стрелка в своём
// +0x1B, и отряд жертвы поднимается против неё (VA 0x41FDD0).
//
// Деревня — ОДИН отряд (у Чёрного Бора это сторона 55, все девять жителей),
// поэтому «поднять жертву» и «поднять всю деревню» в движке одно и то же:
// флаг стоит в записи отряда, а не у каждого юнита.
export function warbandSwing(attacker, victim, units) {
  if (!attacker || !victim) return false;
  if ((attacker.side ?? 0) === (victim.side ?? 0)) return false;
  return warbandDeclare(warbandOf(victim), attacker.side ?? 0, units);
}

// ПОДНЯТЬ ПО РАЗГОВОРУ (VA 0x4333A4, обработчик 37). Эта ветка НЕ проходит
// через объявление 0x4159DC и не смотрит на маску 0x4F: движок пишет и
// врага, и флаг боя прямо в обе записи — и собеседнику, и игроку. Поэтому
// отвечает даже отряд, который сам ни на кого не бросается.
export function warbandAlarm(attacker, victim, units) {
  if (!attacker || !victim) return false;
  const theirs = warbandOf(victim);
  if (theirs && !theirs.player) {
    theirs.enemySide = attacker.side ?? 0;
    theirs.fighting = true;
    for (const unit of membersOf(theirs.side, units)) orderClear(unit);
  }
  const ours = warbandOf(attacker);
  if (ours) { ours.enemySide = victim.side ?? 0; ours.fighting = true; }
  return true;
}

// Игрок сам ударил — его отряд входит в бой в миг ПРИКАЗА, а не удара
// (VA 0x421690: щелчок по чужому пишет отряду игрока врага в +0x06 и
// единицу в +0x1D, и только потом раздаёт приказ 0x61 выбранным).
export function warbandPlayerAttacks(victim) {
  const ours = playerBand();
  if (!ours || !victim) return false;
  ours.enemySide = victim.side ?? 0;
  ours.fighting = true;
  return true;
}

// Воюет ли сторона юнита прямо сейчас — по этому флагу решается, драться
// ему или заниматься своими делами.
export function unitFighting(unit) {
  return Boolean(warbandOf(unit)?.fighting);
}
