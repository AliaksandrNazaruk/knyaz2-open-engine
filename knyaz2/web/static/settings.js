// Настройки игрока: игра читает то же, что пишет стартовое меню.
//
// ЭТО НЕ КАНОН. У движка настроек экрана нет вовсе (KONUNG2.CFG хранит только
// громкость и разрешение), и всё, что здесь заводится, — уступки браузеру и
// телефону. Поэтому правило простое: по умолчанию ВСЁ ВЫКЛЮЧЕНО, то есть без
// спроса игра ведёт себя ровно как оригинал.
//
// Меню — отдельная страница, общий у них только ключ localStorage. Читаем его
// один раз на запуске: вернуться в меню можно лишь через перезагрузку, так
// что разойтись значениям негде. Сложность и громкость сюда не попадают — их
// разбирают свои модули там, где они нужны.
import { DIFFICULTY, DIFFICULTY_DEFAULT, difficultyOf } from "./difficulty.js";

const SETTINGS_KEY = "knyaz2.settings";

export const settings = {
  //: ступень сложности — номер строки таблицы difficulty.js
  difficulty: DIFFICULTY_DEFAULT,
  //: камера держит выбранное лицо в середине окна
  follow: true,
  //: всегда бегом
  run: true,
  //: проситься во весь экран и набок
  fullscreen: true,
  //: идут ли сутки. Выключено — вечное позднее утро, см. DAY_FIXED
  daynight: true,
};

// ВРЕМЯ ПРИ ВЫКЛЮЧЕННЫХ СУТКАХ. В движке это одна из галочек KONUNG2.CFG:
// при нулевом `_DAT_008495B4` расчёт освещения первым же условием отдаёт
// уровень ноль (VA 0x4295D8), то есть день навсегда. Наши кривые говорят то
// же: подкраска [0,0,0] держится от начала суток до такта 1800, а дальше
// темнеет — граница сходится с порогом движка до двух тактов. Берём треть
// светлой полосы: солнце уже высоко, но тени ещё косые.
export const DAY_FIXED = 630;

//: Множители текущей ступени: опыт и стартовые деньги.
export function difficultyNow() { return difficultyOf(settings.difficulty); }

// ВСЕГДА ЛИ БЕГОМ. По умолчанию да — на телефоне двойное касание браузеры
// ловят как придётся, и без этого бег там был бы недоступен вовсе. Кому
// нужен канонический шаг с двойным щелчком, снимает галочку в меню.
export function runAlways() { return settings.run !== false; }

//: Идут ли сутки. Снятая галочка держит вечное позднее утро (DAY_FIXED).
export function dayNightRuns() { return settings.daynight !== false; }

export function settingsLoad() {
  let saved = null;
  try {
    const text = localStorage.getItem(SETTINGS_KEY);
    saved = text ? JSON.parse(text) : null;
  } catch {
    // хранилище недоступно или в нём мусор — остаёмся на значениях по умолчанию
  }
  if (typeof saved?.follow === "boolean") settings.follow = saved.follow;
  if (typeof saved?.run === "boolean") settings.run = saved.run;
  if (typeof saved?.fullscreen === "boolean") settings.fullscreen = saved.fullscreen;
  if (typeof saved?.daynight === "boolean") settings.daynight = saved.daynight;
  const step = saved?.difficulty;
  if (Number.isInteger(step) && step >= 0 && step < DIFFICULTY.length) {
    settings.difficulty = step;
  }
  return settings;
}
