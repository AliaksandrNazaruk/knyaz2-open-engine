// Соприсутствие: игроки на одной карте видят друг друга.
//
// ЭТО ПРИЗРАКИ, А НЕ ОБЩИЙ МИР. Каждый браузер по-прежнему считает свою игру
// целиком: своих жителей, свой лут, свои броски. Отсюда уходит наружу ТОЛЬКО
// поза самого игрока, а обратно приходят чужие позы. Чужой виден, но ударить
// его, обменяться с ним или помешать ему нельзя — и не должно быть можно,
// иначе миры разъедутся в первую же минуту.
//
// Общий мир требует сервера, который миром ВЛАДЕЕТ, — это отдельная большая
// работа (см. knyaz2/web/presence.py, там же разобрано почему).
//
// СЦЕНЫ БОЯ ЛИЧНЫЕ. Карты 26…32 и 44…54 движок выбирает жребием под конкретную
// встречу: это временные площадки, делить их не с кем. Сервер их и не сводит,
// но и клиент туда не пишет — незачем гонять кадры впустую.
import { world } from "./world.js";
import { hero } from "./hero.js";

//: Как часто отдавать свою позу. Считаем ПО ВРЕМЕНИ, а не по кадрам: кадры
//: у всех разные, и на быстром мониторе выходило по тридцать посылок в
//: секунду вместо нужных восьми.
const SEND_EVERY_MS = 120;

//: Сколько ждать до следующей попытки соединиться, по нарастающей.
const RETRY_MIN = 3000;
const RETRY_MAX = 60000;

//: Сцены встреч — у каждого свои (см. konung2/worldmap.py).
function privateMap(number) {
  const map = Number(number);
  return (map >= 26 && map <= 32) || (map >= 44 && map <= 54);
}

// Чужие игроки этой карты, в виде, годном отрисовщику юнитов. В список
// `units` они НЕ попадают намеренно: туда смотрят бой, приказы и память
// карты, и призрак стал бы для них настоящим.
export const ghosts = [];

const known = new Map();          // ident -> запись призрака
let socket = null;
let retry = RETRY_MIN;
let ticks = 0;              // время прошлой посылки
let lastSent = "";
let myMap = null;

function address() {
  const spot = window.location;
  // Своя разработка идёт на статике: сокет живёт отдельным портом. На сервере
  // его проксирует nginx тем же адресом, поэтому путь общий.
  if (spot.hostname === "127.0.0.1" || spot.hostname === "localhost") {
    return `ws://${spot.hostname}:8766`;
  }
  return `${spot.protocol === "https:" ? "wss" : "ws"}://${spot.host}/ws`;
}

//: Что показывать в табло: словами, а не кодом состояния.
function state() {
  if (!socket) return "нет связи";
  if (socket.readyState === WebSocket.CONNECTING) return "соединяюсь";
  if (socket.readyState === WebSocket.OPEN) return "на связи";
  return "связь рвётся";
}

function forget(ident) {
  const ghost = known.get(ident);
  if (!ghost) return;
  known.delete(ident);
  const at = ghosts.indexOf(ghost);
  if (at >= 0) ghosts.splice(at, 1);
}

function apply(ident, state) {
  let ghost = known.get(ident);
  if (!ghost) {
    // Призрак живёт по тем же полям, что и юнит, — иначе отрисовщик его не
    // поймёт. Лишнего не заводим: ни здоровья, ни стороны, ни приказов.
    //
    // СТОЙКА ОБЯЗАТЕЛЬНА. Кадр ищется как `animations[стойка][поза][сторона]`
    // (actor.js), и без неё поиск уходит в `animations[undefined]`, потом в
    // запасные «действия», где стояния и ходьбы нет вовсе. Кадра не находится,
    // и призрак числится рядом, но не рисуется — ровно это и было видно.
    ghost = { ghost: true, alive: true, insideSlot: null, stance: "peace",
              equipment: {}, bag: [], skills: [], pose: "stand", frame: 0,
              x: 0, y: 0, direction: 2, body: 0, palette: 0 };
    known.set(ident, ghost);
    ghosts.push(ghost);
  }
  if (Number.isFinite(state.x)) ghost.x = state.x;
  if (Number.isFinite(state.y)) ghost.y = state.y;
  if (Number.isFinite(state.d)) ghost.direction = state.d;
  if (Number.isFinite(state.f)) ghost.frame = state.f;
  if (Number.isFinite(state.b)) ghost.body = state.b;
  if (Number.isFinite(state.pal)) ghost.palette = state.pal;
  if (typeof state.p === "string") ghost.pose = state.p;
  if (state.st === "combat" || state.st === "peace") ghost.stance = state.st;
  if (typeof state.n === "string") ghost.name = state.n.slice(0, 24);
}

function connect() {
  if (socket) return;
  let live;
  try {
    live = new WebSocket(address());
  } catch {
    return;                            // адрес не годится — молча живём один
  }
  socket = live;
  live.addEventListener("open", () => { retry = RETRY_MIN; });
  live.addEventListener("message", (event) => {
    let packet;
    try { packet = JSON.parse(event.data); } catch { return; }
    if (packet.gone) { forget(packet.gone); return; }
    if (packet.id && packet.s) apply(packet.id, packet.s);
  });
  const bury = () => {
    if (socket !== live) return;
    socket = null;
    lastSent = "";
    ghosts.length = 0;
    known.clear();
    //: Пробуем снова, разводя попытки: сервер может быть просто выключен.
    setTimeout(connect, retry);
    retry = Math.min(RETRY_MAX, retry * 2);
  };
  live.addEventListener("close", bury);
  live.addEventListener("error", bury);
}

// Такт соприсутствия: посылаем свою позу, если она изменилась, и держим
// призраков только для текущей карты.
export function presenceTick(map) {
  const number = Number.isFinite(map) ? Number(map) : null;
  if (number !== myMap) {
    myMap = number;
    lastSent = "";
    //: Сменили карту — прежние соседи не наши; сервер пришлёт новых сам.
    ghosts.length = 0;
    known.clear();
  }
  if (number === null || privateMap(number)) return false;
  connect();
  if (!socket || socket.readyState !== WebSocket.OPEN) return false;
  const now = performance.now();
  if (now - ticks < SEND_EVERY_MS) return false;
  ticks = now;
  const packet = {
    m: number,
    x: Math.round(hero.x ?? 0), y: Math.round(hero.y ?? 0),
    d: hero.direction ?? 2, p: hero.pose ?? "stand", f: hero.frame ?? 0,
    b: hero.body ?? 0, pal: hero.palette ?? 0,
    //: Стойка нужна отрисовщику: наборы кадров у мира и боя разные.
    st: hero.stance === "combat" ? "combat" : "peace",
    n: world.map?.hero?.template?.name ?? "Путник",
  };
  const line = JSON.stringify(packet);
  //: Стоим на месте — молчим. Сеть от этого не устаёт, а сервер тем более.
  if (line === lastSent) return false;
  lastSent = line;
  try { socket.send(line); } catch { /* рвётся — переподключимся сами */ }
  return true;
}

// ВКЛЮЧАЕТСЯ ТОЛЬКО ОТДЕЛЬНОЙ СТРАНИЦЕЙ. Обычная игра этот модуль не грузит
// вовсе, и в ней ничего не меняется: в сцене стоит `world.ghosts ?? []`, а
// пока список никто не завёл, это пустая раскладка.
//
// Свой цикл кадров, а не врезка в главный: так опыт не трогает точку входа.
// Номер карты берём из самих данных — `world.map.legacy.map_number`.
export function presenceStart() {
  world.ghosts = ghosts;
  // ВИДИМЫЙ СЧЁТЧИК. Без него «сломалось» не отличить от «рядом никого»:
  // первое чинят, второе — зовут товарища на ту же карту.
  const табло = document.createElement("div");
  табло.id = "presence-badge";
  табло.style.cssText = "position:fixed;left:8px;bottom:8px;z-index:46;" +
    "padding:4px 9px;background:rgb(8 6 4 / .82);color:rgb(255 174 84);" +
    "border:1px solid rgb(215 183 95 / .45);font:12px/1.3 system-ui,sans-serif;" +
    "pointer-events:none;letter-spacing:.04em";
  document.body.append(табло);
  setInterval(() => {
    const карта = world.map?.legacy?.map_number;
    табло.textContent = `соприсутствие: ${state()}` +
      (карта == null ? " · карта не загружена"
                     : ` · карта ${карта} · рядом ${ghosts.length}`);
  }, 500);
  const шаг = () => {
    presenceTick(world.map?.legacy?.map_number ?? null);
    requestAnimationFrame(шаг);
  };
  requestAnimationFrame(шаг);
  return true;
}
