# Редактор карт: концепция и спецификация API

Дата: 25.08.2026. Статус: концепция согласуется, API v2 строится.

## Зачем переделываем

Первый живой прогон (25.08) показал: фазы 1–12 дали МЕХАНИКИ, но не
РЕДАКТОР. Конкретные провалы:

1. **Правки-призраки.** Поставленный враг виден только в той сессии,
   где его поставили: живой юнит умирает с F5, запись лежит в проекте
   и оживёт лишь пересборкой. Для человека это «врагов нет — не
   работает».
2. **Нет цикла Build→Play.** Пересборка — консольная команда вне
   редактора; редактор не знает, собран ли пак, и не умеет собрать.
3. **Предпросмотр врёт.** Здание из каталога рисуется сырыми слоями
   поверх живой сцены: чёрный интерьер без пола, «стирает» текстуры.
4. **Удаление неочевидно.** Добавленный объект убирается только
   правкой JSON руками.
5. **Тормоза.** Каждый мазок перепекает весь видимый слой земли;
   каталог тянет большие картинки без миниатюр.
6. **Нет концепции.** Панель — свалка кнопок, а не инструментов.

## Видение (равнение на Heroes III / WarCraft III)

Редактор — ОТДЕЛЬНОЕ приложение (UI собирается в Claude Design),
которое говорит с дев-сервером по HTTP JSON API. Классическая
трёхпанельная раскладка:

```
┌────────────┬──────────────────────────────┬──────────────┐
│ ПАЛИТРА    │  ХОЛСТ КАРТЫ                 │ ИНСПЕКТОР    │
│ инструмент │  (рендер из данных проекта,  │ свойства     │
│ + каталог  │   не из живой игры)          │ выбранного   │
│ текущего   │                              │              │
│ инструмента│  [мини-карта]                │ [слои]       │
└────────────┴──────────────────────────────┴──────────────┘
  строка состояния: карта · счётчики · Build ▶ · Play ▶
```

Инструменты (вкладки палитры, как в H3):

| Инструмент | Аналог H3/WC3 | Что правит |
|---|---|---|
| Ландшафт | Terrain brush | тайлы низ/верх, свет клетки (layer1/2.png) |
| Вода | Water | подложка 16×32, Lake/Stream, тайл |
| Проходимость | Passability | биты клетки: глушь, стрелы, выход, признаки |
| Объекты | Object palette | здания и реквизит (T_OBJECTS) |
| Декор | Doodads | оверлеи земли (T_DYNAMIC): берега, кувшинки |
| Существа | Creatures | юниты: жители, твари, ВРАГИ (через отряды) |
| Отряды | — (наша механика) | warbands: кто на кого бросается, зоны |
| Клады | Treasure | кучи и тайники |
| Событ< | Events/Triggers | выходы, диалоги, квесты (позже) |

### Три принципа, снимающие «правки-призраки»

1. **Проект — единственный источник истины.** Редактор читает и пишет
   `project/maps/NN_*` (grid.txt, layer*.png, map.json, scenario.json).
   Пак — производная. Никаких правок «в живую сессию».
2. **Холст рендерится ИЗ ПРОЕКТА.** API отдаёт полное состояние карты
   (все слои с учётом draft-правок) + готовые картинки пака (кадры,
   тайлы, листы). UI рисует сам и потому НИКОГДА не расходится с тем,
   что будет после сборки. F5 ничего не теряет.
3. **Build и Play — кнопки редактора.** Build зовёт пересборку карты
   через API (фоновый процесс с прогрессом), Play открывает игру на
   собранном паке. Разрыв «поставил — не увидел» исчезает: увидел на
   холсте сразу (из проекта), в игре — после Build.

## Модель данных (сущности API)

Всё, что оканчивается на `*_add`/`editor_*`, — draft-слой в
scenario.json; остальное — прямые данные проекта.

| Сущность | Хранение | Ключ |
|---|---|---|
| meta | map.json: имя, номер, light_flag | номер карты |
| terrain | layer1.png (пары тайлов), layer2.png (свет) | row 0-159, col 0-79 |
| water | map.json `light`: 16×32 байт | row 0-15, col 0-31 |
| cells | grid.txt 256×160 LO:HI | row 0-255, col 0-159 |
| objects | map.json `objects` (T_OBJECTS, 1000×36) | slot |
| overlays | map.json `dynamic` (T_DYNAMIC, 1000×12) | slot |
| units | пак (жители из GAME) + scenario `editor_units*` | id (`unit_N` / `unit_new_*`) |
| warbands | пак (отряды из GAME) + scenario `editor_warbands_add` | side |
| loot | пак + scenario `editor_loot*` | id (`pile_N` / `pile_new_*`) |
| каталоги | пак: тайлы GRAPH, объекты, бестиарий, вещи | slot / breed / class |

## API v2

База: `http://127.0.0.1:8767/editor/api/…`, JSON, UTF-8.
CORS: `Access-Control-Allow-Origin: *` на ВСЕХ ответах + OPTIONS
(преflight) — UI живёт на чужом origin (Claude Design / artifacts).
Дев-сервер локальный, наружу не выставляется — поэтому `*` допустим.

Ошибки: `{ "ok": false, "note": "почему" }` + HTTP 400/404.
Успех: `{ "ok": true, ... }`.

### Чтение

```
GET /editor/api/maps
  → { ok, maps: [{ map, dir, name }] }            # все карты проекта

GET /editor/api/maps/{n}
  → { ok, meta: { map, name, dir, light_flag },
      water:    { tile, stream, count, rows: ["hex64" × 16] },
      objects:  { records: [{ slot, sprite, resource_slot, palette,
                              state, x, y }] },     # палитра уже РАЗ-
      overlays: { records: [{ slot, id, x, y }] },  # решённая, из kind
      draft:    { units_add, units_patch, loot_add, loot_patch,
                  props_patch, warbands_add },      # scenario.json как есть
      counters: { units, loot, warbands } }         # из пака, если собран

GET /editor/api/maps/{n}/terrain
  → { ok, rows: 160, cols: 80,
      lower: [[…80] × 160], upper: [[…]], light: [[…]] }
      # индексы тайлов, 0 = пусто (внутри PNG лежит индекс+1)

GET /editor/api/maps/{n}/cells
  → { ok, rows: 256, cols: 160, cells: ["LO:HI" × 160] × 256 }

GET /editor/api/maps/{n}/pack
  → { ok, built: bool, units: N, warbands: N, loot: N, mtime }
      # что лежит в СОБРАННОМ паке (для сравнения с draft)

GET /editor/api/catalog/tiles?page=0        # 50 на страницу, превью-URL
GET /editor/api/catalog/objects?page=0      # 24 на страницу: url, слои,
                                            #   размеры, якоря
GET /editor/api/catalog/bestiary            # 23 породы: превью, масти,
                                            #   образцовые числа
GET /editor/api/pack/units/{n}              # юниты собранного пака карты
                                            #   (жители — их redактор
                                            #   патчит, не создаёт)
```

Все картинки (тайлы, кадры объектов, листы тварей) UI берёт напрямую:
`GET /content/<путь-из-каталога>` — уже работает, тот же сервер.

### Запись (мутации)

Существующие ручки v1 остаются рабочими и получают зеркала в v2-стиле;
семантика та же (они уже проверены тестами и ритуалами):

```
POST /editor/api/maps/{n}/terrain   { row, col, lower?, upper?, light? }
POST /editor/api/maps/{n}/water     { row?, col?, value? | stream? | tile? }
POST /editor/api/maps/{n}/cells     { row, col, blocked?, solid?, exit?,
                                      transparent?, inner?, light?,
                                      upoff?, object? }
POST /editor/api/maps/{n}/objects   { add: { slot, palette, state, x, y } }
DELETE /editor/api/maps/{n}/objects/{slot}      # запись из T_OBJECTS
POST /editor/api/maps/{n}/overlays  { add: {…} | slot, x?, y?, id? }
DELETE /editor/api/maps/{n}/overlays/{slot}
POST /editor/api/maps/{n}/units     { id, patch }   # patch юнита пака
                                    # или unit_new_*: запись целиком
DELETE /editor/api/maps/{n}/units/{id}          # removed: true / из add
POST /editor/api/maps/{n}/warbands  { row, col, side? }
DELETE /editor/api/maps/{n}/warbands/{side}
POST /editor/api/maps/{n}/loot      { id, patch }
DELETE /editor/api/maps/{n}/loot/{id}
POST /editor/api/maps               { map, name }   # новая карта
```

Каноничные инварианты (сервер их ДЕРЖИТ, UI может не знать):
- слоты T_OBJECTS/T_DYNAMIC выдаются строго за последним занятым
  (движок читает до первого пустого);
- кисть воды льёт байт типа карты (OR всех клеток: 0x80 Lake / 0x40
  Stream), переключатель типа конвертирует все клетки;
- у добавленных юнитов числа по образцу породы; `party == side`
  отряда; вражда живёт в отряде;
- удаление жителя пака — это `removed: true` в патче (сам пак
  неприкосновенен), удаление добавленного — изъятие записи draft.

### Миры (E2 — население без draft-заплаток)

Исходники миров: `project/worlds/<N>/{meta.json, maps/<M>.json}` —
экспорт `python -m konung2.worlds`. Каждая запись несёт `raw` (hex
оригинала): сборка мира кладёт разобранные поля ПОВЕРХ raw, нетронутый
экспорт собирается байт-в-байт (проверено всеми шестью мирами).

```
GET  /editor/api/worlds                     6 миров: герой, старт, счётчики
GET  /editor/api/worlds/{w}                 мета мира
GET  /editor/api/worlds/{w}/maps/{m}        отряды/юниты/кучи/выходы/
                                            события/поселение карты
POST /editor/api/worlds/{w}/maps/{m}/units    { index, patch } — правка
                                            юнита в исходнике (словари
                                            мержатся по ключам)
POST /editor/api/worlds/{w}/maps/{m}/parties  { slot, patch } — отряд:
                                            зона, вражда, счёт
POST /editor/api/worlds/{w}/build           собрать GAME.<w> (секунды) в
                                            project/worlds/build/ — его
                                            приоритетно читает ВСЁ
                                            (одна точка _game_bytes);
                                            после — обычный Build пака
```

Поля юнита, которые сборка мира кладёт поверх raw: клетка (row/col),
direction, pose, side, breed/body, palette, level, money, experience/
next_level/free_xp, health, armour, speed, venom, accuracy, face,
dialog, breed_counter, characteristics/current (6), skills (20; нет
имени в словаре — ноль). Снаряжение и мешок в v1 едут только через raw
(правка — E2.1: у вещей своя таблица записей).

### Сюжет (E3 — узловой редактор диалогов)

Исходники: `project/story/` — экспорт `python -m konung2.story`
(qst/ — правимая копия 156 файлов cp866, files/*.json — разбор,
summary.json). Конвертер двусторонний, арбитр — авторский M_QUEST:
канонический перерендер ВСЕХ файлов собирается в QUESTS.RES побайтово
равный эталону (закреплено тестом).

```
GET  /editor/api/story               153 диалога, токены, сквозная
                                     валидация (недостижимость, битые
                                     @-цели, неизвестные токены)
GET  /editor/api/story/dialog/{имя}  граф: узлы switch (cases: cond →
                                     target) и section (reply + answers:
                                     cond/do/target/texts), достижимость
POST /editor/api/story/dialog/{имя}  { nodes: […] } — запись диалога:
                                     сначала валидатор графа, затем
                                     КОМПИЛЯЦИЯ-ВОРОТА (M_QUEST в
                                     песочнице собирает весь сюжет;
                                     отказ компилятора = откат правки)
POST /editor/api/story/compile       собрать QUESTS.RES из project/story
                                     (итог в project/story/QUESTS.RES;
                                     донос в каталог игры — ручной шаг)
```

Грамматика узлов: имя `*` — старт; `END_OF_DIALOG` — выход;
цель `@Имя` — глобальный вход (межскриптовый; сам @-узел — тоже
старт достижимости); условия `<[!][?]имя[:арг]>` через `&`/`|`;
действия — последовательность `<…>`, `+ТОКЕН`/`-ТОКЕН` правят
квестовые переменные; `NPC_QV<n>` — встроенные переменные собеседника.
Undo-журнал охватывает правки диалогов.

### Сборка и запуск

```
POST /editor/api/build              { maps: [23] }   # пустой список -
  → { ok, job }                     #  только правила (быстро)
GET  /editor/api/build/status
  → { ok, running: bool, job, code?, tail: ["последние строки"] }
GET  /editor/api/play/{n}           # 302 на игру (после сборки)
```

Build запускает `python -m knyaz2.content build --map N` фоновым
процессом; одновременно одна сборка (вторая получает 409). UI
показывает прогресс по status и после code==0 предлагает Play.

## Что редактор НЕ делает (границы v2)

- Не правит движок игры и правила боя — только данные карты.
- Не редактирует деревья диалогов (номер диалога юниту — да, сами
  тексты — M_QUEST, фаза 6).
- Не рисует сам: холст — работа UI (данные terrain + картинки пака
  дают всё нужное; сцена = тайлы → оверлеи → вода → объекты по
  sort_y → юниты).
- Живой предпросмотр в ИГРЕ (?editor=1) остаётся как «посмотреть
  глазами игрока», но больше не единственный способ увидеть правку.

## Дорожная карта

1. **v2.0 (сейчас):** CORS + OPTIONS; GET maps/state/terrain/cells;
   зеркала мутаций; DELETE объектов/оверлеев/юнитов/отрядов/куч;
   build/status/play. Тесты на каждый endpoint.
2. **v2.1:** миниатюры каталога объектов (thumb-URL), пагинация
   бестиария, мини-карта (готовый PNG со сборки).
3. **v2.2:** зоны обстановки интерьеров (T_ZONES), выходы карты,
   undo-журнал (журналирование мутаций уже даёт git проекта).
```
