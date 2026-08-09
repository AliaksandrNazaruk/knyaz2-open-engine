// Приказы и выбор отряда.
//
// В движке приказ — это байт unit+0x16, поделённый пополам: младшая
// половина говорит, ЧТО юнит делает сейчас, старшая — в каком он режиме.
// Выдача приказа меняет только младшую (VA 0x416574):
//
//     0 сам   1 к цели   2 подойти и заговорить   3 обыскать   6 идти
//
// Старшая половина — БИТЫ: 0x10 «держаться за вожаком», 0x20 «идёт по
// приказу игрока», 0x40 особое. Движок проверяет их поодиночке: когда
// действия нет и юнит не занят, он смотрит ровно бит 0x10 и зовёт догон
// (VA 0x4111E8 -> 0x41209C). Отсюда знакомые числа: 0x10 и 0x30 — оба
// «за вожаком», 0x26 «иду, куда велели», 0x22 «подойти и заговорить».
//
// Куда идти — клетка в unit+0x13 и +0x15, кого имели в виду — номер в
// unit+0x10 (объект хранится отрицательным).
//
// Приказ дошёл (VA 0x4115AC): юнит стоит на клетке назначения, и движок
// смотрит младшую половину — заговорить, обыскать или ничего.
import { world } from "./world.js";
import { sfxSelect } from "./sfx.js";

function rules() { return world.map?.hero?.rules?.orders ?? null; }

export function orderKinds() {
  return rules()?.kind ??
    { none: 0, target: 1, talk: 2, take: 3, go: 6, wait_talk: 0x0C };
}

// СТОЙ, С ТОБОЙ ГОВОРЯТ (VA 0x410A08, случай 2). Приказ достаётся не
// игроку, а СОБЕСЕДНИКУ, и ровно в тот миг, когда игрок отдал приказ 2:
// целый байт 0x0C (старшая половина стирается) плюс счётчик в +0xF5.
//
// Это НЕ проверка задним числом, а настоящий приказ на юните — потому он и
// сильнее всех его дел: рассудок (VA 0x4111E8) зовётся только при нулевой
// младшей половине байта, а тут она 0x0C. Пока приказ держится, юнит не
// берёт ни работы, ни цели, ни строя.
export function orderWaitTalk(unit) {
  if (!unit || unit.alive === false) return false;
  const kinds = orderKinds();
  unit.orderByte = kinds.wait_talk ?? 0x0C;
  unit.orderKind = kinds.wait_talk ?? 0x0C;
  unit.orderTarget = null;
  unit.busy = false;
  unit.waitTalk = rules()?.wait_talk_counter ?? 100;
  // Дел больше нет: маршрут и срок работы обнуляются сразу, а начатый шаг
  // юнит доигрывает — движок его тоже не обрывает.
  unit.path = [];
  unit.goal = null;
  unit.workRest = 0;
  return true;
}
export function orderModes() {
  return rules()?.mode ?? { follow: 0x10, player: 0x20, special: 0x40 };
}

// Догонять вожака начинают, отойдя на десять клеток в отряде игрока и на
// пять в чужом (VA 0x41209C).
export function followDistance(own = true) {
  const set = rules()?.follow ?? { own: 10, other: 5 };
  return own ? set.own : set.other;
}

export function follows(unit) {
  return Boolean((unit?.orderByte ?? 0) & (orderModes().follow ?? 0x10));
}

//: Список выбора: до девяти, как в движке (0x840B94). Держится
//: отсортированным по номеру слота и НИКОГДА не бывает пустым — сняв
//: последнего, движок кладёт туда самого игрока (VA 0x43AE5C).
export const selection = [];

export function selectionMax() { return rules()?.selection?.max ?? 9; }

//: Кого класть в список, когда не осталось никого. Ставится извне, чтобы
//: модуль приказов не тянул за собой героя.
let fallbackUnit = null;
export function selectionFallback(unit) { fallbackUnit = unit; }

function sortSelection() {
  // По АДРЕСУ записи юнита (VA 0x423F80, пузырёк по указателям): записи
  // лежат подряд через 0x100, то есть это порядок номеров слотов.
  selection.sort((a, b) => (a.slot ?? 0) - (b.slot ?? 0));
}

// Выбрать своего (VA 0x423F80). Без добавки список заменяется одним
// юнитом, с добавкой юнит дописывается — а если он там уже был, СНИМАЕТСЯ
// (VA 0x4217D8). Пустым список не остаётся.
export function select(unit, add = false) {
  if (!unit) return selection;
  if (!add) {
    selection.length = 0;
    selection.push(unit);
    sfxSelect(unit);           // голос отклика (0x421690 -> 0x42D308)
    return selection;
  }
  const at = selection.indexOf(unit);
  if (at >= 0) deselect(unit);
  else if (selection.length < selectionMax()) {
    selection.push(unit);
    sortSelection();
    sfxSelect(unit);           // пополнение списка тоже звучит (0x423F80)
  }
  return selection;
}

// Снять выделение (VA 0x43AE14): юнит вычёркивается, хвост сдвигается, а
// опустевший список получает игрока.
export function deselect(unit) {
  const at = selection.indexOf(unit);
  if (at < 0) return selection;
  selection.splice(at, 1);
  if (!selection.length && fallbackUnit) selection.push(fallbackUnit);
  return selection;
}

// Рамка мышью (VA 0x42A6E0): ловит живых своих в прямоугольнике. Мёртвых
// и типы 3/0x0B/0x0C не берёт; без добавки список сперва очищается, но
// если рамка не поймала НИКОГО, прежний выбор возвращается — пустой
// протяжкой выбор не сбрасывается.
export function selectBand(candidates, box, add = false) {
  const band = rules()?.selection?.band ?? {};
  const skipTypes = band.skip_types ?? [3, 0x0B, 0x0C];
  const before = [...selection];
  const caught = candidates.filter((unit) => {
    if (!unit?.ally && unit !== fallbackUnit) return false;
    if (unit.alive === false || unit.hidden) return false;
    if (skipTypes.includes(unit.type ?? 0)) return false;
    return unit.x >= box.left && unit.x <= box.right &&
           unit.y >= box.top && unit.y <= box.bottom;
  });
  if (!add) selection.length = 0;
  for (const unit of caught) {
    if (selection.length >= selectionMax()) break;
    if (!selection.includes(unit)) selection.push(unit);
  }
  if (!selection.length) selection.push(...before);
  sortSelection();
  return selection;
}

export function isSelected(unit) { return selection.includes(unit); }

//: Первый выбранный — тот, чьи вещи и характеристики показывает панель
//: (0x849514, VA 0x4292DC). Нет никого — показывается сам игрок.
export function selectionLead() { return selection[0] ?? fallbackUnit ?? null; }

// Выдать приказ одному: младшая половина байта меняется, старшая остаётся.
export function orderUnit(unit, row, col, kind, target = null) {
  if (!unit || unit.alive === false) return false;
  const previous = unit.orderByte ?? 0;
  unit.orderByte = (kind & 0x0F) | (previous & 0xF0);
  unit.orderKind = kind;
  unit.orderRow = row;
  unit.orderCol = col;
  unit.orderTarget = target;
  // Флаг «занят приказом» (+0x19 | 0x40) ставит не выдача приказа, а
  // щелчок по земле и раздача приказа отряду (VA 0x4240BC и ветка 0x26
  // в 0x421690). Приказ по ЦЕЛИ — 0x61, поджог или атака — этот бит
  // наоборот СНИМАЕТ (маска 0xBF).
  const kinds = orderKinds();
  unit.busy = kind !== kinds.target;
  // НОВЫЙ ПРИКАЗ ОТМЕНЯЕТ СТАРЫЙ МАРШРУТ. Движок хранит в юните только
  // КЛЕТКУ НАЗНАЧЕНИЯ (+0x13 и +0x15), а дорогу к ней достраивает кусками
  // по шестнадцать шагов (VA 0x441441): перезаписал клетку — и следующий
  // кусок уже строится к ней. У нас же маршрут лежал целиком, и юнит
  // честно дотапывал до старой точки, прежде чем повернуть к новой.
  // Отсюда и «мейн пошёл сразу, а отряд добежал до прежнего места».
  unit.path = [];
  unit.goal = null;
  world.onOrder?.(unit, kind, row, col, target);
  return true;
}

// Приказ всем выбранным: движок сбрасывает каждому цель и ставит флаг
// «идёт по приказу» (VA 0x4240BC).
export function orderSelected(row, col, kind, running = false) {
  let given = 0;
  for (const unit of selection) {
    if (unit.alive === false) continue;
    unit.orderTarget = null;
    // Режим движения 1 ставит бит бега (VA 0x416641) — двойной щелчок
    // посылает бежать весь выбор, а не одного героя.
    unit.running = running;
    if (orderUnit(unit, row, col, kind)) given += 1;
  }
  return given;
}

// Достаточно ли близко подошли, чтобы заговорить: движок мерит
// прямоугольником в семь строк и четыре столбца (VA 0x4115AC).
export function withinTalk(one, two) {
  const set = rules()?.talk ?? { rows: 7, cols: 4 };
  if (!one?.cell || !two?.cell) return false;
  return Math.abs(one.cell.row - two.cell.row) < set.rows &&
         Math.abs(one.cell.col - two.cell.col) < set.cols;
}

// Приказ дошёл — что делать по прибытии. Возвращает вид приказа, если он
// сработал, иначе null.
export function orderArrived(unit, handlers = {}) {
  const kinds = orderKinds();
  const kind = unit.orderKind ?? kinds.none;
  if (kind === kinds.talk) {
    const target = unit.orderTarget;
    if (!target) { orderClear(unit); return null; }
    if (!withinTalk(unit, target)) return null;      // не дошли — идём дальше
    orderClear(unit);
    handlers.talk?.(unit, target);
    return kind;
  }
  if (kind === kinds.take) {
    // Цель движок в приказе НЕ хранит: раздача приказа обнуляет unit+0x10
    // (VA 0x4240BC), а дойдя, юнит ищет кучу ПО СВОЕЙ КЛЕТКЕ
    // (VA 0x4115AC -> 0x4149F8 перебирает кучи и сравнивает строку и
    // столбец). Поэтому сохранённая цель — лишь подсказка, и её отсутствие
    // не должно отменять обыск.
    const target = unit.orderTarget;
    const row = unit.orderRow ?? unit.cell?.row;
    const col = unit.orderCol ?? unit.cell?.col;
    orderClear(unit);
    handlers.take?.(unit, target, { row, col });
    return kind;
  }
  if (kind === kinds.go) { orderClear(unit); return kind; }
  return null;
}

// Завершение приказа (VA 0x416E24): цель обнуляется, а из байта приказа
// остаётся маска 0xB0 — то есть вместе с номером приказа снимается и бит
// 0x40. Маска 0xF0 сохраняла бы его и оставляла юнита «занятым».
export function orderClear(unit) {
  const kinds = orderKinds();
  unit.orderKind = kinds.none;
  unit.orderTarget = null;
  unit.busy = false;
  unit.orderByte = (unit.orderByte ?? 0) & 0xB0;
}

// Режим спутника — биты старшей половины. Ставим и снимаем по одному,
// как это делает движок.
export function setMode(unit, bit, on = true) {
  const byte = unit.orderByte ?? 0;
  unit.orderByte = on ? (byte | (bit & 0xF0)) : (byte & ~(bit & 0xF0));
}


// Ходит ли сейчас сам игрок. Ссылку на него модуль приказов не держит
// намеренно — иначе получился бы круг импортов hero <-> orders; игрока
// сюда кладёт selectionFallback при настройке боя.
export function heroSelected() {
  return !selection.length || (fallbackUnit != null && selection.includes(fallbackUnit));
}
