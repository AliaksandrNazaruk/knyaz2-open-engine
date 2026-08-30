// Наполнение прилавков при входе на карту.
//
// Перенос FUN_0041896C. Зовёт её загрузчик карты FUN_0043DF48 последней
// строкой, поэтому лавки набиваются НА КАЖДОМ ВХОДЕ, а не однажды при старте
// игры. В самих GAME.N прилавки пусты — и это правильно: `village().goods`
// отдаёт три пустых списка, наполняет их только загрузчик. Пока вызова не
// было, все лавки в игре стояли пустыми — на это и пожаловался первый
// бета-тестер (отчёт Александра С., 09.08.2026).
//
// Прилавков у поселения три, но этот генератор трогает только два (проверено
// по дизассемблеру: обращений к +0x3E0 — два, к +0x40E — двадцать шесть, к
// +0x44E — ни одного):
//
//     роль 2 (знахарь), +0x3E0, 22 места — одни пустые банки;
//     роль 3 (купец),   +0x40E, 32 места — четыре группы товара;
//     роль 4 (кузнец),  +0x44E, 39 мест  — НЕ его забота, это работа
//                                          мастерской (FUN_00417BD8).
//
// Роль — это НОМЕР ДОЛЖНОСТИ ПЛЮС ОДИН: FUN_00415190 перебирает пятёрку с
// +0x3D0 и возвращает найденное место + 1. Отсюда роль 2 — должность 1,
// знахарь, а роль 3 — должность 2, купец. Рандомный товар с привязкой к
// уровню игрока достаётся, стало быть, КУПЦУ — как и говорил бета-тестер.
//
// Уровень игрока читается из байта +0xF3 и режется потолком 13 — снято
// дизассемблером, VA 0x00418A22.
import { world } from "./world.js";
import { hero } from "./hero.js";
import { actorItem, actorNewItemRef } from "./actor.js";
import { units } from "./units.js";
import { eventAlive, officialRole } from "./village.js";
import { potionMix } from "./craft.js";
import { SLOTS, requirementMet } from "./inventory.js";
import { roundHalfEven } from "./round.js";

//: Бросок движка FUN_00442B93 — остаток от деления на границу.
const roll = (bound) => (bound > 0 ? Math.floor(Math.random() * bound) : 0);

//: `x % n`, но при n < 2 движок не бросает жребия вовсе и берёт ноль.
const rollUnder = (bound) => (bound < 2 ? 0 : roll(bound));

const LEVEL_CAP = 13;
const EMPTY_BOTTLE = 0x53;          // класс 83, «Пустая банка», вид 9

//: Границы групп и их вероятности — из разбора цикла по местам: граница
//: наращивается на 3, 2, 3 и 6, а порог сравнивается с остатком rand()%100.
//: Шанс = 100 − порог − 1: 0x46 даёт 29 %, 0x32 — 49 %, 0x1E — 69 %.
const GROUPS = [
  { size: 3, over: 0x46 },          // украшения
  { size: 2, over: 0x32 },          // напитки
  { size: 3, over: 0x1e },          // оружие по культуре
  { size: 6, over: 0x32 },          // снаряжение
];

function rules() { return world.map?.hero?.rules?.trade ?? null; }

//: Ссылка на класс. Пак ключует предметы как `class:<номер>`, и генератор
//: называет именно номера классов.
function classRef(index) {
  const ref = `class:${index}`;
  return actorItem(ref) ? ref : null;
}

// Школа вещей по культуре деревни (VA 0x00416E80).
function school(culture) {
  if (culture === 0) return roll(2) + 1;
  if (culture === 2) return roll(2);
  return roll(2) === 0 ? 0 : 2;
}

// Класс оружия по школе и уровню (VA 0x00416F48): три равновероятные ветви,
// у каждой своя база и свой делитель уровня, и к любой с вероятностью ½
// прибавляется семь.
function weaponClass(pick, level) {
  const bases = [0x65, 0x68, 0x6a];
  const divisors = [5, 8, 8];
  const branch = roll(3);
  const step = rollUnder(Math.trunc(level / divisors[branch]) + 1);
  return step + pick * 0x22 + bases[branch] + roll(2) * 7;
}

//: Слово прибавок: уровень задаёт величину, сдвиг выбирает, какому свойству
//: она достанется (VA 0x41896C, `(n + 1) << ((rand() % k) * 3)`).
function enchantWord(range, shifts) {
  return (rollUnder(range) + 1) << ((roll(shifts) * 3) & 0x1f);
}

// ПРИЛАВОК ПРИНАДЛЕЖИТ ПОСЕЛЕНИЮ, А НЕ ТОРГОВЦУ.
//
// Генератор в движке берёт аргументом ЗАПИСЬ ПОСЕЛЕНИЯ: загрузчик карты
// находит её перебором `0x83D408` по номеру карты и зовёт
// `FUN_0041896C(запись)` (VA 0x43DF48:210-232). Места прилавка — поля этой
// записи (`+0x3E0`, `+0x40E`, `+0x44E`), а в местах лежат НОМЕРА записей
// предметов в общей таблице `0x6F956C`. Запись поселения живёт весь сеанс и
// целиком уезжает в сохранение, поэтому купленное не возвращается: место
// осталось пустым, а генератор наполняет только пустые (`== 0` в каждом из
// его условий).
//
// Порт держал прилавок на самом торговце, а юниты карты пересоздаются из пака
// при каждом входе — счётчик всякий раз оказывался пуст, и лавка набивалась
// заново. Теперь список мест лежит в записи поселения, а торговцу отдаётся
// ССЫЛКА на него: покупка (`trade.js` гасит место) правит сразу поселение.
//: Запись поселения приходит доводом: прилавок дальней деревни лежит в её
//: записи из склада, а не в записи карты, на которой стоит игрок.
function counterBox(unit, role, village = world.map?.village) {
  if (!village) return { slots: unit.counter ?? (unit.counter = []), details: null };
  village.counters = village.counters ?? {};
  const box = village.counters[String(role)] ??
    (village.counters[String(role)] = { slots: [], details: {} });
  box.slots = box.slots ?? [];
  box.details = box.details ?? {};
  unit.counter = box.slots;
  // Крепость и слово чар выложенного — обратно торговцу: у нас они живут в
  // картах владельца по имени экземпляра, а торговец каждый вход новый.
  for (const [name, detail] of Object.entries(box.details)) {
    if (detail?.strength != null) {
      unit.bagStrength = unit.bagStrength ?? {};
      unit.bagStrength[name] = detail.strength;
    }
    if (detail?.enchant) {
      unit.bagEnchant = unit.bagEnchant ?? {};
      unit.bagEnchant[name] = detail.enchant;
    }
  }
  return box;
}

//: Положить вещь на место прилавка: ссылка экземплярная, как новая запись
//: предмета в движке, а прочность и слово прибавок ложатся в те же карты, что
//: у вещей в мешке, и заодно в запись поселения — переживать уход с карты.
function place(unit, box, slot, index, word = 0) {
  const ref = classRef(index);
  if (!ref) return false;
  const instance = actorNewItemRef(ref, "shop");
  box.slots[slot] = instance;
  const item = actorItem(instance);
  const detail = {};
  if (typeof item?.durability === "number") {
    unit.bagStrength = unit.bagStrength ?? {};
    unit.bagStrength[instance] = item.durability;
    detail.strength = item.durability;
  }
  if (word) {
    unit.bagEnchant = unit.bagEnchant ?? {};
    unit.bagEnchant[instance] = word;
    detail.enchant = word;
  }
  if (box.details) box.details[instance] = detail;
  return true;
}

// Прилавок роли 2 (знахарь): одни пустые банки, от одной до трёх, и только на
// первые два места.
function restockBottles(unit, slots) {
  const box = counterBox(unit, 2);
  let left = roll(3) + 1;
  let put = 0;
  for (let slot = 0; slot < Math.min(2, slots); slot += 1) {
    if (!left || box.slots[slot]) continue;
    if (!place(unit, box, slot, EMPTY_BOTTLE)) continue;
    left -= 1;
    put += 1;
  }
  return put;
}

// Прилавок роли 3 (купец): четыре группы подряд, каждая со своим броском на
// место. Занятое место генератор не трогает — товар копится между заходами.
function restockGoods(unit, slots, level, culture) {
  const box = counterBox(unit, 3);
  const pick = school(culture);
  const byFive = Math.trunc(level / 5);
  const byEight = Math.trunc(level / 8);
  let slot = 0;
  let put = 0;

  const group = (index, fill) => {
    const limit = Math.min(slot + GROUPS[index].size, slots);
    for (; slot < limit; slot += 1) {
      if (box.slots[slot]) continue;
      if (roll(100) <= GROUPS[index].over) continue;
      if (fill(slot)) put += 1;
    }
  };

  // 1. Украшения: кольцо, браслет или ожерелье по броску из тридцати.
  group(0, (at) => {
    const die = roll(30);
    const base = die < 10 ? 66 : die < 20 ? 63 : 60;
    return place(unit, box, at, base + rollUnder(byFive),
                 enchantWord(byEight * 2 + 2, 4));
  });

  // 2. Напитки: вид 0x0B, классы 30…56.
  group(1, (at) => place(unit, box, at, roll(0x1b) + 0x1e));

  // 3. Оружие по культуре деревни; слово прибавок редкое — одно из десяти.
  group(2, (at) => {
    const word = roll(0x65) < 10 ? enchantWord(Math.trunc(level / 2), 5) : 0;
    return place(unit, box, at, weaponClass(pick, level), word);
  });

  // 4. Снаряжение: броня, щит или шлем — по броску из трёх, каждому своя
  // база класса и свой делитель уровня.
  //
  // ШКОЛА ЗДЕСЬ СВОЯ НА КАЖДУЮ ВЕЩЬ. Стояло `(культура + 1) % 3` — соседняя
  // по счёту, — а движок зовёт FUN_00416E80(культура) отдельно для брони,
  // щита и шлема (VA 0x418F5D, 0x418FC8, 0x419033: `mov eax,[ebp-4]` —
  // культура — и сразу `call 0x416E80`). Помощник возвращает СЛУЧАЙНУЮ из
  // двух ЧУЖИХ школ, поэтому у деревни в снаряжении встречались обе, а у нас
  // всегда одна и та же.
  //
  // И СЕМЬ ПРОЦЕНТОВ НА ЧАРЫ — их не было вовсе: VA 0x4190BA, `idiv 0x64` и
  // `cmp edx, 7`, дальше слово прибавок от половины уровня со сдвигом из
  // пяти. Ровно как у оружия третьей группы, только шанс там десять.
  group(3, (at) => {
    const branch = roll(3);
    const [base, divisor] = branch === 0 ? [0x78, 4]
      : branch === 1 ? [0x7c, 3] : [0x81, 3];
    const step = rollUnder(Math.trunc(level / divisor) + 1);
    const word = roll(100) < 7 ? enchantWord(Math.trunc(level / 2), 5) : 0;
    return place(unit, box, at, school(culture) * 0x22 + base + step, word);
  });
  return put + restockTail(unit, box, slots, level, culture);
}

//: Первое место хвоста. До него — четыре группы по жребию (3 + 2 + 3 + 6).
const TAIL_AT = 14;

// ХВОСТ ПРИЛАВКА КУПЦА: места 14…31, восемнадцать вещей.
//
// Их движок кладёт БЕЗ ЖРЕБИЯ и БЕЗ ПРОВЕРКИ «место пусто». Сперва гасит всё,
// что там лежало (VA 0x419126: цикл `0xE…0x20`, каждой прежней записи предмета
// ставится вид 0xFF — «исчезла»), а затем заполняет все восемнадцать заново.
// То есть половина прилавка перевыпекается при каждом входе на карту, и она-то
// и даёт купцу настоящий ассортимент: без неё у него оставались одни жребии
// первых четырнадцати мест, и тестеры видели «одни стрелы».
//
// ХВОСТ НЕ ПОД УСЛОВИЕМ. `cmp eax, [ebp-8]` / `jge 0x419126` (VA 0x418E8A) —
// это выход из цикла четвёртой группы прямо сюда, а не гейт. Прежняя запись в
// docs/SHOP_STOCK_SPEC.md — «никакого скрытого гейта нет» — приняла сравнение
// за границу группы и весь хвост проглядела.
//
// ТРИ НАБОРА ПО ШКОЛАМ: (культура+1)%3, (культура+2)%3 и — внимание —
// СЛУЧАЙНАЯ НА КАЖДУЮ ВЕЩЬ. Ghidra печатает у последних пяти мест `iVar5 % 3`,
// и `iVar5` выглядит культурой, но к этому месту он давно переприсвоен
// броском. Проверено по стеку: культура лежит в `[ebp-4]`, и в хвосте её
// читают ровно двенадцать раз — все до места 26 включительно, дальше ни разу.
//
// Чары достаются восьми вещам из восемнадцати: трём украшениям и всей
// последней пятёрке (записи слова в `+0x0E` — VA 0x419267, 0x41936E, 0x419475,
// 0x419E23, 0x41A003, 0x41A15A, 0x41A2AF, 0x41A409).
function restockTail(unit, box, slots, level, culture) {
  const byEight = Math.trunc(level / 8);
  const byFive = Math.trunc(level / 5);
  const byFour = Math.trunc(level / 4);
  const byThree = Math.trunc(level / 3);
  //: Слово прибавок хвоста: величина от восьмой доли уровня, сдвиг из четырёх
  //: (VA 0x41A3EC — `mov ecx, 4`, и `lea ecx,[edx+edx*2]` — те же три бита).
  const word = () => enchantWord(byEight * 2 + 2, 4);
  //: Метательное (вид 1), база 0x73: шаг мерится то восьмой долей уровня, то
  //: пятой — движок бросает монетку.
  const thrown = (pick) => pick * 0x22 + 0x73 +
    (roll(2) === 0 ? rollUnder(byEight + 1) : rollUnder(byFive + 1));
  const armour = (pick) => pick * 0x22 + 0x78 + rollUnder(byFour + 1);
  const shield = (pick) => pick * 0x22 + 0x7c + rollUnder(byThree + 1);
  const helmet = (pick) => pick * 0x22 + 0x81 + rollUnder(byThree + 1);
  const near = (culture + 1) % 3;
  const far = (culture + 2) % 3;
  const any = () => roll(3);

  //: Порядок мест — движковый, менять нельзя: по нему же считает окно
  //: торговли, и он определяет, что игрок увидит в первом ряду.
  const goods = [
    () => [0x3f + rollUnder(byFive), word()],        // 14 браслет
    () => [0x3c + rollUnder(byFive), word()],        // 15 ожерелье
    () => [0x42 + rollUnder(byFive), word()],        // 16 кольцо
    () => [weaponClass(near, level), 0],             // 17 оружие
    () => [weaponClass(far, level), 0],              // 18 оружие
    () => [thrown(near), 0],                         // 19 метательное
    () => [thrown(far), 0],                          // 20 метательное
    () => [armour(near), 0],                         // 21 броня
    () => [shield(near), 0],                         // 22 щит
    () => [helmet(near), 0],                         // 23 шлем
    () => [armour(far), 0],                          // 24 броня
    () => [shield(far), 0],                          // 25 щит
    () => [helmet(far), 0],                          // 26 шлем
    () => [weaponClass(any(), level), word()],       // 27 оружие
    () => [thrown(any()), word()],                   // 28 метательное
    () => [armour(any()), word()],                   // 29 броня
    () => [shield(any()), word()],                   // 30 щит
    () => [helmet(any()), word()],                   // 31 шлем
  ];

  const last = Math.min(slots, TAIL_AT + goods.length);
  if (last <= TAIL_AT) return 0;
  //: Чистка идёт ДО набивки и по всему хвосту, а не только по тем местам,
  //: куда что-то ляжет: в движке гасятся все восемнадцать.
  for (let slot = TAIL_AT; slot < last; slot += 1) {
    const was = box.slots[slot];
    if (was && box.details) delete box.details[was];
    box.slots[slot] = undefined;
  }
  let put = 0;
  goods.forEach((make, index) => {
    const slot = TAIL_AT + index;
    if (slot >= last) return;
    const [item, enchant] = make();
    if (place(unit, box, slot, item, enchant)) put += 1;
  });
  return put;
}

// Наполнить лавки этой карты. Возвращает, сколько вещей выложено.
export function shopsRestock() {
  const counters = rules()?.counters;
  if (!counters || !world.map?.village) return 0;
  const level = Math.min(hero.level ?? 1, LEVEL_CAP);
  const culture = world.map.village.culture ?? 0;
  let put = 0;
  for (const unit of units) {
    // Роль ВЫВОДИМ из должностей: поле `role` в паке проставлено по миру 0 и
    // чужому герою не годится (см. officialRole).
    const role = officialRole(unit);
    const slots = counters[String(role)]?.slots;
    if (!slots) continue;
    if (role === 2) put += restockBottles(unit, slots);
    else if (role === 3) put += restockGoods(unit, slots, level, culture);
  }
  return put;
}

// ЗНАХАРЬ ВАРИТ ЗЕЛЬЯ — перенос FUN_004176C8. Зовут её из ФАЗЫ ДЕРЕВЕНЬ
// (0x41C944:509, тот же гейт `(такт + 7) & 0xF`, что у стройки), и работает
// она, только пока должность знахаря занята (+0x3D2 записи поселения).
//
// ЧАСЫ ВАРКИ — счётчик +0x04 записи поселения:
//
//     поселение[+4] -= 1;
//     if (< 1)              { = 0x5A0; жетоны 0,1,2 = 1; }   // круг заново
//     else if (== 0x2D0)    { жетоны 1,2 = 1; }              // половина
//     else if (== 0x438 || == 0x168) { жетон 2 = 1; }        // четверти
//
// ГНЁЗДА СЧИТАЮТСЯ ОТ +0x3DA, а прилавок начинается на +0x3E0 — то есть с
// гнезда 3. Значит гнёзда 0, 1 и 2 это не товар, а ТЕ САМЫЕ ЖЕТОНЫ: одно и
// то же поле, просто первые три слова под прилавком игроку не показывают.
//
//     гнёзда 5 и 18: класс 0x52 + пустая банка, жетон 2
//     гнёзда 6 и 19: класс 0x50 + пустая банка, жетон 0
//     гнёзда 7 и 20: класс 0x51 + пустая банка, жетон 1
//     гнёзда 8..12 и 21..25: FUN_004170F8 — СМЕШАТЬ ДВА УЖЕ СТОЯЩИХ зелья
//         (18,19) (18,20) (18,22) (19,20) (19,22)
//         результат ложится в целевое гнездо, оба исходных освобождаются
//
// То есть знахарь сперва варит три простых зелья, а потом смешивает их между
// собой — той же `mixmagics`, что и игрок. Отсюда в сейве оригинала и стоят
// две группы по восемь: сначала база, потом смеси.
const BREW_PERIOD = 0x5A0;
const BREW_HALF = 0x2D0;
const BREW_QUARTERS = [0x438, 0x168];
//: Прилавок в порте начинается с гнезда 3 движка — вычитаем его из номеров.
const BREW_SHOP_FROM = 3;
//: гнездо движка -> [класс зелья, номер жетона]
const BREW_SIMPLE = { 5: [0x52, 2], 6: [0x50, 0], 7: [0x51, 1],
                      18: [0x52, 2], 19: [0x50, 0], 20: [0x51, 1] };
//: гнездо движка -> два гнезда-источника
const BREW_PAIRS = { 8: [18, 19], 9: [18, 20], 10: [18, 22],
                     11: [19, 20], 12: [19, 22],
                     21: [18, 19], 22: [18, 20], 23: [18, 22],
                     24: [19, 20], 25: [19, 22] };

function brewSlot(box, engineSlot) { return box.slots[engineSlot - BREW_SHOP_FROM] ?? null; }

function brewPut(box, engineSlot, value) {
  box.slots[engineSlot - BREW_SHOP_FROM] = value;
}

//: ГДЕ ВАРИТ. Без доводов — своя деревня и живой знахарь. С доводами —
//: дальняя: её запись из склада и знахарь из снимка жителя карты. В движке
//: разницы нет вовсе: 0x4176C8 зовётся для всех двенадцати записей подряд,
//: карту эта ветка не спрашивает.
export function villageBrew(phases = 1, data = null, official = null) {
  const village = data ?? world.map?.village;
  if (!village || phases < 1) return 0;
  const healer = official
    ?? units.find((unit) => officialRole(unit) === 2 && unit.alive !== false);
  if (!healer) return 0;
  const box = counterBox(healer, 2, village);
  village.brewTokens = village.brewTokens ?? [0, 0, 0];
  let brewed = 0;
  for (let phase = 0; phase < phases; phase += 1) {
    // СТАРТ ЧАСОВ — ИЗ ЗАПИСИ ПОСЕЛЕНИЯ (+0x04), а не с полного круга. В
    // мирах поле нулевое, и канонная ветка 0x4176C8 «< 1 → перезаряд И все
    // три жетона» срабатывает НА ПЕРВОМ ЖЕ тике деревни: знахарь сразу
    // получает чем варить. Прежний старт с BREW_PERIOD заставлял ждать
    // жетона Яда полный круг — ~30 минут на карте, — и Противоядие (Яд +
    // Бальзам) было недостижимо; отсюда разом «не продаёт снадобья» и
    // «не лечит отраву» (лечит его в игре только Противоядие).
    village.brewTimer = (village.brewTimer ?? village.brew_timer ?? 0) - 1;
    if (village.brewTimer < 1) {
      village.brewTimer = BREW_PERIOD;
      village.brewTokens = [1, 1, 1];
    } else if (village.brewTimer === BREW_HALF) {
      village.brewTokens[1] = 1;
      village.brewTokens[2] = 1;
    } else if (BREW_QUARTERS.includes(village.brewTimer)) {
      village.brewTokens[2] = 1;
    }
    for (let slot = 5; slot < 0x1A; slot += 1) {
      if (brewSlot(box, slot)) continue;          // гнездо занято — не трогаем
      const simple = BREW_SIMPLE[slot];
      if (simple) {
        const [klass, token] = simple;
        if (!village.brewTokens[token]) continue;
        if (!place(healer, box, slot - BREW_SHOP_FROM, klass)) continue;
        //: Сваренное — это класс, смешанный с пустой банкой (mixmagics).
        const made = brewInto(healer, box, slot, EMPTY_BOTTLE);
        if (made) brewed += 1;
        village.brewTokens[token] -= 1;
        continue;
      }
      const pair = BREW_PAIRS[slot];
      if (!pair) continue;
      const first = brewSlot(box, pair[0]);
      const second = brewSlot(box, pair[1]);
      if (!first || !second) continue;
      const mixed = potionMix(first, second, healer,
                              healer.bagStrength?.[first], healer.bagStrength?.[second]);
      if (!mixed?.result) continue;
      brewPut(box, slot, mixed.result);
      brewPut(box, pair[0], null);
      brewPut(box, pair[1], null);
      if (healer.bagStrength) healer.bagStrength[mixed.result] = mixed.strength;
      if (box.details) box.details[mixed.result] = { strength: mixed.strength };
      brewed += 1;
    }
  }
  return brewed;
}

//: Долить в только что выложенный класс пустую банку и оставить результат.
function brewInto(healer, box, slot, bottleClass) {
  const target = brewSlot(box, slot);
  if (!target) return false;
  const ref = classRef(bottleClass);
  if (!ref) return false;
  const bottle = actorNewItemRef(ref, "brew");
  const mixed = potionMix(target, bottle, healer, healer.bagStrength?.[target], 0);
  if (!mixed?.result) return true;      //: рецепта нет — остаётся как есть
  brewPut(box, slot, mixed.result);
  healer.bagStrength = healer.bagStrength ?? {};
  healer.bagStrength[mixed.result] = mixed.strength;
  if (box.details) box.details[mixed.result] = { strength: mixed.strength };
  return true;
}

// КУЗНЕЦ КУЁТ — перенос FUN_00417BD8. Зовут её из той же ФАЗЫ ДЕРЕВЕНЬ, что
// варку и стройку (0x41C944), и работает она, пока занята должность кузнеца
// (+0x3D6 записи поселения, место 3 → роль 4).
//
// Работа идёт ПО ОДНОЙ ВЕЩИ, в два такта:
//
//   1. Заказа нет (+0x49F < 0) — выбрать, что ковать: перебор 39 мест, и
//      место годится, если ПОРОГ этого места не выше навыка «Кузнечное дело»
//      кузнеца (+0xE3) и место на прилавке свободно. Первое подошедшее и
//      берётся: `+0x49F = место`, а срок работы `+0x08 = ROUND(порог * 60)`.
//   2. Заказ есть — срок убавляется каждую фазу, и на нуле заводится запись
//      предмета, кладётся в своё место прилавка, заказ снимается.
//
// ЧТО КУЁТСЯ НА КАЖДОМ МЕСТЕ. Места 0..2 это стрелы, 3..4 болты, их пороги
// лежат отдельными таблицами (0x45F438 и 0x45F458) и равны 1, 2, 3, 3, 5.
// Места с пятого — обычные вещи, и адрес пятого поля даёт формула
// `0x45DA58 + (культура*0x22 + 100 + место)*0x20`. База там на 0x98 левее
// записи класса, поэтому в переводе на классы это:
//
//     класс = культура*34 + 95 + место,  порог = поле +0x08 этого класса
//
// Поле +0x08 — это `durability`, и оно уже едет в паке, так что доставать
// ничего не нужно. Сверка с сохранением оригинала сходится: у кузнеца там
// лежат Нож (16), Топор (9), Дубина (5), Палица (13) — и НЕТ Меча (40) и
// Длинного меча (70), то есть ровно то, что пускает его навык.
// ЕДИНСТВЕННАЯ РЕАЛИЗАЦИЯ. Функция кузнеца была портирована ДВАЖДЫ: полная
// механика (сроки с корнем, рост навыка, раздача) жила в village.js и
// складывала товар в `village.stock`, которого не читал ни один торговый
// экран, а здешняя копия клала на настоящий прилавок, но потеряла делитель
// срока `sqrt(навык/10 + 1)` — ковка шла в 1.5–3.3 раза дольше канона, — и
// не имела ни роста навыка, ни раздачи. Отсюда «кузнец не куёт оружия»:
// пять патронных мест впереди, каждое втрое дольше, а без раздачи и роста
// навыка очередь до оружия не доходила. Дубль из village.js удалён, вся
// механика — здесь, с выходом на настоящий прилавок.
const SMITH_AMMO = [
  { class: 202, need: 1 },   // Кремниевые стрелы (пороги — таблицы
  { class: 203, need: 2 },   // 0x45F438 и 0x45F458, а не durability
  { class: 204, need: 3 },   // самих классов)
  { class: 206, need: 3 },   // Медные болты
  { class: 207, need: 5 },   // Железные болты
];
const SMITH_PLACES = 39;
const SMITH_CLASS_FROM = 95;        //: класс = культура*34 + 95 + место
const SMITH_CULTURE_STEP = 34;      //: 0x22

function workshopRules() {
  return world.map?.hero?.rules?.buildings?.workshop ?? {};
}

// Навык «Кузнечное дело» — по имени из правил, как у village.js: мастер —
// обычный житель, и навык растёт прямо в его юните.
function smithSkillIndex() {
  const names = world.map?.hero?.rules?.progression?.skills?.names ?? [];
  return names.indexOf("Кузнечное дело");
}

function smithSkill(unit) {
  const index = smithSkillIndex();
  return index >= 0 ? unit.skills?.[index] ?? 0 : 0;
}

function setSmithSkill(unit, value) {
  const index = smithSkillIndex();
  if (index >= 0 && unit.skills) unit.skills[index] = value;
}

//: Срок ПЕРВОГО заказа (0x417CE5-0x417D15, снято дизасмом): round(нужда·60
//: / sqrt(навык/10 + 1)) — единица стоит ПОД корнем, ноль невозможен.
function orderTicks(need, skillTenth, shop) {
  const root = Math.sqrt(skillTenth);
  if (!root) return 0;
  return roundHalfEven(need * (shop.minute ?? 60) / root);
}

//: Срок ПЕРЕЗАКАЗА после выдачи (0x417F22 и 0x41800A): формула ДРУГАЯ —
//: round(нужда·60 / (sqrt(навык/10) + 1)): единица прибавляется ПОСЛЕ корня.
function reorderTicks(need, skill, shop) {
  const root = Math.sqrt(Math.trunc(skill / (shop.skill_divisor ?? 10))) + 1;
  return roundHalfEven(need * (shop.minute ?? 60) / root);
}

function smithNeed(place, culture) {
  if (place < SMITH_AMMO.length) return SMITH_AMMO[place];
  const klass = culture * SMITH_CULTURE_STEP + SMITH_CLASS_FROM + place;
  const item = actorItem(classRef(klass));
  if (!item) return null;
  return { class: klass, need: item.durability ?? 0 };
}

// РАЗДАЧА ГОТОВОГО (хвост 0x417BD8): когда ковать больше нечего, бросок
// d8 против порога по статусу и владельцу деревни, и один товар с прилавка
// уходит годному жителю — стрелы стрелку с пустым гнездом, вещь в слот
// вида, если она мощнее носимой, с проверкой требований 0x418648. Выдав,
// движок ТУТ ЖЕ заказывает то же место снова — сроком перезаказа.
function giveForged(village, smith, box, shop, crew = units) {
  const thresholds = (village.status ?? 0) === 1
    ? (shop.give_thresholds?.["1"] ?? [7, 6, 4])
    : (shop.give_thresholds?.other ?? [6, 4, 0]);
  const bar = thresholds[Math.min(village.owner ?? 0, 2)] ?? 0;
  if (roll(shop.give_die ?? 8) < bar) return false;
  const side = village.side;
  for (let index = 0; index < box.slots.length; index += 1) {
    const name = box.slots[index];
    if (!name) continue;
    const item = actorItem(name);
    if (!item) continue;
    for (const unit of crew) {
      if (unit.alive === false || unit.side !== side) continue;
      // зверям мастерская не раздаёт (0x417BD8: бит 0x40 породы)
      //: у снимка жителя поля нет — там мерка движка «облик меньше шести»
      if (unit.beast ?? (unit.body ?? 0) >= 6) continue;
      if (index < SMITH_AMMO.length && !unit.equipment?.ranged) continue;
      if (!requirementMet(name, unit)) continue;
      if (index < SMITH_AMMO.length) {
        if (unit.equipment.ammo) continue;
        unit.equipment.ammo = name;
      } else {
        const slot = SLOTS[item.kind ?? 0];
        if (!slot || !(slot in (unit.equipment ?? {}))) continue;
        const worn = actorItem(unit.equipment[slot]);
        if (worn && (worn.power ?? 0) >= (item.power ?? 0)) continue;
        // старая вещь пропадает: движок помечает её запись пустой
        unit.equipment[slot] = name;
      }
      box.slots[index] = null;
      if (box.details) delete box.details[name];
      village.forgeOrder = index;
      village.forgeLeft = reorderTicks(item.durability ?? 0,
                                       smithSkill(smith), shop);
      return true;
    }
  }
  return false;
}

//: Те же доводы, что у варки: 0x417BD8 в движке тоже идёт по всем записям.
//: `crew` — кому раздавать откованное: жители своей карты или их снимки.
export function villageForge(phases = 1, data = null, official = null,
                             crew = null) {
  const village = data ?? world.map?.village;
  if (!village || phases < 1) return 0;
  const shop = workshopRules();
  const smith = official
    ?? units.find((unit) => officialRole(unit) === 4 && unit.alive !== false);
  if (!smith) return 0;
  const box = counterBox(smith, 4, village);
  const culture = village.culture ?? 0;
  let made = 0;
  for (let phase = 0; phase < phases; phase += 1) {
    if (village.forgeOrder == null || village.forgeOrder < 0) {
      //: Заказа нет — первое годное свободное место: порог не выше навыка,
      //: место прилавка пусто (0x417BD8, выбор заказа).
      village.forgeOrder = -1;
      const skill = smithSkill(smith);
      for (let place = 0; place < SMITH_PLACES; place += 1) {
        const what = smithNeed(place, culture);
        if (!what || what.need > skill) continue;
        if (box.slots[place]) continue;
        village.forgeOrder = place;
        village.forgeLeft = orderTicks(
          what.need, Math.trunc(skill / (shop.skill_divisor ?? 10)) + 1, shop);
        break;
      }
      // Всё годное отковано — раздача жителям, но не при живом отряде
      // события (0x417BD8 зовёт 0x435214, ту же проверку, что обработчик 23).
      //: Отряд события виден только на СВОЕЙ карте: у дальней деревни его
      //: событий в памяти нет, и раздача там идёт без этой оговорки.
      if (village.forgeOrder < 0 && (data ? true : !eventAlive())) {
        if (giveForged(village, smith, box, shop, crew ?? units)) made += 1;
      }
      continue;
    }
    village.forgeLeft = (village.forgeLeft ?? 0) - 1;
    if (village.forgeLeft >= 1) continue;
    const what = smithNeed(village.forgeOrder, culture);
    if (what && !box.slots[village.forgeOrder]) {
      if (place(smith, box, village.forgeOrder, what.class)) {
        made += 1;
        // Рост мастера (хвост 0x417BD8): sqrt-формула, кап 100.
        const skill = smithSkill(smith);
        setSmithSkill(smith, Math.min(100,
          roundHalfEven(Math.sqrt(what.need * 2 + skill * skill + 10))));
      }
    }
    village.forgeOrder = -1;
  }
  return made;
}
