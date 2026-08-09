# -*- coding: utf-8 -*-
"""
Скопировать в exe запись «параметров локации» с одной карты на другую.

    python tools\\patch_maptable.py 19 32       посмотреть и пропатчить
    python tools\\patch_maptable.py --show      показать всю таблицу

Таблица из 44 записей по 6 байт лежит по файловому смещению 0x4D1CC
(VA 0x4615CC). Загрузчик карты (VA 0x43DF9D) делает так:

    if (карта <= 43 && таблица[карта].слово0 != 0) { инициализация локации }

То есть у карты с нулевой записью часть инициализации просто не выполняется.
Работает поверх build\\konung2.exe, результат кладётся в тестовое зеркало.
"""
import os, struct, sys, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from konung2.names import LOCATIONS
from konung2.paths import BUILD_DIR, game_file

TABLE = 0x4D1CC
COUNT, SIZE = 44, 6
RIG = os.path.join(os.path.expanduser('~'), 'Documents', 'Knyaz2Test')

src_exe = os.path.join(BUILD_DIR, 'konung2.exe')
if not os.path.exists(src_exe):
    src_exe = game_file('konung2.exe')
data = bytearray(open(src_exe, 'rb').read())


def entry(m):
    return struct.unpack_from('<3H', data, TABLE + m*SIZE)


if '--show' in sys.argv:
    for m in range(COUNT):
        e = entry(m)
        if any(e):
            print(f"  карта {m:2d} {LOCATIONS.get(m,'?'):28s} {e}")
    sys.exit()

src, dst = int(sys.argv[1]), int(sys.argv[2])
print(f"карта {src} {LOCATIONS.get(src,'?')}: {entry(src)}")
print(f"карта {dst} {LOCATIONS.get(dst,'?')}: {entry(dst)}")
if dst >= COUNT:
    sys.exit(f"карта {dst} вне таблицы (только 0..{COUNT-1})")

data[TABLE + dst*SIZE: TABLE + (dst+1)*SIZE] = data[TABLE + src*SIZE: TABLE + (src+1)*SIZE]
out = os.path.join(RIG, 'konung2.exe')
open(out, 'wb').write(bytes(data))
print(f"запись скопирована {src} -> {dst}, записано в {out}")
print(f"проверка: карта {dst} теперь {entry(dst)}")
