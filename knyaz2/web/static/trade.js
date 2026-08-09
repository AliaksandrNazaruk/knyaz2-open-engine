// Торговый экран.
//
// Экран номер 7 занимает окно мира целиком и держит четыре ряда по сорок
// два места, из которых видно девять (VA 0x42C2AC рисует, 0x43AEF0 ловит
// мышь):
//
//     ряд 2  вверху   товар собеседника
//     ряд 3           что он отдаёт
//     ряд 1           что отдаю я
//     ряд 0  внизу    мой мешок
//
// Щелчок по вещи перекладывает её в парный ряд (0 <-> 1 у меня, 2 <-> 3 у
// него), а исходный ряд уплотняется. Вещь с нулевой ценой не берётся —
// квестовое не продаётся.
//
// Деньги экран сводит сам: пока стороны неравны, монеты по одной
// переезжают из кошелька на стол и обратно, поэтому обмен всегда сходится
// в ноль (VA 0x42C2AC).
import { world } from "./world.js";
import { hero } from "./hero.js";
import { actorItem } from "./actor.js";
import { bagPut, bagTake } from "./inventory.js";
import { enchantPrice } from "./jewels.js";
import { carriedWeight, itemWeight } from "./carry.js";
import { selectionLead } from "./orders.js";
import { roundHalfEven } from "./round.js";

export const trade = {
  open: false,
  partner: null,          // юнит или куча
  trader: null,           // чей мешок слева (0x849514 = первый выбранный)
  village: false,         // деревенский торговец: товар со склада, денег без счёта
  mode: 0,                // 0x849624: должность 2…4 у деревенского, 6 у обычного,
                          // 0 у кучи. Деревенские множители — только при mode > 0.
  priced: false,          // считать ли цены вообще (куча и «неторгующие» — нет)
  columns: [[], [], [], []],
  scroll: [0, 0, 0, 0],
  purse: { mine: 0, his: 0 },     // в кошельках
  table: { mine: 0, his: 0 },     // на столе
};

function rules() { return world.map?.hero?.rules?.trade ?? null; }

// ЧЕЙ мешок лежит слева. В движке это указатель 0x849514 — тот же, что у
// панели персонажа (VA 0x43346C копирует `0x849514 + 0x62`), а он идёт за
// первым выбранным. То есть торгует ТОТ, кого выбрали, а не обязательно
// герой. Деньги при этом общие — кошелёк отряда (0x84951C + 0x26).
function trader() { return trade.trader ?? hero; }

export function tradeLayout() { return rules()?.screen_layout ?? null; }

function slots() { return tradeLayout()?.slots ?? 42; }

function say(key) {
  const text = tradeLayout()?.messages?.[key];
  if (text) world.onStatus?.(text);
  return false;
}

// Торгует ли этот собеседник по настоящим ценам (VA 0x41A6CC, 0x41AF3C).
// Кучу на земле движок открывает вовсе без партнёра (VA 0x424128 обнуляет
// 0x849524), а гейт цен у юнита — «ПАРТНЁР ЖИВ»: порода без бита 0x80 и
// поза не 3/0xB/0xC (позы смерти). У ТРУПА цен нет: и наценки (0x41A6CC
// возвращает базу), и проверка «Слишком мало даешь!» (0x41F638:74)
// стоят за этим гейтом — обыск убитого всегда бесплатный.
function partnerIsPriced(partner) {
  if (!partner || partner.items) return false;       // куча — не собеседник
  const gate = rules()?.price_gate;
  if (!gate) return true;
  // порода юнита — поле breed (+0x1A); бит 0x80 ставит смерть зверя.
  // Позы смерти движка (gate.types 3/0xB/0xC) в порте — alive === false.
  if ((partner.breed ?? 0) & (gate.flag ?? 0x80)) return false;
  if (partner.alive === false) return false;
  return true;
}

// Открыть обмен. Слева мой мешок, справа его товар — деревенскому
// торговцу товар кладёт прилавок, обычному юниту его же мешок, куче — её
// содержимое (VA 0x43346C и 0x424128).
//
// Монеты в мешке движок при открытии приплюсовывает к деньгам: каждая вещь
// вида 0x0B класса 0x24 стоит 50 (VA 0x433489).
export function tradeOpen(partner, stock = [], village = false) {
  const size = slots();
  const set = rules();
  trade.open = true;
  trade.partner = partner;
  // Торгует выбранный: панель и обмен в движке смотрят один указатель.
  trade.trader = selectionLead() ?? hero;
  trade.village = village;
  trade.priced = partnerIsPriced(partner);
  // Режим: должность деревенского торговца, 6 у обычного, 0 у кучи.
  trade.mode = trade.priced
    ? (village ? (partner?.role ?? 2) : (set?.mode?.ordinary ?? 6))
    : 0;
  trade.columns = [
    (trader().bag ?? []).filter(Boolean).slice(0, size),
    [],
    stock.filter(Boolean).slice(0, size),
    [],
  ];
  trade.scroll = [0, 0, 0, 0];
  // ЭКЗЕМПЛЯРНЫЕ поля (В10): крепость/износ, слово чар и отрава едут через
  // обмен по уникальной ссылке записи, как поля +0x04/+0x0C/+0x0E GAME.x.
  trade.details = {};
  const remember = (name, patch) => {
    if (!name || !patch) return;
    const entry = trade.details[name] ?? (trade.details[name] = {});
    Object.assign(entry, patch);
  };
  const who = trader();
  for (const [name, word] of Object.entries(who.bagEnchant ?? {})) {
    if (word) remember(name, { enchant: word });
  }
  for (const [name, strength] of Object.entries(who.bagStrength ?? {})) {
    if (typeof strength === "number") remember(name, { strength });
  }
  for (const [name, count] of Object.entries(who.bagCount ?? {})) {
    if (typeof count === "number") remember(name, { count });
  }
  for (const [name, poison] of Object.entries(who.bagPoison ?? {})) {
    if (poison) remember(name, { poison });
  }
  for (const [name, oiled] of Object.entries(who.itemOiled ?? {})) {
    if (oiled) remember(name, { oiled: true });
  }
  if (Array.isArray(partner?.details)) {
    // куча: параллельные массивы items/details/enchant
    (partner.items ?? []).forEach((name, at) => {
      const detail = partner.details[at];
      if (detail && Object.keys(detail).length) remember(name, { ...detail });
      const word = partner.enchant?.[at];
      if (word) remember(name, { enchant: word });
    });
  } else if (partner) {
    // юнит: его собственные карты по имени
    for (const [name, word] of Object.entries(partner.bagEnchant ?? {})) {
      if (word) remember(name, { enchant: word });
    }
    for (const [name, strength] of Object.entries(partner.bagStrength ?? {})) {
      if (typeof strength === "number") remember(name, { strength });
    }
    for (const [name, count] of Object.entries(partner.bagCount ?? {})) {
      if (typeof count === "number") remember(name, { count });
    }
    for (const [name, poison] of Object.entries(partner.bagPoison ?? {})) {
      if (poison) remember(name, { poison });
    }
    for (const [name, oiled] of Object.entries(partner.itemOiled ?? {})) {
      if (oiled) remember(name, { oiled: true });
    }
  }
  const coin = set?.coin;
  let purse = hero.money ?? 0;
  if (coin) {
    for (const name of trader().bag ?? []) {
      const item = name ? actorItem(name) : null;
      if (item?.kind === coin.kind && item?.index === coin.class) purse += coin.value;
    }
  }
  trade.purse = {
    mine: purse,
    his: village ? 999999 : (partner?.money ?? 0),
  };
  trade.table = { mine: 0, his: 0 };
  return trade;
}

// Переложить вещь в парный ряд.
export function tradeMove(column, row) {
  const layout = tradeLayout();
  if (!layout || !trade.open) return false;
  const list = trade.columns[column];
  const name = list?.[row];
  if (!name) return false;
  // Квестовую вещь (цена ноль) на стол не выложить.
  if (column === 0 && (actorItem(name)?.price ?? 0) === 0) return false;
  const target = Number(layout.pair[String(column)]);
  if (trade.columns[target].length >= slots()) return false;
  list.splice(row, 1);                     // ряд уплотняется
  trade.columns[target].push(name);
  balance();
  return true;
}

// Полная цена ОДНОЙ ЗАПИСИ предмета (VA 0x41ABBC). Голое поле цены класса
// для этого не годится: у зелий оно отрицательное (классы 85…92 несут
// −2…−14), у стопок означает цену штуки, а у зачарованной вещи не
// учитывает надбавок. Движок разбирает вид записи:
//
//     0x0C стопка   цена класса * количество (запись +0x04)
//     0x09 зелье    round(−крепость * цена) << 3, крепость — та же +0x04
//     0x0B монета   цена класса как есть
//     прочее        цена плюс надбавки пяти групп чар и суффикса,
//                   и не меньше единицы у ОПОЗНАННОЙ вещи
//
// Состояния записи приходят сюда по ссылке экземпляра: count/strength/enchant.
export function itemValue(name, instance = null) {
  const item = actorItem(name);
  if (!item) return 0;
  const kinds = rules()?.item_kinds ?? { stack: 0x0C, potion: 0x09, coin: 0x0B };
  const price = item.price ?? 0;
  if (item.kind === kinds.stack) {
    const count = instance?.count ?? rules()?.ammo_stack ?? 30;
    return price * count;
  }
  if (item.kind === kinds.potion) {
    const strength = instance?.strength ?? item.durability ?? 0;
    const value = price < 0 ? roundHalfEven(-strength * price) : price;
    return value << 3;
  }
  if (item.kind === kinds.coin) return price;
  const word = instance?.enchant ?? 0;
  let value = price + enchantPrice(word);
  if (value < 1) value = 1;
  return value;
}

//: Цена стороны — по правилам движка: своё считается продажной ценой,
//: чужое закупочной, и обе зависят от разницы навыка торговли. У кучи и
//: у «неторгующих» собеседников поправок нет вовсе — цена базовая.
function sideValue(names, selling) {
  const set = rules();
  const skill = tradeSkill(hero);
  const his = tradeSkill(trade.partner);
  let total = 0;
  for (const name of names) total += itemValue(name, trade.details?.[name]);
  if (!set?.price || !trade.priced) return total;
  const step = selling ? set.price.skill_step_sell : set.price.skill_step_buy;
  const share = 1 + (selling ? 1 : -1) * (skill - his) * step;
  let value = selling ? total * set.price.half * share : total * share;
  // Деревенские множители идут по РЕЖИМУ: он положителен только когда
  // торговец деревенский и деревня торговать разрешает (VA 0x41A6E4).
  if (trade.mode > 0 && trade.mode !== (set.mode?.ordinary ?? 6)) {
    value *= selling ? set.price.village_sell : set.price.village_buy;
  }
  return roundHalfEven(value);
}

export function tradeSkill(actor) {
  const index = rules()?.skill?.index ?? 14;
  return actor?.skills?.[index] ?? 0;
}

export function tradeTotals() {
  return {
    mine: sideValue(trade.columns[1], true) + trade.table.mine,
    his: sideValue(trade.columns[3], false) + trade.table.his,
  };
}

// Свести стороны монетами — в движке это делается по одной за кадр, у нас
// сразу, но правило то же: не хватает у меня — доплачиваю из кошелька.
//
// У КУЧИ монеты не двигаются вовсе: вся балансировка стоит под проверкой
// «есть собеседник» (VA 0x42C2AC), а открытие кучи обнуляет и собеседника,
// и монеты стола (VA 0x424128). Взять с земли своё — даром.
function balance() {
  if (!trade.priced) return;
  let guard = 0;
  for (;;) {
    const { mine, his } = tradeTotals();
    if (mine === his || guard++ > 100000) return;
    if (his < mine) {
      if (trade.table.mine > 0) { trade.table.mine -= 1; trade.purse.mine += 1; continue; }
      if (trade.purse.his > 0) { trade.purse.his -= 1; trade.table.his += 1; continue; }
      return;
    }
    if (trade.table.his > 0) { trade.table.his -= 1; trade.purse.his += 1; continue; }
    if (trade.purse.mine > 0) { trade.purse.mine -= 1; trade.table.mine += 1; continue; }
    return;
  }
}

// Закрыть сделку. Отказ возвращает всё по местам, согласие меняет.
export function tradeFinish(deal) {
  if (!trade.open) return false;
  const size = slots();
  const mine = deal ? trade.columns[3] : trade.columns[1];
  const stays = trade.columns[0];
  if (stays.length + mine.length > size) return say("weight");
  if (deal) {
    // Вес считается по всему, что окажется в мешке, и предел — ЦЕЛОЧИСЛЕННЫЙ:
    // выносливость * 1000 / 3 + 20000 с усечением, а не округлением
    // (VA 0x423218). Стопка весит за все свои штуки (VA 0x41AA78).
    const who = trader();
    const oldBag = (who.bag ?? []).reduce((sum, name) =>
      sum + itemWeight(name, who.bagCount?.[name] ?? null), 0);
    let grams = carriedWeight(who) - oldBag;
    for (const name of [...stays, ...mine]) {
      grams += itemWeight(name, trade.details?.[name]?.count ?? null);
    }
    const limit = world.map?.hero?.rules?.carry?.weight;
    const stamina = trader().characteristics?.[5] ?? 10;
    const cap = limit
      ? Math.trunc(stamina * limit.per_stamina / limit.divisor) + limit.base
      : Math.trunc(stamina * 1000 / 3) + 20000;
    if (grams > cap) return say("weight");
    // Куча под ногами держит те же 42 места: если моя выкладка и её
    // остаток вместе не влезают, движок отказывает (VA 0x41F638).
    if (!trade.priced &&
        trade.columns[1].length + trade.columns[2].length > size) {
      return say("pile_full");
    }
    // «Слишком мало даешь!»: торговец не отдаёт своё дешевле, чем берёт.
    // Проверка стоит только у настоящего собеседника — у кучи её нет.
    if (trade.priced) {
      const totals = tradeTotals();
      if (totals.mine < totals.his) return say("too_little");
    }
  }
  const who = trader();
  who.bag = new Array(size).fill(null);
  [...stays, ...mine].forEach((name, index) => { who.bag[index] = name; });
  // Экземплярные карты переписываются тем же составом, что и мешок.
  const details = trade.details ?? {};
  who.bagStrength = {};
  who.bagCount = {};
  who.bagEnchant = {};
  who.bagPoison = {};
  // Масло — поле самой записи, поэтому карта общая для мешка и гнезда.
  // Пересборка торговых рядов не должна смыть метку с надетых стрел.
  who.itemOiled = Object.fromEntries(
    Object.values(who.equipment ?? {})
      .filter((name) => name && who.itemOiled?.[name])
      .map((name) => [name, true]));
  for (const name of who.bag) {
    const detail = name && details[name];
    if (!detail) continue;
    if (typeof detail.strength === "number") {
      who.bagStrength[name] = detail.strength;
    }
    if (typeof detail.count === "number") who.bagCount[name] = detail.count;
    if (detail.enchant) {
      who.bagEnchant[name] = detail.enchant;
    }
    if (detail.poison) {
      who.bagPoison[name] = detail.poison;
    }
    if (detail.oiled) who.itemOiled[name] = true;
  }
  // Что осталось у той стороны: моя выкладка плюс её нетронутое. Так
  // движок и переписывает и мешок собеседника, и содержимое кучи
  // (VA 0x41F638) — взятое из кучи оттуда пропадает.
  const left = deal
    ? [...trade.columns[1], ...trade.columns[2]]
    : [...trade.columns[2], ...trade.columns[3]];
  const partner = trade.partner;
  if (partner) {
    if (partner.items) {
      partner.items = left.slice(0, size);
      // параллельные экземплярные поля кучи пересобираются по именам
      partner.details = partner.items.map((name) =>
        details[name] ? { ...details[name] } : {});
      partner.enchant = partner.items.map((name) => details[name]?.enchant ?? 0);
      // Опустела — куча с земли убирается совсем (VA 0x4136A8).
      if (!partner.items.length && !partner.money) partner.taken = true;
    } else if (!trade.village) {
      partner.bag = left.slice(0, size);
      partner.bagStrength = {};
      partner.bagCount = {};
      partner.bagEnchant = {};
      partner.bagPoison = {};
      partner.itemOiled = Object.fromEntries(
        Object.values(partner.equipment ?? {})
          .filter((name) => name && partner.itemOiled?.[name])
          .map((name) => [name, true]));
      for (const name of partner.bag) {
        const detail = name && details[name];
        if (!detail) continue;
        if (typeof detail.strength === "number") {
          partner.bagStrength[name] = detail.strength;
        }
        if (typeof detail.count === "number") partner.bagCount[name] = detail.count;
        if (detail.enchant) partner.bagEnchant[name] = detail.enchant;
        if (detail.poison) partner.bagPoison[name] = detail.poison;
        if (detail.oiled) partner.itemOiled[name] = true;
      }
    } else if (deal) {
      // Деревенский прилавок движок правит поимённо (VA 0x41F638): каждую
      // купленную вещь он ищет в прилавке и обнуляет её место, а каждую
      // проданную уничтожает совсем — деревня их не перепродаёт. Без этого
      // прилавок был бы бездонным.
      const counter = partner.counter ?? [];
      for (const name of trade.columns[3]) {
        const at = counter.indexOf(name);
        if (at >= 0) counter[at] = null;
      }
      partner.counter = counter;
      trade.columns[1].length = 0;          // проданное исчезает из мира
    }
  }
  if (deal) {
    // Деньги считает движок разницей столов, а не остатком кошелька, и
    // ниже нуля не пускает (VA 0x41F638). У кучи столы пусты — обмен
    // с землёй денег не касается.
    hero.money = Math.max(0, (hero.money ?? 0) + trade.table.his - trade.table.mine);
    if (partner && !trade.village && !partner.items) {
      partner.money = (partner.money ?? 0) + (trade.table.mine - trade.table.his);
    }
    // Торговать учит только живой собеседник: рост навыка лежит в ветке
    // «партнёр есть» (VA 0x41F638), у кучи его нет.
    if (trade.priced) learn();
  }
  trade.open = false;
  world.onTrade?.(partner);
  return true;
}

// Удачная сделка учит торговать обоих: навык растёт на сумму сделки,
// делённую на 1024, и упирается в сотню (VA 0x41F638).
function learn() {
  const set = tradeLayout()?.skill;
  const index = rules()?.skill?.index ?? 14;
  if (!set) return;
  const gained = Math.floor((sideValue(trade.columns[1], true) + trade.table.mine)
                            / set.per_deal);
  if (!gained) return;
  for (const actor of [hero, trade.partner]) {
    if (!actor?.skills) continue;
    actor.skills[index] = Math.min(set.cap, (actor.skills[index] ?? 0) + gained);
  }
}

export function tradeClose() { trade.open = false; }
