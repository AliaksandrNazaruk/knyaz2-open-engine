# -*- coding: utf-8 -*-
"""Спека лута (docs/LOOT_SPEC.md) — числа и механики под сторожем.

Числа спеки сняты сканом собранного пака: если пересборка их сдвинет,
тест обязан упасть — тогда правится СПЕКА, а не подгоняется скан.
"""
from __future__ import annotations

import json
import pathlib
import unittest

КОРЕНЬ = pathlib.Path(__file__).resolve().parents[1]


def _скан():
    итог = {"всего": 0, "гнёзда": 0, "тайники": 0, "разговорные": 0,
            "с_деньгами": 0}
    карты_тайников = set()
    кусты = 0
    карты_растений = set()
    for путь in sorted(pathlib.Path(КОРЕНЬ, "content_build", "maps")
                       .glob("*/map.json")):
        номер = int(путь.parent.name)
        документ = json.loads(путь.read_text(encoding="utf-8"))
        for pile in (документ.get("loot") or []):
            # кучи редактора (pile_new_*) — пользовательский контент;
            # спека меряет канон и не должна дрожать от демо-карт
            if str(pile.get("id") or "").startswith("pile_new_"):
                continue
            итог["всего"] += 1
            if pile.get("zone") is not None:
                итог["гнёзда"] += 1
            if pile.get("buried"):
                итог["тайники"] += 1
                карты_тайников.add(номер)
            if pile.get("dialog_number") is not None:
                итог["разговорные"] += 1
            if pile.get("money"):
                итог["с_деньгами"] += 1
        группы = [документ.get("loot") or []]
        for кучи in (документ.get("loot_by_world") or {}).values():
            группы.append(кучи or [])
        нашёл = False
        for кучи in группы:
            for pile in кучи:
                for ref in (pile.get("items") or []):
                    части = str(ref).split(":")
                    if части[0] in ("class", "instance") and int(части[1]) in (81, 82):
                        кусты += 1
                        нашёл = True
        if нашёл:
            карты_растений.add(номер)
    return итог, карты_тайников, кусты, карты_растений


class LootPackNumbersTest(unittest.TestCase):
    """Числа пака — ровно те, что записаны в спеке."""

    def test_pack_matches_the_spec(self) -> None:
        if not (КОРЕНЬ / "content_build" / "maps" / "33" / "map.json").is_file():
            self.skipTest("пак не собран")
        итог, карты_тайников, кусты, карты_растений = _скан()
        self.assertEqual(итог["всего"], 701)
        self.assertEqual(итог["гнёзда"], 90)
        self.assertEqual(итог["тайники"], 203)
        self.assertEqual(len(карты_тайников), 73)
        self.assertEqual(итог["разговорные"], 39)
        self.assertEqual(итог["с_деньгами"], 417)
        self.assertEqual(кусты, 628, "кустов растений (классы 81/82)")
        self.assertEqual(len(карты_растений), 45)

    def test_spec_document_names_the_numbers(self) -> None:
        спека = (КОРЕНЬ / "docs" / "LOOT_SPEC.md").read_text(encoding="utf-8")
        for кусок in ("701", "203 на 73 картах", "628 кустов на 45 картах",
                      "5400…5759", "PILE_LIMIT", "d100"):
            self.assertIn(кусок, спека)


class LootMechanicsGuardTest(unittest.TestCase):
    """Строки-сторожа механик, на которых стоит спека."""

    def клиент(self, name: str) -> str:
        return (КОРЕНЬ / "knyaz2" / "web" / "static" / name).read_text(
            encoding="utf-8")

    def test_regrow_classes_and_ticks(self) -> None:
        loot = self.клиент("loot.js")
        self.assertIn("REGROW_CLASSES = new Set([0x51, 0x52])", loot)
        # порог движка: метка с делением на записи и сравнение 0x1517
        self.assertIn("REGROW_AFTER = 0x1517", loot)
        self.assertIn("-1 - Math.floor(ticks / REGROW_STEP)", loot)
        self.assertIn("PILE_SLOTS = 42", loot)
        self.assertIn("PILE_LIMIT = 200", loot)

    def test_search_order_identify_money_dug(self) -> None:
        combat = self.клиент("combat.js")
        self.assertIn("identifyRoll(hero, word)", combat)
        self.assertIn("Math.abs(pile.money)", combat)
        self.assertIn("if (pile.buried) pile.dug = true", combat)
        jewels = self.клиент("jewels.js")
        self.assertIn("roll >= skill", jewels)      # d100 ПРОТИВ навыка

    def test_shovel_and_mirror(self) -> None:
        combat = self.клиент("combat.js")
        self.assertIn("shovel_class ?? 32", combat)
        loot = self.клиент("loot.js")
        self.assertIn("export function lootReveal", loot)


if __name__ == "__main__":
    unittest.main()
