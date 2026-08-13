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
import { carriedWeight, carry, carryActor, carryApplyTo, carryCancel, carryDrop,
         carryMixing, carryPlaceBag, carryPlaceSlot, carryTake, carryUse, carrying,
         weightLimit } from "./carry.js";
import { mixing, mixingHides, mixingSlot, mixingTake } from "./craft.js";
import { carryCursorSync } from "./cursors.js";
import { SLOT_TITLES, equipFromBag, inventoryWeight,
         requirementMet, unequip } from "./inventory.js";
import { armourOf, orderTalkTo } from "./combat.js";
import { bonusStrike, currentCharacteristics,
         enchantBonuses } from "./jewels.js";
import { dialog, dialogChoose, dialogClose, dialogJournal,
         dialogOptions } from "./dialog.js";
import { locationName, markerVisible, standAt, startTravel,
         startTravelTo, travelling,
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

//: Зажатые модификаторы. В движке это два отдельных флага главного цикла:
//: 0x849608 «добавить к выбору» по клавише 0x10 (Shift) и 0x8495AC
//: «заговорить» по клавише 0x11 (Ctrl) — VA 0x438A00:44.
const keyHeld = { shift: false, ctrl: false };
function keyHeldFrom(event) {
  keyHeld.shift = event.shiftKey;
  keyHeld.ctrl = event.ctrlKey;
}
window.addEventListener("keydown", keyHeldFrom);
window.addEventListener("keyup", keyHeldFrom);

let onChange = () => {};
let scale = 1;
// Номер первой видимой ячейки мешка: в движке это 0x849714.
let beltFirst = 0;

function info() { return world.map?.interface ?? null; }

function screen() {
  return info()?.screen ?? { width: 1024, height: 768, panel_width: 140,
                             view_width: 884, view_height: 709 };
}

// Пояс из движка (VA 0x43096C): ряд на строке 639, двенадцать ячеек 70x70
// с шагом 69, первая с x=168, по краям стрелки прокрутки.
function belt() {
  return info()?.belt ?? { y: 639, height: 70, cell: 70, pitch: 69,
                           first_x: 168, cells: 12, left_x: 140, right_x: 1023 };
}

//: Ширина стрелок ряда: слева 28, справа 27 (INTERF.RES, VA 0x43096C).
function beltArrows() {
  const set = info()?.belt?.arrows;
  return (set?.left?.width ?? 28) + (set?.right?.width ?? 27);
}

// СКОЛЬКО ЯЧЕЕК ПОМЕЩАЕТСЯ — НЕ БОЛЬШЕ ДВЕНАДЦАТИ, НО МОЖЕТ БЫТЬ МЕНЬШЕ.
//
// В игре их всегда двенадцать: экран 1024x768, и ряд от кромки панели до
// правого края рассчитан ровно на них. У нас окно любой формы, и когда оно
// уже четырёх третей, двенадцать ячеек в общем масштабе в проём не лезут —
// ряд вылезал на панель. Считаем, сколько шагов поместится в проёме, и
// показываем столько; до остальных мешок листается стрелками, как и прежде.
export function beltCells() {
  const geometry = belt();
  const most = geometry.cells ?? 12;
  const pitch = geometry.pitch ?? 69;
  const room = (viewNode?.clientWidth ?? 0) / (scale || 1) - beltArrows();
  if (!(room > 0)) return most;
  return Math.max(1, Math.min(most, Math.floor(room / pitch)));
}

//: Ниже какой концентрации снадобье считается слабым (VA 0x432303 и
//: 0x432324): «Масло» и класс 93 хотят десять, «Эликсир Мудрости» — шесть.
const WEAK_BELOW = { 87: 10.0, 92: 6.0, 93: 10.0 };

// Подсказка предмета — те же поля, что печатает игра (VA 0x4315A0): урон
// или броня, вес в килограммах, цена, дальность и требование.
// ВЛАДЕЛЬЦА СПРАШИВАЕМ У ВЫЗЫВАЮЩЕГО. Концентрация зелья — это float +0x04
// САМОЙ ЗАПИСИ предмета, и движку всё равно, у кого она в руках. У нас
// экземплярные поля живут картами владельца, поэтому владельца надо назвать:
// в окне обмена вещь принадлежит собеседнику, а не игроку. Здесь всегда
// стоял `panelUnit()`, то есть игрок, — и любое зелье на чужом прилавке
// показывало «концентрация 0.00», хотя в паке у него честные 5.0 и 6.0.
function describe(name, owner = panelUnit()) {
  const item = actorItem(name);
  if (!item) return "";
  const parts = [item.name];
  //: Экземплярные поля вещи: в открытом обмене они лежат в его складе (туда
  //: `tradeOpen` собирает обе стороны по ссылке записи), иначе — у владельца.
  const traded = trade.open ? trade.details?.[name] : null;
  // СНАДОБЬЕ ОПИСЫВАЕТСЯ ИНАЧЕ (VA 0x4322A1).
  //
  // Признак — ОТРИЦАТЕЛЬНАЯ ЦЕНА в записи класса: движок читает знаковое
  // поле +0x12 и при минусе дописывает к названию концентрацию:
  //
  //     mov eax, [eax + 0x45db00]; sar eax, 0x10; test eax, eax
  //     jge пропустить
  //       strcat(буфер, ", концентрация ")
  //       fld dword [запись + 4]; sprintf(врем, "%5.2f", крепость)
  //
  // Минус стоит ровно у восьми варимых зелий (85…92: бальзам, яд, масло,
  // противоядие, брага, зелье, чистая слеза, эликсир), и цену движок им НЕ
  // печатает вовсе — ветка кончается весом. Мы же выводили сырое поле, и в
  // подсказке Яда стояло «цена -11».
  //
  // Сама концентрация — тот же float +0x04 записи предмета, что у оружия
  // служит прочностью; у нас оба живут в `bagStrength`, как и в движке.
  if (item.price < 0) {
    const value = (name === mixing.name && typeof mixing.strength === "number")
      ? mixing.strength
      : (traded?.strength ?? owner?.bagStrength?.[name] ?? 0);
    parts.push(`концентрация ${value.toFixed(2)}`);
    const need = WEAK_BELOW[item.index];
    if (need !== undefined && value < need) parts.push("недостаточная концентрация");
    parts.push(`вес ${(item.weight / 1000).toFixed(2)} кг`);
    return parts.join(" · ");
  }
  if (item.power) parts.push(`${item.slot === "hand" || item.slot === "ranged"
    ? "урон" : "броня"} ${item.power}`);
  parts.push(`вес ${(item.weight / 1000).toFixed(2)} кг`, `цена ${item.price}`);
  if (item.range_cells > 1) parts.push(`дальность ${item.range_cells}`);
  if (item.requires && item.requirement) {
    parts.push(`требует ${item.requires} ${item.requirement}`);
  }
  // ЧТО ВЕЩЬ ДАЁТ. Слово прибавок (+0x0E записи) — пять значений по три
  // бита, и величину каждому даёт таблица (VA 0x41C494). Неопознанная магия
  // молчит: пока стоит старший бит, прибавок нет вовсе, и это канон —
  // `enchantBonuses` возвращает пусто.
  //
  // Показываем и в мешке, и на чужом прилавке: до этой строки судить об
  // украшении можно было, только купив его и надев.
  const word = traded?.enchant ?? owner?.bagEnchant?.[name] ?? 0;
  for (const [field, value] of Object.entries(enchantBonuses(word))) {
    parts.push(`${bonusName(field)} +${value}`);
  }
  return parts.join(" · ");
}

// ИМЯ ПРИБАВКИ ВМЕСТО НОМЕРА ПОЛЯ. В подсказке стояло сырое число, и игрок
// видел «6 +1» — а это Выносливость.
//
// Номера полей у чар единые с требованиями вещей и считаются С ЕДИНИЦЫ:
// `FUN_0041AAD8` разрешает их так же — 0 уровень, 1…6 байты +0xCC…+0xD1
// (Харизма, Ловкость, Интеллект, Обучаемость, Сила, Выносливость), а дальше
// вычисляемые. У чар сверх шестёрки идут три поля самой записи юнита, и они
// названы в паке: 7 броня (+0x42), 8 сила удара (+0x44), 9 точность (+0x46).
const BONUS_EXTRA = { 7: "Броня", 8: "Удар", 9: "Точность" };

function bonusName(field) {
  const number = Number(field);
  const names = hero.data?.rules?.progression?.characteristics?.names ?? [];
  if (number >= 1 && number <= names.length) return names[number - 1];
  return BONUS_EXTRA[number] ?? `поле ${number}`;
}

// ЦВЕТ ЗНАЧКА ВЕЩИ — перенос FUN_0042FF20. Движок не рисует значок как есть:
// он подбирает вещи палитру и красит её ПЕРЕД отрисовкой (зовут из разбора
// мешка, VA 0x42BFE8 и 0x43096C). Порядок проверок такой:
//
//     не может надеть (FUN_00418648)      -> FUN_0044293F(0x18, 0, 0)  красный
//     опознана:
//         байт +1 отрицателен И слово чар (маска 0x7FFF) ноль -> без краски
//         иначе                            -> FUN_0044293F(0, 0x0C, 0)  зелёный
//     не опознана (вещь[+0x0F] бит 0x80)   -> FUN_0044293F(0x0F, 0x0F, 0) жёлтый
//
// ЖЁЛТЫЙ В ОБЫЧНОЙ ИГРЕ НЕ ПОКАЗЫВАЕТСЯ, и это не наша недоделка. Тело
// `FUN_00418648` целиком лежит под `if ((вещь[+0x0F] & 0x80) == 0)` — то есть
// неопознанная вещь не проходит саму проверку «можно ли надеть» и красится
// КРАСНЫМ раньше, чем разбор дойдёт до жёлтой ветки. Открыть её может только
// флаг `0x849620`, который снимает проверку целиком. Мы повторяем это как
// есть: у нас `requirementMet` тоже отвергает неопознанное первой строкой.
//
// Ровно этого и не хватало игроку: у торговца всё выглядело одинаково, и
// понять, что вещь не надеть по характеристикам, можно было только купив её.
//
//: Сама КРАСКА в движке табличная: `0x4429 3F` выбирает три строки заранее
//: посчитанных таблиц (0x4BEA2C красная, 0x479D50 зелёная, 0x474950 синяя,
//: плюс «вычитающие» близнецы), а `0x441DF9` гоняет через них каждый из трёх
//: пятибитных каналов палитры. Таблиц в паке пока нет, поэтому здесь оттенок
//: приближённый — ВЫБОР состояния канонический, а сам цвет ещё нет.
function itemTint(name, owner = panelUnit()) {
  if (!name || !owner) return null;
  if (!requirementMet(name, owner)) return "unusable";
  const traded = trade.open ? trade.details?.[name] : null;
  const word = traded?.enchant ?? owner.bagEnchant?.[name] ?? 0;
  const dormant = world.map?.hero?.rules?.jewellery?.enchant?.dormant ?? 0x8000;
  if (word & dormant) return "unknown";
  return word ? "special" : null;
}

function iconNode(name, owner = panelUnit()) {
  const icon = actorItem(name)?.icon;
  if (!icon) return null;
  const image = document.createElement("img");
  image.src = contentUrl(icon.path);
  image.alt = name;
  const tint = itemTint(name, owner);
  // ЦВЕТ — ЭТО ЦВЕТ, А НЕ ПОДПИСЬ. Здесь стояло `image.title = ITEM_TINTS[tint]`,
  // и всплывающая подсказка над значком говорила игроку «зелёный» или
  // «красный» вместо описания вещи: своя подсказка у картинки перебивает
  // подсказку ячейки, в которой она лежит. Никакой такой подписи в движке
  // нет — там `FUN_0042FF20` только подбирает вещи палитру перед отрисовкой
  // значка, и весь смысл передаётся самим цветом. Название вещи ставит
  // ячейка (`describe`), и мешать ему нельзя.
  if (tint) image.classList.add(`item-${tint}`);
  return image;
}

//: Мерки пары касаний — те же, что на карте (input.js): срок и допуск по
//: месту, потому что пальцем во второй раз в ту же точку не попадают.
const TAP_GAP_MS = 400;
const TAP_SLIP = 24;

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
  //: Модификаторы берём из САМОГО щелчка, а не только из клавиатуры: мышью
  //: можно нажать Ctrl или Shift и не дать окну ни одного keydown — скажем,
  //: зажав их до того, как страница получила фокус.
  if (onClick) {
    node.addEventListener("click", (event) => {
      keyHeldFrom(event);
      onClick(event);
      refresh();
      onChange();
    });
  }
  if (onDoubleClick) node.addEventListener("dblclick", () => { onDoubleClick(); });
  if (onDrop) {
    node.addEventListener("contextmenu", (event) => {
      event.preventDefault();
      onDrop();
      refresh();
      onChange();
    });
    // ДВОЙНОЕ КАСАНИЕ — ТА ЖЕ ПРАВАЯ КНОПКА. На телефоне второй кнопки нет
    // вовсе: Android иногда даёт `contextmenu` по долгому нажатию, iPhone не
    // даёт никогда, — и применить вещь было нечем.
    //
    // Пару считаем сами, теми же мерками, что и на карте (input.js): два
    // касания подряд, в срок и в одно место. Событию `dblclick` доверять
    // нельзя — по касаниям браузеры шлют его как придётся.
    //
    // ВЕЩЬ СНАЧАЛА ВОЗВРАЩАЕМ. Первое касание уже успело взять её в руку
    // (это обычный щелчок по ячейке), и применять было бы нечего: отменяем
    // перенос, вещь ложится назад, и только потом идёт применение.
    let последнее = 0;
    let точка = { x: 0, y: 0 };
    node.addEventListener("pointerdown", (event) => {
      const пара = event.timeStamp - последнее < TAP_GAP_MS &&
        Math.abs(event.clientX - точка.x) < TAP_SLIP &&
        Math.abs(event.clientY - точка.y) < TAP_SLIP;
      последнее = пара ? 0 : event.timeStamp;
      точка = { x: event.clientX, y: event.clientY };
      if (!пара) return;
      event.preventDefault();
      if (carrying()) carryCancel();
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
      const following = mates.every((mate) => (mate.orderByte ?? 0) & bit);
      for (const mate of mates) {
        setMode(mate, bit, !following);
        mate.path = [];
      }
      status(following ? `Отряд ждёт на месте: ${mates.length}`
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

// ПОДПИСЬ КАРТЫ. Имя показывается только у ИЗВЕСТНОГО места — решает это
// `locationName` (worldmap.js), общая для подписи, наведения и прихода.
// Здесь имя бралось прямо из номера клетки, и над неоткрытой локацией
// писалось её настоящее название.
function mapTitle() {
  const rules = worldMap.rules;
  if (!rules) return world.map?.name ?? "";
  const here = mapHover || (worldMap.row === null ? 0
    : worldMap.cells[worldMap.row][worldMap.col] & 0xFF);
  if (!here) return world.map?.name || "";
  return locationName(here);
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
  status(`Входим: ${locationName(number)}`);
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
    const name = under && locationName(under);
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

// ПОЯС ЖИВЁТ В ОБЩЕМ МАСШТАБЕ, А НЕ РАСТЯГИВАЕТСЯ ПО ОКНУ.
//
// Ряд у движка один и тот же: 28 точек левой стрелки, двенадцать ячеек шагом
// 69, 27 правой — от кромки панели (140) до края экрана (1023), ровно 884
// (VA 0x43096C). Ячеек всегда двенадцать, это канон.
//
// Раньше ряд считался от ФАКТИЧЕСКОЙ ширины окна, чтобы лечь между кромками
// вплотную. Но окно браузера редко бывает 4:3, и ряд от этого разъезжался:
// ячейки выходили не квадратными, а на телефоне в альбомной ориентации ряд
// становился ещё и вдвое выше положенного — там ширина к высоте куда больше
// четырёх третей, и множитель по ширине оказывался вдвое крупнее общего.
// Теперь масштаб один на всю рамку, а сам ряд стоит по центру окна.
function beltScale() { return scale; }

function layout() {
  const data = info();
  const box = screen();
  const height = gameNode?.clientHeight || box.height;
  scale = height / box.height;
  const panelWidth = Math.round(box.panel_width * scale);
  panelNode.style.width = `${panelWidth}px`;
  const frameWidth = Math.round((data?.frame?.width ?? box.width) * scale);
  const frameHeight = Math.round((data?.frame?.height ?? box.height) * scale);
  // НИЖНЕЙ ПОЛОСЫ РАМКИ У НАС НЕТ. В игре под окном мира идёт лента кожи со
  // строки 709 до низа экрана — украшение, ничего на ней не лежит. Мы её
  // убрали: окно мира занимает всю высоту, и это пятьдесят девять точек по
  // мерке игры, которых на телефоне очень не хватает.
  if (data?.frame) {
    panelArtNode.style.backgroundImage = `url("${contentUrl(data.frame.path)}")`;
    panelArtNode.style.backgroundSize = `${frameWidth}px ${frameHeight}px`;
  }
  //: Ряд ячеек стоит на самой нижней кромке окна мира: полосы под ним больше
  //: нет, и отступать не от чего. Ширина — по числу поместившихся ячеек, а
  //: прижат ряд к кромке панели, как в игре.
  const пояс = belt();
  beltNode.style.width =
    `${Math.round((beltArrows() + beltCells() * (пояс.pitch ?? 69)) * scale)}px`;
  beltNode.style.height = `${Math.round(belt().height * scale)}px`;
  beltNode.style.bottom = "0px";
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
// ЗДОРОВЬЕ ИЗМЕНИЛОСЬ — ПЕРЕРИСОВАТЬ. В движке ровно так: каждое место,
// правящее `+0x4E`, зовёт FUN_004305A4 само (0x41C944, 0x414DF0, 0x41FDD0,
// 0x41D954, 0x4277F4, 0x413894 и три ветки разговора). Своего расписания у
// панели нет — потому и рассинхрона нет. Наш `healthSet` (effects.js) зовёт
// это, и портрет с подписью пересчитываются в тот же миг.
world.onHealth = () => refresh();

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

// СВОБОДНАЯ ПОЛОСА ПАНЕЛИ — от низа портретов отряда до первой кнопки.
//
// В таблице раскладки движка (0x460EB4) шестнадцать записей: девять портретов
// и семь кнопок. Между ними остаётся полоса — у стартовых героев это y 424…501,
// сто сорок на семьдесят семь, — и в таблице её НЕТ: попадание мыши там движок
// не считает вовсе (VA 0x43AFE3 возвращает только номера записей). То есть
// герб на ней — чистое украшение рамки, и место ничем не занято.
//
// Границы берём из самой таблицы, а не числами: сместится раскладка — уедет и
// полоса, без правок здесь.
function panelGap(panel) {
  let top = 0;
  let bottom = Infinity;
  for (const rect of panel) {
    if (rect.name.startsWith("party_")) top = Math.max(top, rect.y + rect.height);
    if (rect.name.startsWith("button_")) bottom = Math.min(bottom, rect.y);
  }
  if (!top || !Number.isFinite(bottom) || bottom - top < 20) return null;
  return { x: 0, y: Math.round(top * scale),
           width: Math.round((screen().panel_width ?? 140) * scale),
           height: Math.round((bottom - top) * scale) };
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
                          // С ВЕЩЬЮ В РУКЕ портрет не выбирает, а применяет
                          // (VA 0x421690:292 -> 0x41F55C): для того, чья
                          // панель открыта, это «использовать на нём».
                          onClick: () => {
                            if (carrying()) {
                              if (carryActor() === hero) carryApplyTo(hero);
                              else carryPlaceBag(-1, hero);
                            } else selectUnit(hero, keyHeld.shift);
                            refresh();
                          },
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
        // А с вещью в руке портрет спутника — это ПЕРЕДАЧА: движок кладёт
        // вещь ему в мешок через 0x423218 с индексом −1, то есть в первую
        // свободную ячейку (VA 0x421690:301).
        // CTRL ПО ПОРТРЕТУ — ЗАГОВОРИТЬ, а не выбрать: в движке это та же
        // ветка, что и Ctrl по юниту в мире, — приказ 0x22 игроку с номером
        // соотрядника целью (VA 0x421690:349, разбор попадания 0x43AEF0 по
        // таблице панели 0x460EB4). Без неё до спутника, зашедшего в дом или
        // застрявшего за спинами, было не докликаться вовсе, а через этот
        // разговор его назначают на должность в деревне.
        onClick: mate ? () => {
          if (carrying()) {
            if (carryActor() === mate) carryApplyTo(mate);
            else carryPlaceBag(-1, mate);
          } else if (!(keyHeld.ctrl && orderTalkTo(mate))) {
            selectUnit(mate, keyHeld.shift);
          }
          refresh();
        } : null,
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
  // ВЫХОД В МЕНЮ — НАША КНОПКА, канону она неизвестна: в движке меню
  // открывается своей клавишей, и места на панели под него нет.
  //
  // Своей картинки не рисуем: герб уже лежит в самой рамке (спрайт 3), а
  // золотая обводка по наведению у ячеек панели общая. Клавиша Esc делает то
  // же самое — обе дороги сходятся в `world.openMenu`, то есть поднимают
  // накладку. Страницу не уводит ни одна: это стоило бы полной перезагрузки
  // пака и карты (gamemenu.js).
  const gap = panelGap(data.panel);
  if (gap) {
    // Класс НАРОЧНО не `menu`: в menu.css так зовётся плита стартового меню
    // (`translate: -50% 0`), а он подгружается вместе с накладкой и накрыл бы
    // эту кнопку, уведя её на половину ширины влево.
    const node = cell({ ...gap, title: "Меню (Esc)", className: "to-menu",
                        onClick: () => world.openMenu?.() });
    // ПЛАШКА — НАШ СПРАЙТ, не из пака: в игровых ресурсах такой кнопки нет,
    // и место ей в клиенте, а не среди данных игры. Рисунок повторяет герб,
    // запечённый в рамку, и ложится ровно поверх него — подмены не видно.
    // Ради неё всё и затевалось: часть рамки не подсветишь и не вдавишь, а
    // отдельную картинку — сколько угодно (styles.css).
    node.style.backgroundImage = 'url("/menu-button.png")';
    node.style.backgroundSize = "100% 100%";
    // ПОВТОР ГАСИМ ЯВНО. У ячейки рамка в пиксель, фон размеряется по
    // внутренней коробке, а рисуется по внешней — и при повторе (значение по
    // умолчанию!) под рамкой выглядывала соседняя плитка: слева тёмный правый
    // край картинки, справа светлый левый. `cell` ставит `no-repeat` только
    // тем, кто пришёл через `art`, а мы кладём фон сами.
    node.style.backgroundRepeat = "no-repeat";
    //: И размеряем по ВНЕШНЕЙ коробке, чтобы пиксель рамки не съедал край.
    node.style.backgroundOrigin = "border-box";
    nodes.push(node);
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

// ПОЯС ПРЯЧЕТСЯ ПО Ё/~ — перенос ветки клавиши из FUN_00437FF8 (строка 220):
//
//     else if ((клавиша == 0xC0) && (режим_экрана == 0)) {
//         [0x849514] = [0x840B94];                  // панель — первому выбранному
//         if ([0x840B94] == 0) { [0x849618] = 0; [0x8495D8] = 0; }   // СКРЫТЬ
//         else if (номер выбранного == [0x8495D8]) {                  // тот же — СКРЫТЬ
//             [0x849618] = 0; [0x8495D8] = 0;
//         } else {                                                     // другой — ПОКАЗАТЬ
//             [0x849714] = 0;   // смещение пояса в начало
//             [0x849668] = 0;   // и пометку гнезда смешивания долой
//             FUN_0043096C(выбранный, 0);
//         }
//     }
//
// 0xC0 — это VK_OEM_3, клавиша Ё на нашей раскладке и ~ на латинской; ветка
// живёт только в режиме экрана 0, то есть в самой игре, а не в меню и не в
// окнах. То есть Ё — не «скрыть», а ПЕРЕКЛЮЧАТЕЛЬ: пояс уже показывает мешок
// этого юнита — прячем; показывает чужой или не показан — показываем его и
// сбрасываем смещение.
//: Чей мешок на поясе — наш [0x8495D8]. `undefined` значит «пояс показан и
//: следует за панелью» (обычное состояние экрана: движок держит [0x849618]
//: поднятым с самого начала), `null` — игрок его спрятал.
let beltOwner;

export function beltHidden() { return beltOwner === null; }

export function beltToggle() {
  const unit = panelUnit();
  //: Показывает мешок этого же юнита — прячем; спрятан или чужой — показываем.
  if (beltOwner === null || (unit && beltOwner !== undefined && beltOwner !== unit)) {
    beltOwner = unit ?? undefined;
    beltFirst = 0;
    mixingTake();
  } else {
    beltOwner = null;
  }
  refresh();
  return beltOwner !== null;
}

// ПРАВАЯ КНОПКА ПО МИРУ пустой рукой (VA 0x422AFC -> 0x420644). Движок
// сбрасывает ровно две вещи: смещение пояса (0x849714) и пометку гнезда
// смешивания (0x849668). Сама вещь из гнезда никуда не девается — она всё
// это время лежит в мешке, гнездо только помечало её.
//
// Панель персонажа движок тут же возвращает игроку (0x849514 = игрок). У нас
// панель ВЫВОДИТСЯ из выбора (`panelUnit`), поэтому отдельного указателя
// нет, и трогать выбор я не стал: в разборе 0x422AFC его никто не чистит.
export function panelToHero() {
  beltFirst = 0;
  mixingTake();
}

// Движок сам прокручивает пояс к первой свободной ячейке, когда предмет
// попадает за его край (VA 0x43834C).
export function beltFollow() {
  const bag = panelUnit().bag ?? [];
  beltFirst = 0;
  while (bag[beltFirst + beltCells()]) beltFirst += 1;
}

function renderBelt() {
  // Спрятанный пояс просто не показывается — и не закрывает нижнюю часть
  // карты. ЧИСТИТЬ ЕГО НЕЛЬЗЯ: ячейки лежат в дочернем узле `bagNode`, и
  // `replaceChildren()` на поясе вырезал его из DOM целиком. Пояс после
  // этого «возвращался» пустой рамкой, а нарисованное уходило в узел,
  // которого на странице больше нет.
  if (beltHidden()) { beltNode.hidden = true; return; }
  beltNode.hidden = false;
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

  for (let slot = 0; slot < beltCells(); slot += 1) {
    const index = beltFirst + slot;
    // Помеченная гнездом вещь читается как пустая ячейка (VA 0x420890).
    const held = bag[index] ?? null;
    const name = mixingHides(held) ? null : held;
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
      // Правая кнопка ПРИМЕНЯЕТ, а не бросает (VA 0x422AFC): надеть, выпить
      // или — если вещь в руке — отменить перенос. Бросок на землю в движке
      // делается щелчком по миру, а не по ячейке.
      onDrop: () => carryUse(index, panelUnit()),
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
      // Правая кнопка по НАДЕТОМУ в оригинале не делает ничего: её разбор
      // (VA 0x422AFC) знает только мир и список мешка, гнёзд снаряжения в
      // его switch нет. Единственное, что остаётся, — отмена переноса, если
      // вещь в руке; ею и занимается carryUse с несуществующей ячейкой.
      onDrop: rect.wearable ? () => carryUse(-1, panelUnit()) : null,
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
  // ЭКРАН ОБМЕНА ВПИСЫВАЕТСЯ В ПРОЁМ ЦЕЛИКОМ И ВСТАЁТ ПО ЦЕНТРУ.
  //
  // В игре он занимает всё окно мира — там оно всегда 884x709. У нас окно
  // любой формы, и прежний расчёт брал масштаб самой игры: на телефоне это
  // давало коробку вчетверо меньше проёма, прижатую в угол, — отсюда и
  // ощущение, что всё разбежалось. Берём наибольший масштаб, при котором
  // раскладка целиком помещается по обеим сторонам, и центруем остаток.
  const ширина = screen().view_width ?? 884;
  const высота = screen().view_height ?? 709;
  const k = Math.min(view.width / ширина, view.height / высота);
  const originX = screen().panel_width ?? 140;
  tradeNode.style.left =
    `${Math.round(view.left - game.left + (view.width - ширина * k) / 2)}px`;
  tradeNode.style.top = `${Math.round((view.height - высота * k) / 2)}px`;
  tradeNode.style.width = `${Math.round(ширина * k)}px`;
  tradeNode.style.height = `${Math.round(высота * k)}px`;
  // РАЗМЕР БУКВ ТОЖЕ ОТ МАСШТАБА. Коробки кнопок и чисел считаются с `k`, а
  // шрифт стоял намертво в пятнадцать точек: на маленьком окне надписи
  // вылезали из кнопок, на большом тонули в них. Отдаём множитель в стиль
  // одним свойством, а сами числа остаются в таблице стилей.
  tradeNode.style.setProperty("--trade-k", String(k));
  const nodes = [];
  const cellSize = data.cell;
  // СТРЕЛКИ ЛИСТАНИЯ. Ряд вмещает девять ячеек из сорока двух (`visible` и
  // `slots` раскладки), и без них до остального мешка не добраться вовсе —
  // на это и жаловались. Свои коды у них есть (`codes.left` 0x1D и
  // `codes.right` 0x1E), а прямоугольников в exe нет: они и не нужны, потому
  // что ПРЯМОУГОЛЬНИК РЯДА ИХ УЖЕ СОДЕРЖИТ. Арифметика сходится до байта:
  //
  //     288 + 28 + 8*69 + 70 + 27 = 965 = правый край ряда
  //     ^     ^     ^      ^       ^
  //     x   левая  восемь  ширина  правая
  //         стрелка шагов  ячейки  стрелка
  //
  // Поэтому ячейки начинаются не от края ряда, а после левой стрелки —
  // раньше они стояли от самого края, и справа оставалась пустая полоса.
  //
  // Спрайты те же, что у пояса (18/19 и 20/21 — `screen_layout.arrows`),
  // оттуда их и берём: второго набора в паке нет и заводить его незачем.
  const стрелки = info()?.belt?.arrows ?? null;
  const шагов = (column) => Math.max(0, (trade.columns[column]?.length ?? 0) - data.visible);
  const пролистать = (column, step) => {
    const было = trade.scroll[column] ?? 0;
    const стало = Math.min(Math.max(0, было + step), шагов(column));
    if (стало === было) return;
    trade.scroll[column] = стало;
    refresh();
  };
  for (const column of data.order) {
    const row = data.columns[column];
    const first = trade.scroll[column] ?? 0;
    const слева = стрелки?.left?.width ?? 28;
    const справа = стрелки?.right?.width ?? 27;
    const стрелка = (art, x, step, живая, подпись) => {
      if (!art) return;
      nodes.push(cell({
        x: Math.round((x - originX) * k),
        y: Math.round((row.y + (row.height - art.height) / 2) * k),
        width: Math.round(art.width * k), height: Math.round(art.height * k),
        art, className: живая ? "" : "disabled", title: подпись,
        onClick: живая ? () => пролистать(column, step) : null,
      }));
    };
    стрелка(стрелки?.left, row.x, -1, first > 0, "левее");
    стрелка(стрелки?.right, row.x + row.width - справа, 1,
            first < шагов(column), "правее");
    for (let step = 0; step < data.visible; step += 1) {
      const index = first + step;
      const name = trade.columns[column][index] ?? null;
      nodes.push(cell({
        x: Math.round((row.x + слева - originX + step * cellSize.pitch) * k),
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
    const entries = dialogJournal();
    journalListNode.textContent = "";
    if (!entries.length) {
      // Пустой журнал в начале игры — это КАНОН: в QUESTS.RES бит 0x80 не
      // взведён ни у одного из трёхсот квестов.
      const blank = document.createElement("p");
      blank.textContent = "Записей пока нет";
      journalListNode.append(blank);
    }
    for (const journalEntry of entries) {
      const paragraph = document.createElement("p");
      paragraph.textContent = journalEntry.text;
      journalListNode.append(paragraph);
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
  // Вещь в руке видна поверх всего экрана, а не только над миром: перенос в
  // движке — режим курсора, панели ему не помеха.
  carryCursorSync();
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
