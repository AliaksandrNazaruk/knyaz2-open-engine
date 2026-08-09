# -*- coding: utf-8 -*-
"""
Таблицы строк внутри konung2.exe ↔ JSON.

В exe нет ресурсной секции с текстом: названия локаций, имена NPC, названия и
описания предметов, навыки — это массивы указателей на CP866-строки в сегменте
данных. Модуль находит такие таблицы автоматически, выгружает их в JSON и
умеет патчить: короткая строка пишется на место старой, длинная переносится
в свободный «хвост» сегмента данных, а указатель перенаправляется.
"""
import json
import struct

from .paths import game_file

IMAGE_BASE = 0x400000
# секции PE: (имя, RVA, размер в файле, файловое смещение)
SECTIONS = [
    ('BEGTEXT', 0x10000, 0x3B800, 0x00400),
    ('DGROUP',  0x50000, 0x1B9E00, 0x3BC00),
]
MIN_TABLE = 8          # минимальная длина таблицы указателей
ENCODING = 'cp866'

#: Опознанные таблицы: файловое смещение -> имя
KNOWN_TABLES = {
    0x4B6E0: 'roles',        # 87  роли/профессии NPC: староста, знахарь, купец…
    0x4D2D4: 'locations',    # 55  названия локаций, индекс = номер <N>.KN2
    0x4D48C: 'npc_names',    # 206 имена и прозвища персонажей
    0x4E400: 'item_texts',   # 311 названия и описания предметов
    0x4E960: 'ui_hints',     # 16  подсказки интерфейса
    0x4EC20: 'months',       # 12  названия месяцев
}
#: Служебные таблицы рантайма Watcom — не трогать
IGNORE_ABOVE = 0x1D0000

#: Параметры локаций: 44 записи по 6 байт (VA 0x4615CC).
#: Загрузчик карты (VA 0x43DF9D) проверяет:
#:     if (карта <= 43 && параметры[карта].a != 0) { инициализация локации }
#: У карты с нулевой записью инициализация пропускается, и позже игра
#: падает по нулевому указателю. Новой локации запись обязательна.
MAP_PARAMS_OFFSET = 0x4D1CC
MAP_PARAMS_COUNT = 44
MAP_PARAMS_SIZE = 6


def va_to_foff(va):
    rva = va - IMAGE_BASE
    for _, sec_rva, size, foff in SECTIONS:
        if sec_rva <= rva < sec_rva + size:
            return foff + (rva - sec_rva)
    return None


def foff_to_va(off):
    for _, sec_rva, size, foff in SECTIONS:
        if foff <= off < foff + size:
            return IMAGE_BASE + sec_rva + (off - foff)
    return None


class ExeTables:
    """Читает/патчит строковые таблицы konung2.exe."""

    def __init__(self, data):
        self.data = bytearray(data)
        self._free_ptr = None

    @classmethod
    def from_game(cls):
        with open(game_file('konung2.exe'), 'rb') as f:
            return cls(f.read())

    # --- поиск строк ----------------------------------------------------
    def cstr(self, off):
        end = self.data.find(b'\0', off)
        return self.data[off:end].decode(ENCODING, errors='replace')

    def _is_string_ptr(self, off):
        """Указывает ли dword по смещению на «похожую на текст» строку."""
        if off + 4 > len(self.data):
            return None
        va = struct.unpack_from('<I', self.data, off)[0]
        foff = va_to_foff(va)
        if foff is None:
            return None
        end = self.data.find(b'\0', foff, foff + 300)
        if end < 0:
            return None
        raw = self.data[foff:end]
        if len(raw) > 260:
            return None
        # строка считается текстом, если состоит из печатных cp866-символов
        for b in raw:
            if b < 0x20 and b not in (9, 10, 13):
                return None
        return va

    def find_tables(self):
        """Автопоиск массивов указателей на строки во всём сегменте данных."""
        tables = []
        _, sec_rva, size, base = SECTIONS[1]
        off = base
        end = base + size - 4
        while off < end:
            if self._is_string_ptr(off) is None:
                off += 4
                continue
            start = off
            while off < end and self._is_string_ptr(off) is not None:
                off += 4
            count = (off - start) // 4
            if count >= MIN_TABLE:
                tables.append({'file_offset': start, 'va': foff_to_va(start), 'count': count})
        return tables

    def read_table(self, file_offset, count):
        out = []
        for i in range(count):
            va = struct.unpack_from('<I', self.data, file_offset + i*4)[0]
            out.append(self.cstr(va_to_foff(va)))
        return out

    # --- патч -----------------------------------------------------------
    def _find_free_space(self, need):
        """Ищет хвост нулей в сегменте данных для новых строк."""
        _, _, size, base = SECTIONS[1]
        if self._free_ptr is None:
            end = base + size
            i = end - 1
            while i > base and self.data[i] == 0:
                i -= 1
            self._free_ptr = i + 16          # с запасом от последних данных
        if self._free_ptr + need > base + size:
            raise RuntimeError('в exe не осталось места под новые строки')
        pos = self._free_ptr
        self._free_ptr += need
        return pos

    def set_string(self, table_offset, index, text):
        """Заменить строку таблицы. Длинная строка переносится в свободное место."""
        raw = text.encode(ENCODING, errors='replace') + b'\0'
        ptr_off = table_offset + index*4
        va = struct.unpack_from('<I', self.data, ptr_off)[0]
        foff = va_to_foff(va)
        old_len = self.data.find(b'\0', foff) - foff + 1
        if len(raw) <= old_len:
            self.data[foff:foff+len(raw)] = raw
            for i in range(foff+len(raw), foff+old_len):
                self.data[i] = 0
        else:
            new_off = self._find_free_space(len(raw))
            self.data[new_off:new_off+len(raw)] = raw
            struct.pack_into('<I', self.data, ptr_off, foff_to_va(new_off))

    # --- проект ---------------------------------------------------------
    def unpack(self, path, known=None):
        names = dict(KNOWN_TABLES)
        names.update(known or {})
        known = names
        doc = {'tables': []}
        for t in self.find_tables():
            if t['file_offset'] >= IGNORE_ABOVE:
                continue                       # таблицы рантайма C, не игровые
            entry = dict(t)
            entry['name'] = known.get(t['file_offset'], f"table_{t['file_offset']:X}")
            entry['strings'] = self.read_table(t['file_offset'], t['count'])
            doc['tables'].append(entry)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        return doc

    def apply(self, path):
        """Применить изменения из JSON обратно в exe."""
        with open(path, encoding='utf-8') as f:
            doc = json.load(f)
        changed = 0
        for t in doc['tables']:
            current = self.read_table(t['file_offset'], t['count'])
            for i, (old, new) in enumerate(zip(current, t['strings'])):
                if old != new:
                    self.set_string(t['file_offset'], i, new)
                    changed += 1
        return changed

    # --- параметры локаций ----------------------------------------------
    def map_params(self):
        out = []
        for m in range(MAP_PARAMS_COUNT):
            out.append(list(struct.unpack_from(
                '<3H', self.data, MAP_PARAMS_OFFSET + m*MAP_PARAMS_SIZE)))
        return out

    def set_map_params(self, m, values):
        if m >= MAP_PARAMS_COUNT:
            raise ValueError(f'карта {m} вне таблицы параметров (0..{MAP_PARAMS_COUNT-1})')
        struct.pack_into('<3H', self.data, MAP_PARAMS_OFFSET + m*MAP_PARAMS_SIZE, *values)

    def unpack_map_params(self, path):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({'map_params': self.map_params()}, f, ensure_ascii=False, indent=1)

    def apply_map_params(self, path):
        with open(path, encoding='utf-8') as f:
            want = json.load(f)['map_params']
        changed = 0
        for m, v in enumerate(want):
            if list(self.map_params()[m]) != list(v):
                self.set_map_params(m, v)
                changed += 1
        return changed

    def save(self, path):
        with open(path, 'wb') as f:
            f.write(bytes(self.data))
