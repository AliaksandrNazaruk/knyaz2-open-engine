// Звуковая лаборатория: каталог слотов пака с канонными формулами.
//
// Страница нарочно НЕ зависит от модулей клиента (world, hero): это стенд
// для ушей и чисел, он ходит в пак напрямую. Правила берёт те же —
// assets/audio.json, поэтому питч, громкость и пан ведут себя как в игре.

const contentUrl = (path) =>
  `/content/${path.split("/").map(encodeURIComponent).join("/")}`;

const state = {
  context: null, rules: null, slots: null, voices: null,
  buffers: new Map(), active: new Set(), playing: new Map(),
};

const statsNode = document.getElementById("stats");
const volNode = document.getElementById("vol");
const panNode = document.getElementById("pan");
const pitchNode = document.getElementById("pitch");

//: Имена слотов, снятые с карты вызовов (docs/AUDIO_AUDIT.md §7, §9).
const SLOT_NAMES = {
  0: "надеть кольцо (немой)", 1: "взвод самострела / надеть", 2: "надеть доспех",
  3: "попадание: броня 5", 4: "замах: оружие 0xF", 5: "выстрел лука",
  6: "щелчок интерфейса", 7: "попадание: тело", 8: "сирота",
  9: "попадание: броня", 10: "замах", 11: "окно (немой)",
  12: "промах/в землю", 13: "шаги героя (вырезаны)", 14: "level-up",
  15: "попадание: броня 1", 16: "замах: оружие 0xD", 17: "взять предмет",
  18: "подтверждение", 19: "сирота",
};
const CREATURE_ACTS = { 0: "смерть", 2: "атака", 3: "стойка/ходьба", 4: "бег" };

function ensureContext() {
  if (!state.context) state.context = new AudioContext();
  if (state.context.state === "suspended") state.context.resume();
  return state.context;
}

async function buffer(key, path) {
  const cached = state.buffers.get(key);
  if (cached) return cached;
  const promise = fetch(contentUrl(path))
    .then((r) => { if (!r.ok) throw new Error(`${r.status} ${path}`); return r.arrayBuffer(); })
    .then((raw) => ensureContext().decodeAudioData(raw))
    .then((decoded) => { state.buffers.set(key, decoded); return decoded; });
  state.buffers.set(key, promise);
  return promise;
}

function stopAll() {
  for (const source of state.active) { try { source.stop(); } catch {} }
  state.active.clear();
  for (const [, button] of state.playing) button.classList.remove("playing");
  state.playing.clear();
  refreshStats();
}

async function play(key, path, button, { rate = 1, loop = false } = {}) {
  const decoded = await buffer(key, path);
  const context = ensureContext();
  const source = context.createBufferSource();
  source.buffer = decoded;
  source.loop = loop;
  // питч-вариация движка: случайная из трёх частот, если включена
  const rates = state.rules.pitch.rates;
  const varied = pitchNode.checked
    ? rates[Math.floor(Math.random() * rates.length)] / rates[0] : 1;
  source.playbackRate.value = rate * varied;
  const gain = context.createGain();
  gain.gain.value = volumeGain(Number(volNode.value));
  const panner = context.createStereoPanner();
  panner.pan.value = Math.max(-1, Math.min(1, Number(panNode.value) / 10000));
  source.connect(gain).connect(panner).connect(context.destination);
  source.onended = () => {
    state.active.delete(source);
    if (state.playing.get(key) === button) {
      button.classList.remove("playing");
      state.playing.delete(key);
    }
    refreshStats();
  };
  source.start();
  state.active.add(source);
  if (button) { button.classList.add("playing"); state.playing.set(key, button); }
  refreshStats();
}

function volumeGain(volume100) {
  if (volume100 <= state.rules.mixer.silence) return 0;
  return Math.pow(10, volume100 / 2000);
}

function slotButton(slot, label) {
  const entry = state.slots[String(slot)];
  const button = document.createElement("button");
  button.className = "snd";
  if (!entry) {
    button.classList.add("silent");
    button.innerHTML = `${slot} <small>${label ?? "пусто"}</small>`;
    button.title = "слот пуст в SOUNDS.RES — событие немое";
    button.disabled = true;
    return button;
  }
  button.innerHTML = `${slot} <small>${label ?? ""} · ${entry.seconds}c</small>`;
  button.addEventListener("click", () =>
    play(`s${slot}`, entry.path, button, { loop: slot >= 20 && slot <= 30 }));
  return button;
}

function group(title, note, buttons) {
  const box = document.createElement("fieldset");
  const legend = document.createElement("legend");
  legend.textContent = title;
  box.append(legend);
  if (note) {
    const p = document.createElement("p");
    p.className = "note";
    p.textContent = note;
    box.append(p);
  }
  const row = document.createElement("div");
  row.className = "row";
  row.append(...buttons);
  box.append(row);
  document.getElementById("groups").append(box);
}

function occupiedIn(from, to) {
  return Object.keys(state.slots).map(Number)
    .filter((slot) => slot >= from && slot <= to).sort((a, b) => a - b);
}

function build() {
  const r = state.rules;

  group("Интерфейс и общие (0–19)",
    "вечная предзагрузка движка; серые — события без данных (немые в оригинале)",
    Array.from({ length: 20 }, (_, slot) => slotButton(slot, SLOT_NAMES[slot])));

  group("Музыка (20–30, петли)", "стерео 44100, в игре зациклены",
    occupiedIn(20, 30).map((slot) => slotButton(slot, "трек")));

  const resp = r.voices.response;
  group("Голоса юнитов (32–79)",
    "восьмёрка актёра: +2 крик смерти, +4 крик боли (0x429B2C), " +
    "+5…+7 отклики на выбор (0x42D308)",
    occupiedIn(32, 79).map((slot) => {
      const actor = Math.floor((slot - resp.base) / resp.stride);
      const offset = (slot - resp.base) % resp.stride;
      const label = offset === 2 ? "смерть" : offset === 4 ? "боль" : "отклик";
      return slotButton(slot, `актёр ${actor} · ${label}`);
    }));

  group("Звери (80–255)",
    "вид*8 + {80 смерть, 82 атака, 83 стойка, 84 бег}; 121 и 169 — «немые» спец-звуки лодки и духа",
    occupiedIn(80, 255).map((slot) => {
      const kind = Math.floor((slot - r.creatures.base) / r.creatures.stride);
      const act = CREATURE_ACTS[(slot - r.creatures.base) % r.creatures.stride];
      const special = (slot - r.creatures.special_offset) % 8 === 0;
      return slotButton(slot, special
        ? (slot === 121 ? "ЛОДКА (спец)" : slot === 169 ? "ДУХ (спец)" : "спец")
        : `вид ${kind} · ${act}`);
    }));

  const ambientButtons = [];
  for (let map = 6; map <= 54; map += 1) {
    const base = r.ambient.base + (map - 1) * r.ambient.stride;
    const slots = occupiedIn(base, base + 7);
    if (!slots.length) continue;
    for (const slot of slots) {
      const night = slot - base >= r.ambient.night_offset;
      ambientButtons.push(slotButton(slot, `к${map} ${night ? "ночь" : "день"}`));
    }
  }
  group("Амбиент карт (256–686)",
    "по восьмёрке на карту: +0…+4 день, +5…+7 ночь; в пещерах деление выключено",
    ambientButtons);

  const talk = r.voices.talk_request;
  group("«Эй, есть разговор!» (700–723)",
    "приказ заговорить издалека: 6 актёров × 2 базы (по типу собеседника) × 2 дорожки",
    occupiedIn(700, 723).map((slot) => {
      const actor = Math.floor((slot - talk.base) / talk.stride);
      const alt = (slot - talk.base) % talk.stride >= talk.variants;
      return slotButton(slot, `актёр ${actor}${alt ? " · база 702" : ""}`);
    }));

  // приветствия спутников
  const greetings = document.getElementById("greetings");
  const greet = r.voices.greeting;
  for (let actor = 0; actor < 6; actor += 1) {
    for (let variant = 0; variant < greet.per_actor; variant += 1) {
      const index = greet.base + actor * greet.per_actor + variant;
      const entry = state.voices.lines[String(index)];
      const button = document.createElement("button");
      button.className = "snd";
      button.innerHTML = `${index} <small>актёр ${actor}</small>`;
      if (!entry) { button.classList.add("silent"); button.disabled = true; }
      else button.addEventListener("click", () => play(`v${index}`, entry.path, button));
      greetings.append(button);
    }
  }
}

function refreshStats() {
  const lines = [
    `буферов в кэше: ${state.buffers.size}`,
    `играет: ${state.active.size}`,
    state.context ? `контекст: ${state.context.state}` : "контекст: до первого клика",
  ];
  statsNode.textContent = lines.join("\n");
}

async function main() {
  const [index, voices] = await Promise.all([
    fetch(contentUrl("assets/audio.json")).then((r) => r.json()),
    fetch(contentUrl("assets/voices.json")).then((r) => r.json()),
  ]);
  state.rules = index.rules;
  state.slots = index.slots;
  state.voices = voices;
  build();
  refreshStats();

  volNode.addEventListener("input", () => {
    document.getElementById("volText").textContent = volNode.value;
  });
  panNode.addEventListener("input", () => {
    document.getElementById("panText").textContent = panNode.value;
  });
  document.getElementById("stopAll").addEventListener("click", stopAll);
  document.getElementById("playLine").addEventListener("click", () => {
    const index = Number(document.getElementById("lineNo").value);
    const voice = Number(document.getElementById("voiceNo").value);
    const entry = state.voices.lines[String(index)];
    const info = document.getElementById("lineInfo");
    if (!entry) { info.textContent = `реплики ${index} нет`; return; }
    const rates = state.rules.voices.rates;
    const rate = (rates[String(voice)] ?? state.voices.base_rate) / state.voices.base_rate;
    info.textContent = `${entry.seconds} c` + (rates[String(voice)]
      ? ` · голос ${voice}: ${rates[String(voice)]} Гц` : "");
    play(`v${index}`, entry.path, null, { rate });
  });
}

main().catch((error) => {
  statsNode.textContent = String(error);
  console.error(error);
});

// для отладки из консоли и самопроверок
window.lab = state;
