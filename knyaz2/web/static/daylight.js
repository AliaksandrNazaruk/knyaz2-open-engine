// Время суток: кривая уровней из движка, часы и подпись.
//
// Уровни каналов синий/зелёный/красный лежат в 0x58E2C8..CA; кривая снята с
// расписания VA 0x4295D8 и запечена в assets/daylight.json.
import { clockLabelNode, clockMoonNode, clockRunNode, clockTimeNode } from "./dom.js";
import { clock } from "./clock.js";
import { world } from "./world.js";

// ПОСТОЯННОЕ ОСВЕЩЕНИЕ КАРТЫ (таблица 0x4617B0, семь карт из 53).
//
// Загрузчик кладёт запись целиком в 0x8495A4, и расчёт освещения смотрит её
// ПЕРВЫМ делом: `if ([0x8495A4] == 0) { суточная кривая } else { уровень =
// таблица[карта] & 0xFFFFFF }` (VA 0x4295D8, строки 17 и 138). То есть на
// этих картах часы не спрашиваются вовсе — ни днём, ни ночью.
//
// Дворец Повелителя (1) и Лабиринт смерти (2) стоят на вечной глубокой ночи
// −70/−50/−50 со взведённым флагом локального света; пещеры 45..49 — на
// ровном −1/−1/−1 и БЕЗ флага. Порт раньше крутил там обычные сутки, и
// днём во дворце было светло.
function fixedLighting() {
  const fixed = world.map?.lighting?.fixed ?? null;
  return fixed?.frozen ? fixed : null;
}

// Уровни замороженной карты отдаём ОДНИМ И ТЕМ ЖЕ массивом: смена уровня
// проверяется сравнением по ссылке (clockTick), и свежий массив на каждый
// такт означал бы перерисовку сцены каждые 78 мс без всякой причины.
let frozenLevels = null, frozenFor = null;
function fixedLevels(fixed) {
  if (frozenFor !== fixed) {
    const { blue = 0, green = 0, red = 0 } = fixed.levels ?? {};
    frozenLevels = [blue, green, red];
    frozenFor = fixed;
  }
  return frozenLevels;
}

// День и ночь: кривая уровней (c8,c9,c10) эмулирована из konung2.exe
// (VA 0x4295D8) по всем 21600 тикам суток. Отрицательный уровень затемняет
// канал c*(1-L/100), положительный тянет к максимуму c+(255-c)*L/100 —
// формулы генератора канальных таблиц VA 0x43CA8B.
export const daylight = {
  period: 21600,
  curves: { moon: [], no_moon: [] },
  time: 4600,                 // старт днём
  levels: [0, 0, 0],
  // Время суток — ЭТО И ЕСТЬ мировой такт движка. Счётчик один: `0x84962C`
  // читают и кривая освещения (VA 0x4295D8), и фаза построек, и счётчик
  // работы жителя. Сутки — 21600 тактов, все пороги (закат 8100, рассвет
  // 18961, таблица фаз 0x45FC3C) заданы в тех же тактах.
  //
  // Раньше здесь стоял СВОЙ темп 6 тактов/с, чтобы сутки длились ровно час.
  // Это была не оптимизация, а подгонка темпа, и она расщепляла игру на двое
  // часов: мастерская и казна шли по этим, а стройка и юниты — по кадрам.
  // При каноничном такте 78 мс сутки длятся 21600 × 0.078 ≈ 28 минут.
  lastTick: 0,
  // Солнце над горизонтом: от рассвета (конец ночной кривой) до конца
  // заката; нужен только «живым теням» — нашему расширению.
  sunrise: 18961,
  sunset: 8100,
};

export function daylightCurve() {
  const moon = clockMoonNode.checked;
  const curve = daylight.curves[moon ? "moon" : "no_moon"];
  return curve.length ? curve : daylight.curves.moon;
}

export function daylightLevels(time) {
  // Карта с записью в таблице: уровень постоянный, кривая не читается.
  const fixed = fixedLighting();
  if (fixed) return fixedLevels(fixed);
  const curve = daylightCurve();
  if (!curve.length) return [0, 0, 0];
  let levels = curve[curve.length - 1][1];   // кривая кусочно-константна
  for (const [start, value] of curve) {
    if (start > time) break;
    levels = value;
  }
  return levels;
}

export function sunProgress(time) {
  const dayLength = (daylight.sunset + daylight.period - daylight.sunrise) %
    daylight.period;
  const since = (time - daylight.sunrise + daylight.period) % daylight.period;
  return since <= dayLength ? since / dayLength : null;
}

// Ночь ли сейчас. Движок держит это отдельным флагом (0x8495CC) и ставит
// его в той же функции, что считает цвет неба: до восхода и после заката —
// единица (VA 0x4295D8). По нему же разговоры выбирают ночные реплики.
export function isNight(time = daylight.time) {
  // На картах с постоянным светом флаг ночи — это СТАРШИЙ БАЙТ записи, а не
  // положение солнца: `[0x8495CC] = таблица[карта] & 0xFF000000` (VA
  // 0x4295D8, первая же строка). У дворца и лабиринта он стоит, у пещер нет.
  const fixed = fixedLighting();
  if (fixed) return Boolean(fixed.always);
  return sunProgress(time) === null;
}

export function daylightLabel(time) {
  const [b, g, r] = daylight.levels;
  const fixed = fixedLighting();
  if (fixed) return `без суток · R${r} G${g} B${b}`;
  const sun = sunProgress(time);
  let phase = "ночь";
  if (r === 0 && g === 0 && b === 0) phase = "день";
  else if (g > 0) phase = "полуденное солнце";
  else if (sun !== null) phase = "закат";
  else if (b > -70) phase = "сумерки";
  return `${phase} · R${r} G${g} B${b}`;
}

export function daylightSet(time) {
  daylight.time = ((time % daylight.period) + daylight.period) % daylight.period;
  daylight.levels = daylightLevels(daylight.time);
  clockTimeNode.value = String(Math.round(daylight.time));
  clockLabelNode.textContent = daylightLabel(daylight.time);
}

// Время суток двигается ровно на столько, на сколько шагнул мировой такт:
// один такт движка — одна единица времени (VA 0x438A00 увеличивает
// `_DAT_0084962c`, кривая освещения читает его же). Собственного темпа у
// суток больше нет.
export function clockTick(now) {
  daylight.lastTick = now;
  if (!clockRunNode.checked || !daylightCurve().length) return false;
  if (!clock.elapsed) return false;
  const before = daylight.levels;
  daylightSet(daylight.time + clock.elapsed);
  return before !== daylight.levels;
}
