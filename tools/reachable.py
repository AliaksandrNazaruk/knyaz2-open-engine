# -*- coding: utf-8 -*-
"""Что движок исполняет КАЖДЫЙ ТАКТ, а мы не исполняем никогда.

Третий обход «с другой стороны» (после `tools/coverage.py` и `tools/fields.py`).
Охват по упоминаниям показывает, чего мы не касались вообще; здесь вопрос
острее: какие функции движка достижимы из главного игрового цикла — то есть
работают в оригинале всегда, — и каких из них нет у нас.

Граф вызовов берётся из `engine/decompiled/index.json` (поля `callees`).
Корень по умолчанию — `0x438A00`, главный цикл карты: до него доходит
сообщение WM_USER из `0x42F1EF`, и во всей секции кода вызов ровно один.

Глубина в отчёте — сколько вызовов отделяет функцию от главного цикла: чем
меньше, тем ближе к сердцу и тем больнее её отсутствие.

    python tools/reachable.py
    python tools/reachable.py --root-va 0x00438a00 --md docs/ENGINE_TICK.md
"""
from __future__ import annotations

import argparse
import collections
import io
import json
import os
import re

ADDRESS = re.compile(r"0x0*4[0-9A-Fa-f]{5}")
RUNTIME_FROM = 0x442000
MAIN_LOOP = 0x00438A00


def mentions(root: str, places) -> set[int]:
    found: set[int] = set()
    for folder, suffixes in places:
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
                found.update(int(hit, 16) for hit in ADDRESS.findall(text))
    return found


def walk(functions: dict[int, dict], start: int) -> dict[int, int]:
    """Достижимые из start: адрес -> глубина (вширь, поэтому кратчайшая)."""
    depth = {start: 0}
    queue = collections.deque([start])
    while queue:
        current = queue.popleft()
        for callee in functions.get(current, {}).get("callees") or []:
            address = int(callee, 16)
            if address in depth or address >= RUNTIME_FROM:
                continue
            depth[address] = depth[current] + 1
            queue.append(address)
    return depth


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="reachable")
    parser.add_argument("--root", default=".")
    parser.add_argument("--root-va", default=hex(MAIN_LOOP))
    parser.add_argument("--md")
    parser.add_argument("--limit", type=int, default=60)
    args = parser.parse_args(argv)

    corpus = json.load(io.open(os.path.join(
        args.root, "engine", "decompiled", "index.json"), encoding="utf-8"))
    functions = {int(row["entry"], 16): row for row in corpus}
    start = int(args.root_va, 16)
    depth = walk(functions, start)
    in_code = mentions(args.root, (("knyaz2", (".js", ".py")),
                                   ("konung2", (".py",)), ("tests", (".py",))))
    in_docs = mentions(args.root, (("docs", (".md",)),))

    missing = [(va, level) for va, level in depth.items() if va not in in_code]
    missing.sort(key=lambda pair: (pair[1],
                                   -len(functions.get(pair[0], {}).get("callers") or []),
                                   pair[0]))
    head = (f"достижимо из {args.root_va}: {len(depth)} функций\n"
            f"из них есть в коде порта: {len(depth) - len(missing)}\n"
            f"НЕТ в коде порта: {len(missing)} "
            f"(в доках разобрано: {sum(1 for va, _ in missing if va in in_docs)})")
    print(head)
    for va, level in missing[:10]:
        row = functions.get(va, {})
        print(f"  {va:#010x}  глубина {level}  размер {row.get('size', 0):>5}"
              f"  {'разобрана в доках' if va in in_docs else 'нигде'}")
    if not args.md:
        return 0

    lines = ["# Что движок делает каждый такт, а порт — нет", "",
             f"Отчёт `tools/reachable.py`. Корень — `{args.root_va}`, главный "
             "цикл карты. Граф вызовов из `engine/decompiled/index.json`; "
             f"рантайм C (VA >= {RUNTIME_FROM:#x}) отсечён. Глубина — сколько "
             "вызовов отделяет функцию от цикла.", "",
             head.replace("\n", "\n\n"), "",
             "| адрес | глубина | размер | вызывающих | в доках |",
             "|---|---|---|---|---|"]
    for va, level in missing[:args.limit]:
        row = functions.get(va, {})
        lines.append(f"| `{va:#010x}` | {level} | {row.get('size', 0)} | "
                     f"{len(row.get('callers') or [])} | "
                     f"{'да' if va in in_docs else '**нет**'} |")
    io.open(os.path.join(args.root, args.md), "w", encoding="utf-8").write(
        "\n".join(lines) + "\n")
    print(f"отчёт: {args.md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
