# -*- coding: utf-8 -*-
"""
Установить собранный мод в игру:  python tools\\install.py [--restore]

Перед первой заменой каждый оригинальный файл копируется в backup/.
Папка игры лежит в Program Files, поэтому запускать надо от имени
администратора, иначе будет «Отказано в доступе».

    --restore   вернуть все файлы из backup/ (откат мода)
"""
import os, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from konung2.paths import GAME_DIR, BUILD_DIR, BACKUP_DIR

os.makedirs(BACKUP_DIR, exist_ok=True)


def restore():
    n = 0
    for name in sorted(os.listdir(BACKUP_DIR)):
        src, dst = os.path.join(BACKUP_DIR, name), os.path.join(GAME_DIR, name)
        shutil.copy2(src, dst)
        print(f"  восстановлен {name}")
        n += 1
    print(f"откат завершён: {n} файлов")


def install():
    if not os.path.isdir(BUILD_DIR):
        sys.exit("build/ пуст — сначала запустите tools\\build_all.py")
    files = sorted(os.listdir(BUILD_DIR))
    if not files:
        sys.exit("build/ пуст — сначала запустите tools\\build_all.py")
    installed = skipped = 0
    for name in files:
        src = os.path.join(BUILD_DIR, name)
        dst = os.path.join(GAME_DIR, name)
        if os.path.exists(dst):
            with open(src, 'rb') as a, open(dst, 'rb') as b:
                if a.read() == b.read():
                    skipped += 1
                    continue
            bak = os.path.join(BACKUP_DIR, name)
            if not os.path.exists(bak):
                shutil.copy2(dst, bak)
                print(f"  бэкап   {name} -> backup/")
        try:
            shutil.copy2(src, dst)
        except PermissionError:
            sys.exit(f"\nОтказано в доступе к {dst}\n"
                     f"Запустите терминал от имени администратора и повторите.")
        print(f"  установлен {name}")
        installed += 1
    print(f"\nустановлено {installed}, без изменений {skipped}")
    if installed:
        print("Изменения мира (GAME.x) видны только при НАЧАЛЕ НОВОЙ ИГРЫ.")


if __name__ == '__main__':
    (restore if '--restore' in sys.argv else install)()
