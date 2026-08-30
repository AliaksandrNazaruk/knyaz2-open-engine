# -*- coding: utf-8 -*-
"""Дозаливка клиента на сервер: шлём только изменившиеся файлы.

Пару к `deploy_pack.py`, но для `knyaz2/web/static`. Описи у клиента нет,
поэтому sha256 серверных файлов считаем на самом сервере одной командой —
это дешевле, чем качать их обратно.

    python tools/deploy_web.py            # посмотреть, что поедет
    python tools/deploy_web.py --send     # отправить

РЯДОМ С КАЖДЫМ ФАЙЛОМ ЛЕЖИТ `.gz`, и его надо пережимать вместе с самим
файлом: nginx отдаёт браузеру заранее сжатую копию (gzip_static). Забудешь —
и на сервере будет свежий `app.js` рядом со старым `app.js.gz`, а игрок
получит старый. Ровно на этих граблях уже стояли с паком.

Каталог `menu/` не трогаем: это нарезка из MENU.RES, она в репозиторий не
идёт и воспроизводится `tools/menu_extract.py`.
"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from deploy_ssh import ssh_pipe, ssh_read   # noqa: E402

КОРЕНЬ_СЕРВЕРА = "/var/www/konung2/web"
ПРОД = "https://konung-open-engine.techvisioncloud.pl"
КЛИЕНТ = Path("knyaz2/web/static")

#: Что не наше и не должно уехать.
ПРОПУСК = {"menu"}


def свои() -> dict[str, str]:
    """Файл -> sha256. Только верхний уровень: подкаталог у клиента один."""
    out = {}
    for путь in sorted(КЛИЕНТ.iterdir()):
        if путь.is_dir() or путь.name in ПРОПУСК:
            continue
        out[путь.name] = hashlib.sha256(путь.read_bytes()).hexdigest()
    return out


def серверные() -> dict[str, str]:
    """Файл -> sha256 на сервере.

    ОТВЕТ СВЕРЯЕТСЯ СО СЧЁТОМ. Обрезанный ответ ssh (а он случается, когда
    канал занят) выглядит как «этих файлов на сервере нет», и средство
    молча объявляет их новыми. Поэтому сервер сам считает свои файлы, и
    расхождение — это отказ, а не тихая правда.
    """
    команда = (f"cd {КОРЕНЬ_СЕРВЕРА} && "
               "find . -maxdepth 1 -type f ! -name '*.gz' | wc -l && "
               "find . -maxdepth 1 -type f ! -name '*.gz' -exec sha256sum {} +")
    готово = ssh_read(команда, timeout=90)
    if готово.returncode != 0:
        raise SystemExit(f"сервер не ответил: {готово.stderr.strip()}")
    строки = готово.stdout.splitlines()
    if not строки:
        raise SystemExit("сервер вернул пустой список — заливать вслепую нельзя")
    сколько, строки = int(строки[0]), строки[1:]
    out = {}
    for строка in строки:
        части = строка.split(None, 1)
        if len(части) == 2:
            out[части[1].strip().removeprefix("./")] = части[0]
    if len(out) != сколько:
        raise SystemExit(f"ответ обрезан: файлов {сколько}, "
                         f"разобрано {len(out)} — повторите")
    return out


def main() -> int:
    разбор = argparse.ArgumentParser(description=__doc__)
    разбор.add_argument("--send", action="store_true", help="отправить")
    аргументы = разбор.parse_args()

    наши, там = свои(), серверные()
    новые = sorted(имя for имя, sha in наши.items() if там.get(имя) != sha)
    лишние = sorted(set(там) - set(наши))
    вес = sum((КЛИЕНТ / имя).stat().st_size for имя in новые)
    print(f"файлов у клиента: {len(наши)}, на сервере: {len(там)}")
    print(f"изменилось:       {len(новые)}  ({вес / 1024:.0f} КБ до сжатия)")
    for имя in новые:
        print(f"    {'новый' if имя not in там else 'правка'}  {имя}")
    print(f"лишних на сервере: {len(лишние)}"
          + (f" — {', '.join(лишние)}" if лишние else ""))
    if not аргументы.send:
        print("\n— это просмотр; чтобы отправить, добавьте --send")
        return 0
    if not новые and not лишние:
        print("нечего слать")
        return 0

    список = КЛИЕНТ / ".deploy-list"
    список.write_text("\n".join(новые), encoding="utf-8")
    удалить = " ".join(f"'{КОРЕНЬ_СЕРВЕРА}/{имя}' '{КОРЕНЬ_СЕРВЕРА}/{имя}.gz'"
                       for имя in лишние)
    пережать = " ".join(f"'{КОРЕНЬ_СЕРВЕРА}/{имя}'" for имя in новые)
    команда = (f"tar -xzf - -C {КОРЕНЬ_СЕРВЕРА}"
               + (f" && rm -f {удалить}" if лишние else "")
               + (f" && gzip -9 -k -f {пережать}" if пережать else "")
               + " && echo ЗАЛИТО")
    поток = subprocess.Popen(["tar", "-czf", "-", "-T", список.name],
                             cwd=str(КЛИЕНТ), stdout=subprocess.PIPE)
    код = ssh_pipe(команда, поток.stdout, timeout=600)
    поток.wait()
    список.unlink(missing_ok=True)
    if код != 0:
        return код
    return 0 if сверить_прод(новые, наши) else 1


def сверить_прод(имена: list[str], наши: dict[str, str]) -> bool:
    """Замкнуть петлю: каждый отправленный файл перечитывается С БОЕВОГО
    (curl с обходом кэша — Cloudflare режет urllib по User-Agent) и его
    sha сверяется с локальным. «ЗАЛИТО» без этой сверки уже врало."""
    метка = int(time.time())
    беды = []
    for имя in имена:
        готово = subprocess.run(
            ["curl", "-s", "-m", "30", f"{ПРОД}/{имя}?deploycheck={метка}"],
            capture_output=True, timeout=60)
        удалённый = hashlib.sha256(готово.stdout).hexdigest()
        if удалённый != наши.get(имя):
            беды.append(имя)
    if беды:
        print(f"ПРОД РАЗОШЁЛСЯ после заливки: {', '.join(беды)}")
        return False
    print(f"прод сверен: {len(имена)} файлов совпали с локальными")
    return True


if __name__ == "__main__":
    sys.exit(main())
