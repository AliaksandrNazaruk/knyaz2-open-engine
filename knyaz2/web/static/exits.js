// Выходы с локации.
//
// Это не наша выдумка: в стартовом мире есть таблица переходов (250 записей
// по 17 байт, konung2/gamefile.py). Запись называет карту-источник, куда
// ведёт (-1 — уйти на глобальную карту, -2 — особый переход), клетку, куда
// встанет отряд на той стороне, и ПРЯМОУГОЛЬНИК-ТРИГГЕР в клетках исходной
// карты. У Черного Бора их четыре: две полосы по краям ведут на глобальную
// карту, узкая полоса на западе — к Волхву (карта 34), и есть особый выход
// в три клетки.
//
// Сборщик переводит прямоугольник в мировые координаты, здесь остаётся
// поймать героя внутри и сказать об этом один раз.
import { world } from "./world.js";
import { hero } from "./hero.js";

export const exits = [];
let inside = null;

export function exitsSetup(map) {
  exits.length = 0;
  inside = null;
  for (const entry of map.exits ?? []) exits.push({ ...entry });
  return exits;
}

// Выход, внутри которого лежит точка.
export function exitAt(x, y) {
  for (const door of exits) {
    if (x >= door.left && x <= door.right && y >= door.top && y <= door.bottom) {
      return door;
    }
  }
  return null;
}

// Проверка на каждом шаге: сообщаем ровно один раз на вход в зону.
export function exitsTick() {
  if (!hero.alive) return false;
  const door = exitAt(hero.x, hero.y);
  if (!door) {
    inside = null;
    return false;
  }
  if (inside === door) return false;
  inside = door;
  world.onExit?.(door);
  return true;
}
