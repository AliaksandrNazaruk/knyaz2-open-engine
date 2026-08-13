// Постройки и реквизит: кадры в порядке отрисовки движка.
import { showRoofsNode } from "./dom.js";
import { world } from "./world.js";
import { context, drawBrightImage, layeredFrame } from "./viewport.js";
import { drawHeroAtDepth, hero, heroBodyFrame, roster } from "./hero.js";
import { renderUnit, units } from "./units.js";
import { actorFrame, UNIT_SORT_BIAS } from "./actor.js";
import { renderInsideShadows } from "./shadows.js";
import { buildingFrames } from "./buildings.js";
import { drawPile, lootInside } from "./loot.js";
import { furnitureOf } from "./furniture.js";

export function drawFrame(object, frame, bright = false) {
  const frameX = object.position.x + frame.offset_x;
  const frameY = object.position.y + frame.offset_y;
  const image = world.images.get(frame.asset);
  if (image) {
    if (bright) drawBrightImage(image, frameX, frameY);
    else context.drawImage(image, frameX, frameY);
  } else {
    context.fillStyle = "rgba(211, 0, 158, .65)";
    context.fillRect(frameX, frameY, frame.width, frame.height);
  }
}

// Статический объект по движку (VA 0x425AA8): main всегда; при наличии
// стен — содержимое здания (здесь герой, если стоит на клетке постройки),
// затем стены; крыша — только у первых 30 записей карты и только пока на
// клетках здания не стоит член отряда (VA 0x428282). Все кадры получают
// один и тот же якорь. Маска тени не рисуется здесь: она затемняет кадр
// отдельным проходом (VA 0x440788), см. renderShadows().
// Слоты построек, чьи крыши сейчас прячем: клетки всего отряда игрока.
function partyRoofSlots() {
  const slots = new Set();
  // Движок перебирает ВЕСЬ отряд игрока начиная с него самого и помечает
  // постройки, над которыми кто-то стоит (VA 0x428253). Слот у каждого
  // юнита свой — считается на шаге, как и у героя.
  for (const unit of roster(units)) {
    if (unit !== hero && (!unit.ally || unit.alive === false)) continue;
    if (unit.roofSlot != null) slots.add(unit.roofSlot);
  }
  return slots;
}

export function drawObject(object) {
  // Горящая постройка рисуется картинкой своей ступени.
  const frames = buildingFrames(object) ?? {};
  if (!frames.main) return false;
  const heroInside = hero.data && object.record_slot === hero.insideSlot;
  // Кадр main постройки движок блитит ИСХОДНОЙ палитрой (VA 0x425B0C:
  // [0x58E300] + запись[+4]) — без пересчёта под время суток, который
  // делает VA 0x441393 для стен и крыши. Бит 0x04 байта hdr+0xFE стоит
  // ровно у построек со стенами. Интерьер — это и есть кадр main, поэтому
  // ПОЛ В ДОМЕ НИКОГДА НЕ ТЕМНЕЕТ: он всегда дневной яркости.
  const brightMain = layeredFrame && Boolean(object.lighting?.main_static_palette);
  drawFrame(object, frames.main, brightMain);
  // ОБСТАНОВКА — сразу после пола. В движке проход нутра постройки рисует
  // гнёзда зоны первыми, до куч на полу и до людей (VA 0x424514:113-131), а
  // сам проход стоит между главным кадром и стенами (VA 0x425AA8:30).
  // Точка у гнезда своя, абсолютная, поэтому смещения кадра нулевые.
  for (const nest of furnitureOf(object.record_slot)) {
    if (!nest.frame) continue;
    drawFrame({ position: nest.position },
              { ...nest.frame, offset_x: 0, offset_y: 0 });
  }
  // ВНУТРИ ПОСТРОЙКИ рисуются ПОСЛЕ пола — иначе он их накрывает. Правило
  // общее для всех юнитов, а не только для игрока: в движке проход
  // содержимого постройки (VA 0x425AA8) перебирает всех, у кого клетка
  // помечена битом 21. Раньше герой шёл этой веткой, а купец и знахарь
  // оставались под полом.
  // Тени тех, кто внутри, — здесь же, СРАЗУ ПОСЛЕ ПОЛА и до самих фигур:
  // проход содержимого постройки в движке сперва копит их спаны и делит
  // яркость (VA 0x424514 → 0x43F260, 0x440788), а уже потом рисует людей.
  // В общем проходе сцены эти тени рисовать бесполезно — он идёт раньше
  // построек, и пол их накрывает.
  // Кучи на полу этой постройки — сразу после пола, до стен и крыши.
  for (const pile of lootInside(object.record_slot)) drawPile(pile);
  const inside = [];
  if (heroInside) inside.push({ actor: hero, frame: heroBodyFrame(), player: true });
  for (const unit of units) {
    if (unit.insideSlot === object.record_slot) {
      inside.push({ actor: unit, frame: actorFrame(hero.data, unit) });
    }
  }
  // Тень кладём туда же, куда лёг ПОЛ: светлый кадр уходит мимо слоя, прямо
  // на кадр, и тень обязана идти за ним — иначе её поднимет заливка фильтра
  // суток и вместо тени выйдет светлое серое пятно (см. shadows.js).
  renderInsideShadows(inside, brightMain);
  // ВНУТРИ ПОСТРОЙКИ ТОЖЕ ПО ГЛУБИНЕ. Проход содержимого не рисует юнитов
  // подряд: он раскладывает их по ТАБЛИЦЕ СТРОК (0x84F53C, 2000 записей по
  // 16 байт, переполнение в 0x85723C) и ключом берёт НИЗ СПРАЙТА — экранный
  // Y плюс высота холста (VA 0x424514:43, `local_14 + юнит[+0x54]`), а потом
  // идёт по строкам сверху вниз. Это ровно тот же ключ, что у общего прохода
  // сцены, — у человека низ холста приходится на ноги плюс шесть.
  //
  // Здесь герой рисовался ПЕРВЫМ, а жители за ним в порядке списка, поэтому
  // любой стоящий в доме житель закрывал героя собой — даже тот, что стоит
  // дальше по изометрии.
  const depth = (entry) => Math.round(entry.actor.y) + UNIT_SORT_BIAS;
  inside.sort((one, two) => depth(one) - depth(two));
  for (const entry of inside) {
    if (entry.player) drawHeroAtDepth();
    else renderUnit(entry.actor);
  }
  // Стены и крыша — обычный блиттер по палитре текущего времени суток.
  if (frames.walls) drawFrame(object, frames.walls);
  // Крыша прячется над постройкой, в которой стоит КТО-ТО ИЗ ОТРЯДА, а не
  // только главный: спутник, зашедший в дом, иначе оставался под крышей.
  const roofAllowed = object.record_slot < 30 && showRoofsNode.checked &&
    !partyRoofSlots().has(object.record_slot);
  if (roofAllowed && frames.roof) drawFrame(object, frames.roof);
  return heroInside;
}
