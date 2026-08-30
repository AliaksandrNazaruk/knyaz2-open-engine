// Тени: маски копятся в отдельном слое и делят яркость кадра пополам.
import { canvas, dynamicShadowsNode } from "./dom.js";
import { world } from "./world.js";
import { drawSprite, spriteReady, context, view,
         withMainContext } from "./viewport.js";
import { daylight, daylightCurve, sunProgress } from "./daylight.js";
import { hero, heroBodyFrame } from "./hero.js";
import { sheetsFor, actorFrame } from "./actor.js";
import { units } from "./units.js";
import { drawPlane, drawPlanePart, perspective } from "./perspective.js";

// Тени: маски объектов регистрируются спанами (VA 0x43F260), затем один
// проход VA 0x440788 делит яркость фона под ними пополам, не затемняя
// перекрытия дважды. Здесь маски копятся в offscreen-слое и накладываются
// на кадр один раз с альфой 0.5 — арифметика та же: bg/2.
//: Два холста, а не один. В `canvas` тени копятся КАЖДАЯ ПО ОДНОМУ РАЗУ, а
//: `smear` собирает из него вытянутую тень сдвинутыми копиями. Раньше копии
//: рисовались на каждую тень отдельно, и цена кадра росла как «объекты ×
//: шаги»: на Кирингхольме ночью это 10 829 отрисовок только на тени.
export const shadows = {
  canvas: document.createElement("canvas"), context: null,
  smear: document.createElement("canvas"), smearContext: null,
};

shadows.context = shadows.canvas.getContext("2d");
shadows.smearContext = shadows.smear.getContext("2d");

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
  //: Тень кладётся ОДИН РАЗ. Вытягивание при низком солнце делает `finishMask`
  //: над собранной маской — см. там, почему это то же самое и почему дешевле.
  drawSprite(world.images, sheetsFor(actor), shadow, x, y, target);
  return true;
}

//: СМАЗ ДЕЛАЕТСЯ НАД СОБРАННОЙ МАСКОЙ, А НЕ НАД КАЖДОЙ ТЕНЬЮ.
//
// Сдвиг у всех теней один и тот же — направление света, — поэтому
// объединение N сдвинутых копий каждой тени и N сдвинутых копий всей маски
// это одно и то же множество точек. А цена разная: было `(1 + N)` отрисовок
// НА КАЖДЫЙ объект, стало `(1 + N)` полноэкранных блитов на весь кадр. Ночью
// N = 12, и на Кирингхольме это 10 829 отрисовок против 13.
//
// КОПИИ БЕРУТСЯ С БАЗЫ, А НЕ С НАКОПЛЕННОГО. Рисовать маску саму в себя
// нельзя: каждый следующий шаг размазывал бы уже размазанное, и тень уползла
// бы много дальше положенного. Поэтому холста два.
//
// Мировой сдвиг переводится в пиксели холста масштабом самого кадра
// (`getTransform`), а не пересчётом zoom×dpr вручную: так он не разъедется с
// тем, чем нарисована сама маска.
function finishMask(set) {
  if (!set.dynamic || set.smear <= 0) return shadows.canvas;
  const steps = Math.max(1, Math.round(set.smear / set.smearStep));
  const { a, d } = context.getTransform();
  if (shadows.smear.width !== shadows.canvas.width ||
      shadows.smear.height !== shadows.canvas.height) {
    shadows.smear.width = shadows.canvas.width;
    shadows.smear.height = shadows.canvas.height;
  }
  const target = shadows.smearContext;
  target.setTransform(1, 0, 0, 1, 0, 0);
  target.clearRect(0, 0, shadows.smear.width, shadows.smear.height);
  target.imageSmoothingEnabled = false;
  target.drawImage(shadows.canvas, 0, 0);
  for (let i = 1; i <= steps; i += 1) {
    const shift = set.smear * i / steps;
    target.drawImage(shadows.canvas,
                     set.lightX * shift * a, set.lightY * shift * d);
  }
  return shadows.smear;
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

// Приложить накопленную маску. `onMain` кладёт её МИМО слоя сцены — прямо на
// кадр, как это делает светлый кадр интерьера (`drawBrightImage`).
//
// Иначе тень сереет, и вот почему. Слой сцены заливается фильтром суток
// целиком (`endSceneLayer` → `applyDaylight`), а у фильтра есть не только
// множитель, но и ПРИБАВКА (движковый «плюс к максимуму», VA 0x43CA8B):
// затемнённый тенью пиксель она поднимает обратно, и вместо тени выходит
// светлое серое пятно. Уличные тени этого избегают тем, что штампуются между
// закрытием слоя земли и открытием слоя объектов (scene.js), — то есть на
// сам кадр. Интерьерная тень рисуется изнутри постройки и до этой правки
// ложилась в слой.
//
// Класть её на кадр можно ровно потому, что пол интерьера тоже там: он
// рисуется светлым кадром мимо слоя (VA 0x425B0C — исходная палитра, без
// пересчёта под сутки). Слой объектов ляжет сверху и накроет тень стенами и
// фигурами, а порядок «после пола, до людей» сохранится.
function stampMask(alpha, onMain = false, source = shadows.canvas) {
  const put = () => {
    context.save();
    context.setTransform(1, 0, 0, 1, 0, 0);
    context.globalCompositeOperation = "source-over";
    context.globalAlpha = alpha;
    context.drawImage(source, 0, 0);
    context.restore();
  };
  if (onMain) withMainContext(put);
  else put();
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
export function renderInsideShadows(actors, onMain = false) {
  if (!actors.length) return;
  const set = shadowSettings();
  let any = false;
  for (const { actor, frame } of actors) {
    if (!any) prepareMask();          // чистим маску перед первой удачной тенью
    if (paintActorShadow(shadows.context, actor, frame, set)) any = true;
  }
  //: Пол интерьера лежит на кадре мимо слоя — значит и тень туда же, иначе
  //: заливка фильтра поднимет её до серого пятна (см. stampMask).
  if (any) stampMask(set.alpha, onMain, finishMask(set));
}

export function renderShadows(visible) {
  // «Живые тени» — наше расширение поверх движка. Никаких трансформаций
  // маски: исходная копия всегда рисуется на своём месте (примыкание к
  // стене не может оторваться по построению), а удлинение при низком
  // солнце — это дорисовка копий, сдвинутых вдоль направления света:
  // объединение копий и есть вытянутая тень. Ночью остаётся статичная
  // маска, как в оригинале (спановое затемнение фона не зависит от
  // времени суток) — исчезает только солнечное удлинение.
  //: Настройки прохода считает `shadowSettings` — одна на тени сцены и на
  //: тени внутри постройки. Здесь они пересчитывались вторым экземпляром, и
  //: две копии одной формулы уже расходились бы молча.
  const set = shadowSettings();
  const reach = set.reach;                     // запас клипа под смаз

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
    if (!any) { prepareMask(); any = true; }
    //: Тень объекта — ОДИН раз; вытягивание делает `finishMask` над всей
    //: собранной маской.
    //: ТЕНЬ ЛЕЖИТ НА ЗЕМЛЕ — и корёжится по закону ЗЕМЛИ, полосами по своим
    //: строкам, как вода и пятна света. Спрайтовое правило (один масштаб по
    //: якорю хозяина) держит её у ног, но при движении камеры она ползёт
    //: относительно грунта: у плоскости и у спрайта законы разные.
    //:
    //: Полосуем КАЖДУЮ ТЕНЬ, а не всю маску разом: маска размером с экран, и
    //: её укладка полосами стоила сотни блитов на кадр — кадр рвался на
    //: глазах. Здесь цена идёт по площади теней и укладывается в бюджет.
    drawPlane(shadows.context, image,
              object.position.x + layer.offset_x,
              object.position.y + layer.offset_y, layer.width, layer.height);
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
    .filter(({ actor }) => actor.insideBuilding == null) : [];
  for (const { actor, frame } of actors) {
    const shadow = frame?.shadow;
    // Тень кадра лежит на тех же листах, что и тело: у неё прямоугольник
    // на листе, а не свой файл.
    if (!spriteReady(world.images, sheetsFor(actor), shadow)) continue;
    if (!any) { prepareMask(); any = true; }
    // Живая тень юнита — то же расширение, что у построек, и тем же
    // способом: исходная маска на своём месте, а удлинение при низком
    // солнце — копии, сдвинутые вдоль света. Иначе выходит несуразица:
    // изба на закате тянет тень через полдвора, а идущий рядом человек
    // стоит с полуденным пятном под ногами.
    //
    // В движке тень юнита СТАТИЧНА: это готовый спрайт из записи кадра
    // (VA 0x426047 кладёт её теми же спанами, что и тени построек). Так
    // что удлинение — наше, и живёт оно под тем же переключателем.
    const sheets = sheetsFor(actor);
    const sheet = shadow.sheet !== undefined ? sheets?.[shadow.sheet] : null;
    const image = sheet ? world.images.get(sheet.path)
                        : world.images.get(shadow.path);
    const atX = Math.round(actor.x) + shadow.offset_x;
    const atY = Math.round(actor.y) + shadow.offset_y;
    //: Плоскостью — только когда у кадра есть и картинка, и размеры. У
    //: кадра-файла (без листа) их могло бы не быть; тогда обычная укладка.
    if (perspective.on && image && shadow.width > 0 && shadow.height > 0) {
      drawPlanePart(shadows.context, image,
                    sheet ? shadow.x : 0, sheet ? shadow.y : 0,
                    shadow.width, shadow.height,
                    atX, atY, shadow.width, shadow.height);
    } else {
      drawSprite(world.images, sheets, shadow, atX, atY, shadows.context);
    }
  }

  if (!any) return;
  // Проход VA 0x440788 делит яркость фрейм-буфера под отрезками пополам,
  // то есть тень ложится на всё, что уже нарисовано, — и на обычную землю,
  // и на освещённые клетки. Поэтому маски накладываются на СОБРАННЫЙ кадр
  // (земля + аура), а не внутрь слоя сцены: полупрозрачная тень над
  // прозрачным местом слоя ловила заливку фильтра и светлела.
  stampMask(set.alpha, false, finishMask(set));
}
