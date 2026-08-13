# -*- coding: utf-8 -*-
"""Слепок памяти живого движка и сравнение слепков.

Пятый обход, и первый ЭМПИРИЧЕСКИЙ. Четыре предыдущих (`coverage`, `fields`,
`reachable`, `constants`) отвечают на заданный вопрос; этот показывает всё поле
сразу: что движок пишет в свои массивы, пока игра идёт.

Понимать механику для этого не нужно — достаточно увидеть, что через триста
тактов у оригинала в счётчике места стоит одно, а у нас другое. Дальше уже
понятно, куда смотреть в декомпиляте.

Адреса массивов добыты разбором и записаны в `konung2/gamefile.py`; образ
грузится по 0x400000, перемещения у сборок 2004 года нет, поэтому адреса
одинаковы от запуска к запуску.

    python tools/snapshot.py --list                    # найти процесс
    python tools/snapshot.py --out слепок1.bin         # снять
    python tools/snapshot.py --diff слепок1.bin слепок2.bin

Читаем чужой процесс через ReadProcessMemory: игра своя, всё локально, ничего
обходить не требуется. Права администратора не нужны — процесс запущен тем же
пользователем.
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import io
import json
import os
import struct

#: Что снимаем: имя -> (адрес, размер записи, сколько записей).
AREAS = {
    "squads":   (0x0071E56C, 0x100, 200),    # отряды
    "items":    (0x006F956C, 0x010, 1000),   # записи предметов
    "cells":    (0x005662BC, 0x004, 0xA000), # поле клеток карты
    "units":    (0x007B3C08, 0x100, 2000),   # юниты
    "objects":  (0x00834768, 0x024, 1000),   # объекты карты
    "villages": (0x0083D408, 0x4A1, 12),     # поселения
}

#: Отдельные глобалы, за которыми полезно следить.
GLOBALS = {
    "tick":       0x0084962C,   # мировой такт
    "map":        0x008496C8,   # номер текущей карты
    "difficulty": 0x0084958C,
    "night":      0x008495CC,
}

PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
TH32CS_SNAPPROCESS = 0x0002


class ENTRY(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD),
                ("th32ProcessID", wt.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
                ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
                ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wt.DWORD), ("szExeFile", ctypes.c_char * 260)]


def processes() -> list[tuple[int, str]]:
    kernel = ctypes.windll.kernel32
    snapshot = kernel.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == -1:
        return []
    entry = ENTRY()
    entry.dwSize = ctypes.sizeof(ENTRY)
    out = []
    if kernel.Process32First(snapshot, ctypes.byref(entry)):
        while True:
            out.append((entry.th32ProcessID,
                        entry.szExeFile.decode("cp1251", "replace")))
            if not kernel.Process32Next(snapshot, ctypes.byref(entry)):
                break
    kernel.CloseHandle(snapshot)
    return out


def find(name: str = "konung2") -> int | None:
    for pid, exe in processes():
        if name.lower() in exe.lower():
            return pid
    return None


def read(pid: int, address: int, size: int) -> bytes | None:
    kernel = ctypes.windll.kernel32
    handle = kernel.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION,
                                False, pid)
    if not handle:
        return None
    try:
        buffer = ctypes.create_string_buffer(size)
        got = ctypes.c_size_t(0)
        ok = kernel.ReadProcessMemory(handle, ctypes.c_void_p(address), buffer,
                                      size, ctypes.byref(got))
        return buffer.raw[:got.value] if ok else None
    finally:
        kernel.CloseHandle(handle)


def take(pid: int) -> dict:
    """Слепок: все области плюс глобалы."""
    shot = {"pid": pid, "areas": {}, "globals": {}}
    for name, (address, stride, count) in AREAS.items():
        blob = read(pid, address, stride * count)
        shot["areas"][name] = blob or b""
    for name, address in GLOBALS.items():
        blob = read(pid, address, 4)
        shot["globals"][name] = struct.unpack("<i", blob)[0] if blob else None
    return shot


def save(shot: dict, path: str) -> None:
    """Формат простой: заголовок JSON, затем области подряд."""
    head = {"pid": shot["pid"], "globals": shot["globals"],
            "areas": {name: len(blob) for name, blob in shot["areas"].items()},
            "order": list(shot["areas"])}
    with open(path, "wb") as handle:
        line = json.dumps(head, ensure_ascii=False).encode("utf-8")
        handle.write(struct.pack("<I", len(line)) + line)
        for name in head["order"]:
            handle.write(shot["areas"][name])


def load(path: str) -> dict:
    with open(path, "rb") as handle:
        size, = struct.unpack("<I", handle.read(4))
        head = json.loads(handle.read(size).decode("utf-8"))
        areas = {}
        for name in head["order"]:
            areas[name] = handle.read(head["areas"][name])
    return {"pid": head["pid"], "globals": head["globals"], "areas": areas}


def diff(first: dict, second: dict, limit: int = 40) -> list[str]:
    """Что изменилось: по записям и полям, а не по голым байтам."""
    lines = []
    for name in ("tick", "map", "difficulty", "night"):
        was, now = first["globals"].get(name), second["globals"].get(name)
        if was != now:
            lines.append(f"глобал {name}: {was} -> {now}")
    for name, (address, stride, count) in AREAS.items():
        one, two = first["areas"].get(name, b""), second["areas"].get(name, b"")
        if not one or len(one) != len(two):
            continue
        changed = []
        for index in range(count):
            at = index * stride
            left, right = one[at:at + stride], two[at:at + stride]
            if left == right:
                continue
            fields = [offset for offset in range(stride)
                      if left[offset] != right[offset]]
            changed.append((index, fields))
        if not changed:
            continue
        lines.append(f"\n{name}: изменилось записей {len(changed)}")
        for index, fields in changed[:limit]:
            подпись = ", ".join(f"+{offset:#04x}" for offset in fields[:12])
            lines.append(f"  запись {index}: поля {подпись}"
                         + (" …" if len(fields) > 12 else ""))
    return lines


def places(pid: int, number: int) -> tuple[int, dict[int, tuple]] | None:
    """Такт и места поселения нужной карты — дёшево, без полного слепка."""
    tick = read(pid, GLOBALS["tick"], 4)
    address, stride, count = AREAS["villages"]
    blob = read(pid, address, stride * count)
    if not tick or not blob:
        return None
    for index in range(count):
        record = blob[index * stride:(index + 1) * stride]
        if len(record) < stride or record[3] != number:
            continue
        out = {}
        for slot in range(record[0] + record[1] + 7):
            at = 0x18 + slot * 8
            kind, state, _ = struct.unpack_from("<bBH", record, at)
            timer, = struct.unpack_from("<h", record, at + 6)
            if kind >= 0:
                out[slot] = (kind, state, timer)
        return struct.unpack("<i", tick)[0], out
    return None


def watch(pid: int, number: int, times: int, every: float) -> None:
    """Следим за стройкой: печатаем только то, что изменилось.

    Счётчик места движок убавляет не каждый кадр, поэтому важен НЕ секундомер,
    а мировой такт (0x84962C) — он снимается тем же чтением.
    """
    import time
    было = None
    for _ in range(times):
        got = places(pid, number)
        if got is None:
            print("не прочиталось")
            return
        tick, now = got
        if было is None:
            строится = {s: v for s, v in now.items() if v[2] or v[1] not in (0, 3)}
            print(f"такт {tick}: мест {len(now)}, из них в работе {len(строится)}")
            for slot, (kind, state, timer) in sorted(строится.items()):
                print(f"   место {slot} вид {kind}: ступень {state} счётчик {timer}")
        else:
            меняется = {s: v for s, v in now.items() if было[1].get(s) != v}
            if меняется:
                прошло = tick - было[0]
                print(f"такт {tick} (+{прошло}):")
                for slot, (kind, state, timer) in sorted(меняется.items()):
                    сколько, ступень = было[1][slot][2], было[1][slot][1]
                    print(f"   место {slot} вид {kind}: ступень {ступень}->{state}"
                          f" счётчик {сколько}->{timer}")
        было = (tick, now)
        time.sleep(every)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="snapshot")
    parser.add_argument("--list", action="store_true", help="показать процессы")
    parser.add_argument("--name", default="konung2")
    parser.add_argument("--out", help="снять слепок в файл")
    parser.add_argument("--diff", nargs=2, metavar=("БЫЛО", "СТАЛО"))
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--watch", type=int, metavar="СКОЛЬКО",
                        help="следить за стройкой: столько замеров")
    parser.add_argument("--every", type=float, default=1.0, help="секунд между замерами")
    parser.add_argument("--map", type=int, default=33, help="номер карты поселения")
    args = parser.parse_args(argv)

    if args.diff:
        for line in diff(load(args.diff[0]), load(args.diff[1]), args.limit):
            print(line)
        return 0

    if args.list:
        for pid, exe in processes():
            if args.name.lower() in exe.lower():
                print(f"{pid:>7}  {exe}")
        return 0

    pid = find(args.name)
    if pid is None:
        print(f"процесс с «{args.name}» в имени не найден — игра не запущена")
        return 1
    if args.watch:
        watch(pid, args.map, args.watch, args.every)
        return 0

    shot = take(pid)
    пусто = [name for name, blob in shot["areas"].items() if not blob]
    if пусто:
        print("не прочитались области:", ", ".join(пусто))
    print("глобалы:", shot["globals"])
    if args.out:
        save(shot, args.out)
        print(f"слепок: {args.out} "
              f"({sum(len(b) for b in shot['areas'].values())} байт)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
