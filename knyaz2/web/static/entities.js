// Постройки и реквизит: кадры в порядке отрисовки движка.
import { showRoofsNode } from "./dom.js";
import { clock } from "./clock.js";
import { shared, world } from "./world.js";
import { context, drawBrightImage, drawBrightPart,
         layeredFrame } from "./viewport.js";
import { drawHeroAtDepth, hero, heroAnchor, heroBodyFrame,
         roster } from "./hero.js";
import { drawMesh, perspective } from "./perspective.js";
import { renderUnit, units } from "./units.js";
import { actorFrame, unitSortKey } from "./actor.js";
import { renderInsideShadows } from "./shadows.js";
import { buildingFrames } from "./buildings.js";
import { drawPile, loot, lootHidden, lootInNest, lootInside,
         lootSlotOf } from "./loot.js";
import { furnitureOf } from "./furniture.js";

// ЯКОРЬ ПОСТРОЙКИ — В ОДНОМ МЕСТЕ. Его берут и проход сцены, и полосовая
// укладка; разойдись они, дом поедет вдвое.
export function buildingAnchor(object) {
  return { x: object.bounds.draw_x + object.bounds.width / 2,
           y: object.bounds.sort_y };
}

// ЛИНИЯ ОСНОВАНИЯ: где стена каждого экранного столбца упирается в землю.
//
// Считается из следа постройки — списка её клеток. У каждой клетки берём
// мировую точку, и для каждого столбца оставляем САМУЮ НИЖНЮЮ: это и есть
// ближняя кромка следа. Форма выходит Λ-образная — ниже всего в ближнем
// углу ромба, выше к боковым.
//
// Считаем один раз и держим при записи постройки: след не меняется, пока
// дом стоит на месте.
function baseLineOf(object) {
  //: КЛЮЧ КЕША — ПОЛОЖЕНИЕ. Постройку двигают и скрипт разговора
  //: (dialog.js, токен OBJECT), и редактор; со «сосчитано однажды» линия
  //: осталась бы от прежнего места, а дом уехал.
  const key = `${object.position?.x ?? 0}:${object.position?.y ?? 0}`;
  if (object.baseLineKey === key) return object.baseLine;
  object.baseLineKey = key;
  const cells = object.cells?.footprint;
  if (!Array.isArray(cells) || cells.length < 2) {
    object.baseLine = null;
    return null;
  }
  const lowest = new Map();
  for (const cell of cells) {
    const at = heroAnchor(cell[0], cell[1]);
    const key = Math.round(at.x);
    const have = lowest.get(key);
    if (have === undefined || at.y > have) lowest.set(key, at.y);
  }
  const points = [...lowest.entries()]
    .map(([x, y]) => ({ x, y })).sort((one, two) => one.x - two.x);
  //: След должен хотя бы касаться рамки кадра постройки. Разъехались —
  //: значит клетки от прежнего места (их скрипт не двигает), и лучше
  //: обычная укладка, чем продолжение прямой в никуда.
  const left = object.bounds?.draw_x ?? points[0].x;
  const right = left + (object.bounds?.width ?? 0);
  const touches = points[points.length - 1].x >= left && points[0].x <= right;
  object.baseLine = points.length >= 2 && touches ? points : null;
  return object.baseLine;
}

//: Основание в произвольном столбце: между замерами — прямая, за краями —
//: продолжение по наклону крайнего отрезка (свес крыши выходит за след, и
//: без продолжения там был бы скачок).
function baseAt(points) {
  const last = points.length - 1;
  return (x) => {
    if (x <= points[0].x) {
      const step = (points[1].y - points[0].y) / (points[1].x - points[0].x || 1);
      return points[0].y + (x - points[0].x) * step;
    }
    if (x >= points[last].x) {
      const step = (points[last].y - points[last - 1].y) /
        (points[last].x - points[last - 1].x || 1);
      return points[last].y + (x - points[last].x) * step;
    }
    for (let i = 1; i <= last; i += 1) {
      if (x <= points[i].x) {
        const share = (x - points[i - 1].x) /
          (points[i].x - points[i - 1].x || 1);
        return points[i - 1].y + (points[i].y - points[i - 1].y) * share;
      }
    }
    return points[last].y;
  };
}

export function drawFrame(object, frame, bright = false) {
  const frameX = object.position.x + frame.offset_x;
  const frameY = object.position.y + frame.offset_y;
  const image = world.images.get(frame.asset);
  if (!image) {
    context.fillStyle = "rgba(211, 0, 158, .65)";
    context.fillRect(frameX, frameY, frame.width, frame.height);
    return;
  }
  //: СЕТКА — ТОЛЬКО СТЕНАМ, и вот почему.
  //:
  //: Линия основания говорит: «у столбца x земля вот здесь». Для СТЕНЫ это
  //: правда — стена и упирается в грунт этим столбцом. Для КРЫШИ ложь:
  //: крыша накрывает весь след, и в одном столбце у неё и ближний скат, и
  //: конёк, и дальний скат — глубины у них разные, а модель даёт всем
  //: ближнюю. Крыша — самая большая масса дома, оттого перекос и бросается
  //: в глаза. Пол — тоже плоскость, и по столбцам его мерить так же неверно.
  //:
  //: Правильно было бы плоскостям дать свою модель (по строкам, как земле),
  //: но у крыши свой наклон и свой закон, а проверить его не на чем.
  //: `mesh=all` возвращает прежнее поведение для сравнения.
  const meshable = perspective.on && perspective.mesh &&
    (perspective.meshAll || frame === object.frames?.walls);
  const points = meshable ? baseLineOf(object) : null;
  if (points) {
    const anchor = buildingAnchor(object);
    const target = bright
      ? (im, sx, sy, sw, sh, dx, dy, dw, dh) =>
          drawBrightPart(im, sx, sy, sw, sh, dx, dy, dw, dh)
      : null;
    drawMesh(target ? { drawImage: target } : context, image,
             frameX, frameY, frame.width, frame.height,
             baseAt(points), anchor.x, anchor.y);
    return;
  }
  if (bright) drawBrightImage(image, frameX, frameY);
  else context.drawImage(image, frameX, frameY);
}

// ПРАВИЛО КРЫШИ ЖИВЁТ ЗДЕСЬ, И БОЛЬШЕ НИГДЕ.
//
// Крыша прячется над постройкой, на клетках которой стоит КТО-ТО ИЗ ОТРЯДА
// игрока, а не только сам игрок: движок перебирает весь отряд начиная с
// него (VA 0x428253) и помечает такие постройки, после чего проход объекта
// пропускает их кадр крыши (VA 0x428282). Метка у каждого юнита своя и
// считается на шаге — `unit.roofBuilding` (hero.unitUpdateBuilding).
//
// Сверка ССЫЛКАМИ, а не номерами: постройки и реквизит нумеруются каждый со
// своего нуля, и номера пересекаются.
//
// ГЕЙТА «СЛОТ МЕНЬШЕ ТРИДЦАТИ» У НАС НЕТ. Он повторял предел канонного
// движка, но у канона дома с крышей не заходят дальше слота 20 — гейт там
// ничего не решал, — а города «Продолжения легенды» держат до 57 домов, и
// слоты за тридцаткой стояли без крыш вовсе.
//
// Выключатель `#show-roofs` — наш, отладочный: в движке крышу снять нечем.
export function partyRoofBuildings() {
  const owners = new Set();
  for (const unit of roster(units)) {
    if (unit !== hero && (!unit.ally || unit.alive === false)) continue;
    if (unit.roofBuilding != null) owners.add(unit.roofBuilding);
  }
  return owners;
}

export function roofVisible(object, owners) {
  return showRoofsNode.checked && !owners.has(object);
}

// Статический объект по движку (VA 0x425AA8): main всегда; при наличии
// стен — содержимое здания (здесь герой, если стоит на клетке постройки),
// затем стены, затем крыша по правилу выше. Все кадры получают один и тот же
// якорь. Маска тени не рисуется здесь: она затемняет кадр отдельным проходом
// (VA 0x440788), см. renderShadows().
//
// Хозяев крыш считает сцена ОДИН РАЗ на кадр и передаёт сюда: набор общий
// для всех объектов, а объектов на карте бывает под шесть сотен.
// РАСКЛАДКА НУТРА — ОДНА НА ПРОХОД, А НЕ НА КАЖДУЮ ПОСТРОЙКУ.
//
// `drawObject` спрашивал у каждой постройки «какие кучи на твоём полу» и
// «кто из юнитов внутри тебя», и оба ответа считались перебором ВСЕГО
// списка: фильтр по кучам и цикл по юнитам, каждый со своим временным
// массивом. Вблизи это незаметно (105 построек в кадре), а на отдалении
// рисуются все 546 — и замер игрока показал, что постройки съедают 42%
// времени при цене 30 мкс на штуку, тогда как сам блит спрайта стоит 4-7.
//
// Теперь оба ответа складываются один раз перед проходом. Порядок отрисовки
// не меняется: списки те же и в том же виде.
let passPiles = null;      // слот постройки -> кучи на её полу
let passInside = null;     // постройка -> юниты внутри неё

export function entitiesBeginPass() {
  passPiles = new Map();
  for (const pile of loot) {
    if (pile.taken || !pile.items.length) continue;
    if (lootHidden(pile) || lootInNest(pile)) continue;
    const slot = lootSlotOf(pile);
    if (slot == null) continue;
    const list = passPiles.get(slot);
    if (list) list.push(pile);
    else passPiles.set(slot, [pile]);
  }
  passInside = new Map();
  for (const unit of units) {
    if (unit.hidden || !unit.insideBuilding) continue;
    const list = passInside.get(unit.insideBuilding);
    if (list) list.push(unit);
    else passInside.set(unit.insideBuilding, [unit]);
  }
}

//: Проход кончился — раскладку снимаем, чтобы одиночные вызовы `drawObject`
//: (их делает отладка) считали по-старому и не читали вчерашние списки.
export function entitiesEndPass() {
  passPiles = null;
  passInside = null;
}

const EMPTY = [];

export function drawObject(object, roofOwners = partyRoofBuildings()) {
  // Горящая постройка рисуется картинкой своей ступени.
  const frames = buildingFrames(object) ?? {};
  if (!frames.main) return false;
  // Сверка ссылкой: номера построек и реквизита — две разные нумерации.
  const heroInside = hero.data && object === hero.insideBuilding;
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
  //
  // ОБСТАНОВКА СВЕТЛА ВМЕСТЕ С ПОЛОМ. Флаг «рисовать исходной палитрой» у
  // постройки один, и проход нутра получает ЕГО ЖЕ третьим доводом
  // (VA 0x425AA8:15 берёт бит 0x04 байта +0x22, строка 30 передаёт его в
  // 0x424514). Внутри прохода он и выбирает палитру гнезда: без флага —
  // пересчёт под сутки (0x441393), с флагом — база 0x58E300 без пересчёта.
  // У нас гнёзда уходили в слой сцены и темнели ночью на дневном полу;
  // самопроверка ловила это правилом «интерьер не темнеет» — 13 626 точек
  // из 64 487 на карте 19.
  for (const nest of furnitureOf(object.record_slot)) {
    if (!nest.frame) continue;
    drawFrame({ position: nest.position },
              { ...nest.frame, offset_x: 0, offset_y: 0 }, brightMain);
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
  const piles = passPiles
    ? (passPiles.get(object.record_slot) ?? EMPTY)
    : lootInside(object.record_slot);
  for (const pile of piles) drawPile(pile);
  const inside = [];
  if (heroInside) inside.push({ actor: hero, frame: heroBodyFrame(), player: true });
  // Ушедший с карты не рисуется и ТЕНИ НЕ ОТБРАСЫВАЕТ: в общий список он
  // не попадал и раньше, а сюда проходил — и его тень оставалась висеть
  // на полу дома. Отбор по `hidden` сделан в `entitiesBeginPass`.
  const dwellers = passInside
    ? (passInside.get(object) ?? EMPTY)
    : units.filter((unit) => !unit.hidden && unit.insideBuilding === object);
  for (const unit of dwellers) {
    inside.push({ actor: unit, frame: actorFrame(hero.data, unit) });
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
  inside.sort((one, two) => unitSortKey(one.actor) - unitSortKey(two.actor));
  for (const entry of inside) {
    if (entry.player) drawHeroAtDepth();
    else renderUnit(entry.actor);
  }
  // Стены и крыша — обычный блиттер по палитре текущего времени суток.
  if (frames.walls) drawFrame(object, frames.walls);
  if (frames.roof && roofVisible(object, roofOwners)) drawFrame(object, frames.roof);
  drawObjectFire(object);
  return heroInside;
}

// ОГНИ НА ОБЪЕКТЕ (VA 0x427E94): костры, факелы, горящие руины.
//
// У заголовка объекта в движке до восьми точек «id анимации + смещение», и
// отрисовка ведёт каждую своим кадром: поле кадра живёт в записи объекта,
// загрузчик кладёт туда СЛУЧАЙНЫЙ кадр диапазона (VA 0x4423E1), такт двигает
// на единицу за мировой такт, рисуется спрайт в точке объекта плюс смещение.
// Разбор и провенанс кадров — konung2/objectanim.py.
//
// Кадр считаем от мировых часов с фазой объекта: то же самое поведение без
// отдельного поля-счётчика. Фаза случайная при первом показе — как в движке,
// где случайность кладёт загрузчик карты, а не выпечка.
function drawObjectFire(object) {
  const points = object.fire;
  if (!points?.length) return;
  const anims = shared.effects?.object_anims;
  if (!anims) return;
  for (let i = 0; i < points.length; i += 1) {
    const point = points[i];
    const frames = anims[point.anim]?.frames;
    if (!frames?.length) continue;
    if (object.firePhase === undefined) {
      object.firePhase = Math.floor(Math.random() * frames.length);
    }
    const index = (Math.floor(clock.ticks) + object.firePhase + i)
      % frames.length;
    const image = world.images.get(frames[index]);
    if (!image) continue;
    //: Точка огня — от точки ОБЪЕКТА на карте, не от кадра: движок
    //: складывает pixel_x с dx без участия якорей спрайта.
    context.drawImage(image,
                      object.position.x + point.dx,
                      object.position.y + point.dy);
  }
}
