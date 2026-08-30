// -*- coding: utf-8 -*-
// Засады НАСТОЯЩИМ кодом клиента: чья земля — того и встреча.
//
// Проверяется то, ради чего переносилась таблица местностей донора: на его
// половине карты мира должны выпадать ЕГО отряды и ЕГО места боя, а на
// канонной — канонные. Раньше вся его земля несла канонные виды 1 и 4, и
// засада в пустыне уводила на русский лесной пруд.
//
// Правила у двух игр разные, и обе ветки должны отработать:
//   * канон (VA 0x4360A8): класс опасности по телу героя -> строка отрядов,
//     место боя — жребий из пятнадцати сцен ЗАПИСИ местности;
//   * донор (FUN_00439B38): класса нет, двадцать номеров лежат в записи,
//     место боя — байт 2 САМОЙ КЛЕТКИ.
//
// Запуск:  node tools/worldmap_ambush.js <каталог пака> [бросков]
import { readFileSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { join, resolve } from "node:path";
import { tmpdir } from "node:os";

const packDir = process.argv[2];
const rolls = Number(process.argv[3] ?? 4000);
if (!packDir) {
  console.error("нужно: node tools/worldmap_ambush.js <каталог пака> [бросков]");
  process.exit(2);
}

const shared = JSON.parse(readFileSync(join(packDir, "shared.json"), "utf8"));
const rules = shared.hero.rules.world_map;
const manifest = JSON.parse(readFileSync(join(packDir, "manifest.json"), "utf8"));
const anyMap = JSON.parse(
  readFileSync(join(packDir, manifest.maps[0].path), "utf8"));

const stage = join(tmpdir(), `worldmap-ambush-${process.pid}`);
mkdirSync(stage, { recursive: true });
writeFileSync(join(stage, "world.js"), "export const world = globalThis.__world;\n");
writeFileSync(join(stage, "content.js"), "export const contentUrl = (p) => p;\n");
writeFileSync(join(stage, "worldmap.js"),
  readFileSync(resolve("knyaz2/web/static/worldmap.js"), "utf8"));
globalThis.__world = {
  map: { hero: { rules: { world_map: rules } }, interface: anyMap.interface },
};
//: Жребий воспроизводимый: проверка про раскладку, а не про удачу.
let seed = 20260817;
Math.random = () => {
  seed = (seed * 1103515245 + 12345) & 0x7fffffff;
  return seed / 0x80000000;
};

const wm = await import("file://" + join(stage, "worldmap.js").replace(/\\/g, "/"));
rmSync(stage, { recursive: true, force: true });
const { worldMap, worldMapSetup, rollEncounter } = wm;
if (!worldMapSetup()) { console.error("сетки карты мира в паке нет"); process.exit(1); }

const encounters = anyMap.encounters ?? {};
const maps = new Set(manifest.maps.map((entry) => entry.legacy_number));

//: ЧЬЯ ЗЕМЛЯ — РЕШАЕТ ВИД МЕСТНОСТИ, А НЕ МЕСТО НА КАРТЕ. «Не канонная
//: вставка» это не «донорская»: у общей карты есть углы, которых нет ни в
//: одной игре (440 клеток), и они несут канонные виды честно. Делить по
//: прямоугольнику значило бы записать их донору и получить ложную тревогу.
const DONOR_TERRAIN_BASE = 12;
const donorLand = (row, col) =>
  ((worldMap.cells[row][col] >> 8) & 0xFF) >= DONOR_TERRAIN_BASE;

let bad = 0;
const say = (ok, text) => { if (!ok) bad += 1; console.log(`${ok ? "  ок " : "ПЛОХО"}  ${text}`); };

//: Клетки, где встреча вообще возможна: с местностью, у которой спокойствие
//: меньше тысячи. По ним и бросаем.
const places = { канон: [], донор: [] };
for (let row = 0; row < rules.rows; row += 1) {
  for (let col = 0; col < rules.cols; col += 1) {
    const kind = (worldMap.cells[row][col] >> 8) & 0xFF;
    const terrain = rules.terrain?.[kind];
    if (!terrain || terrain.calm >= 1000) continue;
    places[donorLand(row, col) ? "донор" : "канон"].push([row, col]);
  }
}
console.log(`клеток со встречами: канон ${places["канон"].length}, `
            + `донор ${places["донор"].length}`);

for (const side of ["канон", "донор"]) {
  const cells = places[side];
  const groups = new Set(), scenes = new Set();
  let met = 0, noRoster = 0, noMap = 0;
  for (let i = 0; i < rolls; i += 1) {
    const [row, col] = cells[i % cells.length];
    const result = rollEncounter(row, col, { body: i % 6 });
    if (!result) continue;
    met += 1;
    groups.add(result.group);
    scenes.add(result.scene);
    if (!encounters[String(result.group)]) noRoster += 1;
    if (!maps.has(result.scene)) noMap += 1;
  }
  console.log(`\n${side}: встреч ${met} из ${rolls} бросков`);
  console.log(`  разных отрядов ${groups.size}, разных мест боя ${scenes.size}`);
  const numbers = [...groups].sort((a, b) => a - b);
  console.log(`  номера отрядов: ${numbers[0]}…${numbers[numbers.length - 1]}`);
  say(met > 0, "встречи вообще случаются");
  say(noRoster === 0, `у всех отрядов есть состав в паке (без состава ${noRoster})`);
  say(noMap === 0, `все места боя — существующие карты (без карты ${noMap})`);
  const own = side === "донор"
    ? numbers.every((n) => n >= 1000)
    : numbers.every((n) => n < 1000);
  say(own, side === "донор"
    ? "на его земле выпадают ТОЛЬКО его отряды"
    : "на канонной земле выпадают только канонные отряды");
}

console.log(`\nнеудач: ${bad}`);
process.exit(bad ? 1 : 0);
