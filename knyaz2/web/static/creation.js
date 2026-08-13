// Экран создания героя — состояние экрана 2 движка.
//
// Собран по docs/MENU_CANON_SPEC.md, где каждое число снято с кода:
//
//   отрисовка          0x430DF4
//   разбор щелчков     таблица 0x461D44, 91 прямоугольник; номер попавшего
//                      и есть код действия (0x43B5F8)
//   выбор архетипа     коды 0…5 — щелчок по портрету, зовёт 0x4387CC(N)
//   прибавки           6…11 «+» и 12…17 «−» характеристик,
//                      18…37 «+» и 38…57 «−» навыков
//   «Играть»           код 87, состояние ← 8
//   «Отмена»           код 88, назад в меню
//   описание героя     0x431548 печатает строку 0x462CDC[N]
//
// Экран НЕ накладка поверх игры: в движке это отдельное состояние со своим
// фоном 1024x768 из NEWHERO.RES, и сцена под ним не рисуется вовсе. Здесь
// так же — холст игры прячется, мировой такт стоит.
//
// Все координаты — в системе экрана 1024x768 и переводятся в проценты, так
// что экран не разъезжается при любом размере окна.
import { hero } from "./hero.js";
import { contentUrl } from "./content.js";
import { canRaiseCharacteristic, canRaiseSkill, canLowerCharacteristic,
         canLowerSkill, creationReset, lowerCharacteristic, lowerSkill,
         progressSetup, raiseCharacteristic, raiseSkill } from "./progress.js";

const SCREEN_W = 1024, SCREEN_H = 768;
//: подписи и значения выравниваются правым краем по этим x (0x430DF4)
const NAME_X = 870, VALUE_X = 920;
const CHAR_Y = 130, SKILL_Y = 345, ROW_STEP = 20;
const FREE_XP_Y = 74, WEIGHT_Y = 270, PARTY_Y = 290;
//: предел веса — граммы (0x423218), экран делит на тысячу и печатает «%4.1f»
const WEIGHT_SCALE = 0.001;
const PARTY_CAP = 9;

let node = null;
let frame = null;
let starts = [];
let picked = 0;
let finish = null;
let data = null;

function rules() { return hero.data?.rules?.progression ?? null; }
function names(kind) { return rules()?.[kind]?.names ?? []; }

//: Взять героя выбранного мира заново — как 0x4387CC: запись из GAME.<номер>
//: целиком, счётчики прибавок обнулены.
function loadArchetype(index) {
  picked = (index + starts.length) % starts.length;
  const template = starts[picked]?.template;
  if (!template || !hero.data) return;
  hero.data.template = template;
  progressSetup();
  creationReset(hero);
}

// Разместить узел по прямоугольнику экрана движка.
function place(element, [x1, y1, x2, y2]) {
  element.style.left = `${(x1 / SCREEN_W) * 100}%`;
  element.style.top = `${(y1 / SCREEN_H) * 100}%`;
  element.style.width = `${((x2 - x1) / SCREEN_W) * 100}%`;
  element.style.height = `${((y2 - y1) / SCREEN_H) * 100}%`;
}

function text(value, x, y, className = "") {
  const span = document.createElement("span");
  span.className = `creation__text ${className}`.trim();
  span.textContent = value;
  span.style.left = `${(x / SCREEN_W) * 100}%`;
  span.style.top = `${(y / SCREEN_H) * 100}%`;
  frame.append(span);
  return span;
}

// Кнопка-прямоугольник поверх фона: своей картинки у неё нет, попадание
// считается по той же таблице, что и в движке.
function zone(rect, title, press) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "creation__zone";
  button.title = title;
  place(button, rect);
  button.addEventListener("click", () => { press(); paint(); });
  frame.append(button);
  return button;
}

function paint() {
  if (!node || !frame || !data) return;
  frame.textContent = "";
  const rects = data.rects ?? [];
  const codes = data.codes ?? {};
  const start = starts[picked] ?? {};

  // фон экрана
  if (data.background) {
    const picture = document.createElement("img");
    picture.className = "creation__background";
    picture.src = contentUrl(data.background.path);
    picture.alt = "";
    frame.append(picture);
  }

  // ШЕСТЬ КЛЕТОК СЛЕВА — ТОЛЬКО ЗОНЫ ВЫБОРА. Лица в них уже НАРИСОВАНЫ НА
  // ФОНЕ: в блоке 0 файла NEWHERO.RES все шесть портретов вписаны в резные
  // рамки. Раньше клиент клал поверх них ещё по картинке из блоков 1…6 —
  // отсюда и двоение, и «разъезжается»: картинка 76x87 рисовалась в своём
  // натуральном размере, а рамка тянулась процентами от кадра 1024x768.
  const [firstFace, lastFace] = codes.portraits ?? [0, 5];
  for (let code = firstFace; code <= lastFace; code += 1) {
    const rect = rects[code];
    if (!rect) continue;
    const button = zone(rect, starts[code - firstFace]?.name ?? "герой",
                        () => loadArchetype(code - firstFace));
    if (picked === code - firstFace) button.classList.add("выбран");
  }

  // ЯРКИЙ ПОРТРЕТ — ТОЛЬКО У ВЫБРАННОГО, И В ЕГО ЖЕ КЛЕТКЕ.
  //
  // Сверил пиксельно: блоки 1…6 файла NEWHERO.RES совпадают с фоном ровно
  // на местах клеток, смещение (0,0). Разница только в яркости — в фоне
  // лица ПРИГЛУШЕНЫ (средняя разница 10…16 из 255). Значит фон рисует шесть
  // тусклых лиц, а движок кладёт поверх яркое, и только одно: выбранное.
  //
  // Точка `portrait_at` (547, 75) к этому отношения не имеет — там узор с
  // драконом, никакой рамки под портрет в фоне нет. Она из соседней таблицы
  // точек экрана и служит чему-то другому.
  const shot = data.portraits?.[picked];
  const spot = rects[firstFace + picked];
  if (shot && spot) {
    const picture = document.createElement("img");
    picture.className = "creation__portrait";
    picture.src = contentUrl(shot.path);
    picture.alt = "";
    picture.style.left = `${(spot[0] / SCREEN_W) * 100}%`;
    picture.style.top = `${(spot[1] / SCREEN_H) * 100}%`;
    picture.style.width = `${(shot.width / SCREEN_W) * 100}%`;
    picture.style.height = `${(shot.height / SCREEN_H) * 100}%`;
    frame.append(picture);
  }

  text("Свободный опыт", NAME_X, FREE_XP_Y);
  text(String(hero.freeExperience ?? 0), VALUE_X, FREE_XP_Y);

  const chars = names("characteristics");
  const [charRaise] = codes.characteristic_raise ?? [6];
  const [charLower] = codes.characteristic_lower ?? [12];
  for (let i = 0; i < chars.length; i += 1) {
    const y = CHAR_Y + i * ROW_STEP;
    text(chars[i], NAME_X, y);
    const added = (hero.raisedCharacteristics?.[i] ?? 0) > 0;
    text(String(hero.baseCharacteristics?.[i] ?? hero.characteristics?.[i] ?? 0),
         VALUE_X, y, added ? "добавлено" : "");
    if (canRaiseCharacteristic(i, hero) && rects[charRaise + i]) {
      zone(rects[charRaise + i], "поднять за 2",
           () => raiseCharacteristic(i, hero, { creation: true })).textContent = "+";
    }
    if (canLowerCharacteristic(i, hero) && rects[charLower + i]) {
      zone(rects[charLower + i], "вернуть 2",
           () => lowerCharacteristic(i, hero)).textContent = "−";
    }
  }

  // оба итога — от ТЕКУЩИХ характеристик, как на экране движка
  const stamina = hero.characteristics?.[5] ?? 0;
  const charisma = hero.characteristics?.[0] ?? 0;
  text("Максимальный вес", NAME_X, WEIGHT_Y);
  text(((Math.trunc(stamina * 1000 / 3) + 20000) * WEIGHT_SCALE).toFixed(1),
       VALUE_X, WEIGHT_Y);
  text("Максимальный отряд", NAME_X, PARTY_Y);
  text(String(Math.min(PARTY_CAP, (charisma >> 4) + 1)), VALUE_X, PARTY_Y);

  const skills = names("skills");
  const [skillRaise] = codes.skill_raise ?? [18];
  const [skillLower] = codes.skill_lower ?? [38];
  for (let i = 0; i < skills.length; i += 1) {
    const y = SKILL_Y + i * ROW_STEP;
    text(skills[i], NAME_X, y);
    const added = (hero.raisedSkills?.[i] ?? 0) > 0;
    text(String(hero.skills?.[i] ?? 0), VALUE_X, y, added ? "добавлено" : "");
    if (canRaiseSkill(i, hero) && rects[skillRaise + i]) {
      zone(rects[skillRaise + i], "поднять за 1",
           () => raiseSkill(i, hero, { creation: true })).textContent = "+";
    }
    if (canLowerSkill(i, hero) && rects[skillLower + i]) {
      zone(rects[skillLower + i], "вернуть 1",
           () => lowerSkill(i, hero)).textContent = "−";
    }
  }

  // Описание выбранного героя — то, что печатает 0x431548, и рамка у него
  // КАНОННАЯ: перенос идёт от x 0x4622E4 до x 0x4622EC, начиная с y
  // 0x4622E8; снизу текст упирается в кнопки. Раньше рамка была задана на
  // глаз в процентах, и текст вылезал за неё.
  if (start.story) {
    const box = data.story_box ?? { x: 52, y: 410, x2: 550, y2: 699 };
    const about = document.createElement("p");
    about.className = "creation__story";
    about.textContent = start.story;
    about.style.left = `${(box.x / SCREEN_W) * 100}%`;
    about.style.top = `${(box.y / SCREEN_H) * 100}%`;
    about.style.width = `${((box.x2 - box.x) / SCREEN_W) * 100}%`;
    about.style.height = `${((box.y2 - box.y) / SCREEN_H) * 100}%`;
    frame.append(about);
  }

  // «Играть» и «Отмена» — коды 87 и 88
  if (rects[codes.play ?? 87]) {
    zone(rects[codes.play ?? 87], "начать игру", () => {
      const chosen = starts[picked];
      creationClose();
      finish?.(chosen);
    }).textContent = "Играть";
  }
  if (rects[codes.cancel ?? 88]) {
    zone(rects[codes.cancel ?? 88], "вернуться в меню", () => {
      creationClose();
      location.href = "/menu.html";
    }).textContent = "Отмена";
  }
}

export function creationOpen(list, world, onDone, creation = null) {
  starts = list ?? [];
  data = creation ?? null;
  if (!starts.length || !hero.data || !data?.rects?.length) return false;
  finish = onDone;
  node = document.createElement("div");
  node.className = "creation";
  // КАДР 4:3 по центру. Экран движка — 1024x768, и все его числа имеют смысл
  // только внутри этого кадра. Раньше проценты считались от окна, а фон
  // лежал по центру с полями — оттого подписи и кнопки уезжали мимо
  // картинки, и экран «разъезжался».
  frame = document.createElement("div");
  frame.className = "creation__frame";
  node.append(frame);
  document.body.append(node);
  // Сцена под экраном не рисуется — в движке это отдельное состояние.
  document.body.classList.add("creation-open");
  const at = starts.findIndex((entry) => entry.world === Number(world));
  loadArchetype(at >= 0 ? at : 0);
  paint();
  return true;
}

export function creationClose() {
  node?.remove();
  node = null;
  frame = null;
  document.body.classList.remove("creation-open");
}

export function creationOpened() { return Boolean(node); }
