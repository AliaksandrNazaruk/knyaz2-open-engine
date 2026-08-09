// Звуковой пейзаж карты: амбиент, музыка и приветствия спутников.
//
// Планировщик — тик главного цикла 0x438A00 (case 0), один в один:
//   * раз в такт мира с шансом 1 % играется амбиент-слот текущей карты:
//     днём +0…+4, после заката +5…+7 (тот же гейт, что у ночного света,
//     тик 8100), в «пещерах» (карты с фиксированным светом) — любой из
//     восьми; без позиционирования;
//   * раз в 1024 такта случайный СПУТНИК (не герой) здоровается репликой
//     voices.res 5500 + актёр*5 + rand%5 — если в отряде больше одного;
//   * музыка карты крутится одним зацикленным треком (map_track из пака,
//     выбор — VA 0x437F48); включение — после первого жеста игрока.
import { world } from "./world.js";
import { hero } from "./hero.js";
import { units } from "./units.js";
import { lightActive } from "./light.js";
import { trade } from "./trade.js";
import { worldMap } from "./worldmap.js";
import { playEffect, playMusic, playVoiceLine, sound } from "./sound.js";

const TICK_SECONDS = 1 / 18;
const scape = { clock: 0, ticks: 0 };

const rnd = (n) => Math.floor(Math.random() * n);

function ambientOnce() {
  const block = world.map?.audio?.ambient;
  const rules = sound.rules?.ambient;
  if (!block || !rules) return;
  // жребий движка: rand%100 > 98 — один шанс из ста за такт
  if (rnd(100) < 100 - rules.chance_percent) return;
  let pool;
  if (block.cave) pool = [...block.day, ...block.night];
  else if (lightActive()) pool = block.night;
  else pool = block.day;
  if (!pool?.length) return;
  playEffect(pool[rnd(pool.length)]);
}

function greetingOnce() {
  const voices = sound.rules?.voices;
  if (!voices) return;
  // Гейт движка `[0x8495F0] == 0` (0x438A00:170): при ОТКРЫТОМ экране —
  // разговор, торговля — спутники молчат и не перебивают рассказ NPC.
  // Канал у приветствий тот же, что у реплик (0x849670), поэтому без
  // гейта приветствие обрывало бы реплику на полуслове.
  if (world.talking || trade.open) return;
  // спутники живые и словесные; герой в жребии не участвует (0x438A00
  // берёт юнитов отряда с индекса 1)
  const party = units.filter((unit) =>
    unit.ally && unit.alive !== false && !unit.beast);
  if (!party.length) return;
  const companion = party[rnd(party.length)];
  const greet = voices.greeting;
  const line = greet.base + (companion.body ?? 0) * greet.per_actor +
    rnd(greet.per_actor);
  // голос для питча — ЧИСЛО диалога (у юнитов карты dialog — дерево)
  const voice = typeof companion.dialogNumber === "number"
    ? companion.dialogNumber : companion.dialog?.number ?? null;
  playVoiceLine(line, voice);
}

function musicFollowsMap() {
  // Ручной выбор панели сильнее трека карты — это дев-инструмент.
  // На глобальной карте свой трек (слот 20, VA 0x4209FA).
  const mapTrack = worldMap.onMap
    ? sound.rules?.tracks?.global_map
    : world.map?.audio?.map_track;
  const track = sound.musicOverride ?? mapTrack;
  if (!track || !sound.context || !sound.musicOn) return;
  if (sound.music?.slot === track) return;
  playMusic(track);
}

export function soundscapeTick(now) {
  const seconds = now / 1000;
  if (seconds - scape.clock < TICK_SECONDS) return;
  // здесь не догоняем пропущенные такты: у жребиев движка нет долга
  scape.clock = seconds;
  scape.ticks += 1;
  if (!world.map || !sound.ready || !hero.alive) return;
  // На глобальной карте главный цикл движка идёт другим режимом: ни
  // амбиента локации, ни приветствий там нет — только её трек.
  if (!worldMap.onMap) {
    ambientOnce();
    if ((scape.ticks & 0x3FF) === 0) greetingOnce();  // раз в 1024 такта
  }
  musicFollowsMap();
}
