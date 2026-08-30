// Настоящее меню поверх игры — без ухода со страницы.
//
// ЗАЧЕМ. Стартовое меню живёт отдельной страницей, и путь «Esc — посмотрел —
// обратно» означал полную перезагрузку: заново 22 МБ общего блока пака,
// заново описание карты и заново сотни картинок, которые только что лежали
// разобранными в памяти. Заголовки у пака верные — адреса версионные,
// `immutable` на год, — но кэш браузера невелик, на телефоне тем более, и к
// возврату уже вытеснен. Оттого большие карты вроде Морского лагеря и
// тянулись «с нуля».
//
// РАЗМЕТКУ НЕ ДУБЛИРУЕМ. Меню втягивается тем же файлом `menu.html`: берём из
// него плиту целиком и кладём в накладку, следом подключаем его же стиль и
// его же модуль. Значит меню в игре и меню на своей странице — буквально одно
// и то же, и разъехаться им негде.
//
// Три пункта в игре ведут себя иначе, и решает это сам `menu.js` по наличию
// `#game` в разметке: «Продолжить» закрывает накладку, «Сохранить» сперва
// просит игру записаться, «Выход» уводит на стартовую страницу. «Загрузить» и
// «Новая игра» требуют другого мира целиком — им перезагрузка нужна по
// существу, и они остались как были.
import { world } from "./world.js";
import { settingsLoad } from "./settings.js";
import { perspective, perspectiveForced } from "./perspective.js";
import { view } from "./viewport.js";

const node = document.getElementById("game-menu");

let open = false;
let ready = null;

export function gameMenuOpen() { return open; }

//: Втягиваем меню при первом открытии, а не при запуске: на старте игре
//: дорога каждая миллисекунда, а меню может и не понадобиться.
async function prepare() {
  const page = await (await fetch("/menu.html")).text();
  const parsed = new DOMParser().parseFromString(page, "text/html");
  const stage = parsed.querySelector(".stage");
  if (!stage) throw new Error("в menu.html нет .stage");
  // Стиль меню подключаем перед разметкой, чтобы плита не мигнула голой.
  await new Promise((done, bad) => {
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "/menu.css";
    link.addEventListener("load", done, { once: true });
    link.addEventListener("error", bad, { once: true });
    document.head.append(link);
  });
  node.append(stage);
  document.addEventListener("menu:continue", () => gameMenuShow(false));
  document.addEventListener("menu:save", (event) => {
    const ok = world.onMenuSave?.();
    if (event.detail) event.detail.ok = ok;
  });
  document.addEventListener("menu:exit", () => world.leaveToMenu?.());
  //: Модуль меню сам находит свои узлы — они уже в документе.
  await import("./menu.js");
}

export function gameMenuShow(on = true) {
  if (!node) return false;
  if (on && !ready) {
    ready = prepare().catch((trouble) => {
      console.warn("меню не втянулось:", trouble);
      ready = null;
      //: Не вышло — уходим на страницу меню, как раньше. Хуже, но работает.
      world.leaveToMenu?.();
    });
  }
  //: Закрываясь, перечитываем настройки: меню пишет их в хранилище, а игра
  //: держит свою копию — без этого галочки срабатывали бы только с перезахода.
  if (!on && ready) {
    const свежие = settingsLoad();
    view.follow = свежие.follow;
    //: ПЕРСПЕКТИВА ТОЖЕ ЖИВАЯ. Модуль решает «включено или нет» при загрузке
    //: страницы, а игрок снимает галочку посреди игры — переносим сюда же.
    //: Адресную строку не трогаем: если перспективу задали параметром, она
    //: перебивает настройку и остаётся как задана.
    if (!perspectiveForced()) perspective.on = свежие.perspective !== false;
  }
  open = Boolean(on);
  node.hidden = !open;
  // Ролик и музыка меню играют только пока оно открыто.
  const film = node.querySelector(".frame__film");
  if (film) {
    if (open) film.play?.().catch(() => {});
    else film.pause?.();
  }
  //: Вернувшись в игру, пересчитываем раскладку и рисуем кадр. Пока накладка
  //: была открыта, кадры не собирались, а размеры могли смениться — поворотом
  //: телефона, полным экраном или просто окном.
  if (!open) world.onMenuClose?.();
  return open;
}

export function gameMenuToggle() { return gameMenuShow(!open); }
