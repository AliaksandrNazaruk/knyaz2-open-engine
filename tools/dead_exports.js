// Что экспортируется и никем не зовётся.
//
//     node tools/dead_exports.js
//
// Ищем в knyaz2/web/static: экспорт, который не импортирован ни одним другим
// модулем, не выставлен наружу через `window.knyaz2` и не используется внутри
// своего же файла. Такой экспорт — либо забытая ветка, либо остаток снятой
// подсистемы; в git он всё равно останется, а в голове мешать перестанет.
//
// СЧИТАЕМ ГРУБО И НАМЕРЕННО. Разбирать JS по-настоящему тут незачем: цель —
// список кандидатов на удаление, который человек просмотрит глазами. Ошибка в
// сторону «показали лишнее» дешёвая, в сторону «умолчали» — нет, поэтому
// сомнительное показываем.
import { readFileSync, readdirSync } from "node:fs";

const КАТАЛОГ = "knyaz2/web/static";
const файлы = readdirSync(КАТАЛОГ).filter((n) => n.endsWith(".js"));

const тексты = new Map();
for (const имя of файлы) {
  тексты.set(имя, readFileSync(`${КАТАЛОГ}/${имя}`, "utf8"));
}

//: Имена, объявленные экспортом: функции, классы, const/let и списки `export {}`.
function экспорты(текст) {
  const out = new Set();
  for (const m of текст.matchAll(/export\s+(?:async\s+)?function\s*\*?\s*(\w+)/g)) out.add(m[1]);
  for (const m of текст.matchAll(/export\s+class\s+(\w+)/g)) out.add(m[1]);
  for (const m of текст.matchAll(/export\s+(?:const|let|var)\s+(\w+)/g)) out.add(m[1]);
  for (const m of текст.matchAll(/export\s*\{([^}]*)\}/g)) {
    for (const кусок of m[1].split(",")) {
      const имя = кусок.trim().split(/\s+as\s+/).pop().trim();
      if (имя) out.add(имя);
    }
  }
  return out;
}

//: Имена, которые файл ИМПОРТИРУЕТ у соседей.
function импорты(текст) {
  const out = new Set();
  for (const m of текст.matchAll(/import\s*\{([^}]*)\}\s*from/g)) {
    for (const кусок of m[1].split(",")) {
      const имя = кусок.trim().split(/\s+as\s+/)[0].trim();
      if (имя) out.add(имя);
    }
  }
  return out;
}

const импортировано = new Set();
for (const текст of тексты.values()) {
  for (const имя of импорты(текст)) импортировано.add(имя);
}

//: Ручки наружу: всё, что перечислено в объекте `window.knyaz2`, живёт для
//: консоли и агента — это использование, а не мусор.
const app = тексты.get("app.js") ?? "";
const ручки = new Set();
const начало = app.indexOf("window.knyaz2 = {");
if (начало >= 0) {
  const конец = app.indexOf("};", начало);
  for (const m of app.slice(начало, конец).matchAll(/[\s{,]([a-zA-Z_$][\w$]*)\s*[,:}]/g)) {
    ручки.add(m[1]);
  }
}
for (const m of app.matchAll(/window\.knyaz2\.(\w+)\s*=/g)) ручки.add(m[1]);

let всего = 0;
for (const [имя, текст] of тексты) {
  const мёртвые = [];
  for (const name of экспорты(текст)) {
    if (импортировано.has(name) || ручки.has(name)) continue;
    //: Внутри своего файла имя может работать и без импорта.
    const внутри = (текст.match(new RegExp(`\\b${name}\\b`, "g")) || []).length;
    if (внутри > 1) continue;
    мёртвые.push(name);
  }
  if (мёртвые.length) {
    всего += мёртвые.length;
    console.log(`${имя}: ${мёртвые.join(", ")}`);
  }
}
console.log(всего ? `\nэкспортов без единого потребителя: ${всего}`
                  : "\nвсё экспортированное кем-то зовётся");
process.exit(0);
