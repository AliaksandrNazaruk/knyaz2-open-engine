// Точка входа браузерного клиента: загрузка карты, цикл кадров, отладка.
//
// Раскладка модулей повторяет устройство самой сцены:
//   dom        узлы страницы            viewport  холст, слои, камера
//   content    чтение пака              world     мир в рантайме
//   daylight   время суток              light     локальный свет у построек
//   water      анимированная подложка   shadows   тени
//   hero       персонаж                 entities  постройки и реквизит
//   ambient    атмосфера                scene     сборка кадра
//   debug      диагностика              input     ввод
import { ambientNode, canvas, clockRunNode, clockTimeNode, debugGroundNode,
         debugObjectsNode, errorNode, showRoofsNode, statsNode, statusNode,
         titleNode } from "./dom.js";
import { contentUrl, preload, readJson } from "./content.js";
// Счётчик такта НЕ сбрасывается при входе на карту: в движке
// `_DAT_0084962c` глобальный и монотонный, от него же считается время суток.
import { clock, clockAdvance } from "./clock.js";
import { creationOpen, creationOpened } from "./creation.js";
import { loadMap, loadShared, mapAssets, shared,
         world } from "./world.js";
import { actorItem, actorItemName, actorSheetPaths } from "./actor.js";
import { resize, updateZoom, view } from "./viewport.js";
import { clockTick, daylight, daylightSet, sunProgress } from "./daylight.js";
import { lightActive } from "./light.js";
import { water, waterInit, waterRender, waterTick } from "./water.js";
import { ambient, ambientInit, ambientTick } from "./ambient.js";
import { centreOnHero, hero, heroAnchor, heroAttackPose, heroCellAt, heroCellKey, heroDie,
         heroEquip, heroEquipmentAssets, heroFree, heroItem, heroNeighbor, heroPlanPath,
         heroPlayAction, heroSetup, heroTick,
         heroUnequip, heroUpdateBuilding, heroWeapon } from "./hero.js";
import { audioSetup } from "./audio.js";
import { playEffect, playMusic, playPositional, playUnitVoice, playVoiceLine,
         positionPan, positionVolume, sound, soundBindCell, soundInit,
         soundMapEnter, soundStats, soundTick } from "./sound.js";
import { sfxSetup } from "./sfx.js";
import { soundscapeTick } from "./soundscape.js";
import { shadows } from "./shadows.js";
import { render } from "./scene.js";
import { edgeScrollTick } from "./input.js";
import { lootAssets, lootDrop, lootPut, lootSetup, loot } from "./loot.js";
import { projectileAssets, projectiles } from "./projectiles.js";
import { inventorySetup, pickUp } from "./inventory.js";
import { beltFollow, refresh as refreshUi, showWorldMap, uiEscape,
         uiSetup } from "./ui.js";
import { unitSpawn } from "./units.js";
import { warbandJoin } from "./warband.js";
import { exitsSetup, exitsTick } from "./exits.js";
import { partyRegroup, unitsSetup, unitsTick, units } from "./units.js";
import { combat, combatSetup, combatTick, orderAt } from "./combat.js";
import { dialog, dialogApproachTick, dialogJournal,
         questsReset } from "./dialog.js";
import { effectsTick } from "./effects.js";
import { buildingsSetup } from "./buildings.js";
import { createSelfCheck } from "./selfcheck.js";
import { formationCells, markerVisible, openLocation, revealAll, standAt,
         travelTick, travelling, worldMap, worldMapSetup } from "./worldmap.js";
import { applySave, dropSave, saveGame, savedGame } from "./save.js";
import { questItemUsable, useQuestItem } from "./questitems.js";
import { villageSetup, villageTick } from "./village.js";
import { mapStateCapture } from "./mapstate.js";

import "./input.js";

//: Свёртка локации при уходе (VA 0x43A628) идёт НЕ на всех картах: движок
//: гейтит её номером — ниже 50 и мимо 26…32. Двадцать шестая и следующие
//: семь это карты случайных боёв, на них добро не копится.
const TEARDOWN_MAP_MAX = 0x32;
const TEARDOWN_SKIP_FROM = 0x1A, TEARDOWN_SKIP_TO = 0x20;

function mapKeepsSpoils(number) {
  const map = Number(number);
  return map < TEARDOWN_MAP_MAX &&
    (map < TEARDOWN_SKIP_FROM || map > TEARDOWN_SKIP_TO);
}

// СВЁРТКА ЛОКАЦИИ (VA 0x43A628). Всё, что было на убитом, ложится кучей в
// его клетку — боеприпас (+0x50), пять надетых (+0x58), пять украшений
// (+0xB6) и сорок две ячейки мешка (+0x62), — а следом туда же идут его
// деньги (+0x26). Сама запись потом вырезается из отряда; у нас вместо этого
// слот попадает в память карты, и `unitsSetup` его больше не поднимает.
//
// Делается это ИМЕННО ПРИ УХОДЕ, а не в миг смерти: пока игрок на карте,
// труп лежит со своим добром, и обобрать его можно обычным способом.
function mapTeardown(number) {
  if (!mapKeepsSpoils(number)) return 0;
  let dropped = 0;
  for (const unit of units) {
    if (unit.alive !== false || unit.ally || !unit.cell) continue;
    const at = heroAnchor(unit.cell.row, unit.cell.col);
    const goods = [...Object.values(unit.equipment ?? {}).filter(Boolean),
                   ...(unit.bag ?? []).filter(Boolean)];
    let pile = null;
    for (const name of goods) {
      const put = lootPut(name, at.x, at.y, { ...unit.cell });
      if (put) { pile = put; dropped += 1; }
    }
    unit.equipment = {};
    unit.bag = [];
    if (pile && unit.money) {
      pile.money = (pile.money ?? 0) + unit.money;
      unit.money = 0;
    }
  }
  return dropped;
}

let lastFrameTime = 0;

function animationLoop(now) {
  const seconds = now / 1000;
  const dt = lastFrameTime ? Math.min(0.1, seconds - lastFrameTime) : 0;
  lastFrameTime = seconds;
  // Мировой такт движка двигается РОВНО ЗДЕСЬ и больше нигде — как
  // `_DAT_0084962c` в начале главного цикла (VA 0x438A00). Всё периодическое
  // фазируется от него, а не от кадров браузера.
  clockAdvance(seconds);
  let dirty = false;
  if (waterTick(now)) { waterRender(); dirty = true; }
  soundTick(now);            // догрузка звуков карты — по одному за такт мира
  soundscapeTick(now);       // амбиент, музыка карты и приветствия спутников
  if (clockTick(now)) dirty = true;
  if (ambientTick(now)) dirty = true;
  // Камера за идущим героем НЕ едет: в движке её двигает только курсор
  // у края и наведение при загрузке карты (VA 0x437CD0 и 0x4291B4).
  if (edgeScrollTick()) dirty = true;
  // ЛОКАЦИЯ СЧИТАЕТСЯ, ТОЛЬКО ПОКА МЫ НА НЕЙ.
  //
  // В движке уход на глобальную карту делает текущую карту −1 (VA 0x420900),
  // а КАЖДЫЙ проход по юнитам отфильтрован по ней (VA 0x413894:37 —
  // `отряд.map == [0x8496C8]`). Отряда с картой −1 не бывает, поэтому в
  // походе локация не считается вовсе: ни шагов, ни ударов, ни разговоров.
  //
  // Гейт стоит на currentMap, а не на worldMap.onMap. Разница существенная:
  // onMap поднимается на клетке двери, а снимается только входом в другую
  // локацию — стоило закрыть панель и отойти, как игрок снова ходил по
  // карте, а игра считала его в походе. Прошлая попытка гейта развалилась
  // именно об это. currentMap же обнуляется на выходе и заполняется только
  // enterMap, так что «отойти от двери» нельзя: герой тоже стоит.
  //
  // Саму карту при этом НЕ ВЫГРУЖАЕМ. Глобальная карта рисуется из тех же
  // данных (`world.map.interface` и `hero.rules.world_map`), и обнуление
  // world.map оставляет чёрный экран: панели неоткуда взяться.
  if (currentMap !== null) {
    if (heroTick(now, dt)) dirty = true;
    if (unitsTick(now, dt)) dirty = true;
    // Сюжетная встреча: NPC с взведённым битом «подойди и заговори» сам
    // ловит игрока рядом и переводит его в приказ 0x22 (VA 0x410684).
    if (dialogApproachTick()) dirty = true;
    if (combatTick(dt)) dirty = true;
  }
  // ОТРАВА ИДЁТ И В ПОХОДЕ. Её вычитание в мировом такте не отфильтровано по
  // карте (VA 0x41C944), а у хода по глобальной есть ещё своя копия того же
  // вычитания (VA 0x4277F4). Терять здоровье в пути — канон.
  if (effectsTick()) dirty = true;
  // хозяйство деревни: казна владения и мастерская (VA 0x41D530, 0x417BD8)
  if (villageTick()) dirty = true;
  if (worldTick(now)) refreshUi();
  exitsTick();
  if (dirty) render();
  requestAnimationFrame(animationLoop);
}

function refresh() {
  resize();
  render();
}

// ВЫХОД В МЕНЮ ПО ESC. В движке меню открывается прямо из игры, и «Сохранить
// игру» там пишет текущее состояние в выбранное место (KONUNG2.SA<N>).
// Здесь меню — отдельная страница, поэтому состояние сохраняется ПЕРЕД
// уходом: тогда в меню есть что раскладывать по местам, и ни один шаг не
// теряется. Автосохранение при входе на карту остаётся как было.
window.addEventListener("keydown", (event) => {
  if (event.code !== "Escape" || event.repeat) return;
  event.preventDefault();
  // Экран создания героя ESC не закрывает: из него выходят кнопкой «Играть»,
  // как в движке — там это отдельное состояние экрана.
  if (creationOpened()) return;
  // Сперва то же, что делает движок: отменить перенос вещи и закрыть
  // открытый экран. Пока что-то открыто, ESC из игры не выкидывает.
  if (uiEscape()) { render(); return; }
  if (Number.isFinite(currentMap)) saveGame(currentMap);
  location.href = "/menu.html";
});

// Ход по глобальной карте идёт мировыми тактами: на каждом отряд
// продвигается и бросает жребий встречи (VA 0x4277F4 зовётся раз за такт).
// Собственных часов здесь больше нет — счётчик один на всю игру и живёт в
// clock.js; сюда приходит только число тактов, прошедших за этот кадр.
function worldTick(now) {
  const seconds = now / 1000;
  // Пока идёт вход в карту, поход не тикает: встреча посреди чужой загрузки
  // запускала бы второй enterMap поверх первого.
  //
  // ЧАСЫ ЗДЕСЬ НЕ ТРОГАЕМ. Счётчик такта общий на всю игру, и подводить его
  // к текущему моменту отсюда нельзя: этот выход срабатывает каждый кадр,
  // пока отряд не в походе, и обнулял накопитель — такт шёл ~0.7 в секунду
  // вместо 12.8, а вместе с ним стояли сутки, стройка и счётчик работы.
  // Копиться шагам похода нечему: они берутся из clock.elapsed, то есть
  // только из тактов ЭТОГО кадра.
  if (!travelling() || entering) return false;
  let moved = false;
  for (let шаг = 0; шаг < clock.elapsed; шаг += 1) {
    const step = travelTick({ body: hero.data?.body ?? 0,
                              pathfinder: heroPathfinder() });
    moved = true;
    if (!step || step.kind === "walking") continue;
    if (step.kind === "encounter") { meetEnemy(step); return true; }
    statusNode.textContent = step.kind === "blocked" ? "Дальше пути нет"
      : arrivalText(step.row, step.col);
    return true;
  }
  return moved;
}

// Следопыт ГЕРОЯ: уклонение от бродячих отрядов меряется по нему одному
// (VA 0x4277F4 читает 0x84951C+0xDF) — в отличие от скорости похода,
// которая берёт максимум по отряду.
function heroPathfinder() {
  const names = world.map?.hero?.rules?.progression?.skills?.names ?? [];
  const index = names.indexOf("Следопыт");
  return index >= 0 ? hero.skills?.[index] ?? 0 : 0;
}

//: Что писать, придя в клетку. ИМЯ ЗАКРЫТОЙ ЛОКАЦИИ НЕ ПОКАЗЫВАЕМ: пока её
//: значок скрыт сюжетом (бит 0x80 клетки), игрок о ней знать не должен —
//: движок и рисует такую клетку пустой (VA 0x4277F4 -> markerVisible).
function arrivalText(row, col) {
  const cell = worldMap.cells[row][col];
  if (markerVisible(cell)) {
    const name = worldMap.rules.names?.[cell & 0xFF];
    if (name) return name;
  }
  return `Клетка ${row}:${col}`;
}

// Встреча в пути: движок показывает заставку и уводит бой на отдельную
// карту-местность, а туда переносит скопированный отряд (VA 0x4277F4).
async function meetEnemy(met) {
  statusNode.textContent = "Засада!";
  showWorldMap(false);
  const ok = await enterMap(met.scene, arrivalCell(met.scene));
  if (!ok) { showWorldMap(true); return; }
  const roster = world.map?.encounters?.[String(met.group)]?.units ?? [];
  if (!roster.length) {
    statusNode.textContent = `Встреча (отряд ${met.group}) — состава в паке нет`;
    return;
  }
  // Вожак встаёт поодаль от героя, остальные — по таблице расстановки.
  const here = hero.cell ?? { row: 0, col: 0 };
  const lead = { row: Math.max(0, here.row - 10), col: here.col };
  const spots = formationCells(lead.row, lead.col, 0, roster.length,
                               (row, col) => row >= 0 && col >= 0);
  roster.forEach((foe, index) => {
    const spot = spots[index] ?? spots[spots.length - 1];
    const foeUnit = unitSpawn({ ...foe, cell: { row: spot.row, col: spot.col } });
    // Засада приезжает УЖЕ в бою: движок переносит на карту-местность саму
    // запись отряда вместе с её флагами (VA 0x4277F4).
    warbandJoin(foeUnit.side ?? 0, hero.side ?? 0);
  });
  await preload(mapAssets([]));
  statusNode.textContent = `Засада: ${roster[0].name} и ещё ${roster.length - 1}`;
  render();
}

// ЗАКАЗ НЕДОСТАЮЩЕЙ КАРТИНКИ. Зовётся из spriteReady, когда кадру нужен
// лист, которого ещё нет. Заявки копятся кадр-другой и уходят пачкой, иначе
// на каждый кадр отрисовки летел бы свой запрос и своя перерисовка.
const заказано = new Set();
let очередь = [];
let таймер = null;
world.requestAsset = (path) => {
  if (!path || заказано.has(path)) return;
  заказано.add(path);
  очередь.push(path);
  if (таймер) return;
  таймер = setTimeout(() => {
    const пачка = очередь;
    очередь = [];
    таймер = null;
    preload(пачка).then(() => render());
  }, 50);
};

//: Что где лежит в паке: номер карты -> путь до её описания.
const mapPaths = new Map();
//: Имена локаций из манифеста — они канонные, из таблицы имён exe.
const mapNames = new Map();
function mapNameOf(number) {
  return mapNames.get(Number(number)) ?? `карта ${number}`;
}
let currentMap = null;

// ЗАМОК ВХОДА. enterMap долгий (fetch и предзагрузки), а зовут его четыре
// дороги сразу: двери, глобальная карта, засада из worldTick и консоль.
// Два входа внахлёст раскладывали мир и героя вперемешку, и самосохранение
// в конце писало эту смесь в хранилище. Второй вход, пришедший до конца
// первого, честно отваливается — щёлкнуть ещё раз дешевле, чем чинить сейв.
let entering = false;

// Войти в карту. Тем же путём идёт и первый запуск, и переход с соседней:
// мир, жители, кучи и выходы заводятся заново, а герой — его мешок,
// навыки и здоровье — переезжает как есть.
async function enterMap(number, entry = null) {
  if (entering) return false;
  const path = mapPaths.get(Number(number));
  if (!path) {
    statusNode.textContent = `Карты ${number} нет в паке`;
    return false;
  }
  entering = true;
  try {
    // Уходим с прежней локации — сперва запомним, что на ней случилось.
    // В движке помнить нечего: записи юнитов лежат в отряде и никуда не
    // деваются, а тут они пересоздаются из пака при каждом входе.
    if (currentMap !== null) {
      mapTeardown(currentMap);
      mapStateCapture(currentMap, units, loot);
    }
    return await enterMapInner(number, path, entry);
  } finally {
    entering = false;
  }
}

async function enterMapInner(number, path, entry) {
  const map = await readJson(contentUrl(path));
  // Вошли в локацию — отряд больше не на глобальной: в движке текущая
  // карта перестаёт быть −1, и щелчки по карте снова ничего не делают.
  worldMap.onMap = false;
  // Свечение Факела и Чистой слезы живёт до входа на карту: загрузчик
  // 0x43DF48 гасит флаг 0x849610 первым делом.
  world.glow = false;
  loadMap(map);
  ambientInit();
  // heroSetup зовём ОДИН раз: он заводит сетку и клетки построек, и
  // повторный вызов после расстановки сбивал героя с клетки прибытия.
  const assets = heroSetup(map.hero, map) ?? [];
  unitsSetup(map);
  lootSetup(map);
  exitsSetup(map);
  villageSetup(map);
  // Герой встаёт на клетку прибытия — её называет сама запись выхода.
  if (entry) {
    const anchor = heroAnchor(entry.row, entry.col);
    hero.cell = { row: entry.row, col: entry.col };
    hero.x = anchor.x;
    hero.y = anchor.y;
    hero.path = [];
    hero.step = null;
    heroUpdateBuilding();
    // Отряд встаёт вокруг вожака ПОСЛЕ него: расстановка юнитов идёт
    // раньше, и без этого спутники оставались у прежней клетки.
    partyRegroup();
  }
  // Листы кадров — только те, что нужны актёрам ЭТОЙ карты (см.
  // actorSheetPaths): вместо 121.6 МБ выходит около десяти.
  const нужные = actorSheetPaths(map.hero, [hero, ...units]);
  await preload(mapAssets([...assets, ...нужные]));
  // Листы тварей НЕ тянем скопом: их 83 на 43.4 МБ, а на карте встречается
  // горстка пород. Они рисуются через тот же spriteReady, поэтому нужный лист
  // закажет он сам, когда тварь попадёт в кадр.
  buildingsSetup();
  const waterAnimation = world.underlayVisual?.animation ?? null;
  const waterSource = waterAnimation ? world.images.get(waterAnimation.source) : null;
  if (waterSource) waterInit(waterAnimation, waterSource);
  audioSetup(map.audio);
  soundMapEnter(map.audio, hero.data?.body ?? 0);
  titleNode.textContent = map.name;
  currentMap = Number(number);
  // ВОШЛИ — ЛОКАЦИЯ ОТКРЫЛАСЬ. Загрузчик карты первым делом зовёт открытие
  // текущей локации (VA 0x43DF48 -> 0x436908): побывал — значит знаешь, и
  // её значок появляется на глобальной карте. Без этого игрок исходил бы
  // полмира, а карта оставалась пустой.
  if (worldMapSetup()) {
    openLocation(currentMap);
    standAt(currentMap);
  }
  await preload(worldMapAssets(map));
  view.zoom = 1;
  updateZoom();
  centreOnHero();
  refreshUi();
  render();
  // САМОСОХРАНЕНИЕ НА КАЖДОМ ВХОДЕ. Для демо это главное: тестировщик
  // должен вернуться туда, где поймал багу, а не начинать сначала.
  saveGame(currentMap);
  return true;
}

// Клетка, где отряд встаёт, войдя на карту: у каждой карты своя, и
// движок берёт её из таблицы 0x460028 (VA 0x436430). У переходов клетка
// своя собственная, а вот приход с глобальной идёт именно сюда.
function arrivalCell(number) {
  const table = world.map?.hero?.rules?.world_map?.arrivals ?? {};
  const place = table[String(number)];
  return place ? { row: place.row, col: place.col } : null;
}

//: Картинки глобальной карты: сама карта, значки локаций и значок отряда.
//: Значков ДВА и они разные: 179 — свой отряд (его и рисуем на карте),
//: 235 — чужие отряды. Раньше в предзагрузку шёл только 235, а рисовался
//: 179 — он не был загружен, и своего отряда на карте не появлялось вовсе.
function worldMapAssets(map) {
  const ui = map?.interface ?? {};
  const paths = [ui.map?.path, ui.world_player?.path, ui.world_party?.path];
  for (const marker of Object.values(ui.world_markers ?? {})) {
    if (marker?.path) paths.push(marker.path);
  }
  return paths.filter(Boolean);
}

async function boot() {
  refresh();
  const manifest = await readJson("/content/manifest.json");
  if (!manifest.maps?.length) throw new Error("В content pack нет карт");
  // Канон звука и вечный набор (UI + отклики) — параллельно с остальным.
  soundBindCell(heroCellAt);   // порт 0x43B9B0 для панорамы, без петли модулей
  soundInit().catch((error) => console.warn("звук не завёлся:", error));
  for (const entry of manifest.maps) {
    const number = Number(String(entry.path).match(/maps\/(\d+)\//)?.[1]);
    if (Number.isFinite(number)) {
      mapPaths.set(number, entry.path);
      if (entry.name) mapNames.set(number, entry.name);
    }
  }
  // Общее на весь пак тянем ОДИН раз: кадры героя, слои снаряжения и
  // наборы тварей одинаковы на всех картах.
  loadShared(await readJson("/content/shared.json"));
  // БЕЗ ШАБЛОНА НЕ ИГРАЕМ. Пак без hero.template (регрессия Б1 — например,
  // shared.json отдан посреди пересборки) молча собирал героя-пустышку, а
  // автосейв закреплял её в хранилище. Лучше честная ошибка загрузки, чем
  // тихая порча: сюда попадает только сломанный пак, и его надо пересобрать.
  if (!shared.hero?.template) {
    throw new Error("В shared.json нет hero.template — пак собран без героя");
  }
  // НОВАЯ ИГРА ИЗ МЕНЮ. Выбор персонажа там — это выбор мира: движок при
  // «Новой игре» открывает GAME.<номер> и читает оттуда запись героя
  // (VA 0x4387CC), а стартовая карта у каждого мира своя. Меню кладёт
  // выбранное сюда, мы применяем и СРАЗУ ЗАБЫВАЕМ — иначе перезагрузка
  // страницы начинала бы игру заново поверх уже сыгранного.
  const newGame = (() => {
    try {
      const text = localStorage.getItem("knyaz2.newgame");
      localStorage.removeItem("knyaz2.newgame");
      return text ? JSON.parse(text) : null;
    } catch { return null; }
  })();
  // ВЫБРАННЫЙ ГЕРОЙ ДОЛЖЕН ПЕРЕЖИВАТЬ ПЕРЕЗАГРУЗКУ. В движке архетип лежит в
  // САМОЙ ЗАПИСИ героя — байт +0xFC, — и потому никуда не девается: он едет
  // с записью в сейв и обратно. Делает он ровно две вещи: выбирает
  // `GAME.<N>` при «Играть» (VA 0x4387CC читает оттуда запись юнита №0) и
  // выбирает слой тела `0x30 + N` при отрисовке (VA 0x424200). Портрет на
  // экране создания к этому байту отношения не имеет — он берётся по
  // таблице 0x462CDC; прежний комментарий приписывал +0xFC ещё и картинку,
  // и из-за этой формулировки архетип уехал в localStorage вместо записи.
  //
  // Здесь заказ новой игры потребляется при старте, поэтому номер мира
  // кладётся отдельно и читается при каждом запуске. Правильное решение —
  // хранить архетип в самом герое и в сейве (это и сделано: `applyActor`
  // восстанавливает облик), а localStorage оставить лишь подсказкой.
  // ГЕРОЙ ПОЯВЛЯЕТСЯ ТОЛЬКО ВМЕСТЕ СО СВОИМ МИРОМ — и другого героя не бывает.
  //
  // Так устроен движок. «Играть» (VA 0x438A00, состояние 8) снимает копию
  // записи героя в 0x844A4C и зовёт 0x43D898, а тот открывает
  // `GAME.<байт +0xFC копии>` и перечитывает МИР ЦЕЛИКОМ: классы предметов,
  // отряды, переходы, весь массив юнитов 0x7B3C08 и поселения. Юнит №0 этого
  // массива И ЕСТЬ герой — его тело, палитра, лицо, снаряжение и отряд
  // пришли из файла. Обратно из копии движок берёт ТОЛЬКО правки экрана
  // создания: характеристики +0xC0, текущие +0xCC, двадцать навыков +0xD2,
  // породу и клетку. Облик не восстанавливают — он и так верный.
  //
  // Подменять, стало быть, некого и нечем: второго героя не существует, а
  // архетип не может рассинхронизироваться, потому что живёт ВНУТРИ копии.
  //
  // Поэтому здесь нет и не должно быть героя «по умолчанию». Мир берётся по
  // порядку: заказ новой игры, затем сохранение; нет ни того ни другого —
  // открывается экран создания, как состояние 2 в движке, которое живёт без
  // мира вовсе. Прежний `knyaz2.world` в localStorage был нашей выдумкой и
  // убран: архетип едет в записи героя, то есть в сейве.
  const saved = newGame ? null : savedGame();
  const starts = shared.hero?.starts ?? [];
  const startOf = (world) =>
    starts.find((start) => start.world === Number(world)) ?? null;

  let start = null;
  if (saved) {
    start = startOf(saved.world);
    // Сейвы, записанные до появления поля `world`, узнаются по облику: пара
    // «тело + палитра» у шести стартов однозначна (0/70, 1/70, 2/28, 3/31,
    // 4/34, 5/34), и этого хватает, чтобы не показать чужого героя ни кадра.
    if (!start && saved.hero) {
      start = starts.find((entry) =>
        entry.template?.body === saved.hero.body &&
        entry.template?.palette === saved.hero.palette) ?? null;
    }
  } else if (!newGame?.create) {
    start = startOf(newGame?.world);
  }
  if (!start) {
    // Экрану нужны правила прокачки: они лежат в общем блоке пака, там же,
    // где список стартов. Карта до этого мига не грузится вовсе.
    hero.data = hero.data ?? shared.hero;
    const chosen = await new Promise((resolve) => {
      const opened = creationOpen(starts, newGame?.world, resolve,
                                  shared.hero?.creation ?? null);
      if (!opened) resolve(null);
    });
    start = chosen ? (startOf(chosen.world) ?? chosen) : null;
  }
  // Вот единственное место, где герой обретает облик, — и оно ДО карты.
  if (start?.template) shared.hero.template = start.template;
  // ЗАПИСЬ ОТРЯДА — тоже ДО расстановки. Расстановку карты делает
  // `unitsSetup`, и она берёт бойцов из `template.party.members`; сейв
  // применяется много позже, поэтому нанятый разговором боец без этого
  // исчезал при перезагрузке. В движке та же вещь получается сама собой:
  // блок отрядов сохраняется целиком и читается до всякой расстановки.
  if (Array.isArray(saved?.party_members) && shared.hero?.template?.party) {
    shared.hero.template.party.members = saved.party_members;
  }
  // КАРТУ НАЗЫВАЕТ ВЫБРАННЫЙ МИР, а не манифест. В движке номер берётся из
  // записи отряда только что загруженного мира (`0x8496C8 = отряд+...`,
  // VA 0x438A00), то есть у каждого героя своя стартовая карта: Ратибор 33,
  // Велиславна 19, Эйнар 23, Хельга 37, Александр 45, Анастасия 1.
  //
  // `manifest.start_map` — это карта мира 0, и опора на неё была ещё одним
  // источником Ратибора: любой путь мимо выбора приземлялся у него.
  // Оставлен последним запасным, чтобы пак без стартов не ронял загрузку.
  const первая = mapPaths.get(Number(start?.map))
    ?? mapPaths.get(Number(manifest.start_map)) ?? manifest.maps[0].path;
  const путь = (saved && mapPaths.get(Number(saved.map))) || первая;
  const map = await readJson(contentUrl(путь));
  currentMap = Number(String(путь).match(/maps\/(\d+)\//)?.[1]);
  loadMap(map);
  ambientInit();

  const debugByDefault = new URLSearchParams(location.search).get("debug") === "1";
  debugGroundNode.checked = debugByDefault;
  debugObjectsNode.checked = debugByDefault;
  // Шапка и боковая панель — наши инструменты, а не часть игры. С экрана
  // они убраны стилями; этот класс возвращает их для отладки.
  document.body.classList.toggle("debug", debugByDefault);

  // Состояние трёхсот квестов заводится ОДИН раз на игру, а не на карту:
  // в движке это глобальный блок 0x6A50E8, который переживает переходы и
  // уезжает в сейв целиком (0x423CB8). В ветке смены карты его трогать
  // нельзя — стёрся бы весь прогресс.
  questsReset();
  const heroAssets = heroSetup(map.hero, map) ?? [];
  unitsSetup(map);
  lootSetup(map);
  exitsSetup(map);
  villageSetup(map);
  // Инвентарь заводится ДО боя: combatSetup раскладывает по слотам стартовое
  // снаряжение героя из GAME.0, и обнулять его после этого нельзя.
  inventorySetup();
  combatSetup();
  world.onPickup = (name) => {
    const куда = pickUp(name);
    statusNode.textContent = `Поднято: ${actorItemName(name)} (${куда})`;
    // пояс сам доезжает до свободной ячейки, как в игре
    beltFollow();
    refreshUi();
  };
  world.onTrade = () => { refreshUi(); render(); };
  world.onTalk = () => { refreshUi(); render(); };
  world.onDrop = (name, x, y, detail = null) => {
    const pile = lootDrop(name, x, y, heroCellAt(x, y), detail);
    if (!pile) return null;
    statusNode.textContent = `Брошено: ${actorItemName(name)}`;
    // Брошенное надо ещё и УВИДЕТЬ: куче нужна картинка вида на земле, а
    // не только иконка для мешка. Мешочек тоже: с двумя вещами на клетке
    // куча рисуется им.
    const item = actorItem(name);
    preload([item?.icon?.path, item?.ground?.path,
             world.map?.interface?.ground_pile?.path].filter(Boolean))
      .then(() => render());
    render();
    return pile;
  };
  world.units = units;
  world.onStatus = (text) => { statusNode.textContent = text; };
  // Поднятие уровня. Сигнал шлёт само ядро начисления (progress.js), и
  // только для стороны игрока — как 0x413110 играет фанфару (слот 14).
  //: Пока звуковых эффектов в клиенте нет, вместо фанфары статусная строка;
  //: звук встанет сюда же, когда эффекты приедут в пак.
  world.onLevelUp = (unit) => {
    statusNode.textContent = unit === hero
      ? `Герой получает уровень ${unit.level}`
      : `${unit.name} получает уровень ${unit.level}`;
    refreshUi();
  };
  // ПЕРЕНОС ПО ПРИКАЗУ РАЗГОВОРА — не то же самое, что выход в дверь.
  //
  // Действие 69 (VA 0x435AA0) берёт запись графа переходов и переносит отряд
  // по ней БЕЗУСЛОВНО: пишет заявку на загрузку и клетку входа. Карта
  // назначения при этом вполне может быть ТЕКУЩЕЙ — так, переход 18 ведёт с
  // карты 1 на карту 1, в клетку (29, 21): Повелитель отсылает Анастасию
  // через тронный зал ко входу.
  //
  // У выхода в дверь гейт «уже на этой карте» нужен — иначе стоящий в дверном
  // проёме входил бы в неё без конца. Приказу разговора он противопоказан:
  // с ним перенос молча пропадал, героиня оставалась у трона, Повелитель
  // заговаривал снова — а флаг 0 к тому мигу уже поднят, и разговор уходил в
  // ветку 2152, то есть в бой с боссом.
  world.onTransition = (door) => {
    if (!door) return false;
    if (door.to_map === -1 || door.to_map === -2) { world.onExit(door); return true; }
    // Приказ разговора ключа НЕ спрашивает: замок живёт только в двери
    // (0x420900), а 0x435AA0 просто пишет заявку `[0x8496D8] = -куда`.
    // Поэтому отрицательная карта здесь — это прямо карта |куда|.
    const цель = door.to_map < 0 ? -door.to_map : door.to_map;
    const path = mapPaths.get(Number(цель));
    if (!path) return false;
    statusNode.textContent = `Переход: ${mapNameOf(цель)}`;
    enterMap(цель, { row: door.entry_row, col: door.entry_col });
    return true;
  };
  // Выход с локации: -1 уводит на глобальную карту, остальное — в соседнюю
  // локацию по её номеру (пока в паке одна карта, поэтому только говорим).
  world.onExit = (door) => {
    if (door.to_map === -1) {
      // ВЫШЛИ НА ГЛОБАЛЬНУЮ. В движке это значит, что текущая карта стала
      // −1 (0x8496C8), и только с этого мига по карте можно идти и входить
      // в локации. До того она из панели лишь смотрится.
      //
      // И карта при этом ИСЧЕЗАЕТ: шаг на клетку выхода зовёт
      // FUN_0043A628(карта) и лишь потом ставит −1 (VA 0x420900). Пока порт
      // держал локацию живой, главный цикл продолжал её считать — и в бою
      // урон капал, пока отряд шёл по глобальной. Сворачиваем по-настоящему:
      // тогда отдельный гейт не нужен, unitsTick и render сами выходят по
      // пустой карте.
      //
      // ОТРАВУ НЕ ТРОГАЕМ: её вычитание идёт по всем отрядам без фильтра по
      // карте (VA 0x41C944), и в ходе по глобальной есть своя копия
      // (VA 0x4277F4). Терять здоровье в походе — канон.
      mapTeardown(currentMap);
      mapStateCapture(currentMap, units, loot);
      currentMap = null;
      // Бой держит ссылки на юнитов: цель, начатый замах и намеченную кучу.
      // Без сброса первый же кадр после возврата доводил бы удар по тому,
      // кого мы уже покинули.
      combat.target = null;
      combat.pendingHit = null;
      combat.pickup = null;
      worldMap.onMap = true;
      statusNode.textContent = "Вышли на глобальную карту";
      showWorldMap(true);
      return;
    }
    if (door.to_map === -2) {
      statusNode.textContent = "Особый переход";
      return;
    }
    // ЗАПЕРТАЯ ДВЕРЬ (VA 0x420900). Отрицательная карта, кроме −1 и −2, —
    // это дверь под ключ, и ведёт она на карту |куда|. Движок делает ровно
    // три вещи:
    //
    //     if (FUN_00434f8c(0x19) == 0) return;   // условие 17: класс 25 в мешке
    //     FUN_00433d38(0x19);                    // действие 45: забрать его
    //     ... переход на -куда ...
    //
    // Класс 0x19 = 25 — «Связка ключей», и он ЗАШИТ в самом движке, а не
    // лежит в записи выхода; поэтому и здесь стоит числом. Ключ тратится.
    //
    // Порт знал только −1 и −2, а дальше искал карту «−3» и писал, что её
    // нет в паке. Из-за этого Анастасия не могла выйти из Дворца Повелителя
    // даже со связкой: единственный выход карты 1 ведёт как раз в −3, то
    // есть на карту 3 «Застава Летающего острова».
    if (door.to_map < 0) {
      const КЛЮЧ = 25;
      if (!dialog.handlers?.[17]?.(КЛЮЧ)) {
        statusNode.textContent = "Заперто";
        return;
      }
      dialog.handlers?.[45]?.(КЛЮЧ);
      const цель = -door.to_map;
      statusNode.textContent = `Переход: ${mapNameOf(цель)}`;
      enterMap(цель, { row: door.entry_row, col: door.entry_col })
        .then((ok) => { if (ok) statusNode.textContent = mapNameOf(цель); });
      return;
    }
    if (door.to_map === currentMap) return;
    // Клетку прибытия называет сама запись выхода (+0x05 и +0x07).
    statusNode.textContent = `Переход: ${door.to_name}`;
    enterMap(door.to_map, { row: door.entry_row, col: door.entry_col })
      .then((ok) => {
        if (ok) statusNode.textContent = `${door.to_name}`;
      });
  };
  world.onAttackOrder = (unit) => { orderAt(unit.x, unit.y - 40); render(); };
  // Уход в локацию с глобальной карты: своей клетки прибытия у неё нет,
  // герой встаёт туда, где его ставит сама карта.
  world.onTravel = (location) => {
    showWorldMap(false);
    enterMap(location, arrivalCell(location)).then((ok) => {
      if (!ok) showWorldMap(true);
    });
  };
  // Интерфейс сам двигает кромки окна мира, поэтому после его раскладки
  // холст пересчитывается по новому размеру, а не только перерисовывается.
  uiSetup(() => refresh());
  heroAssets.push(...lootAssets());
  heroAssets.push(...projectileAssets());
  // Иконки предметов карты: их единицы, а нужны и на земле, и в панели.
  for (const item of Object.values(map.items ?? {})) {
    if (item.icon) heroAssets.push(item.icon.path);
  }
  heroAssets.push(...worldMapAssets(map));
  const нужныеЛисты = actorSheetPaths(map.hero, [hero, ...units]);
  await preload(mapAssets([...heroAssets, ...нужныеЛисты]));
  buildingsSetup();
  // Слои оружия и щитов догружаются фоном: кадр рисует то, что уже приехало.
  preload(heroEquipmentAssets());

  const waterAnimation = world.underlayVisual?.animation ?? null;
  const waterSource = waterAnimation ? world.images.get(waterAnimation.source) : null;
  if (waterSource) waterInit(waterAnimation, waterSource);
  audioSetup(map.audio);

  if (map.daylight) {
    try {
      const curves = await readJson(contentUrl(map.daylight));
      daylight.period = curves.period ?? 21600;
      daylight.curves.moon = curves.moon ?? [];
      daylight.curves.no_moon = curves.no_moon ?? [];
      clockTimeNode.max = String(daylight.period - 1);
      daylightSet(daylight.time);
    } catch (error) {
      console.warn("день/ночь недоступны:", error);
    }
  }

  // Продолжаем с сохранения: отряд, вещи, туман карты и флаги квестов
  // раскладываются по уже собранной карте. Делается это ПОСЛЕ всей
  // настройки, иначе расстановка юнитов затрёт восстановленное.
  if (saved) {
    applySave(saved);
    daylightSet(daylight.time);
    statusNode.textContent = "Продолжаем с сохранения";
  }

  titleNode.textContent = map.name;
  const stats = map.statistics ?? {};
  statsNode.innerHTML = `
    <div><dt>Земля</dt><dd>${(stats.ground_cells ?? 0).toLocaleString("ru-RU")}</dd></div>
    <div><dt>Слои</dt><dd>${(stats.terrain_overlays ?? 0).toLocaleString("ru-RU")}</dd></div>
    <div><dt>Постройки</dt><dd>${(stats.buildings ?? 0).toLocaleString("ru-RU")}</dd></div>
    <div><dt>Реквизит</dt><dd>${(stats.props ?? 0).toLocaleString("ru-RU")}</dd></div>
    <div><dt>Коллизии</dt><dd>${(stats.blocked_cells ?? 0).toLocaleString("ru-RU")}</dd></div>`;
  // Камера встаёт у героя в натуральную величину: игра рисуется один к
  // одному, и с высоты всей карты по спутнику не попасть мышью.
  view.zoom = 1;
  updateZoom();
  centreOnHero();
  soundMapEnter(map.audio, hero.data?.body ?? 0);
  sfxSetup({ hero });
  statusNode.textContent = world.missingAssets.size
    ? `Схема ${manifest.schema_version} · нет ресурсов: ${world.missingAssets.size}`
    : `Схема ${manifest.schema_version} · готово`;
  render();
  // Сетку глобальной карты заводим и на первом запуске, а не только при
  // переходе: без неё туман некуда копить и нечего сохранять.
  if (worldMapSetup() && worldMap.x === null) standAt(currentMap);
  // Первая карта грузится в обход enterMap, поэтому самосохранение здесь
  // своё: иначе у нового игрока сохранения не появлялось до первого
  // перехода между локациями.
  if (!saved) saveGame(currentMap);
}

new ResizeObserver(refresh).observe(canvas);
requestAnimationFrame(animationLoop);

window.knyaz2 = { useQuestItem, questItemUsable,
  world, view, water, waterRender, render, shadows,
  daylight, daylightSet, sunProgress, ambient, ambientTick,
  hero, heroTick, heroAnchor, heroUpdateBuilding, lightActive,
  heroCellKey, heroCellAt, heroPlayAction, heroDie,
  heroPlanPath, heroNeighbor, heroFree,
  heroEquip, heroUnequip, heroItem, heroWeapon, heroAttackPose,
  units, loot, combat, orderAt,
  worldMap, showWorldMap, standAt, revealAll,
  sound, soundStats, playEffect, playPositional, playMusic,
  playUnitVoice, playVoiceLine, positionVolume, positionPan, soundscapeTick,
  // РАЗГОВОРЫ ВЫНЕСЕНЫ НАРУЖУ. В `dialog` копятся два счётчика пробелов:
  // `pending` — действия, обработчика которых у нас нет (разговор идёт
  // дальше как ни в чём не бывало), и `missing` — условия, которые из-за
  // того же молча считаются истиной. Добраться до них было нельзя, и потому
  // пробелы вылезали только в игре: реплика показывается, а ничего не
  // происходит. Смотреть так: `knyaz2.dialog.pending`, `knyaz2.dialog.missing`.
  dialog, dialogJournal, dialogApproachTick, questsReset,
  canvas, showRoofsNode, ambientNode, clockRunNode };  // отладка
// Повторяемая проверка правил света и глубины: knyaz2.selfcheck().
window.knyaz2.selfcheck = createSelfCheck(window.knyaz2);

boot().catch((error) => {
  console.error(error);
  statusNode.textContent = "Ошибка загрузки";
  errorNode.hidden = false;
  errorNode.textContent = `${error.name}: ${error.message}`;
});
