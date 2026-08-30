// Респавн-механика «Дом2» (docs/BROADCAST_PLAN.md, Ф4): смерть героя не
// конец партии, а откат мира к ЯКОРНОМУ сейву — снимку, сделанному в
// деревне. С погибшего при этом переезжают ТОЛЬКО деньги и сумка (пояс —
// это витрина мешка, отдельного хранилища у него нет), а всё надетое
// пропадает вместе с ним. Уровень, опыт, навыки и мир — какими были в
// якоре: прогресс после якоря сгорает.
//
// Реализация нарочно едет по канонной дороге загрузки: слитое состояние
// кладётся в слот «Продолжить» (savePut), и страница перезагружается —
// применяет его тот же код, что грузит обычный сейв. Своей ветки
// восстановления мира здесь нет, ломаться нечему.
import { hero } from "./hero.js";
import { world } from "./world.js";
import { saveState, saveUsable, savePut } from "./save.js";

//: Якорь лежит отдельным ключом: слот «Продолжить» живёт своей жизнью.
const ANCHOR_KEY = "knyaz2.respawn.anchor.v1";

//: Пауза между смертью и воскрешением — зрителю нужно УВИДЕТЬ смерть.
const REVIVE_DELAY_MS = 5000;

let currentMapOf = () => world.map?.id ?? null;

function readAnchor() {
  try {
    const text = localStorage.getItem(ANCHOR_KEY);
    return text ? JSON.parse(text) : null;
  } catch {
    return null;
  }
}

// Снять якорь с ЖИВОГО героя в текущем месте. Где именно ставить якорь —
// решает вызывающий (агент или игрок в деревне); механике всё равно.
export function respawnAnchorSet() {
  const state = saveState(currentMapOf());
  if (!saveUsable(state)) {
    return { ok: false, reason: "якорь не снят: герой мёртв или не собран" };
  }
  try {
    localStorage.setItem(ANCHOR_KEY, JSON.stringify(state));
  } catch (error) {
    return { ok: false, reason: `якорь не записан: ${error?.message ?? error}` };
  }
  return { ok: true, map: state.map, cell: state.hero?.cell ?? null };
}

export function respawnArmed() { return readAnchor() !== null; }

export function respawnAnchorDrop() {
  try { localStorage.removeItem(ANCHOR_KEY); } catch { /* и пусть */ }
}

// Слить якорь с наследством погибшего. ЧИСТАЯ функция — её гоняет
// самопроверка, ничего не трогая: вход два состояния, выход новое.
//
// Правило наследства: деньги и сумка (с экземплярными картами вещей) — от
// погибшего; надетое НЕ наследуется и в якоре ЗАНУЛЯЕТСЯ вместе со всеми
// полями, живущими на надетых вещах (чары, износ, яд на клинке, стрелы,
// стойка стрельбы). Остальное — мир, уровень, навыки — из якоря как есть.
export function respawnMerge(anchor, dead) {
  const state = JSON.parse(JSON.stringify(anchor));
  const heir = state.hero;
  if (!heir) return state;
  heir.money = dead.money ?? heir.money ?? 0;
  heir.bag = [...(dead.bag ?? [])];
  heir.bagEnchant = { ...(dead.bagEnchant ?? {}) };
  heir.bagStrength = { ...(dead.bagStrength ?? {}) };
  heir.bagCount = { ...(dead.bagCount ?? {}) };
  heir.bagPoison = { ...(dead.bagPoison ?? {}) };
  heir.itemOiled = { ...(dead.itemOiled ?? {}) };
  heir.equipment = Object.fromEntries(
    Object.keys(heir.equipment ?? {}).map((slot) => [slot, null]));
  heir.enchant = {};
  heir.wear = {};
  heir.wearMax = {};
  heir.poisonOn = {};
  heir.ammoCount = null;
  heir.ammoPoison = 0;
  heir.rangedMode = false;
  return state;
}

//: Наследство снимается С ЖИВОГО ОБЪЕКТА героя в момент смерти — packActor
//: сюда не нужен: интересуют только деньги и сумка.
function inheritance() {
  return {
    money: hero.money ?? 0,
    bag: [...(hero.bag ?? [])],
    bagEnchant: { ...(hero.bagEnchant ?? {}) },
    bagStrength: { ...(hero.bagStrength ?? {}) },
    bagCount: { ...(hero.bagCount ?? {}) },
    bagPoison: { ...(hero.bagPoison ?? {}) },
    itemOiled: { ...(hero.itemOiled ?? {}) },
  };
}

// Воскресить сейчас: слить, положить в слот «Продолжить», перезагрузиться.
export function respawnNow() {
  const anchor = readAnchor();
  if (!anchor) return { ok: false, reason: "якоря нет — некуда воскрешать" };
  const merged = respawnMerge(anchor, inheritance());
  if (!savePut(merged)) {
    return { ok: false, reason: "слитое состояние не записалось" };
  }
  world.onStatus?.("Смерть — возврат в деревню");
  location.reload();
  return { ok: true };
}

// ---- надзор за смертью -----------------------------------------------------

//: Авто-воскрешение включено, пока есть якорь и его не выключили ручкой.
export const respawn = { auto: true, pending: false };

function watchTick() {
  if (!respawn.auto || respawn.pending) return;
  if (hero.alive !== false) return;
  if (!respawnArmed()) return;
  respawn.pending = true;
  world.onStatus?.("Героиня пала — деревня ждёт её через несколько мгновений");
  setTimeout(() => { respawnNow(); respawn.pending = false; }, REVIVE_DELAY_MS);
}

// ---- самопроверка ----------------------------------------------------------

// knyaz2.respawn.selfcheck(): правила слияния — числами, без перезагрузки.
export function respawnSelfCheck() {
  const checks = [];
  const rule = (name, ok, value) =>
    checks.push({ rule: name, ok: Boolean(ok), value });

  const anchor = {
    map: 19,
    hero: {
      money: 100, level: 3, experience: 500,
      equipment: { hand: "старый нож", head: "шапка", body: null },
      bag: ["якорная вещь"], bagCount: { "якорная вещь": 1 },
      enchant: { hand: 7 }, wear: { hand: 3 }, wearMax: { hand: 9 },
      poisonOn: { hand: 1 }, ammoCount: 13, ammoPoison: 2, rangedMode: true,
      skills: [1, 2, 3],
    },
  };
  const dead = {
    money: 5432, bag: ["меч из смерти", "зелье"],
    bagCount: { "зелье": 4 }, bagEnchant: { "меч из смерти": 9 },
    bagStrength: {}, bagPoison: {}, itemOiled: { "меч из смерти": true },
  };
  const merged = respawnMerge(anchor, dead);
  const heir = merged.hero;

  rule("деньги переезжают с погибшего", heir.money === 5432, heir.money);
  rule("сумка переезжает с погибшего",
    heir.bag.join(",") === "меч из смерти,зелье" && heir.bagCount["зелье"] === 4,
    heir.bag.join(","));
  rule("надетое пропадает",
    Object.values(heir.equipment).every((slot) => slot === null),
    JSON.stringify(heir.equipment));
  rule("поля надетых вещей зачищены",
    !Object.keys(heir.enchant).length && !Object.keys(heir.wear).length &&
    !Object.keys(heir.poisonOn).length && heir.ammoCount === null &&
    heir.rangedMode === false,
    "enchant/wear/poisonOn/ammo/rangedMode");
  rule("уровень и навыки — из якоря",
    heir.level === 3 && heir.experience === 500 &&
    heir.skills.join(",") === "1,2,3",
    `level ${heir.level}, xp ${heir.experience}`);
  rule("якорь не изменён слиянием",
    anchor.hero.money === 100 && anchor.hero.equipment.hand === "старый нож",
    "исходник цел");
  rule("якорь: снимок текущего состояния пригоден",
    saveUsable(saveState(currentMapOf())) || hero.alive === false,
    hero.alive === false ? "герой мёртв — пропущено" : "пригоден");

  const score = `${checks.filter((entry) => entry.ok).length}/${checks.length}`;
  return { score, checks };
}

// ---- сборка ----------------------------------------------------------------

export function respawnSetup(knyaz2, { currentMap } = {}) {
  if (typeof currentMap === "function") currentMapOf = currentMap;
  //: Свой интервал, как у дифф-тикера агента: смерть надо заметить и при
  //: задушенном rAF фоновой вкладки.
  setInterval(watchTick, 1000);
  knyaz2.respawn = {
    anchor: respawnAnchorSet,
    drop: respawnAnchorDrop,
    armed: respawnArmed,
    revive: respawnNow,
    merge: respawnMerge,
    selfcheck: respawnSelfCheck,
    state: respawn,
  };
  return knyaz2.respawn;
}
