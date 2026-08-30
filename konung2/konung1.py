"""«Князь: Легенды лесной страны» — первая игра серии.

Она лежит в том же комплекте, что и обе части «Князя 2», и её данные
иногда нужны для сверки: часть мест перешла во вторую игру (Чёрный Бор,
Борье, Ловье, Верхний лагерь), а таблица имён НПС унаследована целиком.

ЧТО РАЗОБРАНО И ЧЕМ ПРОВЕРЕНО

Карта — файл ``KONUNG.<номер>`` на 128800 байт (у «Князя 2» 262660).
Раскладка взята из ОТКРЫТОГО ДВИЖКА (``Engine::LoadGameMap``,
github.com/Marisa-Chan/Slavik, клон в ``project/community/slavik``) и
сходится с длиной файла байт в байт:

    0x00000  25600 байт  земля: 160 рядов x 80 столбцов, по ДВА БАЙТА:
                         нижняя и верхняя плитка
    0x06400  51200 байт  проходимость: 160 x 320 по байту
    0x12C00  16000 байт  ДЕКОРАЦИИ: 1000 записей по 16 байт
                             +0x00 s32 номер ПЛИТКИ (не спрайта!)
                             +0x0C s16 x, +0x0E s16 y
                         рисуются плиткой ``Tiles[номер]`` — БЕЗ вычета
                         единицы, в отличие от земли
    0x16A80  36000 байт  ОБЪЕКТЫ: 1000 записей по 36 байт
                             +0x00 s32 номер объекта (< 0 — гнездо пусто)
                             +0x08 20 байт огни
                             +0x1C s16 остаток кадра
                             +0x1E s16 x, +0x20 s16 y
                             +0x22 u8 флаги, +0x23 u8 ТЕКУЩИЙ КАДР

ЭТО ДВЕ РАЗНЫЕ ТАБЛИЦЫ, И Я ИХ ПЕРЕПУТАЛА. Таблицу декораций на
0x12C00 я приняла за таблицу объектов, читала номер плитки как номер
спрайта и рисовала им постройки: дома вставали там, где лежит трава, а
настоящих домов на карте не было вовсе. Никакой автокорреляцией шаг
записи искать не следовало — раскладка лежала в открытом движке.

ИМЕНА ЛОКАЦИЙ лежат в exe ПОДРЯД, а не таблицей указателей, как во
второй игре: 50 записей по 40 байт со смещения 275956. Номер файла
карты равен номеру локации ПЛЮС ОДИН (``KONUNG.19`` — «Черный Бор»,
локация 18).

ГРАФИКА. Кодек и палитры у обеих игр общие, различается ТОЛЬКО
контейнер, и различается он одинаково: у первой игры таблицы на 512
гнёзд, у второй на 1000.

``GRAPH.RES``: 0x20000 палитр, дальше служебные блоки, ``u32`` длины
данных, таблица плиток 512 x {u32 смещение; u32 байтовое смещение
палитры} на 0x227F0 и данные плиток на 0x237F0. Плитка — обычный
спрайт RLE (``res.decode_rle``), а не сырые индексы.

``OBJECTS.RES``: 8 байт шапки (метка 0x01000000 и общий размер), затем
512 пар {u32 смещение; u32 длина}; смещения отсчитываются от КОНЦА
таблицы, то есть от 4104. Все 492 стыка сходятся байт в байт, и конец
последней записи совпадает с длиной файла.

Заголовок записи — тот же, что у «Крови Титанов», СДВИНУТЫЙ НА ЧЕТЫРЕ
БАЙТА:

    +0x04  u32   длина всей записи (совпала у всех живых гнёзд)
    +0x14  u32   палитра по умолчанию: байтовое смещение, индекс = /512
    +0x80  u32   смещение маски перекрытия (состояние 0)
    +0x84  u32   смещение спрайта (состояние 0), дальше шаг 8 на состояние
    +0xC0  2xi16 якорь маски
    +0xC4  2xi16 якорь спрайта: рисовать в (x + dx, y + dy)
    0x100        конец заголовка, дальше данные RLE

НОМЕР ГНЕЗДА РАВЕН ПОЛЮ ``sprite`` записи карты — без прибавки 30, как
во второй игре. Проверено размерами: при базе 30 все двенадцать спрайтов
Поречья выходили под 730x600, при базе 0 получаются постройки 445x500 и
593x463 и мелочь 39x67.
"""
from __future__ import annotations

import os
import struct
from pathlib import Path

#: Игра ставится рядом с обеими частями «Князя 2».
DIRECTORY = os.environ.get(
    "KONUNG1_DIR",
    r"C:\Program Files (x86)\Князь - Коллекционное издание"
    r"\01. Князь - Легенды лесной страны")
EXE = "konung.exe"

#: Земля: та же сетка, что у второй части.
GROUND_ROWS, GROUND_COLS = 160, 80
GROUND_SIZE = GROUND_ROWS * GROUND_COLS * 2
#: Шаг плитки в точках — им объект переводится в клетку.
TILE_W, TILE_H = 116, 32

#: Проходимость: 160 x 320 по байту.
FOOT_AT, FOOT_SIZE = GROUND_SIZE, 160 * 320
#: Декорации: номер ПЛИТКИ и место в точках.
DECORATIONS_AT, DECORATION_STRIDE = FOOT_AT + FOOT_SIZE, 16
#: Обе таблицы карты на 1000 гнёзд; пустое гнездо — отрицательный номер.
MAP_TABLE_SLOTS = 1000
#: Объекты: номер простого объекта OBJECTS.RES и место в точках.
OBJECTS_AT = DECORATIONS_AT + MAP_TABLE_SLOTS * DECORATION_STRIDE
OBJECT_STRIDE = 36

#: Имена локаций: 50 записей по 40 байт, подряд.
LOCATIONS_AT, LOCATION_STRIDE, LOCATION_COUNT = 275956, 40, 50


def game_file(name: str) -> Path:
    return Path(DIRECTORY) / name


def available() -> bool:
    """Стоит ли первая игра рядом."""
    return game_file(EXE).is_file()


def location_names() -> list[str]:
    """Названия локаций по номеру локации (0…49).

    Номер КАРТЫ на единицу больше: «Черный Бор» — локация 18, файл
    ``KONUNG.19``. Проверено на двух местах, чьи номера совпали и во
    второй игре: Чёрный Бор 19 и Борье 33.
    """
    data = game_file(EXE).read_bytes()
    out = []
    for index in range(LOCATION_COUNT):
        begin = LOCATIONS_AT + index * LOCATION_STRIDE
        chunk = data[begin:begin + LOCATION_STRIDE]
        end = chunk.find(b"\0")
        out.append(chunk[:end if end >= 0 else LOCATION_STRIDE]
                     .decode("cp866", "replace").strip())
    return out


def map_name(number: int) -> str:
    """Название карты по номеру ФАЙЛА (``KONUNG.<номер>``)."""
    names = location_names()
    at = number - 1
    return names[at] if 0 <= at < len(names) else f"карта {number}"


def map_numbers() -> list[int]:
    """Номера существующих карт.

    Их 43 из 50: файлов 9, 13, 18, 26, 31, 34 и 41 нет, хотя имена у
    этих локаций есть («Болото у Византийского Лагеря», «Поляны у
    Ловье», «Пепелище у Лесовья», «Островок на болоте», «Пещера у
    Камней», «Рудник у Борья», «Гнездо»). Это её собственное
    невключённое содержимое.
    """
    root = Path(DIRECTORY)
    out = []
    for file in root.glob("KONUNG.*"):
        tail = file.suffix[1:]
        if tail.isdigit():
            out.append(int(tail))
    return sorted(out)


def ground(number: int) -> list[list[tuple[int, int]]]:
    """Земля карты: в клетке ПАРА плиток — нижняя и верхняя.

    ДВА БАЙТА, А НЕ ОДНО ЧИСЛО. Сперва я читала клетку как u16 — и
    получала номера до 33924 при таблице в 305 плиток. Разгадка та же,
    что во второй игре: клетка это «нижний тайл, верхний тайл», и
    0x8484 — просто плитка 132 в обоих слоях. Верхний рисуется поверх
    нижнего, нулевые точки прозрачны.
    """
    data = game_file(f"KONUNG.{number}").read_bytes()
    if len(data) < GROUND_SIZE:
        raise ValueError(f"KONUNG.{number}: файл короче слоя земли")
    out = []
    for row in range(GROUND_ROWS):
        line = []
        for col in range(GROUND_COLS):
            at = (row * GROUND_COLS + col) * 2
            line.append((data[at], data[at + 1]))
        out.append(line)
    return out


def _ground_extent(cells: list[list[tuple[int, int]]]) -> tuple[int, int]:
    """Сколько рядов и столбцов ЗАНЯТО: карта лежит в углу сетки."""
    rows_count = cols_count = 0
    for row, line in enumerate(cells):
        for col, pair in enumerate(line):
            if any(pair):
                rows_count = max(rows_count, row + 1)
                cols_count = max(cols_count, col + 1)
    return rows_count or GROUND_ROWS, cols_count or GROUND_COLS


def decorations(number: int) -> list[dict]:
    """Декорации карты: номер ПЛИТКИ и место в точках.

    Движок рисует их ``Tiles[номер]`` — тем же набором, что и землю, но
    БЕЗ вычета единицы (у земли ``Tiles[байт - 1]``). Это мелочь
    обстановки: тропы, пятна, кусты, — а не постройки.
    """
    data = game_file(f"KONUNG.{number}").read_bytes()
    out = []
    for nest in range(MAP_TABLE_SLOTS):
        at = DECORATIONS_AT + nest * DECORATION_STRIDE
        tile, = struct.unpack_from("<i", data, at)
        if tile < 0:
            continue
        x, y = struct.unpack_from("<2h", data, at + 0x0C)
        out.append({"slot": nest, "tile": tile, "x": x, "y": y})
    return out


def objects(number: int) -> list[dict]:
    """Объекты карты: постройки, ограды, всё крупное.

    ``id`` — номер ПРОСТОГО объекта, гнездо в ``OBJECTS.RES`` равно
    ``id + 30``: первые тридцать гнёзд отданы динамическим объектам
    (``Resources::LoadObjectsRes``: 30 динамических и 482 простых, всего
    512).

    КООРДИНАТЫ ЛЕЖАТ В ПОЛУКЛЕТКАХ, а не в точках, и сетка вдвое мельче
    плиточной — как и слой проходимости 160 x 320. Перевод из движка::

        x = столбец * 116 / 2 - (ряд & 1) * 29
        y = ряд * 64 / 4

    Номер кадра в файле не хранится осмысленно (у всех 0 или 0xFF):
    движок ставит его сам при входе на карту — ноль у неподвижного
    объекта, случайный из ``NumFrames`` у мигающего.

    Поле на +0x04 — ПЕРЕКРАСКА: палитра поверх заголовочной, ноль
    значит «брать из заголовка» (у движка ``if (PaletteIndex == 0)
    PaletteIndex = SimpleObject.PaletteIndex``). Она в деле: 576
    объектов на 30 картах из 43, все в палитрах 223…230 — отдельная
    полоса, которой нет ни у заголовков (76…93), ни у плиток (11…24).
    В ``palette`` кладётся номер или None, если перекраски нет.
    """
    data = game_file(f"KONUNG.{number}").read_bytes()
    out = []
    for nest in range(MAP_TABLE_SLOTS):
        at = OBJECTS_AT + nest * OBJECT_STRIDE
        number, = struct.unpack_from("<i", data, at)
        if number < 0:
            continue
        col, row = struct.unpack_from("<2h", data, at + 0x1E)
        own_one, = struct.unpack_from("<I", data, at + 0x04)
        out.append({"slot": nest, "id": number,
                      "palette": (own_one // 512) or None,
                      "col": col, "row": row,
                      "x": col * 58 - (row & 1) * 29,
                      "y": row * 16,
                      "flags": data[at + 0x22]})
    return out

# --- графика: палитры, плитки земли, спрайты объектов --------------------

#: Обе таблицы первой игры на 512 гнёзд (у «Крови Титанов» на 1000).
SLOTS = 512
TABLE_SIZE = SLOTS * 8

#: `GRAPH.RES`: таблица плиток и данные. Место таблицы снято перебором —
#: база данных проверена тем, что по ней разбираются 40 плиток из 40.
TILE_TABLE_AT = 0x227F0
TILE_DATA_AT = TILE_TABLE_AT + TABLE_SIZE

#: `OBJECTS.RES`: 8 байт шапки, дальше таблица; смещения от её конца.
OBJECTS_HEAD = 8
OBJECTS_BIAS = OBJECTS_HEAD + TABLE_SIZE        # 4104
#: Заголовок записи; поля см. во вступлении модуля.
RECORD_HEADER = 0x100
RECORD_SIZE_AT, RECORD_PALETTE_AT = 0x04, 0x14
RECORD_FRAMES_AT, RECORD_ANCHORS_AT = 0x84, 0xC4
RECORD_STATES, RECORD_STATE_STRIDE = 8, 8


def _pairs(data: bytes, begin: int) -> list[tuple[int, int] | None]:
    """Таблица на 512 пар: пустые гнёзда возвращаются как None."""
    out = []
    for i_ in range(SLOTS):
        first, second = struct.unpack_from("<2I", data, begin + i_ * 8)
        out.append(None if first == 0xFFFFFFFF else (first, second))
    return out


class Graph:
    """`GRAPH.RES` первой игры: палитры и плитки земли."""

    def __init__(self, data: bytes):
        self.data = data
        self.table = _pairs(data, TILE_TABLE_AT)
        self._palettes = None

    @classmethod
    def from_game(cls) -> "Graph":
        return cls(game_file("GRAPH.RES").read_bytes())

    @property
    def palettes(self):
        from .res import read_palettes
        if self._palettes is None:
            self._palettes = read_palettes(self.data)
        return self._palettes

    def tile(self, number: int):
        """Плитка земли как спрайт; None — гнездо пустое или битое."""
        from .res import decode_rle
        if not 0 <= number < SLOTS:
            return None
        record = self.table[number]
        if record is None:
            return None
        offset, palette = record
        at = palette // 512
        if at >= len(self.palettes):
            return None
        return decode_rle(self.data, TILE_DATA_AT + offset,
                          self.palettes[at])


class Objects:
    """`OBJECTS.RES` первой игры: спрайты объектов карты.

    Гнёзда 0…29 — динамические объекты (люди, твари), 30…511 — простые
    (постройки, ограды). Номер простого объекта на карте отсчитывается
    от тридцатого гнезда: ``слот = id + 30``.
    """

    #: Первые тридцать гнёзд отданы динамическим объектам.
    DYNAMIC_SLOTS = 30

    def __init__(self, data: bytes):
        self.data = data
        self.nests = []
        for record in _pairs(data, OBJECTS_HEAD):
            if record is None or record[1] in (0, 0xFFFFFFFF):
                self.nests.append(None)
                continue
            offset, length = record
            offset += OBJECTS_BIAS
            self.nests.append((offset, length)
                               if offset + length <= len(data) else None)

    @classmethod
    def from_game(cls) -> "Objects":
        return cls(game_file("OBJECTS.RES").read_bytes())

    def header(self, slot: int) -> dict | None:
        """Поля заголовка записи."""
        if not 0 <= slot < SLOTS or self.nests[slot] is None:
            return None
        begin, length = self.nests[slot]
        size, = struct.unpack_from("<I", self.data,
                                     begin + RECORD_SIZE_AT)
        palette, = struct.unpack_from("<I", self.data,
                                      begin + RECORD_PALETTE_AT)
        return {"at": begin, "length": length, "size": size,
                "palette": palette // 512}

    def frames(self, slot: int) -> list[dict]:
        """Состояния объекта: смещение спрайта и его якорь."""
        head = self.header(slot)
        if head is None:
            return []
        begin, length = head["at"], head["length"]
        out = []
        for state in range(RECORD_STATES):
            stride = state * RECORD_STATE_STRIDE
            offset, = struct.unpack_from(
                "<I", self.data, begin + RECORD_FRAMES_AT + stride)
            if offset == 0xFFFFFFFF or offset >= length:
                continue
            dx, dy = struct.unpack_from(
                "<2h", self.data, begin + RECORD_ANCHORS_AT + stride)
            out.append({"state": state, "offset": offset,
                          "dx": dx, "dy": dy})
        return out

    def sprite(self, slot: int, palette=None, state: int = 0):
        """Спрайт объекта и его якорь: ``(спрайт, dx, dy)`` или None."""
        from .res import decode_rle
        frames = self.frames(slot)
        head = self.header(slot)
        if not frames or head is None:
            return None
        frame = next((k_ for k_ in frames if k_["state"] == state), frames[0])
        if palette is None:
            palette = head["palette"]
        colors = Graph.from_game().palettes
        if palette >= len(colors):
            return None
        sprite = decode_rle(self.data,
                            head["at"] + RECORD_HEADER + frame["offset"],
                            colors[palette], max_size=2048)
        return None if sprite is None else (sprite, frame["dx"], frame["dy"])

    def simple(self, number: int, frame: int = 0, palette=None):
        """Спрайт ПРОСТОГО объекта по его номеру на карте."""
        return self.sprite(number + self.DYNAMIC_SLOTS, palette, frame)
