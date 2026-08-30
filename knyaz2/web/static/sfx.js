// События мира → канонные слоты SOUNDS.RES. Вся карта «что чем озвучено» —
// в одном месте, с адресами движка; модули игры зовут одну функцию или
// вообще ничего не знают (часть событий снимается цепочкой с world.on*).
//
// Правила слотов приезжают в rules ядра (assets/audio.json); здесь только
// выбор слота по событию — ровно как в docs/AUDIO_AUDIT.md §7.
// Ни hero, ни units сюда не импортируются: этот модуль зовут orders и units,
// а те стоят ниже hero в графе — петля запрещена. Всё нужное (клетка, тело,
// снаряжение) приходит в аргументах: герой — такой же объект юнита.
import { world } from "./world.js";
import { actorItem } from "./actor.js";
import { fixes, playEffect, playPositional, playUnitVoice, slotEntry, sound }
  from "./sound.js";

const rnd = (n) => Math.floor(Math.random() * n);

// «Голос» юнита для питча — номер его диалога: у юнитов карты поле dialog
// несёт целое дерево, у спутников — отдельное число dialogNumber.
function voiceOf(unit) {
  if (typeof unit?.dialogNumber === "number") return unit.dialogNumber;
  const dialog = unit?.dialog;
  if (typeof dialog === "number") return dialog;
  return dialog?.number ?? null;
}

// Актёр голоса — ТЕЛО юнита (+0xFC). У объекта героя своего поля нет:
// он — первый участник отряда из шаблона пака.
function actorOf(unit) {
  if (typeof unit?.body === "number") return unit.body;
  if (typeof unit?.data?.body === "number") return unit.data.body;
  return world.map?.hero?.template?.party?.members?.[0]?.body ?? 0;
}

function ui() { return sound.rules?.ui; }
function combatRules() { return sound.rules?.combat; }

// ---- интерфейс -------------------------------------------------------------

// Щелчок (слот 6) — универсальный звук кнопок и пунктов (0x421690, 0x437FF8,
// 0x438A00 case 1 и десяток других мест).
export function sfxClick() {
  if (ui()) playEffect(ui().click);
}

//: `sfxTake` удалён: слот 17 — звук ПРИМЕНЕНИЯ ЗЕЛЬЯ (единственный
//: вызывающий — 0x41D954), а подъём и сброс вещи в оригинале немые.
//: Зелья зовут его напрямую (carry.js, playEffect(0x11)).

// Фанфара уровня (0x413110): только сторона игрока — гейт уже в progress.js.
export function sfxLevelUp() { if (ui()) playEffect(ui().level_up); }

// ---- бой --------------------------------------------------------------------

// Замах (0x429B2C, ветка людей): слот по СЛОЮ оружия в руке — двуручные
// мечи (слой 13) → 16, двуручные топоры (15) → 4, остальное → 10.
export function sfxSwing(actor) {
  const rules = combatRules();
  if (!rules) return;
  // ЗВУК — ПО ПОЗЕ, а не по режиму стрельбы: в движке он привязан к
  // смене блока (0x429B2C), и ближний замах лучника — тренировка в
  // казарме прежде всего — должен свистеть, а не натягивать тетиву.
  // Стреляющие позы приходят сюда только из настоящего выстрела.
  const shooting = String(actor?.pose ?? "").startsWith("shoot");
  const weapon = actor?.equipment
    ? actorItem(shooting ? actor.equipment.ranged : actor.equipment.hand)
    : null;
  // Выстрел — набор 4 (0x429B2C): самострел (класс слоя 0x15) взводится
  // слотом 1, лук натягивается слотом 5. Ближний замах — набор 8, по типу.
  let slot;
  if (shooting && weapon) {
    slot = weapon.layer === rules.crossbow_layer
      ? rules.shot_crossbow : rules.shot_bow;
  } else {
    slot = rules.swing[String(weapon?.layer ?? 0)] ?? rules.swing_default;
  }
  const cell = actor?.cell;
  if (cell) playPositional(slot, cell.row, cell.col);
  else playEffect(slot);
}

// Крики людей (0x429B2C): реакция на удар (набор 2) — актёр*8+36, смерть
// (наборы 3/0xB/0xC) — актёр*8+34. Позиционно, обычным эффектным путём.
export function sfxHurtCry(unit) {
  const rules = combatRules();
  const voices = sound.rules?.voices;
  if (!rules || !voices || unit?.beast || !unit?.cell) return;
  const slot = voices.response.base + actorOf(unit) * voices.response.stride +
    rules.hurt_cry_offset;
  playPositional(slot, unit.cell.row, unit.cell.col);
}

export function sfxDeathCry(unit) {
  const rules = combatRules();
  const voices = sound.rules?.voices;
  if (!rules || !voices || unit?.beast || !unit?.cell) return;
  const slot = voices.response.base + actorOf(unit) * voices.response.stride +
    rules.death_cry_offset;
  playPositional(slot, unit.cell.row, unit.cell.col);
}

// Результат удара по человеку (0x412570, зовёт общий тик 0x413894):
//   промах или блок  -> 12 (свист);
//   парировано       -> звон о предмет в руке цели: слой 1 -> 15, 5 -> 3;
//   попало           -> тело без брони -> 7, иначе 9.
// Всё позиционно от клетки ЦЕЛИ. Звери получают удар без этого звука —
// у них своя озвучка действий.
export function sfxHit(defender, outcome) {
  const rules = combatRules();
  if (!rules || defender?.beast) return;
  const cell = defender?.cell;
  if (!cell) return;
  let slot;
  if (outcome === "miss") {
    slot = rules.miss;
  } else if (outcome === "parry") {
    const held = defender?.equipment ? actorItem(defender.equipment.hand) : null;
    slot = rules.armor[String(held?.layer ?? 0)] ?? rules.armor_default;
    if (!held) slot = rules.miss;
  } else {
    const worn = defender?.equipment ? actorItem(defender.equipment.armor) : null;
    slot = worn ? rules.armor_default : rules.body;
  }
  playPositional(slot, cell.row, cell.col);
}

// ---- юниты -------------------------------------------------------------------

// Смена анимации (0x429B2C, ветка зверей): слот вид*8 + {80,82,83,84} с
// шансами движка — стойка 4 %, ходьба 24 %, бег и атака всегда, смерть
// всегда. Всё позиционно. Людям здесь звучит только замах — sfxSwing.
export function sfxPose(unit, pose) {
  const rules = sound.rules?.creatures;
  if (!rules || !unit?.beast || !unit.cell) return;
  const kind = unit.body ?? 0;
  const base = rules.base + kind * rules.stride;
  let offset = null;
  if (pose === "stand") {
    if (rnd(100) < 100 - rules.idle_percent) return;
    offset = rules.idle;
  } else if (pose === "walk") {
    if (rnd(100) < 100 - rules.walk_percent) return;
    offset = rules.idle;
  } else if (pose === "run") {
    offset = rules.run;
  } else if (pose.startsWith("attack")) {
    offset = rules.attack;
  } else if (pose.startsWith("death")) {
    offset = rules.death;
  }
  // Спец-звук «состояния 4» (0x413894: запись*8+49) — включён фиксом.
  // Состояния 4 в клиенте нет, привязка поз наша: лодка (запись 9) гребёт
  // на старте движения, дух (запись 15) воет, исчезая; слот и позиционка —
  // канон, звучат только записанные (в данных это ровно 121 и 169).
  if (fixes.specialStateSounds) {
    const record = (unit.breed ?? 0) & 0x3F;
    const special = record * rules.stride + rules.special_offset;
    const wants = (record === 9 && (pose === "walk" || pose === "run")) ||
                  (record === 15 && pose.startsWith("death"));
    if (wants && slotEntry(special)) {
      playPositional(special, unit.cell.row, unit.cell.col);
    }
  }
  if (offset === null) return;
  playPositional(base + offset, unit.cell.row, unit.cell.col);
}

// Люди на тех же переходах поз (0x429B2C, ветка без бита зверя): боль и
// смерть кричат своими дорожками восьмёрки актёра. Замах и выстрел зовёт
// units.setPose отдельно (sfxSwing), стойки и шаги в данных пусты.
export function sfxHumanPose(unit, pose) {
  if (unit?.beast) return;
  if (pose === "hit") sfxHurtCry(unit);
  else if (pose.startsWith("death")) sfxDeathCry(unit);
}

// Отклик на выбор (0x421690/0x423F80 -> 0x42D308): слот актёр*8+37+rand%3,
// канал один, при живом голосе новый молчит; питч — частота «голоса»
// (номер диалога юнита, файл _VOICES).
export function sfxSelect(unit) {
  const voices = sound.rules?.voices;
  if (!voices || unit?.beast) return;
  const actor = actorOf(unit);
  const { base, stride, offset, variants } = voices.response;
  // Строго канонные дорожки +5…+7 (0x42D308). Дорожки +2/+4 восьмёрки
  // записаны, но движок их не зовёт НИОТКУДА (скан вызовов герметичен), а
  // на слух это крики боли/смерти — подмешивать их в отклик призыва было
  // ошибкой: «нажимаю на перса — слышу реплику получения урона».
  const first = base + actor * stride;
  playUnitVoice(first + offset + rnd(variants), voiceOf(unit));
}

// «Эй, есть разговор!» (0x410A08, case 2 — приказ «подойти и заговорить»):
// звучит, пока игрок ИДЁТ к собеседнику; вплотную (|Δстрок| < 7 и
// |Δколонок| < 4) разговор открывается молча. База 700/702 — по ТИПУ
// собеседника (таблица 0x45FE90), актёр — идущего; сетка 700…723 закрыта
// целиком (6 актёров × 2 базы × 2 варианта), дублей здесь нет. Движение
// (приказ «идти») в движке НЕ озвучивается вовсе.
export function sfxTalkRequest(unit, target) {
  const talk = sound.rules?.voices?.talk_request;
  if (!talk || unit?.beast) return;
  const mine = unit?.cell;
  const theirs = target?.cell;
  if (mine && theirs &&
      Math.abs(mine.row - theirs.row) < talk.near_rows &&
      Math.abs(mine.col - theirs.col) < talk.near_cols) {
    return;                       // уже рядом — сразу разговор, без оклика
  }
  const actor = actorOf(unit);
  const base = talk.alt_base_types.includes(target?.type ?? 0)
    ? talk.alt_base : talk.base;
  playUnitVoice(base + actor * talk.stride + rnd(talk.variants),
                voiceOf(unit));
}

// ---- подключение --------------------------------------------------------------

// Цепочки поверх мировых хуков: sfx ставится ПОСЛЕ раскладки хуков карты
// (конец enterMap/boot), запоминает прежний обработчик и зовёт его следом.
function chain(name, extra) {
  const previous = world[name];
  world[name] = (...args) => {
    extra(...args);
    return previous?.(...args);
  };
}

export function sfxSetup({ hero } = {}) {
  // Хуки оборачиваются ровно один раз: повторный вызов намотал бы вторую
  // цепочку, и каждое событие звучало бы дважды.
  if (sfxSetup.done) return;
  sfxSetup.done = true;
  chain("onLevelUp", () => sfxLevelUp());
  // ПОДЪЁМ И СБРОС ВЕЩИ В ОРИГИНАЛЕ НЕМЫЕ. По всем 26 вызовам проигрывателя
  // 0x42D660 в декомпиляте: «положить в клетку» (0x423360), ветка «уронить»
  // (0x421690:156-168), «взять» (0x423538/0x420B7C) звука не зовут вовсе.
  // Здесь на оба события вешался слот 17 — а он у движка играет РОВНО из
  // одного места, 0x41D954, и это ПРИМЕНЕНИЕ ЗЕЛЬЯ (строка «взять/положить
  // предмет | 17» в AUDIO_AUDIT.md подписана неверно). Оттого при сбросе
  // лута и звучало зелье.
  chain("onOrder", (unit, kind, row, col, target) => {
    // Озвучен только приказ «подойти и заговорить» (0x410A08, case 2) —
    // и его в движке отдаёт ИГРОК. Движение и приказ цели идут молча.
    const kinds = world.map?.hero?.rules?.orders?.kind ?? {};
    if (unit === hero && kind === (kinds.talk ?? 2) && target) {
      sfxTalkRequest(unit, target);
    }
  });
  // Щелчок интерфейса: одна делегация вместо правок в каждом обработчике.
  // Кнопки ПАНЕЛИ и окон — как в движке слот 6 на элементах интерфейса;
  // мир (канвас) сюда не попадает.
  if (!sfxSetup.clicksBound) {
    sfxSetup.clicksBound = true;
    document.addEventListener("click", (event) => {
      const button = event.target.closest("button, select, input[type=checkbox]");
      if (button && !button.closest("#lab")) sfxClick();
    });
  }
}
