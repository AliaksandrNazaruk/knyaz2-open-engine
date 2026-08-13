# -*- coding: utf-8 -*-
"""Охват полей записи: какие смещения движок трогает, а мы не знаем.

Второй обход «с другой стороны» (первый — `tools/coverage.py`). Функции мы
обошли почти все, но внутри функции можно перенести половину: движок читает у
записи юнита поле, о котором мы не догадываемся, и механика тихо расходится.

Считаем механически. Массивы записей лежат в exe по известным адресам с шагом
0x100, и Ghidra печатает обращения к их полям опознаваемой идиомой — именем
данных с адресом внутри первой записи:

    (&DAT_007b3c23)[iVar5] = ...      юниты  0x7B3C08 -> поле +0x1B
    (&DAT_0071e585)[n * 0x40] >> 0x18 отряды 0x71E56C -> поле +0x1C

Отсюда гистограмма: какое поле сколько функций трогает. Дальше сверяем с тем,
что моделируем сами — таблицы записей в `konung2/gamefile.py` и упоминания
`+0xNN` в комментариях порта. Что движок трогает часто, а у нас не названо
нигде, — то и есть незамеченная механика.

Метод НЕ ловит обращения через указатель-параметр (`*(int *)(param_1 + 0x4e)`):
там неизвестно, чья это запись. Зато то, что он ловит, — точно и без догадок.

    python tools/fields.py                    # юниты
    python tools/fields.py --record squad     # отряды
    python tools/fields.py --md docs/FIELDS_UNIT.md
"""
from __future__ import annotations

import argparse
import collections
import glob
import io
import os
import re

#: Известные массивы записей: имя -> (база, шаг, сколько записей).
RECORDS = {
    "unit": ("юниты", 0x7B3C08, 0x100),
    "squad": ("отряды", 0x71E56C, 0x100),
    "village": ("поселения", 0x83D408, 0x4A1),
    "item": ("предметы", 0x6F956C, 0x10),
    "object": ("объекты карты", 0x834768, 0x24),
}

DATA = re.compile(r"DAT_00([0-9a-f]{6})")
FIELD = re.compile(r"\+\s*0x([0-9A-Fa-f]{1,3})\b")


def touches(folder: str, base: int, stride: int) -> dict[int, set[str]]:
    """Смещение записи -> имена функций, которые его трогают."""
    found: dict[int, set[str]] = collections.defaultdict(set)
    low, high = base - stride, base + stride * 2
    for path in glob.glob(os.path.join(folder, "*.c")):
        name = os.path.basename(path)[:-2]
        try:
            text = io.open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for hit in DATA.findall(text):
            address = int(hit, 16)
            if not (low <= address < high):
                continue
            offset = (address - base) % stride
            found[offset].add(name)
    return found


#: Обращение через параметр или локальный указатель. Чья это запись — из
#: текста не видно, поэтому такие смещения идут отдельным списком: они не
#: доказательство, а НАВОДКА, куда смотреть. Именно так нашлись поля
#: поселения +0x3D8…+0x3DE, о которых мы не знали.
BY_POINTER = re.compile(r"(?:param_\d+|local_[0-9a-f]+)\s*\+\s*0x([0-9A-Fa-f]{1,3})\b")


def pointer_touches(folder: str) -> dict[int, set[str]]:
    """Смещение -> функции, которые адресуют его через указатель."""
    found: dict[int, set[str]] = collections.defaultdict(set)
    for path in glob.glob(os.path.join(folder, "*.c")):
        name = os.path.basename(path)[:-2]
        try:
            text = io.open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for hit in BY_POINTER.findall(text):
            found[int(hit, 16)].add(name)
    return found


def known(root: str) -> set[int]:
    """Смещения, которые порт хотя бы НАЗЫВАЕТ — в коде или в комментариях."""
    seen: set[int] = set()
    for folder, suffixes in (("konung2", (".py",)), ("knyaz2", (".js", ".py")),
                             ("docs", (".md",))):
        for base, _, files in os.walk(os.path.join(root, folder)):
            if "__pycache__" in base:
                continue
            for name in files:
                if not name.endswith(suffixes):
                    continue
                try:
                    text = io.open(os.path.join(base, name),
                                   encoding="utf-8").read()
                except (OSError, UnicodeDecodeError):
                    continue
                seen.update(int(hit, 16) for hit in FIELD.findall(text))
    return seen


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fields")
    parser.add_argument("--root", default=".")
    parser.add_argument("--record", default="unit", choices=sorted(RECORDS))
    parser.add_argument("--md")
    parser.add_argument("--limit", type=int, default=40)
    args = parser.parse_args(argv)

    title, base, stride = RECORDS[args.record]
    folder = os.path.join(args.root, "engine", "decompiled", "functions")
    found = touches(folder, base, stride)
    seen = known(args.root)
    rows = sorted(found.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    strangers = [(offset, users) for offset, users in rows if offset not in seen]

    print(f"{title}: база {base:#x}, шаг {stride:#x}")
    print(f"трогаемых смещений: {len(found)}, из них НЕ названы у нас: "
          f"{len(strangers)}")
    for offset, users in strangers[:12]:
        print(f"  +{offset:#04x}  функций {len(users):>2}  "
              f"{', '.join(sorted(users)[:4])}")
    if not args.md:
        return 0

    lines = [f"# Поля записи «{title}»", "",
             f"Отчёт `tools/fields.py --record {args.record}`. База "
             f"`{base:#x}`, шаг `{stride:#x}`. Считаны обращения вида "
             "`(&DAT_00xxxxxx)[i]` по всему декомпиляту: сколько РАЗНЫХ функций "
             "трогает каждое поле.", "",
             f"Трогаемых смещений: **{len(found)}**, из них не названы нигде у "
             f"нас: **{len(strangers)}**.", "",
             "## Не названы у нас", "",
             "| поле | функций | кто трогает |", "|---|---|---|"]
    for offset, users in strangers[:args.limit]:
        lines.append(f"| `+{offset:#04x}` | {len(users)} | "
                     f"{', '.join(sorted(users)[:6])} |")
    lines += ["", "## Все поля по частоте", "",
              "| поле | функций | знаем |", "|---|---|---|"]
    for offset, users in rows[:args.limit * 2]:
        lines.append(f"| `+{offset:#04x}` | {len(users)} | "
                     f"{'да' if offset in seen else '**нет**'} |")

    # Наводки через указатель — по всему декомпиляту, без привязки к записи.
    pointed = pointer_touches(folder)
    strange = sorted(((offset, users) for offset, users in pointed.items()
                      if offset not in seen),
                     key=lambda kv: (-len(kv[1]), kv[0]))
    lines += ["", "## Наводки: смещения через указатель, не названные у нас", "",
              "Чья это запись — из текста не видно (может оказаться и шагом "
              "массива, и полем). Список нужен как список мест для проверки, "
              "а не как доказательство.", "",
              f"Всего смещений через указатель: **{len(pointed)}**, "
              f"не названы нигде: **{len(strange)}**.", "",
              "| смещение | функций | кто трогает |", "|---|---|---|"]
    for offset, users in strange[:args.limit]:
        lines.append(f"| `+{offset:#05x}` | {len(users)} | "
                     f"{', '.join(sorted(users)[:6])} |")
    io.open(os.path.join(args.root, args.md), "w", encoding="utf-8").write(
        "\n".join(lines) + "\n")
    print(f"отчёт: {args.md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
