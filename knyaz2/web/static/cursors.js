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
import { exitAt } from "./exits.js";
import { buildingAtCell } from "./buildings.js";
import { carrying } from "./carry.js";
import { hasTalk } from "./dialog.js";
import { actorItem, isBeast } from "./actor.js";
import { selection } from "./orders.js";

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
