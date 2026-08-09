// Интерфейс игры: рамка, левая панель, пояс и окно снаряжения.
//
// Всё берётся из ресурсов игры, ничего не рисуется своими средствами:
//
//     спрайт 3   1024x768  рамка: левая панель и нижняя полоса
//     спрайт 2    884x638  окно снаряжения (силуэт с гнёздами)
//     спрайт 17     70x70  ячейка пояса, 18/20 — стрелки прокрутки
//
// Раскладка левой панели — таблица движка 0x460EB4 (портрет, восемь гнёзд
// отряда, овал оружия, шесть кнопок), гнёзда окна снаряжения — 0x460FB4.
// Координаты там в экране 1024x768, поэтому всё умножается на один
// множитель: высота окна браузера, делённая на 768. Пропорции родные.
import { world } from "./world.js";
import { contentUrl } from "./content.js";
import { centreOn, hero } from "./hero.js";
import { render } from "./scene.js";
import { actorItem } from "./actor.js";
import { orderModes, setMode } from "./orders.js";
import { isSelected, select as selectUnit, selection,
         selectionLead } from "./orders.js";
import { combatStanceNode } from "./dom.js";
import { trade, tradeFinish, tradeLayout, tradeMove, tradeTotals } from "./trade.js";
import { carriedWeight, carry, carryCancel, carryDrop, carryMixing,
         carryPlaceBag, carryPlaceSlot, carryTake, carrying,
         weightLimit } from "./carry.js";
import { mixing, mixingSlot } from "./craft.js";
import { SLOT_TITLES, dropFromBag, dropFromSlot, equipFromBag,
         inventoryWeight, unequip } from "./inventory.js";
import { armourOf } from "./combat.js";
import { bonusStrike, currentCharacteristics } from "./jewels.js";
import { dialog, dialogChoose, dialogClose, dialogJournal,
         dialogOptions } from "./dialog.js";
import { markerVisible, standAt, startTravel, startTravelTo, travelling,
         worldMap, worldMapSetup } from "./worldmap.js";
import { canRaiseCharacteristic,
         canRaiseSkill, characteristicCost, levelThreshold,
         raiseCharacteristic, raiseSkill, skillCost,
         skillLimit } from "./progress.js";

const gameNode = document.querySelector("#game");
// ЧЕЙ экран персонажа мы показываем. В движке это указатель 0x849514, и
// он идёт за ПЕРВЫМ ВЫБРАННЫМ (VA 0x4292DC); нет выбранных — сам игрок.
// Поэтому у спутника свой мешок, свои гнёзда, свои характеристики и свой
// опыт, а не общие с героем.
export function panelUnit() { return selectionLead() ?? hero; }

const panelNode = document.querySelector("#ui-panel");
const panelArtNode = document.querySelector("#ui-panel-art");
const panelCellsNode = document.querySelector("#ui-panel-cells");
const viewNode = document.querySelector("#ui-view");
const beltNode = document.querySelector("#ui-belt");
const frameBottomNode = document.querySelector("#ui-frame-bottom");
const bagNode = document.querySelector("#bag-slots");
const windowNode = document.querySelector("#ui-window");
const windowSlotsNode = document.querySelector("#equip-slots");
const windowCloseNode = document.querySelector("#ui-window-close");
const journalNode = document.querySelector("#ui-journal");
const journalListNode = document.querySelector("#ui-journal-list");
const journalCloseNode = document.querySelector("#ui-journal-close");
const mapNode = document.querySelector("#ui-map");
const talkNode = document.querySelector("#ui-talk");
const tradeNode = document.querySelector("#ui-trade");
const weightNode = document.querySelector("#inventory-weight");

//: Зажат ли Shift — модификатор «добавить к выбору» (в движке 0x849608).
const keyHeld = { shift: false };
window.addEventListener("keydown", (event) => { keyHeld.shift = event.shiftKey; });
window.addEventListener("keyup", (event) => { keyHeld.shift = event.shiftKey; });

let onChange = () => {};
let scale = 1;
// Номер первой видимой ячейки мешка: в движке это 0x849714.
let beltFirst = 0;

function info() { return world.map?.interface ?? null; }

function screen() {
  return info()?.screen ?? { width: 1024, height: 768, panel_width: 140,
                             view_width: 884, view_height: 709, frame_bottom: 709 };
}

// Пояс из движка (VA 0x43096C): ряд на строке 639, двенадцать ячеек 70x70
// с шагом 69, первая с x=168, по краям стрелки прокрутки.
function belt() {
  return info()?.belt ?? { y: 639, height: 70, cell: 70, pitch: 69,
                           first_x: 168, cells: 12, left_x: 140, right_x: 1023 };
}

export function beltCells() { return belt().cells ?? 12; }

// Подсказка предмета — те же поля, что печатает игра (VA 0x4315A0): урон
// или броня, вес в килограммах, цена, дальность и требование.
function describe(name) {
  const item = actorItem(name);
  if (!item) return "";
  const parts = [item.name];
  if (item.power) parts.push(`${item.slot === "hand" || item.slot === "ranged"
    ? "урон" : "броня"} ${item.power}`);
  parts.push(`вес ${(item.weight / 1000).toFixed(2)} кг`, `цена ${item.price}`);
  if (item.range_cells > 1) parts.push(`дальность ${item.range_cells}`);
  if (item.requires && item.requirement) {
    parts.push(`требует ${item.requires} ${item.requirement}`);
  }
  return parts.join(" · ");
}

function iconNode(name) {
  const icon = actorItem(name)?.icon;
  if (!icon) return null;
  const image = document.createElement("img");
  image.src = contentUrl(icon.path);
  image.alt = name;
  return image;
}

function cell({ x, y, width, height, name = null, title = "", art = null,
                onClick = null, onDoubleClick = null, onDrop = null,
                className = "" }) {
  const node = document.createElement("div");
  node.className = `ui-cell ${className}`.trim();
  node.style.left = `${x}px`;
  node.style.top = `${y}px`;
  node.style.width = `${width}px`;
  node.style.height = `${height}px`;
  node.title = name ? describe(name) : title;
  // Подложка ячейки — спрайт игры (пустая ячейка, кнопка, овал оружия).
  if (art) {
    node.style.backgroundImage = `url("${contentUrl(art.path)}")`;
    node.style.backgroundSize = "100% 100%";
    node.style.backgroundRepeat = "no-repeat";
  }
  const icon = name && iconNode(name);
  if (icon) node.append(icon);
  if (onClick) node.addEventListener("click", () => { onClick(); refresh(); onChange(); });
  if (onDoubleClick) node.addEventListener("dblclick", () => { onDoubleClick(); });
  if (onDrop) {
    node.addEventListener("contextmenu", (event) => {
      event.preventDefault();
      onDrop();
      refresh();
      onChange();
    });
  }
  return node;
}

// Что делает кнопка — разбор нажатия из движка (VA 0x422943): код 0x0A
// меняет ближнее оружие на метательное, 0x0B достаёт и убирает оружие,
// дальше карта, «все ко мне», атака, журнал и панель персонажа. Порядок,
// названия и клавиши приезжают в паке, здесь только сами действия.
const ACTIONS = {
  // Первая кнопка: чем биться — тем, что в руке, или метательным. Движок
  // держит это байтом unit+0xEE и ставит единицу, только если метательное
  // вообще надето (VA 0x420704).
  weapon_mode: {
    active: () => hero.rangedMode === true,
    press: () => {
      if (hero.rangedMode) { hero.rangedMode = false; return; }
      if (!panelUnit().equipment?.ranged) { status("Метательного оружия нет"); return; }
      hero.rangedMode = true;
    },
  },
  // Достать оружие — это и есть боевая стойка: бит 0x04 байта unit+0x19.
  toggle_weapon: {
    active: () => hero.stance === "combat",
    press: () => {
      hero.stance = hero.stance === "combat" ? "peace" : "combat";
      if (combatStanceNode) combatStanceNode.checked = hero.stance === "combat";
    },
  },
  character: { active: () => !windowNode.hidden, press: () => toggleWindow() },
  attack: {
    press: () => {
      const target = nearestEnemy();
      if (target) world.onAttackOrder?.(target);
      else status("Некого атаковать");
    },
  },
  // «Все ко мне» — движок переводит весь отряд в режим 0x30, то есть
  // «следовать за вожаком» (VA 0x420BFC).
  call_party: {
    press: () => {
      const mates = (world.units ?? []).filter((unit) => unit.ally && unit.alive);
      if (!mates.length) { status("Отряда пока нет"); return; }
      // Бит «за вожаком» — единственное, чем спутник отличается от
      // стоящего на месте (VA 0x4111E8 смотрит только его). Кнопка его и
      // переключает: идут следом или ждут там, где стоят.
      const bit = orderModes().follow;
      const идут = mates.every((mate) => (mate.orderByte ?? 0) & bit);
      for (const mate of mates) {
        setMode(mate, bit, !идут);
        mate.path = [];
      }
      status(идут ? `Отряд ждёт на месте: ${mates.length}`
                  : `Отряд идёт за тобой: ${mates.length}`);
    },
  },
  journal: { active: () => !journalNode.hidden, press: () => toggleJournal() },
  map: { active: () => mapOpen, press: () => showWorldMap(!mapOpen) },
};

// Лицо первой кнопки по правилу движка (VA 0x4292DC).
function weaponFace() {
  const data = info();
  const faces = data?.weapon_faces ?? {};
  const families = data?.weapon_face_families ?? { blade: 166, axe: 154 };
  const ranged = actorItem(panelUnit().equipment?.ranged);
  if (hero.rangedMode && ranged) {
    const crossbow = hero.data?.rules?.attack_by_item?.crossbow_group ?? 0x15;
    return ranged.layer === crossbow ? faces.crossbow : faces.bow;
  }
  const hand = actorItem(panelUnit().equipment?.hand);
  if (!hand?.layer) return faces.empty;
  if (hand.ground_sprite === families.blade) return faces.blade;
  if (hand.ground_sprite === families.axe) return faces.axe;
  return faces.other;
}

function status(text) { world.onStatus?.(text); }

// Карта мира — спрайт 4 во весь проём окна, как её показывает движок
// (VA 0x4277F4). Поверх картинки ложатся туман по клеткам, значки
// открытых локаций и значок отряда.
let mapOpen = false;

export function showWorldMap(open = !mapOpen) {
  const picture = info()?.map;
  if (open && !picture) { status("Карты в паке нет"); return false; }
  if (open && !worldMapSetup()) { status("Сетки карты мира в паке нет"); return false; }
  // Отряд встаёт туда, где стоит: в клетку текущей локации. Её же
  // движок открывает по сюжету, когда локация становится известна.
  if (open && worldMap.row === null) standAt(world.map?.legacy?.map_number ?? 0);
  mapOpen = open;
  refresh();
  return mapOpen;
}

// Разговор: реплика собеседника и варианты ответа. Что показывать, решает
// дерево из QUESTS.RES, здесь только вывод.
function renderTalk() {
  if (!talkNode) return;
  if (!dialog.line) { talkNode.hidden = true; return; }
  talkNode.hidden = false;
  talkNode.querySelector(".ui-talk-who").textContent = dialog.unit?.name ?? "";
  talkNode.querySelector(".ui-talk-text").textContent = dialog.line.text;
  const box = talkNode.querySelector(".ui-talk-options");
  const options = dialogOptions();
  const nodes = options.map((option) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = option.text;
    button.addEventListener("click", () => { dialogChoose(option); refresh(); onChange(); });
    return button;
  });
  if (!nodes.length) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "Закончить разговор";
    button.addEventListener("click", () => { dialogClose(); refresh(); onChange(); });
    nodes.push(button);
  }
  box.replaceChildren(...nodes);
}

//: Холст поверх картинки карты: туман, значки и отряд.
let mapCanvas = null;

function mapGeometry() {
  const rules = worldMap.rules;
  const picture = info()?.map;
  if (!rules || !picture) return null;
  // Сетка задана в координатах всего экрана 1024x768, а картинка карты
  // это окно мира, начинающееся со столбца panel_width — отсюда сдвиг.
  return {
    picture,
    x0: rules.origin[0] - screen().panel_width,
    y0: rules.origin[1],
    w: rules.cell[0], h: rules.cell[1],
    rows: rules.rows, cols: rules.cols,
  };
}

//: Клетка под точкой картинки; вне сетки — null.
function mapCellAt(x, y) {
  const box = mapGeometry();
  if (!box) return null;
  const col = Math.floor((x - box.x0) / box.w);
  const row = Math.floor((y - box.y0) / box.h);
  if (row < 0 || col < 0 || row >= box.rows || col >= box.cols) return null;
  return { row, col };
}

//: Картинки значков нужны холсту загруженными — берём из общего кэша.
function mapImage(entry) {
  return entry?.path ? world.images.get(entry.path) ?? null : null;
}

function renderWorldMap() {
  const picture = info()?.map;
  if (!mapOpen || !picture) { mapNode.hidden = true; return; }
  const view = viewNode.getBoundingClientRect();
  const game = gameNode.getBoundingClientRect();
  const k = Math.min(scale, view.width / picture.width);
  mapNode.hidden = false;
  mapNode.style.left = `${view.left - game.left}px`;
  mapNode.style.top = "0px";
  mapNode.style.width = `${Math.round(picture.width * k)}px`;
  mapNode.style.height = `${Math.round(picture.height * k)}px`;
  mapNode.style.backgroundImage = `url("${contentUrl(picture.path)}")`;
  mapNode.style.backgroundSize = "100% 100%";
  const title = mapNode.querySelector(".ui-map-title");
  if (title) title.textContent = mapTitle();
  drawWorldMap(picture);
}

//: Подпись внизу — как в движке: имя локации под курсором (0x84968C),
//: а пока курсор не на значке — имя той, где стоит отряд.
let mapHover = 0;

function mapTitle() {
  const rules = worldMap.rules;
  if (!rules) return world.map?.name ?? "";
  const here = mapHover || (worldMap.row === null ? 0
    : worldMap.cells[worldMap.row][worldMap.col] & 0xFF);
  return rules.names?.[here] || world.map?.name || "";
}

function drawWorldMap(picture) {
  const box = mapGeometry();
  if (!box) return;
  if (!mapCanvas) {
    mapCanvas = document.createElement("canvas");
    mapCanvas.className = "ui-map-layer";
    mapNode.prepend(mapCanvas);
  }
  if (mapCanvas.width !== picture.width) {
    mapCanvas.width = picture.width;
    mapCanvas.height = picture.height;
  }
  const ctx = mapCanvas.getContext("2d");
  ctx.clearRect(0, 0, mapCanvas.width, mapCanvas.height);
  const { cells, rules } = worldMap;
  const { explored, seen } = rules.flags;
  // Туман. В движке клетка, где отряд был, рисуется картинкой как есть, а
  // виденная от соседа — её же копией, прогнанной через таблицы цвета со
  // смещением -20 на канал (VA 0x4277F4 -> 0x44293F/0x441DF9); в пятибитном
  // канале это примерно две трети яркости долой. Незнакомая клетка просто
  // заливается чёрным.
  for (let row = 0; row < box.rows; row += 1) {
    for (let col = 0; col < box.cols; col += 1) {
      const flags = (cells[row][col] >>> 24) & 0xFF;
      if (flags & explored) continue;
      const x = box.x0 + col * box.w;
      const y = box.y0 + row * box.h;
      ctx.fillStyle = flags & seen ? "rgba(0, 0, 0, .645)" : "#000";
      ctx.fillRect(x, y, box.w, box.h);
    }
  }
  // Значки локаций поверх тумана — свой спрайт и свой сдвиг в клетке.
  const markers = info()?.world_markers ?? {};
  for (let row = 0; row < box.rows; row += 1) {
    for (let col = 0; col < box.cols; col += 1) {
      const cell = cells[row][col];
      if (!markerVisible(cell)) continue;
      const marker = markers[String(cell & 0xFF)];
      const image = mapImage(marker);
      if (!image) continue;
      ctx.drawImage(image, box.x0 + col * box.w + marker.dx,
                    box.y0 + row * box.h + marker.dy);
    }
  }
  // Бродячие отряды — рогатый шлем по УГЛУ их клетки, и только когда
  // клетка открыта: движок рисует значок лишь при флагах 0x60
  // (VA 0x4277F4, обращение к 0x6B2D70).
  const party = mapImage(info()?.world_party);
  if (party) {
    for (const wanderer of worldMap.wandering ?? []) {
      if (!wanderer.alive) continue;
      const flags = (cells[wanderer.row]?.[wanderer.col] >>> 24) & 0xFF;
      if (!(flags & (explored | seen))) continue;
      ctx.drawImage(party, box.x0 + wanderer.col * box.w,
                    box.y0 + wanderer.row * box.h);
    }
  }
  // Свой отряд — щит с руной, и кладётся он по ПИКСЕЛЬНОМУ месту отряда
  // со сдвигом -7, а не по углу клетки (VA 0x4277F4, 0x45244D). В походе
  // это и даёт плавный ход между клетками.
  const player = mapImage(info()?.world_player);
  if (player && worldMap.x !== null) {
    // Значок кладётся по ТОЧКЕ отряда, а не по клетке: в движке своей
    // клетки у отряда нет вовсе, есть пиксельное место (0x84956C/0x849570),
    // и клетка из него только выводится. Поэтому отряд и стоит там, где
    // остановился, а не прыгает в середину клетки.
    const offset = rules.player_offset ?? -7;
    ctx.drawImage(player, worldMap.x - screen().panel_width + offset,
                  worldMap.y + offset);
  }
}

//: Точка события в координатах картинки карты.
function mapPoint(event) {
  const rect = mapNode.getBoundingClientRect();
  const picture = info()?.map;
  if (!picture || !rect.width) return null;
  return {
    x: ((event.clientX - rect.left) / rect.width) * picture.width,
    y: ((event.clientY - rect.top) / rect.height) * picture.height,
  };
}

// Локация под указателем. В движке это проверка попадания в сам спрайт
// значка (VA 0x4277F4 -> 0x441F63), здесь — попадание в его прямоугольник:
// значки не перекрываются, и разницы не видно.
function markerAt(x, y) {
  const box = mapGeometry();
  const markers = info()?.world_markers ?? {};
  if (!box || !worldMap.cells) return 0;
  for (let row = 0; row < box.rows; row += 1) {
    for (let col = 0; col < box.cols; col += 1) {
      const cell = worldMap.cells[row][col];
      if (!markerVisible(cell)) continue;
      const marker = markers[String(cell & 0xFF)];
      if (!marker?.width) continue;
      const left = box.x0 + col * box.w + marker.dx;
      const top = box.y0 + row * box.h + marker.dy;
      if (x >= left && y >= top && x < left + marker.width
          && y < top + marker.height) return cell & 0xFF;
    }
  }
  return 0;
}

function worldMapMove(event) {
  if (!mapOpen || !worldMap.cells) return;
  const point = mapPoint(event);
  const under = point ? markerAt(point.x, point.y) : 0;
  if (under !== mapHover) { mapHover = under; refresh(); }
}

// Щелчок по карте мира. Движок различает два случая (VA 0x421690): по
// значку локации — сразу входим в неё (код мыши 0x40), по чистому месту —
// ведём отряд туда (код 0x42).

//: На сколько пикселей от своего отряда должен попасть щелчок, чтобы это
//: считалось «войти», а не «идти» (VA 0x43B20E: обе проекции меньше семи).
const ENTER_RADIUS = 7;

// Войти в то, на чём стоим (VA 0x422CCC). Что именно грузить, решает не
// значок под курсором сам по себе, а клетка отряда:
//
//   значок локации на клетке  ->  её карта
//   значка нет                ->  сцена клетки, байт 2 её слова
//   и сцены нет               ->  запасная сцена 0x32 «В пути»
//
// Последняя ветка — это и есть привал посреди дороги: своей карты у клетки
// нет, и отряд оказывается на общей дорожной местности.
function enterHere() {
  const cell = worldMap.cells[worldMap.row][worldMap.col];
  const spare = worldMap.rules.scenes?.random ?? 0x32;
  let number = markerVisible(cell) ? (cell & 0xFF) : 0;
  if (!number) number = (cell >> 16) & 0xFF;
  if (!number) number = spare;
  const name = worldMap.rules.names?.[number] || `карта ${number}`;
  status(`Входим: ${name}`);
  world.onTravel?.(number);
}

function worldMapClick(event) {
  if (!mapOpen || !worldMap.cells) return;
  const point = mapPoint(event);
  if (!point) return;
  // ИЗНУТРИ ЛОКАЦИИ КАРТА ТОЛЬКО СМОТРИТСЯ. В движке обе ветки этого
  // щелчка начинаются с проверки «текущая карта равна −1»: и поход
  // (VA 0x42227F), и вход в локацию по значку (VA 0x421FB8). Пока отряд
  // стоит в локации, её номер там обычный, и щелчок не делает ничего.
  //: Строка состояния — наша: движок в этом случае молчит.
  if (!worldMap.onMap) {
    const under = markerAt(point.x, point.y);
    const name = under && (worldMap.rules.names?.[under] || `карта ${under}`);
    status(name ? `${name} — чтобы идти, выйдите из локации`
                : "Отсюда карту можно только смотреть: выйдите краем локации");
    return;
  }
  // ВОЙТИ МОЖНО ТОЛЬКО ТУДА, ГДЕ СТОИШЬ. Движок различает два щелчка по
  // РАССТОЯНИЮ ДО СВОЕГО ОТРЯДА: коды мыши считает VA 0x43B20E, и код 0x40
  // «войти» он выдаёт, лишь когда |мышь − отряд| меньше семи пикселей по
  // ОБЕИМ осям. Всё остальное — код 0x42, то есть поход.
  //
  // Поэтому щелчок по далёкому значку никуда не переносит: он просто ведёт
  // туда отряд. А чтобы войти, надо стоять на клетке и щёлкнуть по своему
  // же значку.
  const screenX = point.x + (screen().panel_width ?? 140);
  if (Math.abs(worldMap.x - screenX) < ENTER_RADIUS &&
      Math.abs(worldMap.y - point.y) < ENTER_RADIUS) {
    enterHere();
    return;
  }
  const place = mapCellAt(point.x, point.y);
  if (!place) return;
  // Прыть отряда — наибольший байт +0xDF среди своих: он и укорачивает
  // путь, и снижает шанс нарваться (VA 0x421690 и 0x4277F4).
  //
  // Идём в САМУ ТОЧКУ щелчка, а не в середину клетки: движок берёт целью
  // координаты мыши. Проходимость он заранее НЕ проверяет и «туда не
  // пройти» не говорит — отряд идёт, сколько может, и встаёт у преграды
  // (маска смотрится на каждом кадре хода, VA 0x427951).
  //
  // ТОЧКА ЩЕЛЧКА — В КООРДИНАТАХ КАРТИНКИ, а сетка и место отряда заданы в
  // координатах ЭКРАНА 1024x768 (начало сетки 167, а картинка начинается со
  // столбца panel_width). Без этого сдвига цель уезжала влево на ширину
  // панели, и отряд шёл не туда, куда показали.
  const speed = partySpeed();
  const toX = point.x + (screen().panel_width ?? 140);
  if (!startTravelTo(toX, point.y, { speed })) return;
  status("В пути");
  refresh();
  onChange();
}

// Прыть отряда — наибольший «Следопыт» среди героя и живых спутников:
// движок перебирает бойцов отряда и берёт максимум байта +0xDF
// (VA 0x421690, строки хода по глобальной карте).
function partySpeed() {
  const names = world.map?.hero?.rules?.progression?.skills?.names ?? [];
  const index = names.indexOf("Следопыт");
  const speedOf = (unit) => (index >= 0 ? unit.skills?.[index] ?? 0 : 0);
  let best = speedOf(hero);
  for (const mate of world.units ?? []) {
    if (!mate.ally || !mate.alive) continue;
    best = Math.max(best, speedOf(mate));
  }
  return best;
}

export function worldMapBusy() { return mapOpen && travelling(); }

function nearestEnemy() {
  let best = null;
  let bestDistance = Infinity;
  for (const unit of world.units ?? []) {
    if (!unit.alive) continue;
    const distance = Math.hypot(unit.x - hero.x, (unit.y - hero.y) / 0.6);
    if (distance < bestDistance) { best = unit; bestDistance = distance; }
  }
  return best;
}

// Ряд пояса занимает всю ширину окна мира: 28 (левая стрелка) + 12*69 +
// 27 (правая) = 883 при ширине окна 884. Окно браузера шире или уже, чем
// 884 в масштабе высоты, поэтому ряд считается от фактической ширины окна
// мира — так он всегда точно ложится между его кромками, как в игре.
function beltScale() {
  const view = screen().view_width || 884;
  return (viewNode?.clientWidth || view) / view;
}

function layout() {
  const data = info();
  const box = screen();
  const height = gameNode?.clientHeight || box.height;
  scale = height / box.height;
  const panelWidth = Math.round(box.panel_width * scale);
  panelNode.style.width = `${panelWidth}px`;
  const frameWidth = Math.round((data?.frame?.width ?? box.width) * scale);
  const frameHeight = Math.round((data?.frame?.height ?? box.height) * scale);
  // Нижняя полоса рамки — её же строки с 709-й до низа экрана, взятые
  // правее панели и повторённые по ширине (текстура там однородная).
  const bandTop = box.frame_bottom ?? 709;
  const band = Math.round((box.height - bandTop) * scale);
  frameBottomNode.style.height = `${band}px`;
  if (data?.frame) {
    const url = `url("${contentUrl(data.frame.path)}")`;
    panelArtNode.style.backgroundImage = url;
    panelArtNode.style.backgroundSize = `${frameWidth}px ${frameHeight}px`;
    frameBottomNode.style.backgroundImage = url;
    frameBottomNode.style.backgroundSize = `${frameWidth}px ${frameHeight}px`;
    frameBottomNode.style.backgroundPosition =
      `${-panelWidth}px ${-Math.round(bandTop * scale)}px`;
    frameBottomNode.style.backgroundRepeat = "repeat-x";
  }
  // Ряд ячеек стоит на нижней кромке окна мира — сразу над полосой рамки.
  beltNode.style.height = `${Math.round(belt().height * beltScale())}px`;
  beltNode.style.bottom = `${band}px`;
}

// Здоровье показывает сам портрет (VA 0x4305A4): верхняя часть рисуется
// обычной палитрой, нижняя — подкрашенной, и граница ходит по высоте 62 по
// шкале 1600. Отравленному вместо красного дают синевы: движок зовёт
// перекраску с (50, -30, -30) и (50, -30, 50) соответственно.
//: Перекраска раненой части портрета (VA 0x4305A4): здоровому красным,
//: отравленному — лиловым. Числа приезжают в паке, тут только запас.
const PORTRAIT_TINT = { hurt: [50, -30, -30], poisoned: [50, -30, 50] };
function portraitTint(poisoned) {
  const set = world.map?.hero?.rules?.effects?.portrait;
  return (poisoned ? set?.poisoned ?? PORTRAIT_TINT.poisoned
                   : set?.hurt ?? PORTRAIT_TINT.hurt);
}
const portraitCache = new Map();

// Портрет спутника — тот же спрайт, только по его номеру лица: движок
// берёт лицо юнита плюс 261 (VA 0x430631).
function portraitPath(data, face) {
  const own = data.portrait?.path;
  if (!own) return null;
  const base = data.portrait_base ?? 261;
  return own.replace(/ui_\d+\.png$/, `ui_${base + face}.png`);
}

// Картинку портрета держим свою: в общий склад изображений мира она не
// попадает, потому что панель показывает её фоном.
const portraitImages = new Map();

function portraitImage(source) {
  if (!source?.path) return null;
  const ready = portraitImages.get(source.path);
  if (ready !== undefined) return ready;
  portraitImages.set(source.path, null);
  const image = new Image();
  image.addEventListener("load", () => {
    portraitImages.set(source.path, image);
    refresh();
  });
  image.src = contentUrl(source.path);
  return null;
}

function portraitFace(data, actor, face = null) {
  const source = face == null ? data.portrait : { path: portraitPath(data, face) };
  if (!source.path) return null;
  const image = portraitImage(source);
  if (!image) return null;
  const scale = data.health_bar?.scale ?? 1600;
  const height = data.health_bar?.height ?? 62;
  const share = Math.max(0, Math.min(1, (actor.health ?? 0) / scale));
  const hurt = Math.round((1 - share) * height);
  const poisoned = Boolean(actor.poison);
  const key = `${source.path}|${hurt}|${poisoned}`;
  if (portraitCache.has(key)) return portraitCache.get(key);

  const canvas = document.createElement("canvas");
  canvas.width = image.width;
  canvas.height = image.height;
  const paint = canvas.getContext("2d");
  paint.drawImage(image, 0, 0);
  if (hurt > 0) {
    const top = Math.max(0, image.height - hurt);
    const box = paint.getImageData(0, top, image.width, image.height - top);
    const [dr, dg, db] = portraitTint(poisoned);
    for (let i = 0; i < box.data.length; i += 4) {
      if (!box.data[i + 3]) continue;
      box.data[i] = Math.max(0, Math.min(255, box.data[i] + dr));
      box.data[i + 1] = Math.max(0, Math.min(255, box.data[i + 1] + dg));
      box.data[i + 2] = Math.max(0, Math.min(255, box.data[i + 2] + db));
    }
    paint.putImageData(box, 0, top);
  }
  const url = canvas.toDataURL();
  portraitCache.set(key, url);
  return url;
}

function renderPanel() {
  const data = info();
  if (!data?.panel) return;
  const nodes = [];
  for (const rect of data.panel) {
    const geometry = {
      x: Math.round(rect.x * scale), y: Math.round(rect.y * scale),
      width: Math.round(rect.width * scale), height: Math.round(rect.height * scale),
    };
    if (rect.name.startsWith("button_")) {
      const index = Number(rect.name.slice("button_".length)) - 1;
      const button = data.buttons?.[index] ?? null;
      const action = button && ACTIONS[button.id];
      // Две первые кнопки меняют картинку: первая по оружию, вторая по
      // стойке. Предметы в панель не кладутся — гнёзд под них там нет.
      let art = button;
      if (button?.id === "weapon_mode") art = weaponFace() ?? button;
      if (button?.id === "toggle_weapon") {
        art = data.stance_faces?.[hero.stance === "combat" ? "combat" : "peace"] ?? button;
      }
      nodes.push(cell({
        ...geometry,
        title: button ? `${button.title}${button.key ? ` (${button.key})` : ""}` : "",
        art, className: action?.active?.() ? "active" : "",
        onClick: action?.press ?? null,
      }));
    } else if (rect.name === "portrait") {
      // Портрет игрока — такая же кнопка выбора, как у спутников: щелчок
      // по нему делает главного единственным выбранным (VA 0x421690 ведёт
      // и портрет, и щелчок по юниту в одну и ту же FUN_0041ECB8).
      const node = cell({ ...geometry, art: data.portrait,
                          className: isSelected(hero) ? "active" : "",
                          // Порядок движковый: сперва прозвище, потом уровень
                          // и здоровье — и здоровье в той же шкале, что лист
                          // персонажа, то есть 100, а не 1600.
                          title: [heroEpithet(), `уровень ${hero.level ?? 1}`,
                                  `здоровье ${healthShown(hero.health, healthDivisor())}`
                                  + ` из ${healthShown(hero.maxHealth ?? 1600, healthDivisor())}`]
                            .filter(Boolean).join(", "),
                          onClick: () => { selectUnit(hero, keyHeld.shift); refresh(); },
                          onDoubleClick: () => { centreOn(hero); render(); } });
      // Портрет героя — ПО ЕГО ЛИЦУ, а не по картинке, запечённой в пак:
      // движок берёт спрайт «лицо + 261» (VA 0x430631) для любого юнита, и
      // герой не исключение. Стартовых героев шесть, лица у них 0…5, и с
      // жёсткой картинкой Велиславна показывалась иконкой героя мира 0.
      const face = portraitFace(data, hero, hero.face ?? null);
      if (face) {
        node.style.backgroundImage = `url("${face}")`;
        node.style.backgroundSize = "100% 100%";
      }
      nodes.push(node);
    } else {
      // Места отряда: у игрока их восемь при вместимости девять (VA 0x433070
      // кладёт новичка в конец отряда, а панель показывает всех).
      const place = Number(rect.name.slice("party_".length)) - 1;
      const member = (hero.party?.members ?? []).slice(1)[place] ?? null;
      // ВАЖНО: в списке выбора должен лежать ЖИВОЙ юнит сцены, а не запись
      // из пака. Раньше сюда клали запись — она никогда не совпадала с тем,
      // что в списке, поэтому портрет не подсвечивался и не переключал.
      const mate = member
        ? (world.units ?? []).find((unit) => unit.slot === member.index) ?? null
        : null;
      const node = cell({
        ...geometry, art: data.cell,
        className: mate && isSelected(mate) ? "active" : "",
        title: member ? `${member.name}, уровень ${member.level}` : "место отряда",
        // Клик по портрету выбирает юнита, с Shift — добавляет к выбору
        // (VA 0x423F80: без модификатора список сначала очищается).
        onClick: mate ? () => { selectUnit(mate, keyHeld.shift); refresh(); } : null,
        // Двойной щелчок ведёт камеру к юниту. Это НАШЕ добавление: в
        // движке камеру наводят только на игрока, а до спутника доходят
        // краевой прокруткой.
        onDoubleClick: mate ? () => { centreOn(mate); render(); } : null,
      });
      if (member) {
        const face = portraitFace(data, { health: mate?.health ?? member.health,
                                          maxHealth: member.health },
                                  member.face);
        if (face) {
          node.style.backgroundImage = `url("${face}")`;
          node.style.backgroundSize = "100% 100%";
        }
      }
      nodes.push(node);
    }
  }
  panelCellsNode.replaceChildren(...nodes);
}

// Пояс — окно из двенадцати ячеек мешка юнита (unit+0x62, всего 42).
// Стрелки двигают это окно: влево до нуля, вправо — пока за краем окна
// лежит непустая ячейка (VA 0x4231E6, 0x423C99 и предикат 0x420890).
function beltLimit() {
  const bag = panelUnit().bag ?? [];
  return bag[beltFirst + beltCells()] ? beltFirst + 1 : beltFirst;
}

export function beltScroll(step) {
  const next = step < 0 ? Math.max(0, beltFirst - 1) : beltLimit();
  if (next === beltFirst) return false;
  beltFirst = next;
  refresh();
  return true;
}

// Движок сам прокручивает пояс к первой свободной ячейке, когда предмет
// попадает за его край (VA 0x43834C).
export function beltFollow() {
  const bag = panelUnit().bag ?? [];
  beltFirst = 0;
  while (bag[beltFirst + beltCells()]) beltFirst += 1;
}

function renderBelt() {
  const data = info();
  const geometry = belt();
  const k = beltScale();
  const size = Math.max(8, Math.round(geometry.cell * k));
  const height = Math.round(geometry.height * k);
  const origin = (geometry.first_x - (screen().panel_width ?? 140)) * k;
  const width = beltNode.clientWidth || 1;
  const bag = panelUnit().bag ?? [];
  const nodes = [];

  const arrow = (side, art, x, step, enabled) => {
    if (!art) return;
    const node = cell({
      x: Math.round(x), y: 0,
      width: Math.round(art.width * k), height,
      art, className: enabled ? "" : "disabled",
      title: side === "left" ? "пояс левее" : "пояс правее",
      onClick: enabled ? () => beltScroll(step) : null,
    });
    nodes.push(node);
  };
  arrow("left", data?.belt?.arrows?.left, 0, -1, beltFirst > 0);
  arrow("right", data?.belt?.arrows?.right,
        width - (data?.belt?.arrows?.right?.width ?? 27) * k, 1,
        beltLimit() !== beltFirst);

  for (let slot = 0; slot < geometry.cells; slot += 1) {
    const index = beltFirst + slot;
    const name = bag[index] ?? null;
    nodes.push(cell({
      x: Math.round(origin + slot * geometry.pitch * k),
      y: Math.round((height - size) / 2),
      width: size, height: size, art: data?.cell ?? null,
      name, title: `ячейка ${index + 1}`,
      // Щелчок по ячейке: пустая рука берёт вещь, занятая — кладёт.
      onClick: () => {
        if (carrying()) carryPlaceBag(index);
        else if (name) carryTake("bag", index);
      },
      onDrop: () => dropFromBag(index, panelUnit()),
    }));
  }
  bagNode.replaceChildren(...nodes);
}

// Окно снаряжения открывается поверх окна мира — как в игре: оно ровно
// такой же ширины (884) и кончается там, где начинается пояс (638 из 709),
// поэтому и лежит от верхней кромки, а не по центру.
function renderWindow() {
  const data = info()?.equipment_window;
  if (!data || windowNode.hidden) return;
  const view = viewNode.getBoundingClientRect();
  const game = gameNode.getBoundingClientRect();
  // на узком окне браузера картинка не должна вылезать за кромки мира
  const k = Math.min(scale, view.width / data.width);
  const height = Math.round(data.height * k);
  const width = Math.round(data.width * k);
  windowNode.style.left = `${view.left - game.left + Math.round((view.width - width) / 2)}px`;
  windowNode.style.top = "0px";
  windowNode.style.width = `${width}px`;
  windowNode.style.height = `${height}px`;
  windowNode.style.backgroundImage = `url("${contentUrl(data.path)}")`;
  windowNode.style.backgroundSize = `${width}px ${height}px`;
  windowNode.style.backgroundRepeat = "no-repeat";
  const nodes = [];
  // Гнёзда движок держит в координатах ЭКРАНА, а окно стоит в проёме мира,
  // то есть с x = 140: гнездо руки на экране x=213 — это 73-й пиксель самой
  // картинки, ровно её левая ячейка.
  const originX = screen().panel_width ?? 140;
  for (const rect of data.slots) {
    // Гнездо смешивания — живое: в нём лежит вещь, на которую роняют
    // камень, зелье или точило (VA 0x436C48, код мыши 0x1C).
    const isMixing = rect.slot === "mixing";
    const name = isMixing
      ? mixing.name
      : rect.wearable ? (panelUnit().equipment?.[rect.slot] ?? null) : null;
    // подсказка гнезда — строка самой игры (таблица 0x45A090; у смешивания
    // своя, из craft-правил — VA 0x45042D)
    const hint = (isMixing ? mixingSlot()?.hint : rect.hint)
      || SLOT_TITLES[rect.slot] || "";
    nodes.push(cell({
      x: Math.round((rect.x - originX) * k), y: Math.round(rect.y * k),
      width: Math.round(rect.width * k), height: Math.round(rect.height * k),
      name, title: rect.slot === "ammo" && name
        ? `${hint} — ${panelUnit().ammoCount ?? 0} шт.` : hint,
      className: rect.wearable || isMixing ? "" : "disabled",
      onClick: isMixing
        ? () => { carryMixing(); refresh(); onChange(); }
        : rect.wearable
        ? () => { if (carrying()) carryPlaceSlot(rect.slot); else carryTake(rect.slot, -1); }
        : null,
      onDrop: rect.wearable ? () => dropFromSlot(rect.slot, panelUnit()) : null,
    }));
  }
  // Мешка в этом окне нет и в игре: окно снаряжения на 638 пикселей ровно
  // кончается там, где начинается пояс, а весь мешок листается его
  // стрелками. Своей сетки ячеек мы сюда не добавляем.
  windowSlotsNode.replaceChildren(...nodes, ...characterText(k));
}

// Торговый экран: четыре ряда по девять ячеек, две кнопки и шесть чисел.
// Всё по координатам из exe, только сдвинутым на ширину панели — окно
// стоит в проёме мира.
function renderTrade() {
  const data = tradeLayout();
  if (!data || !trade.open) { tradeNode.hidden = true; return; }
  tradeNode.hidden = false;
  const view = viewNode.getBoundingClientRect();
  const game = gameNode.getBoundingClientRect();
  const k = Math.min(scale, view.width / (screen().view_width ?? 884));
  const originX = screen().panel_width ?? 140;
  tradeNode.style.left = `${view.left - game.left}px`;
  tradeNode.style.top = "0px";
  tradeNode.style.width = `${Math.round((screen().view_width ?? 884) * k)}px`;
  tradeNode.style.height = `${Math.round((screen().view_height ?? 709) * k)}px`;
  const nodes = [];
  const cellSize = data.cell;
  for (const column of data.order) {
    const row = data.columns[column];
    const first = trade.scroll[column] ?? 0;
    for (let step = 0; step < data.visible; step += 1) {
      const index = first + step;
      const name = trade.columns[column][index] ?? null;
      nodes.push(cell({
        x: Math.round((row.x - originX + step * cellSize.pitch) * k),
        y: Math.round(row.y * k),
        width: Math.round(cellSize.width * k),
        height: Math.round(cellSize.height * k),
        art: info()?.cell ?? null,
        name, title: name ?? `ряд ${column}`,
        onClick: () => { if (name) tradeMove(column, index); },
      }));
    }
  }
  // шесть чисел: кошельки, столы и два итога
  const totals = tradeTotals();
  const values = [trade.purse.his, trade.table.his, totals.his,
                  trade.table.mine, trade.purse.mine, totals.mine];
  data.numbers.forEach((rect, index) => {
    const node = document.createElement("div");
    node.className = "trade-number";
    node.style.left = `${Math.round((rect.x - originX) * k)}px`;
    node.style.top = `${Math.round(rect.y * k)}px`;
    node.textContent = String(values[index] ?? 0);
    nodes.push(node);
  });
  for (const button of data.buttons) {
    const node = document.createElement("button");
    node.className = "trade-button";
    node.style.left = `${Math.round((button.x - originX) * k)}px`;
    node.style.top = `${Math.round(button.y * k)}px`;
    node.style.width = `${Math.round(button.width * k)}px`;
    node.style.height = `${Math.round(button.height * k)}px`;
    node.textContent = button.action === "deal" ? "Ok" : "Закрыть";
    node.addEventListener("click", () => {
      tradeFinish(button.action === "deal");
      refresh();
      onChange();
    });
    nodes.push(node);
  }
  tradeNode.replaceChildren(...nodes);
}

// Нажать кнопку панели по её имени — этим пользуются горячие клавиши.
export function pressButton(id) {
  const action = ACTIONS[id];
  if (!action?.press) return false;
  action.press();
  refresh();
  onChange();
  return true;
}

// Экран персонажа — по таблицам движка: числа стоят по 0x4612E4, подписи по
// 0x46140C, и те и другие выравниваются ПРАВЫМ краем по своему x. У
// характеристики печатаются базовая и текущая (на 0x5A правее), у навыка одно
// значение; знак «поднять» появляется там, где движок разрешает поднять —
// характеристику за 2 свободного опыта (VA 0x4131FC), навык за 1 (0x413268).
function characterText(k) {
  const data = info()?.character;
  const nodes = [];
  if (!data) return nodes;

  const put = (text, x, y, { align = "right", className = "" } = {}) => {
    const node = document.createElement("span");
    node.className = `ui-char ${className}`.trim();
    node.textContent = text;
    node.style.left = `${Math.round((x - (screen().panel_width ?? 140)) * k)}px`;
    node.style.top = `${Math.round(y * k)}px`;
    node.style.transform = align === "right" ? "translateX(-100%)" : "none";
    node.style.fontSize = `${Math.max(9, Math.round(15 * k))}px`;
    nodes.push(node);
    return node;
  };

  for (const label of data.labels ?? []) put(label.text, label.x, label.y);

  // ВЕСЬ экран — про одного юнита: первого выбранного (0x849514). Ему же
  // уходят и щелчки «поднять»: движок зовёт 0x4131FC/0x413268 с тем же
  // указателем, и свободный опыт у каждого юнита свой (+0x48).
  const who = panelUnit();
  const values = {
    level: who.level ?? 1,
    experience: who.experience ?? 0,
    free_xp: who.freeExperience ?? 0,
    next_level: levelThreshold(who.level ?? 1),
  };
  const extras = characterExtras(who, data);
  for (const number of data.numbers ?? []) {
    if (number.field in values) {
      // Уровень, опыт и порог движок печатает ЛЕВЫМ краем, а свободный
      // опыт — правым, с вычетом ширины строки (VA 0x42A8F4).
      const align = number.field === "free_xp" ? "right" : "left";
      put(String(values[number.field]), number.x, number.y, { align });
      continue;
    }
    if (number.field in extras) {
      const extra = extras[number.field];
      put(extra.text, number.x, number.y,
          { className: extra.over ? "over" : "" });
      continue;
    }
    if (number.field === "characteristic") {
      const index = number.index;
      put(String(who.baseCharacteristics?.[index] ?? who.characteristics?.[index] ?? 0),
          number.x, number.y);
      // правая колонка — ТЕКУЩАЯ характеристика (+0xCC): база вместе с
      // прибавками надетых украшений
      put(String(currentCharacteristics(who)[index] ?? 0),
          number.current_x, number.y);
      if (canRaiseCharacteristic(index, who)) {
        const mark = put("+", number.raise_x, number.y,
                         { align: "left", className: "raise" });
        mark.title = `поднять за ${characteristicCost()} свободного опыта`;
        mark.addEventListener("click", () => {
          raiseCharacteristic(index, who); refresh(); onChange();
        });
      }
      // «−» ЗДЕСЬ НЕТ. Откат живёт только на экране СОЗДАНИЯ героя: там его
      // рисует 0x430DF4 (x = 0x3CA, на 20 правее «+»), там же лежат счётчики
      // прибавок 0x8442D8/0x8442E0, и обнуляет их выбор архетипа (0x4387CC).
      // Игровой экран персонажа — другая функция: рендер 0x42A8F4 печатает
      // ТОЛЬКО «+», а обработчик щелчков 0x421690 знает лишь ветки поднятия
      // и счётчиков не трогает. Поднятое в игре окончательно.
      continue;
    }
    if (number.field === "skill") {
      const index = number.index;
      put(String(who.skills?.[index] ?? 0), number.x, number.y);
      if (canRaiseSkill(index, who)) {
        const mark = put("+", number.raise_x, number.y,
                         { align: "left", className: "raise" });
        mark.title = `поднять за ${skillCost()}, предел ${skillLimit(index, who)}`;
        mark.addEventListener("click", () => {
          raiseSkill(index, who); refresh(); onChange();
        });
      }
      // «−» у навыка — тоже только на экране создания (см. выше).
    }
  }
  return nodes;
}

//: Сдвиг знака «−» от знака «+» на экране СОЗДАНИЯ героя (0x430DF4:
//: 0x3CA − 0x3B6 = 20). На игровом экране персонажа «−» нет вовсе, поэтому
//: здесь число лежит для будущего экрана создания.
export const LOWER_DX = 20;

// Семь итоговых полей экрана — продолжение той же таблицы 0x4612E4 (их
// печатает та же ветка VA 0x42A8F4 следом за навыками): здоровье в
// шестнадцатых долях шкалы 0x640, отрава, броня, удар, вес несомого и его
// предел в килограммах, деньги. Подписи этих строк запечены в фоновом
// спрайте, поэтому в таблице подписей их нет.
// ЗДОРОВЬЕ НА ЭКРАНЕ = i16/16 С УСЕЧЕНИЕМ (VA 0x42A8F4): движок берёт поле
// unit+0x4E, делит на шестнадцать с округлением К НУЛЮ и, если у ЖИВОГО вышел
// ноль, печатает единицу. Полное здоровье 1600 показывается как 100.
//
// Сырое число 1600 движок не показывает нигде. Раньше эта формула жила
// только на листе персонажа, а подсказка на портрете и список сейвов писали
// сырое поле — отсюда и «здоровье 1600 из 1600» на экране.
function healthDivisor() { return info()?.character?.health_divisor ?? 16; }

// ПРОЗВИЩЕ ИГРОКА (VA 0x42FDC0). Подсказка о своём герое начинается не с
// имени, а с прозвища по двум сильнейшим характеристикам:
//
//     берутся ПЯТЬ базовых из шести — Обучаемость не участвует;
//     сортировка по убыванию с переносом номеров;
//     номер первой меньше номера второй -> вторую уменьшить на единицу;
//     строка = таблица[(значение_второй − 1) / шаг
//                      + номер_первой * 20 + номер_второй * 5]
//
// Существительное задаёт первая характеристика, прилагательное — вторая, а
// ступень внутри пятёрки — величина второй. Пока таблицы в паке нет,
// возвращаем пустое: подсказка тогда просто начнётся с уровня.
function heroEpithet() {
  const set = info()?.epithets;
  const names = set?.names;
  if (!names?.length) return "";
  const base = hero.baseCharacteristics ?? hero.characteristics;
  if (!base) return "";
  const picked = (set.characteristics ?? [0, 1, 2, 4, 5])
    .map((at, place) => ({ value: base[at] ?? 0, place }));
  // Устойчивая сортировка по убыванию — движок меняет местами только при
  // строгом «меньше», то есть равные сохраняют исходный порядок.
  picked.sort((a, b) => b.value - a.value);
  const first = picked[0]?.place ?? 0;
  let second = picked[1]?.place ?? 0;
  const value = picked[1]?.value ?? 0;
  if (first < second) second -= 1;
  const index = Math.trunc((value - 1) / (set.step ?? 30)) + first * 20 + second * 5;
  return names[index] ?? "";
}

export function healthShown(health, divisor = 16) {
  const shown = Math.trunc((health ?? 0) / divisor);
  return shown === 0 && (health ?? 0) !== 0 ? 1 : shown;
}

function characterExtras(who, data) {
  const divisor = data?.health_divisor ?? 16;
  const health = healthShown(who.health, divisor);
  const scale = data?.weight_scale ?? 0.001;
  const weight = carriedWeight(who);
  const limit = weightLimit(who);
  const kilograms = (grams) => (grams * scale).toFixed(1);
  return {
    health: { text: String(health) },
    poison: { text: String(who.poison ?? 0) },
    armour: { text: String(armourOf(who)) },
    strike: { text: String(strikeDisplay(who)) },
    // перегруз движок печатает красной палитрой 0x60054C
    weight: { text: kilograms(weight), over: weight > limit },
    weight_limit: { text: kilograms(limit) },
    money: { text: String(who.money ?? 0) },
  };
}

// Удар для экрана (VA 0x42A8F4): стрелковый (0x41A624) — когда есть
// боеприпас (+0x50), взведён режим (+0xEE) и занято метательное гнездо;
// иначе ближний (0x41A7D0) — оружие основной руки плюс, если в щитовом
// гнезде оружие (вид записи 0), удар второй руки. Чара удара (+0x44)
// прибавляется в КАЖДОМ вызове 0x41A7D0, поэтому при двух руках она
// входит дважды. Удар пустой руки в движке считается из Силы FP-выражением,
// съеденным Ghidra (SKILLS_AUDIT, В3) — пока, как и в бою, ноль.
function strikeDisplay(who) {
  const ranged = Boolean(who.rangedMode) && Boolean(who.equipment?.ranged) &&
    Boolean(who.equipment?.ammo);
  if (ranged) {
    const ammo = actorItem(who.equipment?.ammo);
    const bow = actorItem(who.equipment?.ranged);
    return Math.max(0, (ammo?.power ?? 0) * (bow?.power ?? 0) + bonusStrike(who));
  }
  const weapon = actorItem(who.equipment?.hand);
  let strike = (weapon?.power ?? 0) + bonusStrike(who);
  const off = actorItem(who.equipment?.off_hand);
  if (off && off.kind === 0) strike += (off.power ?? 0) + bonusStrike(who);
  return Math.max(0, strike);
}

export function toggleWindow(open = windowNode.hidden) {
  windowNode.hidden = !open;
  refresh();
}

// ЖУРНАЛ ЗАДАНИЙ (VA 0x42A8F4, ветка 1). Движок перебирает триста состояний
// и печатает те, у которых взведён бит 0x80 И есть номер фразы; строки
// «MAP=» он пропускает (strncmp по 0x4524BD) — их отсеял сборщик пака.
// Порядок — по номеру квеста, как в переборе.
export function toggleJournal(open = journalNode.hidden) {
  journalNode.hidden = !open;
  if (open) {
    const записи = dialogJournal();
    journalListNode.textContent = "";
    if (!записи.length) {
      // Пустой журнал в начале игры — это КАНОН: в QUESTS.RES бит 0x80 не
      // взведён ни у одного из трёхсот квестов.
      const пусто = document.createElement("p");
      пусто.textContent = "Записей пока нет";
      journalListNode.append(пусто);
    }
    for (const запись of записи) {
      const строка = document.createElement("p");
      строка.textContent = запись.text;
      journalListNode.append(строка);
    }
  }
  refresh();
}
journalCloseNode?.addEventListener("click", () => toggleJournal(false));

// ESC ПО КАНОНУ. Движок разбирает его по состоянию экрана (VA 0x438A00,
// ветка кода 0x1B, switch по 0x849574):
//
//   в игре (состояние 0): сперва ОТМЕНЯЕТСЯ ПЕРЕНОС вещи — `FUN_0042944c(1)`;
//   затем, если открыт какой-то экран (0x8495F0 не ноль), закрывается ОН,
//   и игра продолжается; и только когда не открыто ничего, движок уходит в
//   меню (состояние 7).
//
// То есть один ESC никогда не выкидывает из игры, если на экране что-то
// открыто, — он сначала снимает это. Возвращает true, если нажатие
// израсходовано здесь и до меню дело не дошло.
export function uiEscape() {
  if (carrying()) { carryCancel(); refresh(); return true; }
  if (!journalNode.hidden) { toggleJournal(false); return true; }
  if (!windowNode.hidden) { toggleWindow(false); return true; }
  if (mapOpen) { showWorldMap(false); return true; }
  return false;
}

export function refresh() {
  if (!gameNode) return;
  layout();
  renderPanel();
  renderBelt();
  renderWindow();
  renderTrade();
  renderWorldMap();
  renderTalk();
  if (weightNode) weightNode.textContent = `вес ${inventoryWeight().toFixed(2)} кг`;
}

export function uiSetup(changed = () => {}) {
  onChange = changed;
  windowCloseNode?.addEventListener("click", () => toggleWindow(false));
  mapNode?.addEventListener("click", worldMapClick);
  mapNode?.addEventListener("mousemove", worldMapMove);
  // Раскладка задаёт ширину панели и высоту пояса, то есть меняет сам размер
  // окна мира, поэтому после неё холст обязан пересчитаться: об этом и
  // сообщает onChange.
  window.addEventListener("resize", () => { refresh(); onChange(); });
  refresh();
  onChange();
}
