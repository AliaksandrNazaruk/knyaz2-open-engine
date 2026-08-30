# -*- coding: utf-8 -*-
"""
Общий механизм «таблица записей фиксированного размера» ↔ JSON.

Идея: каждая запись хранится в JSON как набор ИМЕНОВАННЫХ полей плюс поле
``raw`` с полным hex-дампом. При сборке буфер берётся из ``raw``, а затем
поверх него записываются именованные поля. Благодаря этому:

* сборка всегда байт-в-байт, даже если формат расшифрован не полностью;
* модмейкер правит понятные поля, не думая о неизвестных байтах;
* если поле удалить из JSON — останется оригинальное значение из ``raw``.

Записи, совпадающие со «значением по умолчанию» (обычно нули или 0xFF),
в JSON не попадают вовсе — иначе файлы распухают от 1000 пустых слотов.
"""
import struct
from collections import Counter

FMT_SIZE = {'u8': 1, 's8': 1, 'u16': 2, 's16': 2, 'u32': 4, 's32': 4, 'f32': 4}
FMT_CODE = {'u8': 'B', 's8': 'b', 'u16': '<H', 's16': '<h', 'u32': '<I', 's32': '<i', 'f32': '<f'}


class RecordTable:
    """Таблица из ``count`` записей по ``size`` байт со схемой ``fields``.

    fields: список кортежей (имя, смещение, тип) — тип из FMT_SIZE.
    """

    def __init__(self, name, offset, count, size, fields):
        self.name = name
        self.offset = offset
        self.count = count
        self.size = size
        self.fields = fields

    # --- чтение ---------------------------------------------------------
    #: ДЛИНА ТАБЛИЦЫ МОЖЕТ БЫТЬ НЕ ТА, ЧТО ОБЪЯВЛЕНА. У карт «Продолжения
    #: легенды» блок обстановки построек длиннее нашего — 62 записи против
    #: 30, — и число выводится из длины самого файла, а не задаётся здесь.
    #: Без довода берётся объявленное, и всё работает как раньше.
    def default_record(self, data, count=None):
        """Самое частое значение записи — считается «пустым слотом»."""
        count = self.count if count is None else count
        c = Counter(bytes(data[self.offset + i*self.size: self.offset + (i+1)*self.size])
                    for i in range(count))
        rec, n = c.most_common(1)[0]
        return rec if n > count // 3 else bytes(self.size)

    def unpack(self, data, count=None):
        count = self.count if count is None else count
        default = self.default_record(data, count)
        out = {'_default': default.hex(), '_count': count, '_size': self.size, 'records': []}
        for i in range(count):
            raw = bytes(data[self.offset + i*self.size: self.offset + (i+1)*self.size])
            if raw == default:
                continue
            rec = {'slot': i}
            for fname, foff, ftype in self.fields:
                v = struct.unpack_from(FMT_CODE[ftype], raw, foff)[0]
                # NaN/inf не переживают JSON — такие поля показываем как null,
                # исходные байты всё равно сохранены в raw
                if ftype == 'f32' and v != v:
                    v = None
                rec[fname] = v
            rec['raw'] = raw.hex()
            out['records'].append(rec)
        return out

    # --- запись ---------------------------------------------------------
    def pack(self, table):
        default = bytes.fromhex(table['_default'])
        # Сколько записей — говорит САМА таблица: она могла приехать длиннее
        # объявленного (см. default_record). Слот за пределами — это не
        # «допишем в конец», а рассогласование, и молчать о нём нельзя.
        count = int(table.get('_count', self.count))
        buf = bytearray(default * count)
        for rec in table['records']:
            i = rec['slot']
            if not 0 <= i < count:
                raise ValueError(f"{self.name}: запись {i} вне таблицы "
                                 f"из {count}")
            raw = bytearray(bytes.fromhex(rec['raw'])) if 'raw' in rec else bytearray(default)
            for fname, foff, ftype in self.fields:
                if fname not in rec or rec[fname] is None:
                    continue                      # поля нет — оставляем как в raw
                old = struct.unpack_from(FMT_CODE[ftype], raw, foff)[0]
                if repr(old) == repr(rec[fname]):
                    continue                      # значение не менялось — не трогаем байты
                struct.pack_into(FMT_CODE[ftype], raw, foff, rec[fname])
            buf[i*self.size:(i+1)*self.size] = raw
        return bytes(buf)


def new_record(table_meta, slot, **fields):
    """Создать новую запись «с нуля» на базе значения по умолчанию."""
    rec = {'slot': slot, 'raw': table_meta['_default']}
    rec.update(fields)
    return rec
