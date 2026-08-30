# Аудит движка перед вторым (3D) рендерером

> **Поправка от 30.08.2026 (второй проход).** Наклон камеры и формула yaw ниже
> исправлены: `pitch = asin(16/29) = 33.4854°` (а не `atan`), `yaw = 45·((dir+5) mod 8)`.
> Вывод и численная проверка — `docs/HD_RENDERER_PASS2.md` §1.

Дата: 2026-08-30. Предмет аудита: **браузерный движок** `knyaz2/web/static/*.js`
(37 500 строк, 60 модулей) — это и есть «наш движок»: игровая логика живёт
именно там, сверенная с декомпилятом `konung2.exe`. Python (`konung2/`,
`knyaz2/content/`) — кодеки и сборщик пака, во время игры не исполняется.
`simulation/` — отдельный прототип причинного автомата NPC, к игре не
подключён (см. `SIMULATION.md`, историческая пометка).

Цель: понять, что старый движок уже может отдать новому 3D-рендереру и где
геймплей завязан на старую графику. Ничего не переписываем.

---

## 0. Одной страницей

| Вопрос | Ответ |
| --- | --- |
| Симуляция отделима? | **Да.** Такт фиксированный 78 мс, решения заперты тактом, отрисовка — ОДИН вызов `render()` в конце кадра (`app.js:252`). |
| Рендерер заменяем? | **Да, кроме трёх мест**: попиксельный выбор юнита, кадры удара, ключ глубины как арбитр клика. |
| Второй рендерер параллельно? | **Да.** Шов уже готов: `render()` — единственный потребитель мира, состояние читается снаружи (`window.knyaz2`). |
| Сколько кода на PoC? | ~250 строк нового модуля + 3 файла с правками на ~10 строк. |
| Интерполяция? | **Не нужна.** Позиции юнитов уже непрерывные: шаг клетки интерполируется по `dt` (`hero.js:911`). |

---

## 1. Общая архитектура

```text
Main  app.js:161 animationLoop → :175 animationFrame(now)
 ├─ Input           input.js (pointer/wheel/keys на #world), cursors.js
 │                  hero.js:1232 edgeScroll, hero.js:498 heroInputVector
 ├─ Simulation
 │   ├─ World       world.js (мир карты), clock.js (мировой такт),
 │   │              daylight.js (сутки), village.js, worldmap.js, exits.js
 │   ├─ Units       units.js:1643 unitsTick — ОДИН цикл на всех, герой первый
 │   ├─ AI          units.js:1705+ (гейт `!acting && clock.elapsed`),
 │   │              warband.js (кто кому враг), orders.js
 │   ├─ Physics     hero.js:618 heroPlanPath (волна), hero.js:806 unitTryStep,
 │   │              hero.js:269 heroFree, units.js:2354 unitBlocks
 │   └─ Combat      combat.js:524 strike, :615 applyDamage, :1022 combatTick,
 │                  projectiles.js:125 projectilesTick, effects.js:88 (яд)
 │
 ├─ Animation       units.js:2136-2250 (кадр по такту), actor.js:215 actorFrames,
 │                  actor.js:271 actorAttackPose, hero.js:1034 heroSetPose
 │
 └─ Rendering       scene.js:45 render() — мастер кадра
                    viewport.js (камера, слои, фильтр суток)
                    ground.js, shadows.js, light.js, entities.js,
                    units.js:2274 renderUnit, hero.js:1143 renderHero,
                    projectiles.js:287, weather.js, ambient.js
                    perspective.js — опыт «перспектива Diablo» поверх изометрии
```

**Инициализация.** `app.js:879 boot()` → загрузка `shared.json` (`world.js:65
loadShared`) → `app.js:623 enterMap(number, entry)` → `:668 enterMapInner`:
`loadMap(map)` → `heroSetup` (сетка проходимости) → `unitsSetup`, `lootSetup`,
`furnitureSetup`, `exitsSetup`, `villageSetup` → `questEditsReplay` → постановка
героя на клетку прихода → `partyRegroup()` → предзагрузка ресурсов радиусом.

**Shutdown.** Отдельного нет. Выход с карты — `app.js:118 mapTeardown(number)`
(свёртка добра, VA 0x43A628) + `mapStateCapture`; уход в меню — `app.js:270
leaveToMenu()` (сохранение + смена страницы). Ресурсы чужой карты выбрасывает
`forgetForeignSheets`.

**Окно/ввод/звук.** Единственный холст `#world` (`index.html:33`), весь
интерфейс — **DOM, а не канвас** (`ui.js`, `styles.css`). Для второго
рендерера это подарок: интерфейс переносить не надо вовсе.

---

## 2. Game loop и timestep

### 2.1 Реальный call stack

```text
requestAnimationFrame → app.js:161 animationLoop(now)
  app.js:175 animationFrame(now)
      dt = min(0.1, now/1000 − lastFrameTime)               // :176-178
      [гейт паузы: gameMenuOpen() || loadScreenHolding()]   // :189
      clock.scale = timeScale();  clockAdvance(seconds)     // :194-195
                                    ↑ ЕДИНСТВЕННОЕ место, где растёт мировой такт
      waterTick / soundTick / soundscapeTick / clockTick / ambientTick  // :199-206
      edgeScrollTick()                                      // :210
      if (currentMap !== null) {
          requeueByDistance()                               // :227 (стриминг листов)
          unitsTick(now, dt)                                // :229 ← ИИ, движение, кадры, удары
          dialogApproachTick()                              // :231
          combatTick(dt)                                    // :233 ← снаряды, удар героя
          cameraFollow(panelUnit())                         // :239
      }
      effectsTick(); villageTick(); worldTick(now); exitsTick()   // :243-247
      if (dirty || view.dirty) render()                     // :250-253
                                    ↑ ЕДИНСТВЕННЫЙ вызов отрисовки
```

Второй, «спящий», источник кадра: воркер-пульс `app.js:1446-1462` шлёт
сообщение раз в 100 мс и зовёт **тот же** `animationFrame`, если rAF молчит
дольше 0.25 с (скрытая вкладка) / 1 с (видимая). Мир идёт и без картинки.

### 2.2 Timestep

`clock.js` — аккумулятор:

```js
export const TICK_SECONDS = 0.078;          // clock.js:22
const CATCHUP_LIMIT = 4;                    // clock.js:55
while (seconds - clock.seconds >= step && clock.elapsed < limit) { ... }   // clock.js:80
```

* **fixed timestep есть**: 78 мс = 12.82 такта/с. Частота доказана по коду
  оригинала: `VA 0x42F1EF cmp eax,0x4E` (78 мс) → `SendMessageA WM_USER` →
  `0x42F913 call 0x438A00`, и это ЕДИНСТВЕННЫЙ вызов главного цикла.
* **accumulator есть**, с потолком догона 4 такта × множитель темпа.
* Ускорение времени (`clock.scale`, настройка игрока) — **короче шаг**, а не
  больше тактов за раз: фазы `& 0xF` остаются на своих местах.

### 2.3 От чего что зависит

| Подсистема | Источник времени | Файл |
| --- | --- | --- |
| Решения ИИ, выбор цели, приказы | **мировой такт** (`clock.elapsed`) | `units.js:1705` |
| Отряды, вражда, тренировка, срок работы | **раз в 16 тактов** (`clockPhaseHits(0xF)`) | `units.js:1649`, `clock.js:92` |
| Движение по клетке | `dt`, длительность = `unitCellTicks × 0.078` | `hero.js:911`, `hero.js:872` |
| Кадр анимации | свой аккумулятор `unit.frameTime += dt`, шаг `tickSeconds()` | `units.js:2140-2145` |
| Снаряды | `dt / tickSeconds()` × 8 подшагов | `projectiles.js:129-135` |
| Яд, стройка, сутки, деревня | мировой такт и его фазы | `effects.js:88`, `daylight.js` |
| Погода, вода, амбиент, тени | **кадры браузера** (чистая презентация) | `weather.js`, `water.js`, `shadows.js` |

**Вывод: геймплей от FPS не зависит.** Все игровые решения и все длительности
привязаны к 78-мс такту; `dt` служит только для ровной интерполяции того, что
такт уже решил.

### 2.4 Смешение update/render

Оно есть, но в трёх известных точках:

1. `render()` зовётся из обработчиков ввода: `input.js:235,241,244,448,475`,
   `ui.js:1166,1221` — перерисовка по требованию, не геймплей.
2. `units.js:2274 renderUnit` и `hero.js:1143 renderHero` физически лежат в
   геймплейных модулях (P2, косметика раскладки файлов).
3. Кадр анимации двигает такт **внутри** `unitsTick`, и он же наносит удар
   (см. §7 и §15) — это канон движка, а не наш дефект.

---

## 3. Координатные системы

### 3.1 Список

| Система | Тип | Единицы | Origin | X | Y | Z |
| --- | --- | --- | --- | --- | --- | --- |
| **world (мировые пиксели)** | float | 1 пиксель плоской изометрии | левый верх карты | вправо | вниз | **нет** |
| **navigation cell** | int `{row, col}` | клетка 58×16 px, ряды со сдвигом | (0,0) | col вправо | row вниз | нет |
| **ground tile** | int `{row, col}` | ромб 114×64 px, шаг 116×32, сдвиг 58 | (0,0) | col | row | нет |
| **screen** | float | пиксель канваса × dpr | центр вида | вправо | вниз | — |
| **sprite/frame** | int | пиксель листа | `offset_x/offset_y` от якоря сущности | — | — | — |
| **collision** | тот же navigation cell | 12 младших бит слова клетки | — | — | — | нет |

Ключевое: **мировые координаты — это и есть плоское изометрическое экранное
пространство**. Отдельного «мира в метрах» не существует; камера — просто
сдвиг и масштаб над ним.

### 3.2 Преобразования (реальные функции)

```text
cell  → world     hero.js:201  heroAnchor(row, col)          VA 0x43B974
                  x = col*58 + (row&1 ? 29 : 58);  y = row*16 + 16
world → cell      hero.js:232  heroCellAt(x, y)              VA 0x43B9B0
                  (ромбическая поправка двумя векторными произведениями)
cell  → cell      hero.js:334  heroNeighbor(row, col, dir)   таблица 0x49CF68
                  N/S шагают ЧЕРЕЗ ДВА ряда, диагонали — на один
world → screen    viewport.js:333 worldTransform(target)
                  scale = dpr*zoom, translate = dpr*(w/2 − camX*zoom)
screen → world    viewport.js:397 screenToWorld(clientX, clientY)
                  + крючок perspective.js:229 perspectiveUnproject
tile  → world     konung2/world/geometry.py:67  GroundCell.origin()
world → tile      konung2/world/geometry.py:87  ground_at_point()
объект → глубина  konung2/world/geometry.py:137 Bounds.sort_key() → bounds.sort_y
юнит  → глубина   actor.js:45 unitSortKey(actor)
```

Python-зеркала тех же формул: `konung2/world/geometry.py:50 Cell.anchor`,
`konung2/grid.py pixel_to_cell`.

### 3.3 Форма проекции

* Ромб подклетки **58 × 32** (клетка 58×16, но сосед по вертикали — через два
  ряда). Половинный сдвиг нечётных рядов — 29 px. Классическая
  staggered-изометрия 2:1.
* Тайл земли — ромб **114 × 64**, шаг решётки 116 × 32, сдвиг нечётного ряда
  58 (`konung2/graph.py:37-40`). Один тайл земли ≈ 2×2 клетки навигации.
* Базис восьми направлений (`shared.json → hero.direction_steps`):

```text
0 W (−58, 0)   1 NW (−29,−16)   2 N (0,−32)   3 NE (29,−16)
4 E ( 58, 0)   5 SE ( 29, 16)   6 S (0, 32)   7 SW (−29, 16)
```

  Отсюда чистые оси земли: `u = SE = (29, 16)`, `v = NE = (29, −16)`.
  Обратно из мировых пикселей: **`u = x/58 + y/32`, `v = x/58 − y/32`** — это
  и есть готовые координаты плоскости для 3D-сцены, целое число на клетку.
* **Elevation нет.** Ни в `.KN2`, ни в паке нет ни поля высоты, ни слоя
  рельефа. Мосты, лестницы, возвышенности нарисованы в спрайте объекта,
  логически это ровный пол.
* **Логической Z нет.** Единственные суррогаты:
  * `bounds.sort_y` — ключ глубины (подошва кадра минус четверть высоты);
  * `projectiles.js:71 height = 30` — высота полёта, **вычтенная прямо из y**;
  * биты клетки 15 «пол постройки», 21/22 «рисовать поверх / исходной
    палитрой» (`konung2/grid.py`).
* **Объекты друг над другом стоять не могут**: младшие 12 бит клетки — либо 0
  (свободно), либо 0xFFF (глухо), либо ссылка на ОДНОГО юнита.

---

## 4. Камера

`viewport.js:84 export const view`:

```js
{ dirty, width, height, dpr, cameraX, cameraY, zoom: 0.45, dragging,
  pointerX, pointerY, follow }
```

* **position** — `cameraX/cameraY` — ЦЕНТР вида в мировых пикселях (в движке
  это левый верх окна 884×708; пересчёт в центровую форму и его причина —
  `viewport.js:100-118`).
* **target/follow** — `viewport.js:185 cameraFollow(target)` — наша настройка,
  не канон: в движке камеру двигают только курсор у края (VA 0x437CD0) и
  наведение при загрузке карты (VA 0x4291B4).
* **zoom** — наш, движок масштаба не знал. Пределы `ZOOM_LIMIT {0.1, 2.5}` плюс
  пол `zoomFit()` по рамке карты (`viewport.js:126`).
* **rotation — отсутствует.** Поворота нет нигде, и это принципиально: спрайты
  нарисованы под 8 фиксированных направлений.
* **scrolling** — `hero.js:1232 edgeScroll` (шаг 0x39 × 0x20 — канонные числа).
* **viewport/clamp** — `viewport.js:146 clampCamera()` по
  `map.coordinates.camera {left, right, top, bottom}`.
* **projection** — аффинная матрица `viewport.js:333 worldTransform`; поверх неё
  опыт с перспективой (`perspective.js`), дающий линейный по строке масштаб
  (закон снят с `Game.exe` Diablo II, `docs/PERSPECTIVE.md`).

Позиция объекта на экране сейчас = `worldTransform × (x + frame.offset_x,
y + frame.offset_y)`. Других шагов нет.

**Для 3D:** камера переводится в ортографическую с фиксированным углом —
`yaw = 45°`, `pitch = asin(16/29) = 33.4854°` (наклон, дающий ромб 58×32), центр —
`(cameraX, cameraY)` через `u/v`-разложение §3.3, орто-высота
`view.height / zoom`. `perspective.js` показывает, что вариант с настоящей
перспективой в кадр уже заложен.

---

## 5. Карта и геометрия уровней

### 5.1 Конвейер

```text
.KN2 (256 512 байт) ──konung2/kn2.py, grid.py, graph.py──┐
GAME.x (юниты, отряды, деревни) ──konung2/gamefile.py────┤
OBJECTS.RES / HEROES.RES / GRAPH.RES ──konung2/res.py────┼──► knyaz2/content/builder.py
QUESTS.RES ──konung2/quests.py──────────────────────────┘         │
                                                                  ▼
                                             content_build/maps/<N>/map.json (+ shared.json)
                                                                  │  fetch
                                                                  ▼
                                                world.js:87 loadMap(map) → рабочие списки
```

### 5.2 Что лежит в `map.json`

| Элемент | Где | Как хранится | ID | Rotation | Variation | Height | Collision |
| --- | --- | --- | --- | --- | --- | --- | --- |
| floor tiles | `terrain.ground[]` | `{row, col, x, y, asset, tiles{lower,upper}, light}` | пара индексов тайлов | нет | два наложенных тайла | нет | нет |
| подложка (вода) | `terrain.underlay` | `{cell_size:256, cells[[row,col,val]], visual}` | — | нет | анимация | нет | нет |
| overlays ландшафта | `terrain.overlays[]` | кадр + позиция, порядок по `record_slot` | slot | нет | — | нет | нет |
| стены / обрывы | **отдельной сущности нет** | это `blocked` + спрайт объекта | — | — | — | — | `terrain.blocked[]` |
| постройки | `buildings[]` | `position`, `bounds`, `frames{main,walls,roof,shadow}`, `states{0..N}`, `cells{floor,footprint,routed}` | `record_slot`, `resource_slot` | нет | `palette`, `state` | нет | `footprint` |
| реквизит | `props[]` | то же, но без `floor` | `record_slot` | нет | `palette` | нет | `footprint` |
| двери / переходы | `exits[]` | прямоугольник клеток + `to_name` | — | — | — | — | триггер |
| обстановка | `terrain.furniture[]` | кадр + абсолютная точка | slot | нет | — | нет | нет |
| огни | `object.fire[]` | `{anim, offset}` | id анимации | нет | случайная фаза | нет | нет |
| навигация | `terrain.blocked`, `blocked_soft`, `solid` | списки клеток | — | — | — | — | да |
| свет | `terrain.ground[].light.glow`, `lighting{}` | маска-картинка + уровни | — | — | — | — | нет |
| триггеры / квесты | `events`, `units[].dialog`, `legacy` | узлы разговора | — | — | — | — | — |

**Rotation нет ни у чего.** Вариативность объекта — это `state` (ступень
стройки или пожара) и `palette`. Chunk/sector-системы нет: карта монолитна,
256×160 клеток; отсечение — только по видимой рамке (`viewport.js:322
visibleWorld`).

### 5.3 Пригодность к HD-конверсии

Схема из ТЗ работает почти дословно:

```text
LegacyTile { tileId = tiles.lower/upper, row, col, x, y }
   elevation = 0        (всегда)
   rotation  = 0        (всегда)
   flags     = blocked | solid | light
        ↓
HDTileInstance { meshId = f(tileId), materialId = f(tileId, палитра карты),
                 worldTransform = translate(u, v из §3.3) }
```

Для объектов вместо `tileId` — пара `(resource_slot, state)`; ключ уже
уникален и стабилен между картами (имя ассета `264_91_0_main.png` =
`slot_palette_state_part`).

---

## 6. Entities / Units / Objects

Иерархии классов нет — есть **три вида записей**:

1. **Актёр** (герой, спутник, житель, тварь) — `units[]` и `hero`, заводится
   `units.js:525 unitSpawn(entry, map)`. Герой — тот же объект (`hero.js:14`),
   просто первый в `roster()` (`hero.js:453`).
2. **Объект сцены** (постройка, реквизит) — `world.objects[]`.
3. **Снаряд / вспышка / куча** — `projectiles[]`, `bursts[]`, `loot[]`.

### 6.1 Поля актёра (полный список из `unitSpawn`, units.js:525-673)

| Категория | Поля |
| --- | --- |
| идентичность | `id`, `slot`, `homeMap`, `name`, `game` |
| позиция | `x`, `y` (мировые px, точка ног), `cell{row,col}`, `home`, `step{fromX,fromY,toX,toY,direction,time,duration,block}` |
| ориентация | `direction` 0…7 |
| скорость | **вектора нет**; есть `speed` (+0x1D) и `unitCellTicks()` — тактов на клетку |
| состояние | `alive`, `hidden`, `moving`, `running`, `stance` peace/combat, `busy`, `orderByte`, `orderKind`, `orderTarget`, `path[]` (список направлений), `goal`, `goalTarget`, `chaseAt` |
| анимация | `pose`, `frame`, `frameTime`, `attackWait`, `struck`, `hurt`, `cooldown` |
| бой | `health`, `maxHealth`, `characteristics[6]`, `baseCharacteristics`, `skills[]`, `side`, `hostile`, `target`, `venom`, `poison` |
| экипировка | `equipment{hand, off_hand, ranged, body, head, ammo}`, `bag[]`, `money`, `rangedMode` |
| визуал | `body` (форма), `palette` (масть), `breed` (бит 0x40 = тварь), `beast`, `face` |
| флаги рендера | `insideBuilding`, `overlay` (бит 15), `bright` (бит 22), `roofBuilding` — ставит `hero.js:370 unitUpdateBuilding` |
| прочее | `dialog`, `dialogNumber`, `workplaces`, `workRest`, `role`, `counter`, `level` |

**Минимальное состояние для рендерера (доступно каждый кадр, без правок):**

```text
id, x, y            — мировые пиксели, непрерывные
direction           — 0…7
pose, frame         — блок анимации и номер кадра
frameTime           — фаза внутри кадра (0…0.078) → готовый alpha
stance, running     — какой набор блоков
body, palette, breed, game — какой набор кадров / меш
equipment{6 слотов} — что надеть на 3D-модель
alive, hidden, bright, overlay, insideBuilding — видимость и режим
health / maxHealth  — если нужен цвет круга или полоски
```

---

## 7. Character animation

### 7.1 Модель

Анимация — **таблица блоков**, не граф состояний. `konung2/heroes.py:78-120`:

```text
стойка мирная   16 stand, 17 walk, 18 idle, 19 run
стойка боевая    0 stand,  1 walk,  6 idle,  7 run     (бит 0x04 байта +0x19)
действия         9 attack_one_hand, 5 attack_shield, 8 attack_two_hand,
                 4 shoot_bow, 10 shoot_crossbow, 2 hit,
                 3/11/12 death_1..3, 13/14/15 corpse_1..3
```

Переход стойки — таблицы 0x45A0C0 / 0x45A098 (16↔0, 17↔1, 18↔6, 19↔7).
Отдельных анимаций «меч / топор / лук» у тела **нет**: оружие — отдельный слой
кадра, а какой блок играть, решает группа предмета (`actor.js:271
actorAttackPose`, правило `rules.attack_by_item`).

### 7.2 Тайминг

```js
// units.js:2140-2146
const step = tickSeconds();               // 0.078
unit.frameTime += dt;
const advance = Math.floor(unit.frameTime / step);
unit.frameTime -= advance * step;
```

Один кадр = один мировой такт, замедлений нет ни у одного блока. Ждать умеет
только замах — на нулевом кадре, проедая `attackWait` (`units.js:2148-2153`,
поле +0xFD оригинала).

Переходы: конец блока → `stand` (`units.js:2225`); позы стойки крутятся по
кругу (`units.js:2174`); смерть → труп (`units.js:2181`); жребий простоя
1 из `rules.idle_chance` (`units.js:2243`).

### 7.3 Combat timing — здесь главное

**Да, события боя привязаны к номеру кадра спрайта.** Это канон движка, но для
нас это самая жёсткая связка «визуал → геймплей».

| Событие | Кадр | Код | Оригинал |
| --- | --- | --- | --- |
| «объявление войны» отряду жертвы | кадр 2 | `units.js:1508 SWING_DECLARES_AT`, `:2160 swingDeclares` | 0x413894 (сверка +0x1C с 2) |
| удар основной рукой, `attack_shield` | кадр 5 | `units.js:1511 STRIKE_FRAME` | байт 0x45FE95 = 0xFB |
| удар, `attack_two_hand` | кадр 7 | там же | 0x45FE98 = 0xF9 |
| удар, `attack_one_hand` | кадры 7 (main) и 9 (off) | там же | половинки 0xF9 |
| **запуск снаряда** | `всего − 6` | `units.js:1527 world.strikeFrames` | 0x413894:321 |
| расход стрелы | тот же кадр | `combat.js:325 ammoSpend` | 0x4148E5 |
| звук замаха | начало блока | `combat.js:837 sfxSwing` | 0x429B2C |
| урон и стрельба героя | по `hero.frame` | `combat.js:846 resolvePendingHit` | — |
| переход в следующую клетку | счётчик +0xFB ≥ походки +0xFD | `hero.js:872 unitCellTicks` | 0x41611C |
| подъём скелета | конец блока смерти | `units.js:2196 skeletonRises` | 0x413894:275 |

Точки вызова: `units.js:2162` (объявление войны), `units.js:2172` и
`units.js:2221` (`world.onUnitStrike`), `combat.js:280` (обработчик),
`combat.js:846-882` (герой).

Желаемое направление `gameplay event → animation` **сейчас не выполняется**, и
чинить это «в лоб» нельзя: темп боя в оригинале ЗАДАН длиной анимации.
Правильная развязка — §16.

---

## 8. Направления

**8 направлений**, без промежуточных, без квантизации угла в градусах.

```text
0 W   1 NW   2 N   3 NE   4 E   5 SE   6 S   7 SW      (таблицы 0x459AD4/0x459D14)
```

Функции:

* `hero.js:465 heroDirection(dx, dy)` — максимум скалярного произведения с
  `direction_steps` (не `atan2`: ряды сетки со сдвигом, угол врал бы);
* `hero.js:457 heroDirectionToCell(cell, from)` — перебор восьми соседей;
* `units.js:1168 directionTo(unit, target)` и `combat.js:921 directionTo`;
* при шаге направление ставится один раз, на границе клетки
  (`hero.js:836 unit.direction = direction`).

**Перевод в 3D yaw** (плоскость земли повёрнута на 45°):

```text
yaw(dir) = 45° × ((dir + 5) mod 8)     // выведено и проверено, см. HD_RENDERER_PASS2 §1
```

или напрямую из `direction_steps[dir]`: `yaw = atan2(sx/58, −sy/32)`.

---

## 9. Sprite renderer

`scene.js:45 render()` повторяет порядок мастера кадра `VA 0x4288D4`:

```text
1  подложка (вода)                scene.js:76-89   drawPlane
2  земля одним испечённым куском   ground.js:137    renderGround(visible)
3  дождь                           weather.js       renderRain
4  снаряды и вспышки               projectiles.js:287, :255
5  [склейка слоя суток] → аура light.js:34 → тени shadows.js:159 → новый слой
6  ОДНА очередь по глубине: объекты + юниты + кучи + герой   scene.js:150-215
7  амбиент, рамка выбора           ambient.js, scene.js:29
8  фильтр суток, огонь, струи      viewport.js:274 applyDaylight, projectiles.js:270
9  отложенные полупрозрачные копии (список 0x866F5C)         scene.js:239-268
```

* **Batching нет** — блит на кадр; экономия достигнута выпечкой земли в
  offscreen (`ground.js:62 bake`) и одним проходом смаза теней
  (`shadows.js:74 finishMask`).
* **Атласы есть**: 72 листа (у актёров 4095×1709), кадр несёт
  `{sheet, x, y, width, height, offset_x, offset_y}`; `viewport.js:36
  drawSprite` и `viewport.js:66 spriteReady` (ленивый заказ листа) —
  единственные точки доступа.
* **Палитры**: 256 палитр × 256 цветов X1R5G5B5 из `GRAPH.RES`
  (`konung2/res.py:42 read_palettes`). В паке они уже применены — PNG.
  Динамический выбор палитры остался в двух местах: тело и масть
  (`actor.js:392 actorBody`) и слой снаряжения (`actor.js:300 layerFrame`,
  ключ `слой:палитра`).
* **Прозрачность и блендинг**: `destination-out` (вырезы силуэтов), `lighter`
  (аура, огонь), `multiply` (фильтр суток), альфа 0.5 (просвечивающие копии).
* **Z-order / sorting rule** — самое важное:

```text
юнит-человек:  ключ = round(y) + 6                       actor.js:45-52
юнит-тварь:    ключ = round(y) + frame.offset_y + frame.height
постройка:     ключ = position.y + offset_y + max(h_main, h_walls)
                      − (флаг 0x08 ? h/4 : 0)
               konung2/world/geometry.py:137 Bounds.sort_key → bounds.sort_y
сортировка:    world.js:120 (объекты) + scene.js:143 (юниты) + слияние scene.js:157
```

То есть **sort by screen-Y нижнего края спрайта**, с поправкой на переднюю
стену. Разбор целиком — `docs/RENDER_DEPTH.md`.

**Использует ли геймплей данные сортировки?** Да, в одном месте:
`units.js:1352` — из нескольких юнитов под курсором побеждает тот, у кого ключ
глубины больше («нарисован позже»). Это единственная утечка (P1).

---

## 10. Освещение

Три независимых механизма, все данные уже в паке:

| Механизм | Данные | Код |
| --- | --- | --- |
| **Суточный фильтр** | кривая 21600 тактов → `levels [blue, green, red]`, каждое −100…+100 | `assets/daylight.json`, `daylight.js:42`, применение `viewport.js:274 applyDaylight` |
| **Постоянное освещение карты** | `map.lighting.fixed {frozen, levels}` — 7 карт из 53 (дворец −70/−50/−50, пещеры −1/−1/−1) | `daylight.js:22 fixedLighting`, таблица 0x4617B0 |
| **Локальный свет (аура)** | `terrain.ground[].light.glow` — готовая маска-картинка 114×64 на клетку; включается с такта 8100 или всегда | `light.js:20 lightActive`, `light.js:34 renderLightGlow` |

Точечных источников с радиусом, цветом и интенсивностью **в оригинале нет** —
свет запечён в маску клетки (`LIGHTS.RES`, 19 масок интенсивности,
`konung2/graph.py:44-50`). Fog of war отсутствует; «знание» глобальной карты —
отдельная система (`worldmap.js knownReset`).

Что можно отдать 3D-рендереру:

```cpp
struct RenderLight {           // из world.litCells
    Vec3  position;            // (cell.x, cell.y) → u/v; высота ~ 0
    Color color;               // тёплый: маска трогает только R и G
    float radius;              // 114×64 px ≈ один тайл земли
    float intensity;           // байт слоя 2 клетки, 0…31
};
struct RenderAmbient {         // из daylight.levels
    float redLevel, greenLevel, blueLevel;   // −100…+100
};
```

---

## 11. Тени

`shadows.js`. Три вида:

1. **Запечённая маска спрайта** — у каждого кадра актёра свой спановый слой
   тени (`konung2/heroes.py:26 SHADOW_TABLE_AT`), у построек — отдельный кадр
   `frames.shadow`.
2. Маски копятся в offscreen-слое и **делят яркость кадра пополам** одним
   блитом с альфой (`shadows.js:12-19` — арифметика `bg/2` из VA 0x440788).
3. **Наше расширение** — «живые тени»: смаз маски по направлению солнца
   (`shadows.js:29 shadowSettings`, `lightX −0.95, lightY 0.32`, длина до
   130 px по высоте солнца). Включается галочкой `dynamicShadowsNode`.

**Геймплейного значения тени не имеют вовсе** — ни один игровой модуль не
импортирует `shadows.js`. Подсистема удаляется целиком без последствий.

---

## 12. Effects / Spells / Particles

| Что | Геймплейная часть | Визуальная часть | Смешаны? |
| --- | --- | --- | --- |
| стрела, болт | `projectiles.js:71 projectileFire` → запись `{x, y, stepX, stepY, life, accuracy, strength, venom, side, shooter, target}` | `shot.frame ^= 1`, `renderProjectiles` | **да, в одной записи** |
| фаербол героя | `combat.js:948 heroCast`, та же запись + `free: true` | `sprite`, `anim`, `burst`, `blend: additive` | **да** |
| бросок кикиморы | `combat.js:300 kikimoraSpits` | тот же снаряд | да |
| вспышка попадания | нет | `projectiles.js:196 burstAt`, `bursts[]` | нет — чистый визуал |
| огонь на объектах | поджог: `buildingIgnite` (`buildings.js`) | `entities.js:305 drawObjectFire`, фаза от мировых часов | разделены |
| яд, зелья, лечение | `effects.js` целиком | визуала нет вовсе | **разделены** |
| дождь, снег, струи | нет | `weather.js` | разделены |
| кровь | отсутствует | отсутствует | — |

**Единственное реальное смешение — запись снаряда** (`projectiles.js:76-95`):
там рядом лежат `strength / venom / accuracy / side / target` (геймплей) и
`frame / anim / sprite / direction` (визуал). Плюс `height = 30`, которую
**вычитают из y** — то есть высота полёта неотличима от смещения по земле.

Ещё две мелочи: радиус попадания задан в экранных пикселях
(`projectiles.js:101 HIT_RADIUS_X = 30, HIT_RADIUS_Y = 46`), подшагов ровно 8
на такт (`projectiles.js:128`).

---

## 13. Equipment / character appearance

Внешность собирается **слоями кадра**, до 54 слоёв на запись
(`konung2/heroes.py:50 LAYER_COUNT`). Сценарий отрисовки — `actor.js:349
actorLayers` (VA 0x425DB4):

```text
слой 0                тело:   0, если body == 0, иначе 48 + body
до сценария           доспех (equipment.body), свой слой из класса предмета
далее по направлению  5 шагов из таблицы 0x4627D0 (rules.equipment_draw.script[dir]):
                      оружие руки / вторая рука / щит / лук / метательное,
                      каждый со своим условием (in_hand, melee, shooting,
                      not_shooting, at_rest) — actor.js:332 stepAllowed
```

Палитра слоя берётся **из предмета**, а не из юнита (`actor.js:300
layerFrame`, ключ `слой:палитра`); тело красится палитрой юнита
(`actor.js:392 actorBody`, ключ `game:body:palette`).

Состояние, которое HD-рендерер может получить **уже сейчас, без правок**:

```cpp
struct CharacterVisualState {
    int   bodyType;      // unit.body      (форма: женская, монах, воин…)
    int   palette;       // unit.palette   (масть)
    int   breed;         // unit.breed     (бит 0x40 — тварь, свой набор кадров)
    const char* game;    // unit.game      ("legend" или null)
    ItemRef helmet;      // unit.equipment.head
    ItemRef armor;       // unit.equipment.body
    ItemRef weaponRight; // unit.equipment.hand
    ItemRef weaponLeft;  // unit.equipment.off_hand   (щит или второе оружие)
    ItemRef ranged;      // unit.equipment.ranged
    ItemRef ammo;        // unit.equipment.ammo
    bool    rangedMode;  // чем бьётся сейчас (+0xEE)
};
```

Слотов «сапоги / перчатки / плащ» в игре нет. У каждого предмета в паке есть
`layer` и `palette` — это и будет ключ 3D-модели снаряжения.

---

## 14. Assets — карта конвейера

### 14.1 Оригинал → пак

| Тип | Оригинал | Формат | Кодек | Итог в паке |
| --- | --- | --- | --- | --- |
| персонажи, снаряжение | `HEROES.RES` 44.8 МБ | заголовок 0x49C0, 1400 записей, холст 256×150, якорь (127,144), 54 слоя, RLE + спановая тень | `konung2/heroes.py` | `assets/units/` (292) + листы |
| твари | `OBJECTS.RES` 53.4 МБ | 512 записей, свои наборы поз | `konung2/creatures.py` | `assets/creatures/` (99) |
| постройки, реквизит | `OBJECTS.RES` | main/walls/roof/shadow + `states`, якоря `0xC0` | `konung2/res.py`, `world/entities.py` | `assets/objects/` (3597) |
| земля | `GRAPH.RES` 2.7 МБ | 256 палитр + 1000 тайлов 114×64 | `konung2/graph.py` | `assets/ground/` (4192) |
| накладки ландшафта | `.KN2` слой + `OBJECTS.RES` | — | `konung2/kn2.py` | `assets/terrain_overlays/` (736) |
| локальный свет | `LIGHTS.RES` 145 КБ | 19 масок 114×64, дымка 64×43 | `konung2/graph.py` | `assets/light/` (2208) |
| интерфейс, курсоры, иконки | `INTERF.RES` 1.8 МБ | спрайты | `konung2/interf.py`, `cursors.py` | `assets/icons/` (367), `cursors/` (9) |
| эффекты, огни | `FLAMES.RES` 1.6 МБ | 7 анимаций | `konung2/objectanim.py`, `effects.py` | `assets/effects/` (74) |
| звук | `SOUNDS.RES` 69 МБ | таблица 1000 × {off, size}, PCM 22050/16/mono | `konung2/sounds.py` | `assets/sfx/` (1153), `audio/` (23 opus) |
| реплики | `KONUNG2/voices.res` 469 МБ | — | `konung2/voices.py` | `assets/voices/` (3563) |
| карта мира | `INTERF.RES` спрайт 4 | 884×709, сетка вшита в картинку | `konung2/worldmap.py` | `assets/worldmap/` |
| портреты, шрифты | `INTERF.RES`, `MENU.RES` | — | `konung2/interf.py` | `assets/icons/`, DOM-шрифты |
| данные (юниты, отряды, деревни) | `GAME.0…GAME.5` | записи по 0x100+ | `konung2/gamefile.py` (1945 строк) | `map.json` |
| карты | `1..54.KN2` | слои: земля 0x0, свет 0x6400, сетка 0x9600 | `konung2/kn2.py`, `grid.py` | `map.json` |
| квесты | `QUESTS.RES` | 152 диалога, 103 токена | `konung2/quests.py` | `map.json → units[].dialog` |

### 14.2 Пак → клиент

* `manifest.json`: `content_id`, `start_map`, `files[]` с sha256 и размерами —
  версия подставляется в адрес (`content.js:19 contentUrl`).
* `shared.json`: `hero` (анимации, слои, листы, правила), `creatures`,
  `projectiles`, `weather`, `settlements`, `reputation`, `effects`, `palettes`.
* `maps/<N>/map.json`: всё описанное в §5.
* Загрузка: `content.js:60 loadImage` → **`ImageBitmap`**, а не `Image`
  (иначе браузер перераспаковывает 27-МБ листы десятками раз за игру).
* Ленивая догрузка листа — только через `viewport.js:66 spriteReady`.

**Сжатия и палитр в паке уже нет** — всё PNG и Opus. Метаданные кадра:
`{sheet, x, y, width, height, offset_x, offset_y, record, shadow}`.

---

## 15. Renderer dependencies внутри gameplay

Механический замер (число упоминаний `context.` / `canvas` / `drawImage` /
`getImageData` / `view.`):

```text
combat.js 0   orders.js 0   warband.js 0   village.js 0   effects.js 0
worldmap.js 0 exits.js 0    dialog.js 0    loot.js 6      units.js 14   hero.js 27
```

| # | Место | Что делает | Severity |
| --- | --- | --- | --- |
| 1 | `units.js:1299 unitPixelHit` + `:1331 unitAt` | Выбор юнита мышью — **чтением альфы пикселя листа спрайта** через 1×1 канвас-пробу. Через него идут ВСЕ приказы игрока (`combat.js:711 orderAt`), прицел, курсор и агент (`agent.js:203 aimAt`, бьющий «на 40 точек выше якоря») | **P0** |
| 2 | `units.js:2172, :2221` + `combat.js:846 resolvePendingHit` | Урон, запуск снаряда и расход стрелы — **на конкретном кадре спрайта** (5/7/9, «всего−6»); `units.js:2162` — объявление войны на кадре 2 | **P0** |
| 3 | `units.js:1001 swingHalf`, `:1527 strikeFrames`, `:2206` | Игровые длительности берутся из **длины набора кадров** `actorFrames(...).length` — темп тренировки, кадр выстрела, подъём скелета | **P0** |
| 4 | `units.js:1352` | Из нескольких юнитов под курсором побеждает больший **ключ глубины** («нарисован позже») | **P1** |
| 5 | `combat.js:1071` | Дальность до постройки: `hypot(dx, dy*1.8)/58` — **экранная** арифметика в игровой проверке | **P1** |
| 6 | `projectiles.js:71, :101` | `height = 30` вычитается из `y` (высоты как отдельной величины нет); радиусы попадания 30×46 — экранные пиксели | **P1** |
| 7 | `warband.js:32 KEEP_RANGE = 0x348` | Порог выхода из боя и удержания агро — 840 **мировых пикселей** по каждой оси. Канон, но единица — пиксель, не клетка | **P1** |
| 8 | `hero.js:370 unitUpdateBuilding` | Симуляция вычисляет чисто рендерные флаги `insideBuilding / overlay / bright / roofBuilding` из битов клетки | **P1** |
| 9 | `hero.js:1220 centreOn`, `:1232 edgeScroll` | Геймплейный модуль пишет прямо в `view.cameraX/Y` | **P2** |
| 10 | `units.js:2274 renderUnit`, `:2328 renderUnitsOverlay`, `hero.js:1143 renderHero`, `:1184 drawHeroAtDepth`, `:1122 drawSelectionCircle`, `loot.js drawPile` | Отрисовка живёт внутри геймплейных модулей | **P2** |
| 11 | `input.js:235,241,448,475`, `ui.js:1166,1221` | `render()` из обработчиков ввода | **P2** |
| 12 | `actor.js:180 actorSheetPaths`, `app.js:500 requeueByDistance` | Стриминг листов зависит от `view.zoom/width` | **P2** (так и должно быть) |

Чего **нет** (проверено): нет `if (frame == N) DealDamage()` вне таблицы
`STRIKE_FRAME`; нет `position += spriteOffset` (смещения кадра применяются
только при блите); нет игровых расчётов в координатах камеры — всё, что
похоже, считается в мировых пикселях, от камеры не зависящих.

---

## 16. Presentation Bridge — предложение

Минимальный API, без переписывания движка. Строится **читателем поверх
существующих массивов**, ничем не владеет.

```cpp
// ---- камера -------------------------------------------------------------
struct CameraState {
    Vec2  center;        // view.cameraX, view.cameraY   (мировые пиксели)
    float zoom;          // view.zoom
    Vec2  viewport;      // view.width, view.height
    float dpr;
    float perspective;   // perspective.spread, 0 — плоская изометрия
};

// ---- сущности -----------------------------------------------------------
struct RenderEntity {
    uint64_t id;              // unit.slot | (homeMap << 32)
    Vec2  previousPosition;   // step ? {step.fromX, step.fromY} : currentPosition
    Vec2  currentPosition;    // unit.x, unit.y   (уже непрерывные)
    uint8_t direction;        // 0…7  → yaw = 45° × ((dir + 5) & 7)
    VisualId  visual;         // {game, body, palette, breed}
    AnimationId animation;    // {stance, pose} — блок таблицы движка
    uint16_t frame;           // unit.frame
    float    animationPhase;  // unit.frameTime / 0.078 → 0…1 внутри кадра
    float    sortKey;         // actor.unitSortKey(unit) — для проверки паритета
    EquipmentSet equipment;   // §13 CharacterVisualState
    uint32_t flags;           // ALIVE|HIDDEN|BRIGHT|OVERLAY|INSIDE_BUILDING|
                              // SELECTED|RUNNING|MOVING
    int32_t  health, maxHealth;
};

struct RenderProp {           // world.objects[]
    uint32_t recordSlot;
    uint16_t resourceSlot, palette, state;
    Vec2     position;        // object.position
    Rect     bounds;          // object.bounds (draw_x/y/width/height)
    float    sortKey;         // bounds.sort_y
    uint32_t flags;           // HAS_WALLS|HAS_ROOF|ROOF_HIDDEN|BRIGHT_MAIN|BURNING
};

struct RenderTile {           // terrain.ground[]
    uint16_t row, col;
    uint16_t lower, upper;    // два наложенных тайла
    Vec2     origin;
    uint8_t  lightMask;
};

struct RenderLight  { Vec2 position; Color color; float radius, intensity; };
struct RenderEffect { Vec2 position; Vec2 velocity; float height;
                      EffectId sprite; uint16_t frame; uint32_t flags; };

// ---- снимок -------------------------------------------------------------
struct RenderWorldSnapshot {
    uint64_t           tick;       // clock.ticks
    float              tickPhase;  // фаза внутри такта, для интерполяции
    uint32_t           daylight;   // упакованные levels[3]
    CameraState        camera;
    Span<RenderTile>   ground;     // статика: отдаётся раз на карту
    Span<RenderProp>   props;      // статика + state: раз на карту и по событию
    Span<RenderEntity> entities;
    Span<RenderLight>  lights;
    Span<RenderEffect> effects;
};
```

Правила:

1. Рендерер — **только потребитель**. Никаких обратных вызовов в мир.
2. `ground` / `props` строятся один раз при `enterMap` и обновляются событием
   (смена `state`, поджог, скрипт `OBJECT`), а не каждый кадр.
3. `entities` / `effects` / `lights` — каждый кадр; на карте это десятки
   записей, цена ничтожна.
4. Мировые пиксели отдаём **как есть**; перевод в плоскость
   (`u = x/58 + y/32`, `v = x/58 − y/32`) делает рендерер.

**Развязка «кадр → удар» без переписывания боя.** Сейчас удар объявляет
`world.onUnitStrike(unit, hand)` (`units.js:2172`, обработчик `combat.js:280`).
Достаточно добавить рядом второй, чисто уведомительный хук — и HD-рендерер
получит событие с игровой стороны, а не будет угадывать по кадру:

```js
world.onCombatEvent?.({ type: "strike", unit, hand, target, tick: clock.ticks });
```

Симуляция при этом не меняется вовсе: она как играла кадрами, так и играет.

---

## 17. Интерполяция

| Объект | Интерполируется? | Почему |
| --- | --- | --- |
| **игрок** | **уже да** | `hero.js:911 unitMove`: `t = step.time / step.duration`, `x = fromX + (toX−fromX)·t`. Отдельного «тика героя» нет |
| **монстры, NPC** | **уже да** | тот же `unitMove` — одна реализация на всех (`units.js:2088`) |
| **снаряды** | да | `projectiles.js:135` — 8 подшагов на такт по `dt`, между подшагами линейно |
| **объекты** | не нужно | статичны; смена `state` дискретна по смыслу |
| **анимация** | **да, но нужен наш вклад** | `unit.frame` целый, но `unit.frameTime` даёт фазу 0…0.078 → готовый `alpha` для блендинга поз 3D-скелета |
| **камера** | нет, и правильно | `edgeScroll` — дискретные шаги 0x39/0x20; `cameraFollow` — мгновенно за юнитом, который сам едет плавно |
| **направление** | нет | 8 дискретных значений, меняется только на границе клетки. Для 3D нужен свой сглаживатель yaw, иначе разворот «щелчком» |

**Классический `interpolate(A, B, alpha)` нам не нужен.** Мир уже отдаёт
непрерывные позиции на любой частоте кадров; причина — порт с самого начала
разделил «решать по тактам, рисовать по кадрам» (`units.js:1689-1704`).

Реальная работа по интерполяции для HD:

1. смешивание поз скелета по `animationPhase`;
2. плавный поворот модели между восемью направлениями;
3. `previousPosition` для motion blur / TAA, если понадобится (берётся из
   `unit.step.fromX/fromY` даром).

---

## 18. Threading

* **Один поток.** Вся симуляция и вся отрисовка — в главном потоке.
* Есть **два воркера, оба служебные**:
  * пульс такта `app.js:1446` — `setInterval(100)` в воркере, будит
    `animationFrame`, когда браузер душит rAF у скрытой вкладки;
  * распаковка картинок — внутри `createImageBitmap` (`content.js:66`), это
    делает браузер вне главного потока.
* **Локов нет**, потому что нет параллелизма.
* **Глобальное состояние есть и оно намеренное**: `world` (`world.js:6`),
  `hero` (`hero.js:14`), `units` (`units.js:42`), `clock`, `view`,
  `projectiles`, `loot`, `combat`, `daylight`. Всё это живые модульные
  синглтоны, доступные снаружи через `window.knyaz2` (`app.js:1465`).

Схема `Simulation thread → immutable RenderSnapshot → Render thread` возможна
в будущем, но сейчас не нужна и вредна:

* профилировщик (`profiler.js`, `probe()` вокруг каждого прохода) показывает,
  что узкое место — не симуляция, а слои кадра (ночной кадр ~33 мс: слои 12.6 +
  смаз теней 20.8) и поиск пути (16–28 мс на вызов);
* весь мир — мутабельные объекты с циклическими ссылками (`unit.target`,
  `unit.goalTarget`, `hero.insideBuilding`), их сериализация в снимок каждый
  кадр стоила бы дороже выигрыша.

**Рекомендация: первый этап — single-threaded.** Границу снимка (§16)
проектируем так, чтобы позже её можно было сделать копирующей, но копию сейчас
не делаем.

---

## 19. Что делать со старым рендерером

| Подсистема | Оставить | Заменить | Использовать как данные |
| --- | --- | --- | --- |
| Map loader (`konung2/*`, `content/builder.py`, `world.js:87`) | да, целиком | — | да, источник геометрии карты |
| Collision и навигация (`hero.js:269,618,806`, `units.js:2354`) | да, целиком | — | да, сетка 256×160 → навмеш |
| Sprite renderer (`scene.js`, `viewport.js:36`, `entities.js`, `ground.js`) | как эталон на время перехода | да | — |
| Animation **state** (`konung2/heroes.py`, `actor.js:215/271`, `units.js:2136`) | **обязательно** — это симуляция | — | да, блок+кадр → клип 3D |
| Sprite animation **playback** (`drawActor`, `drawLayerFrame`) | — | да | да, число кадров блока = длина клипа |
| Camera (`viewport.js:84-200`) | модель и клампы | матрицу | да, `cameraX/Y/zoom` → орто-камера |
| Lighting (`daylight.js`, `light.js`) | — | да | да, уровни суток + маски клеток |
| Shadows (`shadows.js`) | — | да (удалить) | нет, ничего не даёт |
| Particle renderer (`weather.js`, `bursts`, `renderFire`) | — | да | — |
| Projectile **entity** (`projectiles.js:71-190`) | да | — | да, позиция, скорость, цель |
| Perspective (`perspective.js`) | — | да (в 3D это настоящая камера) | да, 32–35 % как эталон ощущения |
| Depth sorting (`actor.js:45`, `geometry.py:137`) | пока нужен для клика | да (z-buffer) | да, эталон паритета |
| Picking (`units.js:1299`) | **пока обязателен** | позже — 3D raycast | — |
| UI (`ui.js`, `styles.css`, DOM) | **целиком, менять нечего** | — | — |
| Звук (`sound.js`, `sfx.js`, `soundscape.js`) | да | — | — |
| Selfcheck (`selfcheck.js`, 12 правил света и глубины) | да | — | да, **готовый тест паритета** |

---

## 20. Можно ли подключить второй рендерер параллельно?

**Да, и это самый дешёвый первый шаг из всех возможных.** Основания:

1. Отрисовка вызывается **ровно один раз** — `app.js:252 probe("рисование",
   render)`. Ни один игровой модуль не зависит от того, что `render()` сделал.
2. Всё состояние мира уже опубликовано наружу: `window.knyaz2` (`app.js:1465`)
   отдаёт `world, view, hero, units, loot, combat, daylight` и производные.
3. Интерфейс — DOM, а не канвас: второй рендерер не обязан рисовать ни панель,
   ни пояс, ни диалог.
4. Симуляция уже умеет идти без картинки (воркер-пульс, `app.js:1448`) — «нет
   кадра» для неё штатная ситуация.
5. Есть готовый арбитр правильности — `knyaz2.selfcheck()` (12 правил света и
   глубины, снятых с exe) и `docs/RENDER_DEPTH.md`.

Целевая схема на переходный период:

```js
// app.js, вместо одной строки :252
if (dirty || view.dirty) {
  view.dirty = false;
  if (renderMode !== "hd")     probe("рисование", render);                     // старый
  if (renderMode !== "legacy") probe("рисование HD", () => hd.render(buildSnapshot()));
}
```

Старый рендерер остаётся эталоном: `F1` — legacy, `F2` — HD, `F3` —
side-by-side (два холста рядом, одна камера).

---

## 21. Первый Proof of Concept

**Задача:** тот же мир, тот же герой, но нарисован капсулой в 3D, и капсула
ходит синхронно со спрайтом.

### Файлы, которые надо ТРОНУТЬ (три, ~10 строк правок)

| Файл | Правка |
| --- | --- |
| `knyaz2/web/static/index.html:33` | добавить рядом `<canvas id="world-hd" hidden>` |
| `knyaz2/web/static/dom.js` | экспортировать новый узел |
| `knyaz2/web/static/app.js:250-253` | развилка режима отрисовки (см. §20) + клавиши F1/F2/F3 рядом с обработчиком Escape (`app.js:296`) |

### Файлы, которые надо СОЗДАТЬ (два)

**1. `knyaz2/web/static/snapshot.js` (~70 строк)** — сборка снимка §16.

```js
import { world } from "./world.js";
import { hero } from "./hero.js";
import { units, roster } from "./units.js";
import { view } from "./viewport.js";
import { clock } from "./clock.js";
import { daylight } from "./daylight.js";
import { unitSortKey } from "./actor.js";

// мировые пиксели → плоскость земли в клетках-диагоналях
export function worldToPlane(x, y) { return { u: x / 58 + y / 32, v: x / 58 - y / 32 }; }

export function buildSnapshot() {
  return {
    tick: clock.ticks,
    daylight: daylight.levels,
    camera: { center: worldToPlane(view.cameraX, view.cameraY),
              zoom: view.zoom, width: view.width, height: view.height },
    entities: roster(units).filter((u) => !u.hidden).map((u) => ({
      id: u.slot ?? 0,
      plane: worldToPlane(u.x, u.y),
      yaw: 45 * ((u.direction + 5) & 7),
      pose: u.pose, stance: u.stance, frame: u.frame,
      phase: (u.frameTime ?? 0) / 0.078,
      body: u.body, palette: u.palette, beast: Boolean(u.beast),
      alive: u.alive !== false, sortKey: unitSortKey(u),
    })),
    ground: world.ground,      // отдаём ссылкой: список статичен
    props: world.objects,
  };
}
```

**2. `knyaz2/web/static/render3d.js` (~180 строк)** — WebGL2 без библиотек:
одна ортографическая камера, один шейдер, две геометрии (плоскость и капсула).

* камера: `yaw 45°`, `pitch asin(16/29) = 33.4854°`, орто-высота
  `view.height / view.zoom / 32` (в клетках);
* пол: для каждой клетки `terrain.ground[]` — quad 1×1 в плоскости u/v, цвет по
  `tiles.lower` (пока просто хеш индекса в цвет);
* стены: для каждой клетки `terrain.blocked[]` — куб высотой 1.5;
* герой: капсула в `plane(hero)`, поворот `yaw`, высота 1.8;
* остальные юниты: капсулы другого цвета;
* фон: уровень суток из `daylight.levels`.

### Порядок проверки (что считать успехом)

1. `F1` — старый кадр, всё как было (регрессии нет).
2. `F2` — 3D-мир: капсула стоит там же, где стоял герой; идёт по клику той же
   дорогой; повороты совпадают.
3. `F3` — side-by-side: клетка под курсором совпадает в обоих (проверяется
   `knyaz2.heroCellAt` от `screenToWorld`).
4. `knyaz2.selfcheck()` — 12/12 в режиме `F1` (доказывает, что мир не тронут).
5. Числовая сверка глубины: для каждой пары «юнит перед домом» знак
   `unitSortKey(u) − object.bounds.sort_y` обязан совпадать со знаком
   z-разности в 3D. Это заменяет глазную проверку.

Ни одной строки в `units.js`, `combat.js`, `hero.js`, `warband.js`,
`dialog.js` менять не надо.

---

## 22. Чего НЕ делаем на этом этапе

Подтверждаю ограничения из задания и добавляю проектные:

* никакого PBR, Unreal, Unity, новых моделей и шейдеров;
* не трогаем `project/maps` и `project/story` — это распакованная игра, канон
  только для чтения;
* не меняем формат пака: смена формата данных не падает, а **тихо съезжает**
  (угол сетки карты мира однажды увёл значки на 140 точек, потому что
  `content_build` остался старым);
* не оптимизируем и не рефакторим по дороге;
* после любой правки, задевающей канон, гоняем `pytest` (сейчас 971 тест).

---

# Итоговые артефакты

## A. Architecture map

```text
Legacy Engine  (knyaz2/web/static, 60 модулей)
 ├─ Simulation   app.js:175 animationFrame  ← единственная точка входа такта
 │   ├─ clock.js         мировой такт 78 мс, аккумулятор, фазы
 │   ├─ units.js:1643    unitsTick — ИИ, приказы, движение, кадры, удары
 │   ├─ hero.js          движение и поиск пути ЛЮБОГО юнита (не только героя)
 │   ├─ combat.js        strike / applyDamage / combatTick / orderAt
 │   ├─ warband.js       отряды, вражда, зона боя (KEEP_RANGE)
 │   ├─ orders.js, village.js, effects.js, dialog.js, worldmap.js, exits.js
 │   └─ projectiles.js   снаряды (запись = геймплей + визуал)
 ├─ World        world.js (map, ground, objects, images), mapstate.js, save.js
 ├─ Entities     units[] + hero (актёры), world.objects[] (постройки/реквизит),
 │               loot[], projectiles[], bursts[]
 ├─ Animation    konung2/heroes.py (таблица блоков) → shared.json → actor.js
 │               units.js:2136-2250 (кадр за такт, удар по таблице кадров)
 ├─ Rendering    scene.js:45 render() → viewport.js / ground.js / entities.js /
 │               shadows.js / light.js / weather.js / perspective.js
 └─ Assets       konung2/*.py (кодеки) → knyaz2/content/builder.py →
                 content_build/{manifest,shared,maps/N/map}.json + assets/
```

## B. Render dependency map (gameplay → graphics)

```text
[ВЫБОР ЮНИТА]      input.js → combat.js:711 orderAt → units.js:1331 unitAt
                             → units.js:1299 unitPixelHit → альфа пикселя листа
[УДАР]             units.js:2140 счётчик кадра → :2166 strikeHand
                             → world.onUnitStrike → combat.js:280 → strike/projectileFire
[СТРЕЛЬБА]         units.js:1527 strikeFrames("всего−6") → тот же путь + ammoSpend
[ОБЪЯВЛЕНИЕ ВОЙНЫ] units.js:2160 swingDeclares(кадр 2) → warbandSwing
[ТЕМП ТРЕНИРОВКИ]  units.js:1001 swingHalf = actorFrames(...).length / 2
[ПРИОРИТЕТ КЛИКА]  units.js:1352 max(unitSortKey) — «нарисован позже»
[ДАЛЬНОСТЬ ПОДЖОГА] combat.js:1071 hypot(dx, dy*1.8)/58
[ВЫСОТА СНАРЯДА]   projectiles.js:71 y = shooter.y − 30
[ФЛАГИ РЕНДЕРА]    hero.js:370 unitUpdateBuilding → insideBuilding/overlay/bright
[КАМЕРА]           hero.js:1220 centreOn, :1232 edgeScroll → view.cameraX/Y
```

Всё остальное (`combat`, `orders`, `warband`, `village`, `effects`,
`worldmap`, `exits`, `dialog`) от графики **не зависит вовсе** — нулевые
счётчики §15.

## C. Coordinate system document

```text
tile       ground_grid 160×80, ромб 114×64, шаг 116×32, сдвиг нечёт. ряда 58
           origin: konung2/world/geometry.py:67

cell       navigation_grid 256×160, «кирпич» 58×16, нечёт. ряды сдвинуты на 29
           anchor:  x = col*58 + (row&1 ? 29 : 58);  y = row*16 + 16   (hero.js:201)
           обратно: hero.js:232 heroCellAt (ромбическая поправка)
           соседи:  hero.js:334 (N/S через ДВА ряда)

world      float, мировые пиксели = плоская изометрия. Origin — левый верх карты.
           X вправо, Y вниз, Z НЕТ.
           плоскость земли: u = x/58 + y/32 ;  v = x/58 − y/32

camera     view.cameraX/Y — ЦЕНТР вида; zoom 0.1…2.5; поворота нет.
           матрица viewport.js:333; обратно viewport.js:397 (+перспектива).
           клампы по map.coordinates.camera {left,right,top,bottom}

direction  8 значений: 0 W, 1 NW, 2 N, 3 NE, 4 E, 5 SE, 6 S, 7 SW
           шаги: (−58,0) (−29,−16) (0,−32) (29,−16) (58,0) (29,16) (0,32) (−29,16)
           3D: yaw = 45° × ((dir + 5) mod 8)

elevation  ОТСУТСТВУЕТ. Суррогаты: bounds.sort_y (глубина),
           projectiles height=30 (вычтена из y), биты клетки 15/21/22.
           Мосты, лестницы, ярусы — нарисованы, но логически плоские.
```

## D. RenderSnapshot proposal

См. §16 целиком. Ключевое: снимок **читающий**, статика (`ground`, `props`)
отдаётся раз на карту, динамика (`entities`, `effects`, `lights`) — каждый
кадр; ни одна структура не владеет игровым объектом.

## E. Migration risk table

| Приоритет | Риск | Место | Что делать |
| --- | --- | --- | --- |
| **P0** | Попиксельный выбор юнита по спрайту | `units.js:1299`, `:1331` | На PoC — оставить legacy-пробу (она работает от данных листа, а не от кадра на экране). Позже: 3D raycast по капсуле + сверка с legacy на тех же координатах |
| **P0** | Урон и снаряд на кадре анимации | `units.js:2166-2221`, `combat.js:846` | Не трогать логику. Добавить уведомительный `world.onCombatEvent` (§16) и кормить им HD-рендерер |
| **P0** | Игровые длительности из длины набора кадров | `units.js:1001`, `:1527`, `:2206` | Зафиксировать число кадров каждого блока как **данные** (`shared.json → animations`), а не как свойство картинки. HD-клип обязан иметь ту же длину в тактах |
| **P1** | Ключ глубины как арбитр клика | `units.js:1352` | Оставить `unitSortKey` доступным рендереру; после перехода на raycast — сверять оба ответа в тесте |
| **P1** | Высота снаряда вычтена из y | `projectiles.js:71` | Добавить в снимок поле `height` отдельно (значение уже известно: 30), y не менять |
| **P1** | Экранные радиусы попадания 30×46 | `projectiles.js:101` | Перевести в клетки в снимке; в симуляции оставить как есть |
| **P1** | Дальность поджога через `hypot(dx, dy*1.8)` | `combat.js:1071` | Оставить, задокументировать; при 3D-луче использовать ту же формулу |
| **P1** | `KEEP_RANGE` 840 пикселей | `warband.js:32` | Ничего не делать: мировые пиксели останутся мерой мира и в 3D |
| **P1** | Рендер-флаги считает симуляция | `hero.js:370` | Оставить: это дешёвая и уже проверенная классификация; рендерер читает |
| **P2** | Отрисовка в геймплейных модулях | `units.js:2274`, `hero.js:1143` | Позже вынести в `render_units.js`; на PoC не мешает |
| **P2** | `render()` из обработчиков ввода | `input.js`, `ui.js` | Заменить на `view.dirty = true` (механизм уже есть, `viewport.js:86`) |
| **P2** | Камера из геймплея | `hero.js:1220`, `:1232` | Позже — через команду презентации |

## F. Первый PoC — что менять

**Тронуть 3 файла:** `index.html` (второй холст), `dom.js` (экспорт узла),
`app.js:250-253` + `:296` (развилка отрисовки и клавиши F1/F2/F3).
**Создать 2 файла:** `snapshot.js` (~70 строк) и `render3d.js` (~180 строк).
Подробности и критерии успеха — §21.

Ни строки в `units.js`, `combat.js`, `hero.js`, `warband.js`, `dialog.js`.

## G. Краткий вывод

**1. Можно ли оставить симуляцию практически без изменений?**
Да. Такт фиксированный (78 мс, `clock.js:22`), решения заперты тактом
(`units.js:1705`), позиции непрерывные (`hero.js:911`), от FPS ничего не
зависит. Для PoC изменений в симуляции **не требуется вовсе**; для полноценного
HD-рендерера нужен один добавленный уведомительный хук.

**2. Можно ли полностью заменить рендерер?**
Да — весь `scene.js`, `viewport.js` (отрисовочная часть), `ground.js`,
`entities.js`, `shadows.js`, `light.js`, `weather.js`, `perspective.js`.
Интерфейс переносить не надо: он на DOM. Не заменяются три вещи, пока не
появится 3D-эквивалент: попиксельное попадание по юниту, таблица кадров удара
и ключ глубины как арбитр клика.

**3. Какие 3–5 зависимостей мешают сильнее всего?**
1. `units.js:1299 unitPixelHit` — выбор юнита читает альфу спрайта (через это
   идут ВСЕ приказы игрока);
2. `units.js:2166 / combat.js:846` — урон и запуск снаряда на конкретном кадре
   (5/7/9, «всего−6»);
3. `units.js:1001, :1527` — игровые длительности из длины набора кадров;
4. `projectiles.js:71` — высота полёта вычтена из `y`, отдельной Z не
   существует нигде в мире;
5. `units.js:1352` — порядок отрисовки решает, по кому кликнули.

**4. Какой минимальный код нужен для параллельного HD-рендерера?**
Около 250 строк нового кода (`snapshot.js` + `render3d.js`) и ~10 строк правок
в трёх существующих файлах. Старый рендерер остаётся эталоном, переключение
F1/F2/F3, паритет проверяется числами: `knyaz2.selfcheck()` (12 правил) и
сверка знака `unitSortKey − bounds.sort_y` с z-разностью в 3D.
