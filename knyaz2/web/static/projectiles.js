// Летящие стрелы.
//
// В движке это отдельный массив снарядов (0x833AE8, до ста записей по 32
// байта), который заполняет выстрел VA 0x41BB10:
//
//     +0x00 шаг по X за такт, +0x04 шаг по Y — делятся на длину пути,
//           поэтому снаряд летит по прямой; константа шага 0x450128 =
//           0.25 (прочитана из exe), но ЕДИНИЦА НЕ СНЯТА — FPU-код шага
//           съеден декомпилятором. Наши 4 пикселя за подшаг — калибровка
//           на глаз; вопрос записан в COMBAT_SPEC §10
//     +0x08 X, +0x0C Y снаряда
//     +0x14 номер стрелка, +0x1B его сторона
//     +0x1A кадр: направление * 2 − 0x48 как беззнаковый байт — это же и
//           номер спрайта INTERF.RES, а второй кадр мигает наконечником
//           (VA 0x424454)
//     +0x1F точность именно этого выстрела
//
// Рисуются они вместе со всеми (список 0x85EF3C, вид 1), поэтому и у нас
// стрела летит в сцене, а не поверх неё.
import { world } from "./world.js";
import { tickSeconds } from "./clock.js";
import { context } from "./viewport.js";
import { heroCellAt } from "./hero.js";
import { buildingAtCell } from "./buildings.js";
import { withPerspective } from "./perspective.js";

export const projectiles = [];

//: СВОЙ СНАРЯД. У канонной стрелы кадры лежат в интерфейсе карты: пара
//: кадров на направление, и мигают они наконечником. Свой снаряд несёт имя
//: набора из пака (project/projectiles), а в наборе восемь направлений с
//: любым числом кадров и вспышка попадания. Всё, что нужно выстрелу, —
//: поле `sprite` с этим именем.
function spriteSet(name) {
  return name ? (world.map?.projectiles?.sets?.[name] ?? null) : null;
}

//: Вспышки попадания живут отдельно от снарядов: снаряда уже нет, а огонь
//: на его месте ещё горит. Кадр вспышки идёт по такту, как и у снаряда.
export const bursts = [];

function rules() { return world.map?.hero?.rules?.accuracy?.projectiles ?? null; }

export function projectileAssets() {
  const sheets = world.map?.interface?.projectiles ?? [];
  const arrows = sheets.flat().filter(Boolean).map((sprite) => sprite.path);
  //: ЛИСТЫ СВОИХ СНАРЯДОВ — СЮДА ЖЕ. Без них ни шар, ни вспышка не рисуются
  //: вовсе: `drawOwn` молча уходит, когда картинки нет в наборе, — а взять
  //: её на лету неоткуда, лист один на весь пак.
  const own = (world.map?.projectiles?.sheets ?? [])
    .map((sheet) => sheet?.path).filter(Boolean);
  return [...arrows, ...own];
}

// Выстрел: снаряд вылетает из стрелка по направлению на цель и живёт
// столько тактов, какова дальность оружия в клетках (VA 0x41BB10).
//
// `snapshot` — СНИМОК УДАРА, снятый в миг выстрела. Так делает движок:
// когда стрела долетела, резолвер получает жертву, силу, посчитанную ИЗ
// ЗАПИСИ СНАРЯДА (VA 0x41A52C), и байт записи +0x1F — самого стрелка он не
// видит вовсе, а находит потом по индексу, только чтобы начислить опыт
// (VA 0x41FDD0: `FUN_0041a52c(жертва, снаряд)` → `FUN_0041bf54(жертва,
// сила, снаряд[0x1F])`). Иначе выходит, что за время полёта у стрелка
// сменилось оружие, кончились стрелы или он сам умер — и стрела бьёт по
// новым числам.
//: `height` — на какой высоте над землёй летит снаряд. У канонной стрелы это
//: 30 точек: движок пускает её от пояса, и кадр стрелы нарисован без своего
//: подъёма. У СВОЕГО снаряда подъём нарисован в самом кадре (диабловская
//: привязка к земле: огненный шар сидит на 54 точках над своей точкой), и
//: поднимать его ещё раз кодом значит задрать огонь выше головы.
export function projectileFire(shooter, target, accuracy = 0, weapon = null,
                               snapshot = null, height = 30) {
  const set = rules();
  if (!set || projectiles.length >= (set.limit ?? 100)) return null;
  const dx = target.x - shooter.x;
  const dy = (target.y - height) - shooter.y;
  const length = Math.max(1, Math.max(Math.abs(dx), Math.abs(dy)));
  const speed = set.speed ?? 4;
  const shot = {
    x: shooter.x, y: shooter.y - height,
    stepX: (dx / length) * speed,
    stepY: (dy / length) * speed,
    direction: shooter.direction ?? 0,
    frame: 0,
    // жизнь снаряда — дальность оружия в клетках, по такту на клетку
    life: Math.max(1, weapon?.range_cells ?? 15),
    accuracy,
    // сила и отрава этого выстрела — то, что движок держит в самой записи
    strength: snapshot?.strength ?? 0,
    venom: snapshot?.venom ?? 0,
    side: snapshot?.side ?? shooter.side ?? 0,
    shooter,
    target,
  };
  projectiles.push(shot);
  return shot;
}

//: Насколько близко к цели снаряд считается попавшим — половина ширины
//: тела, той же, по которой ловится клик по юниту.
const HIT_RADIUS_X = 30;
const HIT_RADIUS_Y = 46;

// Такт полёта: восемь подшагов, как в движке, и на каждом проверяем, не
// накрыл ли снаряд свою цель. Кончилась жизнь — снаряд пропал, это и есть
// промах мимо (VA 0x41FE03).
//: СВОБОДНЫЙ ВЫСТРЕЛ — В КОГО ПОПАЛ, ТОТ И ЦЕЛЬ.
//:
//: У канонной стрелы цель назначена в миг выстрела, и такт проверяет только
//: её: движок держит жертву в самой записи снаряда. Огонь же посылают КУДА
//: ЗАХОТЯТ, и жжёт он первого встречного — поэтому у такого снаряда цели нет
//: вовсе, а попадание ищется перебором живых чужих на каждом подшаге. Своих
//: не задевает: сторона стрелка записана в снаряде тем же снимком удара.
function freeHit(shot) {
  const list = world.unitsInPlay?.() ?? [];
  for (const unit of list) {
    if (!unit || unit === shot.shooter || unit.alive === false) continue;
    if ((unit.side ?? 0) === (shot.side ?? 0)) continue;
    if (Math.abs(unit.x - shot.x) <= HIT_RADIUS_X &&
        Math.abs((unit.y - 40) - shot.y) <= HIT_RADIUS_Y) return unit;
  }
  return null;
}

export function projectilesTick(dt, onHit) {
  if (!projectiles.length) return false;
  const set = rules();
  const substeps = set?.substeps ?? 8;
  const step = tickSeconds();
  const ticks = dt / step;
  for (let index = projectiles.length - 1; index >= 0; index -= 1) {
    const shot = projectiles[index];
    let landed = false;
    let blocked = false;
    const moves = Math.max(1, Math.round(substeps * ticks));
    for (let move = 0; move < moves && !landed && !blocked; move += 1) {
      shot.x += shot.stepX;
      shot.y += shot.stepY;
      // Снаряд гасит ТОЛЬКО стена или постройка — бит 0x4000 клетки
      // (VA 0x41FE4A). Вода и деревья ходить не дают, но стрелу
      // ПРОПУСКАЮТ: прежний гейт «клетка непроходима» ронял её и в них.
      const cell = heroCellAt(shot.x, shot.y);
      if (cell && world.solidAt?.(cell.row, cell.col)) {
        // Стрела, пущенная в постройку, на её клетке и попадает: движок
        // на глухой клетке (бит 0x4000) проверяет саму картинку объекта и
        // идёт поджигать (VA 0x41FDD0). Про «ноль масла» эта функция
        // ничего не знает — метку масла читают прицел и щелчок.
        if (shot.target?.building &&
            buildingAtCell(cell.row, cell.col) === shot.target.building) {
          landed = true;
          break;
        }
        blocked = true;
        break;
      }
      const target = shot.target;
      if (target && target.alive !== false &&
          Math.abs(target.x - shot.x) <= HIT_RADIUS_X &&
          Math.abs((target.y - 40) - shot.y) <= HIT_RADIUS_Y) {
        landed = true;
      } else if (!target && shot.free) {
        const met = freeHit(shot);
        if (met) { shot.target = met; landed = true; }
      }
    }
    // Стрела мигает двумя кадрами, а у своего снаряда кадров сколько угодно.
    //
    // ЗДЕСЬ НЕЛЬЗЯ ВЫХОДИТЬ ДОСРОЧНО. Ниже списывается жизнь и разбирается
    // попадание; пропустив их, снаряд не увидит ни цели, ни стены и будет
    // лететь вечно. Отбор «огонь рисуется отдельно» живёт в renderProjectiles,
    // а такт обязан обойти КАЖДЫЙ снаряд до конца.
    const own = spriteSet(shot.sprite);
    if (own) {
      const strip = own.directions[shot.direction % own.directions.length];
      shot.anim = ((shot.anim ?? 0) + 1) % Math.max(1, strip?.length ?? 1);
    } else {
      shot.frame ^= 1;
    }
    shot.life -= ticks;
    if (landed) {
      projectiles.splice(index, 1);
      burstAt(shot);
      onHit?.(shot);
    } else if (blocked) {
      projectiles.splice(index, 1);   // ушла в стену
      burstAt(shot);
    } else if (shot.life <= 0) {
      projectiles.splice(index, 1);   // не долетел — просто пропал
    }
  }
  return true;
}

//: Зажечь вспышку там, где снаряд кончился. У стрелы её нет — в движке
//: стрела просто исчезает, — а у своего снаряда набор может нести взрыв.
function burstAt(shot) {
  const own = spriteSet(shot.sprite);
  if (!own?.burst?.length) return;
  bursts.push({ x: shot.x, y: shot.y, frames: own.burst, frame: 0,
                additive: own.blend === 'additive' });
}

//: Вспышка НЕ ОТ ПОПАДАНИЯ — та же машинка, но кадры берутся по направлению
//: и рисуются в точке того, кто её зажёг. Так сделана вспышка в руках при
//: касте: у её набора кадры лежат в `directions`, а не в `burst`, и
//: привязаны к ногам, как у любого эффекта НА персонаже.
//: `speed` — во сколько раз быстрее такта крутится вспышка. Кадр анимации у
//: персонажа идёт по одному за такт (0x41611C), и эффект по умолчанию тоже;
//: но вспышка каста коротка по смыслу и должна успеть внутри жеста, а не
//: догорать на уже стоящей фигуре.
export function burstSpawn(x, y, name, direction = 0, speed = 1) {
  const own = spriteSet(name);
  const strip = own?.directions?.[direction % (own.directions?.length || 1)];
  if (!strip?.length) return false;
  bursts.push({ x, y, frames: strip, frame: 0, speed,
                additive: own.blend === 'additive' });
  return true;
}

export function burstsTick(dt) {
  if (!bursts.length) return false;
  const ticks = dt / tickSeconds();
  for (let index = bursts.length - 1; index >= 0; index -= 1) {
    const fire = bursts[index];
    fire.frame += ticks * (fire.speed ?? 1);
    if (fire.frame >= fire.frames.length) bursts.splice(index, 1);
  }
  return true;
}

//: Кадр своего снаряда или вспышки — прямоугольник на своём листе.
//:
//: ОГОНЬ КЛАДЁТСЯ СЛОЖЕНИЕМ. В оригинале у него `Trans 1` — «прозрачность по
//: яркости» (Missiles.txt), то есть тёмные точки почти не видны. Обычной
//: альфой они рисуются чёрными, и вокруг шара идёт чёрная кайма. Режим
//: приходит из набора, а не угадывается здесь.
function drawOwn(shot, frame, additive = false) {
  const sheets = world.map?.projectiles?.sheets ?? [];
  const image = world.images.get(sheets[frame.sheet]?.path);
  if (!image) return;
  const mode = context.globalCompositeOperation;
  if (additive) context.globalCompositeOperation = "lighter";
  //: ЯКОРЬ СНАРЯДА — ОН САМ. Строго говоря камере нужна точка НА ЗЕМЛЕ под
  //: ним, а снаряд летит на высоте (у канонной стрелы 30 точек); высоту в
  //: записи выстрела не хранят — она уже вычтена из `y`. Ошибка от этого
  //: меньше двух процентов масштаба, и на летящем шаре её не видно.
  withPerspective(context, shot.x, shot.y, () =>
    context.drawImage(image, frame.x, frame.y, frame.width, frame.height,
                      Math.round(shot.x + frame.offset_x),
                      Math.round(shot.y + frame.offset_y),
                      frame.width, frame.height));
  if (additive) context.globalCompositeOperation = mode;
}

export function renderBursts() {
  for (const fire of bursts) {
    if (fire.additive) continue;               // огонь идёт отдельным проходом
    const frame = fire.frames[Math.floor(fire.frame)];
    if (frame) drawOwn(fire, frame, false);
  }
}

//: ОГОНЬ РИСУЕТСЯ ПОВЕРХ ВСЕЙ СЦЕНЫ, а канонная стрела — внутри неё.
//:
//: Стрелу движок кладёт общим списком вместе с объектами и юнитами (0x85EF3C,
//: вид 1), поэтому её и затеняет, и перекрывает — так и оставлено. А огонь
//: светит: тень на нём бессмысленна, и вспышка в руках должна ложиться НА
//: фигуру, а не под неё. Поэтому всё, что рисуется сложением, уходит отдельным
//: проходом после слоя суток (scene.js).
export function renderFire() {
  const sheets = world.map?.projectiles?.sheets ?? [];
  if (!sheets.length) return;
  for (const shot of projectiles) {
    const own = spriteSet(shot.sprite);
    if (own?.blend !== "additive") continue;
    const strip = own.directions[shot.direction % own.directions.length];
    const frame = strip?.[(shot.anim ?? 0) % Math.max(1, strip.length)];
    if (frame) drawOwn(shot, frame, true);
  }
  for (const fire of bursts) {
    if (!fire.additive) continue;
    const frame = fire.frames[Math.floor(fire.frame)];
    if (frame) drawOwn(fire, frame, true);
  }
}

export function renderProjectiles() {
  const sheets = world.map?.interface?.projectiles ?? [];
  for (const shot of projectiles) {
    const own = spriteSet(shot.sprite);
    if (own?.blend === "additive") continue;   // огонь идёт отдельным проходом
    if (own) {
      const strip = own.directions[shot.direction % own.directions.length];
      const frame = strip?.[(shot.anim ?? 0) % Math.max(1, strip.length)];
      if (frame) drawOwn(shot, frame, own.blend === 'additive');
      continue;
    }
    const pair = sheets[shot.direction % sheets.length];
    const sprite = pair?.[shot.frame % pair.length];
    const image = sprite && world.images.get(sprite.path);
    if (!image) continue;
    withPerspective(context, shot.x, shot.y, () =>
      context.drawImage(image, Math.round(shot.x - sprite.width / 2),
                        Math.round(shot.y - sprite.height / 2)));
  }
}
