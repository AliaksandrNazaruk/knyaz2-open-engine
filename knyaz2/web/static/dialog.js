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
import { hero, heroCellToggle, heroDie } from "./hero.js";
import { tradeOpen } from "./trade.js";
import { isNight } from "./daylight.js";
import { actorItem, actorNewItemRef } from "./actor.js";
import { grantExperience } from "./progress.js";
import { currentCharacteristics, identifyAll } from "./jewels.js";
import { JEWEL_SLOTS, bagPut } from "./inventory.js";
import { nameOfClassAny } from "./questitems.js";
import { eventFighterAlive, officialRole, village, villageState }
  from "./village.js";
import { partyHire, partyRelease, unitSendTo, units } from "./units.js";
import { warbandAlarm, warbands } from "./warband.js";
import { lootDrop } from "./loot.js";
import { craftWhetstone } from "./craft.js";
import { mapSquads, mapStateJoin, mapStateSquads, mapStateUnjoin }
  from "./mapstate.js";
import { openLocation, worldMap } from "./worldmap.js";
import { playVoiceLine } from "./sound.js";
import { deselect, orderKinds, orderUnit } from "./orders.js";
import { clock, clockPhaseHits } from "./clock.js";

export const dialog = {
  unit: null,          // с кем говорим
  line: null,          // текущая реплика
  quests: new Map(),   // состояния квестов: номер -> true/false (бит 0x80)
  approach: new Set(), // «подойди и заговори»: номера диалогов (бит 0x01)
  //: ЧТО ИЗ ЭТОГО НАБОРА ИЗМЕНИЛ РАЗГОВОР — номер -> взведён ли. Сам набор
  //: приходит из пака и в сохранении ему делать нечего: сохранённый плоский
  //: список пережил бы правку данных и вернул отменённое. Так и вышло —
  //: донорские квесты переехали со 128 на 152, у Фёдоры (разговор 136) бит
  //: в паке снялся, а сейв приносил его обратно, и она по-прежнему сама
  //: заговаривала. Хранить надо ПРАВКИ, а исходное брать из пака.
  approachEdits: new Map(),
  flags: new Map(),    // биты состояния собеседников: "юнит:бит" -> true
  pending: [],         // обработчики действий, которых мы ещё не перенесли
  missing: new Map(),  // обработчики УСЛОВИЙ: номер -> сколько раз спросили
  //: ПОСЕЛЕНИЕ, ВЫБРАННОЕ РАЗГОВОРОМ. «Продолжение легенды» умеет
  //: переключать контекст на деревню другой карты (его обработчик 72,
  //: VA 0x438DC4 пишет запись в свою глобальную ячейку), и дальше про
  //: постройки и должности спрашивают уже про НЕЁ. Ноль возвращает
  //: поселение своей карты.
  villageOverride: null,
};

//: Поселение, о котором идёт речь: выбранное разговором или своей карты.
export function dialogVillage() {
  return dialog.villageOverride ?? world.map?.village ?? null;
}

// НАЧАЛЬНОЕ СОСТОЯНИЕ КВЕСТОВ — хвост QUESTS.RES (300 dword, 0x6A50E8).
// Раньше порт не читал его вовсе и начинал с пустоты. Пустой ЖУРНАЛ в начале
// игры — это канон (бит 0x80 не взведён ни у одного из трёхсот), а вот шесть
// взведённых битов 0x01 порт терял, и сюжетные встречи не запускались.
export function questsReset() {
  const rules = world.map?.hero?.rules?.quests ?? null;
  dialog.quests.clear();
  dialog.approach.clear();
  dialog.approachEdits.clear();
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
    // ПРИКАЗ ВЫДАЁТСЯ ОДИН РАЗ НА СОБЕСЕДНИКА. Пока герой идёт, эта ветка
    // срабатывает каждые шестнадцать тактов, и раньше она переписывала
    // приказ заново — со всеми последствиями:
    //   * `onOrder` на каждый повтор кричит оклик «Эй, есть разговор!»
    //     (слоты 700…723). Игрок слышал пятнадцать «Э!» подряд за один
    //     подход — жалоба 17.08.2026, поймана хвостом sound.recent;
    //   * `orderUnit` при выдаче СБРАСЫВАЕТ маршрут (`path = []`), то есть
    //     герой пересчитывал дорогу по два раза в секунду всю дорогу.
    // Идём к нему же — значит приказ уже отдан, и делать нечего.
    if (hero.orderTarget === unit && (hero.orderByte & 0x0F) === kinds.talk) {
      return null;
    }
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

//: Метка времени разговора (+0x4C): мировой такт, урезанный до слова, в
//: пятнадцатых долях (VA 0x435A2C пишет, 0x434FFC читает). Слово, а не
//: полный счётчик, — потому и круг у метки 65536 тактов.
function talkStampNow() {
  return Math.trunc((clock.ticks & 0xFFFF) / 15);
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
      value = unitFlagGet(unit, command.bit) === true;
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

// БИТ СОСТОЯНИЯ СОБЕСЕДНИКА — ПО УСТОЙЧИВОЙ ИДЕНТИЧНОСТИ. Ключ по
// `unit.id` жил тремя жизнями у одного персонажа: `unit_N` жителем,
// `mate_N` спутником и снова `unit_N` после «останься здесь» — биты
// терялись на каждом переходе состояния; а между картами `unit_N`
// ещё и коллидировал (донорские слоты). Пара «родная карта : слот»
// одна на все три состояния. Старый ключ читается запасным — ради
// прежних сейвов.
function unitFlagKey(unit, bit) {
  return `${unit.homeMap ?? "?"}:${unit.slot}:${bit}`;
}

function unitFlagGet(unit, bit) {
  const value = dialog.flags.get(unitFlagKey(unit, bit));
  if (value !== undefined) return value;
  return dialog.flags.get(`${unit.id}:${bit}`);
}

//: ИСПОЛНИТЬ СКРИПТ КВЕСТА (его 0x439864; механика ОБЩАЯ — канонный квест
//: 96 открывает клетку карты 14 тем же путём, и порт не делал этого
//: никогда). «Взвести квест» у движка значит поставить бит 0x80 И исполнить
//: строку фразы журнала:
//:
//:     MAP=карта,строка,столбец,значение   клетке XOR значение: пустота
//:                                         0x4FFF^0x4FFF=0 — проход открылся
//:     OBJECT=карта,запись,x,y             объекту карты новые экранные x,y;
//:                                         в (-1000,-1000) — спрятать
//:     LANDSCAPE=карта,запись,x,y          то же оверлею земли
//:
//: Все три исполняются ТОЛЬКО когда стоишь на названной карте (движок
//: сверяет первый довод с текущей) — и правка живёт в памяти живой карты.
//: Перезаход перечитывает пак, поэтому правка запоминается в mapstate;
//: снятие квеста скрипт НЕ исполняет — как в движке.
function questScriptRun(number) {
  const script = world.map?.hero?.rules?.quests?.scripts?.[String(number)];
  if (!script) return false;
  // Запоминать правку отдельно не нужно: постоянство даёт повтор при
  // входе на карту (questEditsReplay), как в движке. Запись в mapstate
  // здесь удваивала бы применение — XOR клетки вернулся бы в исходное.
  return questScriptApply(script);
}

//: ВЗВЕСТИ ТОКЕН СНАРУЖИ — через мир, а не импортом: квестовые вещи
//: (questitems.js, «Берестяная грамота» ставит токен 0) не могут тянуть
//: dialog.js — он сам берёт у них nameOfClassAny, вышло бы кольцо.
world.questTokenSet = (number) => {
  dialog.quests.set(number, true);
  questScriptRun(number);
};

export function questScriptApply(script) {
  const [map, slot, x, y] = script?.args ?? [];
  if (!script || mapNumber() !== map) return false;
  if (script.kind === "map") {
    // слова довода: строка, столбец, сырое значение (клиенту не нужно —
    // на уровне стен XOR пустоты это переключение клетки)
    return heroCellToggle(slot, x);
  }
  const pool = script.kind === "object" ? world.objects
    : script.kind === "landscape" ? world.terrainOverlays : null;
  const entry = (pool ?? []).find((row) => row.record_slot === slot);
  if (!entry) return false;
  const dx = x - (entry.position?.x ?? 0);
  const dy = y - (entry.position?.y ?? 0);
  entry.position = { x, y };
  if (entry.bounds) {
    entry.bounds.draw_x += dx;
    entry.bounds.draw_y += dy;
    entry.bounds.sort_y += dy;
  }
  if (script.kind === "object") {
    // порядок глубины пересчитывается: объект мог переехать по вертикали
    world.objects.sort((a, b) => a.bounds.sort_y - b.bounds.sort_y ||
      a.bounds.draw_x - b.bounds.draw_x || a.record_slot - b.record_slot);
    world.objects.forEach((object, index) => { object.draw_order = index; });
  }
  return true;
}

//: ЗАГРУЗКА КАРТЫ ПЕРЕИГРЫВАЕТ ВСЕ ВЗВЕДЁННЫЕ ТОКЕНЫ — зовёт app.js после
//: постройки сцены. В движке это цикл по всем тремстам записям состояний
//: в загрузчике (донорский 0x4417E0): у кого стоит бит 0x80, тому заново
//: исполняется командная фраза, и правка ложится на свежепрочитанную
//: карту. Раньше здесь переигрывался сохранённый список правок mapstate —
//: но квест, взведённый НЕ на своей карте, туда не попадал вовсе (сам
//: questScriptRun на чужой карте отказывает), и брод на Переправе через
//: реку не открывался никогда. Сохранённые правки старых сейвов теперь
//: просто не читаются: состояние квестов — единственный источник.
export function questEditsReplay(number) {
  const scripts = world.map?.hero?.rules?.quests?.scripts ?? {};
  let applied = 0;
  for (const [key, script] of Object.entries(scripts)) {
    if (dialog.quests.get(Number(key)) !== true) continue;
    if (questScriptApply(script)) applied += 1;
  }
  return applied;
}

function runActions(unit, actions) {
  for (const command of actions ?? []) {
    if (command.kind === "quest") {
      dialog.quests.set(command.quest, command.set);
      // Скрипт исполняется на ВЗВОДЕ, снятие его не трогает (0x4399C8:
      // ветка без бита SET лишь гасит 0x80).
      if (command.set) questScriptRun(command.quest);
    } else if (command.kind === "unit_flag") {
      dialog.flags.set(unitFlagKey(unit, command.bit), command.set);
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
  const data = dialogVillage();
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
  const data = dialogVillage();
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
    // ПОМЕТКА, А НЕ ВЫРЕЗАНИЕ. Снимок карты (mapStateCapture) идёт по
    // массиву юнитов: вырезанный до ухода в память не попадал, и на
    // следующем входе отряд возвращался из пака — «квесты сбросились».
    // Ушедший остаётся в массиве до свёртки с полями removed/hidden.
    unit.removed = true;
    unit.hidden = true;
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
//: ОБРАБОТЧИКИ «ПРОДОЛЖЕНИЯ ЛЕГЕНДЫ», КОТОРЫХ У КАНОНА НЕТ ВОВСЕ.
//:
//: Канон владеет номерами 0…75, и класть туда чужой обработчик нельзя — там
//: он значит другое. Поэтому у проекта свой участок: его обработчик H живёт
//: под номером 128 + H (konung2/donor.py: PROJECT_HANDLER_BASE). Правило то
//: же, что у карт и локаций: канон владеет началом, проект продолжением.
const PROJECT_HANDLER_BASE = 128;

const HANDLERS = {
  // 128+49: прибавить к репутации (его VA 0x436A14).
  //
  // РЕПУТАЦИЯ — механика донора, которой у нас нет. Он держит её глобальным
  // числом (0x87F410), показывает в панели персонажа рядом с уровнем и
  // свободным опытом (0x433C30) и пишет в сохранение (0x425158). Стартовое
  // значение у каждого его героя своё: −30, 0, −100, 30. Нашим героям
  // репутации не назначено, и придумывать её было бы враньём — берём ноль.
  //
  // Это вторая по величине дыра донорских разговоров после его 35-го:
  // прибавление зовут 360 раз, проверку — 101.
  [PROJECT_HANDLER_BASE + 49]: (argument) => {
    hero.reputation = (hero.reputation ?? 0) + argument;
    return true;
  },
  // 128+8: репутация не меньше довода (его VA 0x438120).
  [PROJECT_HANDLER_BASE + 8]: (argument) => argument <= (hero.reputation ?? 0),

  // ---- прочие обработчики «Продолжения легенды» ---------------------
  // Все разобраны по его декомпиляту (engine/decompiled_legend); поля юнита
  // и поселения — наши же, из konung2/gamefile.py.

  // 128+12: ХВАТИТ ЛИ У ЛЕКАРЯ УМЕНИЯ НА МОИ РАНЫ (его VA 0x438210).
  // `Знахарство собеседника * 16` должно превышать здоровье игрока; при
  // ненулевом доводе сверх того требуется порог 0x5F0, то есть навык 95.
  // Самое частое из его собственных: 74 вызова.
  [PROJECT_HANDLER_BASE + 12]: (argument) => {
    const power = unitSkill(dialog.unit, "Знахарство") * 16;
    if (power <= (hero.health ?? 0)) return false;
    return argument === 0 || power >= 0x5F0;
  },

  // 128+21: НАДЕТО ЛИ НА ИГРОКЕ УКРАШЕНИЕ ЭТОГО КЛАССА (его VA 0x4384B0).
  // Пять слотов с +0xB6 записи юнита — это украшения: ожерелье, два
  // браслета и два кольца (JEWEL_SLOTS). Всеми 26 вызовами он спрашивает
  // про класс 3, «Волшебный фиал с кровью Титанов».
  [PROJECT_HANDLER_BASE + 21]: (argument) => JEWEL_SLOTS.some((slot) => {
    const name = hero.equipment?.[slot];
    return Boolean(name) && actorItem(name)?.index === argument;
  }),

  // 128+26: ПОСТРОЙКА В ЗАДАННОМ СОСТОЯНИИ (его VA 0x4386E0). Довод несёт
  // два байта: младший — номер объекта постройки, старший — состояние.
  // Ищет место с таким номером объекта и сравнивает его ступень.
  [PROJECT_HANDLER_BASE + 26]: (argument) => {
    const object = argument & 0xFF;
    const state = (argument >> 8) & 0xFF;
    const found = (dialogVillage()?.buildings ?? []).find(
      (building) => building.object === object);
    return Boolean(found) && (found.state ?? 0) === state;
  },

  // 128+29 и 128+30: «Следопыт» не ниже довода — у игрока и у собеседника
  // (его VA 0x43890C и 0x438948, байт +0xDF записи юнита).
  [PROJECT_HANDLER_BASE + 29]: (argument) => argument <= heroSkill("Следопыт"),
  [PROJECT_HANDLER_BASE + 30]: (argument) =>
    argument <= unitSkill(dialog.unit, "Следопыт"),

  // 128+33 и 128+38: «Сила» и «Выносливость» игрока не ниже довода
  // (его VA 0x438A2C и 0x438C24, байты +0xD0 и +0xD1).
  [PROJECT_HANDLER_BASE + 33]: (argument) =>
    argument <= (hero.characteristics?.[4] ?? 0),
  [PROJECT_HANDLER_BASE + 38]: (argument) =>
    argument <= (hero.characteristics?.[5] ?? 0),

  // 128+51: ПРИБАВИТЬ К НАВЫКУ «Смертельный удар» (его VA 0x436AA4, зовёт
  // его VA 0x43A538: байт +0xD4 записи юнита, кламп 0…100).
  [PROJECT_HANDLER_BASE + 51]: (argument) => {
    const names = world.map?.hero?.rules?.progression?.skills?.names ?? [];
    const index = names.indexOf("Смертельный удар");
    if (index < 0) return false;
    hero.skills = hero.skills ?? [];
    hero.skills[index] = Math.max(0, Math.min(100,
      (hero.skills[index] ?? 0) + argument));
    return true;
  },

  // 128+62: ОБЪЯВИТЬ ВОЙНУ ОТРЯДОМ СОБЕСЕДНИКА (его VA 0x437804). Довод
  // ИЛИ-ится в байт +0x1F записи отряда — тот самый, где у нас живут биты
  // «на игрока» (0x01), «на отряды» (0x04), «только если дерутся» (0x08) и
  // «особый» (0x80).
  [PROJECT_HANDLER_BASE + 62]: (argument) => {
    const unit = dialog.unit;
    if (!unit) return false;
    const band = warbands.get(unit.side ?? 0);
    if (!band) return false;
    band.war = (band.war ?? 0) | argument;
    warbandAlarm(hero, unit, world.units ?? []);
    return true;
  },

  // 128+61: ПОКАЗАТЬ СООБЩЕНИЕ (его VA 0x437754). Строку он собирает из
  // своих кусков в exe; у нас окна для неё пока нет, поэтому действие
  // считается выполненным и уходит в `pending` — молчать о нём нельзя.
  [PROJECT_HANDLER_BASE + 61]: () => {
    dialog.pending.push({ handler: PROJECT_HANDLER_BASE + 61 });
    return true;
  },

  // 128+71: ПРИБАВИТЬ К «Интеллекту» ИГРОКА НАВСЕГДА (его VA 0x437BE0,
  // зовёт его VA 0x43A498: базовый байт +0xC2 и скрытая копия +0xC8,
  // кламп 0…150).
  [PROJECT_HANDLER_BASE + 71]: (argument) => liftCharacteristic(2, argument),

  // 128+72: СДЕЛАТЬ ТЕКУЩИМ ПОСЕЛЕНИЕ ЭТОЙ КАРТЫ (его VA 0x438DC4). Ноль
  // возвращает поселение своей карты. Дальше на него смотрят обработчики
  // построек и должностей — то есть это ПЕРЕКЛЮЧАТЕЛЬ КОНТЕКСТА, а не
  // действие над миром.
  [PROJECT_HANDLER_BASE + 72]: (argument) => {
    const found = argument ? villageState(argument) : null;
    dialog.villageOverride = argument ? (found ?? null) : null;
    return Boolean(!argument || found);
  },

  // 128+75: ПОСТАВИТЬ ПОСТРОЙКУ (его VA 0x438ED0). Ищет место с таким
  // номером объекта и пишет единицу в слово +6 записи — тот самый счётчик,
  // по которому «постройка есть» отвечает да.
  [PROJECT_HANDLER_BASE + 75]: (argument) => {
    const found = (dialogVillage()?.buildings ?? []).find(
      (building) => building.object === argument);
    if (!found) return false;
    found.timer = 1;
    found.built = true;
    return true;
  },

  // 128+91: НАЗНАЧИТЬ РАБОТУ ВСЕМУ ОТРЯДУ СОБЕСЕДНИКА (его VA 0x439714).
  // То же, что наш 75 «назначить работу собеседнику», но по всем бойцам
  // отряда, и номер места растёт на единицу с каждым.
  [PROJECT_HANDLER_BASE + 91]: (argument) => {
    const unit = dialog.unit;
    if (!unit) return false;
    let place = argument;
    let touched = 0;
    for (const other of world.units ?? []) {
      if ((other.side ?? 0) !== (unit.side ?? 0)) continue;
      other.workplaces = [place];
      other.busy = false;
      place += 1;
      touched += 1;
    }
    return touched > 0;
  },

  // 128+80: ВЫБРАТЬ СОБЕСЕДНИКА ПО НОМЕРУ (его VA 0x4390B8). Дальше
  // разговор говорит уже с ним. Нет такого юнита — ложь, и ветка не идёт.
  [PROJECT_HANDLER_BASE + 80]: (argument) => {
    if (!argument) return false;
    const found = unitByNumber(argument);
    if (!found) return false;
    dialog.unit = found;
    return true;
  },
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
      //: Бойцы лежат в `units`; мерка живого — общая с кузницей, чтобы две
      //: копии одного правила движка (0x435214) не разошлись.
      return (event.units ?? []).some(eventFighterAlive);
    });
  },
  // 27: чья деревня (VA 0x435438): -1 спрашивает «принадлежит ли кому-то»,
  // иначе сравнивает владельца (запись поселения +0x4A0) с аргументом.
  27: (argument) => {
    const village = dialogVillage();
    if (!village) return false;
    if (argument === -1) return Boolean(village.owned);
    return village.owner === argument;
  },
  // 28: разрешение по флагам деревни (VA 0x4354A8): ноль всегда «да»,
  // иначе смотрит биты 0x15 байта +0x49C.
  //
  // ДОВОД ДВУХБАЙТОВЫЙ, и старший байт — НОМЕР КАРТЫ поселения, ноль значит
  // текущее. Так его читает «Продолжение легенды» (его обработчик 35,
  // FUN_00438AD8: ищет запись по номеру карты через FUN_0043F670, дальше
  // проверка та же буквально). Наша игра сюда шлёт только 0 и 1, то есть
  // всегда «текущее поселение», и для неё ничего не меняется; донор же
  // спрашивает про дальние деревни — карты 6, 8 и 15, девять раз.
  28: (argument) => {
    const where = (argument >> 8) & 0xFF;
    const village = where ? villageState(where) : dialogVillage();
    if (!village) return false;
    if (!(argument & 0xFF)) return true;
    return ((village.flags ?? 0) & 0x15) === 0;
  },
  // 30: занимает ли собеседник должность (VA 0x435550): пять мест по u16
  // с +0x3D0 записи поселения, номер юнита сравнивается напрямую.
  //
  // Сравниваем СЛОТ, а не разбор id: должность и пишется слотом (действие
  // 74), а у поднятого из памяти экс-спутника id — `mate_N`, и разбор
  // `replace("unit_")` давал NaN. NaN не равен ничему — воеводская ветка
  // Путяты не открывалась никогда, «не могу его забрать».
  30: (argument) => {
    const officials = dialogVillage()?.officials ?? [];
    const slot = dialog.unit?.slot;
    return slot != null && officials[argument] === slot;
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
    // +0x19 (ступень) и слову +0x1E (счётчик); хватает любого ненулевого.
    // Читаем их НАПРЯМУЮ, а не поле `built` из пака: пак знает лишь то, что
    // было при выпечке, а ступень и счётчик меняются по ходу игры.
    //
    // Раньше в ИЛИ стоял ещё и `kind` — байт ВИДА (+0x18). Он заполнен и у
    // непостроенных мест (карта 19, место 1: вид 3, состояние 0), поэтому
    // «постройка есть» отвечало да там, где движок отвечает нет.
    return Boolean((found.state ?? 0) || (found.timer ?? 0));
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
    // Место должно быть ПУСТЫМ: обе ветки 0x434BC4 требуют нулей и в ступени,
    // и в счётчике. Пока стройка идёт, счётчик не ноль — и староста больше не
    // предлагает заложить то, что уже строится.
    if ((found.state ?? 0) || (found.timer ?? 0)) return false;
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
  29: (place) => Boolean((dialogVillage()?.officials ?? [])[place]),

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
    // ИЗ ПРЕЖНЕГО ОТРЯДА ОН ВЫЧЁРКИВАЕТСЯ — обе ветки 0x433070: должность в
    // поселении обнуляется (слово +0x3D0), счётчик отряда деревни убавляется
    // (+0x1C -= 1). Без первого Путята держал место воеводы навсегда и
    // назначить другого было нельзя; без второго squad_people только рос,
    // и после пары кругов «отпустил/забрал» деревня считалась полной.
    // Сторону сверяем ДО того, как перепишем её на сторону игрока.
    const settlement = dialogVillage();
    if (settlement) {
      const officials = settlement.officials;
      if (Array.isArray(officials)) {
        const place = officials.indexOf(unit.slot);
        if (place >= 0) officials[place] = 0;
      }
      if (typeof settlement.side === "number" &&
          unit.side === settlement.side &&
          (settlement.squad_people ?? 0) > 0) {
        settlement.squad_people -= 1;
      }
    }
    // Запись приёмыша карты о нём больше не нужна: юнита теперь несёт
    // запись отряда, а оставленная память поднимала клона («два Белуна»).
    mapStateUnjoin(world.map?.legacy?.map_number, unit.slot);
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
  3: (argument) => (dialogVillage()?.status ?? -1) === argument,
  // 8: деревня заложена ростовщику (бит 0x20 байта +0x49C; ставит 41).
  8: () => Boolean((dialogVillage()?.flags ?? 0) & 0x20),
  // 9/16: ТЕКУЩИЕ характеристики вожака (байты +0xCC и +0xCE).
  9: (argument) => argument <= (currentCharacteristics(hero)[0] ?? 0),
  16: (argument) => argument <= (currentCharacteristics(hero)[2] ?? 0),
  // 11/12: здоровье не ниже сотой доли (аргумент*16 против +0x4E).
  11: (argument) => argument * 16 <= (hero.health ?? 0),
  12: (argument) => argument * 16 <= (dialog.unit?.health ?? 0),
  // 14: в отряде не меньше бойцов (счёт отряда +0x1C).
  14: (argument) => 1 + (world.units ?? []).filter((unit) => unit.ally &&
    unit.alive !== false).length >= argument,
  // 18: прошло времени с метки собеседника (+0x4C; метку ставит действие
  // 67). Мерка — МИРОВОЙ ТАКТ, УРЕЗАННЫЙ ДО СЛОВА, поделённый на 15
  // (VA 0x434FFC): `abs(метка − (такт & 0xFFFF) / 15) >= довод`. Здесь
  // стояло время СУТОК, и круг у него вчетверо короче движкового.
  18: (argument) => {
    return Math.abs(talkStampNow() - (dialog.unit?.talkStamp ?? 0)) >= argument;
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
  // Класс 4 «Грамота на владение кораблём» попутно выписывает корабельное
  // право текущей карте (0x84960C = карта; у донора 0x4360E8 зовёт
  // 0x435E00) — выход −2 оживает в самый миг получения бумаги.
  35: (argument) => {
    const classRef = nameOfClassAny(argument);
    if (!classRef) return false;
    if (argument === 4) {
      const here = world.map?.legacy?.map_number;
      if (Number.isFinite(here)) worldMap.ship = here;
    }
    return bagPut(actorNewItemRef(classRef, "dialog"), -1, hero) >= 0;
  },
  // 39: сменить статус деревни (байт +0x49D).
  39: (argument) => {
    const data = dialogVillage();
    if (!data) return false;
    data.status = argument;
    return true;
  },
  // 41: заложить (не ноль: бит 0x20, игроку +1000) или выкупить деревню
  // (ноль: бит долой, у игрока −1200). Возвращает НОЛЬ, как движок.
  41: (argument) => {
    const data = dialogVillage();
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
    world.healthSet?.(hero, unitSkill(dialog.unit, "Знахарство") * 16);
    return true;
  },
  55: () => {
    for (const unit of [hero, ...(world.units ?? []).filter((u) => u.ally)]) {
      if (unit.alive === false) continue;
      const skill = unitSkill(dialog.unit, "Знахарство");
      if (skill * 16 <= (unit.health ?? 0)) continue;
      growSkill(dialog.unit, "Знахарство");
      world.healthSet?.(unit, unitSkill(dialog.unit, "Знахарство") * 16);
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
    world.healthSet?.(hero, health);
    if (health < 1) { hero.alive = false; heroDie(); }
    return true;
  },
  56: () => {
    const unit = dialog.unit;
    if (!unit) return false;
    const skill = heroSkill("Знахарство");
    if (skill * 16 > (unit.health ?? 0)) {
      growSkill(hero, "Знахарство");
      world.healthSet?.(unit, heroSkill("Знахарство") * 16);
    }
    return true;
  },
  // 58: опознать всё у игрока (0x41B7C0), Идентификация растёт внутри.
  58: () => { identifyAll(hero); return true; },
  // 67: метка времени собеседнику (слово +0x4C = время/15) — пара к 18.
  67: () => {
    const unit = dialog.unit;
    if (!unit) return false;
    unit.talkStamp = talkStampNow();
    return true;
  },
  // 71: назначить владельца деревни; −1 — казна владения игроку.
  71: (argument) => {
    const data = dialogVillage();
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
    const data = dialogVillage();
    if (!data) return false;
    if (argument === -1) data.flags = (data.flags ?? 0) | 0x15;
    else if (argument === 0) data.flags = (data.flags ?? 0) | 0x10;
    else if (argument === 1) {
      data.flags = (data.flags ?? 0) & ~0x15;
      data.owned = 0;
      //: Метка выплаты живёт в мировых тактах (village.js, treasuryTick) —
      //: суточные часы здесь остались от прежней мерки и обнуляли срок в
      //: чужих единицах.
      village.incomeStamp = clock.ticks;
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
  //
  // ГРАФ БЕРЁТСЯ ПО ИГРЕ РАЗГОВОРА. У «Продолжения легенды» таблица своя —
  // 350 записей вместо наших 250, — и номер в ней значит другой переход.
  // Один общий граф уносил бы героя из донорского разговора в случайное
  // место, и молча: номер законный, запись есть, ошибки нет. Имя игры
  // несёт само дерево (konung2/quests.py: tree).
  69: (argument) => {
    const rules = world.map?.hero?.rules ?? {};
    const game = dialog.unit?.dialog?.game;
    const graph = (game && rules.transitions_by_game?.[game])
      ?? rules.transitions ?? [];
    const door = graph[argument];
    if (!door) return false;
    // Цель, которой у нас нет: карта чужой игры ещё не перенесена. Открыть
    // её нельзя — номер значил бы у нас другое место.
    if (door.foreign_map) return false;
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
    // ВЕТКА «СТОРОНА ИГРОКА» (0x433E30:29-35): союзник вычёркивается из
    // отряда — счёт −1, сдвиг хвоста, правка панели девяти. Так уходит
    // Лучеслав (узел 4582, действие 46). Без этого его иконка оставалась в
    // отряде, partyCapture возил запись дальше, spawnCompanion на каждом
    // входе ставил его рядом с героем, и квест закрывался заново.
    // ally снимаем: снимок жителей карты берёт только не-союзников, а без
    // снимка removed юнит воскресал бы из пака.
    if (unit.ally) {
      partyRelease(unit);
      deselect(unit);
      unit.ally = false;
    } else {
      // Иначе-ветка движка: житель вычёркивается из отряда своей деревни со
      // сдвигом массива (0x433E30:101-109) — счётчик отряда убавляется.
      const settlement = dialogVillage();
      if (settlement && typeof settlement.side === "number" &&
          unit.side === settlement.side &&
          (settlement.squad_people ?? 0) > 0) {
        settlement.squad_people -= 1;
      }
    }
    // Пометка вместо вырезания — иначе снимок карты его не увидит и на
    // следующем входе юнит вернётся из пака (см. squadLeaves).
    unit.removed = true;
    unit.hidden = true;
    unit.cell = null;
    // Должности поселения: своя освобождается — движок пишет в её слово
    // (+0x3D0) ноль, а стоящие после неё уменьшает на единицу; уменьшать нам
    // нечего, у нас не индексы в массиве, а ссылки.
    const officials = dialogVillage()?.officials;
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
    const data = dialogVillage();
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

  // 43: СДЕЛАТЬ СОБЕСЕДНИКА ЖИТЕЛЕМ (VA 0x4338B0). Это и есть просьба
  // «Останься здесь, пока я не хочу рисковать тобой» — единственный канонный
  // способ вывести спутника из отряда, не убивая его.
  //
  // Движок по шагам:
  //
  //     нет поселения ([0x849538] == 0)          -> ноль, ничего не менять
  //     отряд деревни полон (+0x1C == +0x1A)     -> ноль
  //     +0x19 &= 0xBF                             снять «занят работой»
  //     запись цели (256 байт) в конец отряда деревни, его +0x1C += 1
  //     +0x1B = отряд деревни, +0x16 = 0          приказа нет вовсе,
  //                                               вместе с битом 0x10
  //                                               «за вожаком»
  //     из отряда игрока вычеркнуть, +0x1C -= 1, сдвинуть хвост
  //     панель девяти: ушедшего убрать, пустую занять вожаком (0x420644)
  //
  // Слот освобождается сам собой: условие 7 сравнивает вместимость по
  // Харизме с тем же счётчиком бойцов, который только что убавился.
  //
  // Мест у деревни ровно столько, сколько отведено её отряду в массиве
  // юнитов (+0x1A). Запас заложен намеренно и невелик: в Борье 14 занято из
  // 17. Отказ движок никак не показывает — возврат действия отбрасывается
  // (0x435F44), поэтому и мы молчим.
  43: (argument) => {
    const settlement = dialogVillage();
    const unit = argument ? unitByNumber(argument) : dialog.unit;
    if (!settlement || !unit || unit.alive === false) return false;
    const places = settlement.squad_places ?? 0;
    const people = settlement.squad_people ?? 0;
    if (places && people >= places) return false;
    settlement.squad_people = people + 1;
    // Запись, по которой юнита поднимать при возвращении. Берём ДО того, как
    // его вычеркнут из отряда: в паке карты бывшего спутника нет, и без этой
    // записи он на ней просто не появится. В движке заботы нет вовсе — запись
    // юнита лежит в общем массиве и переживает всё (см. mapstate.js).
    const member = (hero.party?.members ?? [])
      .find((row) => row.index === unit.slot) ?? null;
    partyRelease(unit);
    unit.ally = false;
    if (typeof settlement.side === "number") unit.side = settlement.side;
    // Приказ обнуляется целиком: без бита «за вожаком» он остаётся стоять,
    // а любой новый приказ этот бит бы сохранил (0x416574 пишет
    // `вид | старое & 0xF0`).
    unit.orderByte = 0;
    unit.orderKind = 0;
    unit.orderTarget = null;
    unit.busy = false;
    deselect(unit);
    mapStateJoin(world.map?.legacy?.map_number, unit, member);
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
      // ЭТО НЕ МЁРТВАЯ ЗАПИСЬ, ХОТЬ И ВЫГЛЯДИТ ЕЮ. `roam` — прямоугольник
      // СКИТАНИЙ из записи отряда (konung2/gamefile.py, party_combat), а
      // `zone` рядом — зона появления, по ней идёт проверка агра. Скитания
      // у нас пока не ходят: их водит ИИ юнитов, который ещё не перенесён
      // (задача 12, VA 0x41611C и соседние). Поэтому поле пишется впрок и
      // ждёт читателя — не удалять как «никем не читаемое».
      band.roam = {
        row_from: (door.entry_row ?? 0) - half,
        row_to: (door.entry_row ?? 0) + half,
        col_from: (door.entry_col ?? 0) - half,
        col_to: (door.entry_col ?? 0) + half,
      };
    }
    return squadLeaves(side);
  },

  // 74: НАЗНАЧИТЬ СОБЕСЕДНИКА НА ДОЛЖНОСТЬ ДЕРЕВНИ (VA 0x435D4C).
  //
  // Аргумент — номер должности, и сами реплики его называют: 0 староста,
  // 1 знахарь, 2 купец, 3 кузнец, 4 воевода («останешься здесь воеводой и
  // будешь обучать военным навыкам жителей»). Пятёрка должностей лежит по u16
  // с +0x3D0 записи поселения.
  //
  // Движок сначала проверяет, что место свободно, потом заводит жителю запись
  // в отряде деревни (FUN_004338B0: копия 0x100 байт, если у культуры ещё
  // есть место) и вписывает её номер в должность. Роль потом читается обратно
  // перебором той же пятёрки — FUN_00415190 отдаёт «номер места + 1», поэтому
  // у знахаря роль 2, а у купца 3.
  //
  // Без этого действия НИ ОДНА должность не могла быть занята: воеводы нет —
  // некому обучать в казарме, кузнеца нет — мастерская стоит. Казарма при
  // этом ни на одной карте и ни в одном мире не построена изначально
  // (проверено по всем 52 картам и шести GAME.N), её сперва надо возвести.
  //
  // ПОРЯДОК ДВИЖКОВЫЙ: сперва проверка, что место свободно, потом переезд
  // в деревню общим действием 43, и лишь при его успехе — запись должности.
  // Если деревня переполнена, 0x4338B0 возвращает ноль, и 0x435D4C бросает
  // всё как было: должность не занимается, спутник остаётся в отряде.
  74: (post) => {
    const village = dialogVillage();
    const unit = dialog.unit;
    if (!village || !unit || unit.alive === false) return false;
    if (!(post >= 0 && post < 5)) return false;
    const officials = village.officials ?? (village.officials = [0, 0, 0, 0, 0]);
    // Занятую должность движок не перезаписывает — возвращает ноль.
    if (officials[post]) return false;
    // Переезд в отряд деревни — тот же 0x4338B0, что и у «Останься здесь».
    if (!HANDLERS[43](0)) return false;
    officials[post] = unit.slot;
    // Поле `role` не трогаем: роль выводится из этого же списка (0x415190),
    // и держать её вторым источником правды — значит однажды разойтись.
    // Восемь рабочих байт забиваются 0xFF, а первый получает НОМЕР
    // ДОЛЖНОСТИ (0x435D4C: `(&DAT_007b3bee)[i] = (char)param_1` сразу после
    // забивки восьмёрки) — у нас это единственный элемент списка.
    unit.workplaces = [post];
    unit.workRest = 0;
    // Уход из отряда, сторона деревни и снятый приказ — всё это сделал
    // обработчик 43 выше, как и в движке.
    //
    // НА СВОЁ МЕСТО, С ЗАНЯТИЕМ 0x0B (VA 0x435D4C, хвост):
    //
    //     (&DAT_007b3b1b)[i] = *(byte *)((int)psVar2 + должность * 4 + 0x21);
    //     (&DAT_007b3b1d)[i] = (char)psVar2[должность * 2 + 0x11];
    //     FUN_00416574(юнит, строка, столбец, 0xb);
    //
    // Байты +0x21 и +0x22 записи культуры со сдвигом «должность × 4» — это ТА
    // ЖЕ память, где лежит таблица рабочих мест (записи по четыре байта с
    // +0x20, поля: вид, строка, столбец, вес). Значит место должности N — это
    // строка и столбец рабочего места N, и они у нас уже в паке. Без этого
    // назначенный оставался стоять там, где с ним заговорили.
    const spot = (village.workplaces ?? []).find((place) => place.slot === post);
    if (spot) unitSendTo(unit, spot.row, spot.col, 0x0B);
    else unit.orderByte = 0x0B;
    return true;
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
  //: Помним ПРАВКУ, а не итог: набор пересобирается из пака при каждой
  //: загрузке, и поверх него ложится только то, что изменил разговор.
  dialog.approachEdits.set(number, armed);
  return true;
}
// Таблица видна снаружи там же, где missing и pending: чтобы разобранное
// можно было проверить с живой страницы, а не только по коду.
dialog.handlers = HANDLERS;

// Юнит по номеру слота — движок ищет его в общем массиве (VA 0x432D1C).
//
// В движке массив ГЛОБАЛЬНЫЙ и слот уникален; в порте слоты разных карт
// пересекаются (донорские несут свои номера), поэтому номер из данных
// диалога значит: юнит ЭТОЙ карты либо спутник (его номер — с карты
// найма, он и есть адресат «отпустить»/«назначить»). Чужаку с той же
// цифрой, но другой родной картой номер не принадлежит.
function unitByNumber(number) {
  const mapNumber = Number(world.map?.legacy?.map_number ?? NaN);
  return (world.units ?? []).find((unit) => unit.slot === number &&
    (unit.ally || unit.homeMap == null || unit.homeMap === mapNumber)) ?? null;
}

// Должность собеседника: номер его места в списке должностей плюс один
// (VA 0x415190).
//: Роль собеседника — та же выводимая из пятёрки должностей роль
//: (VA 0x415190). Своей копии здесь больше нет: хозяин один —
//: `village.js::officialRole`, и он же берёт номер юнита из `slot`.
function dialogRole() { return officialRole(dialog.unit); }

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
  //: Выбор чужого поселения живёт РОВНО ОДИН разговор: в движке его
  //: глобальную ячейку переставляет вход на карту, у нас переставлять
  //: нечему, поэтому сбрасываем на входе в разговор. Иначе следующий
  //: собеседник отвечал бы про чужую деревню.
  dialog.villageOverride = null;
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
