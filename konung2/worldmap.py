# -*- coding: utf-8 -*-
"""Глобальная карта: сетка 24x32, значки локаций, туман и проходимость.

Всё взято из движка, ничего не придумано:

* сетка живёт в памяти по 0x6AFAD8, по dword на клетку, и на новой игре
  копируется из exe с 0x460174 (VA 0x438A00, ветка «новая игра»);
* клетка: байт 0 — номер локации (он же номер карты <N>.KN2), байт 1 —
  вид местности для случайных встреч, байт 2 — сцена боя M<n>.RES,
  байт 3 — флаги тумана;
* рисуется с (0xA7, 0x19) шагом 0x1A на 0x1C (VA 0x4277F4), отряд стоит
  в середине клетки: x = столбец*0x1A + 0xB4, y = строка*0x1C + 0x27
  (VA 0x437EA8);
* значок локации — спрайт INTERF.RES из таблицы 0x4615CC по шесть байт;
* пройти можно там, где маска из exe (строки 0x45C7F4, данные 0x45A0E8)
  даёт бит 1 посуху и бит 2 по воде (VA 0x4277F4 -> 0x43B754).
"""
import struct

from .exetables import va_to_foff
from .paths import game_file

#: Начальная карта мира лежит в exe и на новой игре копируется как есть.
GRID_VA = 0x460174
#: Строк и столбцов; в памяти строка занимает 0x80 байт (32 dword).
ROWS, COLS = 0x18, 0x20
ROW_STRIDE = 0x80
GRID_SIZE = ROWS * ROW_STRIDE

#: Левый верхний угол сетки на экране и размер клетки (VA 0x4277F4).
ORIGIN_X, ORIGIN_Y = 0xA7, 0x19
CELL_W, CELL_H = 0x1A, 0x1C
#: Середина клетки, куда движок ставит отряд (VA 0x437EA8: +0xB4 и +0x27).
CENTRE_DX, CENTRE_DY = 0xB4 - ORIGIN_X, 0x27 - ORIGIN_Y

#: Разбор dword клетки.
CELL_LOCATION, CELL_TERRAIN, CELL_SCENE, CELL_FLAGS = 0, 8, 16, 24

#: Флаги тумана в старшем байте клетки.
FLAG_EXPLORED = 0x20   # отряд здесь был: клетка видна в полную силу
FLAG_SEEN = 0x40       # видно от соседней клетки: рисуется затемнённой
FLAG_HIDDEN = 0x80     # значок локации ещё не открыт по сюжету
#: Бит 0x10 в исходной сетке есть, но ни одна разобранная ветка движка его
#: не читает — держим как есть, чтобы не выдумывать смысл.
FLAG_UNKNOWN = 0x10

#: Значок локации: шесть байт на локацию — спрайт и сдвиг от угла клетки.
MARKERS_VA = 0x4615CC
MARKER_STRIDE = 6
#: СКОЛЬКО ЗАПИСЕЙ. Считается по расстоянию до следующей таблицы: имена
#: локаций лежат на 0x4616D4, то есть через 0x108 = 264 байта, а это ровно
#: 44 записи по шесть. Не 55: гнёзд локаций больше, чем значков.
#:
#: В каноне граница не мешала — самая большая локация на сетке имеет номер
#: 43, — но локации расширенной карты пойдут за 44, и без проверки значок
#: читался бы уже из таблицы имён.
MARKER_COUNT = 44
#: Столько ячеек «локация открыта» движок держит и пишет в сейв (VA 0x438A00).
LOCATION_SLOTS = 0x37

#: Спрайты INTERF.RES: сама карта во весь проём, свой отряд и чужие.
#: Свой — щит с руной (179, 15x15), чужие — рогатый шлем над костями
#: (235, ровно в клетку). Разные значки и рисуются по-разному: щит кладётся
#: по пиксельному месту отряда со сдвигом -7, чужие — по углу их клетки
#: (VA 0x4277F4, обращения к 0x6B2BB0 и 0x6B2D70).
MAP_SPRITE = 4
PLAYER_SPRITE = 179
PLAYER_OFFSET = -7
PARTY_SPRITE = 235

#: Скорость похода: кадров на путь = ((100 - прыть) * 0.01 + 1) * пиксели,
#: где прыть — наибольший байт +0xDF в отряде (VA 0x421690, 0x45049E).
TRAVEL_SPEED_AT = 0xDF
TRAVEL_SPEED_SCALE = 0.01

#: Расстановка отряда вокруг вожака: два набора на чётность строки, восемь
#: направлений, шесть мест (таблица 0x461BC0, VA 0x415238).
FORMATION_VA = 0x461BC0
FORMATION_SLOTS = 6
FORMATION_DIRECTIONS = 8

#: Куда отряд попадает, войдя на карту: по шесть байт на номер карты
#: (VA 0x436430 пишет их в запись отряда: строка -> +0x0C, столбец -> +0x14,
#: лицо -> +0x18). Вторая тройка есть не у всех — это второе место
#: прибытия, например у Морского лагеря со стороны моря.
ARRIVALS_VA = 0x460028
ARRIVAL_STRIDE = 6
#: СКОЛЬКО ЗАПИСЕЙ В ТАБЛИЦЕ. Считается по расстоянию до следующей: сетка
#: мира начинается на 0x460174, то есть через 0x14C = 332 байта, а это ровно
#: 55 записей по шесть и ещё два байта хвоста. Столько же, сколько гнёзд
#: локаций (LOCATION_SLOTS).
#:
#: Читали 64 и залезали в сетку: оттуда приезжали прибытия для карт 56, 58,
#: 60 и 63 — например «строка 0, столбец 2». Карт с такими номерами нет, но
#: у перенесённых из «Продолжения легенды» номера как раз за каноном, и такое
#: прибытие поставило бы отряд в угол карты вместо положенного места.
ARRIVAL_COUNT = LOCATION_SLOTS

#: Шаблоны встречных отрядов стоят на несуществующих «картах» 100…146:
#: движок ищет отряд, у которого номер карты равен номеру группы
#: (VA 0x4360A8), и копирует его целиком. Хвост 140…146 — СЕМЬ РОЛЕЙ
#: бродячих отрядов глобальной карты (VA 0x41C944: роль = 0x8C + жребий
#: из свободных, отряды лежат в GAME.x парами «шаблон + слот копии»).
TEMPLATE_FIRST, TEMPLATE_LAST = 100, 146

#: Маска проходимости: строки — dword на строку экрана, -1 значит «пусто»,
#: данные — пары (значение, длина) (VA 0x43B754).
MASK_ROWS_VA = 0x45C7F4
MASK_DATA_VA = 0x45A0E8
MASK_LAND = 1
MASK_SEA = 2

#: Случайные встречи: запись на вид местности (байт 1 клетки).
TERRAIN_VA = 0x45FC7C
TERRAIN_STRIDE = 0x17
TERRAIN_COUNT = 12
#: Отряды-противники: пятнадцать номеров на каждый класс опасности.
GROUPS_VA = 0x45FD90
GROUP_CHOICES = 15

#: Особые сцены: корабль в пути и бой на корабле (VA 0x4360A8 и 0x422CCC).
SCENE_SEA = 0x1A
SCENE_SEA_BATTLE = 0x1B
SCENE_RANDOM = 0x32

#: Бродячие отряды глобальной карты: десять записей по шестнадцать байт в
#: 0x7B2ACC — это ПОСЛЕДНИЕ 0xA0 байт файла GAME.x (загрузчик 0x43D898
#: читает их после поселений). Поля живой записи: +4 номер отряда-копии,
#: +5/+7 текущие строка и столбец, +9 сцена боя (-1 — не назначена);
#: в файле лежат только порог возрождения (dword +0) и ДОМАШНЯЯ клетка
#: (+6 строка, +8 столбец) — при возрождении движок копирует её в текущую
#: (VA 0x41C944: каждый 16-й тик, если +4 пуст и rand % 10000 больше
#: порога, роль — жребий из семи свободных, состав — копия отряда с
#: «картой» 0x8C + роль). Столкновение (VA 0x4277F4): каждый 16-й тик,
#: сцена не назначена, клетка совпала с отрядом игрока и Следопыт героя
#: (+0xDF) меньше rand % 100 — иначе отряд УКЛОНИЛСЯ; сцена боя берётся
#: из сцен местности клетки (0x45FC81 + местность*0x17 + rand % 15).
PARTY_RECORDS, PARTY_STRIDE = 10, 0x10
PARTY_INDEX_AT, PARTY_ROW_AT, PARTY_COL_AT, PARTY_SCENE_AT = 4, 5, 7, 9
PARTY_HOME_ROW_AT, PARTY_HOME_COL_AT = 6, 8
WANDER_ROLE_FIRST, WANDER_ROLES = 0x8C, 7
WANDER_RESPAWN_DIE, WANDER_EVADE_DIE, WANDER_CHECK_MASK = 10000, 100, 0xF
#: ДВИЖЕНИЕ бродячих (0x41C9B3, В9): каждый 16-й тик живой отряд при
#: ``rand % 60 == 0`` пробует до восьми направлений от случайного и делает
#: ОДИН шаг на соседнюю клетку 24×32. Не годятся: закрытые клетки (бит
#: 0x10 байта флагов), клетка героя, клетки других бродячих. Текущая
#: клетка отряда — байты +5/+7 его записи (дом +6/+8 копируется туда при
#: возрождении). Клетка с локацией начинает НАБЕГ на её поселение
#: (0x41CBD6: гость/грабёж через village_raiders) — в порте набеги не
#: смоделированы, отряд обходит локации стороной.
WANDER_MOVE_DIE = 60
WANDER_BLOCK_FLAG = 0x10
#: Восемь соседей в порядке движка (case 0…7): (строка, столбец).
WANDER_STEPS = ((0, -1), (-1, -1), (-1, 0), (-1, 1),
                (0, 1), (1, 1), (1, 0), (1, -1))


def wandering(world: int = 0) -> list[dict]:
    """Записи бродячих отрядов из хвоста GAME.x (живые в файле не лежат)."""
    with open(game_file(f"GAME.{world}"), "rb") as handle:
        data = handle.read()
    tail = data[-PARTY_RECORDS * PARTY_STRIDE:]
    out: list[dict] = []
    for index in range(PARTY_RECORDS):
        record = tail[index * PARTY_STRIDE:][:PARTY_STRIDE]
        threshold = struct.unpack_from("<I", record, 0)[0]
        if not threshold:
            continue
        out.append({"threshold": threshold,
                    "home_row": record[PARTY_HOME_ROW_AT],
                    "home_col": record[PARTY_HOME_COL_AT]})
    return out


def _exe() -> bytes:
    with open(game_file("konung2.exe"), "rb") as handle:
        return handle.read()


def grid(data: bytes | None = None) -> list[list[int]]:
    """Начальная сетка карты мира: строки по 32 клетки-dword."""
    blob = data if data is not None else _exe()
    at = va_to_foff(GRID_VA)
    return [list(struct.unpack_from("<32I", blob, at + row * ROW_STRIDE))
            for row in range(ROWS)]


def cell_fields(cell: int) -> dict[str, int]:
    """Разбор одной клетки на поля."""
    return {
        "location": (cell >> CELL_LOCATION) & 0xFF,
        "terrain": (cell >> CELL_TERRAIN) & 0xFF,
        "scene": (cell >> CELL_SCENE) & 0xFF,
        "flags": (cell >> CELL_FLAGS) & 0xFF,
    }


def cell_screen(row: int, col: int) -> tuple[int, int]:
    """Левый верхний угол клетки на экране."""
    return ORIGIN_X + col * CELL_W, ORIGIN_Y + row * CELL_H


def cell_centre(row: int, col: int) -> tuple[int, int]:
    """Куда движок ставит отряд внутри клетки (VA 0x437EA8)."""
    return ORIGIN_X + col * CELL_W + CENTRE_DX, ORIGIN_Y + row * CELL_H + CENTRE_DY


def cell_at(x: int, y: int) -> tuple[int, int] | None:
    """Клетка под точкой экрана; вне сетки — None."""
    col = (x - ORIGIN_X) // CELL_W
    row = (y - ORIGIN_Y) // CELL_H
    if 0 <= row < ROWS and 0 <= col < COLS:
        return int(row), int(col)
    return None


def markers(data: bytes | None = None) -> dict[int, dict[str, int]]:
    """Значки локаций: номер локации -> спрайт и сдвиг внутри клетки.

    Таблица идёт подряд по шесть байт, но осмысленных записей в ней
    ровно столько, сколько локаций стоит на самой карте, — остальное
    мусор за концом. Поэтому берём только то, что встречается в сетке.
    """
    blob = data if data is not None else _exe()
    at = va_to_foff(MARKERS_VA)
    standing = {fields["location"] for row in grid(blob) for fields in
                map(cell_fields, row) if fields["location"]}
    out: dict[int, dict[str, int]] = {}
    for location in sorted(standing):
        if not 0 <= location < MARKER_COUNT:
            continue
        sprite, dx, dy = struct.unpack_from("<Hhh", blob, at + location * MARKER_STRIDE)
        if sprite:
            out[location] = {"sprite": sprite, "dx": dx, "dy": dy}
    return out


def mask_value(x: int, y: int, data: bytes | None = None) -> int:
    """Значение маски проходимости в точке экрана (VA 0x43B754)."""
    blob = data if data is not None else _exe()
    rows_at, data_at = va_to_foff(MASK_ROWS_VA), va_to_foff(MASK_DATA_VA)
    if y < 0:
        return 0
    offset = struct.unpack_from("<i", blob, rows_at + y * 4)[0]
    if offset == -1:
        return 0
    at = data_at + offset + 1
    total = 0
    while True:
        run = blob[at]
        total += run
        if run == 0 or x < total:
            break
        at += 2
    return blob[at - 1]


def passable(row: int, col: int, ship: bool = False,
             data: bytes | None = None) -> bool:
    """Пройдёт ли отряд по этой клетке: посуху бит 1, на корабле бит 2."""
    x, y = cell_centre(row, col)
    bit = MASK_SEA if ship else MASK_LAND
    return bool(mask_value(x, y, data) & bit)


def reveal(cells: list[list[int]], row: int, col: int) -> None:
    """Отряд вошёл в клетку (VA 0x437ABC).

    Своя клетка становится «пройденной», восемь соседних — «виденными».
    Флаг тумана значка (0x80) при этом не трогается: его снимает только
    открытие локации по сюжету.
    """
    cells[row][col] |= FLAG_EXPLORED << CELL_FLAGS
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            r, c = row + dr, col + dc
            if (dr or dc) and 0 <= r < ROWS and 0 <= c < COLS:
                cells[r][c] |= FLAG_SEEN << CELL_FLAGS


def open_location(cells: list[list[int]], location: int) -> tuple[int, int] | None:
    """Открыть локацию по сюжету (VA 0x00436908): показать её значок."""
    for row in range(ROWS):
        for col in range(COLS):
            if cells[row][col] & 0xFF == location:
                cells[row][col] |= FLAG_SEEN << CELL_FLAGS
                cells[row][col] &= ~(FLAG_HIDDEN << CELL_FLAGS)
                return row, col
    return None


def marker_visible(cell: int) -> bool:
    """Виден ли значок локации на этой клетке (VA 0x4277F4)."""
    flags = (cell >> CELL_FLAGS) & 0xFF
    return (not flags & FLAG_HIDDEN and bool(flags & (FLAG_EXPLORED | FLAG_SEEN))
            and bool(cell & 0xFF))


def terrain_table(data: bytes | None = None) -> list[dict]:
    """Случайные встречи по видам местности (VA 0x4360A8).

    Запись на местность — 23 байта:

        +0x00 u16   «спокойствие»: если ``rand % 1000`` меньше него,
                    ничего не случилось
        +0x02  6    класс опасности, выбор по байту героя +0xFC
        +0x08 15    номера сцен, на которых разыграется бой

    Класс опасности — это строка в таблице 0x45FD90 (по пятнадцать номеров
    в строке); из неё жребием берётся НОМЕР КАРТЫ, и встречным отрядом
    становится тот, у кого в записи стоит эта карта (VA 0x4360A8).
    """
    blob = data if data is not None else _exe()
    at = va_to_foff(TERRAIN_VA)
    groups_at = va_to_foff(GROUPS_VA)
    table = []
    for kind in range(TERRAIN_COUNT):
        base = at + kind * TERRAIN_STRIDE
        calm = struct.unpack_from("<H", blob, base)[0]
        # ШЕСТЬ классов, а не три: движок читает байт +2 + тело героя
        # (VA 0x4360A8), а сцены начинаются только с +8 — между ними ровно
        # шесть байт. Читая три, мы теряли половину таблицы, и телу 3, 4, 5
        # доставался чужой класс: у местности 2 записано [2, 11, 12, 10,
        # 10, 2], у местности 4 — [10, 10, 11, 2, 2, 10].
        classes = list(blob[base + 2:base + 8])
        scenes = list(blob[base + 8:base + 8 + GROUP_CHOICES])
        table.append({
            "calm": calm, "classes": classes, "scenes": scenes,
            "parties": [list(blob[groups_at + danger * GROUP_CHOICES:
                                  groups_at + (danger + 1) * GROUP_CHOICES])
                        for danger in classes],
        })
    return table


def formation(data: bytes | None = None) -> list[list[list[list[int]]]]:
    """Где встают спутники вокруг вожака (таблица 0x461BC0, VA 0x415238).

    Два набора — по чётности строки, в каждом восемь направлений и по
    шесть мест: сдвиг строки и столбца. Движок берёт направление, обратное
    ходу отряда, и перебирает места с произвольного, пока не найдёт
    свободное.
    """
    blob = data if data is not None else _exe()
    at = va_to_foff(FORMATION_VA)
    out = []
    for parity in range(2):
        directions = []
        for direction in range(FORMATION_DIRECTIONS):
            slots = []
            for slot in range(FORMATION_SLOTS):
                off = at + parity * 0xC0 + direction * 0x18 + slot * 2
                slots.append([struct.unpack_from("<b", blob, off + 4)[0],
                              struct.unpack_from("<b", blob, off + 5)[0]])
            directions.append(slots)
        out.append(directions)
    return out


def arrivals(data: bytes | None = None,
             count: int = ARRIVAL_COUNT) -> dict[int, dict]:
    """Куда отряд встаёт, войдя на карту (таблица 0x460028, VA 0x436430).

    На карту приходится шесть байт: клетка и лицо, а следом — второе
    место прибытия, если оно у карты есть.
    """
    blob = data if data is not None else _exe()
    at = va_to_foff(ARRIVALS_VA)
    out: dict[int, dict] = {}
    for number in range(count):
        row, col, facing, row2, col2, facing2 = blob[
            at + number * ARRIVAL_STRIDE: at + (number + 1) * ARRIVAL_STRIDE]
        if not (row or col):
            continue
        place = {"row": row, "col": col, "facing": facing}
        if row2 or col2:
            place["second"] = {"row": row2, "col": col2, "facing": facing2}
        out[number] = place
    return out


def encounter_templates(world: int = 0) -> dict[int, dict]:
    """Отряды, которые встречаются в пути: номер группы -> кто в нём.

    Движок держит их отрядами, приписанными к несуществующим картам
    100…140, и по номеру группы из таблицы 0x45FD90 находит нужный
    (VA 0x4360A8). Здесь то же самое: номер группы — он же «номер карты».
    """
    from .gamefile import T_PARTIES, map_units
    from .paths import game_file
    with open(game_file(f"GAME.{world}"), "rb") as stream:
        data = stream.read()
    out: dict[int, dict] = {}
    for party in range(T_PARTIES.count):
        record = data[T_PARTIES.offset + party * T_PARTIES.size:][:T_PARTIES.size]
        group = struct.unpack_from("<H", record, 0x08)[0]
        if not TEMPLATE_FIRST <= group <= TEMPLATE_LAST or group in out:
            continue
        units = map_units(group, world)
        if units:
            out[group] = {"party": party, "count": record[0x1C], "units": units}
    return out


def rules() -> dict:
    """Правила глобальной карты одним куском — для выгрузки в пак."""
    blob = _exe()
    cells = grid(blob)
    return {
        "policy": "konung2_exe_0x4277f4_0x437abc_0x436908_0x421690",
        "rows": ROWS, "cols": COLS,
        "origin": [ORIGIN_X, ORIGIN_Y], "cell": [CELL_W, CELL_H],
        "centre": [CENTRE_DX, CENTRE_DY],
        "flags": {"explored": FLAG_EXPLORED, "seen": FLAG_SEEN,
                  "hidden": FLAG_HIDDEN},
        "map_sprite": MAP_SPRITE, "party_sprite": PARTY_SPRITE,
        "player_sprite": PLAYER_SPRITE, "player_offset": PLAYER_OFFSET,
        # поход идёт кадрами, и на каждом кадре бросается жребий встречи
        "travel": {"speed_at": TRAVEL_SPEED_AT, "scale": TRAVEL_SPEED_SCALE},
        "formation": formation(blob),
        # куда отряд встаёт, войдя на карту (VA 0x436430)
        "arrivals": {str(number): place
                     for number, place in arrivals(blob).items()},
        "scenes": {"sea": SCENE_SEA, "sea_battle": SCENE_SEA_BATTLE,
                   "random": SCENE_RANDOM},
        # бродячие отряды: домашние клетки из хвоста GAME.0, роли — отряды
        # с «картами» 0x8C…0x92, жребии и гейт Следопыта (VA 0x41C944,
        # 0x4277F4)
        "wandering": {"records": wandering(),
                      "role_first": WANDER_ROLE_FIRST,
                      "roles": WANDER_ROLES,
                      "respawn_die": WANDER_RESPAWN_DIE,
                      "evade_die": WANDER_EVADE_DIE,
                      "check_mask": WANDER_CHECK_MASK,
                      "move_die": WANDER_MOVE_DIE,
                      "block_flag": WANDER_BLOCK_FLAG,
                      "steps": [list(step) for step in WANDER_STEPS]},
        "mask": {"land": MASK_LAND, "sea": MASK_SEA},
        "grid": [[cell for cell in row] for row in cells],
        # проходимость клетки посчитана заранее: в браузере читать RLE из
        # exe незачем, а решение движка — бит маски в середине клетки
        "walk": [[mask_value(*cell_centre(row, col), blob)
                  for col in range(COLS)] for row in range(ROWS)],
        "markers": {str(location): marker
                    for location, marker in markers(blob).items()},
        "terrain": terrain_table(blob),
        "names": location_names(),
    }


def location_names() -> list[str]:
    """Названия локаций — те же, что движок пишет у переходов."""
    from .gamefile import location_names as places
    return places()
