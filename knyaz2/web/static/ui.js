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
import { orderClear, orderModes, setMode } from "./orders.js";
import { warbandOf } from "./warband.js";
import { isSelected, select as selectUnit, selection,
         selectionLead } from "./orders.js";
import { combatStanceNode } from "./dom.js";
import { trade, tradeFinish, tradeLayout, tradeMove, tradeTotals } from "./trade.js";
import { carriedWeight, carry, carryActor, carryApplyTo, carryCancel, carryDrop,
         carryMixing, carryPlaceBag, carryPlaceSlot, carryTake, carryUse, carrying,
         weightLimit } from "./carry.js";
import { mixing, mixingHides, mixingSlot, mixingTake } from "./craft.js";
import { carryCursorSync } from "./cursors.js";
import { SLOT_TITLES, bagSize, equipFromBag, inventoryWeight,
         requirementMet, unequip } from "./inventory.js";
import { armourOf, orderTalkTo, strengthOf } from "./combat.js";
import { reputationValue } from "./reputation.js";
import { currentCharacteristics } from "./jewels.js";
import { dialog, dialogChoose, dialogClose, dialogJournal,
         dialogOptions } from "./dialog.js";
import { locationName, mapPicture, markerVisible, standAt, startTravel,
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
//: Насколько кнопка «заговорить» уже своего гнезда, в точках экрана.
//: Подогнано на глаз: сперва ужали на десять, потом отпустили вправо на
//: четыре — рисунок у неё свой, и в паковую ширину он не ложится.
const TALK_TRIM = 6;

const keyHeld = { shift: false, ctrl: false };
function keyHeldFrom(event) {
  keyHeld.shift = event.shiftKey;
  keyHeld.ctrl = event.ctrlKey;
}

// РЕЖИМ РАЗГОВОРА — КОСТЫЛЬ ДЛЯ СЕНСОРНОГО ЭКРАНА.
//
// Ctrl в движке — не действие, а ФЛАГ главного цикла (0x8495AC, клавиша
// 0x11, VA 0x438A00:44): с ним щелчок по своему становится «подойти и
// заговорить» вместо «выбрать». На телефоне зажать его нечем, а без него
// закрыты и разговор с самим собой (лечение и починка), и назначение
// спутника на должность.
//
// Поэтому кнопка панели держит тот же флаг взведённым, пока её не отожмут.
// Живёт он в `world`, а не здесь: спрашивают его трое — панель, щелчок по
// миру (input.js) и курсор (cursors.js), — а `cursors.js` ui.js импортировать
// не может, иначе выйдет петля (ui.js тянет его сам).
function ctrlHeld() { return keyHeld.ctrl || world.talkMode === true; }
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

// СКОЛЬКО ЯЧЕЕК ПОМЕЩАЕТСЯ — ПО ПРОЁМУ, А НЕ ПО ДВЕНАДЦАТИ.
//
// В игре их всегда двенадцать, но это не свойство пояса, а следствие
// экрана: при 1024x768 ряд от кромки панели (x=140) до правого края
// (x=1023) вмещает ровно столько шагов по 69. Само гнездо ничем не
// выделено — пояс показывает ТОТ ЖЕ мешок юнита (+0x62, сорок два
// слова), просто лентой, и до остальных ячеек движок листает стрелками.
//
// У нас окно любой формы. На узком двенадцать в проём не лезли, и ряд
// вылезал на панель, — это чинилось и раньше. На широком же места
// ОСТАВАЛОСЬ БОЛЬШЕ, а ряд всё равно обрывался на двенадцатой и дальше
// требовал стрелок впустую. Теперь потолок один — сколько вещей вообще
// может быть в мешке; между ним и проёмом выбирается меньшее.
//
// Ширина ряда считается из этого же числа и потому в окно попадает
// ровно: `arrows + cells*pitch <= arrows + room = ширина вида`.
export function beltCells() {
  const geometry = belt();
  //: `geometry.cells` (двенадцать из exe) остаётся запасом на случай,
  //: когда проём ещё не измерен — до первой раскладки.
  const most = bagSize() || geometry.cells || 12;
  const pitch = geometry.pitch ?? 69;
  const room = (viewNode?.clientWidth ?? 0) / (scale || 1) - beltArrows();
  if (!(room > 0)) return Math.min(geometry.cells ?? 12, most);
  return Math.max(1, Math.min(most, Math.floor(room / pitch)));
}

//: Ниже какой концентрации снадобье считается слабым (VA 0x432303 и
//: 0x432324): «Масло» и класс 93 хотят десять, «Эликсир Мудрости» — шесть.
const WEAK_BELOW = { 87: 10.0, 92: 6.0, 93: 10.0 };

//: Короткие имена полей — таблица 0x462D74, приезжает в паке
//: (rules.inventory.tooltip). Имя несёт ведущий пробел — так печатает игра.
function statShort(field) {
  const stats = hero.data?.rules?.inventory?.tooltip?.stats ?? {};
  return stats[String(field)] ?? ` поле ${field}`;
}

//: Чары для подсказки — СВОИМ ходом по группам слова, а не через свёртку
//: `enchantBonuses`: печать идёт в порядке групп движка (старшая тройка
//: первой: броня, удар, ловкость, сила, выносливость), а объект со
//: числовыми ключами перечисляется по возрастанию и путал порядок.
function enchantParts(word) {
  const set = hero.data?.rules?.jewellery?.enchant;
  if (!set || !word || (word & set.dormant)) return "";
  let out = "";
  for (const { shift, section } of set.groups) {
    const level = (word >> shift) & 0x7;
    if (!level) continue;
    const row = set.table[section + level - 1];
    if (!row) continue;
    // « Сил» «+» «2» — ровно три куска печатника (0x431898…0x4318CF)
    out += `${statShort(row.field)}+${row.value}`;
  }
  return out;
}

// Подсказка предмета — перенос печатника 0x4315A0 ДОСЛОВНО: те же строки
// (сняты из exe, см. docs/_descr_strings*.txt), тот же порядок, та же
// развилка по ВИДУ записи (байт +0x00; в паке он у класса — `kind`).
// Цены и дальности в канонной подсказке НЕТ ВООБЩЕ — они были нашей
// отсебятиной, как и разделитель « · ».
//
// ВЛАДЕЛЬЦА СПРАШИВАЕМ У ВЫЗЫВАЮЩЕГО. Экземплярные поля (износ, чары,
// отрава, счёт стрел) живут картами владельца, а в открытом обмене — его
// складом details; движок читает их из самой записи предмета.
function describe(name, owner = panelUnit()) {
  const item = actorItem(name);
  if (!item) return "";
  const traded = trade.open ? trade.details?.[name] : null;
  const word = traded?.enchant ?? owner?.bagEnchant?.[name] ?? 0;
  const dormant = hero.data?.rules?.jewellery?.enchant?.dormant ?? 0x8000;
  const asleep = Boolean(word & dormant);       // заколдованное = не опознано
  const kind = item.kind ?? (item.ammo ? 12 : null);
  const kg = (grams) => (grams / 1000).toFixed(2);     // «%4.2f» печатника
  // вид отравы — байт +0x02 записи: масло кладёт ноль («, зажигательные»)
  const poisons = hero.data?.rules?.inventory?.tooltip?.poisons ?? [];
  const oiled = Boolean(traded?.oiled ?? owner?.itemOiled?.[name]);
  const poison = traded?.poison ?? owner?.bagPoison?.[name] ?? 0;

  // СНАРЯЖЕНИЕ, виды 0…4: оружие, стрелковое, доспех, шлем, щит.
  if (kind !== null && kind >= 0 && kind <= 4) {
    if (asleep) {
      return kind === 0 ? "Заколдованное оружие"
        : kind === 1 ? "Заколдованное стрелковое оружие"
        : "Заколдованный предмет";
    }
    let out = item.name;
    out += (kind < 2 ? ", урон " : ", броня: ") + item.power;
    // износ: текущий из записи (0 печатается единицей — 0x4315A0), полный
    // — из неё же; у вещи без экземплярных полей оба равны классу
    const full = Math.round(traded?.max ?? owner?.wearMax?.[name]
      ?? item.durability ?? 0);
    const worn = Math.round(traded?.strength ?? owner?.bagStrength?.[name]
      ?? full) || 1;
    out += `, износ ${worn}/${full}`;
    out += `, вес ${kg(item.weight)}`;
    if (kind === 0 && poison) out += `, отравление: ${poison}`;
    if (oiled && poisons[0]) out += poisons[0];
    out += enchantParts(word);
    if (item.requires && item.requirement) {
      out += `, требует: ${statShort(requirementField(item))}:${item.requirement}`;
    }
    return out;
  }

  // УКРАШЕНИЯ, виды 6…8: ожерелье, браслет, кольцо.
  if (kind === 6 || kind === 7 || kind === 8) {
    if (asleep) return "Заколдованный предмет";
    return `${item.name}, вес ${kg(item.weight)}${enchantParts(word)}`;
  }

  // ЗЕЛЬЯ, вид 9: бит «заколдовано» печатник не смотрит вовсе.
  if (kind === 9) {
    let out = item.name;
    if (item.price < 0) {
      const value = (name === mixing.name && typeof mixing.strength === "number")
        ? mixing.strength
        : (traded?.strength ?? owner?.bagStrength?.[name] ?? 0);
      out += `, концентрация ${value.toFixed(2).padStart(5)}`;   // «%5.2f»
      const need = WEAK_BELOW[item.index];
      if (need !== undefined && value < need) out += ", недостаточная концентрация";
    }
    return out + `, вес ${kg(item.weight)}`;
  }

  // СТРЕЛЫ, вид 0x0C: счёт, урон и вес ВСЕЙ пачки.
  if (kind === 12) {
    // печатник обрывает заколдованные стрелы на заголовке (0x431C84:
    // strcat строки 0x45267C и переход в конец) — воспроизводим как есть
    if (asleep) return "Заколдованные стрелы: ";
    const count = traded?.count ?? owner?.bagCount?.[name]
      ?? (owner?.equipment?.ammo === name ? owner?.ammoCount : null) ?? 0;
    let out = `${item.name}${count} шт.`;
    out += `, урон ${item.power}`;
    out += `, вес ${kg(count * item.weight)}`;
    if (poison) out += `, отравление: ${poison}`;
    if (oiled && poisons[0]) out += poisons[0];
    if (item.requires && item.requirement) {
      out += `, требует: ${statShort(requirementField(item))}:${item.requirement}`;
    }
    return out;
  }

  // ПРОЧЕЕ, вид 0x0B (и вещи без вида): имя и вес.
  if (asleep) return "Заколдованный предмет";
  return `${item.name}, вес ${kg(item.weight)}`;
}

//: Номер поля требования. Пак несёт `requires` ИМЕНЕМ («Сила»), печатник —
//: номером в таблицу коротких имён; сводим по полным именам прокачки.
function requirementField(item) {
  const names = hero.data?.rules?.progression?.characteristics?.names ?? [];
  const at = names.indexOf(item.requires);
  if (at >= 0) return at + 1;
  return BONUS_EXTRA_FIELDS[item.requires] ?? 0;
}

//: Поля сверх шести характеристик — как в требованиях классов (0x462D74).
const BONUS_EXTRA_FIELDS = { "Броня": 7, "Удар": 8, "Вера": 9, "Здоровье": 10 };

// ЦВЕТ ЯЧЕЙКИ ПОД ВЕЩЬЮ — перенос FUN_0042FF20. КРАСИТСЯ ПОДЛОЖКА, А НЕ
// ЗНАЧОК: разбор мешка (VA 0x42BFE8, обмен) и пояс (VA 0x43096C) рисуют
// спрайт-ячейку перекрашенной палитрой, а значок кладут вторым проходом
// РОДНЫМИ цветами, по центру, без масштаба. Прежний комментарий здесь
// приписывал краску значку — это было неверное чтение: `0x42FF20`
// перекрашивает палитру ЯЧЕЙКИ (аргумент — её палитра, DAT_006B26A4).
// Порядок проверок такой:
//
//     не может надеть (FUN_00418648)      -> FUN_0044293F(0x18, 0, 0)  красная
//     опознана:
//         байт +1 отрицателен И слово чар (маска 0x7FFF) ноль -> без краски
//         иначе                            -> FUN_0044293F(0, 0x0C, 0)  зелёная
//     не опознана (вещь[+0x0F] бит 0x80)   -> FUN_0044293F(0x0F, 0x0F, 0) жёлтая
//
// ЖЁЛТАЯ В ОБЫЧНОЙ ИГРЕ НЕ ПОКАЗЫВАЕТСЯ, и это не наша недоделка. Тело
// `FUN_00418648` целиком лежит под `if ((вещь[+0x0F] & 0x80) == 0)` — то есть
// неопознанная вещь не проходит саму проверку «можно ли надеть» и красится
// КРАСНОЙ раньше, чем разбор дойдёт до жёлтой ветки. Открыть её может только
// флаг `0x849620`, который снимает проверку целиком. Мы повторяем это как
// есть: у нас `requirementMet` тоже отвергает неопознанное первой строкой.
//
// Сами крашеные подложки испечены паком по таблицам движка (0x43C228
// строит ряды с шагом 0.01; краска — ряд 0x18 красного канала, зелень —
// ряд 0x0C зелёного) — `interface.cell_unusable` и `interface.cell_special`.
function itemTint(name, owner = panelUnit()) {
  if (!name || !owner) return null;
  //: Слово чар — ИЗ САМОЙ ВЕЩИ (в обмене — из склада details), и оно же
  //: уходит в проверку «можно ли надеть»: иначе заколдованный товар на
  //: прилавке проходил её по пустому слову ПОКУПАТЕЛЯ и терял красную.
  const traded = trade.open ? trade.details?.[name] : null;
  const word = traded?.enchant ?? owner.bagEnchant?.[name] ?? 0;
  if (!requirementMet(name, owner, word)) return "unusable";
  const dormant = world.map?.hero?.rules?.jewellery?.enchant?.dormant ?? 0x8000;
  if (word & dormant) return "unknown";
  return word ? "special" : null;
}

function iconNode(name, owner = panelUnit(), k = scale) {
  const icon = actorItem(name)?.icon;
  if (!icon) return null;
  const image = document.createElement("img");
  image.src = contentUrl(icon.path);
  image.alt = name;
  // ЗНАЧОК БОЛЬШЕ НЕ КРАСИТСЯ И НЕ ОБВОДИТСЯ: движок рисует его родными
  // цветами поверх КРАШЕНОЙ ПОДЛОЖКИ ячейки (см. itemTint) — краску несёт
  // сама ячейка. И рисует он его 1:1 В МАСШТАБЕ ИГРЫ, по центру бокса
  // ячейки (0x42BFE8/0x43096C: x + (70-ширина)/2, y + (71-высота)/2, без
  // масштаба) — потому размер значка задаётся здесь, множителем интерфейса
  // ВЫЗЫВАЮЩЕГО (у пояса, обмена и окна снаряжения он свой), а не «своим
  // размером» картинки, который у прежней вёрстки не рос вместе с экраном.
  if (k > 0 && k !== 1) {
    image.style.width = `${Math.round(icon.width * k)}px`;
    image.style.height = `${Math.round(icon.height * k)}px`;
  }
  return image;
}

//: Мерки пары касаний — те же, что на карте (input.js): срок и допуск по
//: месту, потому что пальцем во второй раз в ту же точку не попадают.
const TAP_GAP_MS = 400;
const TAP_SLIP = 24;

function cell({ x, y, width, height, name = null, title = "", art = null,
                onClick = null, onDoubleClick = null, onDrop = null,
                className = "", iconScale = null }) {
  const node = document.createElement("div");
  node.className = `ui-cell ${className}`.trim();
  node.style.left = `${x}px`;
  node.style.top = `${y}px`;
  node.style.width = `${width}px`;
  node.style.height = `${height}px`;
  node.title = name ? describe(name) : title;
  // Подложка ячейки — спрайт игры (пустая ячейка, кнопка, овал оружия).
  // ЯЧЕЙКА ПОД ВЕЩЬЮ КРАСИТСЯ ЦЕЛИКОМ, как её рисует движок (см. itemTint):
  // подложке с вещью, которую нельзя надеть, пак даёт красный вариант
  // спрайта, вещи с чарами — зелёный. Красится только сама ячейка (спрайт
  // 17) — кнопок и овалов окна снаряжения краска не касается, их и движок
  // не красит (0x42FF20 зовут только разбор мешка и пояс).
  let paint = art;
  if (name && art && art === info()?.cell) {
    const tint = itemTint(name);
    paint = tint === "unusable" ? info()?.cell_unusable ?? art
      : tint === "special" ? info()?.cell_special ?? art
      : art;
  }
  if (paint) {
    node.style.backgroundImage = `url("${contentUrl(paint.path)}")`;
    node.style.backgroundSize = "100% 100%";
    node.style.backgroundRepeat = "no-repeat";
  }
  const icon = name && iconNode(name, undefined, iconScale ?? scale);
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
  // ЗАГОВОРИТЬ — вместо «атаковать» (см. renderPanel). Кнопка не делает
  // ничего сама: она держит взведённым тот же флаг, что и зажатый Ctrl, и
  // пока горит, щелчок по себе или по своему открывает разговор, а не
  // выбирает. Второе нажатие отпускает.
  talk_mode: {
    active: () => world.talkMode === true,
    press: () => {
      world.talkMode = !world.talkMode;
      status(world.talkMode
        ? "Разговор: щёлкни по себе или по своему"
        : "Разговор выключен");
    },
  },
  // «Все ко мне» — движок переводит весь отряд в режим 0x30, то есть
  // «следовать за вожаком» (VA 0x420BFC), и ЭТИМ ЖЕ выводит отряд из боя:
  //
  //     *(отряд_игрока + 0x1D) = 0;          // война снята
  //     каждому живому бойцу: +0x16 = 0x30   // весь байт, приказ стёрт
  //                           +0x01 = 0xFF   // путь очищен
  //                           +0x19 &= 0xBF  // бит «занят» снят
  //
  // Это и есть канонный способ увести отряд из драки: просто приказ
  // «идти» войну не снимает — дошедший юнит вернётся в бой рассудком.
  // Порт держит кнопку переключателем (игрок настоял: отряд без зова не
  // бродит), но начинка при включении — движковая.
  call_party: {
    press: () => {
      const mates = (world.units ?? []).filter((unit) => unit.ally && unit.alive);
      if (!mates.length) { status("Отряда пока нет"); return; }
      const bit = orderModes().follow;
      const following = mates.every((mate) => (mate.orderByte ?? 0) & bit);
      if (!following) {
        // Зов: война отряда игрока гаснет (0x420BFC, третья строка тела).
        const ours = warbandOf(hero);
        if (ours) ours.fighting = false;
      }
      for (const mate of mates) {
        if (!following) {
          // Весь байт целиком, как пишет движок: приказ и цель стёрты.
          orderClear(mate);
          // …и РУКА ИГРОКА ОТПУСКАЕТ БОЙЦА (+0x19 &= 0xBF). Раньше это делал
          // сам orderClear, но там бит стоял не в своём байте; теперь снимаем
          // тут, ровно как движок, — иначе позванный спутник остался бы
          // «занятым» и за вожаком не пошёл.
          mate.busy = false;
          mate.orderByte = 0x30;
          mate.target = null;
          mate.goal = null;
          mate.goalTarget = null;
        } else {
          setMode(mate, bit, false);
        }
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
  const picture = mapPicture();
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
  const picture = mapPicture();
  if (!rules || !picture) return null;
  // УГОЛ УЖЕ В КООРДИНАТАХ КАРТИНКИ. Движок держит его экранным (0xA7,
  // 0x19), потому что рисует карту в окне мира и считает от левого края
  // ЭКРАНА; пересчёт на ширину панели делает пак — knyaz2/content/worldmap.py,
  // а старый пак поправляет `worldMapSetup`. Здесь вычитать нечего: у
  // нарисованной карты панели нет вовсе.
  return {
    picture,
    x0: rules.origin[0],
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
  const picture = mapPicture();
  if (!mapOpen || !picture) { mapNode.hidden = true; return; }
  const view = viewNode.getBoundingClientRect();
  const game = gameNode.getBoundingClientRect();
  // ВПИСЫВАЕМ В ПРОЁМ ПО ОБЕИМ ОСЯМ И СТАВИМ ПО ЦЕНТРУ.
  //
  // Канонная карта ровно в размер проёма (884x709), и для неё это по-прежнему
  // общий масштаб игры — вид не меняется. Нарисованная другой формы, и предела
  // по высоте тут раньше не было вовсе: на высоком узком окне она вылезала
  // вниз за рамку, а прижатая к левому верхнему углу выглядела съехавшей.
  const k = Math.min(scale, view.width / picture.width,
                     view.height / picture.height);
  const width = Math.round(picture.width * k);
  const height = Math.round(picture.height * k);
  mapNode.hidden = false;
  mapNode.style.left =
    `${Math.round(view.left - game.left + (view.width - width) / 2)}px`;
  mapNode.style.top =
    `${Math.round(view.top - game.top + (view.height - height) / 2)}px`;
  mapNode.style.width = `${width}px`;
  mapNode.style.height = `${height}px`;
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
  // Сверяем ОБЕ стороны: карты разной высоты при одной ширине холст бы не
  // переразметил, и туман лёг бы по чужой сетке.
  if (mapCanvas.width !== picture.width || mapCanvas.height !== picture.height) {
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
    //
    // Точка отряда — В КООРДИНАТАХ КАРТИНКИ: её считает `centre` по тому же
    // углу сетки, что и всё здесь. Ширину панели тут вычитали, пока угол
    // приходил экранным; теперь это увело бы один только щит отряда влево,
    // и он разошёлся бы со своей же клеткой.
    const offset = rules.player_offset ?? -7;
    ctx.drawImage(player, worldMap.x + offset, worldMap.y + offset);
  }
}

//: Точка события в координатах картинки карты.
function mapPoint(event) {
  const rect = mapNode.getBoundingClientRect();
  const picture = mapPicture();
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
  world.onTravel?.(ownGameLocation(number));
}

// ЗНАЧОК ВЕДЁТ В СВОЮ ИГРУ.
//
// Под локацию в клетке отведён один байт, и на месте Чёрного Бора стоит
// донорский: он объявил `"replaces": 19` и занял клетку канонного. Значок
// при этом канонный — клетка лежит на канонной части картинки. Оттого
// канонный герой со значка приходил в чужую деревню, где нет Велиславны и
// стоит Ярополк, и тестер записал это как «не Кровь Титанов канон».
//
// Байт остаётся один, а выбор делает клиент — то же правило «дома читаешь
// свой мир», что уже применено к деревням (world.js) и отрядам. Таблицу
// подмены печёт сборщик (locations.canon_instead).
//
// Донорского героя не трогаем: ему в клетке стоит ровно его карта.
function ownGameLocation(number) {
  const свои = worldMap.rules?.canon_instead;
  const канонный = !hero.game || hero.game === "canon";
  const вместо = свои?.[String(number)];
  const итог = канонный && вместо ? вместо : number;
  status(`Входим: ${locationName(итог)}`);
  return итог;
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
  //
  // Обе точки — В КООРДИНАТАХ КАРТИНКИ: и щелчок, и место отряда. Ширину
  // панели тут прибавляли, пока место отряда было экранным; с ней «войти»
  // не срабатывало бы вовсе — курсор не может отстоять от отряда меньше чем
  // на семь точек и одновременно на сто сорок.
  if (Math.abs(worldMap.x - point.x) < ENTER_RADIUS &&
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
  // ЦЕЛЬ БЕРЁТСЯ КАК ЕСТЬ. Точка щелчка и место отряда теперь в одних и тех
  // же координатах — картинки; ширину панели тут прибавляли, пока сетка
  // задавалась экранным углом, и без этого цель уезжала влево. Теперь та же
  // прибавка увела бы отряд вправо.
  const speed = partySpeed();
  // Плывём или идём — решает корабельное право (0x4277F4: при 0x84960C ==
  // −1 маска хода берёт бит моря, а не суши).
  if (!startTravelTo(point.x, point.y, { speed, ship: worldMap.ship === -1 })) return;
  status(worldMap.ship === -1 ? "В плавании" : "В пути");
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
function portraitPath(data, face, game = null) {
  const own = data.portrait?.path;
  if (!own) return null;
  const base = data.portrait_base ?? 261;
  // ЛИЦО ДОНОРА — ЕГО ПОРТРЕТ. Номер спрайта у обеих игр один («лицо +
  // 261»), но лица под ним разные: за Иззарка (лицо 0) панель показывала
  // нашего Ратибора, за Гильдис (лицо 3) — Хельгу. Выпечка кладёт его
  // портреты под ключом `legend:<лицо>` и файлом `legend_ui_N.png`.
  const ready = game ? data.portraits?.[`${game}:${face}`] : null;
  if (ready?.path) return ready.path;
  const name = `${game ? `${game}_` : ""}ui_${base + face}.png`;
  return own.replace(/(?:legend_)?ui_\d+\.png$/, name);
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
  const game = actor?.game ?? null;
  const source = (face == null && !game)
    ? data.portrait
    : { path: portraitPath(data, face ?? 0, game) };
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
      // МЕСТО «АТАКОВАТЬ» ОТДАНО «ЗАГОВОРИТЬ» — И ЭТО НАШЕ ОТСТУПЛЕНИЕ.
      //
      // Кнопка атаки канонная: и спрайт (`assets/icons/ui_7.png`), и подпись
      // «Атаковать», и клавиша A приезжают в паке из данных самой игры. Мы
      // забираем у неё ГНЕЗДО ПАНЕЛИ, потому что сенсорному экрану нужнее
      // то, чего у него нет вовсе: держатель Ctrl. Атака при этом никуда не
      // девается — клавиша A по-прежнему зовёт её (input.js, PANEL_KEYS), а
      // на телефоне клавиатуры нет и кнопка там всё равно была бы вторым
      // способом сделать то же, что и щелчок по врагу.
      //
      // Гнездо, размер и место остаются паковыми; меняются действие,
      // подпись и картинка.
      const id = button?.id === "attack" ? "talk_mode" : button?.id;
      const action = id && ACTIONS[id];
      // Две первые кнопки меняют картинку: первая по оружию, вторая по
      // стойке. Предметы в панель не кладутся — гнёзд под них там нет.
      let art = button;
      if (id === "weapon_mode") art = weaponFace() ?? button;
      if (id === "toggle_weapon") {
        art = data.stance_faces?.[hero.stance === "combat" ? "combat" : "peace"] ?? button;
      }
      //: У «заговорить» картинки в игровых ресурсах нет — как и у кнопки
      //: меню, она наша и лежит рядом с клиентом, а не в паке.
      const ours = id === "talk_mode";
      //: НАША КНОПКА УЖЕ ГНЕЗДА (TALK_TRIM). Гнездо паковое, 67 единиц
      //: панели, а рисунок у неё свой, 92x83, и во всю ширину он вылезал за
      //: соседей по столбцу. Левый край на месте, ужимается правый. Точки
      //: экранные — их и видит игрок.
      const box = ours
        ? { ...geometry, width: Math.max(1, geometry.width - TALK_TRIM) }
        : geometry;
      const node = cell({
        ...box,
        title: ours ? "Заговорить: то же, что зажатый Ctrl"
          : button ? `${button.title}${button.key ? ` (${button.key})` : ""}` : "",
        art: ours ? null : art,
        className: action?.active?.() ? "active" : "",
        onClick: action?.press ?? null,
      });
      if (ours) {
        node.style.backgroundImage = 'url("/speak-button.png")';
        node.style.backgroundSize = "100% 100%";
        node.style.backgroundRepeat = "no-repeat";
        node.style.backgroundOrigin = "border-box";
      }
      nodes.push(node);
    } else if (rect.name === "portrait") {
      // Портрет игрока — такая же кнопка выбора, как у спутников: щелчок
      // по нему делает главного единственным выбранным (VA 0x421690 ведёт
      // и портрет, и щелчок по юниту в одну и ту же FUN_0041ECB8).
      const node = cell({ ...geometry, art: data.portrait,
                          className: isSelected(hero) ? "active" : "",
                          // Порядок движковый: сперва прозвище, потом уровень
                          // и здоровье — и здоровье в той же шкале, что лист
                          // персонажа, то есть 100, а не 1600.
                          // РЕПУТАЦИЯ — ТОЛЬКО У ИГРОКА, и это правило
                          // донора, а не наше удобство: его панель
                          // (VA 0x42DF7E) печатает её лишь тогда, когда
                          // показанный юнит совпал с записью игрока.
                          title: [heroEpithet(), `уровень ${hero.level ?? 1}`,
                                  `репутация ${reputationValue(hero)}`,
                                  `здоровье ${healthShown(hero.health, healthDivisor())}`
                                  + ` из ${healthShown(hero.maxHealth ?? 1600, healthDivisor())}`]
                            .filter(Boolean).join(", "),
                          // С ВЕЩЬЮ В РУКЕ портрет не выбирает, а применяет
                          // (VA 0x421690:292 -> 0x41F55C): для того, чья
                          // панель открыта, это «использовать на нём».
                          // CTRL ПО СВОЕМУ ПОРТРЕТУ — РАЗГОВОР С САМИМ
                          // СОБОЙ. Ветка портрета в движке (VA 0x421690:349)
                          // игрока не отсекает: место 0 таблицы панели — он
                          // сам, и Ctrl пишет ему приказ 0x22 со своим же
                          // номером. Через этот разговор чинят снаряжение и
                          // лечат отряд (HERO.QST, разговор 138).
                          onClick: () => {
                            if (carrying()) {
                              if (carryActor() === hero) carryApplyTo(hero);
                              else carryPlaceBag(-1, hero);
                            } else if (!(ctrlHeld() && orderTalkTo(hero))) {
                              selectUnit(hero, keyHeld.shift);
                            }
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
      //
      // И ТОЛЬКО СВОЙ (`ally`): слоты юнитов уникальны лишь в пределах
      // одной игры, а донорские карты несут свои номера — без фильтра
      // портрет дружинника цеплялся к чужому жителю карты с тем же слотом,
      // и клик/передача вещи уходили не тому.
      const mate = member
        ? (world.units ?? []).find((unit) =>
            unit.ally && unit.slot === member.index) ?? null
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
          } else if (!(ctrlHeld() && orderTalkTo(mate))) {
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
        //: ИГРА СПУТНИКА — ТОЖЕ В ПОРТРЕТ. Здесь собирался объект из одного
        //: здоровья, и метка игры до `portraitFace` не доходила: спутник
        //: донора получал канонное лицо под своим номером, как это было у
        //: героя (лицо 2 показывалось Эйнаром).
        const face = portraitFace(data, { health: mate?.health ?? member.health,
                                          maxHealth: member.health,
                                          game: mate?.game ?? member.game ?? null },
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
      name, title: `ячейка ${index + 1}`, iconScale: k,
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
      iconScale: k,
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
        name, title: name ?? `ряд ${column}`, iconScale: k,
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
    node.style.transform = align === "right" ? "translateX(-100%)"
      : align === "center" ? "translateX(-50%)" : "none";
    // ШРИФТ МАСШТАБИРУЕТСЯ ВМЕСТЕ С ОКНОМ, без нижнего пола. Пол в девять
    // точек ломал пропорцию: координаты сжимались с k, а буквы — нет, и на
    // узком окне соседние числа и подписи налезали друг на друга. Движок
    // растровый и не масштабируется вовсе, поэтому «доля текста в экране»
    // и есть канон — как у экрана создания (styles.css, cqw-шрифт).
    node.style.fontSize = `${15 * k}px`;
    nodes.push(node);
    return node;
  };

  // ПЕРВЫЕ ПЯТЬ ПОДПИСЕЙ — ЛЕВЫМ КРАЕМ, остальные правым. Это не свойство
  // данных, а правило рендера движка: цикл 0x42AD0E рисует пять записей
  // таблицы 0x46140C без вычета ширины строки, и лишь со следующей записи
  // (0x42AD43) x уменьшается на ширину (0x441EB7). Пятёрка — «Уровень»,
  // «Опыт», «Свободный опыт», «Следующий уровень» и шапка «базовая сейчас
  // поднять»; ровнять их правым краем значит уложить «Опыт» на цифру
  // уровня, а шапку — под рамку фона.
  //
  // ШАПКА — СЛОВАМИ ПО СТОЛБЦАМ. В движке это одна растровая строка, чьи
  // пробелы подогнаны так, что слова ложатся над своими столбцами. Наш
  // шрифт другой ширины, и целой строкой «поднять» повисало над столбцом
  // «сейчас». Раскладываем сами: «базовая» и «сейчас» правым краем по
  // столбцам чисел, «поднять» — серединой над столбцом «+» (полширины
  // плюса — четыре точки движка).
  const columns = (data.numbers ?? [])
    .find((number) => number.field === "characteristic");
  (data.labels ?? []).forEach((label, index) => {
    const words = label.text.trim().split(/\s+/);
    if (index === 4 && columns && words.length === 3) {
      put(words[0], columns.x, label.y);
      put(words[1], columns.current_x, label.y);
      put(words[2], columns.raise_x + 4, label.y, { align: "center" });
      return;
    }
    put(label.text, label.x, label.y, { align: index < 5 ? "left" : "right" });
  });

  // ВЕСЬ экран — про одного юнита: первого выбранного (0x849514). Ему же
  // уходят и щелчки «поднять»: движок зовёт 0x4131FC/0x413268 с тем же
  // указателем, и свободный опыт у каждого юнита свой (+0x48).
  const who = panelUnit();

  // ТРИ СТРОКИ-ТУМБЛЕРА (VA 0x42A8F4:126-180, щелчки — зоны 0x39…0x3F в
  // 0x421690). Живут на битах байта состояния +0x19 показанного юнита:
  //
  //     «Выбор оружия»   Запрещен/Разрешен      бит 0x20 (взведён = запрещён:
  //                      юнит сам не переключается между рукой и метательным —
  //                      0x410A08:67 и 0x411F28 пробуют выстрел только при
  //                      +0xEE == 1 ИЛИ снятом бите)
  //     «Защищать героя» Да/Нет                 бит 0x10 (0x410010:46 — цель
  //                      выбирается среди бьющих ВОЖАКА отряда)
  //     «Лечебные смеси» Никогда/Здр<50/Здр<75  биты 0x01/0x02 — тумблер
  //                      автопитья бальзама (0x414DF0, пороги 800/1200 сырых)
  //
  // Активное значение движок печатает второй палитрой (0x60054C); тексты и
  // координаты значений — таблица указателей 0x45D3F4…0x45D40C. Подписи
  // строк уже пришли в общем списке labels; здесь — значения и щелчки.
  const toggles = data.toggles ?? [
    { y: 380, field: "weaponLock", values: [
      { text: "Запрещен", x: 0x145, value: true },
      { text: "Разрешен", x: 0x1C7, value: false }] },
    { y: 400, field: "defendLeader", values: [
      { text: "Да", x: 0x145, value: true },
      { text: "Нет", x: 0x1C7, value: false }] },
    { y: 420, field: "healTrigger", values: [
      { text: "Никогда", x: 0x145, value: 0 },
      { text: "Здр<50", x: 0x1A4, value: 1 },
      { text: "Здр<75", x: 0x1F9, value: 2 }] },
  ];
  for (const row of toggles) {
    for (const option of row.values ?? []) {
      const current = row.field === "healTrigger"
        ? (who.healTrigger ?? 0) : Boolean(who[row.field]);
      const active = current === option.value;
      const mark = put(option.text, option.x, row.y,
                       { align: "left", className: active ? "toggle on" : "toggle" });
      mark.title = "переключить";
      mark.addEventListener("click", () => {
        who[row.field] = option.value;
        refresh(); onChange();
      });
    }
  }
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
// входит дважды.
//
// ЭКРАН ЗОВЁТ ПОЛНЫЙ РАСЧЁТ СИЛЫ, а не поле класса: 0x41A7D0 — это
// power оружия ПЛЮС член от текущей Силы и здоровья, ТРУНК(Сила × 0.04 ×
// здоровье × 0.0625), а пустой рукой — тот же член с 0.02 (ветки сняты
// дизасмом, см. COMBAT_SPEC §9в — «съеденное Ghidra FP-выражение» из
// SKILLS_AUDIT В3 закрыто). Здесь стояло голое power: прокачка Силы
// МЕНЯЛА урон в бою, но цифра «Удар» на экране не двигалась — оттого и
// казалось, что Сила не работает; а кулак показывал ноль. Теперь экран
// считает тем же strengthOf, что и бой.
function strikeDisplay(who) {
  const ranged = Boolean(who.rangedMode) && Boolean(who.equipment?.ranged) &&
    Boolean(who.equipment?.ammo);
  if (ranged) return Math.max(0, strengthOf(who, "main"));
  // Ближний удар считаем с погашенным режимом стрельбы: strengthOf при
  // взведённом +0xEE ушёл бы в стрелковую ветку, а движок здесь зовёт
  // именно ближний расчёт (нет боеприпаса — нет стрелкового удара).
  const melee = who.rangedMode ? { ...who, rangedMode: false } : who;
  let strike = strengthOf(melee, "main");
  const off = actorItem(who.equipment?.off_hand);
  if (off && off.kind === 0) strike += strengthOf(melee, "off");
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
