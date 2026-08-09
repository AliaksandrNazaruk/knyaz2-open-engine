// Летящие стрелы.
//
// В движке это отдельный массив снарядов (0x833AE8, до ста записей по 32
// байта), который заполняет выстрел VA 0x41BB10:
//
//     +0x00 шаг по X за такт, +0x04 шаг по Y — делятся на длину пути,
//           поэтому снаряд летит по прямой; скорость выходит четыре
//           пикселя за такт (константа 0x450128)
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
import { heroCellAt, heroFree } from "./hero.js";
import { buildingAtCell } from "./buildings.js";

export const projectiles = [];

function rules() { return world.map?.hero?.rules?.accuracy?.projectiles ?? null; }

export function projectileAssets() {
  const sheets = world.map?.interface?.projectiles ?? [];
  return sheets.flat().filter(Boolean).map((sprite) => sprite.path);
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
export function projectileFire(shooter, target, accuracy = 0, weapon = null,
                               snapshot = null) {
  const set = rules();
  if (!set || projectiles.length >= (set.limit ?? 100)) return null;
  const dx = target.x - shooter.x;
  const dy = (target.y - 30) - shooter.y;
  const length = Math.max(1, Math.max(Math.abs(dx), Math.abs(dy)));
  const speed = set.speed ?? 4;
  const shot = {
    x: shooter.x, y: shooter.y - 30,
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
      // Стена гасит снаряд: движок смотрит бит 0x4000 клетки на каждом
      // подшаге и снимает стрелу (VA 0x41FE4A).
      const cell = heroCellAt(shot.x, shot.y);
      if (cell && !heroFree(cell.row, cell.col)) {
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
      }
    }
    shot.frame ^= 1;
    shot.life -= ticks;
    if (landed) {
      projectiles.splice(index, 1);
      onHit?.(shot);
    } else if (blocked) {
      projectiles.splice(index, 1);   // ушла в стену
    } else if (shot.life <= 0) {
      projectiles.splice(index, 1);   // не долетел — просто пропал
    }
  }
  return true;
}

export function renderProjectiles() {
  const sheets = world.map?.interface?.projectiles ?? [];
  for (const shot of projectiles) {
    const pair = sheets[shot.direction % sheets.length];
    const sprite = pair?.[shot.frame % pair.length];
    const image = sprite && world.images.get(sprite.path);
    if (!image) continue;
    context.drawImage(image, Math.round(shot.x - sprite.width / 2),
                      Math.round(shot.y - sprite.height / 2));
  }
}
