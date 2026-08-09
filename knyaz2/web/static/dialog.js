// Разговор с жителем.
//
// Дерево разговора приезжает в паке прямо из QUESTS.RES: узлы по 8 байт
// (действие, следующий, условие, фраза), у реплики следом идут варианты
// ответа. Номер диалога лежит в самом юните (+0xF2), а начинает разговор
// VA 0x4369A0. Здесь повторяется то, что уже разобрано: показать реплику,
// дать выбрать ответ, выполнить его команды и перейти дальше.
//
// Команды разговора — общий язык действий и условий (VA 0x435F44 и
// 0x436664). Разобраны три вида: поставить или снять бит состояния
// собеседника (+0xF7), поставить или снять состояние квеста и вызвать
// обработчик из таблицы 0x462E90. Первые два выполняются здесь, обработчики
// (торговля, найм в отряд, стройка) пока только называются номером.
import { world } from "./world.js";
import { hero, heroDie } from "./hero.js";
import { tradeOpen } from "./trade.js";
import { isNight } from "./daylight.js";
import { actorItem, actorNewItemRef } from "./actor.js";
import { grantExperience } from "./progress.js";
import { currentCharacteristics, identifyAll } from "./jewels.js";
import { bagPut } from "./inventory.js";
import { nameOfClassAny } from "./questitems.js";
import { daylight } from "./daylight.js";
import { village } from "./village.js";
import { partyHire, units } from "./units.js";
import { warbandAlarm, warbands } from "./warband.js";
import { lootDrop } from "./loot.js";
import { craftWhetstone } from "./craft.js";
import { mapSquads, mapStateSquads } from "./mapstate.js";
import { openLocation } from "./worldmap.js";
import { playVoiceLine } from "./sound.js";
import { orderKinds, orderUnit } from "./orders.js";
import { clockPhaseHits } from "./clock.js";

export const dialog = {
  unit: null,          // с кем говорим
  line: null,          // текущая реплика
  quests: new Map(),   // состояния квестов: номер -> true/false (бит 0x80)
  approach: new Set(), // «подойди и заговори»: номера диалогов (бит 0x01)
  flags: new Map(),    // биты состояния собеседников: "юнит:бит" -> true
  pending: [],         // обработчики действий, которых мы ещё не перенесли
  missing: new Map(),  // обработчики УСЛОВИЙ: номер -> сколько раз спросили
};

// НАЧАЛЬНОЕ СОСТОЯНИЕ КВЕСТОВ — хвост QUESTS.RES (300 dword, 0x6A50E8).
// Раньше порт не читал его вовсе и начинал с пустоты. Пустой ЖУРНАЛ в начале
// игры — это канон (бит 0x80 не взведён ни у одного из трёхсот), а вот шесть
// взведённых битов 0x01 порт терял, и сюжетные встречи не запускались.
export function questsReset() {
  const rules = world.map?.hero?.rules?.quests ?? null;
  dialog.quests.clear();
  dialog.approach.clear();
  const flags = rules?.flags ?? [];
  const known = rules?.known_bit ?? 0x80;
  const approach = rules?.approach_bit ?? 0x01;
  for (let index = 0; index < flags.length; index += 1) {
    if (flags[index] & known) dialog.quests.set(index, true);
    if (flags[index] & approach) dialog.approach.add(index);
  }
}

// СЮЖЕТНАЯ ВСТРЕЧА: NPC САМ ЗАГОВАРИВАЕТ (VA 0x410684).
//
// Условия движка, по порядку: у юнита есть диалог (+0xF2 != −1), младшая
// половина его приказа НЕ единица, текущая карта (0x8496C8) не 26 и не 27,
// у его диалога взведён бит 1, и он рядом с игроком — не дальше ШЕСТИ клеток
// по строке и ТРЁХ по столбцу (в записи юнита +0x12 это строка, +0x14 —
// столбец). Тогда движок пишет игроку целый байт приказа 0x22 и целью —
// номер этого юнита. То есть игрок идёт заговаривать сам, будто щёлкнул.
//
// Зовётся это из такта поведения NPC (0x413894) под гейтом
// `(_DAT_0084962c & 0xF) == 0`, раз в шестнадцать мировых тактов. Здесь
// проход отдельный, а не внутри unitsTick, только чтобы не заводить петлю
// импортов: dialog.js уже тянет units.js, обратно нельзя.
const APPROACH_ROWS = 6, APPROACH_COLS = 3;
const APPROACH_SKIP_MAPS = new Set([0x1A, 0x1B]);

// НОМЕР ТЕКУЩЕЙ КАРТЫ — аналог глобала 0x8496C8.
//
// Поля `map.number` в паке НЕТ вовсе: карта опознаётся строкой
// `id: "legacy:18"`, а число лежит в `legacy.map_number` (так его и читает
// ui.js:232). Три места в этом файле спрашивали несуществующее поле, и хуже
// всех приходилось условию 19 «мы на карте N»: оно сравнивало строку
// "legacy:18" с числом и потому было ВСЕГДА ЛОЖНЫМ.
function mapNumber() {
  return world.map?.legacy?.map_number ?? -1;
}

// Потолок здоровья — 0x640 на всех (VA 0x41C494, 0x4347D8). Читаем правило
// пака напрямую, а не через effects.js: тот тянет units.js, и вышла бы петля.
function healthMax() {
  return world.map?.hero?.rules?.effects?.health?.max ?? 1600;
}

export function dialogApproachTick() {
  if (dialog.unit) return null;              // разговор уже идёт
  if (!clockPhaseHits(0xF)) return null;
  if (!dialog.approach.size) return null;
  const map = mapNumber();
  if (APPROACH_SKIP_MAPS.has(map)) return null;
  const kinds = orderKinds();
  for (const unit of units) {
    if (unit === hero || unit.alive === false) continue;
    const number = unit.dialog?.number;
    if (number == null || !dialog.approach.has(number)) continue;
    if ((unit.orderByte & 0x0F) === 1) continue;
    if (!hero.cell || !unit.cell) continue;
    if (Math.abs(hero.cell.row - unit.cell.row) > APPROACH_ROWS) continue;
    if (Math.abs(hero.cell.col - unit.cell.col) > APPROACH_COLS) continue;
    orderUnit(hero, unit.cell.row, unit.cell.col, kinds.talk, unit);
    // Движок пишет БАЙТ ЦЕЛИКОМ (0x22), а не только младшую половину:
    // старший разряд 0x20 «иду по приказу игрока» тоже выставляется.
    hero.orderByte = 0x22;
    return unit;
  }
  return null;
}

// ЖУРНАЛ (VA 0x42A8F4, ветка 1). Показываются записи, у которых взведён бит
// 0x80 И есть номер фразы; строки «MAP=» движок пропускает — их отсеял ещё
// сборщик пака, положив в journal −1.
export function dialogJournal() {
  const rules = world.map?.hero?.rules?.quests ?? null;
  const journal = rules?.journal ?? [];
  const text = rules?.text ?? {};
  const out = [];
  for (let index = 0; index < journal.length; index += 1) {
    if (journal[index] < 0) continue;
    if (dialog.quests.get(index) !== true) continue;
    const line = text[String(index)];
    if (line) out.push({ quest: index, text: line });
  }
  return out;
}

//: Навык героя по имени из правил пака — для гейтов условий разговора.
function heroSkill(name) {
  const names = world.map?.hero?.rules?.progression?.skills?.names ?? [];
  const index = names.indexOf(name);
  return index >= 0 ? hero.skills?.[index] ?? 0 : 0;
}

//: То же у любого юнита — лекари и кузнецы разговоров.
function unitSkill(unit, name) {
  const names = world.map?.hero?.rules?.progression?.skills?.names ?? [];
  const index = names.indexOf(name);
  return index >= 0 ? unit?.skills?.[index] ?? 0 : 0;
}

//: Рост навыка на единицу с потолком сто — как учат лечение и починка.
function growSkill(unit, name) {
  const names = world.map?.hero?.rules?.progression?.skills?.names ?? [];
  const index = names.indexOf(name);
  if (index < 0 || !unit) return;
  unit.skills = unit.skills ?? [];
  unit.skills[index] = Math.min(100, (unit.skills[index] ?? 0) + 1);
}

//: Подъём характеристики игрока НАВСЕГДА (0x436BA8): база и спрятанная
//: копия, кламп 0…150 — как у порошков.
function liftCharacteristic(index, gain) {
  const cap = world.map?.hero?.rules?.progression?.characteristics?.cap ?? 150;
  const lift = (list) => {
    if (!list) return;
    list[index] = Math.max(0, Math.min(cap, (list[index] ?? 0) + gain));
  };
  lift(hero.baseCharacteristics);
  lift(hero.characteristics);
  lift(hero.savedCharacteristics);
  return true;
}

function nodesOf(unit) { return unit?.dialog?.nodes ?? []; }

function nodeByIndex(unit, index) {
  return nodesOf(unit).find((node) => node.node === index) ?? null;
}

// Развилку движок проходит так: идёт по подряд идущим записям, пока у них
// есть условие и оно НЕ выполнено; первая подошедшая даёт переход
// (VA 0x436478). Запись без условия срабатывает всегда, а переход на -1
// закрывает разговор.
//
// Предела глубины у движка нет — там `while (true)`, и на закольцованных
// данных завис бы и оригинал. Здесь считаем узлы: пройти больше, чем их
// есть, честная цепочка не может, а страница от петли не встанет.
function resolve(unit, index, guard = 0) {
  const node = nodeByIndex(unit, index);
  if (!node || guard > nodesOf(unit).length) return null;
  if (node.kind === "line") return node;
  for (const branch of node.branches ?? []) {
    if (branch.always || conditionMet(unit, branch.condition)) {
      return branch.next >= 0 ? resolve(unit, branch.next, guard + 1) : null;
    }
  }
  return null;
}

// Условие варианта (VA 0x436664). Накопитель начинается с истины, и команды
// вычисляются ЛЕНИВО, по своему биту:
//
//     И-команда (0x40000000)  считается, только пока накопитель истинен
//     ИЛИ-команда             считается, только пока накопитель ложен
//
// То есть это короткое замыкание: истину ИЛИ-команда не перезаписывает, а
// пропущенная команда не вычисляется вовсе — её побочных действий не будет.
// Неизвестное пропускаем как выполненное, иначе разговор оборвётся на
// первом же шаге.
function conditionMet(unit, condition) {
  let result = true;
  for (const command of condition ?? []) {
    // пропуск по короткому замыканию: обработчик даже не зовётся
    if (command.and ? !result : result) continue;
    let value = true;
    if (command.kind === "quest") {
      value = dialog.quests.get(command.quest) === true;
    } else if (command.kind === "unit_flag") {
      value = dialog.flags.get(`${unit.id}:${command.bit}`) === true;
    } else if (command.kind === "handler") {
      const handler = HANDLERS[command.handler];
      if (!handler) {
        // Неразобранный обработчик УСЛОВИЯ молча считается выполненным, и
        // из-за этого квест проходится без своего условия.
        //
        // ЧИСЛА НА 2026-08-09, пересчитаны по всем 8000 узлам QUESTS.RES:
        // условий такого рода 37 из 1561, и 34 из них — один обработчик 0
        // «карта зачищена». Действий не работает 208 из 1374. Прежняя цифра
        // «1457 из 2143» осталась с той поры, когда перенесено было мало
        // обработчиков, и много лет вводила в заблуждение.
        //
        // Считаем их здесь, а сам `dialog` вынесен в `window.knyaz2`: без
        // этого счётчики копились, но посмотреть их было негде, и пробел
        // вылезал только в игре.
        dialog.missing.set(command.handler,
          (dialog.missing.get(command.handler) ?? 0) + 1);
        continue;
      }
      value = Boolean(handler(command.argument));
    } else {
      continue;
    }
    if (command.set) value = !value;  // в условии старший бит значит «не»
    result = command.and ? (result && value) : value;
  }
  return result;
}

function runActions(unit, actions) {
  for (const command of actions ?? []) {
    if (command.kind === "quest") {
      dialog.quests.set(command.quest, command.set);
    } else if (command.kind === "unit_flag") {
      dialog.flags.set(`${unit.id}:${command.bit}`, command.set);
    } else if (command.kind === "handler") {
      if (!runHandler(command)) {
        dialog.pending.push({ handler: command.handler, argument: command.argument });
      }
    }
  }
}

// Место поселения по номеру из реплики — общий разбор условий 4 и 6.
// Первые семь мест «особые» и спрашиваются номером напрямую. Место с
// седьмого движок адресует иначе: берёт байт +0x00 записи поселения и
// прибавляет семь, а при нулевом байте +0x01 отказывает сразу
// (VA 0x434AF0 и 0x434BC4 — одинаково в обоих).
//
// Раньше здесь читались village.extra_slots и village.first_slot, которых
// в паке нет вовсе: ветка «аргумент больше шести» была мертва и всегда
// давала ложь. Теперь оба байта приезжают полями slots_a и slots_b.
function villagePlace(argument) {
  const data = world.map?.village;
  if (!data) return null;
  let slot = argument;
  if (argument >= 7) {
    if (!data.slots_b) return null;
    slot = (data.slots_a ?? 0) + 7;
  }
  return (data.buildings ?? []).find((building) => building.slot === slot) ?? null;
}

// Лучшие «Строительные навыки» в отряде деревни (VA 0x432C9C: максимум
// байта +0xE4 по юнитам отряда). Отряд — тот, чья сторона записана в байте
// +0x02 поселения.
function villageBuildSkill() {
  const data = world.map?.village;
  const set = world.map?.hero?.rules?.buildings;
  const index = set?.build_skill_index ?? 18;
  if (!data) return 0;
  let best = 0;
  for (const unit of units) {
    if (unit.side !== data.side) continue;
    const value = unit.skills?.[index] ?? 0;
    if (value > best) best = value;
  }
  return best;
}

// Отряд уходит с этой карты — общая часть действий 44 и 70. В движке это
// не смерть: отряду пишется другая карта (действие 70) или ноль (44), а
// клетки его живых бойцов освобождаются, и на ЭТОЙ карте его больше нет
// (VA 0x433C30, VA 0x435B60). Карта у отряда у нас не хранится — юниты
// живут только на текущей и приезжают из пака при входе, — поэтому видимая
// часть та же, что у действия 46: бойцы убираются из мира.
function squadLeaves(side) {
  if (side === undefined || side === null) return false;
  let left = 0;
  for (const unit of [...units]) {
    if (unit.side !== side) continue;
    const at = units.indexOf(unit);
    if (at >= 0) units.splice(at, 1);
    unit.cell = null;
    left += 1;
  }
  const band = warbands.get(side);
  if (band) {
    band.fighting = false;
    band.count = 0;
  }
  if (dialog.unit?.side === side) dialog.unit = null;
  return left > 0;
}

// Обработчики команд разговора (таблица 0x462E90). Здесь только те, что
// разобраны по коду; остальные копятся в dialog.pending, чтобы было видно,
// чего ещё не хватает.
const HANDLERS = {
  // 45: забрать у игрока предмет заданного класса (VA 0x433D38)
  45: (argument) => {
    const bag = hero.bag ?? [];
    const index = bag.findIndex((name) => actorItem(name)?.index === argument);
    if (index < 0) return false;
    // Движок не оставляет дырки: он освобождает запись предмета и
    // СДВИГАЕТ хвост мешка влево, обнуляя последнюю ячейку (VA 0x433D38).
    bag.splice(index, 1);
    bag.push(null);
    return true;
  },
  // 51: дать опыт (VA 0x434504 -> 0x413110). Награда идёт ИГРОКУ и
  // ЦЕЛИКОМ: четверть убийцы (VA 0x414150) к разговору отношения не имеет.
  51: (argument) => { grantExperience(hero, argument); return true; },
  // Гейты по навыкам ГЕРОЯ — однострочные условия «аргумент не больше
  // навыка» (номера сняты с таблицы 0x462E90 и прибиты контрактом):
  // 5: Строительные навыки (VA 0x434B88, unit+0xE4)
  5: (argument) => argument <= heroSkill("Строительные навыки"),
  // 10: Знахарство (VA 0x434DEC, unit+0xDD)
  10: (argument) => argument <= heroSkill("Знахарство"),
  // 26: Кузнечное дело (VA 0x4353FC, unit+0xE3)
  26: (argument) => argument <= heroSkill("Кузнечное дело"),
  // 32: свой ли юнит (VA 0x435650). Аргумент ноль — про собеседника, иначе
  // ищется юнит с таким номером, и не нашёлся — ложь.
  32: (argument) => {
    const unit = argument ? unitByNumber(argument) : dialog.unit;
    if (!unit) return false;
    return (unit.side ?? 0) === (hero.side ?? 0);
  },
  // 23: жив ли отряд события на карте (VA 0x435214). Аргумент — НОМЕР
  // КАРТЫ, ноль значит текущую. Событие засчитывается, только если в его
  // отряде есть хоть один живой боец: флаг 0x80 в +0x1A снят и тип не
  // 3, 0x0B, 0x0C.
  23: (argument) => {
    const map = argument || mapNumber();
    return (world.map?.events ?? []).some((event) => {
      if (!event.active || (event.map ?? map) !== map) return false;
      return (event.members ?? []).some((member) =>
        !(member.flags & 0x80) && ![3, 0x0B, 0x0C].includes(member.type ?? 0));
    });
  },
  // 27: чья деревня (VA 0x435438): -1 спрашивает «принадлежит ли кому-то»,
  // иначе сравнивает владельца (запись поселения +0x4A0) с аргументом.
  27: (argument) => {
    const village = world.map?.village;
    if (!village) return false;
    if (argument === -1) return Boolean(village.owned);
    return village.owner === argument;
  },
  // 28: разрешение по флагам деревни (VA 0x4354A8): ноль всегда «да»,
  // иначе смотрит биты 0x15 байта +0x49C.
  28: (argument) => {
    const village = world.map?.village;
    if (!village) return false;
    if (!argument) return true;
    return ((village.flags ?? 0) & 0x15) === 0;
  },
  // 30: занимает ли собеседник должность (VA 0x435550): пять мест по u16
  // с +0x3D0 записи поселения, номер юнита сравнивается напрямую.
  30: (argument) => {
    const officials = world.map?.village?.officials ?? [];
    const index = Number(String(dialog.unit?.id ?? "").replace("unit_", ""));
    return officials[argument] === index;
  },
  // 38: торговля (VA 0x43346C). У должностей 2, 3 и 4 в правый ряд идёт
  // ПРИЛАВОК деревни своей длины на должность — 22, 32 и 39 мест — и цены
  // считаются деревенские; у прочих собственный мешок и их же деньги.
  //
  // Проверки «торговать нечем» в движке НЕТ: оба выхода функции возвращают
  // единицу и открывают экран, даже если и прилавок, и мешок пусты.
  38: () => {
    const unit = dialog.unit;
    if (!unit) return false;
    const role = dialogRole();
    const village = role >= 2 && role <= 4;
    const sizes = world.map?.hero?.rules?.trade?.counters ?? {};
    const limit = sizes[String(role)]?.slots ?? 42;
    const stock = village
      ? (unit.counter ?? []).slice(0, limit)
      : (unit.bag ?? []);
    dialogClose();
    if (village) unit.role = role;
    tradeOpen(unit, stock, village);
    world.onTrade?.(unit);
    return true;
  },
  // 21: сейчас ночь (VA 0x4350C0 отдаёт флаг 0x8495CC, который ставит
  // расчёт неба). Ночью жители отвечают своё: «дай хоть ночью отдохнуть».
  21: () => isNight(),
  // Бросок «один к N» (VA 0x435340). Так выбираются случайные реплики.
  // Меньше двух — движок кладёт в остаток
  // ноль, не бросая жребия вовсе, и проверка «остаток равен нулю» даёт
  // ИСТИНУ. То есть аргумент 0, 1 и любой отрицательный — всегда да.
  24: (argument) => argument < 2 || Math.floor(Math.random() * argument) === 0,
  // 4: есть ли постройка в этом месте списка поселения (VA 0x434AF0).
  // Первые семь мест «особые», их движок и спрашивает номером.
  //
  // Разбор места общий с условием 6 — см. villagePlace ниже.
  4: (argument) => {
    const found = villagePlace(argument);
    if (!found) return false;
    // «Постройка есть» движок решает по ДВУМ полям записи места: байту
    // +0x19 и слову +0x1E; хватает любого ненулевого. Ровно эту пару и
    // считает поле `built` пака, поэтому больше здесь смотреть нечего.
    //
    // Раньше в ИЛИ стоял ещё и `kind` — байт ВИДА (+0x18). Он заполнен и у
    // непостроенных мест (карта 19, место 1: вид 3, состояние 0), поэтому
    // «постройка есть» отвечало да там, где движок отвечает нет.
    return Boolean(found.built);
  },
  // 6: МОЖНО ЛИ ЗАЛОЖИТЬ ПОСТРОЙКУ (VA 0x434BC4). То же, что 4, плюс два
  // условия: у места задан вид и в отряде деревни есть достаточно умелый
  // строитель.
  //
  // Это НЕ про деньги, хотя конспект quests.py и называл сверяемое «ценой
  // вида, а казну — VA 0x432C9C». Сама 0x432C9C казны не считает: она
  // проходит по юнитам отряда и возвращает МАКСИМУМ байта +0xE4, то есть
  // лучший навык 18 «Строительные навыки» (блок навыков идёт с +0xD2).
  // Сверяется он с младшей половиной слова +0x04 записи вида
  // (`&DAT_0045d844 + вид * 0x10`), и числа это подтверждают: у изб и
  // казарм там единица, у кузницы тройка — ценами в монетах такие быть не
  // могут.
  6: (argument) => {
    const found = villagePlace(argument);
    if (!found) return false;
    // Вид места движок читает знаковым байтом и при отрицательном
    // отказывает сразу — место без назначения не закладывают.
    const kind = found.kind ?? -1;
    if (kind < 0 || kind > 0x7F) return false;
    if (found.built) return false;
    const set = world.map?.hero?.rules?.buildings;
    const need = set?.kinds?.[String(kind)]?.build_skill ?? 0;
    return villageBuildSkill() >= need;
  },
  // 17: ЕСТЬ ЛИ У ИГРОКА ПРЕДМЕТ ЭТОГО КЛАССА (VA 0x434F8C). Движок
  // перебирает сорок две ячейки мешка (unit+0x62) и сравнивает класс
  // записи (+3) с аргументом; возвращает номер ячейки плюс один. Это и
  // есть проверка квестового предмета — без неё квест шёл даром.
  17: (klass) => {
    const bag = hero.bag ?? [];
    for (let index = 0; index < bag.length; index += 1) {
      const item = bag[index] ? actorItem(bag[index]) : null;
      if (item && item.index === klass) return index + 1;
    }
    return 0;
  },
  // 20: хватает ли денег (VA 0x435088). Цена в реплике названа ДЕСЯТКАМИ:
  // движок сравнивает аргумент, умноженный на десять, с деньгами отряда.
  20: (price) => (hero.money ?? 0) >= price * 10,
  // 13: облик игрока (VA 0x434EA0) — байт unit+0xFC, то самое тело, что
  // меняет Чистая слеза. Сравнивается с аргументом напрямую.
  13: (shape) => (hero.body ?? 0) === shape,
  // 7: ЕСТЬ ЛИ МЕСТО В ОТРЯДЕ (VA 0x434CD0). Вместимость не константа:
  // движок считает её из ХАРИЗМЫ вожака (unit+0xCC >> 4) + 1, не больше
  // девяти, кладёт в запись отряда и сравнивает с числом бойцов. Отсюда и
  // «некуда взять» при низкой Харизме. Байт +0xCC — ТЕКУЩАЯ Харизма, то
  // есть с прибавками надетых украшений, не базовая.
  7: () => {
    const set = world.map?.hero?.rules?.party;
    const charisma = currentCharacteristics(hero)[0] ?? 0;
    const capacity = Math.min(set?.capacity_max ?? 9,
      (charisma >> (set?.capacity_shift ?? 4)) + 1);
    const inParty = 1 + (world.units ?? []).filter((unit) => unit.ally &&
      unit.alive !== false).length;
    return inParty < capacity;
  },
  // 29: занята ли должность в деревне (VA 0x435500) — пять мест по слову
  // с +0x3D0 записи поселения.
  29: (place) => Boolean((world.map?.village?.officials ?? [])[place]),

  // 36: ВЗЯТЬ СОБЕСЕДНИКА В ОТРЯД (VA 0x433070). Движок дописывает его
  // запись в КОНЕЦ отряда игрока и правит её:
  //
  //     +0x1B  сторона игрока
  //     +0x16  0x10 — «за вожаком», с этого мига он ходит следом
  //     +0xE6  восемь байт рабочих мест забиваются 0xFF: новичок
  //            перестаёт быть жителем деревни и ходить на её работы
  //     +0x1A  младшие три бита породы гасятся
  //
  // Из прежнего отряда он вычёркивается, и счётчик того отряда убавляется.
  // Здесь то же самое в нашей модели: свои живут одним списком с признаком
  // ally, поэтому «переписать в отряд» — это сменить сторону и признак.
  36: () => {
    const unit = dialog.unit;
    if (!unit || unit.alive === false) return false;
    unit.ally = true;
    unit.side = hero.side ?? 0;
    unit.orderByte = 0x10;          // за вожаком
    unit.orderKind = 0;
    unit.orderTarget = null;
    unit.workplaces = [];           // деревенские работы за ним больше не числятся
    unit.workRest = 0;
    unit.breed = (unit.breed ?? 0) & ~0x07;
    unit.hostile = false;
    // ДОПИСАТЬ В ЗАПИСЬ ОТРЯДА — это и есть наём (0x433070 копирует запись в
    // слот `первый + число бойцов`). Без этого боец оставался юнитом карты:
    // в панель отряда он не попадал и пропадал на первой же смене карты.
    partyHire(unit);
    world.onStatus?.(`${unit.name} присоединяется к отряду`);
    return true;
  },

  // 63: ОТКРЫТЬ ЛОКАЦИЮ НА КАРТЕ (VA 0x435818 -> 0x436908). Хребет сюжета:
  // без него игрок не узнаёт, куда идти дальше. Движок ставит клетке
  // локации бит 0x40 «видно» и снимает 0x80 «закрыто сюжетом», а саму
  // локацию отмечает в таблице 0x8442A0. Аргумент — номер локации.
  63: (location) => Boolean(openLocation(location)),

  // 60: ДАТЬ ИЛИ ЗАБРАТЬ ДЕНЬГИ (VA 0x435724): `игрок+0x26 += аргумент*10`.
  // Цена в разговоре названа ДЕСЯТКАМИ — та же шкала, что у условия 20
  // «хватает денег». Отрицательный аргумент забирает.
  60: (amount) => {
    hero.money = (hero.money ?? 0) + amount * (world.map?.hero?.rules?.dialog?.money_step ?? 10);
    return true;
  },

  // 37: ПОДНЯТЬ ОТРЯД СОБЕСЕДНИКА НА ИГРОКА (VA 0x4333A4). Ветка пишет
  // флаги прямо, минуя объявление 0x4159DC и его маску: враг и единица
  // ложатся и в запись отряда собеседника, и в запись отряда игрока.
  37: () => {
    const unit = dialog.unit;
    if (!unit) return false;
    warbandAlarm(hero, unit, world.units ?? []);
    return true;
  },

  // 0: КАРТА ЗАЧИЩЕНА (VA 0x4348F8). Аргумент несёт два байта: младший —
  // номер карты, старший — сколько отрядов на ней пропустить. Движок идёт по
  // отрядам подряд, берёт (пропустить + 1)-й из стоящих на этой карте (отряд
  // игрока не в счёт) и отвечает НУЛЁМ, если в нём остался хоть один живой.
  // Кончились отряды — единица: зачищать нечего.
  //
  // Мы отвечаем по своей карте из живых юнитов, по чужой — из памяти карты,
  // снятой в миг ухода (mapstate.js). Про карту, где мы не были, честный
  // ответ «не зачищена»: раньше этот обработчик отсутствовал вовсе и все
  // тридцать четыре его вызова молча считались ИСТИНОЙ — награды и
  // продолжения выдавались, не зачистив карту.
  0: (argument) => {
    const map = argument & 0xFF;
    const skip = (argument >> 8) & 0xFF;
    const squads = mapNumber() === map
      ? mapSquads(world.units ?? units)
      : mapStateSquads(map);
    if (!squads) return false;          // там мы ещё не были
    const squad = squads[skip];
    return squad ? !squad.alive : true; // отряда нет — считается зачищенным
  },

  // --- опознание таблицы 0x462E90 (В5): простые условия ---
  // 1/15: гейты навыков, как 5/10/26.
  1: (argument) => argument <= heroSkill("Торговля"),
  15: (argument) => argument <= heroSkill("Идентификация предметов"),
  // 2: стоит ли флаг игрока (байт +0xF9; ставит 34, снимает 42).
  2: (argument) => Boolean(argument & (hero.flags ?? 0)),
  // 3: статус деревни (байт +0x49D).
  3: (argument) => (world.map?.village?.status ?? -1) === argument,
  // 8: деревня заложена ростовщику (бит 0x20 байта +0x49C; ставит 41).
  8: () => Boolean((world.map?.village?.flags ?? 0) & 0x20),
  // 9/16: ТЕКУЩИЕ характеристики вожака (байты +0xCC и +0xCE).
  9: (argument) => argument <= (currentCharacteristics(hero)[0] ?? 0),
  16: (argument) => argument <= (currentCharacteristics(hero)[2] ?? 0),
  // 11/12: здоровье не ниже сотой доли (аргумент*16 против +0x4E).
  11: (argument) => argument * 16 <= (hero.health ?? 0),
  12: (argument) => argument * 16 <= (dialog.unit?.health ?? 0),
  // 14: в отряде не меньше бойцов (счёт отряда +0x1C).
  14: (argument) => 1 + (world.units ?? []).filter((unit) => unit.ally &&
    unit.alive !== false).length >= argument,
  // 18: прошло времени с метки собеседника (+0x4C, пятнадцатые доли
  // тика суток; метку ставит действие 67).
  18: (argument) => {
    const now = Math.trunc((daylight.time ?? 0) / 15);
    return Math.abs(now - (dialog.unit?.talkStamp ?? 0)) >= argument;
  },
  // 19: мы на карте с этим номером (глобал 0x8496C8).
  19: (argument) => mapNumber() === argument,
  // 22: есть ли при игроке неопознанная вещь (бит 0x80 слова чар).
  22: () => {
    const dormant = hero.data?.rules?.jewellery?.enchant?.dormant ?? 0x8000;
    const words = [...Object.values(hero.enchant ?? {}),
                   ...Object.values(hero.bagEnchant ?? {})];
    return words.some((word) => word & dormant);
  },
  // 31: игрок вооружён — в руках что-то есть либо в мешке оружие
  // (группа 0 или 1).
  31: () => {
    if (hero.equipment?.hand || hero.equipment?.ranged) return true;
    return (hero.bag ?? []).some((name) => {
      const kind = name ? actorItem(name)?.kind : null;
      return kind === 0 || kind === 1;
    });
  },
  // 33: в отряде есть раненый (здоровье меньше 1600).
  33: () => [hero, ...(world.units ?? []).filter((unit) => unit.ally)]
    .some((unit) => unit.alive !== false && (unit.health ?? 1600) < 1600),

  // --- простые действия ---
  // 34/42: флаги игрока ставятся и снимаются; бит 2 не ставится, пока в
  // мешке предмет класса 33 (VA 0x432ED0).
  34: (argument) => {
    if (argument === 2 && (hero.bag ?? []).some((name) =>
      name && actorItem(name)?.index === 33)) return false;
    hero.flags = (hero.flags ?? 0) | argument;
    return true;
  },
  42: (argument) => { hero.flags = (hero.flags ?? 0) & ~argument; return true; },
  // 47: снять флаги собеседника.
  47: (argument) => {
    const unit = dialog.unit;
    if (!unit) return false;
    unit.flags = (unit.flags ?? 0) & ~argument;
    return true;
  },
  // 35: дать игроку предмет класса аргумент (создать запись — 0x432F1C).
  35: (argument) => {
    const classRef = nameOfClassAny(argument);
    if (!classRef) return false;
    return bagPut(actorNewItemRef(classRef, "dialog"), -1, hero) >= 0;
  },
  // 39: сменить статус деревни (байт +0x49D).
  39: (argument) => {
    const data = world.map?.village;
    if (!data) return false;
    data.status = argument;
    return true;
  },
  // 41: заложить (не ноль: бит 0x20, игроку +1000) или выкупить деревню
  // (ноль: бит долой, у игрока −1200). Возвращает НОЛЬ, как движок.
  41: (argument) => {
    const data = world.map?.village;
    if (!data) return false;
    if (argument) {
      data.flags = (data.flags ?? 0) | 0x20;
      hero.money = (hero.money ?? 0) + 1000;
    } else {
      data.flags = (data.flags ?? 0) & ~0x20;
      hero.money = (hero.money ?? 0) - 1200;
    }
    return false;
  },
  // 48: забрать у собеседника предмет группы 11 класса аргумент.
  48: (argument) => {
    const unit = dialog.unit;
    const bag = unit?.bag ?? [];
    for (let index = 0; index < bag.length; index += 1) {
      const item = bag[index] ? actorItem(bag[index]) : null;
      if (item && item.index === argument && item.kind === 11) {
        bag.splice(index, 1);
        bag.push(null);
        return true;
      }
    }
    return false;
  },
  // 49/53/68/73: поднять характеристику игроку НАВСЕГДА (0x436BA8:
  // база и спрятанная копия, кламп 0…150).
  49: (argument) => liftCharacteristic(1, argument),
  53: (argument) => liftCharacteristic(0, argument),
  68: (argument) => liftCharacteristic(4, argument),
  73: (argument) => liftCharacteristic(5, argument),
  // 52/66: затемнить и просветлить экран (фейд 0x8495C0 шагом 0x849588;
  // остальные действия ждут конца — 0x436A44). Состояния игры фейд не
  // трогает, у клиента переходы мгновенные.
  52: () => true,
  66: () => true,
  // 54/55/56: лечение Знахарством в разговоре (аргумент не участвует).
  54: () => {
    const skill = unitSkill(dialog.unit, "Знахарство");
    if (skill * 16 <= (hero.health ?? 0)) return true;
    growSkill(dialog.unit, "Знахарство");
    hero.health = unitSkill(dialog.unit, "Знахарство") * 16;
    return true;
  },
  55: () => {
    for (const unit of [hero, ...(world.units ?? []).filter((u) => u.ally)]) {
      if (unit.alive === false) continue;
      const skill = unitSkill(dialog.unit, "Знахарство");
      if (skill * 16 <= (unit.health ?? 0)) continue;
      growSkill(dialog.unit, "Знахарство");
      unit.health = unitSkill(dialog.unit, "Знахарство") * 16;
    }
    return true;
  },
  // 57: ЗДОРОВЬЕ ИГРОКУ (VA 0x4347D8). Аргумент ЗНАКОВЫЙ и задан В ПРОЦЕНТАХ:
  //
  //     игрок+0x4E += аргумент * 16;
  //     если значение >= 0x641 -> 0x640;   иначе если < 1 -> смерть;
  //     перерисовать портрет.
  //
  // Шестнадцать — та же шкала, что везде: полное здоровье 1600 это сто
  // процентов. Бьёт обработчик ВСЕГДА по игроку (0x84951C), цель действия
  // (0x849524) здесь не спрашивается — в отличие от 59.
  //
  // Пять вызовов во всей игре, и один из них — стражник, который перевязывает
  // раненого Эйнара перед допросом («Дай я тебя перевяжу», +40): тот стартует
  // с 640, то есть на 40%, и после перевязки у него 1280. Остальные четыре
  // бьют: −10, −10, −10 и −100. Без обработчика реплика показывалась, а
  // здоровье не менялось.
  57: (argument) => {
    const cap = healthMax();
    // аргумент приходит знаковым уже из разбора команд (konung2/quests.py)
    let health = (hero.health ?? 0) + argument * 16;
    if (health >= cap + 1) health = cap;
    hero.health = health;
    if (health < 1) { hero.alive = false; heroDie(); }
    return true;
  },
  56: () => {
    const unit = dialog.unit;
    if (!unit) return false;
    const skill = heroSkill("Знахарство");
    if (skill * 16 > (unit.health ?? 0)) {
      growSkill(hero, "Знахарство");
      unit.health = heroSkill("Знахарство") * 16;
    }
    return true;
  },
  // 58: опознать всё у игрока (0x41B7C0), Идентификация растёт внутри.
  58: () => { identifyAll(hero); return true; },
  // 67: метка времени собеседнику (слово +0x4C = время/15) — пара к 18.
  67: () => {
    const unit = dialog.unit;
    if (!unit) return false;
    unit.talkStamp = Math.trunc((daylight.time ?? 0) / 15);
    return true;
  },
  // 71: назначить владельца деревни; −1 — казна владения игроку.
  71: (argument) => {
    const data = world.map?.village;
    if (!data) return false;
    if (argument === -1) {
      hero.money = (hero.money ?? 0) + (data.owned ?? 0);
      data.owned = 0;
    } else {
      data.owner = argument;
    }
    return true;
  },
  // 72: тревога деревни: −1 биты 0x15; 0 бит 0x10 (казна стоит);
  // 1 — снять всё, казну владения в ноль, метка времени свежая.
  72: (argument) => {
    const data = world.map?.village;
    if (!data) return false;
    if (argument === -1) data.flags = (data.flags ?? 0) | 0x15;
    else if (argument === 0) data.flags = (data.flags ?? 0) | 0x10;
    else if (argument === 1) {
      data.flags = (data.flags ?? 0) & ~0x15;
      data.owned = 0;
      village.incomeStamp = daylight.time ?? 0;
    }
    return true;
  },

  // 59: СМЕНИТЬ ОБЛИК (VA 0x43487C). Целевому юниту действия (указатель
  // 0x849524 — по умолчанию собеседник): тело +0xFC = аргумент % 10,
  // палитра +0x2E = аргумент / 10 * 512 (байтовое смещение, как у
  // объектов), порода +0x1A гасится целиком, кадр пересобирается
  // (0x416740, 0x416E24). Чистая слеза тела НЕ меняет — только это
  // действие. Условие 13 сравнивает облик ВОЖАКА с аргументом.
  59: (argument) => {
    const unit = dialog.unit;
    if (!unit) return false;
    unit.body = ((argument % 10) + 10) % 10;
    // движок пишет байтовое смещение (арг/10 * 512); в паке палитра
    // ИНДЕКСОМ (кодек делит на 512) — значит здесь просто арг/10
    unit.palette = Math.trunc(argument / 10);
    unit.breed = 0;
    unit.beast = false;
    return true;
  },

  // 69: ПЕРЕНЕСТИ ОТРЯД ИГРОКА ПО ПЕРЕХОДУ (VA 0x435AA0). Функции нет в
  // декомпиляте — снята дизассемблером. Семнадцать вызовов: это сюжетные
  // телепорты, и без них разговор доводит до «пойдём» и никуда не ведёт.
  //
  //     запись = 0x7B2B6C + аргумент * 0x11;   // 17 байт, номер = место
  //     куда = (i8) запись[+4];
  //     если куда == -1 -> текущая карта = -1, экран 5 (глобальная);
  //     если куда == -2 -> то же плюс 0x84960C = -1 (особый переход);
  //     [0x8496D8] = -куда;                    // заявка на загрузку
  //     отряд+0x18 = запись[+2];               // поворот
  //     отряд+0x0C = слово запись[+5];         // клетка входа
  //     отряд+0x14 = запись[+7];
  //
  // Номер адресует ВЕСЬ граф, а не переходы текущей карты, поэтому пак
  // несёт таблицу целиком (`rules.transitions`, 250 записей).
  69: (argument) => {
    const graph = world.map?.hero?.rules?.transitions ?? [];
    const door = graph[argument];
    if (!door) return false;
    // ИМЕННО onTransition, а не onExit: движок переносит отряд безусловно, и
    // карта назначения бывает текущей. У выхода в дверь стоит гейт «уже на
    // этой карте», и через него приказ разговора пропадал молча.
    return Boolean(world.onTransition?.({ ...door,
      to_name: door.to_name ?? "переход" }));
  },

  // 46: УДАЛИТЬ ЮНИТА ИЗ МИРА (VA 0x433E30). Функции нет в выгрузке
  // декомпилята — снята дизассемблером целиком. Самое частое из
  // непеpенесённых действий: 61 вызов, и без него квестовые NPC после
  // разговора остаются стоять на месте.
  //
  // Порядок движка:
  //   цель = аргумент ? юнит_по_номеру(аргумент) : цель_действия;
  //   если цели нет -> 0;
  //   сетка[строка*0x280 + столбец*4] &= 0xF000;      // клетка чистится
  //   FUN_00420d5c(цель);
  //   если сторона цели == стороне игрока:
  //       отряд+0x1C--;                                // бойцов меньше
  //       записи массива сдвигаются на 0x100 вверх;    // и панель девяти
  //   иначе если поселение той же стороны:
  //       из пяти должностей (+0x3D0) своя обнуляется,
  //       а стоящие ПОСЛЕ неё уменьшаются на единицу.
  //
  // Сдвиги индексов повторять НЕ НАДО: они целиком следствие того, что
  // движок держит юнитов непрерывным массивом по 0x100 байт и хранит на них
  // указатели. У нас юниты — объекты по ссылке, и вычёркивания достаточно;
  // должность же освобождается по-настоящему, это не артефакт.
  46: (argument) => {
    const unit = argument ? unitByNumber(argument) : dialog.unit;
    if (!unit) return false;
    const at = units.indexOf(unit);
    if (at >= 0) units.splice(at, 1);
    unit.alive = false;
    unit.cell = null;
    // Должности поселения: своя освобождается — движок пишет в её слово
    // (+0x3D0) ноль, а стоящие после неё уменьшает на единицу; уменьшать нам
    // нечего, у нас не индексы в массиве, а ссылки.
    const officials = world.map?.village?.officials;
    if (Array.isArray(officials)) {
      const place = officials.indexOf(unit.slot);
      if (place >= 0) officials[place] = 0;
    }
    // Разговор с исчезнувшим продолжать не с кем.
    if (dialog.unit === unit) dialog.unit = null;
    return true;
  },

  // 40: ЗАЛОЖИТЬ ПОСТРОЙКУ (VA 0x433730). Аргумент меньше семи — одно
  // «особое» место; иначе закладываются ВСЕ обычные разом: движок идёт от
  // места `slots_a + 7` и берёт их `slots_b` штук.
  //
  // В счётчик места кладётся СЫРОЙ срок вида (таблица 0x45D848, у нас
  // rules.buildings.kinds[вид].build_time) — БЕЗ деления на число
  // работников. Делит уже мировой такт, когда ступень сменится
  // (VA 0x41C944). Поэтому первая ступень заложенной постройки проходит
  // быстрее следующих — так в движке и есть, это не наша вольность.
  40: (argument) => {
    const data = world.map?.village;
    if (!data) return false;
    const places = data.buildings ?? [];
    let chosen;
    if (argument < 7) {
      chosen = places.filter((place) => place.slot === argument);
    } else {
      const first = (data.slots_a ?? 0) + 7;
      const count = data.slots_b ?? 0;
      chosen = places.filter((place) => place.slot >= first &&
                                        place.slot < first + count);
    }
    const kinds = world.map?.hero?.rules?.buildings?.kinds ?? {};
    for (const place of chosen) {
      const time = kinds[String(place.kind)]?.build_time ?? 1;
      place.timer = time;
      // Счётчик, по которому реально идёт стройка, живёт у постройки на
      // карте: её место названо полем village_slot (buildings.js).
      for (const object of world.objects ?? []) {
        if (object.village_slot === place.slot) object.timer = time;
      }
    }
    return true;
  },

  // 44: УВЕСТИ ОТРЯД СОБЕСЕДНИКА С КАРТЫ (VA 0x433C30).
  44: () => squadLeaves(dialog.unit?.side),

  // 50: СОБЕСЕДНИК СБРАСЫВАЕТ СНАРЯЖЕНИЕ (VA 0x434478). Все пять надетых
  // гнёзд (+0x58…+0x60) освобождаются, и каждая вещь ложится кучей в его
  // клетку (0x423360). Порядок гнёзд — движковый, он же порядок ячеек.
  50: () => {
    const unit = dialog.unit;
    if (!unit?.equipment) return false;
    let dropped = false;
    for (const slot of ["hand", "ranged", "body", "head", "off_hand"]) {
      const name = unit.equipment[slot];
      if (!name) continue;
      unit.equipment[slot] = null;
      lootDrop(name, unit.x, unit.y, unit.cell ? { ...unit.cell } : null);
      dropped = true;
    }
    return dropped;
  },

  // 64: ПОМИРИТЬ ОТРЯД ЦЕЛИ (VA 0x435844). Аргумент ноль — собеседник,
  // иначе юнит с этим номером. Отряду его СТОРОНЫ гасится бой (+0x1D) и
  // снимается младший бит боевых битов (+0x1F) — тот самый, которым
  // warbandDeclare запоминает обидчика.
  64: (argument) => {
    const unit = argument ? unitByNumber(argument) : dialog.unit;
    if (!unit) return false;
    const band = warbands.get(unit.side ?? 0);
    if (!band) return false;
    band.fighting = false;
    band.warFlags = (band.warFlags ?? 0) & ~1;
    return true;
  },

  // 65: ПОЧИНИТЬ СНАРЯЖЕНИЕ ОТРЯДА (VA 0x4358BC). Собеседник чинит каждому
  // живому бойцу отряда игрока все пять надетых вещей и все сорок две
  // ячейки мешка — тем же кодом, что точильный камень (repairweapon).
  // Потолок прочности ставит «Кузнечное дело» СОБЕСЕДНИКА, а сама прочность
  // правится у владельца вещи; за удачную починку растёт навык починившего.
  65: () => {
    const smith = dialog.unit;
    if (!smith) return false;
    const party = [hero, ...units.filter((unit) => unit.ally)];
    for (const owner of party) {
      if (owner.alive === false) continue;
      const worn = Object.values(owner.equipment ?? {}).filter(Boolean);
      const bag = (owner.bag ?? []).filter(Boolean);
      for (const name of [...worn, ...bag]) craftWhetstone(name, smith, owner);
    }
    return true;
  },

  // 70: УВЕСТИ ОТРЯД СОБЕСЕДНИКА ПО ПЕРЕХОДУ (VA 0x435B60). Движок берёт
  // запись перехода, ставит отряду её карту и зону скитаний вокруг клетки
  // прибытия — ПЛЮС-МИНУС число бойцов минус один, — и переносит туда.
  //
  // Перенос между картами у нас не моделируется (юниты живут только на
  // текущей), поэтому здесь делается то, что видно с этой карты: зона
  // скитаний правится по записи перехода, а отряд с карты уходит.
  70: (argument) => {
    const side = dialog.unit?.side;
    const band = side === undefined || side === null ? null : warbands.get(side);
    const door = (world.map?.exits ?? []).find((exit) => exit.index === argument);
    if (band && door) {
      const half = Math.max(0, (band.count ?? 1) - 1);
      band.roam = {
        row_from: (door.entry_row ?? 0) - half,
        row_to: (door.entry_row ?? 0) + half,
        col_from: (door.entry_col ?? 0) - half,
        col_to: (door.entry_col ?? 0) + half,
      };
    }
    return squadLeaves(side);
  },

  // 75: НАЗНАЧИТЬ РАБОТУ СОБЕСЕДНИКУ (VA 0x435EA4). Восемь его рабочих мест
  // (+0xE6) очищаются, первым ставится аргумент, и снимается бит 0x40 байта
  // +0x19 — «занят приказом», из-за которого житель стоял бы на месте.
  75: (argument) => {
    const unit = dialog.unit;
    if (!unit) return false;
    unit.workplaces = [argument];
    unit.busy = false;
    return true;
  },

  // 62: ПОДОЙДИ И ЗАГОВОРИ (VA 0x4357B4) и 61: ОТБОЙ (VA 0x435750, снято
  // дизассемблером — в декомпиляте функции нет). Пара зеркальных действий
  // над битом 1 состояния квеста с номером ДИАЛОГА цели (unit+0xF2):
  // 62 ставит `| 1`, 61 гасит `& 0xFE`. Аргумент 0 — цель действия, то есть
  // собеседник; иначе юнит по номеру (0x432D1C).
  //
  // Бит читает 0x410684: NPC с ним, оказавшись в шести клетках по X и трёх
  // по Y от игрока, сам переводит игрока в приказ 0x22 на себя. Так в
  // оригинале начинаются сюжетные встречи — шесть штук взведено уже в
  // QUESTS.RES.
  62: (argument) => questApproach(argument, true),
  61: (argument) => questApproach(argument, false),
};

function questApproach(argument, armed) {
  const unit = argument ? unitByNumber(argument) : dialog.unit;
  const number = unit?.dialog?.number;
  if (number == null) return false;
  if (armed) dialog.approach.add(number);
  else dialog.approach.delete(number);
  return true;
}
// Таблица видна снаружи там же, где missing и pending: чтобы разобранное
// можно было проверить с живой страницы, а не только по коду.
dialog.handlers = HANDLERS;

// Юнит по номеру слота — движок ищет его в общем массиве (VA 0x432D1C).
function unitByNumber(number) {
  return (world.units ?? []).find((unit) => unit.slot === number) ?? null;
}

// Должность собеседника: номер его места в списке должностей плюс один
// (VA 0x415190).
function dialogRole() {
  const officials = world.map?.village?.officials ?? [];
  const index = Number(String(dialog.unit?.id ?? "").replace("unit_", ""));
  const place = officials.indexOf(index);
  return place < 0 ? 0 : place + 1;
}

function runHandler(command) {
  const handler = HANDLERS[command.handler];
  if (!handler) return false;
  try { return handler(command.argument) !== false; } catch { return false; }
}

// Показ реплики (VA 0x436478). Реплика без единого прошедшего условия
// варианта не показывается вовсе: движок возвращает 0, и вызывающий
// сворачивает экран разговора (VA 0x436A44). Иначе разговор завис бы
// открытым, а отвечать было бы нечем.
function show(unit, line) {
  if (!line) return null;
  if (!dialogOptionsOf(unit, line).length) return null;
  return line;
}

// Озвучка реплики (VA 0x436478): номер записи voices.res лежит в самой
// фразе (поле voice узла), питч — личная частота «голоса» собеседника,
// то есть номера его диалога (_VOICES, VA 0x42A43C). Новая реплика глушит
// предыдущую в самом ядре; закрытие окна голос НЕ обрывает — в движке
// канал реплик останавливает только следующая реплика.
function speak(unit, line) {
  if (line?.voice) playVoiceLine(line.voice, unit?.dialog?.number ?? null);
}

export function dialogStart(unit) {
  const root = unit?.dialog?.root;
  if (root == null) return false;
  dialog.unit = unit;
  // Пока идёт разговор, собеседник стоит и смотрит на игрока
  // (VA 0x413894, случай 0x0C сверяет юнита с 0x849524).
  world.talking = { unit };
  dialog.line = show(unit, resolve(unit, root));
  if (!dialog.line) { dialogClose(); return false; }
  runActions(unit, dialog.line.actions);
  speak(unit, dialog.line);
  world.onDialog?.(dialog);
  return true;
}

function dialogOptionsOf(unit, line) {
  // Вариант без условия проходит всегда (поле условия -1 в записи узла).
  return (line?.options ?? []).filter((option) =>
    option.always || conditionMet(unit, option.condition));
}

export function dialogOptions() {
  return dialogOptionsOf(dialog.unit, dialog.line);
}

export function dialogChoose(option) {
  if (!dialog.unit || !option) return false;
  runActions(dialog.unit, option.actions);
  const next = option.next >= 0
    ? show(dialog.unit, resolve(dialog.unit, option.next)) : null;
  if (!next) return dialogClose();
  dialog.line = next;
  runActions(dialog.unit, next.actions);
  speak(dialog.unit, next);
  world.onDialog?.(dialog);
  return true;
}

// Есть ли у юнита разговор: в паке это дерево узлов, а в движке — номер
// разговора в unit+0xF2, и «нет разговора» там 0xFF.
export function hasTalk(unit) {
  if (!unit?.dialog?.nodes?.length) return false;
  // Мёртвого с номером разговора от восьми движок заговорить не даёт
  // (VA 0x4369A0): флаг 0x80 в +0x1A и dialog >= 8 закрывают вход.
  const dead = unit.alive === false || Boolean(unit.hidden);
  if (dead && (unit.dialog.number ?? 0) >= 8) return false;
  return true;
}

export function dialogClose() {
  // Разговор кончился — собеседник свободен и идёт своей дорогой.
  world.talking = null;
  dialog.unit = null;
  dialog.line = null;
  world.onDialog?.(dialog);
  return false;
}
