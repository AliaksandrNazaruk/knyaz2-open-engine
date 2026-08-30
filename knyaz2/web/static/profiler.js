// Замер и неуязвимость. Оверлеи под курсором живут отдельно, в debug.js.
//
// Ничего из этого в игре не участвует и по умолчанию выключено. Замер
// намеренно сделан «дырками» внутри кадра, а не обёрткой снаружи: снаружи
// видно только суммарные 300 мс, а нужен ответ, ЧЕМ они заняты.
//
//     knyaz2.profiler.invulnerable = true   // герой не теряет здоровье
//     knyaz2.profiler.profile(10)           // мерить десять секунд и напечатать
//     knyaz2.profiler.memory()              // вес распакованных картинок
//     knyaz2.profiler.counters()            // что могло вырасти за игру
//
// ПЕЧАТАЕТСЯ ПРОСТЫМ ТЕКСТОМ, а не console.table: табличку из консоли не
// скопировать, и первый же замер пришёл ко мне пустым.
import { world } from "./world.js";

export const profiler = {
  //: Неуязвимость. Точка одна — `healthSet` в effects.js, через неё идут все
  //: пути урона: ближний бой, снаряд, отрава и ход по глобальной.
  invulnerable: false,
  profiling: false,
};

const totals = new Map();          // имя части кадра -> {ms, calls, worst}
let frames = 0;
let startedAt = 0;

//: Дырка замера. Когда замер выключен, стоит один `if` — на кадр их полтора
//: десятка, и это ничто рядом с самой работой.
// ЧЕСТНЫЙ РЕЖИМ: canvas2d ОТКЛАДЫВАЕТ работу.
//
// Браузер копит команды и выполняет их пачкой, поэтому `performance.now()`
// вокруг части кадра меряет не её труд, а момент, когда очередь сбросилась.
// Замер тогда врёт систематически: дешёвая часть, на которой случился сброс,
// забирает себе чужие миллисекунды. Читая одну точку с холста, мы заставляем
// браузер доделать всё накопленное — и часть отвечает за свой труд.
//
// Само чтение стоит около 0.05 мс, поэтому по умолчанию выключено:
// включать только на разбор (`knyaz2.profiler.flush = true`).
profiler.flush = false;

function сбросить() {
  if (!profiler.flush) return;
  try {
    const c = document.querySelector("canvas");
    c?.getContext("2d")?.getImageData(0, 0, 1, 1);
  } catch {
    // холста нет или он запрещён к чтению — просто меряем как раньше
  }
}

export function probe(name, fn) {
  if (!profiler.profiling) return fn();
  сбросить();
  const from = performance.now();
  try {
    return fn();
  } finally {
    сбросить();
    const spent = performance.now() - from;
    let row = totals.get(name);
    if (!row) totals.set(name, row = { ms: 0, calls: 0, worst: 0 });
    row.ms += spent;
    row.calls += 1;
    if (spent > row.worst) row.worst = spent;
  }
}

//: Кадр целиком — чтобы сумме частей было с чем сравниваться.
export function probeFrame() {
  if (profiler.profiling) frames += 1;
}

function pad(value, width) {
  return String(value).padStart(width);
}

//: ВОЗВРАЩАЕМ СТРОКУ, А НЕ ОБЪЕКТ, и кладём её в буфер обмена. Консоль
//: показывает объект свёрнутым — `{rows: {…}, текст: '  куча JS…'}`, — и
//: замер приходил ко мне обрезанным многоточием. Последний ответ лежит в
//: `knyaz2.profiler.last`, так что его всегда можно достать заново.
function emit(text) {
  profiler.last = text;
  console.log(text);
  try {
    navigator.clipboard?.writeText(text);
  } catch {
    // без доступа к буферу просто останется в консоли и в `last`
  }
  return text;
}

profiler.profile = (seconds = 10) => {
  totals.clear();
  frames = 0;
  startedAt = performance.now();
  profiler.profiling = true;
  console.log(`замер пошёл, ${seconds} с`);
  return new Promise((done) => setTimeout(() => {
    profiler.profiling = false;
    const elapsed = (performance.now() - startedAt) / 1000;
    const rows = [...totals.entries()]
      .map(([name, row]) => ({
        часть: name,
        всего_мс: Math.round(row.ms),
        доля: `${Math.round((row.ms / (elapsed * 1000)) * 100)}%`,
        за_вызов_мс: +(row.ms / Math.max(1, row.calls)).toFixed(2),
        худший_мс: Math.round(row.worst),
        вызовов: row.calls,
      }))
      .sort((a, b) => b.всего_мс - a.всего_мс);
    const wide = Math.max(10, ...rows.map((r) => r.часть.length));
    const lines = [
      `кадров ${frames} за ${elapsed.toFixed(1)} с — `
        + `${(frames / elapsed).toFixed(1)} в секунду`,
      `${"часть".padEnd(wide)}  всего_мс   доля  за_вызов  худший  вызовов`,
      ...rows.map((r) => `${r.часть.padEnd(wide)}  ${pad(r.всего_мс, 8)}`
        + `  ${pad(r.доля, 5)}  ${pad(r.за_вызов_мс, 8)}`
        + `  ${pad(r.худший_мс, 6)}  ${pad(r.вызовов, 7)}`),
    ];
    done(emit(lines.join("\n")));
  }, seconds * 1000));
};

//: Сколько памяти держат распакованные картинки. Файл на диске сжат, а в
//: памяти лежит четыре байта на пиксель — лист юнита 4095x1709 это 27 МБ.
profiler.memory = () => {
  const kinds = new Map();
  let total = 0;
  for (const [path, image] of world.images) {
    //: У `ImageBitmap` размеры зовутся просто width/height, у `Image` —
    //: naturalWidth/naturalHeight. В кэше теперь первое, второе осталось
    //: запасным путём (content.js).
    const w = image?.width ?? image?.naturalWidth ?? 0;
    const h = image?.height ?? image?.naturalHeight ?? 0;
    if (!w || !h) continue;
    const bytes = w * h * 4;
    total += bytes;
    const kind = (/assets\/([^/]+)\//.exec(path) ?? [, "прочее"])[1];
    let row = kinds.get(kind);
    if (!row) kinds.set(kind, row = { картинок: 0, МБ: 0, крупнейшая: "", max: 0 });
    row.картинок += 1;
    row.МБ += bytes / 1048576;
    if (bytes > row.max) { row.max = bytes; row.крупнейшая = `${w}x${h}`; }
  }
  const rows = [...kinds.entries()]
    .map(([kind, row]) => ({ вид: kind, картинок: row.картинок,
                             МБ: Math.round(row.МБ), крупнейшая: row.крупнейшая }))
    .sort((a, b) => b.МБ - a.МБ);
  const lines = [
    `распакованных картинок: ${world.images.size}, `
      + `в памяти ${(total / 1073741824).toFixed(2)} ГБ`,
    ...rows.map((r) => `  ${r.вид.padEnd(18)} ${pad(r.картинок, 4)} шт.`
      + `  ${pad(r.МБ, 5)} МБ   крупнейшая ${r.крупнейшая}`),
  ];
  return emit(lines.join("\n"));
};

//: Мгновенный снимок всего, что МОЖЕТ расти. Постоянный вес и растущий кадр —
//: разные болезни: первую видно в `memory`, вторую только тут, если снять
//: счётчики дважды с разницей в несколько минут.
//: Читаем через `window.knyaz2`, а не импортом: profiler.js тянет effects.js,
//: и обратный импорт units/combat замкнул бы круг.
profiler.counters = () => {
  const k = globalThis.window?.knyaz2 ?? {};
  const heap = performance.memory?.usedJSHeapSize ?? null;
  //: РАЗМЕР ХОЛСТА И МАСШТАБ — ПЕРВЫЕ СТРОКИ. Цена одной постройки растёт
  //: вместе с площадью холста (замерено: 23 мкс при 700x600, 103 мкс при
  //: 1723x1080), а число построек в кадре растёт при отдалении. Без этих
  //: двух чисел чужой замер не с чем сравнивать.
  const c = globalThis.window?.knyaz2?.canvas ?? null;
  const v = globalThis.window?.knyaz2?.view ?? {};
  const rows = {
    "холст, точек": c ? `${c.width}x${c.height}` : "нет",
    "экран, точек": `${innerWidth}x${innerHeight} при dpr ${devicePixelRatio}`,
    "масштаб": v.zoom ?? "нет",
    "куча JS, МБ": heap === null ? "нет данных" : Math.round(heap / 1048576),
    "узлов в DOM": document.getElementsByTagName("*").length,
    "картинок": world.images.size,
    "объектов сцены": world.objects.length,
    "клеток земли": world.ground.length,
    "юнитов": k.units?.length ?? null,
    "снарядов": k.combat?.projectiles?.length ?? null,
    "строк лога боя": k.combat?.log?.length ?? null,
    "шагов пути героя": k.hero?.path?.length ?? null,
    "звуков в кэше": k.sound?.buffers?.size ?? null,
  };
  const wide = Math.max(...Object.keys(rows).map((s) => s.length));
  return emit(Object.entries(rows)
    .map(([name, value]) => `  ${name.padEnd(wide)}  ${value}`)
    .join("\n"));
};

world.profiler = profiler;
