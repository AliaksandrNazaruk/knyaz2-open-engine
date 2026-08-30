# -*- coding: utf-8 -*-
"""Готовность боевого сервера — один прогон, все ярусы.

    python tools/server_health.py            # полный отчёт
    python tools/server_health.py --fast     # без ssh (только http и локалка)

Четыре яруса, каждый — своя беда из пережитых:

1. ЛОКАЛЬНЫЕ ЗОМБИ. Виснущий `ssh.exe` из python-subprocess (24.08 съел
   пятнадцать часов CPU) душит и канал, и sshd сервера — «прод не
   отвечает» начинается на этой машине. Ищем ssh/deploy-процессы старше
   десяти минут.
2. HTTP. Три лица прода: страница меню, модуль клиента, манифест пака.
   Меряем код и время с обходом кэша; медленнее двух секунд — тревога
   (обычные 0.3 с; девять секунд были симптомом зомби).
3. СЕРВЕР ПО SSH. Нагрузка, память, диск, systemd-статус nginx, висящие
   команды прежних деплоев (find/sha256sum/tar старше пяти минут), счёт
   sshd-сессий.
4. СВЕЖЕСТЬ. Отданный прод-файл сверяется sha с локальным деревом — .gz
   у nginx (gzip_static) уже приезжал старым при свежем соседе.

Выход: 0 — всё зелено; 1 — есть FAIL. WARN на код не влияет.
"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import time
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(КОРЕНЬ / "tools"))
from deploy_ssh import ssh_read   # noqa: E402

ПРОД = "https://konung-open-engine.techvisioncloud.pl"
КЛИЕНТ = КОРЕНЬ / "knyaz2" / "web" / "static"

#: Итоги копятся здесь; печать сразу, код возврата в конце.
итог = {"fail": 0, "warn": 0}


def строка(уровень: str, текст: str) -> None:
    метка = {"ok": "  OK  ", "warn": " WARN ", "fail": " FAIL "}[уровень]
    if уровень != "ok":
        итог[уровень] += 1
    print(f"[{метка}] {текст}")


# ── ярус 1: локальные зомби ──────────────────────────────────────────────

def местные_зомби() -> None:
    print("— локальные процессы")
    команда = ("Get-CimInstance Win32_Process -Filter \"Name='ssh.exe' or "
               "Name='python.exe'\" | ForEach-Object { "
               "'{0}|{1}|{2}' -f $_.ProcessId, $_.CreationDate, "
               "($_.CommandLine -replace '\\|', '/') }")
    try:
        готово = subprocess.run(
            ["powershell", "-NoProfile", "-Command", команда],
            capture_output=True, text=True, encoding="utf-8",
            stdin=subprocess.DEVNULL, timeout=30)
    except (subprocess.TimeoutExpired, OSError) as беда:
        строка("warn", f"опрос процессов не удался: {беда}")
        return
    сейчас = time.time()
    зомби = 0
    for line in готово.stdout.splitlines():
        части = line.split("|", 2)
        if len(части) != 3:
            continue
        pid, начат, cmd = части
        cmd = cmd or ""
        деплойный = ("deploy_web" in cmd or "deploy_pack" in cmd
                     or (" vps2 " in cmd or cmd.rstrip().endswith("vps2")))
        if not деплойный:
            continue
        # CIM-дата: 20260824053400.123456+120 — берём первые 14 цифр
        try:
            возраст = сейчас - time.mktime(time.strptime(начат[:14],
                                                         "%Y%m%d%H%M%S"))
        except ValueError:
            возраст = 0
        if возраст > 600:
            зомби += 1
            строка("fail", f"зомби-деплой pid {pid}, живёт "
                           f"{возраст / 60:.0f} мин: {cmd[:90]}")
    if not зомби:
        строка("ok", "зомби деплоя не найдено")


# ── ярус 2: http ─────────────────────────────────────────────────────────

def http_замер(путь: str) -> tuple[int, float, bytes]:
    метка = int(time.time() * 1000)
    готово = subprocess.run(
        ["curl", "-s", "-m", "20", "-w", "\n%{http_code} %{time_total}",
         f"{ПРОД}/{путь}?health={метка}"],
        capture_output=True, timeout=40)
    тело, _, хвост = готово.stdout.rpartition(b"\n")
    код_с, _, время_с = хвост.decode("ascii", "replace").partition(" ")
    try:
        return int(код_с), float(время_с), тело
    except ValueError:
        return 0, 99.0, b""


def канал_эталоном() -> float:
    """Скорость до НЕЗАВИСИМОГО быстрого хоста. Если и он ползёт — задушен
    канал этой машины, и медленный прод не вина сервера (24.08: спидтест
    Cloudflare выдал те же 30 КБ/с, что и прод)."""
    готово = subprocess.run(
        ["curl", "-s", "-o", "NUL" if sys.platform == "win32" else "/dev/null",
         "-m", "15", "-w", "%{speed_download}",
         "https://speed.cloudflare.com/__down?bytes=1000000"],
        capture_output=True, text=True, timeout=30)
    try:
        return float(готово.stdout.strip().replace(",", "."))
    except ValueError:
        return 0.0


def прод_отвечает() -> None:
    print("— http боевого")
    эталон = канал_эталоном()
    канал_плох = 0 < эталон < 200_000
    if канал_плох:
        строка("warn", f"канал этой машины задушен: эталон "
                       f"{эталон / 1024:.0f} КБ/с — медленный прод дальше "
                       f"считается КАНАЛОМ, не сервером")
    else:
        строка("ok", f"канал машины: {эталон / 1024:.0f} КБ/с")
    for путь in ("menu.html", "app.js", "content/manifest.json"):
        код, секунды, _ = http_замер(путь)
        if код != 200:
            строка("fail", f"{путь}: код {код}")
        elif секунды > 5:
            строка("warn" if канал_плох else "fail",
                   f"{путь}: {секунды:.2f} с — "
                   + ("канал" if канал_плох else "сервер задыхается"))
        elif секунды > 2:
            строка("warn", f"{путь}: {секунды:.2f} с — медленно")
        else:
            строка("ok", f"{путь}: 200 за {секунды:.2f} с")


# ── ярус 3: сервер по ssh ────────────────────────────────────────────────

def сервер_изнутри() -> None:
    print("— сервер по ssh")
    команда = ("uptime && nproc && free -m | awk 'NR==2{print $7}' && "
               "df -P /var/www | awk 'NR==2{print $4, $5}' && "
               "systemctl is-active nginx && "
               "pgrep -c sshd || true && "
               "ps -eo pid,etimes,comm | awk '$3 ~ "
               "/^(find|sha256sum|tar|gzip)$/ && $2>300 {print}' | wc -l")
    try:
        готово = ssh_read(команда, timeout=45, попытки=1)
    except SystemExit:
        строка("fail", "ssh к серверу не прошёл — ярус пропущен")
        return
    if готово.returncode != 0:
        строка("fail", f"ssh вернул {готово.returncode}: "
                       f"{готово.stderr.strip()[:120]}")
        return
    строки_ответа = готово.stdout.splitlines()
    if len(строки_ответа) < 6:
        строка("warn", f"ответ сервера короче ожидаемого: {строки_ответа}")
        return
    аптайм, ядра, память, диск, nginx, *хвост = строки_ответа
    сессии = хвост[0] if хвост else "?"
    висяки = хвост[1] if len(хвост) > 1 else "0"
    нагрузка = float(аптайм.rsplit("load average:", 1)[1].split(",")[0]
                     .replace(",", "."))
    предел = int(ядра) * 2
    уровень = "ok" if нагрузка < предел else "fail"
    строка(уровень, f"load {нагрузка:.2f} при {ядра} ядрах "
                    f"(порог {предел})")
    мб = int(память)
    строка("ok" if мб > 200 else "fail", f"память доступна: {мб} МБ")
    свободно_кб, занято_проц = диск.split()
    гб = int(свободно_кб) / 1024 / 1024
    процент = int(занято_проц.rstrip("%"))
    строка("ok" if гб > 1 and процент < 90 else "fail",
           f"диск /var/www: свободно {гб:.1f} ГБ, занято {процент}%")
    строка("ok" if nginx.strip() == "active" else "fail",
           f"nginx: {nginx.strip()}")
    строка("ok", f"sshd-процессов: {сессии.strip()}")
    сколько_висит = int(висяки.strip() or 0)
    строка("ok" if сколько_висит == 0 else "warn",
           f"висящих find/sha256sum/tar старше 5 мин: {сколько_висит}")


# ── ярус 4: свежесть выложенного ─────────────────────────────────────────

def свежесть() -> None:
    print("— свежесть прода")
    for имя in ("app.js", "units.js", "combat.js"):
        код, _, тело = http_замер(имя)
        if код != 200:
            строка("fail", f"{имя}: код {код}")
            continue
        локальный = hashlib.sha256((КЛИЕНТ / имя).read_bytes()).hexdigest()
        удалённый = hashlib.sha256(тело).hexdigest()
        if локальный == удалённый:
            строка("ok", f"{имя}: прод равен рабочему дереву")
        else:
            строка("warn", f"{имя}: прод отличается от рабочего дерева "
                           f"(есть невыложенные правки?)")


def main() -> int:
    разбор = argparse.ArgumentParser(description=__doc__)
    разбор.add_argument("--fast", action="store_true",
                        help="без ssh-яруса (только локалка и http)")
    аргументы = разбор.parse_args()
    местные_зомби()
    прод_отвечает()
    if not аргументы.fast:
        сервер_изнутри()
    свежесть()
    print(f"\nитого: FAIL {итог['fail']}, WARN {итог['warn']}")
    return 1 if итог["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
