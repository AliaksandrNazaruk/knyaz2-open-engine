// Поля, которые пишут, а никто не читает.
//
//     node tools/write_only_fields.js
//
// Третий вид мусора после мёртвого экспорта и пустышек, и самый незаметный:
// поле исправно вычисляется и присваивается каждый кадр, но его никто не
// спрашивает. Такое остаётся, когда потребителя убрали, а писателя забыли —
// и стоит оно не только памяти: читающий код верит, что поле зачем-то нужно,
// и боится его тронуть.
//
// СЧИТАЕМ ГРУБО. Присваивания — `что-то.имя =` (кроме `==`, `=>` и прочих
// сравнений). Чтения — любое другое упоминание `.имя`, а также строковый ключ
// `"имя"` или `'имя'`: поля уезжают в сохранение и в снимок агента именно
// строками, и без этого средство обвинило бы половину сейва.
//
// Смотрим ВЕСЬ репозиторий, а не только клиент: поле может писаться в
// клиенте, а читаться в тесте или в стенде.
import { readFileSync, readdirSync, statSync } from "node:fs";

const КОРНИ = ["knyaz2/web/static", "tools", "tests"];
const РАСШИРЕНИЯ = [".js", ".py", ".html"];

function собрать(путь, из = []) {
  for (const имя of readdirSync(путь)) {
    if (имя === "__pycache__" || имя === "menu") continue;
    const полный = `${путь}/${имя}`;
    if (statSync(полный).isDirectory()) собрать(полный, из);
    else if (РАСШИРЕНИЯ.some((р) => имя.endsWith(р))) из.push(полный);
  }
  return из;
}

const файлы = КОРНИ.flatMap((к) => собрать(к));
const тексты = new Map(файлы.map((п) => [п, readFileSync(п, "utf8")]));

//: Куда пишут: `.имя =`, но не `==`, `===`, `=>`.
const ПИШУТ = /\.([a-zA-Z_$][\w$]*)\s*=(?![=>])/g;
//: Чтения: любое `.имя` не перед `=`, плюс строковый ключ.
const ЧИТАЮТ = /\.([a-zA-Z_$][\w$]*)\s*(?!\s*=(?![=>]))/g;
const КЛЮЧИ = /["']([a-zA-Z_$][\w$]*)["']/g;

const пишут = new Map();     // имя -> где писали
const читают = new Set();

for (const [путь, текст] of тексты) {
  //: Комментарии выкидываем: в них поля упоминаются как объяснение, а не
  //: как чтение, и живого потребителя это не доказывает.
  const код = текст
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/(^|[^:])\/\/[^\n]*/g, "$1 ")
    .replace(/^\s*#.*$/gm, " ");
  for (const m of код.matchAll(ПИШУТ)) {
    if (!пишут.has(m[1])) пишут.set(m[1], new Set());
    пишут.get(m[1]).add(путь.split("/").pop());
  }
  //: Чтения ищем по тексту БЕЗ присваиваний — иначе левая часть `a.b = 1`
  //: сама себя и зачтёт.
  const безПрисваиваний = код.replace(ПИШУТ, ".");
  for (const m of безПрисваиваний.matchAll(ЧИТАЮТ)) читают.add(m[1]);
  for (const m of код.matchAll(КЛЮЧИ)) читают.add(m[1]);
}

//: Свойства браузера и наши служебные — не наши поля, их писать законно.
const ЧУЖИЕ = new Set([
  "width", "height", "src", "alt", "title", "className", "hidden", "checked",
  "value", "textContent", "innerHTML", "onclick", "onload", "onerror",
  "onmessage", "style", "left", "top", "right", "bottom", "display",
  "backgroundImage", "backgroundSize", "backgroundRepeat", "cssText", "href",
  "rel", "type", "id", "name", "disabled", "selected", "length", "current",
  "globalAlpha", "globalCompositeOperation", "fillStyle", "strokeStyle",
  "lineWidth", "font", "textAlign", "textBaseline", "filter", "volume",
  "currentTime", "loop", "muted", "playbackRate", "crossOrigin", "async",
  "defer", "tabIndex", "ariaLabel", "role", "min", "max", "step", "placeholder",
  "imageRendering", "transform", "opacity", "zIndex", "position", "cursor",
  "pointerEvents", "visibility", "overflow", "padding", "margin", "border",
  "gap", "flex", "order", "content", "background", "color", "maxWidth",
  "maxHeight", "minWidth", "minHeight", "innerText", "onpointerdown",
  "onkeydown", "onchange", "oninput", "capture", "passive", "once", "signal",
]);

const только_пишут = [...пишут.keys()]
  .filter((имя) => !читают.has(имя) && !ЧУЖИЕ.has(имя))
  .sort();

for (const имя of только_пишут) {
  console.log(`${имя} — пишут в ${[...пишут.get(имя)].join(", ")}`);
}
console.log(только_пишут.length
  ? `\nполей пишут и не читают: ${только_пишут.length}`
  : "\nвсё, что пишется, кем-то читается");
process.exit(0);
