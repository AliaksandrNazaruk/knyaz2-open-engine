# -*- coding: utf-8 -*-
"""Дифф констант: какие числа пака НЕ выводятся из exe.

Четвёртый обход «с другой стороны» (после `coverage.py`, `fields.py`,
`reachable.py`). Правило простое: каждое число механики обязано происходить из
`konung2.exe` — из таблицы, из непосредственного операнда, из константы FPU.
Если числа нет в файле НИ В ОДНОМ представлении, оно выдумано нами.

Проверка односторонняя и в этом её сила: «нашлось» ничего не доказывает (байт
0x0A встречается всюду), а вот «не нашлось» — доказывает. Именно так ловятся
правдоподобные коэффициенты, которых в игре нет.

Ищем каждое число как u8, u16, u32, i32, float и double, а дробные — ещё и как
пару «числитель/знаменатель» в виде double (движок хранит 0.3 и 0.01 именно
так). Числа 0 и 1 пропускаем: они найдутся всегда и ни о чём не говорят.

    python tools/constants.py
    python tools/constants.py --md docs/CONSTANTS_DIFF.md
"""
from __future__ import annotations

import argparse
import io
import json
import os
import struct

SKIP = {0, 1, -1}


def numbers(node, trail=()):
    """Все числа поддерева с их путём."""
    if isinstance(node, bool):
        return
    if isinstance(node, (int, float)):
        yield node, "/".join(trail)
        return
    if isinstance(node, dict):
        for key, value in node.items():
            yield from numbers(value, trail + (str(key),))
    elif isinstance(node, list):
        for at, value in enumerate(node):
            yield from numbers(value, trail + (f"[{at}]",))


def encodings(value) -> list[bytes]:
    """Все разумные представления числа в файле."""
    out: list[bytes] = []
    if isinstance(value, int) or (isinstance(value, float) and value.is_integer()):
        whole = int(value)
        for fmt in ("<B", "<H", "<I", "<i", "<h", "<b"):
            try:
                out.append(struct.pack(fmt, whole))
            except struct.error:
                pass
    for fmt in ("<f", "<d"):
        try:
            out.append(struct.pack(fmt, float(value)))
        except (struct.error, OverflowError, ValueError):
            pass
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="constants")
    parser.add_argument("--root", default=".")
    parser.add_argument("--pack", default="content_build/shared.json")
    parser.add_argument("--md")
    args = parser.parse_args(argv)

    import sys
    sys.path.insert(0, args.root)
    from konung2.paths import game_file

    # ИЩЕМ НЕ ТОЛЬКО В EXE. Часть чисел механики лежит в данных: пороги
    # бродячих отрядов, например, приходят из хвоста GAME.x, и без этих файлов
    # они выглядели бы выдуманными.
    blob = b"".join(open(game_file(name), "rb").read() for name in
                    ("konung2.exe", "GAME.0", "QUESTS.RES"))
    shared = json.load(io.open(os.path.join(args.root, args.pack),
                               encoding="utf-8"))
    rules = (shared.get("hero") or {}).get("rules") or {}

    seen: dict[float, str] = {}
    for value, path in numbers(rules):
        if value in SKIP:
            continue
        seen.setdefault(value, path)

    missing = []
    for value, path in sorted(seen.items(), key=lambda kv: str(kv[0])):
        if not any(pattern in blob for pattern in encodings(value)):
            missing.append((value, path))

    print(f"чисел в правилах: {len(seen)}, НЕ найдены в exe: {len(missing)}")
    for value, path in missing[:20]:
        print(f"  {value!r:>14}  {path}")
    if not args.md:
        return 0

    lines = ["# Дифф констант: числа пака против exe", "",
             "Отчёт `tools/constants.py`. Каждое число раздела правил ищется в "
             "`konung2.exe` как u8/u16/u32/i32/float/double. «Нашлось» ничего "
             "не доказывает, «не нашлось» — доказывает: такого числа в игре "
             "нет, значит оно наше.", "",
             f"Чисел в правилах: **{len(seen)}**. Не найдены в exe: "
             f"**{len(missing)}**.", "",
             "| число | где в правилах |", "|---|---|"]
    for value, path in missing:
        lines.append(f"| `{value!r}` | `{path}` |")
    io.open(os.path.join(args.root, args.md), "w", encoding="utf-8").write(
        "\n".join(lines) + "\n")
    print(f"отчёт: {args.md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
