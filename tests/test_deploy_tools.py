# -*- coding: utf-8 -*-
"""Деплой и готовность сервера — сторожа против возврата виснущего ssh.

История 24.08: `ssh.exe` из python-subprocess без явного stdin уходит в
busy-loop (пятнадцать часов CPU у зомби), его сессии душат sshd, и прод
отвечает по девять секунд. Лекарство — `-n` + DEVNULL + жёсткий таймаут
+ keepalive — живёт в tools/deploy_ssh.py; здесь закреплено, что оба
деплоя ходят ТОЛЬКО через него и что после заливки прод сверяется.
Сеть эти тесты не трогают.
"""
from __future__ import annotations

import pathlib
import re
import unittest

КОРЕНЬ = pathlib.Path(__file__).resolve().parents[1]


def инструмент(имя: str) -> str:
    return (КОРЕНЬ / 'tools' / имя).read_text(encoding='utf-8')


class SshLayerTest(unittest.TestCase):
    """Слой tools/deploy_ssh.py — все четыре ремня на месте."""

    def test_reading_calls_never_hang(self) -> None:
        код = инструмент('deploy_ssh.py')
        # -n и DEVNULL чинят РАЗНЫЕ сборки Windows-OpenSSH — нужны оба
        self.assertIn('"ssh", "-n", *ОПЦИИ', код)
        self.assertIn('stdin=subprocess.DEVNULL', код)
        self.assertIn('"ConnectTimeout=15"', код)
        self.assertIn('"ServerAliveInterval=10"', код)
        # повисший вызов убивается и повторяется, а не ждётся вечно
        self.assertIn('subprocess.TimeoutExpired', код)
        self.assertIn('timeout=timeout', код)

    def test_pipe_call_kills_on_timeout(self) -> None:
        код = инструмент('deploy_ssh.py')
        self.assertIn('процесс.kill()', код)
        # передающий вызов живёт с живым stdin — без -n
        self.assertIn('["ssh", *ОПЦИИ, ХОСТ, команда]', код)


class DeployToolsUseLayerTest(unittest.TestCase):
    """Оба деплоя ходят через слой; голых ssh-вызовов не осталось."""

    def test_no_bare_ssh_subprocess(self) -> None:
        for имя in ('deploy_web.py', 'deploy_pack.py'):
            код = инструмент(имя)
            self.assertIn('from deploy_ssh import', код, имя)
            self.assertNotRegex(
                код, re.compile(r'subprocess\.run\(\s*\[\s*"ssh"'),
                f'{имя}: голый subprocess.run(["ssh"...]) вернулся')
            self.assertNotRegex(
                код, re.compile(r'Popen\(\s*\[\s*"ssh"'),
                f'{имя}: голый Popen(["ssh"...]) вернулся')

    def test_send_verifies_prod_after_upload(self) -> None:
        web = инструмент('deploy_web.py')
        # каждый отправленный файл перечитывается с боевого и сверяется
        self.assertIn('def сверить_прод(', web)
        self.assertIn('deploycheck=', web)
        self.assertIn('ПРОД РАЗОШЁЛСЯ', web)
        pack = инструмент('deploy_pack.py')
        # пак сверяется серверным манифестом мимо CDN
        self.assertIn('серверный манифест не равен локальному', pack)

    def test_upload_timeouts_are_finite(self) -> None:
        self.assertIn('timeout=600', инструмент('deploy_web.py'))
        self.assertIn('timeout=3600', инструмент('deploy_pack.py'))


class ServerHealthTest(unittest.TestCase):
    """Инструмент готовности: все четыре яруса и честный эталон канала."""

    def test_all_tiers_present(self) -> None:
        код = инструмент('server_health.py')
        for кусок in ('def местные_зомби', 'def прод_отвечает',
                      'def сервер_изнутри', 'def свежесть',
                      'def канал_эталоном'):
            self.assertIn(кусок, код)

    def test_channel_baseline_downgrades_prod_fail(self) -> None:
        код = инструмент('server_health.py')
        # при задушенном канале медленный прод — WARN, а не FAIL сервера
        self.assertIn('speed.cloudflare.com', код)
        self.assertIn('"warn" if канал_плох else "fail"', код)

    def test_server_side_greps_are_anchored(self) -> None:
        # daemon.start ловился на «tar» внутри слова — якоря обязательны
        self.assertIn('/^(find|sha256sum|tar|gzip)$/',
                      инструмент('server_health.py'))

    def test_exit_code_follows_fail(self) -> None:
        код = инструмент('server_health.py')
        self.assertIn('return 1 if итог["fail"] else 0', код)


if __name__ == '__main__':
    unittest.main()
