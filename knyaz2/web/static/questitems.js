// Применение квестовых вещей (VA 0x436C48).
//
// Предмет в мире — запись в шестнадцать байт (0x6F956C, шаг 0x10): байт +0
// это ГРУППА, байт +3 — КЛАСС. Разбор начинается с проверки группы: она
// должна быть 11, «квестовое». Дальше действие выбирает КЛАСС применяемой
// вещи, а вторая вещь (та, НА КОТОРУЮ применяют) может участвовать или нет.
// Съеденная вещь помечается группой −1.
//
// Зовётся это из трёх мест: обыска (VA 0x41F55C), щелчка по миру
// (VA 0x421690) и VA 0x422AFC.
//
//: ЗДЕСЬ ПЕРЕНЕСЕНЫ НЕ ВСЕ СЛУЧАИ. В движке их около двадцати, и часть —
//: переносы отряда на другие карты со своими условиями. Перенесено то, что
//: разобрано построчно и проверяемо; остальные помечены в docs.
import { world } from "./world.js";
import { hero } from "./hero.js";
import { actorItem, actorItemName, actorReclassItemRef,
         isBeast } from "./actor.js";
// Опыт квестовых вещей идёт через общее ядро 0x413110 ЦЕЛИКОМ, как и
// награда разговора: четверть убийцы (VA 0x414150) сюда не относится.
import { grantExperience } from "./progress.js";
import { craftWhetstone, isWhetstone } from "./craft.js";
import { drinkWine, potionDrink } from "./effects.js";
import { playEffect } from "./sound.js";
import { locationName, openLocation, worldMap } from "./worldmap.js";

//: Группа квестовых вещей — с неё начинается разбор.
export const QUEST_GROUP = 11;

//: Класс «съеден»: движок пишет в группу −1.
const EATEN = -1;

// Найти в мешке игрока вещь этого класса. Так же ищет и сам движок
// (VA 0x434F8C перебирает сорок две ячейки и сравнивает класс).
function findInBag(klass) {
  const bag = hero.bag ?? [];
  for (let index = 0; index < bag.length; index += 1) {
    const item = bag[index] ? actorItem(bag[index]) : null;
    if (item && item.index === klass) return index;
  }
  return -1;
}

function takeFromBag(klass) {
  const index = findInBag(klass);
  if (index < 0) return false;
  // Движок не оставляет дырок: запись освобождается, хвост сдвигается
  // (VA 0x433D38).
  hero.bag.splice(index, 1);
  hero.bag.push(null);
  return true;
}

function nameOfClass(klass) {
  const items = world.map?.items ?? {};
  for (const [name, item] of Object.entries(items)) {
    if (item.index === klass && item.kind === QUEST_GROUP) return name;
  }
  return null;
}

//: То же, но без оглядки на группу — банки зелий любого вида.
export function nameOfClassAny(klass) {
  const items = world.map?.items ?? {};
  for (const [name, item] of Object.entries(items)) {
    if (item.index === klass) return name;
  }
  return null;
}

// Заменить вещь в мешке другим классом: так работает соединение двух вещей
// (береста плюс уголёк дают грамоту).
function replaceInBag(fromClass, toClass) {
  const index = findInBag(fromClass);
  if (index < 0) return false;
  const classRef = nameOfClass(toClass);
  if (!classRef) return false;
  const previous = hero.bag[index];
  const next = actorReclassItemRef(previous, classRef);
  hero.bag[index] = next;
  for (const field of ["bagStrength", "bagCount", "bagEnchant", "bagPoison",
                       "wear", "wearMax", "itemOiled"]) {
    const values = hero[field];
    if (!values || !Object.prototype.hasOwnProperty.call(values, previous)) continue;
    values[next] = values[previous];
    delete values[previous];
  }
  return true;
}

// КАРТА ГОВОРИТ, ЧТО ОТКРЫЛА.
//
// Движок открывает место молча: игрок сам увидит новый значок, когда полезет
// на глобальную карту. У нас так же — и тестер записал «карта ничего не
// открыла при использовании», хотя замер показывает обратное: флаг клетки
// сменился со «скрыта» на «видно». Открылось место на другом конце карты, и
// узнать об этом было неоткуда.
//
// Строка НАША, как у зеркала («открыло тайников») и свистка («разогнал
// тварей»), — движок таких сообщений не даёт вовсе. Имя берём у того же
// единственного владельца, что и подпись карты мира.
function revealPlace(location) {
  const место = openLocation(location);
  if (!место) return false;
  //: Своими словами, а не общим «использована»: та строка идёт ПОСЛЕ действия
  //: и затирала частную. Здесь только запоминаем, что сказать, — говорит один
  //: владелец, в конце useQuestItem.
  сказать = `Карта открыла место: ${locationName(location)}`;
  return true;
}

//: Что сказать вместо общего «использована», если действию есть что добавить.
//: Живёт один вызов: ставится действием, читается и гасится сразу после него.
let сказать = null;

//: Что делает применённая вещь. Ключ — КЛАСС применяемой вещи, значение
//: разобрано построчно по VA 0x436C48. Каждый случай возвращает, вышло ли:
//: не вышло — вещь не тратится, как и в движке.
const USES = {
  // 0 «Береста»: применяется НА уголёк (класс 21). Даёт сто опыта, уголёк
  // превращается в класс 24, а сама береста съедается.
  //: Вторую вещь движку называет интерфейс — её туда перетаскивают. Пока
  //: перетаскивания вещи НА вещь у нас нет, напарник ищется в мешке: это
  //: то же самое действие, только без лишнего шага.
  0: (target) => {
    if (target && target.index !== 21) return false;
    if (!target && findInBag(21) < 0) return false;
    grantExperience(hero, 100);
    replaceInBag(21, 24);
    return true;
  },
  // 21 «Уголёк»: то же самое с другой стороны — применяется на бересту.
  21: (target) => {
    if (target && target.index !== 0) return false;
    if (!target && findInBag(0) < 0) return false;
    grantExperience(hero, 100);
    replaceInBag(0, 24);
    return true;
  },
  // 9, 10, 11, 12: вещи-карты, открывающие локацию на глобальной карте
  // (VA 0x436908). Номера локаций взяты прямо из разбора.
  9: () => revealPlace(20),    // Приволье
  10: () => revealPlace(13),   // Темнолесье
  11: () => revealPlace(23),   // Морской лагерь
  12: () => revealPlace(19),   // Чёрный Бор
  // 22 «Почтовый ястреб»: нужна вещь класса 24; она забирается, даётся
  // полсотни опыта и открывается локация 6.
  22: () => {
    if (findInBag(24) < 0) {
      world.onStatus?.("Не с чем отправить весть");
      return false;
    }
    takeFromBag(24);
    grantExperience(hero, 50);
    openLocation(6);
    return true;
  },
  // 1 «Берестяная грамота»: взводит ТОКЕН КВЕСТА 0 — движок ставит бит
  // 0x80 первой записи блока 0x6A50E8 (случай '\x01'). Ходим через мир:
  // прямой импорт dialog.js дал бы кольцо (он сам берёт nameOfClassAny).
  1: () => {
    if (!world.questTokenSet) return false;
    world.questTokenSet(0);
    return true;
  },
  // 15 «Магическая сфера Летающего острова» (случай '\x0f'): перенос
  // отряда записью заявки (0x8496D8 = −карта), как у дверей. С карт
  // Летающего острова (номер < 4) — на карту 6 в клетку (120, 18),
  // взгляд 2, и сфера ОСТАЁТСЯ; с прочих — на карту 3 (застава) в
  // (48, 30), взгляд 1, сфера съедается. Поля входа записи игрока:
  // +0x0C строка, +0x14 столбец — интерпретация сверена проходимостью
  // целевых клеток пака: (48,30) карты 3 свободна, (30,48) — глушь.
  15: () => {
    if (!world.onTransition) return false;
    const карта = Number(world.map?.legacy?.map_number ?? -1);
    if (карта < 4) {
      world.onTransition({ to_map: 6, entry_row: 120, entry_col: 18, facing: 2 });
      return "keep";
    }
    world.onTransition({ to_map: 3, entry_row: 48, entry_col: 30, facing: 1 });
    return true;
  },
  // 25 «Связка ключей» (случай '\x19'): переносы ПО МЕСТУ. В Подземной
  // тюрьме (карта 48, стоя в строках 21…24 столбцах 22…23) — перенос
  // внутри той же карты в (12, 22), взгляд 3; во Дворце Повелителя
  // (карта 1, строки 7…11 столбцы 30…32) — на карту 3 в (6, 26),
  // взгляд 5. В остальных местах ветка молчит и ключи не тратятся.
  25: () => {
    if (!world.onTransition) return false;
    const карта = Number(world.map?.legacy?.map_number ?? -1);
    const клетка = hero.cell ?? {};
    const внутри = (r1, r2, c1, c2) =>
      клетка.row >= r1 && клетка.row <= r2 && клетка.col >= c1 && клетка.col <= c2;
    if (карта === 48 && внутри(21, 24, 22, 23)) {
      world.onTransition({ to_map: 48, entry_row: 12, entry_col: 22, facing: 3 });
      return true;
    }
    if (карта === 1 && внутри(7, 11, 30, 32)) {
      world.onTransition({ to_map: 3, entry_row: 6, entry_col: 26, facing: 5 });
      return true;
    }
    // ДОНОРСКОЕ МЕСТО (его 0x43B8C4:81): его карта 27 (наша 177), ровно
    // клетка (58,17) -> внутрикарточный перенос в (44,17), взгляд 2.
    if (карта === 177 && внутри(58, 58, 17, 17)) {
      world.onTransition({ to_map: 177, entry_row: 44, entry_col: 17, facing: 2 });
      return true;
    }
    return false;
  },
  // 39 «Свиток ведуна» (случай '\'' -> 0x41B7C0): опознаёт ВСЁ у юнита —
  // пять слотов снаряжения, боеприпас, сорок две ячейки мешка и пять
  // украшений; за КАЖДУЮ опознанную вещь «Идентификация предметов» +1,
  // кап 100. У нас слова чар живут двумя картами: по имени в мешке
  // (bagEnchant) и по гнезду у надетого (enchant) — обходим обе.
  //
  // РАНЬШЕ этот код висел на классе 37 — ошибка чтения switch: 0x27=39,
  // а 0x25=37. Живой «замер опознания паутиной» был самосбывшимся.
  39: () => {
    const dormant = 0x8000;
    let opened = 0;
    for (const store of [hero.bagEnchant, hero.enchant]) {
      if (!store) continue;
      for (const [key, word] of Object.entries(store)) {
        if (!(word & dormant)) continue;
        store[key] = word & ~dormant;
        opened += 1;
      }
    }
    if (opened) raiseSkill("Идентификация предметов", opened);
    сказать = opened ? `Опознано вещей: ${opened}` : "Опознавать нечего";
    return true;
  },
  // 37 «Паутина странного паука» (случай '%'): ЗАМЕДЛЯЕТ всех чужих
  // бойцов-людей карты — байт скорости юнита (+0x1D) = 0xFE, то есть
  // −2: клетка шага дорожает на два такта. Пересчёт скорости
  // (0x41C944 -> 0x41B3B8) отрицательное значение у ЧУЖИХ нарочно
  // залипает — паутина держится, пока юнит жив. У нас то же правило:
  // скорость по формуле пересчитывается только отряду игрока.
  37: () => {
    let ensnared = 0;
    for (const unit of world.units ?? []) {
      if (unit.alive === false || unit.side === hero.side || isBeast(unit)) continue;
      unit.speed = -2;
      ensnared += 1;
    }
    сказать = `Паутина оплела бойцов: ${ensnared}`;
    return true;
  },
  // 34 «Кукла»: всем бойцам ЧУЖИХ отрядов карты — людям (звери мимо), у
  // кого в мешке нет «Заячьего хвоста» (класс 33), — ставится квестовый
  // бит юнита +0xF9 |= 2 (случай '\"', проверка вещи — FUN_00432C30).
  // Юниты — через мир (world.units кладёт app.js): прямой импорт units.js
  // тянул бы кольцо через carry.js.
  34: () => {
    let cursed = 0;
    for (const unit of world.units ?? []) {
      if (unit.alive === false || unit.side === hero.side || isBeast(unit)) continue;
      const guarded = (unit.bag ?? []).some((held) =>
        held && actorItem(held)?.index === 33);
      if (guarded) continue;
      unit.flags = (unit.flags ?? 0) | 2;
      cursed += 1;
    }
    сказать = `Кукла подействовала: ${cursed}`;
    return true;
  },
  // 41 «Святые мощи»: квестовый бит игрока +0xF9 |= 1 (случай ')').
  // ДОНОРСКАЯ ЭВОЛЮЦИЯ (его 0x43B8C4:283): если на герое ПРОКЛЯТИЕ
  // (бит 2 — Кукла), мощи сначала СНИМАЮТ его; благословение — только
  // следующим применением. В канонном движке ветки снятия нет.
  41: () => {
    if (hero.game === "legend" && ((hero.flags ?? 0) & 2)) {
      hero.flags = (hero.flags ?? 0) ^ 2;
      сказать = "Мощи сняли проклятие";
      return true;
    }
    hero.flags = (hero.flags ?? 0) | 1;
    return true;
  },
  // 23 «Финики» — донорская еда (его 0x43B8C4:55, у канона ветки нет):
  // Интеллект +2 НАВСЕГДА (оба ряда, кап 150 — его 0x43A498) и
  // здоровье +160 с потолком 1600.
  23: () => {
    if (hero.game !== "legend") return false;
    raiseCharacteristic(2, 2);
    hero.health = Math.min(1600, (hero.health ?? 0) + 160);
    сказать = "Финики подкрепили силы";
    return true;
  },
  // 4 «Грамота на владение кораблём» — донорское применение (его case 4
  // -> 0x435E00): выписывает корабельное право текущей карте (0x87F4B8 =
  // карта, наш worldMap.ship) — зона выхода −2 оживает. Грамота НЕ
  // тратится; гейта «один раз» в 0x435E00 нет: повторное применение
  // просто выписывает право заново — в том числе ПОСЛЕ рейса, когда
  // прошлый шаг на трап его погасил.
  4: () => {
    if (hero.game !== "legend") return false;
    const карта = Number(world.map?.legacy?.map_number ?? -1);
    const корабельных = (world.map?.exits ?? [])
      .filter((exit) => exit.to_map === -2).length;
    if (!корабельных) return false;
    worldMap.ship = карта;
    сказать = "Корабль готов к отплытию";
    return "keep";
  },
  // 223 «Волшебный точильный камень» (его 24, случай 0x18): чинит
  // оружие руки КАК МАСТЕР — движок временно подставляет «Кузнечное
  // дело» = 100, зовёт починку и возвращает навык; камень ВЕЧНЫЙ.
  223: () => {
    const цель = hero.equipment?.hand;
    if (!цель) return false;
    const имена = world.map?.hero?.rules?.progression?.skills?.names ?? [];
    const кузнец = имена.indexOf("Кузнечное дело");
    if (кузнец < 0) return false;
    hero.skills = hero.skills ?? [];
    const было = hero.skills[кузнец] ?? 0;
    hero.skills[кузнец] = 100;
    const вышло = craftWhetstone(цель, hero);
    hero.skills[кузнец] = было;
    if (!вышло) return false;
    сказать = "Волшебный камень наточил оружие";
    return "keep";
  },
  // Учебники и разовые дары (случаи '(', ',', '-', '0', '2', '*', '/',
  // '1' — Свиток кузнеца, Трактат, Гиппократ, Чертежи, Ягода, Лапка,
  // Чаша, Яблоко) в USES НЕ живут: их ведёт usePowder по правилам пака
  // (rules.craft.powders — тот же 0x436C48, с родными сообщениями движка),
  // и он стоит в useQuestItem РАНЬШЕ этой таблицы.
};

//: Навык по имени из правил прокачки; движок капит сотней (0x64).
function skillIndex(name) {
  const names = world.map?.hero?.rules?.progression?.skills?.names ?? [];
  return names.indexOf(name);
}

function raiseSkill(name, amount) {
  const index = skillIndex(name);
  if (index < 0) return false;
  hero.skills = hero.skills ?? [];
  hero.skills[index] = Math.max(0, Math.min(100,
    (hero.skills[index] ?? 0) + amount));
  return true;
}

//: Характеристика НАВСЕГДА — все ряды (рабочий, база, снимок отката),
//: кап 0…150, как FUN_00436BA8 и его донорский двойник 0x43A498.
function raiseCharacteristic(field, amount) {
  for (const list of [hero.characteristics, hero.baseCharacteristics,
                      hero.savedCharacteristics]) {
    if (!list) continue;
    list[field] = Math.max(0, Math.min(150, (list[field] ?? 0) + amount));
  }
  return true;
}

// Применить вещь. `name` — что применяют, `targetName` — на что (можно без
// неё). Возвращает, случилось ли что-нибудь.
export function useQuestItem(name, targetName = null) {
  const item = actorItem(name);
  const label = actorItemName(name);
  // Точильный камень — тот же путь «применить на вещь» (VA 0x436C48 ->
  // 0x432DE0). Цели движку называет интерфейс; пока перетаскивания вещи
  // НА вещь нет, по умолчанию точится предмет основной руки.
  // В КАНОНЕ камень вечный; у ДОНОРА (его 0x43B8C4:360) он ЛОМАЕТСЯ по
  // жребию «Кузнечное дело < rand % 105» — мастера точат дольше.
  if (isWhetstone(name)) {
    const target = targetName ?? hero.equipment?.hand;
    if (!target || !craftWhetstone(target, hero)) return false;
    if (hero.game === "legend") {
      const кузнец = hero.skills?.[skillIndex("Кузнечное дело")] ?? 0;
      if (кузнец < Math.floor(Math.random() * 105)) {
        takeFromBag(item.index);
        world.onStatus?.(`«${actorItemName(target)}» наточено — камень истёрся`);
        return true;
      }
    }
    world.onStatus?.(`«${actorItemName(target)}» наточено`);
    return true;
  }
  // Порошки (ветки применения VA 0x436C48): навыковые растят свой навык до
  // ста, характеристические (FUN_00436BA8) навсегда поднимают базу с
  // клампом 0…150, а класс 0x31 даёт опыт «Волхование × 3» через общее
  // начисление 0x413110. Вещь съедается.
  if (item && usePowder(item)) {
    const index = findInBag(item.index);
    if (index >= 0) { hero.bag.splice(index, 1); hero.bag.push(null); }
    playEffect(0x12);
    return true;
  }
  // Зелья пьются тем же жестом: те же три входа движка зовут 0x41D954.
  // Банка меняет класс (пустая — 83, у временных сразу) либо остаётся с
  // меньшей крепостью; крепость экземпляра живёт по имени банки. Классы
  // без действия (масло и прочие) не тратятся. Удачу движок озвучивает
  // слотом 0x11 (хвост 0x41D954).
  const potions = world.map?.hero?.rules?.effects?.potions;
  // Гейт — по ВИДУ записи (зелья — вид 9), как пьёт движок. Прежняя
  // проверка «класс >= 84» съедала ДОНОРСКИЙ ХВОСТ каталога (211+):
  // Волшебный точильный камень и прочие уходили в potionDrink и молча
  // умирали в его default-ветке.
  if (potions && item && item.kind === (potions.kind ?? 9) &&
      item.index >= (potions.first ?? 84)) {
    const state = { strength: hero.bagStrength?.[name] };
    const sipped = typeof state.strength === "number";
    const became = potionDrink(item, hero, state);
    const acted = became !== null ||
      (typeof state.strength === "number" && !sipped) ||
      (sipped && state.strength !== hero.bagStrength?.[name]);
    if (!acted) return false;
    hero.bagStrength = hero.bagStrength ?? {};
    if (typeof state.strength === "number") {
      hero.bagStrength[name] = state.strength;
    }
    if (became !== null) {
      const bottle = nameOfClassAny(became);
      const index = findInBag(item.index);
      if (index >= 0) {
        const next = actorReclassItemRef(name, bottle);
        hero.bag[index] = next;
        for (const field of ["bagEnchant", "bagPoison", "wear", "wearMax",
                             "itemOiled"]) {
          const values = hero[field];
          if (!values || !Object.prototype.hasOwnProperty.call(values, name)) continue;
          values[next] = values[name];
          delete values[name];
        }
      }
      delete hero.bagStrength[name];
    }
    playEffect(0x11);
    world.onStatus?.(became !== null ? `«${label}» выпито` : `«${label}» отпито`);
    return true;
  }
  if (!item || item.kind !== QUEST_GROUP) return false;
  // ФАКЕЛ (класс 46, ветка 0x2E): зажигает общий флаг свечения 0x849610 —
  // тот же, что Чистая слеза. В КАНОНЕ предмет не тратится вовсе; у
  // ДОНОРА (его 0x43B8C4:320) факел СГОРАЕТ по жребию — «Волхование <
  // rand % 105» — то есть выживает тем чаще, чем выше навык.
  if (item.index === (potions?.glow_torch_class ?? 46)) {
    world.glow = true;
    playEffect(0x12);
    if (hero.game === "legend") {
      const волхование = hero.skills?.[skillIndex("Волхование")] ?? 0;
      if (волхование < Math.floor(Math.random() * 105)) {
        takeFromBag(item.index);
        world.onStatus?.(`«${label}» догорел`);
        return true;
      }
    }
    world.onStatus?.(`«${label}» зажжён`);
    return true;
  }
  // ВИНО (класс 30, ветка 0x1E): Брага без крепости — сила из Ловкости,
  // но не больше пяти. Вещь съедается.
  if (item.index === (potions?.wine?.class ?? 30)) {
    if (!drinkWine(hero)) return false;
    const wineAt = findInBag(item.index);
    if (wineAt >= 0) { hero.bag.splice(wineAt, 1); hero.bag.push(null); }
    playEffect(0x11);
    world.onStatus?.(`«${label}» выпито`);
    return true;
  }
  const action = USES[item.index];
  if (!action) {
    // Не разобранный случай: вещь не тратим и говорим честно.
    world.onStatus?.(`«${label}» пока применить не к чему`);
    return false;
  }
  const target = targetName ? actorItem(targetName) : null;
  сказать = null;
  const result = action(target);
  if (!result) { сказать = null; return false; }
  // Вышло — вещь съедается (движок пишет в группу −1). «keep» — ветка
  // прошла БЕЗ съедания: у сферы с Летающего острова пометки −1 нет.
  if (result !== "keep") {
    const index = findInBag(item.index);
    if (index >= 0) { hero.bag.splice(index, 1); hero.bag.push(null); }
  }
  world.onStatus?.(сказать ?? `«${label}» использована`);
  сказать = null;
  return EATEN === -1;
}

//: Правила порошков — из пака (craft.powders, VA 0x436C48).
function powderRules() { return world.map?.hero?.rules?.craft?.powders ?? null; }

// Применить порошок к самому герою. Возвращает, подошёл ли класс.
function usePowder(item) {
  const set = powderRules();
  if (!set) return false;
  const names = world.map?.hero?.rules?.progression ?? {};
  const skillRow = set.skills?.[String(item.index)];
  if (skillRow) {
    const skills = hero.skills ?? [];
    skills[skillRow.skill] = Math.min(100,
      (skills[skillRow.skill] ?? 0) + (skillRow.gain ?? 0));
    if (skillRow.message) world.onStatus?.(skillRow.message);
    return true;
  }
  const charRow = set.characteristics?.[String(item.index)];
  if (charRow) {
    // подъём НАВСЕГДА: и базы, и текущей (движок правит ещё и спрятанную
    // копию +0xC6, чтобы возврат временного зелья не съел прибавку)
    const cap = names.characteristics?.cap ?? 150;
    const at = charRow.characteristic ?? 0;
    const lift = (list) => {
      if (!list) return;
      list[at] = Math.max(0, Math.min(cap, (list[at] ?? 0) + (charRow.gain ?? 0)));
    };
    lift(hero.baseCharacteristics);
    lift(hero.characteristics);
    lift(hero.savedCharacteristics);
    return true;
  }
  if (item.index === (set.experience?.class ?? 0x31)) {
    const sorcery = hero.skills?.[set.experience?.skill ?? 16] ?? 0;
    grantExperience(hero, sorcery * (set.experience?.scale ?? 3));
    return true;
  }
  return false;
}

// Есть ли у этой вещи разобранное применение — по этому интерфейс решает,
// показывать ли её как применимую.
export function questItemUsable(name) {
  const item = actorItem(name);
  if (!item) return false;
  if (isWhetstone(name)) return true;
  const potions = world.map?.hero?.rules?.effects?.potions;
  if (potions && item.kind === (potions.kind ?? 9) &&
      item.index >= (potions.first ?? 84)) return true;
  const powders = powderRules();
  if (powders && (powders.skills?.[String(item.index)]
      || powders.characteristics?.[String(item.index)]
      || item.index === powders.experience?.class)) return true;
  return Boolean(item.kind === QUEST_GROUP && USES[item.index]);
}
