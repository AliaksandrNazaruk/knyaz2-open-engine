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
import { agentSetup } from "./agent.js";
import { respawnSetup } from "./respawn.js";
import { contentUrl, preload, readJson,
         setContentVersion } from "./content.js";
// Счётчик такта НЕ сбрасывается при входе на карту: в движке
// `_DAT_0084962c` глобальный и монотонный, от него же считается время суток.
import { clock, clockAdvance } from "./clock.js";
import { creationOpen, creationOpened } from "./creation.js";
import { loadMap, loadShared, mapAssets, shared,
         world } from "./world.js";
import { actorItem, actorItemName, actorSheetPaths,
         creatureSheetPaths } from "./actor.js";
import { cameraFollow, resize, updateZoom, view } from "./viewport.js";
import { settingsLoad, timeScale } from "./settings.js";
import { fullscreenArm } from "./fullscreen.js";
import { gameMenuOpen, gameMenuShow, gameMenuToggle } from "./gamemenu.js";
import { loadScreenAwaitClick, loadScreenDone, loadScreenHide,
         loadScreenHolding, loadScreenShow } from "./loadscreen.js";
import { clockTick, daylight, daylightSet, sunProgress } from "./daylight.js";
import { lightActive } from "./light.js";
import { water, waterInit, waterRender, waterTick } from "./water.js";
import { ambient, ambientInit, ambientTick } from "./ambient.js";
import { centreOnHero, hero, heroAnchor, heroAttackPose, heroCellAt, heroCellKey, heroDie,
         heroEquip, heroEquipmentAssets, heroFree, heroItem, heroNeighbor, heroPlanPath,
         wavePeek,
         heroPlayAction, heroSetup,
         heroUnequip, heroUpdateBuilding, heroWeapon } from "./hero.js";
import { reputationStart } from "./reputation.js";
import { audioSetup } from "./audio.js";
import { probe, probeFrame, profiler } from "./profiler.js";
import { playEffect, playMusic, playPositional, playUnitVoice, playVoiceLine,
         positionPan, positionVolume, sound, soundBindCell, soundInit,
         soundMapEnter, soundStats, soundTick } from "./sound.js";
import { sfxSetup } from "./sfx.js";
import { soundscapeTick } from "./soundscape.js";
import { shadows } from "./shadows.js";
import { render } from "./scene.js";
import { edgeScrollTick } from "./input.js";
import { lootAssets, lootDrop, lootPut, lootSetup, loot } from "./loot.js";
import { furnitureAssets, furnitureSetup } from "./furniture.js";
import { projectileAssets } from "./projectiles.js";
import { weatherAssets } from "./weather.js";
import { inventorySetup, pickUp } from "./inventory.js";
import { beltFollow, panelUnit, refresh as refreshUi, showWorldMap, uiEscape,
         uiSetup } from "./ui.js";
import { unitSpawn } from "./units.js";
import { warbandJoin, warbandsReset } from "./warband.js";
import { exitsSetup, exitsTick } from "./exits.js";
import { partyCapture, partyRegroup, unitsSetup, unitsTick, units } from "./units.js";
import { combat, combatDropTargets, combatSetup, combatTick,
         orderAt } from "./combat.js";
import { dialog, dialogApproachTick, dialogJournal,
         questEditsReplay, questsReset } from "./dialog.js";
import { effectsTick, effectsTravelStep } from "./effects.js";
import { buildingsSetup } from "./buildings.js";
import { shopsRestock } from "./shops.js";
import { createSelfCheck } from "./selfcheck.js";
import { formationCells, knownReset, locationName, markerVisible,
         openLocation,
         revealAll, standAt,
         stopTravel, travelTick, travelling, worldMap,
         worldMapSetup } from "./worldmap.js";
import { applySave, saveGame, savedGame } from "./save.js";
import { questItemUsable, useQuestItem } from "./questitems.js";
import { editorAutostart, editorCloneProp, editorCloneUnit, editorCompileQuests, editorBestiary, editorCloneOverlay, editorNewMap, editorNewPile, editorSave, editorTilesToggle, editorToggle, editorWaterToggle } from "./editor.js";
import { villageCapture, villageReset, villageSetup, villageTick,
         villageUnpack } from "./village.js";
import { mapStateCapture, mapStateUnpack } from "./mapstate.js";

import "./input.js";

// ЗАМЕРЫ ЗАГРУЗКИ ЧЕСТНЫМИ. Браузер держит в `performance` последние 250
// записей о ресурсах и молча выбрасывает остальные, а вход на карту стоит
// шестисот с лишним файлов. Пока буфер стоял по умолчанию, любой подсчёт
// трафика показывал вес первых двухсот пятидесяти и выглядел вдвое меньше
// настоящего. Ставим до первой загрузки — задним числом записи не вернуть.
performance.setResourceTimingBufferSize?.(5000);

//: Настройки игрока из меню — до первого кадра, чтобы камера уже знала,
//: держать ли выбранного в середине окна. Ставим её здесь, а не в самом
//: модуле настроек: он намеренно ничего не знает про холст, иначе выходила
//: петля settings -> viewport -> daylight.
view.follow = settingsLoad().follow;
//: Полный экран просится на ПЕРВОЕ КАСАНИЕ: без жеста игрока браузер его не
//: даёт. Взводим сразу — жест придёт когда придёт.
fullscreenArm();

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
//
// ПАВШИЙ СПУТНИК — ТАКОЙ ЖЕ УБИТЫЙ. Обе ветки 0x43A628 вычёркивают мёртвых
// ИЗ ОТРЯДА ИГРОКА безусловно (в ветке обычных карт условие «номер диалога
// > 7 ИЛИ отряд игрока», :34-36), и добро его сыплется той же кучей. Здесь
// стояло `|| unit.ally`, и павший спутник уносил вещи с собой — а запись
// отряда, которую partyCapture «не трогал», поднимала его на следующей
// карте живым и с полным здоровьем. Вычёркивание из отряда — partyCapture.
function mapTeardown(number) {
  if (!mapKeepsSpoils(number)) return 0;
  let dropped = 0;
  for (const unit of units) {
    if (unit.alive !== false || !unit.cell) continue;
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

// ОШИБКА В ТИКЕ НЕ ДОЛЖНА УБИВАТЬ ИГРУ. Кадр заказывался последней строкой
// цикла, поэтому любое исключение по дороге обрывало цепочку rAF навсегда:
// картинка застывала, часы вставали, никто не шевелился — со стороны это
// «игра зависла», и найти причину игрок не мог. Так и случилось с обучением
// у воеводы. Заказ следующего кадра вынесен в `finally`, а само исключение
// печатается ОДИН раз на своём месте: молча глотать его нельзя.
let loopFault = "";

function animationLoop(now) {
  try {
    animationFrame(now);
  } catch (error) {
    const mark = String(error?.stack ?? error);
    if (mark !== loopFault) {
      loopFault = mark;
      console.error("сбой в тике игры (кадр пропущен, игра продолжается):", error);
    }
  } finally {
    requestAnimationFrame(animationLoop);
  }
}

function animationFrame(now) {
  const seconds = now / 1000;
  const dt = lastFrameTime ? Math.min(0.1, seconds - lastFrameTime) : 0;
  lastFrameTime = seconds;
  // Мировой такт движка двигается РОВНО ЗДЕСЬ и больше нигде — как
  // `_DAT_0084962c` в начале главного цикла (VA 0x438A00). Всё периодическое
  // фазируется от него, а не от кадров браузера.
  // ПОКА МЕНЮ ОТКРЫТО, ИГРА СТОИТ. Счётчик такта не двигаем вовсе: от него
  // фазируется всё периодическое, и накопленный за паузу долг прокрутился бы
  // разом — отрава, стройка и сутки скакнули бы вперёд. Возврат безопасен:
  // `clockAdvance` видит разрыв больше секунды и просто подводит своё время
  // к текущему, ничего не начисляя (clock.js).
  if (gameMenuOpen() || loadScreenHolding()) {
    lastFrameTime = seconds;
    return;
  }
  //: ТЕМП БЕРЁМ КАЖДЫЙ КАДР, а не однажды на запуске: игровое меню — накладка
  //: поверх идущей игры, и, закрываясь, оно перечитывает настройки
  //: (gamemenu.js). Так ползунок скорости действует сразу, без перезахода.
  clock.scale = timeScale();
  clockAdvance(seconds);
  probeFrame();
  let dirty = false;
  if (probe("вода", () => waterTick(now))) { probe("вода", waterRender); dirty = true; }
  // догрузка звуков карты — по одному за такт мира
  probe("звук", () => soundTick(now));
  // амбиент, музыка карты и приветствия спутников
  probe("звук", () => soundscapeTick(now));
  if (probe("часы", () => clockTick(now))) dirty = true;
  if (probe("амбиент", () => ambientTick(now))) dirty = true;
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
    // Отдельного тика героя больше нет: он первый юнит общего цикла
    // (units.js идёт по roster), как первая запись отряда №0 в 0x413894.
    probe("очередь", requeueByDistance);
    if (probe("юниты", () => unitsTick(now, dt))) dirty = true;
    // Сюжетная встреча: NPC с взведённым битом «подойди и заговори» сам
    // ловит игрока рядом и переводит его в приказ 0x22 (VA 0x410684).
    if (probe("подход", dialogApproachTick)) dirty = true;
    if (probe("бой", () => combatTick(dt))) dirty = true;
    // Камера за выбранным лицом, если игрок её попросил (settings.js). Идёт
    // ПОСЛЕ шагов: место юнита уже свежее, и камера не отстаёт на кадр. Панель
    // и камера смотрят на одного и того же — `panelUnit` — поэтому щелчок по
    // портрету сам переносит взгляд, отдельного обработчика не нужно.
    if (probe("камера", () => cameraFollow(panelUnit()))) dirty = true;
  }
  // ОТРАВА ИДЁТ И В ПОХОДЕ. Её вычитание в мировом такте не отфильтровано по
  // карте (VA 0x41C944), а у хода по глобальной есть ещё своя копия того же
  // вычитания (VA 0x4277F4). Терять здоровье в пути — канон.
  if (probe("отрава и зелья", effectsTick)) dirty = true;
  // хозяйство деревни: казна владения и мастерская (VA 0x41D530, 0x417BD8)
  if (probe("деревня", villageTick)) dirty = true;
  if (probe("мир", () => worldTick(now))) probe("интерфейс", refreshUi);
  probe("выходы", exitsTick);
  //: Заказ от мыши и колеса (view.dirty) — такой же повод нарисовать, как
  //: и сдвинувшийся мир. Раньше они рисовали сами, прямо из обработчика.
  if (dirty || view.dirty) {
    view.dirty = false;
    probe("рисование", render);
  }
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
// ОДНА ДВЕРЬ В МЕНЮ — и для клавиши, и для герба на панели. С телефона
// клавиши нет вовсе, поэтому кнопка там не роскошь, а единственный выход.
function leaveToMenu() {
  if (Number.isFinite(currentMap)) saveGame(currentMap);
  location.href = "/menu.html";
}
world.leaveToMenu = leaveToMenu;

//: Герб на панели и клавиша Esc делают одно и то же — поднимают накладку.
world.openMenu = () => { gameMenuShow(true); render(); };
//: Обратно в игру: раскладка панели и пояса пересчитывается (`refreshUi`),
//: следом холст и кадр. Просто `refresh` тут мало — он трогает только холст.
world.onMenuClose = () => { refreshUi(); refresh(); };

//: «Сохранить игру» из накладки — тем же путём, что и самосохранение входа.
//: ОТВЕТ `saveGame` ВОЗВРАЩАЕМ, а не выбрасываем. Здесь стояло `saveGame(...)`
//: без проверки и `return true` — меню рапортовало об успехе даже тогда,
//: когда записать не вышло, и игрок уходил уверенный, что сохранился.
world.onMenuSave = () => {
  if (!Number.isFinite(currentMap)) return false;
  return saveGame(currentMap);
};

//: Беда с записью — сразу в строку состояния, молчать о ней нельзя.
world.onSaveTrouble = (text) => {
  console.error("сохранение:", text);
  world.onStatus?.(`СОХРАНЕНИЕ: ${text}`);
};

window.addEventListener("keydown", (event) => {
  if (event.code !== "Escape" || event.repeat) return;
  event.preventDefault();
  // Экран создания героя ESC не закрывает: из него выходят кнопкой «Играть»,
  // как в движке — там это отдельное состояние экрана.
  if (creationOpened()) return;
  // Сперва то же, что делает движок: отменить перенос вещи и закрыть
  // открытый экран. Пока что-то открыто, ESC из игры не выкидывает.
  if (uiEscape()) { render(); return; }
  // МЕНЮ ОТКРЫВАЕТСЯ ПОВЕРХ ИГРЫ, А НЕ УВОДИТ СТРАНИЦУ. Уход означал бы
  // полную перезагрузку: заново общий блок пака, описание карты и сотни
  // картинок, которые вот только что лежали разобранными в памяти.
  gameMenuToggle();
  render();
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
  // ПОХОД ИДЁТ ТОЛЬКО НА ГЛОБАЛЬНОЙ КАРТЕ. Здесь стояли лишь два условия —
  // «идём ли» и «не грузится ли карта», — а спросить, где мы, забыли. Из-за
  // этого отряд, ушедший в локацию посреди маршрута, продолжал шагать по
  // глобальной: встречи срабатывали, точки сменялись, и на выходе из поля
  // игрока выкидывало в следующую точку маршрута без всякого подтверждения.
  //
  // В движке такого случиться не может по построению: ход по глобальной
  // считает своё состояние главного цикла (`0x8495F0`), а вход в локацию из
  // него выходит — тика просто нет. Наш `worldMap.onMap` — то же самое
  // состояние: `enterMapInner` гасит его, выход на глобальную поднимает.
  if (!travelling() || entering || !worldMap.onMap) return false;
  let moved = false;
  for (let tick = 0; tick < clock.elapsed; tick += 1) {
    // ТЕЛО ГЕРОЯ — ЭТО `hero.body`, а не поле карты. Класс опасности встречи
    // движок берёт байтом `местность + 2 + игрок[+0xFC]` (VA 0x4360A8), а
    // +0xFC — облик героя, у нас `hero.body` (progress.js ставит его из
    // шаблона старта, save.js возит в сейве). Здесь стояло `hero.data.body`
    // — такого поля у блока карты нет вовсе, и жребий всегда брал строку 0:
    // за кого ни играй, на глобальной попадались одни и те же отряды.
    const step = travelTick({ body: hero.body ?? 0,
                              pathfinder: heroPathfinder() });
    moved = true;
    // ОТРАВА В ПОХОДЕ ИДЁТ ПОШАГОВО (VA 0x4277F4): круг по отряду стоит
    // ВНУТРИ ветки «маска пустила», сразу после переноса отряда в новую
    // точку, и потому случается на каждый принятый шаг, а не раз в
    // шестнадцать тактов. Отказ маски (`blocked`) шага не даёт — там движок
    // обрывает поход и возвращает отряд, до круга дело не доходит.
    if (step && step.kind !== "blocked") effectsTravelStep();
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
  const number = cell & 0xFF;
  //: Имя решает `locationName` — одна на всех: подпись карты, наведение и
  //: приход. Неизвестное место называется «Неизвестное место», как в движке.
  if (number && markerVisible(cell)) return locationName(number);
  return `Клетка ${row}:${col}`;
}

// Встреча в пути: движок показывает заставку и уводит бой на отдельную
// карту-местность, а туда переносит скопированный отряд (VA 0x4277F4).
async function meetEnemy(met) {
  statusNode.textContent = "Засада!";
  showWorldMap(false);
  const ok = await enterMap(met.scene, arrivalCell(met.scene));
  if (!ok) { showWorldMap(true); return; }
  // МОРСКАЯ ВСТРЕЧА ПЕРЕВЫПИСЫВАЕТ КОРАБЕЛЬНОЕ ПРАВО: и стычка в плавании
  // (0x422CCC: 0x84960C = карта встречи), и жребий, обёрнутый в «Бой на
  // корабле» (0x4360A8: сцена 26 -> 27 и 0x84960C = 27), оставляют выход
  // −2 карты боя живым — иначе с палубы не уплыть.
  const seaScenes = new Set([worldMap.rules?.scenes?.sea ?? 26,
                             worldMap.rules?.scenes?.sea_battle ?? 27]);
  if (worldMap.ship === -1 || seaScenes.has(met.scene)) worldMap.ship = met.scene;
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

// ОЧЕРЕДЬ ПОДГРУЗКИ С ПРИОРИТЕТОМ ПО БЛИЗОСТИ.
//
// Заявки приходят из двух мест: из `spriteReady`, когда кадру не хватило
// картинки (вес нулевой — это нужно немедленно), и из разбора карты по
// радиусу, где весом служит квадрат расстояния до героя.
//
// Тянем помалу и по порядку, а не залпом: залп забивает канал дальними
// домами, пока ближний юнит ещё не приехал. Шесть штук разом — столько же
// соединений браузер и так держит на один адрес.
const requested = new Set();
let queue = [];
let inFlight = 0;

// СКОЛЬКО ТЯНЕМ РАЗОМ — ПО ПРОТОКОЛУ. На HTTP/1.1 браузер и сам не откроет
// больше шести соединений на хост, и просить больше бессмысленно. Боевой
// сервер отдаёт по h2/h3, где запросы мультиплексируются в одном соединении:
// там шестёрка была нашим собственным тормозом. Протокол берём у первого же
// доехавшего ресурса — к моменту первой заявки их уже десятки.
//: Считается ОДИН раз: `качать()` зовётся после каждого доехавшего файла, а
//: список ресурсов к тому времени в тысячу записей — перебирать его на каждый
//: файл значило бы отдать загрузке больше времени, чем она экономит.
let slotsCached = 0;

function slotLimit() {
  if (slotsCached) return slotsCached;
  const protocol = performance.getEntriesByType("resource")
    .find((e) => e.nextHopProtocol)?.nextHopProtocol ?? "";
  if (!protocol) return 6;                    // ещё нечего спрашивать
  slotsCached = multiplexed(protocol) ? 12 : 6;
  return slotsCached;
}

function multiplexed(protocol) {
  return protocol === "h2" || protocol === "h3" || protocol.startsWith("h3-");
}

// ПЕРЕРИСОВКА СКЛЕИВАЕТСЯ. Раньше `render()` звался на каждый доехавший файл.
// Пока в очередь шли десятки листов, это сходило с рук; но в неё теперь
// попадают и сотни иконок, а ночной кадр стоит около 33 мс — вышло бы больше
// времени на рисование, чем на саму загрузку. Кадр всё равно один на экран,
// поэтому копим отметку и рисуем раз за кадр браузера.
// А ТЕПЕРЬ И ВОВСЕ НЕ РИСУЕМ САМИ. Склейка по кадру браузера убрала лишние
// вызовы, но оставила ВТОРОЙ путь отрисовки — свой requestAnimationFrame
// рядом с кадровым циклом, и в замере под троттлингом он стоил 175 вызовов
// по 108 мс, то есть девятнадцать секунд из ста двадцати. Кадровый цикл и
// так рисует всё, что помечено грязным, поэтому доехавшему файлу довольно
// поднять отметку: он попадёт на экран тем же кадром, не заводя своего.
function redrawSoon() {
  view.dirty = true;
}

function pump() {
  const limit = slotLimit();
  while (inFlight < limit && queue.length) {
    queue.sort((a, b) => a.weight - b.weight);
    const { path } = queue.shift();
    inFlight += 1;
    preload([path]).finally(() => {
      inFlight -= 1;
      redrawSoon();
      pump();
    });
  }
}

world.requestAsset = (path, weight = 0, origin = null) => {
  if (!path || requested.has(path)) return;
  requested.add(path);
  queue.push({ path, weight, origin });
  pump();
};

// ГЕРОЙ ПОШЁЛ — ВЕСА УСТАРЕЛИ. Расстояния считались один раз, на входе; пока
// игрок идёт через карту, дальний лист продолжает ехать впереди того, к кому
// герой уже подошёл. Пересчитываем ОЖИДАЮЩИЕ заявки — их десятки, это дешевле
// одного кадра, и делать это чаще, чем герой прошёл полокна, незачем.
//
// У заявки помнится её источник — актёр, из-за которого лист понадобился.
// Один лист может обслуживать нескольких, тогда остаётся первый: очередь
// решает лишь порядок, и ошибка здесь стоит одного места в ней.
let reweighedAt = null;

function requeueByDistance() {
  if (!queue.length) return;
  const threshold = view.width / (2 * (view.zoom || 1));
  if (reweighedAt) {
    const dx = hero.x - reweighedAt.x, dy = hero.y - reweighedAt.y;
    if (dx * dx + dy * dy < threshold * threshold) return;
  }
  reweighedAt = { x: hero.x, y: hero.y };
  for (const request of queue) {
    if (request.origin) request.weight = actorWeight(request.origin);
  }
}

//: Новая карта — новая очередь: прежние дальние заявки больше не нужны.
//: Уже загруженное помним, иначе `spriteReady` закажет то же самое второй раз.
function queueReset() {
  queue = [];
  requested.clear();
  for (const path of world.images.keys()) requested.add(path);
  reweighedAt = null;
}

// АКТЁРЫ ПО БЛИЗОСТИ — как видеокарта с текстурами: сперва те, кто в кадре,
// остальные по мере удаления от героя.
//
// Раньше вход ЖДАЛ листы ВСЕХ юнитов: на Морском лагере это двадцать бойцов,
// из которых в первом кадре видны двое-трое.
function actorInFrame(actor, box) {
  if (!actor) return false;
  const x = actor.x ?? 0, y = actor.y ?? 0;
  return x >= box.left && x <= box.right && y >= box.top && y <= box.bottom;
}

// РАМКА СЧИТАЕТСЯ ОТ ГЕРОЯ, А НЕ ОТ КАМЕРЫ.
//
// Через камеру это уже подводило: на входе она ещё стоит в нуле, кламп
// прижимает её к левому верхнему углу карты, и «близким» оказывался угол —
// игрок смотрел в черноту, пока грузилось не то. Герой к этому мигу уже
// расставлен, поэтому берём его место и те же полразмера окна.
function frameAroundHero() {
  const halfWidth = view.width / (2 * (view.zoom || 1)) + 256;
  const halfHeight = view.height / (2 * (view.zoom || 1)) + 256;
  const x = hero.x ?? 0, y = hero.y ?? 0;
  return { left: x - halfWidth, right: x + halfWidth,
           top: y - halfHeight, bottom: y + halfHeight };
}

function actorsByProximity() {
  const box = frameAroundHero();
  const own = [hero, ...units];
  const distanceTo = (actor) => {
    const dx = (actor.x ?? 0) - (hero.x ?? 0);
    const dy = (actor.y ?? 0) - (hero.y ?? 0);
    return dx * dx + dy * dy;
  };
  return {
    inFrame: own.filter((actor) => actorInFrame(actor, box)),
    rest: own.filter((actor) => !actorInFrame(actor, box))
      .sort((a, b) => distanceTo(a) - distanceTo(b)),
  };
}

//: Вес заявки — квадрат расстояния до героя в мировых единицах. Одна шкала на
//: всю очередь: `spriteReady` просит нулём (нужно прямо сейчас), актёры — своим
//: расстоянием, иконки — заведомо большим числом.
function actorWeight(actor) {
  const dx = (actor.x ?? 0) - (hero.x ?? 0);
  const dy = (actor.y ?? 0) - (hero.y ?? 0);
  return dx * dx + dy * dy;
}

//: Дальше любого расстояния на карте: сторона мира меньше 65536, квадрат —
//: меньше 2^32, так что эта отметка всегда в хвосте очереди.
const LAST_OF_ALL = 2 ** 34;

// ИКОНКИ ПРЕДМЕТОВ — В ХВОСТ, А НЕ В ЖДУЩУЮ ПАЧКУ.
//
// Раньше они собирались в `heroAssets` с пометкой «их единицы»: на Морском
// лагере их 225 на 1.47 МБ, и первый кадр ждал их все. Между тем на карте они
// не рисуются вовсе — панель заводит свой `Image`, курсор подставляет путь в
// CSS, а куча на земле берёт `item.ground`. Нужны они, только когда игрок
// откроет сумку, поэтому едут последними и никого не держат.
function queueItemIcons(map) {
  for (const item of Object.values(map.items ?? {})) {
    if (item.icon) world.requestAsset?.(item.icon.path, LAST_OF_ALL);
  }
}

// Выбросить листы, которых на новой карте нет ни у кого. Возвращает, сколько
// картинок отпущено.
function forgetForeignSheets(data, actors) {
  if (!data?.sheets?.length) return 0;
  const keep = new Set(actorSheetPaths(data, actors));
  let dropped = 0;
  for (const path of [...world.images.keys()]) {
    if (!path.includes("/units/") || keep.has(path)) continue;
    world.images.delete(path);
    dropped += 1;
  }
  return dropped;
}

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
      // Спутники — в запись отряда: она у нас единственная долгая память о
      // них, и без этого переход возвращал им здоровье и опыт дня найма.
      partyCapture();
    }
    // Хозяйство деревни — в свой склад: запись поселения в движке живёт
    // отдельно от карты и уход с неё переживает (0x83D408 читается один раз
    // при новой игре или из сейва, 0x43DF48 её только читает).
    //
    //: ВНЕ гейта по текущей карте: приходя с глобальной, мы карту уже
    //: покинули (`currentMap = null`), а поселение всё это время тикало —
    //: его наработку тоже надо сложить в склад, иначе вход в следующую
    //: локацию заменит `village` целиком и она пропадёт. Сама функция
    //: молчит, когда складывать нечего.
    villageCapture();
    // ЭКРАН ЗАГРУЗКИ ИДЁТ ПЕРВЫМ И ДОЖИДАЕТСЯ ОТРИСОВКИ. Иначе он встанет в
    // очередь за шестью сотнями файлов локации и приедет, когда уже не нужен.
    // Картинка общая на все переходы, так что платим за неё раз за сеанс.
    await loadScreenShow();
    return await enterMapInner(number, path, entry);
  } finally {
    entering = false;
    // ЖДЁМ ЩЕЛЧКА. Локация готова, но сцена не начинается, пока игрок не
    // нажмёт: иначе стычка стартует раньше, чем он разглядел, куда попал.
    // Мир при этом стоит — такт заперт `loadScreenHolding` в кадре ниже.
    // Начальная загрузка идёт другим путём и щелчка не просит: он там уже
    // был, в меню.
    loadScreenAwaitClick();
  }
}

async function enterMapInner(number, path, entry) {
  const map = await readJson(contentUrl(path));
  // Вошли в локацию — отряд больше не на глобальной: в движке текущая
  // карта перестаёт быть −1, и щелчки по карте снова ничего не делают.
  worldMap.onMap = false;
  // И САМ МАРШРУТ БРОСАЕМ. Вход в локацию — это выход из состояния похода, а
  // не пауза в нём: движок в локации глобальную карту не считает вовсе.
  // Оставленный маршрут иначе оживал бы при возвращении и уводил отряд
  // дальше, хотя игрок уже передумал и зашёл сюда по своим делам.
  stopTravel();
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
  furnitureSetup(map);
  exitsSetup(map);
  villageSetup(map);
  // Токены-команды квестов: вход на карту переигрывает ВСЕ взведённые
  // (движок — цикл по тремстам записям в загрузчике, донорский 0x4417E0),
  // и правка ложится на свежепрочитанную из пака карту.
  questEditsReplay(map?.legacy?.map_number);
  // Герой встаёт на клетку прибытия — её называет сама запись выхода.
  if (entry) {
    const anchor = heroAnchor(entry.row, entry.col);
    hero.cell = { row: entry.row, col: entry.col };
    hero.x = anchor.x;
    hero.y = anchor.y;
    hero.path = [];
    hero.step = null;
    // НАПРАВЛЕНИЕ ПРИХОДА НАЗЫВАЕТ САМА ЗАПИСЬ. Переход кладёт его отряду
    // (`отряд[+0x18] = запись[+2]`, VA 0x420900:56), а расстановка переписывает
    // отряду ЖЕ вожаку (`юнит[+0x18] = отряд[+0x18]`, VA 0x415238:61) и от него
    // отсчитывает кольцо. Без этого герой выходил из двери, глядя туда же, куда
    // шёл на прошлой карте, и отряд вставал не с той стороны.
    if (entry.facing != null) hero.direction = entry.facing;
    heroUpdateBuilding();
  }
  // ПРИБЫТИЕ В КАМЕНЬ. Записи прибытия нет у двадцати четырёх карт из
  // пятидесяти двух, и без неё герой остаётся на координатах ПРОШЛОЙ карты
  // (гейт `if (entry)` выше). Если там оказалась глухая клетка, он не
  // сдвинется никуда: волна не находит ни одного соседа, щелчки молчат, и
  // карта просто не играется — так вход `?map=19` ставил героя в скалу.
  // Ставим на ближайшую свободную, расходясь кольцами.
  //
  // ГЕРОЙ САМ СЕБЕ НЕ ПРЕПЯТСТВИЕ. Проверка звалась без него самого
  // (`heroFree(r, c)` вместо `heroFree(r, c, hero)`), а игрок в движке
  // держит клетку наравне со всеми (units.js unitBlocks) — и клетка,
  // куда его только что поставили строкой выше, всегда выходила занятой.
  // То есть объезд включался НА КАЖДОМ входе на карту и уводил героя на
  // первого соседа кольца, то есть ровно на клетку вверх-влево: и после
  // двери, и по «играть отсюда». Замер: просили 49:30 — вставал 48:29,
  // просили 41:36 — вставал 40:35, оба раза ровно (−1,−1).
  if (!heroFree(hero.cell.row, hero.cell.col, hero)) {
    let spot = null;
    for (let ring = 1; ring <= 12 && !spot; ring += 1) {
      for (let dr = -ring; dr <= ring && !spot; dr += 1) {
        for (let dc = -ring; dc <= ring && !spot; dc += 1) {
          if (Math.max(Math.abs(dr), Math.abs(dc)) !== ring) continue;
          const row = hero.cell.row + dr, col = hero.cell.col + dc;
          if (heroFree(row, col, hero)) spot = { row, col };
        }
      }
    }
    if (spot) {
      const anchor = heroAnchor(spot.row, spot.col);
      hero.cell = spot;
      hero.x = anchor.x;
      hero.y = anchor.y;
      hero.path = [];
      hero.step = null;
      heroUpdateBuilding();
    }
  }

  // ОТРЯД ВСТАЁТ ВОКРУГ ВОЖАКА ВСЕГДА, а не только по переходу. В движке это
  // последняя строка загрузчика карты, и стоит она без условий:
  //
  //     FUN_00415238(отряд_игрока, текущая_карта, 1)     // VA 0x43DF48:294
  //
  // Гейт `if (entry)` стоил отряда на всех картах БЕЗ записи в таблице
  // прибытия (0x460028): их в паке двадцать четыре из пятидесяти двух, и на
  // них спутники оставались там, где их поставил spawnCompanion, — у клетки,
  // которую герой занимал на ПРОШЛОЙ карте. Среди этих двадцати четырёх и
  // карта 17 «Волхв у Борье», то есть ровно тот путь, на котором тестер и
  // увидел «отряд не выходит, уходит только герой».
  //
  // Порядок важен: сперва герой на своей клетке, потом отряд вокруг него.
  // partyRegroup гасит и приказы — вожаку тоже, иначе он с порога убегает к
  // цели прошлой карты (см. там же).
  partyRegroup();
  combatDropTargets();
  // ЖДЁМ ТОЛЬКО РАДИУС ВОКРУГ ГЕРОЯ: землю и постройки в кадре плюс тех, кто
  // в нём стоит. Всё дальнее уходит в очередь по удалению и приезжает, пока
  // игрок осматривается.
  // КАМЕРА НА ГЕРОЯ — ДО расчёта радиуса, иначе рамка считается вокруг нуля,
  // а герой стоит посреди карты: «близким» оказывался её угол, а всё нужное
  // уезжало в хвост очереди. Зум ставим тут же — от него зависит, сколько
  // мира попадает в кадр.
  // ЧУЖИЕ ЛИСТЫ ВЫБРАСЫВАЕМ. Лист актёра — 4095x1700, в распакованном виде
  // около 26 МБ; на Морском лагере их два десятка, то есть под треть гигабайта
  // битмапов. Между картами `world.images` не чистился вовсе, и телефон убивал
  // вкладку раньше, чем кончался трафик.
  //
  // Выбрасывать безопасно: набор листов актёра НЕ зависит от позы (замер на
  // карте 23 — `stand` из 16 записей требует те же 24 листа, что и все позы
  // вместе), поэтому `actorSheetPaths` для актёров новой карты и есть полный
  // список нужного. Всё, что сверх него, осталось от прежней карты.
  forgetForeignSheets(map.hero, [hero, ...units]);
  view.zoom = 1;
  updateZoom();
  centreOnHero();
  queueReset();
  const near = actorsByProximity();
  // mapAssets ОБЯЗАТЕЛЕН: он подаёт землю, подложку, круги выбора и дымку.
  // Убрав его ради радиуса, я оставил карту без земли — радиус теперь лишь
  // ПОДСКАЗКА для очереди, а не замена списку обязательного.
  // Спрайты куч — в ту же предзагрузку: lootSetup уже отработал, список
  // от НОВОЙ карты. Вход переходом их раньше не грузил вовсе, и одиночные
  // напольные кучи (топор в Беглом) не рисовались до загрузки сейвом.
  // ЖДЁМ ВСЕХ, КТО НА КАРТЕ, А НЕ ТОЛЬКО ТЕХ, КТО В КАДРЕ.
  //
  // Ждали только `near.inFrame`, остальные ехали фоном — и после перехода
  // игрок видел, как жители и твари проявляются из пустоты уже на готовой
  // сцене. Теперь экран держится, пока не готовы тела всех юнитов карты и
  // листы её пород.
  //
  // Скопом листы тварей по-прежнему не тянем: их 83 на 43.4 МБ. Берём ровно
  // те наборы, что нужны стоящим тут породам, — `creatureSheetPaths`.
  const all = [...near.inFrame, ...near.rest];
  await preload(mapAssets([...assets, ...furnitureAssets(map),
                           ...lootAssets(),
                           ...actorSheetPaths(map.hero, all),
                           //: герой тоже может ходить набором твари (customHeroSetup),
                           //: и тогда его лист нужен до первого кадра
                           ...projectileAssets(),
                           ...weatherAssets(),
                           ...creatureSheetPaths([hero, ...all])]));
  queueItemIcons(map);
  buildingsSetup();
  // ЛАВКИ НАБИВАЮТСЯ ПРИ КАЖДОМ ВХОДЕ. В движке это последняя строка
  // загрузчика карты: FUN_0043DF48 зовёт генератор FUN_0041896C уже после
  // расстановки построек. Без этого вызова прилавки стояли пустыми всегда —
  // в самих GAME.N они и есть пустые.
  shopsRestock();
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
  return place ? { row: place.row, col: place.col, facing: place.facing } : null;
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

//: FNV-1a по хешам файлов манифеста. Не криптография: нужно лишь, чтобы
//: строка менялась при любой правке пака и не менялась без неё.
function packVersion(manifest) {
  let h = 0x811c9dc5;
  for (const record of manifest.files ?? []) {
    for (const text of [record.path ?? "", record.sha256 ?? ""]) {
      for (let i = 0; i < text.length; i += 1) {
        h ^= text.charCodeAt(i);
        h = Math.imul(h, 0x01000193) >>> 0;
      }
    }
  }
  return `${manifest.content_id ?? "pack"}-${h.toString(36)}`;
}

async function boot() {
  refresh();
  const manifest = await readJson("/content/manifest.json");
  // ВЕРСИЯ ПАКА — СВЁРТКА ЕГО СОДЕРЖИМОГО, А НЕ ИМЯ И СЧЁТ ФАЙЛОВ.
  //
  // Версия подставляется в адрес каждого ресурса (`?v=`), и на ней держится
  // весь кеш. Прежняя пара «content_id + число файлов» этого не выдерживает:
  // `content_id` от сборки к сборке один и тот же, а перепечь карту или лист,
  // не меняя их числа, — обычное дело. Тогда адрес остаётся прежним, и браузер
  // вправе отдать старое. Пока сервер слал `no-cache`, спасала перепроверка;
  // с `immutable` на `/content/` она пропадает, поэтому версия обязана меняться
  // от ЛЮБОЙ правки. Свёртка идёт по sha256 всех файлов — они и так в манифесте.
  setContentVersion(packVersion(manifest));
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
  // Через `contentUrl`, а не голым путём: без версии в адресе этот файл на
  // 2.4 МБ не удержать в кеше — правка пака его бы уже не сменила.
  loadShared(await readJson(contentUrl("shared.json")));
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
    let ordered = null;
    try {
      const text = localStorage.getItem("knyaz2.newgame");
      localStorage.removeItem("knyaz2.newgame");
      ordered = text ? JSON.parse(text) : null;
    } catch { ordered = null; }
    if (ordered) return ordered;
    //: ПРОБА КАРТЫ ИЗ РЕДАКТОРА — С ЧИСТОГО ЛИСТА (?fresh=1).
    //:
    //: Сохранение помнит карту СИЛЬНЕЕ ПАКА: убитые, подобранное и сами
    //: жители переживают уход (mapstate.js — для игры это верно). Автору
    //: карты это ставит ловушку: он правит юнита, пересобирает пак, жмёт
    //: «Play» — а игра продолжает прошлый заход и поднимает жителя ИЗ
    //: ПАМЯТИ, со старыми числами. Живая проверка на «Малом Бору»:
    //: ослабленный до 2-го уровня скелет выходил одиннадцатым, пока сейв
    //: не стёрли, а «мирный» житель дрался — потому что подрался в
    //: прошлой сессии. В самом паке при этом всё было правильно.
    try {
      const адрес = new URLSearchParams(location.search);
      if (адрес.get("fresh") === "1") return { create: false };
    } catch { /* адрес не разобрался — обычная загрузка */ }
    return null;
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
    //: Свой персонаж узнаётся по слоту: мир у него чужой, и по миру поднялся
    //: бы канонный герой того же мира.
    start = (saved.slot != null
             && starts.find((entry) => entry.template?.slot === saved.slot))
      || startOf(saved.world);
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
    //: Выбор героя — это уже не загрузка: экран уводим, иначе он закроет
    //: карточки. Вход на карту поднимет его снова.
    loadScreenHide();
    const chosen = await new Promise((resolve) => {
      const opened = creationOpen(starts, newGame?.world, resolve,
                                  shared.hero?.creation ?? null);
      if (!opened) resolve(null);
    });
    //: СВОЙ ПЕРСОНАЖ БЕРЁТСЯ КАК ЕСТЬ. `startOf` ищет запись ПО МИРУ, а свой
    //: занимает мир канонного (builder._custom_hero_choices): по миру нашёлся
    //: бы канонный, и выбор игрока молча пропадал бы — герой выходил Ратибором.
    //: У канонных записей поля `slot` в шаблоне нет вовсе, им ничего не меняется.
    start = chosen
      ? (chosen.template?.slot != null ? chosen : (startOf(chosen.world) ?? chosen))
      : null;
  }
  // Вот единственное место, где герой обретает облик, — и оно ДО карты.
  if (start?.template) shared.hero.template = start.template;
  // РЕПУТАЦИЯ НОВОЙ ИГРЫ — ХАРАКТЕР ГЕРОЯ. Донор кладёт её при выборе
  // персонажа (VA 0x0043C4AC): Драгомир начинает при −100, Гильдис при
  // +30, канонные при нуле. Только для НОВОЙ игры: сейв несёт своё
  // накопленное значение и разворачивается много позже.
  if (!saved) reputationStart(hero, start);
  // ЗАПИСЬ ОТРЯДА — тоже ДО расстановки. Расстановку карты делает
  // `unitsSetup`, и она берёт бойцов из `template.party.members`; сейв
  // применяется много позже, поэтому нанятый разговором боец без этого
  // исчезал при перезагрузке. В движке та же вещь получается сама собой:
  // блок отрядов сохраняется целиком и читается до всякой расстановки.
  if (Array.isArray(saved?.party_members) && shared.hero?.template?.party) {
    // МИГРАЦИЯ СТАРЫХ ЗАПИСЕЙ ОТРЯДА: без родной карты (`home`) запись
    // прячет пачного юнита ЛЮБОЙ карты с тем же слотом — «Ярл превращается
    // в Белуна». Родную карту знаем только у стартовой пары — берём её из
    // пачного шаблона отряда (выпечка кладёт туда home), запасным — карта
    // старта героя. Нанятых в старом сейве не трогаем: их родная карта
    // неизвестна, и лучше прежнее поведение, чем неверный ключ.
    const templateParty = shared.hero.template.party.members ?? [];
    for (const member of saved.party_members) {
      if (!member || member.home != null) continue;
      const original = templateParty.find((row) => row?.index === member.index);
      if (original) member.home = original.home ?? (Number(start?.map) || null);
    }
    shared.hero.template.party.members = saved.party_members;
  }
  // ПАМЯТЬ КАРТ — ПО ТОЙ ЖЕ ПРИЧИНЕ И В ТОМ ЖЕ МЕСТЕ. Из неё `unitsSetup`
  // берёт убитых и приёмышей (оставленного в деревне спутника), а `applySave`
  // разворачивает её много позже — стартовая карта успевала собраться на
  // пустой памяти, и оставленный житель на ней не поднимался. Развернуть
  // дважды безвредно: `mapStateUnpack` каждый раз чистит и заполняет заново,
  // а между этими двумя вызовами память никто не трогает.
  if (Array.isArray(saved?.mapState)) mapStateUnpack(saved.mapState);
  // МИРОВОЙ ТАКТ — ТОЖЕ ДО СБОРКИ КАРТЫ. `lootSetup` решает, отросла ли
  // грядка, сравнением `clock.ticks - regrowAt` (loot.js), а `applySave`
  // разворачивается много позже: с нулевым тактом сорванная трава на
  // стартовой карте оставалась сорванной до следующего перезахода.
  // В движке порядок тот же: счётчик 0x84962C читается из сейва
  // (0x4236E0:36) до расстановки карты.
  if (Number.isFinite(saved?.ticks)) clock.ticks = saved.ticks;
  // ПОСЕЛЕНИЯ — ТУДА ЖЕ И ПО ТОЙ ЖЕ ПРИЧИНЕ. `villageSetup` накладывает
  // сохранённое при ПЕРВОМ визите на карту, но берёт его из отложенного
  // склада, который заполняет `villageUnpack`. Из `applySave` тот звался уже
  // после сборки стартовой карты: постройки успевало наложить (запись правится
  // на месте), а прилавок — нет, потому что генератор к тому мигу уже раздал
  // торговцу ссылку на пустой список мест.
  if (Array.isArray(saved?.villages)) villageUnpack(saved.villages);
  // КАРТУ НАЗЫВАЕТ ВЫБРАННЫЙ МИР, а не манифест. В движке номер берётся из
  // записи отряда только что загруженного мира (`0x8496C8 = отряд+...`,
  // VA 0x438A00), то есть у каждого героя своя стартовая карта: Ратибор 33,
  // Велиславна 19, Эйнар 23, Хельга 37, Александр 45, Анастасия 1.
  //
  // `manifest.start_map` — это карта мира 0, и опора на неё была ещё одним
  // источником Ратибора: любой путь мимо выбора приземлялся у него.
  // Оставлен последним запасным, чтобы пак без стартов не ронял загрузку.
  const firstMap = mapPaths.get(Number(start?.map))
    ?? mapPaths.get(Number(manifest.start_map)) ?? manifest.maps[0].path;
  const path = (saved && mapPaths.get(Number(saved.map))) || firstMap;
  // ЭКРАН ПОДНИМАЕМ СНОВА — И ЖДЁМ ЕГО. Мимо экрана создания сюда приходят с
  // погашенной картинкой (её убрали, чтобы не закрывала карточки героев), и
  // без этой строки самая долгая часть запуска — чтение карты и шести сотен
  // её файлов — шла бы на пустой рамке. Ждать обязательно: иначе картинка
  // встанет в очередь за файлами локации.
  await loadScreenShow();
  const map = await readJson(contentUrl(path));
  currentMap = Number(String(path).match(/maps\/(\d+)\//)?.[1]);
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
  // Склад поселений — тоже на игру, а не на карту: новая партия начинает с
  // чистого блока, как 0x43D898 перечитывает его из GAME.x.
  villageReset();
  //: И знание о местах: новая партия не помнит ни одного, как и блок
  //: состояния движка, который перечитывается целиком.
  knownReset();
  // Записи отрядов — туда же. Блок 0x71E56C движок читает заново ровно тут
  // (0x43D898) и при загрузке сохранения; вход на карту его не касается.
  warbandsReset();
  const heroAssets = heroSetup(map.hero, map) ?? [];
  unitsSetup(map);
  lootSetup(map);
  furnitureSetup(map);
  exitsSetup(map);
  villageSetup(map);
  // Токены-команды квестов: вход на карту переигрывает ВСЕ взведённые
  // (движок — цикл по тремстам записям в загрузчике, донорский 0x4417E0),
  // и правка ложится на свежепрочитанную из пака карту.
  questEditsReplay(map?.legacy?.map_number);
  // Инвентарь заводится ДО боя: combatSetup раскладывает по слотам стартовое
  // снаряжение героя из GAME.0, и обнулять его после этого нельзя.
  inventorySetup();
  combatSetup();
  world.onPickup = (name) => {
    const placedIn = pickUp(name);
    statusNode.textContent = `Поднято: ${actorItemName(name)} (${placedIn})`;
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
    if (door.to_map === -2) {
      // Приказ разговора сажает на корабль БЕЗ права (0x435AA0: перенос
      // безусловен) — и тоже взводит «плывём».
      worldMap.ship = -1;
      leaveToWorldMap("Отплыли: отряд в море");
      return true;
    }
    if (door.to_map === -1) { world.onExit(door); return true; }
    // Приказ разговора ключа НЕ спрашивает: замок живёт только в двери
    // (0x420900), а 0x435AA0 просто пишет заявку `[0x8496D8] = -куда`.
    // Поэтому отрицательная карта здесь — это прямо карта |куда|.
    const targetMap = door.to_map < 0 ? -door.to_map : door.to_map;
    const path = mapPaths.get(Number(targetMap));
    if (!path) return false;
    statusNode.textContent = `Переход: ${mapNameOf(targetMap)}`;
    enterMap(targetMap, { row: door.entry_row, col: door.entry_col, facing: door.facing });
    return true;
  };
  // Выход с локации: -1 уводит на глобальную карту, остальное — в соседнюю
  // локацию по её номеру (пока в паке одна карта, поэтому только говорим).
  // Полный уход с локации на глобальную карту — общий и для пешего выхода
  // −1, и для корабельного −2: в движке обе ветки 0x420900 кончаются одним
  // «карта = −1, режим 5».
  //
  // Карта при этом ИСЧЕЗАЕТ: шаг на клетку выхода зовёт FUN_0043A628(карта)
  // и лишь потом ставит −1. Пока порт держал локацию живой, главный цикл
  // продолжал её считать — и в бою урон капал, пока отряд шёл по
  // глобальной. Сворачиваем по-настоящему: тогда отдельный гейт не нужен,
  // unitsTick и render сами выходят по пустой карте.
  //
  // ОТРАВУ НЕ ТРОГАЕМ: её вычитание идёт по всем отрядам без фильтра по
  // карте (VA 0x41C944), и в ходе по глобальной есть своя копия
  // (VA 0x4277F4). Терять здоровье в походе — канон.
  const leaveToWorldMap = (note) => {
    mapTeardown(currentMap);
    mapStateCapture(currentMap, units, loot);
    // Выход на глобальную — тот же уход с карты: нажитое спутниками в
    // запись отряда, иначе поход вернёт им здоровье дня найма.
    partyCapture();
    // Хозяйство деревни — тоже в склад, как и при переходе на соседнюю
    // карту. Без этого нажитое за визит (метка выплаты, счётчик учёбы,
    // число рук) откатывалось на возврате: `enterMap` захват пропускает,
    // когда текущей карты нет, — а её только что не стало.
    villageCapture();
    currentMap = null;
    // Бой держит ссылки на юнитов: цель, начатый замах и намеченную кучу.
    // Тот же сброс, что и при входе на карту, — общей функцией.
    combatDropTargets();
    worldMap.onMap = true;
    statusNode.textContent = note;
    showWorldMap(true);
  };
  world.onExit = (door) => {
    if (door.to_map === -1) {
      // ВЫШЛИ НА ГЛОБАЛЬНУЮ. В движке это значит, что текущая карта стала
      // −1 (0x8496C8), и только с этого мига по карте можно идти и входить
      // в локации. До того она из панели лишь смотрится.
      leaveToWorldMap("Вышли на глобальную карту");
      return;
    }
    if (door.to_map === -2) {
      // РЕЙС КОРАБЛЯ (0x420900, ветка 0xFE). Зона выхода молчит, пока
      // корабельное право не выписано именно ЭТОЙ карте — его ставит
      // получение «Грамоты на владение кораблём» (обработчик 35 с классом
      // 4) или её донорское применение. Срабатывая, право гаснет и
      // становится «плывём» (0x84960C = −1): по глобальной карте отряд
      // идёт морской маской, а встречи в пути становятся корабельными.
      const here = world.map?.legacy?.map_number;
      if (!Number.isFinite(here) || worldMap.ship !== here) return;
      worldMap.ship = -1;
      leaveToWorldMap("Отплыли: отряд в море");
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
      const KEY = 25;
      if (!dialog.handlers?.[17]?.(KEY)) {
        statusNode.textContent = "Заперто";
        return;
      }
      dialog.handlers?.[45]?.(KEY);
      const targetMap = -door.to_map;
      statusNode.textContent = `Переход: ${mapNameOf(targetMap)}`;
      enterMap(targetMap, { row: door.entry_row, col: door.entry_col, facing: door.facing })
        .then((ok) => { if (ok) statusNode.textContent = mapNameOf(targetMap); });
      return;
    }
    // ПЕРЕХОД НА ТУ ЖЕ КАРТУ — ЭТО НОРМАЛЬНЫЙ ПЕРЕХОД, А НЕ ОШИБКА.
    //
    // Здесь стояло `if (door.to_map === currentMap) return;`, и оно молча
    // съедало целый вид дверей: проход ВНУТРИ локации. В «Подземной тюрьме»
    // таких две из четырёх — выход со строк 63..66 ставит отряд на (51,13),
    // а запертая дверь со строк 21..24 на (12,22), и обе ведут на карту 48,
    // то есть на саму себя. Игрок подходит к проходу в скале, и не
    // происходит ничего.
    //
    // В движке никакой такой проверки нет: `0x420900` на положительной карте
    // всегда делает одно и то же — сворачивает локацию (`0x43A628`) и грузит
    // карту по номеру (`0x43DF48`), даже если номер тот же самый. Через это
    // и работают проходы сквозь стену: карта перечитывается, а отряд встаёт
    // на клетку прибытия из записи двери.
    //
    // Клетку прибытия называет сама запись выхода (+0x05 и +0x07).
    statusNode.textContent = `Переход: ${door.to_name}`;
    enterMap(door.to_map, { row: door.entry_row, col: door.entry_col, facing: door.facing })
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
  heroAssets.push(...lootAssets(), ...furnitureAssets(map));
  heroAssets.push(...projectileAssets(), ...weatherAssets());
  heroAssets.push(...worldMapAssets(map));
  // КАМЕРА НА ГЕРОЯ — ДО расчёта радиуса, иначе рамка считается вокруг нуля,
  // а герой стоит посреди карты: «близким» оказывался её угол, а всё нужное
  // уезжало в хвост очереди. Зум ставим тут же — от него зависит, сколько
  // мира попадает в кадр.
  // ЧУЖИЕ ЛИСТЫ ВЫБРАСЫВАЕМ. Лист актёра — 4095x1700, в распакованном виде
  // около 26 МБ; на Морском лагере их два десятка, то есть под треть гигабайта
  // битмапов. Между картами `world.images` не чистился вовсе, и телефон убивал
  // вкладку раньше, чем кончался трафик.
  //
  // Выбрасывать безопасно: набор листов актёра НЕ зависит от позы (замер на
  // карте 23 — `stand` из 16 записей требует те же 24 листа, что и все позы
  // вместе), поэтому `actorSheetPaths` для актёров новой карты и есть полный
  // список нужного. Всё, что сверх него, осталось от прежней карты.
  forgetForeignSheets(map.hero, [hero, ...units]);
  view.zoom = 1;
  updateZoom();
  centreOnHero();
  queueReset();
  const near = actorsByProximity();
  // ЖДЁМ ВСЕХ, КТО НА КАРТЕ, — как на входе переходом (см. enterMapInner).
  // Здесь, на загрузке страницы с сейвом, ждали только тех, кто в кадре,
  // а дальних и листы тварей везли фоном — и после экрана загрузки игрок
  // видел, как жители «проявляются» на готовой сцене. Жалоба 23.08.
  const all = [...near.inFrame, ...near.rest];
  await preload(mapAssets([...heroAssets,
                           ...actorSheetPaths(map.hero, all),
                           //: герой тоже может ходить набором твари (customHeroSetup),
                           //: и тогда его лист нужен до первого кадра
                           ...projectileAssets(),
                           ...weatherAssets(),
                           ...creatureSheetPaths([hero, ...all])]));
  queueItemIcons(map);
  buildingsSetup();
  // ЛАВКИ НАБИВАЮТСЯ ПРИ КАЖДОМ ВХОДЕ. В движке это последняя строка
  // загрузчика карты: FUN_0043DF48 зовёт генератор FUN_0041896C уже после
  // расстановки построек. Без этого вызова прилавки стояли пустыми всегда —
  // в самих GAME.N они и есть пустые.
  shopsRestock();
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
    // КАМЕРА — СЛЕДОМ ЗА ГЕРОЕМ, А НЕ ЗА КЛЕТКОЙ ИЗ ПАКА. Наведение выше
    // (0x4291B4) случилось ДО разбора сохранения, когда герой ещё стоял на
    // стартовой клетке карты. Сейв ставит его на его настоящее место, и без
    // повторного наведения игрок после загрузки смотрел на точку начала игры,
    // а сам стоял неизвестно где. В движке такой щели нет: сохранение
    // читается блоками ДО загрузки карты, и наведение всегда идёт последним.
    centreOnHero();
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
  // (камера наведена выше, до расчёта радиуса подгрузки)
  soundMapEnter(map.audio, hero.data?.body ?? 0);
  sfxSetup({ hero });
  statusNode.textContent = world.missingAssets.size
    ? `Схема ${manifest.schema_version} · нет ресурсов: ${world.missingAssets.size}`
    : `Схема ${manifest.schema_version} · готово`;
  render();
  // ЭКРАН ЗАГРУЗКИ УХОДИТ ЗДЕСЬ — когда сцена нарисована и герой на месте.
  // Первая карта грузится в обход `enterMap`, поэтому и гасить его приходится
  // своим вызовом: при переходах это делает `finally` там.
  loadScreenDone();
  // Сетку глобальной карты заводим и на первом запуске, а не только при
  // переходе: без неё туман некуда копить и нечего сохранять.
  if (worldMapSetup() && worldMap.x === null) standAt(currentMap);
  // Первая карта грузится в обход enterMap, поэтому самосохранение здесь
  // своё: иначе у нового игрока сохранения не появлялось до первого
  // перехода между локациями.
  if (!saved) saveGame(currentMap);
  // Режим редактора включается ПОСЛЕ мира: ему нужны юниты и карта.
  editorAutostart();
  // Кнопка Play редактора: ?map=N — после ЧЕСТНОГО старта мира (боевой
  // сетап отработал на стартовой карте) штатный переход на заданную.
  const request = new URLSearchParams(location.search);
  const wanted = Number(request.get("map"));
  if (Number.isFinite(wanted) && wanted > 0 && wanted !== currentMap) {
    // «ИГРАТЬ ОТСЮДА»: ?at=строка,столбец. Клетка подставляется ЗАПИСЬЮ
    // ПРИБЫТИЯ — тем же путём, каким на карту приводит дверь, так что
    // работает и постановка отряда, и взгляд, и объезд глухой клетки
    // кольцами. Без неё проба начиналась у входа карты: до места правки
    // приходилось идти по восемь десятков клеток, и на дорогу уходило
    // больше времени, чем на саму правку.
    const spot = (request.get("at") || "").split(",").map(Number);
    enterMap(wanted, spot.length === 2 && spot.every(Number.isFinite)
      ? { row: spot[0], col: spot[1] } : null);
  }
}

new ResizeObserver(refresh).observe(canvas);
requestAnimationFrame(animationLoop);
// ФОНОВЫЙ ДРАЙВЕР ТАКТА (Ф1 плана трансляции, docs/BROADCAST_PLAN.md).
// Скрытой вкладке браузер не даёт requestAnimationFrame ВОВСЕ (замерено:
// мир стоит секундами при готовом маршруте), а вкладке ИИ-игрока рисоваться
// и не нужно — нужно тикать. Обычный setInterval не годится тоже: таймеры
// скрытой вкладки Chrome душит до раза в секунду, а после пяти минут фона —
// до раза в МИНУТУ (замерено: ~2 такта/с вместо 12.8). Таймер потому живёт
// в крошечном воркере — воркеры под троттлинг не попадают, а их сообщения
// будят главный поток немедленно. Кадр зовётся только когда rAF молчит
// дольше четверти секунды: у видимой вкладки долг не копится, у скрытой мир
// идёт своим темпом — быстрее его не пустит clockAdvance по реальным часам.
const pulse = new Worker(URL.createObjectURL(new Blob(
  ["setInterval(() => postMessage(0), 100);"], { type: "text/javascript" })));
pulse.onmessage = () => {
  // У ВИДИМОЙ ВКЛАДКИ ПОРОГ ДРУГОЙ. Четверть секунды — признак задушенной
  // вкладки, но им же оказывается ЛЮБОЙ тяжёлый кадр: при входе на карту
  // кадр занимает 300-600 мс, порог срабатывает всегда, и мир рисуется
  // дважды — ровно там, где машине и без того тяжело (замерено на старте за
  // Драгомира: rAF 150-680 мс вперемешку с message 150-555 мс). Совсем
  // выключать будильник у видимой вкладки нельзя: окно, закрытое другим,
  // остаётся `visible`, а rAF ему Chrome всё равно душит. Поэтому секунда:
  // тяжёлый кадр в неё укладывается, настоящий затык — нет.
  const now = performance.now();
  if (now / 1000 - lastFrameTime <= (document.hidden ? 0.25 : 1)) return;
  try {
    animationFrame(now);
  } catch (error) {
    console.error("сбой фонового такта (пропущен, игра продолжается):", error);
  }
};

window.knyaz2 = { useQuestItem, questItemUsable, profiler,
  editorToggle, editorSave, editorNewPile, editorCloneUnit, editorCloneProp, editorCloneOverlay, editorCompileQuests, editorNewMap, editorBestiary, editorTilesToggle, editorWaterToggle,
  world, view, water, waterRender, render, shadows,
  daylight, daylightSet, sunProgress, ambient, ambientTick,
  hero, heroAnchor, heroUpdateBuilding, lightActive,
  heroCellKey, heroCellAt, heroPlayAction, heroDie,
  heroPlanPath, heroNeighbor, heroFree,
  //: счётчики поиска пути: подвисания меряем числами
  wavePeek,
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
  // Вход в карту по номеру, минуя глобальную. Нужен для карт, которых на
  // глобальной ещё нет: перенесённых из «Продолжения легенды» и вообще любых
  // новых. Обычный путь игрока сюда не ведёт — он идёт через приход отряда.
  enterMap,
  canvas, showRoofsNode, ambientNode, clockRunNode };  // отладка
// Повторяемая проверка правил света и глубины: knyaz2.selfcheck().
window.knyaz2.selfcheck = createSelfCheck(window.knyaz2);
// Ручки ИИ-игрока и журнал событий: knyaz2.agent (снапшот, приказы,
// самопроверка knyaz2.agent.selfcheck()). Ему нужен currentMap — гейт
// «мы на локации» живёт только здесь.
agentSetup(window.knyaz2, { currentMap: () => currentMap });
// Дом2-респавн: смерть откатывает мир к якорному сейву в деревне, деньги и
// сумка переезжают, надетое пропадает. knyaz2.respawn.selfcheck().
respawnSetup(window.knyaz2, { currentMap: () => currentMap });

boot().catch((error) => {
  console.error(error);
  statusNode.textContent = "Ошибка загрузки";
  errorNode.hidden = false;
  errorNode.textContent = `${error.name}: ${error.message}`;
});
