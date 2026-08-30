# -*- coding: utf-8 -*-
"""Тренировка у казармы: числа, на которых держится «махать».

Жалоба тестера была «в казармах никто не машет». Приказ ставился и опыт
капал, а поз не ставил никто — бойцы стояли столбами. Разбор в
`knyaz2/web/static/units.js` (sparringTick), движок — VA 0x413894
(приказы 9 и 10), 0x416B50 (замах), 0x412C0C (выбор места).

Здесь сторожатся ДАННЫЕ, на которых стоит правило: если поедут они,
правило станет неверным молча.
"""
from __future__ import annotations

import glob
import json
import pathlib
import unittest

КОРЕНЬ = pathlib.Path(__file__).resolve().parents[1]

#: Такты на клетку по блоку анимации. Ею движок проверяет, не идёт ли
#: напарник: `таблица[поза] < 1` (VA 0x413894:93).
POSE_STEP_VA = 0x45FE90
#: Блоки: боевые 0…7, мирные 16…19 (konung2/heroes.py, STANCE_BLOCKS).
WALKING_BLOCKS = {1, 7, 17, 19}


def _pose_table() -> list[int]:
    from konung2.exetables import va_to_foff
    from konung2.profile import CANON
    data = CANON.exe_bytes()
    at = va_to_foff(POSE_STEP_VA)
    return [int.from_bytes(data[at + i:at + i + 1], "little", signed=True)
            for i in range(24)]


class PoseTableTest(unittest.TestCase):
    """Ходячие позы — ровно четыре, и это не догадка."""

    def test_only_walk_and_run_have_steps(self) -> None:
        """Положительное значение стоит ТОЛЬКО у ходьбы и бега.

        На этом держится проверка напарника: движок не трогает того, кто
        идёт. Если бы в таблице оказалось что-то ещё, «не идёт» значило
        бы другое, и спарринг цеплял бы не тех.
        """
        table = _pose_table()
        walking = {i for i, value in enumerate(table) if value > 0}
        self.assertEqual(walking, WALKING_BLOCKS, dict(enumerate(table)))
        # Обе стойки, и ходьба всегда медленнее бега.
        self.assertGreater(table[1], table[7], "боевые: шаг медленнее бега")
        self.assertGreater(table[17], table[19], "мирные: шаг медленнее бега")


class CombatWorkplaceTest(unittest.TestCase):
    """Вид рабочего места: занятие в старшей половине, взгляд в младшей."""

    #: Ниже 0x70 — обычная работа; воевода нужен от этого порога.
    COMBAT_FROM = 0x70
    #: 0x90/0xA0 дают приказ 9 (пара), 0x70/0x80 — приказ 10 (в одиночку).
    PAIR_KINDS = {0x90, 0xA0}
    SOLO_KINDS = {0x70, 0x80}

    def setUp(self) -> None:
        maps = sorted(glob.glob(str(КОРЕНЬ / "content_build" / "maps"
                                    / "*" / "map.json")))
        if not maps:
            self.skipTest("пак не собран")
        self.combat = []
        for path in maps:
            document = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
            villages = [document.get("village")]
            villages += list((document.get("village_by_world") or {}).values())
            for village in villages:
                for place in ((village or {}).get("workplaces") or []):
                    if (place.get("kind", 0) & 0xF0) >= self.COMBAT_FROM:
                        self.combat.append((path, place))

    def test_facing_fits_eight_directions(self) -> None:
        """Младшая половина вида — направление взгляда, значит меньше восьми.

        Отдельного поля направления у места НЕТ вовсе, и спарринг ищет
        напарника именно по нему: боец смотрит, куда велит место, а
        напарник стоит через клетку. Восьмёрка и выше значила бы, что
        младшая половина — не направление, и весь поиск был бы наугад.
        """
        self.assertTrue(self.combat, "боевых мест в паке нет")
        wrong = [(path, place["kind"]) for path, place in self.combat
                 if (place["kind"] & 0x0F) >= 8]
        self.assertEqual(wrong, [], "взгляд не помещается в восемь сторон")

    def test_every_combat_kind_is_known(self) -> None:
        """Иных боевых видов, кроме четырёх известных, в паке не водится."""
        kinds = {place["kind"] & 0xF0 for _, place in self.combat}
        self.assertTrue(kinds <= (self.PAIR_KINDS | self.SOLO_KINDS), kinds)

    def test_pairs_and_solos_both_exist(self) -> None:
        """Есть и парные места, и одиночные — обе ветви живые."""
        pairs = [p for _, p in self.combat if (p["kind"] & 0xF0) in self.PAIR_KINDS]
        solos = [p for _, p in self.combat if (p["kind"] & 0xF0) in self.SOLO_KINDS]
        self.assertTrue(pairs, "парных мест нет — приказ 9 не появится нигде")
        self.assertTrue(solos, "одиночных мест нет — приказ 10 не появится")


class ArcherTrainsMeleeTest(unittest.TestCase):
    """Тренировка — всегда ближний бой, даже у лучника (жалоба 23.08).

    Замах движка (0x416B50) третьей командой сбрасывает «бьётся
    метательным» (`+0xEE = 0`) — без переноса лучник в казарме «махал
    луком» со звуком натяга тетивы. Обратно режим возвращает задумывание
    боя (0x412FF4: стреляет тот, у кого есть И метательное, И боеприпас),
    иначе сбитый в рукопашную стрелок не стрелял бы уже никогда. Звук
    замаха привязан к ПОЗЕ (блоку), как в 0x429B2C, а не к режиму.
    """

    def client(self, name: str) -> str:
        return (КОРЕНЬ / "knyaz2" / "web" / "static" / name).read_text(
            encoding="utf-8")

    def test_swing_drops_ranged_mode(self) -> None:
        units = self.client("units.js")
        self.assertIn("if (melee) unit.rangedMode = false", units)

    def test_combat_thinking_restores_ranged_mode(self) -> None:
        units = self.client("units.js")
        self.assertIn("unit.equipment?.ranged && unit.equipment?.ammo", units)
        self.assertIn("unit.rangedMode = true", units)

    def test_swing_sound_follows_the_pose(self) -> None:
        sfx = self.client("sfx.js")
        self.assertIn('String(actor?.pose ?? "").startsWith("shoot")', sfx)
        self.assertNotIn("actor?.rangedMode && weapon", sfx)


if __name__ == "__main__":
    unittest.main()
