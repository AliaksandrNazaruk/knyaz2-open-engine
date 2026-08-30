# -*- coding: utf-8 -*-
"""Родословная боевых формул: константы и таблицы против exe и Slavik.

Slavik — открытая реализация «Князя 1» (project/community/slavik);
сверка с ней — docs/COMBAT_SPEC_VS_SLAVIK.md. Здесь сторожатся ФАКТЫ,
на которых сверка стоит: числа читаются из konung2.exe, а не приняты
на слово, и таблица парирования по направлениям совпадает с той, что
Slavik держит литералом Can[8][8].
"""
from __future__ import annotations

import pathlib
import re
import struct
import unittest

КОРЕНЬ = pathlib.Path(__file__).resolve().parents[1]

#: Таблица «можно ли парировать» по (направление жертвы, атакующего) —
#: 0x459F94 нашего exe и литерал Can[8][8] Slavik (game_play.cpp).
ПАРИРОВАНИЕ = [
    [0, 0, 0, 1, 1, 1, 0, 0],
    [0, 0, 0, 0, 1, 1, 1, 0],
    [0, 0, 0, 0, 0, 1, 1, 1],
    [1, 0, 0, 0, 0, 0, 1, 1],
    [1, 1, 0, 0, 0, 0, 0, 1],
    [1, 1, 1, 0, 0, 0, 0, 0],
    [0, 1, 1, 1, 0, 0, 0, 0],
    [0, 0, 1, 1, 1, 0, 0, 0],
]

#: Константы формул (double), адрес -> значение. Смысл — в COMBAT_SPEC.md;
#: 0.00025 (износ оружия) до сверки со Slavik значился безымянным.
КОНСТАНТЫ = {
    0x450138: 0.1,      # порог парирования стрелы: Ловкость * 0.1
    0x450140: 0.7,      # урон выстрела: доля, которую режет броня
    0x450148: 0.3,      # урон выстрела: доля мимо брони
    0x450150: 16.0,     # шкала здоровья
    0x450158: 0.001,    # износ брони от выстрела
    0x450160: 0.5,      # порог парирования ближнего: Ловкость * 0.5
    0x450168: 0.7,      # урон ближнего: доля, которую режет броня
    0x450170: 0.3,      # урон ближнего: доля мимо брони
    0x450178: 16.0,     # шкала здоровья
    0x450180: 0.001,    # износ брони от удара
    0x450188: 0.00025,  # износ оружия атакующего
}


class ExeFactsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from konung2.paths import game_file
        try:
            cls.exe = pathlib.Path(game_file('konung2.exe')).read_bytes()
        except OSError:
            raise unittest.SkipTest('konung2.exe недоступен')

    def test_parry_table_matches(self) -> None:
        from konung2.exetables import va_to_foff
        at = va_to_foff(0x459F94)
        got = [list(self.exe[at + row * 8:at + row * 8 + 8])
               for row in range(8)]
        self.assertEqual(got, ПАРИРОВАНИЕ)

    def test_formula_constants_match(self) -> None:
        from konung2.exetables import va_to_foff
        for va, wanted in КОНСТАНТЫ.items():
            value = struct.unpack_from('<d', self.exe, va_to_foff(va))[0]
            # 0.7 в exe записан не тем же double, что литерал Python
            # (0.7000000000000001): сверяем до девятого знака
            self.assertAlmostEqual(value, wanted, places=9, msg=hex(va))


class SlavikMirrorTest(unittest.TestCase):
    """Литералы Slavik — те же числа. Пропускается без клона."""

    @classmethod
    def setUpClass(cls) -> None:
        путь = КОРЕНЬ / 'project' / 'community' / 'slavik' / 'game_play.cpp'
        if not путь.is_file():
            raise unittest.SkipTest('Slavik не клонирован')
        cls.text = путь.read_text(encoding='utf-8', errors='replace')

    def test_can_table_is_ours(self) -> None:
        m = re.search(r'Can\[8\]\[8\]\s*=\s*\{(.*?)\};', self.text, re.S)
        self.assertIsNotNone(m)
        numbers = [int(x) for x in re.findall(r'[01]', m.group(1))]
        self.assertEqual(numbers, [x for row in ПАРИРОВАНИЕ for x in row])

    def test_damage_formula_literals(self) -> None:
        for literal in ('* 0.7', '* 0.3', '* 16.0', '* 0.001', '* 0.00025',
                        '/ (float)chr1->CurrentVinoslivost'):
            self.assertIn(literal, self.text, literal)

    def test_trade_price_literals(self) -> None:
        """Формула цен К1 — те же числа, что наши правила пака.

        Наши значения сторожит tests/test_items_contract.py (0.002, 0.5,
        1.5, 2/3 из exe); здесь — что родословная не выдумана.
        """
        путь = КОРЕНЬ / 'project' / 'community' / 'slavik' / 'game_trade.cpp'
        text = путь.read_text(encoding='utf-8', errors='replace')
        for literal in ('* 0.002', '* 0.5', '*= 1.5', '*= 0.6666667'):
            self.assertIn(literal, text, literal)


if __name__ == '__main__':
    unittest.main()
