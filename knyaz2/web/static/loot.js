// Кучи на земле.
//
// В движке куча — это не предмет, а ЗАПИСЬ НА КЛЕТКУ: таблица 0x7AD7E4, до
// двухсот записей по 101 байту (VA 0x423360):
//
//     +0x05 строка, +0x06 столбец, +0x08 карта
//     +0x0B спрайт, +0x0F деньги, +0x11 сорок два слова предметов
//
// Кладут вещь так: если у клетки уже стоит бит 0x20, вещь падает в её кучу,
// иначе заводится новая. Спрайт выбирает VA 0x43BBC4 — одна вещь без денег
// показывает свою картинку (поле класса +0x18: 153 колчан, 154 топор, 155
// лук, 158 и 159 доспехи, 161 шлем, 165 щит, 166 меч, 214 дубина), а две и
// больше или деньги — мешочек 163.
//
// Подойдя к куче, движок сам ОПОЗНАЁТ её вещи броском против навыка
// «Идентификация предметов», забирает деньги и открывает обмен
// (VA 0x4115AC и 0x424128).
import { world } from "./world.js";
import { context, drawBrightImage, layeredFrame } from "./viewport.js";
import { actorItem } from "./actor.js";
import { hero, heroCellAt } from "./hero.js";
import { mapStateLoot } from "./mapstate.js";
import { clock } from "./clock.js";

export const loot = [];

// ГРЯДКИ ОТРАСТАЮТ (VA 0x4136A8 и 0x43DF48:315-317). Сорванная трава —
// куча, чья единственная вещь имеет вид 9 и класс 'Q' (0x51, Земляной
// орех) или 'R' (0x52, Белый корень): при опустошении движок НЕ
// освобождает архивную запись, а пишет в неё метку времени сбора
// `−1 − floor(такт/360)` и заводит копию травы заново; загрузчик
// возвращает кучу, когда `метка·360 + такт > 0x1517` (5399). Проверка
// ЛЕНИВАЯ, только на входе — в такте роста нет.
//
// Из-за деления НА ЗАПИСИ порог плавает: срок выходит
// `5759 − (тактСбора mod 360)`, то есть 5400…5759 тактов (~15 суток) —
// раньше здесь стояло ровное 5760, и трава всходила на десятки тактов
// позже движка. Повторяем деление дословно.
const REGROW_CLASSES = new Set([0x51, 0x52]);
const REGROW_AFTER = 0x1517;
const REGROW_STEP = 360;

//: Метка сбора движка и его же проверка «отросла».
function regrowStamp(ticks) {
  return -1 - Math.floor(ticks / REGROW_STEP);
}

function regrown(stamp, ticks) {
  return stamp * REGROW_STEP + ticks > REGROW_AFTER;
}

function regrows(name) {
  const item = actorItem(name);
  return Boolean(item) && REGROW_CLASSES.has(item.index ?? 0);
}

//: Куча живёт В КЛЕТКЕ, и движок ищет её только по клетке: бит 0x20
//: слова клетки плюс совпадение строки и столбца (VA 0x423360), а подбор
//: случается, когда юнит ДОШЁЛ до этой клетки (VA 0x4115AC сравнивает
//: клетку юнита с целевой). Пиксельных радиусов в движке нет вовсе.
//: В куче столько же мест, сколько в мешке.
export const PILE_SLOTS = 42;
export const PILE_LIMIT = 200;

export function lootSetup(map) {
  loot.length = 0;
  // УЖЕ БЫЛИ ЗДЕСЬ — берём кучи из памяти карты, а не из пака. В памяти
  // лежит весь список живой карты: и приехавшее из пака, и брошенное
  // игроком, и высыпавшееся из убитых при уходе (VA 0x43A628). Пак знает
  // только исходную расстановку и вернул бы уже подобранное.
  const remembered = mapStateLoot(map.legacy?.map_number);
  if (remembered) {
    for (const pile of remembered) {
      const live = {
        ...pile,
        items: [...(pile.items ?? [])],
        details: (pile.details ?? []).map((detail) => ({ ...(detail ?? {}) })),
        enchant: [...(pile.enchant ?? [])],
        cell: pile.cell ? { ...pile.cell } : null,
        taken: false,
      };
      // ГРЯДКА ОТРОСЛА: пустая, с перевалившей порог меткой сбора и без
      // доложенного игроком (движок не отращивает кучу с занятой второй
      // ячейкой) — трава заводится заново (0x43DF48:315-317). Старые
      // сейвы несут `regrowAt` тактом сбора — метка выводится из него.
      if (live.regrowItem && !live.items.length &&
          regrown(live.regrowStamp ?? regrowStamp(live.regrowAt ?? 0),
                  clock.ticks)) {
        live.items = [live.regrowItem];
        live.details = [{}];
        live.enchant = [0];
        delete live.regrowItem;
        delete live.regrowAt;
        delete live.regrowStamp;
      }
      loot.push(live);
    }
    lootReattachTalk(map);
    return loot;
  }
  // КУЧИ ВЫБРАННОГО МИРА. Клетки у куч общие для всех шести миров, а
  // содержимое своё: на карте 19 у Ратибора лежит Медное зеркало колдуна и
  // 1500 монет, у Велиславны на том же месте Эликсир Мудрости и 700. Пока
  // читался общий список (мир 0), в родном Чёрном Бору Велиславне попадался
  // чужой лут — тот же корень, что был у двойника героя и его жителей.
  const worldId = String(map.hero?.template?.world ?? 0);
  const piles = map.loot_by_world?.[worldId] ?? map.loot ?? [];
  for (const entry of piles) {
    // РАЗГОВОРНАЯ КУЧА «Продолжения легенды»: байт +0x07 записи GAME.N —
    // номер диалога, и приказ «обыскать» на её клетке открывает разговор
    // БЕЗ СОБЕСЕДНИКА, а не обмен (донорский 0x411BC6: байт < 0xFE ->
    // диалог 0x100 + байт). Так сделаны семь чанов с маслом в Ущелье
    // возле Угорья. Вещей в ней нет, рисовать нечего — спрайт нулевой.
    if (entry.dialog_tree) {
      loot.push({
        id: entry.id, items: [], details: [], enchant: [], money: 0,
        x: entry.position.x, y: entry.position.y,
        cell: entry.cell ? { ...entry.cell } : null,
        dialog: entry.dialog_tree, taken: false,
      });
      continue;
    }
    // Куча без позиции (старый пак с draft-кучей) не должна ронять
    // весь вход на карту — позиция восстановима из шаговой клетки.
    // Y куч — в полустроках (канон данных: pos.y = row*16+16).
    const at = entry.position ?? (entry.cell ? {
      x: entry.cell.col * 58 + (entry.cell.row % 2 ? 29 : 58),
      y: entry.cell.row * 16 + 16,
    } : null);
    if (!at) continue;
    const pile = lootPut(entry.item, at.x, at.y,
                         entry.cell, entry.id);
    if (!pile) continue;
    // куча из пака может нести НЕСКОЛЬКО вещей и их экземплярные поля
    // (В10): крепость/износ, слово чар, отрава — параллельно items
    if (Array.isArray(entry.items) && entry.items.length > 1) {
      pile.items = [...entry.items];
    }
    const details = (entry.details ?? []).slice(0, pile.items.length);
    while (details.length < pile.items.length) details.push({});
    pile.details = details;
    pile.enchant = details.map((detail) => detail?.enchant ?? 0);
    if (entry.money) pile.money = entry.money;
    //: Признак «спрятана» приезжает из пака — знак поля +0x0F записи.
    if (entry.buried) pile.buried = true;
    // КУЧА В ГНЕЗДЕ ОБСТАНОВКИ — сундук или бочка. Пара байтов записи
    // (`+0x09` зона и `+0x0A` гнездо) говорит, где она лежит; по ней
    // `furnitureBind` и связывает её с гнездом, как это делает загрузчик
    // карты (VA 0x43DF48:344-352). Без переноса пары сундук приезжал бы
    // обычной кучей на полу — невидимой и недостижимой.
    if (entry.zone != null) {
      pile.zone = entry.zone;
      pile.nest = entry.nest;
    }
  }
  return loot;
}

//: РАЗГОВОРНОЕ ДЕРЕВО — ДАННЫЕ, А НЕ СОСТОЯНИЕ. В память карты и сейв оно
//: не пишется (packPile — белый список), и старые сейвы его не знают
//: вовсе, поэтому после ЛЮБОГО восстановления куч — из памяти карты или
//: из сохранения — дерево возвращается из пака по id кучи. Хранить его в
//: сейве нельзя ещё и потому, что правка данных пака не доехала бы до
//: старых сохранений — тот же уговор, что у «подойди и заговори»
//: (dialog.approachEdits).
export function lootReattachTalk(map) {
  const packWorld = String(map?.hero?.template?.world ?? 0);
  const packed = map?.loot_by_world?.[packWorld] ?? map?.loot ?? [];
  let touched = 0;
  for (const entry of packed) {
    if (!entry.dialog_tree) continue;
    const live = loot.find((pile) => pile.id === entry.id);
    if (live) {
      live.dialog = entry.dialog_tree;
      delete live.speaker;
    } else {
      loot.push({
        id: entry.id, items: [], details: [], enchant: [], money: 0,
        x: entry.position.x, y: entry.position.y,
        cell: entry.cell ? { ...entry.cell } : null,
        dialog: entry.dialog_tree, taken: false,
      });
    }
    touched += 1;
  }
  return touched;
}

//: Собеседник разговорной кучи — то, что уедет в dialogStart. Дерево уже
//: лежит в куче; остальное — подписи. Объект кешируется на куче, чтобы
//: `world.talking.unit` был одним и тем же всю длину разговора.
export function lootSpeaker(pile) {
  if (!pile?.dialog) return null;
  pile.speaker ??= {
    id: pile.id,
    // имени у чана нет — окно разговора покажет пустую строку, как движок
    name: null,
    cell: pile.cell,
    dialog: pile.dialog,
    dialogNumber: pile.dialog.number,
  };
  return pile.speaker;
}

// Куча на этой точке — решает клетка, а не расстояние.
function pileHere(x, y, cell) {
  for (const pile of loot) {
    if (pile.taken) continue;
    if (cell && pile.cell && pile.cell.row === cell.row && pile.cell.col === cell.col) {
      return pile;
    }
    if (!cell && pile.cell) {
      // клетки не дали — считаем её сами, той же формулой, что и движок
      const at = heroCellAt(x, y);
      if (pile.cell.row === at.row && pile.cell.col === at.col) return pile;
    }
  }
  return null;
}

// Положить вещь на землю: в кучу этой клетки, а нет её — завести новую.
export function lootPut(name, x, y, cell = null, id = null, detail = null) {
  const state = detail ? { ...detail } : {};
  const pile = pileHere(x, y, cell);
  if (pile) {
    if (pile.items.length >= PILE_SLOTS) return null;
    pile.items.push(name);
    pile.details?.push(state);
    pile.enchant?.push(state.enchant ?? 0);
    return pile;
  }
  // Таблица движка фиксирована: 200 записей по 101 байту (0x7AD7E4).
  // Освобождённая запись может использоваться снова, живая 201-я — нет.
  if (loot.filter((entry) => !entry.taken).length >= PILE_LIMIT) return null;
  const fresh = {
    id: id ?? `pile_${loot.length}`,
    items: [name], money: 0,
    details: [state], enchant: [state.enchant ?? 0],
    x, y, cell: cell ? { ...cell } : null, taken: false,
  };
  loot.push(fresh);
  return fresh;
}

// Картинка кучи: одна вещь и без денег — её собственный вид, иначе мешочек
// (VA 0x43BBC4).
function groundSprite(pile) {
  const single = pile.items.length === 1 && !pile.money
    ? actorItem(pile.items[0])?.ground : null;
  return single ?? world.map?.interface?.ground_pile ?? null;
}

export function lootAssets() {
  const paths = [];
  const pouch = world.map?.interface?.ground_pile;
  if (pouch) paths.push(pouch.path);
  for (const pile of loot) {
    for (const name of pile.items) {
      const ground = actorItem(name)?.ground;
      if (ground) paths.push(ground.path);
    }
  }
  return paths;
}

// Куча под точкой — строго по КЛЕТКЕ, как её ищет движок (VA 0x423360).
// Ни радиуса, ни эллипса: попал в клетку кучи — нашёл, не попал — нет.
// СПРЯТАННАЯ КУЧА НЕ ВИДНА И НЕ БЕРЁТСЯ. Знак поля +0x0F записи (GAME.N,
// таблица 0x2C800) значит «лежит под землёй»: обыск такой кучи по клетке
// движок запрещает, пока в мешке нет Лопаты (VA 0x4115AC, проверка
// FUN_00434F8C(0x20)). На игру их девяносто пять на тридцати двух картах —
// раньше знак терялся в сборщике, и все тайники лежали у нас на виду.
//
// `dug` — уже откопанная: обыск обнуляет поле вместе со знаком.
export function lootHidden(pile) {
  return Boolean(pile?.buried) && !pile.dug;
}

// КУЧА В ГНЕЗДЕ ОБСТАНОВКИ НА ПОЛУ НЕ ЛЕЖИТ. Её не рисуют и по клетке не
// ищут — до неё добираются, щёлкнув по самому сундуку (furniture.js).
//
// В движке это выходит само собой: загрузчик карты считает экранную точку и
// ставит клетке бит 0x2000 «здесь куча» ТОЛЬКО напольной (VA 0x43DF48:328,
// ветка `+0x09 == 0xFF`), а куче в гнезде не даёт ни того ни другого. Дальше
// обе дороги идут через этот бит: отрисовка перебирает клетки и рисует те, у
// которых он стоит (VA 0x424514:137), а поиск по клетке `FUN_004149F8` сам
// сверяет `+0x09 == 0xFF` и непольную не вернёт никогда.
//
// У нас клетки такого бита не несут, поэтому проверка идёт по самой записи —
// но смысл тот же, и место одно на всех троих потребителей.
export function lootInNest(pile) {
  return pile?.zone != null;
}

export function lootNear(x, y, { hidden = false } = {}) {
  const at = heroCellAt(x, y);
  for (const pile of loot) {
    if (pile.taken || !pile.cell) continue;
    // Разговорная куча вещей не несёт, но щелчок обязан её видеть: приказ
    // «обыскать» на её клетке и открывает диалог (донорский 0x411BC6).
    if (!pile.items.length && !pile.dialog) continue;
    if (lootInNest(pile)) continue;              // сундук ищут не по клетке
    if (!hidden && lootHidden(pile)) continue;
    if (pile.cell.row === at.row && pile.cell.col === at.col) return pile;
  }
  return null;
}

// Раскрыть спрятанные кучи ЭТОЙ карты — Медное зеркало колдуна
// (FUN_00436C48, класс 35: у всех записей карты знак поля переворачивается,
// и куча просто оказывается на виду). Возвращает, сколько раскрыто.
export function lootReveal() {
  let count = 0;
  for (const pile of loot) {
    if (!lootHidden(pile)) continue;
    pile.dug = true;
    count += 1;
  }
  return count;
}

//: Развязка без петли: carry.js зовёт раскрытие через `world`.
world.lootReveal = lootReveal;

// Выброшенный предмет ложится на землю там же, где стоит персонаж.
export function lootDrop(name, x, y, cell = null, detail = null) {
  return lootPut(name, x, y, cell, null, detail);
}

// РАЗВЯЗКА «КУЧА ОПУСТЕЛА» — ОДНА НА ВСЕ ДОРОГИ (0x41F638 → 0x4136A8).
//
// Гнездовая (сундук, бочка) не умирает никогда: всё тело удаления движка
// стоит под `+0x09 == 0xFF` — «стоит на земле»; в пустой контейнер можно
// класть своё. Грядкой становится куча, державшая РОВНО ОДНУ вещь класса
// 'Q'/'R': 0x4136A8:19-23 читает ПЕРВОЕ слово предметов архивной записи и
// требует пустого ВТОРОГО (+0x13). Решает содержимое, а не происхождение
// кучи — поэтому и посаженный игроком орех (брошенный на землю, 0x423360)
// плодоносит потом так же, как пачная грядка. Прочая напольная уходит.
//
// `held` — чем куча владела перед опустошением: живые слоты к этому мигу
// уже пусты, ровно как у движка, который читает архив, а не живую запись.
// Уже помеченная грядка остаётся грядкой, что бы из неё ни забрали.
export function lootEmptied(pile, held = null) {
  if (!pile || pile.taken || pile.items.length || pile.money) return false;
  if (pile.zone != null || pile.nest != null) return false;
  const seed = held?.length === 1 && regrows(held[0]) ? held[0] : null;
  if (seed || pile.regrowItem) {
    pile.regrowItem = pile.regrowItem ?? seed;
    // метка — движковая, с делением на записи (0x4136A8); такт сбора
    // остаётся рядом для старых сейвов и отладки
    pile.regrowStamp = regrowStamp(clock.ticks);
    pile.regrowAt = clock.ticks;
  } else {
    pile.taken = true;
  }
  return true;
}

// Взять из кучи. Без номера берётся верхняя вещь; судьбу опустевшей решает
// общая развязка lootEmptied — раньше окно обмена шло своей дорогой и
// ставило `taken` всем подряд, хороня и сундуки, и грядки.
export function lootTake(pile, index = 0) {
  if (!pile || pile.taken || !pile.items.length) return null;
  const held = [...pile.items];
  const [name] = pile.items.splice(index, 1);
  pile.details?.splice(index, 1);
  pile.enchant?.splice(index, 1);
  if (!pile.items.length) lootEmptied(pile, held);
  return name ?? null;
}

// Куча рисуется своим спрайтом по центру клетки — ровно как в движке.
//
// СВЕЧЕНИЕ ФАКЕЛА ПОДСВЕЧИВАЕТ ИМЕННО КУЧИ. Пока горит флаг 0x849610
// (Факел или Чистая слеза), ОБА прохода отрисовки куч — напольный
// (VA 0x424514:146) и на помеченных клетках (VA 0x424FD8:220) — рисуют
// одно и то же: маску-осветление 64×43 (буфер 0x6A5598 из LIGHTS.RES)
// с центром на середине спрайта кучи, и сам спрайт БАЗОВОЙ палитрой
// (DAT_0058e300) — мимо суточного пересчёта 0x441393. То есть кучи в
// ночи горят пятнами света. Раньше дымка рисовалась вокруг круга
// выделения — это было неверное чтение тех же адресов, и «подсветить
// лут факелом» не работало вовсе (жалоба 23.08).
export function drawPile(pile) {
  const sprite = groundSprite(pile);
  if (!sprite) return false;
  const image = world.images.get(sprite.path);
  if (!image) {
    // Картинки ещё нет — заказать и пропустить кадр. Кучи возникают и на
    // ходу (брошенное игроком, высыпавшееся из мёртвых), их спрайтов может
    // не оказаться даже в предзагрузке входа; молчаливый выход без заказа
    // оставлял топор в Беглом невидимым до конца сеанса.
    world.requestAsset?.(sprite.path);
    return false;
  }
  const x = Math.round(pile.x - sprite.width / 2);
  const y = Math.round(pile.y - sprite.height / 2);
  if (world.glow) {
    const glow = world.map?.interface?.glow;
    const halo = glow && world.images.get(glow.path);
    if (halo) {
      // Пятно света: центр маски — на центре спрайта кучи (движок кладёт
      // левый верх в «верх спрайта + половина размера − (32, 21)», и ровно
      // эти −32/−21 испечены в glow.offset). Режим lighter — наш перенос
      // светового блита 0x43FBDC: он ДОБАВЛЯЕТ свет к уже нарисованному.
      context.save();
      context.globalCompositeOperation = "lighter";
      context.drawImage(halo, Math.round(pile.x + (glow.offset?.[0] ?? -32)),
                        Math.round(pile.y + (glow.offset?.[1] ?? -21)));
      context.restore();
    }
    // Сам спрайт — базовой палитрой, мимо фильтра суток: при послойном
    // кадре тем же приёмом, что интерьер (на кадр + немедленный вырез
    // окна; всё, что глубже, ляжет в слой позже и закроет окно само).
    if (layeredFrame) drawBrightImage(image, x, y);
    else context.drawImage(image, x, y);
    return true;
  }
  context.drawImage(image, x, y);
  return true;
}

// КУЧИ ИДУТ В ОБЩЕМ ПРОХОДЕ ПО ГЛУБИНЕ, А НЕ ОТДЕЛЬНЫМ РАННИМ.
//
// В движке кучу на полу рисует САМА ПОСТРОЙКА: в отрисовщике объекта
// (VA 0x00424514) есть цикл по её клеткам, который берёт клетки с битами
// 0x2000 и 0x200000, принадлежащие этому объекту, находит контейнер через
// FUN_004149F8 и рисует его — уже ПОСЛЕ пола. Поэтому в оригинале мешок в
// будке видно.
//
// У нас кучи рисовались одним ранним проходом до объектов, и постройка
// закрашивала их сверху: курсор кучу находил (он ищет по клетке), а
// картинки не было. Теперь куча получает ключ глубины и едет в тот же
// отсортированный проход, что юниты и объекты; куча на клетках постройки
// берёт ключ САМОЙ постройки с малой добавкой, чтобы лечь сразу за ней.
//
// В том же цикле движка стоит `-1 < контейнер[+0x0F]` — спрятанные кучи он
// не рисует вовсе. Это независимое подтверждение смысла знака: он выведен
// из ветки обыска, а здесь всплывает в отрисовке.
// В КАКОЙ ПОСТРОЙКЕ ЛЕЖИТ КУЧА. Клетки построек знает hero.buildingCells,
// а у объекта сцены свой номер — `record_slot`. Куча внутри рисуется НЕ
// общим проходом, а самой постройкой: в движке проход содержимого
// (VA 0x00424514, 0x425AA8) идёт СРАЗУ ПОСЛЕ ПОЛА и до стен с крышей.
// Иначе выходит одно из двух: либо пол накрывает кучу, либо куча
// просвечивает сквозь крышу.
export function lootSlotOf(pile) {
  const cell = pile?.cell;
  if (!cell) return null;
  return hero.buildingCells?.get(`${cell.row}:${cell.col}`)?.slot ?? null;
}

// Кучи ВНУТРИ этой постройки — их рисует она сама, сразу после пола.
export function lootInside(slot) {
  return loot.filter((pile) => !pile.taken && pile.items.length &&
    !lootHidden(pile) && !lootInNest(pile) && lootSlotOf(pile) === slot);
}

// Кучи ВНЕ построек, в порядке отрисовки.
//
// ХОЗЯИН РЕШАЕТСЯ ПО КЛЕТКАМ, И ТОЛЬКО ПО НИМ. В движке кучу на клетках
// постройки рисует сама постройка, сразу после пола (VA 0x00424514) — у нас
// это `lootSlotOf` по `hero.buildingCells`, и такие кучи отсеяны выше. Всё
// остальное — обычные предметы сцены со своей глубиной.
//
// Здесь же стоял ВТОРОЙ ответ на тот же вопрос: `coverSortY` брал максимальный
// ключ среди объектов, ЧЬЯ РАМКА накрывает точку кучи, и куча уезжала за него.
// Рамка — не пиксели и не клетки: у лесной плитки она тянется на четыре сотни
// точек, и топор на земле получал её ключ вместо своего. Тем же тестом вчера
// съело спутника под избой, только там он отменял вырез силуэта.
export function lootDrawList(visible) {
  const out = [];
  for (const pile of loot) {
    if (pile.taken || !pile.items.length) continue;
    if (lootInNest(pile)) continue;              // лежит в сундуке, а не на полу
    if (lootHidden(pile)) continue;
    //: Лежащую в постройке пропускаем — её рисует сама постройка.
    if (lootSlotOf(pile) != null) continue;
    // Запас в 80 пикселей — НАШ, чисто отрисовочный: он лишь не даёт
    // отсечь кучу, чья картинка залезает за край окна.
    if (pile.x < visible.left - 80 || pile.x > visible.right + 80 ||
        pile.y < visible.top - 80 || pile.y > visible.bottom + 80) continue;
    out.push({ pile, sortY: Math.round(pile.y) });
  }
  return out.sort((a, b) => a.sortY - b.sortY);
}
