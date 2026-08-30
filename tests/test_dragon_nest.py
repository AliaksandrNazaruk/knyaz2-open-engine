# -*- coding: utf-8 -*-
"""Гнездо дракона: остров, страж и телепорт (карта 188, донорская 38).

Что здесь закреплено и почему это было сломано:

* СТРАЖ ГНЕЗДА — гигантский дракон (порода 88, тело 23, уровень 25,
  Сила 250) — не попадал в пак ВООБЩЕ: он безымянный, наша подпись
  «житель N» шла по номеру записи, а номера в GAME.0…3 разные
  (813/822/810/801) — и «нейтральное ядро» сборщика выбрасывало его как
  сюжетного. Ключ юнита теперь не верит подписи (builder._unit_key).
* Стоит он РОВНО на клетке телепорта 103:60 — сторожит выход; сам
  телепорт (запись выходов #284 донора) ведёт с острова вниз на 69:44.
* СЕМЬ ЧАНОВ — ЭТО И ЕСТЬ КВЕСТ ВХОДА (раскрыто 2026-08-22 по языку QST
  из посылки сообщества). Незажжённый чан — оверлей 264 карты; «Поджечь
  чан факелом» (нужен предмет класса 46) взводит ДВА токена: спрятать
  оверлей (LANDSCAPE=38,…,−300,−300) и поставить горящий объект
  (OBJECT=38,n,x,y — семь пар, разница якорей ровно 66,15). Седьмой
  зажжённый чан сам переносит отряд действием 69(38): запись выходов #38
  донора с нулевой зоной, вход 107:58 — остров. Пешком в ущелье входят
  из Угорья, запись 266. Прежняя подпись «не квест, а вечный огонь» была
  неверной; в паке чаны пока горят с начала — это отступление, механика
  токенов-команд записана в бэклог.
"""
from __future__ import annotations

import json
import pathlib
import unittest

КОРЕНЬ = pathlib.Path(__file__).resolve().parents[1]


class DragonNestTest(unittest.TestCase):
    def setUp(self) -> None:
        путь = КОРЕНЬ / "content_build" / "maps" / "188" / "map.json"
        if not путь.is_file():
            self.skipTest("пак не собран")
        self.карта = json.loads(путь.read_text(encoding="utf-8"))

    def юниты(self) -> list[dict]:
        return list(self.карта.get("units") or [])

    def test_giant_dragon_guards_the_teleport(self) -> None:
        """Страж на месте: порода 88, тело 23, клетка 103:60, разговор 90."""
        гиганты = [u for u in self.юниты() if u.get("breed") == 88]
        self.assertEqual(len(гиганты), 1, "гигантский дракон должен быть один")
        г = гиганты[0]
        self.assertEqual(г.get("body"), 23)
        self.assertEqual(г.get("cell"), {"row": 103, "col": 60})
        self.assertEqual(г.get("dialog_number"), 90)

    def test_ordinary_dragons_are_ten(self) -> None:
        обычные = [u for u in self.юниты() if u.get("breed") == 82]
        self.assertEqual(len(обычные), 10)

    def test_units_are_thirty_one(self) -> None:
        """31, а не 30: раньше страж терялся, и число было круглым."""
        self.assertEqual(len(self.юниты()), 31)

    def test_self_exit_teleport_exists(self) -> None:
        """Выход карты в саму себя: 103:60 -> 69:44."""
        свои = [e for e in (self.карта.get("exits") or [])
                if e.get("to_map") == 188]
        self.assertEqual(len(свои), 1)
        e = свои[0]
        self.assertEqual((e["row1"], e["col1"], e["row2"], e["col2"]),
                         (103, 60, 103, 60))
        self.assertEqual((e["entry_row"], e["entry_col"]), (69, 44))

    def test_burning_bowls_survived_the_rebake(self) -> None:
        """Перепечка карты не должна терять огни (builder печёт их сам)."""
        огни = [o for g in ("props", "buildings")
                for o in (self.карта.get(g) or []) if o.get("fire")]
        self.assertEqual(len(огни), 7)


class IgnitionChainTest(unittest.TestCase):
    """Цепочка входа в гнездо — прямо из донорского QUESTS.RES.

    Семь диалогов чанов 277…283: ответ «Поджечь чан факелом» требует
    предмет класса 46 и взводит два токена чана; ветка седьмого чана
    зовёт действие 69(38) — перенос на остров. Числа в проектной
    нумерации: квесты донора сдвинуты на 152.
    """

    @classmethod
    def setUpClass(cls) -> None:
        from konung2 import donor
        if not donor.available():
            raise unittest.SkipTest("exe «Продолжения легенды» недоступен")
        from konung2.profile import LEGEND
        from konung2.quests import Dialogs
        cls.dialogs = Dialogs.from_game(LEGEND)

    def test_bowl_dialog_ignites_two_tokens(self) -> None:
        дерево = self.dialogs.tree(277)
        ответы = [o for n in дерево["nodes"] if n["kind"] == "line"
                  for o in n["options"] if o["text"] == "Поджечь чан факелом."]
        self.assertEqual(len(ответы), 2, "ветка обычная и ветка седьмого чана")
        for о in ответы:
            self.assertEqual([c["handler"] for c in о["condition"]], [17])
            self.assertEqual([c["argument"] for c in о["condition"]], [46])
            self.assertEqual(
                [(c["kind"], c["quest"], c["set"]) for c in о["actions"]],
                [("quest", 215, True), ("quest", 216, True)])

    def test_seventh_bowl_teleports_to_island(self) -> None:
        дерево = self.dialogs.tree(277)
        переносы = [c for n in дерево["nodes"] if n["kind"] == "line"
                    for c in n["actions"]
                    if c["kind"] == "handler" and c["handler"] == 69]
        self.assertEqual(len(переносы), 1)
        self.assertEqual(переносы[0]["argument"], 38)

    def test_island_entry_record_is_38(self) -> None:
        """Запись #38: зона нулевая (вход только действием), клетка 107:58."""
        from konung2.profile import LEGEND
        from konung2.gamefile import _game_bytes, _exit_record
        data, layout = _game_bytes(0, LEGEND)
        at, count, size = layout["exits"]
        запись = _exit_record(data[at + 38 * size:][:size],
                              LEGEND.game_exit_shift)
        self.assertEqual(запись["to_map"], 38)
        self.assertEqual((запись["entry_row"], запись["entry_col"]), (107, 58))
        self.assertEqual((запись["row1"], запись["col1"],
                          запись["row2"], запись["col2"]), (0, 0, 0, 0))


class TalkPilesTest(unittest.TestCase):
    """Разговорные кучи: чаны — это кучи с байтом диалога (+0x07 записи).

    Донорский 0x411BC6: байт меньше 0xFE — приказ «обыскать» открывает
    диалог 0x100 + байт БЕЗ собеседника. Пак везёт им дерево разговора,
    как юнитам. У канона этой ветки нет (0x4115AC байт не читает), и его
    нулевые байты разговором считаться не должны.
    """

    def setUp(self) -> None:
        путь = КОРЕНЬ / "content_build" / "maps" / "188" / "map.json"
        if not путь.is_file():
            self.skipTest("пак не собран")
        self.карта = json.loads(путь.read_text(encoding="utf-8"))

    def кучи(self) -> list[dict]:
        return list(self.карта.get("loot") or [])

    def test_seven_talk_piles_with_trees(self) -> None:
        говорящие = [p for p in self.кучи() if p.get("dialog_tree")]
        self.assertEqual(len(говорящие), 7)
        # проектные номера деревьев: донорские 277…283 со сдвигом 152
        self.assertEqual(sorted(p["dialog_number"] for p in говорящие),
                         list(range(429, 436)))
        for p in говорящие:
            дерево = p["dialog_tree"]
            self.assertEqual(дерево["number"], p["dialog_number"])
            self.assertEqual(дерево["game"], "Продолжение легенды")
            тексты = [n.get("text", "") for n in дерево["nodes"]
                      if n.get("kind") == "line"]
            self.assertTrue(any("маслом" in т for т in тексты), p["id"])

    def test_talk_piles_carry_no_items(self) -> None:
        for p in self.кучи():
            if p.get("dialog_tree"):
                self.assertFalse(p.get("items"), p["id"])
                self.assertFalse(p.get("money"), p["id"])

    def test_canon_map_has_no_talk_piles(self) -> None:
        """Нулевой байт канона — не «диалог 256»: ветки в его движке нет."""
        путь = КОРЕНЬ / "content_build" / "maps" / "19" / "map.json"
        if not путь.is_file():
            self.skipTest("канонная карта не собрана")
        карта = json.loads(путь.read_text(encoding="utf-8"))
        кучи = list(карта.get("loot") or [])
        self.assertTrue(кучи, "на 19-й кучи есть всегда")
        self.assertFalse([p for p in кучи if p.get("dialog_tree")])

    def test_talk_piles_across_donor_maps(self) -> None:
        """Все НАПОЛЬНЫЕ разговорные кучи донора доехали до пака.

        154 несёт ВСЕ ТРИ бочки: третья (донорская куча 54, диалог 270)
        стоит на мягкой глуши донора (бит 0x1000; terrain.blocked_soft),
        и движок до неё доводит — его отказ «цель — стена» ловит только
        низ 0xFFF, а финиш волны не проверяется. Разговорные кучи
        сборщик проходимостью не отсеивает: движок такой проверки не
        делает вовсе.
        """
        #: С «лодочными» разговорами (гнездо 0xFF — разговор объекта,
        #: LOOT_SPEC §8) счёт вырос: 26 куч на 17 картах добавились к
        #: чанам и бочкам. Полный срез пака 23.08.
        ожидание = {154: 6, 155: 3, 156: 1, 159: 1, 171: 1, 178: 3,
                    181: 2, 182: 2, 183: 2, 184: 1, 185: 1, 186: 4,
                    188: 7, 195: 1, 197: 1, 203: 1, 216: 1, 217: 1}
        for номер, надо in ожидание.items():
            путь = КОРЕНЬ / "content_build" / "maps" / str(номер) / "map.json"
            if not путь.is_file():
                continue
            карта = json.loads(путь.read_text(encoding="utf-8"))
            говорящие = [p for p in (карта.get("loot") or [])
                         if p.get("dialog_tree")]
            self.assertEqual(len(говорящие), надо, f"карта {номер}")

    def test_soft_blocked_cells_travel_in_the_pack(self) -> None:
        """Мягкая глушь донора едет в пак подмножеством blocked.

        На Переправе (186) вся глушь мягкая: у донора в сетке нет ни
        одной клетки с канонным низом 0xFFF — 15185 клеток несут бит
        0x1000 при пустом низе. Клетки брода — среди них: квест-XOR
        снимает именно этот бит.
        """
        путь = КОРЕНЬ / "content_build" / "maps" / "186" / "map.json"
        if not путь.is_file():
            self.skipTest("карта 186 не собрана")
        terrain = json.loads(путь.read_text(encoding="utf-8"))["terrain"]
        blocked = set(map(tuple, terrain["blocked"]))
        soft = set(map(tuple, terrain.get("blocked_soft") or []))
        self.assertEqual(len(soft), 15185)
        self.assertTrue(soft <= blocked, "мягкие обязаны быть подмножеством")
        for клетка in ((92, 48), (93, 48), (95, 50)):
            self.assertIn(клетка, soft, "клетка брода")
        # канонная карта поля не несёт
        канон = КОРЕНЬ / "content_build" / "maps" / "19" / "map.json"
        if канон.is_file():
            terrain19 = json.loads(канон.read_text(encoding="utf-8"))["terrain"]
            self.assertNotIn("blocked_soft", terrain19)

    def test_client_wave_accepts_soft_goal(self) -> None:
        """Проводка клиента: мягкая цель волны и обратный ход XOR."""
        hero = (КОРЕНЬ / "knyaz2" / "web" / "static" / "hero.js").read_text(
            encoding="utf-8")
        self.assertIn("const CELL_SOFT = 0x1000", hero)
        self.assertIn("occupant !== CELL_SOFT", hero)
        self.assertIn("terrain.blocked_soft", hero)
        # для шага и приказа «идти» мягкая глушь — та же стена
        self.assertIn("kind === CELL_WALL || kind === CELL_SOFT", hero)
        # квест-XOR возвращает клетке ЕЁ вид глуши
        self.assertIn("hero.softCells?.has(at) ? CELL_SOFT : CELL_WALL", hero)
        # шаг довершает маршрут на мягкую ЦЕЛЬ, но не в свободном ходу
        self.assertIn("const softGoal = unit.goal", hero)
        self.assertIn("!softGoal && !heroFree", hero)


class ClickThroughTest(unittest.TestCase):
    """Клик сквозь прозрачные пиксели юнита («факел не работает», 23.08).

    Движок ищет юнита под курсором по маске НАРИСОВАННОГО кадра: блит
    юнита пишет его номер в буфер попаданий (VA 0x425DB4 -> 0x442260),
    прозрачные пиксели не пишут ничего. Наша прежняя рамка 60x106 при
    строке сетки в 16 точек накрывала пять строк вверх — герой у чана
    глотал щелчок, приказ «обыскать» не выдавался, и поджечь чан было
    нельзя вовсе. Живой прогон 23.08: с пробой альфы клик вплотную
    открывает диалог чана, а клик в тело по-прежнему выбирает героя.
    """

    def test_unit_hit_is_pixel_accurate(self) -> None:
        units = (КОРЕНЬ / "knyaz2" / "web" / "static" / "units.js").read_text(
            encoding="utf-8")
        self.assertIn("function unitPixelHit", units)
        # канонные адреса буфера попаданий — в объяснении правила
        self.assertIn("0x425DB4", units)
        self.assertIn("0x442260", units)
        # порог альфы и запасной ответ рамкой, пока лист кадра не доехал
        self.assertIn(".data[3] >= 128", units)
        self.assertIn("return best ?? backup", units)
        # из попавших пикселем побеждает нарисованный позже
        self.assertIn("unitSortKey(unit)", units)


if __name__ == "__main__":
    unittest.main()
