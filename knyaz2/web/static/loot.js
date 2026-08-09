// Кучи на земле.
//
// В движке куча — это не предмет, а ЗАПИСЬ НА КЛЕТКУ: таблица 0x7AD7E4, до
// двухсот записей по 101 байту (VA 0x423360):
//
//     +0x05 строка, +0x06 столбец, +0x08 карта
//     +0x0B спрайт, +0x0F деньги, +0x11 сорок два слова предметов
//
// Кладут вещь так: если у клетки уже стоит бит 0x20, вещь падает в её кучу,
// иначе заводится новая. Спрайт выбирает VA 0x43BBC4 — одна вещь без денег
// показывает свою картинку (поле класса +0x18: 153 колчан, 154 топор, 155
// лук, 158 и 159 доспехи, 161 шлем, 165 щит, 166 меч, 214 дубина), а две и
// больше или деньги — мешочек 163.
//
// Подойдя к куче, движок сам ОПОЗНАЁТ её вещи броском против навыка
// «Идентификация предметов», забирает деньги и открывает обмен
// (VA 0x4115AC и 0x424128).
import { world } from "./world.js";
import { context } from "./viewport.js";
import { actorItem } from "./actor.js";
import { heroCellAt } from "./hero.js";
import { mapStateLoot } from "./mapstate.js";

export const loot = [];

//: Куча живёт В КЛЕТКЕ, и движок ищет её только по клетке: бит 0x20
//: слова клетки плюс совпадение строки и столбца (VA 0x423360), а подбор
//: случается, когда юнит ДОШЁЛ до этой клетки (VA 0x4115AC сравнивает
//: клетку юнита с целевой). Пиксельных радиусов в движке нет вовсе.
//: В куче столько же мест, сколько в мешке.
export const PILE_SLOTS = 42;
export const PILE_LIMIT = 200;

export function lootSetup(map) {
  loot.length = 0;
  // УЖЕ БЫЛИ ЗДЕСЬ — берём кучи из памяти карты, а не из пака. В памяти
  // лежит весь список живой карты: и приехавшее из пака, и брошенное
  // игроком, и высыпавшееся из убитых при уходе (VA 0x43A628). Пак знает
  // только исходную расстановку и вернул бы уже подобранное.
  const запомненные = mapStateLoot(map.legacy?.map_number);
  if (запомненные) {
    for (const pile of запомненные) {
      loot.push({
        ...pile,
        items: [...(pile.items ?? [])],
        details: (pile.details ?? []).map((detail) => ({ ...(detail ?? {}) })),
        enchant: [...(pile.enchant ?? [])],
        cell: pile.cell ? { ...pile.cell } : null,
        taken: false,
      });
    }
    return loot;
  }
  // КУЧИ ВЫБРАННОГО МИРА. Клетки у куч общие для всех шести миров, а
  // содержимое своё: на карте 19 у Ратибора лежит Медное зеркало колдуна и
  // 1500 монет, у Велиславны на том же месте Эликсир Мудрости и 700. Пока
  // читался общий список (мир 0), в родном Чёрном Бору Велиславне попадался
  // чужой лут — тот же корень, что был у двойника героя и его жителей.
  const мир = String(map.hero?.template?.world ?? 0);
  const кучи = map.loot_by_world?.[мир] ?? map.loot ?? [];
  for (const entry of кучи) {
    const pile = lootPut(entry.item, entry.position.x, entry.position.y,
                         entry.cell, entry.id);
    if (!pile) continue;
    // куча из пака может нести НЕСКОЛЬКО вещей и их экземплярные поля
    // (В10): крепость/износ, слово чар, отрава — параллельно items
    if (Array.isArray(entry.items) && entry.items.length > 1) {
      pile.items = [...entry.items];
    }
    const details = (entry.details ?? []).slice(0, pile.items.length);
    while (details.length < pile.items.length) details.push({});
    pile.details = details;
    pile.enchant = details.map((detail) => detail?.enchant ?? 0);
    if (entry.money) pile.money = entry.money;
  }
  return loot;
}

// Куча на этой точке — решает клетка, а не расстояние.
function pileHere(x, y, cell) {
  for (const pile of loot) {
    if (pile.taken) continue;
    if (cell && pile.cell && pile.cell.row === cell.row && pile.cell.col === cell.col) {
      return pile;
    }
    if (!cell && pile.cell) {
      // клетки не дали — считаем её сами, той же формулой, что и движок
      const at = heroCellAt(x, y);
      if (pile.cell.row === at.row && pile.cell.col === at.col) return pile;
    }
  }
  return null;
}

// Положить вещь на землю: в кучу этой клетки, а нет её — завести новую.
export function lootPut(name, x, y, cell = null, id = null, detail = null) {
  const state = detail ? { ...detail } : {};
  const pile = pileHere(x, y, cell);
  if (pile) {
    if (pile.items.length >= PILE_SLOTS) return null;
    pile.items.push(name);
    pile.details?.push(state);
    pile.enchant?.push(state.enchant ?? 0);
    return pile;
  }
  // Таблица движка фиксирована: 200 записей по 101 байту (0x7AD7E4).
  // Освобождённая запись может использоваться снова, живая 201-я — нет.
  if (loot.filter((entry) => !entry.taken).length >= PILE_LIMIT) return null;
  const fresh = {
    id: id ?? `pile_${loot.length}`,
    items: [name], money: 0,
    details: [state], enchant: [state.enchant ?? 0],
    x, y, cell: cell ? { ...cell } : null, taken: false,
  };
  loot.push(fresh);
  return fresh;
}

// Картинка кучи: одна вещь и без денег — её собственный вид, иначе мешочек
// (VA 0x43BBC4).
function groundSprite(pile) {
  const single = pile.items.length === 1 && !pile.money
    ? actorItem(pile.items[0])?.ground : null;
  return single ?? world.map?.interface?.ground_pile ?? null;
}

export function lootAssets() {
  const paths = [];
  const pouch = world.map?.interface?.ground_pile;
  if (pouch) paths.push(pouch.path);
  for (const pile of loot) {
    for (const name of pile.items) {
      const ground = actorItem(name)?.ground;
      if (ground) paths.push(ground.path);
    }
  }
  return paths;
}

// Куча под точкой — строго по КЛЕТКЕ, как её ищет движок (VA 0x423360).
// Ни радиуса, ни эллипса: попал в клетку кучи — нашёл, не попал — нет.
export function lootNear(x, y) {
  const at = heroCellAt(x, y);
  for (const pile of loot) {
    if (pile.taken || !pile.items.length || !pile.cell) continue;
    if (pile.cell.row === at.row && pile.cell.col === at.col) return pile;
  }
  return null;
}

// Выброшенный предмет ложится на землю там же, где стоит персонаж.
export function lootDrop(name, x, y, cell = null, detail = null) {
  return lootPut(name, x, y, cell, null, detail);
}

// Взять из кучи. Без номера берётся верхняя вещь; опустевшая куча уходит.
export function lootTake(pile, index = 0) {
  if (!pile || pile.taken || !pile.items.length) return null;
  const [name] = pile.items.splice(index, 1);
  pile.details?.splice(index, 1);
  pile.enchant?.splice(index, 1);
  if (!pile.items.length && !pile.money) pile.taken = true;
  return name ?? null;
}

// Куча рисуется своим спрайтом по центру клетки — ровно как в движке.
export function renderLoot(visible) {
  for (const pile of loot) {
    if (pile.taken || !pile.items.length) continue;
    // Запас в 80 пикселей — НАШ, чисто отрисовочный: он лишь не даёт
    // отсечь кучу, чья картинка залезает за край окна.
    if (pile.x < visible.left - 80 || pile.x > visible.right + 80 ||
        pile.y < visible.top - 80 || pile.y > visible.bottom + 80) continue;
    const sprite = groundSprite(pile);
    const image = sprite && world.images.get(sprite.path);
    if (!image) continue;
    context.drawImage(image, Math.round(pile.x - sprite.width / 2),
                      Math.round(pile.y - sprite.height / 2));
  }
}
