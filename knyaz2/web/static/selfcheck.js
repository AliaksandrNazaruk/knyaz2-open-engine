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

import { saveHealth } from "./save.js";
import { resize } from "./viewport.js";
import { heroSheets } from "./actor.js";

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
  function interiorNeverDarkens() {
    const results = [];
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
    return [{
      rule: "персонаж виден в доме",
      pass: Object.values(results).every((r) => r.доля > 0.9),
      details: results,
    }];
  }

  // ── правило 6 ──────────────────────────────────────────────────────────
  function brightFramesStayInPlace() {
    const target = buildings()[0];
    if (!target) return [{ rule: "светлые кадры не текут", pass: false, details: "нет построек" }];
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

    for (const object of world.objects) {
      const frames = object.frames ?? {};
      if (!frames.main) continue;
      stamp(object, frames.main, object.lighting?.main_static_palette ? 2 : 1);
      if (frames.walls) stamp(object, frames.walls, 1);
      if (frames.roof && object.record_slot < 30 && showRoofsNode.checked) {
        stamp(object, frames.roof, 1);
      }
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
