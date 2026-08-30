// Агентские ручки: ИИ-игрок и лента трансляции (docs/BROADCAST_PLAN.md, Ф0).
//
// Три вещи в одном модуле:
//   снапшот     — всё, что агент «видит», одним объектом и в одних терминах;
//   исполнитель — действия словами предметной области, а не пикселями;
//   журнал      — события с меткой мирового такта: ими будят модель, они же
//                 пойдут кадрами в ленту трансляции (Ф2).
//
// КЛЕТКИ ВЕЗДЕ ШАГОВОЙ СЕТКИ — той же, что hero.cell и unit.cell. Тайловая
// ground_grid наружу не отдаётся вовсе: смешение двух сеток уже уводило
// героя через полкарты. Перевод клетки в пиксели мира — только heroAnchor.
//
// Журнал подписывается на одноместные хуки world.on*. Их переназначает
// каждый вход на карту, поэтому обёртки ставятся ЗАНОВО и идемпотентно:
// своя помечена меткой, чужую оборачиваем, вызывая прежнюю первой.
import { world } from "./world.js";
import { hero, heroAnchor } from "./hero.js";
import { units, unitAt } from "./units.js";
import { loot, lootHidden, lootNear } from "./loot.js";
import { dialog, dialogChoose, dialogClose, dialogOptions } from "./dialog.js";
import { orderAt } from "./combat.js";
import { trade, tradeFinish, tradeMove, tradeClose } from "./trade.js";
import { worldMap } from "./worldmap.js";
import { clock } from "./clock.js";
import { daylight } from "./daylight.js";
import { gameMenuOpen } from "./gamemenu.js";
import { actorItemName } from "./actor.js";

//: Журнал — кольцо: старое вытесняется, счёт потерянного копится в dropped.
const JOURNAL_CAP = 600;
const journal = [];
let dropped = 0;

//: Хуки, за которыми смотрит журнал. Одноместные слоты app.js/ui.js.
const TAPPED = [
  "onStatus", "onPickup", "onDrop", "onExit", "onTransition", "onLevelUp",
  "onOrder", "onTrade", "onTalk", "onDialog", "onUnitStrike", "onHealth",
  "onPoisonDamage", "onVillageAlarm", "onTravel", "onAttackOrder",
];

function note(type, data = {}) {
  journal.push({ t: clock.ticks, day: daylight.time, type, ...data });
  if (journal.length > JOURNAL_CAP) { journal.shift(); dropped += 1; }
}

// Аргументы хуков — юниты, двери, вещи. В журнал кладутся ИМЕНА и числа:
// живых ссылок журнал не держит, чтобы лента могла уехать по сети как есть.
function plain(value) {
  if (value == null) return value;
  if (typeof value === "string") {
    // имя экземпляра вещи разыменовывается в имя класса
    return value.startsWith("instance:") ? actorItemName(value) : value;
  }
  if (typeof value === "number" || typeof value === "boolean") return value;
  if (typeof value === "object") {
    if (value.name) return value.name;                     // юнит или герой
    if (value.to_name !== undefined) return value.to_name; // дверь
    if (value.items) return (value.items ?? []).map(plain); // куча
    if (value.text) return String(value.text).slice(0, 120); // реплика
  }
  return undefined;
}

function tapOne(slot) {
  const previous = world[slot];
  if (previous?.__agentTap) return;
  const wrapped = (...args) => {
    const result = previous?.(...args);
    // onDialog зовётся и репликой, и закрытием — различаем по состоянию.
    if (slot === "onDialog") {
      note(dialog.unit ? "dialog_line" : "dialog_end", {
        who: dialog.unit?.name,
        text: dialog.line ? plain(dialog.line) : undefined,
      });
    } else {
      const described = args.map(plain).filter((v) => v !== undefined);
      note(slot, described.length ? { what: described } : {});
    }
    return result;
  };
  wrapped.__agentTap = true;
  world[slot] = wrapped;
}

function tapAll() { for (const slot of TAPPED) tapOne(slot); }

//: Диффы, которых хуками не поймать: смерть, уровень, карта, урон.
const seen = { alive: null, level: null, map: null, health: null };

function diffTick() {
  tapAll();  // вход на карту переназначает слоты — вернуть обёртки
  const map = world.map?.id ?? null;
  if (seen.map !== map) {
    if (seen.map !== null) note("map_change", { map: world.map?.name });
    seen.map = map;
  }
  if (seen.alive !== hero.alive) {
    if (seen.alive !== null) note(hero.alive ? "hero_revived" : "hero_died", {});
    seen.alive = hero.alive;
  }
  if (seen.level !== hero.level) {
    if (seen.level !== null) note("hero_level", { level: hero.level });
    seen.level = hero.level;
  }
  const health = hero.health;
  if (seen.health !== null && typeof health === "number" && health < seen.health) {
    note("hero_damage", { lost: seen.health - health, health });
  }
  if (typeof health === "number") seen.health = health;
}

// ---- снапшот ---------------------------------------------------------------

let currentMapOf = () => world.map?.id ?? null;

// Единый режим игры. Раньше он был размазан по трём флагам, и агент,
// не заметив ухода на глобальную карту, слал приказы в пустую сцену.
export function agentMode() {
  if (gameMenuOpen()) return "menu";
  if (hero.alive === false) return "dead";
  if (dialog.unit) return "dialog";
  if (trade.open) return "trade";
  if (currentMapOf() == null) return "worldmap";
  return "local";
}

function distanceTo(cell) {
  if (!cell || !hero.cell) return null;
  return Math.abs(cell.row - hero.cell.row) + Math.abs(cell.col - hero.cell.col);
}

function namesOf(list) {
  return (list ?? []).filter(Boolean).map((name) => actorItemName(name));
}

export function agentSnapshot({ unitsCap = 12, lootCap = 10, journalTail = 12 } = {}) {
  const mode = agentMode();
  const result = {
    mode,
    map: { id: currentMapOf(), name: world.map?.name ?? null },
    time: { ticks: clock.ticks, day: daylight.time },
    hero: {
      cell: hero.cell ? { ...hero.cell } : null,
      health: hero.health, maxHealth: hero.maxHealth,
      level: hero.level, experience: hero.experience,
      freeExperience: hero.freeExperience, money: hero.money,
      moving: hero.moving, orderKind: hero.orderKind, busy: hero.busy,
      equipment: Object.fromEntries(Object.entries(hero.equipment ?? {})
        .filter(([, name]) => name)
        .map(([slot, name]) => [slot, actorItemName(name)])),
      bag: namesOf(hero.bag),
    },
    units: units.filter((unit) => unit.alive !== false && unit !== hero)
      .map((unit) => ({
        name: unit.name, cell: unit.cell ? { ...unit.cell } : null,
        distance: distanceTo(unit.cell),
        hostile: Boolean(unit.hostile), health: unit.health,
      }))
      .sort((a, b) => (a.distance ?? 1e9) - (b.distance ?? 1e9))
      .slice(0, unitsCap),
    loot: loot.filter((pile) => !pile.taken && pile.items?.length &&
        pile.cell && !lootHidden(pile))
      .map((pile) => ({
        cell: { ...pile.cell }, distance: distanceTo(pile.cell),
        items: namesOf(pile.items),
      }))
      .sort((a, b) => (a.distance ?? 1e9) - (b.distance ?? 1e9))
      .slice(0, lootCap),
    exits: (world.map?.exits ?? []).map((door) => ({
      to: door.to_name, rows: [door.row1, door.row2], cols: [door.col1, door.col2],
    })),
    dialog: dialog.unit ? {
      with: dialog.unit.name,
      text: dialog.line?.text ?? null,
      options: dialogOptions().map((option, index) =>
        ({ index, text: option.text })),
    } : null,
    trade: trade.open ? {
      partner: trade.partner?.name ?? "куча",
      myBag: namesOf(trade.columns?.[0]),
      myOffer: namesOf(trade.columns?.[1]),
      theirGoods: namesOf(trade.columns?.[2]),
      myPick: namesOf(trade.columns?.[3]),
    } : null,
    journal: journal.slice(-journalTail),
  };
  return result;
}

// ---- исполнитель -----------------------------------------------------------

function fail(reason) { return { ok: false, reason }; }
function done(result) { return { ok: true, result }; }

function unitByName(name) {
  return units.find((unit) => unit.name === name && unit.alive !== false) ?? null;
}

// ЦЕЛИТЬСЯ В ТЕЛО, А НЕ В ПЯТКИ. Приказ по юниту разбирается попиксельно
// (unitAt -> маска кадра), а якорь юнита лежит у ног, где спрайт прозрачен:
// щелчок ровно в (x, y) не попадает НИ В КОГО, и «подойти и заговорить»
// вырождалось в «идти на клетку» — приказ разговора не ставился вовсе, а
// разговор потом открывался лишь случайно, по пути. Замер на карте 64:
// unitAt в якоре жителя — null, и только с сорока точками выше — он сам.
// Ищем ближайшую точку над якорем, которую разбор щелчка отдаёт этому юниту.
function aimAt(unit) {
  for (let up = 0; up <= 96; up += 8) {
    if (unitAt(unit.x, unit.y - up, true) === unit) {
      return { x: unit.x, y: unit.y - up };
    }
  }
  return { x: unit.x, y: unit.y };
}

function pileAt(cell) {
  // Разговорная куча (pile.dialog) тоже цель: приказ «обыскать» на ней
  // открывает диалог без собеседника — чаны с маслом в Ущелье.
  return loot.find((pile) => !pile.taken && pile.cell &&
    (pile.items?.length || pile.dialog) &&
    pile.cell.row === cell.row && pile.cell.col === cell.col) ?? null;
}

// Действие агента. Возвращает {ok, reason|result} и НИКОГДА не бросает:
// модель должна получить отказ словами, а не сломать петлю исключением.
export function agentExec(action = {}) {
  try {
    const mode = agentMode();
    const kind = action.action;
    if (mode === "menu") return fail("открыто меню — игровых действий нет");
    if (mode === "dead" && kind !== "wait") return fail("герой мёртв");
    switch (kind) {
      case "goto": {
        const cell = action.cell;
        if (!cell || cell.row == null || cell.col == null) {
          return fail("goto: нужна клетка {row, col} шаговой сетки");
        }
        const at = heroAnchor(cell.row, cell.col);
        if (!at) return fail("goto: клетка вне карты");
        return orderAt(at.x, at.y, action.run !== false)
          ? done({ goal: { ...cell } }) : fail("goto: приказ не принят");
      }
      case "approach": {
        const unit = unitByName(action.name);
        if (!unit) return fail(`approach: юнита «${action.name}» нет среди живых`);
        const aim = aimAt(unit);
        return orderAt(aim.x, aim.y, action.run !== false, false,
                       Boolean(action.talk))
          ? done({ target: unit.name, talk: Boolean(action.talk) })
          : fail("approach: приказ не принят");
      }
      case "pickup": {
        const pile = action.cell ? pileAt(action.cell)
          : loot.filter((entry) => !entry.taken && entry.items?.length &&
              entry.cell && !lootHidden(entry))
            .sort((a, b) => distanceTo(a.cell) - distanceTo(b.cell))[0];
        if (!pile) return fail("pickup: кучи не видно");
        // По прибытии откроется обыск (обмен) — брать вещи действием take.
        return orderAt(pile.x, pile.y, action.run !== false)
          ? done({ cell: { ...pile.cell }, items: namesOf(pile.items) })
          : fail("pickup: приказ не принят");
      }
      case "take": {
        if (!trade.open) return fail("take: обмен не открыт");
        const goods = trade.columns?.[2] ?? [];
        const wanted = action.index != null ? [action.index]
          : goods.map((_, index) => index);
        // Индексы разбираются с конца: перенос уплотняет ряд.
        let moved = 0;
        for (const index of wanted.sort((a, b) => b - a)) {
          if (tradeMove(2, index)) moved += 1;
        }
        if (!moved) return fail("take: ничего не перенеслось");
        if (!tradeFinish(true)) {
          tradeClose();
          world.onTrade?.();
          return fail("take: не влезло (вес или мешок) — обмен закрыт");
        }
        world.onTrade?.();
        return done({ taken: moved, bag: namesOf(hero.bag) });
      }
      case "choose": {
        if (!dialog.unit) return fail("choose: разговора нет");
        const options = dialogOptions();
        const option = options[action.index ?? -1];
        if (!option) {
          return fail(`choose: нет варианта ${action.index} (всего ${options.length})`);
        }
        dialogChoose(option);
        return done({ ended: !dialog.unit });
      }
      case "close_dialog":
        if (!dialog.unit) return fail("close_dialog: разговора нет");
        dialogClose();
        return done({});
      case "close_trade":
        if (!trade.open) return fail("close_trade: обмен не открыт");
        tradeFinish(false);
        tradeClose();
        world.onTrade?.();
        return done({});
      case "wait":
        return done({});
      default:
        return fail(`неизвестное действие «${kind}»`);
    }
  } catch (error) {
    return fail(`сбой исполнителя: ${error?.message ?? error}`);
  }
}

// ---- самопроверка ----------------------------------------------------------

// Повторяемый прогон ручек агента: knyaz2.agent.selfcheck().
// Тот же уговор, что у selfcheck рендера: имя правила, числа, вердикт.
// Состояние игры прогоном НЕ ПОРТИТСЯ: приказ движения отдаётся и тут же
// перекрывается приказом в собственную клетку (новый приказ стирает маршрут).
export function agentSelfCheck() {
  const checks = [];
  const rule = (name, ok, value) =>
    checks.push({ rule: name, ok: Boolean(ok), value });

  const snap = agentSnapshot();
  rule("снапшот: обязательные поля на месте",
    ["mode", "map", "time", "hero", "units", "loot", "exits", "journal"]
      .every((key) => key in snap),
    Object.keys(snap).join(","));
  rule("снапшот: режим из известного набора",
    ["local", "worldmap", "dialog", "trade", "dead", "menu"].includes(snap.mode),
    snap.mode);
  const opaque = [...snap.hero.bag, ...Object.values(snap.hero.equipment)]
    .filter((name) => String(name).startsWith("instance:"));
  rule("вещи героя разыменованы в имена", opaque.length === 0,
    opaque.join(",") || "все имена");
  rule("журнал: хуки world.on* обёрнуты",
    TAPPED.every((slot) => world[slot]?.__agentTap),
    TAPPED.filter((slot) => !world[slot]?.__agentTap).join(",") || "все");

  const before = journal.length + dropped;
  world.onStatus?.("агент: проверка журнала");
  rule("журнал: событие хука записалось",
    journal.length + dropped === before + 1 &&
    journal[journal.length - 1]?.type === "onStatus",
    journal[journal.length - 1]?.type);

  const refuse = agentExec({ action: "нет такого" });
  rule("исполнитель: мусор отвергается без исключения",
    refuse.ok === false && typeof refuse.reason === "string", refuse.reason);

  if (snap.mode === "local" && hero.cell) {
    const target = { row: hero.cell.row + 2, col: hero.cell.col };
    const going = agentExec({ action: "goto", cell: target, run: false });
    const goalOk = going.ok && hero.goal &&
      hero.goal.row === target.row && hero.goal.col === target.col;
    rule("goto: клетка агента и цель приказа — одна сетка", goalOk,
      `цель ${hero.goal?.row}:${hero.goal?.col} ждали ${target.row}:${target.col}`);
    // вернуть как было: приказ в собственную клетку стирает маршрут
    agentExec({ action: "goto", cell: hero.cell, run: false });
  } else {
    rule("goto: клетка агента и цель приказа — одна сетка", true,
      `пропущено: режим ${snap.mode}`);
  }

  const score = `${checks.filter((entry) => entry.ok).length}/${checks.length}`;
  return { score, checks };
}

// ---- сборка ----------------------------------------------------------------

//: Дифф-тикер намеренно на своих часах, а не в кадре: он обязан замечать
//: смерть и смену карты даже при задушенном rAF фоновой вкладки.
export function agentSetup(knyaz2, { currentMap } = {}) {
  if (typeof currentMap === "function") currentMapOf = currentMap;
  tapAll();
  diffTick();
  setInterval(diffTick, 700);
  knyaz2.agent = {
    snapshot: agentSnapshot,
    exec: agentExec,
    mode: agentMode,
    journal,
    note,
    selfcheck: agentSelfCheck,
  };
  return knyaz2.agent;
}
