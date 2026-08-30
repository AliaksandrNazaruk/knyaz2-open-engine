// Во весь экран и поворотом набок — насколько браузер вообще это позволяет.
//
// ЧЕГО НЕЛЬЗЯ. Сам по себе, при загрузке, полноэкранный режим не включается
// нигде: и `requestFullscreen`, и блокировка поворота требуют ЖЕСТА игрока.
// Поэтому просимся на первое же касание страницы, а не на её открытие.
//
// НА IPHONE НЕ РАБОТАЕТ НИЧЕГО ИЗ ЭТОГО. Safari на телефоне не умеет
// `requestFullscreen` (там во весь экран уходит только видео) и не знает
// `screen.orientation.lock` вовсе. Оба вызова здесь заканчиваются отказом, и
// это НОРМАЛЬНО: отказ гасится, игра идёт как шла, а книжную ориентацию
// перехватывает подсказка «поверните телефон» (styles.css). Настоящий
// полный экран на iPhone даёт только ярлык на домашний экран — для него и
// положен app.webmanifest с `display: fullscreen`.
//
// НА ANDROID РАБОТАЕТ ОБА. Порядок важен: поворот запирается ТОЛЬКО из
// полноэкранного режима, поэтому сперва экран, потом ориентация.
import { settings } from "./settings.js";

//: Просить ли. По умолчанию да; снявшему галочку не навязываемся.
export function fullscreenWanted() { return settings.fullscreen !== false; }

export function fullscreenNow() {
  return Boolean(document.fullscreenElement ?? document.webkitFullscreenElement);
}

async function enter() {
  const page = document.documentElement;
  const ask = page.requestFullscreen ?? page.webkitRequestFullscreen;
  if (!ask) return false;
  try {
    // navigationUI: браузер не рисует своих полосок поверх игры там, где умеет
    await ask.call(page, { navigationUI: "hide" });
  } catch {
    return false;                      // отказали — молча живём дальше
  }
  try {
    await screen.orientation?.lock?.("landscape");
  } catch {
    // Safari не знает блокировки, Android может отказать на планшете —
    // и то и другое не повод шуметь: игра уже развернулась во весь экран.
  }
  return true;
}

// Взвести ожидание жеста. Слушатели одноразовые: получилось — снялись сами,
// не получилось — снялись тоже, чтобы не дёргать отказ на каждое касание.
export function fullscreenArm() {
  if (!fullscreenWanted()) return false;
  const events = ["pointerdown", "keydown"];
  const attempt = () => {
    for (const name of events) window.removeEventListener(name, attempt);
    if (!fullscreenNow()) enter();
  };
  for (const name of events) {
    window.addEventListener(name, attempt, { once: true, passive: true });
  }
  return true;
}
