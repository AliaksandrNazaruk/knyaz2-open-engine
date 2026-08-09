# -*- coding: utf-8 -*-
"""
Карта движка: где что лежит в konung2.exe и что из этого уже перенесено.

Раньше каждый вопрос к бинарнику начинался с нуля: угадать адрес, разобрать
окно дизассемблером, догадаться о смысле. Эта карта убирает повторное
раскапывание — она знает три вещи:

* ``engine/decompiled/index.json`` — все функции, найденные Ghidra: адрес,
  размер, кто вызывает, кого вызывает, на какие данные ссылается;
* ``engine/decompiled/functions/0x004xxxxx.c`` — их же декомпилированный код;
* ``engine/names.json`` — наши имена и заметки, собранные из комментариев
  репозитория: там уже стоят сотни адресов вида ``VA 0x425DB4``.

Команды::

    python tools/engine_map.py collect          # пересобрать names.json
    python tools/engine_map.py info 0x425DB4    # всё про адрес
    python tools/engine_map.py refs 0x460FB4    # кто читает эту таблицу
    python tools/engine_map.py search "0x5c"    # поиск по декомпилированному
    python tools/engine_map.py todo              # что найдено, но не перенесено
    python tools/engine_map.py coverage          # сколько секции кода разобрано
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "engine"
DECOMPILED = ENGINE / "decompiled"
INDEX = DECOMPILED / "index.json"
FUNCTIONS = DECOMPILED / "functions"
NAMES = ENGINE / "names.json"

#: Где искать наши упоминания адресов движка.
SOURCES = ("konung2/**/*.py", "knyaz2/**/*.py", "knyaz2/web/static/*.js",
           "tools/*.py", "tests/*.py", "docs/**/*.md")
#: Адрес движка: код 0x41xxxx…0x44xxxx, данные 0x45xxxx и выше.
#:
#: Восьмизначная форма (0x0041896C) — не прихоть: так их пишет Ghidra, и так
#: озаглавлены все двадцать разделов docs/ENGINE_SCOUT.md. Пока `00` не было в
#: шаблоне, вся эта разведка не попадала в names.json, и уже разобранные
#: функции числились нетронутыми — команда todo врала на двадцать штук.
ADDRESS = re.compile(r"0x(?:00)?(?:4[0-9A-Fa-f]{5}|[5-8][0-9A-Fa-f]{5})")


def load_index() -> dict[int, dict]:
    if not INDEX.is_file():
        return {}
    records = json.loads(INDEX.read_text(encoding="utf-8"))
    return {int(item["entry"], 16): item for item in records}


def load_names() -> dict[int, list[dict]]:
    if not NAMES.is_file():
        return {}
    raw = json.loads(NAMES.read_text(encoding="utf-8"))
    return {int(key, 16): value for key, value in raw.items()}


def collect() -> dict[int, list[dict]]:
    """Собрать все адреса, упомянутые в наших исходниках, с их строками."""
    found: dict[int, list[dict]] = defaultdict(list)
    for pattern in SOURCES:
        for path in ROOT.glob(pattern):
            if not path.is_file() or "build" in path.parts:
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            for number, line in enumerate(lines, 1):
                for match in ADDRESS.finditer(line):
                    address = int(match.group(0), 16)
                    found[address].append({
                        "file": path.relative_to(ROOT).as_posix(),
                        "line": number,
                        "text": line.strip()[:200],
                    })
    return dict(sorted(found.items()))


def command_collect() -> int:
    found = collect()
    ENGINE.mkdir(parents=True, exist_ok=True)
    NAMES.write_text(
        json.dumps({f"0x{address:06X}": rows for address, rows in found.items()},
                   ensure_ascii=False, indent=1),
        encoding="utf-8")
    functions = sum(1 for address in found if 0x410000 <= address < 0x44B800)
    print(f"адресов в наших исходниках: {len(found)}, из них в коде: {functions}")
    print(f"записано: {NAMES.relative_to(ROOT)}")
    return 0


def function_of(index: dict[int, dict], address: int) -> dict | None:
    """Функция, внутри которой лежит адрес."""
    best = None
    for entry, record in index.items():
        if entry <= address < entry + record.get("size", 0):
            return record
        if entry <= address and (best is None or entry > int(best["entry"], 16)):
            best = record
    return best


def command_info(text: str) -> int:
    address = int(text, 16)
    index = load_index()
    names = load_names()
    record = function_of(index, address) if index else None

    print(f"адрес 0x{address:06X}")
    if record:
        entry = int(record["entry"], 16)
        inside = "начало функции" if entry == address else f"внутри функции 0x{entry:06X}"
        print(f"  {inside}: {record['name']}, размер {record['size']}")
        print(f"  вызывают: {', '.join(record['callers']) or '—'}")
        print(f"  вызывает: {', '.join(record['callees'][:12]) or '—'}")
        path = FUNCTIONS / f"{record['entry']}.c"
        if path.is_file():
            print(f"  код: {path.relative_to(ROOT)}")
    elif index:
        print("  функции с таким адресом Ghidra не нашла")
    else:
        print("  указателя нет — сначала прогоните tools/ghidra_decompile.sh")

    mentions = names.get(address, [])
    if mentions:
        print("  у нас уже упомянут:")
        for row in mentions[:10]:
            print(f"    {row['file']}:{row['line']}  {row['text']}")
    else:
        print("  в наших исходниках не упомянут")
    return 0


def command_refs(text: str) -> int:
    address = int(text, 16)
    index = load_index()
    tag = f"0x{address:08x}"
    users = [record for record in index.values() if tag in record.get("data", [])]
    print(f"на 0x{address:06X} ссылаются функций: {len(users)}")
    for record in sorted(users, key=lambda r: r["entry"]):
        print(f"  {record['entry']}  {record['name']}  (размер {record['size']})")
    return 0


def command_search(pattern: str, limit: int = 40) -> int:
    regex = re.compile(pattern, re.IGNORECASE)
    if not FUNCTIONS.is_dir():
        print("нет декомпилированного кода — прогоните tools/ghidra_decompile.sh")
        return 1
    hits = 0
    for path in sorted(FUNCTIONS.glob("*.c")):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for number, line in enumerate(lines, 1):
            if regex.search(line):
                print(f"{path.stem}:{number}  {line.strip()[:160]}")
                hits += 1
                if hits >= limit:
                    print("…")
                    return 0
    print(f"совпадений: {hits}")
    return 0


def command_todo(limit: int = 30) -> int:
    """Крупные функции, которых мы ещё ни разу не упоминали."""
    index = load_index()
    names = load_names()
    if not index:
        print("нет указателя — сначала прогоните tools/ghidra_decompile.sh")
        return 1
    known = set()
    for address in names:
        record = function_of(index, address)
        if record:
            known.add(record["entry"])
    rest = [r for r in index.values() if r["entry"] not in known]
    rest.sort(key=lambda r: r["size"], reverse=True)
    print(f"функций всего {len(index)}, упомянуто у нас {len(known)}, "
          f"нетронутых {len(rest)}")
    for record in rest[:limit]:
        print(f"  {record['entry']}  размер {record['size']:5d}  "
              f"вызывают {len(record['callers'])}")
    return 0


#: Секция кода BEGTEXT в konung2.exe: заголовок PE даёт VA 0x410000 и
#: 243712 байт сырого размера. Считаем покрытие относительно неё.
CODE_START, CODE_SIZE = 0x410000, 243712


def command_coverage(limit: int = 10) -> int:
    """Сколько секции кода разобрано и где остались дыры.

    Ghidra заводит функцию по CALL, поэтому точки входа из таблиц
    указателей она пропускает (см. tools/ghidra/MakeMissingFunctions.java).
    Эта команда показывает, много ли осталось непокрытым.
    """
    index = load_index()
    if not index:
        print("нет указателя — сначала прогоните tools/ghidra_decompile.sh")
        return 1
    end = CODE_START + CODE_SIZE
    spans = sorted((address, address + record["size"])
                   for address, record in index.items())
    covered, cursor, gaps = 0, CODE_START, []
    for start, stop in spans:
        if start > cursor:
            gaps.append((cursor, start))
        covered += max(0, min(stop, end) - max(start, cursor, CODE_START))
        cursor = max(cursor, stop)
    if cursor < end:
        gaps.append((cursor, end))
    print(f"секция кода 0x{CODE_START:06X}..0x{end:06X} — {CODE_SIZE} байт")
    print(f"функций {len(index)}, покрыто {covered} байт "
          f"({covered * 100 / CODE_SIZE:.1f}%)")
    print(f"не покрыто {CODE_SIZE - covered} байт в {len(gaps)} дырах")
    for start, stop in sorted(gaps, key=lambda g: g[1] - g[0], reverse=True)[:limit]:
        print(f"  0x{start:06X}..0x{stop:06X}  {stop - start:5d} байт")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="engine_map")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("collect", help="пересобрать карту наших упоминаний")
    info = commands.add_parser("info", help="всё, что известно про адрес")
    info.add_argument("address")
    refs = commands.add_parser("refs", help="кто ссылается на адрес данных")
    refs.add_argument("address")
    search = commands.add_parser("search", help="поиск по декомпилированному коду")
    search.add_argument("pattern")
    search.add_argument("--limit", type=int, default=40)
    todo = commands.add_parser("todo", help="крупные функции, которых мы не касались")
    todo.add_argument("--limit", type=int, default=30)
    coverage = commands.add_parser("coverage", help="сколько секции кода разобрано")
    coverage.add_argument("--limit", type=int, default=10)

    args = parser.parse_args(argv)
    if args.command == "collect":
        return command_collect()
    if args.command == "info":
        return command_info(args.address)
    if args.command == "refs":
        return command_refs(args.address)
    if args.command == "search":
        return command_search(args.pattern, args.limit)
    if args.command == "todo":
        return command_todo(args.limit)
    if args.command == "coverage":
        return command_coverage(args.limit)
    return 1


if __name__ == "__main__":
    sys.exit(main())
