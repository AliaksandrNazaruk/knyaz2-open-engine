// Экран загрузки: одна картинка на все переходы и полоса хода внизу.
//
// В игре экранов было двадцать три, по одному на локацию (`PICS\M<номер>.RES`,
// VA 0x422CCC), и у большинства карт своего не было вовсе — движок тогда не
// показывал ничего. Здесь экран ОДИН и общий: он приезжает единожды за сеанс,
// дальше берётся из кэша браузера, и ни один переход больше не платит за
// картинку. Разбор оригинального формата остался в konung2/pics.py.
//
// ПОРЯДОК ЗДЕСЬ ГЛАВНОЕ. Локация — это шестьсот с лишним файлов. Если пустить
// их первыми, картинка встанет в очередь за ними и приедет тогда, когда уже не
// нужна. Поэтому `loadScreenShow` ЖДЁТ разбора картинки и одного кадра на
// отрисовку, и только потом зовущий берётся за карту.
import { world } from "./world.js";

// ВЕРСИЯ В АДРЕСЕ — ИНАЧЕ КАРТИНКУ НЕ СМЕНИТЬ. Файл на сервер доезжает, а
// игроку продолжает идти прежний: перед нами Cloudflare, и он держит свою
// копию, отвечая `cf-cache-status: REVALIDATED` со старыми long-modified и
// etag. Проверено числами: на диске сервера sha совпадал с нашим и файл был
// 178 510 байт, а отдавалось 206 750 — прошлая картина.
//
// Ресурсы пака от этого защищены версией в запросе (`?v=` от content id), а
// экран загрузки лежит среди файлов клиента, и своей версии у него не было.
// ПОДНИМАТЬ ПРИ КАЖДОЙ СМЕНЕ КАРТИНКИ — иначе игрок увидит прежнюю.
const PICTURE_VERSION = 3;
const PICTURE = `/loading.webp?v=${PICTURE_VERSION}`;

const node = document.getElementById("load-screen");
const bar = document.getElementById("load-progress");
const fill = bar?.querySelector("i") ?? null;
const label = document.getElementById("load-label");

//: Пока карта только читается, считать нечего — полоса ходит сама.
function waiting() {
  bar?.classList.add("waiting");
  if (fill) fill.style.width = "";
  if (label) label.textContent = "Загрузка…";
}

// Ход загрузки ресурсов. Сюда приходит `preload` (content.js) — она одна
// знает, сколько файлов у карты и сколько уже разобрано.
world.onAssetProgress = (loaded, total) => {
  if (!node || node.hidden || !total) return;
  bar?.classList.remove("waiting");
  if (fill) fill.style.width = `${Math.round(loaded * 100 / total)}%`;
  if (label) label.textContent = `Загрузка… ${loaded} из ${total}`;
};

export async function loadScreenShow() {
  if (!node) return false;
  try {
    // Ждём именно разбора, а не события `load`: после `decode` картинка
    // ложится в кадр без задержки на первой отрисовке. Со второго раза
    // это мгновенно — файл уже в кэше браузера.
    //
    // НО НЕ ЖДЁМ ЕГО У СКРЫТОЙ ВКЛАДКИ: decode() без кадров может не
    // завершиться НИКОГДА (замерено: загрузка «Продолжить» стояла на нём
    // вечно), поэтому разбор идёт наперегонки с таймером — проигрыш не
    // страшен, картинка дорисуется своим чередом.
    const image = new Image();
    image.src = PICTURE;
    await Promise.race([image.decode(),
                        new Promise((идём) => setTimeout(идём, 500))]);
  } catch {
    return false;                 // не приехала — молча идём дальше
  }
  waiting();
  node.hidden = false;
  // СКРЫТОЙ ВКЛАДКЕ КАДРОВ НЕ ПОЛОЖЕНО: requestAnimationFrame у неё молчит
  // вовсе (замерено: 2.5 с без единого кадра), и ожидание кадра ниже стояло
  // бы вечно — загрузка «Продолжить» замирала на «Читаю content pack» именно
  // здесь. Проверки видимости мало: в первые мгновения после навигации
  // вкладка ещё числится видимой, а кадров уже нет. Поэтому кадр ждётся
  // НАПЕРЕГОНКИ с таймером: видимой вкладке достаётся честная отрисовка
  // (кадр приходит за десятки миллисекунд), скрытой — короткая пауза.
  if (document.hidden) return true;
  await new Promise((готово) => {
    const срок = setTimeout(готово, 400);
    requestAnimationFrame(() => requestAnimationFrame(() => {
      clearTimeout(срок);
      готово();
    }));
  });
  return true;
}

export function loadScreenHide() {
  if (!node) return;
  node.hidden = true;
  waiting();
}

// Погасить, КОГДА КАДР СО СЦЕНОЙ УЖЕ НА ЭКРАНЕ.
//
// `render()` только рисует в холст — на экране это оказывается следующим
// кадром. Снимая картинку сразу, мы открываем пустую рамку на один кадр, и
// на глаз это заметно как мигание. Поэтому ждём отрисовки: первый
// requestAnimationFrame ставит нас в очередь текущего кадра, второй
// срабатывает уже после того, как он показан.
export function loadScreenDone() {
  if (!node || node.hidden) return;
  // Той же скрытой вкладке ждать нечего — экран гаснет сразу, иначе он
  // висел бы «показанным» до первого настоящего кадра.
  if (document.hidden) { loadScreenHide(); return; }
  requestAnimationFrame(() => requestAnimationFrame(loadScreenHide));
}

// ЩЕЛЧОК ПЕРЕД ПЕРЕХОДОМ И СТЫЧКОЙ.
//
// Локация уже готова, но сцена не начинается, пока игрок не нажмёт: иначе
// бой стартует раньше, чем он успел разглядеть, куда попал. При начальной
// загрузке этого нет — там щелчок уже был, в меню.
//
// ПОКА ЖДЁМ, МИР СТОИТ. `loadScreenHolding` спрашивает кадровый цикл
// (app.js), и такт не двигается вовсе — как при открытом меню. Иначе
// «продолжить» теряло бы смысл: за время разглядывания тварь успела бы
// подойти.
//
//: Побочная польза: этот щелчок — первое действие игрока на странице, и он
//: же снимает запрет браузера на звук. Без него AudioContext оставался
//: запертым до первого клика по миру (sound.js:133).
const continueNode = document.getElementById("load-continue");
let holding = false;

export function loadScreenHolding() {
  return holding;
}

export function loadScreenAwaitClick() {
  if (!node || node.hidden || !continueNode) {
    loadScreenDone();
    return Promise.resolve();
  }
  //: Скрытой вкладке щёлкать некому — там ждать нечего, гасим как обычно.
  if (document.hidden) { loadScreenHide(); return Promise.resolve(); }
  holding = true;
  continueNode.hidden = false;
  return new Promise((готово) => {
    const снять = () => {
      node.removeEventListener("pointerdown", снять);
      window.removeEventListener("keydown", снять);
      holding = false;
      continueNode.hidden = true;
      loadScreenHide();
      готово();
    };
    node.addEventListener("pointerdown", снять);
    window.addEventListener("keydown", снять);
  });
}
