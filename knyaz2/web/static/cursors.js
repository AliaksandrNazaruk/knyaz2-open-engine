// Курсоры.
//
// В движке их девять картинок 32x32, они лежат в GRAPH.RES сразу за
// палитрами (VA 0x43C228 раскладывает указатели в 0x840BB8), и остриё у
// всех — левый верхний угол:
//
//     0 бить   1 нельзя   2 обычный   3 говорить   4 поджечь
//     5 взять  6 на глобальную карту  7 на другую карту  8 несём вещь
//
// Какой показать, решает VA 0x428B88 по тому, что под мышью, и порядок
// проверок там жёсткий — сначала поджог, потом юниты, потом вещи, потом
// клетка. Тот же порядок и здесь.
import { world } from "./world.js";
import { contentUrl } from "./content.js";
import { hero, heroCellAt, heroFree } from "./hero.js";
import { unitAt } from "./units.js";
import { lootNear } from "./loot.js";
import { furnitureAt } from "./furniture.js";
import { exitAt } from "./exits.js";
import { buildingAtCell } from "./buildings.js";
import { carrying } from "./carry.js";
import { hasTalk } from "./dialog.js";
import { actorItem, isBeast } from "./actor.js";
import { selection } from "./orders.js";
import { officialRole } from "./village.js";
import { warbandOf } from "./warband.js";

function rules() { return world.map?.interface?.cursors ?? null; }


//: БОЕВАЯ СТОЙКА — бит 0x04 байта unit+0x19 (heroes.py STANCE_BIT). Именно
//: она, а не «идёт ли бой», решает, покажется ли меч: движок перебирает
//: СПИСОК ВЫБОРА и ищет в нём хоть одного с этим битом (VA 0x428B88).
function drawnWeapon(unit) { return unit?.stance === "combat"; }

function selectionHasWeaponOut() {
  for (const unit of selection) {
    if (!unit || unit.alive === false) continue;
    if (drawnWeapon(unit)) return true;
  }
  return drawnWeapon(hero);
}

// Какой курсор просится в этой точке мира. Порядок проверок — из движка
// (VA 0x428B88), и он жёсткий: поджог, куча, юнит, клетка.
export function cursorAt(x, y) {
  const set = rules();
  if (!set) return null;
  const kind = set.kind;

  // Поджог. Движок смотрит постройку под мышью (её байт +0x22 бит 0x01) и
  // перебирает СПИСОК ВЫБОРА: нужен лучник с вынутым оружием, метательным,
  // боеприпасом и намасленной стрелой.
  //: Признака +0x22 у построек в паке пока нет, поэтому здесь стоит любая
  //: постройка под мышью — это единственное, чего тут не хватает до канона.
  {
    const cell = heroCellAt(x, y);
    if (cell && buildingAtCell(cell.row, cell.col)) {
      for (const unit of [...selection, hero]) {
        if (!unit || unit.alive === false || !drawnWeapon(unit)) continue;
        if (unit.itemOiled?.[unit.equipment?.ammo] && unit.rangedMode &&
            unit.equipment?.ranged && unit.equipment?.ammo) return kind.burn;
      }
    }
  }

  // Несём вещь — движок в этом режиме рисует не курсор, а иконку самой
  // вещи (VA 0x42DDA0), поэтому в разборе 0x428B88 её и нет.
  if (carrying()) return kind.carry;

  // Куча под мышью — рука. Лежачего движок разбирает ниже, вместе с живыми.
  if (lootNear(x, y)) return kind.take;

  const unit = unitAt(x, y, true);
  if (unit) {
    // ЛЕЖАЧИЙ. С ним ещё можно заговорить, если его номер разговора меньше
    // восьми и мы не с оружием наголо; иначе его обыскивают.
    if (unit.alive === false) {
      const number = unit.dialogNumber ?? (hasTalk(unit) ? 0 : 0xFF);
      return (number < 8 && !drawnWeapon(hero)) ? kind.talk : kind.take;
    }
    // СВОЙ — обычный курсор.
    if (unit.ally || (unit.side ?? 0) === (hero.side ?? 0)) return kind.normal;
    // ЧУЖОЙ. Меч показывается, только когда в выборе есть кто-то с вынутым
    // оружием — «идёт ли бой» тут ни при чём.
    if (selectionHasWeaponOut()) return kind.attack;
    // Оружие убрано: заговорить можно лишь с тем, у кого есть разговор и кто
    // сам не стоит с оружием (тварь этой оговорки не знает — у неё оружия
    // нет вовсе). Всё прочее — перечёркнутый курсор.
    if (!hasTalk(unit)) return kind.forbidden;
    if (drawnWeapon(unit) && !isBeast(unit)) return kind.forbidden;
    return kind.talk;
  }

  // СУНДУК ИЛИ БОЧКА — тот же курсор «взять», что и у кучи на земле.
  //
  // В разборе движка контейнер стоит ТРЕТЬИМ, сразу за юнитом и до клетки:
  //
  //     if (куча == 0) { if (юнит == 0) { if (контейнер == 0) ...клетка...
  //                                       else курсор = 5; }
  //                      else ...юниты... }
  //     else курсор = 5;                                  // VA 0x428B88:44-88
  //
  // Никаких оговорок у этой ветки нет: под мышью гнездо с кучей — значит
  // «взять». Без неё курсор доходил до разбора клетки, а клетка у сундука
  // непроходима (он стоит у стены), и выходил перечёркнутый.
  if (furnitureAt(x, y)) return kind.take;

  // КЛЕТКА. Движок смотрит её младшие 12 бит: там либо номер стоящего на
  // ней юнита, либо 0xFFF «глухая». Не ноль — перечёркнутый курсор, и
  // ПОСТРОЙКИ к этому отношения не имеют: их биты лежат выше. Раньше здесь
  // стояла наша выдумка «под мышью постройка — значит нельзя», из-за неё
  // перечёркнутый курсор и висел над входом в дом.
  const cell = heroCellAt(x, y);
  if (!cell) return kind.normal;
  if (!heroFree(cell.row, cell.col)) return kind.forbidden;

  // Клетка перехода — бит 0x1000 её слова. Куда ведёт, говорит запись
  // выхода: −1 уводит на глобальную карту, −2 курсор не меняет.
  const door = exitAt(x, y);
  if (door) {
    if (door.to_map === set.exit.special) return kind.normal;
    return door.to_map === set.exit.leave ? kind.world_map : kind.travel;
  }
  return kind.normal;
}

// ПОДПИСЬ ПОД КУРСОРОМ — перенос FUN_00420E88, разбора «что там под мышью».
// Главный цикл зовёт его каждый кадр (VA 0x438A00), и порядок проверок такой:
//
//     юнит (живой и не в предсмертной позе)  -> табличка с именем
//     контейнер                              -> «Здесь что-то хранится»
//     несомая вещь                           -> «Что-то лежит на земле»
//     клетка перехода                        -> куда он ведёт
//
// Сама табличка юнита — FUN_00432A44, и собирается она так:
//
//     имя (FUN_0043000C: у твари по породе, у человека роль плюс имя)
//     СВОЙ, но не игрок      -> «, воин дружины»
//     ЧУЖОЙ с должностью     -> её название из 0x45FAE0
//     всегда                 -> «, Уров:<N>, Здор:<здоровье / 16>»
//     +0x52 не ноль          -> «, отравлен»
//     отряд поднял бит войны -> « враг»
//
// Здоровье именно ДЕЛИТСЯ НА ШЕСТНАДЦАТЬ (VA 0x42FBF0): 1600 в записи — это
// сотня в табличке. Ненулевое здоровье, обратившееся в ноль, показывается
// единицей.
const HEALTH_SCALE = 16;

//: ИМЕНИ ГЕРОЯ В ПАКЕ ПОКА НЕТ. В движке оно берётся из таблицы 0x46188C по
//: байту +0xF0 записи (у Ратибора это 35), а у нас в запись героя оно не
//: попадает вовсе — панель тоже показывает подпись, начинающуюся с запятой.
//: До правки выпечки подставляем строку выбора героя: она из самой игры и
//: называет его верно, хоть и длинно.
function heroName() {
  const starts = world.map?.hero?.starts ?? [];
  const own = world.map?.hero?.template?.world ?? 0;
  return starts.find((start) => start.world === Number(own))?.name ?? null;
}

// ПОДПИСЬ ПОД КУРСОРОМ — перенос FUN_00432A44, ветка в ветку:
//
//     имя (FUN_0043000C)
//     если НЕ зверь (+0x1A & 0x40 == 0):
//         своя сторона:  игрок -> его звание (0x42FDC0), прочие -> «, воин дружины»
//                        затем «Уров:N, Здор:M» (0x42FBF0)
//                        и если +0x52 != 0 -> «, отравлен»
//         чужая сторона: должность деревни (0x415190), если есть
//                        затем «Уров:N, Здор:M»
//                        и если отряд[+0x1E] & 1 -> « враг»
//     зверь с породой < 0x54: только имя и «Уров:N, Здор:M»
//     зверь с породой >= 0x54: ОДНО ИМЯ
//
// Строки вынуты из exe: 0x452792 «, воин дружины», 0x4527A1 «, отравлен»,
// 0x4527AC « враг».
//
// Что здесь было не так: отрава сверялась с полем `poisoned`, которого у
// юнита нет вовсе (в записи это `poison`, число +0x52), — то есть не
// показывалась НИКОГДА; чужому не хватало пометки «враг»; должность бралась
// из поля пака, а её надо выводить из должностей поселения (0x415190); и
// крупные твари получали уровень со здоровьем, хотя движок им их не даёт.
const BEAST_PLATE_BELOW = 0x54;

function unitCaption(unit) {
  const parts = [unit.name ?? (unit === hero ? heroName() : null) ?? "?"];
  const breed = (unit.breed ?? 0) & 0x7F;
  if (isBeast(unit)) {
    if (breed >= BEAST_PLATE_BELOW) return parts[0];
  } else if (unit === hero) {
    //: У самого игрока движок вместо «воина дружины» подставляет строку
    //: его звания (FUN_0042FDC0) — её в паке пока нет, поэтому молчим.
  } else if (unit.ally || (unit.side ?? 0) === (hero.side ?? 0)) {
    parts.push("воин дружины");
  } else {
    const role = officialRole(unit);
    const names = world.map?.hero?.rules?.roles ?? null;
    if (role && names?.[String(role)]) parts.push(names[String(role)]);
  }
  const health = Math.max(
    unit.health ? 1 : 0,
    Math.trunc((unit.health ?? 0) / HEALTH_SCALE));
  parts.push(`Уров:${unit.level ?? 1}`, `Здор:${health}`);
  const свой = unit === hero || unit.ally || (unit.side ?? 0) === (hero.side ?? 0);
  if (свой) {
    //: Отрава — только у своих: у чужого движок на этом месте печатает «враг».
    if (unit.poison) parts.push("отравлен");
    return parts.join(", ");
  }
  //: Бит 0x01 байта +0x1E записи отряда — «этот отряд воюет с игроком».
  const band = warbandOf(unit);
  const враг = Boolean(band?.fighting) || Boolean((band?.warFlags ?? 0) & 1);
  return parts.join(", ") + (враг ? " враг" : "");
}

export function hintAt(x, y) {
  const texts = world.map?.hero?.rules?.hints ?? null;
  const unit = unitAt(x, y, true);
  if (unit && unit.alive !== false) return unitCaption(unit);
  if (furnitureAt(x, y)) return texts?.container ?? "Здесь что-то хранится";
  if (lootNear(x, y)) return texts?.ground ?? "Что-то лежит на земле";
  const door = exitAt(x, y);
  if (door) {
    if (door.to_map === -1) return texts?.world_map ?? "Выход на карту Лесной страны";
    if (door.to_map === -2) return texts?.ship ?? "Посадка на корабль";
    if (door.to_map < 0) return texts?.locked ?? "Порог у запертой двери";
    return texts?.transition ?? "Место перехода";
  }
  return null;
}

//: Что уже стоит, чтобы не переписывать стиль на каждом движении мыши.
let shown = null;

// Поставить курсор на холст. Картинку берём из пака, остриё — левый
// верхний угол, как в движке.
export function cursorApply(node, x, y) {
  const set = rules();
  if (!set || !node) return false;
  // Пока тащим камеру, курсор наш, а не игровой.
  if (node.classList?.contains("dragging")) {
    node.style.cursor = "";
    shown = null;
    return false;
  }
  const index = cursorAt(x, y);
  if (index === null || index === shown) return false;
  // В режиме переноса вместо курсора идёт иконка самой вещи
  // (VA 0x42DDA0 берёт её из класса, поле +0x16).
  if (index === set.kind.carry) {
    const icon = actorItem(carrying())?.icon;
    if (icon) {
      node.style.cursor = `url("${contentUrl(icon.path)}") ${icon.width >> 1} ${icon.height >> 1}, auto`;
      shown = `вещь:${carrying()}`;
      return true;
    }
  }
  const picture = set.images?.[index];
  if (!picture) return false;
  const [hotX, hotY] = set.hotspot ?? [0, 0];
  node.style.cursor = `url("${contentUrl(picture.path)}") ${hotX} ${hotY}, auto`;
  shown = index;
  return true;
}

export function cursorReset() { shown = null; }

// НЕСОМАЯ ВЕЩЬ ВИДНА ПОВЕРХ ВСЕГО ЭКРАНА.
//
// Курсор ставился только на холст мира, а пояс, левая панель, гнёзда и окно
// снаряжения — отдельные узлы со своим `cursor: pointer` в стилях. Стоило
// увести мышь на панель, и вещь с курсора пропадала, хотя оставалась в
// руке. В движке такого разделения нет: перенос — это режим курсора (8), и
// рисуется он поверх всего экрана, панели в том числе (VA 0x42DDA0).
//
// Поэтому картинку вешаем на КОРЕНЬ игры переменной, а правило в styles.css
// раздаёт её всем потомкам и перебивает их собственные курсоры.
export function carryCursorSync() {
  const root = document.querySelector("#game");
  if (!root) return false;
  const icon = actorItem(carrying())?.icon;
  if (!icon) {
    root.classList.remove("carrying");
    root.style.removeProperty("--carry-cursor");
    return false;
  }
  root.style.setProperty("--carry-cursor",
    `url("${contentUrl(icon.path)}") ${icon.width >> 1} ${icon.height >> 1}, auto`);
  root.classList.add("carrying");
  return true;
}
