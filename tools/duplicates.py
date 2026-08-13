# -*- coding: utf-8 -*-
"""Дубли и самодеятельность: один адрес движка — одна реализация.

Как отличить правильную механику от паразитной? У нас для этого уже есть
разметка: по уговору каждая перенесённая механика НАЗЫВАЕТ адрес движка, из
которого снята («VA 0x41C944»). Значит:

* **дубль** — один адрес заявлен ДВУМЯ разными функциями порта. Так вышло с
  выбором рабочего места: `pickWorkplace` в units.js и почти написанный
  второй перенос той же `0x412C0C`;
* **самодеятельность** — функция в модуле механики не называет НИ ОДНОГО
  адреса. Либо это связка (тогда нормально), либо выдуманное правило.

Обратную сторону считает `tools/coverage.py`: функции движка, которых у нас
нет вовсе. Вместе они замыкают круг — что не перенесено, что перенесено
дважды и что написано из головы.

Адрес приписывается функции вместе с её ШАПКОЙ: комментарий перед
определением — это и есть место, где мы пишем, откуда снято.

    python tools/duplicates.py
    python tools/duplicates.py --md docs/PORT_DUPLICATES.md
"""
from __future__ import annotations

import argparse
import collections
import io
import os
import re

ADDRESS = re.compile(r"0x0*4[0-9A-Fa-f]{5}")
RUNTIME_FROM = 0x442000

#: Определения, которые считаем «функцией порта».
JS_DEF = re.compile(r"^(?:export\s+)?(?:async\s+)?function\s+(\w+)", re.M)
PY_DEF = re.compile(r"^def\s+(\w+)", re.M)

#: Где ищем механику. Разметка, сборка пака и тесты сюда не входят.
PLACES = (("knyaz2/web/static", ".js", JS_DEF),
          ("konung2", ".py", PY_DEF))

#: Файлы, где адреса — справочник, а не перенос.
SKIP = {"quests.py", "exetables.py", "paths.py"}


#: Строка комментария — только из таких состоит ШАПКА функции.
COMMENT = re.compile(r"^\s*(?://|#)")


def head_of(text: str, at: int) -> str:
    """Сплошной комментарий НЕПОСРЕДСТВЕННО над определением.

    Только он считается объявлением «снято отсюда». Шапка модуля и чужие
    пояснения в счёт не идут: иначе один адрес из заголовка файла приписался
    бы всем функциям подряд, и настоящие дубли утонули бы в шуме — так первая
    редакция этого обхода и вышла бесполезной (386 «дублей» из 481 адреса).
    """
    lines = text[:at].split("\n")
    if lines and not lines[-1].strip():
        lines = lines[:-1]
    out = []
    for line in reversed(lines):
        if not line.strip() or not COMMENT.match(line):
            break
        out.append(line)
    return "\n".join(reversed(out))


def blocks(text: str, pattern: re.Pattern):
    """(имя, шапка, тело) — шапка отдельно, чтобы отличить заявку от ссылки."""
    marks = [(m.start(), m.group(1)) for m in pattern.finditer(text)]
    for index, (start, name) in enumerate(marks):
        tail = marks[index + 1][0] if index + 1 < len(marks) else len(text)
        yield name, head_of(text, start), text[start:tail]


def survey(root: str = "."):
    claims: dict[int, set[str]] = collections.defaultdict(set)
    silent: list[tuple[str, str, int]] = []
    for folder, suffix, pattern in PLACES:
        for base, _, files in os.walk(os.path.join(root, folder)):
            if "__pycache__" in base:
                continue
            for name in files:
                if not name.endswith(suffix) or name in SKIP:
                    continue
                path = os.path.join(base, name)
                try:
                    text = io.open(path, encoding="utf-8").read()
                except (OSError, UnicodeDecodeError):
                    continue
                short = os.path.relpath(path, root).replace("\\", "/")
                for function, head, body in blocks(text, pattern):
                    # ЗАЯВКА — первый адрес в собственной шапке функции.
                    # Именно так мы и пишем: «(VA 0x41C944)» в первых строках
                    # комментария над определением.
                    claim = ADDRESS.search(head)
                    if claim is None or int(claim.group(0), 16) >= RUNTIME_FROM:
                        if not ADDRESS.search(body):
                            silent.append((short, function, body.count("\n")))
                        continue
                    claims[int(claim.group(0), 16)].add(f"{short}::{function}")
    doubles = {va: sorted(who) for va, who in claims.items() if len(who) > 1}
    silent.sort(key=lambda row: -row[2])
    return claims, doubles, silent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="duplicates")
    parser.add_argument("--root", default=".")
    parser.add_argument("--md")
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--silent-from", type=int, default=25,
                        help="с какого размера показывать функции без адреса")
    args = parser.parse_args(argv)

    claims, doubles, silent = survey(args.root)
    big = [row for row in silent if row[2] >= args.silent_from]
    head = (f"адресов заявлено: {len(claims)}\n"
            f"заявлены дважды и более: {len(doubles)}\n"
            f"функций без единого адреса: {len(silent)} "
            f"(крупнее {args.silent_from} строк: {len(big)})")
    print(head)
    for va, who in sorted(doubles.items())[:12]:
        print(f"  {va:#010x}  {', '.join(who)}")
    if not args.md:
        return 0

    lines = ["# Дубли и самодеятельность в порте", "",
             "Отчёт `tools/duplicates.py`. Различитель — ссылка на адрес "
             "движка: каждая перенесённая механика называет, откуда снята. "
             "Адрес, заявленный двумя функциями, — дубль; функция без единой "
             "ссылки — либо связка, либо выдуманное правило.", "",
             head.replace("\n", "\n\n"), "",
             "## Один адрес — две реализации", "",
             "| адрес | кто заявляет |", "|---|---|"]
    for va, who in sorted(doubles.items()):
        lines.append(f"| `{va:#010x}` | {', '.join(f'`{x}`' for x in who)} |")
    lines += ["", "## Функции без единого адреса, по размеру", "",
              "Связка и разметка тут нормальны; смотреть надо на те, что "
              "считают правила.", "",
              "| файл и функция | строк |", "|---|---|"]
    for path, function, size in big[:args.limit]:
        lines.append(f"| `{path}::{function}` | {size} |")
    io.open(os.path.join(args.root, args.md), "w", encoding="utf-8").write(
        "\n".join(lines) + "\n")
    print(f"отчёт: {args.md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
