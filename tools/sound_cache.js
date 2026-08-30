// -*- coding: utf-8 -*-
// Жизнь звукового кэша НАСТОЯЩИМ кодом клиента, без браузера.
//
// Проверяется то, что в игре слышно, а по данным не видно: у двух игр номера
// слотов общие, а звуки под ними разные. Отсюда три поломки, все тихие:
//
//   1) вместе с кэшем уходил ВЕЧНЫЙ набор движка (интерфейс 0…19 и отклики
//      32…79, VA 0x43C228) — его грузили один раз при старте, а очередь
//      входа на карту его не несёт. Промах кэша по канону молчит и ничего
//      не догружает, значит 68 звуков пропадали до конца сеанса;
//
//   2) кэш ключевался НОМЕРОМ слота, а номер уникален только внутри одной
//      игры: звук чужого банка садился в кэш и играл вместо своего;
//
//   3) музыка карты мира бралась из набора ПОСЛЕДНЕЙ КАРТЫ, хотя карта мира
//      одна на две игры. Канонный слот 20 — тема на 39 секунд, донорский —
//      обрывок на 0.37, и зациклённый он давал «заглючивший» звук.
//
// Из окружения sound.js тянет `content`, `viewport` и `world`, а из среды —
// `document`, `window.AudioContext` и `fetch`. Всё это заглушки, сам модуль
// берётся как есть (как в tools/worldmap_route.js).
//
// Запуск:  node tools/sound_cache.js <каталог пака> [каталог клиента]
//
// Второй довод — для проверки самой проверки: подсунув сюда каталог с
// копиями модулей, где поломка возвращена, надо УВИДЕТЬ красное. Зелёный
// стенд, который не краснеет ни на чём, не доказывает ничего.
import { readFileSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { join, resolve } from "node:path";
import { tmpdir } from "node:os";

const packDir = process.argv[2];
const clientDir = process.argv[3] ?? "knyaz2/web/static";
if (!packDir) {
  console.error("нужно: node tools/sound_cache.js <каталог пака> [каталог клиента]");
  process.exit(2);
}

const audioIndex = JSON.parse(
  readFileSync(join(packDir, "assets", "audio.json"), "utf8"));
const voices = JSON.parse(
  readFileSync(join(packDir, "assets", "voices.json"), "utf8"));

// --- среда ------------------------------------------------------------------

//: Ответы держим, пока не отпустим: гонка «запрос начат до сброса, ответ
//: пришёл после» иначе не воспроизводится.
let held = [];
//: Готовый буфер помнит, из какого файла он взялся. Только так и можно
//: поймать канонный звук, легший под донорский номер.
const origin = new WeakMap();

globalThis.fetch = (url) => {
  const path = String(url);
  return new Promise((release) => {
    held.push(() => {
      const bytes = new ArrayBuffer(8);
      origin.set(bytes, path);
      release({ ok: true, arrayBuffer: async () => bytes, json: async () => ({}) });
    });
  });
};

async function settle() {
  const pending = held;
  held = [];
  for (const release of pending) release();
  for (let i = 0; i < 4; i += 1) await new Promise((r) => setImmediate(r));
}

globalThis.document = { addEventListener() {} };
//: Узлы WebAudio — пустышки: нас занимает не звучание, а КАКОЙ файл попал в
//: источник. `connect` обязан возвращать своего собеседника — клиент строит
//: цепочку `source.connect(gain).connect(destination)`.
const node = (extra = {}) => ({ connect: (next) => next, ...extra });
globalThis.window = {
  AudioContext: class {
    constructor() {
      this.state = "running";
      this.currentTime = 0;
      this.destination = node();
    }
    async decodeAudioData(bytes) { return { path: origin.get(bytes) ?? null }; }
    createBufferSource() {
      return node({ buffer: null, loop: false, playbackRate: { value: 1 },
                    start() {}, stop() {}, onended: null });
    }
    createGain() { return node({ gain: { value: 1 } }); }
    createStereoPanner() { return node({ pan: { value: 0 } }); }
    resume() {}
  },
};

const stage = join(tmpdir(), `sound-cache-${process.pid}`);
mkdirSync(stage, { recursive: true });
writeFileSync(join(stage, "content.js"),
  "export const contentUrl = (p) => p;\n"
  + "export const readJson = async (p) => globalThis.__json[p];\n");
writeFileSync(join(stage, "viewport.js"), "export const view = {};\n");
writeFileSync(join(stage, "world.js"), "export const world = globalThis.__world;\n");
writeFileSync(join(stage, "sound.js"),
  readFileSync(resolve(clientDir, "sound.js"), "utf8"));
// Окружение звукового пейзажа: он тянет полмира, но нужны от него только
// «на карте мира или нет» и «какой трек у текущей карты».
writeFileSync(join(stage, "hero.js"), "export const hero = { alive: true };\n");
writeFileSync(join(stage, "units.js"), "export const units = [];\n");
writeFileSync(join(stage, "light.js"), "export const lightActive = () => false;\n");
writeFileSync(join(stage, "trade.js"), "export const trade = { open: false };\n");
writeFileSync(join(stage, "worldmap.js"),
  "export const worldMap = globalThis.__worldMap;\n");
writeFileSync(join(stage, "soundscape.js"),
  readFileSync(resolve(clientDir, "soundscape.js"), "utf8"));
globalThis.__world = { map: { audio: null }, talking: false };
globalThis.__worldMap = { onMap: false };
globalThis.__json = {
  "assets/audio.json": audioIndex,
  "assets/voices.json": voices,
};

const load = (name) =>
  import("file://" + join(stage, name).replace(/\\/g, "/"));
const snd = await load("sound.js");
const scape = await load("soundscape.js");
rmSync(stage, { recursive: true, force: true });
const { sound, soundInit, soundMapEnter, preloadSlots } = snd;

let bad = 0;
const say = (ok, text) => {
  if (!ok) bad += 1;
  console.log(`${ok ? "  ок " : "ПЛОХО"}  ${text}`);
};

const streaming = audioIndex.rules.streaming;
const eternal = [];
for (let s = streaming.preload_ui[0]; s < streaming.preload_ui[1]; s += 1) {
  eternal.push(s);
}
for (let s = streaming.preload_responses[0]; s < streaming.preload_responses[1];
     s += 1) {
  eternal.push(s);
}
//: Кэш ключуется ПУТЁМ к файлу — как в самом клиенте. Ищем так же, иначе
//: стенд проверял бы не то, что играет.
const pathOf = (game, slot) =>
  (game ? sound.slots[`${game}:${slot}`] : null)?.path
  ?? sound.slots[String(slot)]?.path ?? null;
const buffer = (slot, game = sound.game) => {
  const path = pathOf(game, slot);
  const value = path ? sound.buffers.get(path) : null;
  return value && !(value instanceof Promise) ? value : null;
};
const ready = () => eternal.filter((slot) => buffer(slot)).length;

// --- 1. Старт: вечный набор грузится ---------------------------------------
await soundInit();
await settle();
console.log(`вечный набор: ${eternal.length} слотов `
            + `(интерфейс ${streaming.preload_ui}, отклики ${streaming.preload_responses})`);
say(ready() > 0, `после старта в кэше ${ready()} из ${eternal.length}`);
const atStart = ready();

// --- 2. Вход на КАНОННУЮ карту: набор тот же, кэш не трогаем ---------------
soundMapEnter({ game: null, preload: [] });
await settle();
say(ready() === atStart,
    `вход на карту своей же игры кэш не сбросил: ${ready()} из ${eternal.length}`);

// --- 3. Вход на ДОНОРСКУЮ: набор другой, кэш сброшен и взят заново ----------
soundMapEnter({ game: "legend", preload: [] });
await settle();
const own = eternal.filter((slot) => buffer(slot)?.path === pathOf("legend", slot));
say(ready() > 0,
    `после смены набора вечный набор снова в кэше: ${ready()} из ${eternal.length}`);
say(own.length === ready(),
    `и все они донорские: ${own.length} из ${ready()}`);

// --- 4. Чужой банк не подменяет свой ---------------------------------------
//: Слот нужен такой, где файл есть у ОБЕИХ игр и он разный: на пустом
//: канонном слоте подменять нечего, и проверка прошла бы вхолостую —
//: зелёная и ничего не значащая.
const slot = eternal.find((number) => {
  const canon = pathOf(null, number);
  const legend = pathOf("legend", number);
  return canon && legend && canon !== legend;
});
const canonPath = slot === undefined ? null : pathOf(null, slot);
const legendPath = slot === undefined ? null : pathOf("legend", slot);
console.log(`\nподмена банка на слоте ${slot}: `
            + `канон «${canonPath}», донор «${legendPath}»`);
if (slot === undefined) {
  say(false, "не нашлось слота, где файл есть у обеих игр и он разный — "
             + "подмену показать не на чем");
} else {
  // Канонный звук уже в кэше, и тут игра меняется. Под тем же номером
  // должен зазвучать донорский файл, а не оставшийся канонный.
  soundMapEnter({ game: null, preload: [] });
  preloadSlots([slot]);
  await settle();
  soundMapEnter({ game: "legend", preload: [] });
  preloadSlots([slot]);
  await settle();
  say(buffer(slot)?.path === legendPath,
      `под слотом ${slot} звучит донорский файл: ${buffer(slot)?.path ?? "пусто"}`);
}

// --- 5. Музыка карты мира — всегда канонная --------------------------------
//: Карта мира в мире ОДНА на две игры, и трек у неё канонный. Пока он
//: брался из набора последней карты, после выхода с донорской играл
//: обрывок на 0.37 секунды вместо темы на 39 — зациклённый.
const globalSlot = audioIndex.rules.tracks.global_map;
const globalCanon = pathOf(null, globalSlot);
const globalLegend = pathOf("legend", globalSlot);
console.log(`\nтрек карты мира — слот ${globalSlot}: `
            + `канон «${globalCanon}» ${sound.slots[String(globalSlot)]?.seconds} с, `
            + `донор «${globalLegend}» ${sound.slots[`legend:${globalSlot}`]?.seconds} с`);
//: Зовём НЕ playMusic напрямую, а сам звуковой пейзаж: банк выбирает он,
//: и поломка жила именно там. Такт у него с гейтом по времени, поэтому
//: время двигаем; ответы придерживаются, поэтому после каждого такта
//: отпускаем их и даём промисам разойтись.
const tick = async (millis) => { scape.soundscapeTick(millis); await settle(); };

//: Донорская карта: её трек, и он донорский.
const villageSlot = audioIndex.rules.tracks.village_base;
globalThis.__world.map = { audio: { game: "legend", map_track: villageSlot } };
globalThis.__worldMap.onMap = false;
soundMapEnter(globalThis.__world.map.audio);
await settle();
await tick(1000);
await tick(2000);
say(sound.music?.path === pathOf("legend", villageSlot),
    `на донорской карте играет её трек: ${sound.music?.path ?? "ничего"}`);

//: Вышли на карту мира — трек обязан смениться на КАНОННУЮ тему.
globalThis.__worldMap.onMap = true;
await tick(3000);
await tick(4000);
say(sound.music?.path === globalCanon,
    `на карте мира играет канонная тема: ${sound.music?.path ?? "ничего"}`);
say(sound.music?.path !== globalLegend,
    "донорский обрывок на 0.37 с не играет");

// --- 6. Гонка на входе: банк ещё канонный, а трек уже просят -------------
//: Так и было в игре: `soundscapeTick` успевает пройти раньше, чем
//: `soundMapEnter` выставит набор. Под номером 38 у канона звук на 0.34 с,
//: у донора дорожка на 32 с — и петля крутила канонный обрывок.
console.log("\nгонка на входе (набор ещё не выставлен):");
const RACE = audioIndex.rules.tracks ? 38 : null;
if (RACE === null || !pathOf("legend", RACE) || !pathOf(null, RACE)) {
  console.log("  — под этим номером нет пары «канон/донор», гонку не показать");
} else {
  sound.game = null;                       // как сразу после старта
  globalThis.__world.map = { audio: { game: "legend", map_track: RACE } };
  globalThis.__worldMap.onMap = false;
  scape.soundscapeTick(9000);              // такт ДО входа на карту
  soundMapEnter(globalThis.__world.map.audio);   // и только теперь вход
  scape.soundscapeTick(10000);
  await settle();
  await settle();
  say(sound.music?.path === pathOf("legend", RACE),
      `играет дорожка донора: ${sound.music?.path ?? "ничего"}`);
  say(sound.music?.path !== pathOf(null, RACE),
      `канонный обрывок на ${sound.slots[String(RACE)].seconds} с не крутится`);
}

console.log(`\nнеудач: ${bad}`);
process.exit(bad ? 1 : 0);
