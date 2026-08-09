# -*- coding: utf-8 -*-
"""
Дизассемблер поверх konung2.exe.

Он нужен там, где декомпилятор бессилен: все вычисления с плавающей точкой
Ghidra сворачивает в загадочное ``FUN_00442bf0()`` — а это всего лишь
округление вершины стека сопроцессора, и что именно там лежало, видно
только в командах. Поэтому формулы (урон, цены, отрава) читаем отсюда.

    python tools/disasm.py 0x41bb10            # функция целиком
    python tools/disasm.py 0x41bb10 --lines 40 # первые сорок команд
    python tools/disasm.py 0x41bb10 --find 833b00   # где пишут в поле
"""
from __future__ import annotations

import argparse
import sys

from capstone import CS_ARCH_X86, CS_MODE_32, Cs

sys.path.insert(0, ".")
from konung2.exetables import va_to_foff          # noqa: E402
from konung2.paths import game_file               # noqa: E402

#: Дальше этого одна функция точно не тянется.
MAX_BYTES = 0x4000


def disassemble(va: int, count: int = 0):
    """Команды с адреса до ``ret`` (или пока не кончится счёт)."""
    with open(game_file("konung2.exe"), "rb") as stream:
        stream.seek(va_to_foff(va))
        code = stream.read(MAX_BYTES)
    engine = Cs(CS_ARCH_X86, CS_MODE_32)
    out = []
    for instruction in engine.disasm(code, va):
        out.append(instruction)
        if count and len(out) >= count:
            break
        if not count and instruction.mnemonic == "ret":
            break
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("va")
    parser.add_argument("--lines", type=int, default=0)
    parser.add_argument("--find", default="", help="показать только строки с этим текстом")
    parser.add_argument("--context", type=int, default=6)
    args = parser.parse_args()

    listing = disassemble(int(args.va, 0), args.lines)
    rows = [f"{i.address:08x}  {i.mnemonic:<7} {i.op_str}" for i in listing]
    if args.find:
        keep = set()
        for index, row in enumerate(rows):
            if args.find.lower() in row.lower():
                keep.update(range(max(0, index - args.context),
                                  min(len(rows), index + args.context + 1)))
        rows = [rows[i] if i in keep else "..."
                for i in sorted(keep | {i for i in range(len(rows)) if i in keep})]
    print("\n".join(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
