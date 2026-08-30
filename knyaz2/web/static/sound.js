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
  music: null,          // { source, gain, slot, path }
  musicWanted: null,    // путь последней ЗАПРОШЕННОЙ дорожки — против гонки
  musicOverride: null,  // слот, выбранный панелью вручную (сильнее карты)
  unitVoice: null,      // синглтон голосового отклика
  dialogVoice: null,    // синглтон реплики диалога
  queue: [],            // догрузка карты по одному слоту за тик
  played: 0, misses: 0, // диагностика: сыграно / промахов кэша
  //: ХВОСТ СЫГРАННОГО — для вопросов «что это сейчас прозвучало». Звук
  //: живёт мгновение, и по счётчику `played` не понять, ЧТО именно играло:
  //: «много одинаковых голосов при загрузке» на счётчике неотличимо от
  //: «много разных». Держим последние RECENT_TAIL записей.
  recent: [],
  ready: false,
};

//: Сколько последних звуков помнить. Хватает, чтобы разглядеть залп при
//: входе на карту, и мало, чтобы не думать о памяти.
const RECENT_TAIL = 64;

//: ОТКУДА ЗВУК — только для залпа при загрузке. Стек берётся, пока хвост
//: набирается в первый раз: именно там сидят вопросы вида «почему один и
//: тот же отклик звучит десять раз подряд», а живой перехват из консоли их
//: не ловит — он ставится уже после залпа. Дальше стек не снимается: он
//: недёшев, а на устоявшейся игре и не нужен.
let traced = 0;

function remember(kind, slot, path) {
  const record = { род: kind, слот: slot, файл: path ?? null };
  if (traced < RECENT_TAIL) {
    traced += 1;
    record.откуда = new Error().stack.split("\n").slice(2, 6)
      .map((line) => line.trim().replace(/^at\s+/, ""))
      .filter((line) => !line.includes("/sound.js"));
  }
  sound.recent.push(record);
  if (sound.recent.length > RECENT_TAIL) sound.recent.shift();
}

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

//: Запись слота: сперва набор своей игры, потом канонный. Канонный остаётся
//: запасным осознанно — у донора 118 наших слотов нет вовсе, и без отката
//: удар мечом на его карте стал бы немым.
//:
//: Набор берётся у карты, но не всегда: у карты мира он КАНОННЫЙ, потому что
//: карта мира в мире одна на две игры. Отсюда явный довод — вызывающий может
//: назвать банк сам, и по умолчанию это банк текущей карты.
export function slotEntry(slot, game = sound.game) {
  const key = String(slot);
  return (game ? sound.slots?.[`${game}:${key}`] : null)
    ?? sound.slots?.[key] ?? null;
}

export async function soundInit() {
  if (sound.ready) return sound;
  const [index, voices] = await Promise.all([
    readJson(contentUrl("assets/audio.json")),
    readJson(contentUrl("assets/voices.json")),
  ]);
  sound.rules = index.rules;
  sound.slots = index.slots;
  //: ЧЕЙ НАБОР ЗВУКОВ. Номера общие, а звуки под ними у двух игр разные:
  //: из 376 общих слотов не совпал НИ ОДИН, а у десяти совпала только
  //: длительность. Приставку ставит карта (`map.audio.game`), и слот
  //: ищется сперва под ней.
  sound.game = null;
  sound.voices = voices;
  sound.ready = true;
  // Браузер не даёт звук до жеста — контекст заводится по первому же.
  const wake = () => { ensureContext(); };
  document.addEventListener("pointerdown", wake, { once: true });
  document.addEventListener("keydown", wake, { once: true });
  // вечный набор оригинала: UI + отклики (0x43C228); четвёрка героя — при
  // входе на карту, когда известен его актёр
  loadEternal();
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

//: КЛЮЧ КЭША — ПУТЬ К ФАЙЛУ, А НЕ НОМЕР СЛОТА. Номер уникален внутри одной
//: игры, а у нас их две, и под одним номером лежат разные звуки: канонный
//: слот 20 это тема карты мира на 39 секунд, донорский — обрывок на 0.37.
//: Пока ключом был номер, звук из чужого банка садился в кэш и потом играл
//: вместо своего; на карте мира это давало треть секунды по кругу. Путь
//: уникален всегда, и вопрос закрыт целиком: чей звук — решает только тот,
//: кто выбрал запись слота.
function fetchBuffer(path) {
  const cached = sound.buffers.get(path);
  if (cached) return cached;
  const promise = fetch(contentUrl(path))
    .then((response) => {
      if (!response.ok) throw new Error(`${response.status}: ${path}`);
      return response.arrayBuffer();
    })
    .then((raw) => ensureContext().decodeAudioData(raw))
    .then((buffer) => { sound.buffers.set(path, buffer); return buffer; })
    .catch((error) => { sound.buffers.delete(path); console.warn(error); return null; });
  sound.buffers.set(path, promise);
  return promise;
}

function slotBuffer(slot) {
  // Кэш-промах молчит, как в движке; звук доедет с очередью карты.
  const entry = slotEntry(slot);
  const buffer = entry ? sound.buffers.get(entry.path) : null;
  if (!buffer || buffer instanceof Promise) {
    sound.misses += 1;
    return null;
  }
  return buffer;
}

export function preloadSlots(slotNumbers) {
  for (const slot of slotNumbers) {
    const entry = slotEntry(slot);
    if (entry) fetchBuffer(entry.path);
  }
}

//: ВЕЧНЫЙ НАБОР ОРИГИНАЛА: интерфейс и отклики (0x43C228). У движка арена
//: поделена на две части: эта загружена всегда, а переиспользуемую он
//: сбрасывает на каждой карте (курсор 0x849558). Держим так же — иначе
//: одно из двух: либо чистка карты уносит вечный набор навсегда (очередь
//: входа его не несёт, а промах кэша молчит и не догружает), либо мы не
//: чистим вовсе и копим декодированный PCM со всех пройденных карт.
const permanent = new Set();

//: Слоты вечного набора для ТЕКУЩЕГО банка: у двух игр под ними разные
//: звуки, поэтому при смене игры набор берётся заново.
function eternalSlots() {
  const streaming = sound.rules.streaming;
  const slots = [];
  for (let slot = streaming.preload_ui[0]; slot < streaming.preload_ui[1];
       slot += 1) slots.push(slot);
  for (let slot = streaming.preload_responses[0];
       slot < streaming.preload_responses[1]; slot += 1) slots.push(slot);
  return slots;
}

//: Взять вечный набор своего банка и запомнить, что он не выбрасывается.
function loadEternal() {
  permanent.clear();
  for (const slot of eternalSlots()) {
    const entry = slotEntry(slot);
    if (!entry) continue;
    permanent.add(entry.path);
    fetchBuffer(entry.path);
  }
}

//: Сброс переиспользуемой части арены: всё, кроме вечного набора и хвоста
//: реплик (у него свой предел, LINE_CACHE).
function releaseMapBuffers() {
  const lines = new Set(sound.lineKeys);
  for (const key of [...sound.buffers.keys()]) {
    if (!permanent.has(key) && !lines.has(key)) sound.buffers.delete(key);
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
  //: Чей набор звуков у этой карты. Ставится ДО очереди и до предзагрузки:
  //: обе ищут слоты через slotEntry, то есть с приставкой.
  const game = audioBlock?.game ?? null;
  const switched = game !== sound.game;
  sound.game = game;
  //: Переиспользуемая часть арены сбрасывается на каждой карте, как курсор
  //: 0x849558 у движка; вечный набор остаётся. А сменилась игра — вечный
  //: набор берётся заново: под теми же номерами у неё другие звуки.
  releaseMapBuffers();
  if (switched) loadEternal();
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
      if (slotEntry(slot)) sound.queue.push(slot);
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
    const entry = slotEntry(slot);
    if (!entry) continue;                    // пустой слот — как у движка
    fetchBuffer(entry.path);                 // ровно ОДИН слот за такт
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
  remember("эффект", slot, slotEntry(slot)?.path);
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
//
// «ТОТ ЖЕ ТРЕК» — ЭТО ТОТ ЖЕ ФАЙЛ, А НЕ ТОТ ЖЕ НОМЕР. У двух игр под одним
// номером разная музыка, и сравнение по номеру оставляло играть канонную
// тему на донорской карте (и наоборот). Банк можно назвать явно: у карты
// мира он канонный, она в мире одна на две игры.
export async function playMusic(slot, game = sound.game) {
  if (!sound.ready) return;
  const entry = slotEntry(slot, game);
  if (!entry || sound.music?.path === entry.path) return;
  // ПОСЛЕДНИЙ ПОПРОСИВШИЙ ВЫИГРЫВАЕТ, А НЕ ПОСЛЕДНИЙ ДОЖДАВШИЙСЯ. Буфер
  // едет асинхронно, и на входе на карту вызовов бывает два подряд — с
  // разными наборами под ОДНИМ номером. Чей буфер приедет первым, заранее
  // не известно, и однажды выигрывал опоздавший: под номером 38 у канона
  // звук на 0.34 с, и он крутился петлёй вместо дорожки донора на 32 с.
  sound.musicWanted = entry.path;
  const buffer = await fetchBuffer(entry.path);
  if (!buffer || sound.musicWanted !== entry.path) return;
  if (sound.music?.path === entry.path) return;
  stopMusic();
  const context = ensureContext();
  const source = context.createBufferSource();
  source.buffer = buffer;
  source.loop = true;
  const gain = context.createGain();
  gain.gain.value = sound.musicOn ? 1 : 0;
  source.connect(gain).connect(context.destination);
  source.start();
  sound.music = { source, gain, slot, path: entry.path };
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
  const buffer = await fetchBuffer(entry.path);
  rememberLine(entry.path);
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
  remember("реплика", index, entry.path);
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
    //: Что играло последним — с конца, как читают журнал.
    последние: sound.recent.slice(-16).reverse(),
  };
}
