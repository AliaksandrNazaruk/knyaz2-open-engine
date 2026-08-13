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

const PICTURE = "/loading.webp";

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
    const image = new Image();
    image.src = PICTURE;
    await image.decode();
  } catch {
    return false;                 // не приехала — молча идём дальше
  }
  waiting();
  node.hidden = false;
  // Отдаём кадр браузеру, чтобы экран успел нарисоваться ДО того, как
  // зовущий займёт поток чтением карты.
  await new Promise((готово) => requestAnimationFrame(() => {
    requestAnimationFrame(готово);
  }));
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
  requestAnimationFrame(() => requestAnimationFrame(loadScreenHide));
}
