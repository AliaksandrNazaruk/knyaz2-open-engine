# -*- coding: utf-8 -*-
"""Обратный охват движка: чего порт не касался вовсе.

Проверять свои утверждения по одному — долго и ненадёжно. Этот обход идёт с
другой стороны: берёт ВЕСЬ корпус функций движка и смотрит, какие из них
вообще нигде у нас не упомянуты. Мы всюду ссылаемся на адреса в комментариях
(«VA 0x41C944»), поэтому «ни одного упоминания» — надёжный признак механики,
которой в порте нет и которую никто не разбирал.

Три ведра:

* **в коде** — адрес встречается в `knyaz2/`, `konung2/` или `tests/`:
  механика перенесена или хотя бы задета;
* **только в доках** — разобрана в `docs/`, но кода нет. Это и есть очередь
  работ: изучено, не сделано;
* **нигде** — белое пятно.

Рантайм C (VA >= 0x442000: memcpy, файлы, printf) отсекается: это библиотека
Microsoft, а не механика игры. Порог задан по последней игровой функции —
поиск пути 0x441441 и мелкие помощники сразу за ним.

    python tools/coverage.py                 # сводка на экран
    python tools/coverage.py --md docs/ENGINE_COVERAGE.md
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re

#: Адрес в тексте: 0x0041C944 или 0x41c944 — обе записи в ходу.
ADDRESS = re.compile(r"0x0*4[0-9A-Fa-f]{5}")

#: Выше этого — рантайм C, а не игра.
RUNTIME_FROM = 0x442000

CORPUS = os.path.join("engine", "decompiled", "index.json")
CODE = (("knyaz2", (".js", ".py")), ("konung2", (".py",)), ("tests", (".py",)))
DOCS = (("docs", (".md",)),)


def mentions(folder: str, suffixes: tuple[str, ...]) -> set[int]:
    """Все адреса движка, упомянутые в дереве."""
    found: set[int] = set()
    for base, _, files in os.walk(folder):
        if "__pycache__" in base:
            continue
        for name in files:
            if not name.endswith(suffixes):
                continue
            try:
                text = io.open(os.path.join(base, name), encoding="utf-8").read()
            except (OSError, UnicodeDecodeError):
                continue
            found.update(int(hit, 16) for hit in ADDRESS.findall(text))
    return found


def gather(root: str, places) -> set[int]:
    found: set[int] = set()
    for folder, suffixes in places:
        found |= mentions(os.path.join(root, folder), suffixes)
    return found


def survey(root: str = ".") -> dict:
    corpus = json.load(io.open(os.path.join(root, CORPUS), encoding="utf-8"))
    functions = {int(row["entry"], 16): row for row in corpus
                 if int(row["entry"], 16) < RUNTIME_FROM}
    in_code = gather(root, CODE)
    in_docs = gather(root, DOCS)

    def rank(rows):
        return sorted(rows, key=lambda row: (-len(row.get("callers") or []),
                                             row["entry"]))

    ported = rank([row for va, row in functions.items() if va in in_code])
    studied = rank([row for va, row in functions.items()
                    if va not in in_code and va in in_docs])
    blank = rank([row for va, row in functions.items()
                  if va not in in_code and va not in in_docs])
    return {"всего": len(functions), "в коде": ported,
            "только в доках": studied, "нигде": blank}


def table(rows, limit: int) -> str:
    lines = ["| адрес | вызывающих | размер | зовут |", "|---|---|---|---|"]
    for row in rows[:limit]:
        callers = row.get("callers") or []
        lines.append(f"| `{row['entry']}` | {len(callers)} | "
                     f"{row.get('size', 0)} | {', '.join(callers[:5]) or '—'} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="coverage")
    parser.add_argument("--root", default=".")
    parser.add_argument("--md", help="записать отчёт в файл")
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args(argv)

    got = survey(args.root)
    total = got["всего"]
    head = (f"игровых функций (VA < {RUNTIME_FROM:#x}): {total}\n"
            f"упомянуты в коде порта: {len(got['в коде'])}\n"
            f"только в доках (разобрано, кода нет): {len(got['только в доках'])}\n"
            f"не упомянуты нигде: {len(got['нигде'])}")
    print(head)
    if not args.md:
        return 0
    body = [
        "# Охват движка портом", "",
        "Отчёт `tools/coverage.py`. Считает не наши слова о механиках, а сами",
        "адреса: какие функции движка порт упоминает, какие только разобраны в",
        "доках, а каких не касался никто. Рантайм C (VA >= "
        f"{RUNTIME_FROM:#x}) отсечён.", "",
        head.replace("\n", "\n\n"), "",
        "## Разобрано, но не перенесено", "",
        "Очередь работ: механика изучена, кода нет.", "",
        table(got["только в доках"], args.limit), "",
        "## Белые пятна", "",
        "Никто не смотрел вовсе.", "",
        table(got["нигде"], args.limit), "",
    ]
    io.open(os.path.join(args.root, args.md), "w", encoding="utf-8").write(
        "\n".join(body))
    print(f"отчёт: {args.md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
