// Локальный свет у построек: аура складывается с готовым кадром.
import { daylight } from "./daylight.js";
import { world } from "./world.js";
import { cellVisible, context } from "./viewport.js";
import { drawPlane } from "./perspective.js";

export function nightDarkness() {
  const [b, g, r] = daylight.levels;
  const darkest = Math.min(b, g, r, 0);
  return Math.min(1, -darkest / 70);
}

// Локальный свет включает САМ ДВИЖОК, и не по темноте: земля рисуется
// проходом с маской, только если [0x8495CC] и [0x8495DC] оба ненулевые
// (VA 0x424FFA). Первый флаг ставит расписание суток — единица появляется
// в ветке «ночь», то есть с тика 8100 (VA 0x429806), а у карт из таблицы
// 0x4617B0 он ненулевой всегда (пещеры, VA 0x4295E4). Второй — настройка
// качества из меню, у нас всегда включена.
export function lightActive() {
  if (!world.litCells.length) return false;
  const lighting = world.map?.lighting ?? {};
  if (lighting.always) return true;
  const from = lighting.from_tick ?? 8100;
  return daylight.time >= from;
}

// Аура у построек: клетка с ненулевым байтом слоя 2 идёт в движке по
// ветке VA 0x43FEB0 — красный и зелёный берутся из таблиц уровня
// «уровень канала + маска», синий не меняется вовсе. Пак несёт РАЗНОСТЬ
// с обычной клеткой, поэтому здесь она просто складывается с кадром
// (composite lighter). При маске 0 разность нулевая — тёмной каймы у
// пятна света не возникает в принципе, и подмешивать по темноте ничего
// не нужно: свет либо включён движком, либо нет.
export function renderLightGlow(visible) {
  if (!lightActive()) return;
  context.save();
  context.globalCompositeOperation = "lighter";
  for (const cell of world.litCells) {
    if (!cellVisible(cell.x, cell.y, visible)) continue;
    const image = world.images.get(cell.light.glow);
    //: Пятно света лежит НА ЗЕМЛЕ, значит едет плоскостью, а не спрайтом.
    if (image) drawPlane(context, image, cell.x, cell.y, image.width, image.height);
  }
  context.restore();
}
