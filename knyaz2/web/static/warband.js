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
export const KEEP_RANGE = 0x348;

//: Породы: бит 0x40 в +0x1A значит «тварь», бит 0x80 — «мёртв».
export const BREED_BEAST = 0x40;
export const BREED_DEAD = 0x80;

//: Как тварь выбирает жертву — разбор по породе из VA 0x410010. Породы,
//: которых здесь нет, идут общим путём: ближайший живой враг.
//:   стая      — бить того, кого уже бьёт сородич        (VA 0x41F0D0)
//:   свободный — ближайшего, кого ещё никто не бьёт      (VA 0x41F340)
//:   вплотную  — только восемь соседних клеток            (0x410010:85-108)
//:   досягаемый — первый, до кого дотянется бросок          (0x410010:127-160)
//
// РАЗБОР ПЕРЕЧИТАН 12.08.2026 по самой цепочке `bVar1` (0x410010:82-177), и
// три породы стояли не там: 0x43 Болотник и 0x45 Мертвяк идут ОБЩИМ путём
// (в цепочке для них ветки нет вовсе), а 0x44 Цветок-людоед имеет свою и
// здесь её не хватало. Кикимора (0x53) имеет собственную —
// перебор всего вражеского отряда по досягаемости; перенесена 12.08.
const BREED_HUNT = new Map([
  [0x41, "стая"], [0x4D, "стая"], [0x4F, "стая"],
  [0x46, "свободный"], [0x4C, "свободный"],
  [0x44, "вплотную"], [0x53, "досягаемый"],
]);

// ЗАПИСИ ОТРЯДОВ ЖИВУТ ВЕСЬ СЕАНС, А НЕ ПЕРЕЧИТЫВАЮТСЯ ПРИ ВХОДЕ НА КАРТУ.
//
// Здесь стояло `warbands.clear()`, и это прямо против движка. Массив отрядов
// `0x71E56C` (0xC800 байт, двести записей по 0x100) читается РОВНО ДВАЖДЫ за
// игру: при новой игре (`0x43D898:30`) и из сохранения (`0x4236E0:59`), — и
// целиком пишется в сейв (`0x423CB8:37`). Загрузчик карты `0x43DF48` его не
// касается ВООБЩЕ: ни одной ссылки на этот адрес во всей функции.
//
// А в записи отряда лежит вся война: `+0x1D` идёт ли бой, `+0x1E`/`+0x1F`
// флаги войны, `+0x1C` счёт бойцов. Пока порт стирал их на каждом входе,
// любой переход мирил игрока со всеми разом — и, что заметнее, ВОЗВРАЩАЛ В
// ЗЕМЛЮ поднявшихся тварей: скелет держит кадр 0, пока его отряд не в бою
// (см. пункт 103), и после перехода снова оказывался закопанным.
//
// Поэтому пак теперь только ЗАВОДИТ незнакомую сторону, а известную не
// трогает: её состояние старше карты.
export function warbandsSetup(map = world.map) {
  // ОТРЯДЫ ВЫБРАННОГО МИРА. Сторона юнита равна НОМЕРУ его отряда, и наборы
  // у миров разные: на карте 23 у Ратибора это 1, 30, 65, а у Эйнара 0, 1, 2,
  // 31, 66. Пока читался общий список (мир 0), у Асбада со стороной 2 отряда
  // не находилось вовсе — и действие 37 «поднять отряд собеседника» ничего не
  // поднимало: стражник не нападал.
  const worldId = String(map?.hero?.template?.world ?? 0);
  const list = map?.warbands_by_world?.[worldId] ?? map?.warbands ?? [];
  for (const entry of list) {
    if (warbands.has(entry.side)) continue;
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

//: Новая игра — единственное место, где склад отрядов чистится целиком
//: (движок читает блок заново только там и при загрузке сохранения).
export function warbandsReset() { warbands.clear(); }

export function warbandOf(unit) {
  return warbands.get(unit?.side ?? 0) ?? null;
}

// АГРО — В СЕЙВ. Движок пишет весь массив отрядов `0x71E56C` (0xC800 байт,
// двести записей по 0x100) одним куском (VA 0x423CB8), а «на кого злимся»
// живёт именно там: `+0x1D` — идёт ли бой, `+0x1E`/`+0x1F` — флаги войны,
// `+0x1C` — счёт бойцов. Расстановка карты (`warbandsSetup`) поднимает их
// из пака в мирном виде, поэтому без этой пары загрузка мирила игрока со
// всем лагерем разом.
export function warbandsPack() {
  return [...warbands.values()].map((band) => ({
    side: band.side,
    fighting: Boolean(band.fighting),
    enemySide: band.enemySide ?? 0,
    warFlags: band.warFlags ?? 0,
    flags: band.flags ?? 0,
  }));
}

export function warbandsApply(list) {
  for (const saved of list ?? []) {
    if (!Number.isFinite(saved?.side)) continue;
    // Отряда может и не быть: засада приезжает на карту своей записью
    // (0x4277F4), и в паке местности её нет.
    const band = warbands.get(saved.side) ?? warbandJoin(saved.side, saved.enemySide ?? 0);
    band.fighting = Boolean(saved.fighting);
    band.enemySide = saved.enemySide ?? 0;
    band.warFlags = saved.warFlags ?? 0;
    band.flags = saved.flags ?? 0;
  }
  return warbands;
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

// ПЕРВЫЙ ДОСЯГАЕМЫЙ (VA 0x410010:127-160) — так ищет цель Кикимора, и только
// она. Движок идёт по ВСЕМУ вражескому отряду подряд и для каждого живого
// спрашивает 0x414AF8: дотянется ли; первый, до кого дотягивается, и
// становится целью с приказом 1. Не ближайший — ПЕРВЫЙ ПОДХОДЯЩИЙ по порядку
// записей, поэтому она может кинуть в дальнего, пройдя мимо ближнего вне
// досягаемости.
function reachableEnemy(unit, enemySide, units) {
  for (const other of membersOf(enemySide, units)) {
    const distance = cellRange(other, unit);
    //: Дальность больше единицы, поэтому правило простое — расстояние в
    //: клетках не больше броска (units.js::withinReach, вторая ветка).
    //: Звать саму withinReach нельзя: units.js уже тянет этот модуль, и
    //: обратный импорт замкнул бы петлю.
    if (distance <= KIKIMORA_REACH) return other;
  }
  return null;
}

//: Дальность броска Кикиморы — константа 0x28 из 0x41BB10, та же, что и у
//: снаряда: досягаемость и жизнь снаряда в движке одно и то же число.
const KIKIMORA_REACH = 0x28;

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
  // ЦВЕТОК-ЛЮДОЕД дальше соседних клеток не смотрит вовсе: его ветка в
  // 0x410010 перебирает восемь направлений и, никого не найдя, ВЫХОДИТ. Их
  // уже перебрал `enemyFor` через 0x4107EC, поэтому здесь остаётся вернуть
  // пустоту — иначе неподвижный цветок выбрал бы дальнюю жертву и потянулся
  // бы к ней.
  else if (style === "вплотную") return null;
  else if (style === "досягаемый") {
    found = reachableEnemy(unit, enemySide, units);
  }
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
