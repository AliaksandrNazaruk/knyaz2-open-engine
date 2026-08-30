// Стартовое меню: пункты, выбор героя, настройки, слоты сохранений.
//
// Пункты живут в разметке (menu.html) — там же их раскладка из MENU.RES.
// Здесь поведение. Что берётся из движка, а что наше:
//
//   ВЫБОР ПЕРСОНАЖА — канон. «Новая игра» открывает GAME.<номер> и читает
//   оттуда запись юнита 0 прямо в героя, а счётчики прибавок обнуляет
//   (VA 0x4387CC). Миров шесть, и у каждого СВОЯ стартовая карта, поэтому
//   выбор героя решает и то, кем играть, и то, где начинать. Карточки
//   строятся по hero.starts из shared.json — там лежат настоящие записи.
//
//   СЛОТЫ СОХРАНЕНИЙ — канон по смыслу: движок пишет KONUNG2.SA<N>, здесь
//   это отдельные ключи хранилища браузера.
//
//   СЛОЖНОСТЬ — канон наполовину. В движке она множит только опыт и имеет
//   три ступени (VA 0x413110, 0x438A00); здесь ступеней пять, у верхних
//   вместо прибавки штраф, и она же множит стартовые деньги. Числа и весь
//   разбор канона — в difficulty.js.
//
//   ГРОМКОСТЬ — наша: оригинал держит её в KONUNG2.CFG, и до разбора того
//   файла числа здесь свои.

//: Таблица ступеней общая с игрой: и подпись здесь, и множители там читают
//: один и тот же файл, чтобы обещанное меню совпадало с игрой.
import { DIFFICULTY, DIFFICULTY_DEFAULT, difficultyHint } from './difficulty.js';
import { SPEEDS } from './settings.js';

// МЕНЮ ЖИВЁТ В ДВУХ МЕСТАХ: своей страницей и накладкой поверх игры. Разница
// только в трёх пунктах, и узнаётся она по разметке — на странице игры есть
// `#game`. Игровых модулей отсюда не видно и видеть не нужно: наружу мы
// говорим событиями, их ловит gamemenu.js.
const inGame = Boolean(document.getElementById('game'));
//: Ответ игры возвращается в `detail`: рассылка события синхронная, значит
//: сразу после неё поле уже заполнено. Нужно это «Сохранить»: без ответа
//: меню бодро рапортовало об успехе даже когда запись не удалась.
const tell = (name) => {
  const ответ = {};
  document.dispatchEvent(new CustomEvent(`menu:${name}`, { detail: ответ }));
  return ответ;
};

const menu = document.getElementById('menu');
const items = [...menu.querySelectorAll('.menu__item')];
const hint = document.getElementById('hint');
const sound = document.getElementById('sound');
const film = document.querySelector('.frame__film');
const screens = {
  options: document.getElementById('screen-options'),
  slots: document.getElementById('screen-slots'),
};

//: трек меню — в оригинале это слот 29 (VA 0x437F48), пак кладёт его сюда
const MENU_TRACK = '/content/assets/audio/track_029.opus';
//: щелчок пункта — слот 6, тот же универсальный звук интерфейса; движок
//: играет его ровно на нажатии (0x438A00 case 1), наведение немое
const CLICK_SOUND = '/content/assets/sfx/006.opus';

//: ключ, который читает сама игра при загрузке (save.js)
const ACTIVE_SAVE = 'knyaz2.save.v1';
//: слоты меню. Нулевой — тот же ключ, что у игры, чтобы уже сделанное
//: сохранение никуда не делось.
const SLOTS = 6;
const slotKey = (index) => (index === 0 ? ACTIVE_SAVE : `${ACTIVE_SAVE}.s${index}`);
//: заказ на новую игру: его читает boot() и начинает с выбранного мира
const NEW_GAME = 'knyaz2.newgame';
const SETTINGS = 'knyaz2.settings';

//: Все три удобства подняты по умолчанию: игра сначала должна быть удобной,
//: а канон — по желанию. Сутки тоже идут, как в оригинале.
const DEFAULT_SETTINGS = { difficulty: DIFFICULTY_DEFAULT, music: 55, sound: 80,
                           follow: true, run: true, fullscreen: true,
                           daynight: true, speed: 1 };

function readJson(key, fallback = null) {
  try {
    const text = localStorage.getItem(key);
    return text ? JSON.parse(text) : fallback;
  } catch { return fallback; }
}

function writeJson(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); return true; }
  catch { return false; }
}

const settings = { ...DEFAULT_SETTINGS, ...(readJson(SETTINGS) ?? {}) };

const click = new Audio(CLICK_SOUND);
click.preload = 'auto';
function playClick() {
  // одна нота, но щелчки могут частить — клон позволяет им накладываться
  const note = click.cloneNode() ?? click;
  note.volume = settings.sound / 100;
  note.play().catch(() => {});
}

let sayTimer = 0;
function say(text) {
  hint.textContent = text;
  hint.removeAttribute('data-quiet');
  clearTimeout(sayTimer);
  sayTimer = setTimeout(() => hint.setAttribute('data-quiet', ''), 3200);
}

// ---- экраны ---------------------------------------------------------------

let openScreen = null;

function showScreen(name) {
  for (const [key, node] of Object.entries(screens)) node.hidden = key !== name;
  openScreen = name ?? null;
  menu.hidden = Boolean(name);
  if (!name) select(current, { focus: false });
}

for (const node of document.querySelectorAll('[data-back]')) {
  node.addEventListener('click', () => { playClick(); showScreen(null); });
}

//: Обычные кнопки на экранах — не пункты меню: у тех своя разметка спрайтами,
//: свой обход стрелками и свой список `items`. Их зовём напрямую по действию.
for (const node of document.querySelectorAll('.screen [data-action]')) {
  node.addEventListener('click', () => {
    playClick();
    ACTIONS[node.dataset.action]?.();
  });
}

// ---- сохранения -----------------------------------------------------------

//: Что показывать про слот: карта, время суток и уровень героя — по ним
//: сохранение и узнаётся.
function slotInfo(index) {
  const saved = readJson(slotKey(index));
  if (!saved?.hero) return null;
  return {
    map: saved.map ?? null,
    level: saved.hero.level ?? 1,
    // В ТОЙ ЖЕ ШКАЛЕ, ЧТО ЛИСТ ПЕРСОНАЖА: движок нигде не показывает сырое
    // поле unit+0x4E, он делит его на шестнадцать с усечением и печатает
    // живому с остатком единицу (VA 0x42A8F4). Полное здоровье — 100, не
    // 1600. Здесь делитель зашит числом: меню живёт до загрузки карты, и
    // правил пака (map.interface.character.health_divisor) ещё нет.
    health: (() => {
      const raw = saved.hero.health ?? 0;
      const shown = Math.trunc(raw / 16);
      return shown === 0 && raw !== 0 ? 1 : shown;
    })(),
    money: saved.hero.money ?? 0,
  };
}

function anySave() {
  for (let index = 0; index < SLOTS; index += 1) if (slotInfo(index)) return true;
  return false;
}

function renderSlots(mode) {
  const box = document.getElementById('slots');
  document.getElementById('slots-title').textContent =
    mode === 'save' ? 'Сохранить игру' : 'Загрузить игру';
  box.textContent = '';
  for (let index = 0; index < SLOTS; index += 1) {
    const info = slotInfo(index);
    const node = document.createElement('button');
    node.type = 'button';
    node.className = 'slot';
    // При загрузке пустое место нажать нельзя; при записи нельзя нажать
    // нулевое — это и есть текущая игра.
    node.disabled = mode === 'load' ? !info : index === 0;
    node.innerHTML = info
      ? `<b>Место ${index + 1}</b><span>карта ${info.map ?? '?'} · уровень ${info.level}`
        + ` · здоровье ${info.health} · монет ${info.money}</span>`
      : `<b>Место ${index + 1}</b><span>пусто</span>`;
    node.addEventListener('click', () => {
      playClick();
      if (mode === 'save') {
        // Сохранение: раскладываем текущую игру по местам. Нулевое место и
        // есть сама текущая игра — переписывать его собой незачем.
        const text = localStorage.getItem(ACTIVE_SAVE);
        if (!text || index === 0) { renderSlots('save'); return; }
        try { localStorage.setItem(slotKey(index), text); }
        catch { say('Хранилище переполнено — место не записано.'); return; }
        renderSlots('save');
        say(`Записано в место ${index + 1}.`);
        return;
      }
      const text = localStorage.getItem(slotKey(index));
      if (!text) return;
      // Загрузка: кладём выбранное сохранение туда, откуда его читает игра.
      // МОЛЧА НЕ ПРОХОДИМ МИМО: здесь стояло `catch { /* переполнено */ }`, и
      // при неудаче игра просто перезагружалась в старую партию, а игрок думал,
      // что загрузил выбранную. Хуже того — прежняя запись оставалась поверх.
      try { localStorage.setItem(ACTIVE_SAVE, text); }
      catch {
        say('Не вышло загрузить: хранилище переполнено или данные сайта запрещены.');
        return;
      }
      localStorage.removeItem(NEW_GAME);
      location.href = '/index.html';
    });
    box.append(node);
  }
}

// ---- настройки ------------------------------------------------------------

const difficultyNode = document.getElementById('opt-difficulty');
const musicNode = document.getElementById('opt-music');
const soundNode = document.getElementById('opt-sound');
const followNode = document.getElementById('opt-follow');
const runNode = document.getElementById('opt-run');
const fullscreenNode = document.getElementById('opt-fullscreen');
const daynightNode = document.getElementById('opt-daynight');
const perspectiveNode = document.getElementById('opt-perspective');
const speedNode = document.getElementById('opt-speed');
//: Сутки в тактах и такт в секундах — те же числа, что в daylight.js и
//: clock.js; сколько это минут, считаем здесь, чтобы подпись не врала при
//: смене ступени.
const СУТКИ_МИНУТ = (21600 * 0.078) / 60;
for (const шаг of SPEEDS) {
  const option = document.createElement('option');
  option.value = String(шаг);
  option.textContent = шаг === 1 ? 'как в оригинале' : `${шаг}×`;
  speedNode.append(option);
}

//: Список ступеней строится один раз из общей таблицы.
for (const [at, step] of DIFFICULTY.entries()) {
  const option = document.createElement('option');
  option.value = String(at);
  option.textContent = step.name;
  difficultyNode.append(option);
}

function paintSettings() {
  difficultyNode.value = String(settings.difficulty);
  musicNode.value = String(settings.music);
  soundNode.value = String(settings.sound);
  // Следствия ступени показываем прямо в подписи, чтобы выбор не был
  // вслепую. Числа берутся из difficulty.js — там же, откуда их читает игра.
  document.getElementById('opt-difficulty-hint').textContent =
    difficultyHint(settings.difficulty);
  document.getElementById('opt-music-hint').textContent = `${settings.music}%`;
  document.getElementById('opt-sound-hint').textContent = `${settings.sound}%`;
  followNode.checked = Boolean(settings.follow);
  document.getElementById('opt-follow-hint').textContent = settings.follow
    ? 'держит выбранного; портрет переносит взгляд'
    : 'как в оригинале: курсор у края окна';
  const runs = settings.run !== false;
  runNode.checked = runs;
  document.getElementById('opt-run-hint').textContent = runs
    ? 'приказ идти — всегда бегом'
    : 'как в оригинале: шаг, двойной щелчок — бег';
  // Полный экран просится уже в игре, на первое касание. На iPhone браузер
  // откажет — там во весь экран уходят только с ярлыка на домашнем экране.
  const full = settings.fullscreen !== false;
  fullscreenNode.checked = full;
  document.getElementById('opt-fullscreen-hint').textContent = full
    ? 'в игре: во весь экран и набок, если браузер даст'
    : 'играть в окне браузера';
  // Смена дня и ночи — галочка самого движка (KONUNG2.CFG, VA 0x4295D8):
  // снятая держит вечный день.
  const темп = SPEEDS.includes(settings.speed) ? settings.speed : 1;
  speedNode.value = String(темп);
  document.getElementById('opt-speed-hint').textContent =
    `сутки за ${(СУТКИ_МИНУТ / темп).toFixed(0)} мин, из них половина ночь`;
  const сутки = settings.daynight !== false;
  daynightNode.checked = сутки;
  document.getElementById('opt-daynight-hint').textContent = сутки
    ? 'как в оригинале: утро, день, вечер, ночь'
    : 'всегда позднее утро';
  const объём = settings.perspective !== false;
  perspectiveNode.checked = объём;
  document.getElementById('opt-perspective-hint').textContent = объём
    ? 'дальнее мельче, ближнее крупнее — как в Diablo'
    : 'как в оригинале: чистая изометрия';
  music.volume = settings.music / 100;
}

//: Галочка хранится булевым, а не числом: игра читает её как есть.
function bindToggle(node, key, after) {
  node.addEventListener('change', () => {
    settings[key] = node.checked;
    writeJson(SETTINGS, settings);
    paintSettings();
    after?.();
  });
}

function bindSetting(node, key, after) {
  node.addEventListener('input', () => {
    settings[key] = Number(node.value);
    writeJson(SETTINGS, settings);
    paintSettings();
    after?.();
  });
}

// ---- пункты ---------------------------------------------------------------

const ACTIONS = {
  // В ИГРЕ «Продолжить» просто закрывает накладку: страницу перезагружать
  // незачем, мир никуда не девался. Со стартовой страницы — как было.
  continue: () => {
    if (inGame) { tell('continue'); return; }
    localStorage.removeItem(NEW_GAME);
    location.href = '/index.html';
  },
  // «Новая игра» ведёт СРАЗУ на экран создания героя — он живёт в игре, это
  // состояние экрана 2 движка (0x849574). Своего выбора персонажа в меню
  // нет и быть не должно: в оригинале пункт меню открывает именно этот
  // экран, причём на архетипе 2 (VA 0x438A00 case 3 зовёт 0x4387CC(2)).
  new: () => {
    localStorage.removeItem(ACTIVE_SAVE);
    writeJson(NEW_GAME, { world: 2, create: true });
    location.href = '/index.html';
  },
  // «Загрузить» и «Новая игра» требуют другого мира целиком — им
  // перезагрузка нужна по существу, и они уходят на страницу игры.
  load: () => { renderSlots('load'); showScreen('slots'); },
  //: В игре сперва просим её записать текущее состояние, иначе раскладывать
  //: по местам было бы нечего или досталось бы вчерашнее.
  save: () => {
    //: Ответ игры проверяем: раньше «Сохранить» молча открывало список мест
    //: даже когда запись не удалась, и игрок уходил уверенный, что сохранился.
    if (inGame && tell('save').ok === false) {
      say('Записать не вышло — хранилище переполнено или данные сайта запрещены.');
      return;
    }
    renderSlots('save');
    showScreen('slots');
  },
  // ВЫГРУЗКА И ЗАГРУЗКА ФАЙЛОМ.
  //
  // Хранилище браузера чужое и ненадёжное: его сносит «очистить данные сайта»,
  // его не бывает в приватном окне, и оно СВОЁ у каждого адреса — партия с
  // локального сервера на боевом не видна. Файл на диске от этого не зависит и
  // заодно переносит игру между машинами. Проверку самого сохранения не
  // дублируем: её владелец — save.js, он и откажется от негодного при загрузке.
  export: () => {
    const text = localStorage.getItem(ACTIVE_SAVE);
    if (!text) { say('Сохранять нечего — игра ещё не записана.'); return; }
    const метка = new Date().toISOString().slice(0, 16).replace(/[:T]/g, '-');
    const ссылка = document.createElement('a');
    ссылка.href = URL.createObjectURL(new Blob([text], { type: 'application/json' }));
    ссылка.download = `knyaz2-${метка}.json`;
    ссылка.click();
    URL.revokeObjectURL(ссылка.href);
    say(`Выгружено в файл ${ссылка.download}.`);
  },
  import: () => {
    const выбор = document.createElement('input');
    выбор.type = 'file';
    выбор.accept = '.json,application/json';
    выбор.addEventListener('change', async () => {
      const файл = выбор.files?.[0];
      if (!файл) return;
      const text = await файл.text();
      try { JSON.parse(text); }
      catch { say('Это не файл сохранения: не разбирается.'); return; }
      try {
        const прежнее = localStorage.getItem(ACTIVE_SAVE);
        if (прежнее) localStorage.setItem(`${ACTIVE_SAVE}.prev`, прежнее);
        localStorage.setItem(ACTIVE_SAVE, text);
      } catch {
        say('Не вышло записать: хранилище переполнено или данные сайта запрещены.');
        return;
      }
      localStorage.removeItem(NEW_GAME);
      location.href = '/index.html';
    });
    выбор.click();
  },
  options: () => { paintSettings(); showScreen('options'); },
  exit: () => {
    if (inGame) { tell('exit'); return; }
    window.close();                       // сработает, только если вкладку открыл скрипт
    say('Закройте вкладку, чтобы выйти.');
  },
};

//: почему пункт погашен — показывается при наведении
const PENDING = {
  continue: 'сохранённой игры пока нет — начните новую',
  //: В движке «Сохранить» на СТАРТОВОМ экране тоже недоступно: сохранять
  //: нечего, пока игра не идёт. Внутри игры сохранение делает сама игра.
  save: 'сохранять можно только в идущей игре',
  load: 'сохранений пока нет',
};

function usable(item) {
  const action = item.dataset.action;
  // «Сохранить» работает, когда есть текущая игра: в игру выходят по Esc,
  // и она пишет своё состояние ПЕРЕД уходом в меню — отсюда и раскладываем
  // его по местам, как движок пишет KONUNG2.SA<N>.
  //: В идущей игре сохранять можно всегда: состояние запишет она сама.
  if (action === 'save') return inGame || Boolean(readJson(ACTIVE_SAVE));
  if (action === 'continue') return Boolean(slotInfo(0));
  if (action === 'load') return anySave();
  return Boolean(ACTIONS[action]);
}

let current = 0;

function enabled(item) { return !item.disabled; }

function select(index, { focus = true } = {}) {
  const list = items.filter(enabled);
  if (!list.length) return;
  current = Math.max(0, Math.min(items.length - 1, index));
  items.forEach((item) => item.removeAttribute('data-active'));
  const item = items[current];
  item.setAttribute('data-active', '');
  if (focus) item.focus({ preventScroll: true });
}

function step(direction) {
  let index = current;
  for (let guard = 0; guard < items.length; guard += 1) {
    index = (index + direction + items.length) % items.length;
    if (enabled(items[index])) break;
  }
  select(index);
}

function activate(item) {
  if (!enabled(item)) { say(item.title); return; }
  const action = ACTIONS[item.dataset.action];
  if (!action) return;
  playClick();
  action();
}

function refreshItems() {
  for (const item of items) {
    const action = item.dataset.action;
    item.disabled = !usable(item);
    item.title = item.disabled ? (PENDING[action] ?? 'ещё не сделано') : '';
  }
  const first = items.findIndex(enabled);
  if (first >= 0 && !enabled(items[current])) select(first, { focus: false });
}

for (const item of items) {
  item.addEventListener('pointerenter', () => {
    if (enabled(item)) select(items.indexOf(item));
    else say(item.title);
  });
  item.addEventListener('click', () => activate(item));
}
refreshItems();
select(items.findIndex(enabled), { focus: false });

document.addEventListener('keydown', (event) => {
  // В ИГРЕ КЛАВИШИ НАШИ, ТОЛЬКО ПОКА НАКЛАДКА ОТКРЫТА. Модуль остаётся в
  // документе и после закрытия, и без этой проверки он ловил бы стрелки и
  // Esc посреди игры.
  if (inGame && document.getElementById('game-menu')?.hidden !== false) return;
  if (openScreen) {
    if (event.key === 'Escape') {
      showScreen(null);
      event.preventDefault();
      //: Дальше по цепочке Esc не пускаем: у игры он свой, и накладка
      //: закрылась бы вместе с этим экраном.
      event.stopPropagation();
    }
    return;
  }
  // ESC ИЗ ГЛАВНОГО МЕНЮ ВОЗВРАЩАЕТ В ИГРУ. Так делает движок: в состоянии
  // меню ветка 0x1B ставит состояние обратно в ноль и продолжает игру
  // (VA 0x438A00, case 1). Здесь меню — отдельная страница, поэтому
  // возвращаемся на страницу игры: состояние сохранено при выходе.
  //
  // Если игры ещё нет (в хранилище пусто), возвращаться некуда — тогда
  // ESC просто говорит об этом, а не уводит в пустоту.
  if (event.key === 'Escape') {
    event.preventDefault();
    //: В игре Esc просто закрывает накладку — уходить со страницы незачем.
    if (inGame) { event.stopPropagation(); tell('continue'); return; }
    if (readJson(ACTIVE_SAVE)) {
      playClick();
      localStorage.removeItem(NEW_GAME);
      location.href = '/index.html';
    } else {
      say('Игра ещё не начата — выберите «Новая игра».');
    }
    return;
  }
  switch (event.key) {
    case 'ArrowDown': case 'ArrowRight': step(+1); break;
    case 'ArrowUp': case 'ArrowLeft': step(-1); break;
    case 'Home': select(items.findIndex(enabled)); break;
    case 'End': select(items.findLastIndex(enabled)); break;
    case 'Enter': case ' ': activate(items[current]); break;
    default: return;
  }
  event.preventDefault();
});

// подсказка про клавиши гаснет сама, чтобы не спорить с картинкой
setTimeout(() => hint.setAttribute('data-quiet', ''), 6000);

// ---- музыка ---------------------------------------------------------------

const music = new Audio(MENU_TRACK);
music.loop = true;
music.volume = settings.music / 100;
music.preload = 'auto';

function setMusic(on) {
  sound.setAttribute('aria-pressed', String(on));
  if (on) music.play().catch(() => sound.setAttribute('aria-pressed', 'false'));
  else music.pause();
}

sound.addEventListener('click', () => setMusic(sound.getAttribute('aria-pressed') !== 'true'));

bindSetting(difficultyNode, 'difficulty');
bindSetting(musicNode, 'music');
bindSetting(soundNode, 'sound', () => playClick());
bindToggle(followNode, 'follow', () => playClick());
bindToggle(runNode, 'run', () => playClick());
bindToggle(fullscreenNode, 'fullscreen', () => playClick());
bindToggle(daynightNode, 'daynight', () => playClick());
bindToggle(perspectiveNode, 'perspective', () => playClick());
bindSetting(speedNode, 'speed', () => playClick());
paintSettings();

// В ИГРЕ СВОЙ ТРЕК МЕНЮ НЕ ЗАВОДИМ. Накладка открывается поверх идущей игры,
// и подменять её музыку на менюшную — значит потом ещё и гасить эту менюшную
// при закрытии. Кнопкой «♪» включить по-прежнему можно.
if (inGame) sound.setAttribute('aria-pressed', 'false');
// Браузер не пускает звук до первого действия пользователя, поэтому пробуем
// сразу, а при отказе ждём любого касания клавиши или мыши.
else music.play().then(() => sound.setAttribute('aria-pressed', 'true')).catch(() => {
  const wake = () => { setMusic(true); document.removeEventListener('pointerdown', wake);
                       document.removeEventListener('keydown', wake); };
  document.addEventListener('pointerdown', wake, { once: false });
  document.addEventListener('keydown', wake, { once: false });
});

// ---- ролик ----------------------------------------------------------------

// Если у человека выключена анимация в системе — оставляем неподвижный кадр.
if (matchMedia('(prefers-reduced-motion: reduce)').matches) film.pause();

// Вкладка в фоне: не гоняем декодер впустую.
document.addEventListener('visibilitychange', () => {
  if (document.hidden) film.pause();
  else if (!matchMedia('(prefers-reduced-motion: reduce)').matches) film.play().catch(() => {});
});
