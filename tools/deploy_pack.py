# -*- coding: utf-8 -*-
"""Дозаливка пака на сервер: шлём только изменившиеся файлы.

rsync под рукой нет, но он здесь и не нужен: в `manifest.json` у каждого
файла лежит sha256, и пак заведомо описан целиком. Сравниваем свой манифест
с серверным и отправляем tar-ом ровно те пути, что разошлись, плюс сам
манифест. Удалённые файлы вычищаем отдельным списком.

    python tools/deploy_pack.py            # посмотреть, что поедет
    python tools/deploy_pack.py --send     # отправить

Первая заливка на пустой сервер уедет целиком — это нормально.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ХОСТ = "vps2"
КОРЕНЬ_СЕРВЕРА = "/var/www/konung2/content"
ПАК = Path("content_build")


def карта_файлов(манифест: dict) -> dict[str, str]:
    return {запись["path"]: запись.get("sha256", "")
            for запись in манифест.get("files", [])}


def серверный_манифест() -> dict:
    готово = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", ХОСТ, f"cat {КОРЕНЬ_СЕРВЕРА}/manifest.json"],
        capture_output=True, text=True, encoding="utf-8")
    if готово.returncode != 0 or not готово.stdout.strip():
        return {}
    try:
        return json.loads(готово.stdout)
    except json.JSONDecodeError:
        return {}


def main() -> int:
    разбор = argparse.ArgumentParser()
    разбор.add_argument("--send", action="store_true", help="отправить, а не только показать")
    аргументы = разбор.parse_args()

    свой = json.loads((ПАК / "manifest.json").read_text(encoding="utf-8"))
    наши, чужие = карта_файлов(свой), карта_файлов(серверный_манифест())

    новые = [путь for путь, хеш in наши.items() if чужие.get(путь) != хеш]
    лишние = [путь for путь in чужие if путь not in наши]
    вес = sum((ПАК / путь).stat().st_size for путь in новые if (ПАК / путь).exists())

    print(f"файлов в паке: {len(наши)}")
    print(f"изменилось:    {len(новые)}  ({вес / 1024 / 1024:.1f} МБ до сжатия)")
    print(f"лишних на сервере: {len(лишние)}")
    if not аргументы.send:
        print("\n— это просмотр; чтобы отправить, добавьте --send")
        return 0
    if not новые and not лишние:
        print("нечего слать")
        return 0

    список = ПАК / ".deploy-list"
    список.write_text("\n".join([*новые, "manifest.json"]), encoding="utf-8")
    удалить = " ".join(f"'{КОРЕНЬ_СЕРВЕРА}/{путь}'" for путь in лишние)
    # ПЕРЕЖИМАЕМ РОВНО ТО, ЧТО ЗАЛИЛИ. Раньше здесь стоял отбор по «новее
    # manifest.json», и он промахивался: nginx отдаёт браузеру заранее сжатый
    # `.gz` (gzip_static), а тот оставался прежним — карта приезжала старая,
    # хотя рядом лежал свежий json. Через curl всё выглядело правильно, потому
    # что он gzip не просит.
    json_новые = [путь for путь in новые if путь.endswith(".json")]
    пережать = " ".join(f"'{КОРЕНЬ_СЕРВЕРА}/{путь}'"
                        for путь in [*json_новые, "manifest.json"])
    команда = (f"tar -xzf - -C {КОРЕНЬ_СЕРВЕРА}"
               + (f" && rm -f {удалить}" if лишние else "")
               + (f" && gzip -9 -k -f {пережать}" if пережать else "")
               + " && echo ЗАЛИТО")
    # Рабочий каталог УЖЕ пак, поэтому `-C` здесь не нужен: с ним tar искал
    # бы content_build внутри content_build и падал «Error is not recoverable».
    поток = subprocess.Popen(
        ["tar", "-czf", "-", "-T", str(список.name)],
        cwd=str(ПАК), stdout=subprocess.PIPE)
    итог = subprocess.run(["ssh", "-o", "BatchMode=yes", ХОСТ, команда],
                          stdin=поток.stdout)
    поток.wait()
    список.unlink(missing_ok=True)
    return итог.returncode


if __name__ == "__main__":
    sys.exit(main())
