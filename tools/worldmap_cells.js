// -*- coding: utf-8 -*-
// Перенос сохранённой сетки карты мира НАСТОЯЩИМ кодом клиента, без браузера.
//
// Проверяется одно правило и его четыре следствия: РАСКЛАД ЛОКАЦИЙ ЖИВЁТ В
// ПАКЕ, ТУМАН — В СОХРАНЕНИИ. Клетка карты мира несёт и то и другое в одном
// числе, и если при загрузке класть сохранённую сетку как есть, содержимое
// пака до начатой игры не доедет никогда: деревню перенесли на другую карту,
// а игрок по-прежнему входит в прежнюю — молча, без единой ошибки.
//
// Кто чем владеет, видно по тому, кто это пишет. На ходу клиент трогает три
// бита: ставит `explored` и `seen`, снимает `hidden`. Всё остальное пишет
// только сборка.
//
// Из окружения worldmap.js нужны `world` и `contentUrl` — обе подменяются
// заглушками, сам модуль берётся как есть (как в tools/worldmap_route.js).
//
// Запуск:  node tools/worldmap_cells.js <каталог пака>
import { readFileSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { join, resolve } from "node:path";
import { tmpdir } from "node:os";

const packDir = process.argv[2];
if (!packDir) {
  console.error("нужно: node tools/worldmap_cells.js <каталог пака>");
  process.exit(2);
}

const shared = JSON.parse(readFileSync(join(packDir, "shared.json"), "utf8"));
const rules = shared.hero.rules.world_map;
const manifest = JSON.parse(readFileSync(join(packDir, "manifest.json"), "utf8"));
const anyMap = JSON.parse(
  readFileSync(join(packDir, manifest.maps[0].path), "utf8"));

const stage = join(tmpdir(), `worldmap-cells-${process.pid}`);
mkdirSync(stage, { recursive: true });
writeFileSync(join(stage, "world.js"), "export const world = globalThis.__world;\n");
writeFileSync(join(stage, "content.js"), "export const contentUrl = (p) => p;\n");
writeFileSync(join(stage, "worldmap.js"),
  readFileSync(resolve("knyaz2/web/static/worldmap.js"), "utf8"));
globalThis.__world = {
  map: { hero: { rules: { world_map: rules } }, interface: anyMap.interface },
};
const wm = await import("file://" + join(stage, "worldmap.js").replace(/\\/g, "/"));
rmSync(stage, { recursive: true, force: true });
const { worldMap, worldMapSetup, markerVisible, cellsRestore } = wm;

if (!worldMapSetup()) { console.error("сетки карты мира в паке нет"); process.exit(1); }

const { explored, seen, hidden } = rules.flags;
let bad = 0;
const say = (ok, text) => {
  if (!ok) bad += 1;
  console.log(`${ok ? "  ок " : "ПЛОХО"}  ${text}`);
};
//: Свежая сетка пака — она же образец правильного содержимого.
const fresh = rules.grid;
//: Берём первую клетку с локацией: правило общее, не про конкретную деревню.
let spot = null;
for (let r = 0; r < fresh.length && !spot; r += 1) {
  for (let c = 0; c < fresh[r].length && !spot; c += 1) {
    if (fresh[r][c] & 0xFF) spot = [r, c];
  }
}
if (!spot) { console.error("в сетке нет ни одной локации"); process.exit(1); }
const [row, col] = spot;
const number = fresh[row][col] & 0xFF;
console.log(`пробная клетка (${row},${col}): локация ${number}, `
            + `сырое 0x${(fresh[row][col] >>> 0).toString(16)}`);

//: Старое сохранение: в той же клетке ДРУГАЯ локация, стоит «скрыта», и
//: отряд там уже побывал. Ровно то, что осталось бы у игрока после переноса.
const OLD = 7;
const aged = fresh.map((line) => line.slice());
aged[row][col] = OLD | (0x99 << 16) | ((hidden | explored) << 24);

cellsRestore(aged);
const cell = worldMap.cells[row][col];
console.log(`после загрузки: 0x${(cell >>> 0).toString(16)}`);
say((cell & 0xFF) === number,
    `локация из пака: ${cell & 0xFF} (в сохранении было ${OLD})`);
say(((cell >>> 16) & 0xFF) === ((fresh[row][col] >>> 16) & 0xFF),
    `прочее содержимое из пака: карта стычки ${(cell >>> 16) & 0xFF} `
    + `(в сохранении было 0x99)`);
say(Boolean((cell >>> 24) & explored), "исхоженность из сохранения цела");
say(!((cell >>> 24) & hidden),
    "«скрыта» снята: пак её не ставит, а сохранение одно решать не может");
say(markerVisible(cell), "значок виден в уже начатой игре");

//: И обратно, на клетке, которую прячет САМ ПАК: сюжетное открытие из
//: сохранения переживает загрузку, а без него локация остаётся скрытой.
//: Иначе перенос тумана открыл бы игроку полкарты разом.
let dark = null;
for (let r = 0; r < fresh.length && !dark; r += 1) {
  for (let c = 0; c < fresh[r].length && !dark; c += 1) {
    if ((fresh[r][c] & 0xFF) && ((fresh[r][c] >>> 24) & hidden)) dark = [r, c];
  }
}
if (!dark) {
  console.log("\n  — в паке нет скрытых локаций, второй половине проверять нечего");
} else {
  const [dr, dc] = dark;
  console.log(`\nскрытая паком клетка (${dr},${dc}): `
              + `локация ${fresh[dr][dc] & 0xFF}`);
  const walked = fresh.map((line) => line.slice());
  walked[dr][dc] |= (explored | seen) << 24;          // отряд прошёл мимо
  cellsRestore(walked);
  say(Boolean((worldMap.cells[dr][dc] >>> 24) & hidden),
      "одно хождение скрытую локацию не открывает");
  say(!markerVisible(worldMap.cells[dr][dc]), "значка нет — сюжет ещё не открыл");

  const story = walked.map((line) => line.slice());
  story[dr][dc] &= ~(hidden << 24);                   // сюжет открыл
  cellsRestore(story);
  say(!((worldMap.cells[dr][dc] >>> 24) & hidden),
      "открытое сюжетом остаётся открытым после загрузки");
  say(markerVisible(worldMap.cells[dr][dc]), "значок виден");
}

console.log(`\nнеудач: ${bad}`);
process.exit(bad ? 1 : 0);
