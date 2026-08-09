// Тени: маски копятся в отдельном слое и делят яркость кадра пополам.
import { canvas, dynamicShadowsNode } from "./dom.js";
import { world } from "./world.js";
import { drawSprite, spriteReady, context, view } from "./viewport.js";
import { daylight, daylightCurve, sunProgress } from "./daylight.js";
import { hero, heroBodyFrame } from "./hero.js";
import { sheetsFor, actorFrame } from "./actor.js";
import { units } from "./units.js";

// Тени: маски объектов регистрируются спанами (VA 0x43F260), затем один
// проход VA 0x440788 делит яркость фона под ними пополам, не затемняя
// перекрытия дважды. Здесь маски копятся в offscreen-слое и накладываются
// на кадр один раз с альфой 0.5 — арифметика та же: bg/2.
export const shadows = { canvas: document.createElement("canvas"), context: null };

shadows.context = shadows.canvas.getContext("2d");

// Настройки прохода: одни и те же для теней сцены и для теней внутри
// постройки, поэтому считаются в одном месте.
function shadowSettings() {
  const dynamic = dynamicShadowsNode.checked && daylightCurve().length > 0;
  const sun = dynamic ? sunProgress(daylight.time) : null;
  const night = dynamic && sun === null;
  const altitude = night ? 0 : (sun === null ? 1 : Math.sin(sun * Math.PI));
  const smear = dynamic ? Math.round(130 * Math.max(0, 1 - altitude * 1.15)) : 0;
  return {
    dynamic, smear, smearStep: 11,
    alpha: dynamic ? 0.35 + 0.15 * altitude : 0.5,
    lightX: -0.95, lightY: 0.32,
    reach: smear + 64,
  };
}

// Тень одного актёра в маску. Возвращает false, если кадра или картинки
// ещё нет.
function paintActorShadow(target, actor, frame, set) {
  const shadow = frame?.shadow;
  if (!spriteReady(world.images, sheetsFor(actor), shadow)) return false;
  const x = Math.round(actor.x) + shadow.offset_x;
  const y = Math.round(actor.y) + shadow.offset_y;
  drawSprite(world.images, sheetsFor(actor), shadow, x, y, target);
  if (set.dynamic && set.smear > 0) {
    const steps = Math.max(1, Math.round(set.smear / set.smearStep));
    for (let i = 1; i <= steps; i += 1) {
      const shift = set.smear * i / steps;
      drawSprite(world.images, sheetsFor(actor), shadow,
                 x + set.lightX * shift, y + set.lightY * shift, target);
    }
  }
  return true;
}

function prepareMask() {
  if (shadows.canvas.width !== canvas.width ||
      shadows.canvas.height !== canvas.height) {
    shadows.canvas.width = canvas.width;
    shadows.canvas.height = canvas.height;
  }
  shadows.context.setTransform(1, 0, 0, 1, 0, 0);
  shadows.context.clearRect(0, 0, shadows.canvas.width, shadows.canvas.height);
  shadows.context.setTransform(context.getTransform());
  shadows.context.imageSmoothingEnabled = false;
}

function stampMask(alpha) {
  context.save();
  context.setTransform(1, 0, 0, 1, 0, 0);
  context.globalCompositeOperation = "source-over";
  context.globalAlpha = alpha;
  context.drawImage(shadows.canvas, 0, 0);
  context.restore();
}

// ТЕНИ ЮНИТОВ ВНУТРИ ПОСТРОЙКИ — отдельным проходом, в самой постройке.
//
// Так делает движок: проход содержимого постройки (VA 0x424514) сам
// перебирает её юнитов, регистрирует их теневые спаны (0x43F260) и тут же
// применяет затемнение (0x440788) — то есть тень ложится ПОСЛЕ пола.
// В общем проходе сцены её рисовать нельзя: он идёт до построек, и пол
// накрывает тень целиком. Оттого у всех, кто зашёл в дом, тени и пропадали.
//
// Маска копится и накладывается один раз на всю постройку — иначе
// перекрывающиеся тени двух человек в одной избе затемнили бы фон дважды,
// чего спановый список движка не допускает.
export function renderInsideShadows(actors) {
  if (!actors.length) return;
  const set = shadowSettings();
  let any = false;
  for (const { actor, frame } of actors) {
    if (!any) prepareMask();          // чистим маску перед первой удачной тенью
    if (paintActorShadow(shadows.context, actor, frame, set)) any = true;
  }
  if (any) stampMask(set.alpha);
}

export function renderShadows(visible) {
  // «Живые тени» — наше расширение поверх движка. Никаких трансформаций
  // маски: исходная копия всегда рисуется на своём месте (примыкание к
  // стене не может оторваться по построению), а удлинение при низком
  // солнце — это дорисовка копий, сдвинутых вдоль направления света:
  // объединение копий и есть вытянутая тень. Ночью остаётся статичная
  // маска, как в оригинале (спановое затемнение фона не зависит от
  // времени суток) — исчезает только солнечное удлинение.
  const dynamic = dynamicShadowsNode.checked && daylightCurve().length > 0;
  const sun = dynamic ? sunProgress(daylight.time) : null;
  // Ночью солнце под горизонтом: удлинение не сбрасывается, а замирает на
  // закатной длине — тень остаётся такой, какой её оставил закат.
  const night = dynamic && sun === null;
  const altitude = night ? 0 : (sun === null ? 1 : Math.sin(sun * Math.PI));
  // Общее направление теней игры: влево-вниз (по данным масок).
  const lightX = -0.95, lightY = 0.32;
  const smear = dynamic ? Math.round(130 * Math.max(0, 1 - altitude * 1.15)) : 0;
  const smearStep = 11;
  const alpha = dynamic ? 0.35 + 0.15 * altitude : 0.5;
  const reach = smear + 64;                    // запас клипа под смаз

  let any = false;
  const debug = { drawn: 0, noLayer: 0, offscreen: 0, noImage: 0 };
  window.__shadowDebug = debug;
  for (const object of world.objects) {
    const layer = object.frames?.shadow;
    if (!layer) { debug.noLayer += 1; continue; }
    const maskLeft = object.position.x + layer.offset_x - reach;
    const maskTop = object.position.y + layer.offset_y - reach;
    if (maskLeft > visible.right || maskTop > visible.bottom ||
        maskLeft + layer.width + reach * 2 < visible.left ||
        maskTop + layer.height + reach * 2 < visible.top) {
      debug.offscreen += 1;
      continue;
    }
    const image = world.images.get(layer.asset);
    if (!image) { debug.noImage += 1; continue; }
    debug.drawn += 1;
    if (!any) {
      if (shadows.canvas.width !== canvas.width ||
          shadows.canvas.height !== canvas.height) {
        shadows.canvas.width = canvas.width;
        shadows.canvas.height = canvas.height;
      }
      shadows.context.setTransform(1, 0, 0, 1, 0, 0);
      shadows.context.clearRect(0, 0, shadows.canvas.width, shadows.canvas.height);
      shadows.context.setTransform(context.getTransform());
      shadows.context.imageSmoothingEnabled = false;
      any = true;
    }
    const maskX = object.position.x + layer.offset_x;
    const maskY = object.position.y + layer.offset_y;
    shadows.context.drawImage(image, maskX, maskY);
    if (dynamic && smear > 0) {
      const steps = Math.max(1, Math.round(smear / smearStep));
      for (let i = 1; i <= steps; i += 1) {
        const shift = smear * i / steps;
        shadows.context.drawImage(image,
          maskX + lightX * shift, maskY + lightY * shift);
      }
    }
  }
  // Тень юнита движок регистрирует теми же спанами, что тени построек
  // (VA 0x426047 -> 0x43F260), поэтому кладём её в ту же маску: иначе
  // полупрозрачная тень внутри слоя ловит заливку фильтра и сереет.
  // Тень у юнита та же, что у героя: она лежит в самой записи кадра и от
  // палитры не зависит, поэтому разбойники отбрасывают её ровно так же.
  //
  // ТЕХ, КТО В ПОСТРОЙКЕ, ЗДЕСЬ НЕТ: их тени рисует сама постройка после
  // пола (renderInsideShadows), как и движок в проходе 0x424514. Иначе тень
  // ложится на землю, а сверху её накрывает пол — и человек в доме стоит
  // без тени.
  const actors = hero.data ? [{ actor: hero, frame: heroBodyFrame() },
                              ...units.map((unit) => ({ actor: unit,
                                frame: actorFrame(hero.data, unit) }))]
    .filter(({ actor }) => actor.insideSlot == null) : [];
  for (const { actor, frame } of actors) {
    const shadow = frame?.shadow;
    // Тень кадра лежит на тех же листах, что и тело: у неё прямоугольник
    // на листе, а не свой файл.
    if (!spriteReady(world.images, sheetsFor(actor), shadow)) continue;
    if (!any) {
      if (shadows.canvas.width !== canvas.width ||
          shadows.canvas.height !== canvas.height) {
        shadows.canvas.width = canvas.width;
        shadows.canvas.height = canvas.height;
      }
      shadows.context.setTransform(1, 0, 0, 1, 0, 0);
      shadows.context.clearRect(0, 0, shadows.canvas.width, shadows.canvas.height);
      shadows.context.setTransform(context.getTransform());
      shadows.context.imageSmoothingEnabled = false;
      any = true;
    }
    // Живая тень юнита — то же расширение, что у построек, и тем же
    // способом: исходная маска на своём месте, а удлинение при низком
    // солнце — копии, сдвинутые вдоль света. Иначе выходит несуразица:
    // изба на закате тянет тень через полдвора, а идущий рядом человек
    // стоит с полуденным пятном под ногами.
    //
    // В движке тень юнита СТАТИЧНА: это готовый спрайт из записи кадра
    // (VA 0x426047 кладёт её теми же спанами, что и тени построек). Так
    // что удлинение — наше, и живёт оно под тем же переключателем.
    const shadowX = Math.round(actor.x) + shadow.offset_x;
    const shadowY = Math.round(actor.y) + shadow.offset_y;
    drawSprite(world.images, sheetsFor(actor), shadow, shadowX, shadowY,
               shadows.context);
    if (dynamic && smear > 0) {
      const steps = Math.max(1, Math.round(smear / smearStep));
      for (let i = 1; i <= steps; i += 1) {
        const shift = smear * i / steps;
        drawSprite(world.images, sheetsFor(actor), shadow,
                   shadowX + lightX * shift, shadowY + lightY * shift,
                   shadows.context);
      }
    }
  }

  if (!any) return;
  // Проход VA 0x440788 делит яркость фрейм-буфера под отрезками пополам,
  // то есть тень ложится на всё, что уже нарисовано, — и на обычную землю,
  // и на освещённые клетки. Поэтому маски накладываются на СОБРАННЫЙ кадр
  // (земля + аура), а не внутрь слоя сцены: полупрозрачная тень над
  // прозрачным местом слоя ловила заливку фильтра и светлела.
  context.save();
  context.setTransform(1, 0, 0, 1, 0, 0);
  context.globalCompositeOperation = "source-over";
  context.globalAlpha = alpha;
  context.drawImage(shadows.canvas, 0, 0);
  context.restore();
}
