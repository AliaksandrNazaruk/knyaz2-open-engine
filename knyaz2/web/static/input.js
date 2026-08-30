// Ввод: клавиши героя, перетаскивание камеры, зум, флажки панели.
import { canvas, clockMoonNode, clockRunNode, clockTimeNode, combatStanceNode,
         cursorNode, debugGroundNode, debugObjectsNode, dynamicShadowsNode,
         showRoofsNode } from "./dom.js";
import { cameraFollow, clampCamera, screenToWorld, updateZoom, zoomClamp,
         view } from "./viewport.js";
import { daylight, daylightSet } from "./daylight.js";
import { edgeScroll, hero, heroCellAt, heroOrderTo, keys } from "./hero.js";
import { heroCast, heroCastAt, orderAt } from "./combat.js";
import { beltToggle, panelToHero, panelUnit, pressButton,
         refresh as refreshUi } from "./ui.js";
import { orderKinds, orderSelected, select as selectUnit,
         selectBand } from "./orders.js";
import { world } from "./world.js";
import { trade } from "./trade.js";
import { unitAt, units } from "./units.js";
import { actorPoseKnown } from "./actor.js";
//: `view` уже пришёл из viewport.js строкой выше — второй такой же
//: биндинг это SyntaxError модуля, и клиент не грузился вовсе
import { band } from "./viewport.js";
import { updateDebugInfo } from "./debug.js";
import { render } from "./scene.js";
import { cursorApply, hintAt } from "./cursors.js";
import { carryCancel, carrying } from "./carry.js";
import { runAlways } from "./settings.js";

window.addEventListener("keydown", (event) => {
  if (["KeyW", "KeyA", "KeyS", "KeyD", "ArrowUp", "ArrowDown",
       "ArrowLeft", "ArrowRight"].includes(event.code)) {
    keys.add(event.code);
    hero.target = null;
    hero.goal = null;
    hero.path = [];
    hero.running = false;
    event.preventDefault();
  }
});

window.addEventListener("keyup", (event) => keys.delete(event.code));

//: Куда шёл прошлый приказ — по нему видно, повтор это или новая точка.
let lastGoal = null;

//: Подпись под курсором и то, что стояло в строке до неё.
let lastHint = null;

//: Табличка у курсора. Живёт своим узлом, а не строкой состояния: та занята
//: сообщениями игры, и наведение прежде их затирало.
const tipNode = document.getElementById("ui-tip");
//: Отступ, чтобы табличка не легла ПОД сам курсор и не мешала целиться.
const TIP_GAP = 14;

function tipShow(clientX, clientY) {
  if (!tipNode || tipNode.hidden) return;
  const box = tipNode.getBoundingClientRect();
  // У правого и нижнего края переносим табличку на другую сторону курсора,
  // иначе её обрезало бы окном.
  const x = clientX + TIP_GAP + box.width > window.innerWidth
    ? clientX - TIP_GAP - box.width : clientX + TIP_GAP;
  const y = clientY + TIP_GAP + box.height > window.innerHeight
    ? clientY - TIP_GAP - box.height : clientY + TIP_GAP;
  tipNode.style.left = `${Math.max(0, x)}px`;
  tipNode.style.top = `${Math.max(0, y)}px`;
}

function tipHide() {
  lastHint = null;
  if (tipNode) tipNode.hidden = true;
}

//: Взведён ли режим копки — его ставит применение Лопаты (см. carryTrinket).
let digging = false;
world.digMode = (on = true) => { digging = Boolean(on); };

// Приказ идти: движок различает режимы движения, и режим 1 ставит бит бега
// (VA 0x416641). Одиночный клик — шаг, двойной — бег.
//
// СПАМ ЩЕЛЧКАМИ ДЕРЖИТ БЕГ — отступление от канона, сделанное намеренно.
//
// Браузер на каждую пару щелчков шлёт `click, click, dblclick`, и одиночные
// гасят бег между двойными. В движке ровно то же чередование: ветка 0x401
// снимает бит `юнит[0x19] &= 0x7F`, а двойной щелчок 0x203 его ставит
// (FUN_0042F22C). Поэтому спам в оригинале и удерживает ходьбу.
//
// Меняем на удобное: повтор приказа В ТУ ЖЕ КЛЕТКУ бег не гасит. Щелчок по
// другой точке возвращает ходьбу, как и раньше.
function heroOrderMove(event, running) {
  if (!hero.data) return;
  // ПОКА ОТКРЫТ ЭКРАН, МИР ЩЕЛЧКОВ НЕ ПРИНИМАЕТ.
  //
  // В движке это не проверка, а устройство: попадание мыши разбирает
  // FUN_0043AEF0 через `switch(_DAT_008495F0)`, и код мира (0) отдаёт
  // РОВНО ветка `default` — состояние 0, сама игра. Разговор (состояние 1)
  // возвращает −1 всему, что не попало в прямоугольник варианта ответа;
  // обмен (7), лист персонажа (3), карта мира (5) и создание (2) мира тоже
  // не отдают. Приказа поэтому не выходит вовсе.
  //
  // У нас разговор — полоска внизу, а не картинка во весь экран, и холст
  // под ней оставался живым: собеседник обещал набить лицо, а игрок в это
  // время уходил из лагеря, не закрывая разговора.
  if (screenBlocksWorld()) return;
  const point = screenToWorld(event.clientX, event.clientY);
  const cell = heroCellAt(point.x, point.y);
  // РЕЖИМ КОПКИ. Лопата не тратится, а переводит курсор в особое состояние
  // (в движке `_DAT_00849650 = 5`), и следующий щелчок по ЛЮБОЙ клетке шлёт
  // туда приказ 3 «обыскать» — видеть спрятанную кучу не нужно:
  //
  //     cmp dword ptr [0x849650], 5
  //     ... экран -> клетка (FUN_0043B9B0) ...
  //     push 3;  call 0x4240BC          ; приказ всему выбору
  //
  //: Гасим режим первым же щелчком. В движке курсор держится, пока его не
  //: собьёт другое действие; одноразовость — наша, чтобы копка не липла.
  if (digging) {
    digging = false;
    orderSelected(cell.row, cell.col, orderKinds().take);
    refreshUi();
    view.dirty = true;
    return;
  }
  const repeat = lastGoal && lastGoal.row === cell.row && lastGoal.col === cell.col;
  lastGoal = cell;
  //: «Всегда бегом» — настройка игрока, по умолчанию поднятая на сенсорном
  //: экране (settings.js). Бег всё равно берётся не даром: перегруженного
  //: юнита не пускает `unitCanRun`, ровно как в движке.
  running = running || runAlways() || Boolean(repeat && hero.running);
  // Щелчок разбирается по канону движка, а клавиша-добавка решает, менять
  // выбор или дополнять (VA 0x423F80 смотрит флаг 0x849608).
  // Ctrl — «заговорить со своим» (0x8495AC), Shift — «добавить к выбору»
  // (0x849608). Оба флага движок держит по виртуальным клавишам 0x11 и 0x10.
  //: Кнопка «заговорить» на панели держит тот же флаг, что и клавиша: на
  //: сенсорном экране Ctrl зажать нечем (ui.js, ACTIONS.talk_mode).
  orderAt(point.x, point.y, running, event.shiftKey,
          event.ctrlKey || world.talkMode === true);
  //: Кадр ЗАКАЗЫВАЕМ. Синхронная отрисовка прямо здесь стоила 30 мс на
  //: щелчок и 46 на двойной (замер трейса), причём поверх той, что и так
  //: идёт из кадрового цикла. Круг под юнитом появится следующим кадром,
  //: то есть не позже шестнадцати миллисекунд — на глаз это то же самое.
  // Щелчок мог сменить выбор — а значит и круг под юнитом, и содержимое
  // панели. Без этого выбор менялся молча: новый круг появлялся только
  // со следующим кадром, а панель не обновлялась вовсе.
  refreshUi();
  view.dirty = true;
}

// ДВОЙНОЕ КАСАНИЕ СЧИТАЕМ САМИ.
//
// У мыши двойной щелчок отбивает браузер, и меру времени ему задаёт система —
// там всё работает. С пальца `dblclick` приходит как повезёт: часть браузеров
// не шлёт его по касаниям вовсе, а часть перестаёт после `setPointerCapture`,
// который мы ставим на каждом нажатии ради протяжки. Бег с телефона поэтому
// не включался никак.
//
// Пара касаний ловится теми же мерками, что и мышиный двойной щелчок: два
// подряд, в срок и в одно место. Допуск по месту — пиксели ЭКРАНА, а не
// клетки: палец во второй раз в ту же точку не попадает, промах в пару
// десятков пикселей для него обычное дело.
const TAP_GAP_MS = 400;
const TAP_SLIP = 24;
let lastTap = null;

// Тип указателя здесь НЕ спрашивается намеренно. Часть браузеров помечает
// касание как «мышь» в совместимых событиях, и проверка `pointerType` тихо
// выключала бы бег ровно там, где он и нужен. Мыши общий счёт не мешает: два
// щелчка в одно место подряд — это и есть двойной щелчок, тот же приказ, что
// пришёл бы из `dblclick`. Медленную пару (система разрешает и полсекунды)
// по-прежнему ловит сам `dblclick`.
function tapIsDouble(event) {
  const near = lastTap && event.timeStamp - lastTap.time < TAP_GAP_MS &&
    Math.abs(event.clientX - lastTap.x) < TAP_SLIP &&
    Math.abs(event.clientY - lastTap.y) < TAP_SLIP;
  //: Сложившаяся пара закрывается: третье касание начинает новую, а не
  //: тянет бег дальше — держит его повтор приказа в ту же клетку.
  lastTap = near ? null
    : { time: event.timeStamp, x: event.clientX, y: event.clientY };
  return Boolean(near);
}

canvas.addEventListener("click", (event) => {
  if (view.dragged) return;                    // перетаскивание камеры — не приказ
  heroOrderMove(event, tapIsDouble(event));
});

canvas.addEventListener("dblclick", (event) => heroOrderMove(event, true));

// ПРАВАЯ КНОПКА ПО МИРУ — ИГРЕ, А НЕ БРАУЗЕРУ.
//
// Меню браузера я гасил только на ячейках интерфейса, и по самой карте
// вылезало «Copy / Select All». В игре второй кнопки для окна нет вовсе:
// сообщение 0x204 идёт в FUN_00422AFC (VA 0x42F22C), и по миру (код попадания
// 0) оно делает ровно два дела —
//
//   вещь в руке -> FUN_0042944C(1): перенос отменяется;
//   рука пуста  -> обнуляет 0x24 байта у 0x840B94, кладёт туда игрока и зовёт
//                  FUN_00420644(игрок) — панель персонажа возвращается герою,
//                  а смещение пояса и гнездо смешивания сбрасываются.
canvas.addEventListener("contextmenu", (event) => {
  event.preventDefault();
  // ТАСКАНИЕ КАМЕРЫ — НЕ ЩЕЛЧОК. Правой кнопкой у нас возят камеру (левая
  // занята рамкой выделения), а `contextmenu` приходит на её ОТПУСКАНИИ — и
  // прежде каждый проезд по карте заканчивался тем, что выбор сбрасывался на
  // главного, а панель уезжала к нему же. У левой кнопки такая проверка
  // стоит с самого начала («перетаскивание камеры — не приказ»), правой её
  // просто забыли дать.
  if (view.dragged) return;
  //: И правая по миру тоже молчит при открытом экране: код попадания там
  //: не ноль, а −1 (FUN_0043AEF0), и ветка мира в 0x422AFC не заводится.
  if (screenBlocksWorld()) return;
  if (carrying()) { carryCancel(); refreshUi(); view.dirty = true; return; }
  //: ПРАВАЯ КНОПКА У ЧАРОДЕЯ — ОГОНЬ В СТОРОНУ, как в Diablo: летит, куда
  //: послали, и жжёт первого встречного. Канонного героя это не касается
  //: вовсе: позы `cast` у кадров HEROES.RES нет, и ветка не срабатывает,
  //: так что «панель игроку» правой кнопкой работает как работала.
  if (actorPoseKnown(hero, "cast")) {
    const point = screenToWorld(event.clientX, event.clientY);
    const said = heroCastAt(point.x, point.y);
    if (said !== "каст") console.info(`каст: ${said}`);
    view.dirty = true;
    return;
  }
  // ВЫДЕЛЯЕТСЯ ГЛАВНЫЙ. Движок кладёт указатель панели на игрока
  // (0x420644: `_DAT_00849514 = _DAT_00840B94`, а туда 0x422AFC только что
  // положил самого игрока). У нас панель ВЫВОДИТСЯ из выбора, поэтому «панель
  // игроку» и значит «выбран один главный» — так это и выглядит в оригинале.
  selectUnit(hero);
  panelToHero();
  refreshUi();
  view.dirty = true;
});

// Стойка — бит 0x04 байта unit+0x19. В движке её переключает бой; пока боя
// нет, даём переключатель, чтобы видеть оба набора анимаций.
combatStanceNode.addEventListener("change", () => {
  hero.stance = combatStanceNode.checked ? "combat" : "peace";
  render();
});

clockTimeNode.addEventListener("input", () => {
  clockRunNode.checked = false;
  daylightSet(Number(clockTimeNode.value));
  render();
});

clockMoonNode.addEventListener("change", () => { daylightSet(daylight.time); render(); });

dynamicShadowsNode.addEventListener("change", render);

// ЩИПОК ДВУМЯ ПАЛЬЦАМИ — масштаб, как колесом мыши.
//
// Пальцев на экране может быть сколько угодно, поэтому держим их всех
// поимённо: без списка не отличить «повёл одним» от «свёл двумя». Как только
// вторая точка легла на холст, всё остальное отменяется — и рамка выбора, и
// протяжка камеры: холст на это время принадлежит щипку.
//
// Мерка та же, что у колеса (ниже): мировая точка под ЯКОРЕМ остаётся на
// месте. Якорь у колеса — курсор, здесь — середина между пальцами, и потому
// щипок заодно и возит карту: сместили середину — уехала и она.
const pointers = new Map();
let pinch = null;

function pinchSpan() {
  const [a, b] = [...pointers.values()];
  return { span: Math.hypot(a.x - b.x, a.y - b.y),
           x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
}

function pinchStart() {
  // Холст занят щипком: рамку снимаем, протяжку тоже, а `dragged` взводим,
  // чтобы `click` после снятия пальцев не ушёл приказом идти. Делается это
  // ДО замера: даже если пальцы легли в одну точку и мерить пока нечего,
  // рамке уже не место — двумя пальцами её не тянут.
  band.active = false;
  view.dragging = false;
  view.dragged = true;
  canvas.classList.remove("dragging");
  const now = pinchSpan();
  if (now.span < 1) return;               // пальцы в одной точке — ждём, разойдутся
  pinch = { span: now.span, zoom: view.zoom };
}

// ОДНА ТОЧКА СМЕНЫ МАСШТАБА — и для колеса, и для щипка.
//
// Обычно масштаб меняется вокруг ЯКОРЯ: мировая точка под ним остаётся на
// месте. Якорь у колеса — курсор, у щипка — середина между пальцами; оттого
// щипок заодно и возит карту.
//
// НО КОГДА КАМЕРА ПРИВЯЗАНА К ВЫБРАННОМУ ЛИЦУ, якорь только один — само лицо.
// Камеру там всё равно каждый кадр возвращает слежение (app.js), и попытка
// встать по пальцам давала бы дрожь: зум уводит, слежение возвращает. Поэтому
// при привязке меняем ТОЛЬКО масштаб, а середину держит слежение — персонаж
// остаётся в центре и при зуме.
function zoomTo(next, anchorX, anchorY) {
  const before = screenToWorld(anchorX, anchorY);
  const rect = canvas.getBoundingClientRect();
  // Отдалять дальше, чем позволяет сама карта, нельзя: предел считает
  // `zoomClamp` по её рамке, чтобы за краем не открылась пустота.
  view.zoom = zoomClamp(next);
  if (view.follow) {
    // Центр берём тут же, а не ждём такта: иначе этот кадр нарисовался бы со
    // старой камерой и новым масштабом — на щипке это видно дрожью.
    cameraFollow(panelUnit());
  } else {
    view.cameraX = before.x - (anchorX - rect.left - view.width / 2) / view.zoom;
    view.cameraY = before.y - (anchorY - rect.top - view.height / 2) / view.zoom;
  }
  // Зум меняет видимую половину, поэтому рамку надо пересчитать и здесь:
  // отъехав, камера иначе показала бы пустоту за краем карты.
  clampCamera();
  updateZoom();
  //: Зум тоже только заказывает кадр: 48 мс на одно движение колеса
  //: (замер трейса) — это перепечка земли под новый масштаб плюс полная
  //: сборка сцены, и делать её по каждому щелчку колеса незачем.
  view.dirty = true;
}

function pinchMove() {
  if (pointers.size !== 2) return;
  const now = pinchSpan();
  if (now.span < 1) return;
  zoomTo(pinch.zoom * (now.span / pinch.span), now.x, now.y);
}

//: Тот же гейт, что у приказа: пока идёт разговор или открыт обмен, холст
//: не ловит ни приказ, ни рамку выбора (FUN_0043AEF0, ветки 1 и 7).
export function screenBlocksWorld() {
  return Boolean(world.talking || trade.open);
}

canvas.addEventListener("pointerdown", (event) => {
  pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
  view.pointerX = event.clientX;
  view.pointerY = event.clientY;
  view.dragged = false;
  if (pointers.size >= 2) {
    pinchStart();
    canvas.setPointerCapture(event.pointerId);
    return;
  }
  //: Левая кнопка при открытом экране не делает НИЧЕГО: ни рамки, ни
  //: перетаскивания камеры — второе иначе досталось бы ей по «иначе».
  if (event.button === 0 && screenBlocksWorld()) {
    canvas.setPointerCapture(event.pointerId);
    return;
  }
  if (event.button === 0) {
    const point = screenToWorld(event.clientX, event.clientY);
    band.active = true;
    band.addMode = event.shiftKey;
    band.fromX = point.x;
    band.fromY = point.y;
    band.toX = point.x;
    band.toY = point.y;
  } else if (!view.follow) {
    // Привязанную камеру таскать нельзя: следующий же кадр вернёт её на
    // выбранного, и вышло бы дёрганье вместо прокрутки.
    view.dragging = true;
    canvas.classList.add("dragging");
  }
  canvas.setPointerCapture(event.pointerId);
});

canvas.addEventListener("pointermove", (event) => {
  if (pointers.has(event.pointerId)) {
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
  }
  //: Пальцы легли в одну точку — мерить было нечего; ждали, пока разойдутся.
  if (!pinch && pointers.size >= 2) pinchStart();
  //: Пока идёт щипок, холст занят им одним: ни рамки, ни курсора, ни
  //: подсказок — иначе второй палец успевал бы выдать приказ.
  if (pinch) { pinchMove(); return; }
  if (band.active) {
    const point = screenToWorld(event.clientX, event.clientY);
    band.toX = point.x;
    band.toY = point.y;
    if (Math.abs(event.clientX - view.pointerX) + Math.abs(event.clientY - view.pointerY) > 3) {
      view.dragged = true;
    }
    view.dirty = true;
  }
  if (view.dragging) {
    if (Math.abs(event.clientX - view.pointerX) + Math.abs(event.clientY - view.pointerY) > 3) {
      view.dragged = true;
    }
    view.cameraX -= (event.clientX - view.pointerX) / view.zoom;
    view.cameraY -= (event.clientY - view.pointerY) / view.zoom;
    clampCamera();
    view.pointerX = event.clientX;
    view.pointerY = event.clientY;
    view.dirty = true;
  }
  //: Краевую прокрутку здесь больше не считаем: её точку ведёт слушатель на
  //: ОКНЕ (см. ниже). Иначе владельцев два, и пояс с панелью отбирают у
  //: камеры целые стороны.
  const point = screenToWorld(event.clientX, event.clientY);
  // Курсор выбирается по тому, что под мышью, — как в движке.
  cursorApply(canvas, point.x, point.y);
  // И подпись рядом с ним: имя юнита, «Здесь что-то хранится» у сундука,
  // куда ведёт переход. В движке это отдельный разбор той же точки
  // (VA 0x420E88), и главный цикл зовёт его каждый кадр.
  //
  //: ТАБЛИЧКА ИДЁТ ЗА КУРСОРОМ, а не лежит в строке состояния. Движок держит
  //: её полосой внизу (0x432A44) и гасит через двенадцать тактов (0x84972C),
  //: но у него и разрешение одно на всех; у нас окно любого размера, и у
  //: курсора подпись видно сразу — как у подсказки вещи.
  //:
  //: Заодно это развело две разные вещи, которые прежде делили один узел:
  //: наведение затирало сообщение игры («Засада!») и потом восстанавливало
  //: его из запомненного. Теперь сообщения живут в полосе, подпись — здесь.
  const hint = hintAt(point.x, point.y);
  if (hint !== lastHint) {
    tipNode.hidden = !hint;
    if (hint) tipNode.textContent = hint;
    lastHint = hint;
  }
  if (hint) tipShow(event.clientX, event.clientY);
  cursorNode.textContent = `Мировая точка: ${Math.round(point.x)}, ${Math.round(point.y)}`;
  updateDebugInfo(point);
});

function endDrag(event) {
  pointers.delete(event.pointerId);
  // Щипок кончается, как только пальцев стало меньше двух. Оставшийся палец
  // НЕ подхватывает протяжку: он лежит на холсте с начала щипка, и считать
  // его новым жестом неоткуда — новый начнётся со следующего касания.
  if (pinch && pointers.size < 2) {
    pinch = null;
    view.dragging = false;
    canvas.classList.remove("dragging");
    if (canvas.hasPointerCapture(event.pointerId)) {
      canvas.releasePointerCapture(event.pointerId);
    }
    return;
  }
  //: Пальцев всё ещё двое или больше — значит, снялся лишний, и мерку надо
  //: переснять: старая была взята по другой паре, и масштаб бы прыгнул.
  if (pinch) { pinchStart(); return; }
  if (band.active) {
    band.active = false;
    // Протяжка длиной меньше трёх пикселей — это щелчок, его разбирает
    // обработчик click; рамкой считаем только настоящее движение.
    if (view.dragged) {
      const box = {
        left: Math.min(band.fromX, band.toX), right: Math.max(band.fromX, band.toX),
        top: Math.min(band.fromY, band.toY), bottom: Math.max(band.fromY, band.toY),
      };
      selectBand([hero, ...units], box, band.addMode);
      refreshUi();
      render();
    }
  }
  view.dragging = false;
  canvas.classList.remove("dragging");
  if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
}

canvas.addEventListener("pointerup", endDrag);

canvas.addEventListener("pointercancel", endDrag);

canvas.addEventListener("wheel", (event) => {
  event.preventDefault();
  zoomTo(view.zoom * Math.exp(-event.deltaY * 0.001), event.clientX, event.clientY);
  view.dirty = true;
}, { passive: false });

for (const control of [showRoofsNode, debugGroundNode, debugObjectsNode]) {
  control.addEventListener("change", render);
}

window.addEventListener("keydown", (event) => {
  if (event.key.toLowerCase() !== "d" || event.repeat) return;
  const enabled = !(debugGroundNode.checked || debugObjectsNode.checked);
  debugGroundNode.checked = enabled;
  debugObjectsNode.checked = enabled;
  render();
});


// Клавиши панели — те же, что в оригинале: подсказки движка называют их
// «Все ко мне (F)», «Карта (M)», «Достать/Убрать оружие (Пробел)»,
// «Атаковать (A)», «Информация к размышлению (Q)», «Панель персонажа (I)».
const PANEL_KEYS = {
  KeyF: "call_party", KeyM: "map", Space: "toggle_weapon",
  KeyA: "attack", KeyQ: "journal", KeyI: "character",
};

window.addEventListener("keydown", (event) => {
  const action = PANEL_KEYS[event.code];
  if (!action || event.repeat) return;
  event.preventDefault();
  pressButton(action);
});

// КАСТ — клавиша C. Канонных клавиш она не занимает: у панели заняты
// F, M, Пробел, A, Q, I, у отладки D, у пояса Ё.
//
// Цель берётся из-под курсора тем же попиксельным попаданием, что и щелчок
// (unitAt), а если под курсором пусто — ближайший чужой в дальности каста.
window.addEventListener("keydown", (event) => {
  if (event.code !== "KeyC" || event.repeat) return;
  if (event.ctrlKey || event.altKey || event.metaKey) return;
  if (world.talking || trade.open) return;
  event.preventDefault();
  const point = screenToWorld(view.pointerX, view.pointerY);
  const under = unitAt(point.x, point.y);
  const target = under && under !== hero ? under : nearestFoe();
  const said = heroCast(target);
  if (said !== "каст") console.info(`каст: ${said}`);
});

//: Ближайший чужой живой — на случай, когда курсор ни на кого не показывает.
//: СВОЙ — ЭТО СОЮЗНИК ИЛИ ОДНА СТОРОНА, и проверять надо оба: наёмник
//: стоит в своём отряде (сторона другая), а бить его нельзя. Тем же
//: правилом живут курсор (cursors.js) и приказы боя.
function nearestFoe() {
  let best = null;
  let bestRange = Infinity;
  for (const unit of units) {
    if (!unit?.alive || unit === hero) continue;
    if (unit.ally || (unit.side ?? 0) === (hero.side ?? 0)) continue;
    const range = Math.hypot(unit.x - hero.x, unit.y - hero.y);
    if (range < bestRange) { best = unit; bestRange = range; }
  }
  return best;
}

// Ё/~ ПРЯЧЕТ И ПОКАЗЫВАЕТ ПОЯС (VA 0x437FF8:220, клавиша 0xC0 = VK_OEM_3).
// Ветка движка живёт только в режиме экрана 0 — в самой игре, — поэтому и
// здесь клавиша молчит, пока открыт разговор, обмен или меню.
window.addEventListener("keydown", (event) => {
  if (event.code !== "Backquote" || event.repeat) return;
  if (event.ctrlKey || event.altKey || event.metaKey) return;
  if (world.talking || trade.open) return;
  event.preventDefault();
  beltToggle();
});

//: Где сейчас курсор в окне — по нему камера ползёт у края (VA 0x437CD0).
export const edge = { x: 0, y: 0, width: 0, height: 0, inside: false };

// Такт прокрутки: пока курсор у самого края, камера едет. Зовётся из
// главного цикла, как и в движке.
export function edgeScrollTick() {
  if (!edge.inside || view.dragging || band.active) return false;
  //: Камерой владеет кто-то один. Пока она привязана к выбранному лицу,
  //: краевая прокрутка молчит: иначе они каждый кадр тянули бы её врозь.
  if (view.follow) return false;
  return edgeScroll(edge.x, edge.y, edge.width, edge.height);
}

// КРАЙ МЕРЯЕТСЯ ОТ ВСЕГО ОКНА, А НЕ ОТ ХОЛСТА (VA 0x437CD0):
//
//     if (мышьX == 0)     ... влево  на 0x39
//     if (мышьX == 0x3ff) ... вправо на 0x39
//     if (мышьY == 0)     ... вверх  на 0x20
//     if (мышьY == 0x2ff) ... вниз   на 0x20
//
// 0x3FF и 0x2FF — это 1023 и 767, то есть края экрана 1024x768 ЦЕЛИКОМ, вместе
// с полосой интерфейса. Движку всё равно, что лежит под курсором.
//
// У нас точку вёл обработчик на холсте, а `pointerleave` гасил её, едва курсор
// заходил на пояс или боковую панель. Панель стоит колонкой слева, пояс лежит
// поверх низа — и до крайних пикселей холста мышью было не добраться вовсе.
// Отсюда «экран не двигается влево и вниз»: не работали ровно те стороны, где
// эти двое и находятся.
window.addEventListener("pointermove", (event) => {
  edge.x = event.clientX;
  edge.y = event.clientY;
  edge.width = window.innerWidth;
  edge.height = window.innerHeight;
  edge.inside = true;
}, { passive: true });

// Курсор ушёл из окна (а не просто с холста) — прокрутка останавливается.
// `relatedTarget` пуст только когда указатель покинул документ целиком.
window.addEventListener("pointerout", (event) => {
  if (!event.relatedTarget) { edge.inside = false; tipHide(); }
}, { passive: true });
//: Ушёл с холста на панель или пояс — подписи там нечего подписывать.
canvas.addEventListener("pointerleave", tipHide);
window.addEventListener("blur", () => { edge.inside = false; });
