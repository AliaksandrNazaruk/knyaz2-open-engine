// ОЖИВЛЕНИЕ ДИЗАЙНА ПОЛЬЗОВАТЕЛЯ (editor_design_raw.html из Claude
// Design). Файл дизайна — нетронутая истина вида: здесь он грузится,
// экраны 1a…1i становятся страницами одного приложения, а в их вёрстку
// вживляются данные живого API v2. Обновление дизайна — перезаливка
// raw-файла; монтаж держится за устойчивые якоря (подписи рейки,
// title-атрибуты, data-lucide иконки), а не за точные пиксели.
"use strict";

const API = "/editor/api";
const state = {
  map: null, mapName: "", screen: "1a", screens: {},
  brushTile: 0, cellBrush: "blocked", areaMode: false, area: null,
  place: null, terrain: null, cells: null, mapState: null,
  objPages: null, objByKey: null, bestiary: null, tilePage: 0,
  catalogPage: 0, picked: null,
  //: ОТКУДА НАЧНЁТСЯ ПРОБА. Клетка «играть отсюда» — своя у каждой
  //: карты, поэтому сбрасывается при открытии другой (см. openMap).
  //: `playPick` — взведён ли выбор точки: следующий щелчок по холсту
  //: не пойдёт экрану, а поставит старт.
  playFrom: null, playPick: false,
  //: ЧТО ВЫБРАНО — ОДНО ПОНЯТИЕ НА ВЕСЬ РЕДАКТОР: {вид, объект}.
  //: Полей было три (см. выбрать() ниже), и держать их в согласии
  //: приходилось руками в каждой точке входа.
  выбор: null,
  //: ПРОМАХИ ЯКОРЕЙ — САМАЯ ТИХАЯ ПОЛОМКА ЭТОГО РЕДАКТОРА. Живая логика
  //: ищет узлы макета по подписям и эвристикам («самый тесный контейнер
  //: со строками», «span с текстом Позиция»). Стоит подписи в макете
  //: измениться или эвристике промахнуться — орган просто НЕ НАХОДИТСЯ,
  //: и код молча ничего не делает: ошибки в консоли нет, экран выглядит
  //: целым, кнопка не отвечает. Так уже терялись «Ставить/Снимать» и
  //: все кисти на 1d, подсветка рейки, половина счётчиков. Считаем
  //: промахи вслух — по этому списку видно, цел ли монтаж, без того
  //: чтобы прощёлкивать все девять экранов руками.
  промахи: [],
  //: Что видно на холсте. СЛУЖЕБНАЯ РАЗМЕТКА СКРЫТА ПО УМОЛЧАНИЮ:
  //: красные ромбы глуши закрывали пол-карты, и первым вопросом к
  //: холсту было «что это за красные пиксели?». Редактор показывает
  //: игру, а разметку зажигает экран, который ею работает.
  слои: { тайлы: true, декор: true, вода: true, объекты: true,
          юниты: true, крыши: true, проходимость: false },
};

async function api(path, method = "GET", body = null) {
  const reply = await fetch(API + path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : null,
  }).then(r => r.json()).catch(err => ({ ok: false, note: String(err) }));
  if (!reply.ok && reply.note) status("✗ " + reply.note);
  return reply;
}
//: ЧТО ВЫБРАНО — ОДНО ПОНЯТИЕ НА ВЕСЬ РЕДАКТОР.
//:
//: Полей выбора было ТРИ: state.picked (объекты, юниты, декор),
//: state.pickedPile (кучи) и state.pickedKind (вид — иначе объект от
//: декора не отличить, поля у них одинаковые). Держать их в согласии
//: приходилось руками в КАЖДОЙ точке входа: клик по холсту, клик по
//: строке списка, удержание для переноса, Ins, Del, кнопки инспектора,
//: стрелки. Где-нибудь да забывали: «Дубль» не видел кучу, выбранную в
//: списке; Delete по ней уходил в `/objects/undefined`; панели
//: показывали не то, что выбрано. Теперь одно поле и один вход.
function choose(kindOf, objectRec) {
  state.выбор = objectRec ? { вид: kindOf, объект: objectRec } : null;
}
function clearPick() { state.выбор = null; }
//: Выбранное, но только НУЖНОГО ВИДА: экран не должен оперировать
//: чужим. На экране кладов «Убрать» не убирает избу, даже если она
//: осталась выбранной с прошлого экрана.
function selectedOf(...kinds) {
  const it = state.выбор;
  if (!it) return null;
  return (!kinds.length || kinds.includes(it.вид)) ? it.объект : null;
}
function pickKind() { return state.выбор?.вид || null; }
function isChosen(objectRec) {
  return Boolean(objectRec) && state.выбор?.объект === objectRec;
}
//: Промах якоря: и в консоль, и в список — см. state.промахи выше.
function miss(where2, what) {
  state.промахи.push({ экран: state.screen, где: where2, что: String(what) });
  console.warn(`[редактор] не нашёл «${what}» (${where2}) на экране ` +
               `${state.screen}`);
}
//: «31 видов» читается как машинный вывод и подрывает доверие ко всему
//: остальному на экране. Три формы: 1 вид, 2 вида, 5 видов; 11…14 —
//: всегда третья.
function plural(number2, wordForms) {
  const n2 = Math.abs(number2) % 100;
  if (n2 >= 11 && n2 <= 14) return wordForms[2];
  const e3 = n2 % 10;
  return e3 === 1 ? wordForms[0] : (e3 >= 2 && e3 <= 4 ? wordForms[1] : wordForms[2]);
}
function status(text) {
  state.statusText = text;
  for (const nodeEl of document.querySelectorAll("[data-live-status]")) {
    nodeEl.textContent = text;
  }
}

// ── полифил компонентов дизайн-системы (их бандл живёт на хостинге
//    Claude и сюда не приедет) ────────────────────────────────────────────
const BADGE_COLOR = { ok: "#16a34a", warn: "#d97706", err: "#dc2626",
                      info: "#2563eb", neutral: "#64748b" };
function fillImports(root2) {
  for (const nodeEl of [...root2.querySelectorAll("x-import")]) {
    const typeNum = (nodeEl.getAttribute("component-from-global-scope") || "")
      .split(".").pop();
    const label = nodeEl.getAttribute("label")
      || nodeEl.textContent.trim();
    let repl;
    if (typeNum === "ActionButton") {
      repl = document.createElement("button");
      repl.textContent = label;
      const primary = nodeEl.getAttribute("variant") === "primary";
      repl.style.cssText =
        "font:600 12px 'IBM Plex Sans',sans-serif;padding:5px 12px;" +
        "border-radius:5px;cursor:pointer;border:1px solid " +
        (primary ? "#2563eb;background:#2563eb;color:#fff"
                  : "rgba(2,6,23,.2);background:#fff;color:#0f172a");
    } else if (typeNum === "StatusBadge") {
      repl = document.createElement("span");
      repl.textContent = label;
      const paintColor = BADGE_COLOR[nodeEl.getAttribute("family")] || "#64748b";
      repl.style.cssText =
        "font:600 10px 'IBM Plex Mono',monospace;padding:2px 7px;" +
        `border-radius:999px;color:${paintColor};border:1px solid ${paintColor}55;` +
        `background:${paintColor}18;white-space:nowrap`;
    } else {
      repl = document.createElement("div");
      repl.textContent = nodeEl.getAttribute("message") || label;
      repl.style.cssText =
        "font:12px 'IBM Plex Sans';padding:6px 10px;border-radius:5px;" +
        "background:#fef3c7;color:#92400e";
    }
    repl.setAttribute("data-live-badge", label);
    nodeEl.replaceWith(repl);
  }
}

// ── загрузка дизайна ─────────────────────────────────────────────────────
async function loadDesign() {
  const txt = await fetch("editor_design_raw.html").then(r => r.text());
  const doc2 = new DOMParser().parseFromString(txt, "text/html");
  //: КАРТИНКИ МАКЕТА ЛОМАЛИСЬ ВСЕ ДО ОДНОЙ. В дизайне 89 тегов
  //: `<img src="assets/…">` с ОТНОСИТЕЛЬНЫМ путём; страница отдаётся с
  //: `/editor.html`, и браузер просил `/assets/…` — там 404 и серый
  //: значок битой картинки. Это и были «битые иконки» в составе кучи и
  //: в карточках тайла воды: не наши списки, а неподменённая вёрстка
  //: макета.
  //:
  //: Часть путей живёт в паке (`/content/assets/icons/52.png` отдаётся),
  //: часть дизайнер выдумал под макет (`assets/obj/100.png`) и её нет
  //: нигде. Поэтому два шага: сперва переносим ссылку в пак, а если и
  //: там пусто — УБИРАЕМ картинку совсем. Пустое место честнее значка
  //: поломки: по нему человек решает, что сломан редактор.
  for (const im of doc2.querySelectorAll('img[src^="assets/"]')) {
    im.setAttribute("src", "/content/" + im.getAttribute("src"));
    im.setAttribute("data-lv-макет", "1");
  }
  for (const optEl of doc2.querySelectorAll(".dv-opt[id]")) {
    const card = optEl.querySelector(".dv-card");
    if (card) state.screens[optEl.id] = card;
  }
  //: ЭКРАН ОТРЯДОВ — СВОЙ, ЕГО В МАКЕТЕ НЕТ. Вкладка «Отряды» вела на
  //: экран существ (1f) и не меняла в нём ровно ничего: человек искал,
  //: где собрать отряд и назначить вражду, и попадал в бестиарий.
  //: Отряд — не юнит: у него своя сторона, свои биты войны, зона
  //: появления и зона гуляния, и правятся они отдельно от бойцов.
  //:
  //: Берём КЛОН карточки существ как оболочку: в ней уже есть топбар,
  //: рейка вкладок, холст и две колонки нужной ширины — то есть весь
  //: каркас, который иначе пришлось бы рисовать заново и мимо стиля
  //: макета. Содержимое колонок заменяет жизнь1j.
  if (state.screens["1f"] && !state.screens["1j"]) {
    state.screens["1j"] = state.screens["1f"].cloneNode(true);
  }
  //: ЭКРАН ДЕРЕВНИ — ТОЖЕ СВОЙ. Поселения в редакторе не было вовсе,
  //: хотя это половина игры: постройки, должности, прилавки, казна,
  //: ополчение. Каркас берём тем же клоном.
  if (state.screens["1f"] && !state.screens["1k"]) {
    state.screens["1k"] = state.screens["1f"].cloneNode(true);
  }
  designPolyfill(doc2);
  // не сносим уже успешно показанный экран (см. показанУспешноХотьРаз
  // выше) — но честно выполняем то, что просили показать до того, как
  // дизайн был готов, вместо молчаливого «1a» по умолчанию
  if (!shownOnce) showScreen(state.желаемыйЭкран || "1a");
  status("живой API подключён · выберите карту");
}
function designPolyfill(doc2) {
  // переносим keyframes из дизайна (пульс валидатора и т.п.)
  for (const style2 of doc2.querySelectorAll("style")) {
    document.head.appendChild(style2.cloneNode(true));
  }
}

//: ГОНКА ПРИ ХОЛОДНОМ СТАРТЕ. загрузитьДизайн() грузит editor_design_
//: raw.html асинхронно (внешний <script src> lucide перед editor_live.js
//: в editor.html может держать выполнение секундами) и в конце сама
//: зовёт показать("1a") — БЕЗУСЛОВНО. Если что-то успело позвать
//: показать(имя) РАНЬШЕ, чем этот fetch пришёл (сеть игрока, авто-
//: запуск, второй заход на уже открытой вкладке), то либо (а) ранний
//: вызов бьёт по пустому ещё state.screens и тихо проваливается без
//: единой попытки повтора — намерение просто теряется, либо (б) он
//: успевает сработать (state.screens уже полон), а следом бутстрап всё
//: равно СНОСИТ #stage обратно на "1a" — showScreen уже правильно
//: выбранный экран (со свежесозданным холстом) внезапно пропадает без
//: замены. Оба хвоста одной гонки лечатся одним флагом: помним, что
//: реально показали, и запоминаем, что ХОТЕЛИ показать, если рано.
let shownOnce = false;
//: Картинка макета, которой нет и в паке, прячется целиком: серый значок
//: поломки читается как «редактор сломан», пустое место — как «здесь
//: пока пусто». Вешаем один раз на карточку, повторный показ пропускаем.
function hideBrokenImages(card) {
  for (const im of card.querySelectorAll("img[data-lv-макет]")) {
    if (im.dataset.lvПроверена) continue;
    im.dataset.lvПроверена = "1";
    const hideIt = () => { im.style.visibility = "hidden"; };
    im.addEventListener("error", hideIt);
    if (im.complete && im.naturalWidth === 0) hideIt();
  }
}

//: ПРАВАЯ ПАНЕЛЬ — ИНСПЕКТОР ВЫБРАННОГО, и она нужна: там числа юнита,
//: состав кучи, биты клетки. Но занимает она треть экрана ВСЕГДА, в том
//: числе когда не выбрано ничего и смотреть в ней нечего, — а карта в
//: это время ужата. Поэтому её можно свернуть, и выбор держится между
//: экранами: язычок у края отдаёт место холсту и возвращает обратно.
function rightPanelFolding(card) {
  const columns2 = [...card.querySelectorAll("div")].filter(el =>
    /width:\s*320px/.test(el.getAttribute("style") || ""));
  if (!columns2.length) return;
  const tab2 = document.createElement("div");
  const paint = () => {
    const folded = Boolean(state.правойПанелиНет);
    for (const k2 of columns2) k2.style.display = folded ? "none" : "";
    tab2.textContent = folded ? "‹ инспектор" : "инспектор ›";
    tab2.title = folded
      ? "показать правую панель: числа выбранного, состав кучи, биты клетки"
      : "свернуть правую панель и отдать место карте";
    tab2.style.cssText =
      "position:absolute;top:64px;right:0;z-index:6;cursor:pointer;" +
      "padding:6px 8px;border-radius:7px 0 0 7px;font:600 10px " +
      "'IBM Plex Sans';border:1px solid #cbd5e1;border-right:none;" +
      "background:" + (folded ? "#2563eb" : "#f8fafc") +
      ";color:" + (folded ? "#fff" : "#334155");
  };
  tab2.onclick = () => {
    state.правойПанелиНет = !state.правойПанелиНет;
    paint();
    fitCard(card);
    //: ХОЛСТ НАДО ПЕРЕСНЯТЬ. Место освободилось, но канва держит прежний
    //: размер: без этого сворачивание отдавало пустоту, а карта
    //: оставалась в старой рамке. Тот же сигнал шлёт обработчик resize.
    card.querySelector("canvas")
      ?.dispatchEvent(new CustomEvent("lv-переснять"));
    status(state.правойПанелиНет
      ? "правая панель свёрнута — место отдано карте"
      : "правая панель развёрнута");
  };
  paint();
  const frameBox = card.firstElementChild || card;
  if (getComputedStyle(frameBox).position === "static") {
    frameBox.style.position = "relative";
  }
  insertOwn(frameBox, tab2, "язычок-инспектора");
}

function showScreen(nm) {
  if (nm === "story") { storyPanel(); return; }
  const card = state.screens[nm];
  if (!card) {
    state.желаемыйЭкран = nm;
    status("экрана " + nm + " нет в дизайне");
    return;
  }
  shownOnce = true;
  //: ИНСТРУМЕНТ НЕ ПЕРЕЖИВАЕТ СМЕНУ ЭКРАНА, если на новом ему нечего
  //: делать. Живая проверка: взведённая «Новая куча» тихо пережила уход
  //: на «Проходимость», и Esc там гасил «расстановку», которой на
  //: экране не видно, — режим-невидимка. Инструменты постановки живут
  //: каждый на своём экране; уходим с него — инструмент разряжается.
  const PLACE_SCREEN = { unit: "1f", object: "1b", decor: "1b",
                         loot: "1g" };
  if (state.place && PLACE_SCREEN[state.place.kind] !== nm &&
      state.screen !== nm) {
    state.place = null;
  }
  if (nm !== "1d" && state.screen !== nm) {
    state.exitArm = null; state.exitCorner = null;
    state.areaMode = false; state.area = null;
  }
  state.screen = nm;
  const sceneEl = document.getElementById("stage");
  sceneEl.replaceChildren(card);
  hideBrokenImages(card);
  rightPanelFolding(card);
  fillImports(card);
  fitCard(card);
  window.lucide?.createIcons?.();
  // масштаб пересчитываем ПОСЛЕ оживления: живые списки и свои органы
  // меняют ширину карточки, и посчитанный заранее масштаб оставлял
  // правую панель за краем экрана
  const missesBefore = state.промахи.length;
  wakeScreen(nm, card).then(() => {
    fitCard(card);
    showMisses(card, state.промахи.slice(missesBefore));
    //: СТРОКА СОСТОЯНИЯ ГОВОРИТ, ГДЕ ТЫ И ЧТО ДЕЛАТЬ. Прежде она хранила
    //: сообщение с ПРОШЛОГО экрана: перешёл на «Клады» — внизу висит
    //: «объект 30 · запись 4», перешёл на «Объект» — «кисть клеток:
    //: Глушь». Человек читает её как подсказку к тому, что перед ним, и
    //: делает неверный вывод. Экраны, которые сами говорят при входе
    //: (проверки, сборка), не перебиваем.
    //: ПОДСКАЗКА ТОГО ЭКРАНА, ГДЕ МЫ СЕЙЧАС. Оживление асинхронно, и
    //: медленный экран договаривал свою подсказку уже поверх следующего:
    //: открыл карту — а внизу «выберите карту в списке».
    //: у экрана 1b подсказка зависит от режима: «Объект» и «Декор» — одна
    //: карточка, но разные таблицы карты, и человек должен видеть, куда
    //: попадёт его щелчок
    const hint = typeof SCREEN_HINT[nm] === "function"
      ? SCREEN_HINT[nm]() : SCREEN_HINT[nm];
    const spot = nm === "1b" ? nm + (state.decorMode ? ":декор" : ":объект") : nm;
    if (hint && state.screen === nm && state.лоцманЭкрана !== spot) {
      state.лоцманЭкрана = spot;
      //: НА КАРТЕ ИЗ ИГРЫ ПОДСКАЗКА ОБЕЩАЛА БЫ НЕВОЗМОЖНОЕ: «щёлкните по
      //: карте — поставит», а сервер откажет защитой канона. Говорим об
      //: этом сразу, а не после первого напрасного щелчка.
      const lock = state.editable === false &&
        ["1b", "1c", "1d", "1e", "1f", "1g"].includes(nm);
      status(hint + (lock ? " · но карта из игры: сперва «Скопировать в " +
                            "свою карту» в жёлтой полосе" : ""));
    }
  });
}

//: Что делать на экране — одной строкой, языком действия.
const SCREEN_HINT = {
  //: Подпись говорила «двойной щелчок», а карточка открывается ОДИНАРНЫМ
  //: (screen1a: nodeEl.onclick) — человек стучал дважды и попадал в
  //: карточку второй раз уже на другом экране.
  "1a": "щёлкните карту — откроется её слой объектов; подписи в карточке " +
        "(объекты, юниты, отряды, клады) открывают сразу свой экран",
  "1b": () => (state.decorMode
    ? "режим ДЕКОРА (берега, кувшинки, камыши — таблица T_DYNAMIC): " +
      "щёлкните картинку в каталоге, потом по карте — ляжет серединой " +
      "под курсор; стоящий декор выбирается, возится (удержание) и " +
      "убирается (Del)"
    : "режим ОБЪЕКТОВ: щёлкните образец в каталоге, потом по карте — " +
      "поставит; щелчок по стоящему выбирает его, удержание возит, " +
      "Del убирает"),
  "1c": "возьмите тайл в каталоге (или Ins — взять под курсором) и " +
        "красьте по карте; ПКМ стирает, Ctrl+Z отменяет",
  "1d": "выберите кисть признака слева, потом красьте: ЛКМ ставит, " +
        "ПКМ снимает; Shift+клик — прямоугольник",
  "1e": "ЛКМ заливает клетку 256x256 водой, ПКМ осушает; тип воды и " +
        "тайл подложки — справа",
  "1f": "выберите вид в бестиарии (и масть под ним), потом щёлкните по " +
        "карте; кнопка «отряд» начнёт новый отряд",
  "1g": "«Новая куча» — потом щелчок по карте; щелчок по куче открывает " +
        "её состав",
  "1h": "здесь собирается пак этой карты — жмите сборку и следите за " +
        "журналом",
  "1i": "проверки карты: список слева, щелчок по строке ведёт к месту",
  "1j": "отряды карты: выберите отряд слева, зона и враждебность — справа",
  "1k": "поселение карты: постройки и жители — списком слева",
};

//: ПРОМАХ МОНТАЖА ВИДЕН ЧЕЛОВЕКУ, А НЕ ТОЛЬКО КОНСОЛИ.
//:
//: `промах()` складывал находки в `state.промахи` — список, который не
//: читала ни одна строка. А на экране при этом оставалась вёрстка
//: дизайнера с его выдуманными данными: «55 · изба», «23 породы»,
//: «498/512». То есть неподключённый блок выглядел РАБОЧИМ, и узнать о
//: поломке можно было, только начав им пользоваться.
//:
//: Плашка не чинит монтаж — она отнимает у поломки маскировку.
function showMisses(card, misses) {
  const frameBox = card.firstElementChild || card;
  if (!misses.length) {
    frameBox.querySelector('[data-lv="плашка-промахов"]')?.remove();
    return;
  }
  const banner = document.createElement("div");
  banner.style.cssText =
    "margin:6px 12px;padding:8px 10px;border-radius:7px;" +
    "background:#fef2f2;border:1px solid #fecaca;color:#991b1b;" +
    "font:600 11px 'IBM Plex Sans';line-height:1.4";
  banner.textContent =
    `не подключено блоков: ${misses.length} — ` +
    misses.map(p2 => p2.что).join(", ") +
    ". Всё, что ниже, может быть вёрсткой макета, а не вашими данными.";
  insertOwn(frameBox, banner, "плашка-промахов", frameBox.firstElementChild);
}
//: МАКЕТ ШИРЕ ОКНА, И ЕГО НАДО ВМЕСТИТЬ ЦЕЛИКОМ. Ширину брали из
//: инлайн-стиля рамки, а он есть не у всех экранов: без него бралось
//: 1600 «на глаз», масштаб выходил больше нужного и правая панель
//: (инспектор юнита, отряд) уезжала за край экрана. Меряем РЕАЛЬНУЮ
//: ширину содержимого и подгоняем высоту сцены под масштаб, иначе
//: внизу остаётся пустая полоса от исходной высоты.
//: РЕЗИНОВАЯ ВЁРСТКА ВМЕСТО transform: scale.
//:
//: Макет выгружен с жёсткими размерами: у карточки и её рамки стоит
//: width:1600px, height:860px. Раньше мы подгоняли это под окно
//: масштабированием всей карточки — и получали ровно то, чем костыль
//: и кончается: замыленный текст, экранные точки не равны точкам
//: вёрстки, пересчёт координат в каждом клике и пустые поля по краям.
//:
//: Правильно — снять фиксированные размеры и дать flex-колонкам
//: растянуться самим: колонки внутри макета РЕЗИНОВЫЕ (flex), им
//: просто не давали расти. Тогда html занимает окно без единого
//: множителя, а холст берёт своё место в CSS-точках.
function fitCard(card) {
  card.style.transform = "";
  card.style.transformOrigin = "";
  card.style.width = "100%";
  card.style.maxWidth = "100%";
  const frameBox = card.firstElementChild;
  if (frameBox) {
    frameBox.style.width = "100%";
    frameBox.style.maxWidth = "100%";
    // высота макета тоже жёсткая (860…940) — пусть тянется до низа окна
    frameBox.style.height = "auto";
    frameBox.style.minHeight =
      Math.max(420, window.innerHeight -
                    card.getBoundingClientRect().top - 4) + "px";
  }
  // ФИКСИРОВАННЫЕ ШИРИНЫ ВНУТРИ. Колонка холста и панели несут свои
  // width — снимаем их только у тех, кто должен тянуться (у колонки с
  // холстом), остальным оставляем: это их вёрстка.
  for (const el of card.querySelectorAll("div,section,aside")) {
    const sp = getComputedStyle(el);
    if (sp.overflow === "hidden" || sp.overflowX === "hidden") {
      if (el.style.overflowY !== "auto") {
        el.style.overflow = "visible";
        el.style.overflowX = "visible";
      }
    }
    if (el.style.width && el.style.width.endsWith("px") &&
        parseInt(el.style.width) >= 1200) {
      el.style.width = "100%";        // это рамки-строки макета
      el.style.maxWidth = "100%";
    }
  }
  const sceneEl = document.getElementById("stage");
  if (sceneEl) {
    sceneEl.style.height = "";
    sceneEl.style.overflow = "auto";
    sceneEl.style.display = "block";
  }
}
window.addEventListener("resize", () => {
  const card = document.querySelector("#stage .dv-card");
  if (card) fitCard(card);
  // холст живёт по месту: после смены размеров окна его надо
  // переснять и перерисовать, иначе карта останется в прежней рамке
  document.querySelector("#stage .dv-card canvas")
    ?.dispatchEvent(new CustomEvent("lv-переснять"));
});

// ── общие живые крепления каждого экрана ─────────────────────────────────
//: ОРГАН ДИЗАЙНА, А НЕ СВОЯ КНОПКА РЯДОМ. Первый заход подставлял свои
//: стрелки и поля рядом с нарисованными — пользователь жал НАРИСОВАННЫЕ,
//: и редактор выглядел мёртвым. Ищем узел по подписи и вешаем обработчик
//: на него самого и на его рамку (клик часто приходится по рамке).
//: `тихо` — для перебора вариантов имени (см. органЛюбой): промах
//: одного варианта из трёх это не поломка, а норма поиска.
function organOf(card, label, strict2 = true, quiet = false) {
  // ≤1 ребёнка: у кнопок макета внутри лежит иконка lucide («⌫ ластик»),
  // и строгое «детей нет» их не находило.
  //
  // СНАЧАЛА ТОЧНОЕ СОВПАДЕНИЕ, И ТОЛЬКО ПОТОМ ПО НАЧАЛУ: иначе короткая
  // подпись хватает чужую строку — кнопка размера кисти «3» доставалась
  // заголовку «3 правки вне пака», и размер не переключался.
  const nodes2 = [...card.querySelectorAll("div,span,button")]
    .filter(el => el.childElementCount <= 1);
  const nodeEl = nodes2.find(el => el.textContent.trim() === label) ||
    (strict2 ? null
           : nodes2.find(el => el.textContent.trim().startsWith(label)));
  if (!nodeEl) { if (!quiet) miss("орган", label); return null; }
  // РАМКА — ТОЛЬКО СВОЯ. Родитель берётся, лишь если он не общий с
  // другими кнопками: иначе обработчик садится на контейнер, и клик по
  // СОСЕДНЕЙ кнопке вызывает чужое действие («Убрать» заодно создавал
  // новую кучу, потому что делил рамку с «Новой кучей»).
  const parentEl = nodeEl.parentElement;
  const common2 = parentEl && (parentEl.querySelectorAll("button").length > 1 ||
    (parentEl.querySelectorAll("button").length === 1 &&
     nodeEl.tagName !== "BUTTON" && !nodeEl.closest("button")));
  const frameBox = nodeEl.closest("button") ||
    (parentEl && parentEl.childElementCount <= 3 && !common2
      ? parentEl : nodeEl);
  return { узел: nodeEl, рамка: frameBox };
}
//: ЗНАЧЕНИЕ РЯДА «подпись … значение» — инспекторы клетки/объекта/юнита
//: /кучи сплошь так устроены: слева серая подпись, справа живое число.
//: Подпись ищем ТОЧНО (короткие подписи вроде «Позиция» иначе цепляют
//: чужую строку) и берём следующего соседа — это и есть узел значения.
function rowValue(card, label) {
  const mark = [...card.querySelectorAll("span")]
    .find(el => el.childElementCount === 0 && el.textContent.trim() === label);
  if (!mark) { miss("значениеРяда", label); return null; }
  if (!mark.nextElementSibling) {
    miss("значениеРяда: нет соседа-значения", label);
    return null;
  }
  return mark.nextElementSibling;
}
//: СВОЙ ОРГАН ВСТАВЛЯЕТСЯ ОДИН РАЗ. Экран показывается много раз, а
//: карточка дизайна живёт между показами: вставки копились, и кнопка
//: «сменить на мирный» размножилась на полэкрана, а селект мира — в
//: четыре штуки. Помечаем свои узлы ключом и убираем прежний.
function insertOwn(parentEl, nodeEl, key2, beforeEl = null) {
  if (!parentEl) return null;
  for (const older of parentEl.querySelectorAll(`[data-lv="${key2}"]`)) {
    older.remove();
  }
  nodeEl.dataset.lv = key2;
  if (beforeEl && beforeEl.parentElement === parentEl) {
    parentEl.insertBefore(nodeEl, beforeEl);
  } else {
    parentEl.appendChild(nodeEl);
  }
  return nodeEl;
}
function bindTo(aim, handler2) {
  if (!aim) return;
  // ВСПЛЫТИЕ СЧИТАЕТ КЛИК ДВАЖДЫ. Обработчик висит и на подписи, и на
  // её рамке (клик приходится то туда, то сюда) — без остановки клик по
  // подписи срабатывал ещё раз на рамке, и переключатель с логикой
  // «повторный клик снимает» гасил сам себя.
  const single = (ev) => { ev?.stopPropagation?.(); handler2(ev); };
  for (const el of new Set([aim.узел, aim.рамка])) {
    el.style.cursor = "pointer";
    el.onclick = single;
  }
}
//: Сегментный переключатель: подписи в одной строке, активная подсвечена
//: тёмным (как «Нижний» и «Бестиарий» в макете).
function toggleOf(card, captions, activeOne, choose) {
  // подпись сегмента часто несёт счётчик («Жители пака · 46», «кучи · 8»)
  // — точное сравнение их не находило, и половина тумблеров молчала
  const targets = captions.map(p2 => [p2, organOf(card, p2, false)]);
  //: тумблер без единого найденного сегмента — это мёртвый
  //: переключатель, и молчать о нём нельзя (орган уже сообщил о каждом
  //: сегменте по отдельности, здесь важен сам факт «нет ни одного»)
  if (!targets.some(([, aim]) => aim)) {
    miss("тумблер целиком", captions.join("/"));
  }
  // РАМКА, ОБЩАЯ НА НЕСКОЛЬКО СЕГМЕНТОВ, — НЕ РАМКА ОДНОГО ПУНКТА.
  // орган() поднимается к предку с ≤3 детьми в поисках «своей строки»
  // (это верно для одиночной кнопки вроде «Клон · Ins»), но группа из
  // 2-3 сегментов тумблера САМА держит ≤3 детей — и все сегменты
  // получают ОДИН И ТОТ ЖЕ общий контейнер вместо личной пилюли.
  // Крашенный трижды подряд один узел визуально не меняется вовсе
  // (он позади всех пилюль), а цвет текста при этом красится верно —
  // отсюда «текст читается только у той пилюли, что была активна в
  // макете изначально» на 1a/1b/1c/1f. Обнаруживаем это по счётчику
  // ссылок и в этом случае красим САМ узел, а не разделяемого предка.
  const frameTally = new Map();
  for (const [, aim] of targets) {
    if (aim) frameTally.set(aim.рамка, (frameTally.get(aim.рамка) || 0) + 1);
  }
  function highlight(currentCell) {
    for (const [label, aim] of targets) {
      if (!aim) continue;
      const own = label === currentCell;
      const ownFrame = (frameTally.get(aim.рамка) || 0) <= 1;
      const repaint = ownFrame ? aim.рамка : aim.узел;
      repaint.style.background = own ? "#0f172a" : "transparent";
      repaint.style.color = own ? "#f8fafc" : "";
      if (!ownFrame) {
        // без общей рамки пилюля не наследует её паддинг/скругление —
        // добавляем минимум, иначе покраска — тонкая полоска под текстом
        repaint.style.padding = "2px 8px";
        repaint.style.borderRadius = "5px";
        repaint.style.display = "inline-block";
      }
      aim.узел.style.color = own ? "#f8fafc" : "";
    }
  }
  for (const [label, aim] of targets) {
    bindTo(aim, () => { highlight(label); choose(label); });
  }
  highlight(activeOne);
  return highlight;
}
//: Живое поле поверх нарисованного «инпута» макета.
//: ПОЛЕ ПЕРЕЖИВАЕТ ПОВТОРНЫЙ ЗАХОД НА ЭКРАН.
//:
//: Карточка экрана — ОДИН И ТОТ ЖЕ DOM-узел на все показы. Первый заход
//: подменял нарисованную подпись на настоящий <input> — и на втором
//: заходе подпись уже не находилась (её съел сам input), поле молча
//: оставалось с обработчиком ПЕРВОГО захода, замкнутым на прежние
//: списки и функции. Ровно этот класс однажды уничтожил экран
//: валидатора. Помечаем своё поле и переподключаем найденное, а не
//: ищем исчезнувшую подпись.
//:
//: `найти` — как отыскать подпись макета в ПЕРВЫЙ раз (у экранов она
//: ищется по-разному), зовётся только когда своего поля ещё нет.
function liveField(card, key2, seek, hint2, onInput) {
  if (!card) return null;
  const mark = "поле-" + key2;
  let field = card.querySelector(`input[data-lv="${mark}"]`);
  if (!field) {
    const mockup = seek();
    if (!mockup) { miss("живоеПоле", key2); return null; }
    field = document.createElement("input");
    field.dataset.lv = mark;
    field.placeholder = hint2 || mockup.textContent.trim();
    field.style.cssText = "width:100%;height:100%;border:0;outline:none;" +
      "background:transparent;font:inherit;color:inherit";
    mockup.replaceChildren(field);
  }
  field.oninput = () => onInput(field.value.trim().toLowerCase());
  return field;
}
//: ЗОНА НАХОДИТСЯ ОДИН РАЗ И ПОМЕЧАЕТСЯ.
//:
//: Списки, гриды и палитры ищутся в макете геометрией: «самый тесный
//: контейнер шириной меньше 470 с тремя строками, где есть pile_»,
//: «самый вместительный грид», «блок с двенадцатью детьми». На чистом
//: макете это работает — но после первой же отрисовки содержимое зоны
//: НАШЕ, и второй заход ищет уже среди собственных вставок. Мерки
//: перестают сходиться, эвристика цепляет соседа, и экран ломается
//: молча: так на 1i карточка-образец с кнопками переходов уничтожила
//: сама себя, а поле поиска каталога осталось с обработчиком первого
//: показа.
//:
//: Ищем по эвристике ровно один раз — на нетронутом макете, где она
//: заведомо верна, — и держимся за метку. Промах сообщаем: молчать
//: тут нельзя, это и была главная тихая поломка редактора.
//: ОТБОР КОНТЕЙНЕРА СПИСКА — ПО СОДЕРЖИМОМУ, А НЕ ПО ЧИСЛУ ДЕТЕЙ.
//:
//: Правило «больше всех детей и уже N точек» находило не то. На экране
//: объектов побеждала ПУСТАЯ ПОЛОСКА шириной 56 точек с 24 детьми —
//: боковая лента, — и весь каталог уезжал в неё: слева появлялись
//: крошечные плитки, а на месте каталога оставались карточки макета
//: («55 · изба», «70 · сруб») с чёрными квадратами вместо картинок.
//: Снаружи это читалось как «каталог — заглушка на 70% экрана».
//: Та же промашка держала бестиарий на экране деревни.
//:
//: Настоящий контейнер списка ВСЕГДА несёт текст — подписи карточек
//: макета — и всегда шире пары десятков точек. Эти два условия и
//: отличают его от служебных лент.
function listZone(card, { детей: kidCount = 6, от: fromN = 120, до: before = 480 } = {}) {
  return [...card.querySelectorAll("div")]
    .filter(el => el.children.length >= kidCount &&
                 el.clientWidth >= fromN && el.clientWidth <= before &&
                 el.textContent.trim().length > 0)
    .sort((a2, b2) => b2.children.length - a2.children.length)[0] || null;
}

function zoneOnce(card, key2, seek) {
  if (!card) return null;
  const mark = `зона-${key2}`;
  const zoneOf = card.querySelector(`[data-lv="${mark}"]`);
  if (zoneOf) return zoneOf;
  //: ГЕОМЕТРИЯ ЕСТЬ ТОЛЬКО У ПОКАЗАННОЙ КАРТОЧКИ. Экраны оживают
  //: асинхронно (палитра тайлов сперва ждёт /catalog/tiles), и если за
  //: это время человек ушёл на другой экран, прежняя карточка уже
  //: откреплена от документа — а у откреплённого узла clientWidth равен
  //: НУЛЮ, и мерки вроде «шире ста, уже четырёхсот шестидесяти» не
  //: сойдутся никогда. Это не промах монтажа, а опоздавший ответ:
  //: молча уходим, экран доживёт при следующем показе.
  if (!card.isConnected) return null;
  const found2 = seek();
  if (!found2) { miss("зона", key2); return null; }
  found2.dataset.lv = mark;
  return found2;
}

//: КОНТРАКТ «МАКЕТ ↔ ЖИВОЙ СЛОЙ».
//:
//: Мёртвого кода в редакторе нет — ни одной функции без ссылок, ни
//: одного непрочитанного поля (`node tools/editor_dead.js`). Мусор здесь
//: другой: 27 ДОГАДОК поиска по вёрстке, разбросанных по экранам. Каждая
//: молча берёт узел «на глаз», и её промах не виден никому, потому что
//: на месте остаётся макет с выдуманными данными.
//:
//: Поэтому «где лежит список» объявляется ЗДЕСЬ, по одному месту на
//: экран, а не пишется заново внутри каждой жизни. Отсюда же селфчек
//: берёт свои ожидания: добавили зону — она сама попала под проверку, и
//: разъехаться «как ищем» с «что должно быть» больше нечему.
const ZONES = {
  "грид-карт": { экран: "1a", найти: k2 =>
    [...k2.querySelectorAll("div")]
      .filter(el => getComputedStyle(el).display === "grid")
      .sort((a2, b2) => b2.children.length - a2.children.length)[0] },
  "каталог-объектов": { экран: "1b", найти: k2 =>
    listZone(k2, { детей: 8, до: 480 }) },
  "палитра-тайлов": { экран: "1c", найти: k2 =>
    [...k2.querySelectorAll("div")]
      .filter(el => el.children.length >= 12 &&
                   el.clientWidth < 460 && el.clientWidth > 100)
      .sort((a2, b2) => b2.children.length - a2.children.length)[0] },
  //: у бестиария есть свой якорь по содержимому — он точнее любой мерки
  "список-существ": { экран: "1f", найти: k2 =>
    [...k2.querySelectorAll("div")]
      .filter(el => el.children.length >= 6 && el.clientWidth < 470 &&
                   el.textContent.includes("Болотник"))
      .sort((a2, b2) => b2.children.length - a2.children.length)[0]
    || listZone(k2, { детей: 6, до: 470 }) },
  "список-куч": { экран: "1g", найти: k2 =>
    [...k2.querySelectorAll("div")]
      .filter(el => el.clientWidth < 470 &&
                   [...el.children].filter(
                     d2 => /pile_|сундук/.test(d2.textContent)).length >= 3)
      .sort((a2, b2) => a2.children.length - b2.children.length)[0] },
  "находки-валидатора": { экран: "1i", найти: k2 =>
    [...k2.querySelectorAll("div")]
      .filter(el => el.clientWidth < 470 &&
                   (el.textContent.includes("E-0") ||
                    el.textContent.includes("Юнит в глуши")))
      .sort((a2, b2) => b2.children.length - a2.children.length)[0] },
  "список-отрядов": { экран: "1j", найти: k2 =>
    listZone(k2, { детей: 6, до: 470 }) },
  "список-построек": { экран: "1k", найти: k2 =>
    listZone(k2, { детей: 6, до: 470 }) },
};

//: Зона по имени из контракта. Промах уходит в `state.промахи`, откуда
//: его забирает селфчек, — и он же теперь единственное место, где
//: описано, как эта зона ищется.
function zoneOf(card, key2) {
  const rec = ZONES[key2];
  if (!rec) { miss("зона", `${key2} — нет в контракте ЗОНЫ`); return null; }
  return zoneOnce(card, key2, () => rec.найти(card));
}

//: ЧИСЛОВОЕ ПОЛЕ В СТРОКЕ ИНСПЕКТОРА.
//:
//: Панели инспекторов были насквозь «только чтение»: позицию объекта,
//: его состояние (фазу стройки или руины), деньги в куче можно было
//: увидеть, но не задать. Выровнять три избы в ряд было нечем вовсе —
//: только возить мышью и надеяться, а координаты при этом видны с
//: точностью до пикселя. Ставим на место нарисованного значения
//: настоящие поля ввода.
//:
//: Помечаем своим ключом и переподключаем на повторном заходе — иначе
//: получилось бы ровно то, что уже случалось с полем поиска: подпись
//: макета съедена, обработчик остался от первого показа.
function numberFields(card, rowEl, key2, fields, applyIt) {
  //: ИЩЕМ СВОЁ ОТ КАРТОЧКИ, А НЕ ОТ ПОДМЕНЁННОГО УЗЛА: после первой
  //: подмены исходный узел значения откреплён от документа, и
  //: parentElement у него null — второй заход завёл бы второй короб или
  //: не нашёл ничего.
  let boxEl = card?.querySelector(`[data-lv="числа-${key2}"]`);
  const first = !boxEl;
  if (first) {
    if (!rowEl || !rowEl.parentElement) return null;
    boxEl = document.createElement("span");
    boxEl.dataset.lv = `числа-${key2}`;
    boxEl.style.cssText = "display:flex;align-items:center;gap:4px";
    rowEl.replaceWith(boxEl);
  }
  const prev = [...boxEl.querySelectorAll("input")];
  const entries2 = [];
  fields.forEach((field, i2) => {
    let label = boxEl.children[i2 * 2];
    let entry = prev[i2];
    if (first || !entry) {
      label = document.createElement("span");
      label.style.cssText = "font:10px 'IBM Plex Mono';color:#94a3b8";
      entry = document.createElement("input");
      entry.type = "number";
      entry.style.cssText = "width:58px;padding:1px 3px;border:1px solid " +
        "#cbd5e1;border-radius:3px;font:11px 'IBM Plex Mono';" +
        "background:#fff;color:#0f172a";
      boxEl.append(label, entry);
    }
    label.textContent = field.подпись;
    //: значение не перетираем, пока человек в поле — иначе перерисовка
    //: панели вырывает цифру из-под пальцев на полуслове
    if (document.activeElement !== entry) entry.value = field.значение;
    entry.onchange = () => applyIt(entries2.map(it => Number(it.value) || 0));
    entries2.push(entry);
  });
  return boxEl;
}
//: Листалка страниц дизайна: его стрелки ‹ › и подпись «стр N/M».
function pager(card, takeState, showScreen) {
  const leftArrows = [...card.querySelectorAll("div,span,button,i,svg")]
    .filter(el => ["‹", "◀", "<", "chevron-left"].includes(
      (el.textContent || el.getAttribute?.("data-lucide") || "").trim()));
  const rightArrows = [...card.querySelectorAll("div,span,button,i,svg")]
    .filter(el => ["›", "▶", ">", "chevron-right"].includes(
      (el.textContent || el.getAttribute?.("data-lucide") || "").trim()));
  const step = (whither) => {
    const { страница: page, всего: totalCount } = takeState();
    showScreen(Math.max(0, Math.min(totalCount - 1, page + whither)));
  };
  //: ЦЕЛЬ КЛИКА — НЕ ПРОСТО РОДИТЕЛЬ. Обе стрелки макета лежат в ОДНОМ
  //: ряду, и «ближайший родитель» у них общий: обработчик правой
  //: затирал левую, и страница листалась ТОЛЬКО ВПЕРЁД, куда бы ни
  //: нажали. Поднимаемся вверх лишь до тех пор, пока предок не захватил
  //: чужую стрелку.
  const arrowTarget = (el, others) => {
    const btn = el.closest("button");
    if (btn && !others.some(c3 => btn.contains(c3))) return btn;
    const parent2 = el.parentElement;
    if (parent2 && !others.some(c3 => parent2.contains(c3))) return parent2;
    return el;
  };
  for (const [setOf, whither, others] of [[leftArrows, -1, rightArrows],
                                      [rightArrows, +1, leftArrows]]) {
    for (const el of setOf) {
      const aim = arrowTarget(el, others);
      aim.style.cursor = "pointer";
      aim.onclick = () => step(whither);
    }
  }
  //: ЛИСТАЛКА ПОМНИТ СВОЙ ЭКРАН. Здесь стояло `document.onkeydown = …`:
  //: один глобальный обработчик на всех, и экран БЕЗ листалки доставался
  //: протухшему замыканию соседа — PageDown на проходимости тайно листал
  //: каталог объектов, а вернувшись на «Объекты», человек находил чужую
  //: страницу и не понимал почему. Клавиши теперь один раз висят ниже и
  //: спрашивают шаг у ТЕКУЩЕГО экрана; нет листалки — нет и шага.
  pagerByScreen[state.screen] = step;
}
//: Шаг листания по экранам — и ЕДИНСТВЕННЫЙ слушатель клавиш листания
//: и отмены. Поле ввода и открытая панель клавиши не отдают: Ctrl+Z в
//: числе инспектора обязан править текст, а не откатывать карту.
const pagerByScreen = {};
document.addEventListener("keydown", ev => {
  if (["INPUT", "TEXTAREA", "SELECT"].includes(
      document.activeElement?.tagName)) return;
  if (document.querySelector("#lv-shade")) return;
  if (ev.ctrlKey && ev.key.toLowerCase() === "z") {
    ev.preventDefault();
    undoLast();
    return;
  }
  if (ev.key !== "PageUp" && ev.key !== "PageDown") return;
  const step = pagerByScreen[state.screen];
  if (!step) return;
  ev.preventDefault();
  step(ev.key === "PageUp" ? -1 : +1);
});
//: КНОПКИ ИНСПЕКТОРА — общие для объектов, юнитов и куч: «Клон · Ins»,
//: «Дубль · Ins», «Убрать · Del». Работают над тем, что выбрано на
//: холсте (state.picked / state.pickedPile).
//: НЕСКОЛЬКО ИМЁН У ОДНОГО ОРГАНА. Кнопка клона на трёх экранах
//: подписана по-разному, и перебор вариантов — норма поиска, а не
//: поломка: жалуемся, только если не нашлось НИ ОДНО имя.
function organAny(card, ...captions) {
  for (const p2 of captions) {
    const aim = organOf(card, p2, false, true);
    if (aim) return aim;
  }
  miss("органЛюбой", captions.join(" / "));
  return null;
}
function wakeInspector(card, stage) {
  // подпись у кнопки клона на трёх экранах разная: «Клон · Ins»,
  // «Дубль · Ins», «Дублировать · Ins»
  const cloneEl = organAny(card, "Клон", "Дубль", "Дублировать");
  const removeIt = organOf(card, "Убрать", false);
  bindTo(cloneEl, () => cloneIt(stage));
  bindTo(removeIt, () => removePicked(stage));
}
async function cloneIt(stage) {
  //: Вид берём из выбора, а не угадываем по полям записи: у объекта и
  //: декора набор полей одинаковый (см. выбрать()).
  const p2 = selectedOf();
  const kindOf = pickKind();
  if (!p2) { status("сначала выберите что-нибудь на холсте"); return; }
  if (kindOf === "packUnit" || kindOf === "packLoot") {
    status("это житель пака: он приходит из сборки — клонировать нечего, " +
           "поставьте своего из бестиария");
    return;
  }
  if (!state.editable) {
    status(`карта ${state.map} «${state.mapName}» — из игры, только ` +
           `просмотр: скопируйте её в свою (кнопка вверху)`);
    return;
  }
  //: КЛОН ДЕКОРА — та же запись T_DYNAMIC со сдвигом вправо на ширину
  //: спрайта: берег и камыш кладутся полосой, и копия «встык» экономит
  //: десяток кликов. Раньше здесь стоял отказ — у декора не было своего
  //: каталога, и номер брать было неоткуда; теперь номер лежит в самой
  //: выбранной записи.
  if (kindOf === "decor") {
    const step = Math.round((p2.width || 114) * 0.8);
    const resp = await api(`/maps/${state.map}/overlays`, "POST",
      { add: { id: p2.sprite ?? p2.id, x: Math.round((p2.x || 0) + step),
               y: Math.round(p2.y || 0) } });
    if (resp.ok) { await openMap(state.map); stage?.рисуй();
                status(`клон декора ${p2.sprite ?? p2.id} · запись ` +
                       `${resp.slot}`); }
    return;
  }
  if (kindOf === "loot") {
    const id = nextPileId();
    const cellRec = p2.cell || { row: 0, col: 0 };
    const near = { row: cellRec.row, col: cellRec.col + 1 };
    const resp = await api(`/maps/${state.map}/loot`, "POST",
      { id, patch: { id, on_floor: p2.on_floor !== false,
                     buried: Boolean(p2.buried), money: p2.money || 0,
                     items: Array.isArray(p2.items) ? p2.items : [],
                     details: Array.isArray(p2.details) ? p2.details : [],
                     cell: near } });
    //: подтверждение ПОСЛЕ перечитывания — открытьКарту кончается своим
    //: статусом и съедала итог клона (все три ветки ниже — так же)
    if (resp.ok) { await openMap(state.map); stage?.рисуй();
                status(`клон кучи ${id} → ${near.row}:${near.col}`); }
    return;
  }
  if (kindOf === "unit") {
    const id = "unit_new_" + Date.now();
    const cellRec = p2.cell || { row: 0, col: 0 };
    const near = { row: cellRec.row + 2, col: cellRec.col };
    const resp = await api(`/maps/${state.map}/units`, "POST",
      { id, patch: { ...p2, id, cell: near, home: near } });
    if (resp.ok) { await openMap(state.map); stage?.рисуй();
                status(`клон ${p2.name || p2.id} → ${near.row}:${near.col}`); }
    return;
  }
  if (kindOf === "object") {
    const resp = await api(`/maps/${state.map}/objects`, "POST",
      { add: { slot: p2.resource_slot ?? p2.slot, palette: p2.palette,
               state: p2.state, x: Math.round((p2.x || 0) + 64),
               y: Math.round(p2.y || 0) } });
    if (resp.ok) { await openMap(state.map); stage?.рисуй();
                status(`клон объекта · запись ${resp.record_slot}`); }
  }
}
//: УБРАТЬ ВЫБРАННОЕ — ОДНА РЕАЛИЗАЦИЯ НА КНОПКУ И НА КЛАВИШУ Delete.
//: Их было две, и обе неполные: кнопка не знала про декор, а клавиша
//: вдобавок читала лишь одно из трёх полей выбора — куча, выбранная
//: строкой списка на 1g, для неё не существовала, и путь сваливался в
//: `/objects/undefined`. Объект и декор различаем не по полям (у обоих
//: только slot), а по ВИДУ выбранного.
async function removePicked(stage) {
  const p2 = selectedOf();
  if (!p2) { status("сначала выберите что-нибудь на холсте"); return; }
  if (!state.map) return;
  if (!state.editable) {
    status(`карта ${state.map} «${state.mapName}» — из игры, только ` +
           `просмотр: скопируйте её в свою (кнопка вверху)`);
    return;
  }
  const kindOf = pickKind();
  if (kindOf === "packUnit" || kindOf === "packLoot") {
    status("это житель пака: он приходит из сборки, а не из правок — " +
           "уберите его в мире или правьте зону отряда");
    return;
  }
  const path2 = {
    decor: () => `/maps/${state.map}/overlays/${p2.slot}`,
    unit: () => `/maps/${state.map}/units/${encodeURIComponent(p2.id)}`,
    loot: () => `/maps/${state.map}/loot/${encodeURIComponent(p2.id)}`,
    object: () => `/maps/${state.map}/objects/${p2.slot}`,
  }[kindOf]?.();
  if (!path2) { status("неизвестно, что убирать: " + kindOf); return; }
  const resp = await fetch(API + path2, { method: "DELETE" })
    .then(x => x.json()).catch(() => ({ ok: false, note: "сеть" }));
  clearPick();
  await openMap(state.map);
  showScreen(state.screen);
  //: итог ПОСЛЕ перечитывания: открытьКарту кончается своим статусом и
  //: перетирала «убрано» через долю секунды (та же болезнь, что была у
  //: переноса, — см. commitDrag)
  status(resp.ok ? "убрано" : (resp.note || "не вышло"));
}
//: Подпись «стр N/M» дизайна — обновляем на месте, а не рядом.
function pageLabel(card, page, totalCount) {
  for (const el of card.querySelectorAll("div,span")) {
    const pt = el.textContent.trim();
    if (el.childElementCount === 0 && /^стр\.?\s*\d+\s*\/\s*\d+$/i.test(pt)) {
      el.textContent = `стр ${page + 1}/${Math.max(1, totalCount)}`;
    }
  }
}
function byText(root2, selector2, txt) {
  return [...root2.querySelectorAll(selector2)]
    .find(el => el.textContent.trim().startsWith(txt));
}
//: Инлайн-стили нормализуются браузером (#020617 -> rgb(2, 6, 23),
//: пробелы после двоеточий) — искать зоны только по computed-стилю.
function byBackground(root2, ...colors2) {
  return [...root2.querySelectorAll("div")]
    .filter(el => colors2.includes(getComputedStyle(el).backgroundColor));
}
const CANVAS_BG = "rgb(2, 6, 23)";
const CHROME_BG = "rgb(15, 23, 42)";
const SCREEN_BY_TAB = {
  "Ландш": "1c", "Вода": "1e", "Проход": "1d", "Объект": "1b",
  // «Декор» — те же спрайты GRAPH, но в ДРУГУЮ таблицу карты: T_DYNAMIC
  // (берега, кувшинки, камыши поверх земли), а не T_OBJECTS. Отдельного
  // экрана под него в макете нет, поэтому берём экран объектов и
  // переключаем, куда ложится клик (state.decorMode).
  "Декор": "1b",
  "Сущ-ва": "1f", "Отряды": "1j", "Клады": "1g", "Провер": "1i",
  "Деревня": "1k", "Сборка": "1h",
  "События": "story",
};
// топбар макета шире клип-родителя: всё правее ~1400 обрезано, Build
// и Play были недостижимы мышью — прижимаем их к ВИДИМОМУ правому
// краю (right отсчитан от разницы правых краёв топбара и клипа)
function pinToEdge(nodeEl, inset) {
  const topBar = nodeEl.parentElement;
  let clipEl = topBar;
  while (clipEl && getComputedStyle(clipEl).overflow !== "hidden") {
    clipEl = clipEl.parentElement;
  }
  if (!clipEl || !topBar) return;
  const slice2 = topBar.getBoundingClientRect().right -
               clipEl.getBoundingClientRect().right;
  if (getComputedStyle(topBar).position === "static") {
    topBar.style.position = "relative";
  }
  nodeEl.style.position = "absolute";
  nodeEl.style.right = Math.max(0, slice2) + inset + "px";
  nodeEl.style.top = "50%";
  nodeEl.style.transform = "translateY(-50%)";
  nodeEl.style.zIndex = "30";
}
//: ПОЛОСА «ТОЛЬКО ПРОСМОТР» — ГЛАВНАЯ ПРАВДА ОБ ОТКРЫТОЙ КАРТЕ.
//:
//: В project/maps лежат полторы сотни карт ОБЕИХ игр вперемешку со
//: своими. Канонные защищены на сервере (_канон_под_защитой) — их файлы
//: обязаны остаться байт в байт равными оригиналу. Но редактор об этом
//: не говорил ничего: открываешь «Морской лагерь», видишь полностью
//: живой инструмент — кисти активны, каталог полон, вещь под мышью
//: послушно едет за курсором, — а на отпускании сервер отвечает отказом,
//: холст перечитывается, и вещь прыгает на место. Единственным следом
//: была строчка мелким шрифтом в подвале, куда никто не смотрит, потому
//: что смотрит на карту. Отсюда и «объекты не перемещаются», и
//: «половина редактора не работает»: работало всё, просто писать было
//: некуда.
//:
//: Говорим это ДО первого клика и сразу даём выход — копию. Копия и
//: есть тот самый путь «сделать свою игру по образцу»: та же карта со
//: всеми объектами и жителями, но своя, и пиши что хочешь.
//: Подсветить полосу канона в ответ на отказ. Отдельной функцией, а не
//: строкой в обработчике: зовут её из переноса, а живёт полоса своей
//: жизнью и на некоторых экранах её нет вовсе.
function blinkCanonStrip() {
  const strip = document.querySelector('[data-lv="канон-полоса"]');
  if (!strip) return false;
  strip.scrollIntoView({ block: "nearest" });
  //: три вспышки насыщенным жёлтым — этого хватает, чтобы глаз ушёл
  //: вверх, и мало, чтобы стать мельтешением
  strip.animate(
    [{ background: "#fef3c7" }, { background: "#fbbf24" },
     { background: "#fef3c7" }],
    { duration: 320, iterations: 3 });
  return true;
}
function canonStrip(card) {
  const frameBox = card.firstElementChild;
  if (!frameBox) return;
  for (const olderOne of frameBox.querySelectorAll('[data-lv="канон-полоса"]')) {
    olderOne.remove();
  }
  if (!state.map || state.editable !== false) return;
  const strip = document.createElement("div");
  strip.style.cssText =
    "display:flex;align-items:center;gap:10px;padding:7px 14px;" +
    "background:#fef3c7;border-bottom:1px solid #fcd34d;color:#92400e;" +
    "font:12px 'IBM Plex Sans';flex:none";
  const txt = document.createElement("span");
  txt.textContent =
    `Карта ${state.map} «${state.mapName}» — из игры: её файлы держатся ` +
    `байт в байт равными оригиналу, и правки САМОЙ КАРТЫ (земля, ` +
    `объекты, клады) не сохранятся. Жителей мира двигать можно — они ` +
    `живут отдельно, в исходниках мира.`;
  const btn = document.createElement("button");
  const label = "Скопировать в свою карту";
  btn.textContent = label;
  btn.style.cssText =
    "margin-left:auto;padding:5px 12px;border-radius:5px;cursor:pointer;" +
    "border:1px solid #b45309;background:#b45309;color:#fff;" +
    "font:600 12px 'IBM Plex Sans';flex:none;white-space:nowrap";
  btn.onclick = async () => {
    btn.disabled = true;
    btn.textContent = "копирую…";
    const donorFlag = state.map, nm = state.mapName;
    //: КАМЕРУ СОХРАНЯЕМ. открытьКарту сбрасывает вид, когда номер карты
    //: сменился, — и правильно делает: чужая карта под прежним видом
    //: показала бы пустой угол. Но копия — та же карта, и человек
    //: нажимает кнопку, доведя взгляд до нужного места. Отбросив вид, мы
    //: заставили бы его искать это место заново.
    const kindOf = state.view ? { ...state.view } : null;
    const resp = await api("/maps", "POST",
                        { from: donorFlag, name: `${nm} (моя)` });
    if (resp.ok && await openMap(resp.map)) {
      if (kindOf) state.view = kindOf;
      showScreen(state.screen);
      status(`карта ${resp.map} — ваша копия карты ${donorFlag} «${nm}»: ` +
             `правьте что угодно, включая объекты и землю`);
      return;
    }
    btn.disabled = false;
    btn.textContent = label;
  };
  strip.append(txt, btn);
  insertOwn(frameBox, strip, "канон-полоса", frameBox.children[1] || null);
}
//: ПОДСКАЗКИ МАКЕТА, КОТОРЫЕ ВРУТ.
//:
//: Их писал дизайн, а не код, и половина обещает жесты, которых нет. Для
//: человека, который редактор видит впервые, это хуже отсутствия
//: подсказки: он честно жмёт Shift и тянет мышь, ничего не происходит,
//: и вывод один — «редактор сломан». Приводим текст к тому, что
//: ДЕЙСТВИТЕЛЬНО умеет код; чего не умеем — не обещаем.
//:
//: Ключ — точный текст макета, значение — правда (пустая строка прячет
//: подсказку совсем).
const HONEST_HINTS = {
  //: область набирается ДВУМЯ КЛИКАМИ по углам (битКлик/state.area),
  //: тянуть рамку мышью холст не умеет
  "Shift+драг — прямоугольник": "Shift+клик — два угла области",
  //: Tab не подключён ни к чему
  "TAB ⟳": "",
  //: Space не подключён; «взять под курсором» висит на Insert
  "Space — взять под курсором": "тяните — двигать · Ins — дубль",
  "Space — взять тайл под курсором": "Ins — взять тайл под курсором",
  //: Enter не подключён ни на одном экране
  "Enter — поставить": "клик — поставить",
  //: главный жест редактора нигде не был назван вслух, а угадать его
  //: было невозможно: он и не работал (см. кандидат/начатьПеренос)
  "клик — выбрать": "клик — выбрать · тяните — двигать",
  //: Ctrl+клик был третьим жестом переноса и убран: жест теперь один,
  //: и о нём говорит соседняя подпись
  "Ctrl+клик — перенести": "",
  "Enter — открыть карту": "клик по карточке — открыть",
  //: удаление не помечает removed, а убирает запись
  "Del — убрать (removed)": "Del — убрать",
  //: углы зоны мышью по-прежнему не тянутся, но сама зона теперь
  //: правится — числами на вкладке «Отряды»
  "Зона тянется за углы прямо на холсте.":
    "Зона правится числами на вкладке «Отряды».",
  //: скобки не подключены, размер кисти — кнопки 1/2/3
  "[ ] — размер кисти": "размер кисти — кнопки 1 2 3",
  //: ПКМ на ландшафте стирает, а пипетка — на Ins
  "ПКМ — пипетка": "ПКМ — стереть · Ins — пипетка",
};
function honestHints(card) {
  for (const el of card.querySelectorAll("div,span")) {
    if (el.childElementCount) continue;
    const truth = HONEST_HINTS[el.textContent.trim()];
    if (truth === undefined) continue;
    if (truth === "") el.style.display = "none";
    else el.textContent = truth;
  }
}
function wakeChrome(card) {
  canonStrip(card);
  honestHints(card);
  // рейка-вкладки: кликается ВЕСЬ пункт (иконка + подпись), не только
  // текст — живой прогон показал промахи по иконке
  const objectDecorRail = {};
  const railItems = {};
  let lootItem = null;
  for (const [label, screenName] of Object.entries(SCREEN_BY_TAB)) {
    for (const nodeEl of [...card.querySelectorAll("div,span")]
      .filter(el => el.childElementCount <= 1 &&
                   el.textContent.trim() === label)) {
      let aim = nodeEl;
      const parentEl = nodeEl.parentElement;
      if (parentEl && (parentEl.querySelector("i[data-lucide]") ||
                       parentEl.querySelector("svg"))) {
        aim = parentEl;
      }
      aim.style.cursor = "pointer";
      //: «Декор» и «Объект» делят экран 1b, но кладут в РАЗНЫЕ таблицы
      //: карты, и режим решается здесь же. Прежде его ставил отдельный
      //: слушатель на СЛОВЕ, а onclick висел на родителе с иконкой:
      //: клик по иконке (а это половина площади пункта) переключал экран,
      //: но режим не менял — человек думал, что кладёт декор, а клал
      //: объект. Один обработчик — одно решение.
      aim.onclick = () => {
        if (screenName === "1b") {
          const decorNow = (label === "Декор");
          //: СМЕНА РЕЖИМА ОТПУСКАЕТ ВЫБРАННУЮ КАРТИНКУ: каталоги у
          //: объекта и декора разные, и взведённая постановка из чужого
          //: каталога тут же упрётся в отказ.
          if (decorNow !== Boolean(state.decorMode)) state.place = null;
          state.decorMode = decorNow;
        }
        showScreen(screenName);
      };
      railItems[label] = aim;
      if (label === "Объект" || label === "Декор") {
        objectDecorRail[label] = aim;
      }
      if (label === "Клады") lootItem = aim;
    }
  }
  //: ВКЛАДОК «ДЕРЕВНЯ», «ПРОВЕР» И «СБОРКА» В МАКЕТЕ НЕТ — а «Провер»
  //: нарисована только на рейке самого экрана проверок, и войти в
  //: валидатор с других экранов можно было лишь через бейдж
  //: «валидатор: N · M», который на кнопку не похож. Экран сборки 1h
  //: не был достижим ВООБЩЕ: ни вкладки, ни единого вызова
  //: показать("1h") — его дважды чинили, а открыть мог только селфчек.
  //: Рисовать свою кнопку рядом с чужой рейкой — ровно та ошибка, за
  //: которую редактор уже ругали: человек жмёт нарисованные пункты.
  //: Поэтому берём КЛОН настоящего пункта рейки («Клады») и правим в
  //: нём подпись: иконка, отступы, поведение при наведении — всё
  //: родное. Уже нарисованный пункт (Провер на 1i, прежние клоны)
  //: не дублируем — он найден выше и подключён.
  if (lootItem) {
    let anchor = railItems["Клады"] || lootItem;
    for (const [label, screenName] of [["Деревня", "1k"], ["Провер", "1i"],
                                    ["Сборка", "1h"]]) {
      if (railItems[label]) { anchor = railItems[label]; continue; }
      const railItem = lootItem.cloneNode(true);
      for (const el of [railItem, ...railItem.querySelectorAll("div,span")]) {
        if (el.childElementCount === 0 &&
            el.textContent.trim() === "Клады") {
          el.textContent = label;
        }
      }
      railItem.style.cursor = "pointer";
      railItem.onclick = () => showScreen(screenName);
      insertOwn(anchor.parentElement, railItem,
                   "вкладка-" + label.toLowerCase(),
                   anchor.nextElementSibling);
      anchor = railItem;
    }
  }
  //: «Объект»/«Декор» РЕЙКА НЕ ПЕРЕКЛЮЧАЛАСЬ. Оба пункта делят экран
  //: 1b, и в макете подсветку несёт только «Объект» — он один навсегда
  //: и оставался ярким, даже когда клик по «Декор» уже переключил
  //: state.decorMode. Красим оба сами по актуальному режиму.
  const ACTIVE_BG = "color:#fff;background:#1e293b;" +
    "box-shadow:inset 3px 0 0 #2563eb";
  const IDLE_BG = "color:#94a3b8;background:transparent;" +
    "box-shadow:none";
  if (state.screen === "1b" &&
      objectDecorRail["Объект"] && objectDecorRail["Декор"]) {
    const decorActive = Boolean(state.decorMode);
    objectDecorRail["Объект"].style.cssText +=
      ";" + (decorActive ? IDLE_BG : ACTIVE_BG);
    objectDecorRail["Декор"].style.cssText +=
      ";" + (decorActive ? ACTIVE_BG : IDLE_BG);
  }
  // ОТМЕНА ПО ЗНАЧКУ, А НЕ ПО title. Кнопки undo/redo в макете — это
  // иконки lucide (rotate-ccw/rotate-cw) внутри рамки, и title висит на
  // рамке не всегда: поиск по одному title промахивался, и «отмена не
  // работает» была честной жалобой.
  const iconEl = (namesOf) => [...card.querySelectorAll(
    "i[data-lucide],svg,div,span")].find(el => {
      const nm = el.getAttribute?.("data-lucide") ||
                  el.getAttribute?.("class") || "";
      return namesOf.some(i2 => String(nm).includes(i2)) ||
             namesOf.some(i2 => (el.getAttribute?.("title") || "").includes(i2));
    });
  const btn = (nodeEl) => nodeEl && (nodeEl.closest("button") ||
    nodeEl.closest("[style*='border']") || nodeEl.parentElement || nodeEl);
  const undo = btn(iconEl(["rotate-ccw", "undo", "corner-up-left"]) ||
                      card.querySelector("[title*='undo']"));
  const redo = btn(iconEl(["rotate-cw", "redo", "corner-up-right"]) ||
                      card.querySelector("[title*='redo']"));
  if (undo) { undo.style.cursor = "pointer"; undo.onclick = undoLast; }
  if (redo) { redo.style.cursor = "pointer"; redo.onclick = restore2; }
  let buildAim = null;
  for (const nodeEl of [...card.querySelectorAll("div,span,button")]) {
    const pt = nodeEl.textContent.trim();
    if (pt === "Build" && nodeEl.childElementCount === 0) {
      const aim = nodeEl.closest("[style*='border']") || nodeEl;
      aim.style.cursor = "pointer";
      aim.onclick = buildIt;
      pinToEdge(aim, 64);
      buildAim = aim;
    }
    if (pt === "Play" && nodeEl.childElementCount === 0) {
      const aim = nodeEl.closest("[style*='border']") || nodeEl;
      aim.style.cursor = "pointer";
      aim.onclick = playIt;
      aim.title = "проба идёт с НОВОЙ партии: сейв не читается, " +
                  "иначе правок не видно (память карты сильнее пака)";
      pinToEdge(aim, 8);
    }
    // макетный счётчик ошибок в топбаре статичен и врёт — живёт
    // наш бейдж «валидатор: N · M»; прячем двойника
    if (/^\d+ ошибк/.test(pt) && nodeEl.childElementCount <= 2) {
      (nodeEl.closest("[style*='border']") || nodeEl).style.display = "none";
    }
  }
  mountPlayFrom(card, buildAim);
  // бейдж «валидатор: N · M» в топбаре — вход на экран проверок:
  // пункт «Провер» есть не на каждой рейке его макета
  for (const nodeEl of [...card.querySelectorAll("div,span")]) {
    if (nodeEl.textContent.trim().startsWith("валидатор") &&
        nodeEl.childElementCount <= 2) {
      const aim = nodeEl.closest("[style*='border']") || nodeEl;
      aim.style.cursor = "pointer";
      aim.onclick = () => showScreen("1i");
      // КАЖДЫЙ ЭКРАН НЕСЁТ СВОЮ КОПИЮ ТОПБАРА (карточка не общая), и
      // бейдж застывал на числах первого визита в «Провер» — на 1d/1e
      // висело «2 · 3» даже после того, как карту давно исправили.
      // Здесь оживитьХром() зовётся при КАЖДОМ показать(), поэтому
      // достаточно обновлять бейдж живым запросом при каждом заходе.
      if (state.map) {
        api(`/maps/${state.map}/validate`).then(resp => {
          if (resp.ok) nodeEl.textContent =
            `валидатор: ${resp.errors.length} · ${resp.warnings.length}`;
        });
      }
      break;
    }
  }
  // селектор карты (номер·имя в топбаре) → стартовый экран
  const selNode = byText(card, "div", "23");
  const selector2 = card.querySelector(
    "[style*='cursor'] i[data-lucide='chevrons-up-down']")?.closest("div");
  const selectHost = selector2 || selNode;
  if (selectHost) {
    if (state.map) {
      const num = selectHost.querySelector("span");
      if (num) num.textContent = state.map;
      const nm = selectHost.querySelectorAll("span")[1];
      if (nm) nm.textContent = state.mapName || "";
    }
    selectHost.style.cursor = "pointer";
    selectHost.onclick = () => showScreen("1a");
    //: ВЫБОР МИРА — РЯДОМ С ВЫБОРОМ КАРТЫ, а не во вкладке существ.
    //: Мир (он же выбор героя) меняет ВСЮ карту: жителей, отряды,
    //: клады и деревню, — значит это настройка того, что открыто, и
    //: место ей в топбаре, возле номера карты.
    //: ВЫБИРАЕМ СЛОТ ГЕРОЯ, А НЕ НОМЕР МИРА. Пак ключует население
    //: номером слота (0…8), а слот — это ПАРА «игра + мир»: слот 2 это
    //: канонный мир 2, а слот 1 — мир 1 ДОНОРСКОЙ игры. Прежде список
    //: строился по папкам project/worlds (только канонные, шесть штук),
    //: и три донорских героя — Иззарк, Драгомир, Гильдис — были
    //: недоступны вовсе, а их население посмотреть было нечем.
    const worldSelect = document.createElement("select");
    worldSelect.title = "герой: состав карты у каждого свой";
    worldSelect.style.cssText = "margin-left:10px;padding:3px 6px;" +
      "font:12px 'IBM Plex Mono';border-radius:6px;border:1px solid " +
      "rgba(148,163,184,.5);background:transparent;color:inherit;" +
      "max-width:230px";
    api("/worlds").then(obj => {
      const slots2 = (obj.worlds || []).length ? obj.worlds
        : [...Array(9).keys()].map(sp => ({ slot: sp, world: sp,
                                           game: "canon", editable: false }));
      state.слотыГероев = slots2;
      worldSelect.innerHTML = slots2.map(m2 =>
        `<option value="${m2.slot}" ` +
        `${(state.world ?? 0) === m2.slot ? "selected" : ""}>` +
        `${m2.slot} · ${(m2.hero || "герой " + m2.slot).slice(0, 22)}` +
        `${m2.editable ? "" : " (только показ)"}</option>`).join("");
      state.слотГероя = slots2.find(m2 => m2.slot === (state.world ?? 0)) || null;
    });
    worldSelect.onchange = async () => {
      state.world = Number(worldSelect.value);
      state.слотГероя = (state.слотыГероев || [])
        .find(m2 => m2.slot === state.world) || null;
      if (state.map) await openMap(state.map);
      const sp = state.слотГероя;
      status(`${sp?.hero || "слот " + state.world}: жителей ` +
             `${(state.packUnits || []).length}` +
             (sp && !sp.editable
               ? " · это герой донорской игры, его население только показ"
               : ""));
      showScreen(state.screen);
    };
    //: МЕСТО В РЯДУ, А НЕ В ХВОСТЕ. Топбар — flex-ряд с РАСПОРКОЙ
    //: (`flex:1 1 0`) посередине: всё, что дописано в конец, улетает к
    //: правому краю — прямо под плавающие кнопки Build/Play. Поэтому
    //: вставляем ПЕРЕД распоркой, то есть в левую группу, рядом с
    //: номером карты — как и было задумано.
    const line = selectHost.parentElement;
    const spacer = [...(line?.children || [])].find(el => {
      const sp = getComputedStyle(el);
      return sp.position !== "absolute" && parseFloat(sp.flexGrow) > 0;
    });
    insertOwn(line, worldSelect, "выбор-мира", spacer || null);
    //: ВЫБОР МИРА УЕЗЖАЛ ПОД КНОПКИ BUILD/PLAY. Кнопки топбара лежат
    //: `position:absolute` поверх того же ряда — места в потоке они не
    //: занимают вовсе, и селект честно тянулся до правого края, уходя
    //: под них: читалась только его левая половина. Padding ряду не
    //: поможет — смещения absolute считаются от его же padding-box, и
    //: кнопки уехали бы вместе с ним. Ужимаем САМ СЕЛЕКТ так, чтобы он
    //: кончался перед самой левой плавающей кнопкой.
    const fitSelect = () => {
      const line = worldSelect.parentElement;
      if (!line || !worldSelect.isConnected) return;
      const floating = [...line.children].filter(
        el => el !== worldSelect && getComputedStyle(el).position === "absolute");
      if (!floating.length) return;
      const leftOf = Math.min(...floating.map(
        el => el.getBoundingClientRect().left));
      const mineBox = worldSelect.getBoundingClientRect();
      worldSelect.style.maxWidth =
        `${Math.round(Math.max(90, leftOf - mineBox.left - 12))}px`;
    };
    requestAnimationFrame(fitSelect);
    addEventListener("resize", fitSelect);
  }
  // статус-строка: последний тёмный блок карточки внизу
  const bottomEl = byBackground(card, CHROME_BG).reverse()
    .find(el => el.offsetParent !== null && el.clientHeight > 0 &&
               el.clientHeight < 44);
  if (bottomEl && !bottomEl.querySelector("[data-live-status]")) {
    const slotNum = document.createElement("span");
    slotNum.setAttribute("data-live-status", "1");
    slotNum.style.cssText = "font:11px 'IBM Plex Mono';color:#94a3b8;" +
                         "margin-left:12px";
    slotNum.textContent = state.statusText || "";
    bottomEl.appendChild(slotNum);
  }
}

//: ЖУРНАЛ ОТМЕНЫ ОБЩИЙ НА ВЕСЬ СЕРВЕР, А НЕ НА КАРТУ.
//:
//: _UNDO на сервере — один список путей к файлам всех карт разом.
//: Ctrl+Z откатывал ПОСЛЕДНЮЮ правку вообще: поработал на одной карте,
//: перешёл на другую, нажал отмену — и откатилась правка ПЕРВОЙ карты,
//: которой на экране нет. Видимая карта при этом не менялась ни на
//: пиксель, и отмена выглядела сломанной, хотя честно отработала.
//:
//: Сервер называет откаченный путь (`undone`); по нему видно, какой
//: карты касалась правка. Если чужой — говорим об этом прямо и
//: переводим взгляд туда, а не молчим.
//: Сервер называет откат ПУТЁМ ЗАПРОСА (/editor/api/maps/63/objects),
//: а здесь ждали ФАЙЛОВОГО пути с подчёркиванием (maps/63_…) — ни один
//: откат не совпадал никогда, и «правка была на другой карте — перейти
//: туда» не срабатывало вовсе. Берём номер и за косой чертой, и за
//: подчёркиванием: подходит и путь мира (worlds/0/maps/23/units).
function mapFromPath(path2) {
  const m2 = /maps[\\/](\d+)(?=[_\\/]|$)/.exec(String(path2 || ""));
  return m2 ? Number(m2[1]) : null;
}
//: Человеческое имя отката вместо сырого пути: «⟲ объекты карты 63»,
//: а не «⟲ /editor/api/maps/63/objects» — путь API человеку не говорит
//: ничего и читается как ошибка.
const UNDO_LAYER_NAME = {
  terrain: "земля", water: "вода", objects: "объекты",
  overlays: "декор", exits: "выходы", cells: "клетки",
  units: "жители", loot: "клады", warbands: "отряды",
  village: "деревня",
};
function undoLabel(path2) {
  const p2 = String(path2 || "");
  const world2 = /worlds[\\/](\d+)[\\/]maps[\\/](\d+)[\\/](\w+)/.exec(p2);
  if (world2) {
    return `${UNDO_LAYER_NAME[world2[3]] || world2[3]} карты ${world2[2]} ` +
           `в мире ${world2[1]}`;
  }
  const m2 = /maps[\\/](\d+)[\\/]([\w-]+)/.exec(p2);
  if (m2) return `${UNDO_LAYER_NAME[m2[2]] || m2[2]} карты ${m2[1]}`;
  const d2 = /story[\\/]dialog[\\/]([^\\/]+)/.exec(p2);
  if (d2) return `диалог ${decodeURIComponent(d2[1])}`;
  return p2 || "готово";
}
async function undoAndShow(path2, sign2) {
  const foreign = mapFromPath(path2);
  if (foreign != null && state.map != null && foreign !== state.map) {
    //: правка была на ДРУГОЙ карте — иначе человек смотрит на
    //: неизменившийся экран и думает, что отмена не сработала
    if (await openMap(foreign)) {
      showScreen(state.screen);
      status(`${sign2} правка была на карте ${foreign} — перешли туда: ` +
             `${undoLabel(path2)}`);
      return;
    }
  }
  if (state.map) await openMap(state.map);
  showScreen(state.screen);
  status(`${sign2} ${undoLabel(path2)}`);
}
async function undoLast() {
  const resp = await api("/undo", "POST", {});
  if (!resp.ok) { status(resp.note || "отменять нечего"); return; }
  await undoAndShow(resp.undone, "⟲");
}
async function restore2() {
  const resp = await api("/redo", "POST", {});
  if (!resp.ok) { status(resp.note || "возвращать нечего"); return; }
  await undoAndShow(resp.redone, "⟳");
}
//: ЗНАЧОК «building» В ШАПКЕ 1h стоял в макете «family=busy, pulse=true»
//: намертво — полифилИмпортов() красит StatusBadge один раз при монтаже
//: и больше не трогает; сборка карты давно кончилась, а значок всё
//: горит «идёт». Красим по трём настоящим состояниям сборки.
const BUILD_BADGE = {
  ожидание: { текст: "не запущена", цвет: "#64748b" },
  идёт: { текст: "building", цвет: "#d97706" },
  готово: { текст: "готово · code 0", цвет: "#16a34a" },
  упало: { текст: "упало", цвет: "#dc2626" },
};
function paintBuildBadge() {
  const stateNum = state.buildRunning ? "идёт"
    : state.buildCode == null ? "ожидание"
    : state.buildCode === 0 ? "готово" : "упало";
  const { текст: txt, цвет: paintColor } = BUILD_BADGE[stateNum];
  for (const nodeEl of document.querySelectorAll(
      '[data-live-badge="building"]')) {
    nodeEl.textContent = txt;
    nodeEl.style.color = paintColor;
    nodeEl.style.borderColor = paintColor + "55";
    nodeEl.style.background = paintColor + "18";
  }
}
async function buildIt() {
  if (!state.map) { status("сначала выберите карту"); return; }
  const resp = await api("/build", "POST", { maps: [state.map] });
  if (!resp.ok) return;
  state.buildRunning = true; state.buildCode = null;
  paintBuildBadge();
  status(`сборка пошла · job ${resp.job}`);
  const poll2 = setInterval(async () => {
    const sp = await api("/build/status");
    status(`build: ${sp.running ? "идёт" : "код " + sp.code} · ` +
           (sp.tail?.slice(-1)[0] || "").slice(0, 80));
    if (!sp.running) {
      clearInterval(poll2);
      state.buildRunning = false; state.buildCode = sp.code;
      paintBuildBadge();
      status(sp.code === 0 ? "сборка готова — Play ▶" : "сборка упала");
    }
  }, 1500);
}
async function playIt() {
  if (!state.map) return;
  //: ВКЛАДКА ОТКРЫВАЕТСЯ ДО await, А НЕ ПОСЛЕ. window.open() после
  //: await api(...) стоит уже ВНЕ стека вызова клика — часть браузеров
  //: (в первую очередь Chrome) считает такой вызов не жестом
  //: пользователя и молча режет всплывающее окно: кнопка «Play»
  //: выглядела так, будто ничего не делает. Открываем пустую вкладку
  //: синхронно, в самом обработчике клика, и уже потом наводим её на
  //: адрес — так вкладку не блокируют независимо от задержки запроса.
  const win = window.open("", "_blank");
  const at = state.playFrom;
  const resp = await api(`/play/${state.map}` +
    (at ? `?row=${at.row}&col=${at.col}` : ""));
  if (resp.ok && win) win.location = resp.redirect;
  else if (win) win.close();
  //: Ответ сервера и есть честная надпись: с новой партии, с какой
  //: клетки и глухая ли она.
  if (resp.ok) status("▶ " + resp.note);
}

//: ОТКУДА НАЧНЁТСЯ ПРОБА — ОРГАН РЯДОМ С PLAY.
//:
//: Проба начиналась у точки входа карты, а правка обычно в другом
//: конце: на своей карте 64 до жителя было восемь десятков клеток, и
//: дорога стоила дороже самой правки. Теперь клетка указывается мышью,
//: живёт меткой на холсте и уезжает в адрес игры.
//:
//: Здесь же — ЧЕСТНАЯ НАДПИСЬ ПРО СЕЙВ: проба всегда идёт с новой
//: партии (память карты сильнее пака, mapstate.js), и человек узнаёт
//: об этом до запуска, а не по «правки не применились».
function paintPlayChip() {
  for (const chip of document.querySelectorAll("[data-lv='старт-пробы']")) {
    const [label, cross] = chip.children;
    const at = state.playFrom;
    label.textContent = state.playPick ? "укажите клетку…"
      : at ? `▶ старт ${at.row}:${at.col}` : "▶ отсюда";
    cross.style.display = at && !state.playPick ? "" : "none";
    chip.style.borderColor = state.playPick ? "#f5be5a"
      : at ? "#4ea1d3" : "#3f4a5a";
    chip.style.color = (at || state.playPick) ? "#e7eef7" : "#9fb0c4";
    chip.title = at
      ? `проба начнётся с клетки ${at.row}:${at.col} и с НОВОЙ партии; ` +
        "✕ — вернуть точку входа карты"
      : "щёлкните, потом укажите клетку на карте — проба начнётся оттуда " +
        "(и всегда с новой партии: сейв не читается)";
  }
}
function setPlayFrom(cell) {
  state.playFrom = cell;
  state.playPick = false;
  paintPlayChip();
  liveStage?.рисуйПоверх?.();
  status(cell ? `старт пробы: клетка ${cell.row}:${cell.col} · ` +
                "Play начнёт игру оттуда, с новой партии"
              : "старт пробы: точка входа карты");
}
function mountPlayFrom(card, buildAim) {
  if (!card || card.querySelector("[data-lv='старт-пробы']")) return;
  //: Топбар без Build — это экран списка карт: пробе там неоткуда
  //: начинаться, и это не промах якоря, а нормальный экран.
  const host = buildAim?.parentElement;
  if (!host) return;
  const chip = document.createElement("div");
  chip.dataset.lv = "старт-пробы";
  chip.style.cssText = "display:flex;align-items:center;gap:6px;" +
    "padding:4px 9px;border:1px solid #3f4a5a;border-radius:6px;" +
    "font:11px/1.2 monospace;background:#171d26;cursor:pointer;" +
    "white-space:nowrap";
  const label = document.createElement("span");
  const cross = document.createElement("span");
  cross.textContent = "✕";
  cross.style.cssText = "color:#f5be5a;padding:0 2px";
  cross.onclick = (ev) => { ev.stopPropagation(); setPlayFrom(null); };
  chip.append(label, cross);
  chip.onclick = () => {
    if (!state.map) { status("сначала откройте карту"); return; }
    state.playPick = !state.playPick;
    paintPlayChip();
    status(state.playPick
      ? "укажите клетку на холсте — с неё начнётся проба (Esc — отмена)"
      : "выбор старта отменён");
  };
  host.append(chip);
  //: Отступ считается от НАСТОЯЩЕЙ ширины Build, а не на глазок: у
  //: топбаров разных экранов кнопки разной длины, и угаданное число
  //: наложило бы фишку на кнопку.
  pinToEdge(chip, 64 + (buildAim.offsetWidth || 56) + 8);
  paintPlayChip();
}

// ── данные карты и живой холст ───────────────────────────────────────────
async function openMap(num) {
  const [sp, pt, k2] = await Promise.all([
    api(`/maps/${num}`), api(`/maps/${num}/terrain`),
    api(`/maps/${num}/cells`)]);
  if (!sp.ok) return false;
  // другая карта — камеру в исходное: вид от прежней карты сбивает с
  // толку (пустой угол вместо содержимого)
  if (state.map !== num) {
    state.view = { zoom: 1, x: 0, y: 0, вписать: true };
    //: старт пробы — свойство КАРТЫ: клетка 41:36 на другой карте
    //: означает совсем другое место, а то и глухую стену
    state.playFrom = null;
    state.playPick = false;
  }
  state.map = num;
  state.mapName = sp.meta.name || "";
  //: МОЖНО ЛИ ПИСАТЬ В ЭТУ КАРТУ. Карты обеих игр (их полторы сотни)
  //: защищены на сервере и правке не поддаются, а редактор об этом
  //: молчал: кисти активны, каталог открыт, вещь послушно едет за
  //: курсором — и на отпускании прыгает назад, потому что сервер отказал,
  //: а холст перечитался. Со стороны это ровно «объекты не
  //: перемещаются, половина редактора не работает».
  state.editable = sp.meta.editable !== false;
  state.mapState = sp;
  state.terrain = pt.ok ? pt : null;
  state.cells = k2.ok ? k2.cells : null;
  // жители и выходы СОБРАННОЙ карты — их рисует холст: без них карта
  // выглядит безлюдной, а двери и переходы вообще негде увидеть
  if (!state.bestiary) state.bestiary = await api("/catalog/bestiary");
  const worldNum = state.world ?? 0;
  const packData = await api(`/maps/${num}/pack?world=${worldNum}`);
  state.packUnits = packData.ok ? (packData.units || []) : [];
  state.packLoot = packData.ok ? (packData.loot || []) : [];
  state.packExits = packData.ok ? (packData.exits || []) : [];
  state.packWarbands = packData.ok ? (packData.warbands || []) : [];
  state.packDecor = packData.ok ? (packData.decor || []) : [];
  //: Точные ключи глубины объектов из пака — по слоту записи. Пусто,
  //: пока карта не собрана: тогда холст считает приближённо (см. сцену).
  state.глубины = packData.ok ? (packData.object_depth || {}) : {};
  //: КАТАЛОГ — ИГРЫ ЭТОЙ КАРТЫ. У «Продолжения легенды» свой OBJECTS.RES:
  //: канонный каталог промахивался мимо каждой записи Тиграта, и здания
  //: просто не рисовались (rec не находился — оставалась одна засечка).
  const mapGame = sp.meta.game || "canon";
  if (!state.objByKey || state.objGame !== mapGame) {
    await loadObjectCatalog(mapGame);
  }
  status(`карта ${num} «${state.mapName}»: объектов ` +
         `${sp.objects.records.length}, вода ${sp.water.count}`);
  return true;
}
async function loadObjectCatalog(game) {
  state.objGame = game || "canon";
  state.objByKey = new Map();
  state.objPages = [];
  //: ГРУППЫ У КАЖДОЙ ИГРЫ СВОИ (server.OBJECT_GROUPS и
  //: LEGEND_OBJECT_GROUPS): выбранный чип канона на чужом каталоге
  //: означал бы другое, поэтому при смене игры фильтр сбрасываем, а
  //: набор чипов берём из ответа.
  state.objGroup = "";
  state.objGroups = [];
  let page = 0, totalCount = 1;
  //: предел был 20 страниц (480 записей) — каталог легенды длиннее: 579
  while (page * 24 < totalCount && page < 40) {
    const obj = await api(`/catalog/objects?page=${page}&game=${state.objGame}`);
    if (!obj.ok) break;
    totalCount = obj.total;
    state.objPages.push(obj.items);
    if (obj.groups) state.objGroups = obj.groups;
    for (const z2 of obj.items) state.objByKey.set(
      z2.slot + ":" + z2.palette, z2);
    page += 1;
  }
}

//: КАТАЛОГ ДЕКОРА. Своего каталога у декора не было вовсе, и постановка
//: стояла закрытой: вкладка «Декор» показывала грид ОБЪЕКТОВ, а номера
//: у них из разных таблиц — подставив одно вместо другого, редактор клал
//: в карту чужой спрайт. Список берётся с сервера и там же собирается из
//: самой игры: какие спрайты GRAPH она кладёт в T_DYNAMIC и как часто.
async function loadDecorCatalog(game) {
  state.decorGame = game || "canon";
  state.decorList = [];
  let page = 0, pages = 1;
  while (page < pages && page < 20) {
    const obj = await api(
      `/catalog/decor?page=${page}&game=${state.decorGame}`);
    if (!obj.ok) break;
    pages = obj.pages || 1;
    state.decorList.push(...(obj.decor || []));
    page += 1;
  }
  return state.decorList;
}

const K = 0.155;
//: ГЕОМЕТРИЯ ДВУХ СЕТОК — ИЗ ПАКА (coordinates.navigation_grid и
//: ground_grid), а не «на глаз». Клетка шага 58 x 16 (якорь 29/58 по
//: нечётным рядам, 16 по вертикали), тайл земли 116 x 32. Высота клетки
//: РОВНО ВДВОЕ МЕНЬШЕ шага земли: здесь стояло 32, и весь слой клеток —
//: глушь, юниты, кучи, зоны отрядов — растягивался вдвое вниз
//: относительно земли, а клик по холсту попадал в чужую строку.
const CELL_W = 58, CELL_H = 16;
//: Картинка тайла крупнее шага сетки (ground_grid.tile_width/height
//: против step_x/step_y) — так ромбы смыкаются без щелей.
const TILE_PX_W = 114, TILE_PX_H = 64;
const TILE_W = 0x74, TILE_H = 0x20;
const imgCache = new Map();
//: ПЕРЕРИСОВКА ПО ДОГРУЗКЕ — ОДНА НА КАДР, А НЕ НА КАРТИНКУ. Каждый
//: onload звал полный draw() немедленно: включение «без крыш» на
//: Тиграте ставило в очередь ~90 слоёв, и 90 прогонов сцены по 697
//: объектов вешали вкладку на десятки секунд. Копим догрузки и рисуем
//: один раз следующим кадром.
let redrawQueued = false;
function scheduleRedraw(redraw) {
  if (typeof redraw !== "function" || redrawQueued) return;
  redrawQueued = true;
  requestAnimationFrame(() => { redrawQueued = false; redraw(); });
}
function pic(url, redraw) {
  if (imgCache.has(url)) return imgCache.get(url);
  const image2 = new Image();
  image2.src = url;
  image2.onload = () => scheduleRedraw(redraw);
  imgCache.set(url, image2);
  return image2;
}
function tileColor(i2) {
  return `hsl(${(i2 * 47) % 360} 45% ${28 + (i2 * 13) % 22}%)`;
}

//: Живой холст вживляется в зону холста экрана: самый крупный тёмный
//: блок карточки (#020617). Рисование — как в прототипе, зато вокруг —
//: вёрстка дизайна.
function mountCanvas(card, handlers) {
  const zoneOf = byBackground(card, CANVAS_BG)
    .sort((a2, b2) => (b2.clientWidth * b2.clientHeight)
                  - (a2.clientWidth * a2.clientHeight))[0];
  if (!zoneOf) return null;
  zoneOf.replaceChildren();
  zoneOf.style.position = "relative";
  zoneOf.style.overflow = "hidden";
  //: ХОЛСТ ЗАНИМАЕТ ВСЁ СВОБОДНОЕ МЕСТО. Он был фиксирован в 1500x1320
  //: точек: справа и снизу оставалось пустое поле в треть экрана, а
  //: карту приходилось разглядывать в окошке. Зона холста растягивается
  //: до края карточки, а холст берёт её размер — и меняется вместе с
  //: окном.
  zoneOf.style.flex = "1 1 auto";
  zoneOf.style.minWidth = "0";
  zoneOf.style.alignSelf = "stretch";
  const stage = document.createElement("canvas");
  stage.style.cursor = "crosshair";
  stage.style.display = "block";
  zoneOf.appendChild(stage);
  //: СЛОЙ ПОВЕРХ — ДЛЯ НАВЕДЕНИЯ И ПРИЗРАКА.
  //:
  //: Подсветка того, что под курсором, и полупрозрачный призрак того,
  //: что встанет по щелчку, обязаны обновляться на КАЖДОЕ движение
  //: мыши. Рисовать ради этого всю сцену заново нельзя: она тяжёлая
  //: (земля тайлами, сотни объектов, одетые юниты), и редактор начал бы
  //: заикаться ровно там, где нужна точность. Держим второй прозрачный
  //: холст поверх: чистится и рисуется он за доли миллисекунды, а
  //: сцена под ним не трогается вовсе.
  const overCanvas = document.createElement("canvas");
  overCanvas.style.cssText = "position:absolute;left:0;top:0;" +
    "pointer-events:none";
  zoneOf.appendChild(overCanvas);
  //: ТУМБЛЕРЫ СЛОЁВ — ПРЯМО У ХОЛСТА, на каждом экране с картой.
  //: Прежний цикл «видимость слоёв» на 1b искал подписи в макете,
  //: которых там нет, — переключить слой мышью было нечем. Плавающий
  //: ряд чипов: клик гасит слой; «крыши» снимают кровли с домов, чтобы
  //: видеть людей внутри (движок прячет крышу над отрядом — тут то же
  //: руками).
  const layersBar = document.createElement("div");
  layersBar.dataset.lv = "слои-холста";
  layersBar.style.cssText = "position:absolute;right:8px;top:8px;" +
    "display:flex;gap:4px;flex-wrap:wrap;justify-content:flex-end;" +
    "max-width:60%;z-index:5;font:600 10.5px 'IBM Plex Sans'";
  const paintLayersBar = () => {
    layersBar.replaceChildren();
    for (const nm of Object.keys(state.слои)) {
      const chip = document.createElement("span");
      const on = state.слои[nm] !== false;
      chip.textContent = nm;
      chip.title = on ? `слой «${nm}» виден — щёлкните, чтобы скрыть`
                      : `слой «${nm}» скрыт — щёлкните, чтобы показать`;
      chip.style.cssText = "padding:3px 8px;border-radius:10px;" +
        "cursor:pointer;user-select:none;border:1px solid " +
        (on ? "#334155;background:rgba(15,23,42,.82);color:#e2e8f0"
            : "#1e293b;background:rgba(15,23,42,.45);color:#64748b;" +
              "text-decoration:line-through");
      chip.onclick = () => { state.слои[nm] = !on;
                             paintLayersBar(); draw(); };
      layersBar.appendChild(chip);
    }
  };
  paintLayersBar();
  zoneOf.appendChild(layersBar);
  function atSpot() {
    const prev = [stage.width, stage.height];
    // без transform: scale точки холста = точки экрана, пересчёт не
    // нужен. Ширина — своя зона, высота — до низа окна.
    const frameBox = zoneOf.getBoundingClientRect();
    const width2 = Math.max(320, Math.round(frameBox.width));
    const height2 = Math.max(240,
      Math.round(window.innerHeight - frameBox.top - 8));
    if (prev[0] !== width2 || prev[1] !== height2) {
      for (const sp of [stage, overCanvas]) {
        sp.width = width2;
        sp.height = height2;
        sp.style.width = width2 + "px";
        sp.style.height = height2 + "px";
      }
      return true;
    }
    return false;
  }
  atSpot();
  const brush = stage.getContext("2d");
  const overCtx = overCanvas.getContext("2d");
  //: КАМЕРА ХОЛСТА. Карта 9280x4096 мировых точек ужималась в экран
  //: одним постоянным K=0.155, и разглядеть клетку было нельзя: избы
  //: сливались, а попасть кистью в нужную клетку — только на глаз.
  //: view.zoom — увеличение поверх K, view.x/y — мировая точка левого
  //: верхнего угла видимой части.
  state.view = state.view || { zoom: 1, x: 0, y: 0 };
  const kindOf = state.view;
  const LIMIT = { мин: 0.6, макс: 8 };
  function draw() {
    // трансформация камеры: код ниже рисует в прежних координатах
    // «мир * K», камера лишь двигает и растягивает картинку
    brush.setTransform(1, 0, 0, 1, 0, 0);
    brush.fillStyle = "#101418";
    brush.fillRect(0, 0, stage.width, stage.height);
    brush.setTransform(kindOf.zoom, 0, 0, kindOf.zoom,
                       -kindOf.x * K * kindOf.zoom, -kindOf.y * K * kindOf.zoom);
    // видимость слоёв объявляем ДО первого использования: ниже её
    // читает уже отрисовка земли
    const layerFlags = state.слои || {};
    const visible = (nm) => layerFlags[nm] !== false;
    //: ЗЕМЛЯ — НАСТОЯЩИМИ ТАЙЛАМИ, а не цветными пятнами. Здесь стояла
    //: заглушка `цветТайла(индекс)` — hsl по номеру: карта выглядела
    //: цветной мешаниной, в которой не разобрать ни дороги, ни воды.
    //: Картинки лежат в паке (assets/ground/editor_tile_N.png), кэш —
    //: общий imgCache. Рисуем ТОЛЬКО видимую часть: при 12 800 клетках
    //: полный проход на каждый кадр не нужен.
    //: ВОДА — ПЕРВЫМ СЛОЕМ, ДО ЗЕМЛИ, как в движке (рендер 0x428240:
    //: блит подложки 256x256 по ненулевым клеткам 16x32, а мозаика земли
    //: с нарочными дырами ложится сверху; кромку прикрывают берега из
    //: декора). Раньше вода рисовалась синими квадратами ПОВЕРХ земли —
    //: человек видел разметку, а не воду (docs/WATER_EDITOR_SPEC.md §5.1).
    //: Картинка — испечённая паком фаза 1 подложки: fixed для Lake,
    //: scroll для Stream (в редакторе анимация не нужна).
    const waterDoc = state.mapState?.water;
    if (waterDoc && visible("вода") && Array.isArray(waterDoc.rows) &&
        waterDoc.tile) {
      const tileUrl = `/content/assets/underlay/${waterDoc.tile}_phase1_` +
                      `${waterDoc.stream ? "scroll" : "fixed"}.png`;
      const tileImg = pic(tileUrl, draw);
      for (let row = 0; row < 16; row++) {
        const bytes2 = waterDoc.rows[row];
        for (let col = 0; col < 32; col++) {
          if (bytes2.slice(col * 2, col * 2 + 2) === "00") continue;
          if (tileImg.complete && tileImg.naturalWidth) {
            brush.drawImage(tileImg, col * 256 * K, row * 256 * K,
                            256 * K, 256 * K);
          } else {
            //: подложки нет (не испечена или чужой тайл) — тёмная гладь,
            //: чтобы дыры мозаики не зияли фоном
            brush.fillStyle = "#0b2e26";
            brush.fillRect(col * 256 * K, row * 256 * K, 256 * K, 256 * K);
          }
        }
      }
    }
    const pt = state.terrain;
    if (pt && visible("тайлы")) {
      const leftEl = Math.max(0, Math.floor(kindOf.x / TILE_W) - 1);
      const rightEl = Math.min(pt.cols - 1,
        Math.ceil((kindOf.x + stage.width / (K * kindOf.zoom)) / TILE_W) + 1);
      const upperTile = Math.max(0, Math.floor(kindOf.y / TILE_H) - 1);
      const lowerTile = Math.min(pt.rows - 1,
        Math.ceil((kindOf.y + stage.height / (K * kindOf.zoom)) / TILE_H) + 1);
      for (let row = upperTile; row <= lowerTile; row++) {
        const shift2 = (row & 1) ? 0x3A : 0;
        for (let col = leftEl; col <= rightEl; col++) {
          const x = (col * TILE_W + shift2) * K;
          const y = row * TILE_H * K;
          // ТАЙЛ РИСУЕТСЯ В НАТУРАЛЬНУЮ ВЕЛИЧИНУ 114x64, А НЕ В ШАГ
          // СЕТКИ 116x32: он вдвое выше шага и заходит на соседний ряд —
          // ромбы смыкаются. Ужатый до шага, он оставлял между рядами
          // чёрные щели, и пол читался как решётка.
          const w2 = TILE_PX_W * K, it = TILE_PX_H * K;
          for (const layer of ["lower", "upper"]) {
            const index2 = pt[layer]?.[row]?.[col];
            if (index2 === null || index2 === undefined) continue;
            const img = pic(
              `/content/assets/ground/editor_tile_${index2}.png`, draw);
            if (img.complete && img.naturalWidth) {
              brush.drawImage(img, x, y, w2, it);
            } else if (layer === "lower") {
              brush.fillStyle = tileColor(index2);
              brush.fillRect(x, y, w2, it);
            }
          }
        }
      }
    }
    //: ДЕКОР — СРАЗУ ПОСЛЕ ЗЕМЛИ, ДО ОБЪЕКТОВ. Первая 12-байтовая
    //: таблица .KN2 (VA 0x42543D): берега, кувшинки, камыши. Ими
    //: прикрыта нарочно неполная базовая мозаика — без них уличные
    //: карты выглядят дырявыми, а щели между тайлами читаются решёткой.
    if (visible("декор")) {
      for (const d2 of decorRows()) {
        if (d2.x == null) continue;
        const img = pic(d2.url, draw);
        if (img.complete && img.naturalWidth) {
          brush.drawImage(img, d2.x * K, d2.y * K,
                          (d2.width || 114) * K, (d2.height || 64) * K);
        }
      }
    }
    const sp = state.mapState;
    //: Синяя подсветка клеток воды — только РЕЖИМНАЯ ПОДСКАЗКА на экране
    //: «Вода»: сама вода теперь лежит подложкой под землёй (см. выше), а
    //: здесь видно, КУДА попадает кисть — большую часть подложки закрывает
    //: мозаика.
    if (sp && state.screen === "1e" && visible("вода")) {
      brush.fillStyle = "rgba(60,130,220,.28)";
      brush.strokeStyle = "rgba(96,165,250,.8)";
      brush.lineWidth = 1;
      for (let row = 0; row < 16; row++) {
        const bytes2 = sp.water.rows[row];
        for (let col = 0; col < 32; col++) {
          if (bytes2.slice(col * 2, col * 2 + 2) !== "00") {
            brush.fillRect(col * 256 * K, row * 256 * K,
                           256 * K, 256 * K);
            brush.strokeRect(col * 256 * K, row * 256 * K,
                             256 * K, 256 * K);
          }
        }
      }
    }
    if (state.cells && (visible("проходимость") || state.screen === "1d")) {
      //: КЛЕТКА — РОМБ, А НЕ ПРЯМОУГОЛЬНИК. Разметка заливалась
      //: прямоугольниками по шагу сетки, и её край шёл зубцами: ряды
      //: смещены на полклетки, поэтому прямоугольники не смыкаются.
      //: Форма ромба — та же, что у клетки в движке (полуширина 29,
      //: полувысота 16 вокруг якоря).
      const rhomb = (row, col) => {
        const x = (col * CELL_W + ((row & 1) ? 29 : CELL_W)) * K;
        const y = (row * CELL_H + CELL_H) * K;
        brush.beginPath();
        brush.moveTo(x, y - CELL_H * K);
        brush.lineTo(x + (CELL_W / 2) * K, y);
        brush.lineTo(x, y + CELL_H * K);
        brush.lineTo(x - (CELL_W / 2) * K, y);
        brush.closePath();
        brush.fill();
      };
      // рисуем только видимую часть — 40 тысяч клеток на кадр не нужны
      const pLeft = Math.max(0, Math.floor(kindOf.x / CELL_W) - 2);
      const pRight = Math.min(159,
        Math.ceil((kindOf.x + stage.width / (K * kindOf.zoom)) / CELL_W) + 2);
      const pTop = Math.max(0, Math.floor(kindOf.y / CELL_H) - 2);
      const pBottom = Math.min(255,
        Math.ceil((kindOf.y + stage.height / (K * kindOf.zoom)) / CELL_H) + 2);
      for (let row = pTop; row <= pBottom; row++) {
        const rowEl = state.cells[row];
        if (!rowEl) continue;
        for (let col = pLeft; col <= pRight; col++) {
          //: ВСЕ БИТЫ КЛЕТКИ ВИДНЫ, а не только глушь. Прежде холст
          //: красил лишь глушь (красным) и бит выхода (зелёным):
          //: человек красил «Глухую для стрел» — и не видел НИЧЕГО,
          //: вывод был «на карте нет зон, кисти не работают». Цвета —
          //: те же, что у квадратиков в строках кистей слева.
          const [loText, hiText] = String(rowEl[col]).split(":");
          const lo = parseInt(loText, 16);
          const hi = parseInt(hiText || "0", 16);
          if ((lo & 0xFFF) === 0xFFF) {
            brush.fillStyle = "rgba(239,68,68,.28)";   // глушь — красный
            rhomb(row, col);
          }
          if (lo & 0x4000) {
            brush.fillStyle = "rgba(245,158,11,.35)";  // стрелы — янтарный
            rhomb(row, col);
          }
          if (lo & 0x1000) {
            brush.fillStyle = "rgba(34,197,94,.45)";   // бит выхода
            rhomb(row, col);
          }
          if (lo & 0x8000) {
            brush.fillStyle = "rgba(59,130,246,.30)";  // прозрачная — синий
            rhomb(row, col);
          }
          if (hi & 0x20) {
            brush.fillStyle = "rgba(71,85,105,.35)";   // внутренняя — грифель
            rhomb(row, col);
          }
          if (hi & 0x40) {
            brush.fillStyle = "rgba(14,165,233,.30)";  // свет — голубой
            rhomb(row, col);
          }
          if (hi & 0x80) {
            brush.fillStyle = "rgba(148,163,184,.35)"; // upoff — серый
            rhomb(row, col);
          }
        }
      }
    }
    // ЗОНЫ ВЫХОДОВ КАРТЫ — куда ведут переходы (из пака: exits)
    for (const door of state.packExits || []) {
      // ДВЕРЬ СТОИТ ТАМ, ГДЕ ЕЁ ПИКСЕЛЬНАЯ РАМКА. Клетки зоны перехода
      // шире самого проёма, и рамка по ним показывала дверь не на стене,
      // а рядом — пользователь честно не находил её на месте.
      const [l2, it, p2, n2] = door.box || [];
      const pixels = [l2, it, p2, n2].every(z2 => typeof z2 === "number");
      const x = pixels ? l2 * K : Math.min(...door.cols) * CELL_W * K;
      const y = pixels ? it * K : Math.min(...door.rows) * CELL_H * K;
      const w2 = pixels ? (p2 - l2) * K
        : (Math.max(...door.cols) - Math.min(...door.cols) + 1) * CELL_W * K;
      const hgt = pixels ? (n2 - it) * K
        : (Math.max(...door.rows) - Math.min(...door.rows) + 1) * CELL_H * K;
      brush.fillStyle = "rgba(120,240,160,.18)";
      brush.fillRect(x, y, w2, hgt);
      brush.strokeStyle = "rgba(120,240,160,.95)";
      brush.lineWidth = 2 / kindOf.zoom;
      brush.strokeRect(x, y, w2, hgt);
      brush.lineWidth = 1;
      brush.fillStyle = "#9df0bf";
      brush.font = `${11 / kindOf.zoom}px monospace`;
      brush.fillText(`⌂ ${door.to || "?"}`, x, y - 4 / kindOf.zoom);
    }
    //: ОБЪЯВЛЕННЫЕ, НО ЕЩЁ НЕ СОБРАННЫЕ ВЫХОДЫ. Рисовались только те,
    //: что уже в паке, — поставленную дверь человек не видел до сборки
    //: и не мог понять, встала она или нет. Жёлтым, как и всё «вне
    //: пака»; пиксельной рамки у них ещё нет, она считается сборкой,
    //: поэтому показываем по клеткам.
    //: ОДНА ДВЕРЬ — ОДНА РАМКА. После сборки та же дверь живёт в двух
    //: списках: в паке (сплошная зелёная рамка по пиксельному проёму,
    //: как в игре) и в объявленных выходах карты (жёлтый пунктир по
    //: клеткам зоны срабатывания — она всегда шире проёма). Рисовались
    //: оба — каждая собранная дверь обводилась дважды, и пунктир
    //: выглядел мусором поверх оригинала («почему у нас пунктирная?»).
    //: Собранную дверь узнаём по совпадению клеточных диапазонов и
    //: пунктиром НЕ обводим: пунктир остаётся только у поставленных, но
    //: ещё не собранных дверей — как и задумывался.
    const bakedDoors = new Set((state.packExits || []).map(d_ => {
      const rr = [...(d_.rows || [])].sort((a_, b_) => a_ - b_);
      const cc = [...(d_.cols || [])].sort((a_, b_) => a_ - b_);
      return rr.concat(cc).join(":");
    }));
    for (const door of (sp?.exits) || []) {
      const doorKey = [
        Math.min(door.row1, door.row2), Math.max(door.row1, door.row2),
        Math.min(door.col1, door.col2), Math.max(door.col1, door.col2),
      ].join(":");
      if (bakedDoors.has(doorKey)) continue;
      const x = Math.min(door.col1, door.col2) * CELL_W * K;
      const y = Math.min(door.row1, door.row2) * CELL_H * K;
      const w2 = (Math.abs(door.col2 - door.col1) + 1) * CELL_W * K;
      const hgt = (Math.abs(door.row2 - door.row1) + 1) * CELL_H * K;
      brush.fillStyle = "rgba(245,190,90,.16)";
      brush.fillRect(x, y, w2, hgt);
      brush.strokeStyle = "rgba(245,190,90,.95)";
      brush.lineWidth = 2 / kindOf.zoom;
      brush.setLineDash([6 / kindOf.zoom, 4 / kindOf.zoom]);
      brush.strokeRect(x, y, w2, hgt);
      brush.setLineDash([]);
      brush.lineWidth = 1;
      brush.fillStyle = "#f5be5a";
      brush.font = `${11 / kindOf.zoom}px monospace`;
      brush.fillText(`⌂ ${door.to_map} ${door.to_name || ""} · вне пака`,
                     x, y - 4 / kindOf.zoom);
      //: точка входа — куда игрок встанет, придя с той стороны
      const vx = (door.entry_col * CELL_W +
                  ((door.entry_row & 1) ? 29 : CELL_W)) * K;
      const vy = (door.entry_row * CELL_H + CELL_H) * K;
      brush.strokeStyle = "#f5be5a";
      brush.lineWidth = 1.5 / kindOf.zoom;
      brush.beginPath();
      brush.moveTo(vx - 6 / kindOf.zoom, vy);
      brush.lineTo(vx + 6 / kindOf.zoom, vy);
      brush.moveTo(vx, vy - 6 / kindOf.zoom);
      brush.lineTo(vx, vy + 6 / kindOf.zoom);
      brush.stroke();
      brush.lineWidth = 1;
    }
    //: СЦЕНА ОДНА НА ОБЪЕКТЫ И ЮНИТОВ — но выключатели у них РАЗНЫЕ.
    //: Условие входа стояло на слое «объекты», и снятая галка уносила
    //: заодно всех жителей: человек гасил дома, чтобы разглядеть, кто
    //: где стоит, и терял именно то, что хотел увидеть. Внутри каждый
    //: вид спрашивает свой слой сам.
    if (sp && state.objByKey && (visible("объекты") || visible("юниты"))) {
      //: ГЛУБИНА, А НЕ ПОРЯДОК ЗАПИСЕЙ.
      //:
      //: Объекты рисовались в порядке таблицы карты, а юниты — всегда
      //: ПОСЛЕ всех объектов. В игре не так: движок сортирует сцену по
      //: нижнему краю спрайта, и воин, стоящий ЗА избой, ею закрыт.
      //: Редактор показывал обратное — расстановка деревни системно
      //: врала о том, что кого перекроет, и понять это можно было
      //: только собрав карту и сходив туда в игре.
      //:
      //: Ключ глубины взят у сборки: bounds.sort_y = нижний край
      //: картинки (сверено на карте 23: position.y 446 + offset_y −76 +
      //: height 113 = sort_y 483, ровно). У юнита канон иной — «ноги
      //: плюс шесть» (живой замер оригинала, см. память проекта), и
      //: тут он к месту: юнит считается по ногам, а не по макушке.
      const sceneEl = [];
      for (const obj of (visible("объекты") ? sp.objects.records : [])) {
        const rec = state.objByKey.get(
          obj.resource_slot + ":" + (obj.palette ?? "?"));
        //: ТОЧНЫЙ КЛЮЧ БЕРЁМ ИЗ ПАКА, приближённый считаем сами. У
        //: построек с битом 0x08 ключ поднят на четверть высоты, и
        //: этого бита у редактора нет — поэтому для только что
        //: поставленного (ещё не собранного) объекта глубина
        //: приблизительна: он может лечь поверх того, за чем окажется
        //: в игре. После сборки станет точно.
        const exact = state.глубины?.[obj.slot];
        const depth2 = exact != null ? exact
          : rec ? obj.y + rec.offset_y + rec.height : obj.y;
        sceneEl.push({ глубина: depth2, рисовать: () => {
          //: БЕЗ КРЫШ — СЛОЯМИ, КАК ИГРА. У построек в паспорте лежат
          //: отдельные main (нутро без стен и кровли), walls и roof;
          //: при выключенном слое «крыши» рисуем main + walls, и людей
          //: в домах видно. Полная картинка (rec.url) содержит кровлю,
          //: из неё крышу не вычесть.
          const parts = rec?.layers;
          if (rec && state.слои.крыши === false && parts?.roof && parts?.main) {
            for (const part of [parts.main, parts.walls]) {
              if (!part) continue;
              const img = pic("/content/" + part.path, draw);
              if (img.complete && img.naturalWidth) {
                brush.drawImage(img, (obj.x + part.offset_x) * K,
                                (obj.y + part.offset_y) * K,
                                part.width * K, part.height * K);
              }
            }
          } else if (rec) {
            const img = pic(rec.url, draw);
            if (img.complete) {
              brush.drawImage(img, (obj.x + rec.offset_x) * K,
                              (obj.y + rec.offset_y) * K,
                              rec.width * K, rec.height * K);
            }
          }
          // точка привязки: у выбранного — рамка, у прочих еле заметная
          // засечка (белые квадраты у каждого объекта читались как сор)
          if (isChosen(obj)) {
            brush.strokeStyle = "#fff";
            brush.lineWidth = 2 / kindOf.zoom;
            brush.strokeRect(obj.x * K - 5 / kindOf.zoom, obj.y * K - 5 / kindOf.zoom,
                             10 / kindOf.zoom, 10 / kindOf.zoom);
            brush.lineWidth = 1;
          } else if (kindOf.zoom >= 2) {
            brush.fillStyle = "rgba(255,255,255,.35)";
            brush.fillRect(obj.x * K - 1 / kindOf.zoom, obj.y * K - 1 / kindOf.zoom,
                           2 / kindOf.zoom, 2 / kindOf.zoom);
          }
        } });
      }
      //: ЖИТЕЛИ ПАКА — 46 душ на карте, и ни одной не было видно:
      //: рисовались только добавленные редактором. Их место в мире
      //: считает сборка (расстановка по зонам отрядов), поэтому берём
      //: готовые клетки из пака.
      //: ЮНИТ РИСУЕТСЯ СВОИМ КАДРОМ, как в игре. Точка-кружок годилась
      //: только чтобы отметить место: игрок видит воина Повелителя, а
      //: редактор показывал синюю крапину. Кадр приходит с паком
      //: (frame — вырез с листа и смещения), точка привязки — «ноги».
      const mark = (cellRec, paintColor, label, isPicked, frm) => {
        const x = (cellRec.col * CELL_W + ((cellRec.row & 1) ? 29 : CELL_W)) * K;
        const y = (cellRec.row * CELL_H + CELL_H) * K;
        let drawn2 = false;
        if (frm && visible("юниты")) {
          // СЛОЯМИ, СНИЗУ ВВЕРХ: тело, доспех, шлем, оружие. Порядок
          // задаёт сценарий пака (rules.equipment_draw) — по нему юнит
          // и одет, как в игре, а не голым телом.
          for (const layer of frm.layers || [frm]) {
            const img = pic(layer.url, draw);
            if (img.complete && img.naturalWidth) {
              brush.drawImage(img, layer.x, layer.y, layer.width, layer.height,
                              x + layer.offset_x * K, y + layer.offset_y * K,
                              layer.width * K, layer.height * K);
              drawn2 = true;
            }
          }
        }
        if (!drawn2) {
          brush.fillStyle = isPicked ? "#fff" : paintColor;
          brush.beginPath();
          brush.arc(x, y, isPicked ? 5 / kindOf.zoom : 3.5 / kindOf.zoom, 0, 7);
          brush.fill();
        }
        if (isPicked) {
          brush.strokeStyle = "#fff";
          brush.lineWidth = 1.5 / kindOf.zoom;
          brush.beginPath();
          brush.arc(x, y, 7 / kindOf.zoom, 0, 7);
          brush.stroke();
          brush.lineWidth = 1;
        }
        // подписи мельчают вместе с зумом, иначе при 4x они закрывают карту
        if (kindOf.zoom >= 1.6 || isPicked) {
          brush.fillStyle = "rgba(232,240,232,.92)";
          brush.font = `${10 / kindOf.zoom}px monospace`;
          brush.fillText(label, x + 6 / kindOf.zoom, y + 3 / kindOf.zoom);
        }
      };
      //: ЮНИТ ВСТАЁТ В ТУ ЖЕ ОЧЕРЕДЬ, что и объекты, — по глубине.
      //: Канонный ключ юнита — «ноги плюс шесть» (живой замер
      //: оригинала), поэтому стоящий вплотную к избе юнит оказывается
      //: то перед ней, то за ней ровно так же, как в игре.
      const enqueue = (cellRec, paintColor, label, isPicked, frm) => {
        if (!cellRec || cellRec.col == null) return;
        const feet = cellRec.row * CELL_H + CELL_H;
        sceneEl.push({ глубина: feet + 6,
                     рисовать: () => mark(cellRec, paintColor, label, isPicked, frm) });
      };
      if (visible("юниты")) {
        for (const resident of state.packUnits || []) {
          if (!resident.cell) continue;
          enqueue(resident.cell, "#7fb2ff", resident.name || resident.id,
                   isChosen(resident), resident.frame);
        }
      }
      const draftList = sp.draft || {};
      for (const unitRec of draftList.editor_units_add || []) {
        if (!visible("юниты")) break;
        // у добавленного редактором кадра в записи нет — берём его у
        // породы из бестиария, там тот же вырез с листа
        const breedRec = breedOfUnit(unitRec);
        enqueue(unitRec.cell || {}, "#8fdf9a", unitRec.name || unitRec.id,
                 isChosen(unitRec), unitRec.frame || breedRec?.preview);
      }
      //: ВСЯ ОЧЕРЕДЬ РАЗОМ, СНИЗУ ВВЕРХ. Ничья по глубине разрешается
      //: порядком добавления — так же, как в движке разрешает её
      //: порядок записей в таблице.
      sceneEl.sort((a2, b2) => a2.глубина - b2.глубина);
      for (const what of sceneEl) what.рисовать();
      // клады: пак — тусклым золотом, черновые — ярким; тайники
      // (buried) обведены, они в игре видны только по навыку
      //: ВЫБРАННАЯ КУЧА ПОДСВЕЧИВАЛАСЬ ТОЛЬКО В СПИСКЕ, А НА ХОЛСТЕ —
      //: НИКАК. У объекта и юнита подсветка была, у кучи нет: выбрал в
      //: списке — и ищи глазами, какая из дюжины золотых точек твоя.
      const smallPile = (cellRec, paintColor, isBuried, isPicked) => {
        if (!cellRec || cellRec.col == null) return;
        const x = (cellRec.col * CELL_W + ((cellRec.row & 1) ? 29 : CELL_W)) * K;
        const y = (cellRec.row * CELL_H + CELL_H) * K;
        const side2 = 5 / kindOf.zoom;
        brush.fillStyle = isPicked ? "#fff" : paintColor;
        brush.fillRect(x - side2 / 2, y - side2 / 2, side2, side2);
        if (isBuried) {
          brush.strokeStyle = "rgba(255,255,255,.75)";
          brush.lineWidth = 1 / kindOf.zoom;
          brush.strokeRect(x - side2, y - side2, side2 * 2, side2 * 2);
          brush.lineWidth = 1;
        }
        if (isPicked) {
          brush.strokeStyle = "#fff";
          brush.lineWidth = 1.5 / kindOf.zoom;
          brush.beginPath();
          brush.arc(x, y, 8 / kindOf.zoom, 0, 7);
          brush.stroke();
          brush.lineWidth = 1;
        }
      };
      for (const pile of state.packLoot || []) {
        smallPile(pile.cell, "rgba(198,160,80,.85)", pile.buried,
               isChosen(pile));
      }
      for (const pile of draftList.editor_loot_add || []) {
        smallPile(pile.cell, "#e7c46a", pile.buried, isChosen(pile));
      }
      //: ЗОНЫ ОТРЯДА — ЭТО И ЕСТЬ «ТРАЕКТОРИЯ ПАТРУЛЯ». Отдельного
      //: маршрута движок не держит: отряд ставится в `zone` (там же его
      //: зона агрессии) и бродит в пределах `roam`. Пока рисовались
      //: только зоны черновых отрядов, а канонные — где ходят жители и
      //: стража — были не видны вовсе.
      const zoneOf = (z2, paintColor, dashed, label) => {
        if (!z2 || (z2.col_to === 0 && z2.row_to === 0 &&
                   z2.col_from === 0 && z2.row_from === 0)) return;
        const x = Math.min(z2.col_from, z2.col_to) * CELL_W * K;
        const y = Math.min(z2.row_from, z2.row_to) * CELL_H * K;
        const w2 = Math.abs(z2.col_to - z2.col_from) * CELL_W * K;
        const it = Math.abs(z2.row_to - z2.row_from) * CELL_H * K;
        brush.strokeStyle = paintColor;
        brush.lineWidth = 1.5 / kindOf.zoom;
        brush.setLineDash(dashed.map(c3 => c3 / kindOf.zoom));
        brush.strokeRect(x, y, w2, it);
        brush.setLineDash([]);
        brush.lineWidth = 1;
        if (label && kindOf.zoom >= 1.2) {
          brush.fillStyle = paintColor;
          brush.font = `${10 / kindOf.zoom}px monospace`;
          brush.fillText(label, x + 3 / kindOf.zoom, y + 11 / kindOf.zoom);
        }
      };
      if (visible("юниты")) {
        for (const band of state.packWarbands || []) {
          //: ОТРЯД ИГРОКА — НЕ ЗОНА, А ТОЧКА ВХОДА. У него запись зоны
          //: перевёрнута (94..0 x 41..0): это не прямоугольник, а место,
          //: где герой встаёт на карту. Нарисованная прямоугольником,
          //: она накрывала пол-карты красным пунктиром и читалась как
          //: огромная вражья территория.
          if (band.player) {
            const cellRec = { row: band.zone?.row_from ?? 0,
                         col: band.zone?.col_from ?? 0 };
            const x = (cellRec.col * CELL_W + ((cellRec.row & 1) ? 29 : CELL_W)) * K;
            const y = (cellRec.row * CELL_H + CELL_H) * K;
            brush.strokeStyle = "rgba(255,215,120,.95)";
            brush.lineWidth = 2 / kindOf.zoom;
            brush.beginPath();
            brush.moveTo(x - 7 / kindOf.zoom, y);
            brush.lineTo(x + 7 / kindOf.zoom, y);
            brush.moveTo(x, y - 7 / kindOf.zoom);
            brush.lineTo(x, y + 7 / kindOf.zoom);
            brush.stroke();
            brush.lineWidth = 1;
            if (kindOf.zoom >= 1.2) {
              brush.fillStyle = "#ffd778";
              brush.font = `${10 / kindOf.zoom}px monospace`;
              brush.fillText("сюда входит герой",
                             x + 9 / kindOf.zoom, y + 3 / kindOf.zoom);
            }
            continue;
          }
          //: ВРАЖДЕБНОСТЬ — ПО МЛАДШИМ БИТАМ И «бросается на игрока».
          //: Бит 0x40 стоит у отряда ИГРОКА, и проверка по маске 0x4F
          //: записывала его во враги.
          const enemy = Boolean((band.war_flags & 0x0F) || band.on_player);
          zoneOf(band.zone, enemy ? "rgba(255,120,90,.7)"
                                : "rgba(150,220,150,.6)",
               [5, 4], `отряд ${band.side}`);
          // обход патруля — шире зоны расстановки и рисуется мельче
          zoneOf(band.roam, "rgba(120,180,255,.65)", [2, 5],
               `обход ${band.side}`);
        }
      }
      for (const band of draftList.editor_warbands_add || []) {
        zoneOf(band.zone, band.war_flags ? "rgba(255,120,90,.85)"
                                         : "rgba(150,220,150,.75)",
             [5, 4], "draft");
        zoneOf(band.roam, "rgba(120,180,255,.8)", [2, 5], null);
      }
    }
  }
  function worldNum(ev) {
    const resp = stage.getBoundingClientRect();
    const mk = resp.width / stage.width;    // карточка отмасштабирована
    return { x: (ev.clientX - resp.left) / mk / (K * kindOf.zoom) + kindOf.x,
             y: (ev.clientY - resp.top) / mk / (K * kindOf.zoom) + kindOf.y };
  }
  //: ЧТО ПОД КУРСОРОМ И ЧТО ВСТАНЕТ ПО ЩЕЛЧКУ — РИСУЕМ ПОВЕРХ СЦЕНЫ.
  //:
  //: Раньше курсор был всегда «прицел», подсветки того, что под ним, не
  //: было вовсе, а в режиме расстановки человек не видел ни ЧТО он
  //: ставит, ни КУДА оно встанет относительно курсора — узнавал только
  //: после щелчка. Отсюда добрая половина «всё криво-косо»: ставишь
  //: избу, а она оказывается не там, потому что точка привязки у неё
  //: не в середине картинки, и знать об этом было неоткуда.
  let hoverItem = null, mouseWorld = null;
  function drawOver() {
    overCtx.setTransform(1, 0, 0, 1, 0, 0);
    overCtx.clearRect(0, 0, overCanvas.width, overCanvas.height);
    overCtx.setTransform(kindOf.zoom, 0, 0, kindOf.zoom,
                             -kindOf.x * K * kindOf.zoom, -kindOf.y * K * kindOf.zoom);
    //: СВОЙ РИСУНОК ЭКРАНА ПОВЕРХ СЦЕНЫ. Экрану бывает что показать
    //: независимо от мыши — зоны выбранного отряда, например: их не
    //: видно нигде, а именно они решают, где отряд встанет и куда
    //: забредёт. Рисуем ДО выхода по «мыши нет»: иначе рисунок гас,
    //: стоило отвести руку с холста.
    handlers.поверх?.(overCtx, kindOf);
    //: МЕТКА «ИГРАТЬ ОТСЮДА» — на всех экранах карты и без мыши: это
    //: свойство пробы, а не текущего инструмента, и человек должен
    //: видеть, откуда начнётся игра, не наводя курсор.
    if (state.playFrom) {
      const { row, col } = state.playFrom;
      const x = (col * CELL_W + ((row & 1) ? 29 : CELL_W)) * K;
      const y = (row * CELL_H + CELL_H) * K;
      const arm = 9 / kindOf.zoom;
      overCtx.strokeStyle = "#4ea1d3";
      overCtx.lineWidth = 2 / kindOf.zoom;
      overCtx.beginPath();
      overCtx.moveTo(x - arm, y); overCtx.lineTo(x + arm, y);
      overCtx.moveTo(x, y - arm); overCtx.lineTo(x, y + arm);
      overCtx.stroke();
      overCtx.beginPath();
      overCtx.arc(x, y, arm * 0.6, 0, Math.PI * 2);
      overCtx.stroke();
      overCtx.fillStyle = "#4ea1d3";
      overCtx.font = `${11 / kindOf.zoom}px monospace`;
      overCtx.fillText("▶ старт пробы", x + arm + 3 / kindOf.zoom,
                       y - 4 / kindOf.zoom);
      overCtx.lineWidth = 1;
    }
    if (!mouseWorld) return;
    //: 1. ПРИЗРАК ТОГО, ЧТО ВСТАНЕТ. Показываем настоящую картинку
    //: полупрозрачной, с тем же смещением привязки, с каким она ляжет.
    const placing = state.place;
    if (placing && state.editable !== false) {
      const frm = ghostFrame(placing, mouseWorld);
      if (frm) {
        overCtx.globalAlpha = 0.55;
        for (const sp of frm) {
          const img = cachedImage(sp.url);
          if (!img) continue;
          if (sp.sx != null) {
            overCtx.drawImage(img, sp.sx, sp.sy, sp.sw, sp.sh,
                                  sp.left * K, sp.top * K,
                                  sp.w * K, sp.h * K);
          } else {
            overCtx.drawImage(img, sp.left * K, sp.top * K,
                                  sp.w * K, sp.h * K);
          }
        }
        overCtx.globalAlpha = 1;
        //: перекрестье в точке привязки: именно ею вещь «садится» в
        //: карту, и без него не понять, за что её держат
        const self2 = frm.якорь || mouseWorld;
        overCtx.strokeStyle = "#7dd3fc";
        overCtx.lineWidth = 1.5 / kindOf.zoom;
        overCtx.beginPath();
        overCtx.moveTo(self2.x * K - 7 / kindOf.zoom, self2.y * K);
        overCtx.lineTo(self2.x * K + 7 / kindOf.zoom, self2.y * K);
        overCtx.moveTo(self2.x * K, self2.y * K - 7 / kindOf.zoom);
        overCtx.lineTo(self2.x * K, self2.y * K + 7 / kindOf.zoom);
        overCtx.stroke();
        overCtx.lineWidth = 1;
      }
      return;                      // в режиме расстановки подсветка лишняя
    }
    //: 2. ПОДСВЕТКА ТОГО, ЧТО ВОЗЬМЁТСЯ. Рамка по НАСТОЯЩИМ слоям кадра
    //: — той же геометрии, какой считается попадание, так что обещание
    //: и дело совпадают.
    if (!hoverItem) return;
    let l2 = Infinity, it = Infinity, p2 = -Infinity, n2 = -Infinity;
    for (const sp of hoverItem.слои) {
      l2 = Math.min(l2, sp.left); it = Math.min(it, sp.top);
      p2 = Math.max(p2, sp.left + sp.w); n2 = Math.max(n2, sp.top + sp.h);
    }
    if (!isFinite(l2)) return;
    overCtx.strokeStyle = hoverItem.двигается
      ? "rgba(125,211,252,.95)" : "rgba(148,163,184,.85)";
    overCtx.lineWidth = 1.5 / kindOf.zoom;
    overCtx.setLineDash(hoverItem.двигается
      ? [] : [4 / kindOf.zoom, 3 / kindOf.zoom]);
    overCtx.strokeRect(l2 * K, it * K, (p2 - l2) * K, (n2 - it) * K);
    overCtx.setLineDash([]);
    overCtx.lineWidth = 1;
    if (kindOf.zoom >= 1) {
      overCtx.fillStyle = "#7dd3fc";
      overCtx.font = `${10 / kindOf.zoom}px monospace`;
      overCtx.fillText(hoverItem.имя, l2 * K, it * K - 3 / kindOf.zoom);
    }
  }
  //: Слои призрака: у объекта — картинка каталога с её смещением, у
  //: юнита — кадр породы от «ног», у прочего — ничего (нечего показать).
  function ghostFrame(placing, pt) {
    if (placing.kind === "object") {
      const z2 = state.objByKey?.get(placing.slot + ":" + placing.palette);
      if (!z2) return null;
      const layerFlags = [{ left: pt.x + z2.offset_x, top: pt.y + z2.offset_y,
                      w: z2.width, h: z2.height, url: z2.url }];
      layerFlags.якорь = pt;
      return layerFlags;
    }
    //: ДЕКОР КЛАДЁТСЯ СЕРЕДИНОЙ ПОД КУРСОР. В записи лежит ЛЕВЫЙ ВЕРХНИЙ
    //: угол (движок рисует спрайт от него), но берег или камыш человек
    //: ведёт серединой — призрак показывает ровно то, что ляжет.
    if (placing.kind === "decor") {
      const w2 = placing.width || 114, h2 = placing.height || 64;
      const layerFlags = [{ left: pt.x - w2 / 2, top: pt.y - h2 / 2,
                            w: w2, h: h2, url: placing.url }];
      layerFlags.якорь = pt;
      return layerFlags;
    }
    if (placing.kind === "unit") {
      const cellRec = cellAt(pt);
      const anchor = cellAnchor(cellRec);
      const frm = placing.preview;
      const layerFlags = [];
      for (const sp of (frm?.layers || (frm ? [frm] : []))) {
        layerFlags.push({ left: anchor.x + sp.offset_x, top: anchor.y + sp.offset_y,
                    w: sp.width, h: sp.height, url: sp.url,
                    sx: sp.x, sy: sp.y, sw: sp.width, sh: sp.height });
      }
      layerFlags.якорь = anchor;
      return layerFlags.length ? layerFlags : null;
    }
    //: у кучи картинки нет — но перекрестье в клетке, куда она ляжет,
    //: обязано быть: без него взведённая постановка ничем себя не выдаёт
    if (placing.kind === "loot") {
      const layerFlags = [];
      layerFlags.якорь = cellAnchor(cellAt(pt));
      return layerFlags;
    }
    return null;
  }
  //: ЗУМ КОЛЕСОМ — К ТОЧКЕ ПОД КУРСОРОМ: мировая точка под мышью
  //: обязана остаться на месте, иначе карта «убегает» из-под руки.
  stage.addEventListener("wheel", ev => {
    ev.preventDefault();
    const before = worldNum(ev);
    const step = ev.deltaY < 0 ? 1.25 : 1 / 1.25;
    kindOf.zoom = Math.min(LIMIT.макс,
                        Math.max(LIMIT.мин, kindOf.zoom * step));
    const after2 = worldNum(ev);
    kindOf.x += before.x - after2.x;
    kindOf.y += before.y - after2.y;
    clampView();
    draw();
    status(`масштаб ${(kindOf.zoom * 100).toFixed(0)}% · ` +
           `колесо — зум, средняя кнопка (или Alt+ЛКМ) — тащить, 0 — вся карта`);
  }, { passive: false });
  //: ПАНОРАМА: средняя кнопка мыши или Alt+ЛКМ. Правая занята кистью
  //: (стирание и снятие бита), поэтому её не трогаем.
  //: ПЕРЕТАСКИВАНИЕ: нажать ЛКМ на вещи и повести. Отпустил, не сдвинув,
  //: — это щелчок, он выбирает. Так возят объекты, юнитов, кучи и декор,
  //: не считая клеток в уме.
  //: `кандидат` — на чём нажали, но ещё не повели: перенос начинается от
  //: первого сдвига мыши (см. начатьПеренос).
  let hauling = null, dragging = null, cand = null, painting = null;
  stage.addEventListener("pointerdown", ev => {
    if (ev.button === 1 || (ev.button === 0 && ev.altKey)) {
      ev.preventDefault();
      hauling = { экранX: ev.clientX, экранY: ev.clientY,
                видX: kindOf.x, видY: kindOf.y };
      stage.setPointerCapture(ev.pointerId);
      stage.style.cursor = "grabbing";
      return;
    }
    if (handlers.drag && (ev.button === 0 || ev.button === 2)) {
      // экран с кистью: зажатая кнопка красит и ведёт
      ev.preventDefault();
      painting = ev.button === 2;
      stage.setPointerCapture(ev.pointerId);
      handlers.drag(worldNum(ev), painting);
      return;
    }
    if (ev.button !== 0) return;
    const pt = worldNum(ev);
    //: НАЖАЛ И ПОТАЩИЛ — И ВСЁ. Здесь стоял таймер на 450 мс: перенос
    //: начинался, только если продержать кнопку почти полсекунды, а
    //: ЛЮБОЕ движение мыши таймер ОТМЕНЯЛО. То есть естественный жест —
    //: нажать на избу и повести — не срабатывал никогда: он сам себя и
    //: гасил. Работало ровно одно сочетание: нажать, замереть на
    //: полсекунды, и только потом вести. Догадаться об этом было
    //: неоткуда, и «объекты не двигаются» было чистой правдой, даже
    //: когда всё остальное уже чинилось.
    //:
    //: Теперь как везде: нажатие лишь запоминает кандидата, а перенос
    //: начинается от первого же сдвига мыши. Отпустил, не сдвинув, —
    //: это был обычный щелчок, и он выбирает.
    cand = { что: hitAt(pt, handlers.хватать), откуда: pt };
    if (!cand.что) cand = null;
  });
  //: Начать перенос по-настоящему: проверки те же, что были в таймере,
  //: но теперь человек уже показал намерение движением, и молчать в
  //: ответ нельзя — говорим, почему не выйдет.
  function startDrag(ev) {
    const what = cand.что;
    choose(what.вид, what.объект);
    //: НЕ ВСЁ, ЧТО ВИДНО, МОЖНО ВОЗИТЬ: у запечённого клада место в
    //: паке, у донорского героя нет исходников мира, а вещи карты из
    //: игры не правятся вовсе (см. картаЗаперта).
    if (!what.двигается) {
      status(`${what.имя}: ${what.почемуНеДвигается || "не двигается"}`);
      //: ОТКАЗ ДОЛЖЕН ВЕСТИ ТУДА, ГДЕ ВЫХОД. Строка состояния внизу —
      //: не то место, куда смотрит рука с мышью: человек тянет дерево,
      //: ничего не происходит, и вывод один — «не двигается». Кнопка
      //: копирования есть, но она в полосе наверху, и её не связывают
      //: с неудавшимся жестом. Подсвечиваем полосу в ответ на попытку.
      if (state.editable === false) blinkCanonStrip();
      cand = null; draw(); return;
    }
    //: ЗАЩИТА КАНОНА — ПРО КАРТУ, А НЕ ПРО МИР. Житель мира пишется в
    //: project/worlds (своя ручка, свои исходники), и правится он даже
    //: тогда, когда сама карта из игры и только для чтения: это разные
    //: источники. Прежде общий страж карты запрещал и его — и
    //: расстановка населения на РОДНЫХ картах игры, ради которой всё и
    //: затевалось, была бы невозможна.
    if (!state.editable && what.вид !== "packUnit") {
      status(`карта ${state.map} «${state.mapName}» — из игры, только ` +
             `просмотр: скопируйте её в свою (кнопка вверху), и правьте`);
      cand = null; draw(); return;
    }
    dragging = { что: what, откуда: cand.откуда };
    cand = null;
    //: захват указателя не обязателен для работы, но без него мышь,
    //: ушедшая за край холста, теряет события; синтетические указатели
    //: его не дают — поэтому не роняем перенос из-за отказа
    try { stage.setPointerCapture(ev.pointerId); } catch (err) { /* ок */ }
    stage.style.cursor = "grabbing";
    status(`${what.имя} — ведите мышью, отпустите чтобы поставить` +
           (what.вид === "object" || what.вид === "decor"
             ? " · Shift — по сетке земли" : ""));
  }
  stage.addEventListener("pointermove", ev => {
    rememberCursor(worldNum(ev));
    mouseWorld = worldNum(ev);
    //: НАВЕДЕНИЕ СЧИТАЕМ ТОЛЬКО КОГДА ОНО НУЖНО. Попадание перебирает
    //: все вещи карты с пробой пикселя — на каждое движение мыши это
    //: заметно; в режимах кисти, расстановки и переноса подсветка всё
    //: равно не показывается, так что и не считаем.
    const needHover = !state.place && painting === null && !dragging &&
      (handlers.хватать || []).length > 0;
    const prev = hoverItem;
    hoverItem = needHover
      ? hitAt(mouseWorld, handlers.хватать) : null;
    if (hoverItem !== prev) {
      stage.style.cursor = hoverItem
        ? (hoverItem.двигается ? "grab" : "help") : "crosshair";
    }
    drawOver();
    if (painting !== null) { handlers.drag(worldNum(ev), painting); return; }
    //: СДВИНУЛИ МЫШЬ — НАЧИНАЕМ ПЕРЕНОС. Прежде движение, наоборот,
    //: отменяло захват. Порог в ЭКРАННЫХ точках, а не в мировых: на
    //: общем плане пара мировых единиц — доли пикселя, а вблизи —
    //: полэкрана. Три точки: меньше — дрожание руки, больше — жест уже
    //: заметно «залипает».
    if (cand && !dragging) {
      const pt = worldNum(ev);
      const threshold = 3 / (K * kindOf.zoom);
      if (Math.abs(pt.x - cand.откуда.x) > threshold ||
          Math.abs(pt.y - cand.откуда.y) > threshold) {
        startDrag(ev);
      }
    }
    if (dragging) {
      const pt = worldNum(ev);
      moveBy(dragging.что, pt, ev.shiftKey);
      draw();
      return;
    }
    if (!hauling) return;
    const resp = stage.getBoundingClientRect();
    const mk = resp.width / stage.width;
    kindOf.x = hauling.видX - (ev.clientX - hauling.экранX) / mk / (K * kindOf.zoom);
    kindOf.y = hauling.видY - (ev.clientY - hauling.экранY) / mk / (K * kindOf.zoom);
    clampView();
    draw();
  });
  const release = async (ev) => {
    if (painting !== null) { painting = null; stage.dataset.lvПеренос = "1"; }
    //: отпустили, не сдвинув — это был обычный щелчок, и разбираться с
    //: ним будет обработчик click (он выберет вещь)
    cand = null;
    hauling = null;
    stage.style.cursor = "crosshair";
    if (!dragging) return;
    const what = dragging.что;
    dragging = null;
    await commitDrag(what, stage);
  };
  stage.addEventListener("pointerup", release);
  stage.addEventListener("pointercancel", release);
  //: за край карты камеру не пускаем — иначе легко «улететь» в пустоту.
  //: ВЫРОЖДЕННЫЙ СЛУЧАЙ: на слабом зуме видимая область (видноШ/видноВ)
  //: бывает БОЛЬШЕ поля 160x256 клеток целиком — тогда старый зажим
  //: Math.max(0, мир - видно) давал ровно 0, и камеру НАВСЕГДА пришпи-
  //: ливало к левому верхнему углу: и вписывание по содержимому (вид
  //: центрировал занятый прямоугольник аккуратно), и зум колесом к
  //: точке под курсором (честно считал сдвиг) — оба тут же гасились
  //: этим зажимом обратно в угол, и первый щелчок колеса «дёргал» карту
  //: на десяток с лишним клеток вместо зума на месте. Раз содержимое не
  //: заполняет экран целиком, центрируем его, а не пришпиливаем к 0 —
  //: асимметричного скачка больше нет. Полностью удержать точку под
  //: курсором тут всё равно нельзя (мировой точки за краем поля не
  //: существует) — это предел зажима, а не то, что чинит центрирование.
  function clampView() {
    const worldW = 160 * CELL_W, worldH = 256 * CELL_H;
    const seenW = stage.width / (K * kindOf.zoom);
    const seenH = stage.height / (K * kindOf.zoom);
    kindOf.x = seenW >= worldW ? (worldW - seenW) / 2
      : Math.min(Math.max(0, kindOf.x), worldW - seenW);
    kindOf.y = seenH >= worldH ? (worldH - seenH) / 2
      : Math.min(Math.max(0, kindOf.y), worldH - seenH);
  }
  stage.addEventListener("click", ev => {
    if (ev.altKey) return;             // Alt+ЛКМ — это была панорама
    if (stage.dataset.lvПеренос) {     // только что возили — не кисть
      delete stage.dataset.lvПеренос;
      return;
    }
    //: ВЫБОР СТАРТА ПРОБЫ ПЕРЕХВАТЫВАЕТ ЩЕЛЧОК ДО ЭКРАНА: он взводится
    //: из топбара и должен работать на любом экране карты, не заменяя
    //: собой инструмент экрана (кисть, каталог, выбор вещи).
    if (state.playPick) {
      setPlayFrom(cellAt(worldNum(ev)));
      return;
    }
    handlers.click?.(worldNum(ev), ev);
  });
  stage.addEventListener("contextmenu", ev => {
    ev.preventDefault();
    handlers.context?.(worldNum(ev), ev);
  });
  //: клавиши: + / − масштаб, 0 — вся карта, стрелки — шаг камерой
  const byKey = (ev) => {
    if (document.querySelector("#lv-shade")) return;   // открыта панель
    if (["INPUT", "TEXTAREA", "SELECT"].includes(
        document.activeElement?.tagName)) return;
    const cameraStep = 200 / kindOf.zoom;
    //: Esc снимает взведённый выбор старта: взвёл и передумал — не
    //: обязан ставить точку куда попало, чтобы вернуть щелчок экрану.
    if (ev.key === "Escape" && state.playPick) {
      state.playPick = false;
      paintPlayChip();
      status("выбор старта отменён");
      return;
    }
    if (ev.key === "+" || ev.key === "=") kindOf.zoom =
      Math.min(LIMIT.макс, kindOf.zoom * 1.25);
    else if (ev.key === "-") kindOf.zoom =
      Math.max(LIMIT.мин, kindOf.zoom / 1.25);
    else if (ev.key === "0") { kindOf.zoom = 1; kindOf.x = 0; kindOf.y = 0; }
    else if (ev.key === "ArrowLeft") kindOf.x -= cameraStep;
    else if (ev.key === "ArrowRight") kindOf.x += cameraStep;
    else if (ev.key === "ArrowUp") kindOf.y -= cameraStep;
    else if (ev.key === "ArrowDown") kindOf.y += cameraStep;
    else return;
    ev.preventDefault();
    clampView();
    draw();
    status(`масштаб ${(kindOf.zoom * 100).toFixed(0)}%`);
  };
  // холст пересоздаётся на каждом показе экрана: прежний слушатель
  // снимаем, иначе на десятом переключении клавиша сдвинет камеру
  // десять раз подряд
  if (mountCanvas.клавиши) {
    document.removeEventListener("keydown", mountCanvas.клавиши);
  }
  document.addEventListener("keydown", byKey);
  mountCanvas.клавиши = byKey;
  //: КАМЕРА ВПИСЫВАЕТСЯ В ЗАНЯТУЮ ЧАСТЬ. Поле карты — 160x256 клеток,
  //: а сама карта занимает от него угол: Дворец Повелителя — меньше
  //: десятой доли. Камера же вставала в ноль с масштабом 1, и человек
  //: видел крошку в море пустоты. Считаем занятый прямоугольник по
  //: земле и подгоняем масштаб под него.
  if (kindOf.вписать && state.terrain) {
    const pt = state.terrain;
    let r1 = 1e9, r2 = -1, c1 = 1e9, c2 = -1;
    for (let row = 0; row < pt.rows; row++) {
      for (let col = 0; col < pt.cols; col++) {
        if (pt.lower[row][col] === null && pt.upper[row][col] === null) continue;
        if (row < r1) r1 = row;
        if (row > r2) r2 = row;
        if (col < c1) c1 = col;
        if (col > c2) c2 = col;
      }
    }
    if (r2 >= 0) {
      const leftEl = c1 * TILE_W, topEl = r1 * TILE_H;
      const width2 = (c2 - c1 + 1) * TILE_W + TILE_PX_W;
      const height2 = (r2 - r1 + 1) * TILE_H + TILE_PX_H;
      const byX = stage.width / (K * width2);
      const byY = stage.height / (K * height2);
      kindOf.zoom = Math.max(LIMIT.мин,
                          Math.min(LIMIT.макс, Math.min(byX, byY) * 0.98));
      kindOf.x = leftEl - (stage.width / (K * kindOf.zoom) - width2) / 2;
      kindOf.y = topEl - (stage.height / (K * kindOf.zoom) - height2) / 2;
      kindOf.вписать = false;
    }
  }
  stage.addEventListener("lv-переснять", () => {
    if (atSpot()) { clampView(); draw(); drawOver(); }
  });
  //: мышь ушла с холста — гасим и подсветку, и призрак, иначе они
  //: остаются висеть на карте после того, как человек отвёл руку
  stage.addEventListener("pointerleave", () => {
    mouseWorld = null; hoverItem = null;
    stage.style.cursor = "crosshair";
    drawOver();
  });
  clampView();
  draw();
  liveStage = { рисуй: draw, вид: kindOf, рисуйПоверх: drawOver };
  return liveStage;
}
//: ПОСЛЕДНИЙ ЖИВОЙ ХОЛСТ — чтобы перерисовать его снаружи закрытия:
//: метку старта пробы ставит топбар, а рисует холст.
let liveStage = null;
//: ЧТО ЛЕЖИТ ПОД ТОЧКОЙ — ПО КАРТИНКЕ, А НЕ ПО НЕВИДИМОЙ ТОЧКЕ.
//:
//: Здесь стояло «мировая точка не дальше 40 единиц от привязки записи» —
//: квадрат 80x80 мировых единиц вокруг ЯКОРЯ. Дом занимает 425x259, и
//: якорь у него не в середине: спрайт рисуется со смещением (offset_x/
//: offset_y), обычно вверх-влево от точки. Схватить дом можно было,
//: только угадав пятую часть его ширины возле невидимой точки — отсюда
//: «объекты не перемещаются», и отсюда же «иногда получается»: квадрат
//: задан в МИРОВЫХ единицах, поэтому на приближении растёт на экране, а
//: на общем плане сжимается до семи точек.
//: У юнитов было то же: ±29 на ±32 ВОКРУГ ног, тогда как канон меряет
//: тело 30 в стороны, 92 ВВЕРХ от ног и 14 ниже (units.js:1270,
//: BODY_HALF_WIDTH/BODY_HEIGHT/BODY_BELOW) — спрайт стоит НАД точкой
//: привязки, а не вокруг неё. Декор и жителей пака не искали вовсе: их
//: рисуют, а взять нельзя.
//:
//: Делаем как сама игра (units.js unitAt): грубая рамка по НАСТОЯЩЕМУ
//: кадру, затем проба альфы под курсором, а из попавших побеждает
//: нарисованный ПОЗЖЕ — движок пишет буфер в порядке отрисовки, и
//: последний блит перекрывает прежние. Прозрачный угол избы больше не
//: перехватывает щелчок по тому, что за ней.
const probeCanvas = typeof document !== "undefined"
  ? document.createElement("canvas") : null;
if (probeCanvas) { probeCanvas.width = 1; probeCanvas.height = 1; }
const probeCtx = probeCanvas
  ? probeCanvas.getContext("2d", { willReadFrequently: true }) : null;
//: Проба альфы: один исходный пиксель в холст 1x1. null — судить не по
//: чему (кадр не загружен или холст запачкан), тогда решает грубая рамка.
function pixelOpaque(img, sx, sy) {
  if (!probeCtx || !img || !img.complete || !img.naturalWidth) return null;
  if (sx < 0 || sy < 0 || sx >= img.naturalWidth || sy >= img.naturalHeight) {
    return false;
  }
  try {
    probeCtx.clearRect(0, 0, 1, 1);
    probeCtx.drawImage(img, sx, sy, 1, 1, 0, 0, 1, 1);
    return probeCtx.getImageData(0, 0, 1, 1).data[3] > 8;
  } catch (err) {
    return null;
  }
}
function cachedImage(url) {
  const img = url ? imgCache.get(url) : null;
  return img && img.complete && img.naturalWidth ? img : null;
}
//: Якорь юнита или кучи в мировых единицах — та же формула, что у
//: отрисовки (нечётный ряд сдвинут на пол-клетки).
//: КЛЮЧ ПОРОДЫ — ПАРА, А НЕ ЧИСЛО.
//:
//: У твари порода уникальна: 0x42 это Аспид и только он. А человек —
//: это ВОСЕМЬ разных тел с одной породой 0 (чётные мужские, нечётные
//: женские, сложение разное), и с тех пор как люди появились в
//: каталоге, `найти по breed` стало давать всегда ПЕРВОЕ тело.
//:
//: Наружу это торчало двумя странностями сразу, и обе выглядели как
//: разные беды: выбираешь одно тело — подсвечиваются все восемь строк
//: (подсветка сравнивала породы), а поставленный житель рисуется чужим
//: телом и с чужими числами (кадр и образец искались по породе).
//: Запись при этом верна: тело и масть сохраняются правильно — врала
//: только картинка.
function breedKey(what) {
  const breedRec = Number(what?.breed ?? -1);
  if (!Number.isFinite(breedRec) || breedRec < 0) return null;
  return (breedRec & 0x40) ? `${breedRec}` : `${breedRec}:${Number(what?.body ?? 0)}`;
}
function breedOfUnit(unitRec) {
  const key2 = breedKey(unitRec);
  if (key2 === null) return undefined;
  return (state.bestiary?.breeds || []).find(p2 => breedKey(p2) === key2);
}
function cellAnchor(cellRec) {
  return { x: (cellRec.col || 0) * CELL_W + (((cellRec.row || 0) & 1) ? 29 : CELL_W),
           y: (cellRec.row || 0) * CELL_H + CELL_H };
}
//: Канонная рамка тела, когда кадра нет (units.js:1270).
function bodyBox(anchor) {
  return [{ left: anchor.x - 30, top: anchor.y - 92, w: 60, h: 92 + 14 }];
}
//: Рамка «на глаз» вокруг якоря — для вещей без картинки (куча, юнит без
//: кадра). ПОСТОЯННАЯ НА ЭКРАНЕ: в мировых единицах в неё не попасть на
//: общем плане, а вблизи она накрыла бы пол-карты.
function anchorBox(anchor, screenDots = 9) {
  const half2 = screenDots / (K * (state.view?.zoom || 1));
  return [{ left: anchor.x - half2, top: anchor.y - half2, w: half2 * 2, h: half2 * 2 }];
}
//: Слои кадра юнита в мировых единицах: кадр несёт вырез с листа (x/y/
//: width/height) и смещение от ног (offset_x/offset_y).
function frameLayers(frm, anchor) {
  const layerFlags = [];
  for (const sp of (frm?.layers || (frm ? [frm] : []))) {
    const img = cachedImage(sp.url);
    if (!img) continue;
    layerFlags.push({ left: anchor.x + sp.offset_x, top: anchor.y + sp.offset_y,
                w: sp.width, h: sp.height,
                обр: img, sx: sp.x, sy: sp.y, sw: sp.width, sh: sp.height });
  }
  return layerFlags;
}
//: ВСЁ, ЧТО МОЖНО СХВАТИТЬ, В ПОРЯДКЕ ОТРИСОВКИ (снизу вверх). Скрытый
//: слой не ловится: спрятал юнитов — значит хочешь работать с землёй под
//: ними, а не выбирать их вслепую.
//: ПОЧЕМУ ВЕЩЬ КАРТЫ МОЖЕТ НЕ ДВИГАТЬСЯ — ОДНА ПРИЧИНА НА ВСЕХ.
//:
//: Из 141 карты проекта правится РОВНО ОДНА своя: остальные 140 —
//: распакованная игра, их файлы держатся байт в байт равными оригиналу,
//: и сервер отказывает в правке. Редактор при этом открывается на карте
//: 1, то есть человек попадает в «только просмотр» с первой секунды.
//:
//: Пока причина жила ОДНОЙ проверкой в начатьПеренос, наружу торчало
//: вот что: наведение на дерево давало курсор «grab» — прямое обещание,
//: что вещь можно взять, — а на попытку взять приходил отказ строкой
//: состояния внизу, куда человек не смотрит. Жители мира при этом
//: возились (у них своя ручка и свои исходники), и выходило ровно
//: «нпс двигаются, а деревья нет»: инструмент выглядел сломанным
//: наполовину, хотя работал как задумано.
//:
//: Теперь причина одна и живёт в самой вещи: курсор честно показывает
//: «help», щелчок объясняет словами, стрелки не двигают, а перенос
//: зовёт полосу канона с кнопкой копирования.
//: НОМЕР ВМЕСТО ШТАМПА ВРЕМЕНИ. Кучи звались pile_new_1787891653215 —
//: тринадцать цифр, которые человеку не говорят ничего и не влезают в
//: строку списка. Серверу важен только ПРЕФИКС pile_new_ (по нему
//: черновик отличается от кучи пака), хвост — наш. Берём наименьший
//: свободный номер среди черновиков карты; старые штампы времени
//: огромны и маленьким номерам не мешают.
function nextPileId() {
  const busy = new Set();
  for (const pile of (state.mapState?.draft?.editor_loot_add) || []) {
    const m2 = /^pile_new_(\d+)$/.exec(String(pile.id || ""));
    if (m2) busy.add(Number(m2[1]));
  }
  let num = 1;
  while (busy.has(num)) num += 1;
  return `pile_new_${num}`;
}

//: ДЕКОР ХОЛСТА — ИЗ ПРОЕКТА, А ПАК ЗАПАСНОЙ.
//:
//: Рисовался он ТОЛЬКО из пака (`state.packDecor` — снимок последней
//: сборки), и поставленный берег не появлялся на карте вовсе: запись в
//: project/maps ложилась верно, а холст показывал вчерашний состав.
//: Со стороны это «поставил декор — ничего не произошло», ровно та же
//: болезнь, что была у куч и отрядов. Правки идут в проект — оттуда и
//: рисуем; пак остаётся запасным для карт, которые редактор ещё не
//: открывал своим слоем.
//:
//: Картинку и размер берём из каталога декора, если он загружен, иначе
//: из пака, иначе строим ссылку по номеру: имя файла у сборки и у
//: каталога одно и то же (assets/terrain_overlays/<префикс><номер>.png).
function decorRows() {
  const own = state.mapState?.overlays?.records;
  if (!own?.length) return state.packDecor || [];
  const known = new Map((state.decorList || []).map(d2 => [d2.id, d2]));
  const packed = new Map((state.packDecor || []).map(d2 => [d2.sprite, d2]));
  const prefix = state.mapState?.meta?.game === "legend" ? "legend" : "";
  return own.map(record => {
    const card = known.get(record.id) || packed.get(record.id) || {};
    return { slot: record.slot, sprite: record.id,
             x: record.x, y: record.y,
             width: card.width || 114, height: card.height || 64,
             url: card.url ||
               `/content/assets/terrain_overlays/${prefix}${record.id}.png` };
  });
}

function mapLocked() {
  if (state.editable !== false) return null;
  return `карта ${state.map} «${state.mapName}» из игры — только просмотр. ` +
         `Нажмите «Скопировать в свою карту» в жёлтой полосе вверху, и ` +
         `правьте копию как угодно`;
}
function canvasThings() {
  const sp = state.mapState;
  if (!sp) return [];
  const layerFlags = state.слои || {};
  const visible = (nm) => layerFlags[nm] !== false;
  const locked = mapLocked();
  const list = [];
  if (visible("декор")) {
    for (const d2 of decorRows()) {
      if (d2.x == null) continue;
      const img = cachedImage(d2.url);
      const w2 = d2.width || 114, it = d2.height || 64;
      list.push({ вид: "decor", объект: d2, имя: `декор ${d2.slot}`,
        двигается: !locked, почемуНеДвигается: locked,
        слои: [{ left: d2.x, top: d2.y, w: w2, h: it, обр: img,
                 sx: 0, sy: 0,
                 sw: img?.naturalWidth, sh: img?.naturalHeight }] });
    }
  }
  if (visible("объекты")) {
    for (const obj of sp.objects?.records || []) {
      const rec = state.objByKey?.get(
        obj.resource_slot + ":" + (obj.palette ?? "?"));
      const img = rec ? cachedImage(rec.url) : null;
      list.push({ вид: "object", объект: obj, имя: `объект ${obj.slot}`,
        двигается: !locked, почемуНеДвигается: locked,
        слои: rec
          ? [{ left: obj.x + rec.offset_x, top: obj.y + rec.offset_y,
               w: rec.width, h: rec.height, обр: img,
               sx: 0, sy: 0,
               sw: img?.naturalWidth, sh: img?.naturalHeight }]
          : anchorBox({ x: obj.x, y: obj.y }) });
    }
  }
  if (visible("юниты")) {
    for (const resident of state.packUnits || []) {
      if (!resident.cell) continue;
      const anchor = cellAnchor(resident.cell);
      const frm = frameLayers(resident.frame, anchor);
      //: ЖИТЕЛЬ МИРА ДВИГАЕТСЯ — ПРАВКОЙ ИСХОДНИКА МИРА.
      //:
      //: Здесь стояло «не двигается: место считает сборка по зоне
      //: отряда» — и это было неверно. Проверено: житель unit_9 карты 23
      //: стоит в паке ровно в клетке 51:14, как записано в
      //: project/worlds/0/maps/23.json (row 51, col 14). Зона отряда
      //: задаёт, где он БРОДИТ, а стоит он там, где сказано полями.
      //: Значит перенос по холсту осмыслен: он пишет в исходник мира.
      //:
      //: Донорские слоты (1, 6, 7, 8) не правятся: их исходников у нас
      //: нет, в project/worlds лежат только канонные миры.
      const heroSlot = state.слотГероя;
      const own = !heroSlot || heroSlot.editable;
      list.push({ вид: "packUnit", объект: resident,
        имя: resident.name || resident.id, двигается: own,
        почемуНеДвигается: heroSlot && !heroSlot.editable
          ? `${heroSlot.hero || "этот герой"} из донорской игры — ` +
            `её миры у нас только в паке, править нечего`
          : "исходников мира нет — запустите экспорт миров",
        слои: frm.length ? frm : bodyBox(anchor) });
    }
    for (const unitRec of (sp.draft?.editor_units_add) || []) {
      const anchor = cellAnchor(unitRec.cell || {});
      const breedRec = breedOfUnit(unitRec);
      const frm = frameLayers(unitRec.frame || breedRec?.preview, anchor);
      list.push({ вид: "unit", объект: unitRec, имя: unitRec.name || unitRec.id,
        двигается: !locked, почемуНеДвигается: locked,
        слои: frm.length ? frm : bodyBox(anchor) });
    }
  }
  for (const pile of state.packLoot || []) {
    if (!pile.cell) continue;
    list.push({ вид: "packLoot", объект: pile, имя: `клад ${pile.id}`,
      двигается: false,
      почемуНеДвигается: "клад уже запечён в пак — правьте до сборки",
      слои: anchorBox(cellAnchor(pile.cell)) });
  }
  for (const pile of (sp.draft?.editor_loot_add) || []) {
    if (!pile.cell) continue;
    list.push({ вид: "loot", объект: pile, имя: `куча ${pile.id}`,
      двигается: !locked, почемуНеДвигается: locked,
      слои: anchorBox(cellAnchor(pile.cell)) });
  }
  return list;
}
//: `виды` — что именно разрешено хватать на этом экране. Без него на
//: экране юнитов щелчок по избе выбирал избу, а на экране объектов —
//: жителя: инструмент ловил всё подряд, и человек не понимал, почему
//: выбралось не то. Инструмент ловит СВОЁ.
function hitAt(pt, kinds = null) {
  let rough = null;
  const goods = canvasThings();
  for (let i = goods.length - 1; i >= 0; i--) {      // сверху вниз
    const goodRec = goods[i];
    if (kinds && !kinds.includes(goodRec.вид)) continue;
    let hitByBox = false;
    for (const sp of goodRec.слои) {
      const dx = pt.x - sp.left, dy = pt.y - sp.top;
      if (dx < 0 || dy < 0 || dx >= sp.w || dy >= sp.h) continue;
      hitByBox = true;
      if (!sp.обр || !sp.sw || !sp.sh) continue;
      const sx = Math.floor(sp.sx + (dx / sp.w) * sp.sw);
      const sy = Math.floor(sp.sy + (dy / sp.h) * sp.sh);
      if (pixelOpaque(sp.обр, sx, sy)) return goodRec;
    }
    if (hitByBox && !rough) rough = goodRec;
  }
  //: Ни одного видимого пикселя — отдаём самое верхнее, во что попали
  //: рамкой: у вещи мог не загрузиться кадр, и терять её нельзя.
  return rough;
}
//: Ведём вещь за мышью — пока только на холсте, запись будет на
//: отпускании: возить по сети каждое движение незачем.
//:
//: ПРИВЯЗКА К СЕТКЕ ПО SHIFT. Объект живёт в пикселях, и поставить три
//: избы в один ряд «на глаз» нельзя: расхождение в пару точек заметно,
//: а попасть мышью точно — нет. С зажатым Shift вещь садится на узлы
//: сетки земли (шаг 0x74 на 0x20 — тот же, которым уложены тайлы), и
//: соседние постройки встают ровно, как в авторских деревнях.
function toGrid(val, step) {
  return Math.round(val / step) * step;
}
function moveBy(what, pt, snap2) {
  if (what.вид === "object" || what.вид === "decor") {
    what.объект.x = snap2 ? toGrid(pt.x, TILE_W) : Math.round(pt.x);
    what.объект.y = snap2 ? toGrid(pt.y, TILE_H) : Math.round(pt.y);
    return;
  }
  //: житель мира держит место в cell, как и все прочие: разница лишь в
  //: том, куда уйдёт запись (см. записатьПеренос)
  const cellRec = cellAt(pt);
  what.объект.cell = { row: cellRec.row, col: cellRec.col };
  if (what.объект.home) what.объект.home = { row: cellRec.row, col: cellRec.col };
}
//: ИТОГ ПЕРЕНОСА, КОТОРЫЙ САМ СЕБЯ СТИРАЛ.
//:
//: В конце переноса стоит открытьКарту — она нужна: холст вёл вещь
//: оптимистично, и после ответа сервера карту надо перечитать (при
//: отказе — чтобы вернуть вещь на место). Но открытьКарту заканчивается
//: своим status() («карта 1: объектов 115, вода 0»), и он перетирал
//: итог переноса через долю секунды — И ОТКАЗ, И УСПЕХ.
//:
//: С отказом выходило ровно то, с чего начались жалобы: вещь послушно
//: едет за курсором, на отпускании прыгает назад — и ни слова почему.
//: С успехом не лучше: подтверждения «изба → 640:320» человек не видел
//: вовсе и не знал, записалось ли.
//:
//: Держим итог отдельно и повторяем его ПОСЛЕ перечитывания — последним
//: словом должно быть то, чем кончился жест, а не пересказ карты.
async function commitDrag(what, stage) {
  stage.dataset.lvПеренос = "1";        // ближайший click — не кисть
  const obj = what.объект;
  let result = null;
  const msg = (resp, luck) => {
    result = resp.ok ? luck : (resp.note || `${what.имя}: сервер не принял перенос`);
    status(result);
  };
  if (what.вид === "object") {
    const resp = await api(`/maps/${state.map}/objects`, "POST",
      { patch: { slot: obj.slot, x: Math.round(obj.x), y: Math.round(obj.y) } });
    msg(resp, `${what.имя} → ${Math.round(obj.x)}:${Math.round(obj.y)}`);
  } else if (what.вид === "decor") {
    //: у оверлея своя таблица (T_DYNAMIC) и своя ручка; патч без обёртки
    //: add — это перенос (editor_sprite_save: {slot, x, y})
    const resp = await api(`/maps/${state.map}/overlays`, "POST",
      { slot: obj.slot, x: Math.round(obj.x), y: Math.round(obj.y) });
    msg(resp, `${what.имя} → ${Math.round(obj.x)}:${Math.round(obj.y)}`);
  } else if (what.вид === "packUnit") {
    //: ЖИТЕЛЬ МИРА ПИШЕТСЯ В ИСХОДНИК МИРА, а не в слой карты. Слой
    //: карты (editor_units) кладётся ПОВЕРХ населения ВСЕХ девяти
    //: слотов сразу — а житель принадлежит одному конкретному герою.
    //: Адресуем парой «игра + мир» из слота, а не номером слота: у
    //: слота 1 и канонного мира 1 номер один, а данные разные.
    const slotNum = state.слотГероя;
    const worldIndex = Number(String(obj.id || "").replace(/^unit_/, ""));
    if (!slotNum?.editable || !Number.isInteger(worldIndex)) {
      status(`${what.имя}: этого жителя отсюда не подвинуть — ` +
             `${slotNum && !slotNum.editable ? "донорская игра" : "нет индекса"}`);
      return;
    }
    const resp = await api(
      `/worlds/${slotNum.world}/maps/${state.map}/units`, "POST",
      { index: worldIndex,
        patch: { row: obj.cell.row, col: obj.cell.col } });
    msg(resp, `${what.имя} → клетка ${obj.cell.row}:${obj.cell.col} · в мире ` +
             `${slotNum.world} · соберите мир и пак, чтобы увидеть в игре`);
  } else {
    const layer = what.вид === "loot" ? "loot" : "units";
    const resp = await api(`/maps/${state.map}/${layer}`, "POST",
      { id: obj.id, patch: { cell: obj.cell, home: obj.cell } });
    msg(resp, `${what.имя} → клетка ${obj.cell.row}:${obj.cell.col}`);
  }
  await openMap(state.map);
  showScreen(state.screen);
  //: перечитывание перебило текст своим — возвращаем итог жеста
  if (result) status(result);
}
function groundCellAt(pt) {
  const row = Math.floor(pt.y / TILE_H);
  const col = Math.floor((pt.x - ((row & 1) ? 0x3A : 0)) / TILE_W);
  return { row, col };
}
//: КЛЕТКА ПО ТОЧКЕ — РОМБИЧЕСКАЯ, как в движке (VA 0x43B974, у клиента
//: это heroCellAt). Здесь стояло прямое деление на прямоугольник, и клик
//: у границы клетки попадал в соседнюю: юнит вставал не туда, куда
//: показывал курсор, а обратный пересчёт «клетка → точка → клетка»
//: сдвигал строку на единицу.
function cellAt(pt) {
  const half = 29;
  let x = Math.trunc(pt.x), y = Math.trunc(pt.y);
  let row = Math.trunc(y / CELL_H);
  let col, edge;
  if (row & 1) {
    col = Math.trunc(x / CELL_W);
    edge = col * CELL_W + half;
  } else {
    col = Math.trunc((x - half) / CELL_W);
    edge = col * CELL_W + CELL_W;
  }
  const bottom = (row + 1) * CELL_H;
  const top = bottom - CELL_H;
  if (x < edge) {
    if ((y - top) * (x - (edge - half)) < (edge - x) * (bottom - y)) {
      row -= 1;
      if (!(row & 1)) col -= 1;
    }
  } else if (x > edge) {
    if ((bottom - y) * (edge - x) < (x - (edge + half)) * (y - top)) {
      if (!(row & 1)) col += 1;
      row -= 1;
    }
  }
  row = Math.min(Math.max(row, 0), 255);
  col = Math.min(Math.max(col, 0), 159);
  return { row, col };
}

// пакетная кисть земли (уроки прототипа: одиночные мазки гоняются)
const strokes = [];
let flush2 = null;
function stroke2(row, col, val, redraw, layer = "lower") {
  strokes.push({ row, col, [layer]: val });
  if (state.terrain && row >= 0 && row < 160 && col >= 0 && col < 80) {
    state.terrain[layer][row][col] = val;
    redraw?.();
  }
  clearTimeout(flush2);
  flush2 = setTimeout(async () => {
    const batch = strokes.splice(0);
    const resp = await api(`/maps/${state.map}/terrain`, "POST",
      { row: batch[0].row, col: batch[0].col, cells: batch });
    if (resp.ok) status(`кисть: ${batch.length} клеток записано`);
  }, 180);
}

//: Пакетная кисть ВОДЫ — та же мысль, что у земли выше. Клетка воды
//: крупная (256 точек), поэтому ведение попадает в одну и ту же по
//: многу раз: держим последнюю записанную, чтобы не гонять повторы.
const waterStrokes = [];
let flushWater = null, lastWaterCell = "";
function waterStroke(pt, val, stage) {
  const row = Math.floor(pt.y / 256), col = Math.floor(pt.x / 256);
  if (row < 0 || row >= 16 || col < 0 || col >= 32) return;
  const key2 = `${row}:${col}:${val}`;
  if (key2 === lastWaterCell) return;
  lastWaterCell = key2;
  waterStrokes.push({ row, col, value: val });
  clearTimeout(flushWater);
  flushWater = setTimeout(async () => {
    const batch = waterStrokes.splice(0);
    lastWaterCell = "";
    if (!batch.length) return;
    const resp = await api(`/maps/${state.map}/water`, "POST",
                        { cells: batch });
    if (resp.ok) {
      await openMap(state.map);
      stage?.рисуй();
      status(`вода: ${batch.length} клеток записано`);
    }
  }, 180);
}

// ── оживление конкретных экранов ─────────────────────────────────────────
async function wakeScreen(nm, card) {
  wakeChrome(card);
  const screenWakers = {
    "1a": screen1a, "1b": screen1b, "1c": screen1c, "1d": screen1d,
    "1e": screen1e, "1f": screen1f, "1g": screen1g, "1h": screen1h,
    "1i": screen1i, "1j": screen1j, "1k": screen1k,
  };
  await screenWakers[nm]?.(card);
}

// 1a — карты проекта: живой грид по его шаблону карточки
async function screen1a(card) {
  const obj = await api("/maps");
  if (!obj.ok) return;
  const gridEl = zoneOf(card, "грид-карт");
  if (!gridEl) return;
  gridEl.style.gridAutoRows = "max-content";
  const template2 = gridEl.firstElementChild.cloneNode(true);
  const PER_PAGE = 12;
  state.mapsPage = state.mapsPage || 0;

  //: СВОИ КАРТЫ — В НАЧАЛО СПИСКА.
  //:
  //: Правится ровно та карта, у которой origin.editor; остальные — это
  //: распакованная игра, и они только для чтения. В алфавитно-числовом
  //: порядке своя карта 63 оказалась 141-й из 141, на двенадцатой
  //: странице из двенадцати: единственное место, где редактор вообще
  //: что-то правит, было спрятано дальше всего. Человек открывал первую
  //: попавшуюся карту игры и упирался в «только просмотр» — а решал,
  //: что не работает сам редактор.
  const filtered = () => {
    const z2 = state.mapsQuery || "";
    const mode = state.mapsFilter || "все";
    const pickFilter = obj.maps.filter(k2 => {
      if (z2 && String(k2.map) !== z2 &&
          !(k2.name || k2.dir || "").toLowerCase().includes(z2)) return false;
      if (mode === "с draft-правками") return Boolean(k2.draft);
      if (mode === "не собраны") return k2.built === false;
      return true;
    });
    //: устойчивая сортировка: внутри своих и внутри чужих порядок
    //: прежний, меняется только то, что своё идёт первым
    return pickFilter.sort((a2, b2) =>
      (b2.editable === true) - (a2.editable === true));
  };
  function renderPage() {
    const list = filtered();
    const totalCount = Math.max(1, Math.ceil(list.length / PER_PAGE));
    state.mapsPage = Math.min(state.mapsPage, totalCount - 1);
    gridEl.replaceChildren();
    for (const mapRec of list.slice(state.mapsPage * PER_PAGE,
                                     (state.mapsPage + 1) * PER_PAGE)) {
      const nodeEl = template2.cloneNode(true);
      nodeEl.style.boxShadow = mapRec.map === state.map
        ? "inset 3px 0 0 #2563eb,0 0 0 3px rgba(59,130,246,.18)" : "none";
      const thumb = nodeEl.firstElementChild;
      if (thumb) {
        thumb.style.background =
          `hsl(${(mapRec.map * 41) % 360} 30% 16%)`;
        thumb.style.height = "96px";
      }
      const spans = nodeEl.querySelectorAll("span");
      if (spans[0]) spans[0].textContent = mapRec.map;
      if (spans[1]) spans[1].textContent = mapRec.name || mapRec.dir;
      //: СТАТУС КАРТОЧКИ — СВОЙ, А НЕ СПИСАННЫЙ С КАРТЫ 23. Шаблон
      //: клонируется из макета вместе с бейджем «online» и строкой «пак
      //: собран · 14:32», и они стояли У КАЖДОЙ карты одинаковые — в том
      //: числе у несобранных и у пустых новых. Сервер честно считает
      //: built и draft; берём их.
      for (const badgeEl of nodeEl.querySelectorAll("[data-live-badge]")) {
        const isBuilt = mapRec.built !== false;
        badgeEl.textContent = isBuilt ? "в паке" : "не собрана";
        const paintColor = isBuilt ? "#16a34a" : "#d97706";
        badgeEl.style.color = paintColor;
        badgeEl.style.borderColor = paintColor + "55";
        badgeEl.style.background = paintColor + "18";
      }
      for (const el of nodeEl.querySelectorAll("div,span")) {
        if (el.childElementCount > 1) continue;
        const pt = el.textContent.trim();
        if (/^пак собран/.test(pt)) {
          const textNodeOf = [...el.childNodes]
            .find(n => n.nodeType === 3 && n.nodeValue.trim());
          const fresh = mapRec.built !== false
            ? "пак собран" : "в паке ещё нет";
          if (textNodeOf) textNodeOf.nodeValue = fresh;
          else el.textContent = fresh;
          el.style.color = mapRec.built !== false ? "#16a34a" : "#d97706";
        }
        if (/^\d+\s+правк/.test(pt) || /черновик/i.test(pt)) {
          el.textContent = mapRec.draft ? "есть правки вне пака"
                                      : "правок вне пака нет";
        }
      }
      //: КАРТЫ ИГРЫ ОТЛИЧАЕМ ОТ СВОИХ ПРЯМО В СПИСКЕ. Их тут полторы
      //: сотни вперемешку, и до открытия было не догадаться, что писать
      //: в них нельзя: человек выбирал «Морской лагерь» и полчаса не
      //: понимал, почему ничего не сохраняется.
      if (mapRec.editable === false) {
        nodeEl.style.opacity = ".72";
        const mark = document.createElement("span");
        mark.textContent = "из игры · только просмотр";
        mark.style.cssText =
          "display:inline-block;margin:2px 0 0;padding:1px 6px;" +
          "border-radius:999px;background:#fef3c7;color:#92400e;" +
          "font:600 9.5px 'IBM Plex Sans';white-space:nowrap";
        insertOwn(spans[1]?.parentElement || nodeEl, mark, "канон-метка");
      }
      // ЧИСЛА КАРТОЧКИ БЫЛИ ШАБЛОННЫМИ: «maps/23 · объекты 214 · юниты
      // 46» стояло у КАЖДОЙ карты, включая пустую новую. Правды о числах
      // здесь взять неоткуда (это стоило бы запроса на карту), поэтому
      // оставляем только честное — путь папки и состав файлов.
      //: ЧЕТЫРЕ СЛОВА В КАРТОЧКЕ БЫЛИ ПРИМАНКОЙ. «объекты · юниты ·
      //: отряды · клады» стоят внутри кликабельной карточки и выглядят
      //: ровно как навигация — но карточка, куда ни ткни, открывала
      //: ОДИН экран существ. Человек жмёт «объекты», попадает к
      //: бестиарию и решает, что редактор живёт своей жизнью.
      //: Раз похожи на ссылки — пусть ими и будут.
      const TAB_TO_SCREEN = { "объекты": "1b", "юниты": "1f", "отряды": "1f",
                     "клады": "1g" };
      for (const el of nodeEl.querySelectorAll("div,span")) {
        const pt = el.textContent.trim();
        if (el.childElementCount) continue;
        if (/^maps\/\d+/.test(pt)) {
          el.textContent = `maps/${mapRec.map}`;
        } else if (/^(объекты|юниты|отряды|клады)\s+\d+$/.test(pt)) {
          el.textContent = pt.split(/\s+/)[0];
        }
        const screenName = TAB_TO_SCREEN[el.textContent.trim()];
        if (!screenName) continue;
        el.style.cursor = "pointer";
        el.style.textDecoration = "underline dotted";
        el.onclick = async ev => {
          ev.stopPropagation();          // иначе сработает и клик карточки
          if (await openMap(mapRec.map)) showScreen(screenName);
        };
      }
      nodeEl.style.cursor = "pointer";
      nodeEl.onclick = async () => {
        if (await openMap(mapRec.map)) showScreen("1f");
      };
      gridEl.appendChild(nodeEl);
    }
    pageLabel(card, state.mapsPage, totalCount);
    // ЧИСЛА В ШАПКЕ И ПОДВАЛЕ. Они сидят ВНУТРИ длинных подписей —
    // «project/maps/ · 52 карты», «пак: content_build · 52/52 карт», —
    // и поиск по целой строке их не находил: макет по-прежнему уверял,
    // что карт 52, когда их 141.
    const builtCount = obj.maps.filter(k2 => k2.built !== false).length;
    for (const el of document.querySelectorAll("#stage div,#stage span")) {
      if (el.childElementCount) continue;
      const pt = el.textContent;
      // ГРАНИЦУ СЛОВА  НЕ БЕРЁМ: в JS она считается по латинице, и
      // «52 карты» ей не граница — подписи так и оставались с 52.
      if (/\d+\s+карты/.test(pt)) {
        el.textContent = pt.replace(/\d+\s+карты/,
                                  `${obj.maps.length} карт`);
      }
      if (/\d+\/\d+\s+карт/.test(pt)) {
        el.textContent = pt.replace(/\d+\/\d+\s+карт/,
                                  `${builtCount}/${obj.maps.length} карт`);
      }
      if (/^все\s*·\s*\d+$/.test(pt.trim())) {
        el.textContent = `все · ${obj.maps.length}`;
      }
      if (/^с draft-правками\s*·\s*\d+$/.test(pt.trim())) {
        el.textContent = "с draft-правками · " +
          obj.maps.filter(k2 => k2.draft).length;
      }
      if (/^не собраны\s*·\s*\d+$/.test(pt.trim())) {
        el.textContent = "не собраны · " +
          obj.maps.filter(k2 => k2.built === false).length;
      }
    }
  }
  //: ФИЛЬТРЫ СПИСКА КАРТ: все / с draft-правками / не собраны. Данные
  //: у /maps есть (draft и pack.built приходят в состоянии карты), но
  //: спрашивать их на 141 карту дорого — берём то, что уже отдаёт /maps.
  toggleOf(card, ["все", "с draft-правками", "не собраны"],
          state.mapsFilter || "все",
          label => { state.mapsFilter = label;
                       state.mapsPage = 0; renderPage(); });
  pager(card,
           () => ({ страница: state.mapsPage,
                    всего: Math.max(1,
                      Math.ceil(filtered().length / PER_PAGE)) }),
           page => { state.mapsPage = page; renderPage(); });
  liveField(card, "поиск-карт",
            () => [...card.querySelectorAll("div")]
              .filter(el => el.textContent.trim().startsWith("имя или номер") &&
                           !el.querySelector("div")).pop(),
            "имя или номер карты…",
            val => { state.mapsQuery = val;
                          state.mapsPage = 0; renderPage(); });
  renderPage();
  // «Новая карта» — панель с полями (prompt блокирует и уродует UX)
  const freshOne = [...card.querySelectorAll("button")]
    .find(b2 => b2.textContent.includes("Новая карта"));
  if (freshOne) freshOne.onclick = () => {
    panelEl("Новая карта", win => {
      win.innerHTML = `
        <label style="display:flex;justify-content:space-between;
          margin:6px 0">номер <input id="lv-num" type="number"
          value="63" style="width:90px"></label>
        <label style="display:flex;justify-content:space-between;
          margin:6px 0">имя <input id="lv-name" value="Новая весь"
          style="width:170px"></label>`;
      const okay = document.createElement("button");
      okay.textContent = "Создать";
      okay.style.cssText = "width:100%;margin-top:8px;padding:6px;" +
        "background:#2563eb;color:#fff;border:0;border-radius:5px;" +
        "cursor:pointer";
      okay.onclick = async () => {
        const num = Number(win.querySelector("#lv-num").value);
        const titleText = win.querySelector("#lv-name").value
          || "Новая весь";
        const resp = await api("/maps", "POST",
                            { map: num, name: titleText });
        if (resp.ok) {
          closePanel();
          status(`создан проект ${resp.dir}`);
          if (await openMap(num)) showScreen("1c");
        }
      };
      win.appendChild(okay);
    });
  };
}

//: Всплывающая панель в стиле дизайна — для форм и сюжета.
function panelEl(title2, fillIn) {
  closePanel();
  const film = document.createElement("div");
  film.id = "lv-shade";
  film.style.cssText = "position:fixed;inset:0;z-index:900;" +
    "background:rgba(2,6,23,.55)";
  film.onclick = ev => { if (ev.target === film) closePanel(); };
  const win = document.createElement("div");
  win.style.cssText = "position:absolute;left:50%;top:8%;" +
    "transform:translateX(-50%);min-width:340px;max-width:760px;" +
    "max-height:84%;overflow:auto;background:#fff;border-radius:10px;" +
    "padding:14px 16px;font:13px 'IBM Plex Sans',sans-serif;" +
    "color:#0f172a;box-shadow:0 12px 40px rgba(2,6,23,.4)";
  win.innerHTML = `<div style="font:600 14px 'IBM Plex Sans';` +
    `margin-bottom:8px;display:flex;justify-content:space-between">` +
    `<span>${title2}</span><span id="lv-close" style="cursor:pointer;` +
    `color:#64748b">✕</span></div>`;
  film.appendChild(win);
  document.body.appendChild(film);
  win.querySelector("#lv-close").onclick = closePanel;
  fillIn(win);
}
function closePanel() {
  document.getElementById("lv-shade")?.remove();
}

// 1c — ландшафт: его палитру заменяем живыми превью тайлов
async function screen1c(card) {
  const stage = mountCanvas(card, {
    хватать: CATCH["1c"],
    click: async (pt, ev) => {
      const cellRec = groundCellAt(pt);
      if (!(cellRec.row >= 0 && cellRec.row < 160 &&
            cellRec.col >= 0 && cellRec.col < 80)) return;
      // Shift+клик — два угла: заливка области одним телом (как 1d)
      if (ev?.shiftKey) {
        if (!state.area) { state.area = cellRec;
          status(`угол А ${cellRec.row}:${cellRec.col} — Shift+клик угла Б`);
          return; }
        const a2 = state.area;
        state.area = null;
        const layer = state.groundLayer || "lower";
        const val = state.erase ? null : state.brushTile;
        const batch = [];
        for (let r = Math.min(a2.row, cellRec.row);
             r <= Math.max(a2.row, cellRec.row); r++) {
          for (let c = Math.min(a2.col, cellRec.col);
               c <= Math.max(a2.col, cellRec.col); c++) {
            batch.push({ row: r, col: c, [layer]: val });
          }
        }
        const resp = await api(`/maps/${state.map}/terrain`, "POST",
          { row: a2.row, col: a2.col, cells: batch });
        if (resp.ok) {
          status(`заливка: ${batch.length} тайлов`);
          const pt2 = await api(`/maps/${state.map}/terrain`);
          if (pt2.ok) { state.terrain = pt2; stage?.рисуй(); }
        }
        return;
      }
      groundBrush(cellRec, stage);
    },
    context: pt => {
      const cellRec = groundCellAt(pt);
      groundBrush(cellRec, stage, true);
    },
    //: РИСОВАНИЕ УДЕРЖАНИЕМ — как в авторском редакторе (EDIT.TXT,
    //: режим TILE): «левый клик на нужный тайл ИЛИ левый клик с
    //: удержанием кнопки для заполнения области тайлов», правый — то же
    //: для удаления. Прежде область набиралась двумя Shift-кликами по
    //: углам, и это ни на что в оригинале не походило.
    drag: (pt, eraseAt) => groundBrush(groundCellAt(pt), stage, eraseAt),
  });
  //: «Тайл под курсором» — панель справа была намертво впечатана в
  //: макет («row 44 · col 66», «44», «— пусто»): курсор двигали, а
  //: числа не менялись. Курсор уже помнится глобально (подКурсором,
  //: его читают INS/DEL) — просто красим четыре строки на каждом
  //: pointermove.
  const positionRow = rowValue(card, "Позиция");
  const lowerRow = rowValue(card, "Нижний слой");
  const upperRow = rowValue(card, "Верхний слой");
  const lightRow = rowValue(card, "Свет клетки");
  function refreshCursorPanel() {
    if (!hoverPoint || !state.terrain) return;
    const cellRec = groundCellAt(hoverPoint);
    if (!(cellRec.row >= 0 && cellRec.row < 160 && cellRec.col >= 0 && cellRec.col < 80)) return;
    if (positionRow) positionRow.textContent = `row ${cellRec.row} · col ${cellRec.col}`;
    const bottomEl = state.terrain.lower?.[cellRec.row]?.[cellRec.col];
    if (lowerRow) {
      (lowerRow.querySelector("span") || lowerRow).textContent =
        bottomEl != null ? String(bottomEl) : "— пусто";
    }
    const topEl = state.terrain.upper?.[cellRec.row]?.[cellRec.col];
    if (upperRow)
      upperRow.textContent = topEl != null ? String(topEl) : "— пусто";
    const lightNum = state.terrain.light?.[cellRec.row]?.[cellRec.col];
    if (lightRow) lightRow.textContent =
      lightNum != null ? `0x${lightNum.toString(16).padStart(2, "0")}` : "— нет";
  }
  card.querySelector("canvas")
    ?.addEventListener("pointermove", refreshCursorPanel);
  refreshCursorPanel();
  //: СТАТУС-СТРОКА «слой: нижний» — тоже вписана в макет намертво,
  //: хотя переключатель слоя тут же рядом. Красим при заходе на экран
  //: и на каждой смене слоя.
  const layerRow = organOf(card, "слой:", false);
  const layerLabel = { lower: "нижний", upper: "верхний", light: "свет" };
  function refreshLayerStatus() {
    if (layerRow) layerRow.узел.textContent =
      "слой: " + (layerLabel[state.groundLayer] || "нижний");
  }
  refreshLayerStatus();
  // «Нижний / Верхний / Свет» — В КАКОЙ СЛОЙ пишет кисть. Слоёв у клетки
  // земли три: два тайла (низ и верх, пара пикселей layer1.png) и свет
  // (layer2.png); писать всегда в низ — значит не дать нарисовать ни
  // переходы, ни освещение.
  toggleOf(card, ["Нижний", "Верхний", "Свет"],
          state.groundLayer === "upper" ? "Верхний"
            : state.groundLayer === "light" ? "Свет" : "Нижний",
          label => {
            state.groundLayer = label === "Верхний" ? "upper"
              : label === "Свет" ? "light" : "lower";
            status("кисть пишет: " + label.toLowerCase());
            refreshLayerStatus();
          });
  // «Кисть 1 2 3» — сторона квадрата мазка в клетках земли.
  toggleOf(card, ["1", "2", "3"], String(state.brushSize || 1),
          label => { state.brushSize = Number(label) || 1;
                       status(`кисть ${label}x${label}`); });
  // «ластик» — тот же мазок пустотой; ПКМ делает то же самое.
  const eraser = organOf(card, "ластик", false);
  bindTo(eraser, () => {
    state.erase = !state.erase;
    if (eraser) {
      eraser.рамка.style.background = state.erase ? "#0f172a" : "transparent";
      eraser.узел.style.color = state.erase ? "#f8fafc" : "";
    }
    status(state.erase ? "ластик: клик стирает" : "ластик выключен");
  });
  await liveTilePalette(card);
}
//: КЛАВИШИ АВТОРСКОГО РЕДАКТОРА (EDIT.TXT). Их язык одинаков во всех
//: режимах, и держаться его дешевле, чем выдумывать свой:
//:   INS   — взять под курсором: тайл становится активной картинкой,
//:           объект и ландшафт — копируются;
//:   DEL   — удалить то, что под курсором;
//:   SPACE — взять вещь «в руку» (у нас это же делает удержание ЛКМ);
//:   стрелки — точное смещение взятого.
//: Курсор помним по последнему движению мыши над холстом.
let hoverPoint = null;
//: «мазков за сессию: 38» — счётчик мазков кисти земли; статус-строка
//: 1c. Не привязан к экрану: копится, пока открыт редактор, как и
//: заявлено подписью «за сессию».
let strokesThisSession = 0;
function rememberCursor(pt) { hoverPoint = pt; }
document.addEventListener("keydown", async ev => {
  if (["INPUT", "TEXTAREA", "SELECT"].includes(
      document.activeElement?.tagName)) return;
  if (document.querySelector("#lv-shade")) return;
  const stage = document.querySelector("#stage .dv-card canvas");
  if (!stage || !state.map) return;

  //: N на «Кладах» — куча в клетку курсора, как и обещает подпись
  //: «N — новая в клетке курсора» (обещание было пустым: клавишу не
  //: подключили вовсе). Явный жест — в отличие от клика по пустому
  //: месту, который кучу больше не создаёт.
  if (ev.key.toLowerCase() === "n" && state.screen === "1g" &&
      !ev.ctrlKey && !ev.altKey) {
    if (!state.editable) { status(mapLocked()); return; }
    if (!hoverPoint) { status("наведите курсор на карту и нажмите N"); return; }
    ev.preventDefault();
    const cellRec = cellAt(hoverPoint);
    const id = nextPileId();
    const resp = await api(`/maps/${state.map}/loot`, "POST", {
      id, patch: { id, on_floor: true, buried: false, money: 25,
                   items: [], details: [], cell: cellRec } });
    if (resp.ok) {
      await openMap(state.map);
      showScreen(state.screen);
      status(`клад ${cellRec.row}:${cellRec.col} · 25 монет`);
    }
    return;
  }
  if (ev.key === "Insert") {
    ev.preventDefault();
    if (state.screen === "1c" && hoverPoint && state.terrain) {
      // пипетка: тайл под курсором становится активной картинкой
      const cellRec = groundCellAt(hoverPoint);
      const layer = state.groundLayer || "lower";
      const index2 = state.terrain[layer]?.[cellRec.row]?.[cellRec.col];
      if (index2 != null) {
        state.brushTile = index2;
        state.erase = false;
        status(`взят тайл ${index2} (${layer}) — рисуйте`);
        showScreen(state.screen);
      }
      return;
    }
    const what = hoverPoint && hitAt(hoverPoint);
    if (what) { choose(what.вид, what.объект); await cloneIt(); }
    return;
  }
  if (ev.key === "Delete") {
    if (state.screen === "1c" && hoverPoint) {
      ev.preventDefault();
      groundBrush(groundCellAt(hoverPoint), null, true);
      status("тайл убран");
      return;
    }
    return;                       // прочее удаление уже висит ниже
  }
  // точное смещение взятого — стрелками, как в оригинале
  if (selectedOf() && ev.shiftKey && ev.key.startsWith("Arrow")) {
    ev.preventDefault();
    const step = { ArrowLeft: [-1, 0], ArrowRight: [1, 0],
                  ArrowUp: [0, -1], ArrowDown: [0, 1] }[ev.key];
    const p2 = selectedOf(), kindOf = pickKind();
    //: сдвигаем только то, что вообще двигается: у жителя пака место
    //: считает сборка, у декора и объекта — пиксели, у юнита и кучи —
    //: клетки. Прежде вид угадывался по наличию полей x/cell, и житель
    //: пака честно «сдвигался» на экране, а на сервер уходил патч,
    //: которого тот не ждал.
    if (!state.editable) { status("карта из игры — только просмотр"); return; }
    if (kindOf === "packUnit" || kindOf === "packLoot") {
      status("житель пака стрелками не двигается — место считает сборка");
      return;
    }
    if (kindOf === "object" || kindOf === "decor") {
      p2.x += step[0] * 4; p2.y += step[1] * 4;
      const path2 = kindOf === "decor" ? "overlays" : "objects";
      const bodyNum = kindOf === "decor"
        ? { slot: p2.slot, x: Math.round(p2.x), y: Math.round(p2.y) }
        : { patch: { slot: p2.slot, x: Math.round(p2.x), y: Math.round(p2.y) } };
      await api(`/maps/${state.map}/${path2}`, "POST", bodyNum);
    } else if (p2.cell) {
      p2.cell = { row: Math.max(0, p2.cell.row + step[1]),
                 col: Math.max(0, p2.cell.col + step[0]) };
      const layer = kindOf === "loot" ? "loot" : "units";
      await api(`/maps/${state.map}/${layer}`, "POST",
        { id: p2.id, patch: { cell: p2.cell, home: p2.cell } });
    }
    status("сдвинуто стрелкой");
    await openMap(state.map);
    showScreen(state.screen);
  }
});

//: Мазок по земле с учётом слоя, размера кисти и ластика.
function groundBrush(cellRec, stage, rightCol = false) {
  const eraseAt = rightCol || state.erase;
  const val = eraseAt ? null : state.brushTile;
  const sideNum = Math.max(1, state.brushSize || 1);
  const layer = state.groundLayer || "lower";
  for (let dr = 0; dr < sideNum; dr++) {
    for (let dc = 0; dc < sideNum; dc++) {
      const row = cellRec.row + dr, col = cellRec.col + dc;
      if (row < 0 || row >= 160 || col < 0 || col >= 80) continue;
      stroke2(row, col, val, stage?.рисуй, layer);
    }
  }
  strokesThisSession++;
  const strokesRow = organOf(document.querySelector("#stage .dv-card"),
                          "мазков за сессию:", false);
  if (strokesRow) strokesRow.узел.textContent =
    `мазков за сессию: ${strokesThisSession}`;
}
async function liveTilePalette(card) {
  const obj = await api(`/catalog/tiles?page=${state.tilePage}`);
  if (!obj.ok) return;
  // зона палитры: левая колонка со множеством мелких картинок-плиток —
  // ищем контейнер с большим числом одинаковых ячеек
  const paletteZone = zoneOf(card, "палитра-тайлов");
  if (!paletteZone) return;
  paletteZone.replaceChildren();
  paletteZone.style.display = "flex";
  paletteZone.style.flexWrap = "wrap";
  paletteZone.style.gap = "3px";
  paletteZone.style.alignContent = "flex-start";
  for (const tileNum of obj.tiles) {
    //: НОМЕР ПОД ПЛИТКОЙ. Палитра — россыпь одинаковых полосок земли, и
    //: понять, что именно взято, было нельзя: номер жил только в
    //: всплывающей подсказке, а он и есть то, чем тайл зовётся везде
    //: (в grid.txt, в POST /terrain, в панели «Тайл под курсором»).
    const slotCell = document.createElement("div");
    slotCell.style.cssText = "display:flex;flex-direction:column;" +
      "align-items:center;gap:1px;cursor:pointer;padding:1px;" +
      "border-radius:3px;border:1px solid " +
      (state.brushTile === tileNum.index ? "#2563eb" : "transparent") +
      (state.brushTile === tileNum.index ? ";background:#dbeafe" : "");
    const i2 = document.createElement("img");
    i2.src = tileNum.url;
    i2.title = "тайл " + tileNum.index;
    i2.style.cssText = "width:56px;height:16px;object-fit:cover;" +
      "cursor:pointer";
    const num = document.createElement("span");
    num.textContent = tileNum.index;
    num.style.cssText = "font:9px 'IBM Plex Mono';color:" +
      (state.brushTile === tileNum.index ? "#1d4ed8" : "#94a3b8");
    slotCell.append(i2, num);
    slotCell.onclick = () => { state.brushTile = tileNum.index;
                             liveTilePalette(card); };
    paletteZone.appendChild(slotCell);
  }
  // страницы палитры — ЕГО стрелки и его подпись «стр 1/7», а не свои
  // кнопки под сеткой (те дублировали орган и путали)
  pager(card,
           () => ({ страница: state.tilePage, всего: obj.pages || 1 }),
           page => { state.tilePage = page;
                         liveTilePalette(card); });
  pageLabel(card, state.tilePage, obj.pages || 1);
  // счётчик «GRAPH · 96 тайлов» — сколько их на самом деле
  for (const el of card.querySelectorAll("div,span")) {
    if (el.childElementCount === 0 &&
        /^GRAPH\s*·\s*\d+\s+тайл/.test(el.textContent.trim())) {
      el.textContent = `GRAPH · ${obj.total ?? obj.tiles.length} тайлов`;
    }
  }
}

// 1e — вода
async function screen1e(card) {
  const stage = mountCanvas(card, {
    хватать: CATCH["1e"],
    //: ВОДА КРАСИТСЯ ВЕДЕНИЕМ И ПАЧКОЙ, как земля. Каждый клик уходил
    //: на сервер отдельным запросом, и КАЖДЫЙ ложился отдельной записью
    //: в журнал отмены — общий на весь сервер и глубиной в 30 шагов.
    //: Одно озеро (сотня клеток) вытесняло оттуда всю прежнюю работу:
    //: Ctrl+Z после заливки откатывал только воду по клетке, а всё, что
    //: делали до неё, из истории уже выпало. Собираем мазки и шлём
    //: одним телом, как кистьЗемли.
    click: pt => waterStroke(pt, 1, stage),
    context: pt => waterStroke(pt, 0, stage),
    drag: (pt, eraseAt) => waterStroke(pt, eraseAt ? 0 : 1, stage),
  });
  //: ТИП ВОДЫ — ОДИН НА КАРТУ (канон: тип = OR всех 512 байтов; 0x80
  //: Lake стоит, 0x40 Stream течёт), поэтому «Конвертировать в Stream»
  //: переливает ВСЕ клетки разом, а подпись «Lake · 0x80» показывает
  //: нынешний тип.
  const setWaterType = async (isStream) => {
    if (Boolean(state.mapState?.water?.stream) === Boolean(isStream)) {
      status(`вода уже ${isStream ? "Stream · течёт" : "Lake · стоит"}`);
      return;
    }
    const resp = await api(`/maps/${state.map}/water`, "POST",
                        { stream: Boolean(isStream) });
    //: итог ПОСЛЕ перечитывания — иначе его съедал статус открытьКарту
    if (resp.ok) { await openMap(state.map);
                showScreen(state.screen);
                status(`вода: ${isStream ? "Stream · 0x40 (течёт)"
                                      : "Lake · 0x80 (стоит)"} — ` +
                       `перелиты ВСЕ клетки, тип один на карту`); }
  };
  bindTo(organOf(card, "Конвертировать", false),
           () => setWaterType(!state.mapState?.water?.stream));
  //: ТАЙЛ ПОДЛОЖКИ — ЧЕСТНОЕ ЧИСЛО, А НЕ «71 · море / 72 · озеро».
  //: Макетная пара была выдумкой: тайлы 71/72 в GRAPH.RES — каменистые
  //: кочки 114x64, не вода, и записанные ею числа ломали воду карты
  //: (builder не печёт подложку из кочки). Канонная подложка одна —
  //: гнездо 160 у всех 140 родных карт; 0 выключает воду целиком
  //: (docs/WATER_EDITOR_SPEC.md §5.2). Поле пишет document.light_flag —
  //: номер ОДИН на карту.
  //: вхождений три: пара кнопок (прячем все) и строка состояния «Тайл»
  //: в правой панели — её не прячем, а переписываем честным числом
  for (const nodeEl of card.querySelectorAll("div,span")) {
    if (nodeEl.childElementCount !== 0) continue;
    if (!/^7[12] · (море|озеро)$/.test(nodeEl.textContent.trim())) continue;
    const rowText = (nodeEl.parentElement?.textContent || "").trim();
    if (/^Тайл/.test(rowText)) {
      nodeEl.textContent = String(state.mapState?.water?.tile ?? 160);
    } else {
      nodeEl.style.display = "none";
    }
  }
  {
    const rowEl = document.createElement("div");
    rowEl.style.cssText = "display:flex;align-items:center;gap:6px;" +
      "margin:6px 4px;font:12px 'IBM Plex Sans';color:#334155";
    const cap = document.createElement("span");
    cap.textContent = "тайл подложки";
    const box = document.createElement("input");
    box.type = "number";
    box.min = "0";
    box.value = String(state.mapState?.water?.tile ?? 160);
    box.style.cssText = "width:64px;padding:3px 6px;border:1px solid " +
      "#cbd5e1;border-radius:6px;font:12px 'IBM Plex Mono'";
    const hint = document.createElement("span");
    hint.textContent = "канон 160 · 0 — воды нет";
    hint.style.cssText = "color:#64748b;font-size:11px";
    box.onchange = async () => {
      const tileNum = Number(box.value);
      if (!Number.isInteger(tileNum) || tileNum < 0) {
        status("тайл подложки — целое число, 0 или больше"); return;
      }
      const resp = await api(`/maps/${state.map}/water`, "POST",
                          { tile: tileNum });
      if (!resp.ok) { status(resp.note || "не вышло"); return; }
      if (state.mapState?.water) state.mapState.water.tile = tileNum;
      stage?.рисуй();
      status(tileNum === 160 ? "тайл подложки: 160 (канон)"
        : tileNum === 0 ? "вода на карте выключена (light_flag 0)"
        : `тайл подложки: ${tileNum} — в паке испечён только 160, ` +
          "в игре такой воды не будет");
    };
    rowEl.append(cap, box, hint);
    const anchorOrg = organOf(card, "Конвертировать", false, true);
    const anchorEl = anchorOrg && (anchorOrg.рамка || anchorOrg.узел);
    insertOwn(anchorEl?.parentElement || card, rowEl, "тайл-подложки",
              anchorEl || null);
  }
  // живые числа панели: тип, клеток воды, тайл
  const waterState = state.mapState?.water;
  const waterTypes = [];
  if (waterState) {
    for (const el of card.querySelectorAll("div,span")) {
      const pt = el.textContent.trim();
      //: ДВЕ КНОПКИ, А НЕ ДВЕ КОПИИ ОДНОЙ ПОДПИСИ. Здесь стояло
      //: «показать нынешний тип», и цикл переписывал ОБА узла пары —
      //: сегментный переключатель макета превращался в «Lake · 0x80»
      //: и «Lake · 0x80». Выбор из одинакового: жмёшь вторую, а она
      //: та же самая. Ниже пара подписывается по своим местам.
      if (/^(Lake|Stream)\s*·\s*0x[0-9a-f]{2}$/i.test(pt) &&
          el.childElementCount === 0) {
        waterTypes.push(el);
        continue;
      }
      if (/^\d+\/512$/.test(pt)) {
        if (el.childElementCount === 0) {
          el.textContent = `${waterState.count}/512`;
        } else {
          // СЧЁТЧИК ВЛОЖЕН В <span>N<span>/512</span></span> — старый
          // поиск требовал childElementCount===0 и пропускал узел
          // целиком, счётчик слева навсегда стоял на «498/512» из
          // макета. Правим только ведущий текстовый узел с числом, не
          // трогая вложенный span.
          const numberNode = [...el.childNodes]
            .find(n => n.nodeType === 3 && /\d/.test(n.nodeValue));
          if (numberNode) numberNode.nodeValue = String(waterState.count);
        }
      }
    }
    //: ПАРА ПОДПИСЫВАЕТСЯ ПО МЕСТАМ: первая кнопка — стоячая вода,
    //: вторая — текучая. Выбранная тёмная, чужая бледная; щелчок по
    //: выбранной ничего не делает и говорит об этом.
    waterTypes.slice(0, 2).forEach((nodeEl, spot) => {
      const isStream = spot === 1;
      nodeEl.textContent = isStream ? "Stream · 0x40" : "Lake · 0x80";
      nodeEl.title = isStream ? "текучая вода: тип 0x40, один на всю карту"
                         : "стоячая вода: тип 0x80, один на всю карту";
      const isOwn = Boolean(waterState.stream) === isStream;
      nodeEl.style.cursor = "pointer";
      nodeEl.style.background = isOwn ? "#0f172a" : "transparent";
      nodeEl.style.color = isOwn ? "#f8fafc" : "#334155";
      nodeEl.style.opacity = isOwn ? "1" : ".6";
      nodeEl.style.borderRadius = "6px";
      nodeEl.style.padding = "6px 10px";
      nodeEl.onclick = () => setWaterType(isStream);
      nodeEl.dataset.lv = "тип-воды";
    });
    //: Остальные такие подписи — не кнопки, а строки состояния (панель
    //: справа). Им показываем НЫНЕШНИЙ тип: иначе на карте с текучей
    //: водой рядом с выбранным «Stream» висело макетное «Lake».
    for (const nodeEl of waterTypes.slice(2)) {
      nodeEl.textContent = waterState.stream ? "Stream · 0x40" : "Lake · 0x80";
    }
    //: ДАМП ПОДЛОЖКИ — НАСТОЯЩИЙ, А НЕ ИЗ МАКЕТА.
    //:
    //: Здесь висели четыре выдуманные строки дизайнера («r5 000…8080»),
    //: одна для красоты подсвечена. Человек читает их как данные карты и
    //: спрашивает «это зачем тут?» — потому что они не про его карту и
    //: ни на что не отвечают. А настоящие строки пак отдаёт всё это
    //: время: подложка воды это 16 рядов по 32 байта, ровно тот «hex64»,
    //: что обещает заголовок.
    //:
    //: Показываем ВСЕ шестнадцать, помечая ряды с водой: по ним сразу
    //: видно, где она есть, а нули остаются приглушёнными.
    const dumpHead = [...card.querySelectorAll("span")]
      .find(el => el.childElementCount === 0 &&
                 el.textContent.trim() === "rows · hex64");
    const dumpBox = dumpHead?.closest("div")?.nextElementSibling;
    if (dumpBox && Array.isArray(waterState.rows)) {
      dumpBox.style.overflow = "auto";
      dumpBox.style.maxHeight = "168px";
      dumpBox.replaceChildren();
      waterState.rows.forEach((line, num) => {
        const emptyEl = /^0*$/.test(line);
        const rowEl = document.createElement("div");
        rowEl.style.cssText = "white-space:pre;color:" +
          (emptyEl ? "#475569" : "#a5f3fc");
        rowEl.textContent =
          `r${String(num).padStart(2, " ")} ${line}`;
        dumpBox.appendChild(rowEl);
      });
      //: «16 строк» рядом с заголовком — тоже из макета; говорим правду
      const tally = dumpHead.parentElement?.lastElementChild;
      if (tally && /строк/.test(tally.textContent || "")) {
        const withWater = waterState.rows.filter(resp => !/^0*$/.test(resp)).length;
        tally.textContent = `${waterState.rows.length} строк · с водой ${withWater}`;
      }
    }
  }
}

//: Карточка кисти по любому её узлу: подъём до div, среди прямых детей
//: которого цветной квадратик 14x14 из макета. Подъём «до первого
//: родителя с двумя детьми» дважды приводил не туда — во внутреннюю
//: колонку «заголовок+подпись», у которой тоже два ребёнка.
function brushCardOf(nodeEl, card) {
  let aim = nodeEl;
  for (let resp = nodeEl.parentElement; resp && resp !== card;
       resp = resp.parentElement) {
    aim = resp;
    const swatch = [...resp.children].some(ch =>
      ch.tagName === "SPAN" &&
      /width:\s*14px/.test(ch.getAttribute("style") || ""));
    if (swatch) break;
  }
  return aim;
}

// 1d — проходимость: его кнопки-биты как кисти
async function screen1d(card) {
  const stage = mountCanvas(card, {
    хватать: CATCH["1d"],
    //: РЕЗИНКА, КАК В ПАИНТЕ. Прямоугольник набирается двумя углами —
    //: и клеток, и проёма выхода, — но между щелчками не было видно
    //: НИЧЕГО: первый угол молча запоминался, и человек узнавал, что
    //: он залил, только после второго. Отсюда «у нас такого нет,
    //: приходится тыкать каждую клетку»: жест был, а показать его
    //: было нечем.
    поверх: (brush, kindOf) => {
      const first = state.exitArm ? state.exitCorner : state.area;
      const currentCell = hoverPoint && cellAt(hoverPoint);
      if (!first || !currentCell) return;
      const corners = [[first.row, first.col], [first.row, currentCell.col],
                    [currentCell.row, currentCell.col], [currentCell.row, first.col]]
        .map(([r, c]) => cellAnchor({ row: r, col: c }));
      const paintColor = state.exitArm ? "#16a34a" : "#2563eb";
      brush.strokeStyle = paintColor;
      brush.fillStyle = paintColor + "22";
      brush.lineWidth = 2 / kindOf.zoom;
      brush.setLineDash([6 / kindOf.zoom, 4 / kindOf.zoom]);
      brush.beginPath();
      corners.forEach((pt, i2) => i2 ? brush.lineTo(pt.x * K, pt.y * K)
                               : brush.moveTo(pt.x * K, pt.y * K));
      brush.closePath();
      brush.fill();
      brush.stroke();
      brush.setLineDash([]);
      brush.lineWidth = 1;
    },
    // Shift+клик — углы области (пачкой); тумблер Ставить/Снимать —
    // его макет так задумал снятие, ПКМ снимает всегда
    click: (pt, ev) => {
      //: ПОСТАНОВКА ВЫХОДА ПЕРЕХВАТЫВАЕТ КЛИК. Взведён инструмент —
      //: два клика задают углы проёма, и только потом холст снова
      //: красит биты.
      if (state.exitArm) { exitCorner2(cellAt(pt), stage); return; }
      //: ПАНЕЛЬ — ПОСЛЕ ОТВЕТА. bitClick асинхронный, а панель клетки
      //: обновлялась сразу за вызовом: после ПКМ она показывала ЕЩЁ
      //: старый 4000:0000, и на живой проверке снятие выглядело
      //: сломанным, хотя сервер бит давно снял.
      bitClick(cellAt(pt), state.cellPut !== false, stage, ev?.shiftKey)
        .then(() => refreshCellPanel(cellAt(pt))); },
    context: (pt, ev) => {
      bitClick(cellAt(pt), false, stage, ev?.shiftKey)
        .then(() => refreshCellPanel(cellAt(pt))); },
  });
  // ГРАНИЦА ЛЕВОЙ ПАНЕЛИ — ПО ХОЛСТУ, А НЕ ПО ОБЪЕКТУ вживитьХолст().
  // Имя «холст» здесь — возврат {рисуй,вид} (см. вживитьХолст), а не
  // canvas: у него нет getBoundingClientRect, и строка ниже кидала
  // TypeError на каждом заходе на экран — «Ставить/Снимать», кисти и
  // «область» не подключались ВООБЩЕ, тихо (заход на 1d не показывал
  // ошибки, но ни одна кнопка слева не отвечала). Берём настоящий DOM
  // холста для границы «слева» — кисти лежат строго левее его края.
  const canvasDom = card.querySelector("canvas");
  const leftPanelEdge = canvasDom.getBoundingClientRect().left;
  const leftOfCanvas = el => el.getBoundingClientRect().left <
    leftPanelEdge;
  //: «СТАВИТЬ / СНИМАТЬ» ВЫГЛЯДЕЛА ДЕКОРАТИВНОЙ. Она работала, но
  //: подсветку рисовал макет: «Ставить» была тёмной ВСЕГДА, что ни
  //: нажми. Человек жмёт «Снимать», ничего не меняется — вывод «кнопка
  //: не подключена». Красим сами по state.cellPut.
  const modeNodes = [];
  const paintModes = () => {
    for (const { режим: mode, узел: nodeEl } of modeNodes) {
      const isOwn = (mode === "Ставить") === (state.cellPut !== false);
      nodeEl.style.background = isOwn ? "#0f172a" : "transparent";
      nodeEl.style.color = isOwn ? "#f8fafc" : "#334155";
      nodeEl.style.borderRadius = "6px";
      nodeEl.style.padding = "6px 10px";
      nodeEl.style.fontWeight = isOwn ? "600" : "400";
    }
  };
  for (const mode of ["Ставить", "Снимать"]) {
    for (const nodeEl of [...card.querySelectorAll("div,span")]
      .filter(el => el.childElementCount === 0 &&
                   el.textContent.trim() === mode && leftOfCanvas(el))) {
      nodeEl.style.cursor = "pointer";
      modeNodes.push({ режим: mode, узел: nodeEl });
      nodeEl.onclick = () => {
        state.cellPut = mode === "Ставить";
        paintModes();
        status(mode === "Ставить"
          ? "клетки: клик СТАВИТ бит выбранной кисти (ПКМ всегда снимает)"
          : "клетки: клик СНИМАЕТ бит выбранной кисти");
      };
    }
  }
  paintModes();
  // «Внутренняя» (inner) и «Смещение верха» (upoff) раньше были в
  // списке кистей на экране, но не в этом словаре — клик по ним не
  // делал ничего (не было .onclick вовсе). Сервер оба бита понимает
  // (editor_cell_save: inner/light/upoff — HI-биты клетки).
  const brushRows = [];
  const brushMap = { "глушь": "blocked", "Глушь": "blocked",
                  "NoWay": "blocked",
                  "стрел": "solid", "NoFly": "solid",
                  //: «Выход с карты» — СНОВА КИСТЬ, как просил пользователь:
                  //: «нажать как на глушь и выделять зону или тыкать
                  //: одиночно». Но пишет она НЕ бит 0x1000 (он мёртвый),
                  //: а ЗАПИСИ переходов — см. exitBrushApply в bitClick.
                  "Выход": "exit", "выход": "exit",
                  "Прозрачная": "transparent", "поверх": "transparent",
                  "Transparency": "transparent",
                  "Свет": "light",
                  "Внутренняя": "inner", "интерьер": "inner",
                  "Смещение верха": "upoff", "upoff": "upoff" };
  for (const [label, key2] of Object.entries(brushMap)) {
    for (const nodeEl of [...card.querySelectorAll("div,span")]
      .filter(el => el.childElementCount === 0 &&
                   el.textContent.includes(label) && leftOfCanvas(el))) {
      //: СТРОКА КИСТИ — ЭТО КАРТОЧКА С ЦВЕТНЫМ КВАДРАТИКОМ, а не первый
      //: родитель с двумя детьми. Прежний подъём останавливался на
      //: колонке «заголовок+подпись» ВНУТРИ карточки (у неё как раз два
      //: ребёнка) — и вся подсветка выбора красила эту внутреннюю
      //: обёртку: синяя рамка оказывалась внутри белой карточки, галочка
      //: прилипала к тексту, а вечная красная карточка макета у «Глуши»
      //: жила уровнем выше и оставалась нетронутой. Снаружи это
      //: выглядело «что за рамка внутри элемента?» — и это был не
      //: дизайн, а промах подъёма. Карточку узнаём по её же квадратику
      //: цвета кисти (span 14x14 из макета).
      const aim = brushCardOf(nodeEl, card);
      const choose = () => { state.cellBrush = key2; state.area = null;
                              //: имя ИЗ СТРОКИ НА ЭКРАНЕ, а не ключ
                              //: поиска: по клику на «Глухая для стрел»
                              //: статус говорил «кисть клеток: стрел»
                              status("кисть клеток: " +
                                     (nodeEl.textContent.trim() || label));
                              paintBrushes(); };
      for (const el of [nodeEl, aim]) {
        el.style.cursor = "pointer";
        el.onclick = choose;
      }
      brushRows.push({ ключ: key2, узел: nodeEl, строка: aim });
    }
  }
  //: КАКАЯ КИСТЬ СЕЙЧАС ВЗЯТА — БЫЛО НЕ ВИДНО ВООБЩЕ. Семь строк кистей
  //: выглядели одинаково всегда, а красили разное: человек жал «Глушь»,
  //: потом «Выход», и убедиться, что переключилось, было нечем.
  //:
  //: РАМКА СТРОКИ БЫВАЕТ ОБЩЕЙ — тот же капкан, что съел подсветку
  //: тумблера: подъём «до родителя с двумя детьми» у части кистей
  //: упирается в ОДИН контейнер на несколько строк, и покраска по нему
  //: гасит сама себя — побеждает кисть, обработанная последней. Считаем,
  //: сколько РАЗНЫХ кистей делят строку, и красим лист, когда общая.
  const brushesOfRow = new Map();
  for (const { ключ: key2, строка: rowEl } of brushRows) {
    if (!brushesOfRow.has(rowEl)) brushesOfRow.set(rowEl, new Set());
    brushesOfRow.get(rowEl).add(key2);
  }
  //: КРАСНАЯ КАРТОЧКА С ГАЛОЧКОЙ У «ГЛУШИ» БЫЛА ВШИТА В МАКЕТ: дизайнер
  //: нарисовал её выбранной один раз и навсегда. Наш живой выбор
  //: подсвечивал строку синим РЯДОМ с этой вечной красной — два разных
  //: указателя, из которых один врал («что значит красная рамка с
  //: галочкой?»). Снимаем макетную декорацию и отдаём карточку и галочку
  //: настоящему выбору.
  for (const { строка: rowEl } of brushRows) {
    for (const galka of rowEl.querySelectorAll(
        'i[data-lucide="check"], svg.lucide-check')) {
      galka.remove();
    }
    //: и вшитую красную раскраску карточки «Глуши» тоже снимаем — выбор
    //: перекрасит её по-настоящему
    rowEl.style.background = "#fff";
    rowEl.style.border = "1.5px solid #e2e8f0";
  }
  function paintBrushes() {
    const card2 = brushRows[0]?.строка?.closest(".dv-card") || document;
    for (const galka of card2.querySelectorAll('[data-lv="кисть-галка"]')) {
      galka.remove();
    }
    for (const { ключ: key2, узел: nodeEl, строка: rowEl } of brushRows) {
      const isOwn = key2 === state.cellBrush;
      const shared2 = (brushesOfRow.get(rowEl)?.size || 0) > 1;
      if (shared2) {
        nodeEl.style.background = isOwn ? "#dbeafe" : "";
        nodeEl.style.boxShadow = isOwn ? "inset 3px 0 0 #2563eb" : "";
        nodeEl.style.padding = "1px 5px";
        nodeEl.style.borderRadius = "4px";
        nodeEl.style.display = "inline-block";
        continue;
      }
      rowEl.style.background = isOwn ? "#eff6ff" : "#fff";
      rowEl.style.border = "1.5px solid " + (isOwn ? "#2563eb" : "#e2e8f0");
      if (isOwn) {
        const galka = document.createElement("span");
        galka.dataset.lv = "кисть-галка";
        galka.textContent = "✓";
        galka.style.cssText = "margin-left:auto;color:#2563eb;" +
          "font:700 13px 'IBM Plex Sans'";
        rowEl.appendChild(galka);
      }
    }
  }
  paintBrushes();
  //: КНОПКА «ОБЛАСТЬ». Прежде здесь стояло решение «третьего способа не
  //: выдумываем — хватит Shift+клика». Оно оказалось неверным: жест был
  //: невидим, и человек, глядя на канонные карты с их блоками
  //: переходов, сделал единственный возможный вывод — «у нас такого
  //: нет, надо тыкать каждую клетку». Кнопка нужна не как третий
  //: способ, а как ЕДИНСТВЕННЫЙ ВИДИМЫЙ.
  //: КНОПКА ДОЛЖНА СТОЯТЬ НАД ВСЕМИ КИСТЯМИ, А НЕ ВНУТРИ ПЕРВОЙ.
  //: Сперва я вставила её перед первым ребёнком родителя первой строки
  //: — и она легла ВНУТРЬ карточки «Глушь». Читалось однозначно:
  //: «область работает только для глуши». Работает она для любой кисти
  //: (битКлик берёт state.cellBrush), поэтому ищем предка, который
  //: держит НЕСКОЛЬКО строк кистей, и встаём над ними.
  const brushColumn = (() => {
    //: ИЩЕМ ПРЕДКА, КОТОРЫЙ СОДЕРЖИТ несколько строк кистей, а не того,
    //: у кого они прямые дети: каждая строка завёрнута в свою карточку,
    //: и «прямых детей-строк» у общего предка НЕТ НИ ОДНОГО. Первая
    //: попытка проверяла именно прямых — поиск доходил до самой
    //: карточки и возвращал null, кнопка «Область» не появлялась вовсе.
    //: Поймал это селфчек на первом же прогоне, а не человек.
    let nodeEl = brushRows[0]?.строка?.parentElement;
    while (nodeEl && nodeEl !== card) {
      if (brushRows.filter(k2 => nodeEl.contains(k2.строка)).length >= 2) {
        return nodeEl;
      }
      nodeEl = nodeEl.parentElement;
    }
    return null;
  })();
  if (brushColumn) {
    const btn = document.createElement("div");
    const paint = () => {
      btn.textContent = state.areaMode
        ? "Область: два угла · выключить"
        : "Область — залить прямоугольник";
      btn.style.cssText =
        "margin:6px 4px;padding:7px 9px;border-radius:7px;cursor:pointer;" +
        "font:600 11px 'IBM Plex Sans';text-align:center;border:1.5px solid " +
        (state.areaMode ? "#2563eb;background:#2563eb;color:#fff"
                        : "#cbd5e1;background:#f8fafc;color:#334155");
    };
    btn.onclick = () => {
      state.areaMode = !state.areaMode;
      state.area = null;
      paint();
      status(state.areaMode
        ? "область: кликните два угла — зальётся весь прямоугольник " +
          "(то же делает Shift+клик)"
        : "область выключена — красим по одной клетке");
      stage?.рисуйПоверх();
    };
    paint();
    insertOwn(brushColumn, btn, "кисть-область", brushColumn.firstChild);
  }
  //: ПАНЕЛЬ КЛЕТКИ СПРАВА была вписана в макет намертво («Клетка
  //: 132:88», «0FFF:0023», пять чекбоксов) — какую клетку ни жми,
  //: цифры не менялись. Биты те же, что кисти слева (editor_cell_save,
  //: CELL_*_BIT в server.py): LO — blocked(&0x0FFF==0x0FFF),
  //: solid(0x4000), exit(0x1000), transparent(0x8000); HI —
  //: object(&0x1F). Мокап у строки «прозрачная» подписывал «HI 0x0020»
  //: (это чужой бит, inner) — берём настоящий: transparent живёт в LO.
  const cellTitle = [...card.querySelectorAll("span")]
    .find(el => el.childElementCount === 0 &&
                /^Клетка \d+:\d+$/.test(el.textContent.trim()));
  const cellHex = [...card.querySelectorAll("span")]
    .find(el => el.childElementCount === 0 &&
                /^[0-9A-F]{4}:[0-9A-F]{4}$/.test(el.textContent.trim()));
  const canvasHint = [...card.querySelectorAll("div")]
    .find(el => el.childElementCount === 0 &&
                /^клетка \d+:\d+/i.test(el.textContent.trim()));
  //: ГРАНИЦА ПО ПИКСЕЛЯМ ЗДЕСЬ ПОДВЕЛА: канвас — flex-блок, и его
  //: правый край (getBoundingClientRect().right) может лежать ПРАВЕЕ
  //: начала соседней 320-пиксельной колонки — они не встык, а внахлёст
  //: по раскладке макета. Берём саму колонку инспектора клетки как
  //: контейнер (её несёт заголовокКлетки) — надёжнее любой границы.
  const cellColumn = cellTitle?.closest(
    '[style*="width:320px"],[style*="width: 320px"]') || card;
  const findRow = prefix2 => [...cellColumn.querySelectorAll("span")]
    .find(el => el.childElementCount === 0 &&
                el.textContent.trim().startsWith(prefix2));
  const bitRows = [
    { префикс: "глушь", узел: findRow("глушь"),
      значение: (lo) => (lo & 0x0FFF) === 0x0FFF,
      подпись: () => `глушь · LO 0x${(0x0FFF).toString(16)
        .toUpperCase()}` },
    { префикс: "глухая для стрел", узел: findRow("глухая для стрел"),
      значение: (lo) => Boolean(lo & 0x4000),
      подпись: () => "глухая для стрел · 0x4000" },
    //: БИТ ВЫХОДА — НЕ СВОЙСТВО КЛЕТКИ, а след записи перехода: в
    //: файлах канона его нет ни у одной клетки, движок ставит его сам
    //: при входе на карту. Строка осталась в панели как справка, но
    //: выглядит справкой, а не правимым свойством — иначе левая кисть
    //: «не выбирается», а правый чекбокс будто бы можно, и это
    //: читалось как противоречие.
    { префикс: "выход с карты", узел: findRow("выход с карты"),
      значение: (lo) => Boolean(lo & 0x1000),
      подпись: () => "выход с карты · зона правится кистью «Выход»",
      справка: true },
    { префикс: "прозрачная", узел: findRow("прозрачная"),
      значение: (lo) => Boolean(lo & 0x8000),
      подпись: () => "прозрачная · LO 0x8000" },
    { префикс: "объект в клетке", узел: findRow("объект в клетке"),
      значение: null,   // отдельно: зависит от hi, не lo
      подпись: (hi) => `объект в клетке · HI 0x${(hi & 0x1F)
        .toString(16).padStart(4, "0").toUpperCase()}` },
  ];
  function paintCheckbox(rowEl, checked2) {
    if (!rowEl) return;
    const checkBox = rowEl.previousElementSibling;
    if (!checkBox) return;
    if (checked2) {
      checkBox.style.background = "#2563eb";
      checkBox.style.border = "none";
      checkBox.textContent = "✓";
      checkBox.style.color = "#fff";
      checkBox.style.font = "700 10px monospace";
      checkBox.style.textAlign = "center";
      checkBox.style.lineHeight = "13px";
    } else {
      checkBox.style.background = "transparent";
      checkBox.style.border = "1.5px solid #cbd5e1";
      checkBox.textContent = "";
    }
  }
  function refreshCellPanel(cellRec) {
    if (!state.cells?.[cellRec.row]?.[cellRec.col]) return;
    state.pickedCell = cellRec;
    const [loText, hiText] = state.cells[cellRec.row][cellRec.col].split(":");
    const lo = parseInt(loText, 16), hi = parseInt(hiText, 16);
    if (cellTitle)
      cellTitle.textContent = `Клетка ${cellRec.row}:${cellRec.col}`;
    if (cellHex) cellHex.textContent = `${loText}:${hiText}`;
    if (canvasHint)
      canvasHint.textContent =
        `клетка ${cellRec.row}:${cellRec.col} · ${loText}:${hiText}`;
    for (const line of bitRows) {
      if (!line.узел) continue;
      const checked2 = line.значение ? line.значение(lo) : (hi & 0x1F) > 0;
      line.узел.textContent = line.подпись(hi);
      paintCheckbox(line.узел, checked2);
      if (line.справка) {
        line.узел.style.color = "#94a3b8";
        const checkBox = line.узел.previousElementSibling;
        if (checkBox) checkBox.style.opacity = ".45";
      }
    }
  }
  if (state.pickedCell) refreshCellPanel(state.pickedCell);
  //: «Alt+клик — панель клетки» в подсказке внизу было пустым обещанием
  //: — Alt целиком занят поворотом камеры (панорамирование), а панель
  //: не подключалась вовсе. Теперь панель обновляется любым кликом по
  //: клетке — подпись держим честной.
  const alt = [...card.querySelectorAll("span")]
    .find(el => el.childElementCount === 0 &&
                el.textContent.trim() === "Alt+клик — панель клетки");
  if (alt) alt.textContent = "клик — красит и показывает клетку";
  await liveExits(card, stage);
}
//: ВЫХОДЫ КАРТЫ — ТО, ЧЕМ КАРТЫ ВООБЩЕ СВЯЗЫВАЮТСЯ.
//:
//: Их не было НИКАК: сборка умела читать `map.json["exits"]`
//: (builder._project_exits — и даже проверяла поля), но ручки записи не
//: существовало, а холст рисовал только уже запечённые двери из пака.
//: Кисть «Выход» на этом же экране красит лишь бит клетки, а бит без
//: записи перехода никуда не ведёт — то есть создавала видимость двери
//: там, где двери нет. Связать две карты мышью было нельзя в принципе,
//: и это единственное, без чего игры не существует вовсе.
//:
//: Жест выбран тот же, что уже живёт на этом экране для заливки области:
//: два клика по углам. Третьего способа заводить не стали.
async function liveExits(card, stage) {
  const title2 = [...card.querySelectorAll("span")]
    .find(el => el.childElementCount === 0 &&
                el.textContent.trim() === "Выходы карты");
  const column2 = title2
    ?.closest('[style*="width:320px"],[style*="width: 320px"]');
  const doors = state.mapState?.exits || [];
  //: СЧЁТЧИК В ШАПКЕ — ПОСЛЕДНИЙ span ТОЙ ЖЕ СТРОКИ, что и заголовок:
  //: между ними лежит распорка <div style="flex:1">, поэтому «span +
  //: span» его не берёт, а поиск «просто число» по всей колонке цепляет
  //: чужие числа из соседних карточек.
  const tally = title2 &&
    [...title2.parentElement.querySelectorAll("span")].pop();
  if (tally && tally !== title2) tally.textContent = String(doors.length);
  //: строки списка: в макете их четыре, статичных
  const bodyNum = column2 && [...column2.querySelectorAll("div")]
    .filter(el => [...el.children].filter(
      d2 => /→/.test(d2.textContent)).length >= 2)
    .sort((a2, b2) => a2.children.length - b2.children.length)[0];
  if (bodyNum) {
    bodyNum.replaceChildren();
    for (const [spot, d2] of doors.entries()) {
      const rowEl = document.createElement("div");
      rowEl.style.cssText = "display:flex;justify-content:space-between;" +
        "gap:6px;padding:4px 12px;font:10.5px 'IBM Plex Mono';" +
        "cursor:pointer;border-radius:4px";
      const where2 = document.createElement("span");
      where2.style.color = "#16a34a";
      where2.textContent = `${d2.row1}:${d2.col1}–${d2.row2}:${d2.col2}`;
      const whither = document.createElement("span");
      whither.style.color = "#475569";
      whither.textContent = `→ ${d2.to_map} ${d2.to_name || ""}`;
      const removeIt = document.createElement("span");
      removeIt.textContent = "✕";
      removeIt.title = "убрать выход";
      removeIt.style.cssText = "color:#dc2626;cursor:pointer;padding:0 2px";
      removeIt.onclick = async (ev) => {
        ev.stopPropagation();
        const resp = await fetch(`${API}/maps/${state.map}/exits/${spot}`,
                              { method: "DELETE" }).then(x => x.json());
        if (resp.ok) { await openMap(state.map); showScreen(state.screen); }
        else status(resp.note || "не вышло");
      };
      //: клик по строке — камера к двери: искать её глазами по карте
      //: 160x256 клеток иначе безнадёжно
      rowEl.onclick = () => {
        const kindOf = state.view;
        kindOf.x = Math.min(d2.col1, d2.col2) * CELL_W - 300;
        kindOf.y = Math.min(d2.row1, d2.row2) * CELL_H - 200;
        stage?.рисуй();
        status(`выход ${spot}: ${d2.row1}:${d2.col1} → карта ${d2.to_map}`);
      };
      rowEl.append(where2, whither, removeIt);
      bodyNum.appendChild(rowEl);
    }
    if (!doors.length) {
      const emptyEl = document.createElement("div");
      emptyEl.style.cssText = "padding:6px 12px;font:10.5px 'IBM Plex Sans';" +
        "color:#94a3b8";
      emptyEl.textContent = "выходов нет — карта ни с чем не связана";
      bodyNum.appendChild(emptyEl);
    }
  }
  //: СВОЙ ИНСТРУМЕНТ: куда ведёт дверь + «обвести проём». В макете его
  //: нет вовсе — выходы там только показывались.
  if (!column2) return;
  const boxEl = document.createElement("div");
  boxEl.style.cssText = "margin:8px 12px;padding:8px;border-radius:6px;" +
    "background:#f8fafc;border:1px solid #e2e8f0;display:flex;" +
    "flex-direction:column;gap:6px";
  const label = document.createElement("div");
  label.style.cssText = "font:600 11px 'IBM Plex Sans';color:#334155";
  label.textContent = "Новый выход";
  const whither = document.createElement("select");
  whither.style.cssText = "font:11px 'IBM Plex Mono';padding:3px";
  const list = await api("/maps");
  whither.innerHTML = '<option value="-1" selected>глобальная карта' +
    " (обычный выход)</option>" + (list.maps || [])
    .filter(k2 => k2.map !== state.map)
    .map(k2 => `<option value="${k2.map}">${k2.map} · ${k2.name || k2.dir}` +
              `${k2.editable === false ? " (из игры)" : ""}</option>`).join("");
  const btn = document.createElement("button");
  btn.style.cssText = "padding:5px;border-radius:5px;cursor:pointer;" +
    "border:1px solid #2563eb;background:#2563eb;color:#fff;" +
    "font:600 11px 'IBM Plex Sans'";
  const usual = "Обвести проём двумя углами";
  btn.textContent = usual;
  btn.onclick = () => {
    if (state.exitArm) {
      state.exitArm = null; state.exitCorner = null;
      btn.textContent = usual;
      status("постановка выхода отменена");
      return;
    }
    if (!state.editable) {
      status("карта из игры — только просмотр; скопируйте её в свою");
      return;
    }
    state.exitArm = { to_map: Number(whither.value),
                      to_name: whither.selectedOptions[0]?.textContent
                        ?.split("·")[1]?.trim() || "" };
    state.exitCorner = null;
    btn.textContent = "отменить";
    status(`выход на карту ${state.exitArm.to_map}: кликните ПЕРВЫЙ угол ` +
           `проёма на холсте`);
  };
  boxEl.append(label, whither, btn);
  insertOwn(column2, boxEl, "выход-инструмент",
               column2.children[1] || null);
}
//: Два клика по углам: первый запоминаем, второй заводит дверь. Точка
//: входа по умолчанию — середина проёма: игрок, придя с той стороны,
//: встаёт в двери, а не в углу.
async function exitCorner2(cellRec, stage) {
  if (!state.exitCorner) {
    state.exitCorner = cellRec;
    status(`угол А ${cellRec.row}:${cellRec.col} — кликните ВТОРОЙ угол проёма`);
    return;
  }
  const a2 = state.exitCorner, b2 = cellRec;
  state.exitCorner = null;
  const arm = state.exitArm;
  state.exitArm = null;
  const resp = await api(`/maps/${state.map}/exits`, "POST", {
    add: { to_map: arm.to_map, to_name: arm.to_name,
           row1: a2.row, row2: b2.row, col1: a2.col, col2: b2.col,
           entry_row: Math.round((a2.row + b2.row) / 2),
           entry_col: Math.round((a2.col + b2.col) / 2) } });
  if (!resp.ok) { status(resp.note || "не вышло"); return; }
  await openMap(state.map);
  showScreen(state.screen);
  status(`выход на карту ${arm.to_map} поставлен · соберите карту, ` +
         `чтобы он заработал в игре`);
}
//: Куда ведёт кисть выхода: по умолчанию — ГЛОБАЛЬНАЯ КАРТА (-1), как
//: у подавляющего большинства канонных переходов. Список «Новый выход»
//: в правой панели остаётся выбором для редких дверей между картами.
function exitDestination() {
  const sel = [...document.querySelectorAll("select")]
    .find(s_ => s_.closest('[data-lv="выход-инструмент"]'));
  if (sel && sel.value !== "" && Number(sel.value) >= 0) {
    return { map: Number(sel.value),
             name: sel.selectedOptions[0]?.textContent
               ?.split("·").slice(1).join("·").trim() || "" };
  }
  return { map: -1, name: "глобальная карта" };
}

//: КИСТЬ ВЫХОДА ПИШЕТ ЗАПИСИ ПЕРЕХОДОВ, А НЕ БИТ. ЛКМ по клетке — зона
//: 1x1, область двумя углами — прямоугольник, ПКМ — убрать запись, в
//: которую попала клетка. Точка входа игрока — середина зоны.
async function exitBrushApply(a2, b2, putMode, stage) {
  if (!putMode) {
    const doors = state.mapState?.exits || [];
    const at = doors.findIndex(d_ =>
      a2.row >= Math.min(d_.row1, d_.row2) &&
      a2.row <= Math.max(d_.row1, d_.row2) &&
      a2.col >= Math.min(d_.col1, d_.col2) &&
      a2.col <= Math.max(d_.col1, d_.col2));
    if (at < 0) {
      status(`в клетке ${a2.row}:${a2.col} нет выхода — снимать нечего`);
      return;
    }
    const resp = await api(`/maps/${state.map}/exits/${at}`, "DELETE");
    if (resp.ok) { await openMap(state.map); stage?.рисуй();
                status(`выход убран (${a2.row}:${a2.col})`); }
    return;
  }
  const dest = exitDestination();
  const row1 = Math.min(a2.row, b2.row), row2 = Math.max(a2.row, b2.row);
  const col1 = Math.min(a2.col, b2.col), col2 = Math.max(a2.col, b2.col);
  const resp = await api(`/maps/${state.map}/exits`, "POST", { add: {
    to_map: dest.map, to_name: dest.name,
    row1, row2, col1, col2,
    entry_row: Math.round((row1 + row2) / 2),
    entry_col: Math.round((col1 + col2) / 2) } });
  if (resp.ok) {
    await openMap(state.map);
    stage?.рисуй();
    status(`выход ${row1}:${col1}–${row2}:${col2} → ` +
           `${dest.name || dest.map} · соберите карту, чтобы заработал`);
  } else {
    status(resp.note || "выход не записался");
  }
}

async function bitClick(cellRec, putMode, stage, shiftHeld) {
  //: кисть выхода живёт записями, а не битами клеток
  if (state.cellBrush === "exit") {
    if (state.areaMode || shiftHeld) {
      if (!state.area) { state.area = cellRec;
        status(`угол А ${cellRec.row}:${cellRec.col} — кликните угол Б`);
        return; }
      const a2 = state.area;
      state.area = null;
      await exitBrushApply(a2, cellRec, putMode, stage);
      return;
    }
    await exitBrushApply(cellRec, cellRec, putMode, stage);
    return;
  }
  if (state.areaMode || shiftHeld) {
    if (!state.area) { state.area = cellRec;
      status(`угол А ${cellRec.row}:${cellRec.col} — кликните угол Б`); return; }
    const a2 = state.area;
    state.area = null;
    const batch = [];
    for (let r = Math.min(a2.row, cellRec.row);
         r <= Math.max(a2.row, cellRec.row); r++) {
      for (let c = Math.min(a2.col, cellRec.col);
           c <= Math.max(a2.col, cellRec.col); c++) {
        batch.push({ row: r, col: c, [state.cellBrush]: putMode });
      }
    }
    const resp = await api(`/maps/${state.map}/cells`, "POST",
                        { cells: batch });
    if (resp.ok) {
      status(`область: ${batch.length} клеток · режим области ещё ` +
             `включён — следующие два клика зальют новый прямоугольник, ` +
             `Esc выключит`);
      const k2 = await api(`/maps/${state.map}/cells`);
      if (k2.ok) { state.cells = k2.cells; stage?.рисуй(); }
    }
    return;
  }
  const resp = await api(`/maps/${state.map}/cells`, "POST",
    { row: cellRec.row, col: cellRec.col, [state.cellBrush]: putMode });
  if (resp.ok && state.cells) {
    state.cells[cellRec.row][cellRec.col] =
      (resp.lo.toString(16).padStart(4, "0") + ":" +
       resp.hi.toString(16).padStart(4, "0")).toUpperCase();
    stage?.рисуй();
  }
}

// 1b — объекты: живой каталог в его гриде, клик по холсту ставит
//: ЧТО ЛОВИТ КАЖДЫЙ ИНСТРУМЕНТ. Раньше щелчок ловил всё подряд: на
//: экране существ можно было выбрать избу, на экране объектов — жителя,
//: и человек не понимал, почему выбралось не то, по чему он целился.
//: Инструмент ловит своё — как в любом редакторе со слоями.
const CATCH = {
  "1b": ["object", "decor"],
  "1f": ["unit", "packUnit"],
  "1g": ["loot", "packLoot"],
  //: у кисти земли, воды и клеток холст не хватает НИЧЕГО: там зажатая
  //: кнопка красит, а не возит (пустой список = не ловим вовсе)
  "1c": [], "1d": [], "1e": [],
  //: на экране отрядов ловим юнитов: щелчок по бойцу выбирает ЕГО
  //: отряд — так проще всего понять, чей это боец
  "1j": ["packUnit", "unit"],
  //: на экране деревни холст только показывает: постройки правятся
  //: слотами в списке, а не мышью по карте
  "1k": [],
  //: сборка и валидатор показывают карту, но не правят её
  "1h": [], "1i": [],
};
async function screen1b(card) {
  const stage = mountCanvas(card, {
    хватать: CATCH["1b"],
    click: async pt => {
      // Клик ПРЯМО ПО уже стоящему объекту/юниту — всегда выбирает
      // (даже в режиме расстановки), иначе постановка штампует копию
      // поверх того, что человек пытался выбрать.
      if (await pickOnCanvas(pt, stage, CATCH["1b"])) {
        if (pickKind() === "object") {
          refreshObjectPanel(selectedOf());
        }
        return;
      }
      // ДЕКОР ИДЁТ В ДРУГУЮ ТАБЛИЦУ. T_DYNAMIC (оверлеи) рисуется сразу
      // после земли и до объектов — этим и отличается берег от избы.
      //: ПОСТАНОВКА ДЕКОРА. Спрайт кладётся СЕРЕДИНОЙ под курсор, а в
      //: запись идёт левый верхний угол — движок рисует картинку от него
      //: (canvas делает то же: drawImage(x, y, width, height)).
      if (state.place?.kind === "decor") {
        if (!state.decorMode) {
          status("это декор — перейдите на вкладку «Декор»");
          return;
        }
        const w2 = state.place.width || 114, h2 = state.place.height || 64;
        const resp = await api(`/maps/${state.map}/overlays`, "POST",
          { add: { id: state.place.id,
                   x: Math.round(pt.x - w2 / 2),
                   y: Math.round(pt.y - h2 / 2) } });
        if (resp.ok) {
          await openMap(state.map); stage?.рисуй();
          status(`декор ${state.place.id} · запись ${resp.slot}`);
        }
        return;
      }
      if (!state.place || state.place.kind !== "object") return;
      if (state.decorMode) {
        //: ОБЪЕКТ В РЕЖИМЕ ДЕКОРА НЕ КЛАДЁМ. Номера у них из РАЗНЫХ
        //: таблиц: у объекта это гнездо T_OBJECTS (сверено на карте 23:
        //: sprite 129 → resource_slot 159), у декора — индекс спрайта
        //: GRAPH в T_DYNAMIC (там же: 247…256). Подставив первое вторым,
        //: редактор положил бы в карту заведомо чужой спрайт — молча, и
        //: заметить это можно было бы только в игре. У декора теперь
        //: свой каталог, поэтому просто отправляем человека в него.
        status("выбран объект, а вкладка — «Декор»: возьмите картинку из " +
               "каталога декора или вернитесь на «Объект»");
        return;
      }
      const resp = await api(`/maps/${state.map}/objects`, "POST",
        { add: { slot: state.place.slot, palette: state.place.palette,
                 state: state.place.state,
                 x: Math.round(pt.x), y: Math.round(pt.y) } });
      //: подтверждение ПОСЛЕ перечитывания: открытьКарту кончается своим
      //: статусом и съедала «объект N · запись M» — человек не знал,
      //: встал ли объект (та же болезнь, что была у переноса)
      if (resp.ok) { await openMap(state.map); stage?.рисуй();
                  status(`объект ${state.place.slot} · запись ` +
                         resp.record_slot); }
    },
  });
  if (!state.objPages) await loadObjectCatalog();
  //: КАТАЛОГ ДЕКОРА ГРУЗИМ ПОД ИГРУ КАРТЫ: спрайты GRAPH у канона и у
  //: «Продолжения легенды» СВОИ, и общий список положил бы на пустынную
  //: карту чужой берег.
  const mapGame = state.mapState?.meta?.game || "canon";
  if (state.decorMode &&
      (!state.decorList || state.decorGame !== mapGame)) {
    await loadDecorCatalog(mapGame);
  }
  const gridEl = zoneOf(card, "каталог-объектов");
  if (!gridEl) return;
  // каталог листается СВОИМИ страницами по 24, но фильтры режут весь
  // список — держим плоский список и режем его сами
  const allObjects = state.objPages.flat();
  const KIND_BY_LABEL = { "здания": "building", "реквизит": "prop", "руины": "ruin" };

  function filtered() {
    const needle = state.objQuery || "";
    //: В РЕЖИМЕ ДЕКОРА КАТАЛОГ СВОЙ. Поиск по номеру спрайта, порядок —
    //: по тому, как часто игра им пользуется: первыми идут берега и
    //: трава, которыми закрыта мозаика, а редкие камни в конце.
    if (state.decorMode) {
      const rows = state.decorList || [];
      return needle
        ? rows.filter(z2 => String(z2.id).includes(needle)) : rows;
    }
    const groupOf = state.objGroup || "";
    return allObjects.filter(z2 => {
      if (groupOf && (z2.group || "") !== groupOf) return false;
      if (!needle) return true;
      return String(z2.slot).includes(needle) ||
             String(z2.palette).includes(needle) ||
             (z2.name || "").toLowerCase().includes(needle);
    });
  }
  function renderPage() {
    const list = filtered();
    const PER_PAGE = 24;
    const totalCount = Math.max(1, Math.ceil(list.length / PER_PAGE));
    state.catalogPage = Math.min(state.catalogPage, totalCount - 1);
    gridEl.replaceChildren();
    gridEl.style.display = "flex";
    gridEl.style.flexWrap = "wrap";
    gridEl.style.gap = "4px";
    gridEl.style.alignContent = "flex-start";
    // каталог длиннее макета — прокрутка внутри его же рамки
    gridEl.style.maxHeight = "min(58vh, 520px)";
    gridEl.style.overflowY = "auto";
    const slice2 = list.slice(state.catalogPage * PER_PAGE,
                              (state.catalogPage + 1) * PER_PAGE);
    for (const z2 of slice2) {
      const i2 = document.createElement("img");
      i2.src = z2.url;
      //: У ДЕКОРА НЕТ ИМЁН, ЗАТО ЕСТЬ ПОВАДКА. Пока их не разметили
      //: глазами, честная подпись — где игра сама этим пользуется:
      //: «спрайт 110 · 670 раз на 23 картах» говорит о берегe больше,
      //: чем пустое место.
      if (state.decorMode) {
        i2.title = `спрайт ${z2.id} · ${z2.count} ` +
          plural(z2.count, ["раз", "раза", "раз"]) + " на " +
          `${z2.maps.length} ` +
          plural(z2.maps.length, ["карте", "картах", "картах"]) +
          ` (${z2.maps.slice(0, 6).join(", ")}` +
          (z2.maps.length > 6 ? "…" : "") + ")";
        i2.style.cssText =
          "max-width:84px;max-height:66px;object-fit:contain;" +
          "cursor:pointer;border:1px solid " +
          (state.place?.kind === "decor" && state.place?.id === z2.id
            ? "#2563eb" : "transparent");
        i2.onclick = () => { state.place = { ...z2, kind: "decor" };
                             renderPage(); };
        gridEl.appendChild(i2);
        continue;
      }
      i2.title = `гнездо ${z2.slot} · палитра ${z2.palette}`;
      i2.style.cssText =
        "max-width:84px;max-height:66px;object-fit:contain;" +
        "cursor:pointer;border:1px solid " +
        (state.place?.slot === z2.slot &&
         state.place?.palette === z2.palette ? "#2563eb" : "transparent");
      // KIND ПОСЛЕ СПРЕДА: у записи каталога своё поле kind
      // (prop/building/ruin — вид объекта для фильтра), и спред ...з
      // ПЕРЕЗАТИРАЛ им kind:"object" — клик по холсту после выбора
      // картинки уходил не в постановку, а в выбор (state.place.kind
      // никогда не был "object"), и постановка объектов не работала
      // вовсе. Держим оригинальный вид каталога отдельным полем.
      i2.onclick = () => { state.place = { ...z2, catalogKind: z2.kind,
                                          kind: "object" };
                          renderPage(); };
      gridEl.appendChild(i2);
    }
    if (!slice2.length) {
      const emptyEl = document.createElement("div");
      emptyEl.style.cssText = "font:12px 'IBM Plex Mono';color:#64748b";
      emptyEl.textContent = "ничего не нашлось";
      gridEl.appendChild(emptyEl);
    }
    pageLabel(card, state.catalogPage, totalCount);
    //: счётчик шапки — ОДИН span «T_OBJECTS · 882»: число вписано макетом
    //: и не значит ничего (записей 451). Прежний цикл ждал число отдельным
    //: узлом рядом с подписью — и не совпадал никогда, 882 так и висело.
    for (const el of card.querySelectorAll("div,span")) {
      if (el.childElementCount === 0 &&
          /^T_OBJECTS\s*·\s*\d+$/.test(el.textContent.trim())) {
        el.textContent = state.decorMode
          ? `T_DYNAMIC · ${list.length}` : `T_OBJECTS · ${list.length}`;
      }
    }
  }
  //: ВИДИМОСТЬ СЛОЁВ ХОЛСТА — «тайлы · декор · вода · объекты · юниты ·
  //: проходимость» в правой панели. Это не фильтр данных, а что рисовать:
  //: без него холст всегда показывал всё разом, и разглядеть глушь под
  //: избами было нельзя.
  for (const nm of Object.keys(state.слои)) {
    const aim = organOf(card, nm);
    if (!aim) continue;
    const paint = () => {
      aim.рамка.style.opacity = state.слои[nm] ? "1" : ".45";
      aim.узел.style.textDecoration =
        state.слои[nm] ? "none" : "line-through";
    };
    bindTo(aim, () => { state.слои[nm] = !state.слои[nm];
                           paint(); stage?.рисуй(); });
    paint();
  }
  wakeInspector(card, stage);
  pager(card,
           () => ({ страница: state.catalogPage,
                    всего: Math.max(1, Math.ceil(filtered().length / 24)) }),
           page => { state.catalogPage = page; renderPage(); });
  liveField(card, "поиск-объектов",
            () => organOf(card, "спрайт или слот", false)?.узел,
            "спрайт или слот…",
            val => { state.objQuery = val;
                          state.catalogPage = 0; renderPage(); });
  //: ЧИПЫ ГРУПП ВМЕСТО ТРЁХ ВКЛАДОК МАКЕТА. «здания · реквизит · руины»
  //: делили 451 запись как 57/393/1: «реквизит» был свалкой всего — «и
  //: руины, и мебель, и деревья», — а в «руинах» жило одно дерево
  //: (случайная фаза с ненулевым состоянием). Группы размечены глазами
  //: по контактным листам (server.OBJECT_GROUPS) и приезжают со
  //: страницей каталога; макетные кнопки прячем.
  for (const label of Object.keys(KIND_BY_LABEL)) {
    const org = organOf(card, label, false, true);
    if (org?.узел) {
      const rowKind = org.узел.closest("div");
      if (rowKind && rowKind.childElementCount <= 4) {
        rowKind.style.display = "none";
      } else {
        org.узел.style.display = "none";
      }
    }
  }
  {
    const chips = document.createElement("div");
    chips.style.cssText = "display:flex;flex-wrap:wrap;gap:4px;" +
      "margin:6px 4px";
    const paintChips = () => {
      chips.replaceChildren();
      const все = [{ key: "", label: "все" }, ...(state.objGroups || [])];
      for (const g of все) {
        const chip = document.createElement("span");
        const isOwn = (state.objGroup || "") === g.key;
        chip.textContent = g.label;
        chip.style.cssText = "padding:3px 9px;border-radius:11px;" +
          "cursor:pointer;font:600 10.5px 'IBM Plex Sans';border:1px solid " +
          (isOwn ? "#2563eb;background:#2563eb;color:#fff"
                 : "#cbd5e1;background:#fff;color:#334155");
        chip.onclick = () => {
          state.objGroup = isOwn ? "" : g.key;
          state.catalogPage = 0;
          paintChips();
          renderPage();
          status("каталог: " + (state.objGroup ? g.label : "все группы"));
        };
        chips.appendChild(chip);
      }
    };
    paintChips();
    const гридEl = card.querySelector('[data-lv="зона-каталог-объектов"]');
    insertOwn(гридEl?.parentElement || card, chips, "группы-объектов",
              гридEl || null);
  }
  //: ПАНЕЛЬ ОБЪЕКТА СПРАВА была вписана в макет намертво («слот 214»,
  //: «85 · дом с сеном», «12», «3/8 · целое», «x 4224 · y 2816», «sort_y
  //: 2934») — выбор другого объекта ничего в ней не менял. Запись
  //: объекта (api_map_state → поля_объекта) несёт только {slot, sprite,
  //: resource_slot, palette, state, x, y} — имени спрайта, названия
  //: палитры и sort_y сервер не отдаёт, и подделывать их текстом хуже,
  //: чем оставить как есть: чёстно показываем то, что есть.
  const objectTitle = [...card.querySelectorAll("span")]
    .find(el => el.childElementCount === 0 &&
                /^Объект\s*·\s*слот\s*\d+$/.test(el.textContent.trim()));
  const spriteRow = rowValue(card, "Спрайт");
  const resourceRow = rowValue(card, "Ресурсный слот");
  const paletteRow = rowValue(card, "Палитра");
  const stateRow = rowValue(card, "Состояние");
  const objectPositionRow = rowValue(card, "Позиция");
  const orderRow = rowValue(card, "Порядок отрисовки");
  function refreshObjectPanel(obj) {
    if (objectTitle)
      objectTitle.textContent = `Объект · слот ${obj.slot}`;
    if (spriteRow) spriteRow.textContent = String(obj.sprite);
    if (resourceRow) resourceRow.textContent = String(obj.resource_slot);
    if (paletteRow) {
      const swatch = paletteRow.querySelector("span");
      if (swatch) swatch.style.background =
        `hsl(${((obj.palette || 0) * 41) % 360} 45% 45%)`;
      const number2 = paletteRow.querySelector("span + span") ||
        paletteRow.querySelector("span");
      if (number2) number2.textContent = String(obj.palette ?? 0);
    }
    //: СОСТОЯНИЕ — ФАЗА СТРОЙКИ ИЛИ РУИНЫ, и задать её было нельзя:
    //: сменить фазу можно было только «убрать и поставить заново
    //: вслепую». Сервер это умеет (editor_object_move принимает state).
    numberFields(card, stateRow, "состояние-объекта",
      [{ подпись: "состояние", значение: obj.state ?? 0 }],
      async ([stateNum]) => {
        const resp = await api(`/maps/${state.map}/objects`, "POST",
          { patch: { slot: obj.slot, state: stateNum } });
        if (resp.ok) { await openMap(state.map); showScreen(state.screen); }
        else status(resp.note || "не вышло");
      });
    //: ПОЗИЦИЯ ЧИСЛАМИ. Возить мышью — хорошо для «примерно там», но
    //: выровнять три избы в ряд так нельзя вовсе, а координаты при этом
    //: видны с точностью до пикселя.
    numberFields(card, objectPositionRow, "позиция-объекта",
      [{ подпись: "x", значение: obj.x }, { подпись: "y", значение: obj.y }],
      async ([x, y]) => {
        const resp = await api(`/maps/${state.map}/objects`, "POST",
          { patch: { slot: obj.slot, x, y } });
        if (resp.ok) { await openMap(state.map); showScreen(state.screen); }
        else status(resp.note || "не вышло");
      });
    if (orderRow) orderRow.textContent =
      state.глубины?.[obj.slot] != null
        ? `sort_y ${state.глубины[obj.slot]}`
        : "sort_y — после сборки";
  }
  if (pickKind() === "object") refreshObjectPanel(selectedOf());
  renderPage();
}
//: Возвращает true, если под точкой РЕАЛЬНО что-то нашлось и выбрано —
//: вызывающий обязан на этом остановиться и не ставить новую вещь
//: поверх найденной (иначе клик по уже стоящему юниту в режиме
//: расстановки штамповал копию вместо выбора — см. жизнь1f/жизнь1b).
//: ОДНА ПРОВЕРКА ПОПАДАНИЯ НА ВЕСЬ РЕДАКТОР. Здесь жила ВТОРАЯ, своя, с
//: другим допуском (60 против 40 у чтоПодТочкой) и своим набором вещей:
//: выделение и перенос ловили РАЗНОЕ, и «щёлкаю по одному, берётся
//: другое» было честным описанием. Обе теперь идут через чтоПодТочкой.
//: КУДА ИДТИ ЗА ВЕЩЬЮ ЧУЖОГО ВИДА. Инструмент ловит своё — это верно,
//: но молчать о чужом нельзя: щелчок по дереву на экране существ не
//: делал РОВНО НИЧЕГО и ничего не говорил. А именно туда человек и
//: попадает первым делом: карточка карты открывает экран существ. Вот и
//: выходило «нпс двигаются, деревья нет» — жители-то здесь ловятся.
const TAB_KIND = {
  object: ["Объект", "объект"], decor: ["Декор", "декор"],
  unit: ["Сущ-ва", "существо"], packUnit: ["Сущ-ва", "житель мира"],
  loot: ["Клады", "куча"], packLoot: ["Клады", "клад из пака"],
};
async function pickOnCanvas(pt, stage, kinds = null) {
  const what = hitAt(pt, kinds);
  if (!what) {
    //: под точкой пусто ДЛЯ НАС — но, может, там чужая вещь
    const alien = kinds ? hitAt(pt, null) : null;
    const whither = alien && TAB_KIND[alien.вид];
    if (whither && !kinds.includes(alien.вид)) {
      status(`это ${whither[1]} «${alien.имя}» — этот инструмент его не ` +
             `берёт: перейдите на вкладку «${whither[0]}»`);
    }
    return false;
  }
  //: ВИД ВЫБРАННОГО ЗАПОМИНАЕМ ОТДЕЛЬНО. У объекта и у декора одинаковый
  //: набор полей (только slot), различить их по записи нельзя — а ручки
  //: у них разные (/objects против /overlays), и удаление не по той
  //: ручке стёрло бы ЧУЖУЮ запись в соседней таблице.
  choose(what.вид, what.объект);
  stage?.рисуй();
  if (what.вид === "unit" || what.вид === "packUnit") {
    unitInspector(what.объект);
    return true;
  }
  status(`выбран ${what.имя}` +
         (what.двигается ? " · держите ЛКМ чтобы возить, Del — убрать"
                        : ` · ${what.почемуНеДвигается || "не двигается"}`));
  return true;
}
//: Escape выходит из режима расстановки (сброс state.place) — раньше
//: выбор породы/картинки в каталоге не отпускал НИЧЕМ: ни Escape, ни
//: ПКМ, ни Delete, ни повторный клик по той же строке каталога, и
//: единственный способ вернуться к обычному выбору был залезть в
//: консоль браузера.
//: ESCAPE ВЫХОДИТ ИЗ ЛЮБОГО РЕЖИМА, А НЕ ТОЛЬКО ИЗ РАССТАНОВКИ.
//: Режимов у редактора несколько, и каждый ловит клики по холсту:
//: расстановка (state.place), набор области двумя углами (areaMode/
//: area), постановка выхода (exitArm/exitCorner). Escape отпускал
//: только первый — из двух других выйти было нечем вовсе, кроме
//: перезагрузки страницы.
document.addEventListener("keydown", ev => {
  if (ev.key !== "Escape") return;
  if (["INPUT", "TEXTAREA", "SELECT"].includes(
      document.activeElement?.tagName)) return;
  const prev = [];
  if (state.place) { state.place = null; prev.push("расстановка"); }
  if (state.exitArm || state.exitCorner) {
    state.exitArm = null; state.exitCorner = null;
    prev.push("постановка выхода");
  }
  if (state.areaMode || state.area) {
    state.areaMode = false; state.area = null;
    prev.push("набор области");
  }
  if (!prev.length) return;
  status(`выключено: ${prev.join(", ")} — клик снова выбирает`);
  showScreen(state.screen);
});
document.addEventListener("keydown", async ev => {
  if (ev.key !== "Delete") return;
  if (!selectedOf()) return;
  if (["INPUT", "TEXTAREA", "SELECT"].includes(
      document.activeElement?.tagName)) return;
  //: КЛАВИША И КНОПКА ДЕЛАЮТ ОДНО И ТО ЖЕ. Здесь лежала вторая, урезанная
  //: копия удаления: она не видела кучу из списка (state.pickedPile) и
  //: слала её в `/objects/undefined`. Теперь обе зовут убратьВыбранное.
  await removePicked(document.querySelector("#stage .dv-card canvas"));
});

// 1f — существа и отряды: живой бестиарий в его списке
//: собрать имя человека из двух номеров — так же, как это делает движок:
//: сначала имя (таблица 0xF0), затем прозвище (0xF1) через пробел.
//: Таблица приходит с /catalog/names и лежит в state.каталогИмён.
function nameByNumber(name_id, nick_id) {
  const k2 = state.каталогИмён;
  if (!k2) return "";
  const nm = k2.names.find(z2 => z2.id === Number(name_id))?.name || "";
  const nick = k2.nicknames.find(z2 => z2.id === Number(nick_id))?.name;
  return nick ? `${nm} ${nick}` : nm;
}
async function screen1f(card) {
  const stage = mountCanvas(card, {
    хватать: CATCH["1f"],
    //: ОДИН ЖЕСТ ПЕРЕНОСА НА ВЕСЬ РЕДАКТОР — УДЕРЖАНИЕ ЛКМ.
    //: Здесь жил свой, третий по счёту: Ctrl+клик переносил юнита. На
    //: экране кладов был четвёртый (простой клик по холсту переносил
    //: выбранную кучу — и любой промах мимо неё увозил её куда попало),
    //: а объекты возились удержанием. Одно и то же действие тремя
    //: разными жестами на трёх экранах — человеку приходилось помнить,
    //: где он находится, чтобы знать, как двигать. Осталось удержание:
    //: оно работает для всего, включая юнитов (ЛОВИТ["1f"]).
    click: async (pt, ev) => {
      // Клик ПРЯМО ПО уже стоящему юниту/объекту — всегда выбирает,
      // даже когда в бестиарии выбрана порода для расстановки: иначе
      // клик по существующему юниту штамповал поверх него ещё одного
      // вместо того, чтобы открыть его инспектор.
      if (await pickOnCanvas(pt, stage, CATCH["1f"])) {
        const u2 = selectedOf("unit", "packUnit");
        if (u2) refreshUnitPanel(u2);
        return;
      }
      if (!state.place || state.place.kind !== "unit") return;
      const cellRec = cellAt(pt);
      //: КАРТА ИЗ ИГРЫ — ЖИТЕЛЬ В НЕЁ НЕ ЛЯЖЕТ, и молчать об этом
      //: нельзя. Клик уходил на сервер, тот отказывал защитой канона, а
      //: ответ никто не показывал: со стороны «выбрал породу, тыкаю по
      //: карте — ничего не происходит». Отказ говорим сразу и подсвечиваем
      //: полосу с кнопкой копирования — там выход.
      if (state.editable === false && state.кудаЮнит !== "world") {
        status(`${mapLocked()} · житель ляжет в копию`);
        blinkCanonStrip();
        return;
      }
      //: ЖИТЕЛЬ В МИР — СВОИМ ОТРЯДОМ, а не в слой карты. Слой карты
      //: виден всем девяти героям сразу; житель мира принадлежит одному.
      //: Породу, тело и ИМЯ задаём сами: все они в белом списке полей,
      //: которые сборка мира пишет поверх записи-образца.
      if (state.кудаЮнит === "world") {
        const slotNum = state.слотГероя;
        if (!slotNum?.editable) {
          status("у этого героя нет исходников мира — писать некуда");
          return;
        }
        const p2 = state.place;
        const patchRec = { breed: p2.breed, body: p2.body,
                         palette: p2.palette ?? p2.palettes?.[0] ?? 0 };
        //: ИМЯ — НОМЕР В ТАБЛИЦЕ exe (0xF0), а не строка: самой строки в
        //: GAME.<мир> нет вовсе. Поэтому имя не пишется, а ВЫБИРАЕТСЯ из
        //: авторских 184. Не выбрано — не трогаем байт совсем: житель
        //: тогда честно наследует имя записи-образца.
        //: Тварей это не касается: у пород 0x41…0x53 имя берётся из
        //: таблицы пород по самому байту породы.
        const beast = p2.breed >= 0x41 && p2.breed <= 0x53;
        if (!beast && state.имяЖителя?.name_id) {
          patchRec.name_id = state.имяЖителя.name_id;
          patchRec.nick_id = state.имяЖителя.nick_id || 0;
        }
        const resp = await api(
          `/worlds/${slotNum.world}/maps/${state.map}/units`, "POST",
          { add: { row: cellRec.row, col: cellRec.col, patch: patchRec } });
        if (resp.ok) {
          await openMap(state.map);
          stage?.рисуй();
          //: ГОВОРИМ РОВНО ТО, ЧТО ВЫШЛО. Раньше здесь стояло «имя
          //: унаследовано от образца» — правда до тех пор, пока имени
          //: не было в белом списке. Теперь имён три случая, и путать
          //: их нельзя: человек иначе полчаса ищет, почему его
          //: «Ратибор» зовётся «Хрофтом».
          const ownVal = !beast && patchRec.name_id
            ? nameByNumber(patchRec.name_id, patchRec.nick_id) : "";
          status(`${beast ? p2.name : (ownVal || resp.name || p2.name)} → ` +
                 `${cellRec.row}:${cellRec.col} · мир ${slotNum.world}, свой отряд ` +
                 `${resp.side}` +
                 (beast ? "" : ownVal
                    ? ` · имя выбрано из таблицы игры`
                    : ` · имя унаследовано от «${resp.name}»: выберите своё ` +
                      `в списке слева`) +
                 ` · осталось слотов: отрядов ${resp.free_parties}, ` +
                 `юнитов ${resp.free_units} · соберите мир и пак`);
        }
        return;
      }
      let side = state.place.side;
      if (side === "hostile" || side === "peace" || side == null) {
        //: НОВЫЙ ОТРЯД — ТОЛЬКО ПО ПРОСЬБЕ. Каждый клик заводил свой:
        //: пятнадцать сторон редактора кончались на шестнадцатом жителе,
        //: и расстановка ломалась совсем. Сервер подселяет в уже
        //: заведённый отряд той же враждебности; кнопка «отряд»
        //: взводит state.новыйОтряд — тогда просим новый.
        const obj = await api(`/maps/${state.map}/warbands`, "POST",
          { row: cellRec.row, col: cellRec.col,
            hostile: side !== "peace",
            fresh: Boolean(state.новыйОтряд) });
        state.новыйОтряд = false;
        //: ОТКАЗ БЕЗ СЛОВ — ЭТО «НЕ РАБОТАЕТ». Здесь стоял голый return:
        //: отряд не завёлся, житель не встал, а строка состояния молчала.
        if (!obj.ok) {
          status("отряд не завёлся: " + (obj.note || "сервер отказал"));
          return;
        }
        side = obj.warband.side;
        //: НОМЕР ЗАВЕДЁННОГО ОТРЯДА ЗАПОМИНАЕТСЯ. Здесь его теряли, и на
        //: КАЖДЫЙ следующий клик state.place.side снова оказывался
        //: строкой "hostile" — сервер заводил ЕЩЁ ОДИН отряд (190, 191,
        //: 192…), по одному бойцу в каждом. Засаду из пятерых собрать
        //: было нельзя в принципе: пятеро одиночек не воюют как отряд,
        //: а зона агрессии у каждого своя. Новый отряд начинается
        //: осознанно — кнопкой смены стороны или новым выбором породы.
        state.place.side = side;
      }
      const p2 = state.place;
      const img = p2.sample || {};
      const id = "unit_new_" + Date.now();
      //: ИМЯ ЧЕЛОВЕКА. У твари имя даёт порода, и «Аспид» — верное имя.
      //: У человека имени в породе нет вовсе: в игре оно берётся из
      //: таблицы exe по номеру. Записав сюда имя строки каталога, мы
      //: получили бы жителя по имени «Человек · тело 0». Берём то, что
      //: выбрано в ряду имён; не выбрано — честное «Житель».
      const chosenName = p2.human && state.имяЖителя?.name_id
        ? nameByNumber(state.имяЖителя.name_id, state.имяЖителя.nick_id) : "";
      const resp = await api(`/maps/${state.map}/units`, "POST", {
        id, patch: {
          id, name: chosenName || (p2.human ? "Житель" : p2.name),
          //: номера имени пригодятся сборке мира, если жителя однажды
          //: перенесут из draft-слоя в исходники
          name_id: p2.human ? (state.имяЖителя?.name_id || 0) : 0,
          nick_id: p2.human ? (state.имяЖителя?.nick_id || 0) : 0,
          breed: p2.breed, body: p2.body,
          //: ЧЬИ КАДРЫ. Народ пустыни (тела 6 и 7) живёт только во
          //: второй игре — канонных слоёв под него нет вовсе, и без
          //: этого поля такой житель выходил цветным шумом и на холсте,
          //: и в игре. Сборка печёт его пару «игра+тело+масть».
          game: p2.game && p2.game !== "canon" ? p2.game : undefined,
          palette: p2.palette ?? p2.palettes?.[0] ?? 0,
          side, party: side, direction: 6,
          level: img.level ?? 1, money: img.money ?? 0,
          speed: img.speed ?? 0, venom: img.venom ?? 0,
          face: img.face ?? 0,
          stats: { ...(img.stats || { health: 400 }) },
          characteristics: { ...(img.characteristics || {}) },
          skills: { ...(img.skills || {}) },
          cell: { row: cellRec.row, col: cellRec.col },
          home: { row: cellRec.row, col: cellRec.col },
        },
      });
      if (resp.ok) {
        const inBand = ((state.mapState?.draft?.editor_units_add) || [])
          .filter(u2 => u2.side === side).length + 1;
        //: СНАЧАЛА ПЕРЕЧИТАТЬ, ПОТОМ СКАЗАТЬ. открытьКарту кончается
        //: своим status() «карта 63: объектов 4, вода 2» и затирала
        //: подтверждение через долю секунды: человек ставил жителя и
        //: видел в строке пересказ карты, то есть не знал, вышло ли.
        //: Та же болезнь, что была у переноса (см. записатьПеренос).
        await openMap(state.map); stage?.рисуй();
        status(`${chosenName || (p2.human ? "Житель" : p2.name)} → клетка ` +
               `${cellRec.row}:${cellRec.col} · отряд ${side} (в нём ${inBand}) · ` +
               `следующий клик добавит в ТОТ ЖЕ отряд; кнопка «отряд» ` +
               `начнёт новый · нажмите Build, чтобы увидеть его в игре`);
      } else {
        //: та же болезнь, что у отряда выше: отказ обязан быть слышен
        status("житель не встал: " + (resp.note || "сервер отказал"));
      }
    },
  });
  if (!state.bestiary) state.bestiary = await api("/catalog/bestiary");
  // зона бестиария: колонка со многими строками-карточками
  const beastZone = zoneOf(card, "список-существ");
  if (!beastZone) return;
  beastZone.style.maxHeight = "min(56vh, 520px)";
  beastZone.style.overflowY = "auto";

  //: Вырез кадра с листа — фоном: и в строке породы, и в ряду мастей.
  function previewThumb(previewRec, box) {
    const z = Math.min(box / previewRec.width, (box - 4) / previewRec.height, 1);
    const it = document.createElement("div");
    it.style.cssText =
      `flex:none;width:${previewRec.width * z}px;` +
      `height:${previewRec.height * z}px;` +
      `background-image:url(${previewRec.url});background-repeat:no-repeat;` +
      `background-position:${-previewRec.x * z}px ${-previewRec.y * z}px;` +
      `background-size:${previewRec.sheet_width * z}px ` +
      `${previewRec.sheet_height * z}px`;
    return it;
  }

  function listRow(previewRec, title2, label, isPicked, click2) {
    const rowEl = document.createElement("div");
    rowEl.style.cssText =
      "display:flex;align-items:center;gap:9px;padding:5px 8px;" +
      "border-radius:6px;cursor:pointer;border:1.5px solid " +
      (isPicked ? "#2563eb" : "transparent");
    if (previewRec) rowEl.appendChild(previewThumb(previewRec, 34));
    const txt = document.createElement("div");
    txt.innerHTML =
      `<div style="font:600 12px 'IBM Plex Sans'">${title2}</div>` +
      `<div style="font:10px 'IBM Plex Mono';color:#64748b">${label}</div>`;
    rowEl.appendChild(txt);
    rowEl.onclick = click2;
    beastZone.appendChild(rowEl);
  }

  //: «Бестиарий» — что СТАВИТЬ (породы каталога), «Жители пака» — кого
  //: ПРАВИТЬ (те, кто уже стоит на карте). Раньше жила только первая
  //: половина, и вторая вкладка выглядела сломанной.
  async function renderList() {
    beastZone.replaceChildren();
    //: КАК ВООБЩЕ ПОСТАВИТЬ ЖИТЕЛЯ. Порядок тут неочевиден: сначала
    //: выбрать породу в списке, и только потом кликать по карте. Пока
    //: порода не выбрана, клик по пустому месту не делает НИЧЕГО и
    //: молчит — «не понимаю, как добавить нпс» было честным описанием.
    //: Подсказка живёт над списком и исчезает, как только выбор сделан.
    if (state.unitsTab !== "pack" && !state.place) {
      const howTo = document.createElement("div");
      howTo.style.cssText = "margin:4px;padding:6px 8px;border-radius:5px;" +
        "background:#eff6ff;color:#1e40af;font:11px 'IBM Plex Sans';" +
        "line-height:1.4";
      howTo.textContent = "Чтобы поставить жителя: выберите породу ниже, " +
        "потом кликните по карте. Куда он ляжет — решает «Пишем в» " +
        "сверху, а мирный он или вражий — кнопка «отряд».";
      beastZone.appendChild(howTo);
    }
    if (state.unitsTab === "pack") {
      const p2 = await api(`/maps/${state.map}/pack`);
      const residents = (p2.ok && p2.units) || [];
      for (const resident of residents) {
        listRow(null, resident.name || resident.id,
          `breed 0x${Number(resident.breed || 0).toString(16)} · ` +
          `клетка ${resident.cell?.row}:${resident.cell?.col}` +
          (resident.dialog_number != null && resident.dialog_number !== 255
            ? ` · диалог ${resident.dialog_number}` : ""),
          isChosen(resident),
          () => { choose("packUnit", resident);
                  unitInspector(resident);
                  refreshUnitPanel(resident); });
      }
      //: ТОЛЬКО ЧТО ПОСТАВЛЕННОГО ТУТ НЕ БЫЛО. Список читал ТОЛЬКО пак,
      //: то есть собранных; поставленный житель лежит в draft-слое и
      //: попадает в пак лишь после Build. Человек ставил жителя, шёл в
      //: список — пусто, и вывод один: клик не сработал. Показываем и
      //: черновых, но подписываем честно: они ещё не в паке.
      const drafts = (state.mapState?.draft?.editor_units_add) || [];
      for (const u2 of drafts) {
        listRow(null, u2.name || u2.id,
          `черновик · отряд ${u2.side} · клетка ` +
          `${u2.cell?.row}:${u2.cell?.col} · в паке будет после Build`,
          isChosen(u2),
          //: инспектор открываем и черновым — у паковых строк он
          //: открывался, у своих нет, а именно у своих чаще всего и
          //: надо поправить имя или диалог
          () => { choose("unit", u2); refreshUnitPanel(u2);
                  unitInspector(u2);
                  stage?.рисуй(); renderList(); });
      }
      if (!residents.length && !drafts.length) {
        const emptyEl = document.createElement("div");
        emptyEl.style.cssText = "padding:8px;font:12px 'IBM Plex Mono';" +
          "color:#64748b";
        emptyEl.textContent = "жителей нет ни в паке, ни в черновике — " +
          "выберите породу на вкладке «Бестиарий» и кликните по карте";
        beastZone.appendChild(emptyEl);
      }
      return;
    }
    for (const breedRec of state.bestiary.breeds || []) {
      //: У ЧЕЛОВЕКА ПОДПИСЬ ДРУГАЯ. Имя человека берётся из таблицы exe
      //: и к породе не привязано — «breed 0x0» ему ничего не говорит.
      //: Полезно другое: на кого он ПОХОЖ (из живых записей игры) и
      //: сколько у этого вида мастей.
      listRow(breedRec.preview, breedRec.name,
        breedRec.human
          ? `как «${breedRec.looks_like || "житель"}» · мастей ` +
            `${(breedRec.palettes || []).length} · hp ` +
            `${(breedRec.sample?.stats || {}).health ?? "?"}`
          //: у ИМЕННЫХ персонажей (породы выше 0x53) названия породы нет
          //: вовсе — движок зовёт их по имени записи; показываем, кто ТАК
          //: выглядит в самой игре
          : (breedRec.looks_like
             ? `как «${breedRec.looks_like}» · порода 0x` +
               `${breedRec.breed.toString(16)} · мастей ` +
               `${(breedRec.palettes || []).length}`
             : `порода 0x${breedRec.breed.toString(16)} · мастей ` +
               `${(breedRec.palettes || []).length} · hp ` +
               `${(breedRec.sample?.stats || {}).health ?? "?"}`),
        Boolean(state.place) &&
          breedKey(state.place) === breedKey(breedRec),
        () => {
          //: масть несёт СВОЮ игру: народ пустыни рисуется кадрами
          //: «Продолжения легенды», славяне — канонными
          const firstCoat = (breedRec.previews || [])[0];
          state.place = { kind: "unit", ...breedRec,
                          palette: firstCoat?.palette
                            ?? (breedRec.palettes || [])[0] ?? 0,
                          game: firstCoat?.game || "canon",
                          side: state.unitSide || "hostile" };
          //: выбрали человека — открываем ряд имён (у твари имя даёт
          //: порода, и выбирать там нечего)
          state.показатьРядИмени?.();
          status(`${breedRec.name}: кликните по холсту — отряд ` +
                 (state.unitSide === "peace" ? "мирный" : "вражий") +
                 (breedRec.human ? " · имя выберите в списке над породами"
                               : ""));
          renderList();
        });
      //: РЯД МАСТЕЙ У ВЫБРАННОЙ ПОРОДЫ. Масти были только числом в
      //: подписи («мастей 5»), а ставилась всегда первая — и житель
      //: выходил в диковинном цвете, который человек не выбирал.
      const picked = Boolean(state.place) &&
        breedKey(state.place) === breedKey(breedRec);
      const shots = breedRec.previews || [];
      if (picked && shots.length > 1) {
        const strip = document.createElement("div");
        strip.dataset.lv = "масти-породы";
        strip.style.cssText = "display:flex;flex-wrap:wrap;gap:5px;" +
          "padding:4px 8px 8px 44px;align-items:flex-end";
        for (const shot of shots) {
          const cell = document.createElement("div");
          //: масть опознаётся ПАРОЙ «игра+номер»: номер 28 у канона и у
          //: легенды — разные цвета
          const own = (state.place.palette ?? shots[0].palette) === shot.palette
            && (state.place.game || "canon") === (shot.game || "canon");
          cell.title = `масть ${shot.palette}` +
            (shot.game === "legend" ? " · кадры второй игры" : "");
          cell.style.cssText = "display:flex;align-items:flex-end;" +
            "justify-content:center;width:36px;height:40px;cursor:pointer;" +
            "border-radius:5px;border:1.5px solid " +
            (own ? "#2563eb;background:#eff6ff" : "#e2e8f0;background:#fff");
          const frm = shot.frame?.layers?.[0] || shot.frame;
          if (frm?.url) cell.appendChild(previewThumb(frm, 30));
          cell.onclick = () => {
            state.place.palette = shot.palette;
            state.place.game = shot.game || "canon";
            status(`${breedRec.name}: масть ${shot.palette}` +
                   (shot.game === "legend" ? " (кадры второй игры)" : "") +
                   ` — кликните по холсту`);
            renderList();
          };
          strip.appendChild(cell);
        }
        beastZone.appendChild(strip);
      }
    }
  }
  toggleOf(card, ["Бестиарий", "Жители пака"],
          state.unitsTab === "pack" ? "Жители пака" : "Бестиарий",
          label => {
            state.unitsTab = label === "Жители пака" ? "pack" : "breeds";
            renderList();
          });
  //: ЧИСЛА ВКЛАДОК БЫЛИ ИЗ МАКЕТА. «23 породы» и «Жители пака · 46»
  //: стояли на КАЖДОЙ карте, включая пустую: дизайнер написал их один
  //: раз, глядя на карту 23. Человек читает их как данные и делает
  //: выводы — «здесь 46 жителей», — хотя на его карте их двое. Числа,
  //: которые лгут, хуже отсутствующих: по ним принимают решения.
  const breedTotal = (state.bestiary?.breeds || []).length;
  const packResidents = (state.packUnits || []).length;
  const draftTotal =
    ((state.mapState?.draft?.editor_units_add) || []).length;
  for (const el of card.querySelectorAll("div,span")) {
    if (el.childElementCount) continue;
    const pt = el.textContent.trim();
    if (/^\d+\s+пород/.test(pt) && breedTotal) {
      el.textContent = `${breedTotal} ${plural(breedTotal,
        ["вид", "вида", "видов"])}`;
    } else if (/^Жители пака(\s*·\s*\d+)?$/.test(pt)) {
      el.textContent = draftTotal
        ? `Жители пака · ${packResidents} (+${draftTotal})`
        : `Жители пака · ${packResidents}`;
    }
  }
  //: «ПИШЕМ В: draft-слой | мир» — ТУМБЛЕР С НУЛЕВЫМ ДЕЙСТВИЕМ.
  //:
  //: Он переключал state.writeTo и уверял строкой статуса, что «правки
  //: пойдут в мир (POST /worlds)», — но НИ ОДНА запись это поле не
  //: читала: во всём файле writeTo встречался ровно дважды, оба раза
  //: внутри самого тумблера. Что бы человек ни выбрал, юнит уходил в
  //: draft-слой карты. Кнопка, которая делает вид, что переключает
  //: важное, хуже отсутствующей: по ней принимают решения.
  //:
  //: Ручки на сервере для правки мира есть (POST /worlds/{w}/maps/{n}/
  //: units), но они умеют только ПАТЧИТЬ существующего жителя по
  //: индексу — добавить нового в мир нечем, а расстановка населения
  //: мира это отдельный экран (см. docs/EDITOR_USABILITY_AUDIT).
  //: Пока его нет — говорим правду вместо переключателя.
  //: «ПИШЕМ В: draft-слой | мир» СНОВА ЖИВОЙ — теперь по-настоящему.
  //:
  //: Тумблер долго был обманом: он переключал поле, которое никто не
  //: читал. Потом я заменила его честной надписью «правки идут в
  //: draft-слой», потому что добавить жителя В МИР было нечем. Теперь
  //: есть (editor_world_unit_add), и выбор снова осмыслен:
  //:   draft-слой — юнит ложится в scenario.json карты и виден ВСЕМ
  //:                девяти героям сразу;
  //:   мир        — житель уходит в исходники ЭТОГО героя своим
  //:                отрядом, как родные жители игры.
  //: Донорские слоты писать нечем — их исходников у нас нет.
  //: назначается ниже, вместе с рядом выбора имени; красить() зовёт его,
  //: чтобы ряд появлялся и исчезал вместе с режимом «пишем в мир»
  let showNameRow = () => {};
  const writeTo = organAny(card, "draft-слой", "правки идут в draft");
  const toWorld = organAny(card, "мир · ", "мир");
  //: сама подпись «Пишем в:» — её тоже прячем, когда выбора нет
  const writeToLabel = [...card.querySelectorAll("div,span")]
    .find(el => el.childElementCount === 0 &&
               /^Пишем в:?$/.test(el.textContent.trim()));
  //: ПИСАТЬ В МИР МОЖНО НЕ НА ЛЮБОЙ КАРТЕ. В исходниках мира 79 карт
  //: игры; у карты, СОЗДАННОЙ РЕДАКТОРОМ, записи там нет вовсе, и
  //: добавление жителя падает с «карты N в мире W нет». Прежде тумблер
  //: предлагался всегда — человек на своей «Тихой заводи» выбирал
  //: доступный на вид путь, который не работает никогда.
  const worldMapNumbers = state.слотГероя?.map_numbers;
  const worldKnows = !Array.isArray(worldMapNumbers) ||
                   worldMapNumbers.includes(Number(state.map));
  const ownWorld = state.слотГероя ? (state.слотГероя.editable && worldKnows)
                                  : false;
  if (writeTo) {
    const paint = () => {
      const peaceful = state.кудаЮнит === "world" && ownWorld;
      writeTo.узел.textContent = "draft-слой";
      writeTo.узел.style.background = peaceful ? "transparent" : "#0f172a";
      writeTo.узел.style.color = peaceful ? "" : "#f8fafc";
      writeTo.узел.style.padding = "2px 8px";
      writeTo.узел.style.borderRadius = "5px";
      if (toWorld && toWorld.узел !== writeTo.узел) {
        //: ВЫБОРА ИЗ ОДНОГО НЕ ПОКАЗЫВАЕМ — НО ТОЛЬКО ТАМ, ГДЕ ЕГО НЕТ
        //: ПО УСТРОЙСТВУ КАРТЫ. У карты, СОЗДАННОЙ РЕДАКТОРОМ, записи в
        //: исходниках мира нет вовсе, и второй вариант не заработает
        //: никогда: тумблер вырождался в служебную подпись «мир (карта
        //: не из игры)», которая на экране существ только сбивает
        //: («зачем эта информация в существах?»). Прячем.
        //:
        //: А вот у ДОНОРСКОГО героя карта в мире есть, писать нечем
        //: только нам — здесь подпись объясняет, почему путь закрыт, и
        //: остаётся: без неё человек, видевший выбор на другом герое,
        //: решит, что редактор потерял кнопку.
        toWorld.узел.style.display = worldKnows ? "" : "none";
        toWorld.узел.textContent = ownWorld
          ? `мир · ${(state.слотГероя?.hero || "").slice(0, 14)}`
          : "мир (нет исходников)";
        toWorld.узел.style.opacity = ownWorld ? "1" : ".45";
        toWorld.узел.style.background = peaceful ? "#0f172a" : "transparent";
        toWorld.узел.style.color = peaceful ? "#f8fafc" : "";
        toWorld.узел.style.padding = "2px 8px";
        toWorld.узел.style.borderRadius = "5px";
      }
      //: «Пишем в:» без второго варианта — тоже лишнее слово.
      if (writeToLabel) writeToLabel.style.display = worldKnows ? "" : "none";
      //: ПОДПИСЬ ПОД ТУМБЛЕРОМ БЫЛА ЗАПИСКОЙ РАЗРАБОТЧИКА: «население
      //: 23-й разное в 6 мирах · имена героев — из GET /worlds». Она
      //: висела на ЛЮБОЙ карте (в том числе на 63-й, к 23-й отношения не
      //: имеющей) и говорила про ручку API, а не про выбор. Пишем то,
      //: что человеку решать: кто увидит поставленного жителя.
      const writeNote = [...card.querySelectorAll("div,span")]
        .find(el => el.childElementCount === 0 &&
                    /население 23|GET \/worlds/.test(el.textContent));
      if (writeNote) {
        writeNote.style.display = worldKnows ? "" : "none";
        writeNote.textContent = ownWorld
          ? "draft-слой карты видят все девять героев · житель мира — " +
            "только тот, чей это мир"
          : "у этой карты нет записи в исходниках мира — доступен только " +
            "draft-слой";
      }
      writeTo.узел.title = ownWorld ? ""
        : "у этой карты нет записи в исходниках мира — правки идут в " +
          "draft-слой карты, его видят все девять героев";
      //: ряд имён нужен не только для мира: у ЧЕЛОВЕКА в draft-слое
      //: имени тоже неоткуда взяться, кроме этого выбора
      showNameRow(peaceful || Boolean(state.place?.human));
    };
    state.показатьРядИмени = paint;
    bindTo(writeTo, () => {
      state.кудаЮнит = "draft"; paint();
      status("новый житель ляжет в draft-слой карты — его увидят все " +
             "девять героев");
    });
    if (toWorld && toWorld.узел !== writeTo.узел) {
      bindTo(toWorld, () => {
        if (!ownWorld) {
          status(!worldKnows
            ? `карту ${state.map} «${state.mapName}» создал редактор — в ` +
              `исходниках мира её нет, и жителю мира там негде лечь. ` +
              `Ставьте в draft-слой: он работает на любой карте`
            : `${state.слотГероя?.hero || "этот герой"} из донорской ` +
              `игры — её исходников у нас нет, писать некуда`);
          return;
        }
        state.кудаЮнит = "world"; paint();
        status(`новый житель уйдёт в мир ${state.слотГероя.world} ` +
               `(${state.слотГероя.hero || ""}) своим отрядом`);
      });
    }
    if (!ownWorld) state.кудаЮнит = "draft";
    paint();
  }
  //: вражий/мирный отряд. В макете такой пары нет — ставим свою кнопку
  //: над списком (без неё жителя-миролюбца не поставить вовсе).
  const choice = document.createElement("button");
  const sideLabel = () => choice.textContent =
    state.unitSide === "peace" ? "отряд: МИРНЫЙ (жители) — сменить"
                               : "отряд: вражий — сменить на мирный";
  choice.style.cssText = "margin:4px;width:calc(100% - 8px);padding:5px;" +
    "font:12px 'IBM Plex Sans';cursor:pointer";
  choice.onclick = () => {
    state.unitSide = state.unitSide === "peace" ? "hostile" : "peace";
    if (state.place?.kind === "unit") state.place.side = state.unitSide;
    //: смена стороны — это и есть просьба «начать НОВЫЙ отряд»
    state.новыйОтряд = true;
    sideLabel();
    //: смена стороны сбрасывает запомненный номер отряда (выше он стал
    //: строкой) — то есть это и есть жест «начать НОВЫЙ отряд»
    status("следующий клик начнёт НОВЫЙ " +
           (state.unitSide === "peace" ? "мирный" : "вражий") +
           " отряд · заново выбрать породу — тоже новый отряд");
  };
  sideLabel();
  insertOwn(beastZone.parentElement, choice, "сторона-отряда", beastZone);
  //: ВЫБОР ИМЕНИ ЖИТЕЛЯ. Имени как строки в исходниках мира НЕТ: запись
  //: юнита хранит два номера (0xF0 имя, 0xF1 прозвище), а сами строки
  //: лежат в exe игры. Значит придумать имя нельзя — можно только взять
  //: одно из 184 авторских, и ровно это здесь и предлагается. Ряд виден
  //: только в режиме «пишем в мир»: в draft-слое карты имя не хранится.
  const nameRow = document.createElement("div");
  nameRow.style.cssText = "margin:4px;display:flex;gap:4px;" +
    "font:12px 'IBM Plex Sans'";
  const nameList = document.createElement("select");
  const nickList = document.createElement("select");
  for (const el of [nameList, nickList])
    el.style.cssText = "flex:1;min-width:0;padding:4px;font:inherit";
  nameList.innerHTML = '<option value="0">имя: от образца</option>';
  nickList.innerHTML = '<option value="0">без прозвища</option>';
  nameRow.append(nameList, nickList);
  insertOwn(beastZone.parentElement, nameRow, "выбор-имени", beastZone);
  state.имяЖителя = state.имяЖителя || { name_id: 0, nick_id: 0 };
  nameList.onchange = () => {
    state.имяЖителя.name_id = Number(nameList.value) || 0;
    status(state.имяЖителя.name_id
      ? `следующий житель будет зваться ` +
        `«${nameByNumber(state.имяЖителя.name_id, state.имяЖителя.nick_id)}»`
      : "имя нового жителя унаследуется от записи-образца");
  };
  nickList.onchange = () => {
    state.имяЖителя.nick_id = Number(nickList.value) || 0;
    nameList.onchange();
  };
  showNameRow = async isSeen => {
    nameRow.style.display = isSeen ? "flex" : "none";
    if (!isSeen || state.каталогИмён) return;
    //: тянем таблицу один раз на сеанс — она из exe и не меняется
    const k2 = await api("/catalog/names");
    if (!k2.ok) return;
    state.каталогИмён = k2;
    for (const [list, key2, emptyEl] of [[nameList, "names", "имя: от " +
        "образца"], [nickList, "nicknames", "без прозвища"]]) {
      list.innerHTML = `<option value="0">${emptyEl}</option>`;
      for (const z2 of k2[key2]) {
        const obj = document.createElement("option");
        obj.value = String(z2.id); obj.textContent = z2.name;
        list.append(obj);
      }
    }
    nameList.value = String(state.имяЖителя.name_id || 0);
    nickList.value = String(state.имяЖителя.nick_id || 0);
  };
  showNameRow(state.кудаЮнит === "world" && ownWorld);
  //: ПАНЕЛЬ ЮНИТА СПРАВА (краткая, не модальный инспекторЮнита) стояла
  //: намертво на «Скелет · 0x4c» из макета — какого юнита ни выбери.
  //: Именно её, не модалку, чинил свод: породу берём как есть (у записи
  //: уже есть человеческое имя, придумывать не нужно), «Масть» не
  //: трогаем — своей палитры цветов у нас нет, а перекрашивать кружки
  //: наугад хуже, чем оставить статикой.
  //: ЯКОРЬ ПЕРЕСТАВАЛ НАХОДИТЬ САМ СЕБЯ. Он искал «Юнит · <одно слово>»,
  //: а первая же перерисовка без выбора писала сюда «Юнит · не выбран» —
  //: два слова. Со следующего показа экрана заголовок не находился ВОВСЕ,
  //: и карточка навсегда замирала на «не выбран», хотя строки под ней
  //: исправно менялись (поймано живьём: «Житель · Славяне · мужчина» в
  //: строках при «не выбран» в заголовке). Берём всё, что начинается с
  //: «Юнит ·», и считаем промах, если не нашли.
  const unitTitle = [...card.querySelectorAll("span")]
    .find(el => el.childElementCount === 0 &&
                /^Юнит\s*·/.test(el.textContent.trim()));
  if (!unitTitle) state.промахи.push("карточка юнита: заголовок");
  const breedRow = rowValue(card, "Порода");
  const bandRow = rowValue(card, "Отряд · party");
  const levelRow = rowValue(card, "Уровень / деньги");
  const dialogRow = rowValue(card, "Диалог №");
  const healthRow = rowValue(card, "Здоровье / броня");
  const unitColumn = unitTitle?.closest(
    '[style*="width:320px"],[style*="width: 320px"]') || card;
  const STATS = [["сила", "Сила"], ["ловк", "Ловкость"],
    ["вынс", "Выносливость"], ["интл", "Интеллект"],
    ["харз", "Харизма"], ["обуч", "Обучаемость"]];
  const statRows = STATS.map(([pref]) =>
    [...unitColumn.querySelectorAll("span")]
      .find(el => el.childElementCount === 0 &&
                  el.textContent.trim().startsWith(pref)));
  function refreshUnitPanel(unitRec) {
    //: ПУСТАЯ КАРТОЧКА ДОЛЖНА БЫТЬ ПУСТОЙ. Пока никто не выбран, здесь
    //: стояли числа МАКЕТА: «Юнит · unit_new_2 · Скелет 0x4c · отряд 2
    //: разбойники · сила 9 ловк 7 вынс 8…». Выдумка дизайнера, к карте
    //: отношения не имеющая, — но человек видит заполненную карточку и
    //: заключает, что кто-то выбран и статы показываются. Отсюда и
    //: «не видно статов у нпс»: видно, только чужие и ненастоящие.
    if (!unitRec) {
      if (unitTitle) unitTitle.textContent = "Юнит · не выбран";
      for (const line of [breedRow, bandRow, levelRow, dialogRow,
                         healthRow, ...statRows]) {
        if (line) line.textContent = "—";
      }
      if (breedRow) breedRow.textContent = "щёлкните по жителю на карте";
      return;
    }
    if (unitTitle)
      unitTitle.textContent = `Юнит · ${unitRec.id || unitRec.name}`;
    //: ПОРОДА, ОТРЯД И ДИАЛОГ — СМЫСЛАМИ. Здесь стояли «0x4c», номер
    //: стороны и номер дерева: три числа, за каждым из которых надо было
    //: идти на другой экран. Порода есть в бестиарии по паре
    //: «порода:тело», вражда — у отряда, имя разговора — в сюжете.
    if (breedRow) {
      const breedRec = breedOfUnit(unitRec);
      const kin = breedRec?.name ||
        `порода 0x${Number(unitRec.breed || 0).toString(16)}`;
      //: У твари имя и порода совпадают («Скелет · Скелет») — говорим
      //: один раз; у человека имя своё, а порода общая.
      breedRow.textContent = (unitRec.name && unitRec.name !== kin)
        ? `${unitRec.name} · ${kin}` : kin;
    }
    if (bandRow) {
      const side = Number(unitRec.party ?? unitRec.side ?? -1);
      const band = mapBands().find(b2 => Number(b2.side) === side);
      bandRow.textContent = `${side} · ${bandMeaning(band)}`;
    }
    if (levelRow)
      levelRow.textContent = `${unitRec.level ?? 1} · ${unitRec.money ?? 0}`;
    if (dialogRow) {
      const num = unitRec.dialog_number;
      const talks = num != null && num !== 255;
      dialogRow.textContent = talks
        ? `${num} · ${dialogNameOf(num) || "имя ещё не прочитано"}`
        : "молчит (0xFF)";
      //: имена читаются один раз на весь редактор, и первая панель
      //: успевает нарисоваться раньше ответа — перерисуем её тогда
      if (talks && !state.диалоги) {
        ensureDialogs().then(() => refreshUnitPanel(unitRec));
      }
    }
    if (healthRow) healthRow.textContent =
      `${unitRec.stats?.health ?? "?"} · ${unitRec.stats?.armour ?? "?"}`;
    statRows.forEach((nodeEl, i) => {
      if (!nodeEl) return;
      const [pref, key2] = STATS[i];
      nodeEl.textContent = `${pref} ${unitRec.characteristics?.[key2] ?? "?"}`;
    });
  }
  refreshUnitPanel(selectedOf("unit", "packUnit"));
  wakeInspector(card, stage);
  await renderList();
}
// 1j — ОТРЯДЫ: свой экран, а не второе имя экрана существ
//: ОТРЯД — ЕДИНИЦА ВРАЖДЫ, А НЕ ПРОСТО ГРУППА БОЙЦОВ. Нападает не юнит,
//: а отряд, и решает это один проход по всем отрядам карты (VA
//: 0x415B20). Сторона юнита (+0x1B) РАВНА номеру его отряда, поэтому
//: «чей это боец» спрашивается у самого бойца. А своё у отряда —
//: биты войны (+0x1F), зона появления и зона гуляния, причём это
//: РАЗНЫЕ байты (0x0C/0x10/0x14/0x16 против 0x0E/0x12/0x15/0x17).
//:
//: Правилось всё это нигде: вкладка «Отряды» вела на экран существ и не
//: меняла там ровно ничего. Завести отряд было можно (кнопка на экране
//: существ), а поправить — нечем.
const WAR_BITS = [
  ["on_player", "нападает на игрока"],
  ["on_parties", "нападает на другие отряды"],
  ["only_if_fighting", "только если уже в бою"],
  ["on_special", "особая цель"],
];
function mapBands() {
  const packData = (state.packWarbands || []).map(obj => ({ ...obj, свой: false }));
  const mine = ((state.mapState?.draft?.editor_warbands_add) || [])
    .map(obj => ({ ...obj, свой: true }));
  //: черновик побеждает пак: правки идут в него, а паковая копия —
  //: снимок последней сборки (та же беда, что была у куч)
  const taken2 = new Set(mine.map(obj => Number(obj.side)));
  return [...packData.filter(obj => !taken2.has(Number(obj.side))), ...mine]
    .sort((a2, b2) => Number(a2.side) - Number(b2.side));
}
//: бойцы отряда: сторона лежит в самом бойце — и у паковых, и у своих.
//:
//: ОДИН БОЕЦ — ОДНА СТРОКА. После сборки поставленный юнит лежит В ОБОИХ
//: списках: в черновике (правки идут туда) и в паке (снимок сборки), и
//: сложение списков считало его дважды — «2 бойца» у отряда, где стоит
//: один. Ключ — клетка: двух юнитов на одной клетке не бывает (это
//: отдельно стерегут и сборка, и тест), а черновик побеждает пак, как и
//: у отрядов.
function bandFighters(sideNum) {
  const mine = (state.mapState?.draft?.editor_units_add) || [];
  const seen = new Map();
  for (const list of [state.packUnits || [], mine]) {
    for (const u2 of list) {
      if (Number(u2.side) !== Number(sideNum)) continue;
      seen.set(u2.cell ? `${u2.cell.row}:${u2.cell.col}` : (u2.id ?? u2), u2);
    }
  }
  return [...seen.values()];
}
//: клетки бойцов в силе, только когда у отряда стоит бит keep_cells
//: (байт 0x1E, 0x10): иначе движок при входе на карту рассыпает отряд
//: по зоне появления и ПЕРЕЗАПИСЫВАЕТ записанные клетки (FUN_00415764)
function bandKeepsCells(band) {
  const z2 = band?.zone || {};
  if (z2.keep_cells != null) return Boolean(z2.keep_cells);
  return Boolean(Number(z2.flags || 0) & 0x10);
}
async function screen1j(card) {
  canonStrip(card);
  const stage = mountCanvas(card, {
    хватать: CATCH["1j"],
    //: ЗОНЫ ВЫБРАННОГО ОТРЯДА — ПОВЕРХ СЦЕНЫ. Прямоугольники появления
    //: и гуляния не были видны нигде, а именно они решают, где отряд
    //: встанет при входе на карту и куда забредёт потом.
    поверх: (brush, kindOf) => {
      const band = mapBands().find(obj => Number(obj.side) === state.отряд);
      if (!band) return;
      for (const [key2, paintColor, label] of [["zone", "#2563eb", "появление"],
                                           ["roam", "#16a34a", "гуляние"]]) {
        const z2 = band[key2];
        if (!z2) continue;
        if (z2.row_from === z2.row_to && z2.col_from === z2.col_to) continue;
        const corners = [[z2.row_from, z2.col_from], [z2.row_from, z2.col_to],
                      [z2.row_to, z2.col_to], [z2.row_to, z2.col_from]]
          .map(([r, c]) => cellAnchor({ row: r ?? 0, col: c ?? 0 }));
        brush.strokeStyle = paintColor;
        brush.lineWidth = 2 / kindOf.zoom;
        brush.setLineDash(key2 === "roam"
          ? [6 / kindOf.zoom, 4 / kindOf.zoom] : []);
        brush.beginPath();
        corners.forEach((pt, i) => i ? brush.lineTo(pt.x * K, pt.y * K)
                                 : brush.moveTo(pt.x * K, pt.y * K));
        brush.closePath();
        //: ЗАЛИВКА, А НЕ ОДИН КОНТУР. Зоны бывают во всю карту (у
        //: отряда 65 «Морского лагеря» это строки 3…182, столбцы
        //: 1…117), и тогда все четыре кромки уходят за края экрана:
        //: контур нарисован честно, а видно пусто. Чуть заметная
        //: заливка показывает зону и изнутри — а на маленькой зоне она
        //: не мешает, потому что почти прозрачна.
        brush.globalAlpha = 0.10;
        brush.fillStyle = paintColor;
        brush.fill();
        brush.globalAlpha = 1;
        brush.stroke();
        brush.setLineDash([]);
        brush.fillStyle = paintColor;
        brush.font = (11 / kindOf.zoom) + "px monospace";
        brush.fillText(label, corners[0].x * K + 4,
                       corners[0].y * K - 4 / kindOf.zoom);
      }
      brush.lineWidth = 1;
    },
    click: async pt => {
      //: щелчок по бойцу выбирает ЕГО отряд — так проще всего понять,
      //: чей это боец, и не нужно держать номера сторон в уме
      const what = hitAt(pt, CATCH["1j"]);
      if (!what) return;
      const sideNum = Number(what.объект.side);
      const band = mapBands().find(obj => Number(obj.side) === sideNum);
      if (!band) {
        status(`${what.имя}: сторона ${sideNum}, а отряда с таким номером ` +
               `на карте нет — запись отряда потерялась`);
        return;
      }
      state.отряд = sideNum;
      showScreen("1j");
      status(`${what.имя} — боец отряда ${sideNum}`);
    },
  });
  //: ЛЕВАЯ КОЛОНКА. Клон карточки существ принёс сюда бестиарий —
  //: чистим зону и наполняем своим списком отрядов.
  const bandZone = zoneOf(card, "список-отрядов");
  //: подписи макета говорят про существ — на этом экране они врут
  for (const el of card.querySelectorAll("span,div")) {
    if (el.childElementCount !== 0) continue;
    const pt = el.textContent.trim();
    if (pt === "Существа") el.textContent = "Отряды";
    else if (pt === "Бестиарий") el.textContent = "На карте";
    else if (/^\d+\s+(пород|вид)/.test(pt)) el.textContent = "";
    else if (/^Жители пака/.test(pt)) el.textContent = "";
  }
  //: ЯКОРЬ ПЕРЕСТАВАЛ НАХОДИТЬ САМ СЕБЯ. Он искал «Юнит · <одно слово>»,
  //: а первая же перерисовка без выбора писала сюда «Юнит · не выбран» —
  //: два слова. Со следующего показа экрана заголовок не находился ВОВСЕ,
  //: и карточка навсегда замирала на «не выбран», хотя строки под ней
  //: исправно менялись (поймано живьём: «Житель · Славяне · мужчина» в
  //: строках при «не выбран» в заголовке). Берём всё, что начинается с
  //: «Юнит ·», и считаем промах, если не нашли.
  const unitTitle = [...card.querySelectorAll("span")]
    .find(el => el.childElementCount === 0 &&
                /^Юнит\s*·/.test(el.textContent.trim()));
  if (!unitTitle) state.промахи.push("карточка юнита: заголовок");
  const rightCol = unitTitle?.closest(
    '[style*="width:320px"],[style*="width: 320px"]') || card;

  async function saveIt(band, patchBody) {
    const resp = await api(`/maps/${state.map}/warbands`, "POST",
                        { side: band.side, patch: patchBody });
    const msg = resp.note || (resp.ok ? "готово" : "не вышло");
    if (resp.ok) { await openMap(state.map); showScreen("1j"); }
    //: статус ПОСЛЕ перечитывания: открытьКарту кончается своим и
    //: затирает итог (та же болезнь, что была у переноса и куч)
    status(msg);
  }

  function bandPanel(band) {
    const blk = document.createElement("div");
    blk.style.cssText = "padding:10px;font:11px 'IBM Plex Mono';" +
      "color:#334155;display:flex;flex-direction:column;gap:8px";
    if (!band) {
      blk.insertAdjacentHTML("beforeend",
        `<div style="color:#64748b">Отряд не выбран — щёлкните строку ` +
        `слева или бойца на карте</div>`);
      insertOwn(rightCol, blk, "панель-отряда", rightCol.firstElementChild);
      return;
    }
    const fighters = bandFighters(band.side);
    blk.insertAdjacentHTML("beforeend",
      `<div style="font:600 13px 'IBM Plex Sans';color:#0f172a">` +
      `Отряд ${band.side}${band.player ? " · отряд игрока" : ""}` +
      `<span style="font:400 10px 'IBM Plex Mono';color:#64748b;` +
      `margin-left:6px">${band.свой ? "черновик" : "из игры"}</span></div>`);
    blk.insertAdjacentHTML("beforeend",
      `<div>бойцов на карте: ${fighters.length}` +
      (band.count != null ? ` · в записи ${band.count}` : "") + `</div>`);
    if (fighters.length) {
      blk.insertAdjacentHTML("beforeend",
        `<div style="color:#64748b">${fighters.slice(0, 6)
          .map(u2 => u2.name || u2.id).join(", ")}` +
        (fighters.length > 6 ? ` и ещё ${fighters.length - 6}` : "") + `</div>`);
    }
    //: ВРАЖДА — БИТАМИ, И КАЖДЫЙ ПОДПИСАН СЛОВАМИ. Числом 0x4F человек
    //: не оперирует, галочками — оперирует.
    for (const [key2, label] of WAR_BITS) {
      const rowEl = document.createElement("label");
      rowEl.style.cssText = "display:flex;align-items:center;gap:6px;" +
        (band.player ? "opacity:.5" : "cursor:pointer");
      const checkBox = document.createElement("input");
      checkBox.type = "checkbox";
      checkBox.checked = Boolean(band[key2]);
      checkBox.disabled = Boolean(band.player);
      checkBox.onchange = () => saveIt(band, { [key2]: checkBox.checked });
      rowEl.append(checkBox, Object.assign(document.createElement("span"),
        { textContent: label }));
      blk.appendChild(rowEl);
    }
    if (band.player) {
      blk.insertAdjacentHTML("beforeend",
        `<div style="color:#92400e">отряд игрока не правим: это сам ` +
        `герой со спутниками</div>`);
    }
    //: ЗОНЫ — ПО ЧЕТЫРЕ ЧИСЛА КАЖДАЯ, И ЭТО РАЗНЫЕ БАЙТЫ ЗАПИСИ.
    //: Появление решает, где отряд встанет при входе на карту; гуляние
    //: — куда он забредёт потом.
    for (const [key2, label] of [["zone", "зона появления"],
                                   ["roam", "зона гуляния"]]) {
      const z2 = band[key2] || {};
      const line = document.createElement("div");
      line.style.cssText = "display:flex;flex-direction:column;gap:3px";
      line.insertAdjacentHTML("beforeend",
        `<div style="font:600 11px 'IBM Plex Sans';color:#0f172a">` +
        `${label}</div>`);
      const fields = document.createElement("div");
      fields.style.cssText = "display:flex;gap:4px";
      for (const nm of ["row_from", "row_to", "col_from", "col_to"]) {
        const field = document.createElement("input");
        field.type = "number";
        field.min = "0";
        field.max = nm.startsWith("row") ? "255" : "159";
        field.value = String(z2[nm] ?? 0);
        field.title = nm;
        field.disabled = Boolean(band.player);
        field.style.cssText = "width:100%;min-width:0;" +
          "font:11px 'IBM Plex Mono'";
        field.onchange = () => saveIt(band,
          { [key2]: { [nm]: Number(field.value) || 0 } });
        fields.appendChild(field);
      }
      line.appendChild(fields);
      line.insertAdjacentHTML("beforeend",
        `<div style="color:#64748b">строки от/до, столбцы от/до</div>`);
      blk.appendChild(line);
    }
    blk.insertAdjacentHTML("beforeend", bandKeepsCells(band)
      ? `<div style="color:#166534">клетки бойцов в силе: этот отряд ` +
        `движок по зоне не рассыпает</div>`
      : `<div style="color:#92400e">бит keep_cells снят: при входе на ` +
        `карту движок рассыплет бойцов по зоне появления, а записанные ` +
        `клетки перепишет</div>`);
    //: УБРАТЬ ОТРЯД. Ручка DELETE на сервере была всегда — из UI её не
    //: звал никто, и отряды-сироты «бойцов 0» копились навсегда: бойцов
    //: удалили, запись осталась, и вычистить её было нечем. Кнопка
    //: только у своего (draft) отряда: паковый приходит из игры, его
    //: записи здесь не правятся. С бойцами отряд не убираем — бойцы
    //: остались бы сиротами без записи стороны.
    if (band.свой && !band.player) {
      const removeBtn = document.createElement("button");
      removeBtn.textContent = `Убрать отряд ${band.side}`;
      removeBtn.style.cssText = "padding:6px;cursor:pointer;" +
        "border-radius:5px;border:1px solid #dc2626;background:#fff;" +
        "color:#b91c1c;font:600 11px 'IBM Plex Sans'";
      removeBtn.onclick = async () => {
        const fighters2 = bandFighters(band.side);
        if (fighters2.length) {
          status(`в отряде ${band.side} ещё ${fighters2.length} ` +
                 plural(fighters2.length, ["боец", "бойца", "бойцов"]) +
                 ` — сначала уберите их (Del по бойцу на «Сущ-ва»)`);
          return;
        }
        const resp = await fetch(
          `${API}/maps/${state.map}/warbands/${band.side}`,
          { method: "DELETE" })
          .then(x => x.json()).catch(() => ({ ok: false, note: "сеть" }));
        if (resp.ok) {
          state.отряд = null;
          await openMap(state.map);
          showScreen("1j");
        }
        //: итог ПОСЛЕ перечитывания — иначе его съест статус открытьКарту
        status(resp.ok ? `отряд ${band.side} убран`
                     : (resp.note || "не вышло"));
      };
      blk.appendChild(removeBtn);
    }
    insertOwn(rightCol, blk, "панель-отряда", rightCol.firstElementChild);
  }

  function renderBandList() {
    if (!bandZone) return;
    bandZone.replaceChildren();
    bandZone.style.maxHeight = "min(56vh, 520px)";
    bandZone.style.overflowY = "auto";
    const bands = mapBands();
    if (!bands.length) {
      bandZone.insertAdjacentHTML("beforeend",
        `<div style="padding:8px;font:12px 'IBM Plex Mono';color:#64748b">` +
        `отрядов на этой карте нет — заведите первого бойца на вкладке ` +
        `«Сущ-ва», отряд появится вместе с ним</div>`);
      return;
    }
    for (const band of bands) {
      const fighters = bandFighters(band.side).length;
      const isPicked = Number(band.side) === state.отряд;
      const isHostile = WAR_BITS.some(([k2]) => band[k2]);
      const rowEl = document.createElement("div");
      rowEl.style.cssText =
        "display:flex;align-items:center;gap:8px;padding:6px 8px;" +
        "margin:2px 4px;border-radius:7px;cursor:pointer;" +
        "font:12px 'IBM Plex Mono';border:1.5px solid " +
        (isPicked ? "#2563eb" : "#e2e8f0") +
        (band.свой ? ";background:#fffbeb" : "");
      rowEl.textContent =
        `${band.side} · бойцов ${fighters} · ` +
        (band.player ? "игрок" : isHostile ? "вражий" : "мирный") +
        (band.свой ? " · draft" : "");
      rowEl.onclick = () => {
        state.отряд = isPicked ? null : Number(band.side);
        renderBandList();
        bandPanel(mapBands()
          .find(obj => Number(obj.side) === state.отряд));
        stage?.рисуйПоверх();
        status(state.отряд == null ? "выбор снят"
          : `отряд ${band.side}: бойцов на карте ${fighters}` +
            (isHostile ? ", враждебен" : ", мирный"));
      };
      bandZone.appendChild(rowEl);
    }
  }
  renderBandList();
  bandPanel(mapBands().find(obj => Number(obj.side) === state.отряд));
  stage?.рисуйПоверх();
}

// 1k — ДЕРЕВНЯ: поселение карты, его постройки, должности и числа
//: ПОСЕЛЕНИЕ В РЕДАКТОРЕ НЕ СУЩЕСТВОВАЛО ВОВСЕ. Ни ручки, ни экрана —
//: при том, что деревня это половина игры: постройки, должности,
//: прилавки, казна, ополчение. Запись поселения лежит не в проекте, а в
//: GAME.<мир>, и читается сборкой; править её можно только слоем
//: `editor_village` — как кучи и отряды.
//:
//: ЧИСЛА ПОДПИСАНЫ ПРАВДОЙ, А НЕ ИМЕНЕМ КЛЮЧА. Соблазн велик: ключ
//: `treasury` называется казной — и казной НЕ ЯВЛЯЕТСЯ (это счётчик
//: занятий воеводы, +0x0C). Деньги лежат в `owned`. Подписи приходят с
//: сервера, где живёт разбор, чтобы экран не сочинял своих.
const VILLAGE_EDITABLE = [
  ["owned", "казна владения"],
  ["owner", "чьё владение"],
  ["wealth", "богатство"],
  ["status", "статус"],
  ["flags", "признаки"],
  ["slots_a", "мест A"],
  ["slots_b", "мест B"],
  ["treasury", "счётчик воеводы"],
];
const VILLAGE_READONLY = [
  ["index", "номер записи"],
  ["side", "сторона деревни"],
  ["culture", "культура"],
  ["squad_places", "мест в отряде"],
  ["squad_people", "занято мест"],
  ["brew_timer", "часы варки"],
];
async function screen1k(card) {
  canonStrip(card);
  const stage = mountCanvas(card, {
    хватать: CATCH["1k"],
    //: постройки деревни подсвечиваем на карте: у записи постройки есть
    //: village_slot, и по нему видно, какая из них чья
    поверх: (brush, kindOf) => {
      const isPicked = state.постройка;
      if (isPicked == null) return;
      for (const obj of state.mapState?.objects?.records || []) {
        if (Number(obj.village_slot) !== Number(isPicked)) continue;
        brush.strokeStyle = "#f59e0b";
        brush.lineWidth = 2 / kindOf.zoom;
        brush.strokeRect((obj.x - 40) * K, (obj.y - 40) * K, 80 * K, 80 * K);
      }
      brush.lineWidth = 1;
    },
  });
  const worldNum = state.слотГероя?.world ?? state.world ?? 0;
  const obj = await api(`/maps/${state.map}/village?world=${worldNum}`);
  //: подписи макета говорят про существ — на этом экране они врут
  for (const el of card.querySelectorAll("span,div")) {
    if (el.childElementCount !== 0) continue;
    const pt = el.textContent.trim();
    if (pt === "Существа") el.textContent = "Деревня";
    else if (pt === "Бестиарий") el.textContent = "Постройки";
    else if (/^\d+\s+(пород|вид)/.test(pt)) el.textContent = "";
    else if (/^Жители пака/.test(pt)) el.textContent = "";
  }
  const buildZone = zoneOf(card, "список-построек");
  //: ЯКОРЬ ПЕРЕСТАВАЛ НАХОДИТЬ САМ СЕБЯ. Он искал «Юнит · <одно слово>»,
  //: а первая же перерисовка без выбора писала сюда «Юнит · не выбран» —
  //: два слова. Со следующего показа экрана заголовок не находился ВОВСЕ,
  //: и карточка навсегда замирала на «не выбран», хотя строки под ней
  //: исправно менялись (поймано живьём: «Житель · Славяне · мужчина» в
  //: строках при «не выбран» в заголовке). Берём всё, что начинается с
  //: «Юнит ·», и считаем промах, если не нашли.
  const unitTitle = [...card.querySelectorAll("span")]
    .find(el => el.childElementCount === 0 &&
                /^Юнит\s*·/.test(el.textContent.trim()));
  if (!unitTitle) state.промахи.push("карточка юнита: заголовок");
  const rightCol = unitTitle?.closest(
    '[style*="width:320px"],[style*="width: 320px"]') || card;

  if (!obj.ok) {
    buildZone?.replaceChildren();
    buildZone?.insertAdjacentHTML("beforeend",
      `<div style="padding:8px;font:12px 'IBM Plex Mono';color:#64748b">` +
      `${obj.note || "поселения нет"}</div>`);
    insertOwn(rightCol, Object.assign(document.createElement("div"), {
      style: "padding:10px;font:11px 'IBM Plex Mono';color:#64748b",
      textContent: obj.note || "на этой карте поселения нет",
    }), "панель-деревни", rightCol.firstElementChild);
    return;
  }
  const villageRec = obj.village;
  const captions = obj.notes || {};
  const namesOf = obj.names || {};
  const draftRec = obj.draft || {};

  async function saveIt(patchBody) {
    const resp = await api(`/maps/${state.map}/village`, "POST",
                        { patch: patchBody });
    const msg = resp.note || (resp.ok ? "готово" : "не вышло");
    if (resp.ok) { await openMap(state.map); showScreen("1k"); }
    //: статус ПОСЛЕ перечитывания: открытьКарту кончается своим
    status(msg);
  }

  function villagePanel() {
    const blk = document.createElement("div");
    blk.style.cssText = "padding:10px;font:11px 'IBM Plex Mono';" +
      "color:#334155;display:flex;flex-direction:column;gap:8px;" +
      "max-height:min(70vh,640px);overflow-y:auto";
    blk.insertAdjacentHTML("beforeend",
      `<div style="font:600 13px 'IBM Plex Sans';color:#0f172a">` +
      `Поселение ${villageRec.index} · сторона ${villageRec.side}</div>`);
    //: ДОЛЖНОСТИ — ИМЕНАМИ. В записи это номера юнитов в таблице мира;
    //: «369» человеку не говорит ничего, «Трюгви Кожаные штаны» —
    //: говорит. Правкой не даём: на этих номерах держится маршрутизация
    //: разговоров (обработчик 30 спрашивает про должность).
    const offices = (villageRec.officials || []).map((n2, i) =>
      `${i + 1}. ${namesOf[String(n2)] || `житель ${n2}`}` +
      (Number(n2) === Number(villageRec.master) ? " · мастер" : ""));
    blk.insertAdjacentHTML("beforeend",
      `<div><div style="font:600 11px 'IBM Plex Sans';color:#0f172a">` +
      `Должностные лица</div>` +
      (offices.length
        ? offices.map(sp => `<div>${sp}</div>`).join("")
        : `<div style="color:#64748b">нет</div>`) +
      `<div style="color:#64748b;margin-top:2px">${captions.officials ||
        ""}</div></div>`);
    //: ПРАВИМЫЕ ЧИСЛА. У каждого — подпись с сервера, где живёт разбор.
    for (const [key2, nm] of VILLAGE_EDITABLE) {
      const rowEl = document.createElement("div");
      rowEl.style.cssText = "display:flex;flex-direction:column;gap:2px";
      const head2 = document.createElement("div");
      head2.style.cssText = "display:flex;align-items:center;gap:6px";
      const ownVal = draftRec[key2];
      const field = document.createElement("input");
      field.type = "number";
      field.value = String(ownVal ?? villageRec[key2] ?? 0);
      field.style.cssText = "width:96px;font:11px 'IBM Plex Mono'";
      field.onchange = () => saveIt({ [key2]: Number(field.value) || 0 });
      head2.append(Object.assign(document.createElement("span"),
        { textContent: nm, style: "width:120px;color:#64748b;flex:none" }),
        field);
      if (ownVal !== undefined) {
        head2.appendChild(Object.assign(document.createElement("span"), {
          textContent: "правка", style: "color:#b45309" }));
      }
      rowEl.appendChild(head2);
      if (captions[key2]) {
        rowEl.insertAdjacentHTML("beforeend",
          `<div style="color:#64748b;line-height:1.35">${captions[key2]}</div>`);
      }
      blk.appendChild(rowEl);
    }
    //: ЧИСЛА ТОЛЬКО ДЛЯ ПОКАЗА — и сказано, почему их нельзя править.
    for (const [key2, nm] of VILLAGE_READONLY) {
      if (villageRec[key2] == null) continue;
      blk.insertAdjacentHTML("beforeend",
        `<div style="display:flex;gap:6px"><span style="width:120px;` +
        `color:#64748b;flex:none">${nm}</span><span>${villageRec[key2]}` +
        `</span></div>` +
        (captions[key2]
          ? `<div style="color:#94a3b8;margin:-6px 0 0 126px">` +
            `${captions[key2]}</div>` : ""));
    }
    insertOwn(rightCol, blk, "панель-деревни", rightCol.firstElementChild);
  }

  function renderBuildings() {
    if (!buildZone) return;
    buildZone.replaceChildren();
    buildZone.style.maxHeight = "min(60vh, 560px)";
    buildZone.style.overflowY = "auto";
    const buildings2 = villageRec.buildings || [];
    const isBuiltFlag = buildings2.filter(p2 => p2.built).length;
    buildZone.insertAdjacentHTML("beforeend",
      `<div style="padding:6px 8px;font:11px 'IBM Plex Sans';color:#334155">` +
      `Мест ${buildings2.length}, построено ${isBuiltFlag}. Первые семь — ` +
      `особые: дом старосты, знахарь, купец, кузня, казарма и прочие ` +
      `должностные дворы.</div>`);
    for (const p2 of buildings2) {
      const ownVal = (draftRec.buildings || {})[String(p2.slot)] || {};
      const isStanding = ownVal.built ?? p2.built;
      const rowEl = document.createElement("div");
      rowEl.style.cssText =
        "display:flex;align-items:center;gap:6px;padding:5px 8px;" +
        "margin:2px 4px;border-radius:7px;font:12px 'IBM Plex Mono';" +
        "border:1.5px solid " +
        (Number(state.постройка) === Number(p2.slot) ? "#2563eb" : "#e2e8f0") +
        (Object.keys(ownVal).length ? ";background:#fffbeb" : "");
      const checkBox = document.createElement("input");
      checkBox.type = "checkbox";
      checkBox.checked = Boolean(isStanding);
      checkBox.title = "построена";
      checkBox.style.flex = "none";
      checkBox.onclick = ev => ev.stopPropagation();
      checkBox.onchange = () => saveIt(
        { buildings: { [String(p2.slot)]: { built: checkBox.checked } } });
      rowEl.append(checkBox, Object.assign(document.createElement("span"), {
        textContent: `${p2.slot} · ${p2.name}` +
          (p2.special ? " · особая" : "") +
          (isStanding ? ` · состояние ${ownVal.state ?? p2.state}` : " · нет"),
        style: "flex:1;min-width:0;cursor:pointer",
      }));
      rowEl.onclick = () => {
        state.постройка = Number(state.постройка) === Number(p2.slot)
          ? null : Number(p2.slot);
        renderBuildings();
        stage?.рисуйПоверх();
        status(state.постройка == null ? "выбор снят"
          : `${p2.name}: слот ${p2.slot}, состояние ${p2.state}`);
      };
      buildZone.appendChild(rowEl);
    }
  }
  renderBuildings();
  villagePanel();
  stage?.рисуйПоверх();
}

// 1g — клады: клик кладёт кучу, список слева живой
async function screen1g(card) {
  //: КАТАЛОГ ВЕЩЕЙ НУЖЕН СРАЗУ. Панель кучи переводит ссылки записей
  //: («instance:208:…») в имена и значки по нему; загружая его лениво,
  //: первый показ выдавал сырые ссылки вместо «Богатырский меч».
  if (!state.вещи) state.вещи = await api("/catalog/items");
  const stage = mountCanvas(card, {
    хватать: CATCH["1g"],
    //: ПЕРЕНОС КУЧИ ПРОСТЫМ КЛИКОМ УБРАН. Он жил здесь и был четвёртым
    //: жестом переноса в редакторе: выбранная куча уезжала в ЛЮБУЮ
    //: точку, куда пришёлся следующий щелчок, — то есть промах мимо
    //: неё увозил её куда попало, и отменить это можно было только
    //: Ctrl+Z. Возим удержанием, как всё остальное (ЛОВИТ["1g"]).
    click: async pt => {
      // СНАЧАЛА список() (он же и возможный сбой api('/pack') внутри
      // собрать()), ПОТОМ status() — иначе асинхронный провал переписывал
      // верный статус ошибкой «карта не собрана в пак» секунду спустя
      // (см. обновитьПанельКучи выше).
      //: ЩЕЛЧОК ПО УЖЕ ЛЕЖАЩЕЙ КУЧЕ ВЫБИРАЕТ ЕЁ, А НЕ КЛАДЁТ ВТОРУЮ
      //: СВЕРХУ. Прежде любой щелчок по холсту создавал новую кучу — в
      //: том числе прямо поверх существующей, и разложить их потом было
      //: нельзя: под курсором оказывались две в одной клетке.
      if (await pickOnCanvas(pt, stage, CATCH["1g"])) {
        refreshPilePanel(selectedOf("loot", "packLoot"));
        await list();
        return;
      }
      //: КЛИК ПО ПУСТОМУ МЕСТУ КУЧУ БОЛЬШЕ НЕ СОЗДАЁТ. Это был
      //: единственный экран, где инструмент не взводился: ЛЮБОЙ промах
      //: мимо кучи молча заводил новую с 25 монетами, и на карте
      //: копились кучи-сироты одних мискликов (на 63-й их лежало
      //: четыре). Теперь как на объектах и существах: сначала «Новая
      //: куча» (взводит), потом клик; клавиша N кладёт в клетку курсора
      //: сразу — явный жест, а не промах.
      if (state.place?.kind !== "loot") {
        status("пустое место: класть кучу — кнопка «Новая куча» и клик, " +
               "или клавиша N в клетку курсора; клик по лежащей куче " +
               "выбирает её");
        return;
      }
      const cellRec = cellAt(pt);
      const id = nextPileId();
      const resp = await api(`/maps/${state.map}/loot`, "POST", {
        id, patch: { id, on_floor: true, buried: false, money: 25,
                     items: [], details: [],
                     cell: { row: cellRec.row, col: cellRec.col } } });
      if (resp.ok) { await openMap(state.map); await list();
                  stage?.рисуй();
                  status(`клад ${cellRec.row}:${cellRec.col} · 25 монет · ` +
                         `тяните — двигать, состав — в панели справа`); }
    },
  });
  //: ЗОНА СПИСКА — САМЫЙ ТЕСНЫЙ КОНТЕЙНЕР СТРОК, а не самый вместительный.
  //: Брали узел с наибольшим числом детей, и им оказывалась колонка
  //: целиком: replaceChildren сносил вместе со списком инспектор кучи с
  //: кнопками «Дубль» и «Убрать» — они пропадали с экрана.
  const pileZone = zoneOf(card, "список-куч");

  //: КУЧИ ПАКА И ЧЕРНОВИКА В ОДНОМ СПИСКЕ. Слева в макете нарисованы
  //: pile_3…pile_11 и «сундук · slot 89» — это кучи собранной карты;
  //: черновые (pile_new_*) живут в scenario.json. Показываем оба вида,
  //: как макет и обещает.
  async function buildPack() {
    const packData = await api(`/maps/${state.map}/pack`);
    const piles = ((packData.ok && packData.loot) || []).map(k2 => ({ ...k2, draft: false }));
    //: ЧЕРНОВИК ПОБЕЖДАЕТ ПАК. Одна и та же куча живёт в обоих: своя
    //: заведена в scenario.json, а после Build её копия лежит и в паке.
    //: Показывая обе, список двоился, а панель рисовала ПАКОВУЮ — то
    //: есть вчерашнюю: положишь вещь, а состав не меняется, хотя на
    //: диске всё записано. Черновик — редактируемая правда, пак —
    //: снимок последней сборки.
    //:
    //: И `items` у черновой кучи оставляем СПИСКОМ. Прежде здесь стояло
    //: `items: (к.items || []).length`, и панель, взяв число вместо
    //: массива, показывать в куче было нечего.
    const draftList = (state.mapState?.draft?.editor_loot_add || [])
      .map(k2 => ({ ...k2, draft: true }));
    const mine = new Set(draftList.map(k2 => k2.id));
    return [...piles.filter(k2 => !mine.has(k2.id)), ...draftList];
  }
  //: сколько вещей в куче: у паковой это число (items), у черновой —
  //: сам список; спрашиваем одинаково
  function goodsInPile(pile) {
    if (Array.isArray(pile.items)) return pile.items.length;
    return Number(pile.items) || 0;
  }
  async function list() {
    if (!pileZone) return;
    const everything = await buildPack();
    const mode = state.lootTab || "все";
    const visibleOnes = everything.filter(k2 => mode === "все" ? true
      : mode === "тайники" ? k2.buried : !k2.buried);
    pileZone.replaceChildren();
    pileZone.style.maxHeight = "min(56vh, 520px)";
    pileZone.style.overflowY = "auto";
    for (const pile of visibleOnes) {
      const rowEl = document.createElement("div");
      rowEl.style.cssText =
        "display:flex;align-items:center;gap:8px;padding:6px 8px;" +
        "border-radius:7px;cursor:pointer;font:12px 'IBM Plex Mono';" +
        "border:1.5px solid " +
        (isChosen(pile) ? "#2563eb" : "#e2e8f0") +
        (pile.draft ? ";background:#fffbeb" : "");
      //: КЛЕТКА В СТРОКЕ. По одному id кучу на карте не найти; клетка —
      //: единственное, что связывает строку списка с местом на холсте.
      rowEl.textContent =
        `${pile.id}` +
        (pile.cell ? ` · ${pile.cell.row}:${pile.cell.col}` : "") +
        ` · ${pile.money || 0} мон. · ` +
        `${goodsInPile(pile)} вещ.` + (pile.buried ? " · тайник" : "") +
        (pile.draft ? " · draft" : "");
      //: ГОНКА СТАТУСА. список() ждёт собрать() → api('/pack'), а на
      //: несобранной карте это 400: api() САМА пишет в статус-строку
      //: «✗ карта не собрана в пак» (общий побочный эффект на любой
      //: неудаче). Раньше верный подсказ «куча выбрана…» ставили ДО
      //: список(), и асинхронный провал pack переписывал его секунду
      //: спустя — человек видел ошибку про нечто, чего не делал. Строка
      //: statusа теперь ставится ПОСЛЕДНЕЙ, после того как список()
      //: (и его возможный провал) уже случился.
      rowEl.onclick = async () => {
        //: повторный щелчок по той же строке снимает выбор
        if (isChosen(pile)) clearPick();
        else choose(pile.draft ? "loot" : "packLoot", pile);
        const isChosenOne = selectedOf("loot", "packLoot");
        if (isChosenOne) refreshPilePanel(isChosenOne);
        await list();
        stage?.рисуй();
        status(isChosenOne
          ? `куча ${pile.id} выбрана — держите ЛКМ на ней, чтобы возить; ` +
            `Del уберёт`
          : "выбор снят");
      };
      pileZone.appendChild(rowEl);
    }
    // счётчики его фильтров: «кучи · 8», «тайники · 5»
    for (const el of card.querySelectorAll("div,span")) {
      const pt = el.textContent.trim();
      if (el.childElementCount === 0 && /^(кучи|тайники)\s*·\s*\d+$/.test(pt)) {
        const nm = pt.split("·")[0].trim();
        const number2 = nm === "тайники"
          ? everything.filter(k2 => k2.buried).length
          : everything.filter(k2 => !k2.buried).length;
        el.textContent = `${nm} · ${number2}`;
      }
      if (el.childElementCount === 0 && /^\d+\s*\+\s*\d+\s*draft$/.test(pt)) {
        el.textContent = `${everything.filter(k2 => !k2.draft).length} + ` +
                        `${everything.filter(k2 => k2.draft).length} draft`;
      }
    }
  }
  toggleOf(card, ["все", "кучи", "тайники"], state.lootTab || "все",
          label => { state.lootTab = label; list(); });
  //: «Новая куча · N» — ВЗВОДИТ постановку, как каталог на объектах и
  //: породы на существах: следующий клик по карте кладёт кучу ТУДА.
  //: Прежде кнопка сразу создавала кучу в середине видимой карты, а
  //: любой клик по пустому месту создавал ещё одну — кучи плодились от
  //: мискликов. Заявленная подсказкой клавиша N при этом не была
  //: подключена вовсе — теперь она кладёт кучу в клетку курсора (см.
  //: общий обработчик клавиш).
  bindTo(organOf(card, "Новая куча", false), () => {
    state.place = { kind: "loot" };
    stage?.рисуйПоверх();
    status("кладу кучу: кликните по карте, куда её положить · " +
           "Esc — выключить");
  });
  //: ПАНЕЛЬ КУЧИ СПРАВА была вписана в макет намертво («pile_7», «250»,
  //: «141:96») — выбор другой кучи её не трогал. Состав (список вещей с
  //: иконками) не трогаем: и в паке, и в драфте до нас доезжает только
  //: ЧИСЛО вещей (собрать() сводит items к длине), самих вещей клиент
  //: не видит без отдельного запроса — показывать нечего, придумывать
  //: не будем.
  const pileTitle = [...card.querySelectorAll("span")]
    .find(el => el.childElementCount === 0 &&
                /^Куча\s*·\s*\S+$/.test(el.textContent.trim()));
  const moneyRow = rowValue(card, "Деньги");
  const pileCellRow = rowValue(card, "Клетка");
  const buriedRow = [...card.querySelectorAll("span")]
    .find(el => el.childElementCount === 0 && el.textContent.trim() === "Тайник")
    ?.nextElementSibling;
  //: ЧУЖОЙ ИНВЕНТАРЬ ГАСИМ СРАЗУ, А НЕ ПРИ ВЫБОРЕ КУЧИ. Блок «Состав ·
  //: items + details» (Панцирь, Шелом, Зелье живой воды, Рунный камень)
  //: — макет: до первого щелчка по куче он висел как её содержимое, и
  //: человек читал его как правду о клада, которого ещё и не выбрал.
  const hideMockContents = () => {
    const head2 = [...card.querySelectorAll("div,span")]
      .find(el => el.childElementCount === 0 &&
                 /^Состав\s*·\s*items/.test(el.textContent.trim()));
    if (!head2) return;
    const nest = head2.closest("div");
    for (let el = nest; el; el = el.nextElementSibling) {
      if (el !== nest && !/class:\d/.test(el.textContent || "")) break;
      el.style.display = "none";
    }
  };
  hideMockContents();
  function refreshPilePanel(pile) {
    if (pileTitle) pileTitle.textContent = `Куча · ${pile.id}`;
    if (moneyRow) moneyRow.textContent = String(pile.money || 0);
    if (pileCellRow && pile.cell)
      pileCellRow.textContent = `${pile.cell.row}:${pile.cell.col}`;
    if (buriedRow) {
      const checkBox = buriedRow.querySelector("span");
      if (checkBox) {
        checkBox.style.background = pile.buried ? "#2563eb" : "transparent";
        checkBox.style.border = pile.buried ? "none" : "1.5px solid #cbd5e1";
        checkBox.textContent = pile.buried ? "✓" : "";
        checkBox.style.color = "#fff";
        checkBox.style.font = "700 10px monospace";
        checkBox.style.textAlign = "center";
        checkBox.style.lineHeight = "13px";
      }
    }
    //: ЧТО В КУЧЕ ЛЕЖИТ — И КАК ЭТО ПРАВИТЬ. Панель показывала деньги,
    //: клетку и тайник, а вещи — главное в кладе — не показывала вовсе:
    //: сервер отдавал одно число «items: 3». Сперва появился показ,
    //: теперь и правка: положить вещь из каталога, задать заряды
    //: боеприпасу, вынуть лишнее.
    //:
    //: Куча из ПАКА правится тем же слоем, что и всё остальное: патч
    //: ложится в scenario.json, а сборка кладёт его поверх (см.
    //: editor_loot_item на сервере). Своя куча живёт в том же файле
    //: целиком. Разницы для человека нет, и делать её незачем.
    //: «СОСТАВ · ITEMS + DETAILS» — ЧУЖОЙ ИНВЕНТАРЬ. Блок целиком из
    //: макета: Панцирь, Шелом, Зелье живой воды, Рунный камень — с
    //: классами и прочностью, будто это содержимое выбранной кучи. Живой
    //: слой его никогда не заполнял и показывал СВОЙ список ниже. Выходило
    //: два состава у одной кучи: настоящий (часто пустой) и выдуманный
    //: (всегда богатый) — и верили, разумеется, второму. Оттуда же были
    //: «битые значки»: картинки макета с относительными путями.
    //:
    //: Гасим его вместе с заголовком: правда о куче — в списке «В куче».
    const contentsHead = [...card.querySelectorAll("div,span")]
      .find(el => el.childElementCount === 0 &&
                 /^Состав\s*·\s*items/.test(el.textContent.trim()));
    if (contentsHead) {
      const nest = contentsHead.closest("div");
      for (let el = nest; el; el = el.nextElementSibling) {
        if (el !== nest && !/class:\d/.test(el.textContent || "")) break;
        el.style.display = "none";
      }
    }
    const spot = moneyRow?.closest("div")?.parentElement || card;
    const contentsEl = document.createElement("div");
    contentsEl.style.cssText = "margin:6px 0;font:11px 'IBM Plex Mono';" +
      "color:#334155";
    //: у кучи пака состав собран сервером (contents), у своей — лежит
    //: сырыми ссылками; сводим к одному виду по каталогу вещей
    const byRef = ref2 => {
      const m2 = /^(?:class|instance):(\d+)/.exec(String(ref2 || ""));
      return m2 ? (state.вещи?.items || [])
        .find(it => it.ref === `class:${m2[1]}`) : null;
    };
    const goods = pile.contents || (pile.items || []).map((sp, i) => {
      const it = byRef(sp) || {};
      return { ref: sp, name: it.name, icon: it.icon, price: it.price,
               count: (pile.details || [])[i]?.count };
    });
    //: ЧЕЙ ЭТО СОСТАВ — ВАЖНО. Своя куча показывает то, что правится
    //: прямо сейчас; куча из пака — снимок последней сборки, и правка
    //: ляжет патчем поверх. Молча их путать нельзя: человек иначе не
    //: понимает, почему число в списке и в панели разошлись.
    const ownPile = pile.draft || String(pile.id).startsWith("pile_new_");
    contentsEl.insertAdjacentHTML("beforeend",
      `<div style="font:600 12px 'IBM Plex Sans';margin-bottom:3px;` +
      `color:#0f172a">В куче · ${goods.length}` +
      `<span style="font:400 10px 'IBM Plex Mono';color:#64748b;` +
      `margin-left:6px">${ownPile ? "черновик" : "из пака"}</span></div>`);
    if (!goods.length) {
      contentsEl.insertAdjacentHTML("beforeend",
        `<div style="color:#64748b;margin-bottom:4px">вещей нет, ` +
        `только деньги</div>`);
    }
    //: ПОСЛЕ ПРАВКИ ВОЗВРАЩАЕМСЯ К ЧЕРНОВИКУ, А НЕ К ПАКУ. Куча живёт
    //: в двух местах: своя запись в scenario.json и её копия в паке от
    //: последней сборки. Правки идут в первую, а искали мы после них
    //: ВТОРУЮ (packLoot стоял первым в concat) — и панель показывала
    //: вчерашний состав: положишь вещь, статус говорит «теперь вещей
    //: 3», а в списке всё те же две. Черновик первым.
    const repaintAll = async () => {
      await openMap(state.map);
      const mine = (state.mapState?.draft?.editor_loot_add) || [];
      const isOwn = mine.find(k2 => k2.id === pile.id);
      const freshRec = isOwn || (state.packLoot || [])
        .find(k2 => k2.id === pile.id);
      if (freshRec) choose(isOwn ? "loot" : "packLoot", freshRec);
      stage?.рисуй();
      showScreen(state.screen);
    };
    goods.forEach((it, num) => {
      const rowEl = document.createElement("div");
      rowEl.style.cssText = "display:flex;align-items:center;gap:6px;" +
        "margin:2px 0";
      if (it.icon) {
        const img = document.createElement("img");
        img.src = it.icon; img.width = 22; img.height = 22;
        img.style.cssText = "image-rendering:pixelated;flex:none";
        img.onerror = () => img.remove();
        rowEl.appendChild(img);
      }
      rowEl.appendChild(Object.assign(document.createElement("span"), {
        textContent: `${it.name || it.ref}` +
          (it.count ? ` × ${it.count}` : "") +
          (it.price ? ` · ${it.price} монет` : ""),
        style: "flex:1;min-width:0",
      }));
      const takeOut = document.createElement("button");
      takeOut.textContent = "×";
      takeOut.title = "вынуть из кучи";
      takeOut.style.cssText = "flex:none;width:20px;height:20px;padding:0;" +
        "cursor:pointer;border:1px solid #cbd5e1;border-radius:4px;" +
        "background:#fff;color:#b91c1c;font:700 12px monospace";
      takeOut.onclick = async () => {
        const resp = await api(`/maps/${state.map}/loot`, "POST",
                            { id: pile.id, remove_item: num });
        const msg = resp.note || (resp.ok ? "вынуто" : "не вышло");
        if (resp.ok) await repaintAll();
        //: ПОСЛЕ перерисовки: открытьКарту внутри неё кончается своим
        //: status() и затирает итог (см. записатьПеренос)
        status(msg);
      };
      rowEl.appendChild(takeOut);
      contentsEl.appendChild(rowEl);
    });
    //: ПОЛОЖИТЬ ВЕЩЬ. Список тот же, что и у снаряжения юнита, но БЕЗ
    //: отбора по слоту: в кучу кладут что угодно, включая котомочное.
    const putIn = document.createElement("div");
    putIn.style.cssText = "display:flex;gap:4px;margin-top:6px";
    const choice = document.createElement("select");
    choice.style.cssText = "flex:1;min-width:0;font:11px 'IBM Plex Mono'";
    const howMany = document.createElement("input");
    howMany.type = "number"; howMany.min = "1"; howMany.value = "1";
    howMany.title = "заряды у боеприпаса";
    howMany.style.cssText = "width:56px;font:11px 'IBM Plex Mono'";
    const btn = document.createElement("button");
    btn.textContent = "Положить";
    btn.style.cssText = "flex:none;padding:3px 8px;cursor:pointer;" +
      "font:11px 'IBM Plex Sans'";
    const fillPanel = () => {
      const everything = state.вещи?.items || [];
      choice.innerHTML = everything.map(it =>
        `<option value="${it.ref}">${goodLabel(it)}</option>`).join("");
      refreshNumber();
    };
    const refreshNumber = () => {
      const it = (state.вещи?.items || []).find(x => x.ref === choice.value);
      //: заряды есть только у боеприпаса; у меча поле числа врало бы
      howMany.style.display = it?.ammo ? "" : "none";
    };
    choice.onchange = refreshNumber;
    btn.onclick = async () => {
      const it = (state.вещи?.items || []).find(x => x.ref === choice.value);
      const bodyNum = { id: pile.id, add_item: { ref: choice.value } };
      if (it?.ammo) bodyNum.add_item.count = Math.max(1, Number(howMany.value) || 1);
      const resp = await api(`/maps/${state.map}/loot`, "POST", bodyNum);
      const msg = resp.note || (resp.ok ? "положено" : "не вышло");
      if (resp.ok) await repaintAll();
      status(msg);
    };
    putIn.append(choice, howMany, btn);
    contentsEl.appendChild(putIn);
    fillPanel();
    insertOwn(spot, contentsEl, "состав-кучи");
  }
  const pickBox = selectedOf("loot", "packLoot");
  if (pickBox) refreshPilePanel(pickBox);
  //: ЛЕГЕНДА ВНИЗУ ДВАЖДЫ ВРАЛА. В макете стояло «Ctrl+клик —
  //: перенести» (Ctrl был ни при чём, переносил простой клик), потом
  //: правкой стало «клик — перенести» — а перенос кликом с тех пор
  //: убран совсем: он увозил кучу в любую точку промаха. Жест теперь
  //: один на весь редактор, о нём и пишем.
  const legendMove = [...card.querySelectorAll("span")]
    .find(el => el.childElementCount === 0 &&
                ["клик — перенести", "тяните — двигать"]
                  .includes(el.textContent.trim()));
  if (legendMove) legendMove.textContent = "тяните — двигать";
  wakeInspector(card, stage);
  await list();
}

// 1h — сборка: его карточка, живой запуск и настоящий статус
async function screen1h(card) {
  mountCanvas(card, { хватать: CATCH["1h"] });
  bindTo(organOf(card, "Build"), buildIt);
  bindTo(organOf(card, "Play"), playIt);
  paintBuildBadge();
  //: «3 правки поедут в пак» — считаем настоящие слои черновика. ДВА
  //: разных бага разом: (1) editor_loot лежит СЛОВАРЁМ {id: запись},
  //: а не массивом (как editor_units_add) — (словарь || []).length
  //: не падает, а тихо даёт undefined, и слой с реальными правками
  //: не считался вовсе; (2) регекс искал «N правки поедут» — ровно то,
  //: что стоит в макете, — а сама же строка ниже переписывала текст в
  //: «N слоёв правок поедут», и на ВТОРОМ заходе на экран регекс уже
  //: не находил свою же прошлую запись — счётчик застывал навсегда.
  const nonEmpty = (it) => Array.isArray(it) ? it.length > 0
    : Boolean(it) && typeof it === "object" && Object.keys(it).length > 0;
  const draftList = state.mapState?.draft || {};
  const patchCount = Object.keys(draftList).filter(k => nonEmpty(draftList[k])).length;
  for (const el of card.querySelectorAll("div,span")) {
    if (el.childElementCount === 0 &&
        /^\d+\s+(слоёв\s+)?правки?\s+поедут/.test(el.textContent.trim())) {
      el.textContent = `${patchCount} слоёв правок поедут в пак`;
    }
  }
  //: ТРИ СТРОКИ МАКЕТА ВЫДАВАЛИ СЕБЯ ЗА СОСТОЯНИЕ: «build: running · job
  //: b-142» (сборка, которой нет), «GET /build/status — каждые 500ms» и
  //: «после code 0: GET /play/23 → …» — записки разработчика про ручки
  //: API, да ещё и про чужую карту 23. Человек читает их как отчёт о
  //: СВОЕЙ сборке. Спрашиваем настоящий статус и пишем его словами.
  const build = await api("/build/status");
  const built = state.mapState?.pack?.built;
  for (const el of card.querySelectorAll("div,span")) {
    if (el.childElementCount !== 0) continue;
    const pt = el.textContent.trim();
    if (/^build:\s/.test(pt)) {
      el.textContent = !build.ok ? "состояние сборки неизвестно"
        : build.running
          ? `идёт сборка: карты ${(build.maps || []).join(", ") || "—"}`
          : build.code === 0 ? `последняя сборка прошла (карты ` +
              `${(build.maps || []).join(", ") || "—"})`
          : build.code == null ? "сборка ещё не запускалась"
          : `последняя сборка сорвалась, код ${build.code}`;
    }
    if (/^GET \/build\/status/.test(pt)) {
      el.textContent = built
        ? "пак этой карты собран — «Play» откроет её в игре"
        : "пак этой карты ещё не собран — сперва «Build»";
    }
    if (/^после code 0/.test(pt)) {
      el.textContent = "«Build» соберёт пак только этой карты; остальные " +
        "останутся как были";
    }
  }
}

// 1i — валидатор: его списки заменяются живыми находками
async function screen1i(card) {
  mountCanvas(card, { хватать: CATCH["1i"] });
  if (!state.map) return;
  const resp = await api(`/maps/${state.map}/validate`);
  if (!resp.ok) return;
  // НАЙТИ ОДИН РАЗ, ЗАПОМНИТЬ МЕТКОЙ. Карточка экрана — ОДИН И ТОТ ЖЕ
  // DOM-узел на все заходы (показать() не пересоздаёт его), а поиск
  // левого списка находок шёл по тексту-заглушке МАКЕТА («E-0», «Юнит
  // в глуши»). После первой перерисовки этот текст в левом списке
  // пропадает (там уже настоящие находки или «✓ карта чиста»), и на
  // ВТОРОМ заходе («Перепроверить» или повторный показать('1i'))
  // эвристика находила ту же подстроку только в ПРАВОЙ демо-карточке
  // (у неё текст статичный) и стирала её вместе с кнопками переходов —
  // валидатор становился непригоден после первого же использования.
  const findingsZone = zoneOf(card, "находки-валидатора");
  status(`проверка: ${resp.errors.length} ошибок, ` +
         `${resp.warnings.length} предупреждений`);
  // живой бейдж топбара и кнопка «Перепроверить» его макета
  // (она BUTTON — без него в селекторе кнопка оставалась мёртвой)
  for (const nodeEl of [...card.querySelectorAll("div,span,button")]) {
    const pt = nodeEl.textContent.trim();
    if (pt.startsWith("валидатор") && nodeEl.childElementCount === 0) {
      nodeEl.textContent =
        `валидатор: ${resp.errors.length} · ${resp.warnings.length}`;
    }
    // заголовок карточки «2 ошибки / 3 предупр.» и нижняя строка
    // «3 предупреждения» — та же болезнь, что и счётчик карт: цифры из
    // макета, никогда не пересчитывались, и противоречили соседнему
    // живому бейджу «валидатор: N · M» с другими числами. ≤1, А НЕ
    // ===0: у пилюль заголовка внутри лежит иконка lucide (octagon-
    // alert/triangle-alert) — со строгим «детей нет» они не находились
    // вовсе, и «2 ошибки»/«3 предупр.» из макета застревали навсегда.
    // ЗНАЧОК ВНУТРИ — ПИШЕМ В ТЕКСТОВЫЙ УЗЕЛ, НЕ В textContent: у пилюль
    // с иконкой (childElementCount===1) textContent="…" снёс бы саму
    // иконку lucide вместе с текстом (тот же урок, что у «Клеток воды»
    // на 1e — там тоже пишут в nodeValue, а не в textContent узла).
    const textNode2 = [...nodeEl.childNodes]
      .find(n => n.nodeType === 3 && n.nodeValue.trim());
    if (nodeEl.childElementCount <= 1 && /^\d+\s+ошиб/.test(pt)) {
      const fresh = `${resp.errors.length} ошибок`;
      if (textNode2) textNode2.nodeValue = fresh;
      else nodeEl.textContent = fresh;
    }
    if (nodeEl.childElementCount <= 1 && /^\d+\s+предупр/.test(pt)) {
      const fresh = `${resp.warnings.length} предупреждений`;
      if (textNode2) textNode2.nodeValue = fresh;
      else nodeEl.textContent = fresh;
    }
    if (pt === "Перепроверить") {
      const aim = nodeEl.closest("button") ||
        (nodeEl.parentElement?.childElementCount <= 3
          ? nodeEl.parentElement : nodeEl);
      aim.style.cursor = "pointer";
      aim.onclick = (ev) => { ev?.stopPropagation?.();
                               showScreen("1i"); };
    }
    // «На холсте» / «Открыть в Существах» — переходы к найденному
    if (pt === "На холсте" || pt.startsWith("Открыть в")) {
      const aim = nodeEl.closest("button") || nodeEl;
      aim.style.cursor = "pointer";
      aim.onclick = (ev) => {
        ev?.stopPropagation?.();
        const firstOne = (resp.errors[0] || resp.warnings[0] || "");
        const spot = /\((\d+),(\d+)\)/.exec(firstOne);
        if (spot) {
          status(`находка в клетке ${spot[1]}:${spot[2]}`);
        }
        showScreen(pt === "На холсте" ? "1d" : "1f");
      };
    }
  }
  //: КАРТОЧКА НАХОДКИ СПРАВА БЫЛА ЧИСТЫМ МАКЕТОМ: «E-01 · Юнит в глуши,
  //: unit_new_2 · скелет, клетка 34:132, В игре юнит застрянет в стене» —
  //: на КАЖДОЙ карте, включая чистую. Человек читает её как разбор своей
  //: находки и идёт чинить то, чего нет. Заполняем её выбранной строкой,
  //: а на чистой карте честно гасим.
  const allFindings = [...resp.errors, ...resp.warnings];
  const detail = (line, level) => {
    //: заголовок карточки — «которая из скольких», а уровень уже написан
    //: на пилюле рядом: два одинаковых слова подряд читаются как ошибка
    const at = allFindings.indexOf(line);
    const label = [...card.querySelectorAll("div,span")]
      .find(el => el.childElementCount === 0 &&
                  el.textContent.trim() === "Сущность");
    const box = label?.parentElement?.parentElement?.parentElement;
    if (!box) return;
    const valueOf = name_ => {
      const own = [...box.querySelectorAll("div,span")]
        .find(el => el.childElementCount === 0 &&
                    el.textContent.trim() === name_);
      return own?.nextElementSibling
        || [...(own?.parentElement?.children || [])].find(el => el !== own);
    };
    const head2 = [...box.querySelectorAll("div,span")]
      .find(el => el.childElementCount === 0 && /^E-\d|^Находка|^Ошибка|^Предупр/
        .test(el.textContent.trim()));
    const tail = [...box.querySelectorAll("div,span")]
      .find(el => el.childElementCount === 0 && el.textContent.trim().length > 24
                  && !el.textContent.includes("·"));
    //: пилюля уровня рядом с заголовком тоже макетная — на предупреждении
    //: она кричала «ошибка»
    const pill = [...box.querySelectorAll("div,span")]
      .find(el => el.childElementCount <= 1 &&
                  /^(ошибка|предупр\w*)$/i.test(el.textContent.trim()));
    if (pill) {
      const own = [...pill.childNodes].find(n => n.nodeType === 3);
      const word = !line ? "чисто" : level === "err" ? "ошибка" : "предупреждение";
      if (own) own.nodeValue = word; else pill.textContent = word;
      pill.style.color = !line ? "#16a34a" : level === "err" ? "#dc2626" : "#d97706";
    }
    if (!line) {
      if (head2) head2.textContent = "Находок нет";
      if (tail) tail.textContent = "Карта проверку прошла: ни ошибок, ни " +
        "предупреждений.";
      for (const nm of ["Сущность", "Клетка", "Источник"]) {
        const own = valueOf(nm);
        if (own) own.textContent = "—";
      }
      return;
    }
    const who = /^([\w.:-]+):/.exec(line);
    const spot = /\((\d+)\s*,\s*(\d+)\)|\b(\d+):(\d+)\b/.exec(line);
    if (head2) {
      head2.textContent = allFindings.length > 1
        ? `Находка ${at + 1} из ${allFindings.length}`
        : "Находка";
    }
    if (tail) tail.textContent = line;
    const pairs = { "Сущность": who ? who[1] : "—",
                    "Клетка": spot ? (spot[1] ? `${spot[1]}:${spot[2]}`
                                              : `${spot[3]}:${spot[4]}`) : "—",
                    "Источник": "проверка карты" };
    for (const [nm, val] of Object.entries(pairs)) {
      const own = valueOf(nm);
      if (own) own.textContent = val;
    }
  };
  if (!findingsZone) return;
  findingsZone.replaceChildren();
  function rowEl(txt, paintColor, line, level) {
    const el = document.createElement("div");
    el.style.cssText = "padding:6px 8px;margin:3px 0;border-radius:6px;" +
      `font:11.5px 'IBM Plex Sans';background:${paintColor}12;` +
      `border:1px solid ${paintColor}44;color:#0f172a` +
      (line ? ";cursor:pointer" : "");
    el.textContent = txt;
    if (line) el.onclick = () => { detail(line, level); status(txt); };
    findingsZone.appendChild(el);
  }
  if (!resp.errors.length && !resp.warnings.length) {
    rowEl("✓ карта чиста", "#16a34a");
  }
  for (const e3 of resp.errors) rowEl("✗ " + e3, "#dc2626", e3, "err");
  for (const w of resp.warnings) rowEl("⚠ " + w, "#d97706", w, "warn");
  //: карточка сразу показывает первую находку — иначе она осталась бы
  //: макетной до первого щелчка
  detail(resp.errors[0] || resp.warnings[0] || "",
         resp.errors.length ? "err" : "warn");
}

// ── СОБЫТИЯ: сюжет-панель (диалоги, тексты, ворота M_QUEST) ─────────────
//
//: ПОДПИСЬ ДИАЛОГА В СПИСКЕ. Полторы сотни строк, и своих среди них
//: три: без пометки собственный квест ищется глазами по всему списку.
//: Диалог без номера в сборку не включён — его юниту не назначить, и
//: это надо говорить прямо, а не отдавать пустое место.
function dialogLabel(d2) {
  return `${d2.number ?? "—"} · ${d2.name}` +
    (d2.own ? "  ✎ свой" : "") +
    (d2.number == null ? "  (не в сборке)" : "");
}
//: СПИСОК ДИАЛОГОВ ОДИН НА РЕДАКТОР. Сюжет общий для всех карт, читать
//: его на каждую перерисовку панели незачем — берём один раз и обновляем
//: там, где сами же его меняем (завели диалог, убрали, скомпилировали).
async function ensureDialogs() {
  if (state.диалоги) return state.диалоги;
  const sp = await api("/story");
  state.диалоги = sp.ok ? sp.dialogs : [];
  return state.диалоги;
}
function dialogNameOf(number) {
  return (state.диалоги || []).find(d2 => d2.number === Number(number))?.name;
}
//: Отряды карты для условия «карта зачищена»: номер отряда редактор
//: считает сам (server.py _squad_index), человеку остаётся выбрать, чей
//: разгром закрывает задание. Свой отряд игрока в счёт не идёт.
function hostileBands() {
  return mapBands().filter(band => !band.player).map(band => ({
    side: Number(band.side),
    label: `сторона ${band.side} · ${bandFighters(band.side).length} бойц.` +
      (band.on_player ? " · враждебный" : " · мирный"),
  }));
}
async function storyPanel() {
  const sp = await api("/story");
  if (!sp.ok) return;
  state.диалоги = sp.dialogs;          // общий кэш имён разговоров
  panelEl("События — диалоги сюжета", win => {
    const head = document.createElement("div");
    head.style.cssText = "display:flex;gap:8px;margin-bottom:8px";
    const sieve = document.createElement("input");
    sieve.placeholder = "поиск по имени…";
    sieve.style.cssText = "flex:1;padding:4px 7px;font:12px 'IBM Plex Mono';" +
      "border:1px solid #cbd5e1;border-radius:5px";
    const addOne = document.createElement("button");
    addOne.textContent = "+ Новый диалог";
    addOne.style.cssText = "padding:4px 10px;border:1px solid #2563eb;" +
      "background:#2563eb;color:#fff;border-radius:5px;cursor:pointer;" +
      "font:600 12px 'IBM Plex Sans'";
    head.append(sieve, addOne);
    win.appendChild(head);
    const lists = document.createElement("div");
    lists.style.cssText = "display:flex;gap:12px";
    const leftEl = document.createElement("select");
    leftEl.size = 18;
    leftEl.style.cssText = "width:290px;font:12px 'IBM Plex Mono'";
    const fillList = (pick) => {
      const needle = sieve.value.trim().toLowerCase();
      leftEl.replaceChildren();
      //: свои — наверх: их правят, а канонные только читают
      const rows = [...sp.dialogs].sort((a2, b2) =>
        (b2.own === true) - (a2.own === true));
      for (const d2 of rows) {
        if (needle && !d2.name.toLowerCase().includes(needle) &&
            String(d2.number ?? "") !== needle) continue;
        const obj = document.createElement("option");
        obj.value = d2.name;
        obj.textContent = dialogLabel(d2);
        if (d2.own) obj.style.color = "#2563eb";
        if (d2.name === pick) obj.selected = true;
        leftEl.appendChild(obj);
      }
    };
    fillList(null);
    sieve.oninput = () => fillList(leftEl.value);
    const rightEl = document.createElement("div");
    rightEl.style.cssText = "flex:1;min-width:360px";
    rightEl.innerHTML = `<div style="color:#64748b">выберите диалог —
      его номер и есть «диалог №» юнита; синие строки со значком ✎ —
      свои, их можно править и убирать</div>`;
    lists.append(leftEl, rightEl);
    win.appendChild(lists);
    addOne.onclick = () => newDialogForm(rightEl, async (made) => {
      const again = await api("/story");
      if (again.ok) { sp.dialogs = again.dialogs;
                      state.диалоги = again.dialogs; }
      fillList(made.name);
      leftEl.onchange?.();
      status(`диалог «${made.name}» заведён — номер ${made.number}, ` +
             "файл " + made.file);
    });
    const compiled = document.createElement("button");
    compiled.textContent =
      "Скомпилировать сюжет (project/story/QUESTS.RES)";
    compiled.style.cssText = "width:100%;margin-top:10px;padding:6px;" +
      "border:1px solid #2563eb;color:#2563eb;background:#fff;" +
      "border-radius:5px;cursor:pointer";
    compiled.onclick = async () => {
      status("компилирую сюжет…");
      const resp = await api("/story/compile", "POST", {});
      status(resp.ok ? "сюжет собран: " + resp.note
                  : "компилятор отверг: " + resp.note);
    };
    win.appendChild(compiled);
    leftEl.onchange = async () => {
      const nm = leftEl.value;
      const d2 = await api(`/story/dialog/${encodeURIComponent(nm)}`);
      if (!d2.ok) { rightEl.textContent = d2.note; return; }
      rightEl.replaceChildren();
      const card2 = sp.dialogs.find(z2 => z2.name === nm) || {};
      const head2 = document.createElement("div");
      head2.style.cssText = "font:600 13px 'IBM Plex Sans';" +
        "margin-bottom:6px";
      head2.textContent = `${nm} · файл ${d2.file} · узлов ` +
        `${d2.nodes.length}` +
        (card2.number != null ? ` · диалог № ${card2.number}` : "");
      rightEl.appendChild(head2);
      //: КАНОННЫЙ СЮЖЕТ ТОЛЬКО ЧИТАЕТСЯ. Сервер откажет всё равно, но
      //: узнать об этом ПОСЛЕ правки текстов — потерять работу.
      if (!card2.own) {
        const seal = document.createElement("div");
        seal.style.cssText = "margin:0 0 6px;padding:5px 8px;" +
          "border-radius:5px;background:#fef3c7;color:#92400e;font:12px " +
          "'IBM Plex Sans'";
        seal.textContent = "авторский диалог игры — только чтение: " +
          "правка изменила бы разговор на всех картах сразу";
        rightEl.appendChild(seal);
      }
      //: ДЕРЕВО РИСУЕТСЯ ЗАНОВО НА КАЖДУЮ ПРАВКУ СОСТАВА. Поля пишут
      //: прямо в `d2.nodes`, а добавление и удаление меняют список — и
      //: тогда перерисовка обязана быть полной: у ответов и веток
      //: сдвигаются номера, а в списках целей появляется новая секция.
      const treeZone = document.createElement("div");
      rightEl.appendChild(treeZone);
      const redrawTree = () => {
        treeZone.replaceChildren();
        drawDialogTokens(treeZone, d2, Boolean(card2.own), redrawTree);
        drawDialogTree(treeZone, d2, Boolean(card2.own), redrawTree);
      };
      redrawTree();
      const persist = document.createElement("button");
      persist.textContent = "Сохранить диалог (ворота M_QUEST)";
      persist.style.cssText = "width:100%;margin-top:6px;padding:6px;" +
        "background:#2563eb;color:#fff;border:0;border-radius:5px;" +
        "cursor:pointer";
      persist.disabled = !card2.own;
      persist.onclick = async () => {
        status("сохраняю через ворота компилятора…");
        const resp = await api(`/story/dialog/${encodeURIComponent(nm)}`,
                            "POST", { nodes: d2.nodes,
                                      tokens: d2.tokens || [] });
        status(resp.ok ? "сюжет: " + resp.note : "отказ: " + resp.note);
        //: сервер мог поправить разбор (номера фраз, порядок) — читаем
        //: дерево заново, чтобы панель показывала записанное, а не
        //: наши намерения
        if (resp.ok) leftEl.onchange();
      };
      rightEl.appendChild(persist);
      if (card2.own) {
        const drop = document.createElement("button");
        drop.textContent = "Убрать этот диалог";
        drop.style.cssText = "width:100%;margin-top:6px;padding:6px;" +
          "background:#fff;color:#b91c1c;border:1px solid #b91c1c;" +
          "border-radius:5px;cursor:pointer";
        drop.onclick = async () => {
          //: Второе нажатие подтверждает: окно подтверждения браузера в
          //: панели редактора выглядит чужеродно, а промах здесь стоит
          //: файла с текстами.
          if (drop.dataset.точно !== "1") {
            drop.dataset.точно = "1";
            drop.textContent = "Точно убрать? (нажмите ещё раз)";
            return;
          }
          const resp = await api(
            `/story/dialog/${encodeURIComponent(nm)}`, "DELETE");
          if (!resp.ok) {
            drop.dataset.точно = "";
            drop.textContent = "Убрать этот диалог";
            status("не убран: " + resp.note);
            return;
          }
          const again = await api("/story");
          if (again.ok) { sp.dialogs = again.dialogs;
                          state.диалоги = again.dialogs; }
          fillList(null);
          rightEl.replaceChildren();
          status("сюжет: " + resp.note);
        };
        rightEl.appendChild(drop);
      }
    };
  });
}

//: ЗАПИСИ ЖУРНАЛА — ЭТО ТЕКСТЫ ТОКЕНОВ ЭТОГО ЖЕ ФАЙЛА.
//:
//: Токен с текстом становится строкой журнала игрока, и задать её можно
//: было только при заведении квеста: в панели токенов не было, и в
//: журнал уходило машинное «Имя_Диалога: задание взято.» — с
//: подчёркиваниями, как в имени скрипта. Показываем их рядом с деревом:
//: имя токена (его пишут в `DO=<+ИМЯ>`) и сама строка. Пустая строка —
//: токен без журнальной записи, так тоже бывает.
function drawDialogTokens(host, tree, editable, redraw) {
  const box = document.createElement("div");
  box.style.cssText = "border:1px solid #e2e8f0;border-radius:6px;" +
    "padding:6px 8px;margin:5px 0;background:#f8fafc";
  box.append(Object.assign(document.createElement("div"), {
    textContent: "Записи журнала",
    style: "font:600 12px 'IBM Plex Sans';margin-bottom:4px" }));
  for (const token of tree.tokens || []) {
    const row = document.createElement("div");
    row.style.cssText = "display:flex;flex-direction:column;gap:2px;" +
      "margin:4px 0";
    row.append(Object.assign(document.createElement("span"), {
      textContent: token.name,
      style: "font:11px 'IBM Plex Mono';color:#64748b" }));
    const line = document.createElement("textarea");
    line.style.cssText = "width:100%;height:34px;font:12px 'IBM Plex Sans'";
    line.value = token.text || "";
    line.placeholder = "пусто — этот токен в журнале не показывается";
    line.disabled = !editable;
    line.oninput = () => { token.text = line.value; };
    row.appendChild(line);
    box.appendChild(row);
  }
  if (!(tree.tokens || []).length) {
    box.append(Object.assign(document.createElement("div"), {
      textContent: "у этого диалога своих записей нет",
      style: "font:11px 'IBM Plex Mono';color:#64748b" }));
  }
  if (editable) {
    const bar = document.createElement("div");
    bar.style.cssText = "display:flex;gap:6px;margin-top:6px";
    const name = storyField("", () => {}, "ИМЯ_НОВОГО_ТОКЕНА");
    bar.append(name, storyAdd("+ запись", () => {
      const label = name.value.trim().replace(/\s+/g, "_").toUpperCase();
      if (!/^[\wЀ-ӿ]+$/.test(label)) {
        status("имя записи: буквы, цифры и подчёркивание"); return;
      }
      if ((tree.tokens || []).some(z2 => z2.name === label)) {
        status(`запись «${label}» уже есть`); return;
      }
      tree.tokens = tree.tokens || [];
      tree.tokens.push({ name: label, text: "" });
      redraw();
      status(`запись «${label}» добавлена — ставится действием ` +
             `<+${label}>, спрашивается условием <${label}>`);
    }));
    box.appendChild(bar);
  }
  host.appendChild(box);
}

//: ДЕРЕВО ДИАЛОГА ПРАВИТСЯ ЦЕЛИКОМ, А НЕ ОДНИМИ РЕПЛИКАМИ.
//:
//: Панель показывала развилку и ответы СТРОКАМИ и давала править только
//: первую реплику каждой секции: добавить ответ, увести его в другую
//: секцию, повесить условие или действие — всё это оставалось работой в
//: .QST руками. Здесь то же дерево, но полями: секции, ответы, их цели,
//: `IF=` и `DO=`. Осмысленность проверяет сервер (достижимость плюс
//: ворота M_QUEST), поэтому здесь ровно ввод и ни одной догадки.
const STORY_END = "END_OF_DIALOG";
function storyTargets(nodes, current) {
  const names = (nodes || []).filter(n2 => n2.type === "section")
    .map(n2 => n2.name);
  const all = [STORY_END, ...names];
  //: цель может вести в ЧУЖОЙ скрипт (@Имя — глобальный вход библиотек
  //: COM_*): среди наших секций её нет, но терять её нельзя
  if (current && !all.includes(current)) all.push(current);
  return all;
}
function storyField(value, onEdit, placeholder, width) {
  const it = document.createElement("input");
  it.value = value ?? "";
  it.placeholder = placeholder || "";
  it.style.cssText = "font:11px 'IBM Plex Mono';padding:2px 5px;" +
    "border:1px solid #cbd5e1;border-radius:4px;" + (width || "flex:1");
  it.oninput = () => onEdit(it.value.trim());
  return it;
}
function storyTargetPick(tree, holder) {
  const whither = document.createElement("select");
  whither.style.cssText = "font:11px 'IBM Plex Mono';max-width:180px";
  whither.innerHTML = storyTargets(tree.nodes, holder.target)
    .map(t2 => `<option ${t2 === holder.target ? "selected" : ""}>${t2}` +
               `</option>`).join("");
  whither.onchange = () => { holder.target = whither.value; };
  return whither;
}
function storyKill(title, act, tail) {
  const kill = document.createElement("span");
  kill.textContent = "✕";
  kill.title = title;
  //: хвост стиля — строкой в тот же cssText, а не отдельным свойством:
  //: одиночные `style.что-то = …` копятся полями, которые никто не
  //: читает (сторож tools/write_only_fields.js)
  kill.style.cssText = "color:#b91c1c;cursor:pointer;padding:0 2px;" +
    (tail || "");
  kill.onclick = act;
  return kill;
}
function drawDialogTree(host, tree, editable, redraw) {
  for (const [i2, nodeEl] of tree.nodes.entries()) {
    const blk = document.createElement("div");
    blk.style.cssText = "border:1px solid #e2e8f0;border-radius:6px;" +
      "padding:6px 8px;margin:5px 0";
    const head = document.createElement("div");
    head.style.cssText = "display:flex;align-items:center;gap:6px;" +
      "font:600 12px 'IBM Plex Sans'";
    head.append(Object.assign(document.createElement("span"), {
      textContent: (nodeEl.type === "switch" ? "◇ " : "§ ") + nodeEl.name }));
    if (editable && nodeEl.type === "section" && nodeEl.name !== "*") {
      head.appendChild(storyKill("убрать секцию",
        () => { tree.nodes.splice(i2, 1); redraw(); }, "margin-left:auto"));
    }
    blk.appendChild(head);
    if (nodeEl.type === "switch") {
      //: ВЕТКА РАЗВИЛКИ — условие и куда вести. Условие оставляем
      //: строкой языка компилятора: подсказать его формой честно не
      //: выйдет (там и токены, и встроенные предикаты с доводами), а
      //: подставлять за человека — врать.
      for (const [j2, branch] of nodeEl.cases.entries()) {
        const rowEl = document.createElement("div");
        rowEl.style.cssText = "display:flex;align-items:center;gap:4px;" +
          "margin:3px 0";
        rowEl.appendChild(storyField(branch.cond, v => { branch.cond = v; },
                                     "(<ТОКЕН>&<?предикат:довод>)"));
        rowEl.append(Object.assign(document.createElement("span"),
          { textContent: "→", style: "color:#64748b" }));
        rowEl.appendChild(storyTargetPick(tree, branch));
        if (editable) {
          rowEl.appendChild(storyKill("убрать ветку",
            () => { nodeEl.cases.splice(j2, 1); redraw(); }));
        }
        for (const el of rowEl.querySelectorAll("input,select")) {
          el.disabled = !editable;
        }
        blk.appendChild(rowEl);
      }
      if (editable) {
        blk.appendChild(storyAdd("+ ветка", () => {
          nodeEl.cases.push({ cond: "()", target: STORY_END });
          redraw();
        }));
      }
    } else if (nodeEl.type === "section") {
      const txt = document.createElement("textarea");
      txt.style.cssText = "width:100%;height:52px;margin-top:4px;" +
        "font:12px 'IBM Plex Sans'";
      txt.value = (nodeEl.reply?.texts?.[0]?.text || "").replace(/\n\s+$/, "");
      txt.disabled = !editable;
      txt.oninput = () => {
        if (!nodeEl.reply) nodeEl.reply = { texts: [] };
        if (!nodeEl.reply.texts?.length) nodeEl.reply.texts = [{ text: "" }];
        nodeEl.reply.texts[0].text = txt.value;
      };
      blk.appendChild(txt);
      for (const [j2, answer] of (nodeEl.answers || []).entries()) {
        const box = document.createElement("div");
        box.style.cssText = "border-left:2px solid #cbd5e1;padding-left:6px;" +
          "margin:5px 0 5px 8px;display:flex;flex-direction:column;gap:3px";
        const line = document.createElement("textarea");
        line.style.cssText = "width:100%;height:34px;font:12px 'IBM Plex Sans'";
        line.value = (answer.texts?.[0]?.text || "").replace(/\n\s+$/, "");
        line.disabled = !editable;
        line.oninput = () => {
          if (!answer.texts?.length) answer.texts = [{ text: "" }];
          answer.texts[0].text = line.value;
        };
        box.appendChild(line);
        const rowEl = document.createElement("div");
        rowEl.style.cssText = "display:flex;align-items:center;gap:4px";
        rowEl.append(Object.assign(document.createElement("span"),
          { textContent: "если", style: "color:#64748b;font:11px monospace" }));
        rowEl.appendChild(storyField(answer.cond,
          v => { answer.cond = v || null; }, "условие, можно пусто"));
        rowEl.append(Object.assign(document.createElement("span"),
          { textContent: "делать",
            style: "color:#64748b;font:11px monospace" }));
        rowEl.appendChild(storyField(answer.do,
          v => { answer.do = v || null; }, "<+ТОКЕН><money:25>"));
        rowEl.appendChild(storyTargetPick(tree, answer));
        if (editable) {
          rowEl.appendChild(storyKill("убрать ответ",
            () => { nodeEl.answers.splice(j2, 1); redraw(); }));
        }
        for (const el of rowEl.querySelectorAll("input,select")) {
          el.disabled = !editable;
        }
        box.appendChild(rowEl);
        blk.appendChild(box);
      }
      if (editable) {
        blk.appendChild(storyAdd("+ ответ", () => {
          nodeEl.answers = nodeEl.answers || [];
          nodeEl.answers.push({ cond: null, do: null, target: STORY_END,
                                texts: [{ text: "..." }] });
          redraw();
        }));
      }
    }
    host.appendChild(blk);
  }
  if (!editable) return;
  //: НОВАЯ СЕКЦИЯ. Имя — метка перехода, поэтому правила те же, что у
  //: компилятора: буквы, цифры, подчёркивание и без повторов.
  const bar = document.createElement("div");
  bar.style.cssText = "display:flex;gap:6px;margin-top:6px";
  const name = storyField("", () => {}, "ИМЯ_НОВОЙ_СЕКЦИИ");
  bar.append(name, storyAdd("+ секция", () => {
    const label = name.value.trim().replace(/\s+/g, "_").toUpperCase();
    if (!/^[\wЀ-ӿ]+$/.test(label)) {
      status("имя секции: буквы, цифры и подчёркивание"); return;
    }
    if (tree.nodes.some(n2 => n2.name === label)) {
      status(`секция «${label}» уже есть`); return;
    }
    tree.nodes.push({ type: "section", name: label,
      reply: { texts: [{ text: "..." }] },
      answers: [{ cond: null, do: null, target: STORY_END,
                  texts: [{ text: "..." }] }] });
    redraw();
    status(`секция «${label}» добавлена — уведите в неё ответ, иначе она ` +
           `недостижима и сервер откажет`);
  }));
  host.appendChild(bar);
}
function storyAdd(label, act) {
  const add = document.createElement("button");
  add.textContent = label;
  add.style.cssText = "margin-top:4px;padding:2px 8px;font:11px " +
    "'IBM Plex Sans';border:1px solid #2563eb;color:#2563eb;" +
    "background:#fff;border-radius:4px;cursor:pointer";
  add.onclick = act;
  return add;
}

//: ФОРМА НОВОГО ДИАЛОГА. Руками это пять шагов вне редактора (файл
//: .QST, строка #include, компиляция, номер из QUESTS.LOG, номер юниту);
//: здесь остаётся имя и первая реплика, остальное делает сервер.
//:
//: Шаблон «квест» — тот, что прошёл живой прогон на карте 64: взять
//: задание, напоминание, награда по зачистке отряда, разговор после.
//: Номер отряда для условия считает сервер по карте и стороне.
function newDialogForm(host, onDone) {
  host.replaceChildren();
  const rows = document.createElement("div");
  rows.style.cssText = "display:flex;flex-direction:column;gap:6px";
  const field = (label, node) => {
    const box = document.createElement("label");
    box.style.cssText = "display:flex;flex-direction:column;gap:2px;" +
      "font:11px 'IBM Plex Sans';color:#475569";
    box.append(label, node);
    rows.appendChild(box);
    return node;
  };
  const line = () => {
    const it = document.createElement("input");
    it.style.cssText = "padding:4px 6px;font:12px 'IBM Plex Sans';" +
      "border:1px solid #cbd5e1;border-radius:5px";
    return it;
  };
  const name = field("имя диалога (буквы, цифры, подчёркивание)", line());
  name.placeholder = "Житель_Малого_Бора";
  const comment = field("пометка в скобках (для себя)", line());
  comment.placeholder = "для всех, в Малом Бору";
  const kind = field("вид", document.createElement("select"));
  kind.style.cssText = "padding:4px 6px;font:12px 'IBM Plex Sans'";
  kind.innerHTML = '<option value="plain">простой разговор</option>' +
    '<option value="quest">квест: задание → награда за разгром отряда' +
    "</option>";
  const greeting = field("первая реплика", line());
  greeting.placeholder = "Живая душа, наконец-то!";
  const answer = field("ответ игрока", line());
  answer.placeholder = "Чем помочь?";
  const questBox = document.createElement("div");
  questBox.style.cssText = "display:none;flex-direction:column;gap:6px;" +
    "border-left:2px solid #2563eb;padding-left:8px";
  const bands = document.createElement("select");
  bands.style.cssText = "padding:4px 6px;font:12px 'IBM Plex Mono'";
  bands.innerHTML = hostileBands().map(band =>
    `<option value="${band.side}">${band.label}</option>`).join("");
  const money = line(); money.type = "number"; money.value = "25";
  const exp = line(); exp.type = "number"; exp.value = "100";
  for (const [label, node] of [["чей разгром закрывает задание", bands],
                               ["награда деньгами (в диалогах счёт " +
                                "десятками: 25 = 250 монет)", money],
                               ["награда опытом", exp]]) {
    const box = document.createElement("label");
    box.style.cssText = "display:flex;flex-direction:column;gap:2px;" +
      "font:11px 'IBM Plex Sans';color:#475569";
    box.append(label, node);
    questBox.appendChild(box);
  }
  rows.appendChild(questBox);
  kind.onchange = () => {
    questBox.style.display = kind.value === "quest" ? "flex" : "none";
    if (kind.value === "quest" && !bands.options.length) {
      status("на карте нет чужих отрядов — квест на зачистку не из чего " +
             "собрать");
    }
  };
  const make = document.createElement("button");
  make.textContent = "Завести диалог";
  make.style.cssText = "margin-top:8px;padding:6px;background:#2563eb;" +
    "color:#fff;border:0;border-radius:5px;cursor:pointer;font:600 12px " +
    "'IBM Plex Sans'";
  make.onclick = async () => {
    if (!name.value.trim()) { status("у диалога должно быть имя"); return; }
    make.disabled = true;
    status("завожу диалог и собираю сюжет…");
    const body = {
      name: name.value.trim(), comment: comment.value.trim(),
      kind: kind.value, greeting: greeting.value.trim(),
      answer: answer.value.trim(),
    };
    if (kind.value === "quest") {
      body.map = state.map;
      body.side = Number(bands.value);
      body.money = Number(money.value);
      body.exp = Number(exp.value);
    }
    const resp = await api("/story/dialog/new", "POST", body);
    make.disabled = false;
    if (!resp.ok) return;                   // api() уже сказала, что не так
    onDone({ name: resp.name, number: resp.number, file: resp.file });
  };
  rows.appendChild(make);
  host.appendChild(rows);
}

// мини-инспектор юнита: диалог по ИМЕНИ (номер подставится сам)
//: Слоты снаряжения в том же порядке, в каком их читает отрисовка.
const GEAR_SLOTS = [
  ["body", "доспех"], ["head", "шлем"], ["hand", "оружие"],
  ["off_hand", "щит / вторая рука"], ["ranged", "метательное"],
];
//: ЧИСЛА ВЕЩИ — ОДНОЙ СТРОКОЙ. Пак несёт у каждой вещи силу удара,
//: прочность, цену, вес, дальность и требование к владельцу («Сила 95»);
//: до сих пор наружу шло одно имя, и выбор меча был выбором вслепую.
//: Ноль и пустое не печатаем: у бересты нет ни урона, ни цены, и шесть
//: нулей подряд читаются хуже, чем их отсутствие.
//: ОДНО ЧИСЛО, ДВА СМЫСЛА. `power` (+0x04 записи вещи) — это «урон у
//: оружия, ЗАЩИТА у брони и щита» (konung2/items.py). Подписав его
//: везде «удар», получаем «Укрепленная кольчуга · удар 170» — вздор,
//: который вводит в заблуждение вернее, чем отсутствие числа.
function powerLabel(it) {
  if (it.slot === "body" || it.slot === "head" || it.slot === "off_hand")
    return "защита";
  if (it.slot === "hand" || it.slot === "ranged") return "удар";
  //: КОТОМОЧНАЯ ВЕЩЬ — НИ ТО НИ ДРУГОЕ. `power` у неё есть («Доспех
  //: Дракона» — 400 при слоте bag), но надеть её нельзя, и звать это
  //: ударом — врать: по имени она броня. Говорим нейтрально.
  return "сила";
}
function goodNumbers(it) {
  if (!it) return "";
  const parts = [];
  if (it.power) parts.push(`${powerLabel(it)} ${it.power}`);
  if (it.range_cells > 1) parts.push(`бьёт на ${it.range_cells}`);
  if (it.durability) parts.push(`прочность ${it.durability}`);
  if (it.weight) parts.push(`вес ${it.weight}`);
  if (it.price) parts.push(`цена ${it.price}`);
  if (it.requires && it.requirement)
    parts.push(`нужна ${it.requires} ${it.requirement}`);
  if (it.ammo) parts.push("боеприпас");
  return parts.join(" · ");
}
//: подпись в выпадающем списке: имя и САМОЕ важное число, чтобы не
//: раскрывать каждую вещь по очереди. Длинного хвоста тут не место —
//: полный набор чисел показывает карточка под списком.
function goodLabel(it) {
  const tail2 = it.power ? ` · ${powerLabel(it)} ${it.power}`
              : it.price ? ` · ${it.price} монет` : "";
  return `${it.name}${tail2}`;
}
//: ВОСЕМЬ НАПРАВЛЕНИЙ — СЛОВАМИ, И СЛОВА СНЯТЫ С ШАГОВ, а не придуманы.
//: Пак несёт `hero.direction_steps` — сдвиг в точках на каждый номер:
//:
//:   0 (-58, 0)   1 (-29,-16)  2 (0,-32)   3 (29,-16)
//:   4 (58, 0)    5 (29, 16)   6 (0, 32)   7 (-29, 16)
//:
//: то есть 0 — влево, 2 — вверх, 4 — вправо, 6 — вниз. Стороны света
//: здесь ЭКРАННЫЕ (низ карты — юг): человек смотрит на ту же картинку,
//: что и игрок, и «направление 6» ему не говорит ничего.
const COMPASS = ["запад", "северо-запад", "север", "северо-восток",
                 "восток", "юго-восток", "юг", "юго-запад"];
//: ЧТО ЗНАЧИТ ОТРЯД, СЛОВАМИ. Вражда живёт у ОТРЯДА, а не у бойца
//: (VA 0x415B20 решает один проход по отрядам карты), и это ровно та
//: путаница, из-за которой «мирный житель» дрался: биты стояли у его
//: отряда. Инспектор обязан говорить это вслух, у самого юнита.
function bandMeaning(band) {
  if (!band) return "отряда с такой стороной на карте нет";
  if (band.player) return "отряд игрока — герой со спутниками";
  const parts = [];
  if (band.on_player) parts.push("нападает на игрока");
  if (band.on_parties) parts.push("нападает на другие отряды");
  if (band.on_special) parts.push("особая цель");
  if (band.only_if_fighting) parts.push("только если уже в бою");
  return parts.length ? parts.join(" · ") : "мирный: сам не нападает";
}
//: МЕСТО ОТРЯДА В СЧЁТЕ КАРТЫ — довод условия «карта зачищена».
//: Считается по НЕ своим сторонам, отсортированным по возрастанию
//: (mapstate.js mapSquads), и это же считает сервер, когда заводит
//: квест (server.py _squad_index). Здесь — чтобы человек видел число,
//: которым его квест проверяет победу, не выводя его в уме.
function squadPlace(sideNum) {
  const sides = [...new Set(mapBands().filter(b2 => !b2.player)
    .map(b2 => Number(b2.side)))].sort((a2, b2) => a2 - b2);
  const at = sides.indexOf(Number(sideNum));
  return at < 0 ? null : at;
}
//: ОТРЯД ЮНИТА — СМЫСЛАМИ, ПРЯМО В ЕГО ПАНЕЛИ.
//:
//: «отряд 186» не говорит ни того, нападёт ли этот житель, ни того,
//: каким числом квест проверит его разгром. Оба ответа были в другом
//: месте: вражда — на экране отрядов (и живёт она у ОТРЯДА, а не у
//: бойца), а номер отряда для условия «карта зачищена» не показывал
//: никто — его выводили в уме и ошибались. Здесь и то, и другое, и
//: переключатель вражды с честной оговоркой, кого он ещё заденет.
function unitBandBlock(unitRec) {
  const blk = document.createElement("div");
  blk.style.cssText = "margin:6px 0;padding:7px 9px;border-radius:6px;" +
    "background:#f8fafc;border:1px solid #e2e8f0;font:11px 'IBM Plex Mono';" +
    "color:#334155;display:flex;flex-direction:column;gap:4px";
  const side = Number(unitRec.side ?? unitRec.party);
  const band = mapBands().find(b2 => Number(b2.side) === side) || null;
  const mates = bandFighters(side).filter(u2 => u2 !== unitRec);
  const head = document.createElement("div");
  head.style.cssText = "font:600 12px 'IBM Plex Sans';color:#0f172a";
  head.textContent = `Отряд ${side} · ${bandMeaning(band)}`;
  blk.appendChild(head);
  const say = (text) => blk.insertAdjacentHTML("beforeend",
    `<div style="color:#64748b">${text}</div>`);
  if (mates.length) {
    say("с ним в отряде: " + mates.slice(0, 5)
      .map(u2 => u2.name || u2.id).join(", ") +
      (mates.length > 5 ? ` и ещё ${mates.length - 5}` : ""));
  } else if (band) {
    say("больше в этом отряде никого");
  }
  //: Число, которым квест проверяет победу над этим отрядом. Пишем и
  //: его, и из чего оно сложено, — иначе это опять «магия 320».
  const place = squadPlace(side);
  if (place != null) {
    //: Угловые скобки условия — ТЕКСТОМ, а не разметкой: вставленные как
    //: HTML, они молча съедаются браузером, и от главного числа остаётся
    //: пустое место (поймано на живой панели: «условие „зачищено“ для
    //: него —  (карта 64 + 256×0)»).
    const row = document.createElement("div");
    row.style.color = "#64748b";
    row.textContent = `в счёте карты это отряд №${place}; условие ` +
      `«зачищено» для него — <?all_killed:` +
      `${(state.map ?? 0) + place * 256}> (карта ${state.map} + ` +
      `256×${place})`;
    blk.appendChild(row);
  }
  if (band && !band.player) {
    const row = document.createElement("label");
    row.style.cssText = "display:flex;align-items:center;gap:6px;" +
      "cursor:pointer;color:#0f172a";
    const flag = document.createElement("input");
    flag.type = "checkbox";
    flag.checked = Boolean(band.on_player);
    flag.onchange = async () => {
      const resp = await api(`/maps/${state.map}/warbands`, "POST",
        { side, patch: { on_player: flag.checked } });
      if (!resp.ok) { flag.checked = !flag.checked; return; }
      await openMap(state.map);
      showScreen(state.screen);
      status(`отряд ${side}: ${flag.checked ? "нападает на игрока"
                                            : "больше не нападает"}` +
             (mates.length ? ` — правило общее на весь отряд, в нём ещё ` +
              `${mates.length} ` + plural(mates.length,
                ["боец", "бойца", "бойцов"]) : ""));
    };
    row.append(flag, Object.assign(document.createElement("span"),
      { textContent: "нападает на игрока (правило ОТРЯДА, не бойца)" }));
    blk.appendChild(row);
  }
  if (!band) {
    say("отряда с такой стороной на карте нет — боец останется без " +
        "правил вражды; заведите отряд на вкладке «Отряды»");
  }
  return blk;
}
//: ЧИСЛА ЖИТЕЛЯ — ТЕМ ЖЕ СПОСОБОМ. Характеристики, боевые числа и
//: умения приходят из пака (api_pack_units отдаёт их с 27.08); у
//: draft-юнита своей записи нет, и тогда берём образец породы из
//: бестиария — он честно подписан как «числа породы».
function unitNumbersBlock(unitRec) {
  const blk = document.createElement("div");
  blk.style.cssText = "margin:8px 0;border-top:1px solid #e2e8f0;" +
    "padding-top:8px;font:11px 'IBM Plex Mono';color:#334155";
  const breedRec = breedOfUnit(unitRec);
  const mine = unitRec.characteristics || unitRec.stats;
  const source2 = mine ? unitRec : (breedRec?.sample || {});
  const from2 = mine ? "" :
    (breedRec ? ` · числа породы «${breedRec.name}», своих у него ещё нет` : "");
  const rowEl = (label, val) => {
    if (val == null || val === "") return;
    blk.insertAdjacentHTML("beforeend",
      `<div style="display:flex;gap:6px"><span style="width:120px;` +
      `color:#64748b;flex:none">${label}</span><span>${val}</span></div>`);
  };
  blk.insertAdjacentHTML("beforeend",
    `<div style="font:600 12px 'IBM Plex Sans';margin-bottom:4px;` +
    `color:#0f172a">Числа${from2}</div>`);
  //: КТО ЭТО — ИМЕНЕМ ПОРОДЫ, А НЕ ПАРОЙ ЧИСЕЛ. «порода 0, тело 6» не
  //: говорит ничего; бестиарий знает, что это «Славяне · мужчина».
  //: Масть тоже проверяем: чужая масть рисует юнита не теми красками, а
  //: узнать об этом иначе можно только глазами на карте.
  if (breedRec || unitRec.breed != null) {
    const coats = breedRec?.palettes || [];
    const coat = unitRec.palette;
    rowEl("кто", (breedRec?.name || `порода ${unitRec.breed}`) +
      (unitRec.body != null ? ` · тело ${unitRec.body}` : "") +
      (coat != null ? ` · масть ${coat}` : "") +
      (coat != null && coats.length && !coats.includes(Number(coat))
        ? ` — этой масти у породы нет (её: ${[...new Set(coats)].join(", ")})`
        : ""));
  }
  const chars = source2.characteristics || {};
  const keysOf = Object.keys(chars);
  if (keysOf.length) {
    rowEl("характеристики",
           keysOf.map(k2 => `${k2.slice(0, 4).toLowerCase()} ${chars[k2]}`)
                .join(" · "));
  }
  const b2 = source2.stats || {};
  //: parry — ПАРИРОВАНИЕ (konung2/combat.py, PARRY_MELEE_SCALE), а не
  //: «защита»: словом «защита» в этом же окне подписана сила брони, и
  //: два разных числа под одной подписью читаются как одно
  const combat = [["health", "жизнь"], ["armour", "броня"],
               ["parry", "парирование"], ["accuracy", "меткость"],
               ["strength", "сила"], ["toughness", "стойкость"]]
    .filter(([k2]) => b2[k2] != null)
    .map(([k2, p2]) => `${p2} ${b2[k2]}`).join(" · ");
  rowEl("в бою", combat);
  rowEl("уровень", source2.level ?? unitRec.level);
  rowEl("деньги", source2.money ?? unitRec.money);
  rowEl("скорость", source2.speed ?? unitRec.speed);
  rowEl("яд", source2.venom || null);
  const mind = source2.skills || {};
  const skills2 = Object.entries(mind).map(([k2, v]) => `${k2} ${v}`).join(" · ");
  rowEl("умения", skills2);
  const bag2 = (unitRec.bag_details || []).map(it => it?.name || it).filter(Boolean);
  rowEl("в сумке", bag2.join(" · "));
  const places = (unitRec.workplaces || []).length;
  rowEl("рабочих мест", places || null);
  return blk;
}
//: ПРАВКА ЖИТЕЛЯ: УРОВЕНЬ, ЧИСЛА, ПОЯС.
//:
//: Поставить жителя было можно, а сделать с ним что-либо — нет: числа
//: показывались, но не правились, пояса не было вовсе. Между тем всё
//: это лежит в записи и белые списки сборки его пропускают.
//:
//: ПРАВИМ ТОЛЬКО СВОЕГО. Житель draft-слоя лежит в scenario.json
//: целиком — его и правим. У жителя МИРА запись в project/worlds, и
//: числа туда пишет своя ручка (МИР_ПОЛЯ_ЮНИТА); пояс же лежит в
//: байтах записи, и слоем карты его не подменишь. Молча делать вид,
//: что правим, нельзя — говорим прямо.
const UNIT_STATS = [
  "Сила", "Ловкость", "Выносливость", "Интеллект", "Харизма", "Обучаемость",
];
const COMBAT_NUMBERS = [
  ["health", "жизнь"], ["armour", "броня"], ["parry", "парирование"],
  ["accuracy", "меткость"], ["strength", "сила"], ["toughness", "стойкость"],
];
function unitNumberField(label, val, onPatch, available2 = true) {
  const rowEl = document.createElement("label");
  rowEl.style.cssText = "display:flex;align-items:center;gap:6px;" +
    "font:11px 'IBM Plex Mono'" + (available2 ? "" : ";opacity:.55");
  const field = document.createElement("input");
  field.type = "number";
  field.value = String(val ?? 0);
  field.disabled = !available2;
  field.style.cssText = "width:80px;font:11px 'IBM Plex Mono'";
  field.onchange = () => onPatch(Number(field.value) || 0);
  rowEl.append(Object.assign(document.createElement("span"),
    { textContent: label, style: "width:110px;color:#64748b;flex:none" }),
    field);
  return rowEl;
}
async function patchResident(win, unitRec, afterPatch) {
  const own = String(unitRec.id || "").startsWith("unit_new_");
  const breedRec = breedOfUnit(unitRec);
  const blk = document.createElement("div");
  blk.style.cssText = "margin:8px 0;border-top:1px solid #e2e8f0;" +
    "padding-top:8px;display:flex;flex-direction:column;gap:6px";
  blk.insertAdjacentHTML("beforeend",
    `<div style="font:600 12px 'IBM Plex Sans'">Числа</div>`);

  async function saveIt(patchBody) {
    const resp = own
      ? await api(`/maps/${state.map}/units`, "POST",
                  { id: unitRec.id, patch: patchBody })
      : await api(`/worlds/${state.слотГероя?.world}/maps/${state.map}` +
                  `/units`, "POST",
                  { index: Number(String(unitRec.id).replace(/^unit_/, "")),
                    patch: patchBody });
    const msg = resp.note || (resp.ok ? "готово" : "не вышло");
    if (resp.ok) await afterPatch?.();
    status(msg);
  }

  //: УРОВЕНЬ. Порог опыта считается по правилам движка
  //: (konung2/progress.py level_threshold: сумма i*100), и показать
  //: его полезно — уровень без опыта в игре ничего не значит.
  blk.appendChild(unitNumberField("уровень", unitRec.level,
    zn => saveIt({ level: zn })));
  const threshold = Array.from({ length: (Number(unitRec.level) || 0) + 1 })
    .reduce((sp, _, i) => sp + i * 100, 0);
  blk.insertAdjacentHTML("beforeend",
    `<div style="font:10.5px 'IBM Plex Mono';color:#64748b">` +
    `опыта на этот уровень по правилам игры: ${threshold}</div>`);

  //: ХАРАКТЕРИСТИКИ. Их шесть, и они же задают потолки навыков
  //: (skill_limit считает от Обучаемости и пары профильных).
  const chars = unitRec.characteristics || breedRec?.sample?.characteristics || {};
  for (const nm of UNIT_STATS) {
    blk.appendChild(unitNumberField(nm.toLowerCase(), chars[nm],
      zn => saveIt({ characteristics: { [nm]: zn },
                       current: { [nm]: zn } })));
  }
  const combat = unitRec.stats || breedRec?.sample?.stats || {};
  for (const [key2, label] of COMBAT_NUMBERS) {
    if (combat[key2] == null) continue;
    blk.appendChild(unitNumberField(label, combat[key2],
      zn => saveIt({ stats: { [key2]: zn } })));
  }
  //: СБРОС — К ОБРАЗЦУ ПОРОДЫ, а не к нулям: нулевой житель в игре
  //: беспомощен и выглядит поломкой. Образец — тот же, с которого
  //: сняты числа при постановке.
  if (breedRec?.sample) {
    const reset2 = document.createElement("button");
    reset2.textContent = `Сбросить к образцу («${breedRec.name}»)`;
    reset2.style.cssText = "padding:5px;cursor:pointer;" +
      "font:12px 'IBM Plex Sans'";
    reset2.onclick = () => saveIt({
      level: breedRec.sample.level ?? 1,
      characteristics: { ...(breedRec.sample.characteristics || {}) },
      current: { ...(breedRec.sample.characteristics || {}) },
      stats: { ...(breedRec.sample.stats || {}) },
      skills: { ...(breedRec.sample.skills || {}) },
    });
    blk.appendChild(reset2);
  }
  win.appendChild(blk);

  //: ПОЯС. Сорок две ячейки, двенадцать видно разом (konung2/interf.py
  //: BELT). Лежит в `bag`, и `bag_details` идут параллельно — заряды и
  //: прочность. У жителя мира пояс в байтах записи: слоем карты его не
  //: подменить, и обещать этого нельзя.
  const belt = document.createElement("div");
  belt.style.cssText = "margin:8px 0;border-top:1px solid #e2e8f0;" +
    "padding-top:8px;display:flex;flex-direction:column;gap:4px";
  const goods = unitRec.bag || [];
  const details2 = unitRec.bag_details || [];
  belt.insertAdjacentHTML("beforeend",
    `<div style="font:600 12px 'IBM Plex Sans'">Пояс · ${goods.length}` +
    `<span style="font:400 10px 'IBM Plex Mono';color:#64748b;` +
    `margin-left:6px">из 42 ячеек, 12 видно разом</span></div>`);
  if (!state.вещи) state.вещи = await api("/catalog/items");
  const byRef = ref2 => {
    const m2 = /^(?:class|instance):(\d+)/.exec(String(ref2 || ""));
    return m2 ? (state.вещи?.items || [])
      .find(it => it.ref === `class:${m2[1]}`) : null;
  };
  goods.forEach((sp, num) => {
    const it = byRef(sp) || {};
    const rowEl = document.createElement("div");
    rowEl.style.cssText = "display:flex;align-items:center;gap:6px;" +
      "font:11px 'IBM Plex Mono'";
    if (it.icon) {
      const img = document.createElement("img");
      img.src = it.icon; img.width = 20; img.height = 20;
      img.style.cssText = "image-rendering:pixelated;flex:none";
      img.onerror = () => img.remove();
      rowEl.appendChild(img);
    }
    rowEl.appendChild(Object.assign(document.createElement("span"), {
      textContent: (it.name || sp) +
        (details2[num]?.count ? ` × ${details2[num].count}` : ""),
      style: "flex:1;min-width:0",
    }));
    if (own) {
      const unset = document.createElement("button");
      unset.textContent = "×";
      unset.title = "снять с пояса";
      unset.style.cssText = "flex:none;width:20px;height:20px;padding:0;" +
        "cursor:pointer;border:1px solid #cbd5e1;border-radius:4px;" +
        "background:#fff;color:#b91c1c;font:700 12px monospace";
      unset.onclick = async () => {
        const resp = await api(`/maps/${state.map}/units`, "POST",
                            { id: unitRec.id, remove_item: num });
        const msg = resp.note || (resp.ok ? "снято" : "не вышло");
        if (resp.ok) await afterPatch?.();
        status(msg);
      };
      rowEl.appendChild(unset);
    }
    belt.appendChild(rowEl);
  });
  if (own) {
    const line = document.createElement("div");
    line.style.cssText = "display:flex;gap:4px;margin-top:2px";
    const choice = document.createElement("select");
    choice.style.cssText = "flex:1;min-width:0;font:11px 'IBM Plex Mono'";
    choice.innerHTML = (state.вещи?.items || [])
      .map(it => `<option value="${it.ref}">${goodLabel(it)}</option>`).join("");
    const howMany = document.createElement("input");
    howMany.type = "number"; howMany.min = "1"; howMany.value = "1";
    howMany.title = "заряды у боеприпаса";
    howMany.style.cssText = "width:52px;font:11px 'IBM Plex Mono'";
    const refreshNumber = () => {
      const it = (state.вещи?.items || []).find(x => x.ref === choice.value);
      howMany.style.display = it?.ammo ? "" : "none";
    };
    choice.onchange = refreshNumber;
    refreshNumber();
    const btn = document.createElement("button");
    btn.textContent = "В пояс";
    btn.style.cssText = "flex:none;padding:3px 8px;cursor:pointer;" +
      "font:11px 'IBM Plex Sans'";
    btn.onclick = async () => {
      const it = (state.вещи?.items || []).find(x => x.ref === choice.value);
      const bodyNum = { id: unitRec.id, add_item: { ref: choice.value } };
      if (it?.ammo) bodyNum.add_item.count = Math.max(1, Number(howMany.value) || 1);
      const resp = await api(`/maps/${state.map}/units`, "POST", bodyNum);
      const msg = resp.note || (resp.ok ? "положено" : "не вышло");
      if (resp.ok) await afterPatch?.();
      status(msg);
    };
    line.append(choice, howMany, btn);
    belt.appendChild(line);
  } else {
    belt.insertAdjacentHTML("beforeend",
      `<div style="font:11px 'IBM Plex Mono';color:#92400e">` +
      `пояс жителя мира лежит в байтах его записи — слоем карты его не ` +
      `подменить; правится он в исходниках мира</div>`);
  }
  win.appendChild(belt);
}

//: ПЕРЕИМЕНОВАНИЕ ЖИТЕЛЯ. Имя выбиралось только при постановке, и
//: ошибиться было легко: первые люди на карте так и остались зваться
//: «Человек · тело 6» — подписью строки каталога. Исправить это было
//: нечем вовсе.
//:
//: ДВА АДРЕСА, И ЭТО НЕ КОСМЕТИКА. Житель, поставленный редактором,
//: живёт в draft-слое карты, и его имя там — обычная строка: пишем и
//: строку, и номера (пригодятся, если запись однажды уедет в мир).
//: Житель МИРА живёт в project/worlds, и строки имени там нет вовсе —
//: только номера в таблицах exe (0xF0 и 0xF1). Ему пишем номера, и
//: имя соберёт сама игра.
//:
//: Твари имя даёт порода (бит 0x40): движок берёт его из таблицы пород
//: по самому байту породы, и переименовать Аспида нельзя — можно лишь
//: переписать подпись в нашем паке, а это враньё про игру. Поэтому у
//: тварей ряд не показываем и говорим почему.
async function unitNameRow(win, unitRec, afterPatch) {
  const breedRec = Number(unitRec.breed ?? 0);
  const blk = document.createElement("div");
  blk.style.cssText = "margin:8px 0;border-top:1px solid #e2e8f0;" +
    "padding-top:8px;display:flex;flex-direction:column;gap:5px";
  blk.insertAdjacentHTML("beforeend",
    `<div style="font:600 12px 'IBM Plex Sans'">Имя</div>`);
  if (breedRec & 0x40) {
    blk.insertAdjacentHTML("beforeend",
      `<div style="font:11px 'IBM Plex Mono';color:#64748b">` +
      `имя твари даёт порода — движок берёт его из таблицы пород по ` +
      `самому байту породы, и переписать его нельзя</div>`);
    win.appendChild(blk);
    return;
  }
  const own = String(unitRec.id || "").startsWith("unit_new_");
  const worldIndex = Number(String(unitRec.id || "").replace(/^unit_/, ""));
  const slotNum = state.слотГероя;
  const worldMapNumbers = slotNum?.map_numbers;
  const worldKnows = !Array.isArray(worldMapNumbers) ||
                   worldMapNumbers.includes(Number(state.map));
  const allowed = own || (Boolean(slotNum?.editable) && worldKnows &&
                         Number.isInteger(worldIndex));
  if (!state.каталогИмён) {
    const k2 = await api("/catalog/names");
    if (k2.ok) state.каталогИмён = k2;
  }
  const line = document.createElement("div");
  line.style.cssText = "display:flex;gap:4px";
  const nameList = document.createElement("select");
  const nickList = document.createElement("select");
  for (const el of [nameList, nickList]) {
    el.style.cssText = "flex:1;min-width:0;font:11px 'IBM Plex Mono'";
    el.disabled = !allowed;
  }
  const k2 = state.каталогИмён || { names: [], nicknames: [] };
  nameList.innerHTML = `<option value="0">— имя не задано —</option>` +
    k2.names.map(z2 => `<option value="${z2.id}"` +
      `${z2.id === Number(unitRec.name_id) ? " selected" : ""}>${z2.name}` +
      `</option>`).join("");
  nickList.innerHTML = `<option value="0">без прозвища</option>` +
    k2.nicknames.map(z2 => `<option value="${z2.id}"` +
      `${z2.id === Number(unitRec.nick_id) ? " selected" : ""}>${z2.name}` +
      `</option>`).join("");
  line.append(nameList, nickList);
  blk.appendChild(line);
  const btn = document.createElement("button");
  btn.textContent = "Переименовать";
  btn.disabled = !allowed;
  btn.style.cssText = "padding:5px;cursor:pointer;" +
    "font:12px 'IBM Plex Sans'";
  btn.onclick = async () => {
    const nameNo = Number(nameList.value) || 0;
    const nickNo = Number(nickList.value) || 0;
    if (!nameNo) { status("выберите имя из списка"); return; }
    const assembled = nameByNumber(nameNo, nickNo);
    const resp = own
      ? await api(`/maps/${state.map}/units`, "POST",
          { id: unitRec.id,
            patch: { name: assembled, name_id: nameNo, nick_id: nickNo } })
      : await api(`/worlds/${slotNum.world}/maps/${state.map}/units`, "POST",
          { index: worldIndex, patch: { name_id: nameNo, nick_id: nickNo } });
    const msg = resp.ok
      ? `${unitRec.name || unitRec.id} → «${assembled}»` +
        (own ? "" : " · соберите мир и пак, чтобы увидеть в игре")
      : (resp.note || "не вышло");
    if (resp.ok) {
      unitRec.name = assembled;
      unitRec.name_id = nameNo;
      unitRec.nick_id = nickNo;
      closePanel();
      await afterPatch?.();
    }
    status(msg);
  };
  blk.appendChild(btn);
  if (!allowed) {
    blk.insertAdjacentHTML("beforeend",
      `<div style="font:11px 'IBM Plex Mono';color:#92400e">` +
      (worldKnows
        ? `у этого героя нет исходников мира — имя жителя мира лежит в ` +
          `них, и править его нечем`
        : `карту ${state.map} создал редактор: в исходниках мира её нет, ` +
          `и жителя мира на ней быть не может`) + `</div>`);
  }
  win.appendChild(blk);
}
async function unitInspector(unitRec) {
  const sp = { ok: true, dialogs: await ensureDialogs() };
  if (!state.вещи) state.вещи = await api("/catalog/items");
  panelEl(`Юнит ${unitRec.name || unitRec.id}`, win => {
    win.insertAdjacentHTML("beforeend",
      `<div style="font:11px 'IBM Plex Mono';color:#64748b">` +
      `${unitRec.id} · клетка ${unitRec.cell?.row}:${unitRec.cell?.col}` +
      (unitRec.direction != null
        ? ` · смотрит на ${COMPASS[unitRec.direction & 7]}` : "") +
      `</div>`);
    win.appendChild(unitBandBlock(unitRec));
    //: СНАРЯЖЕНИЕ. Ссылка юнита («instance:209:…») несёт номер класса
    //: первым числом — по нему и сверяем выбранное. Запись идёт словарём
    //: equipment, который сборка кладёт в юнита, а слои отрисовки
    //: считает из класса (layer + palette).
    const refClass = (ref2) => {
      const m2 = /^(?:instance|class):(\d+)/.exec(String(ref2 || ""));
      return m2 ? `class:${m2[1]}` : null;
    };
    //: ЧИСЛА ЖИТЕЛЯ. Их тут не было вовсе: инспектор показывал строку
    //: «id · отряд · клетка», снаряжение и диалог — и всё. А в паке у
    //: юнита лежат и характеристики, и боевые числа, и умения; наружу
    //: их просто не отдавала ручка (api_pack_units). Теперь отдаёт.
    win.appendChild(unitNumbersBlock(unitRec));
    //: имя правится здесь же: это первое, что человек хочет поменять у
    //: жителя, и искать его на другом экране незачем
    const refresh2 = async () => {
      await openMap(state.map);
      showScreen(state.screen);
    };
    unitNameRow(win, unitRec, refresh2);
    patchResident(win, unitRec, refresh2);
    const gearEl = document.createElement("div");
    gearEl.style.cssText = "margin:8px 0;border-top:1px solid #e2e8f0;" +
      "padding-top:8px";
    gearEl.innerHTML = `<div style="font:600 12px 'IBM Plex Sans';` +
      `margin-bottom:4px">Снаряжение</div>`;
    const picks = {};
    for (const [slotNum, label] of GEAR_SLOTS) {
      const rowEl = document.createElement("label");
      rowEl.style.cssText = "display:flex;align-items:center;gap:6px;" +
        "margin:3px 0;font:11px 'IBM Plex Mono'";
      const selectEl = document.createElement("select");
      selectEl.style.cssText = "flex:1;min-width:0;font:11px 'IBM Plex Mono'";
      const mine = (state.вещи?.items || []).filter(it => it.slot === slotNum);
      const currentOne = refClass((unitRec.equipment || {})[slotNum]);
      selectEl.innerHTML = `<option value="">— пусто —</option>` +
        mine.map(it => `<option value="${it.ref}" ` +
          `${it.ref === currentOne ? "selected" : ""}>${goodLabel(it)}</option>`)
          .join("");
      picks[slotNum] = selectEl;
      rowEl.append(Object.assign(document.createElement("span"),
        { textContent: label, style: "width:120px;color:#64748b;flex:none" }),
        selectEl);
      gearEl.appendChild(rowEl);
      //: ВЫБОР ВЕЩИ БЫЛ ВЫБОРОМ ВСЛЕПУЮ: список одних имён, без значка,
      //: без цены, веса, силы удара и требования к владельцу. Значок и
      //: числа лежали в паке всё это время. Показываем их для того, что
      //: выбрано прямо сейчас, — и обновляем при смене.
      const itemCard = document.createElement("div");
      itemCard.style.cssText = "display:flex;align-items:center;gap:8px;" +
        "margin:0 0 6px 126px;min-height:20px";
      gearEl.appendChild(itemCard);
      const showGood = () => {
        const it = mine.find(x => x.ref === selectEl.value);
        itemCard.replaceChildren();
        if (!it) return;
        if (it.icon) {
          const img = document.createElement("img");
          img.src = it.icon; img.width = 34; img.height = 34;
          img.style.cssText = "image-rendering:pixelated;flex:none;" +
            "background:#f1f5f9;border-radius:4px";
          img.onerror = () => img.remove();
          itemCard.appendChild(img);
        }
        itemCard.appendChild(Object.assign(
          document.createElement("span"),
          { textContent: goodNumbers(it) || "чисел нет",
            style: "font:10.5px 'IBM Plex Mono';color:#475569;" +
                   "line-height:1.35" }));
      };
      selectEl.onchange = showGood;
      showGood();
    }
    const dressUp = document.createElement("button");
    dressUp.textContent = "Переодеть";
    dressUp.style.cssText = "width:100%;margin-top:6px;padding:5px;" +
      "cursor:pointer";
    dressUp.onclick = async () => {
      const setOf = {};
      for (const [slotNum] of GEAR_SLOTS) {
        const z2 = picks[slotNum].value;
        if (z2) setOf[slotNum] = z2;
      }
      const resp = await api(`/maps/${state.map}/units`, "POST",
        { id: unitRec.id, patch: { equipment: setOf } });
      if (resp.ok) {
        unitRec.equipment = setOf;
        status("снаряжение записано — сборка перепечёт слои");
        closePanel();
      } else {
        status(resp.note || "не вышло");
      }
    };
    gearEl.appendChild(dressUp);
    win.appendChild(gearEl);
    //: РАЗГОВОР ЮНИТА — ИМЕНЕМ, А НЕ НОМЕРОМ. Номер человек всё равно
    //: увидит (он же лежит в записи), но выбирать 152 из 154 чисел, зная
    //: только имя жителя, невозможно: свои диалоги идут наверху и
    //: помечены, канонные — ниже.
    const talkRow = document.createElement("div");
    talkRow.style.cssText = "margin:8px 0 4px;font:11px 'IBM Plex Sans';" +
      "color:#475569";
    const now = sp.ok
      ? sp.dialogs.find(d2 => d2.number === unitRec.dialog_number) : null;
    talkRow.textContent = "разговор: " + (
      unitRec.dialog_number == null || unitRec.dialog_number === 255
        ? "молчит" : now ? `${now.name} (№ ${unitRec.dialog_number})`
                         : `№ ${unitRec.dialog_number} — дерева с таким ` +
                           "номером в сюжете нет");
    win.appendChild(talkRow);
    const dialogNum = document.createElement("select");
    dialogNum.style.cssText = "width:100%;margin:0 0 8px;font:12px " +
      "'IBM Plex Mono'";
    const known = sp.ok ? [...sp.dialogs].filter(d2 => d2.number != null)
      .sort((a2, b2) => (b2.own === true) - (a2.own === true)) : [];
    dialogNum.innerHTML = `<option value="255">— молчит (255) —</option>` +
      known.map(d2 => `<option value="${d2.number}" ` +
        `${unitRec.dialog_number === d2.number ? "selected" : ""}>` +
        `${dialogLabel(d2)}</option>`).join("");
    win.appendChild(dialogNum);
    const applyIt = document.createElement("button");
    applyIt.textContent = "Назначить диалог";
    applyIt.style.cssText = "width:100%;padding:6px;background:#2563eb;" +
      "color:#fff;border:0;border-radius:5px;cursor:pointer";
    applyIt.onclick = async () => {
      const num = Number(dialogNum.value);
      const resp = await api(`/maps/${state.map}/units`, "POST",
        { id: unitRec.id, patch: { dialog_number: num } });
      if (resp.ok) {
        unitRec.dialog_number = num;
        const pick = known.find(d2 => d2.number === num);
        status(`${unitRec.name || "юнит"}: разговор ` +
               (num === 255 ? "убран" : `«${pick?.name ?? num}»`) +
               " — дерево перепечётся сборкой карты");
        closePanel();
      }
    };
    win.appendChild(applyIt);
    //: ЗАВЕСТИ РАЗГОВОР ПРЯМО ЗДЕСЬ. Иначе это уход в «События»,
    //: сочинение диалога, возврат к юниту и поиск номера — четыре
    //: перехода ради одной привязки.
    const fresh = document.createElement("button");
    fresh.textContent = "+ Новый диалог для этого юнита";
    fresh.style.cssText = "width:100%;margin-top:6px;padding:6px;" +
      "background:#fff;color:#2563eb;border:1px solid #2563eb;" +
      "border-radius:5px;cursor:pointer";
    fresh.onclick = () => {
      const host = document.createElement("div");
      host.style.cssText = "margin-top:8px;border-top:1px solid #e2e8f0;" +
        "padding-top:8px";
      fresh.replaceWith(host);
      newDialogForm(host, async (made) => {
        const resp = await api(`/maps/${state.map}/units`, "POST",
          { id: unitRec.id, patch: { dialog_number: made.number } });
        unitRec.dialog_number = made.number;
        state.диалоги = null;        // список вырос — перечитаем при нужде
        status(resp.ok
          ? `«${made.name}» заведён (№ ${made.number}, ${made.file}) и ` +
            `назначен юниту — соберите карту, чтобы дерево попало в игру`
          : `диалог заведён (№ ${made.number}), но назначить не вышло`);
        closePanel();
      });
    };
    win.appendChild(fresh);
  });
}

loadDesign();

// ── СЕЛФЧЕК РЕДАКТОРА ────────────────────────────────────────────────
//
//: ЕДИНСТВЕННАЯ ПРОВЕРКА, КОТОРАЯ СМОТРИТ НА ЭКРАНЫ, А НЕ В ИСХОДНИК.
//:
//: Редактор прищеплен к нетронутому макету догадками: органы ищутся по
//: тексту, по цвету фона, по числу детей и ширине. Каждая догадка может
//: молча взять НЕ ТОТ узел — и тогда на экране остаётся вёрстка
//: дизайнера с его выдуманными данными. Она выглядит рабочей: «55 ·
//: изба», «23 породы», «498/512». Так каталог объектов уехал в полоску
//: шириной 56 точек, а бестиарий остался жить на «Деревне» и «Отрядах».
//:
//: Молчали при этом обе стороны. `промах()` складывал находки в
//: `state.промахи` — список, который НЕ ЧИТАЛА НИ ОДНА строка. А тесты
//: (155 штук, 428 проверок) искали подстроки в самом файле: они не
//: способны увидеть ни кнопку без подсветки, ни две стрелки, ведущие
//: вперёд, ни каталог в 56 точках. «Зелёные тесты и решето» — не
//: противоречие: они проверяли не то.
//:
//: Селфчек открывает КАЖДЫЙ экран и спрашивает: подключены ли его
//: живые блоки и не было ли промахов. Запуск из консоли:
//:     await редактор.селфчек()            // на открытой карте
//:     await редактор.селфчек({ карта: 63 })

//: Что должно быть подключено на каждом экране. Списки НЕ ПЕРЕПИСЫВАЕМ
//: руками: они выводятся из контракта ЗОНЫ, где у каждой зоны указан
//: свой экран. Иначе «как ищем» и «что должно быть» — две копии одного
//: знания, и они разъезжаются молча.
//:
//: Сверх зон проверяем органы, которые не списки: кнопку заливки
//: областью и переключатель типа воды. Обе — свежие находки живого
//: прогона, обе оказались невидимы для тестов по исходнику.
const SELFCHECK_EXTRA = {
  "1d": ["кисть-область"],
  "1e": ["тип-воды"],
};

function selfcheckExpectations() {
  const expected = {};
  for (const [screenName, marks] of Object.entries(SELFCHECK_EXTRA)) {
    expected[screenName] = [...marks];
  }
  for (const [key2, rec] of Object.entries(ZONES)) {
    (expected[rec.экран] = expected[rec.экран] || []).push(`зона-${key2}`);
  }
  return expected;
}

//: ПОТОЛОК ОЖИДАНИЯ ЩЕДРЫЙ НАМЕРЕННО. Экраны оживают асинхронно, и
//: у валидатора это ещё и запрос к серверу: на шести секундах он не
//: успевал, и селфчек винил монтаж там, где виновата была его же
//: спешка. Ложная тревога хуже пропуска — по ней идут чинить целое.
function _selfcheckWait(check2, cap2 = 15000, step = 120) {
  return new Promise(ready2 => {
    const startedAt = Date.now();
    const tick2 = () => {
      if (check2() || Date.now() - startedAt > cap2) return ready2(check2());
      setTimeout(tick2, step);
    };
    tick2();
  });
}

async function selfcheck({ карта: mapRec = null } = {}) {
  const prev = state.screen;
  if (mapRec != null && Number(mapRec) !== Number(state.map)) {
    await openMap(Number(mapRec));
  }
  if (!state.map) {
    return { ok: false, note: "сперва откройте карту: селфчек({ карта: 63 })" };
  }
  const report = [];
  for (const [nm, marks] of Object.entries(selfcheckExpectations())) {
    if (!state.screens[nm]) {
      report.push({ экран: nm, ok: false, нет: ["экрана нет в дизайне"] });
      continue;
    }
    const missesBefore = state.промахи.length;
    showScreen(nm);
    await _selfcheckWait(() => marks.every(m2 =>
      document.querySelector(`#stage [data-lv="${m2}"]`)));
    const card = document.querySelector("#stage .dv-card");
    const missing = marks.filter(m2 =>
      !card?.querySelector(`[data-lv="${m2}"]`));
    //: битые картинки макета считаем отдельно: они видны человеку как
    //: «редактор сломан», даже когда всё остальное смонтировано
    const brokenCount = [...(card?.querySelectorAll("img[data-lv-макет]") || [])]
      .filter(i2 => i2.complete && i2.naturalWidth === 0 &&
                   i2.style.visibility !== "hidden").length;
    report.push({
      экран: nm, ok: !missing.length && !brokenCount, нет: missing,
      битыхКартинок: brokenCount,
      промахи: state.промахи.slice(missesBefore)
        .map(p2 => `${p2.где}: ${p2.что}`),
    });
  }
  if (prev) showScreen(prev);
  const badCount = report.filter(e2 => !e2.ok || e2.промахи.length);
  const result = { ok: !badCount.length, карта: state.map,
                 экранов: report.length, плохих: badCount.length, отчёт: report };
  console.table(report.map(e2 => ({
    экран: e2.экран, ok: e2.ok, "не подключено": e2.нет.join(", ") || "—",
    "битых картинок": e2.битыхКартинок,
    промахи: e2.промахи.join(" | ") || "—" })));
  status(result.ok
    ? `селфчек: все ${report.length} экранов смонтированы`
    : `селфчек: ${badCount.length} из ${report.length} экранов с изъяном — ` +
      `см. таблицу в консоли`);
  return result;
}

window.редактор = Object.assign(window.редактор || {}, { селфчек: selfcheck, state });
