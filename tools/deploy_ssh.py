# -*- coding: utf-8 -*-
"""Общий ssh-слой деплоя: не виснет, не молчит, повторяет.

Родился из ночи 24.08: `ssh.exe` Windows, запущенный из python-subprocess
БЕЗ перенаправленного stdin, уходит в busy-loop — вчерашний зомби съел
пятнадцать часов процессора, его висячие сессии задушили sshd, и статика
боевого отвечала по девять секунд. Та же команда из Git Bash проходит
мгновенно: разница ровно в stdin.

Отсюда три правила каждого вызова:

* stdin ЯВНЫЙ ВСЕГДА: `-n` плюс `DEVNULL` у читающих команд, живой пайп
  у передающих;
* таймаут ЖЁСТКИЙ: подвисший ssh убивается процессом, а не ждётся;
* keepalive: `ServerAliveInterval/CountMax` рвут мёртвый канал сами.
"""
from __future__ import annotations

import subprocess

ХОСТ = "vps2"

#: Опции каждого вызова. BatchMode запрещает интерактив (пароль = отказ),
#: ConnectTimeout не даёт висеть на рукопожатии, ServerAlive рвёт канал,
#: который перестал отвечать (10 с * 3 проверки = полминуты тишины).
ОПЦИИ = ["-o", "BatchMode=yes",
         "-o", "ConnectTimeout=15",
         "-o", "ServerAliveInterval=10",
         "-o", "ServerAliveCountMax=3"]


def ssh_read(команда: str, *, timeout: int = 90,
             попытки: int = 2) -> subprocess.CompletedProcess:
    """Прочитать вывод команды на сервере; повисший вызов убить и повторить.

    `-n` перенаправляет stdin из /dev/null — без него Windows-ssh из
    subprocess крутит пустой цикл; DEVNULL — вторая половина того же
    ремня. Обе стороны обязательны: они чинят РАЗНЫЕ сборки OpenSSH.
    """
    последняя = None
    for попытка in range(1, попытки + 1):
        try:
            return subprocess.run(
                ["ssh", "-n", *ОПЦИИ, ХОСТ, команда],
                capture_output=True, text=True, encoding="utf-8",
                stdin=subprocess.DEVNULL, timeout=timeout)
        except subprocess.TimeoutExpired as беда:
            последняя = беда
            print(f"ssh не ответил за {timeout} с (попытка {попытка} из "
                  f"{попытки}) — процесс убит")
    raise SystemExit(f"ssh так и не ответил: {последняя}")


def ssh_pipe(команда: str, поток_stdin, *, timeout: int = 900) -> int:
    """Прогнать поток (tar) в команду на сервере. stdin живой — это НЕ
    читающий вызов, ему `-n` противопоказан; от зависания защищают
    keepalive и жёсткий таймаут."""
    процесс = subprocess.Popen(["ssh", *ОПЦИИ, ХОСТ, команда],
                               stdin=поток_stdin)
    try:
        return процесс.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        процесс.kill()
        print(f"передача не уложилась в {timeout} с — ssh убит")
        return 1
