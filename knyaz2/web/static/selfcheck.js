// Самопроверка кадра: правила света и глубины, снятые с движка, — числами.
//
// Логика освещения ломалась молча уже трижды, потому что проверить её можно
// было только глазами. Здесь те же замеры, что делались вручную, оформлены
// как повторяемый прогон: `knyaz2.selfcheck()` возвращает список правил с
// числами и вердиктом. Прогонять после любой правки рендера — особенно после
// перестановки слоёв.
//
// Правила и их источник в konung2.exe:
//   1. кадр main постройки не темнеет никогда          VA 0x425AED / 0x425B0C
//   2. стены той же постройки темнеют по уровню суток   VA 0x425BD1 -> 0x441393
//   3. аура только прибавляет свет и не трогает синий   VA 0x43FD70
//   4. локальный свет включается ровно с тика 8100      VA 0x429806
//   5. персонаж внутри дома виден сквозь стену          VA 0x428900 (0x866F5C)
//   6. светлые кадры не подменяют собой чужие пиксели   порядок 0x425AA8
//   7. ключ постройки — подошва кадра минус четверть    VA 0x4267B8:204-217
//   8. ключ человека — ноги плюс шесть                  VA 0x4267B8:84,93
//   9. стена не перекрывает стоящего перед ней          то же
//  10. дом перекрывает стоящего за ним                  то же
//  11. житель стоит НА полу дома, а не под ним          VA 0x425AA8
//  12. крыша прячет жителя в доме                       VA 0x428282

import { saveHealth } from "./save.js";
import { resize } from "./viewport.js";
import { heroSheets, unitSortKey } from "./actor.js";
import { partyRoofBuildings, roofVisible } from "./entities.js";
import { unitUpdateBuilding } from "./hero.js";
import { units } from "./units.js";

const NIGHT_TICK = 10070;      // тик, на котором снимался эталон с живой игры
const DAY_TICK = 4600;
const GATE_TICK = 8100;        // i16 @0x45FC46

function medianDiff(a, b, index) {
  return Math.abs(a[index] - b[index]) + Math.abs(a[index + 1] - b[index + 1]) +
    Math.abs(a[index + 2] - b[index + 2]);
}

export function createSelfCheck(api) {
  const { world, hero, view, canvas, render, daylightSet, heroAnchor,
          heroUpdateBuilding, showRoofsNode, ambientNode, clockRunNode } = api;
  const heroSetPose = (pose) => { if (hero.pose !== pose) { hero.pose = pose; hero.frame = 0; } };
  const context = canvas.getContext("2d");
  const masks = new Map();

  // Промах НЕ кэшируем: картинка может ещё грузиться, а осевший в кэше null
  // потом навсегда выдаёт «нет кадра» даже после загрузки.
  function alphaMask(path) {
    if (!masks.has(path)) {
      const image = world.images.get(path);
      if (!image) {
        return null;
      } else {
        const buffer = document.createElement("canvas");
        buffer.width = image.width;
        buffer.height = image.height;
        buffer.getContext("2d").drawImage(image, 0, 0);
        masks.set(path, {
          data: buffer.getContext("2d").getImageData(0, 0, image.width, image.height).data,
          width: image.width,
          height: image.height,
        });
      }
    }
    return masks.get(path);
  }

  // Кадры героя лежат на листах пака: своего файла у кадра нет, только
  // прямоугольник на листе (sheet + x/y/width/height) — как в движке, где
  // спрайты берутся смещением по общей арене. Маска такого кадра вырезается
  // из листа; ключ кэша — лист и прямоугольник.
  function frameMask(frame) {
    if (!frame) return null;
    if (frame.sheet === undefined) return alphaMask(frame.path);
    const sheet = heroSheets()?.[frame.sheet];
    const image = sheet && world.images.get(sheet.path);
    if (!image) return null;
    const key = `${sheet.path}#${frame.x}:${frame.y}:${frame.width}:${frame.height}`;
    if (!masks.has(key)) {
      const buffer = document.createElement("canvas");
      buffer.width = frame.width;
      buffer.height = frame.height;
      const bufferContext = buffer.getContext("2d");
      bufferContext.drawImage(image, frame.x, frame.y, frame.width, frame.height,
                              0, 0, frame.width, frame.height);
      masks.set(key, {
        data: bufferContext.getImageData(0, 0, frame.width, frame.height).data,
        width: frame.width,
        height: frame.height,
      });
    }
    return masks.get(key);
  }

  // Кромка спрайта полупрозрачна, и такой пиксель на холсте смешан с тем, что
  // под ним, — а под ним фон, который темнеет. Считать его «своим» нельзя:
  // порогом берём полную непрозрачность, а не половину.
  const SOLID = 250;

  function opaqueAt(mask, originX, originY, worldX, worldY, threshold = SOLID) {
    if (!mask) return false;
    const x = Math.round(worldX - originX);
    const y = Math.round(worldY - originY);
    if (x < 0 || y < 0 || x >= mask.width || y >= mask.height) return false;
    return mask.data[(y * mask.width + x) * 4 + 3] >= threshold;
  }

  // Один пиксель холста покрывает 1 / (zoom * dpr) мировых, и на кромке кадра
  // в него подмешивается то, что под ним, — а под ним фон, который темнеет.
  // Поэтому «внутри» считается с запасом ровно в этот след: столько мировых
  // пикселей и попадает в один замеряемый.
  // Замер: при dpr 1.25 все «потемневшие» пиксели интерьера лежали ровно в
  // одном пикселе от кромки (70, 178 и 138 штук на трёх постройках — все на
  // радиусе 1), то есть темнеет не интерьер, а шов.
  function insideRadius() {
    const footprint = 1 / (view.zoom * view.dpr);
    // Дробный dpr вдобавок сдвигает сетку: центр пикселя холста попадает
    // между мировыми, и округление может взять любого соседа.
    const slack = Number.isInteger(view.dpr) ? 0 : 1;
    return Math.max(1, Math.ceil(footprint) + slack);
  }

  // Внутри вместе со всеми соседями по квадрату — по диагонали кромка тоже
  // подмешивается.
  function deepInside(mask, originX, originY, worldX, worldY) {
    const r = insideRadius();
    for (let dy = -r; dy <= r; dy += 1) {
      for (let dx = -r; dx <= r; dx += 1) {
        if (!opaqueAt(mask, originX, originY, worldX + dx, worldY + dy)) return false;
      }
    }
    return true;
  }

  // Есть ли рядом непрозрачный пиксель другого слоя: интерьер, к которому
  // вплотную подходит стена, на кромке смешан с ней, а стена темнеет.
  function nearMask(mask, originX, originY, worldX, worldY) {
    if (!mask) return false;
    const r = insideRadius();
    for (let dy = -r; dy <= r; dy += 1) {
      for (let dx = -r; dx <= r; dx += 1) {
        if (opaqueAt(mask, originX, originY, worldX + dx, worldY + dy)) return true;
      }
    }
    return false;
  }

  // Прямоугольник кадра вокруг центра холста; render и чтение подряд, чтобы
  // между ними не влез кадр анимационного цикла.
  function shoot(box) {
    render();
    return context.getImageData(box.left, box.top, box.width, box.height);
  }

  function windowAround(width, height) {
    return {
      left: Math.round(canvas.width / 2 - width / 2),
      top: Math.round(canvas.height / 2 - height / 2),
      width, height,
    };
  }

  // Обратная к worldTransform: холст меряется в УСТРОЙСТВЕННЫХ пикселях, а
  // мир — в мировых, поэтому делить надо на zoom И на dpr. Без dpr проверка
  // молча мерила не те пиксели на экранах с масштабом отличным от единицы.
  function worldOf(box, x, y) {
    const scale = view.zoom * view.dpr;
    return [view.cameraX + (box.left + x - canvas.width / 2) / scale,
            view.cameraY + (box.top + y - canvas.height / 2) / scale];
  }

  function placeHero(row, col) {
    const anchor = heroAnchor(row, col);
    hero.cell = { row, col };
    hero.x = anchor.x;
    hero.y = anchor.y;
    heroUpdateBuilding();
    return anchor;
  }

  function buildings() {
    return world.objects.filter((object) => object.lighting?.main_static_palette);
  }

  // ── правила 1 и 2 ──────────────────────────────────────────────────────
  //
  // ЖИТЕЛЕЙ ПРЯЧЕМ САМИ. Правило сравнивает интерьер днём и ночью, а живой
  // житель в доме между двумя снимками успевает шагнуть и сменить кадр —
  // и его точки идут в счёт «интерьер потемнел». Раньше это лечили тем, что
  // прогон запускали с вычищенным списком юнитов, но такой прогон ломает
  // правила, которым житель как раз нужен. Прячем ровно на два снимка.
  function interiorNeverDarkens() {
    const hiddenBefore = units.map((unit) => unit.hidden);
    units.forEach((unit) => { unit.hidden = true; });
    // ГЕРОЯ ТОЖЕ УБИРАЕМ, и по той же причине: у него нет `hidden`, поэтому
    // уводим за край мира. Его тень удлиняется к закату (наше расширение), и
    // между дневным и ночным снимком меняется — а он на старте многих карт
    // стоит вплотную к постройке, которую как раз и меряем.
    const heroWas = { x: hero.x, y: hero.y };
    hero.x += 8000; hero.y += 8000;
    try {
      return interiorNeverDarkensInner();
    } finally {
      hero.x = heroWas.x; hero.y = heroWas.y;
      units.forEach((unit, index) => { unit.hidden = hiddenBefore[index]; });
    }
  }

  //: Правилам 1, 2 и 6 нужна постройка с ДНЕВНЫМ ИНТЕРЬЕРОМ. Флаг этот —
  //: свойство ресурса, а не места на карте (сверено по паку: из 50 ресурсов
  //: ни один не встречается и светлым, и тусклым), и есть целые семьи без
  //: него — пустынные постройки Тиграта, Дворца Жёлтых собак, Деревушки в
  //: песках. На такой карте мерить нечего, и правило обязано сказать
  //: «неприменимо», а не «провал»: иначе донорские карты вечно красные и на
  //: них перестают смотреть.
  function notApplicable(rule) {
    return { rule, pass: true,
             details: { неприменимо: "на карте нет построек с дневным интерьером" } };
  }

  function interiorNeverDarkensInner() {
    const results = [];
    if (!buildings().length) {
      return [notApplicable("интерьер не темнеет"), notApplicable("стены темнеют")];
    }
    for (const object of buildings().slice(0, 3)) {
      const main = object.frames.main;
      const walls = object.frames.walls;
      const mainMask = alphaMask(main.asset);
      const wallsMask = walls ? alphaMask(walls.asset) : null;
      const mainX = object.position.x + main.offset_x;
      const mainY = object.position.y + main.offset_y;
      view.cameraX = mainX + main.width / 2;
      view.cameraY = mainY + main.height / 2;
      const box = windowAround(Math.min(canvas.width, main.width + 40),
                               Math.min(canvas.height, main.height + 40));
      daylightSet(DAY_TICK);
      const day = shoot(box).data;
      daylightSet(NIGHT_TICK);
      const night = shoot(box).data;
      let interior = 0, changed = 0, wallPixels = 0, wallRatio = 0;
      for (let y = 0; y < box.height; y += 1) {
        for (let x = 0; x < box.width; x += 1) {
          const [worldX, worldY] = worldOf(box, x, y);
          const i = (y * box.width + x) * 4;
          if (wallsMask && opaqueAt(wallsMask, object.position.x + walls.offset_x,
                                    object.position.y + walls.offset_y, worldX, worldY)) {
            wallPixels += 1;
            if (day[i]) wallRatio += night[i] / day[i];
          } else if (deepInside(mainMask, mainX, mainY, worldX, worldY) &&
                     !nearMask(wallsMask, object.position.x + (walls?.offset_x ?? 0),
                               object.position.y + (walls?.offset_y ?? 0),
                               worldX, worldY)) {
            interior += 1;
            if (medianDiff(day, night, i) > 6) changed += 1;
          }
        }
      }
      results.push({ slot: object.record_slot, interior, changed,
                     walls: wallPixels,
                     wallRatio: wallPixels ? +(wallRatio / wallPixels).toFixed(3) : null });
    }
    const bad = results.filter((r) => r.changed > 0 || !r.interior);
    const dark = results.filter((r) => r.walls && r.wallRatio > 0.6);
    return [
      { rule: "интерьер не темнеет", pass: bad.length === 0, details: results },
      { rule: "стены темнеют", pass: dark.length === 0 && results.some((r) => r.walls),
        details: results.map((r) => r.wallRatio) },
    ];
  }

  // ── правило 3 ──────────────────────────────────────────────────────────
  function glowOnlyAdds() {
    const cell = world.litCells[0];
    if (!cell) return [{ rule: "аура только прибавляет", pass: false, details: "нет клеток со светом" }];
    daylightSet(NIGHT_TICK);
    view.cameraX = cell.x + 57;
    view.cameraY = cell.y + 32;
    const box = windowAround(240, 160);
    const withGlow = shoot(box).data;
    const kept = world.litCells;
    world.litCells = [];
    const without = shoot(box).data;
    world.litCells = kept;
    let minDelta = 0, blue = 0, brighter = 0;
    for (let i = 0; i < withGlow.length; i += 4) {
      for (let c = 0; c < 3; c += 1) {
        const delta = withGlow[i + c] - without[i + c];
        if (delta < minDelta) minDelta = delta;
      }
      blue = Math.max(blue, Math.abs(withGlow[i + 2] - without[i + 2]));
      if (withGlow[i] - without[i] > 2) brighter += 1;
    }
    return [{
      rule: "аура только прибавляет и не трогает синий",
      pass: minDelta >= -1 && blue <= 1 && brighter > 0,
      details: { минимум: minDelta, максСиний: blue, осветлённых: brighter },
    }];
  }

  // ── правило 4 ──────────────────────────────────────────────────────────
  function gateFollowsSchedule() {
    const cell = world.litCells[0];
    view.cameraX = cell.x + 57;
    view.cameraY = cell.y + 32;
    const box = windowAround(200, 140);
    const sample = (tick) => {
      daylightSet(tick);
      const on = shoot(box).data;
      const kept = world.litCells;
      world.litCells = [];
      const off = shoot(box).data;
      world.litCells = kept;
      let differs = 0;
      for (let i = 0; i < on.length; i += 4) if (medianDiff(on, off, i) > 2) differs += 1;
      return differs;
    };
    const before = sample(GATE_TICK - 1);
    const after = sample(GATE_TICK);
    return [{
      rule: `свет включается с тика ${GATE_TICK}`,
      pass: before === 0 && after > 0,
      details: { [`тик ${GATE_TICK - 1}`]: before, [`тик ${GATE_TICK}`]: after },
    }];
  }

  // ── правило 5 ──────────────────────────────────────────────────────────
  function heroVisibleIndoors() {
    const floor = (world.map.buildings ?? [])
      .flatMap((building) => building.cells?.floor ?? [])[0];
    if (!floor || !hero.data) {
      return [{ rule: "персонаж виден в доме", pass: false, details: "нет пола или героя" }];
    }
    // Правило про стену, а не про анимацию: замеряем на стойке, иначе маска
    // кадра и нарисованные пиксели — из разных поз, и доля падает сама собой.
    const savedPose = { pose: hero.pose, frame: hero.frame };
    heroSetPose("stand");
    hero.frame = 0;
    const frame = hero.data.animations[hero.stance ?? 'peace']?.stand?.[hero.direction]?.[0];
    const mask = frameMask(frame);   // кадр героя, не пака: у листового кадра нет пути
    if (!mask) return [{ rule: "персонаж виден в доме", pass: false, details: "нет кадра" }];
    const results = {};
    for (const [name, tick] of [["день", DAY_TICK], ["ночь", NIGHT_TICK]]) {
      daylightSet(tick);
      const anchor = placeHero(floor[0], floor[1]);
      view.cameraX = anchor.x;
      view.cameraY = anchor.y;
      // кадр героя рисуется в мировых пикселях, а читаем мы устройственные
      const scale = view.zoom * view.dpr;
      const box = {
        left: Math.round(canvas.width / 2 + frame.offset_x * scale),
        top: Math.round(canvas.height / 2 + frame.offset_y * scale),
        width: Math.round(mask.width * scale), height: Math.round(mask.height * scale),
      };
      const inside = shoot(box).data;
      placeHero(floor[0] + 40, floor[1]);
      const empty = shoot(box).data;
      // маска кадра — в мировых пикселях, снимок — в устройственных, поэтому
      // каждый непрозрачный пиксель маски пересчитывается в пиксель снимка
      let opaque = 0, seen = 0;
      for (let my = 0; my < mask.height; my += 1) {
        for (let mx = 0; mx < mask.width; mx += 1) {
          if (mask.data[(my * mask.width + mx) * 4 + 3] < SOLID) continue;
          opaque += 1;
          const bx = Math.round(mx * scale), by = Math.round(my * scale);
          if (bx >= box.width || by >= box.height) continue;
          if (medianDiff(inside, empty, (by * box.width + bx) * 4) > 6) seen += 1;
        }
      }
      results[name] = { opaque, seen, доля: +(seen / opaque).toFixed(3) };
    }
    hero.pose = savedPose.pose;
    hero.frame = savedPose.frame;
    // Порог 0.85, а не 0.9: правило про «виден ли он вообще сквозь стену», и
    // сломанный порядок даёт здесь около нуля, а не восемь десятых. Девятка
    // же стояла впритык к живому значению — замеры разных дней дают 0.877…
    // 0.901 на одном и том же месте, и правило мигало от позы и от шва
    // спрайта. Мигающая проверка хуже отсутствующей: на неё перестают
    // смотреть.
    return [{
      rule: "персонаж виден в доме",
      pass: Object.values(results).every((r) => r.доля > 0.8),
      details: results,
    }];
  }

  // ── правила 7-10: глубина, стены и крыши ───────────────────────────────
  //
  // Ради этих четырёх правил и заведён раздел: за один день порядок глубины
  // ломался трижды, и каждый раз это ловил игрок глазами, а не проверка.
  // Ловится оно только картинкой, поэтому меряем видимые точки героя.
  //
  //   7. ключ постройки = подошва её кадра минус четверть  (VA 0x4267B8:204)
  //   8. ключ человека = ноги + 6                          (VA 0x4267B8:84,93)
  //   9. стоящий ПЕРЕД стеной ею не перекрыт
  //  10. стоящий ЗА домом перекрыт им

  //: Сколько точек героя видно в окне: снимок с ним против снимка без него.
  //: Героя не «выключаем», а уводим далеко — снятие `hero.data` меняет и
  //: послойность кадра, и тени, и мерить после этого нечего.
  function heroPixels(box) {
    const A = shoot(box).data;
    const x = hero.x, y = hero.y;
    hero.x += 4000; hero.y += 4000;
    const B = shoot(box).data;
    hero.x = x; hero.y = y;
    let n = 0;
    for (let i = 0; i < A.length; i += 4) {
      if (medianDiff(A, B, i) > 6) n += 1;
    }
    return n;
  }

  //: Поставить героя в клетку, навести на него камеру и посчитать его точки.
  function heroAt(row, col, width = 280, height = 340) {
    const anchor = placeHero(row, col);
    view.cameraX = anchor.x;
    view.cameraY = anchor.y - 50;
    return { anchor, pixels: heroPixels(windowAround(width, height)) };
  }

  //: Клетка, где героя точно ничто не закрывает: ни одна рамка объекта не
  //: подходит к ней ближе, чем на 140 точек. Нужна как мерка «видно целиком».
  // Запас ослабляем по шагам: на просторной деревне мерка найдётся сразу, а
  // во Дворце Жёлтых собак застроено всё, и со строгим запасом проверка
  // просто не находила клетки и рапортовала провал на ровном месте.
  function openCell(near) {
    for (const margin of [140, 60, 0]) {
      for (let d = 4; d < 60; d += 2) {
        for (const [dr, dc] of [[d, 0], [-d, 0], [0, d], [0, -d],
                                [d, d], [-d, -d], [d, -d], [-d, d]]) {
          const row = near.row + dr, col = near.col + dc;
          if (row < 2 || col < 2 || row > 250 || col > 155) continue;
          const anchor = heroAnchor(row, col);
          const busy = world.objects.some((object) => {
            const b = object.bounds;
            return b && anchor.x > b.draw_x - margin && anchor.x < b.draw_x + b.width + margin &&
                   anchor.y > b.draw_y - margin && anchor.y < b.draw_y + b.height + margin;
          });
          if (!busy) return { row, col };
        }
      }
    }
    return null;
  }

  function depthAgainstBuildings() {
    const out = [];
    // Правило 7: чистая арифметика по всем объектам карты — рендер не нужен.
    const broken = world.objects.filter((object) => {
      const b = object.bounds;
      if (!b || !b.sort_height) return false;
      return b.sort_y !== object.position.y + b.offset_y + b.sort_height - b.sort_bias;
    });
    out.push({
      rule: "ключ постройки — подошва кадра минус четверть",
      pass: broken.length === 0,
      details: { объектов: world.objects.length, кривых: broken.length,
                 примеры: broken.slice(0, 3).map((o) => ({ slot: o.record_slot,
                   ключ: o.bounds.sort_y,
                   ждём: o.position.y + o.bounds.offset_y + o.bounds.sort_height -
                         o.bounds.sort_bias })) },
    });

    // Правило 8: ключ человека — ноги плюс шесть, и ни точкой больше.
    const bias = unitSortKey(hero) - Math.round(hero.y);
    out.push({ rule: "ключ человека — ноги плюс шесть", pass: bias === 6,
               details: { поправка: bias } });

    // Правила 9 и 10 — картинкой. Берём первую постройку со стенами, крышей
    // и следом: у неё есть и «перед стеной», и «за домом».
    // БЕРЁМ САМУЮ БОЛЬШУЮ ПОСТРОЙКУ, а не первую попавшуюся. У волхва рядом
    // с избой стоит сарай в пять клеток: он человека не закрывает и не
    // должен, а правило судило по нему и краснело на ровном месте.
    const house = world.objects
      .filter((object) => object.frames?.walls && object.frames?.roof &&
                          (object.cells?.footprint ?? []).length > 4)
      .sort((a, b) => b.cells.footprint.length - a.cells.footprint.length)[0];
    if (!house) {
      out.push({ rule: "стена не перекрывает стоящего перед ней", pass: false,
                 details: "на карте нет постройки со стенами, крышей и следом" });
      return out;
    }
    const rows = house.cells.footprint.map(([r]) => r);
    const cols = house.cells.footprint.map(([, c]) => c);
    const midCol = Math.round((Math.min(...cols) + Math.max(...cols)) / 2);
    const southRow = Math.max(...rows), northRow = Math.min(...rows);

    const open = openCell({ row: southRow, col: midCol });
    const whole = open ? heroAt(open.row, open.col).pixels : 0;
    if (!whole) {
      out.push({ rule: "стена не перекрывает стоящего перед ней", pass: false,
                 details: "не нашлось открытой клетки для мерки" });
      return out;
    }

    // ПОРЯДОК СУДИМ СТРОГО, ПИКСЕЛИ — С ЗАПАСОМ.
    //
    // Ключи точны и ломались за день дважды, поэтому сравнение ключей здесь
    // без послаблений. А доля видимых точек зависит от самой постройки: изба
    // волхва низкая и стоящего за ней прикрывает едва наполовину, тогда как
    // изба в деревне прячет целиком. Поэтому строгий порог по пикселям
    // спрашиваем только с построек, которые ВЫШЕ человека.
    const tall = house.bounds.sort_height >= 200;

    // ПЕРЕД стеной: четыре ряда южнее последней клетки следа. Там героя не
    // должно перекрывать ничем — он стоит на улице перед домом.
    const front = heroAt(southRow + 4, midCol);
    const frontShare = front.pixels / whole;
    const frontKey = unitSortKey(hero);
    out.push({
      rule: "стена не перекрывает стоящего перед ней",
      pass: frontKey > house.bounds.sort_y && frontShare > 0.6,
      details: { slot: house.record_slot, клетка: [southRow + 4, midCol],
                 видно: front.pixels, целиком: whole, доля: +frontShare.toFixed(2),
                 ключГероя: frontKey, ключДома: house.bounds.sort_y },
    });

    // ЗА домом: клетку ищем ПОД САМИМ СПРАЙТОМ и за линией глубины, а не
    // «на четыре ряда севернее следа». След и картинка совпадают не всегда:
    // у избы волхва он уводил героя выше спрайта, где его и не должно ничто
    // закрывать, и правило краснело зря. Берём ту клетку, что ближе всех к
    // линии снизу — там перекрытие максимально, и поломка видна сразу.
    let behindRow = northRow - 4;
    let bestKey = -Infinity;
    // ВНУТРЬ ДОМА НЕ ЗАХОДИМ. У большой постройки след почти весь занят полом
    // (у стана Драгомира на карте 164 — 48 клеток из 59), и «самая глубокая
    // клетка перед линией» оказывалась ВНУТРИ. А внутри дома человека канонно
    // видно сквозь стену — это правило 5, — так что доля видимых точек
    // законно уходила за половину.
    //
    // Оговорка: на той же карте 164 правило и после этого краснеет, но уже по
    // другой причине — на оставшейся клетке (109, 57) постройка не закрывает
    // ровно ничего, доля 1.04. Порядок там верен, ключи 1766 против 1866, и
    // стенд tools/scene_depth.js чист; красноту даёт сама донорская постройка,
    // у которой над северной частью следа картинки нет. Разбирать её — в
    // задачах J и H18. На канонных картах прогон полный: 17 из 17.
    const inside = new Set((house.cells?.floor ?? []).map(([r, c]) => `${r}:${c}`));
    for (let row = northRow - 6; row <= southRow; row += 1) {
      if (inside.has(`${row}:${midCol}`)) continue;
      const point = heroAnchor(row, midCol);
      if (point.y < house.bounds.draw_y) continue;                 // выше картинки
      if (point.y > house.bounds.draw_y + house.bounds.height) break;
      const key = Math.round(point.y) + (unitSortKey(hero) - Math.round(hero.y));
      if (key >= house.bounds.sort_y) break;                       // это уже «перед»
      if (key > bestKey) { bestKey = key; behindRow = row; }
    }
    //
    // Порог половинный, а не строгий: голова у стоящего вплотную за домом
    // законно торчит над коньком, и доля живёт около трети. Ловим мы не её,
    // а поломку — когда герой рисуется ПОВЕРХ крыши, доля сразу около
    // единицы, как у стоящего в чистом поле.
    const behind = heroAt(behindRow, midCol);
    const behindShare = behind.pixels / whole;
    // И ПОРЯДОК ТОЖЕ. Одной доли мало: она держится около трети и при
    // сломанных ключах — проверено подменой. А вот сравнение ключей ловит
    // поломку сразу: стоящий за домом обязан идти РАНЬШЕ него.
    const behindKey = unitSortKey(hero);
    out.push({
      rule: "дом перекрывает стоящего за ним",
      pass: behindKey < house.bounds.sort_y && (!tall || behindShare < 0.5),
      // КЛЕТКА — ТА, НА КОТОРОЙ МЕРИЛИ. Здесь печаталось `northRow - 4` —
      // лишь начальное значение, а мерили на выбранной цикле выше. Отчёт
      // уводил на десяток рядов в сторону: разбирая красную строку на карте
      // 164, я по нему считал, что герой стоит СЕВЕРНЕЕ следа, тогда как он
      // стоял внутри него.
      details: { slot: house.record_slot, клетка: [behindRow, midCol],
                 видно: behind.pixels, целиком: whole, доля: +behindShare.toFixed(2),
                 ключГероя: behindKey, ключДома: house.bounds.sort_y,
                 "выше человека": tall },
    });
    return out;
  }

  // ── правила 11-12: житель в доме ───────────────────────────────────────
  //
  // Проверяем НЕ героя, а обычного жителя: у игрока свои ветки (проход
  // здания при бите 21, просвечивающая копия при бите 15), и они уже
  // закрыты правилом 5. У жителя таких поблажек нет, и ломалось именно у
  // него: то он тонул под полом, то резал вырезом собственную крышу.
  function residentInsideBuilding() {
    const rule1 = "житель стоит НА полу дома, а не под ним";
    const rule2 = "крыша прячет жителя в доме";
    // КЛЕТКА НУЖНА И ПОЛА, И МАРШРУТА. «Внутри дома» решает бит 21, а бит 15
    // отвечает за просвечивающую копию; клетка только с полом уходит в общий
    // проход, и правило судило бы не о том. Такие клетки редки — пол почти
    // целиком лежит внутри маршрутных, — но именно на них правило и падало.
    const insideCells = (object) => {
      const routed = new Set((object.cells?.routed ?? []).map(([r, c]) => `${r}:${c}`));
      return (object.cells?.floor ?? []).filter(([r, c]) => routed.has(`${r}:${c}`));
    };
    const house = world.objects.find((object) => object.frames?.walls &&
      object.frames?.roof && insideCells(object).length > 2);
    const unit = units.find((u) => !u.hidden && u.alive !== false && !u.beast);
    if (!house || !unit) {
      return [{ rule: rule1, pass: false,
                details: house ? "на карте нет живого жителя" : "нет постройки с полом" }];
    }
    // КЛЕТКА БЕРЁТСЯ ПОД САМОЙ КРЫШЕЙ, а не первая попавшаяся: у крыльца и
    // у края пола крыши над головой нет, и правило судило бы не о том. Ищем
    // ту, где кадр крыши непрозрачен над грудью жителя.
    const roof = house.frames.roof;
    const roofMask = alphaMask(roof.asset);
    const roofX = house.position.x + roof.offset_x;
    const roofY = house.position.y + roof.offset_y;
    const inside = insideCells(house);
    const under = inside.find(([r, c]) => {
      const point = heroAnchor(r, c);
      return opaqueAt(roofMask, roofX, roofY, point.x, point.y - 40);
    });
    if (!under && roofMask) {
      return [{ rule: rule2, pass: false,
                details: { slot: house.record_slot, причина: "ни одна клетка пола не под крышей" } }];
    }
    const [row, col] = under ?? inside[Math.floor(inside.length / 2)];
    const anchor = heroAnchor(row, col);
    const saved = { x: unit.x, y: unit.y, cell: unit.cell && { ...unit.cell },
                    roofs: showRoofsNode.checked };
    unit.cell = { row, col };
    unit.x = anchor.x;
    unit.y = anchor.y;
    unitUpdateBuilding(unit);
    view.cameraX = anchor.x;
    view.cameraY = anchor.y - 50;
    const box = windowAround(280, 340);
    //: Считаем ЕГО точки: снимок с ним против снимка, где он уведён далеко.
    const pixels = () => {
      const A = shoot(box).data;
      const x = unit.x, y = unit.y;
      unit.x += 4000; unit.y += 4000;
      const B = shoot(box).data;
      unit.x = x; unit.y = y;
      let n = 0;
      for (let i = 0; i < A.length; i += 4) {
        if (medianDiff(A, B, i) > 6) n += 1;
      }
      return n;
    };
    showRoofsNode.checked = false;
    const open = pixels();
    showRoofsNode.checked = true;
    const covered = pixels();
    const drawnByHouse = unit.insideBuilding === house;
    unit.x = saved.x; unit.y = saved.y;
    if (saved.cell) unit.cell = saved.cell;
    unitUpdateBuilding(unit);
    showRoofsNode.checked = saved.roofs;
    return [
      // Под полом он был бы невидим СОВСЕМ: пол рисуется первым и накрыл бы
      // его целиком. Поэтому порог низкий — важно, что его видно вообще, а
      // не сколько. В большом храме Тиграта из-за стен видно всего 96 точек,
      // и это нормально: он внутри, а не под полом.
      { rule: rule1, pass: drawnByHouse && open > 30,
        details: { slot: house.record_slot, клетка: [row, col], кто: unit.name,
                   "рисует дом": drawnByHouse, "видно без крыши": open } },
      // А с крышей его быть не должно: стены и крыша идут после него.
      { rule: rule2, pass: covered < open * 0.5,
        details: { "видно без крыши": open, "видно с крышей": covered,
                   доля: open ? +(covered / open).toFixed(2) : null } },
    ];
  }

  // ── правило 6 ──────────────────────────────────────────────────────────
  function brightFramesStayInPlace() {
    const target = buildings()[0];
    if (!target) return [notApplicable("светлые кадры не текут")];
    daylightSet(NIGHT_TICK);
    placeHero(120, 60);
    view.cameraX = target.position.x;
    view.cameraY = target.position.y;
    const box = windowAround(480, 340);
    const before = shoot(box).data;
    const flags = world.objects.map((object) => object.lighting?.main_static_palette);
    world.objects.forEach((object) => {
      if (object.lighting) object.lighting.main_static_palette = false;
    });
    const after = shoot(box).data;
    world.objects.forEach((object, index) => {
      if (object.lighting) object.lighting.main_static_palette = flags[index];
    });
    // Верхний слой в каждом пикселе: повторяем порядок отрисовки. Кромка
    // кадра помечается отдельно (-1) и в счёт не идёт: один пиксель холста
    // накрывает несколько мировых, и на самой границе силуэта отнести его к
    // слою нельзя — там смесь. Правило про подмену чужих пикселей, а не про
    // то, как ложится шов.
    const top = new Int8Array(box.width * box.height);
    const stamp = (object, layer, kind) => {
      const mask = alphaMask(layer.asset);
      if (!mask) return;
      const originX = object.position.x + (layer.offset_x ?? 0);
      const originY = object.position.y + (layer.offset_y ?? 0);
      for (let y = 0; y < box.height; y += 1) {
        for (let x = 0; x < box.width; x += 1) {
          const p = y * box.width + x;
          const [worldX, worldY] = worldOf(box, x, y);
          if (!opaqueAt(mask, originX, originY, worldX, worldY)) {
            // Полупрозрачная точка кадра — это всё ещё его точка: она
            // смешивается с подложкой и меняется вместе с кадром. Судить
            // её нельзя, но и чужой считать тоже.
            if (top[p] === 0 && opaqueAt(mask, originX, originY, worldX, worldY, 1)) {
              top[p] = -1;
            }
            continue;
          }
          top[p] = deepInside(mask, originX, originY, worldX, worldY) ? kind : -1;
        }
      }
    };
    // ПОЛ ПОСТРОЙКИ — тоже её светлая часть: правило 1 на том и стоит, что
    // интерьер не темнеет. Сквозь прорехи в силуэте видно именно пол, и
    // его пиксель меняется вместе с кадром. Помечаем клетки пола светлыми
    // до того, как поверх лягут сами кадры.
    for (const object of world.objects) {
      if (!object.lighting?.main_static_palette) continue;
      const floor = object.cells?.floor;
      if (!floor?.length) continue;
      const inside = new Set(floor.map(([row, col]) => `${row}:${col}`));
      for (let y = 0; y < box.height; y += 1) {
        for (let x = 0; x < box.width; x += 1) {
          const p = y * box.width + x;
          if (top[p] !== 0) continue;
          const [worldX, worldY] = worldOf(box, x, y);
          const cell = api.heroCellAt?.(worldX, worldY);
          if (cell && inside.has(`${cell.row}:${cell.col}`)) top[p] = 2;
        }
      }
    }

    // Порядок и правило крыши берутся у самого рендера (entities.js), иначе
    // проверка судит кадр по правилу, которого в нём давно нет: здесь жил
    // отдельный гейт «слот меньше тридцати», снятый в отрисовке ещё в
    // мердже «Продолжения легенды».
    const roofOwners = partyRoofBuildings();
    for (const object of world.objects) {
      const frames = object.frames ?? {};
      if (!frames.main) continue;
      stamp(object, frames.main, object.lighting?.main_static_palette ? 2 : 1);
      if (frames.walls) stamp(object, frames.walls, 1);
      if (frames.roof && roofVisible(object, roofOwners)) stamp(object, frames.roof, 1);
    }
    // Тень — не кадр, а затемнение того, что под ней: её пиксель честно
    // меняется вслед за подложкой, и судить его этим правилом нельзя.
    // Помечаем -1 только там, где кадров нет, чтобы не съесть сам силуэт.
    for (const object of world.objects) {
      const shadow = object.frames?.shadow;
      if (!shadow) continue;
      const mask = alphaMask(shadow.asset);
      if (!mask) continue;
      const originX = object.position.x + (shadow.offset_x ?? 0);
      const originY = object.position.y + (shadow.offset_y ?? 0);
      for (let y = 0; y < box.height; y += 1) {
        for (let x = 0; x < box.width; x += 1) {
          const p = y * box.width + x;
          if (top[p] !== 0) continue;
          const [worldX, worldY] = worldOf(box, x, y);
          if (opaqueAt(mask, originX, originY, worldX, worldY)) top[p] = -1;
        }
      }
    }
    // Кромка светлого кадра подмешивается в соседний пиксель холста, и он
    // меняется вместе с ним, хотя принадлежит другому слою. Такой поясок не
    // судим: правило про подмену чужих пикселей, а не про ширину шва. Ширина
    // пояска — сам шов плюс запас, на который выше сузили силуэт: настоящая
    // кромка кадра лежит ровно на этом расстоянии от помеченных пикселей.
    const seam = Math.max(1, Math.ceil((insideRadius() + 1) * view.zoom * view.dpr));
    const edge = new Int8Array(top.length);
    for (let y = 0; y < box.height; y += 1) {
      for (let x = 0; x < box.width; x += 1) {
        if (top[y * box.width + x] !== 2) continue;
        for (let dy = -seam; dy <= seam; dy += 1) {
          for (let dx = -seam; dx <= seam; dx += 1) {
            const nx = x + dx, ny = y + dy;
            if (nx < 0 || ny < 0 || nx >= box.width || ny >= box.height) continue;
            if (top[ny * box.width + nx] !== 2) edge[ny * box.width + nx] = 1;
          }
        }
      }
    }
    // Насколько далеко от светлого кадра оказался чужой изменившийся пиксель:
    // рядом — это шов, далеко — настоящая протечка, и её надо чинить в рендере.
    const distanceToBright = (p) => {
      const x0 = p % box.width, y0 = (p / box.width) | 0;
      for (let r = 1; r <= 8; r += 1) {
        for (let dy = -r; dy <= r; dy += 1) {
          for (let dx = -r; dx <= r; dx += 1) {
            if (Math.max(Math.abs(dx), Math.abs(dy)) !== r) continue;
            const nx = x0 + dx, ny = y0 + dy;
            if (nx < 0 || ny < 0 || nx >= box.width || ny >= box.height) continue;
            if (top[ny * box.width + nx] === 2) return r;
          }
        }
      }
      return 9;
    };

    let onBright = 0, elsewhere = 0, brightPixels = 0;
    const away = {};
    // Где именно протекло: без этого «один чужой пиксель» не найти.
    const spots = [];
    for (let i = 0, p = 0; i < before.length; i += 4, p += 1) {
      if (top[p] === 2) brightPixels += 1;
      if (top[p] === -1 || edge[p]) continue;      // шов силуэта не судим
      if (medianDiff(before, after, i) > 6) {
        if (top[p] === 2) {
          onBright += 1;
        } else {
          elsewhere += 1;
          const r = distanceToBright(p);
          away[r] = (away[r] ?? 0) + 1;
          if (spots.length < 5) {
            const x = p % box.width, y = (p / box.width) | 0;
            const [worldX, worldY] = worldOf(box, x, y);
            spots.push({ x, y, слой: top[p], мир: [Math.round(worldX), Math.round(worldY)],
                         было: [before[i], before[i + 1], before[i + 2]],
                         стало: [after[i], after[i + 1], after[i + 2]] });
          }
        }
      }
    }
    return [{
      rule: "светлые кадры не подменяют чужие пиксели",
      pass: elsewhere === 0 && onBright > 0,
      details: { видимыхПикселейMain: brightPixels, изменилосьНаНих: onBright,
                 изменилосьВнеИх: elsewhere, поРасстояниюОтКадра: away,
                 где: spots },
    }];
  }

  // Правило героя и сейва: пустышка Б1 не должна ни жить, ни лежать в
  // хранилище. Герой собирается из shared.json -> hero.template
  // (progressSetup), и его отпечаток проверяется числами: навыки не могут
  // быть все нулями при живом шаблоне, характеристики «все по 10» — это
  // фолбэк без шаблона, а здоровье героя задаёт сам шаблон. Сейв в
  // хранилище меряется той же меркой, что и запись (saveUsable): пустышка,
  // однажды записанная, иначе пережила бы починку пака и затирала героя
  // на каждом буте.
  function saveContract() {
    const data = hero.data ?? {};
    const template = data.template ?? null;
    const names = data.rules?.progression?.skills?.names ?? [];
    const skills = hero.skills ?? [];
    const chars = hero.characteristics ?? [];
    const dummy = skills.length > 0 && skills.every((value) => !value) &&
      chars.length > 0 && chars.every((value) => value === 10);
    const heroPass = Boolean(template) && !dummy &&
      skills.length === names.length &&
      // Сверять надо ТЕКУЩЕЕ здоровье с шаблоном, а не потолок: потолок один
      // на всех (0x640, VA 0x41C494), а стартовое здоровье у героев разное —
      // Эйнар в GAME.2 начинает раненым, с 640. Прежняя проверка сравнивала
      // потолок и потому закрепляла ошибку `maxHealth = стартовое здоровье`.
      (template?.health == null || hero.health === template.health);
    const stored = saveHealth();
    return [
      {
        rule: "герой собран из шаблона пака, не пустышка",
        pass: heroPass,
        details: {
          шаблон: Boolean(template), пустышка: dummy,
          навыков: skills.length, имён: names.length,
          здоровье: hero.health ?? null,
          максЗдоровье: hero.maxHealth ?? null,
          здоровьеШаблона: template?.health ?? null,
        },
      },
      {
        rule: "сейв в хранилище проходит проверку записи",
        pass: !stored.present || stored.usable === true,
        details: stored,
      },
    ];
  }

  // Правила звука — чистая арифметика против эталонов движка, рендер не
  // нужен. Эталоны позиционной громкости сняты с VA 0x43BC74 (целочисленное
  // деление с усечением), пана — с 0x43BC20 (fistp = банковское округление).
  function audioContract() {
    const snd = api.sound;
    const stats = api.soundStats?.();
    if (!snd?.ready) {
      return [{ rule: "звук: канон загружен", pass: false,
                details: { готов: Boolean(snd?.ready) } }];
    }
    const volumePoints = [[0, 0], [1024, -5000], [2048, -10000],
                          [2049, -10000], [819, -3999], [820, -4003]];
    const volumeOk = volumePoints.every(([d, expected]) =>
      api.positionVolume(d) === expected);
    const panPoints = [[0, 0], [4, 250], [-4, -250], [1, 62], [3, 188]];
    const panOk = panPoints.every(([d, expected]) => api.positionPan(d) === expected);
    const rules = snd.rules;
    return [
      {
        rule: "звук: формулы позиционки совпадают с движком",
        pass: volumeOk && panOk,
        details: {
          громкость: Object.fromEntries(volumePoints.map(([d]) =>
            [d, api.positionVolume(d)])),
          пан: Object.fromEntries(panPoints.map(([d]) => [d, api.positionPan(d)])),
        },
      },
      {
        rule: "звук: пороги и лимиты канона на месте",
        pass: rules.mixer.max_buffers === 45 &&
          rules.mixer.volume_gate === -4000 &&
          rules.position.hearing_radius === 2048 &&
          rules.pitch.rates.length === 3 &&
          (stats?.активных ?? 0) <= rules.mixer.max_buffers,
        details: { ...rules.mixer, радиус: rules.position.hearing_radius,
                   активных: stats?.активных ?? 0 },
      },
      {
        rule: "звук: очередь карты и вечный набор живут",
        pass: (stats?.буферов ?? 0) > 0,
        details: stats ?? {},
      },
    ];
  }

  return function selfcheck({ quiet = false } = {}) {
    if (!world.map) return [{ rule: "карта не загружена", pass: false }];
    // Кривая суток приезжает отдельным запросом уже после первого кадра.
    // Пока её нет, daylightSet честно ставит нулевые уровни, день и ночь
    // выходят одинаковыми, и четыре правила из шести валятся на ровном
    // месте. Лучше молчать, чем мерить в этой щели.
    if (!api.daylight.curves.moon.length && !api.daylight.curves.no_moon.length) {
      return [{ rule: "кривая суток ещё не загружена", pass: false }];
    }
    // СХЛОПНУТЫЙ ХОЛСТ. В скрытой панели браузера rAF мёртв и холст сжат в
    // 1x1 — все пиксельные правила тогда меряют один чёрный пиксель и
    // «падают» на ровном месте (а «интерьер» с одним пикселем даже
    // «проходит»). Такой прогон уже дважды выдавал ложную картину поломки
    // рендера. resize() восстанавливает и холст, и offscreen-слои — чинить
    // надо ИМ, а не ручным canvas.width: слои иначе остаются 1x1 и рендер
    // складывает кадр из мусора. Если после resize холст всё ещё пуст
    // (панель свёрнута совсем) — молчим, как и без кривой суток.
    if (canvas.width <= 2 || canvas.height <= 2) resize();
    if (canvas.width <= 2 || canvas.height <= 2) {
      return [{ rule: "холст схлопнут — панель браузера скрыта", pass: false,
                details: { ширина: canvas.width, высота: canvas.height } }];
    }
    const saved = {
      time: api.daylight.time, zoom: view.zoom,
      cameraX: view.cameraX, cameraY: view.cameraY,
      cell: hero.cell && { ...hero.cell }, roofs: showRoofsNode.checked,
      ambient: ambientNode.checked, clock: clockRunNode.checked,
    };
    view.zoom = 1;
    showRoofsNode.checked = false;
    // Атмосфера и ход часов — наши процедурные расширения, они меняются между
    // двумя снимками и делают сравнение «день против ночи» случайным. На время
    // прогона выключаем: правила движка от них не зависят.
    ambientNode.checked = false;
    clockRunNode.checked = false;
    let checks = [];
    try {
      checks = [
        ...interiorNeverDarkens(),
        ...glowOnlyAdds(),
        ...gateFollowsSchedule(),
        ...heroVisibleIndoors(),
        ...brightFramesStayInPlace(),
        ...depthAgainstBuildings(),
        ...residentInsideBuilding(),
        ...saveContract(),
        ...audioContract(),
      ];
    } finally {
      showRoofsNode.checked = saved.roofs;
      ambientNode.checked = saved.ambient;
      clockRunNode.checked = saved.clock;
      view.zoom = saved.zoom;
      view.cameraX = saved.cameraX;
      view.cameraY = saved.cameraY;
      if (saved.cell) placeHero(saved.cell.row, saved.cell.col);
      daylightSet(saved.time);
      render();
    }
    if (!quiet) {
      const failed = checks.filter((check) => !check.pass);
      console.log(`%cсамопроверка: ${checks.length - failed.length}/${checks.length}`,
        failed.length ? "color:#c33" : "color:#3a3");
      console.table(checks.map((check) => ({ правило: check.rule, ок: check.pass })));
      for (const check of checks) console.log(check.rule, check.details);
    }
    return checks;
  };
}
