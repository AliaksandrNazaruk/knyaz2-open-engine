// РЕДАКТОР ПОВЕРХ ЖИВОГО ЯДРА — первый камень нового редактора.
//
// Замысел: не отдельная программа со своим рендером (как авторский
// edit.exe — он остаётся для ландшафта .KN2), а РЕЖИМ нашего клиента:
// мир уже отрисован ядром, редактор лишь выбирает сущности и правит их
// данные. Правки летят POST-ом на дев-сервер (/editor/unit), ложатся в
// project/maps/<карта>/map.json ключом `editor_units`, и следующая
// сборка пака доносит их всем (builder._editor_unit_apply, белый список
// полей там же).
//
// Включение: адрес с ?editor=1 либо knyaz2.editorToggle() из консоли.
// Клик по юниту — выбрать; правка в панели меняет юнита СРАЗУ (живой
// предпросмотр ядром); F2 или кнопка «Сохранить» — записать в проект,
// как в старом редакторе.
import { world } from "./world.js";
import { water } from "./water.js";
import { groundInvalidate } from "./ground.js";
import { loadImage } from "./content.js";
import { hero, heroAnchor, heroCellAt } from "./hero.js";
import { unitAt, unitSpawn } from "./units.js";
import { loot, lootNear } from "./loot.js";
import { furnitureAt } from "./furniture.js";
import { screenToWorld } from "./viewport.js";

const editor = {
  on: false,
  kind: null,          // "unit" | "pile" | "prop" | "cell"
  unit: null,          // выбранная сущность (юнит или куча)
  dirty: {},           // накопленный патч выбранного
  node: null,          // корень панели
  // РЕЖИМ ТАЙЛОВ (фаза 7): пока он включён, клики красят землю.
  tiles: {
    on: false,
    page: 0,
    pages: 1,
    brush: null,       // индекс тайла-кисти (null — ластик)
    layer: "lower",    // "lower" | "upper" | "light"
  },
};

//: Имя класса вещи — из каталога карты; ссылка может быть и
//: instance:N:…, и class:N — класс в обеих стоит вторым полем.
function itemLabel(ref) {
  const cls = String(ref ?? "").split(":")[1];
  const entry = world.map?.items?.[`class:${cls}`];
  return `${entry?.name ?? "?"} (${cls})`;
}

//: Порядок характеристик — как в панели персонажа; ключи пака русские.
const TRAIT_NAMES = ["Харизма", "Ловкость", "Интеллект",
                     "Обучаемость", "Сила", "Выносливость"];

function markDirty(key, value) {
  editor.dirty[key] = value;
  editor.node?.querySelector(".editor-save")
      ?.classList.add("editor-save--dirty");
}

//: Поля панели: подпись -> как читать и как писать юнита. Ключи патча —
//: ровно те, что пропускает белый список сборки.
function fieldsOf(unit) {
  const rows = [
    { label: "имя", type: "text",
      read: () => unit.name ?? "",
      write: (v) => { unit.name = v; markDirty("name", v); } },
    { label: "уровень", type: "number",
      read: () => unit.level ?? 1,
      write: (v) => { unit.level = v | 0; markDirty("level", v | 0); } },
    { label: "деньги", type: "number",
      read: () => unit.money ?? 0,
      write: (v) => { unit.money = v | 0; markDirty("money", v | 0); } },
    { label: "здоровье", type: "number",
      read: () => unit.stats?.health ?? 0,
      write: (v) => {
        (unit.stats ??= {}).health = v | 0;
        markDirty("stats", { ...(editor.dirty.stats ?? {}),
                             health: v | 0 });
      } },
    { label: "броня", type: "number",
      read: () => unit.stats?.armour ?? 0,
      write: (v) => {
        (unit.stats ??= {}).armour = v | 0;
        markDirty("stats", { ...(editor.dirty.stats ?? {}),
                             armour: v | 0 });
      } },
    { label: "палитра", type: "number",
      read: () => unit.palette ?? 0,
      write: (v) => { unit.palette = v | 0; markDirty("palette", v | 0); } },
    { label: "диалог №", type: "number",
      read: () => unit.dialog_number ?? 0xFF,
      write: (v) => {
        unit.dialog_number = v | 0;
        markDirty("dialog_number", v | 0);
        const note = editor.node?.querySelector(".editor-note");
        if (note) note.textContent = "дерево разговора приедет пересборкой";
      } },
  ];
  for (const name of TRAIT_NAMES) {
    rows.push({ label: name.toLowerCase(), type: "number",
      read: () => unit.characteristics?.[name] ?? 0,
      write: (v) => {
        (unit.characteristics ??= {})[name] = v | 0;
        (unit.current ??= {})[name] = v | 0;
        markDirty("characteristics",
                  { ...(editor.dirty.characteristics ?? {}),
                    [name]: v | 0 });
        markDirty("current",
                  { ...(editor.dirty.current ?? {}), [name]: v | 0 });
      } });
  }
  return rows;
}

// ── панель ───────────────────────────────────────────────────────────────

function panel() {
  if (editor.node) return editor.node;
  const node = document.createElement("div");
  node.className = "editor-panel";
  node.style.cssText =
    "position:absolute;top:8px;right:8px;z-index:40;min-width:220px;" +
    "background:#1b1712f2;color:#e8dcc0;border:1px solid #6b5a3e;" +
    "font:13px/1.5 monospace;padding:8px;border-radius:4px";
  node.innerHTML =
    '<div class="editor-head" style="margin-bottom:6px">' +
    "<b>Редактор</b> — щёлкните по юниту</div>" +
    '<div class="editor-tools" style="display:flex;flex-wrap:wrap;' +
    'gap:4px;margin-bottom:6px"></div>' +
    '<div class="editor-body"></div>' +
    '<button type="button" class="editor-save" style="margin-top:6px;' +
    'width:100%">Сохранить (F2)</button>' +
    '<div class="editor-note" style="opacity:.7;margin-top:4px"></div>';
  node.querySelector(".editor-save")
      .addEventListener("click", () => editorSave());
  // ТУЛБАР: раньше кисти и добавление жили только в консоли — и их
  // никто не находил. Кнопки зовут те же ручки, что и knyaz2.*.
  const tools = node.querySelector(".editor-tools");
  for (const [label, run] of [
    ["юнит+", () => bestiaryPanel()],
    ["объект+", () => objectsPanel()],
    ["куча+", () => editorNewPile()],
    // кисти — тумблеры: повторное нажатие ВЫКЛЮЧАЕТ режим, иначе из
    // него не выйти без консоли (первый живой прогон 25.08)
    ["тайлы", () => editorTilesToggle()],
    ["вода", () => editorWaterToggle()],
  ]) {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = label;
    b.addEventListener("click", run);
    tools.appendChild(b);
  }
  document.body.appendChild(node);
  editor.node = node;
  return node;
}

//: Снять с живого юнита запись для editor_units_add: подмножество
//: полей пака — клон несёт данные, а не «прожитое» (приказы, позы).
function unitRecordOf(unit, id, cell) {
  return {
    id, name: unit.name, breed: unit.breed, body: unit.body,
    palette: unit.palette ?? 0, face: unit.face ?? 0,
    level: unit.level ?? 1, money: unit.money ?? 0,
    side: unit.side ?? 0, party: unit.party ?? unit.side ?? 0,
    direction: unit.direction ?? 6,
    cell: { ...cell }, home: { ...cell },
    characteristics: { ...(unit.characteristics ?? {}) },
    current: { ...(unit.current ?? unit.characteristics ?? {}) },
    stats: { ...(unit.stats ?? {}) },
    skills: { ...(unit.skills ?? {}) },
    equipment: { ...(unit.equipment ?? {}) },
    bag: [...(unit.bag ?? [])],
    venom: unit.venom ?? 0, speed: unit.speed ?? 0,
    dialog_number: 0xFF, pinned: false, workplaces: [],
  };
}

//: Клон выбранного юнита в клетку героя: живой предпросмотр через
//: unitSpawn, в проект — запись целиком (unit_new_* -> editor_units_add).
export function editorCloneUnit() {
  if (editor.kind !== "unit" || !editor.unit || !hero.cell) return null;
  const id = `unit_new_${Date.now()}`;
  const record = unitRecordOf(editor.unit, id, hero.cell);
  const clone = unitSpawn(record);
  select(clone ?? record);
  editor.dirty = { ...record };
  markDirtyKeep();
  return record;
}

function select(unit) {
  editor.kind = "unit";
  editor.unit = unit;
  editor.dirty = {};
  const node = panel();
  node.querySelector(".editor-head").innerHTML =
    `<b>${unit.id ?? "юнит"}</b> на карте ` +
    `${world.map?.legacy?.map_number ?? "?"}`;
  const body = node.querySelector(".editor-body");
  body.replaceChildren();
  const hint = document.createElement("div");
  hint.style.cssText = "opacity:.6;margin-bottom:4px";
  hint.textContent = "Ctrl+клик по земле — перенести";
  body.appendChild(hint);
  for (const field of fieldsOf(unit)) {
    const row = document.createElement("label");
    row.style.cssText = "display:flex;justify-content:space-between;" +
                        "gap:6px;margin:1px 0";
    const input = document.createElement("input");
    input.type = field.type;
    input.value = field.read();
    input.style.cssText = "width:110px;background:#0e0c09;color:inherit;" +
                          "border:1px solid #6b5a3e";
    input.addEventListener("change", () => {
      field.write(input.type === "number" ? Number(input.value)
                                          : input.value);
    });
    row.append(field.label, input);
    body.appendChild(row);
  }
  const drop = document.createElement("button");
  drop.type = "button";
  drop.textContent = "убрать юнита с карты";
  drop.style.cssText = "margin-top:4px;width:100%";
  drop.addEventListener("click", () => {
    unit.hidden = true;                 // живой предпросмотр: ядро таких
    unit.alive = false;                 // не тикает и не рисует
    markDirty("removed", true);
  });
  body.appendChild(drop);
  node.querySelector(".editor-save").classList
      .remove("editor-save--dirty");
  node.querySelector(".editor-note").textContent = "";
}

// ── кучи ─────────────────────────────────────────────────────────────────

//: Перерисовка панели гасит подсветку — вернуть, если патч не пуст.
function markDirtyKeep() {
  if (Object.keys(editor.dirty).length) {
    editor.node?.querySelector(".editor-save")
        ?.classList.add("editor-save--dirty");
  }
}

function pileDirtyItems(pile) {
  // items и details параллельны — патч всегда несёт оба целиком
  editor.dirty.items = [...(pile.items ?? [])];
  editor.dirty.details = (pile.details ?? []).map((d) => ({ ...(d ?? {}) }));
  markDirtyKeep();
}

function pileRow(label, control) {
  const row = document.createElement("label");
  row.style.cssText = "display:flex;justify-content:space-between;" +
                      "gap:6px;margin:1px 0";
  row.append(label, control);
  return row;
}

function selectPile(pile) {
  const keepDirty = editor.unit === pile ? editor.dirty : {};
  editor.kind = "pile";
  editor.unit = pile;
  editor.dirty = keepDirty;
  const node = panel();
  node.querySelector(".editor-head").innerHTML =
    `<b>${pile.id ?? "куча"}</b> на карте ` +
    `${world.map?.legacy?.map_number ?? "?"}`;
  const body = node.querySelector(".editor-body");
  body.replaceChildren();

  const money = document.createElement("input");
  money.type = "number";
  money.value = pile.money ?? 0;
  money.style.cssText = "width:110px;background:#0e0c09;color:inherit;" +
                        "border:1px solid #6b5a3e";
  money.addEventListener("change", () => {
    pile.money = Number(money.value) | 0;
    markDirty("money", pile.money);
  });
  body.appendChild(pileRow("деньги", money));

  const buried = document.createElement("input");
  buried.type = "checkbox";
  buried.checked = Boolean(pile.buried);
  buried.addEventListener("change", () => {
    pile.buried = buried.checked;
    markDirty("buried", pile.buried);
  });
  body.appendChild(pileRow("тайник (копать)", buried));

  for (const [at, ref] of (pile.items ?? []).entries()) {
    const drop = document.createElement("button");
    drop.type = "button";
    drop.textContent = "убрать";
    drop.addEventListener("click", () => {
      pile.items.splice(at, 1);
      (pile.details ?? []).splice(at, 1);
      if (pile.items.length) pile.item = pile.items[0];
      pileDirtyItems(pile);
      selectPile(pile);          // перечитать список в панели
    });
    body.appendChild(pileRow(itemLabel(ref), drop));
  }

  const cls = document.createElement("input");
  cls.type = "number";
  cls.placeholder = "класс";
  cls.style.cssText = "width:70px;background:#0e0c09;color:inherit;" +
                      "border:1px solid #6b5a3e";
  const add = document.createElement("button");
  add.type = "button";
  add.textContent = "добавить вещь";
  add.addEventListener("click", () => {
    const n = Number(cls.value) | 0;
    if (!n) return;
    (pile.items ??= []).push(`class:${n}`);
    (pile.details ??= []).push({});
    pile.item = pile.items[0];
    pileDirtyItems(pile);
    selectPile(pile);
  });
  const addRow = document.createElement("div");
  addRow.style.cssText = "display:flex;gap:6px;margin-top:4px";
  addRow.append(cls, add);
  body.appendChild(addRow);

  markDirtyKeep();
  node.querySelector(".editor-note").textContent = "";
}

//: Новая напольная куча в клетке героя. Id даёт клиент (pile_new_*),
//: сборка примет запись целиком через `editor_loot_add`.
export function editorNewPile() {
  if (!world.map || !hero.cell) return null;
  const pile = { id: `pile_new_${Date.now()}`, on_floor: true,
                 buried: false, money: 0, items: [], details: [],
                 cell: { row: hero.cell.row, col: hero.cell.col } };
  loot.push(pile);
  selectPile(pile);
  markDirty("cell", { ...pile.cell });
  markDirty("on_floor", true);
  pileDirtyItems(pile);
  return pile;
}

// ── реквизит ─────────────────────────────────────────────────────────────

//: Объект под точкой: рамка отрисовки из пака. Задние берём последними —
//: перебор с конца даёт верхний по порядку рисования.
function propAt(x, y) {
  const list = world.map?.props ?? [];
  for (let at = list.length - 1; at >= 0; at -= 1) {
    const box = list[at]?.bounds;
    if (!box) continue;
    if (x >= box.draw_x && x <= box.draw_x + box.width &&
        y >= box.draw_y && y <= box.draw_y + box.height) {
      return list[at];
    }
  }
  return null;
}

function selectProp(prop) {
  editor.kind = "prop";
  editor.unit = prop;
  editor.dirty = {};
  const node = panel();
  node.querySelector(".editor-head").innerHTML =
    `<b>${prop.id ?? "объект"}</b> на карте ` +
    `${world.map?.legacy?.map_number ?? "?"}`;
  const body = node.querySelector(".editor-body");
  body.replaceChildren();
  const hint = document.createElement("div");
  hint.style.cssText = "opacity:.6;margin-bottom:4px";
  hint.textContent = "Ctrl+клик — перенести объект";
  body.appendChild(hint);

  const rows = [
    { label: "палитра", read: () => prop.palette ?? 0,
      write: (v) => { prop.palette = v | 0; markDirty("palette", v | 0); } },
    { label: "состояние", read: () => prop.state ?? 0,
      write: (v) => { prop.state = v | 0; markDirty("state", v | 0); } },
  ];
  for (const field of rows) {
    const input = document.createElement("input");
    input.type = "number";
    input.value = field.read();
    input.style.cssText = "width:110px;background:#0e0c09;color:inherit;" +
                          "border:1px solid #6b5a3e";
    input.addEventListener("change", () => field.write(Number(input.value)));
    body.appendChild(pileRow(field.label, input));
  }

  const drop = document.createElement("button");
  drop.type = "button";
  drop.textContent = "убрать объект с карты";
  drop.style.cssText = "margin-top:4px;width:100%";
  drop.addEventListener("click", () => {
    const list = world.map?.props ?? [];
    const at = list.indexOf(prop);
    if (at >= 0) list.splice(at, 1);      // живой предпросмотр
    markDirty("removed", true);
  });
  body.appendChild(drop);
  markDirtyKeep();
  node.querySelector(".editor-note").textContent = "";
}

//: Перенос объекта: позиция и предвычисленная рамка сдвигаются ВМЕСТЕ —
//: иначе картинка разъезжается с точкой сортировки.
function propMoveTo(prop, x, y) {
  const dx = Math.round(x - (prop.position?.x ?? 0));
  const dy = Math.round(y - (prop.position?.y ?? 0));
  prop.position = { x: (prop.position?.x ?? 0) + dx,
                    y: (prop.position?.y ?? 0) + dy };
  if (prop.bounds) {
    prop.bounds.draw_x = (prop.bounds.draw_x ?? 0) + dx;
    prop.bounds.draw_y = (prop.bounds.draw_y ?? 0) + dy;
    prop.bounds.sort_y = (prop.bounds.sort_y ?? 0) + dy;
    markDirty("bounds", { draw_x: prop.bounds.draw_x,
                          draw_y: prop.bounds.draw_y,
                          sort_y: prop.bounds.sort_y });
  }
  markDirty("position", { ...prop.position });
}

//: Клон объекта в точку героя — запись целиком (prop_new_* ->
//: editor_props_add), кадры и рамка копируются как есть.
export function editorCloneProp() {
  if (editor.kind !== "prop" || !editor.unit) return null;
  const source = editor.unit;
  const id = `prop_new_${Date.now()}`;
  const clone = JSON.parse(JSON.stringify(source));
  clone.id = id;
  (world.map?.props ?? []).push(clone);
  // сцена рисует world.objects — без вставки туда клон ждал пересборки
  world.objects.push(clone);
  propMoveTo(clone, hero.x, hero.y);
  objectsResort();
  selectProp(clone);
  editor.dirty = { ...clone };
  markDirtyKeep();
  return clone;
}

// ── тайлы: палитра и кисть ───────────────────────────────────────────────

//: Клетка ЗЕМЛИ под мировой точкой — шаг движка 0x74 на 0x20 со сдвигом
//: нечётных рядов 0x3A (konung2/graph.py: cell_position).
const GROUND_STEP_X = 0x74, GROUND_STEP_Y = 0x20, GROUND_ODD = 0x3A;

function groundCellAt(x, y) {
  const row = Math.floor(y / GROUND_STEP_Y);
  const col = Math.floor((x - (row & 1 ? GROUND_ODD : 0)) / GROUND_STEP_X);
  if (row < 0 || col < 0 || row >= 160 || col >= 80) return null;
  return { row, col };
}

async function tilesRequest(body) {
  return fetch(body.page !== undefined ? "/editor/tiles" : "/editor/ground", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ map: world.map?.legacy?.map_number ?? 0,
                           ...body }),
  }).then((r) => r.json()).catch((err) => ({ ok: false,
                                             note: String(err) }));
}

//: ДОГРУЗКА ОБРАЗОВ ДЛЯ ПРЕДПРОСМОТРА. Кэш образов наполняется при
//: входе на карту, и картинки, которых на ней не было (чистый тайл
//: кисти, слои добавленного объекта, листы твари с чужой карты),
//: рисовались розовой заглушкой НАВСЕГДА — никто их не догружал.
async function ensureImages(paths) {
  let fresh = false;
  for (const path of paths) {
    if (!path || world.images.has(path)) continue;
    try {
      world.images.set(path, await loadImage(path));
      fresh = true;
    } catch {
      // файла нет — заглушка честнее молчаливой дыры
    }
  }
  if (fresh) groundInvalidate();
  return fresh;
}

//: Живой предпросмотр мазка: у клетки пака подменяется картинка на
//: чистый тайл кисти. Комбинация «низ+верх» честно приедет пересборкой —
//: панель об этом говорит.
async function groundPreview(row, col, url) {
  const cell = world.groundByKey?.get(`${row}:${col}`)
    ?? (world.map?.terrain?.ground ?? [])
      .find((entry) => entry.row === row && entry.col === col);
  if (cell && url) {
    cell.asset = url.replace(/^\/content\//, "");
    await ensureImages([cell.asset]);
  }
  // слой земли запечён — без сброса мазок ждал бы сдвига камеры
  groundInvalidate();
}

async function tilesPalette() {
  const node = panel();
  node.querySelector(".editor-head").innerHTML =
    "<b>Тайлы</b> — кисть по земле";
  const body = node.querySelector(".editor-body");
  body.replaceChildren();

  const bar = document.createElement("div");
  bar.style.cssText = "display:flex;gap:4px;margin-bottom:4px;flex-wrap:wrap";
  for (const [label, layer] of [["низ", "lower"], ["верх", "upper"],
                                ["свет", "light"]]) {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = label;
    if (editor.tiles.layer === layer) {
      b.style.cssText += ";outline:1px solid #e8dcc0";
    }
    b.addEventListener("click", () => {
      editor.tiles.layer = layer;
      tilesPalette();
    });
    bar.appendChild(b);
  }
  const eraser = document.createElement("button");
  eraser.type = "button";
  eraser.textContent = "ластик";
  if (editor.tiles.brush === null) {
    eraser.style.cssText += ";outline:1px solid #e8dcc0";
  }
  eraser.addEventListener("click", () => {
    editor.tiles.brush = null;
    tilesPalette();
  });
  bar.appendChild(eraser);
  body.appendChild(bar);

  const reply = await tilesRequest({ page: editor.tiles.page });
  if (!reply.ok) {
    body.append(`палитра недоступна: ${reply.note}`);
    return;
  }
  editor.tiles.pages = reply.pages ?? 1;
  const grid = document.createElement("div");
  grid.style.cssText = "display:flex;flex-wrap:wrap;gap:2px;max-width:300px";
  for (const tile of reply.tiles ?? []) {
    const img = document.createElement("img");
    img.src = tile.url;
    img.title = `тайл ${tile.index}`;
    img.style.cssText = "width:56px;height:16px;object-fit:cover;" +
      "cursor:pointer;border:1px solid " +
      (editor.tiles.brush === tile.index ? "#e8dcc0" : "#3a3226");
    img.addEventListener("click", () => {
      editor.tiles.brush = tile.index;
      editor.tiles.brushUrl = tile.url;
      tilesPalette();
    });
    grid.appendChild(img);
  }
  body.appendChild(grid);

  const nav = document.createElement("div");
  nav.style.cssText = "display:flex;justify-content:space-between;" +
                      "margin-top:4px";
  const prev = document.createElement("button");
  prev.type = "button";
  prev.textContent = "PgUp";
  prev.addEventListener("click", () => {
    editor.tiles.page = Math.max(0, editor.tiles.page - 1);
    tilesPalette();
  });
  const label = document.createElement("span");
  label.textContent = `стр. ${editor.tiles.page + 1}/${editor.tiles.pages}`;
  const next = document.createElement("button");
  next.type = "button";
  next.textContent = "PgDn";
  next.addEventListener("click", () => {
    editor.tiles.page = Math.min(editor.tiles.pages - 1,
                                 editor.tiles.page + 1);
    tilesPalette();
  });
  nav.append(prev, label, next);
  body.appendChild(nav);
  const hint = document.createElement("div");
  hint.style.cssText = "opacity:.6;margin-top:4px";
  hint.textContent = "ЛКМ красит выбранным слоем, ПКМ стирает; " +
    "комбинации низ+верх приедут пересборкой";
  body.appendChild(hint);
}

export function editorTilesToggle(on = !editor.tiles.on) {
  editor.tiles.on = Boolean(on);
  if (editor.tiles.on) {
    editor.water = false;   // режимы кисти взаимоисключающие
    tilesPalette();
  }
  return editor.tiles.on;
}

async function tilesPaint(point, erase) {
  const cell = groundCellAt(point.x, point.y);
  if (!cell) return false;
  const value = erase ? null : editor.tiles.brush;
  if (!erase && value === null && editor.tiles.layer !== "light") {
    // кисть-ластик выбрана явно — стираем и левой кнопкой
  }
  const reply = await tilesRequest({ row: cell.row, col: cell.col,
                                     patch: { [editor.tiles.layer]:
                                              erase ? null : value } });
  const note = editor.node?.querySelector(".editor-note");
  if (note) {
    note.textContent = reply.ok
      ? `клетка ${cell.row}:${cell.col} — низ ${reply.lower ?? "—"}, ` +
        `верх ${reply.upper ?? "—"}, свет ${reply.light ?? "—"}`
      : `не записалось: ${reply.note}`;
  }
  if (reply.ok && editor.tiles.layer === "lower") {
    groundPreview(cell.row, cell.col,
                  erase ? null : editor.tiles.brushUrl);
  }
  return reply.ok;
}

// ── вода-подложка ────────────────────────────────────────────────────────

//: Клетка воды = 256x256 px (world.underlay так и раскладывает).
const WATER_CELL = 256;

async function waterRequest(patch) {
  return fetch("/editor/water", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ map: world.map?.legacy?.map_number ?? 0,
                           patch: patch ?? {} }),
  }).then((r) => r.json()).catch((err) => ({ ok: false,
                                             note: String(err) }));
}

//: Живой предпросмотр: клетка появляется/уходит из world.underlay сразу.
function waterPreview(row, col, value) {
  const list = world.underlay ?? [];
  const at = list.findIndex((c) => c.row === row && c.col === col);
  if (value) {
    const cell = { row, col, value, size: WATER_CELL,
                   x: col * WATER_CELL, y: row * WATER_CELL };
    if (at >= 0) list[at] = cell;
    else list.push(cell);
  } else if (at >= 0) {
    list.splice(at, 1);
  }
}

async function waterPanel() {
  const state = await waterRequest(null);
  const node = panel();
  node.querySelector(".editor-head").innerHTML = "<b>Вода</b> — подложка";
  const body = node.querySelector(".editor-body");
  body.replaceChildren();
  if (!state.ok) {
    body.append(`вода недоступна: ${state.note}`);
    return;
  }
  const info = document.createElement("div");
  info.style.cssText = "opacity:.8;margin-bottom:4px";
  info.textContent = `залито ${state.count} из ${state.limit}`;
  body.appendChild(info);

  const stream = document.createElement("input");
  stream.type = "checkbox";
  stream.checked = Boolean(state.stream);
  stream.addEventListener("change", async () => {
    const reply = await waterRequest({ stream: stream.checked });
    if (reply.ok) water.horizontalScroll = stream.checked;
  });
  body.appendChild(pileRow("Stream (течёт)", stream));

  const tile = document.createElement("input");
  tile.type = "number";
  tile.value = state.tile;
  tile.style.cssText = "width:110px;background:#0e0c09;color:inherit;" +
                       "border:1px solid #6b5a3e";
  tile.addEventListener("change", () =>
    waterRequest({ tile: Number(tile.value) | 0 }));
  body.appendChild(pileRow("тайл подложки", tile));

  const hint = document.createElement("div");
  hint.style.cssText = "opacity:.6;margin-top:4px";
  hint.textContent = "ЛКМ заливает клетку 256px, ПКМ осушает; " +
                     "новый тайл подложки приедет пересборкой";
  body.appendChild(hint);
}

export function editorWaterToggle(on = !(editor.water ?? false)) {
  editor.water = Boolean(on);
  if (editor.water) {
    editor.tiles.on = false;
    waterPanel();
  }
  return editor.water;
}

async function waterPaint(point, erase) {
  const row = Math.floor(point.y / WATER_CELL);
  const col = Math.floor(point.x / WATER_CELL);
  const reply = await waterRequest({ row, col,
                                     value: erase ? 0 : 1 });
  const note = editor.node?.querySelector(".editor-note");
  if (note) {
    note.textContent = reply.ok
      ? `вода ${row}:${col} = ${erase ? "суша" : "залито"}; ` +
        `всего ${reply.count} из ${reply.limit}`
      : `не записалось: ${reply.note}`;
  }
  if (reply.ok) waterPreview(row, col, erase ? 0 : 1);
  return reply.ok;
}

// ── каталог объектов пака ────────────────────────────────────────────────

const objectsView = { page: 0, pages: 1 };

async function layerRequest(layer, body) {
  return fetch(`/editor/${layer}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ map: world.map?.legacy?.map_number ?? 0,
                           ...body }),
  }).then((r) => r.json()).catch((err) => ({ ok: false,
                                             note: String(err) }));
}

//: Живой пропс из записи каталога: кадры и рамка уже испечены паком,
//: поэтому добавленный объект виден сразу — сборка потом испечёт то же
//: самое из записи T_OBJECTS.
function objectPreviewProp(item, recordSlot, x, y) {
  const frames = {};
  for (const [part, layer] of Object.entries(item.layers ?? {})) {
    frames[part] = { asset: layer.path, width: layer.width,
                     height: layer.height, offset_x: layer.offset_x,
                     offset_y: layer.offset_y };
  }
  return {
    id: `legacy:${world.map?.legacy?.map_number}:prop:${recordSlot}`,
    kind: "prop", record_slot: recordSlot,
    resource_slot: item.slot, palette: item.palette, state: item.state,
    position: { x, y },
    bounds: { width: item.width, height: item.height,
              offset_x: item.offset_x, offset_y: item.offset_y,
              draw_x: x + item.offset_x, draw_y: y + item.offset_y,
              sort_height: item.height, sort_bias: 0, sort_y: y },
    frames,
    lighting: { main_static_palette: false },
    render_debug: { resolved: true },
  };
}

//: Пересортировать сцену после вставки — как это делает dialog.js при
//: скриптовой подмене объектов.
function objectsResort() {
  world.objects.sort((a, b) => a.bounds.sort_y - b.bounds.sort_y ||
    a.bounds.draw_x - b.bounds.draw_x ||
    a.record_slot - b.record_slot);
  world.objects.forEach((object, index) => { object.draw_order = index; });
}

async function objectPlace(item) {
  const x = Math.round(hero.x), y = Math.round(hero.y);
  const reply = await layerRequest("object", {
    patch: { slot: item.slot, palette: item.palette,
             state: item.state, x, y } });
  const note = editor.node?.querySelector(".editor-note");
  if (note) {
    note.textContent = reply.ok
      ? `объект ${item.slot} поставлен в точку героя ` +
        `(запись ${reply.record_slot})`
      : `не поставился: ${reply.note}`;
  }
  if (!reply.ok) return null;
  const prop = objectPreviewProp(item, reply.record_slot, x, y);
  // кадры объекта могли не встречаться на этой карте — догружаем
  await ensureImages(Object.values(prop.frames).map((f) => f.asset));
  (world.map?.props ?? []).push(prop);
  world.objects.push(prop);
  objectsResort();
  selectProp(prop);
  return prop;
}

async function objectsPanel() {
  const node = panel();
  node.querySelector(".editor-head").innerHTML =
    "<b>Объекты пака</b> — щелчок ставит в точку героя";
  const body = node.querySelector(".editor-body");
  body.replaceChildren();
  const reply = await layerRequest("objects", { page: objectsView.page });
  if (!reply.ok) {
    body.append(`каталог недоступен: ${reply.note}`);
    return;
  }
  objectsView.pages = reply.pages ?? 1;
  const grid = document.createElement("div");
  grid.style.cssText = "display:flex;flex-wrap:wrap;gap:4px;" +
                       "max-width:300px;max-height:320px;overflow:auto";
  for (const item of reply.items ?? []) {
    const img = document.createElement("img");
    img.src = item.url;
    img.title = `гнездо ${item.slot}, палитра ${item.palette}, ` +
                `состояние ${item.state}`;
    img.style.cssText = "max-width:88px;max-height:88px;cursor:pointer;" +
                        "border:1px solid #3a3226;object-fit:contain";
    img.addEventListener("click", () => objectPlace(item));
    grid.appendChild(img);
  }
  body.appendChild(grid);
  const nav = document.createElement("div");
  nav.style.cssText = "display:flex;justify-content:space-between;" +
                      "margin-top:4px";
  const prev = document.createElement("button");
  prev.type = "button";
  prev.textContent = "<";
  prev.addEventListener("click", () => {
    objectsView.page = Math.max(0, objectsView.page - 1);
    objectsPanel();
  });
  const label = document.createElement("span");
  label.textContent = `стр. ${objectsView.page + 1}/${objectsView.pages}`;
  const next = document.createElement("button");
  next.type = "button";
  next.textContent = ">";
  next.addEventListener("click", () => {
    objectsView.page = Math.min(objectsView.pages - 1,
                                objectsView.page + 1);
    objectsPanel();
  });
  nav.append(prev, label, next);
  body.appendChild(nav);
}

// ── бестиарий: юнит с честными числами ───────────────────────────────────

const bestiaryView = { picked: null, palette: null, side: null };

//: Подписи отрядов карты — по флагам записи (warband.js: вражда живёт
//: в отряде, не в юните).
function warbandChoices() {
  const list = world.map?.warbands_by_world?.[
    String(world.map?.hero?.template?.world ?? 0)]
    ?? world.map?.warbands ?? [];
  return list.map((band) => ({
    side: band.side,
    label: band.player ? `${band.side}: отряд игрока`
      : (band.war_flags & 0x4F)
        ? `${band.side}: нападает (война ${band.war_flags})`
        : `${band.side}: мирный`,
  }));
}

async function bestiaryPanel() {
  const reply = await layerRequest("bestiary", {});
  const node = panel();
  node.querySelector(".editor-head").innerHTML =
    "<b>Бестиарий</b> — тварь в точку героя";
  const body = node.querySelector(".editor-body");
  body.replaceChildren();
  if (!reply.ok) {
    body.append(`бестиарий недоступен: ${reply.note}`);
    return;
  }
  const grid = document.createElement("div");
  grid.style.cssText = "display:flex;flex-wrap:wrap;gap:4px;" +
                       "max-width:300px;max-height:240px;overflow:auto";
  for (const breed of reply.breeds ?? []) {
    const card = document.createElement("div");
    card.title = breed.name;
    card.style.cssText = "width:64px;height:72px;cursor:pointer;" +
      "border:1px solid " +
      (bestiaryView.picked?.breed === breed.breed ? "#e8dcc0" : "#3a3226") +
      ";display:flex;flex-direction:column;align-items:center;" +
      "font-size:10px;overflow:hidden";
    if (breed.preview) {
      // кадр вырезается из листа фоном: сдвиг и размер листа делят
      // один масштаб, иначе вырез уезжает
      const pic = document.createElement("div");
      const zoom = Math.min(60 / breed.preview.width,
                            56 / breed.preview.height, 1);
      pic.style.cssText =
        `width:${breed.preview.width * zoom}px;` +
        `height:${breed.preview.height * zoom}px;` +
        `background-image:url(${breed.preview.url});` +
        "background-repeat:no-repeat;" +
        `background-position:${-breed.preview.x * zoom}px ` +
        `${-breed.preview.y * zoom}px;` +
        `background-size:${breed.preview.sheet_width * zoom}px ` +
        `${breed.preview.sheet_height * zoom}px`;
      card.appendChild(pic);
    }
    const cap = document.createElement("span");
    cap.textContent = breed.name;
    card.appendChild(cap);
    card.addEventListener("click", () => {
      bestiaryView.picked = breed;
      bestiaryView.palette = breed.palettes?.[0] ?? 0;
      bestiaryPanel();
    });
    grid.appendChild(card);
  }
  body.appendChild(grid);

  const picked = bestiaryView.picked;
  if (!picked) return;

  const palette = document.createElement("select");
  palette.style.cssText = "background:#0e0c09;color:inherit;" +
                          "border:1px solid #6b5a3e";
  for (const value of picked.palettes ?? []) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = `масть ${value}`;
    if (value === bestiaryView.palette) option.selected = true;
    palette.appendChild(option);
  }
  palette.addEventListener("change", () => {
    bestiaryView.palette = Number(palette.value);
  });
  body.appendChild(pileRow("масть", palette));

  const band = document.createElement("select");
  band.style.cssText = palette.style.cssText;
  for (const choice of warbandChoices()) {
    const option = document.createElement("option");
    option.value = choice.side;
    option.textContent = choice.label;
    if (choice.side === bestiaryView.side) option.selected = true;
    band.appendChild(option);
  }
  const fresh = document.createElement("option");
  fresh.value = "new";
  fresh.textContent = "новый вражий отряд (зона вокруг героя)";
  band.appendChild(fresh);
  band.addEventListener("change", () => {
    bestiaryView.side = band.value === "new" ? "new" : Number(band.value);
  });
  body.appendChild(pileRow("отряд", band));

  const put = document.createElement("button");
  put.type = "button";
  put.textContent = `поставить: ${picked.name}`;
  put.style.cssText = "margin-top:4px;width:100%";
  put.addEventListener("click", () => bestiaryPlace());
  body.appendChild(put);
}

async function bestiaryPlace() {
  const picked = bestiaryView.picked;
  if (!picked) return null;
  const cell = heroCellAt(hero.x, hero.y);
  if (!cell) return null;
  let side = bestiaryView.side;
  if (side === "new" || side === null) {
    const made = await layerRequest("warband", {
      patch: { row: cell.row, col: cell.col } });
    if (!made.ok) {
      const note = editor.node?.querySelector(".editor-note");
      if (note) note.textContent = `отряд не встал: ${made.note}`;
      return null;
    }
    side = made.warband.side;
    (world.map?.warbands ?? []).push(made.warband);
    const worlds = world.map?.warbands_by_world ?? {};
    for (const key of Object.keys(worlds)) worlds[key].push(made.warband);
    bestiaryView.side = side;
  }
  const id = `unit_new_${Date.now()}`;
  const spot = heroAnchor(cell.row, cell.col);
  const sample = picked.sample ?? {};
  const record = {
    id, name: picked.name, breed: picked.breed, body: picked.body,
    palette: bestiaryView.palette ?? picked.palettes?.[0] ?? 0,
    face: sample.face ?? 0, level: sample.level ?? 1,
    money: sample.money ?? 0, side, party: side,
    direction: 6, speed: sample.speed ?? 0, venom: sample.venom ?? 0,
    stats: { ...(sample.stats ?? { health: 400 }) },
    characteristics: { ...(sample.characteristics ?? {}) },
    skills: { ...(sample.skills ?? {}) },
    cell: { row: cell.row, col: cell.col },
    home: { row: cell.row, col: cell.col },
  };
  const reply = await fetch("/editor/unit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ map: world.map?.legacy?.map_number ?? 0,
                           id, patch: record }),
  }).then((r) => r.json()).catch((err) => ({ ok: false,
                                             note: String(err) }));
  const note = editor.node?.querySelector(".editor-note");
  if (note) {
    note.textContent = reply.ok
      ? `${picked.name} записан в отряд ${side}; числа сняты с ` +
        "живого образца, правятся панелью юнита"
      : `не записался: ${reply.note}`;
  }
  if (!reply.ok) return null;
  // листы твари могли не грузиться (на карте таких не было) — соберём
  // пути кадров выбранной масти и догрузим
  const sets = world.map?.creatures?.sets?.[String(picked.body)];
  const sheets = world.map?.creatures?.sheets ?? [];
  const used = new Set();
  for (const pose of Object.values(sets?.[String(record.palette)] ?? {})) {
    for (const direction of pose ?? []) {
      for (const frame of direction ?? []) {
        used.add(sheets[frame.sheet]?.path);
        if (frame.shadow) used.add(sheets[frame.shadow.sheet]?.path);
      }
    }
  }
  await ensureImages([...used]);
  // живой юнит в мир — как editorCloneUnit: пак пересоберёт то же
  const unit = { ...record, x: spot.x, y: spot.y, path: [],
                 alive: true, pose: 0, direction: 6 };
  (world.units ?? []).push(unit);
  select(unit);
  return unit;
}

//: Консольная ручка панели бестиария — родня editorTilesToggle.
export function editorBestiary() {
  return bestiaryPanel();
}

// ── оверлеи ландшафта (режим SPRITE) ─────────────────────────────────────

//: Оверлей под мировой точкой — рамка кадра, перебор с конца: рисуются
//: они в порядке слотов, верхний по порядку и ловится первым.
function overlayAt(x, y) {
  const list = world.terrainOverlays ?? [];
  for (let at = list.length - 1; at >= 0; at -= 1) {
    const frame = list[at]?.frame;
    if (!frame) continue;
    const px = list[at].position.x, py = list[at].position.y;
    if (x >= px && x <= px + frame.width &&
        y >= py && y <= py + frame.height) {
      return list[at];
    }
  }
  return null;
}

async function spriteRequest(patch) {
  return fetch("/editor/sprite", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ map: world.map?.legacy?.map_number ?? 0,
                           patch: patch ?? {} }),
  }).then((r) => r.json()).catch((err) => ({ ok: false,
                                             note: String(err) }));
}

function selectOverlay(overlay) {
  editor.kind = "sprite";
  editor.unit = overlay;
  editor.dirty = {};
  const node = panel();
  node.querySelector(".editor-head").innerHTML =
    `<b>оверлей ${overlay.record_slot}</b> на карте ` +
    `${world.map?.legacy?.map_number ?? "?"}`;
  const body = node.querySelector(".editor-body");
  body.replaceChildren();
  const hint = document.createElement("div");
  hint.style.cssText = "opacity:.6;margin-bottom:4px";
  hint.textContent = "Ctrl+клик — перенести; смена спрайта приедет " +
                     "пересборкой";
  body.appendChild(hint);

  const rows = [
    { label: "спрайт GRAPH", read: () => overlay.resource_slot ?? 0,
      write: (v) => {
        overlay.resource_slot = v | 0;
        spriteRequest({ slot: overlay.record_slot, id: v | 0 });
      } },
    { label: "x", read: () => overlay.position?.x ?? 0,
      write: (v) => overlayMoveTo(overlay, v | 0,
                                  overlay.position?.y ?? 0) },
    { label: "y", read: () => overlay.position?.y ?? 0,
      write: (v) => overlayMoveTo(overlay, overlay.position?.x ?? 0,
                                  v | 0) },
  ];
  for (const field of rows) {
    const input = document.createElement("input");
    input.type = "number";
    input.value = field.read();
    input.style.cssText = "width:110px;background:#0e0c09;color:inherit;" +
                          "border:1px solid #6b5a3e";
    input.addEventListener("change", () => field.write(Number(input.value)));
    body.appendChild(pileRow(field.label, input));
  }

  const drop = document.createElement("button");
  drop.type = "button";
  drop.textContent = "убрать оверлей с карты";
  drop.style.cssText = "margin-top:4px;width:100%";
  drop.addEventListener("click", async () => {
    const reply = await spriteRequest({ slot: overlay.record_slot,
                                        removed: true });
    if (!reply.ok) return;
    const list = world.terrainOverlays ?? [];
    const at = list.indexOf(overlay);
    if (at >= 0) list.splice(at, 1);      // живой предпросмотр
    groundInvalidate();
  });
  body.appendChild(drop);
}

//: Перенос: позиция в мире и запись в проекте двигаются вместе, слой
//: земли перепекается следующим кадром.
async function overlayMoveTo(overlay, x, y) {
  overlay.position = { x: Math.round(x), y: Math.round(y) };
  groundInvalidate();
  const reply = await spriteRequest({ slot: overlay.record_slot,
                                      x: overlay.position.x,
                                      y: overlay.position.y });
  const note = editor.node?.querySelector(".editor-note");
  if (note) {
    note.textContent = reply.ok
      ? `оверлей ${overlay.record_slot} -> ` +
        `${overlay.position.x}:${overlay.position.y}`
      : `не записалось: ${reply.note}`;
  }
  return reply.ok;
}

//: Клон оверлея в точку героя: тот же спрайт GRAPH — кадр уже испечён,
//: предпросмотр полный; свободный слот выбирает сервер.
export async function editorCloneOverlay() {
  if (editor.kind !== "sprite" || !editor.unit) return null;
  const source = editor.unit;
  const x = Math.round(hero.x), y = Math.round(hero.y);
  const reply = await spriteRequest({ add: {
    id: source.resource_slot, x, y } });
  if (!reply.ok) return null;
  const clone = JSON.parse(JSON.stringify(source));
  clone.record_slot = reply.slot;
  clone.id = `legacy:${world.map?.legacy?.map_number}:overlay:${reply.slot}`;
  clone.position = { x, y };
  const list = world.terrainOverlays ?? [];
  list.push(clone);
  list.sort((a, b) => a.record_slot - b.record_slot);
  groundInvalidate();
  selectOverlay(clone);
  return clone;
}

// ── ландшафтная клетка ───────────────────────────────────────────────────

//: Панель клетки: правки уходят В GRID.TXT СРАЗУ (у ландшафта нет
//: dirty-буфера — каждая правка это запись), живой предпросмотр — тумблер
//: стены у ядра и набор solid.
async function cellRequest(row, col, patch) {
  const map = world.map?.legacy?.map_number;
  return fetch("/editor/cell", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ map, row, col, patch: patch ?? {} }),
  }).then((r) => r.json()).catch((err) => ({ ok: false,
                                             note: String(err) }));
}

async function selectCell(row, col) {
  const peek = await cellRequest(row, col, null);
  editor.kind = "cell";
  editor.unit = { id: `cell_${row}_${col}`, row, col };
  editor.dirty = {};
  const node = panel();
  node.querySelector(".editor-head").innerHTML =
    `<b>клетка ${row}:${col}</b> на карте ` +
    `${world.map?.legacy?.map_number ?? "?"}`;
  const body = node.querySelector(".editor-body");
  body.replaceChildren();
  if (!peek.ok) {
    body.textContent = `сетка недоступна: ${peek.note}`;
    return;
  }
  // Полная карта бит клетки — дизасм 24.08 (кисть признаков старого
  // редактора DAT_00640AEC): подписи повторяют его кнопки.
  const rows = [
    { label: "глушь (NoWay)", type: "checkbox", key: "blocked",
      value: peek.blocked },
    { label: "глушит стрелы (NoFly)", type: "checkbox", key: "solid",
      value: peek.solid },
    { label: "выход с карты", type: "checkbox", key: "exit",
      value: peek.exit },
    { label: "юнит поверх (Transparency)", type: "checkbox",
      key: "transparent", value: peek.transparent },
    { label: "интерьер (Inner)", type: "checkbox", key: "inner",
      value: peek.inner },
    { label: "дневной свет (Light)", type: "checkbox", key: "light",
      value: peek.light },
    { label: "UpOff (движок не читает)", type: "checkbox", key: "upoff",
      value: peek.upoff },
    { label: "объект № (0-30)", type: "number", key: "object",
      value: peek.object },
  ];
  for (const field of rows) {
    const input = document.createElement("input");
    input.type = field.type;
    if (field.type === "checkbox") input.checked = Boolean(field.value);
    else {
      input.value = field.value;
      input.style.cssText = "width:110px;background:#0e0c09;" +
                            "color:inherit;border:1px solid #6b5a3e";
    }
    input.addEventListener("change", async () => {
      const value = field.type === "checkbox" ? input.checked
        : Number(input.value);
      const reply = await cellRequest(row, col, { [field.key]: value });
      const note = editor.node?.querySelector(".editor-note");
      if (note) {
        note.textContent = reply.ok
          ? "записано в grid.txt; пересоберите карту"
          : `не сохранилось: ${reply.note}`;
      }
      if (!reply.ok) return;
      // живой предпросмотр: проходимость и стрелы меняются сразу
      if (field.key === "blocked") {
        world.editorCellWall?.(row, col, reply.blocked);
      }
      if (field.key === "solid") {
        const key = `${row}:${col}`;
        // набор ядра ключуется heroCellKey — он строковый row:col
        if (reply.solid) hero.solid?.add?.(key);
        else hero.solid?.delete?.(key);
      }
    });
    body.appendChild(pileRow(field.label, input));
  }
  const hint = document.createElement("div");
  hint.style.cssText = "opacity:.6;margin-top:4px";
  hint.textContent = "правки клетки пишутся сразу, F2 не нужен";
  body.appendChild(hint);
  node.querySelector(".editor-note").textContent = "";
}

// ── сохранение ───────────────────────────────────────────────────────────

export async function editorSave() {
  const unit = editor.unit;
  if (!unit || !Object.keys(editor.dirty).length) return false;
  const map = world.map?.legacy?.map_number;
  const route = editor.kind === "pile" ? "/editor/loot"
    : editor.kind === "prop" ? "/editor/prop" : "/editor/unit";
  const reply = await fetch(route, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ map, id: unit.id, unit: unit.id,
                           patch: editor.dirty }),
  }).then((r) => r.json()).catch((err) => ({ ok: false,
                                             note: String(err) }));
  const note = editor.node?.querySelector(".editor-note");
  if (note) {
    note.textContent = reply.ok
      ? "записано в проект; пересоберите пак"
      : `не сохранилось: ${reply.note}`;
  }
  if (reply.ok) {
    editor.dirty = {};
    editor.node?.querySelector(".editor-save")
        ?.classList.remove("editor-save--dirty");
  }
  return Boolean(reply.ok);
}

// ── выбор и включение ────────────────────────────────────────────────────

function onClick(event) {
  if (!editor.on || !world.map) return;
  if (!(event.target instanceof HTMLCanvasElement)) return;
  // Перевод щелчка в мир — Тем же путём, что и игровой ввод: своя
  // математика здесь уже расходилась с камерой и зумом.
  const point = screenToWorld(event.clientX, event.clientY);
  // РЕЖИМ ВОДЫ: клики заливают клетки подложки.
  if (editor.water) {
    waterPaint(point, false);
    event.stopPropagation();
    event.preventDefault();
    return;
  }
  // РЕЖИМ ТАЙЛОВ: клики красят землю и никого не выбирают.
  if (editor.tiles.on) {
    tilesPaint(point, false);
    event.stopPropagation();
    event.preventDefault();
    return;
  }
  // Alt+клик — ландшафтная клетка (фаза 5): земля правится отдельно от
  // сущностей, иначе клетку под юнитом было бы не выбрать.
  if (event.altKey) {
    const cell = heroCellAt(point.x, point.y);
    if (cell) {
      selectCell(cell.row, cell.col);
      event.stopPropagation();
      event.preventDefault();
      return;
    }
  }
  // Ctrl+клик при выбранном оверлее — перенос в точку.
  if (event.ctrlKey && editor.kind === "sprite" && editor.unit) {
    overlayMoveTo(editor.unit, point.x, point.y);
    event.stopPropagation();
    event.preventDefault();
    return;
  }
  // Ctrl+клик при выбранном объекте — перенос в точку.
  if (event.ctrlKey && editor.kind === "prop" && editor.unit) {
    propMoveTo(editor.unit, point.x, point.y);
    event.stopPropagation();
    event.preventDefault();
    return;
  }
  // Ctrl+клик при выбранном юните — ПЕРЕНОС в клетку (расстановка).
  if (event.ctrlKey && editor.kind === "unit" && editor.unit) {
    const cell = heroCellAt(point.x, point.y);
    if (cell) {
      const unit = editor.unit;
      unit.cell = { row: cell.row, col: cell.col };
      unit.home = { row: cell.row, col: cell.col };
      const spot = heroAnchor(cell.row, cell.col);
      unit.x = spot.x;
      unit.y = spot.y;
      unit.path = [];
      markDirty("cell", { ...unit.cell });
      markDirty("home", { ...unit.home });
      event.stopPropagation();
      event.preventDefault();
      return;
    }
  }
  const unit = unitAt(point.x, point.y, true);
  if (unit) {
    select(unit);
    event.stopPropagation();
    event.preventDefault();
    return;
  }
  // Мимо юнитов — пробуем кучу: редактору видны и тайники.
  const pile = lootNear(point.x, point.y, { hidden: true });
  if (pile) {
    selectPile(pile);
    event.stopPropagation();
    event.preventDefault();
    return;
  }
  // Мебель: сундук открывает свою кучу — состав правится фазой 2.
  const nest = furnitureAt(point.x, point.y);
  if (nest?.pile) {
    selectPile(nest.pile);
    event.stopPropagation();
    event.preventDefault();
    return;
  }
  // Последним — реквизит: он крупный и накрыл бы всех выше.
  const prop = propAt(point.x, point.y);
  if (prop) {
    selectProp(prop);
    event.stopPropagation();
    event.preventDefault();
    return;
  }
  // Совсем последним — оверлей ландшафта: он лежит под всеми.
  const overlay = overlayAt(point.x, point.y);
  if (overlay) {
    selectOverlay(overlay);
    event.stopPropagation();
    event.preventDefault();
  }
}

function onKey(event) {
  if (!editor.on) return;
  if (event.key === "F2") { editorSave(); event.preventDefault(); }
  if (editor.tiles.on && event.key === "PageUp") {
    editor.tiles.page = Math.max(0, editor.tiles.page - 1);
    tilesPalette();
    event.preventDefault();
  }
  if (editor.tiles.on && event.key === "PageDown") {
    editor.tiles.page = Math.min(editor.tiles.pages - 1,
                                 editor.tiles.page + 1);
    tilesPalette();
    event.preventDefault();
  }
}

//: ПКМ в режимах кисти — ластик, как в старом редакторе.
function onContext(event) {
  if (!editor.on) return;
  if (!editor.tiles.on && !editor.water) return;
  const point = screenToWorld(event.clientX, event.clientY);
  if (editor.water) waterPaint(point, true);
  else tilesPaint(point, true);
  event.stopPropagation();
  event.preventDefault();
}

export function editorToggle(on = !editor.on) {
  editor.on = Boolean(on);
  if (editor.on) {
    panel();
    document.addEventListener("click", onClick, true);
    document.addEventListener("keydown", onKey, true);
    document.addEventListener("contextmenu", onContext, true);
  } else {
    document.removeEventListener("click", onClick, true);
    document.removeEventListener("keydown", onKey, true);
    document.removeEventListener("contextmenu", onContext, true);
    editor.node?.remove();
    editor.node = null;
    editor.unit = null;
    editor.dirty = {};
  }
  return editor.on;
}

//: Пересобрать QUESTS.RES авторским компилятором (фаза 6): правишь
//: исходники .QST в посылке — жмёшь из консоли. Статистика в панель.
export async function editorCompileQuests() {
  const reply = await fetch("/editor/quests", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ map: 0 }),
  }).then((r) => r.json()).catch((err) => ({ ok: false,
                                             note: String(err) }));
  const note = panel().querySelector(".editor-note");
  if (note) {
    note.textContent = reply.ok ? `квесты собраны: ${reply.note}`
                                : `компиляция упала: ${reply.note}`;
  }
  return reply;
}

//: Новая карта с нуля (фаза 11): пустой проект NN_имя в project/maps —
//: сетка вся «глушь» (как чистый лист старого редактора), тайлы чёрные,
//: таблицы пустые. Играбельной карта станет после пересборки пака;
//: наполнение — фазами 1-3 и кистями тайлов/воды.
export async function editorNewMap(number, name) {
  const reply = await fetch("/editor/newmap", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ map: Number(number) | 0,
                           name: name ?? `Карта ${number}` }),
  }).then((r) => r.json()).catch((err) => ({ ok: false,
                                             note: String(err) }));
  const note = panel().querySelector(".editor-note");
  if (note) {
    note.textContent = reply.ok
      ? `создан проект ${reply.dir}; карта появится после пересборки ` +
        `пака (--map ${reply.map})`
      : `не создалось: ${reply.note}`;
  }
  return reply;
}

//: Автовключение по адресу с ?editor=1 — зовёт app.js после старта мира.
export function editorAutostart() {
  const params = new URLSearchParams(location.search);
  if (params.get("editor") === "1") editorToggle(true);
}

export { editor };
