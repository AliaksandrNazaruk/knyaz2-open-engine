"""Разбор двоичного формата kiwi, которым Figma пишет .fig.

Формат простой и стабильный:

  СХЕМА              данные лежат по описанию, которое идёт в том же файле
    varuint          сколько определений
    на каждое:
      строка         имя (заканчивается нулём)
      байт           вид: 0 перечисление, 1 структура, 2 сообщение
      varuint        сколько полей
      на каждое:
        строка       имя
        varint       тип: отрицательный — встроенный, иначе номер определения
        байт         массив ли
        varuint      значение (номер варианта у перечисления, номер поля
                     у сообщения)

  ЗНАЧЕНИЯ
    структура        поля подряд, без номеров
    сообщение        пары «номер поля, значение», ноль — конец
"""

import struct

BOOL, BYTE, INT, UINT, FLOAT, STRING = -1, -2, -3, -4, -5, -6
ENUM, STRUCT, MESSAGE = 0, 1, 2


class Reader:
    def __init__(self, data):
        self.data = data
        self.at = 0

    def byte(self):
        value = self.data[self.at]
        self.at += 1
        return value

    def varuint(self):
        value = shift = 0
        while True:
            piece = self.data[self.at]
            self.at += 1
            value |= (piece & 0x7F) << shift
            if not piece & 0x80:
                return value
            shift += 7

    def varint(self):
        value = self.varuint()
        return ~(value >> 1) if value & 1 else value >> 1

    def varfloat(self):
        # kiwi кладёт экспоненту в младший байт: при записи биты float
        # вращаются вправо на 9, при чтении — обратно влево на 23. Ноль и
        # денормалы занимают один байт 0.
        first = self.data[self.at]
        if first == 0:
            self.at += 1
            return 0.0
        bits = int.from_bytes(self.data[self.at:self.at + 4], 'little')
        self.at += 4
        bits = ((bits << 23) | (bits >> 9)) & 0xFFFFFFFF
        return struct.unpack('<f', struct.pack('<I', bits))[0]

    def string(self):
        end = self.data.index(b'\0', self.at)
        out = self.data[self.at:end].decode('utf-8', 'replace')
        self.at = end + 1
        return out

    def bytes_(self):
        n = self.varuint()
        out = self.data[self.at:self.at + n]
        self.at += n
        return out


class Field:
    __slots__ = ('name', 'type', 'is_array', 'value')

    def __init__(self, name, type_, is_array, value):
        self.name, self.type, self.is_array, self.value = name, type_, is_array, value


class Definition:
    __slots__ = ('name', 'kind', 'fields', 'by_id')

    def __init__(self, name, kind, fields):
        self.name, self.kind, self.fields = name, kind, fields
        self.by_id = {f.value: f for f in fields} if kind == MESSAGE else {}


def parse_schema(blob):
    r = Reader(blob)
    out = []
    for _ in range(r.varuint()):
        name = r.string()
        kind = r.byte()
        fields = []
        for _ in range(r.varuint()):
            fname = r.string()
            ftype = r.varint()
            is_array = bool(r.byte())
            value = r.varuint()
            fields.append(Field(fname, ftype, is_array, value))
        out.append(Definition(name, kind, fields))
    return out


class Decoder:
    def __init__(self, defs):
        self.defs = defs
        self.index = {d.name: i for i, d in enumerate(defs)}

    def value(self, r, type_):
        if type_ == BOOL:   return bool(r.byte())
        if type_ == BYTE:   return r.byte()
        if type_ == INT:    return r.varint()
        if type_ == UINT:   return r.varuint()
        if type_ == FLOAT:  return r.varfloat()
        if type_ == STRING: return r.string()
        return self.compound(r, self.defs[type_])

    def compound(self, r, d):
        if d.kind == ENUM:
            code = r.varuint()
            for f in d.fields:
                if f.value == code:
                    return f.name
            return code
        if d.kind == STRUCT:
            return {f.name: self.field(r, f) for f in d.fields}
        out = {}
        while True:
            fid = r.varuint()
            if fid == 0:
                return out
            f = d.by_id.get(fid)
            if f is None:
                raise ValueError(f'{d.name}: неизвестное поле {fid}')
            out[f.name] = self.field(r, f)

    def field(self, r, f):
        if not f.is_array:
            return self.value(r, f.type)
        return [self.value(r, f.type) for _ in range(r.varuint())]

    def decode(self, blob, root='Message'):
        return self.compound(Reader(blob), self.defs[self.index[root]])
