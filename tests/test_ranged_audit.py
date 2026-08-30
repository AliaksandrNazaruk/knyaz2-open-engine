# -*- coding: utf-8 -*-
"""Стрелковый контур — сторожа аудита 24.08 (COMBAT_SPEC §10а).

Три источника истины: константы читаются ПРЯМО из konung2.exe, строки
клиента — из рабочего дерева, вердикты — из спеки. Если кто-то «улучшит»
выбор цели стрелка обратно на ближайшего или снова начнёт ронять стрелу
в воду — здесь загорится.
"""
from __future__ import annotations

import pathlib
import struct
import sys
import unittest

КОРЕНЬ = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(КОРЕНЬ))

EXE = pathlib.Path(r'C:\Program Files (x86)\Князь - Коллекционное издание'
                   r'\02. Князь 2 - Кровь Титанов\konung2.exe')


def клиент(имя: str) -> str:
    return (КОРЕНЬ / 'knyaz2' / 'web' / 'static' / имя).read_text(
        encoding='utf-8')


class ExeConstantsTest(unittest.TestCase):
    """Числа, на которых стоит стрельба, — прямо из exe."""

    @classmethod
    def setUpClass(cls) -> None:
        if not EXE.is_file():
            raise unittest.SkipTest('konung2.exe не найден')
        cls.data = EXE.read_bytes()
        from konung2.exetables import va_to_foff
        cls.off = staticmethod(va_to_foff)

    def тянуть_double(self, va: int) -> float:
        from konung2.exetables import va_to_foff
        return struct.unpack_from('<d', self.data, va_to_foff(va))[0]

    def test_range_penalty_is_03(self) -> None:
        # штраф точности за дальность: навык − дист·K/дальность (0x41ADD8)
        self.assertEqual(self.тянуть_double(0x450094), 0.3)

    def test_projectile_step_constant(self) -> None:
        # константа шага снаряда — 0.25, а не «4 пикселя» (открытый §10.4)
        self.assertEqual(self.тянуть_double(0x450128), 0.25)

    def test_weapon_range_byte_table(self) -> None:
        """Дальность в клетках — байт 0x45DB00 + класс*0x20; он же — жизнь
        снаряда в тактах (0x41BB10 кладёт его в запись)."""
        from konung2.exetables import va_to_foff
        ожидание = {115: 10, 116: 15, 117: 20, 118: 20, 119: 30,
                    149: 12, 150: 18, 151: 25, 152: 15, 153: 40}
        for класс, дальность in ожидание.items():
            байт = self.data[va_to_foff(0x45DB00 + класс * 0x20)]
            self.assertEqual(байт, дальность, f'класс {класс}')


class ShooterTargetPickTest(unittest.TestCase):
    """Выбор цели стрелка — 0x411F28, а не «ближайший враг»."""

    def test_pick_walks_enemy_band_in_record_order(self) -> None:
        units = клиент('units.js')
        self.assertIn('function rangedTargetPick(unit)', units)
        # перебор вражьего отряда в порядке записей
        self.assertIn('membersOf(band.enemySide, units)', units)
        # гейты движка: тварь, гнёзда, тумблер «Выбор оружия»
        self.assertIn('if (!unit.rangedMode && unit.weaponLock) return null;',
                      units)
        # вход в стрельбу взводит режим (0x416AC8)
        self.assertIn('unit.rangedMode = true;', units)
        # дальность и упор проверяются до трассы
        self.assertIn('if (dist < min || dist > reach) continue;', units)

    def test_pick_sits_between_neighbour_and_far_choice(self) -> None:
        warband = клиент('warband.js')
        порядок = warband.find('const shot = rangedPick?.(unit);')
        сосед = warband.find('adjacentEnemy(unit, units, neighbour)')
        дальний = warband.find('return pickEnemy(unit, units);')
        self.assertTrue(0 < сосед < порядок < дальний,
                        'стрелковый выбор обязан стоять между соседом '
                        'и дальним выбором (0x410A08 case 1)')


class ArrowFlightTest(unittest.TestCase):
    """Полёт стрелы: гасит только стена, бьёт только свою цель."""

    def test_wall_bit_only(self) -> None:
        код = клиент('projectiles.js')
        self.assertIn('world.solidAt?.(cell.row, cell.col)', код)
        self.assertNotIn('heroFree(', код,
                         'вода и деревья стрелу ПРОПУСКАЮТ (бит 0x4000)')

    def test_projectile_hits_only_its_target(self) -> None:
        код = клиент('projectiles.js')
        self.assertIn('const target = shot.target;', код)

    def test_speed_comment_is_honest(self) -> None:
        код = клиент('projectiles.js')
        self.assertIn('0.25', код)
        self.assertIn('калибровка', код)


class SpecAuditSectionTest(unittest.TestCase):
    def test_spec_carries_audit_table(self) -> None:
        спека = (КОРЕНЬ / 'docs' / 'COMBAT_SPEC.md').read_text(
            encoding='utf-8')
        self.assertIn('## 10а. Аудит стрелкового контура — 24.08.2026',
                      спека)
        self.assertIn('Геометрия шага снаряда', спека)
        self.assertIn('0x411F28', спека)


if __name__ == '__main__':
    unittest.main()
