// Обстановка интерьера: бочки, лавки, сундуки.
//
// Полный разбор — `docs/CONTAINERS_SPEC.md`. Коротко: блок 0x3D384 карты
// несёт тридцать зон по шестнадцать гнёзд, гнездо — спрайт с экранной точкой.
// Номер зоны это НОМЕР ЗАПИСИ ОБЪЕКТА карты (VA 0x425AA8:29), поэтому
// обстановка и рисуется внутри своей постройки.
//
// Сундук от лавки отличает одно: у сундука в гнезде лежит НОМЕР КУЧИ. Его
// вписывает туда загрузчик карты по паре байтов записи кучи — `+0x09` зона и
// `+0x0A` гнездо (VA 0x43DF48:344-352). В паке эта пара приезжает полями
// `zone` и `nest` самой кучи, и связывание повторяет движок.
import { world } from "./world.js";
import { loot } from "./loot.js";

//: Гнёзда по зонам: номер записи объекта -> список гнёзд.
const byZone = new Map();

export function furnitureSetup(map = world.map) {
  byZone.clear();
  for (const nest of map?.terrain?.furniture ?? []) {
    const zone = Number(nest.zone);
    if (!byZone.has(zone)) byZone.set(zone, []);
    byZone.get(zone).push({ ...nest, pile: null });
  }
  furnitureBind();
  return byZone;
}

// Связать гнёзда с кучами — перенос ветки загрузчика карты. Движок кладёт в
// гнездо номер живой кучи плюс один; у нас вместо номера ссылка на саму кучу,
// но правило то же: связь идёт ОТ КУЧИ, по её паре (зона, гнездо).
export function furnitureBind() {
  for (const nests of byZone.values()) {
    for (const nest of nests) nest.pile = null;
  }
  let bound = 0;
  for (const pile of loot) {
    if (pile.zone == null || pile.nest == null) continue;
    const nest = (byZone.get(Number(pile.zone)) ?? [])
      .find((row) => Number(row.nest) === Number(pile.nest));
    if (!nest) continue;
    nest.pile = pile;
    bound += 1;
  }
  return bound;
}

//: Гнёзда одной постройки. Пусто — обстановки у неё нет.
export function furnitureOf(slot) {
  return byZone.get(Number(slot)) ?? [];
}

// Гнездо под точкой. Движок пробует спрайт попиксельно (VA 0x441F63) и
// запоминает попадание только у гнезда С КУЧЕЙ — пустая лавка курсор не
// ловит вовсе (VA 0x424514:126).
//
//: Попиксельной пробы у нас пока нет ни у одного объекта сцены, поэтому здесь
//: прямоугольник кадра. Для сундука это почти то же: спрайты обстановки
//: мелкие и стоят порознь.
export function furnitureAt(x, y) {
  for (const nests of byZone.values()) {
    for (const nest of nests) {
      if (!nest.pile || nest.pile.taken || !nest.frame) continue;
      const left = nest.position.x;
      const top = nest.position.y;
      if (x >= left && x <= left + nest.frame.width &&
          y >= top && y <= top + nest.frame.height) {
        return nest;
      }
    }
  }
  return null;
}

//: Картинки обстановки — в предзагрузку карты, как оверлеи.
export function furnitureAssets(map = world.map) {
  const paths = [];
  for (const nest of map?.terrain?.furniture ?? []) {
    if (nest.frame?.asset) paths.push(nest.frame.asset);
  }
  return paths;
}
