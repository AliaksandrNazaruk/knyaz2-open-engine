#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
queststool.py — распаковка/запаковка QUESTS.RES (Князь 2)
Использование:
    python queststool.py unpack             # -> ..\quests_text.txt (UTF-8)
    python queststool.py pack               # quests_text.txt -> QUESTS.RES.new
Формат quests_text.txt: каждая строка = "<номер><TAB><текст>".
Пустые строки файла-ресурса пропускаются при распаковке, при запаковке
восстанавливаются автоматически (важно сохранять номера!).
При запаковке: суммарный размер текстового блоба не должен превысить 307200.
"""
import os, sys

GAME_DIR = r"C:\Program Files (x86)\Князь - Коллекционное издание\02. Князь 2 - Кровь Титанов"
WORK = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
BLOB_SIZE = 0x4B000     # 307200
TAIL_SIZE = 0x4B0       # 1200 (300 dword стартовых состояний квестов)


def unpack():
    data = open(os.path.join(GAME_DIR, 'QUESTS.RES'), 'rb').read()
    assert len(data) == BLOB_SIZE + TAIL_SIZE, f"неожиданный размер {len(data)}"
    blob, tail = data[:BLOB_SIZE], data[BLOB_SIZE:]
    parts = blob.split(b'\0')
    out = os.path.join(WORK, 'quests_text.txt')
    with open(out, 'w', encoding='utf-8') as f:
        for i, p in enumerate(parts):
            if p:
                f.write(f"{i}\t{p.decode('cp866', errors='replace')}\n")
    open(os.path.join(WORK, 'quests_tail.bin'), 'wb').write(tail)
    print(f"строк всего (с пустыми): {len(parts)}, непустых: {sum(1 for p in parts if p)}")
    print(f"-> {out}\n-> quests_tail.bin (не редактировать без понимания)")


def pack():
    src = os.path.join(WORK, 'quests_text.txt')
    tailp = os.path.join(WORK, 'quests_tail.bin')
    orig = open(os.path.join(GAME_DIR, 'QUESTS.RES'), 'rb').read()
    parts = orig[:BLOB_SIZE].split(b'\0')
    for line in open(src, encoding='utf-8'):
        line = line.rstrip('\n')
        if not line.strip():
            continue
        num, _, text = line.partition('\t')
        parts[int(num)] = text.encode('cp866', errors='replace')
    blob = b'\0'.join(parts)
    if len(blob) > BLOB_SIZE:
        print(f"ОШИБКА: блоб {len(blob)} > {BLOB_SIZE}; сократите тексты на {len(blob)-BLOB_SIZE} байт")
        sys.exit(1)
    blob = blob.ljust(BLOB_SIZE, b'\0')
    tail = open(tailp, 'rb').read() if os.path.exists(tailp) else orig[BLOB_SIZE:]
    out = os.path.join(WORK, 'QUESTS.RES.new')
    open(out, 'wb').write(blob + tail)
    print(f"-> {out} ({len(blob)+len(tail)} байт). Скопируйте в папку игры (нужны права администратора), сделав бэкап!")


if __name__ == '__main__':
    (unpack if (len(sys.argv) < 2 or sys.argv[1] == 'unpack') else pack)()
