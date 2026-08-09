// Постройки: пожар и стройка.
//
// Состояние постройки — не «есть / нет», а ступень лестницы (запись в
// поселении, байт +1):
//
//     0, 1, 2  строится      3  стоит      4, 5  горит      6  пепелище
//
// Движок и картинку берёт так же: спрайт вида плюс состояние (VA 0x4171CC),
// поэтому каждому виду отведено семь подряд идущих ресурсов. В паке они
// лежат у постройки в `states`.
//
// Ход ступеней считает мировой такт (VA 0x41C944): счётчик постройки
// убавляется, на нуле состояние растёт, и берётся новый срок — стройке из
// одного поля вида (делённый на число работников), пожару из другого.
// Догорело до шестой ступени — место очищается, и деревня строит заново.
import { world } from "./world.js";
import { preload } from "./content.js";

function rules() { return world.map?.hero?.rules?.buildings ?? null; }

export function buildingsSetup() {
  const set = rules();
  for (const object of world.objects ?? []) {
    if (!object.states) continue;
    object.state = object.village_state ?? set?.states?.ready ?? 3;
    object.timer = 0;
  }
}

// Какой вид у постройки — из списка поселения по её месту.
function kindOf(object) {
  const entry = (world.map?.village?.buildings ?? [])
    .find((row) => row.slot === object.village_slot);
  const kinds = rules()?.kinds ?? {};
  return entry ? kinds[String(entry.kind)] ?? null : null;
}

// Поджог зажигательной стрелой: движок бросает жребий и, если выпало,
// ставит постройке единицу в счётчик — гореть она начнёт со следующего
// такта (VA 0x41FDD0).
export function buildingIgnite(object, roll = Math.floor(Math.random() * 100)) {
  const set = rules();
  // Состояния движок здесь НЕ проверяет: жребий бросается по любой
  // постройке, попавшей под зажигательную стрелу (VA 0x41FDD0).
  if (!object?.states) return false;
  if (roll >= (set?.fire?.chance ?? 21)) return false;
  // Удачный жребий ставит постройке состояние 3 И счётчик 1:
  //   `local_58[1] = 3; local_58[6] = 1; local_58[7] = 0;` (VA 0x41FDD0).
  // Тройка — это «стоит», а не «горит»: пожар начинается на следующей фазе
  // построек, когда счётчик добежит до нуля и ступень станет четвёркой.
  // Без записи состояния поджог недостроя лишь ускорял стройку — он
  // получал счётчик 1 и доводил до конца текущую ступень.
  object.state = set?.states?.ready ?? 3;
  object.timer = set?.fire?.timer ?? 1;
  return true;
}

// Мировой такт постройки: та же лестница, что в движке.
export function buildingsTick(workers = 0) {
  const set = rules();
  if (!set) return false;
  const ready = set.states.ready;
  const ashes = set.states.ashes;
  let changed = false;
  for (const object of world.objects ?? []) {
    if (!object.states) continue;
    // Пепелище расчищают РУКИ: без свободных работников оно так и лежит
    // (VA 0x41D6xx, ветка состояния 6 под тем же `0 < работники`).
    if (object.state === ashes && !object.timer) {
      if (workers < 1) continue;
      object.state = 0;                       // место очистилось
      object.timer = buildTime(object, workers);
      changed = true;
      continue;
    }
    if (!object.timer) continue;
    // Стройка (ступени ниже «стоит») идёт только пока есть работники;
    // пожар тикает сам по себе.
    const building = object.state < ready;
    if (building && workers < 1) continue;
    object.timer -= 1;
    if (object.timer > 0) continue;
    object.state += 1;
    changed = true;
    if (object.state < ready) object.timer = buildTime(object, workers);
    else if (object.state > ready && object.state < ashes) {
      object.timer = kindOf(object)?.burn_step ?? 1;
    }
    // дошли до «стоит» или до пепелища — счётчик не заводится
    preload(Object.values(object.states[String(object.state)] ?? {})
      .map((frame) => frame.asset));
  }
  return changed;
}

// Срок ступени: время вида в минутах на число работников, делённое
// ЦЕЛОЧИСЛЕННО и без нижней границы (VA 0x41D8xx: `(base * 0x3C) / рук`).
// Звать его при нуле работников нельзя — в движке туда и не приходят.
function buildTime(object, workers) {
  const set = rules();
  const time = kindOf(object)?.build_time ?? 1;
  return Math.trunc((time * (set?.build_minute ?? 60)) / workers);
}

// Кадры постройки на её нынешней ступени. Пока картинки не подгрузились,
// показываем те, что пришли с картой.
export function buildingFrames(object) {
  const ladder = object.states?.[String(object.state)];
  if (!ladder) return object.frames;
  const ready = Object.values(ladder).every((frame) => world.images.has(frame.asset));
  return ready ? ladder : object.frames;
}

//: Горит ли постройка — по ней видно, что поджог удался.
export function buildingBurning(object) {
  const set = rules();
  const ready = set?.states?.ready ?? 3;
  const ashes = set?.states?.ashes ?? 6;
  // Пепелище уже не горит — оно то, что от пожара осталось.
  return Boolean(object.states) && object.state > ready && object.state < ashes;
}

// Постройка на клетке: движок держит номер объекта прямо в клетке карты,
// у нас есть след постройки в её записи.
export function buildingAtCell(row, col) {
  for (const object of world.objects ?? []) {
    if (!object.states) continue;
    if ((object.cells?.footprint ?? []).some(([r, c]) => r === row && c === col)) {
      return object;
    }
  }
  return null;
}
