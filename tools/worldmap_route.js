// -*- coding: utf-8 -*-
// Проход маршрута по карте мира НАСТОЯЩИМ кодом клиента, без браузера.
//
// Браузерная проверка упирается в среду: пока панель браузера закрыта,
// страница не отрисовывается и загрузка пака стоит. А проверить надо не
// картинку, а поведение — дойдёт ли отряд до перенесённой деревни, попадёт
// ли в неё, вернётся ли. Всё это живёт в knyaz2/web/static/worldmap.js, и
// он тянет из окружения ровно две вещи: объект `world` и `contentUrl`.
// Обе подменяются заглушками, сам модуль берётся как есть.
//
// Запуск:  node tools/worldmap_route.js <каталог пака> <локация> [ещё...]
import { readFileSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { join, resolve } from "node:path";
import { tmpdir } from "node:os";

const packDir = process.argv[2];
const wanted = process.argv.slice(3).map(Number);
if (!packDir || !wanted.length) {
  console.error("нужно: node tools/worldmap_route.js <пак> <локация> [...]");
  process.exit(2);
}

const shared = JSON.parse(readFileSync(join(packDir, "shared.json"), "utf8"));
const rules = shared.hero.rules.world_map;
// Интерфейс лежит в документе карты, а не в общем: берём первый попавшийся.
const manifest = JSON.parse(readFileSync(join(packDir, "manifest.json"), "utf8"));
const anyMap = JSON.parse(
  readFileSync(join(packDir, manifest.maps[0].path), "utf8"));

// Заглушки окружения рядом с копией модуля: импорт разрешается по пути.
const stage = join(tmpdir(), `worldmap-route-${process.pid}`);
mkdirSync(stage, { recursive: true });
writeFileSync(join(stage, "world.js"), "export const world = globalThis.__world;\n");
writeFileSync(join(stage, "content.js"), "export const contentUrl = (p) => p;\n");
writeFileSync(join(stage, "worldmap.js"),
  readFileSync(resolve("knyaz2/web/static/worldmap.js"), "utf8"));

globalThis.__world = {
  map: { hero: { rules: { world_map: rules } }, interface: anyMap.interface },
};

// ЖРЕБИЙ ДЕЛАЕМ ВОСПРОИЗВОДИМЫМ. Встречи бросаются каждый кадр, и на пути
// в тысячу кадров их выпадает по-разному — от двух до шести. Проверка от
// этого мигала: при неудачной серии отряд не успевал дойти за отведённые
// щелчки. Своя случайность с постоянным зерном оставляет встречи как
// явление, но делает прогон повторяемым.
let seed = 20260814;
Math.random = () => {
  seed = (seed * 1103515245 + 12345) & 0x7fffffff;
  return seed / 0x80000000;
};

const wm = await import("file://" + join(stage, "worldmap.js").replace(/\\/g, "/"));
rmSync(stage, { recursive: true, force: true });

const {
  worldMap, worldMapSetup, standAt, revealAll, startTravel, travelTick,
  locationCell, openLocation, markerVisible, locationName,
} = wm;

if (!worldMapSetup()) { console.error("сетки карты мира в паке нет"); process.exit(1); }
revealAll();
for (const number of wanted) openLocation(number);
openLocation(shared.start_map ?? 33);

const START = manifest.start_map ?? 33;
if (!standAt(START)) { console.error(`не встать на локацию ${START}`); process.exit(1); }
console.log(`старт: ${locationName(START)} — клетка (${worldMap.row},${worldMap.col})`);
console.log(`сетка ${rules.cols}x${rules.rows}, угол ${JSON.stringify(rules.origin)}`);

// Путь по суше от клетки к клетке — волна по восьми соседям, как ходит
// сам отряд. Возвращает список клеток без начальной.
function pathOf(fromRow, fromCol, toRow, toCol) {
  const { rows, cols, walk, mask } = rules;
  const land = (r, c) => Boolean(walk[r][c] & mask.land);
  const key = (r, c) => r * cols + c;
  const came = new Map([[key(fromRow, fromCol), null]]);
  const queue = [[fromRow, fromCol]];
  while (queue.length) {
    const [r, c] = queue.shift();
    if (r === toRow && c === toCol) break;
    for (let dr = -1; dr <= 1; dr += 1) {
      for (let dc = -1; dc <= 1; dc += 1) {
        const nr = r + dr, nc = c + dc;
        if ((!dr && !dc) || nr < 0 || nc < 0 || nr >= rows || nc >= cols) continue;
        if (!land(nr, nc) || came.has(key(nr, nc))) continue;
        came.set(key(nr, nc), [r, c]);
        queue.push([nr, nc]);
      }
    }
  }
  if (!came.has(key(toRow, toCol))) return null;
  const back = [];
  let at = [toRow, toCol];
  while (at) { back.push({ row: at[0], col: at[1] }); at = came.get(key(at[0], at[1])); }
  back.reverse();
  return back.slice(1);
}

let failures = 0;
for (const number of wanted) {
  const place = locationCell(number);
  if (!place) { console.log(`\n${number}: НЕТ НА КАРТЕ МИРА`); failures += 1; continue; }
  const name = locationName(number);
  console.log(`\nидём в ${name} (${number}), клетка (${place.row},${place.col})`);

  // ИДЁМ ПО ПУТИ, А НЕ ПО ПРЯМОЙ. Движок ведёт отряд к точке щелчка и
  // встаёт у преграды (VA 0x427A80) — игрок в таком месте щёлкает ещё раз.
  // Поэтому маршрут разбивается на отрезки по клеткам суши, как его прошёл
  // бы человек. Проверяем достижимость, а не умение движка огибать.
  const first = pathOf(worldMap.row, worldMap.col, place.row, place.col);
  if (!first) { console.log("   пути по суше нет вовсе"); failures += 1; continue; }
  console.log(`   путь по суше: ${first.length} клеток`);
  // Игрок щёлкает по одной клетке и повторяет щелчок после каждой встречи
  // или упора. Здесь то же самое: путь пересчитывается от того места, где
  // отряд встал, и попытки считаются.
  let frames = 0, encounters = 0, blocks = 0, clicks = 0;
  while (clicks < 400) {
    if (worldMap.row === place.row && worldMap.col === place.col) break;
    const route = pathOf(worldMap.row, worldMap.col, place.row, place.col);
    if (!route || !route.length) break;
    const point = route[0];
    clicks += 1;
    if (!startTravel(point.row, point.col, { speed: 0 })) break;
    let step = null, guard = 0;
    while (guard < 20000) {
      step = travelTick({ pathfinder: 100 });
      frames += 1; guard += 1;
      if (!step || step.kind !== "walking") break;
    }
    if (step && step.kind === "encounter") { encounters += 1; continue; }
    if (step && step.kind === "blocked") {
      blocks += 1;
      if (blocks > 20) break;
    }
  }
  if (worldMap.row !== place.row || worldMap.col !== place.col) {
    console.log(`   НЕ ДОШЛИ: встали на (${worldMap.row},${worldMap.col}) `
                + `за ${frames} кадров, щелчков ${clicks}, встреч ${encounters}, `
                + `упоров ${blocks}`);
    failures += 1;
    standAt(START);
    continue;
  }
  console.log(`   дошли: щелчков ${clicks}, кадров ${frames}, `
              + `встреч ${encounters}, упоров ${blocks}`);

  const cell = worldMap.cells[worldMap.row][worldMap.col];
  const here = cell & 0xFF;
  if (here !== number) {
    console.log(`   ПРИШЛИ НЕ ТУДА: в клетке локация ${here}`); failures += 1; continue;
  }
  if (!markerVisible(cell)) { console.log("   значок не виден"); failures += 1; continue; }
  console.log(`   на месте: «${locationName(here)}», значок виден`);

  const arrival = rules.arrivals?.[String(number)];
  console.log(`   прибытие на карту: ${arrival ? `строка ${arrival.row}, столбец ${arrival.col}` : "НЕ ЗАДАНО"}`);
  if (!arrival) failures += 1;

  standAt(START);       // возвращаемся, как после выхода краем локации
}
console.log(`\nнеудач: ${failures}`);
process.exit(failures ? 1 : 0);
