# -*- coding: utf-8 -*-
"""
Карты .KN2 ↔ текстовый проект.

Раскладка файла (256516 байт, см. FORMATS.md):

    0x00000  0x06400  слой 1: 160x160 байт          -> layer1.png
    0x06400  0x03200  слой 2: 160x80 байт           -> layer2.png
    0x09600  0x28000  сетка 256 x 160 x u16 lo,hi   -> grid.txt
    0x31600  0x02EE0  1000 GRAPH-оверлеев x 12 байт -> map.json: dynamic
    0x344E0  0x08CA0  1000 записей x 36 байт        -> map.json: objects
    0x3D180  0x00004  флаг                          -> map.json: light_flag
    0x3D184  0x00200  16 записей x 32 байта         -> map.json: light
    0x3D384  0x01680  30 зон x 192 байта            -> map.json: zones
"""
import json
import os
import struct

from .binrec import RecordTable
from .names import LOCATIONS, slug
from .paths import game_file

MAP_SIZE = 256516
GRID_W, GRID_H, GRID_ROW = 160, 256, 0x280
EMPTY_CELL = 0x4FFF

SEC_LAYER1 = (0x00000, 0x6400, 160, 160)
SEC_LAYER2 = (0x06400, 0x3200, 160, 80)
SEC_GRID = (0x09600, 0x28000)
SEC_FLAG = (0x3D180, 4)

T_DYNAMIC = RecordTable('dynamic', 0x31600, 1000, 12, [
    # Историческое имя dynamic оставлено для байт-в-байт совместимости
    # текстового проекта. В оригинале это ранний проход terrain overlays:
    # GRAPH.RES slot, палитра и абсолютная экранная точка (VA 0x42543D).
    ('id',      0, 'u16'),
    ('kind',    4, 'u16'),
    ('pixel_x', 8, 'u16'),
    ('pixel_y', 10, 'u16'),
])

T_OBJECTS = RecordTable('objects', 0x344E0, 1000, 36, [
    # Слот спрайта в OBJECTS.RES = sprite + SIMPLE_SLOT_BASE. Движок (0x43E7D8)
    # при загрузке карты подменяет это поле указателем 0x75835C + sprite*0x100.
    ('sprite',  0, 's32'),
    # ПАЛИТРА — ЦЕЛОЕ СЛОВО, А НЕ ПОЛОВИНА. Это байтовое смещение в блоке
    # палитр (шаг 0x200), и загрузчик читает его двойным словом целиком:
    # `local_50[1]`, а ноль подменяет палитрой из заголовка ресурса
    # (VA 0x43E7D8). Смещения переваливают за 0xFFFF — у деревьев Беглого
    # записано 116736, то есть палитра 228; читая половину, мы получали
    # 51200 и палитру 100, и деревья выходили выбеленными с цветным крапом.
    ('kind',    4, 'u32'),
    ('pixel_x', 30, 'u16'),
    ('pixel_y', 32, 'u16'),
    ('state',   35, 'u8'),    # индекс видимого кадра в заголовке OBJECTS.RES
])

T_LIGHT = RecordTable('light', 0x3D184, 16, 32, [])

#: ОБСТАНОВКА ВНУТРИ ОБЪЕКТОВ. Историческое имя `zones` оставлено ради
#: байт-в-байт совместимости текстового проекта, но это не «зоны»: движок
#: читает блок в 0x6AE458 (VA 0x43DF48) и рисует его отрисовщиком нутра
#: объекта (VA 0x00424514) — тридцать объектов по шестнадцать гнёзд:
#:
#:     +0x00 u32  спрайт; 0xFFFFFFFF — гнездо пустое
#:     +0x04 u32  младшие 24 бита — палитра; в СТАРШИЙ байт загрузчик карты
#:                кладёт номер живого контейнера плюс один
#:     +0x08 i16  экранный x        +0x0A i16  экранный y
#:
#: Через этот старший байт к гнезду и привязывается сундук: у записи кучи
#: (GAME.N, таблица 0x2C800) байт +0x09 — номер объекта, +0x0A — гнездо.
T_ZONES = RecordTable('zones', 0x3D384, 30, 192, [])
ZONE_SUB = 12                       # гнездо — 12 байт
ZONE_OBJECTS, ZONE_SLOTS = 30, 16
ZONE_EMPTY = 0xFFFFFFFF


def interior_slots(kn2) -> dict[tuple[int, int], dict]:
    """Занятые гнёзда обстановки: (объект, гнездо) -> спрайт и точка."""
    out = {}
    for obj in range(ZONE_OBJECTS):
        for slot in range(ZONE_SLOTS):
            at = T_ZONES.offset + obj * T_ZONES.size + slot * ZONE_SUB
            sprite, word = struct.unpack_from('<II', kn2.data, at)
            if sprite == ZONE_EMPTY:
                continue
            x, y = struct.unpack_from('<hh', kn2.data, at + 8)
            out[(obj, slot)] = {'sprite': sprite, 'palette': word & 0xFFFFFF,
                                'x': x, 'y': y}
    return out


class KN2Map:
    """Карта локации. Читает, редактирует и пишет .KN2 без потерь."""

    def __init__(self, number, data):
        assert len(data) == MAP_SIZE, f"размер {len(data)} != {MAP_SIZE}"
        self.number = number
        self.data = bytearray(data)

    # --- загрузка -------------------------------------------------------
    @classmethod
    def from_game(cls, number):
        with open(game_file(f'{number}.KN2'), 'rb') as f:
            return cls(number, f.read())

    @classmethod
    def from_file(cls, path, number=None):
        with open(path, 'rb') as f:
            data = f.read()
        if number is None:
            number = int(os.path.basename(path).split('.')[0])
        return cls(number, data)

    # --- доступ к сетке -------------------------------------------------
    def cell(self, x, y):
        off = SEC_GRID[0] + y*GRID_ROW + x*4
        return struct.unpack_from('<HH', self.data, off)

    def set_cell(self, x, y, lo=None, hi=None):
        off = SEC_GRID[0] + y*GRID_ROW + x*4
        if lo is not None:
            struct.pack_into('<H', self.data, off, lo)
        if hi is not None:
            struct.pack_into('<H', self.data, off + 2, hi)

    def clear_cell(self, x, y):
        """Опустошить клетку (как скрипт MAP=n,x,y,0x00004FFF).

        Внимание: 0xFFF в младших битах — «непроходимо» (VA 0x44146C),
        так что очищенная клетка перестаёт быть проходимой.
        """
        self.set_cell(x, y, EMPTY_CELL, 0)

    def copy_region(self, src, x0, y0, w, h, dx=0, dy=0):
        """Скопировать прямоугольник сетки из другой карты."""
        for y in range(h):
            for x in range(w):
                lo, hi = src.cell(x0 + x, y0 + y)
                self.set_cell(x0 + x + dx, y0 + y + dy, lo, hi)

    # --- распаковка в проект -------------------------------------------
    def unpack(self, outdir):
        from PIL import Image
        os.makedirs(outdir, exist_ok=True)

        for fname, (off, size, w, h) in (('layer1.png', SEC_LAYER1), ('layer2.png', SEC_LAYER2)):
            img = Image.frombytes('L', (w, h), bytes(self.data[off:off+size]))
            img.save(os.path.join(outdir, fname))

        lines = []
        for y in range(GRID_H):
            row = []
            for x in range(GRID_W):
                lo, hi = self.cell(x, y)
                row.append(f'{lo:04X}:{hi:04X}')
            lines.append(' '.join(row))
        with open(os.path.join(outdir, 'grid.txt'), 'w', encoding='utf-8') as f:
            f.write('# сетка карты: 256 строк по 160 клеток, формат LO:HI (hex)\n')
            f.write(f'# LO={EMPTY_CELL:04X} — пустая клетка (0xFFF в младших битах = непроходимо)\n')
            f.write('\n'.join(lines) + '\n')

        doc = {
            'map_number': self.number,
            'name': LOCATIONS.get(self.number, ''),
            'light_flag': struct.unpack_from('<I', self.data, SEC_FLAG[0])[0],
            'objects': T_OBJECTS.unpack(self.data),
            'dynamic': T_DYNAMIC.unpack(self.data),
            'light': T_LIGHT.unpack(self.data),
            'zones': self._unpack_zones(),
        }
        with open(os.path.join(outdir, 'map.json'), 'w', encoding='utf-8') as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        return doc

    def _unpack_zones(self):
        table = T_ZONES.unpack(self.data)
        # дополнительно раскладываем каждую зону на 16 подзаписей по 12 байт
        for rec in table['records']:
            raw = bytes.fromhex(rec['raw'])
            subs = []
            for j in range(16):
                sid, z1, kind, z2, px, py = struct.unpack_from('<6H', raw, j*ZONE_SUB)
                if sid != 0xFFFF or kind != 0xFFFF:
                    subs.append({'i': j, 'id': sid, 'kind': kind,
                                 'pixel_x': px, 'pixel_y': py})
            rec['sub'] = subs
        return table

    # --- сборка из проекта ---------------------------------------------
    @classmethod
    def pack(cls, srcdir, number=None):
        from PIL import Image
        with open(os.path.join(srcdir, 'map.json'), encoding='utf-8') as f:
            doc = json.load(f)
        if number is None:
            number = doc['map_number']
        data = bytearray(MAP_SIZE)

        for fname, (off, size, w, h) in (('layer1.png', SEC_LAYER1), ('layer2.png', SEC_LAYER2)):
            img = Image.open(os.path.join(srcdir, fname)).convert('L')
            raw = img.tobytes()
            assert len(raw) == size, f'{fname}: {len(raw)} != {size}'
            data[off:off+size] = raw

        with open(os.path.join(srcdir, 'grid.txt'), encoding='utf-8') as f:
            rows = [ln for ln in f.read().splitlines() if ln and not ln.startswith('#')]
        assert len(rows) == GRID_H, f'grid.txt: {len(rows)} строк, нужно {GRID_H}'
        for y, line in enumerate(rows):
            cells = line.split()
            assert len(cells) == GRID_W, f'строка {y}: {len(cells)} клеток'
            for x, tok in enumerate(cells):
                lo, hi = tok.split(':')
                struct.pack_into('<HH', data, SEC_GRID[0] + y*GRID_ROW + x*4,
                                 int(lo, 16), int(hi, 16))

        struct.pack_into('<I', data, SEC_FLAG[0], doc['light_flag'])
        for table, spec in ((doc['objects'], T_OBJECTS), (doc['dynamic'], T_DYNAMIC),
                            (doc['light'], T_LIGHT), (doc['zones'], T_ZONES)):
            blob = spec.pack(table)
            data[spec.offset:spec.offset + len(blob)] = blob

        return cls(number, bytes(data))

    def save(self, path):
        with open(path, 'wb') as f:
            f.write(bytes(self.data))

    # --- удобные выборки ------------------------------------------------
    def objects(self):
        return T_OBJECTS.unpack(self.data)['records']

    def used_cells(self):
        return sum(1 for y in range(GRID_H) for x in range(GRID_W)
                   if self.cell(x, y)[0] not in (0, EMPTY_CELL))

    @property
    def dirname(self):
        return slug(self.number)
