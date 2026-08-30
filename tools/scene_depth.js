// Порядок отрисовки по глубине: герой обязан идти в общем потоке.
//
//     node tools/scene_depth.js
//
// Стенд повторяет раскладку scene.js в чистом виде — без холста и картинок, —
// и проверяет ОДНО правило: всё, что нарисовано позже, стоит не ближе того,
// что нарисовано раньше. Ключи глубины у людей это «ноги + 6» (actor.js).
//
// СТАРЫЙ ПОРЯДОК ЭТО ПРАВИЛО НАРУШАЛ. Герой вставлялся не по своему ключу, а
// на границах объектов: сперва рисовались все юниты до глубины очередной
// постройки, и лишь потом он сам. Стоило герою оказаться ДАЛЬШЕ спутника, а
// ближайшей постройке — глубже обоих, и спутника рисовали раньше героя: ноги
// дальнего ложились на ближнего. Снаружи это видно, в доме нет — там жильцов
// рисует сама постройка.

//: Старая раскладка: герой на границе объекта.
function orderOld(objects, units, heroY) {
  const out = [];
  let next = 0, heroDrawn = false;
  const before = (sortY) => {
    while (next < units.length && units[next].sortY <= sortY) {
      out.push(units[next]);
      next += 1;
    }
  };
  for (const object of objects) {
    before(object.sortY);
    if (object.sortY > heroY && !heroDrawn) {
      out.push({ name: "герой", sortY: heroY });
      heroDrawn = true;
    }
    out.push(object);
  }
  before(Infinity);
  if (!heroDrawn) out.push({ name: "герой", sortY: heroY });
  return out;
}

//: Новая раскладка: герой — такой же участник очереди, как юнит и куча.
function orderNew(objects, units, heroY) {
  const out = [];
  let next = 0, heroDrawn = false;
  const before = (sortY) => {
    for (;;) {
      const unitY = next < units.length ? units[next].sortY : Infinity;
      const ownY = heroDrawn ? Infinity : heroY;
      const step = Math.min(unitY, ownY);
      //: Пустая очередь — выход. Без проверки на конечность последний вызов
      //: с Infinity сравнивал бесконечность с самой собой и не кончался.
      if (!Number.isFinite(step) || step > sortY) return;
      if (ownY === step) {
        out.push({ name: "герой", sortY: heroY });
        heroDrawn = true;
      } else {
        out.push(units[next]);
        next += 1;
      }
    }
  };
  for (const object of objects) {
    before(object.sortY);
    out.push(object);
  }
  before(Infinity);
  return out;
}

//: Где очередь пошла вспять: нарисованное позже оказалось ДАЛЬШЕ.
function inversions(order) {
  const bad = [];
  for (let i = 1; i < order.length; i += 1) {
    if (order[i].sortY < order[i - 1].sortY) {
      bad.push(`${order[i - 1].name}(${order[i - 1].sortY})`
        + ` -> ${order[i].name}(${order[i].sortY})`);
    }
  }
  return bad;
}

// Сцена ровно того вида, что на снимке игрока: герой ДАЛЬШЕ спутника, а дом
// стоит глубже обоих. Ключи — «ноги + 6» от клеток соседних рядов.
const scenes = [
  {
    name: "герой дальше спутника, дом глубже обоих",
    objects: [{ name: "дом", sortY: 1400 }],
    units: [{ name: "спутник", sortY: 1206 }],
    heroY: 1158,
  },
  {
    name: "герой ближе спутника",
    objects: [{ name: "дом", sortY: 1400 }],
    units: [{ name: "спутник", sortY: 1158 }],
    heroY: 1206,
  },
  {
    name: "первая клетка: дом между героем и спутником",
    objects: [{ name: "дом", sortY: 1180 }],
    units: [{ name: "спутник", sortY: 1206 }],
    heroY: 1158,
  },
  {
    name: "трое вокруг героя",
    //: Объекты идут ПО ГЛУБИНЕ — так их кладёт пак, и иначе сцена бессмысленна.
    objects: [{ name: "плетень", sortY: 1250 }, { name: "дом", sortY: 1500 }],
    units: [{ name: "спутник A", sortY: 1170 },
            { name: "спутник B", sortY: 1210 },
            { name: "спутник C", sortY: 1300 }],
    heroY: 1190,
  },
];

let плохо = 0;
for (const scene of scenes) {
  const старый = inversions(orderOld(scene.objects, scene.units, scene.heroY));
  const новый = inversions(orderNew(scene.objects, scene.units, scene.heroY));
  console.log(`\n${scene.name}`);
  console.log(`  старый порядок: ${старый.length
    ? "СБОЙ — " + старый.join(", ") : "ровно"}`);
  console.log(`  новый порядок:  ${новый.length
    ? "СБОЙ — " + новый.join(", ") : "ровно"}`);
  if (новый.length) плохо += 1;
}
console.log(плохо ? `\nПРОВАЛ: сцен со сбоем ${плохо}` : "\nВСЕ СЦЕНЫ РОВНЫЕ");
process.exit(плохо ? 1 : 0);
