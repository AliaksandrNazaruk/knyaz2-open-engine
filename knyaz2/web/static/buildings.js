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
import { heroStampBuilding } from "./hero.js";

function rules() { return world.map?.hero?.rules?.buildings ?? null; }

// ВХОД НА КАРТУ: объект берёт ступень у СВОЕГО МЕСТА, а не у пака.
//
// Так делает и движок. `0x43DF48` (строки 222-231) идёт по местам поселения
// (`+0x18`, шаг 8, число `slots_a + slots_b + 7`) и каждому месту с
// неотрицательным видом переставляет картинку его объекта:
//
//     *(int *)(&DAT_00834768 + место[2] * 0x24) =
//          (*(int *)(&DAT_0045D844 + вид * 0x10) >> 0x10) + ступень
//
// То есть ведущая запись — место, а объект лишь показывает его ступень.
// Номер объекта лежит в самом месте (`+2`, у нас поле `object`), но нам
// удобнее обратная связь: у объекта проставлен `village_slot`.
//
// Запись поселения при этом ПЕРЕЖИВАЕТ уход с карты (см. village.js), а
// `village_state` из пака — лишь начальное значение первого визита.
export function buildingsSetup() {
  const set = rules();
  const places = world.map?.village?.buildings ?? [];
  for (const object of world.objects ?? []) {
    if (!object.states) continue;
    const place = object.village_slot == null ? null
      : places.find((row) => row.slot === object.village_slot);
    if (place) {
      object.state = place.state ?? 0;
      object.timer = place.timer ?? 0;
      continue;
    }
    object.state = object.village_state ?? set?.states?.ready ?? 3;
    object.timer = 0;
  }
}

// Место поселения повторяет за своим объектом. В движке этого нет: там
// ступень и счётчик живут ТОЛЬКО в записи места (+0x19 и +0x1E), а объект
// карты лишь показывает их картинкой (0x4171CC). У нас две копии, и
// расходиться им нельзя — по записи места отвечают условия разговора 4
// «постройка есть» и 6 «можно заложить».
function placeFollow(object) {
  const place = (world.map?.village?.buildings ?? [])
    .find((entry) => entry.slot === object.village_slot);
  if (!place) return false;
  place.state = object.state;
  place.timer = object.timer;
  place.built = Boolean(object.state || object.timer);
  return true;
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

// ОДНА СТУПЕНЬКА ЛЕСТНИЦЫ — НАД ЗАПИСЬЮ МЕСТА, а не над объектом карты.
//
// В движке копия одна: ступень и счётчик живут в записи поселения (+0x19 и
// +0x1E), а объект карты по ним лишь перерисовывается (0x43DF48:222-231).
// Нам та же лестница нужна дважды — для построек видимой карты и для
// одиннадцати остальных поселений склада, — и разводить её в две копии
// нельзя: это ровно тот случай, когда один адрес движка получает двух
// владельцев и они расходятся.
//
// Возвращает, сдвинулось ли что-нибудь, и МЕНЯЕТ саму запись места.
export function placeStep(place, kind, workers, set) {
  const ready = set.states.ready;
  const ashes = set.states.ashes;
  // Пепелище расчищают РУКИ: без свободных работников оно так и лежит
  // (VA 0x41D6xx, ветка состояния 6 под тем же `0 < работники`).
  if (place.state === ashes && !place.timer) {
    if (workers < 1) return false;
    place.state = 0;                          // место очистилось
    place.timer = buildStepTime(kind, workers, set);
    return true;
  }
  if (!place.timer) return false;
  // Стройка (ступени ниже «стоит») идёт только пока есть работники;
  // пожар тикает сам по себе.
  //
  // ОТСТУПЛЕНИЕ ОТ КАНОНА, ОСОЗНАННОЕ. В движке недострой без работников не
  // замирает, а ДОГОРАЕТ по burn_step: 3 → 4 → 5 → 6, то есть отлучился —
  // и вместо кузницы пепелище. Мы держим паузу: тестеры и без того жалуются,
  // что стройка стоит, а канонное поведение наказывало бы их вдвое. Если
  // решим вернуть — менять здесь и только здесь.
  if (place.state < ready && workers < 1) return false;
  place.timer -= 1;
  if (place.timer > 0) return false;
  place.state += 1;
  if (place.state < ready) place.timer = buildStepTime(kind, workers, set);
  else if (place.state > ready && place.state < ashes) {
    place.timer = kind?.burn_step ?? 1;
  }
  return true;
}

//: Срок ступени по ВИДУ, а не по объекту: чужому поселению объекта не из чего
//: взять. Формула та же (VA 0x41D8xx).
function buildStepTime(kind, workers, set) {
  return Math.trunc(((kind?.build_time ?? 1) * (set?.build_minute ?? 60))
                    / Math.max(1, workers));
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
    // СЧЁТЧИК ПИШЕМ В МЕСТО КАЖДЫЙ ТАКТ, а не только на смене ступени. В
    // движке копии нет вовсе: счётчик живёт в самой записи места (+0x1E), и
    // условия разговора читают её. У нас копии две, и пока счётчик до конца
    // стройки оставался в объекте, место стояло с тем сроком, что положил
    // обработчик 40, — староста продолжал предлагать заложить то, что уже
    // строится.
    placeFollow(object);
    if (object.timer > 0) continue;
    object.state += 1;
    changed = true;
    if (object.state < ready) object.timer = buildTime(object, workers);
    else if (object.state > ready && object.state < ashes) {
      object.timer = kindOf(object)?.burn_step ?? 1;
    }
    // СТУПЕНЬ ПИШЕМ И В ЗАПИСЬ МЕСТА. В движке она одна: байт +0x19 записи
    // поселения, а объект карты рисуется по ней же. У нас копии две, и пока
    // ступень жила только в объекте, деревня не замечала построенного —
    // условие разговора 4 «есть ли постройка» отвечало нет и на готовой
    // казарме. «Есть» движок решает по двум полям: ступень или срок
    // ненулевые (VA 0x434AF0).
    // Клетки постройки открываются и закрываются по её ступени (0x43F178).
    heroStampBuilding(object, ready);
    placeFollow(object);
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
