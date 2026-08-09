// Звук: WebAudio-ядро по канону движка (docs/AUDIO_AUDIT.md, konung2/sounds.py).
//
// Ни одной формулы здесь не выдумано: пороги, шансы, питчи и лимиты приезжают
// из пака (assets/audio.json — rules() из konung2/sounds.py), а поведение
// повторяет DirectSound-путь оригинала:
//   * до 45 одновременных буферов (0x8A7744), тише −40 дБ не заводится;
//   * кэш-промах МОЛЧИТ (0x42D660 требует слот в 0x840D04) — только счётчик;
//   * три уровня загрузки: вечный набор при старте, очередь карты по ОДНОМУ
//     слоту за тик мира (0x43F07C), реплики и музыка — в момент нужды;
//   * синглтоны: музыка, голос юнита (0x84963C, новый при живом молчит),
//     реплика диалога (0x849670, новая глушит старую);
//   * громкость музыки бинарная (0x42D0E8): вкл — 1, выкл — 0.
import { contentUrl, readJson } from "./content.js";
import { view } from "./viewport.js";
import { world } from "./world.js";

// Порт пиксель→клетка (VA 0x43B9B0) живёт в hero.js, а тот тянет orders —
// прямой импорт замкнул бы петлю модулей. Точка входа отдаёт функцию сюда.
let cellAtPoint = null;
export function soundBindCell(fn) { cellAtPoint = fn; }

export const sound = {
  context: null,
  rules: null,          // канон из assets/audio.json
  slots: null,          // опись слотов: {"6": {path, seconds}, ...}
  voices: null,         // опись реплик из assets/voices.json
  enabled: true,        // «звук» (0x849614)
  musicOn: true,        // «музыка» (0x8495E4)
  buffers: new Map(),   // key -> AudioBuffer | Promise
  lineKeys: [],         // порядок реплик в кэше — держим только хвост
  active: new Set(),    // играющие источники (лимит из rules)
  music: null,          // { source, gain, slot }
  musicOverride: null,  // слот, выбранный панелью вручную (сильнее карты)
  unitVoice: null,      // синглтон голосового отклика
  dialogVoice: null,    // синглтон реплики диалога
  queue: [],            // догрузка карты по одному слоту за тик
  played: 0, misses: 0, // диагностика: сыграно / промахов кэша
  ready: false,
};

const TICK_SECONDS = 1 / 18;      // такт мира — как у догрузки движка
const LINE_CACHE = 16;            // репликам хватает короткого хвоста
let tickClock = 0;

//: НАШИ включения поверх канона — звуки, записанные в SOUNDS.RES, но не
//: звучавшие в оригинале (docs/AUDIO_AUDIT.md §3, §9). Включены решением
//: пользователя 2026-08-08 после прослушивания в sound_lab; false возвращает
//: чистый канон.
//:  * specialStateSounds — спец-звуки «состояния 4»: лодка (слот 121) и
//:    исчезающий дух (169); в оригинале их глушил кэш-промах предзагрузки.
//: Бывший фикс alternateVoiceTakes убран: дорожки +2/+4 восьмёрок 32…79
//: оказались НЕ дублями отклика, а криками боли/смерти (на слух; движок их
//: не зовёт ниоткуда) — в ротации призыва они звучали абсурдно.
export const fixes = {
  specialStateSounds: true,
};

// ---- инициализация ---------------------------------------------------------

export async function soundInit() {
  if (sound.ready) return sound;
  const [index, voices] = await Promise.all([
    readJson(contentUrl("assets/audio.json")),
    readJson(contentUrl("assets/voices.json")),
  ]);
  sound.rules = index.rules;
  sound.slots = index.slots;
  sound.voices = voices;
  sound.ready = true;
  // Браузер не даёт звук до жеста — контекст заводится по первому же.
  const wake = () => { ensureContext(); };
  document.addEventListener("pointerdown", wake, { once: true });
  document.addEventListener("keydown", wake, { once: true });
  // вечный набор оригинала: UI + отклики (0x43C228); четвёрка героя — при
  // входе на карту, когда известен его актёр
  const streaming = sound.rules.streaming;
  const eternal = [];
  for (let slot = streaming.preload_ui[0]; slot < streaming.preload_ui[1]; slot += 1) {
    eternal.push(slot);
  }
  for (let slot = streaming.preload_responses[0];
       slot < streaming.preload_responses[1]; slot += 1) {
    eternal.push(slot);
  }
  preloadSlots(eternal);
  // Карта могла загрузиться раньше канона — повторяем вход с сохранённым.
  if (sound.entered) soundMapEnter(sound.entered.audioBlock, sound.entered.heroActor);
  return sound;
}

export function ensureContext() {
  if (!sound.context) {
    sound.context = new (window.AudioContext || window.webkitAudioContext)();
  }
  if (sound.context.state === "suspended") sound.context.resume();
  return sound.context;
}

// ---- буферы и уровни загрузки ----------------------------------------------

function fetchBuffer(key, path) {
  const cached = sound.buffers.get(key);
  if (cached) return cached;
  const promise = fetch(contentUrl(path))
    .then((response) => {
      if (!response.ok) throw new Error(`${response.status}: ${path}`);
      return response.arrayBuffer();
    })
    .then((raw) => ensureContext().decodeAudioData(raw))
    .then((buffer) => { sound.buffers.set(key, buffer); return buffer; })
    .catch((error) => { sound.buffers.delete(key); console.warn(error); return null; });
  sound.buffers.set(key, promise);
  return promise;
}

function slotBuffer(slot) {
  // Кэш-промах молчит, как в движке; звук доедет с очередью карты.
  const buffer = sound.buffers.get(`s${slot}`);
  if (!buffer || buffer instanceof Promise) {
    sound.misses += 1;
    return null;
  }
  return buffer;
}

export function preloadSlots(slotNumbers) {
  for (const slot of slotNumbers) {
    const entry = sound.slots?.[String(slot)];
    if (entry) fetchBuffer(`s${slot}`, entry.path);
  }
}

// Вход на карту: очередь догрузки амбиента и местных зверей (0x43DF48) и
// четвёрка «пошёл» текущего героя (0x43D898). Очередь разбирается по одному
// слоту за такт — soundTick ниже. Карта может прийти РАНЬШЕ канона (boot
// грузит их параллельно) — тогда вход запоминается и повторяется из
// soundInit, когда правила приехали.
export function soundMapEnter(audioBlock, heroActor = 0) {
  sound.entered = { audioBlock, heroActor };
  if (!sound.ready) return;
  sound.queue = [...(audioBlock?.preload ?? [])];
  // Четвёрка «Эй, есть разговор!» героя (0x43D898): обе базы его актёра.
  // Пак может несёт канон прежней сборки без talk_request — тогда без неё:
  // упавший здесь boot оставлял клиента вовсе без звуковой шины.
  const talk = sound.rules.voices?.talk_request;
  if (talk) {
    const base = talk.base + heroActor * talk.stride;
    for (let i = 0; i < talk.stride; i += 1) sound.queue.push(base + i);
  }
  // Починка предзагрузки оригинала: спец-слоты «запись*8+49» местных
  // зверей движок в очередь не ставил — потому лодка и дух молчали.
  if (fixes.specialStateSounds) {
    const creatures = sound.rules.creatures;
    for (const unit of world.map?.units ?? []) {
      const breed = unit.breed ?? 0;
      if (!(breed & 0x40)) continue;
      const slot = (breed & 0x3F) * creatures.stride + creatures.special_offset;
      if (sound.slots[String(slot)]) sound.queue.push(slot);
    }
  }
}

export function soundTick(now) {
  const seconds = now / 1000;
  if (seconds - tickClock < TICK_SECONDS) return false;
  tickClock = seconds;
  if (!sound.ready) return false;            // канон ещё едет — очередь ждёт
  while (sound.queue.length) {
    const slot = sound.queue.shift();
    const entry = sound.slots[String(slot)];
    if (!entry) continue;                    // пустой слот — как у движка
    fetchBuffer(`s${slot}`, entry.path);     // ровно ОДИН слот за такт
    break;
  }
  return false;
}

// ---- арифметика движка ------------------------------------------------------

// Сотые дБ DirectSound -> множитель громкости.
export function gainOf(volume100) {
  if (volume100 <= (sound.rules?.mixer.silence ?? -10000)) return 0;
  return Math.pow(10, volume100 / 2000);
}

export function panOf(pan100) {
  return Math.max(-1, Math.min(1, pan100 / 10000));
}

// Громкость по расстоянию до центра экрана (VA 0x43BC74): линейный спад,
// дальше радиуса — тишина. Деление целочисленное, к нулю.
export function positionVolume(distance) {
  const { hearing_radius: radius } = sound.rules.position;
  const silence = sound.rules.mixer.silence;
  if (distance > radius) return silence;
  return -Math.trunc((distance * -silence) / radius);
}

// Пан от колонки (VA 0x43BC20): 62.5 сотых за колонку от точки
// «левая видимая колонка + 5». Банковское округление — как fistp.
export function positionPan(columnDelta) {
  const scaled = columnDelta * sound.rules.position.pan_per_column;
  const nearest = Math.round(scaled);
  if (Math.abs(scaled - Math.trunc(scaled)) === 0.5 && nearest % 2 !== 0) {
    return nearest - Math.sign(scaled);
  }
  return nearest;
}

// Позиционные параметры клетки: якорь юнита в мире (VA 0x43B974) против
// центра видимой области (в движке — окно 884x709, у нас камера и есть центр).
export function positional(row, col) {
  const grid = world.map?.coordinates?.navigation_grid;
  if (!grid) return { volume: 0, pan: 0 };
  const x = col * grid.cell_width +
    (row & 1 ? grid.anchor_x_odd : grid.anchor_x_even);
  const y = row * grid.cell_height + grid.anchor_y;
  const distance = Math.round(Math.hypot(view.cameraX - x, view.cameraY - y));
  if (!cellAtPoint) return { volume: positionVolume(distance), pan: 0 };
  const halfWidth = (view.width / 2) / view.zoom;
  const leftColumn = cellAtPoint(view.cameraX - halfWidth, view.cameraY).col;
  const reference = leftColumn + sound.rules.position.pan_center_shift;
  return { volume: positionVolume(distance), pan: positionPan(col - reference) };
}

// ---- проигрыватели ----------------------------------------------------------

function reap() {
  for (const node of [...sound.active]) {
    if (node.__done) sound.active.delete(node);
  }
}

// Эффект (0x42D660): гейты и вариация питча движка. Возвращает узел-источник
// (им же можно остановить) или null — по всем тем же причинам, что оригинал.
// varyPitch=false — путь голосов (0x42D308/0x42D9FC): у них своя частота,
// случайной тройки эффектов там нет.
export function playEffect(slot, { volume = 0, pan = 0, loop = false,
                                   varyPitch = true } = {}) {
  if (!sound.ready || !sound.enabled || !sound.context) return null;
  if (volume < sound.rules.mixer.volume_gate) return null;
  reap();
  if (sound.active.size >= sound.rules.mixer.max_buffers) return null;
  const buffer = slotBuffer(slot);
  if (!buffer) return null;

  const context = sound.context;
  const source = context.createBufferSource();
  source.buffer = buffer;
  source.loop = loop;
  const { rates, ui_slots: uiSlots, slot_range: range } = sound.rules.pitch;
  const pitched = varyPitch &&
    ((slot >= range[0] && slot < range[1]) || uiSlots.includes(slot));
  if (pitched) {
    const rate = rates[Math.floor(Math.random() * rates.length)];
    source.playbackRate.value = rate / rates[0];
  }
  const gain = context.createGain();
  gain.gain.value = gainOf(volume);
  const panner = context.createStereoPanner();
  panner.pan.value = panOf(pan);
  source.connect(gain).connect(panner).connect(context.destination);
  source.onended = () => { source.__done = true; };
  source.start();
  sound.active.add(source);
  sound.played += 1;
  return source;
}

export function playPositional(slot, row, col, options = {}) {
  const at = positional(row, col);
  return playEffect(slot, { ...options, volume: at.volume, pan: at.pan });
}

export function stopEffect(source) {
  if (!source) return;
  try { source.stop(); } catch { /* уже остановлен */ }
  source.__done = true;
}

// Музыка (0x42D13C): один зацикленный буфер; повторный запуск того же трека
// ничего не делает; громкость бинарная (0x42D0E8).
export async function playMusic(slot) {
  if (!sound.ready || sound.music?.slot === slot) return;
  const entry = sound.slots?.[String(slot)];
  if (!entry) return;
  const buffer = await fetchBuffer(`s${slot}`, entry.path);
  if (!buffer || sound.music?.slot === slot) return;
  stopMusic();
  const context = ensureContext();
  const source = context.createBufferSource();
  source.buffer = buffer;
  source.loop = true;
  const gain = context.createGain();
  gain.gain.value = sound.musicOn ? 1 : 0;
  source.connect(gain).connect(context.destination);
  source.start();
  sound.music = { source, gain, slot };
}

export function stopMusic() {
  if (!sound.music) return;
  try { sound.music.source.stop(); } catch { /* уже остановлен */ }
  sound.music = null;
}

export function setMusicOn(on) {
  sound.musicOn = Boolean(on);
  if (sound.music) sound.music.gain.gain.value = sound.musicOn ? 1 : 0;
}

// Голосовой отклик юнита (0x42D308): один канал, ПРИ ЖИВОМ НОВЫЙ МОЛЧИТ;
// частота — базовая или личная частота голоса, без случайной вариации.
export function playUnitVoice(slot, voiceNumber = null) {
  if (sound.unitVoice && !sound.unitVoice.__done) return null;
  const source = playEffect(slot, { volume: 0, pan: 0, varyPitch: false });
  if (source && voiceNumber !== null) applyVoiceRate(source, voiceNumber);
  sound.unitVoice = source;
  return source;
}

// Реплика диалога (0x42D9FC): новая ГЛУШИТ предыдущую; личный питч голоса.
export async function playVoiceLine(index, voiceNumber = null) {
  if (!sound.ready || !sound.enabled) return null;
  const entry = sound.voices?.lines?.[String(index)];
  if (!entry) return null;
  const buffer = await fetchBuffer(`v${index}`, entry.path);
  rememberLine(`v${index}`);
  if (!buffer || !sound.context) return null;
  stopEffect(sound.dialogVoice);
  const context = sound.context;
  const source = context.createBufferSource();
  source.buffer = buffer;
  if (voiceNumber !== null) applyVoiceRate(source, voiceNumber);
  source.connect(context.destination);
  source.onended = () => { source.__done = true; };
  source.start();
  sound.dialogVoice = source;
  sound.played += 1;
  return source;
}

// Личная частота голоса из _VOICES: воспроизведение быстрее или медленнее
// базовой 22050 — ровно как подстановка WAVEFORMATEX говорящего.
function applyVoiceRate(source, voiceNumber) {
  const rates = sound.rules?.voices?.rates ?? {};
  const rate = rates[String(voiceNumber)];
  if (rate) source.playbackRate.value = rate / sound.rules.voices.base_rate;
}

// Кэш реплик держит только хвост: услышанное второй раз не качается, но и
// сотни реплик в памяти не копятся.
function rememberLine(key) {
  const at = sound.lineKeys.indexOf(key);
  if (at !== -1) sound.lineKeys.splice(at, 1);
  sound.lineKeys.push(key);
  while (sound.lineKeys.length > LINE_CACHE) {
    sound.buffers.delete(sound.lineKeys.shift());
  }
}

export function soundStats() {
  reap();
  return {
    ready: sound.ready,
    unlocked: Boolean(sound.context),
    активных: sound.active.size,
    сыграно: sound.played,
    промахов: sound.misses,
    вОчереди: sound.queue.length,
    буферов: sound.buffers.size,
    музыка: sound.music?.slot ?? null,
  };
}
