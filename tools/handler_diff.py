# -*- coding: utf-8 -*-
"""
Сверка обработчиков разговора двух сборок: общая ли у них нумерация.

ПОЧЕМУ НЕ ПОБАЙТНО. В командах сидят абсолютные адреса, и у разных сборок
они разные — сравнение сырых байтов даёт 0.357 против 0.378 у сдвига, то
есть чистый шум. Но разница ровно в операндах, а не в самих командах,
поэтому сравнивать надо РАЗОБРАННЫЙ код с обезличенными операндами:

    mov eax, dword ptr [0x84951c]   ->  mov eax, dword ptr [ADDR]
    je  0x434a90                    ->  je  +0x28   (смещение от начала)

Так обработчик 2 у обеих игр совпадает командой в команду.

Запуск:
    python tools/handler_diff.py            # сводка по всем
    python tools/handler_diff.py 5          # один обработчик, два столбца
    python tools/handler_diff.py --shift 2  # проверить сдвиг нумерации
"""
from __future__ import annotations

import argparse
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from capstone import CS_ARCH_X86, CS_MODE_32, Cs  # noqa: E402

from konung2.profile import CANON, LEGEND  # noqa: E402

#: Дальше одного обработчика код точно не тянется.
MAX_BYTES = 0x1000

#: Числа, которые заведомо не адреса: смещения полей, счётчики, маски.
#: Всё, что попадает в секции сборки, обезличиваем; мелочь оставляем — она
#: и есть смысл обработчика (какое поле читает, с чем сравнивает).
ADDRESS_LOW = 0x400000


def _engine():
    return Cs(CS_ARCH_X86, CS_MODE_32)


def instructions(profile, va: int):
    """Команды обработчика от начала до ret."""
    blob = profile.exe_bytes()
    offset = profile.va_to_foff(va)
    out = []
    for item in _engine().disasm(blob[offset:offset + MAX_BYTES], va):
        out.append(item)
        if item.mnemonic == "ret":
            break
    return out


def canonical(items) -> list[str]:
    """Команды с обезличенными адресами: и переходы, и ссылки на данные."""
    if not items:
        return []
    base = items[0].address
    out = []
    for item in items:
        operands = item.op_str
        # Переходы внутри обработчика — в смещение от его начала.
        if item.mnemonic.startswith("j") or item.mnemonic == "call":
            match = re.fullmatch(r"0x([0-9a-f]+)", operands)
            if match:
                target = int(match.group(1), 16)
                inside = items[0].address <= target <= items[-1].address
                operands = (f"+{target - base:#x}" if inside else "FAR")
        # Всё, что похоже на адрес в образе, — в заглушку. Порог, а не
        # шаблон вида «0x00xxxxxx»: capstone печатает без ведущих нулей,
        # и данные лежат высоко (0x84951C у нас, 0x87F3A4 у него), так что
        # по шаблону они не ловились вовсе — оттого сверка и давала ноль.
        operands = re.sub(
            r"0x[0-9a-f]+",
            lambda hit: ("ADDR" if int(hit.group(0), 16) >= ADDRESS_LOW
                         else hit.group(0)),
            operands)
        out.append(f"{item.mnemonic} {operands}".strip())
    return out


def table(profile) -> list[int]:
    blob = profile.exe_bytes()
    at, count = profile.need("handlers_at"), profile.need("handlers_count")
    return [struct.unpack_from("<I", blob, at + index * 4)[0]
            for index in range(count)]


def compare(shift: int = 0):
    ours, theirs = table(CANON), table(LEGEND)
    same, differ, missing = [], [], []
    for number, address in enumerate(ours):
        other = number + shift
        if not 0 <= other < len(theirs):
            missing.append(number)
            continue
        mine = canonical(instructions(CANON, address))
        yours = canonical(instructions(LEGEND, theirs[other]))
        (same if mine and mine == yours else differ).append(number)
    return same, differ, missing


def bodies(profile) -> list[tuple[str, ...]]:
    """Обезличенные тела всех обработчиков сборки."""
    return [tuple(canonical(instructions(profile, va))) for va in table(profile)]


def mapping():
    """Наш номер -> его номера с ТЕМ ЖЕ телом (и наоборот, чей свободен).

    Считается каждый с каждым, а не по сдвигу: между играми возможна
    ВСТАВКА, и тогда единого сдвига нет вовсе.
    """
    ours, theirs = bodies(CANON), bodies(LEGEND)
    index: dict[tuple[str, ...], list[int]] = {}
    for number, body in enumerate(theirs):
        if body:
            index.setdefault(body, []).append(number)
    out = {}
    for number, body in enumerate(ours):
        out[number] = index.get(body, []) if body else []
    return out, ours, theirs


def resolved() -> tuple[dict[int, int], dict[int, float], list[int]]:
    """Окончательное соответствие «наш номер -> его номер».

    Два прохода. Сперва ТОЧНЫЕ совпадения тела — они опорные. Потом
    пробелы: обработчик, который донор переделал, тела не повторяет, но
    место своё сохраняет, и подходящий кандидат ищется МЕЖДУ соседними
    опорами. Если он там один и похож — берём, иначе оставляем ненайденным.

    Возвращает соответствие, похожесть переделанных и список неопознанных.
    """
    import difflib
    found, ours, theirs = mapping()
    anchor = {number: hits[0] for number, hits in found.items()
              if len(hits) == 1}
    out = dict(anchor)
    scores: dict[int, float] = {}
    lost: list[int] = []
    for number in range(len(ours)):
        if number in out or not ours[number]:
            continue
        before = max((key for key in anchor if key < number), default=None)
        after = min((key for key in anchor if key > number), default=None)
        low = anchor[before] + (number - before) if before is not None else 0
        high = anchor[after] - (after - number) if after is not None else len(theirs) - 1
        window = range(max(0, min(low, high) - 1),
                       min(len(theirs), max(low, high) + 2))
        best, best_at = 0.0, None
        for candidate in window:
            if candidate in out.values() or not theirs[candidate]:
                continue
            ratio = difflib.SequenceMatcher(None, ours[number],
                                            theirs[candidate]).ratio()
            if ratio > best:
                best, best_at = ratio, candidate
        if best_at is not None and best >= 0.5:
            out[number] = best_at
            scores[number] = best
        else:
            lost.append(number)
    return out, scores, lost


def show_resolved() -> None:
    out, scores, lost = resolved()
    theirs = table(LEGEND)
    print("наш -> его, знак ! у переделанных (в скобках похожесть)")
    for number in sorted(out):
        note = f"  ! {scores[number]:.2f}" if number in scores else ""
        print(f"  {number:3d} -> {out[number]:3d}{note}")
    print()
    print(f"не опознаны: {lost}")
    print(f"его собственные (нашей пары нет): "
          f"{sorted(set(range(len(theirs))) - set(out.values()))}")
    order = [out[number] for number in sorted(out)]
    print(f"порядок не нарушен: {order == sorted(order)}")


def show_mapping() -> None:
    found, ours, theirs = mapping()
    matched = {number: hits[0] for number, hits in found.items()
               if len(hits) == 1}
    print(f"наших {len(ours)}, его {len(theirs)}; "
          f"однозначно опознано {len(matched)}")
    print()
    print("наш -> его   (пусто = тело не нашлось)")
    runs, start = [], None
    previous = None
    for number in range(len(ours)):
        other = matched.get(number)
        shift = None if other is None else other - number
        if shift != previous:
            if start is not None:
                runs.append((start, number - 1, previous))
            start, previous = number, shift
    runs.append((start, len(ours) - 1, previous))
    for low, high, shift in runs:
        span = f"{low}" if low == high else f"{low}..{high}"
        if shift is None:
            print(f"  {span:12s} тело не нашлось")
        else:
            print(f"  {span:12s} сдвиг {shift:+d}")
    print()
    used = set(matched.values())
    print(f"его обработчики без нашей пары: "
          f"{[n for n in range(len(theirs)) if n not in used]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("handler", nargs="?", type=int)
    parser.add_argument("--shift", type=int, default=0)
    parser.add_argument("--map", action="store_true",
                        help="полное соответствие каждый с каждым")
    parser.add_argument("--resolve", action="store_true",
                        help="окончательная таблица, с добором переделанных")
    args = parser.parse_args()

    if args.map:
        show_mapping()
        return 0
    if args.resolve:
        show_resolved()
        return 0

    if args.handler is not None:
        ours, theirs = table(CANON), table(LEGEND)
        number = args.handler
        mine = canonical(instructions(CANON, ours[number]))
        yours = canonical(instructions(LEGEND, theirs[number + args.shift]))
        print(f"обработчик {number}: наш 0x{ours[number]:08X}, "
              f"его 0x{theirs[number + args.shift]:08X}")
        for left, right in zip(mine + [""] * len(yours),
                               yours + [""] * len(mine)):
            mark = " " if left == right else "!"
            print(f"  {mark} {left:<36} {right}")
        return 0

    print("сдвиг  совпало  разошлось  за пределами")
    for shift in (0, 1, 2, -1, -2):
        same, differ, missing = compare(shift)
        mark = "  <--" if shift == 0 else ""
        print(f"{shift:5d}  {len(same):7d}  {len(differ):9d}  "
              f"{len(missing):12d}{mark}")
    same, differ, _ = compare(0)
    print()
    print(f"совпали командой в команду: {same}")
    print(f"разошлись: {differ}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
