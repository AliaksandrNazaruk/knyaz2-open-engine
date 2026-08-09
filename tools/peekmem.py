# -*- coding: utf-8 -*-
"""
Чтение памяти живой konung2.exe: подтверждение рантайм-значений.

    python tools\\peekmem.py 0x8496A0:u32 0x849538:u32 ...
"""
from __future__ import annotations

import ctypes
import struct
import subprocess
import sys

PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
kernel32 = ctypes.windll.kernel32


def find_pid(name='konung2.exe'):
    out = subprocess.run(['tasklist', '/FI', f'IMAGENAME eq {name}', '/FO', 'CSV'],
                         capture_output=True, text=True).stdout
    for line in out.splitlines()[1:]:
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) >= 2 and parts[0].lower() == name:
            return int(parts[1])
    return None


def read(handle, address, size):
    buffer = ctypes.create_string_buffer(size)
    got = ctypes.c_size_t()
    ok = kernel32.ReadProcessMemory(handle, ctypes.c_void_p(address),
                                    buffer, size, ctypes.byref(got))
    return buffer.raw[:got.value] if ok else None


def main():
    pid = find_pid()
    if not pid:
        sys.exit('konung2.exe не запущен')
    handle = kernel32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION,
                                  False, pid)
    if not handle:
        sys.exit(f'OpenProcess не удался (pid {pid})')
    print(f'pid {pid}')
    for spec in sys.argv[1:]:
        text, kind = spec.split(':') if ':' in spec else (spec, 'u32')
        address = int(text, 0)
        if kind.startswith('raw'):
            size = int(kind[3:] or 16)
            data = read(handle, address, size)
            print(f'  {text}: {data.hex(" ") if data else "нет доступа"}')
        else:
            data = read(handle, address, 4)
            if data is None:
                print(f'  {text}: нет доступа')
            else:
                print(f'  {text}: {struct.unpack("<I", data)[0]}'
                      f' (i32 {struct.unpack("<i", data)[0]})')
    kernel32.CloseHandle(handle)


if __name__ == '__main__':
    main()
