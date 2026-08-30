# -*- coding: utf-8 -*-
"""
Числа для прогона Ghidra по одной из двух игр.

Отдельным файлом, потому что ВЛАДЕЛЕЦ АДРЕСОВ ОДИН — профиль игры. Прописать
границы секции кода в скрипт значило бы завести им второго хозяина, и рано
или поздно они разойдутся.

Печатает одной строкой, поля через ТАБУЛЯЦИЮ:

    путь_к_exe  имя_exe  код_снизу  код_сверху  таблица_обработчиков  сколько  куда_выгружать

Табуляция, а не пробел: путь к игре — «C:\\Program Files (x86)\\Князь…», и
по пробелам он развалится на четыре поля.

Запуск:
    python tools/ghidra_target.py canon
    python tools/ghidra_target.py legend
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from konung2.profile import CANON, IMAGE_BASE, LEGEND, sections  # noqa: E402

#: Ключ на командной строке -> профиль и куда складывать выгрузку.
TARGETS = {
    "canon": (CANON, "decompiled"),
    "legend": (LEGEND, "decompiled_legend"),
}

#: РЕДАКТОР КАРТ — не игра, профиля у него нет: границы секции читаются из
#: его собственного PE на лету (владелец адресов — сам файл), таблицы
#: обработчиков разговора у редактора не существует — нули.
EDITOR_EXE = Path(__file__).resolve().parent.parent / (
    "project/community/k2_tools/mapedit/edit.exe")

#: НИЖНЮЮ ГРАНИЦУ КОДА ПОДНИМАЕМ. В данных попадаются мелкие числа вроде
#: 0x410002, и это не адреса; подметатель на них заводил бы мусорные функции.
CODE_SKIP = 0x100

#: Имя секции кода. У обеих сборок одно — это компоновщик Watcom.
CODE_SECTION = "BEGTEXT"


def code_bounds(profile) -> tuple[int, int]:
    """Границы секции кода этой сборки, виртуальные адреса."""
    for name, rva, size, _ in sections(profile.exe_bytes()):
        if name == CODE_SECTION:
            return IMAGE_BASE + rva + CODE_SKIP, IMAGE_BASE + rva + size
    raise SystemExit(f"{profile.name}: нет секции {CODE_SECTION}")


def foff_to_va(profile, offset: int) -> int:
    """Файловое смещение -> виртуальный адрес. Обратное va_to_foff."""
    for _, rva, size, at in sections(profile.exe_bytes()):
        if at <= offset < at + size:
            return IMAGE_BASE + rva + (offset - at)
    raise SystemExit(f"{profile.name}: смещение 0x{offset:X} вне секций")


def main() -> int:
    key = sys.argv[1] if len(sys.argv) > 1 else "canon"
    if key == "editor":
        data = EDITOR_EXE.read_bytes()
        for name, rva, size, _ in sections(data):
            if name == CODE_SECTION:
                low = IMAGE_BASE + rva + CODE_SKIP
                high = IMAGE_BASE + rva + size
                break
        else:
            raise SystemExit(f"editor: нет секции {CODE_SECTION}")
        print("	".join((str(EDITOR_EXE), "edit.exe",
                         f"0x{low:X}", f"0x{high:X}", "0x0", "0",
                         "decompiled_editor")))
        return 0
    if key not in TARGETS:
        raise SystemExit(f"неизвестная игра «{key}»: есть {sorted(TARGETS)}")
    profile, out = TARGETS[key]
    if not profile.available():
        raise SystemExit(f"{profile.name}: нет {profile.file(profile.exe)}")
    low, high = code_bounds(profile)
    handlers = foff_to_va(profile, profile.need("handlers_at"))
    print("\t".join((profile.file(profile.exe), profile.exe,
                     f"0x{low:X}", f"0x{high:X}", f"0x{handlers:X}",
                     str(profile.need("handlers_count")), out)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
