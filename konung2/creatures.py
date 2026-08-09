# -*- coding: utf-8 -*-
"""
Твари: где лежат их кадры.

Разобрано по коду; сами кадры ещё не распакованы — здесь то, что уже
точно известно, чтобы не искать заново.

ГДЕ. Человек собирается из слоёв HEROES.RES, а тварь рисуется ЦЕЛЫМ
НАБОРОМ (VA 0x4267B8): движок берёт блок ``0x72CCB0 + тело * 0x1728`` и
внутри него — кадр по указателю unit+0x1E. Тело — тот же байт unit+0xFC,
что у людей выбирает слой.

ОТКУДА. Наборы грузятся из OBJECTS.RES (VA 0x42908C и 0x43C228):

    в начале файла 8000 байт — каталог на 1000 записей по два слова:
    смещение и длина, и к смещению прибавляется размер самого каталога

    записи 0…29   ТВАРИ: по половине-полутора мегабайт каждая
    записи 30…    объекты карты, те самые, что мы уже читаем

То есть тварей в игре не больше тридцати, и на карту их грузится столько,
сколько встретилось.

ЧТО ВНУТРИ. Запись устроена так:

    +0x0000  u32   ноль
    +0x0004  u32   длина записи, та же, что в каталоге; в памяти движок
                   кладёт сюда УКАЗАТЕЛЬ на область кадров, и все смещения
                   ниже считаются от неё (VA 0x4267D9, 0x425DB4)
    +0x0008        ТАБЛИЦА АНИМАЦИЙ: ШЕСТЬ блоков по 0x130 байт, в блоке
                   восемь направлений по 0x26 — счёт кадров и до
                   восемнадцати их номеров (VA 0x416740 читает её так же)
    +0x0728        ТАБЛИЦА ДЕСКРИПТОРОВ: 512 кадров по 8 байт
                       i32  смещение спрайта ТЕНИ, или −1, если тени нет
                       i32  смещение записи кадра
                   Кадр берётся ПО НОМЕРУ из этой таблицы (VA 0x416740:
                   ``кадр = запись + 0x728 + номер*8``), а не подряд.
                   Незанятые места забиты нулями.
    +0x1728        область кадров; запись кадра устроена так:
                       i16 dx, dy   смещение ТЕНИ      (VA 0x4267E5)
                       i16 dx, dy   смещение КАРТИНКИ  (VA 0x426841)
                       спрайт картинки (с +8 записи, VA 0x425E4A)
                   Спрайт тени лежит отдельно, по своему смещению из
                   дескриптора, а не следом за картинкой.

Спрайт — тот же RLE, что у объектов и построек: ширина, высота, длины
строк, а в строке ноль кончает её, старший бит пропускает точки, иначе
идут точки индексами палитры.

ПАЛИТРА у каждого юнита своя: dword unit+0x2E, и это БАЙТОВОЕ смещение,
номер палитры получается делением на 512 (VA 0x425DB4 кладёт его перед
блиттером, VA 0x43487C так его и записывает). У одной породы палитр
несколько — оттого твари одного вида разной масти.

КТО ЕСТЬ КТО. Порода лежит в unit+0x1A: у людей маленькие числа, у тварей
буквы, и бит 0x40 значит «зверь». У Волхва (карта 34) четыре породы:
'B' 66, 'I' 73, 'K' 75 и одиночный 'V' 86, а тела у них 1, 8, 10 и 16 —
это и есть номера записей OBJECTS.RES.
"""
from __future__ import annotations

import struct

#: Каталог в начале OBJECTS.RES.
CATALOGUE_AT, CATALOGUE_SIZE, CATALOGUE_COUNT = 0, 8000, 1000
#: Записи до этой — твари, дальше объекты карты.
CREATURE_ENTRIES = 30
#: Шапка набора в памяти и её шаги.
BLOCK_SIZE, ANIMATION_STRIDE, DIRECTION_STRIDE, TABLE_AT = 0x1728, 0x130, 0x26, 8
#: Бит породы, которым помечен зверь.
BEAST_BIT = 0x40
#: Бит «этого больше не рисовать» в той же породе (unit+0x1A).
HIDDEN_BIT = 0x80

#: ТЕЛО 15 живёт по своим правилам (VA 0x416A15 и 0x425DC0):
#:
#:   * умирая, оно поднимает себе бит 0x80 породы и очищает свою клетку —
#:     трупа не остаётся вовсе, место сразу свободно;
#:   * блиттер такое тело НЕ рисует, если бит 0x80 поднят или поза равна
#:     3, 0x0B или 0x0C.
#:
#: Это единственное тело с особым поведением; у остальных смерть обычная.
VANISHING_BODY = 15
VANISHING_HIDDEN_POSES = (3, 0x0B, 0x0C)


def catalogue(data: bytes | None = None) -> list[tuple[int, int]]:
    """Каталог OBJECTS.RES: (смещение, длина) на запись."""
    from .paths import game_file
    if data is None:
        with open(game_file("OBJECTS.RES"), "rb") as stream:
            data = stream.read(CATALOGUE_SIZE)
    pairs = struct.unpack_from(f"<{CATALOGUE_COUNT * 2}I", data, CATALOGUE_AT)
    out = []
    for i in range(CATALOGUE_COUNT):
        offset = pairs[i * 2]
        # Движок обрывает разбор на первой записи со старшим битом смещения
        # (VA 0x43C228: `смещение < 0x80000000`), а не читает всю тысячу.
        if offset >= 0x80000000:
            break
        out.append((offset + CATALOGUE_SIZE, pairs[i * 2 + 1]))
    return out


#: Палитра юнита: dword unit+0x2E, номер — это смещение, делённое на 512.
UNIT_PALETTE_AT, PALETTE_STRIDE = 0x2E, 512
#: Блоков анимаций РОВНО ШЕСТЬ: сразу за ними, с +0x728, идёт таблица
#: дескрипторов кадров (VA 0x416740 адресует её как ``запись + 0x728``).
DESCRIPTORS_AT = 0x728
ANIMATION_BLOCKS = (DESCRIPTORS_AT - TABLE_AT) // ANIMATION_STRIDE
#: Дескриптор кадра: смещение спрайта тени (или −1) и смещение записи кадра.
DESCRIPTOR_STRIDE = 8
DESCRIPTOR_COUNT = (BLOCK_SIZE - DESCRIPTORS_AT) // DESCRIPTOR_STRIDE
#: Тени у кадра может не быть — тогда в дескрипторе стоит это.
NO_SHADOW = -1
#: В направлении не больше восемнадцати кадров.
FRAMES_PER_DIRECTION = (DIRECTION_STRIDE - 2) // 2
DIRECTIONS = 8


class CreatureRes:
    """Наборы кадров тварей из OBJECTS.RES."""

    def __init__(self, data: bytes):
        self.data = data
        self.catalogue = catalogue(data)

    @classmethod
    def from_game(cls) -> "CreatureRes":
        from .paths import game_file
        with open(game_file("OBJECTS.RES"), "rb") as stream:
            return cls(stream.read())

    def entry(self, body: int) -> bytes:
        """Запись набора целиком."""
        if not 0 <= body < CREATURE_ENTRIES:
            raise ValueError(f"тварь {body}: записи 0…{CREATURE_ENTRIES - 1}")
        start, length = self.catalogue[body]
        return self.data[start:start + length]

    def animations(self, body: int) -> list[list[list[int]]]:
        """Таблица анимаций: блок -> направление -> номера кадров."""
        block = self.entry(body)
        table = []
        for index in range(ANIMATION_BLOCKS):
            directions = []
            for direction in range(DIRECTIONS):
                at = TABLE_AT + index * ANIMATION_STRIDE + direction * DIRECTION_STRIDE
                count = struct.unpack_from("<H", block, at)[0]
                numbers = struct.unpack_from(f"<{FRAMES_PER_DIRECTION}H", block, at + 2)
                directions.append(list(numbers[:min(count, FRAMES_PER_DIRECTION)]))
            table.append(directions)
        return table

    def frames(self, body: int) -> list[dict]:
        """Кадры ПО ТАБЛИЦЕ ДЕСКРИПТОРОВ, как их берёт движок.

        Подряд кадры читать нельзя: тень лежит отдельным спрайтом по
        своему смещению, а у части кадров её нет вовсе, и последовательный
        разбор обрывался на первом же таком. Место кадра в списке — это его
        номер, на который ссылается таблица анимаций.
        """
        block = self.entry(body)
        out: list[dict] = []
        for number in range(DESCRIPTOR_COUNT):
            at = DESCRIPTORS_AT + number * DESCRIPTOR_STRIDE
            if at + DESCRIPTOR_STRIDE > len(block):
                break
            shadow_off, record_off = struct.unpack_from("<2i", block, at)
            # незанятые места забиты нулями; у настоящего кадра нулевым
            # бывает только смещение записи, и только у самого первого
            if shadow_off == 0 and record_off == 0 and number:
                break
            record = BLOCK_SIZE + record_off
            if record + 8 > len(block):
                break
            shadow_dx, shadow_dy, dx, dy = struct.unpack_from("<4h", block, record)
            image_at = record + 8
            if self._sprite_span(block, image_at) is None:
                break
            shadow_at = None
            if shadow_off != NO_SHADOW:
                candidate = BLOCK_SIZE + shadow_off
                if self._sprite_span(block, candidate) is not None:
                    shadow_at = candidate
            out.append({"index": number, "dx": dx, "dy": dy,
                        "shadow_dx": shadow_dx, "shadow_dy": shadow_dy,
                        "image_at": image_at, "shadow_at": shadow_at})
        return out

    @staticmethod
    def _sprite_span(block: bytes, at: int) -> int | None:
        """Сколько байт занимает спрайт вместе с заголовком."""
        if at + 4 > len(block):
            return None
        width, height = struct.unpack_from("<2H", block, at)
        if not (0 < width <= 4096 and 0 < height <= 4096):
            return None
        end = at + 4 + height * 2
        if end > len(block):
            return None
        rows = struct.unpack_from(f"<{height}H", block, at + 4)
        return 4 + height * 2 + sum(rows)

    def decode(self, body: int, frame: int, palette=None, shadow: bool = False):
        """Распаковать кадр по его НОМЕРУ: (спрайт, dx, dy).

        Номер — тот, на который ссылается таблица анимаций. Тени у кадра
        может не быть: тогда с ``shadow=True`` вернётся пусто.
        """
        from .res import decode_rle
        block = self.entry(body)
        row = next((f for f in self.frames(body) if f["index"] == frame), None)
        if row is None:
            return None, 0, 0
        at = row["shadow_at"] if shadow else row["image_at"]
        if at is None:
            return None, 0, 0
        if shadow:
            return (_decode_mask(block, at),
                    row["shadow_dx"], row["shadow_dy"])
        sprite = decode_rle(block, at, palette=palette, mode=8)
        return sprite, row["dx"], row["dy"]


def _decode_mask(block: bytes, at: int):
    """Теневая маска кадра: чёрная форма с альфой по спанам.

    ТЕНЬ — НЕ СПРАЙТ. Движок её пиксели не рисует вовсе: 0x43F260
    регистрирует строки маски спанами, а 0x440788 после всех объектов делит
    яркость фона под ними пополам. Поэтому и байты тут другие — не пиксельный
    RLE, а интервалы (VA 0x43F30D, movsx):

        байт > 0  непрозрачный интервал длины n, БЕЗ байтов данных
        байт < 0  пропуск (n & 0x7F)
        байт == 0 конец строки

    Раньше тень тварей гоняли через распаковщик спрайтов, и она почти всегда
    возвращалась пустой — оттого твари и ходили без теней, в отличие от людей,
    у которых маска читалась своим кодом (HEROES.RES, decode_shadow).
    """
    from .res import Sprite
    if at + 4 > len(block):
        return None
    width, height = struct.unpack_from("<2H", block, at)
    if not (0 < width <= 4096 and 0 < height <= 2048):
        return None
    pos = at + 4 + height * 2                 # длины строк пропускаем
    pixels = [(0, 0, 0, 0)] * (width * height)
    for y in range(height):
        x = 0
        while pos < len(block):
            n = struct.unpack_from("<b", block, pos)[0]
            pos += 1
            if n == 0:
                break
            if n < 0:
                x += n & 0x7F
            else:
                row = y * width
                for step in range(n):
                    if x + step < width:
                        pixels[row + x + step] = (0, 0, 0, 255)
                x += n
    return Sprite(width, height, pixels)


def is_beast(breed: int) -> bool:
    """Зверь ли это по байту породы unit+0x1A."""
    return bool(breed & BEAST_BIT)


def rules() -> dict:
    """Что известно про наборы тварей — для content pack."""
    return {
        "policy": "konung2_exe_0x42908c_0x4267b8",
        "entries": CREATURE_ENTRIES,
        "block": BLOCK_SIZE,
        "animation_stride": ANIMATION_STRIDE,
        "direction_stride": DIRECTION_STRIDE,
        "animation_blocks": ANIMATION_BLOCKS,
        "descriptors_at": DESCRIPTORS_AT,
        "descriptor_count": DESCRIPTOR_COUNT,
        "beast_bit": BEAST_BIT,
        "hidden_bit": HIDDEN_BIT,
        "vanishing": {"body": VANISHING_BODY,
                      "hidden_poses": list(VANISHING_HIDDEN_POSES)},
    }
