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
import { actorItem, actorItemName, actorReclassItemRef } from "./actor.js";
// Опыт квестовых вещей идёт через общее ядро 0x413110 ЦЕЛИКОМ, как и
// награда разговора: четверть убийцы (VA 0x414150) сюда не относится.
import { grantExperience } from "./progress.js";
import { craftWhetstone, isWhetstone } from "./craft.js";
import { drinkWine, potionDrink } from "./effects.js";
import { playEffect } from "./sound.js";
import { openLocation } from "./worldmap.js";

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
  9: () => Boolean(openLocation(20)),    // Приволье
  10: () => Boolean(openLocation(13)),   // Темнолесье
  11: () => Boolean(openLocation(23)),   // Морской лагерь
  12: () => Boolean(openLocation(19)),   // Чёрный Бор
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
};

// Применить вещь. `name` — что применяют, `targetName` — на что (можно без
// неё). Возвращает, случилось ли что-нибудь.
export function useQuestItem(name, targetName = null) {
  const item = actorItem(name);
  const label = actorItemName(name);
  // Точильный камень — тот же путь «применить на вещь» (VA 0x436C48 ->
  // 0x432DE0). Цели движку называет интерфейс; пока перетаскивания вещи
  // НА вещь нет, по умолчанию точится предмет основной руки.
  if (isWhetstone(name)) {
    const target = targetName ?? hero.equipment?.hand;
    if (!target || !craftWhetstone(target, hero)) return false;
    const index = findInBag(item.index);
    if (index >= 0) { hero.bag.splice(index, 1); hero.bag.push(null); }
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
  if (potions && item && item.index >= (potions.first ?? 84)) {
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
  // тот же, что Чистая слеза. Предмет НЕ тратится (в ветке нет пометки
  // группой −1), гаснет флаг при входе на карту (0x43DF48).
  if (item.index === (potions?.glow_torch_class ?? 46)) {
    world.glow = true;
    playEffect(0x12);
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
  if (!action(target)) return false;
  // Вышло — вещь съедается (движок пишет в группу −1).
  const index = findInBag(item.index);
  if (index >= 0) { hero.bag.splice(index, 1); hero.bag.push(null); }
  world.onStatus?.(`«${label}» использована`);
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
  if (potions && item.index >= (potions.first ?? 84)) return true;
  const powders = powderRules();
  if (powders && (powders.skills?.[String(item.index)]
      || powders.characteristics?.[String(item.index)]
      || item.index === powders.experience?.class)) return true;
  return Boolean(item.kind === QUEST_GROUP && USES[item.index]);
}
