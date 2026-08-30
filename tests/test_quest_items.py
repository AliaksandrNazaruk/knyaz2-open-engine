# -*- coding: utf-8 -*-
"""Применение квестовых вещей — покрытие диспетчера 0x436C48.

Спецификация — docs/ITEMS_SPEC.md: полная таблица веток движка по классам.
Здесь сторожится, что каждая ветка либо перенесена (и где), либо честно
записана дырой в спеке. Числа прибавок — из самих веток:

    Свиток кузнеца  +5 «Кузнечное дело»     (случай '(')
    Трактат         +10 «Торговля»          (случай ',')
    Гиппократ       +10 «Знахарство»        (случай '-')
    Чертежи         +10 «Строительные…»     (случай '0')
    Ягода           +10 «Идентификация…»    (случай '2')
    Лапка           Сила +3, Чаша Харизма +10 (FUN_00436BA8, кап 150)
    Яблоко          опыт = «Волхование» × 3  (случай '1')
    Свиток ведуна   опознать всё, +1 навыка за вещь (FUN_0041B7C0)
    Паутина         чужим людям карты скорость −2 (байт +0x1D = 0xFE)
    Кукла           бит +0xF9|2 чужим без «Заячьего хвоста» (класс 33)
    Мощи            бит +0xF9|1 себе
    Грамота (1)     токен квеста 0 (0x6A50E8 |= 0x80)
"""
from __future__ import annotations

import pathlib
import unittest

КОРЕНЬ = pathlib.Path(__file__).resolve().parents[1]


def клиент(name: str) -> str:
    return (КОРЕНЬ / "knyaz2" / "web" / "static" / name).read_text(
        encoding="utf-8")


class UsesCoverageTest(unittest.TestCase):
    """Каждая ветка 0x436C48 перенесена — или записана дырой в спеке."""

    #: Классы, которые обязаны быть в таблице USES questitems.js.
    #: Учебников и даров тут НЕТ: их ведёт usePowder по правилам пака
    #: (rules.craft.powders) — см. отдельный тест ниже.
    В_USES = (0, 1, 4, 9, 10, 11, 12, 15, 21, 22, 23, 25, 34, 37, 39,
              41, 223)

    def test_uses_covers_the_dispatcher(self) -> None:
        код = клиент("questitems.js")
        for класс in self.В_USES:
            with self.subTest(класс=класс):
                self.assertIn(f"\n  {класс}: (", код,
                              f"класса {класс} нет в USES")

    def test_special_paths_live_where_expected(self) -> None:
        self.assertIn("glow_torch_class ?? 46", клиент("questitems.js"))
        self.assertIn("wine?.class ?? 30", клиент("questitems.js"))
        carry = клиент("carry.js")
        self.assertIn("whistle_class ?? 38", carry)
        self.assertIn("whistle_class_alt ?? 31", carry)
        self.assertIn("lootReveal", carry)          # Медное зеркало (35)
        self.assertIn("Лопата", клиент("combat.js"))  # тайники под лопату

    def test_books_travel_as_pack_powder_rules(self) -> None:
        """Учебники и дары — правила пака rules.craft.powders, не USES.

        Числа и НАВЫКИ — ровно движковые ветки 0x436C48; сообщения при
        этом лежат в паке дословными строками exe (0x4591F4 и далее) —
        сверяются с exe ниже.
        """
        import json
        путь = КОРЕНЬ / "content_build" / "shared.json"
        if not путь.is_file():
            self.skipTest("пак не собран")
        document = json.loads(путь.read_text(encoding="utf-8"))
        порошки = document["hero"]["rules"]["craft"]["powders"]
        self.assertEqual(порошки["skills"]["40"], {
            "gain": 5, "skill": 17,
            "message": "Ты познал секреты кузнечного дела"})
        self.assertEqual(порошки["skills"]["44"]["skill"], 14)
        self.assertEqual(порошки["skills"]["45"]["skill"], 11)
        self.assertEqual(порошки["skills"]["48"]["skill"], 18)
        self.assertEqual(порошки["skills"]["50"]["skill"], 15)
        for row in порошки["skills"].values():
            self.assertIn(row["gain"], (5, 10))
        self.assertEqual(порошки["characteristics"]["42"],
                         {"characteristic": 4, "gain": 3})
        self.assertEqual(порошки["characteristics"]["47"],
                         {"characteristic": 0, "gain": 10})
        self.assertEqual(порошки["experience"],
                         {"class": 49, "scale": 3, "skill": 16})
        # сообщения — байт в байт строки exe (адреса из веток 0x436C48)
        адреса = {"40": 0x4591F4, "44": 0x459216, "45": 0x459242,
                  "48": 0x45926F, "50": 0x459299}
        from konung2.exetables import va_to_foff
        from konung2.profile import CANON
        data = CANON.exe_bytes()
        for класс, адрес in адреса.items():
            at = va_to_foff(адрес)
            line = data[at:data.index(0, at)].decode("cp866")
            self.assertEqual(порошки["skills"][класс]["message"], line,
                             f"класс {класс}")

    def test_transfers_follow_the_engine_cells(self) -> None:
        """Сфера (15) и Ключи (25): карты, клетки и взгляды из веток.

        Интерпретация полей входа (+0x0C строка, +0x14 столбец) сверена
        проходимостью пака: клетка (48,30) карты 3 свободна, зеркальная
        (30,48) — глушь.
        """
        код = клиент("questitems.js")
        self.assertIn("to_map: 6, entry_row: 120, entry_col: 18, facing: 2", код)
        self.assertIn("to_map: 3, entry_row: 48, entry_col: 30, facing: 1", код)
        self.assertIn("to_map: 48, entry_row: 12, entry_col: 22, facing: 3", код)
        self.assertIn("to_map: 3, entry_row: 6, entry_col: 26, facing: 5", код)
        self.assertIn('return "keep"', код)      # сфера с острова не тратится
        self.assertIn('result !== "keep"', код)  # и хвост это уважает
        self.assertIn("внутри(21, 24, 22, 23)", код)   # тюрьма
        self.assertIn("внутри(7, 11, 30, 32)", код)    # дворец

    def test_flags_and_token_follow_the_engine(self) -> None:
        код = клиент("questitems.js")
        self.assertIn("hero.flags = (hero.flags ?? 0) | 1", код)   # мощи
        self.assertIn("unit.flags = (unit.flags ?? 0) | 2", код)   # кукла
        # грамота ходит через мир — кольцо с dialog.js запрещено
        self.assertIn("world.questTokenSet(0)", код)
        self.assertIn("world.questTokenSet = (number)", клиент("dialog.js"))
        # оберег от куклы — класс 33 в мешке жертвы
        self.assertIn("index === 33", код)

    def test_web_and_scroll_follow_the_engine(self) -> None:
        """37 — замедление чужих, 39 — опознание (0x25/0x27 switch)."""
        код = клиент("questitems.js")
        self.assertIn("unit.speed = -2", код)              # паутина
        self.assertIn('raiseSkill("Идентификация предметов", opened)', код)
        # донорские эволюции — только в донорском мире
        self.assertIn('hero.game === "legend"', код)
        self.assertIn("Math.floor(Math.random() * 105)", код)  # жребии 0x69
        self.assertIn("raiseCharacteristic(2, 2)", код)    # финики: Инт +2
        self.assertIn("Math.min(1600, (hero.health ?? 0) + 160)", код)
        self.assertIn("to_map: 177, entry_row: 44, entry_col: 17", код)
        # волшебный точильный камень: навык 100 на время починки, вечный
        self.assertIn("hero.skills[кузнец] = 100", код)
        # грамота на корабль: пометка выходов −2, не тратится
        self.assertIn("exit.to_map === -2", код)

    def test_known_holes_are_written_down(self) -> None:
        """Оставшиеся дыры записаны в спеке честно."""
        спека = (КОРЕНЬ / "docs" / "ITEMS_SPEC.md").read_text(encoding="utf-8")
        self.assertIn("BIRD.AVI", спека)
        self.assertIn("Магическая сфера", спека)
        self.assertIn("Связка ключей", спека)


class ShipVoyageTest(unittest.TestCase):
    """Рейс корабля: выход −2 живёт по корабельному праву 0x84960C.

    Канон (0x420900, ветка 0xFE): шаг в зону выхода −2 срабатывает только
    когда право выписано ТЕКУЩЕЙ карте, гасит его в «плывём» (−1) и уводит
    на глобальную карту; по ней отряд идёт морской маской (0x4277F4:
    бит 2), встреча в плавании — «Корабль в пути» с реактивацией права
    (0x422CCC), а жребий «сцена 26 -> 27» реактивирует и пешему
    (0x4360A8). Право выписывают получение грамоты (обработчик 35 с
    классом 4 — 0x432F1C, у донора 0x4360E8) и донорское применение
    грамоты (0x435E00); приказ разговора 69 сажает без права (0x435AA0).
    """

    def test_charter_field_and_voyage_gate(self) -> None:
        worldmap = клиент("worldmap.js")
        self.assertIn("ship: 0", worldmap)
        self.assertIn("0x84960C", worldmap)
        app = клиент("app.js")
        # гейт рейса и гашение в «плывём»
        self.assertIn("worldMap.ship !== here", app)
        self.assertIn("worldMap.ship = -1", app)
        # приказ 69 садится без права — ветка −2 в onTransition своя
        self.assertIn("0x435AA0: перенос", app)

    def test_charter_writers(self) -> None:
        dialog = клиент("dialog.js")
        self.assertIn("argument === 4", dialog)
        self.assertIn("worldMap.ship = here", dialog)
        items = клиент("questitems.js")
        self.assertIn("worldMap.ship = карта", items)

    def test_world_walk_and_encounters_go_by_sea(self) -> None:
        ui = клиент("ui.js")
        self.assertIn("ship: worldMap.ship === -1", ui)
        worldmap = клиент("worldmap.js")
        self.assertIn("worldMap.rules?.scenes?.sea ?? 26", worldmap)
        app = клиент("app.js")
        self.assertIn("seaScenes.has(met.scene)", app)

    def test_charter_survives_saves_and_music(self) -> None:
        save = клиент("save.js")
        self.assertIn("ship: worldMap.ship ?? 0", save)
        self.assertIn("saved.worldMap?.ship", save)
        scape = клиент("soundscape.js")
        self.assertIn("sea_map ?? 21", scape)
        cursors = клиент("cursors.js")
        self.assertIn("worldMap.ship === 0 ? null", cursors)


class DonorTailCatalogueTest(unittest.TestCase):
    """Хвост каталога (211+) — собственные сюжетные классы донора.

    Деревья разговоров пака зовут их переведёнными номерами
    (donor.item_class_map): Книга Мудрых у Азама в Тиграте, Ключи у Радо…
    Без записей класса «дать»/«есть»/«забрать» молчали. Хвост печёт
    donor.tail_classes: вид — из его миров, иконки — из ЕГО INTERF.
    """

    def test_tail_classes_resolve_names_and_kinds(self) -> None:
        from konung2 import donor
        if not donor.available():
            self.skipTest("донора нет")
        пары = {item.index: (item, kind) for item, kind in donor.tail_classes()}
        self.assertGreaterEqual(len(пары), 18)
        self.assertEqual(пары[211][0].name, "Браслет Владыка")
        self.assertEqual(пары[214][0].name, "Ключ Воды")
        self.assertEqual(пары[218][0].name, "Книга Мудрых")
        self.assertEqual(пары[221][0].name, "Амулет Дракона")
        доспех, kind = пары[228]
        self.assertEqual(доспех.name, "Доспех Дракона")
        self.assertEqual(kind, 2, "Доспех Дракона — вид «доспех»")
        self.assertEqual(доспех.power, 400)
        self.assertEqual(доспех.durability, 200)

    def test_the_pack_carries_the_tail(self) -> None:
        import json
        путь = КОРЕНЬ / "content_build" / "maps" / "33" / "map.json"
        if not путь.is_file():
            self.skipTest("пак не собран")
        document = json.loads(путь.read_text(encoding="utf-8"))
        items = document.get("items") or {}
        if "class:211" not in items:
            self.skipTest("пак ещё без хвоста — перепечь карты")
        self.assertEqual(items["class:211"]["name"], "Браслет Владыка")
        self.assertEqual(items["class:221"]["name"], "Амулет Дракона")
        self.assertEqual(items["class:228"]["name"], "Доспех Дракона")
        self.assertEqual(items["class:228"]["kind"], 2)
        # иконки хвоста — из ДОНОРСКОГО листа, не канонного
        for key in ("class:214", "class:221", "class:228"):
            icon = items[key].get("icon") or {}
            self.assertIn("legend_ui_", str(icon.get("path")),
                          f"{key}: иконка обязана быть донорской")


if __name__ == "__main__":
    unittest.main()
