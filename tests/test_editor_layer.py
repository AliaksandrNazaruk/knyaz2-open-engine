# -*- coding: utf-8 -*-
"""Новый редактор поверх ядра — слой правок целиком.

Цепочка: браузерная панель (editor.js) -> POST /editor/unit дев-сервера
-> project/maps/<карта>/map.json ключ `editor_units` -> сборка пака
применяет патчи поверх расстановки (builder._editor_unit_apply).
Здесь каждая ступень проверяется по отдельности и круговым прогоном.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
import tempfile
import unittest
from unittest import mock

КОРЕНЬ = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(КОРЕНЬ))


def клиент(name_: str) -> str:
    return (КОРЕНЬ / 'knyaz2' / 'web' / 'static' / name_).read_text(
        encoding='utf-8')


class BuilderApplyTest(unittest.TestCase):
    """Белый список сборки: данные правятся, устройство — нет."""

    def test_flat_and_dict_fields(self) -> None:
        from knyaz2.content.builder import _editor_unit_apply
        unit = {"id": "unit_7", "name": "Щек", "level": 3,
                "stats": {"health": 1600, "armour": 20},
                "characteristics": {"Сила": 30, "Ловкость": 10}}
        _editor_unit_apply(unit, {
            "level": 9, "money": 500,
            "stats": {"health": 800},
            "characteristics": {"Сила": 77},
            "equipment": {"hand": "взлом"},      # вне списка — мимо
            "dialog": {"root": 1},               # вне списка — мимо
        })
        self.assertEqual(unit["level"], 9)
        self.assertEqual(unit["money"], 500)
        # словарь слился, а не заменился: броня уцелела
        self.assertEqual(unit["stats"], {"health": 800, "armour": 20})
        self.assertEqual(unit["characteristics"],
                         {"Сила": 77, "Ловкость": 10})
        # снаряжение правится с тех пор, как редактор умеет переодевать;
        # словарь сливается, как характеристики
        self.assertEqual(unit["equipment"], {"hand": "взлом"})
        # а вот произвольное поле по-прежнему не проходит
        self.assertNotIn("dialog", unit)

    def test_empty_patch_is_noop(self) -> None:
        from knyaz2.content.builder import _editor_unit_apply
        unit = {"id": "unit_1", "level": 2}
        _editor_unit_apply(unit, None)
        _editor_unit_apply(unit, {})
        self.assertEqual(unit, {"id": "unit_1", "level": 2})


class ServerSaveTest(unittest.TestCase):
    """Ручка сохранения кладёт патч в project-карту и мержит повторы."""

    def test_roundtrip_into_project_map(self) -> None:
        from knyaz2.web import server
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            (root_ / "33_probnaya").mkdir()
            with mock.patch.object(server, "PROJECT_MAPS", root_):
                ok_, reply = server.editor_unit_save(
                    33, "unit_7", {"level": 9, "stats": {"health": 800}})
                self.assertTrue(ok_, reply)
                ok_, _ = server.editor_unit_save(
                    33, "unit_7", {"stats": {"armour": 50}})
                self.assertTrue(ok_)
                document = json.loads(
                    (root_ / "33_probnaya" / "scenario.json").read_text(
                        encoding="utf-8"))
        patch_ = document["editor_units"]["unit_7"]
        self.assertEqual(patch_["level"], 9)
        # повторный патч словаря ДОЛИЛСЯ, а не затёр здоровье
        self.assertEqual(patch_["stats"], {"health": 800, "armour": 50})

    def test_bad_input_is_refused(self) -> None:
        from knyaz2.web import server
        with tempfile.TemporaryDirectory() as tmp_dir:
            with mock.patch.object(server, "PROJECT_MAPS",
                                   pathlib.Path(tmp_dir)):
                self.assertFalse(server.editor_unit_save(
                    33, "unit_7", {"level": 1})[0])   # карты нет
                self.assertFalse(server.editor_unit_save(
                    33, "взлом", {"level": 1})[0])     # чужой id
                self.assertFalse(server.editor_unit_save(
                    33, "unit_7", {})[0])              # пустой патч

    def test_full_chain_server_to_builder(self) -> None:
        """Круговой: что записала ручка — то применила сборка."""
        from knyaz2.web import server
        from knyaz2.content.builder import _editor_unit_apply
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            (root_ / "05_krug").mkdir()
            with mock.patch.object(server, "PROJECT_MAPS", root_):
                server.editor_unit_save(5, "unit_3",
                                        {"name": "Правленый",
                                         "characteristics": {"Сила": 99}})
                document = json.loads(
                    (root_ / "05_krug" / "scenario.json").read_text(
                        encoding="utf-8"))
        unit = {"id": "unit_3", "name": "Былой",
                "characteristics": {"Сила": 10, "Ловкость": 20}}
        _editor_unit_apply(unit, document["editor_units"]["unit_3"])
        self.assertEqual(unit["name"], "Правленый")
        self.assertEqual(unit["characteristics"],
                         {"Сила": 99, "Ловкость": 20})


class BuilderLootApplyTest(unittest.TestCase):
    """Слой куч: патч по id, удаление, добавление новых."""

    def test_patch_remove_and_add(self) -> None:
        from knyaz2.content.builder import _editor_loot_apply
        piles = [
            {"id": "pile_1", "money": 10, "buried": False,
             "items": ["instance:5:game:0:1"], "details": [{}],
             "item": "instance:5:game:0:1"},
            {"id": "pile_2", "money": 0, "items": [], "details": []},
        ]
        патчи = {
            "pile_1": {"money": 500, "buried": True,
                       "items": ["class:46"], "details": [{}],
                       "dialog": {"root": 1}},   # вне списка — мимо
            "pile_2": {"removed": True},
        }
        новые = [{"id": "pile_new_7",
                  "cell": {"row": 5, "col": 6},
                  "items": ["class:23"], "details": [{}], "money": 3},
                 {"без_id": True}]               # брак — отбрасывается
        outcome = _editor_loot_apply([dict(p) for p in piles], патчи, новые)
        по_id = {p["id"]: p for p in outcome}
        self.assertNotIn("pile_2", по_id)         # удалена
        pile = по_id["pile_1"]
        self.assertEqual(pile["money"], 500)
        self.assertTrue(pile["buried"])
        self.assertEqual(pile["items"], ["class:46"])
        self.assertEqual(pile["item"], "class:46")   # первый обновился
        self.assertNotIn("dialog", pile)
        fresh_one = по_id["pile_new_7"]
        self.assertTrue(fresh_one["on_floor"])
        self.assertEqual(fresh_one["item"], "class:23")
        self.assertEqual(len(outcome), 2)

    def test_loot_save_routes_new_to_add_list(self) -> None:
        from knyaz2.web import server
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            (root_ / "12_kuchi").mkdir()
            with mock.patch.object(server, "PROJECT_MAPS", root_):
                ok_, _ = server.editor_save(12, "loot", "pile_3",
                                           {"money": 40})
                self.assertTrue(ok_)
                ok_, _ = server.editor_save(
                    12, "loot", "pile_new_9",
                    {"cell": {"row": 1, "col": 2}, "items": ["class:5"]})
                self.assertTrue(ok_)
                # повторный патч новой кучи — upsert, не дубль
                ok_, _ = server.editor_save(12, "loot", "pile_new_9",
                                           {"money": 77})
                self.assertTrue(ok_)
                document = json.loads(
                    (root_ / "12_kuchi" / "scenario.json").read_text(
                        encoding="utf-8"))
        self.assertEqual(document["editor_loot"]["pile_3"]["money"], 40)
        добавленные = document["editor_loot_add"]
        self.assertEqual(len(добавленные), 1)
        self.assertEqual(добавленные[0]["id"], "pile_new_9")
        self.assertEqual(добавленные[0]["money"], 77)
        self.assertEqual(добавленные[0]["items"], ["class:5"])


class BuilderUnitsListTest(unittest.TestCase):
    """Фаза 3: удаление и добавление юнитов списком."""

    def test_removed_and_added(self) -> None:
        from knyaz2.content.builder import _editor_units_apply
        units_ = [{"id": "unit_1", "name": "Первый", "level": 2},
                 {"id": "unit_2", "name": "Второй", "level": 3}]
        патчи = {"unit_1": {"removed": True},
                 "unit_2": {"level": 9}}
        новые = [{"id": "unit_new_5", "name": "Клон", "breed": 1,
                  "cell": {"row": 4, "col": 5}},
                 {"мусор": True}]
        outcome = _editor_units_apply(units_, патчи, новые)
        по_id = {u["id"]: u for u in outcome}
        self.assertNotIn("unit_1", по_id)
        self.assertEqual(по_id["unit_2"]["level"], 9)
        клон = по_id["unit_new_5"]
        self.assertEqual(клон["dialog_number"], 0xFF)   # мирные умолчания
        self.assertEqual(клон["equipment"], {})
        self.assertEqual(len(outcome), 2)

    def test_home_is_editable(self) -> None:
        from knyaz2.content.builder import (EDITOR_UNIT_DICTS,
                                            _editor_unit_apply)
        self.assertIn("home", EDITOR_UNIT_DICTS)
        unit = {"id": "unit_3", "cell": {"row": 1, "col": 1},
                "home": {"row": 1, "col": 1}}
        _editor_unit_apply(unit, {"cell": {"row": 7, "col": 8},
                                  "home": {"row": 7, "col": 8}})
        self.assertEqual(unit["cell"], {"row": 7, "col": 8})
        self.assertEqual(unit["home"], {"row": 7, "col": 8})

    def test_new_unit_routes_to_add_list(self) -> None:
        from knyaz2.web import server
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            (root_ / "07_klon").mkdir()
            with mock.patch.object(server, "PROJECT_MAPS", root_):
                ok_, _ = server.editor_save(
                    7, "unit", "unit_new_3",
                    {"name": "Клон", "cell": {"row": 2, "col": 2}})
                self.assertTrue(ok_)
                ok_, _ = server.editor_save(7, "unit", "unit_new_3",
                                           {"level": 4})
                self.assertTrue(ok_)
                document = json.loads(
                    (root_ / "07_klon" / "scenario.json").read_text(
                        encoding="utf-8"))
        добавленные = document["editor_units_add"]
        self.assertEqual(len(добавленные), 1)         # upsert, не дубль
        self.assertEqual(добавленные[0]["name"], "Клон")
        self.assertEqual(добавленные[0]["level"], 4)


class BuilderPropsApplyTest(unittest.TestCase):
    """Фаза 4: реквизит — патч, перенос рамкой, удаление, добавление."""

    def test_props_patch_and_move(self) -> None:
        from knyaz2.content.builder import _editor_props_apply
        props = [{"id": "legacy:33:prop:10", "kind": "prop", "palette": 87,
                  "state": 0, "position": {"x": 100, "y": 200},
                  "bounds": {"draw_x": 72, "draw_y": -14, "sort_y": 656,
                             "width": 51, "height": 201}},
                 {"id": "legacy:33:prop:11", "kind": "prop"}]
        патчи = {"legacy:33:prop:10": {
                     "palette": 3, "state": 1,
                     "position": {"x": 130, "y": 220},
                     "bounds": {"draw_x": 102, "draw_y": 6, "sort_y": 676},
                     "frames": {"взлом": True}},   # вне списка — мимо
                 "legacy:33:prop:11": {"removed": True}}
        новые = [{"id": "prop_new_1", "position": {"x": 5, "y": 6},
                  "palette": 1}]
        outcome = _editor_props_apply([dict(p) for p in props], патчи, новые)
        по_id = {p["id"]: p for p in outcome}
        self.assertNotIn("legacy:33:prop:11", по_id)
        объект = по_id["legacy:33:prop:10"]
        self.assertEqual(объект["palette"], 3)
        self.assertEqual(объект["position"], {"x": 130, "y": 220})
        # рамка слилась: ширина уцелела, сдвиги применились
        self.assertEqual(объект["bounds"]["draw_x"], 102)
        self.assertEqual(объект["bounds"]["width"], 51)
        self.assertNotIn("frames", объект)   # вне списка — не приехал
        new_one = по_id["prop_new_1"]
        self.assertEqual(new_one["kind"], "prop")
        self.assertEqual(new_one["state"], 0)

    def test_prop_save_accepts_legacy_ids(self) -> None:
        from knyaz2.web import server
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            (root_ / "09_prop").mkdir()
            with mock.patch.object(server, "PROJECT_MAPS", root_):
                ok_, _ = server.editor_save(9, "prop", "legacy:9:prop:4",
                                           {"palette": 7})
                self.assertTrue(ok_)
                ok_, _ = server.editor_save(9, "prop", "prop_new_2",
                                           {"position": {"x": 1, "y": 2}})
                self.assertTrue(ok_)
                self.assertFalse(server.editor_save(
                    9, "prop", "взлом", {"palette": 1})[0])
                document = json.loads(
                    (root_ / "09_prop" / "scenario.json").read_text(
                        encoding="utf-8"))
        self.assertIn("legacy:9:prop:4", document["editor_props"])
        self.assertEqual(document["editor_props_add"][0]["id"],
                         "prop_new_2")


class CellEditTest(unittest.TestCase):
    """Фаза 5: клетки ландшафта правятся прямо в grid.txt проекта."""

    @staticmethod
    def grid() -> str:
        line = " ".join(["0000:0000"] * 160)
        перевод = chr(10)
        return "# шапка" + перевод + перевод.join(
            [line] * 256) + перевод

    def test_peek_toggle_and_flags(self) -> None:
        from knyaz2.web import server
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            (root_ / "21_zemlya").mkdir()
            (root_ / "21_zemlya" / "grid.txt").write_text(
                self.grid(), encoding="utf-8")
            with mock.patch.object(server, "PROJECT_MAPS", root_):
                ok_, _, кл = server.editor_cell_save(21, 5, 7, {})
                self.assertTrue(ok_)
                self.assertEqual((кл["lo"], кл["hi"]), (0, 0))
                self.assertFalse(кл["blocked"] or кл["solid"])
                # глушь: низ 12 бит целиком
                ok_, _, кл = server.editor_cell_save(21, 5, 7,
                                                    {"blocked": True})
                self.assertTrue(кл["blocked"])
                self.assertEqual(кл["lo"], 0x0FFF)
                # стена для стрел — бит 0x4000 поверх глуши
                ok_, _, кл = server.editor_cell_save(21, 5, 7,
                                                    {"solid": True})
                self.assertEqual(кл["lo"], 0x4FFF)
                # снятие глуши не трогает бит стрел
                ok_, _, кл = server.editor_cell_save(21, 5, 7,
                                                    {"blocked": False})
                self.assertEqual(кл["lo"], 0x4000)
                # перечитанный файл несёт правку и шапку
                text_ = (root_ / "21_zemlya" / "grid.txt").read_text(
                    encoding="utf-8")
                self.assertTrue(text_.startswith("# шапка"))
                self.assertIn("4000:0000", text_)
                # соседняя клетка не тронута
                ok_, _, кл = server.editor_cell_save(21, 5, 8, {})
                self.assertEqual((кл["lo"], кл["hi"]), (0, 0))

    def test_batch_brushes(self) -> None:
        """Пакетные кисти земли и сетки: живой прогон прототипа показал,
        что параллельные одиночные POST затирают друг друга (PNG и
        grid.txt пишутся целиком) — мазок области едет одним телом."""
        from knyaz2.web import server
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            folder = root_ / "61_proba"
            folder.mkdir()
            Image.new("L", (160, 160), 0).save(folder / "layer1.png")
            Image.new("L", (160, 80), 0).save(folder / "layer2.png")
            line = " ".join(["4FFF:0000"] * 160)
            (folder / "grid.txt").write_text(
                chr(10).join(["# ш", *([line] * 256)]) + chr(10),
                encoding="utf-8")
            with mock.patch.object(server, "PROJECT_MAPS", root_):
                strokes = [{"row": r, "col": c, "lower": 7}
                         for r in range(20, 24) for c in range(5, 10)]
                ok_, _, кл = server.editor_ground_save(
                    61, 20, 5, {"cells": strokes})
                self.assertTrue(ok_)
                ok_, _, т = server.api_terrain(61)
                flooded = sum(1 for row_ in т["lower"]
                             for z_ in row_ if z_ == 7)
                self.assertEqual(flooded, 20)
                # сетка: расчистка области пакетом
                пачка = [{"row": r, "col": c, "blocked": False}
                         for r in range(10, 13) for c in range(4, 8)]
                ok_, _, кл = server.editor_cell_save(
                    61, 10, 4, {"cells": пачка})
                self.assertTrue(ok_)
                self.assertFalse(кл["blocked"])
                ok_, _, k_ = server.api_cells(61)
                свободных = sum(
                    1 for row_ in k_["cells"] for cell_ in row_
                    if int(cell_[:4], 16) & 0xFFF == 0)
                self.assertEqual(свободных, 12)
                # hi-биты пачкой: кисть света областью раньше терялась
                light = [{"row": r, "col": c, "light": True}
                        for r in range(10, 12) for c in range(4, 6)]
                ok_, _, кл = server.editor_cell_save(
                    61, 10, 4, {"cells": light})
                self.assertTrue(ok_)
                self.assertTrue(кл["light"])
                ok_, _, k_ = server.api_cells(61)
                светлых = sum(
                    1 for row_ in k_["cells"] for cell_ in row_
                    if int(cell_[5:], 16) & server.CELL_LIGHT_BIT)
                self.assertEqual(светлых, 4)

    def test_full_bit_map_of_cell(self) -> None:
        """Фаза 10: признаки клетки — карта бит по дизасму (кисть
        DAT_00640AEC старого редактора; Light/Inner читает движок,
        UpOff пишется, но финальным движком не читается)."""
        from knyaz2.web import server
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            (root_ / "21_zemlya").mkdir()
            (root_ / "21_zemlya" / "grid.txt").write_text(
                self.grid(), encoding="utf-8")
            with mock.patch.object(server, "PROJECT_MAPS", root_):
                # LO: выход 0x1000, прозрачность 0x8000
                ok_, _, кл = server.editor_cell_save(
                    21, 3, 4, {"exit": True, "transparent": True})
                self.assertTrue(ok_)
                self.assertEqual(кл["lo"], 0x9000)
                self.assertTrue(кл["exit"] and кл["transparent"])
                # HI: интерьер 0x20, свет 0x40, UpOff 0x80, объект 0-4
                ok_, _, кл = server.editor_cell_save(
                    21, 3, 4, {"inner": True, "light": True,
                               "upoff": True, "object": 7})
                self.assertEqual(кл["hi"], 0xE7)
                self.assertTrue(кл["inner"] and кл["light"] and кл["upoff"])
                self.assertEqual(кл["object"], 7)
                # смена объекта не смывает флаги; сброс — нулём
                ok_, _, кл = server.editor_cell_save(21, 3, 4, {"object": 30})
                self.assertEqual(кл["hi"], 0xFE)
                ok_, _, кл = server.editor_cell_save(21, 3, 4, {"object": 0})
                self.assertEqual(кл["hi"], 0xE0)
                # объект вне 0-30 — отказ
                self.assertFalse(server.editor_cell_save(
                    21, 3, 4, {"object": 31})[0])
                # в файле оба слова на месте
                text_ = (root_ / "21_zemlya" / "grid.txt").read_text(
                    encoding="utf-8")
                self.assertIn("9000:00E0", text_)

    def test_bounds_and_missing_grid(self) -> None:
        from knyaz2.web import server
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            (root_ / "22_bez").mkdir()
            with mock.patch.object(server, "PROJECT_MAPS", root_):
                self.assertFalse(server.editor_cell_save(
                    22, 0, 0, {})[0])                    # нет grid.txt
                self.assertFalse(server.editor_cell_save(
                    22, 300, 0, {})[0])                  # вне сетки
                self.assertFalse(server.editor_cell_save(
                    22, 0, 160, {})[0])


class QuestPhaseTest(unittest.TestCase):
    """Фаза 6: номер диалога юнита и компиляция квестов."""

    def test_dialog_number_is_editable(self) -> None:
        from knyaz2.content.builder import (EDITOR_UNIT_FIELDS,
                                            _editor_unit_apply)
        self.assertIn("dialog_number", EDITOR_UNIT_FIELDS)
        unit = {"id": "unit_4", "dialog_number": 255}
        _editor_unit_apply(unit, {"dialog_number": 74})
        self.assertEqual(unit["dialog_number"], 74)

    def test_rebake_wiring_present(self) -> None:
        """Сторожа перепечки: смена номера обязана перепечь дерево —
        оно испечено раньше слоя."""
        билдер = (КОРЕНЬ / 'knyaz2' / 'content' / 'builder.py').read_text(
            encoding='utf-8')
        self.assertIn('def _bake_dialog_tree(game, project, number', билдер)
        self.assertIn('unit["dialog"] = trees[talk_number]', билдер)
        # добавленный говорящий юнит тоже получает дерево
        self.assertIn('entry.get("dialog_number", 0xFF) != 0xFF', билдер)

    def test_quests_compile_live(self) -> None:
        """Живая компиляция авторским M_QUEST.exe в песочнице: статистика
        та же, что у эталона (103 токена)."""
        from knyaz2.web import server
        import shutil
        if not server.QUESTS_COMPILER.is_file():
            self.skipTest('посылка k2_tools не на месте')
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir) / "KONUNG2"
            shutil.copytree(server.QUESTS_DIR.parent, root_)
            with mock.patch.object(server, "QUESTS_DIR",
                                   root_ / "QUESTS"),                  mock.patch.object(server, "QUESTS_COMPILER",
                                   root_ / "RESOURCE" / "M_QUEST.exe"):
                ok_, reply = server.editor_quests_compile()
                self.assertTrue(ok_, reply)
                self.assertIn("Tokens", reply)
                self.assertIn("103", reply)
                self.assertTrue((root_ / "QUESTS" / "QUESTS.RES").is_file())


class GroundEditTest(unittest.TestCase):
    """Фаза 7: тайлы земли — пара в layer1.png, свет в layer2.png."""

    def test_paint_and_peek(self) -> None:
        from knyaz2.web import server
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            folder = root_ / "31_zemlya"
            folder.mkdir()
            Image.new("L", (160, 160), 0).save(folder / "layer1.png")
            Image.new("L", (160, 80), 0).save(folder / "layer2.png")
            with mock.patch.object(server, "PROJECT_MAPS", root_):
                # мазок: нижний 5, верхний 7, свет 2
                ok_, _, кл = server.editor_ground_save(
                    31, 10, 20, {"lower": 5, "upper": 7, "light": 2})
                self.assertTrue(ok_)
                self.assertEqual((кл["lower"], кл["upper"], кл["light"]),
                                 (5, 7, 2))
                # peek читает то же
                ok_, _, кл = server.editor_ground_save(31, 10, 20, {})
                self.assertEqual((кл["lower"], кл["upper"], кл["light"]),
                                 (5, 7, 2))
                # ластик нижнего не трогает верхний
                ok_, _, кл = server.editor_ground_save(
                    31, 10, 20, {"lower": None})
                self.assertIsNone(кл["lower"])
                self.assertEqual(кл["upper"], 7)
                # соседняя клетка чиста
                ok_, _, кл = server.editor_ground_save(31, 10, 21, {})
                self.assertIsNone(кл["lower"])
                # в самих пикселях лежит индекс+1 (формат .KN2)
                img = Image.open(folder / "layer1.png").convert("L")
                self.assertEqual(img.getpixel((20 * 2 + 1, 10)), 8)
                # свет лежит ЛИНЕЙНО со страйдом 0x50 (graph.py:527):
                # клетка (10,20) — байт 820 — пиксель (20, 5), не (20, 10)
                img2 = Image.open(folder / "layer2.png").convert("L")
                self.assertEqual(img2.getpixel((820 % 160, 820 // 160)), 3)
                self.assertEqual(img2.getpixel((20, 10)), 0)
                # границы
                self.assertFalse(server.editor_ground_save(
                    31, 160, 0, {})[0])
                self.assertFalse(server.editor_ground_save(
                    31, 0, 80, {})[0])

    def test_tiles_page_bakes_previews(self) -> None:
        from knyaz2.web import server
        with tempfile.TemporaryDirectory() as tmp_dir:
            ok_, _, reply = server.editor_tiles_page(0, tmp_dir)
            self.assertTrue(ok_)
            self.assertGreater(len(reply["tiles"]), 0)
            first_one = reply["tiles"][0]
            self.assertTrue(first_one["url"].startswith(
                "/content/assets/ground/editor_tile_"))
            name_ = first_one["url"].rsplit("/", 1)[1]
            self.assertTrue((pathlib.Path(tmp_dir) / "assets" / "ground"
                             / name_).is_file())
            self.assertGreater(reply["pages"], 1)


class WaterEditTest(unittest.TestCase):
    """Фаза 8: вода-подложка — sparse-records блока 16x32 в map.json.

    Канон типа воды: OR всех 512 байтов, бит 0x80 = Lake (стоит), иначе
    Stream (течёт); редактор писал единый байт 0x80/0x40 во все клетки
    (VA 0x43DF48 -> 0x84961C -> развилка VA 0x428240).
    """

    @staticmethod
    def _проект(root_: pathlib.Path) -> pathlib.Path:
        folder = root_ / "33_bore"
        folder.mkdir()
        ряд7 = bytearray(32)
        ряд7[4] = 0x40
        ряд7[5] = 0x40
        file = folder / "map.json"
        file.write_text(json.dumps({
            "map_number": 33, "origin": {"editor": True}, "light_flag": 160,
            "light": {"_default": "00" * 32, "_count": 16, "_size": 32,
                      "records": [{"slot": 7, "raw": ряд7.hex()}]},
        }), encoding="utf-8")
        return file

    def test_paint_erase_and_peek(self) -> None:
        from knyaz2.web import server
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            file = self._проект(root_)
            with mock.patch.object(server, "PROJECT_MAPS", root_):
                # peek без патча: две клетки ряда 7, тайл из light_flag
                ok_, _, water = server.editor_water_save(33, {})
                self.assertTrue(ok_)
                self.assertEqual(water["count"], 2)
                self.assertEqual(water["limit"], 512)
                self.assertEqual(water["tile"], 160)
                # капля в новый ряд рождает sparse-запись; кисть льёт
                # канонный байт типа карты, не голую единицу
                ok_, _, water = server.editor_water_save(
                    33, {"row": 5, "col": 10, "value": 1})
                self.assertTrue(ok_)
                self.assertEqual(water["count"], 3)
                self.assertEqual(water["value"], 0x40)
                document = json.loads(file.read_text(encoding="utf-8"))
                slots = {r["slot"] for r in document["light"]["records"]}
                self.assertEqual(slots, {5, 7})
                # ластик осушает и убирает опустевший ряд из records
                ok_, _, water = server.editor_water_save(
                    33, {"row": 5, "col": 10, "value": 0})
                self.assertEqual(water["count"], 2)
                document = json.loads(file.read_text(encoding="utf-8"))
                slots = {r["slot"] for r in document["light"]["records"]}
                self.assertEqual(slots, {7})
                # границы сетки 16x32
                self.assertFalse(server.editor_water_save(
                    33, {"row": 16, "col": 0, "value": 1})[0])
                self.assertFalse(server.editor_water_save(
                    33, {"row": 0, "col": 32, "value": 1})[0])

    def test_stream_toggle_rewrites_all_cells(self) -> None:
        from knyaz2.web import server
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            file = self._проект(root_)
            with mock.patch.object(server, "PROJECT_MAPS", root_):
                # клетки 0x40 -> OR без бита 0x80 -> Stream
                ok_, _, water = server.editor_water_save(33, {})
                self.assertTrue(water["stream"])
                # Lake переписывает ВСЕ ненулевые клетки на 0x80
                ok_, _, water = server.editor_water_save(33, {"stream": False})
                self.assertFalse(water["stream"])
                self.assertEqual(water["count"], 2)
                document = json.loads(file.read_text(encoding="utf-8"))
                ряд7 = bytes.fromhex(
                    {r["slot"]: r["raw"]
                     for r in document["light"]["records"]}[7])
                self.assertEqual((ряд7[4], ряд7[5]), (0x80, 0x80))
                # у Lake-карты и кисть льёт озёрный байт
                ok_, _, water = server.editor_water_save(
                    33, {"row": 2, "col": 2, "value": 1})
                self.assertEqual(water["value"], 0x80)
                self.assertFalse(water["stream"])
                # обратно в Stream — все клетки снова 0x40
                ok_, _, water = server.editor_water_save(33, {"stream": True})
                self.assertTrue(water["stream"])
                document = json.loads(file.read_text(encoding="utf-8"))
                for record in document["light"]["records"]:
                    for byte_val in bytes.fromhex(record["raw"]):
                        self.assertIn(byte_val, (0, 0x40))

    def test_tile_and_nonzero_default(self) -> None:
        from knyaz2.web import server
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            file = self._проект(root_)
            # дефолт РЯДА бывает ненулевым (RecordTable: «самое частое»)
            document = json.loads(file.read_text(encoding="utf-8"))
            document["light"]["_default"] = "01" * 32
            document["light"]["records"] = []
            file.write_text(json.dumps(document), encoding="utf-8")
            with mock.patch.object(server, "PROJECT_MAPS", root_):
                ok_, _, water = server.editor_water_save(33, {"tile": 161})
                self.assertTrue(ok_)
                self.assertEqual(water["tile"], 161)
                self.assertEqual(water["count"], 512)
                document = json.loads(file.read_text(encoding="utf-8"))
                self.assertEqual(document["light_flag"], 161)
                # ряды, равные дефолту, в records не расползлись
                self.assertEqual(document["light"]["records"], [])
                # а изменённый ряд — попал, остальные остались дефолту
                server.editor_water_save(33, {"row": 3, "col": 0,
                                              "value": 0})
                document = json.loads(file.read_text(encoding="utf-8"))
                slots = [r["slot"] for r in document["light"]["records"]]
                self.assertEqual(slots, [3])


class SpriteEditTest(unittest.TestCase):
    """Фаза 9: оверлеи ландшафта — sparse-records блока dynamic."""

    @staticmethod
    def _проект(root_: pathlib.Path) -> pathlib.Path:
        folder = root_ / "33_bore"
        folder.mkdir()
        file = folder / "map.json"
        file.write_text(json.dumps({
            "map_number": 33, "origin": {"editor": True},
            "dynamic": {"_default": "ff" * 12, "_count": 1000, "_size": 12,
                        "records": [
                            {"slot": 0, "id": 26, "kind": 5632,
                             "pixel_x": 1218, "pixel_y": 672,
                             "raw": "1a00000000160000c204a002"},
                            {"slot": 2, "id": 30, "kind": 5632,
                             "pixel_x": 1972, "pixel_y": 960,
                             "raw": "1e00000000160000b407c003"},
                        ]},
        }), encoding="utf-8")
        return file

    def test_move_retint_and_remove(self) -> None:
        from knyaz2.web import server
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            file = self._проект(root_)
            with mock.patch.object(server, "PROJECT_MAPS", root_):
                # peek: обе записи с полями
                ok_, _, reply = server.editor_sprite_save(33, {})
                self.assertTrue(ok_)
                self.assertEqual(reply["count"], 2)
                self.assertEqual(reply["records"][0],
                                 {"slot": 0, "id": 26, "x": 1218, "y": 672})
                # перенос: поля меняются, raw цел (pack положит поля
                # поверх — неизвестные байты записи не теряются)
                ok_, _, reply = server.editor_sprite_save(
                    33, {"slot": 0, "x": 700, "y": 500})
                self.assertTrue(ok_)
                document = json.loads(file.read_text(encoding="utf-8"))
                record = document["dynamic"]["records"][0]
                self.assertEqual((record["pixel_x"], record["pixel_y"]),
                                 (700, 500))
                self.assertEqual(record["raw"], "1a00000000160000c204a002")
                # смена спрайта GRAPH
                ok_, _, reply = server.editor_sprite_save(
                    33, {"slot": 2, "id": 44})
                document = json.loads(file.read_text(encoding="utf-8"))
                self.assertEqual(document["dynamic"]["records"][1]["id"], 44)
                # удаление выкидывает запись — слот вернётся к 12xFF
                ok_, _, reply = server.editor_sprite_save(
                    33, {"slot": 2, "removed": True})
                self.assertEqual(reply["count"], 1)
                document = json.loads(file.read_text(encoding="utf-8"))
                self.assertEqual(
                    [r["slot"] for r in document["dynamic"]["records"]], [0])
                # чужой слот — отказ
                self.assertFalse(server.editor_sprite_save(
                    33, {"slot": 777, "x": 1})[0])

    def test_add_appends_after_last_slot(self) -> None:
        """Слот за последним занятым, НЕ в дырку: движок читает таблицу
        до первого пустого (0x80000000-сентинел в 0x43DF48) — запись в
        дырке спрятала бы хвост от оригинала."""
        from knyaz2.web import server
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            file = self._проект(root_)
            with mock.patch.object(server, "PROJECT_MAPS", root_):
                # заняты 0 и 2 — добавка идёт в 3, дырка 1 не трогается
                ok_, _, reply = server.editor_sprite_save(
                    33, {"add": {"id": 23, "x": 111, "y": 222}})
                self.assertTrue(ok_)
                self.assertEqual(reply["slot"], 3)
                self.assertEqual(reply["count"], 3)
                document = json.loads(file.read_text(encoding="utf-8"))
                records = document["dynamic"]["records"]
                self.assertEqual([r["slot"] for r in records], [0, 2, 3])
                fresh_one = records[2]
                self.assertEqual((fresh_one["id"], fresh_one["pixel_x"],
                                  fresh_one["pixel_y"]), (23, 111, 222))
                # база новой записи — дефолт таблицы
                self.assertEqual(fresh_one["raw"], "ff" * 12)


class ContentLibraryTest(unittest.TestCase):
    """Фаза 12: каталог объектов, бестиарий, отряды, добавление."""

    def test_objects_page_from_pack_passport(self) -> None:
        from knyaz2.web import server
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            (root_ / "assets" / "objects").mkdir(parents=True)
            (root_ / "assets" / "objects" / "index.json").write_text(
                json.dumps({
                    "canon:54:77:0": {"path": "assets/objects/54.png",
                                      "width": 100, "height": 80,
                                      "offset_x": -50, "offset_y": -40,
                                      "layers": {"main": {
                                          "path": "assets/objects/54m.png",
                                          "width": 100, "height": 80,
                                          "offset_x": -50,
                                          "offset_y": -40}}},
                    "legend:600:1:0": {"path": "assets/objects/600.png",
                                       "width": 10, "height": 10},
                }), encoding="utf-8")
            ok_, _, reply = server.editor_objects_page(0, tmp_dir)
            self.assertTrue(ok_)
            # донорские записи каталог канона не мешают
            self.assertEqual(reply["total"], 1)
            record = reply["items"][0]
            self.assertEqual((record["slot"], record["palette"]), (54, 77))
            self.assertIn("main", record["layers"])

    def test_object_add_appends_t_objects_record(self) -> None:
        from knyaz2.web import server
        from konung2.res import ObjectsRes
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            folder = root_ / "33_bore"
            folder.mkdir()
            (folder / "map.json").write_text(json.dumps({
                "map_number": 33, "origin": {"editor": True},
                "objects": {"_default": "ff" * 36, "_count": 1000,
                            "_size": 36, "records": [
                                {"slot": 0, "sprite": 5, "kind": 0,
                                 "pixel_x": 1, "pixel_y": 2,
                                 "raw": "00" * 36}]},
            }), encoding="utf-8")
            with mock.patch.object(server, "PROJECT_MAPS", root_):
                ok_, _, reply = server.editor_object_add(
                    33, {"slot": 264, "palette": 91, "state": 0,
                         "x": 700, "y": 500})
                self.assertTrue(ok_)
                # слот строго за последним занятым (сентинел движка)
                self.assertEqual(reply["record_slot"], 1)
                document = json.loads(
                    (folder / "map.json").read_text(encoding="utf-8"))
                fresh_one = document["objects"]["records"][1]
                self.assertEqual(fresh_one["sprite"],
                                 264 - ObjectsRes.SIMPLE_SLOT_BASE)
                self.assertEqual(fresh_one["kind"], 91 * 0x200)
                self.assertEqual((fresh_one["pixel_x"], fresh_one["pixel_y"]),
                                 (700, 500))

    def test_object_add_evicts_sentinels(self) -> None:
        """Запись-«стоп» (sprite=-1) не занимает слот: добавка встаёт на
        её место, хвост подтягивается — иначе оригинальный движок не
        увидел бы ничего за стопом (поймано валидатором на карте 23)."""
        from knyaz2.web import server
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            folder = root_ / "33_bore"
            folder.mkdir()
            (folder / "map.json").write_text(json.dumps({
                "map_number": 33, "origin": {"editor": True},
                "objects": {"_default": "00" * 36, "_count": 1000,
                            "_size": 36, "records": [
                                {"slot": 0, "id": 129, "kind": 43008,
                                 "pixel_x": 1, "pixel_y": 2,
                                 "raw": "8100000000a8" + "00" * 30},
                                {"slot": 1, "id": 65535, "next": 65535,
                                 "kind": 4294967295,
                                 "raw": "ff" * 36},
                                {"slot": 2, "sprite": 24, "kind": 0,
                                 "pixel_x": 3, "pixel_y": 4, "state": 0,
                                 "raw": "00" * 36}]},
            }), encoding="utf-8")
            with mock.patch.object(server, "PROJECT_MAPS", root_):
                ok_, _, o_ = server.api_validate(33, tmp_dir)
                self.assertIn("за сентинелом", " ".join(o_["errors"]))
                ok_, _, reply = server.editor_object_add(
                    33, {"slot": 40, "palette": 0, "state": 0,
                         "x": 9, "y": 9})
                self.assertTrue(ok_)
                document = json.loads(
                    (folder / "map.json").read_text(encoding="utf-8"))
                records = document["objects"]["records"]
                # сентинел ушёл, хвост подтянулся, добавка за ним
                self.assertEqual([r["slot"] for r in records], [0, 1, 2])
                self.assertEqual(records[1]["sprite"], 24)
                self.assertEqual(reply["record_slot"], 2)
                ok_, _, o_ = server.api_validate(33, tmp_dir)
                self.assertNotIn("за сентинелом", " ".join(o_["errors"]))

    def test_sprite_add_never_fills_holes(self) -> None:
        """Движок читает таблицы до первого пустого слота — добавка в
        дырку прятала бы хвост от оригинала."""
        from knyaz2.web import server
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            folder = root_ / "33_bore"
            folder.mkdir()
            (folder / "map.json").write_text(json.dumps({
                "map_number": 33, "origin": {"editor": True},
                "dynamic": {"_default": "ff" * 12, "_count": 1000,
                            "_size": 12, "records": [
                                {"slot": 0, "id": 26, "kind": 0,
                                 "pixel_x": 1, "pixel_y": 2,
                                 "raw": "ff" * 12},
                                {"slot": 5, "id": 30, "kind": 0,
                                 "pixel_x": 3, "pixel_y": 4,
                                 "raw": "ff" * 12}]},
            }), encoding="utf-8")
            with mock.patch.object(server, "PROJECT_MAPS", root_):
                ok_, _, reply = server.editor_sprite_save(
                    33, {"add": {"id": 44, "x": 9, "y": 9}})
                self.assertTrue(ok_)
                self.assertEqual(reply["slot"], 6)   # за последним, не 1

    def test_warband_layer_reaches_all_worlds(self) -> None:
        from knyaz2.web import server
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            folder = root_ / "33_bore"
            folder.mkdir()
            with mock.patch.object(server, "PROJECT_MAPS", root_):
                ok_, _, reply = server.editor_warband_add(
                    33, {"row": 100, "col": 80})
                self.assertTrue(ok_)
                band = reply["warband"]
                #: полоса редактора расширена 190…199 → 185…199, потому
                #: что десяти сторон не хватило: на карте 63 они
                #: кончились, и постановка встала с «сторона 200 вне
                #: 1-199». Замер по всем 141 карте пака: игра не
                #: занимает в 185…199 НИ ОДНОЙ стороны
                self.assertEqual(band["side"], 185)
                self.assertTrue(band["on_player"])
                self.assertEqual(band["war_flags"] & 0x4F, 0x01)
                self.assertEqual(band["zone"]["row_from"], 80)
                self.assertEqual(band["zone"]["col_to"], 100)
                # повтор стороны — отказ, но следующая берётся сама
                self.assertFalse(server.editor_warband_add(
                    33, {"side": 185, "row": 1, "col": 1})[0])
                #: ОБЫЧНЫЙ ЗАПРОС ПОДСЕЛЯЕТ, А НЕ ПЛОДИТ. Каждый клик по
                #: холсту заводил НОВЫЙ отряд: пятнадцать сторон
                #: редактора кончались на шестнадцатом жителе, и вся
                #: расстановка молча вставала — «юниты не
                #: устанавливаются». Теперь боец идёт в уже заведённый
                #: отряд той же враждебности.
                ok_, _, reply = server.editor_warband_add(
                    33, {"row": 1, "col": 1})
                self.assertEqual(reply["warband"]["side"], 185)
                self.assertTrue(reply.get("reused"))
                #: НОВЫЙ — ТОЛЬКО ПО ЯВНОЙ ПРОСЬБЕ (кнопка «отряд»).
                ok_, _, reply = server.editor_warband_add(
                    33, {"row": 1, "col": 1, "fresh": True})
                self.assertEqual(reply["warband"]["side"], 186)
                self.assertFalse(reply.get("reused"))
                #: мирный отряд — свой: подселение сверяет враждебность
                ok_, _, reply = server.editor_warband_add(
                    33, {"row": 1, "col": 1, "hostile": False})
                self.assertEqual(reply["warband"]["side"], 187)
                self.assertFalse(reply["warband"]["on_player"])

    def test_bestiary_collected_from_pack(self) -> None:
        from knyaz2.web import server
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            (root_ / "maps" / "7").mkdir(parents=True)
            (root_ / "shared.json").write_text(json.dumps({
                "creatures": {
                    "sets": {"2": {"58": {"stand": [
                        [{"sheet": 0, "x": 4, "y": 6, "width": 40,
                          "height": 30, "offset_x": 0, "offset_y": 0}]
                    ]}}},
                    "sheets": [{"path": "assets/creatures/c0.png",
                                "width": 400, "height": 300}]},
            }), encoding="utf-8")
            (root_ / "maps" / "7" / "map.json").write_text(json.dumps({
                "units": [
                    {"id": "unit_1", "name": "Пахарь", "breed": 2,
                     "body": 0},
                    {"id": "unit_9", "name": "Болотник", "breed": 0x43,
                     "body": 2, "level": 7, "speed": 3,
                     "stats": {"health": 1234},
                     "characteristics": {"Сила": 40}},
                ]}), encoding="utf-8")
            # кэш подменяется контекстом: тест не гадит соседям
            with mock.patch.object(server, "_BESTIARY_CACHE", None):
                ok_, _, reply = server.editor_bestiary(tmp_dir)
                self.assertTrue(ok_)
                breeds = reply["breeds"]
                # людей в бестиарии нет — только бит твари 0x40
                self.assertEqual([b["breed"] for b in breeds], [0x43])
                тварь = breeds[0]
                self.assertEqual(тварь["name"], "Болотник")
                self.assertEqual(тварь["palettes"], [58])
                # числа честные — сняты с живого юнита пака
                self.assertEqual(тварь["sample"]["stats"]["health"], 1234)
                превью = тварь["preview"]
                self.assertEqual((превью["x"], превью["y"]), (4, 6))
                self.assertEqual(превью["sheet_width"], 400)


class ApiV2Test(unittest.TestCase):
    """API v2 (docs/EDITOR_SPEC.md): чтение состояния, DELETE, build."""

    @staticmethod
    def _проект(root_: pathlib.Path) -> pathlib.Path:
        from PIL import Image
        folder = root_ / "33_bore"
        folder.mkdir()
        ряд7 = bytearray(32)
        ряд7[4] = 0x40
        (folder / "map.json").write_text(json.dumps({
            "map_number": 33, "origin": {"editor": True}, "name": "Борье", "light_flag": 160,
            "light": {"_default": "00" * 32, "_count": 16, "_size": 32,
                      "records": [{"slot": 7, "raw": ряд7.hex()}]},
            "objects": {"_default": "ff" * 36, "_count": 1000,
                        "_size": 36, "records": [
                            {"slot": 0, "sprite": 24, "kind": 39424,
                             "pixel_x": 100, "pixel_y": 200, "state": 0,
                             "raw": "00" * 36},
                            {"slot": 1, "sprite": 10, "kind": 0,
                             "pixel_x": 300, "pixel_y": 400, "state": 1,
                             "raw": "00" * 36}]},
            "dynamic": {"_default": "ff" * 12, "_count": 1000,
                        "_size": 12, "records": [
                            {"slot": 0, "id": 26, "kind": 0,
                             "pixel_x": 1, "pixel_y": 2, "raw": "ff" * 12},
                            {"slot": 1, "id": 30, "kind": 0,
                             "pixel_x": 3, "pixel_y": 4,
                             "raw": "ff" * 12}]},
        }), encoding="utf-8")
        (folder / "scenario.json").write_text(json.dumps({
            "editor_units_add": [{"id": "unit_new_7", "name": "Тест",
                                  "side": 190}],
            "editor_warbands_add": [{"side": 190}],
            "editor_loot_add": [{"id": "pile_new_3"}],
        }), encoding="utf-8")
        Image.new("L", (160, 160), 0).save(folder / "layer1.png")
        Image.new("L", (160, 80), 0).save(folder / "layer2.png")
        line = " ".join(["4FFF:0000"] * 160)
        (folder / "grid.txt").write_text(
            chr(10).join(["# шапка", *([line] * 256)]) + chr(10),
            encoding="utf-8")
        return folder

    def test_state_terrain_cells(self) -> None:
        from knyaz2.web import server
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            self._проект(root_)
            with mock.patch.object(server, "PROJECT_MAPS", root_):
                ok_, _, m_ = server.api_maps()
                self.assertTrue(ok_)
                # draft/built — признаки для фильтров списка карт,
                # editable — можно ли эту карту вообще писать (карты игры
                # защищены, и до появления признака UI об этом не знал:
                # см. test_maps_say_whether_they_are_editable)
                self.assertEqual(m_["maps"], [{"map": 33, "dir": "33_bore",
                                              "name": "Борье",
                                              "draft": True,
                                              "editable": True,
                                              "built": True}])
                ok_, _, s_ = server.api_map_state(33, tmp_dir)
                self.assertTrue(ok_)
                self.assertEqual(s_["meta"]["name"], "Борье")
                self.assertEqual(s_["water"]["count"], 1)
                self.assertEqual(len(s_["water"]["rows"]), 16)
                objects = s_["objects"]["records"]
                self.assertEqual(objects[0]["resource_slot"], 54)
                self.assertEqual(objects[0]["palette"], 77)
                self.assertIsNone(objects[1]["palette"])  # kind 0
                self.assertEqual(len(s_["overlays"]["records"]), 2)
                self.assertEqual(
                    s_["draft"]["editor_units_add"][0]["id"], "unit_new_7")
                self.assertFalse(s_["pack"]["built"])
                ok_, _, т = server.api_terrain(33)
                self.assertTrue(ok_)
                self.assertEqual((т["rows"], т["cols"]), (160, 80))
                self.assertIsNone(т["lower"][0][0])
                ok_, _, k_ = server.api_cells(33)
                self.assertEqual(len(k_["cells"]), 256)
                self.assertEqual(k_["cells"][0][0], "4FFF:0000")

    def test_water_stream_semantics_in_state(self) -> None:
        # клетки 0x40 -> OR без бита 0x80 -> stream True
        from knyaz2.web import server
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            self._проект(root_)
            with mock.patch.object(server, "PROJECT_MAPS", root_):
                ok_, _, s_ = server.api_map_state(33, tmp_dir)
                self.assertTrue(s_["water"]["stream"])

    def test_delete_object_compacts_tail(self) -> None:
        from knyaz2.web import server
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            folder = self._проект(root_)
            with mock.patch.object(server, "PROJECT_MAPS", root_):
                ok_, _, o_ = server.editor_object_remove(33, 0)
                self.assertTrue(ok_)
                document = json.loads(
                    (folder / "map.json").read_text(encoding="utf-8"))
                records = document["objects"]["records"]
                # хвост съехал: бывший слот 1 стал слотом 0
                self.assertEqual([r["slot"] for r in records], [0])
                self.assertEqual(records[0]["sprite"], 10)
                # оверлеи компактуются так же
                ok_, _, _ = server.editor_sprite_save(
                    33, {"slot": 0, "removed": True})
                document = json.loads(
                    (folder / "map.json").read_text(encoding="utf-8"))
                служба = document["dynamic"]["records"]
                self.assertEqual([r["slot"] for r in служба], [0])
                self.assertEqual(служба[0]["id"], 30)

    def test_delete_unit_loot_warband(self) -> None:
        from knyaz2.web import server
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            folder = self._проект(root_)
            with mock.patch.object(server, "PROJECT_MAPS", root_):
                # добавленный юнит изымается из draft
                ok_, _, o_ = server.api_unit_delete(33, "unit_new_7")
                self.assertTrue(ok_)
                d = json.loads((folder / "scenario.json").read_text(
                    encoding="utf-8"))
                self.assertEqual(d["editor_units_add"], [])
                # житель пака помечается removed
                ok_, _, o_ = server.api_unit_delete(33, "unit_12")
                self.assertTrue(ok_)
                d = json.loads((folder / "scenario.json").read_text(
                    encoding="utf-8"))
                self.assertTrue(d["editor_units"]["unit_12"]["removed"])
                # отряд и куча
                self.assertTrue(server.api_warband_delete(33, 190)[0])
                self.assertFalse(server.api_warband_delete(33, 190)[0])
                self.assertTrue(server.api_loot_delete(
                    33, "pile_new_3")[0])

    def test_dispatch_routes(self) -> None:
        from knyaz2.web import server
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            self._проект(root_)
            with mock.patch.object(server, "PROJECT_MAPS", root_):
                ok_, _, m_ = server.api_dispatch_get("/editor/api/maps", tmp_dir)
                self.assertTrue(ok_)
                ok_, _, s_ = server.api_dispatch_get(
                    "/editor/api/maps/33", tmp_dir)
                self.assertTrue(ok_)
                self.assertIn("water", s_)
                ok_, _, т = server.api_dispatch_get(
                    "/editor/api/maps/33/terrain", tmp_dir)
                self.assertTrue(ok_)
                # мутация через POST-маршрут
                ok_, _, в = server.api_dispatch_post(
                    "/editor/api/maps/33/water",
                    {"row": 3, "col": 3, "value": 1}, tmp_dir)
                self.assertTrue(ok_)
                self.assertEqual(в["count"], 2)
                ok_, _, k_ = server.api_dispatch_post(
                    "/editor/api/maps/33/cells",
                    {"row": 5, "col": 5, "exit": True}, tmp_dir)
                self.assertTrue(k_["exit"])
                # DELETE-маршрут
                ok_, _, o_ = server.api_dispatch_delete(
                    "/editor/api/maps/33/overlays/1")
                self.assertTrue(ok_)
                # неизвестный путь — отказ, не исключение
                self.assertFalse(server.api_dispatch_get(
                    "/editor/api/чушь", tmp_dir)[0])

    def test_build_status_guard(self) -> None:
        from knyaz2.web import server

        class _Живой:
            def poll(self):
                return None

        with mock.patch.dict(server._BUILD, {"proc": None, "job": 0,
                                             "log": None, "maps": []}):
            ok_, _, s_ = server.api_build_status()
            self.assertTrue(ok_)
            self.assertFalse(s_["running"])
            with mock.patch.dict(server._BUILD, {"proc": _Живой(),
                                                 "job": 5}):
                ok_, _, o_ = server.api_build_start([33])
                self.assertFalse(ok_)          # вторая сборка — отказ
                self.assertTrue(o_["running"])


class UndoValidateTest(unittest.TestCase):
    """E1.5: журнал мутаций, валидатор, схемы, API миров."""

    def test_undo_redo_roundtrip(self) -> None:
        from knyaz2.web import server
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            folder = root_ / "33_bore"
            folder.mkdir()
            (folder / "map.json").write_text(json.dumps({
                "map_number": 33, "origin": {"editor": True},
                "light": {"_default": "00" * 32, "_count": 16,
                          "_size": 32, "records": []},
            }), encoding="utf-8")
            было = (folder / "map.json").read_text(encoding="utf-8")
            with mock.patch.object(server, "PROJECT_MAPS", root_), \
                    mock.patch.object(server, "_UNDO", []), \
                    mock.patch.object(server, "_REDO", []):
                path_str = "/editor/api/maps/33/water"
                snapshot = server._journal_snapshot(path_str)
                ok_, _, в = server.api_dispatch_post(
                    path_str, {"row": 2, "col": 2, "value": 1}, tmp_dir)
                self.assertTrue(ok_)
                server._journal_push(snapshot)
                self.assertNotEqual(
                    (folder / "map.json").read_text(encoding="utf-8"),
                    было)
                # откат возвращает файл байт-в-байт
                ok_, _, u = server.api_undo()
                self.assertTrue(ok_)
                self.assertEqual(
                    (folder / "map.json").read_text(encoding="utf-8"),
                    было)
                # и повтор возвращает правку
                ok_, _, r = server.api_redo()
                self.assertTrue(ok_)
                ok_, _, water = server.editor_water_save(33, {})
                self.assertEqual(water["count"], 1)
                # история знает путь
                ok_, _, h = server.api_history()
                self.assertEqual(h["undo"], [path_str])

    def test_validate_finds_holes_and_wilds(self) -> None:
        from knyaz2.web import server
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            folder = root_ / "33_bore"
            folder.mkdir()
            (folder / "map.json").write_text(json.dumps({
                "map_number": 33, "origin": {"editor": True},
                "dynamic": {"_default": "ff" * 12, "_count": 1000,
                            "_size": 12, "records": [
                                {"slot": 0, "id": 1, "raw": "ff" * 12},
                                {"slot": 5, "id": 2, "raw": "ff" * 12}]},
            }), encoding="utf-8")
            line = " ".join(["4FFF:0000"] * 160)
            (folder / "grid.txt").write_text(
                chr(10).join(["# ш", *([line] * 256)]) + chr(10),
                encoding="utf-8")
            (folder / "scenario.json").write_text(json.dumps({
                "editor_units_add": [
                    {"id": "unit_new_1", "side": 190,
                     "cell": {"row": 10, "col": 10}},
                    {"id": "unit_new_2", "side": 191,
                     "cell": {"row": 999, "col": 0}}],
                "editor_warbands_add": [{"side": 190}],
            }), encoding="utf-8")
            with mock.patch.object(server, "PROJECT_MAPS", root_):
                ok_, _, o_ = server.api_validate(33, tmp_dir)
                self.assertTrue(ok_)
                errs = " | ".join(o_["errors"])
                troubles = " | ".join(o_["warnings"])
                self.assertIn("дырки в таблице оверлеев", errs)
                self.assertIn("глушь", errs)       # юнит 1 в 4FFF
                self.assertIn("вне сетки", errs)   # юнит 2
                self.assertIn("191", troubles)           # чужая сторона
                self.assertIn("выхода", troubles)        # выходов нет

    def test_schema_and_worlds_routes(self) -> None:
        from knyaz2.web import server
        ok_, _, s_ = server.api_dispatch_get("/editor/api/schema", None)
        self.assertTrue(ok_)
        self.assertIn("unit", s_["schema"])
        self.assertIn("cell", s_["schema"])
        # подресурс — как зовёт UI наброска
        ok_, _, o_ = server.api_dispatch_get("/editor/api/schema/object",
                                           None)
        self.assertTrue(ok_)
        self.assertTrue(any(f["key"] == "state" for f in o_["fields"]))
        ok_, _, o_ = server.api_dispatch_get("/editor/api/schema/чушь",
                                           None)
        self.assertFalse(ok_)
        self.assertIn("unit", o_["known"])
        # миры: временный экспортированный мир
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            (root_ / "4" / "maps").mkdir(parents=True)
            (root_ / "4" / "meta.json").write_text(json.dumps({
                "world": 4, "hero": {"name": "Эйнар"},
                "start_map": 45, "maps": {"45": {"units": 3}},
            }), encoding="utf-8")
            (root_ / "4" / "maps" / "45.json").write_text(json.dumps({
                "map": 45, "parties": [], "units": [{"index": 1}],
            }), encoding="utf-8")
            with mock.patch.object(server, "PROJECT_WORLDS", root_):
                ok_, _, m_ = server.api_worlds()
                self.assertTrue(ok_)
                # список теперь идёт по СЛОТАМ ГЕРОЕВ (пара «игра+мир»),
                # а не по папкам: канонный мир 4 ищем по паре, см.
                # test_hero_slot_is_a_pair_not_a_number
                own = next(z_ for z_ in m_["worlds"]
                            if z_["game"] == "canon" and z_["world"] == 4)
                self.assertEqual(own["hero"], "Эйнар")
                self.assertTrue(own["editable"])
                ok_, _, meta = server.api_dispatch_get(
                    "/editor/api/worlds/4", None)
                self.assertEqual(meta["start_map"], 45)
                ok_, _, map_rec = server.api_dispatch_get(
                    "/editor/api/worlds/4/maps/45", None)
                self.assertEqual(len(map_rec["units"]), 1)
                self.assertFalse(server.api_world_meta(9)[0])


class StoryTest(unittest.TestCase):
    """E3: .QST ↔ JSON — конвертер, валидатор, ворота компилятора."""

    @staticmethod
    def _посылка() -> pathlib.Path:
        from konung2.story import QUESTS_DIR
        return QUESTS_DIR

    def test_raw_roundtrip_all_files(self) -> None:
        """render(parse(файл)) байт-в-байт для всех 156 исходников."""
        from konung2.story import load_sources, render_file
        if not self._посылка().is_dir():
            self.skipTest("посылка k2_tools не на месте")
        files = load_sources()
        self.assertEqual(len(files), 156)
        for name_, document in files.items():
            self.assertEqual(
                render_file(document).encode("cp866"),
                (self._посылка() / name_).read_bytes(), name_)

    def test_canonical_render_compiles_byte_exact(self) -> None:
        """Арбитраж M_QUEST: перерендер БЕЗ raw собирается в QUESTS.RES,
        побайтово равный эталону, — парсер ничего не теряет."""
        import shutil
        import subprocess
        from konung2.story import load_sources, render_file
        if not (self._посылка().parent / "RESOURCE"
                / "M_QUEST.exe").is_file():
            self.skipTest("посылка k2_tools не на месте")

        def сбросить(node):
            if isinstance(node, dict):
                if node.get("kind") == "script" or node.get("type") in (
                        "switch", "section"):
                    node.pop("raw", None)
                    node["dirty"] = True
                for z_ in node.values():
                    сбросить(z_)
            elif isinstance(node, list):
                for z_ in node:
                    сбросить(z_)

        files = load_sources()
        for document in files.values():
            сбросить(document)
        with tempfile.TemporaryDirectory() as tmp_dir:
            sandbox = pathlib.Path(tmp_dir) / "KONUNG2"
            shutil.copytree(self._посылка().parent, sandbox)
            for name_, document in files.items():
                (sandbox / "QUESTS" / name_).write_bytes(
                    render_file(document).encode("cp866"))
            (sandbox / "QUESTS" / "QUESTS.RES").unlink()
            done_flag = subprocess.run(
                [str(sandbox / "RESOURCE" / "M_QUEST.exe"), "konung2.qst",
                 "-d_DEFINES.QST", "-l"],
                cwd=str(sandbox / "QUESTS"), capture_output=True,
                text=True, encoding="cp866", errors="replace",
                stdin=subprocess.DEVNULL, timeout=120)
            self.assertEqual(done_flag.returncode, 0, done_flag.stdout[-300:])
            ours = (sandbox / "QUESTS" / "QUESTS.RES").read_bytes()
        self.assertEqual(ours, (self._посылка() / "QUESTS.RES")
                         .read_bytes())

    def test_validator_semantics(self) -> None:
        from konung2.story import parse_file, validate_dialog, \
            validate_story
        text_ = (
            "{SCRIPT=Тест\n"
            " {SWITCH=*\n"
            "  CASE=(<ЗНАЕТ>) ЕСТЬ\n"
            "  CASE=() НЕТУ\n"
            " }\n"
            " {SECTION=ЕСТЬ\n"
            "  {REPLY\n   {TEXT\nПривет.\n   }\n  }\n"
            "  {ANSWER DO=<+ВИДЕЛИСЬ> GOTO=ПРОПАЩАЯ\n"
            "   {TEXT\nПока.\n   }\n  }\n"
            " }\n"
            " {SECTION=НЕТУ\n"
            "  {REPLY\n   {TEXT\nКто ты?\n   }\n  }\n"
            "  {ANSWER GOTO=END_OF_DIALOG\n   {TEXT\nНикто.\n   }\n  }\n"
            " }\n"
            " {SECTION=СИРОТА\n"
            "  {REPLY\n   {TEXT\nМеня не видно.\n   }\n  }\n"
            " }\n"
            " {SECTION=@ОБЩИЙ_ВХОД\n"
            "  {REPLY\n   {TEXT\nЯ глобальный.\n   }\n  }\n"
            "  {ANSWER GOTO=END_OF_DIALOG\n   {TEXT\nУгу.\n   }\n  }\n"
            " }\n"
            "}\n")
        document = parse_file(text_, "TEST.QST")
        скрипт = document["items"][0]
        outcome = validate_dialog(скрипт)
        errs = " | ".join(outcome["errors"])
        troubles = " | ".join(outcome["warnings"])
        self.assertIn("ПРОПАЩАЯ", errs)          # битый GOTO
        self.assertIn("СИРОТА» без единого ответа", errs)
        self.assertIn("СИРОТА» недостижима", troubles)
        # @-вход — дополнительный старт, недостижимым не зовётся
        self.assertNotIn("@ОБЩИЙ_ВХОД", troubles)
        summary = validate_story({"TEST.QST": document})
        # токены: ЗНАЕТ и ВИДЕЛИСЬ нигде не объявлены
        self.assertEqual(summary["unknown_tokens"],
                         ["ВИДЕЛИСЬ", "ЗНАЕТ"])

    def test_dialog_save_rejects_broken_graph(self) -> None:
        """Битый GOTO не проходит ворота — проверяем на СВОЁМ файле.

        Канонные .QST только для чтения, поэтому валидатор ловим на
        своём диалоге: такие и заводят под свои карты.
        """
        from knyaz2.web import server
        with tempfile.TemporaryDirectory() as tmp_dir:
            сюжет = pathlib.Path(tmp_dir)
            (сюжет / "qst").mkdir()
            (сюжет / "qst" / "MOYA.QST").write_text(
                "{SCRIPT=Мой_селянин\n"
                " {SECTION=*\n"
                "  {REPLY\n   {TEXT\nЗдравствуй.\n   }\n  }\n"
                "  {ANSWER\n   {TEXT\nИ тебе.\n   }\n"
                "   GOTO=END_OF_DIALOG\n  }\n }\n}\n",
                encoding="cp866")
            with mock.patch.object(server, "PROJECT_STORY", сюжет):
                ok_, reply, _ = server.api_story_dialog_save(
                    "Мой_селянин",
                    {"nodes": [{"type": "section", "name": "*",
                                "reply": {"texts": [{"text": "Хр."}]},
                                "answers": [
                                    {"target": "НЕТ_ТАКОЙ",
                                     "texts": [{"text": "Ага."}]}]}]})
        self.assertFalse(ok_)
        self.assertIn("НЕТ_ТАКОЙ", reply)


class WorldMutationTest(unittest.TestCase):
    """E2: правка мира через API — в исходник, с undo-охватом."""

    def test_unit_and_party_patch_with_undo(self) -> None:
        from knyaz2.web import server
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            (root_ / "2" / "maps").mkdir(parents=True)
            file = root_ / "2" / "maps" / "23.json"
            file.write_text(json.dumps({
                "map": 23,
                "parties": [{"slot": 55, "side": 55, "count": 9,
                             "zone": {"row_from": 1, "row_to": 2,
                                      "col_from": 3, "col_to": 4,
                                      "flags": 0x92},
                             "war_flags": 64, "raw": "00" * 256}],
                "units": [{"index": 215, "name": "Асбад", "level": 3,
                           "skills": {"Знахарство": 5},
                           "raw": "00" * 256}],
            }), encoding="utf-8")
            было = file.read_text(encoding="utf-8")
            with mock.patch.object(server, "PROJECT_WORLDS", root_), \
                    mock.patch.object(server, "_UNDO", []), \
                    mock.patch.object(server, "_REDO", []):
                path_str = "/editor/api/worlds/2/maps/23/units"
                snapshot = server._journal_snapshot(path_str)
                self.assertIsNotNone(snapshot)      # журнал знает миры
                ok_, _, o_ = server.api_dispatch_post(
                    path_str, {"index": 215,
                           "patch": {"level": 9,
                                     "skills": {"Знахарство": 40}}},
                    None)
                self.assertTrue(ok_)
                server._journal_push(snapshot)
                document = json.loads(file.read_text(encoding="utf-8"))
                unit = document["units"][0]
                self.assertEqual(unit["level"], 9)
                # вложенный словарь мержится, не заменяется
                self.assertEqual(unit["skills"]["Знахарство"], 40)
                self.assertEqual(unit["name"], "Асбад")
                # отряд: зона мержится
                ok_, _, o_ = server.api_dispatch_post(
                    "/editor/api/worlds/2/maps/23/parties",
                    {"slot": 55, "patch": {"zone": {"col_from": 7},
                                           "war_flags": 65}}, None)
                self.assertTrue(ok_)
                document = json.loads(file.read_text(encoding="utf-8"))
                band = document["parties"][0]
                self.assertEqual(band["zone"]["col_from"], 7)
                self.assertEqual(band["zone"]["row_to"], 2)
                self.assertEqual(band["war_flags"], 65)
                # undo возвращает исходник целиком
                ok_, _, u = server.api_undo()
                self.assertTrue(ok_)
                self.assertEqual(file.read_text(encoding="utf-8"), было)
                # чужой юнит/отряд — отказ
                self.assertFalse(server.api_world_unit_patch(
                    2, 23, {"index": 999, "patch": {}})[0])
                self.assertFalse(server.api_world_party_patch(
                    2, 23, {"slot": 1, "patch": {}})[0])


class WorldsBuildTest(unittest.TestCase):
    """Наш M_UNIT: сборка GAME.N из исходников (worlds.build_world)."""

    def test_untouched_export_rebuilds_byte_exact(self) -> None:
        """Нетронутый экспорт собирается байт-в-байт: raw — основа,
        поля — поверх; ряды зоны u16, СТОЛБЦЫ — байты (соседние 0x15/
        0x17 заняты roam — u16-запись затирала их, поймано этим тестом
        на 219 байтах)."""
        import hashlib
        from konung2.worlds import build_world, export_world
        from konung2.paths import game_file
        with tempfile.TemporaryDirectory() as tmp_dir:
            export_world(0, tmp_dir)
            file = build_world(0, tmp_dir, pathlib.Path(tmp_dir) / "build")
            ours = hashlib.sha256(file.read_bytes()).hexdigest()
        ориг = hashlib.sha256(
            open(game_file("GAME.0"), "rb").read()).hexdigest()
        self.assertEqual(ours, ориг)

    def test_field_patch_reaches_engine_reader(self) -> None:
        """Правка поля в JSON доезжает до канонного читателя."""
        from konung2.worlds import build_world, export_world
        from konung2.gamefile import unit_stats, T_UNITS
        with tempfile.TemporaryDirectory() as tmp_dir:
            export_world(0, tmp_dir)
            файл33 = pathlib.Path(tmp_dir) / "0" / "maps" / "33.json"
            document = json.loads(файл33.read_text(encoding="utf-8"))
            unit = document["units"][0]
            num_ = unit["index"]
            unit["level"] = 42
            unit["money"] = 7777
            unit["skills"]["Знахарство"] = 33
            unit["characteristics"]["Сила"] = 19
            document["parties"][1]["zone"]["col_from"] = 11
            файл33.write_text(json.dumps(document, ensure_ascii=False),
                              encoding="utf-8")
            собран = build_world(0, tmp_dir, pathlib.Path(tmp_dir) / "build")
            data_ = собран.read_bytes()
            статы = unit_stats(data_, num_)
            self.assertEqual(статы["level"], 42)
            self.assertEqual(статы["money"], 7777)
            self.assertEqual(статы["skills"]["Знахарство"], 33)
            self.assertEqual(статы["characteristics"]["Сила"], 19)
            # зона отряда: столбец лёг байтом, соседний roam цел
            from konung2.gamefile import spawn_zone, _game_bytes
            _, layout = _game_bytes(0)
            start, _, stride = layout["parties"]
            slot = document["parties"][1]["slot"]
            record = data_[start + slot * stride:][:stride]
            self.assertEqual(spawn_zone(record)["col_from"], 11)
            эталон, _ = _game_bytes(0)
            эталонная = эталон[start + slot * stride:][:stride]
            self.assertEqual(record[0x15], эталонная[0x15])

    def test_built_world_is_read_first(self) -> None:
        """_game_bytes берёт собранный мир приоритетно (одна точка)."""
        import konung2.gamefile as gf
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            dest = root_ / "project" / "worlds" / "build"
            dest.mkdir(parents=True)
            подлинник, layout = gf._game_bytes(5)
            подмена = bytearray(подлинник)
            подмена[0] = (подмена[0] + 1) & 0xFF
            (dest / "GAME.5").write_bytes(bytes(подмена))
            # перехват смотрит рядом с konung2/: подменим корень пакета
            with mock.patch.object(gf, "__file__",
                                   str(root_ / "konung2"
                                       / "gamefile.py")):
                data_, _ = gf._game_bytes(5)
            self.assertEqual(data_[0], подмена[0])
            self.assertNotEqual(data_[0], подлинник[0])


class WorldsExportTest(unittest.TestCase):
    """Конвертер GAME.N -> JSON (konung2/worlds.py) против канона."""

    def test_start_maps_match_canon(self) -> None:
        # выбор персонажа = выбор мира: 0->33, 1->19, 2->23, 3->37,
        # 4->45, 5->1 (VA 0x4387CC, отряд №0 называет карту)
        import struct
        from konung2.gamefile import _game_bytes
        канон = {0: 33, 1: 19, 2: 23, 3: 37, 4: 45, 5: 1}
        for world_, map_rec in канон.items():
            data_, layout = _game_bytes(world_)
            start = layout["parties"][0]
            self.assertEqual(
                struct.unpack_from("<H", data_, start + 0x08)[0], map_rec)

    def test_export_map_is_complete(self) -> None:
        from konung2.worlds import export_map, world_map_numbers
        maps = world_map_numbers(0)
        self.assertIn(33, maps)
        self.assertGreater(len(maps), 50)
        d_ = export_map(0, 33)
        self.assertEqual(len(d_["parties"]), 2)
        self.assertEqual(len(d_["units"]), 17)
        self.assertTrue(d_["village"])
        unit = d_["units"][0]
        # запись полная: снаряжение, навыки, зона, рабочие места
        for key_ in ("equipment", "skills", "spawn_zone", "workplaces",
                     "characteristics", "dialog", "direction"):
            self.assertIn(key_, unit)


class NewMapTest(unittest.TestCase):
    """Фаза 11: пустой проект карты, пригодный сборке и ядру."""

    def test_create_pack_and_model(self) -> None:
        from knyaz2.web import server
        from konung2.kn2 import KN2Map, MAP_SIZE, EMPTY_CELL
        from konung2.world.model import MapModel
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            with mock.patch.object(server, "PROJECT_MAPS", root_):
                ok_, path_str, reply = server.editor_map_create(60, "Новая Весь")
                self.assertTrue(ok_, path_str)
                self.assertEqual(reply["dir"], "60_novaya_ves")
                folder = root_ / "60_novaya_ves"
                for file in ("grid.txt", "layer1.png", "layer2.png",
                             "map.json", "scenario.json"):
                    self.assertTrue((folder / file).is_file(), file)
                # ручки соседних фаз видят карту сразу
                self.assertEqual(server.project_map_dir(60), folder)
                ok_, _, кл = server.editor_cell_save(60, 0, 0, {})
                self.assertTrue(ok_)
                self.assertTrue(кл["blocked"])   # чистый лист — глушь
                ok_, _, water = server.editor_water_save(60, {})
                #: пустая вода -> Lake: родной редактор при OR == 0 ставит
                #: кисть 0x80 (FUN_00419EC0), прежняя проверка закрепляла
                #: наш же баг «первый мазок на сухой карте льёт Stream»
                self.assertEqual((water["count"], water["stream"]), (0, False))
                # проект пакуется в честный .KN2 и читается ядром
                kn2 = KN2Map.pack(str(folder), 60)
                self.assertEqual(len(kn2.data), MAP_SIZE)
                self.assertEqual(kn2.cell(0, 0), (EMPTY_CELL, 0))
                self.assertEqual(kn2.used_cells(), 0)
                модель = MapModel.from_kn2(kn2, 60)
                self.assertEqual(len(модель.terrain.tiles), 0)
                self.assertEqual(len(модель.buildings), 0)
                self.assertEqual(len(модель.props), 0)
                # повтор и кривые номера — отказ
                self.assertFalse(server.editor_map_create(60, "Дубль")[0])
                self.assertFalse(server.editor_map_create(0, "Ноль")[0])
                self.assertFalse(server.editor_map_create(255, "Край")[0])


class ClientEditorTest(unittest.TestCase):
    """Сторожа браузерной панели."""

    def test_editor_module_contract(self) -> None:
        code = клиент('editor.js')
        self.assertIn('editor.kind === "prop" ? "/editor/prop" : "/editor/unit";', code)
        # щелчок переводится в мир каноничным путём, не своей математикой
        self.assertIn('screenToWorld(event.clientX, event.clientY)', code)
        self.assertIn('unitAt(point.x, point.y, true)', code)
        # F2 — сохранение, привет старому редактору
        self.assertIn('event.key === "F2"', code)
        self.assertIn('editor_units', code)   # замысел описан на месте

    def test_app_wires_editor(self) -> None:
        app = клиент('app.js')
        self.assertIn('editorAutostart();', app)
        self.assertIn('editorToggle, editorSave,', app)

    def test_pile_panel_contract(self) -> None:
        code = клиент('editor.js')
        self.assertIn('fetch(route', code)
        self.assertIn('"/editor/loot"', code)
        # кучи ловятся после юнитов, тайники видны редактору
        self.assertIn('lootNear(point.x, point.y, { hidden: true })', code)
        # items и details шлются целиком — они параллельны
        self.assertIn('editor.dirty.items = [...(pile.items ?? [])];', code)
        self.assertIn('export function editorNewPile()', code)

    def test_placement_contract(self) -> None:
        code = клиент('editor.js')
        # перенос: Ctrl+клик, клетка каноничным heroCellAt, якорь тем же
        # heroAnchor, что и спавн
        self.assertIn('event.ctrlKey && editor.kind === "unit"', code)
        self.assertIn('heroCellAt(point.x, point.y)', code)
        self.assertIn('heroAnchor(cell.row, cell.col)', code)
        # клон целой записью и удаление приговором removed
        self.assertIn('export function editorCloneUnit()', code)
        self.assertIn('markDirty("removed", true);', code)

    def test_prop_and_furniture_contract(self) -> None:
        code = клиент('editor.js')
        self.assertIn('function propAt(x, y)', code)
        self.assertIn('"/editor/prop"', code)
        # перенос сдвигает позицию и рамку вместе
        self.assertIn('prop.bounds.draw_x', code)
        self.assertIn('prop.bounds.sort_y', code)
        # сундук открывает свою кучу; реквизит пробуется последним
        self.assertIn('furnitureAt(point.x, point.y)', code)
        self.assertIn('export function editorCloneProp()', code)

    def test_tiles_mode_contract(self) -> None:
        code = клиент('editor.js')
        # клетка земли — шаг движка 0x74 на 0x20, сдвиг нечётных 0x3A
        self.assertIn('const GROUND_STEP_X = 0x74, GROUND_STEP_Y = 0x20, '
                      'GROUND_ODD = 0x3A;', code)
        self.assertIn('"/editor/tiles"', code)
        self.assertIn('"/editor/ground"', code)
        self.assertIn('export function editorTilesToggle', code)
        # ПКМ — ластик, страницы PgUp/PgDn — как в старом редакторе
        self.assertIn('function onContext(event)', code)
        self.assertIn('event.key === "PageUp"', code)

    def test_content_library_contract(self) -> None:
        code = клиент('editor.js')
        # тулбар открывает то, что раньше пряталось в консоли
        self.assertIn('"editor-tools"', code)
        for кнопка in ('"юнит+"', '"объект+"', '"куча+"', '"тайлы"',
                       '"вода"'):
            self.assertIn(кнопка, code)
        # каталог и бестиарий говорят со своими ручками
        self.assertIn('layerRequest("objects", { page: objectsView.page })',
                      code)
        self.assertIn('layerRequest("object", {', code)
        self.assertIn('layerRequest("bestiary", {})', code)
        self.assertIn('layerRequest("warband", {', code)
        # вставленное видно сразу: сцена рисует world.objects
        self.assertIn('world.objects.push(prop);', code)
        self.assertIn('world.objects.push(clone);', code)
        self.assertIn('function objectsResort()', code)
        # предпросмотр обязан догружать образы, которых на карте не
        # было (тайл кисти, слои объекта, листы твари) — иначе розовая
        # заглушка навсегда; и перепекать запечённый слой земли
        self.assertIn('async function ensureImages(paths)', code)
        self.assertIn('world.images.set(path, await loadImage(path));',
                      code)
        # применение слоя отрядов дошло до сборки
        билдер = (КОРЕНЬ / 'knyaz2' / 'content' / 'builder.py').read_text(
            encoding='utf-8')
        self.assertIn('editor_warbands_add', билдер)

    def test_design_editor_contract(self) -> None:
        """Редактор пользователя: editor.html — хост, editor_live.js —
        монтаж живого API в его вёрстку, editor_design_raw.html —
        нетронутая истина дизайна из Claude Design."""
        живость = клиент('editor_live.js')
        self.assertTrue((КОРЕНЬ / 'knyaz2' / 'web' / 'static'
                         / 'editor_design_raw.html').is_file())
        self.assertIn('editor_design_raw.html', живость)
        # компоненты дизайн-системы полифилятся (их бандл — на хостинге)
        self.assertIn('x-import', живость)
        self.assertIn('ActionButton', живость)
        # инлайн-стили нормализуются браузером — зоны ищутся только по
        # computed-стилю (урок первого запуска: #020617 -> rgb(2, 6, 23))
        self.assertIn('getComputedStyle', живость)
        self.assertIn('rgb(2, 6, 23)', живость)
        # уроки прототипа переехали: пакетные кисти и область
        self.assertIn('cells: batch', живость)
        self.assertIn('hostile', живость)
        хост = клиент('editor.html')
        self.assertIn('editor_live.js', хост)

    def test_editor_geometry_matches_pack(self) -> None:
        """Сетки редактора — те же, что у пака и клиента игры.

        Клетка 58x16, тайл земли 116x32: высота клетки ВДВОЕ меньше шага
        земли. Пока в холсте стояло 32, слой клеток (глушь, юниты, кучи,
        зоны отрядов) растягивался вдвое вниз относительно земли, а клик
        попадал в чужую строку. Числа берём из собранного пака, чтобы
        расхождение ловилось само.
        """
        живость = клиент('editor_live.js')
        self.assertIn('const CELL_W = 58, CELL_H = 16;', живость)
        self.assertIn('const TILE_W = 0x74, TILE_H = 0x20;', живость)
        # клетка по точке — ромбическая, как heroCellAt клиента
        self.assertIn('const bottom = (row + 1) * CELL_H;', живость)
        pack_ = (КОРЕНЬ / 'content_build' / 'maps' / '19' / 'map.json')
        if pack_.is_file():
            координаты = json.loads(pack_.read_text(encoding='utf-8'))[
                'coordinates']
            grid = координаты['navigation_grid']
            земля = координаты['ground_grid']
            self.assertEqual((grid['cell_width'], grid['cell_height']),
                             (58, 16))
            self.assertEqual((земля['step_x'], земля['step_y']), (116, 32))

    def test_design_organs_are_mounted(self) -> None:
        """Органы ЕГО макета оживлены, а не продублированы своими.

        Первый заход подставлял собственные кнопки рядом с нарисованными:
        пользователь жал нарисованные, и редактор выглядел мёртвым —
        «эти кнопки не нажимаются», «страницы не листаются».
        """
        живость = клиент('editor_live.js')
        for орган in ('function organOf(', 'function toggleOf(',
                      'function pager(', 'function liveField(',
                      'function pageLabel('):
            self.assertIn(орган, живость)
        # переключатели, на которые жаловался прогон
        for подпись in ('"Нижний", "Верхний", "Свет"', '"Бестиарий"',
                        '"draft-слой"', '"все", "кучи", "тайники"',
                        'ластик'):
            self.assertIn(подпись, живость)
        # «Декор» ведёт на экран объектов и пишет в другую таблицу
        self.assertIn('"Декор": "1b"', живость)
        self.assertIn('state.decorMode', живость)
        # клик считается ОДИН раз: обработчик на подписи и на рамке
        self.assertIn('stopPropagation', живость)
        # кнопки инспектора (клон/убрать) общие для объектов, юнитов, куч
        self.assertIn('function wakeInspector(', живость)
        for подпись in ('"Клон"', '"Дубль"', '"Дублировать"'):
            self.assertIn(подпись, живость)
        # видимость слоёв холста и фильтры списка карт
        self.assertIn('state.слои', живость)
        self.assertIn('"все", "с draft-правками", "не собраны"', живость)
        # «Перепроверить» — BUTTON, он обязан быть в выборке узлов
        self.assertIn('querySelectorAll("div,span,button")', живость)

    def test_maps_list_carries_flags(self) -> None:
        """Список карт несёт признаки для фильтров: draft и built.

        Без них фильтры «с draft-правками» и «не собраны» пришлось бы
        считать запросом на каждую из полутора сотен карт.
        """
        from knyaz2.web import server
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            проект = root_ / "maps"
            (проект / "63_proba").mkdir(parents=True)
            (проект / "63_proba" / "map.json").write_text(
                json.dumps({"name": "Проба"}), encoding="utf-8")
            (проект / "63_proba" / "scenario.json").write_text(
                json.dumps({"editor_units_add": [{"id": "unit_new_1"}]}),
                encoding="utf-8")
            (проект / "64_pusto").mkdir(parents=True)
            (проект / "64_pusto" / "map.json").write_text(
                json.dumps({"name": "Пусто"}), encoding="utf-8")
            pack_ = root_ / "pack"
            (pack_ / "maps" / "63").mkdir(parents=True)
            (pack_ / "maps" / "63" / "map.json").write_text("{}",
                                                          encoding="utf-8")
            with mock.patch.object(server, "PROJECT_MAPS", проект):
                ok_, _, reply = server.api_maps(pack_)
            self.assertTrue(ok_)
            by_number = {k_["map"]: k_ for k_ in reply["maps"]}
            self.assertTrue(by_number[63]["draft"])
            self.assertTrue(by_number[63]["built"])
            self.assertFalse(by_number[64]["draft"])
            self.assertFalse(by_number[64]["built"])

    def test_canvas_draws_real_map(self) -> None:
        """Холст показывает КАРТУ, а не отладочную мозаику.

        Земля рисовалась заглушкой `цветТайла` — hsl по номеру тайла, и
        карта выглядела цветной мешаниной без дорог и воды. Жителей пака
        (у Дворца их четверо) и выходы-двери не рисовали вовсе.
        """
        живость = клиент('editor_live.js')
        # настоящие текстуры земли из пака, оба слоя
        self.assertIn('/content/assets/ground/editor_tile_${index2}.png',
                      живость)
        self.assertIn('for (const layer of ["lower", "upper"])', живость)
        # только видимая часть: 12 800 клеток на кадр не нужны
        self.assertIn('const leftEl = Math.max(0, Math.floor(kindOf.x / TILE_W)',
                      живость)
        # жители пака и выходы карты
        self.assertIn('state.packUnits', живость)
        self.assertIn('state.packExits', живость)
        #: холст красит ВСЕ биты клетки цветами строк-кистей, а не только
        #: глушь с выходом: покраска «стрел» была невидимой, и человек
        #: делал вывод «на карте нет зон, кисти не работают»
        self.assertIn('if (lo & 0x4000) {', живость)
        self.assertIn('if (hi & 0x20) {', живость)

    def test_pack_units_carry_exits(self) -> None:
        """Ручка пака отдаёт выходы карты — их рисует холст."""
        from knyaz2.web import server
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            (root_ / "maps" / "1").mkdir(parents=True)
            (root_ / "maps" / "1" / "map.json").write_text(json.dumps({
                "units": [], "loot": [],
                "exits": [{"to_name": "Застава", "row1": 7, "row2": 11,
                           "col1": 30, "col2": 32},
                          {"to_name": "без клеток"}],
            }), encoding="utf-8")
            ok_, _, reply = server.api_pack_units(1, root_)
            self.assertTrue(ok_)
            self.assertEqual(reply["exits"], [{
                "to": "Застава", "rows": [7, 11], "cols": [30, 32],
                # пиксельная рамка двери и клетка входа
                "box": [None, None, None, None],
                "entry": {"row": None, "col": None}}])

    def test_canvas_looks_like_the_game(self) -> None:
        """Холст показывает то же, что видит игрок.

        Три расхождения с игрой, все замеченные на Дворце Повелителя:
        пол читался решёткой (тайл ужимали до шага сетки, а он крупнее и
        должен смыкаться), юниты были синими точками, дверь рисовалась по
        клеткам зоны — то есть не на стене.
        """
        живость = клиент('editor_live.js')
        # тайл рисуется в натуральную величину, а не в шаг сетки
        self.assertIn('const TILE_PX_W = 114, TILE_PX_H = 64;', живость)
        self.assertIn('const w2 = TILE_PX_W * K, it = TILE_PX_H * K;', живость)
        # юнит — кадром с листа, точка осталась запасным вариантом
        self.assertIn('brush.drawImage(img, layer.x, layer.y, layer.width,',
                      живость)
        self.assertIn('for (const layer of frm.layers || [frm])', живость)
        # дверь — по пиксельной рамке выхода
        self.assertIn('const [l2, it, p2, n2] = door.box || [];', живость)
        # зоны отряда: расстановка и обход патруля
        self.assertIn('zoneOf(band.roam,', живость)
        # ОТРЯД ИГРОКА — НЕ ЗОНА, А ТОЧКА ВХОДА: у него запись
        # перевёрнута (94..0 x 41..0), и прямоугольником она накрывала
        # пол-карты красным пунктиром. Он же не враг: бит 0x40 — признак
        # отряда игрока, а маска 0x4F записывала его во враждебные.
        self.assertIn('if (band.player) {', живость)
        self.assertIn('"сюда входит герой"', живость)
        self.assertIn('(band.war_flags & 0x0F) || band.on_player',
                      живость)

    def test_unit_frame_follows_client_rules(self) -> None:
        """Кадр юнита выбирается теми же правилами, что в actor.js.

        Люди: поза stand нужного направления даёт номер записи, набор
        тела по нему — вырез с листа; ключ набора «форма:масть» с
        откатами. Твари (бит 0x40) идут своим набором. Разойдётся с
        клиентом — юнит на холсте будет в чужой раскраске.
        """
        from knyaz2.web import server
        common = {
            "hero": {
                "sheets": [{"path": "assets/units/hero_0.png",
                            "width": 100, "height": 80}],
                "animations": {"peace": {"stand": [
                    [], [], [], [], [], [], [{"record": 7}], []]}},
                "body_layers": {"2:114": {"frames": {"7": {
                    "sheet": 0, "x": 5, "y": 6, "width": 30,
                    "height": 70, "offset_x": -15, "offset_y": -66}}}},
                "bodies": {},
            },
            "creatures": {
                "sheets": [{"path": "assets/units/beast_0.png",
                            "width": 200, "height": 120}],
                "sets": {"9": {"3": {"stand": [
                    [], [], [], [], [], [], [{"sheet": 0, "x": 1, "y": 2,
                                             "width": 40, "height": 50}],
                    []]}}},
            },
        }
        human_flag = server._unit_frame(common, 0, 2, 114, 6)
        self.assertEqual(human_flag["url"], "/content/assets/units/hero_0.png")
        self.assertEqual((human_flag["x"], human_flag["y"]), (5, 6))
        self.assertEqual(human_flag["offset_y"], -66)
        тварь = server._unit_frame(common, 0x40 | 9, 9, 3, 6)
        self.assertEqual(тварь["url"], "/content/assets/units/beast_0.png")
        self.assertEqual((тварь["width"], тварь["height"]), (40, 50))
        # неизвестная масть — кадра нет, холст рисует точку
        self.assertIsNone(server._unit_frame(common, 0, 99, 99, 6))

    def test_pack_units_follow_world(self) -> None:
        """Состав карты зависит от мира: выбор героя — это выбор мира.

        Во Дворце Повелителя в мирах 0…4 четверо, а в мире Анастасии
        шестеро: Мунд и ещё воин у правого края. Пока ручка отдавала
        только базовый список, редактор их не показывал — «не хватает
        двух охранников справа».
        """
        from knyaz2.web import server
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            (root_ / "maps" / "1").mkdir(parents=True)
            (root_ / "maps" / "1" / "map.json").write_text(json.dumps({
                "units": [{"id": "u1", "name": "Воин"}],
                "units_by_world": {"5": [{"id": "u1", "name": "Воин"},
                                         {"id": "u2", "name": "Мунд"}]},
                "warbands": [{"side": 1}],
                "warbands_by_world": {"5": [{"side": 1}, {"side": 2}]},
                "loot": [],
            }), encoding="utf-8")
            _, _, базовый = server.api_pack_units(1, root_)
            self.assertEqual(len(базовый["units"]), 1)
            _, _, пятый = server.api_pack_units(1, root_, world=5)
            self.assertEqual([u_["name"] for u_ in пятый["units"]],
                             ["Воин", "Мунд"])
            self.assertEqual(len(пятый["warbands"]), 2)
            # мира без своего списка нет — остаётся базовый
            _, _, третий = server.api_pack_units(1, root_, world=3)
            self.assertEqual(len(третий["units"]), 1)

    def test_unit_frame_carries_equipment_layers(self) -> None:
        """Кадр несёт СЛОИ: тело, доспех, шлем — как одет юнит в игре.

        Порядок слоёв берётся из сценария пака (rules.equipment_draw), а
        не выдумывается: за телом идёт доспех, затем шаги направления.
        """
        from knyaz2.web import server
        common = {
            "hero": {
                "sheets": [{"path": "assets/units/h.png",
                            "width": 100, "height": 80}],
                "animations": {"peace": {"stand": [[], [], [], [], [], [],
                                                   [{"record": 7}], []]}},
                "body_layers": {"2:114": {"frames": {"7": {
                    "sheet": 0, "x": 5, "y": 6, "width": 30, "height": 70,
                    "offset_x": -15, "offset_y": -66}}}},
                "equipment": {"9:3": {"frames": {"7": {
                    "sheet": 0, "x": 40, "y": 6, "width": 30,
                    "height": 70, "offset_x": -15, "offset_y": -66}}}},
                "rules": {"equipment_draw": {
                    "before": [{"step": "body"},
                               {"step": "layer", "slot": "body",
                                "offset": 0}],
                    "script": [[], [], [], [], [], [], [3], []],
                    "steps": {"3": [{"step": "layer", "slot": "head",
                                     "offset": 0}]},
                }},
                "bodies": {},
            },
            "creatures": {"sheets": [], "sets": {}},
        }
        goods = {"class:209": {"name": "Доспех", "layer": 9, "palette": 3,
                              "slot": "body"}}
        frame = server._unit_frame(common, 0, 2, 114, 6,
                                  {"body": "instance:209:game:0:151"}, goods)
        self.assertEqual(len(frame["layers"]), 2)       # тело + доспех
        self.assertEqual(frame["layers"][1]["x"], 40)
        # без снаряжения остаётся одно тело
        голый = server._unit_frame(common, 0, 2, 114, 6, {}, goods)
        self.assertEqual(len(голый["layers"]), 1)

    def test_equipment_is_editable(self) -> None:
        """Снаряжение правится: белый список сборки и каталог носимых."""
        from knyaz2.content import builder
        self.assertIn("equipment", builder.EDITOR_UNIT_DICTS)
        живость = клиент('editor_live.js')
        self.assertIn('const GEAR_SLOTS = [', живость)
        self.assertIn('"Переодеть"', живость)
        self.assertIn('patch: { equipment: setOf }', живость)

    def test_own_organs_are_inserted_once(self) -> None:
        """Свои органы вставляются ОДИН раз, а масштаб считается после.

        Экран показывается много раз, а карточка дизайна живёт между
        показами: вставки копились, и кнопка «сменить на мирный»
        размножилась на полэкрана, а селект мира — вчетверо. Ширину же
        мерили по рамке макета, хотя топбар и правая панель шире её, —
        на широком окне инспектор уезжал за край.
        """
        живость = клиент('editor_live.js')
        self.assertIn('function insertOwn(parentEl, nodeEl, key2',
                      живость)
        self.assertIn('data-lv="${key2}"', живость)
        # оба своих органа идут через неё
        self.assertIn('"сторона-отряда"', живость)
        self.assertIn('"выбор-мира"', живость)
        # мир выбирается по имени героя, а не по голому номеру, и стоит
        # В ТОПБАРЕ рядом с картой: он меняет ВСЮ карту (жителей, отряды,
        # клады), а не только вкладку существ
        self.assertIn('${m2.slot} · ${(m2.hero || "герой " + m2.slot)'
                      '.slice(0, 22)}', живость)
        self.assertIn('insertOwn(line, worldSelect, "выбор-мира", spacer || null)',
                      живость)
        # РЕЗИНОВАЯ ВЁРСТКА ВМЕСТО transform: scale. Макет выгружен с
        # жёсткими width:1600px/height:860px, и мы подгоняли его под окно
        # масштабированием всей карточки — костыль давал замыленный
        # текст, экранные точки не равные точкам вёрстки и пустые поля.
        # Теперь фиксированные размеры снимаются, а flex-колонки
        # растягиваются сами.
        self.assertIn('function fitCard(card)', живость)
        self.assertIn('card.style.transform = "";', живость)
        self.assertNotIn('карточка.style.transform = `scale(', живость)
        self.assertIn('frameBox.style.width = "100%";', живость)
        self.assertIn('wakeScreen(nm, card).then(() => {',
                      живость)
        # обрезку макета всё так же снимаем: колонки резали содержимое
        self.assertIn('el.style.overflow = "visible";', живость)
        # холст берёт своё место, а не фиксированные 1500x1320
        self.assertIn('function atSpot()', живость)
        self.assertIn('for (const sp of [stage, overCanvas]) {', живость)
        self.assertIn('sp.width = width2;', живость)
        # счётчики карт сидят ВНУТРИ подписей, и  в JS не знает
        # кириллицы — иначе «52 карты» так и остаются
        self.assertIn('/\d+\s+карты/.test(pt)', живость)
        # сцена прижата влево: центрирование ломало масштаб от угла
        хост = клиент('editor.html')
        self.assertIn('justify-content: flex-start', хост)

    def test_service_overlay_is_off_by_default(self) -> None:
        """Служебная разметка скрыта, пока ею не работают.

        Красные ромбы непроходимости закрывали пол-карты, и первым
        вопросом к холсту было «что это за красные пиксели?».
        """
        живость = клиент('editor_live.js')
        #: «крыши: true» между юнитами и проходимостью — слой снятия
        #: кровель, чтобы видеть людей в домах
        self.assertIn('юниты: true, крыши: true, проходимость: false', живость)
        # и рисуется формой клетки — ромбом, а не прямоугольником
        self.assertIn('const rhomb = (row, col) =>', живость)
        self.assertIn('brush.lineTo(x + (CELL_W / 2) * K, y);', живость)

    def test_decor_and_drag(self) -> None:
        """Декор рисуется, а выбранное возится удержанием.

        Декор (T_DYNAMIC) движок кладёт сразу после земли и до объектов:
        берега, кувшинки, камыши — ими прикрыта нарочно неполная базовая
        мозаика. Без него уличные карты выглядят дырявыми (на Чёрном
        Бору таких записей 611).
        """
        живость = клиент('editor_live.js')
        self.assertIn('state.packDecor', живость)
        self.assertIn('if (visible("декор"))', живость)
        # перенос удержанием: короткий клик остаётся кликом
        # перенос начинается от ДВИЖЕНИЯ, а не по таймеру — таймер
        # отменялся любым сдвигом мыши и потому жест не работал
        # вовсе (см. test_drag_starts_on_movement_not_on_a_timer)
        self.assertIn('if (cand && !dragging) {', живость)
        # у чтоПодТочкой появился второй довод — какие виды вещей ловит
        # этот экран (см. test_hit_test_uses_the_sprite_not_a_blind_box)
        self.assertIn('function hitAt(pt, kinds = null)', живость)
        self.assertIn('async function commitDrag(what, stage)', живость)
        # декор теперь не только рисуется, но и ловится, и возится
        self.assertIn('вид: "decor"', живость)
        self.assertIn('what.вид === "object" || what.вид === "decor"', живость)

    def test_object_move_handle(self) -> None:
        """Перенос объекта — отдельная ручка, а не добавление.

        Тело без `add` уходило в editor_object_add и вместо переноса
        плодило новую запись.
        """
        from knyaz2.web import server
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            folder = root_ / "maps" / "07_проба"
            folder.mkdir(parents=True)
            (folder / "map.json").write_text(json.dumps({
                "objects": {"records": [
                    {"slot": 0, "id": 5, "pixel_x": 10, "pixel_y": 20,
                     "raw": "00"},
                ]},
            }), encoding="utf-8")
            with mock.patch.object(server, "PROJECT_MAPS", root_ / "maps"):
                ok_, _, reply = server.editor_object_move(
                    7, {"slot": 0, "x": 111, "y": 222})
            self.assertTrue(ok_)
            self.assertEqual((reply["x"], reply["y"]), (111, 222))
            record = json.loads((folder / "map.json").read_text(
                encoding="utf-8"))["objects"]["records"][0]
            self.assertEqual((record["pixel_x"], record["pixel_y"]),
                             (111, 222))
            # сырые байты сняты: поля теперь важнее
            self.assertNotIn("raw", record)
            # чужой слот — отказ, а не молчаливое создание
            with mock.patch.object(server, "PROJECT_MAPS", root_ / "maps"):
                ок2, нота, _ = server.editor_object_move(7, {"slot": 99})
            self.assertFalse(ок2)
            self.assertIn("99", нота)

    def test_tile_editing_follows_original(self) -> None:
        """Тайлы правятся приёмами авторского редактора (EDIT.TXT).

        В оригинале «левый клик на нужный тайл ИЛИ левый клик с
        удержанием кнопки для заполнения области», правый — то же для
        удаления, INS — пипетка, DEL — убрать под курсором. У нас
        область набиралась двумя Shift-кликами по углам, чего в
        оригинале нет вовсе.
        """
        живость = клиент('editor_live.js')
        self.assertIn('drag: (pt, eraseAt) => groundBrush(', живость)
        self.assertIn('painting = ev.button === 2;', живость)
        self.assertIn('ev.key === "Insert"', живость)
        self.assertIn('взят тайл ${index2}', живость)
        # разбор оригинала записан рядом с кодом
        дока = (КОРЕНЬ / 'docs' / 'EDITOR_ORIGINAL_TILES.md')
        self.assertTrue(дока.is_file())
        text_ = дока.read_text(encoding='utf-8')
        for слово in ('TILE', 'SPRITE', 'OBJECT', 'UpOff', '255'):
            self.assertIn(слово, text_)

    def test_canvas_camera_is_live(self) -> None:
        """У холста есть камера: зум к точке под курсором и панорама.

        Карта 9280x4096 мировых точек ужималась в экран одним постоянным
        K=0.155 — разглядеть клетку было нельзя, и кистью попадали на
        глаз. Клик обязан считаться ЧЕРЕЗ камеру, иначе при увеличении
        правка уедет в чужую клетку.
        """
        живость = клиент('editor_live.js')
        self.assertIn('state.view = state.view || { zoom: 1, x: 0, y: 0 }',
                      живость)
        # зум колесом с удержанием точки под курсором
        self.assertIn('"wheel"', живость)
        self.assertIn('kindOf.x += before.x - after2.x;', живость)
        # панорама средней кнопкой или Alt+ЛКМ (правая занята кистью)
        self.assertIn('ev.button === 1 || (ev.button === 0 && ev.altKey)',
                      живость)
        # клик и рисование идут через камеру
        self.assertIn('/ (K * kindOf.zoom) + kindOf.x', живость)
        self.assertIn('brush.setTransform(kindOf.zoom, 0, 0, kindOf.zoom,',
                      живость)
        # камера не улетает за край карты и сбрасывается на новой карте
        # (там же теперь сбрасывается старт пробы — см. PlayFromHereTest)
        self.assertIn('function clampView()', живость)
        self.assertIn('if (state.map !== num) {', живость)
        self.assertIn('state.view = { zoom: 1, x: 0, y: 0, вписать: true };',
                      живость)
        # КАМЕРА ВПИСЫВАЕТСЯ В ЗАНЯТУЮ ЧАСТЬ. Поле 160x256 клеток, а
        # карта занимает от него угол: Дворец — меньше десятой доли, и
        # при зуме 1 человек видел крошку в море пустоты.
        self.assertIn('if (kindOf.вписать && state.terrain)', живость)
        self.assertIn('kindOf.zoom = Math.max(LIMIT.мин,', живость)

    def test_canon_maps_are_read_only(self) -> None:
        """Правки идут только в СВОИ карты; канон отвергается.

        project/maps — распакованные карты обеих игр, а не песочница:
        живые прогоны редактора дважды пачкали их незаметно (промахи
        кликов наставили в Морской лагерь чужих тварей и объекты).
        """
        from knyaz2.web import server
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            канон = root_ / "19_chernyy_bor"
            канон.mkdir()
            (канон / "map.json").write_text(
                json.dumps({"map_number": 19, "name": "Чёрный Бор"}),
                encoding="utf-8")
            own_one = root_ / "63_moya"
            own_one.mkdir()
            (own_one / "map.json").write_text(
                json.dumps({"map_number": 63, "name": "Моя",
                            "origin": {"editor": True}}), encoding="utf-8")
            with mock.patch.object(server, "PROJECT_MAPS", root_):
                self.assertFalse(server._editor_map(19))
                self.assertTrue(server._editor_map(63))
                refusal = server._canon_protected(19)
                self.assertIsNotNone(refusal)
                self.assertFalse(refusal[0])
                self.assertIn("канон игры", refusal[1])
                self.assertIsNone(server._canon_protected(63))
                # мутации канона отвергаются через диспетчер
                ok_, note, _ = server.api_dispatch_post(
                    "/editor/api/maps/19/cells", {"row": 1, "col": 1,
                                                  "blocked": True}, None)
                self.assertFalse(ok_)
                self.assertIn("канон", note)
                ok_, note, _ = server.api_dispatch_delete(
                    "/editor/api/maps/19/objects/5")
                self.assertFalse(ok_)
                self.assertIn("канон", note)

    def test_new_map_is_marked_as_ours(self) -> None:
        """Созданная редактором карта помечена origin.editor — по этой
        метке и отличается своё от канона."""
        from knyaz2.web import server
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            with mock.patch.object(server, "PROJECT_MAPS", root_):
                ok_, path_str, _ = server.editor_map_create(70, "Проба")
                self.assertTrue(ok_, path_str)
                document = json.loads(
                    (root_ / "70_proba" / "map.json").read_text(
                        encoding="utf-8"))
                self.assertTrue(document["origin"]["editor"])
                self.assertTrue(server._editor_map(70))

    def test_canon_story_is_read_only(self) -> None:
        """Авторский сюжет не правится: канонное дерево меняет разговор
        на ВСЕХ картах разом (деревья юнитов пекутся из общего
        QUESTS.RES), и один заход уже испортил диалог Лешего всей игре."""
        from knyaz2.web import server
        from konung2.story import QUESTS_DIR
        if not (QUESTS_DIR / "LESHIY.QST").is_file():
            self.skipTest("посылка k2_tools не на месте")
        ok_, note, _ = server.api_story_dialog_save(
            "Леший-колдун",
            {"nodes": [{"type": "section", "name": "*",
                        "reply": {"texts": [{"text": "проба"}]},
                        "answers": []}]})
        self.assertFalse(ok_)
        self.assertIn("авторский сюжет", note)

    def test_catalog_objects_carry_kind(self) -> None:
        """Каталог объектов называет вид: здания / реквизит / руины.

        Вид виден по слоям паспорта (постройка несёт отдельные стены и
        крышу) и по состоянию (ненулевое — фаза лестницы строительства),
        и решает это сервер: UI не должен гадать по номеру слота.
        """
        from knyaz2.web import server
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            passport = root_ / "assets" / "objects"
            passport.mkdir(parents=True)
            (passport / "index.json").write_text(json.dumps({
                "canon:10:1:0": {"path": "a.png", "width": 1, "height": 1,
                                 "layers": {"main": {}, "walls": {},
                                            "roof": {}}},
                "canon:11:1:0": {"path": "b.png", "width": 1, "height": 1,
                                 "layers": {"main": {}}},
                "canon:12:1:3": {"path": "c.png", "width": 1, "height": 1,
                                 "layers": {"main": {}}},
            }, ensure_ascii=False), encoding="utf-8")
            ok_, _, reply = server.editor_objects_page(0, root_)
            self.assertTrue(ok_)
            виды = {z_["slot"]: z_["kind"] for z_ in reply["items"]}
            self.assertEqual(виды, {10: "building", 11: "prop", 12: "ruin"})

    def test_new_map_contract(self) -> None:
        code = клиент('editor.js')
        self.assertIn('export async function editorNewMap(number, name)',
                      code)
        self.assertIn('"/editor/newmap"', code)

    def test_sprite_mode_contract(self) -> None:
        code = клиент('editor.js')
        # выбор по рамке кадра, перебор с конца, последний в цепочке клика
        self.assertIn('function overlayAt(x, y)', code)
        self.assertIn('"/editor/sprite"', code)
        # перенос двигает мир и проект вместе и перепекает слой земли
        self.assertIn('async function overlayMoveTo(overlay, x, y)', code)
        self.assertIn('groundInvalidate();', code)
        self.assertIn('export async function editorCloneOverlay()', code)
        # сброс кэша земли экспортирован самим слоем земли
        self.assertIn('export function groundInvalidate()',
                      клиент('ground.js'))

    def test_water_mode_contract(self) -> None:
        code = клиент('editor.js')
        # клетка воды — 256 px, как раскладывает world.underlay
        self.assertIn('const WATER_CELL = 256;', code)
        self.assertIn('"/editor/water"', code)
        self.assertIn('export function editorWaterToggle', code)
        # живой предпросмотр правит world.underlay, скролл — water.js
        self.assertIn('function waterPreview(row, col, value)', code)
        self.assertIn('water.horizontalScroll = stream.checked;', code)
        # ПКМ-ластик обслуживает и воду
        self.assertIn('if (editor.water) waterPaint(point, true);', code)

    def test_quest_phase_contract(self) -> None:
        code = клиент('editor.js')
        self.assertIn('"диалог №"', code)
        self.assertIn('markDirty("dialog_number", v | 0);', code)
        self.assertIn('export async function editorCompileQuests()', code)
        self.assertIn('"/editor/quests"', code)

    def test_cell_panel_contract(self) -> None:
        code = клиент('editor.js')
        self.assertIn('"/editor/cell"', code)
        self.assertIn('if (event.altKey) {', code)
        # живой предпросмотр: тумблер стены ядра и набор solid
        self.assertIn('world.editorCellWall?.(row, col, reply.blocked)', code)
        hero = клиент('hero.js')
        self.assertIn('world.editorCellWall = (row, col, on)', hero)
        # фаза 10: полная карта бит — подписи кнопок старого редактора
        for подпись in ('"глушь (NoWay)"', '"глушит стрелы (NoFly)"',
                        '"юнит поверх (Transparency)"',
                        '"интерьер (Inner)"', '"дневной свет (Light)"',
                        '"объект № (0-30)"'):
            self.assertIn(подпись, code)

    def test_server_writes_scenario_not_metadata(self) -> None:
        """Сборка читает слои из scenario.json — ручка обязана писать
        туда же, а не в map.json (метаданные): первая версия писала не
        туда, и правки не доезжали до пака."""
        сервер = (КОРЕНЬ / 'knyaz2' / 'web' / 'server.py').read_text(
            encoding='utf-8')
        self.assertIn('folder / "scenario.json"', сервер)
        билдер = (КОРЕНЬ / 'knyaz2' / 'content' / 'builder.py').read_text(
            encoding='utf-8')
        self.assertIn('source / "scenario.json"', билдер)

    def test_server_has_post_route(self) -> None:
        code = (КОРЕНЬ / 'knyaz2' / 'web' / 'server.py').read_text(
            encoding='utf-8')
        self.assertIn('def do_POST', code)
        self.assertIn('path_str.startswith("/editor/")', code)
        self.assertIn('EDITOR_LAYERS', code)
        self.assertIn('editor_units', code)
        self.assertIn('editor_loot_add', code)

    def test_selection_is_one_notion(self) -> None:
        """Что выбрано — одно понятие на весь редактор.

        Полей выбора было ТРИ: state.picked (объекты, юниты, декор),
        state.pickedPile (кучи) и state.pickedKind (вид — иначе объект
        от декора не отличить, поля у них одинаковые). Держать их в
        согласии приходилось руками в КАЖДОЙ точке входа: клик по
        холсту, клик по строке списка, удержание для переноса, Ins, Del,
        кнопки инспектора, стрелки. Где-нибудь да забывали: «Дубль» не
        видел кучу, выбранную в списке; Delete по ней уходил в
        `/objects/undefined`; панели показывали не то, что выбрано.

        Живой прогон после сведения: объект выбирается кликом по холсту
        (вид «object»), куча — строкой списка (вид «loot»), Delete по
        куче из списка её убирает, выбор снимается.
        """
        живость = клиент('editor_live.js')
        self.assertIn('function choose(kindOf, objectRec)', живость)
        self.assertIn('function selectedOf(...kinds)', живость)
        self.assertIn('function isChosen(objectRec)', живость)
        self.assertIn('function pickKind()', живость)
        # трёх прежних полей не осталось нигде, кроме объяснений.
        # ГРАНИЦА СЛОВА ОБЯЗАТЕЛЬНА: state.pickedCell — это выбранная
        # КЛЕТКА на экране проходимости, совсем другое понятие, и по
        # подстроке она ложно ловится как остаток старого выбора.
        code = "\n".join(s_ for s_ in живость.split("\n")
                        if not s_.strip().startswith("//"))
        for field in (r"state\.picked\b", r"state\.pickedPile\b",
                     r"state\.pickedKind\b"):
            self.assertIsNone(re.search(field, code),
                              f"осталось прежнее поле выбора: {field}")

    def test_one_drag_gesture_everywhere(self) -> None:
        """Один жест переноса на весь редактор — удержание ЛКМ.

        Их было три на трёх экранах: объекты возились удержанием, юнита
        переносил Ctrl+клик, а выбранную кучу — ПРОСТОЙ клик по холсту,
        то есть любой промах мимо неё увозил её куда попало, и отменить
        это можно было только Ctrl+Z. Человеку приходилось помнить, где
        он находится, чтобы знать, как двигать.
        """
        живость = клиент('editor_live.js')
        self.assertNotIn('ev?.ctrlKey && state.picked', живость)
        self.assertNotIn('выбранную кучу клик переносит', живость)
        # перенос начинается от ДВИЖЕНИЯ, а не по таймеру — таймер
        # отменялся любым сдвигом мыши и потому жест не работал
        # вовсе (см. test_drag_starts_on_movement_not_on_a_timer)
        self.assertIn('if (cand && !dragging) {', живость)
        # у кучи появилась подсветка на холсте — её не было вовсе
        self.assertIn('smallPile(pile.cell, "#e7c46a", pile.buried, '
                      'isChosen(pile));', живость)

    def test_party_unit_ranges_stay_contiguous(self) -> None:
        """ИНВАРИАНТ МИРА: отряд читается НЕПРЕРЫВНЫМ диапазоном.

        Юниты живут не в карте, а в отрядах: запись отряда называет
        первого юнита (+0x00) и сколько их (+0x1C), и сборщик сцены
        (VA 0x428240) читает ровно этот диапазон. Всё, что вне
        диапазонов, движок не читает НИКОГДА — на этом стоит вся
        возможность добавлять жителей, не двигая существующих.

        Сторожим на живых данных: порушится инвариант — и добавление
        жителя начнёт молча портить чужие отряды.
        """
        root_ = КОРЕНЬ / "project" / "worlds"
        if not root_.is_dir():
            self.skipTest("миры не экспортированы")
        band_count = 0
        for world_ in sorted(root_.iterdir()):
            if not (world_ / "maps").is_dir():
                continue
            for file in (world_ / "maps").glob("*.json"):
                document = json.loads(file.read_text(encoding="utf-8"))
                units_ = {int(u["index"]): u
                         for u in document.get("units") or []}
                for band in document.get("parties") or []:
                    first_one = band.get("first_unit")
                    how_many = int(band.get("count") or 0)
                    if first_one is None:
                        continue
                    band_count += 1
                    свои = [i_ for i_ in range(int(first_one),
                                             int(first_one) + how_many)
                            if i_ in units_]
                    self.assertEqual(
                        len(свои), how_many,
                        f"{world_.name}/{file.name}: у отряда "
                        f"{band.get('side')} диапазон {first_one}+{how_many} "
                        f"неполон")
                    side_num = int(band.get("slot", band.get("side", -1)))
                    for i_ in свои:
                        self.assertEqual(
                            int(units_[i_].get("side", -1)), side_num,
                            f"{world_.name}/{file.name}: юнит {i_} в диапазоне "
                            f"отряда {side_num}, а сторона у него другая")
        self.assertGreater(band_count, 900, "отрядов стало подозрительно мало")

    def test_world_unit_add_takes_free_slots_only(self) -> None:
        """Новый житель занимает СВОБОДНЫЕ слоты и не двигает чужих.

        Дописать бойца в существующий отряд можно, только если слот
        сразу за его хвостом свободен, — а он свободен лишь у 115
        отрядов из 946: таблица упакована вплотную. Переезжать же отряд
        нельзя: на индексы юнитов ссылается запись деревни
        (village.master/officials/people), а её сборка мира НЕ
        переписывает — старейшина и торговцы оторвались бы молча.

        Основной путь — новый отряд в свободном слоте. Слот отряда И
        ЕСТЬ его сторона (konung2/gamefile.py map_parties: «сторона
        юнита равна НОМЕРУ его отряда»), а свободен слот тогда, когда
        его счётчик равен нулю.

        Живой прогон на мире 0: житель встал в слот юнита 3 и отряд 103,
        сборка изменила в GAME.0 РОВНО две записи (отряд 103 и юнит 3,
        92 байта из 512 КБ), движок прочитал его на карте 23, а тварь
        получила имя от породы («Скелет»), как и обещает разбор.
        """
        from knyaz2.web import server
        живость = клиент('editor_live.js')
        сервер = (КОРЕНЬ / 'knyaz2' / 'web' / 'server.py').read_text(
            encoding='utf-8')
        self.assertTrue(hasattr(server, "editor_world_unit_add"))
        self.assertIn("def _world_occupancy(", сервер)
        # места работы чистим в самом клоне: они лежат в байтах записи
        self.assertIn("raw_bytes[WORKPLACES_AT] = 0xFF", сервер)
        # рост существующего отряда — только если хвост свободен
        self.assertIn("вплотную упёрся в соседа", сервер)
        # клиент умеет оба пути и не пишет в донорские миры
        self.assertIn('state.кудаЮнит === "world"', живость)
        self.assertIn("у этого героя нет исходников мира", живость)

    def test_resident_can_be_renamed(self) -> None:
        """Имя жителя правится после постановки, а не только при ней.

        Выбрать имя можно было ровно в момент постановки, и ошибиться
        было легко: первые люди на карте так и остались зваться
        «Человек · тело 6» — подписью строки каталога. Исправить это
        было нечем вовсе.

        ДВА АДРЕСА, И ЭТО НЕ КОСМЕТИКА. Житель, поставленный редактором,
        живёт в draft-слое карты, и имя там — обычная строка: пишем и
        строку, и номера. Житель МИРА живёт в project/worlds, и строки
        имени там НЕТ вовсе — только номера в таблицах exe (0xF0 и
        0xF1); ему пишем номера, а имя соберёт сама игра.

        Твари имя даёт порода (бит 0x40): движок берёт его из таблицы
        пород по самому байту породы. Переименовать Аспида нельзя —
        можно лишь переписать подпись в нашем паке, а это враньё про
        игру. Поэтому у тварей ряд не показываем и говорим почему.

        Живой прогон: в draft-слое «Житель» стал «Ратибором Сиротой»
        (name_id 35, nick_id 5); житель мира с индексом 9 после сборки
        прочитан движком как «Ратибор Сирота», канон возвращён.
        """
        живость = клиент('editor_live.js')
        self.assertIn("async function unitNameRow(", живость)
        # два адреса: draft-слой карты и исходники мира
        self.assertIn("patch: { name: assembled, name_id: nameNo, "
                      "nick_id: nickNo }", живость)
        self.assertIn("index: worldIndex, patch: { name_id: nameNo, "
                      "nick_id: nickNo }", живость)
        # у твари имя даёт порода — ряд не показываем
        self.assertIn("имя твари даёт порода", живость)
        # инспектор открывается и у черновых строк списка
        self.assertIn("unitInspector(u2);", живость)

    def test_name_numbers_come_from_the_world_source(self) -> None:
        """Номера имени берём из исходников мира, а не из пака.

        В паке их нет: сборка кладёт собранную строку `name`, а номера
        (0xF0 и 0xF1) остаются в исходниках. Редактору нужны именно они
        — переименование пишет номер, строки имени в GAME.<мир> не
        существует.

        Поля `name_id`/`nick_id` появились в экспорте позже самих файлов
        мира, поэтому в старых записях они пусты, а байты на месте:
        читаем из `raw`, а не гоним экспорт заново.

        Живой прогон на карте 23: Хрофт — 120, Эгиль Деревянный зуб —
        121 с прозвищем 9.
        """
        from knyaz2.web import server
        сервер = (КОРЕНЬ / 'knyaz2' / 'web' / 'server.py').read_text(
            encoding='utf-8')
        self.assertTrue(hasattr(server, "_name_numbers"))
        self.assertIn("raw_bytes[0xF0], raw_bytes[0xF1]", сервер)

        okay, _, data_ = server.api_pack_units(23, world=0)
        if not okay:
            self.skipTest("map_rec 23 не собрана")
        по_имени = {u_["name"]: u_ for u_ in data_["units"]}
        хрофт = по_имени.get("Хрофт")
        if хрофт is None:
            self.skipTest("на карте 23 missing Хрофта")
        self.assertEqual(хрофт["name_id"], 120)

    def test_editor_sides_do_not_run_out_silently(self) -> None:
        """Полоса сторон кончилась на первой же живой карте.

        Отряд заводится вместе с первым бойцом, а при удалении бойцов
        остаётся — каждая проба съедала сторону навсегда. На карте 63
        так набралось десять отрядов, два из них пустые, и постановка
        встала с «сторона 200 вне 1-199»: из этого не следовало ничего.

        Полоса расширена 190…199 → 185…199, и это ЗАМЕРЕНО, а не
        выбрано: сторона индексирует таблицу отрядов МИРА (общую, не
        покарточную), и по всем 141 карте пака игра занимает 166 сторон
        и ни одной в 185…199 — 190 и 191 там наши же черновые.

        Пустой отряд переиспользуется ТОЛЬКО когда свободных не
        осталось: иначе второй подряд заводимый отряд забирал бы первый
        — тот ведь ещё без бойцов, они приходят следующим запросом.
        """
        сервер = (КОРЕНЬ / 'knyaz2' / 'web' / 'server.py').read_text(
            encoding='utf-8')
        self.assertIn("side_num = next((s_ for s_ in range(185, 200)", сервер)
        self.assertIn("ПОЛОСА КОНЧИЛАСЬ — ЗАБИРАЕМ ПУСТОЙ ОТРЯД", сервер)
        #: отказ обязан говорить, что делать
        #: в исходнике строка разбита переносами — ищем непрерывный кусок
        self.assertIn("ненужный отряд на вкладке «Отряды»", сервер)
        self.assertNotIn("side_num = 190", сервер)

    def test_breed_key_is_a_pair_for_humans(self) -> None:
        """Порода перестала быть ключом, как только в каталог вошли люди.

        У твари порода уникальна: 0x42 — это Аспид и только он. А
        человек — это ВОСЕМЬ разных тел с одной породой 0 (чётные
        мужские, нечётные женские, сложение разное). Все поиски вида
        `find(п => п.breed === юнит.breed)` стали давать ПЕРВОЕ тело.

        Наружу это торчало двумя странностями, и выглядели они как
        разные беды: выбираешь одно тело — подсвечиваются все восемь
        строк (подсветка сравнивала породы), а поставленный житель
        рисуется чужим телом и с чужими числами (кадр и образец искались
        по породе). Запись при этом ВЕРНА — проверено: тела 5 и 2
        сохранились как 5 и 2; врала только картинка.

        Живой прогон на карте 63: после правки подсвечивается ровно одна
        строка из восьми. На той же карте лежат три жителя пользователя
        с телами 6, 1 и 1 — ровно те, что рисовались нулевым телом.
        """
        живость = клиент('editor_live.js')
        self.assertIn("function breedKey(", живость)
        self.assertIn("function breedOfUnit(", живость)
        #: ни одного поиска по одной лишь породе не осталось
        self.assertNotIn("p_.breed === unit.breed", живость)
        self.assertNotIn("state.place?.breed === порода.breed", живость)
        #: тварь ключуется породой, человек — парой «порода и тело»
        self.assertRegex(живость, r'\(\w+\ \&\ 0x40\)\ \?\ `\$\{\w+\}`\ :\ ')
        # и все места, где раньше искали по породе, ходят через помощник:
        # три вызова плюс само определение функции
        #: инвариант — НЕ число вызовов (оно растёт с каждым новым
        #: местом), а отсутствие поиска по одной породе: у восьми тел
        #: человека breed один и тот же, и такой поиск всегда отдаёт
        #: первое тело
        self.assertNotIn("п.breed === юнит.breed", живость)
        self.assertGreaterEqual(живость.count("breedOfUnit(unitRec)"), 4)

    def test_humans_are_in_the_catalog(self) -> None:
        """«Добавить НПС» было невозможно: людей не было в каталоге.

        Бит 0x40 у породы означает «имя берётся из таблицы пород»
        (konung2/gamefile.py), то есть это ТВАРЬ. Бестиарий отбирал
        только такие породы и выбрасывал всех людей: собственный подсчёт
        по паку — 532 юнита шести пород (0x00 обычный человек, 444
        записи; 0x01…0x05 — породы именных персонажей) против 856
        тварей. В списке оставались 23 строки, и человека взять было
        неоткуда.

        Причина отбора была не в замысле, а в превью: у твари кадр
        берётся прямо с листа, а человек рисуется послойно из тела и
        надетого. Собирать такой кадр есть чем — _unit_frame делает это
        для жителей пака.

        Ключ у людей — ПАРА «порода и тело»: тела 0…7 это разные люди
        (чётные мужские, нечётные женские). Масти берём из живых записей
        игры, а не из creatures.sets: та таблица про тварей, и превью
        выходило пустым.

        Породы 0x01…0x05 сознательно не предлагаем: чем они отличаются
        от обычного человека в правилах — не разобрано, и ставить их
        наугад значит раздавать неизвестные свойства.

        Живой прогон: в каталоге 31 строка — 8 людей впереди, 23 твари;
        у всех восьми превью со слоями; на карте 63 встал «Боян Косой»
        (порода 0, тело 0, name_id 4), после чего убран.
        """
        from knyaz2.web import server
        сервер = (КОРЕНЬ / 'knyaz2' / 'web' / 'server.py').read_text(
            encoding='utf-8')
        живость = клиент('editor_live.js')
        self.assertIn("human_flag = breed_id == 0", сервер)
        self.assertIn('record.get("human")', сервер)
        # превью человека собирается послойно, а не ищется на листе —
        # и НА КАЖДУЮ МАСТЬ: одна первая масть навязывала цвет и каталогу,
        # и уже поставленному жителю
        self.assertIn('shot = _unit_frame(common, record["breed"]', сервер)
        self.assertIn('record["previews"] = shots', сервер)
        self.assertIn('record["preview"] = shots[0]["frame"]', сервер)
        # клиент подписывает человека иначе: «breed 0x0» ему ничего не говорит
        self.assertIn("breedRec.human", живость)
        self.assertIn("как «${breedRec.looks_like", живость)
        # имя человека выбирается и в draft-слое, иначе он «Человек · тело 0»
        self.assertIn('name: chosenName || (p2.human ? "Житель" : p2.name)',
                      живость)

        okay, _, data_ = server.editor_bestiary()
        if not okay:
            self.skipTest("pack не собран")
        люди = [z_ for z_ in data_["breeds"] if z_.get("human")]
        self.assertEqual(len(люди), 8, "должно быть восемь тел человека")
        self.assertEqual([z_["body"] for z_ in люди], list(range(8)))
        for z_ in люди:
            self.assertTrue(z_.get("preview"), f"{z_['name']} без превью")
            self.assertTrue(z_.get("palettes"), f"{z_['name']} без мастей")
            #: КАДР НА КАЖДУЮ МАСТЬ, И У МАСТИ СВОЯ ИГРА. Ставилась и
            #: рисовалась всегда первая масть, поэтому житель выходил в
            #: цвете, которого никто не выбирал; а народ пустыни (тела 6
            #: и 7) существует ТОЛЬКО во второй игре — канонными слоями
            #: он рисовался цветным шумом.
            self.assertEqual(len(z_["previews"]), len(z_["palettes"]))
            for shot in z_["previews"]:
                self.assertIn(shot["game"], ("canon", "legend"))
                self.assertTrue(shot["frame"].get("layers"))
        desert = [z_ for z_ in люди if z_["body"] in (6, 7)]
        self.assertTrue(desert, "народ пустыни пропал из каталога")
        for z_ in desert:
            self.assertTrue(all(shot["game"] == "legend"
                                for shot in z_["previews"]),
                            "у народа пустыни канонных мастей быть не может")
        # люди идут первыми: искать их в хвосте из тридцати строк неверно
        self.assertTrue(data_["breeds"][0].get("human"))
        # породы именных персонажей не предлагаем
        self.assertFalse([z_ for z_ in data_["breeds"]
                          if 1 <= z_["breed"] <= 5])

    def test_screen_shows_no_invented_numbers(self) -> None:
        """Числа на экране должны быть с карты, а не из макета.

        Правая карточка юнита до любого выбора показывала «Юнит ·
        unit_new_2 · Скелет 0x4c · отряд 2 разбойники · сила 9 ловк 7
        вынс 8…» — выдумку дизайнера, к открытой карте отношения не
        имеющую. Человек видит заполненную карточку и заключает, что
        кто-то выбран и статы показываются; отсюда и «не видно статов у
        нпс» — видно, только чужие и ненастоящие. То же с числами
        вкладок «23 породы» и «Жители пака · 46»: они стояли на КАЖДОЙ
        карте, включая пустую.

        И третье: поставленного жителя не было в списке — он читал
        только пак, то есть собранных. Поставил, посмотрел, пусто —
        вывод «клик не сработал».

        Живой прогон на карте 63: карточка «Юнит · не выбран», вкладки
        «31 вид» и «Жители пака · 2 (+5)», в списке пять черновых с
        подписью «в паке будет после Build».
        """
        живость = клиент('editor_live.js')
        self.assertIn('unitTitle.textContent = "Юнит · не выбран"',
                      живость)
        self.assertIn("refreshUnitPanel(selectedOf(\"unit\", \"packUnit\"))",
                      живость)
        self.assertIn("в паке будет после Build", живость)
        self.assertIn("const breedTotal = (state.bestiary?.breeds || [])",
                      живость)
        #: «31 видов» читается как машинный вывод и подрывает доверие
        self.assertIn("function plural(", живость)

    def test_numbers_of_units_and_items_reach_the_editor(self) -> None:
        """Числа лежали в паке, а наружу не шли — и панель печатала «?».

        Жалоба была двойная: «не вижу ни иконки, ни статов предмета,
        только название» и «не видно статов у нпс». Обе одной формы: в
        паке у юнита лежат characteristics, stats, skills, деньги,
        скорость и сумка, а у вещи — сила, прочность, цена, вес,
        дальность, требование и значок. Ручки отдавали четырнадцать
        полей юнита без чисел и семь полей вещи без них же, поэтому
        `юнит.characteristics?.[ключ]` честно давал undefined.

        Путь значка тоже был нерабочим: пак хранит «assets/icons/87.png»,
        а сервер отдаёт паковые файлы под /content/ — браузер получал бы
        404. Отдаём готовый к показу путь, как давно делает каталог
        объектов.

        Живой прогон: «Богатырский меч» — удар 380, прочность 120, цена
        5000, вес 700, нужна Сила 95, значок отдаётся (200, 1761 байт);
        у жителя карты 23 характеристики шести видов, умения и уровень.
        """
        from knyaz2.web import server
        сервер = (КОРЕНЬ / 'knyaz2' / 'web' / 'server.py').read_text(
            encoding='utf-8')
        живость = клиент('editor_live.js')
        # числа юнита уходят наружу
        for field in ('"characteristics": u.get("characteristics")',
                     '"stats": u.get("stats")', '"skills": u.get("skills")',
                     '"money": u.get("money")'):
            self.assertIn(field, сервер)
        # числа вещи и годный путь значка
        for field in ('"power": thing.get("power")',
                     '"price": thing.get("price")',
                     '"weight": thing.get("weight")',
                     '"requires": thing.get("requires")'):
            self.assertIn(field, сервер)
        self.assertIn('"/content/" + icon["path"]', сервер)
        # клиент их показывает
        self.assertIn("function unitNumbersBlock(", живость)
        self.assertIn("function goodNumbers(", живость)
        #: power — «урон у оружия, ЗАЩИТА у брони и щита» (konung2/items.py),
        #: и подписывать его везде «удар» значит врать про кольчугу
        self.assertIn("function powerLabel(", живость)
        ядро = (КОРЕНЬ / 'konung2' / 'items.py').read_text(encoding='utf-8')
        self.assertIn("защита у брони", ядро)

        # и то же на живых данных, если игра под рукой
        okay, _, data_ = server.editor_items_page()
        if not okay:
            self.skipTest("pack не собран")
        меч = next((в for в in data_["items"]
                    if в["name"].startswith("Богатырский меч")), None)
        if меч is None:
            self.skipTest("в этом паке нет богатырского меча")
        self.assertTrue(меч["icon"].startswith("/content/"))
        self.assertTrue(меч["power"] and меч["price"] and меч["weight"])

    def test_world_writing_is_offered_only_where_it_works(self) -> None:
        """Тумблер «пишем в мир» не должен вести в тупик.

        В исходниках мира 79 карт игры. У карты, СОЗДАННОЙ РЕДАКТОРОМ
        («Тихая заводь», 63), записи там нет вовсе, и добавление жителя
        падало с «карты 63 в мире 0 нет». Редактор об этом не знал и
        предлагал тумблер на любой карте — человек выбирал доступный на
        вид путь, который не работает никогда.

        Проверено живьём: map_numbers мира 0 содержит 79 номеров, карта
        23 в нём есть, карты 63 нет.

        СНАЧАЛА ТУПИК ПОДПИСЫВАЛИ, ТЕПЕРЬ ПРЯЧУТ. Первая правка оставляла
        второй вариант на месте и меняла ему подпись на «мир (карта не из
        игры)». На экране существ это читалось как служебный мусор —
        «зачем эта информация в существах?»: выбор из одного варианта,
        где второй объясняет сам себя. Выбора нет — нет и переключателя:
        и он, и слово «Пишем в:» скрываются целиком.

        А у ДОНОРСКОГО героя карта в мире есть, писать нечем только нам, —
        там подпись «мир (нет исходников)» остаётся: без неё человек,
        видевший выбор на другом герое, решит, что кнопка потерялась.
        """
        from knyaz2.web import server
        сервер = (КОРЕНЬ / 'knyaz2' / 'web' / 'server.py').read_text(
            encoding='utf-8')
        живость = клиент('editor_live.js')
        self.assertIn('record["map_numbers"] = sorted(', сервер)
        self.assertIn("const worldKnows = !Array.isArray(worldMapNumbers) ||",
                      живость)
        #: нет записи в мире — прячем и вариант, и подпись «Пишем в:»
        self.assertIn('toWorld.узел.style.display = worldKnows ? "" : "none"',
                      живость)
        self.assertIn(
            'writeToLabel.style.display = worldKnows ? "" : "none"', живость)
        #: донорский герой — вариант виден и объясняет, почему закрыт
        self.assertIn('"мир (нет исходников)"', живость)
        self.assertNotIn("мир (карта не из игры)", живость)
        # и подсказка «как поставить жителя» — порядок действий неочевиден
        self.assertIn("Чтобы поставить жителя: выберите породу ниже",
                      живость)

        okay, _, data_ = server.api_worlds()
        if not okay:
            self.skipTest("sources миров недоступны")
        own = next((m_ for m_ in data_["worlds"] if m_["slot"] == 0), None)
        if not own or not own.get("map_numbers"):
            self.skipTest("мир 0 недоступен")
        self.assertIn(23, own["map_numbers"])
        self.assertNotIn(63, own["map_numbers"])

    def test_village_has_a_screen_of_its_own(self) -> None:
        """Поселения в редакторе не было вовсе — ни ручки, ни экрана.

        А деревня это половина игры: постройки, должности, прилавки,
        казна, ополчение. Запись поселения в проекте не лежит: она
        читается из GAME.<мир> при сборке, и трогать её там нельзя.
        Поэтому единственный способ дать редактору править деревню —
        слой `editor_village`, как у куч и отрядов.

        Вкладки «Деревня» в макете нет. Рисовать свою кнопку рядом с
        чужой рейкой — ровно та ошибка, за которую редактор уже ругали:
        человек жмёт нарисованные пункты. Берём КЛОН настоящего пункта
        («Клады») и правим подпись — иконка и поведение остаются родными.

        Живой прогон на карте 23: вкладка встала между «Кладами» и
        «Событиями», экран показал поселение 7, пять должностных лиц
        ПОИМЁННО (мастер — Трюгви Кожаные штаны) и 42 постройки с
        галочками.
        """
        живость = клиент('editor_live.js')
        self.assertIn('"Деревня": "1k"', живость)
        self.assertIn('state.screens["1k"] = state.screens["1f"]'
                      '.cloneNode(true)', живость)
        self.assertIn("async function screen1k(", живость)
        self.assertIn('"1k": screen1k', живость)
        #: вкладка — КЛОН настоящего пункта рейки, а не своя кнопка
        #: рядом; вставка теперь общая на все дорисованные вкладки
        #: (Деревня, Провер, Сборка), ключ метки собирается из подписи
        self.assertIn('[["Деревня", "1k"], ["Провер", "1i"],', живость)
        self.assertIn('"вкладка-" + label.toLowerCase()', живость)

    def test_village_numbers_are_labelled_with_the_truth(self) -> None:
        """Подпись числа берётся из разбора, а не из имени ключа.

        Соблазн здесь велик и уже однажды сработал бы: ключ `treasury`
        называется казной — и казной НЕ ЯВЛЯЕТСЯ. Это счётчик занятий
        воеводы (+0x0C): такт деревни убавляет его и сбрасывает в 1200,
        а деньги капают в `owned` (+0x10), по ненулевости которого
        обработчик 27 и отвечает «деревня чья-то». Показав `treasury`
        как казну, редактор врал бы уверенно и правдоподобно.

        Подписи живут на сервере, рядом с разбором, и приходят вместе с
        данными — чтобы экран не сочинял своих.
        """
        from knyaz2.web import server
        живость = клиент('editor_live.js')
        self.assertIn("VILLAGE_NOTES", dir(server))
        self.assertIn("НЕ КАЗНА", server.VILLAGE_NOTES["treasury"])
        self.assertIn("казна владения", server.VILLAGE_NOTES["owned"])
        #: экран берёт подписи с сервера, а не пишет свои
        self.assertIn("const captions = obj.notes || {};", живость)
        self.assertNotIn('"treasury", "казна"', живость)

        okay, _, data_ = server.api_village(23, world=0)
        if not okay:
            self.skipTest("карта 23 не собрана")
        # должностные лица приходят ИМЕНАМИ: номер 369 не говорит ничего
        деревня = data_["village"]
        self.assertTrue(data_["names"].get(str(деревня["master"])))
        self.assertEqual(len(деревня["officials"]), 5)

    def test_village_patch_keeps_keys_untouchable(self) -> None:
        """Номера жителей и сторону деревни редактор не правит.

        master/officials/people — это индексы юнитов в таблице мира, и
        на них держится маршрутизация разговоров (обработчик 30
        спрашивает «занимает ли собеседник должность N»). Сменить их
        врозь с самими юнитами — оторвать деревню от её жителей.
        `side` — байт, которым движок индексирует таблицу отрядов, когда
        деревня ополчается: это ключ, а не настройка.

        Живой прогон: правка side отвергнута, чужое поле постройки
        отвергнуто, пустой патч отвергнут; слой сборки поднял owned
        0→5000 и wealth 8→12, снял постройку слота 9, а сторону и
        должностных не тронул.
        """
        from knyaz2.web import server
        from knyaz2.content import builder
        #: белые списки сервера и сборки обязаны совпадать
        self.assertEqual(set(server.VILLAGE_FIELDS),
                         set(builder.EDITOR_VILLAGE_FIELDS))
        self.assertEqual(set(server.VILLAGE_BUILDING),
                         set(builder.EDITOR_VILLAGE_BUILDING))
        for запретное in ("side", "master", "officials", "people",
                          "workplaces", "goods"):
            self.assertNotIn(запретное, server.VILLAGE_FIELDS)
            self.assertNotIn(запретное, builder.EDITOR_VILLAGE_FIELDS)

        # и сама склейка: числа заменяются, постройки адресуются СЛОТОМ
        record = {"owned": 0, "wealth": 8, "side": 65, "officials": [1, 2],
                  "buildings": [{"slot": 9, "built": True, "state": 3},
                                {"slot": 3, "built": True, "state": 3}]}
        builder._editor_village_apply(record, {
            "owned": 5000, "wealth": 12, "side": 1, "officials": [7],
            "buildings": {"9": {"built": False}}})
        self.assertEqual(record["owned"], 5000)
        self.assertEqual(record["wealth"], 12)
        self.assertEqual(record["side"], 65, "сторону трогать нельзя")
        self.assertEqual(record["officials"], [1, 2], "должности не трогаем")
        по_слоту = {p_["slot"]: p_ for p_ in record["buildings"]}
        self.assertFalse(по_слоту[9]["built"])
        self.assertTrue(по_слоту[3]["built"], "соседний слот не задет")

    def test_warbands_have_their_own_screen(self) -> None:
        """Вкладка «Отряды» — свой экран, а не второе имя экрана существ.

        ЭКРАН_ВКЛАДКИ отправлял «Сущ-ва» и «Отряды» на один и тот же 1f,
        и в поведении не менялось ровно ничего: человек, искавший, где
        задать вражду и зоны, попадал в бестиарий. А отряд — не юнит: у
        него своя сторона, свои биты войны и ДВЕ зоны, лежащие в разных
        байтах записи (0x0C/0x10/0x14/0x16 против 0x0E/0x12/0x15/0x17).

        Карточки под отряды в макете нет, поэтому экран 1j — клон
        карточки существ: в ней уже есть топбар, рейка вкладок, холст и
        две колонки, то есть весь каркас, который иначе пришлось бы
        рисовать мимо стиля макета.
        """
        живость = клиент('editor_live.js')
        self.assertIn('"Отряды": "1j"', живость)
        self.assertIn('state.screens["1j"] = state.screens["1f"]'
                      '.cloneNode(true)', живость)
        self.assertIn("async function screen1j(", живость)
        self.assertIn('"1j": screen1j', живость)
        # экран ловит бойцов: щелчок по бойцу выбирает ЕГО отряд
        self.assertIn('"1j": ["packUnit", "unit"]', живость)
        # и не забывает про защиту канона
        self.assertIn("canonStrip(card);\n  const stage = mountCanvas",
                      живость)

    def test_warband_can_be_patched(self) -> None:
        """Отряд можно поправить, а не только завести и удалить.

        Ручек было две — добавить и удалить, — поэтому сделать
        существующий отряд мирным или подвинуть его зону было нечем, а
        это половина работы со стычками.

        ДВА АДРЕСА У ОДНОЙ ПРАВКИ. Свой отряд лежит в
        `editor_warbands_add` целиком — его и правим на месте. Отряд
        ИГРЫ в проекте не лежит вовсе: он читается из GAME.<мир> при
        сборке, и трогать его там нельзя. Для него правка ложится слоем
        `editor_warbands` (ключ — номер стороны), и сборка кладёт слой
        поверх отрядов КАЖДОГО мира — как и добавку.

        `side` в белый список НЕ входит: это ключ записи и он же номер
        стороны бойцов, сменив его, мы оторвали бы отряд от собственных
        юнитов.

        Живой прогон: правка side отвергнута, пустой патч отвергнут, а
        после сборки в паке отряд 190 получил on_player=false и
        zone.row_from 20→7 при уцелевшем row_to=60 — то есть зоны
        СЛИВАЮТСЯ по ключам, а не заменяются целиком.
        """
        from knyaz2.web import server
        from knyaz2.content import builder
        сервер = (КОРЕНЬ / 'knyaz2' / 'web' / 'server.py').read_text(
            encoding='utf-8')
        сборка = (КОРЕНЬ / 'knyaz2' / 'content' / 'builder.py').read_text(
            encoding='utf-8')
        self.assertTrue(hasattr(server, "editor_warband_patch"))
        self.assertIn('editor_band_patches = document.get("editor_warbands")',
                      сборка)
        #: белые списки сервера и сборки обязаны совпадать — разойдутся,
        #: и правка молча не доедет до пака
        self.assertEqual(set(server.BAND_FIELDS),
                         set(builder.EDITOR_WARBAND_FIELDS))
        self.assertEqual(set(server.BAND_ZONES),
                         set(builder.EDITOR_WARBAND_DICTS))
        # сторона не правится ни там, ни там
        self.assertNotIn("side", server.BAND_FIELDS)
        self.assertNotIn("side", builder.EDITOR_WARBAND_FIELDS)
        # маршрут: патч идёт раньше добавления
        self.assertIn('if payload.get("patch") is not None:',
                      сервер)

    def test_canvas_has_an_overlay_hook(self) -> None:
        """Экран может рисовать поверх сцены независимо от мыши.

        Зоны отряда — прямоугольники появления и гуляния — не были видны
        нигде, а именно они решают, где отряд встанет при входе на карту
        и куда забредёт. Рисовать их некуда: у холста был только
        внутренний рисунок подсветки под курсором, и тот гас, стоило
        отвести руку.

        Ручка `поверх` зовётся ДО выхода по «мыши нет» — иначе рисунок
        экрана пропадал вместе с курсором.

        И заливка, а не один контур: зоны бывают во всю карту (у отряда
        65 «Морского лагеря» это строки 3…182, столбцы 1…117), и тогда
        все четыре кромки уходят за края экрана — контур честно
        нарисован, а видно пусто. Проверено живьём: на отряде 30 с малой
        зоной слой поверх дал 319 закрашенных точек.
        """
        живость = клиент('editor_live.js')
        self.assertIn("handlers.поверх?.(overCtx, kindOf);", живость)
        порядок = живость.index("handlers.поверх?.(overCtx, kindOf);")
        self.assertLess(порядок, живость.index("if (!mouseWorld) return;"))
        self.assertIn("brush.globalAlpha = 0.10;", живость)

    def test_items_can_be_put_into_a_pile(self) -> None:
        """В кучу можно положить вещь, а не только деньги.

        Экран кладов правил ровно два поля — деньги и признак тайника, —
        хотя вещи в кладе и есть главное. Данные под это были готовы
        давно: сборка знает `items` и `details` у кучи
        (builder.EDITOR_LOOT_FIELDS), а клиент игры читает их при входе
        на карту (loot.js). Не хватало ручки и списка в панели.

        ССЫЛКА ЭКЗЕМПЛЯРА, А НЕ КЛАССА. В куче лежат записи вида
        `instance:<класс>:<источник>:<хвост>` (actor.js,
        actorNewItemRef): хвост различает записи, иначе два одинаковых
        меча в одной куче слились бы в один. Хвост берём как «наибольший
        занятый плюс один», а не как длину списка: вынул первую вещь,
        положил новую — и номер бы повторился.

        ПОЛНЫЙ СПИСОК, А НЕ ПРИБАВКА: сборка пишет патч поверх кучи
        целиком, поэтому в патч уходит весь новый состав. Для кучи из
        пака основа берётся из собранной карты, для своей — из
        scenario.json; спутав их, первая же добавка стёрла бы то, что
        уже лежало.

        Живой прогон на пробной карте: положены меч и боеприпас с
        зарядами, вынута первая вещь, отвергнута несуществующая
        `class:99999`; после сборки пак понёс обе вещи с верными
        классами и `details`. Затем в браузере: «В куче · 3 черновик» →
        «Положить» → 4, «×» → 3, пробная карта убрана.
        """
        from knyaz2.web import server
        сервер = (КОРЕНЬ / 'knyaz2' / 'web' / 'server.py').read_text(
            encoding='utf-8')
        живость = клиент('editor_live.js')
        сборка = (КОРЕНЬ / 'knyaz2' / 'content' / 'builder.py').read_text(
            encoding='utf-8')
        self.assertTrue(hasattr(server, "editor_loot_item"))
        self.assertIn('f"instance:{cls}:editor:{tail}"', сервер)
        # хвост уникален, а не «по длине списка»
        self.assertIn("max(taken, default=-1) + 1", сервер)
        # сборка обязана пропускать оба поля, иначе правка не доедет
        self.assertIn('"items", "details"', сборка)
        # клиент кладёт и вынимает
        self.assertIn('add_item: { ref: choice.value }', живость)
        self.assertIn("remove_item: num", живость)
        #: черновик побеждает пак: правка идёт в него, и показывать надо
        #: его же, иначе панель отстаёт на одну сборку
        self.assertIn("const freshRec = isOwn || (state.packLoot || [])",
                      живость)
        self.assertIn('${ownPile ? "черновик" : "из пака"}', живость)

    def test_pile_limit_is_ours_not_the_engine(self) -> None:
        """Предел вещей в куче — наша сдержанность, и так и написано.

        Сперва я написала «восемь мест в окне обыска» — и это была
        выдумка: сетки мест у обмена нет, он показывает список. Замер по
        паку: 702 кучи, максимум вещей у авторов — ШЕСТЬ, и то однажды;
        чаще всего одна. Ограничение оставлено (восемь, с запасом), но
        названо тем, чем является.
        """
        from knyaz2.web import server
        сервер = (КОРЕНЬ / 'knyaz2' / 'web' / 'server.py').read_text(
            encoding='utf-8')
        self.assertEqual(server.PILE_ITEMS_LIMIT, 8)
        self.assertIn("это не «предел игры», а наша сдержанность", сервер)
        self.assertNotIn("больше game_name не покажет", сервер)

    def test_loot_shows_what_is_inside(self) -> None:
        """В куче видно вещи, а не только их число.

        Панель кучи показывала деньги, клетку и тайник — и ни слова о
        вещах, хотя ровно вещи в кладе и есть главное: сервер отдавал
        одно число («items: 3»). Между тем пак несёт и ссылки вещей, и
        количества (details), а имена лежат рядом, в таблице items
        карты.

        Живой прогон на карте 23: куча pile_47 показала «Железные стрелы
        для лука × 30 · 7 монет» трижды, со значками.
        """
        сервер = (КОРЕНЬ / 'knyaz2' / 'web' / 'server.py').read_text(
            encoding='utf-8')
        живость = клиент('editor_live.js')
        self.assertIn('"contents": [_pile_good(s_, d_) for s_, d_ in', сервер)
        self.assertIn('insertOwn(spot, contentsEl, "состав-кучи");', живость)

    def test_locked_map_does_not_promise_a_drag(self) -> None:
        """Курсор не обещает хвата там, где его не будет.

        Из 141 карты проекта правится РОВНО ОДНА своя: остальные 140 —
        распакованная игра, и сервер отказывает в правке (проверено:
        POST объекта на карту 1 отдаёт 400, на карту 63 — ok).

        Пока причина жила одной проверкой в начатьПеренос, наружу
        торчало вот что: наведение на дерево давало курсор grab —
        прямое обещание, — а на попытку взять приходил отказ строкой
        состояния внизу, куда человек не смотрит. Жители мира при этом
        возились: у них своя ручка и свои исходники. Выходило ровно
        «нпс двигаются, а деревья нет».

        Причина теперь одна и живёт в самой вещи (картаЗаперта), так
        что честны разом курсор, щелчок, стрелки и перенос. Жителя
        мира это НЕ касается — он пишется в project/worlds.

        Живой прогон на карте 1: курсоров grab — ноль, help — 78,
        отказ называет объект и путь к копии, полоса канона мигнула.
        """
        живость = клиент('editor_live.js')
        self.assertIn("function mapLocked()", живость)
        # одна причина на все вещи КАРТЫ
        self.assertEqual(
            живость.count("двигается: !locked, почемуНеДвигается: locked"), 4)
        # ...и ни одной безусловной «двигается: true» у вещей карты
        self.assertNotIn("kind_: \"object\", объект: o_, name_: `объект ${о.slot}`,\n"
                         "        двигается: true", живость)
        # житель мира живёт по своим правилам и остаётся подвижным
        self.assertIn("двигается: own", живость)
        # отказ ведёт взгляд к выходу, а не только в строку внизу
        self.assertIn("function blinkCanonStrip()", живость)
        self.assertIn("if (state.editable === false) blinkCanonStrip();",
                      живость)
        # копия карты не теряет камеру: человек уже довёл взгляд до места
        self.assertIn("const kindOf = state.view ? { ...state.view } : null;",
                      живость)
        self.assertIn("if (kindOf) state.view = kindOf;", живость)

    def test_wrong_tool_says_where_to_go(self) -> None:
        """Инструмент ловит своё — но о чужом обязан сказать.

        Щелчок по дереву на экране существ не делал РОВНО НИЧЕГО и
        ничего не говорил: ЛОВИТ["1f"] это ["unit","packUnit"], объекта
        там нет. А именно на этот экран человек и попадает первым делом
        — карточка карты открывает «Сущ-ва». Жители здесь ловятся,
        деревья молчат: вот и «нпс двигаются, деревья нет».

        Живой прогон на карте 1: щелчок по дереву на экране существ
        теперь отвечает «это объект «объект 13» — этот инструмент его не
        берёт: перейдите на вкладку «Объект»».
        """
        живость = клиент('editor_live.js')
        self.assertIn("const TAB_KIND = {", живость)
        self.assertIn("этот инструмент его не ", живость)
        # второй проход по вещам делаем ТОЛЬКО когда своих не нашлось
        self.assertIn("const alien = kinds ? hitAt(pt, null) : null;",
                      живость)
        # у каждого ловимого вида есть куда послать
        for kind_ in ("object", "decor", "unit", "packUnit", "loot", "packLoot"):
            self.assertIn(f"{kind_}:", живость)

    def test_move_result_survives_the_reread(self) -> None:
        """Последнее слово за итогом жеста, а не за пересказом карты.

        В конце переноса стоит открытьКарту — она нужна: холст вёл вещь
        оптимистично, и после ответа сервера карту надо перечитать. Но
        открытьКарту заканчивается своим status() («карта 1: объектов
        115, вода 0») и перетирала итог через долю секунды — и отказ, и
        успех.

        С отказом выходило ровно то, с чего начались жалобы: вещь едет
        за курсором, на отпускании прыгает назад — и ни слова почему.
        С успехом человек не видел подтверждения и не знал, записалось
        ли.

        Живой прогон на своей карте 63: после отпускания в строке
        осталось «объект 0 → 751:498», а не пересказ карты.
        """
        живость = клиент('editor_live.js')
        self.assertIn("result = resp.ok ? luck :", живость)
        self.assertIn("if (result) status(result);", живость)
        # повтор идёт ПОСЛЕ перечитывания, иначе смысла нет
        порядок = живость.index("await openMap(state.map);\n  showScreen"
                                "(state.screen);\n  //: перечитывание")
        self.assertLess(порядок, живость.index("if (result) status(result);"))

    def test_own_maps_come_first(self) -> None:
        """Единственная правимая карта не должна лежать последней.

        Правится та карта, у которой origin.editor; остальные 140 — это
        распакованная игра, только для чтения. В прежнем порядке своя
        карта 63 оказалась 141-й из 141, на двенадцатой странице из
        двенадцати: единственное место, где редактор что-то правит, было
        спрятано дальше всего, и человек открывал первую попавшуюся
        карту игры.

        Живой прогон: «Тихая заводь» стоит первой, за ней «Дворец
        Повелителя» и «Лабиринт смерти» — то есть порядок остальных не
        перемешался.
        """
        живость = клиент('editor_live.js')
        self.assertIn("(b2.editable === true) - (a2.editable === true)", живость)

    def test_map_card_words_are_real_links(self) -> None:
        """Что похоже на ссылку — то и ведёт.

        В карточке карты стоят четыре слова «объекты · юниты · отряды ·
        клады» внутри кликабельной карточки: выглядят ровно как
        навигация. Но карточка, куда ни ткни, открывала ОДИН экран
        существ — человек жмёт «объекты» и попадает к бестиарию.
        Проверено живьём: клик по слову «объекты» на карте 1 приводил на
        вкладку «Сущ-ва».

        Теперь слова ведут каждое на своё, а всплытие гасится — иначе
        сработал бы ещё и обработчик самой карточки и перебил бы экран.
        """
        живость = клиент('editor_live.js')
        self.assertIn('const TAB_TO_SCREEN = { "объекты": "1b", "юниты": "1f"', живость)
        self.assertIn("ev.stopPropagation();", живость)
        # карточка целиком по-прежнему ведёт на существ — это её право
        self.assertIn('if (await openMap(mapRec.map)) showScreen("1f");',
                      живость)

    def test_resident_name_is_a_number_from_the_exe(self) -> None:
        """Имя жителя ВЫБИРАЮТ из таблицы exe, а не пишут строкой.

        Пока имени не было в белом списке, добавленный редактором житель
        наследовал имя записи-образца: поставишь пятерых — выйдет пять
        тёзок «Хрофтов». Соблазн «дать полю name строку» здесь ложный:
        в GAME.<мир> строки имени НЕТ ВОВСЕ, запись хранит два номера
        (0xF0 имя, 0xF1 прозвище), а сами строки лежат в исполняемом
        файле игры и правке не подлежат. Значит единственный честный
        путь — выбор из 184 авторских имён и 20 прозвищ, и ровно его
        отдаёт ручка /catalog/names.

        Три места должны сойтись, иначе выбор тихо не доедет:
        _write_unit обязан писать эти два байта, map_units — отдавать
        номера обратно (по собранной строке запись не восстановить), а
        белый список сервера — пропускать их.

        Живой прогон на мире 0: житель со слотом 983 и name_id 4,
        nick_id 1 после сборки прочитан движком как «Боян Косой».
        """
        from knyaz2.web import server
        живость = клиент('editor_live.js')
        ядро = (КОРЕНЬ / 'konung2' / 'worlds.py').read_text(encoding='utf-8')
        file = (КОРЕНЬ / 'konung2' / 'gamefile.py').read_text(encoding='utf-8')
        # 1. ядро пишет оба байта записи
        self.assertIn('("name_id", 0xF0), ("nick_id", 0xF1)', ядро)
        # 2. разбор отдаёт номера, а не только собранную строку
        self.assertIn('"name_id": unit[0xF0], "nick_id": unit[0xF1]', file)
        # 3. сервер их пропускает и умеет отдать таблицу
        self.assertIn("name_id", server.WORLD_UNIT_FIELDS)
        self.assertIn("nick_id", server.WORLD_UNIT_FIELDS)
        self.assertTrue(hasattr(server, "editor_names_page"))
        # 4. клиент выбирает имя, а не сочиняет его
        self.assertIn("function nameByNumber(", живость)
        self.assertIn('api("/catalog/names")', живость)

        okay, _, data_ = server.editor_names_page()
        if not okay:                           # игры под рукой нет
            self.skipTest("таблица имён недоступна")
        # индекс 0 — пустая строка, её в выбор пускать нельзя
        self.assertTrue(all(z_["id"] and z_["name"] for z_ in data_["names"]))
        self.assertEqual(data_["names"][0], {"id": 1, "name": "Белун"})
        self.assertEqual(data_["nicknames"][0], {"id": 1, "name": "Косой"})

    def test_new_resident_keeps_the_clicked_cell(self) -> None:
        """Клик мышью обязан пережить вход на карту.

        Зона появления отряда — не декорация: при свежем входе движок
        рассыпает отряд по её прямоугольнику случайно и ПЕРЕЗАПИСЫВАЕТ
        клетки юнита (FUN_00415764, вызов из 0x0043DF48). Первая версия
        копировала зону у образца — и житель уезжал туда, где стоит
        чужой отряд: поставленная мышью точка была враньём.

        Разброс огорожен двумя условиями, и оба проверены на живых
        данных: обход начинается с записи 1 (отряд игрока не трогают), и
        бит 0x10 байта 0x1E велит оставить записанное. Держим двойную
        защиту — бит И вырожденный прямоугольник 1x1: при
        row_from == row_to разброс равен нулю, а центр (r + r + 1) // 2
        даёт ровно r, так что клетка та же даже без бита.

        Живой прогон: житель на 64:24 карты 23 получил зону
        64…64 / 24…24 с flags 18, и канонная формула вернула 64:24.
        """
        from knyaz2.web import server
        from konung2.gamefile import PARTY_KEEP_CELLS, map_parties
        сервер = (КОРЕНЬ / 'knyaz2' / 'web' / 'server.py').read_text(
            encoding='utf-8')
        self.assertEqual(PARTY_KEEP_CELLS, 0x10)
        # зона строится вокруг клика, а не копируется у образца
        self.assertIn('"row_from": line, "row_to": line', сервер)
        self.assertIn("| PARTY_KEEP_CELLS", сервер)
        # вырожденная зона обязана давать ту же клетку — это и есть
        # вторая половина защиты, считаем канонной формулой
        for cell_ in (0, 7, 64, 199):
            self.assertEqual((cell_ + cell_ + 1) // 2, cell_)

        # и корреляция на живых данных: бит и записанные клетки ходят вместе
        try:
            bands = {p_["side"]: p_ for p_ in map_parties(23, 0)}
        except Exception:                       # игры под рукой нет
            self.skipTest("GAME.0 недоступен")
        self.assertTrue(bands, "на карте 23 мира 0 missing band_count")
        for p_ in bands.values():
            zone = p_["zone"]
            self.assertEqual(zone["keep_cells"],
                             bool(zone["flags"] & PARTY_KEEP_CELLS))

    def test_free_slot_criteria_are_strict(self) -> None:
        """«Свободен» — это пусто ЦЕЛИКОМ, а не «счётчик равен нулю».

        Первая версия брала слот отряда по одному признаку count==0 и
        слот юнита — по «не входит в диапазон живого отряда». Обе мерки
        оказались слишком мягкими, и состязательный разбор нашёл три
        настоящие ловушки; каждая проверена здесь на живых данных.

        1. СЕМЬ СЛОТОВ ОТРЯДА В КАЖДОМ МИРЕ имеют нулевой счёт, но
           заполнены map (140…146), war_flags 0x41 и first_unit — это
           зарезервированные записи. Первая версия выбрала слот 103 мира
           0 и затёрла бы такую.
        2. БАЙТ 0x1A — ВМЕСТИМОСТЬ, место наперёд: у отряда игрока счёт
           3, а вместимость 9, и слоты 3…8 ждут спутников. Первая версия
           посадила жителя ровно в слот 3 — первый же наём затёр бы его.
        3. ОБРАБОТЧИК 46 СЮЖЕТА снимает юнита с карты по номеру
           (docs/ENGINE_TICK.md), и зовут его с аргументами 7, 58, 98.
           Житель в таком слоте однажды молча исчез бы посреди игры.
        """
        from knyaz2.web import server
        сервер = (КОРЕНЬ / 'knyaz2' / 'web' / 'server.py').read_text(
            encoding='utf-8')
        # мерка слота отряда учитывает все четыре поля
        self.assertIn("if tally or map_rec or war or first_one:", сервер)
        # вместимость держит место наперёд
        self.assertIn("occupy(first_one, max(tally, capacity))", сервер)
        # квестовые жертвы читаются у самого сюжета
        self.assertIn("def _quest_victims()", сервер)

        # и то же самое — на живых данных мира
        try:
            taken_bands, taken_units, sizes = server._world_occupancy(
                0, server._world_documents(0))
        except Exception:                       # игры под рукой нет
            self.skipTest("GAME.0 недоступен")
        for slot in (103, 105, 107, 109, 111, 113, 115):
            self.assertIn(slot, taken_bands,
                          f"слот отряда {slot} зарезервирован под карту "
                          f"140…146, его нельзя считать свободным")
        for slot in range(3, 9):
            self.assertIn(slot, taken_units,
                          f"слот юнита {slot} — резерв спутников отряда "
                          f"игрока (вместимость 9 при счёте 3)")
        for slot in server._quest_victims():
            self.assertIn(slot, taken_units,
                          f"юнита {slot} сюжет снимает с карты "
                          f"обработчиком 46")
        свободныхО = sizes["parties"] - len(taken_bands)
        свободныхЮ = sizes["units"] - len(taken_units)
        self.assertGreater(свободныхО, 20, "слотов band_count почти не left_over")
        self.assertGreater(свободныхЮ, 500, "слотов юнитов почти не осталось")

    def test_hero_slot_is_a_pair_not_a_number(self) -> None:
        """Слот героя — это ПАРА «игра + мир», а не голый номер.

        Пак ключует население номером слота (units_by_world, 0…8), а
        слот раскрывается через konung2.donor.HERO_SLOTS: слот 2 — это
        канонный мир 2, а слот 1 — мир 1 ДОНОРСКОЙ игры, и это разные
        файлы. Исходники в project/worlds — только канонные, папка N
        значит канонный мир N.

        Пока список строился по папкам, показ и запись разъезжались
        молча: редактор показывал население слота 1 (донорского), а
        правка по тому же числу ушла бы в КАНОННЫЙ мир 1 — в чужие
        данные, без единого признака, что что-то не так. Ровно та
        ловушка, о которой предупреждает разбор общих номеров: ключ —
        пара, а не число.

        Заодно список вырос с шести до девяти: трёх донорских героев
        (Иззарк, Драгомир, Гильдис) не было видно вовсе, хотя их
        население в паке лежит.
        """
        from knyaz2.web import server
        from konung2 import donor
        ok_, _, reply = server.api_worlds()
        self.assertTrue(ok_)
        slots = reply["worlds"]
        self.assertEqual(len(slots), len(donor.HERO_SLOTS))
        for record, (game_name, world_) in zip(slots, donor.HERO_SLOTS):
            self.assertEqual((record["game"], record["world"]), (game_name, world_))
            if game_name != "canon":
                self.assertFalse(record["editable"])
        first_one = next(z_ for z_ in slots if z_["slot"] == 1)
        self.assertEqual(first_one["game"], "legend")
        self.assertFalse(first_one["editable"])

    def test_world_unit_patch_is_whitelisted(self) -> None:
        """Ручка мира пишет только то, что доезжает до игры.

        Она принимала ЛЮБОЕ поле — включая сам `raw`, которым запись
        юнита стирается целиком одной опечаткой в теле запроса. И
        наоборот: поле, которого нет в konung2.worlds._write_unit, осело
        бы в json и молча не доехало до GAME.N. Белый список снят с
        самой сборки.
        """
        from knyaz2.web import server
        self.assertIn("row", server.WORLD_UNIT_FIELDS)
        self.assertIn("col", server.WORLD_UNIT_FIELDS)
        self.assertNotIn("raw", server.WORLD_UNIT_FIELDS)
        self.assertIn("zone", server.WORLD_BAND_FIELDS)
        self.assertNotIn("raw", server.WORLD_BAND_FIELDS)
        suitable, surplus = server._world_filter(
            {"row": 5, "raw": "ff", "выдумка": 1}, server.WORLD_UNIT_FIELDS)
        self.assertEqual(suitable, {"row": 5})
        self.assertEqual(surplus, ["raw", "выдумка"])

    def test_world_resident_is_movable(self) -> None:
        """Житель мира двигается — правкой исходника мира.

        В редакторе он был помечен «не двигается: место считает сборка
        по зоне отряда», и это оказалось неверно. Проверено на данных:
        житель unit_9 карты 23 стоит в паке ровно в клетке 51:14, как
        записано в project/worlds/0/maps/23.json (row 51, col 14). Зона
        отряда задаёт, где он БРОДИТ, а стоит он там, где сказано
        полями. Живой прогон: перетащила Хрофта на канонной карте — в
        мире стало 54:16; канон затем возвращён.

        ЗАЩИТА КАНОНА — ПРО КАРТУ, А НЕ ПРО МИР. Житель пишется в свои
        исходники и правится даже когда сама карта из игры и только для
        чтения: иначе расстановка населения на РОДНЫХ картах игры, ради
        которой всё и затевалось, была бы невозможна.
        """
        живость = клиент('editor_live.js')
        self.assertIn('} else if (what.вид === "packUnit") {', живость)
        self.assertIn('`/worlds/${slotNum.world}/maps/${state.map}/units`',
                      живость)
        self.assertIn('if (!state.editable && what.вид !== "packUnit")',
                      живость)
        self.assertIn('state.слотГероя', живость)

    def test_drag_starts_on_movement_not_on_a_timer(self) -> None:
        """Перенос начинается от движения мыши, а не по таймеру.

        Жест был устроен наоборот и потому не работал вовсе: нажатие
        запускало таймер на 450 мс, а ЛЮБОЕ движение мыши таймер
        ОТМЕНЯЛО. То есть естественное «нажал на избу и повёл» само себя
        и гасило; срабатывало ровно одно сочетание — нажать, замереть на
        полсекунды и только потом вести. Догадаться об этом было
        неоткуда, и «объекты не двигаются» оставалось чистой правдой,
        даже когда всё остальное уже чинилось.

        Теперь нажатие только запоминает кандидата, а перенос начинается
        от первого сдвига. Отпустил, не сдвинув, — это щелчок, он
        выбирает. Живой прогон: объект уехал 2500,2000 → 2809,2085
        естественным жестом; простой щелчок выбрал его и НЕ сдвинул;
        юнит уехал 70:40 → 75:44, взятый за тело, а не за ноги.
        """
        живость = клиент('editor_live.js')
        self.assertIn('function startDrag(ev)', живость)
        self.assertIn('cand = { что: hitAt(pt, handlers.хватать)',
                      живость)
        self.assertIn('if (cand && !dragging) {', живость)
        # таймера и его отмены больше нет
        self.assertNotIn('}, 450);', живость)
        self.assertNotIn('ждёмЗахвата', живость)
        # захват указателя не должен ронять перенос, если его не дают
        self.assertIn('try { stage.setPointerCapture(ev.pointerId); }',
                      живость)
        # главный жест назван вслух в подсказках
        self.assertIn('"клик — выбрать": "клик — выбрать · тяните — двигать"',
                      живость)

    def test_zone_lookup_skips_a_detached_card(self) -> None:
        """Геометрия есть только у ПОКАЗАННОЙ карточки.

        Экраны оживают асинхронно (палитра тайлов сперва ждёт
        /catalog/tiles), и если за это время человек ушёл на другой
        экран, прежняя карточка уже откреплена от документа — а у
        откреплённого узла clientWidth равен НУЛЮ, и мерки вроде «шире
        ста, уже четырёхсот шестидесяти» не сойдутся никогда. Это не
        промах монтажа, а опоздавший ответ, и кричать о нём нельзя:
        сторож промахов обесценится ложными тревогами.

        Живой прогон: 27 быстрых переключений экранов подряд (три
        прохода по девяти, по 300 мс) — ноль промахов, палитра на месте.
        """
        живость = клиент('editor_live.js')
        self.assertIn('if (!card.isConnected) return null;', живость)

    def test_zones_are_found_once_and_marked(self) -> None:
        """Зоны списков ищутся эвристикой ОДИН раз и помечаются.

        Списки, гриды и палитры ищутся в макете геометрией: «самый
        тесный контейнер шириной меньше 470 с тремя строками, где есть
        pile_», «самый вместительный грид», «блок с двенадцатью
        детьми». На чистом макете это работает — но после первой же
        отрисовки содержимое зоны НАШЕ, и второй заход ищет уже среди
        собственных вставок: мерки перестают сходиться, эвристика
        цепляет соседа, и экран ломается молча.

        Так уже случалось дважды: на 1i карточка-образец с кнопками
        переходов уничтожила сама себя, а поле поиска каталога осталось
        с обработчиком первого показа. Лечили точечно, по факту
        поломки; теперь приём общий для всех шести зон.

        Живой прогон: три полных прохода по всем девяти экранам — ноль
        промахов, и бестиарий на четвёртом заходе по-прежнему полон.
        """
        живость = клиент('editor_live.js')
        self.assertIn('function zoneOnce(card, key2, seek)', живость)
        self.assertIn('miss("зона", key2)', живость)
        #: КАК ИСКАТЬ — ТЕПЕРЬ В КОНТРАКТЕ, а не по месту вызова. Мерки
        #: «на глаз» были разбросаны по экранам, и одна из них брала
        #: пустую полоску шириной 56 точек: туда уезжал весь каталог
        #: объектов, а на его месте оставался макет. Связность контракта
        #: стережёт tests/test_editor_contract.py.
        for key_ in ('"грид-карт"', '"палитра-тайлов"', '"каталог-объектов"',
                     '"список-существ"', '"список-куч"',
                     '"находки-валидатора"'):
            self.assertIn(f'zoneOf(card, {key_})', живость)
        self.assertIn('const ZONES = {', живость)
        # прежняя точечная заплатка сведена на общий приём
        self.assertNotIn('data-lv="validator-list"', живость)

    def test_inspector_rows_can_be_typed_into(self) -> None:
        """Инспектор перестал быть «только для чтения».

        Позицию объекта, его состояние (фазу стройки или руины) можно
        было увидеть, но не задать. Выровнять три избы в ряд было нечем
        вовсе — только возить мышью и надеяться, хотя координаты видны с
        точностью до пикселя. Сменить фазу постройки можно было лишь
        «убрать и поставить заново вслепую», теряя слот и порядок в
        таблице: ручка editor_object_move принимала ТОЛЬКО координаты.

        Плюс привязка к сетке по Shift: с зажатым Shift вещь садится на
        узлы сетки земли (шаг 0x74 на 0x20), и соседние постройки встают
        ровно, как в авторских деревнях. Живой прогон: перетаскивание на
        нарочно некруглое смещение дало 3828 и 1728 — оба кратны шагу.
        """
        from knyaz2.web import server
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            folder = root_ / "66_proba"
            folder.mkdir()
            (folder / "map.json").write_text(json.dumps({
                "map_number": 66, "origin": {"editor": True},
                "objects": {"records": [
                    {"slot": 0, "pixel_x": 10, "pixel_y": 20, "state": 0,
                     "kind": 0, "raw": "00" * 36}]}}), encoding="utf-8")
            with mock.patch.object(server, "PROJECT_MAPS", root_):
                ok_, _, reply = server.editor_object_move(
                    66, {"slot": 0, "state": 3, "palette": 7})
                self.assertTrue(ok_)
                self.assertEqual(reply["state"], 3)
                # палитра лежит байтовым смещением с шагом 0x200
                self.assertEqual(reply["kind"], 7 * 0x200)
                document = json.loads(
                    (folder / "map.json").read_text(encoding="utf-8"))
                # сырые байты уступают полям, иначе правка не доедет
                self.assertNotIn("raw", document["objects"]["records"][0])
        живость = клиент('editor_live.js')
        self.assertIn(
            'function numberFields(card, rowEl, key2, fields, applyIt)',
            живость)
        # своё поле ищется ОТ КАРТОЧКИ: после первой подмены исходный
        # узел значения откреплён от документа, и parentElement у него
        # null — второй заход завёл бы второй короб
        self.assertIn('card?.querySelector(`[data-lv="числа-${key2}"]`)',
                      живость)
        # значение не перетирается, пока человек в поле
        self.assertIn('if (document.activeElement !== entry)', живость)
        self.assertIn('function toGrid(val, step)', живость)
        self.assertIn('moveBy(dragging.что, pt, ev.shiftKey);', живость)

    def test_scene_is_drawn_by_depth(self) -> None:
        """Холст рисует сцену по глубине, а не по порядку записей.

        Объекты рисовались в порядке таблицы карты, а юниты — ВСЕГДА
        после всех объектов. В игре не так: движок сортирует сцену по
        нижнему краю кадра, и воин, стоящий за избой, ею закрыт.
        Редактор показывал обратное — расстановка деревни системно врала
        о том, что кого перекроет, и заметить это можно было, только
        собрав карту и сходив туда в игре.

        КЛЮЧ БЕРЁМ У СБОРКИ, А НЕ СЧИТАЕМ ЗАНОВО. Формула канона —
        position.y + offset_y + sort_height − sort_bias, где sort_height
        это большая из высот main и walls (крыша не в счёт), а bias —
        четверть высоты у построек с битом 0x08 заголовка (VA 0x426B75:
        линия глубины идёт по подошве передней стены). Ни бита, ни
        sort_height в паспорте объектов нет, и konung2/world/geometry.py
        прямо предупреждает: проверять картинкой или декомпилятом, а не
        своей арифметикой — один раз уже уехало на 183…450 точек.
        Наивное «нижний край кадра» сошлось на 266 объектах карты 23 из
        282 и разошлось ровно на 16 постройках. Поэтому сервер отдаёт
        готовые ключи из пака (живой прогон: 282 из 282 точно), а сам
        редактор считает приближённо только то, чего в паке ещё нет —
        только что поставленное до сборки.
        """
        from knyaz2.web import server
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            map_rec = root_ / "maps" / "23"
            map_rec.mkdir(parents=True)
            (map_rec / "map.json").write_text(json.dumps({
                "props": [{"record_slot": 0,
                           "bounds": {"sort_y": 483, "height": 113}}],
                "buildings": [{"record_slot": 1,
                               "bounds": {"sort_y": 2445, "sort_bias": 140}}],
            }), encoding="utf-8")
            ok_, _, reply = server.api_pack_units(23, root_)
            self.assertTrue(ok_)
            self.assertEqual(reply["object_depth"], {0: 483, 1: 2445})
        живость = клиент('editor_live.js')
        self.assertIn('sceneEl.sort((a2, b2) => a2.глубина - b2.глубина);', живость)
        self.assertIn('const exact = state.глубины?.[obj.slot];', живость)
        # юнит встаёт в ту же очередь, канонным ключом «ноги плюс шесть»
        self.assertIn('sceneEl.push({ глубина: feet + 6,', живость)

    def test_hover_and_ghost_live_on_their_own_layer(self) -> None:
        """Подсветка под курсором и призрак — на отдельном холсте.

        Раньше курсор был всегда «прицел», подсветки того, что под ним,
        не было вовсе, а в режиме расстановки человек не видел ни ЧТО он
        ставит, ни КУДА оно встанет относительно курсора — узнавал
        только после щелчка. Отсюда добрая половина «всё криво-косо»:
        ставишь избу, а она оказывается не там, потому что точка
        привязки у неё не в середине картинки.

        Рисовать это в основной сцене нельзя: она тяжёлая (земля
        тайлами, сотни объектов, одетые юниты), и редактор заикался бы
        ровно там, где нужна точность. Второй прозрачный холст поверх
        стоит 0.04 мс на движение мыши (живой замер, 60 событий).
        """
        живость = клиент('editor_live.js')
        self.assertIn('const overCanvas = document.createElement("canvas")',
                      живость)
        self.assertIn('pointer-events:none', живость)
        self.assertIn('function drawOver()', живость)
        self.assertIn('function ghostFrame(placing, pt)', живость)
        # наведение не считаем там, где оно не показывается
        self.assertIn('const needHover = !state.place && painting === null',
                      живость)
        # курсор говорит, можно ли схватить
        self.assertIn('"grab" : "help"', живость)

    def test_active_mode_is_visible(self) -> None:
        """Видно, какая кисть взята и в каком режиме находишься.

        Семь строк кистей проходимости выглядели одинаково всегда, а
        красили разное: человек жал «Глушь», потом «Выход», и убедиться,
        что переключилось, было нечем. Подсветка наткнулась на тот же
        капкан, что съел подсветку тумблера: подъём «до родителя с двумя
        детьми» у части кистей упирается в ОДИН контейнер на несколько
        строк, и покраска по нему гасит сама себя — побеждает кисть,
        обработанная последней. Считаем, сколько РАЗНЫХ кистей делят
        строку, и красим лист, когда общая.

        Escape отпускал только расстановку; из набора области и из
        постановки выхода выйти было нечем, кроме перезагрузки.

        У плиток палитры земли номер жил только во всплывающей подсказке
        — а он и есть то, чем тайл зовётся везде (grid.txt, POST
        /terrain, панель «Тайл под курсором»).
        """
        живость = клиент('editor_live.js')
        self.assertIn('const brushesOfRow = new Map();', живость)
        self.assertIn('const shared2 = (brushesOfRow.get(rowEl)?.size || 0) > 1',
                      живость)
        self.assertIn('function paintBrushes()', живость)
        # Escape гасит все три режима
        for режим in ('state.place', 'state.exitArm', 'state.areaMode'):
            self.assertIn(режим, живость)
        self.assertIn('prev.push("постановка выхода")', живость)
        self.assertIn('prev.push("набор области")', живость)
        # номер под плиткой палитры
        self.assertIn('num.textContent = tileNum.index;', живость)

    def test_anchor_misses_are_reported(self) -> None:
        """Промах якоря — самая тихая поломка этого редактора.

        Живая логика ищет узлы макета по подписям и эвристикам. Стоит
        подписи измениться или эвристике промахнуться — орган просто НЕ
        НАХОДИТСЯ, и код молча ничего не делает: ошибки в консоли нет,
        экран выглядит целым, кнопка не отвечает. Так уже терялись
        «Ставить/Снимать» и все кисти на 1d, подсветка рейки, половина
        счётчиков. Теперь промахи считаются вслух.

        Перебор нескольких имён одного органа (кнопка клона подписана
        по-разному на трёх экранах) промахом НЕ считается — иначе сторож
        кричит волками на каждом экране и его перестают читать.

        Живой прогон после правки: два прохода по всем девяти экранам —
        ноль промахов (до правки сторож сразу нашёл настоящий: поле
        поиска каталога умирало на втором заходе, см. живоеПоле).
        """
        живость = клиент('editor_live.js')
        self.assertIn('function miss(where2, what)', живость)
        self.assertIn('state.промахи.push(', живость)
        self.assertIn('miss("орган", label)', живость)
        self.assertIn('miss("значениеРяда", label)', живость)
        self.assertIn('function organAny(card, ...captions)', живость)
        self.assertIn('organOf(card, p2, false, true)', живость)

    def test_live_field_survives_second_visit(self) -> None:
        """Поле поиска умирало на повторном заходе на экран.

        Карточка экрана — ОДИН И ТОТ ЖЕ DOM-узел на все показы. Первый
        заход подменял нарисованную подпись на настоящий <input> — и на
        втором подпись уже не находилась (её съел сам input): поле молча
        оставалось с обработчиком ПЕРВОГО захода, замкнутым на прежние
        списки. Ровно этот класс однажды уничтожил экран валидатора.
        """
        живость = клиент('editor_live.js')
        self.assertIn(
            'function liveField(card, key2, seek, hint2, onInput)',
            живость)
        self.assertIn('input[data-lv="${mark}"]', живость)

    def test_water_is_painted_in_batches(self) -> None:
        """Вода красится пачкой, а не по клетке за запрос.

        Каждый клик уходил отдельным запросом, и КАЖДЫЙ ложился
        отдельной записью в журнал отмены — общий на весь сервер и
        глубиной 30 шагов. Одно озеро (сотня клеток) вытесняло оттуда
        всю прежнюю работу: Ctrl+Z после заливки откатывал воду по
        клетке, а всё, что делали до неё, из истории уже выпало.
        Живой прогон: ведение по десяти клеткам — одна запись.
        """
        from knyaz2.web import server
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            folder = root_ / "64_proba"
            folder.mkdir()
            (folder / "map.json").write_text(
                json.dumps({"map_number": 64, "origin": {"editor": True}}),
                encoding="utf-8")
            with mock.patch.object(server, "PROJECT_MAPS", root_):
                ok_, _, reply = server.editor_water_save(64, {"cells": [
                    {"row": 5, "col": c, "value": 1} for c in range(3, 13)]})
                self.assertTrue(ok_)
                self.assertEqual(reply["count"], 10)
                # клетка вне сетки 16x32 — отказ, а не тихая порча
                missing, нота, _ = server.editor_water_save(64, {"cells": [
                    {"row": 99, "col": 0, "value": 1}]})
                self.assertFalse(missing)
                self.assertIn("16x32", нота)
        живость = клиент('editor_live.js')
        self.assertIn('function waterStroke(pt, val, stage)', живость)
        self.assertIn('drag: (pt, eraseAt) => waterStroke(', живость)

    def test_undo_follows_the_map_it_rolled_back(self) -> None:
        """Журнал отмены общий на весь сервер, а не на карту.

        _UNDO — один список путей ко всем картам разом. Ctrl+Z откатывал
        последнюю правку ВООБЩЕ: поработал на одной карте, перешёл на
        другую, нажал отмену — откатилась правка первой, которой на
        экране нет. Видимая карта не менялась ни на пиксель, и отмена
        выглядела сломанной, хотя честно отработала. Сервер называет
        откаченный путь — по нему переводим взгляд туда, где правка.
        """
        живость = клиент('editor_live.js')
        self.assertIn('function mapFromPath(path2)', живость)
        self.assertIn('foreign !== state.map', живость)
        self.assertIn('правка была на карте ${foreign}', живость)

    def test_lying_hints_are_corrected(self) -> None:
        """Подсказки макета обещали жесты, которых нет.

        Их писал дизайн, а не код: «Shift+драг — прямоугольник» (на деле
        два клика по углам), «TAB ⟳» (Tab не подключён), «Enter —
        поставить» (Enter не подключён), «Space — взять» (жест висит на
        Ins), «Del — убрать (removed)» (запись убирается, а не метится),
        «Зона тянется за углы прямо на холсте» (такого нет вовсе). Для
        человека, который видит редактор впервые, это хуже отсутствия
        подсказки: он жмёт, ничего не происходит, вывод — «сломано».
        """
        живость = клиент('editor_live.js')
        self.assertIn('const HONEST_HINTS = {', живость)
        for враньё in ('"Shift+драг — прямоугольник"', '"TAB ⟳"',
                       '"Enter — поставить"', '"Del — убрать (removed)"',
                       '"Space — взять под курсором"'):
            self.assertIn(враньё, живость)
        self.assertIn('function honestHints(card)', живость)
        # ТУМБЛЕР «ПИШЕМ В: draft-слой | мир» ПРОШЁЛ ТРИ ЖИЗНИ. Сперва
        # он не делал НИЧЕГО и врал об этом статусом: поле, которое он
        # переключал, никто не читал — во всём файле оно встречалось
        # дважды, оба раза внутри самого тумблера. Тогда его заменили
        # честной подписью «правки идут в draft-слой», потому что
        # добавить жителя В МИР было нечем. Теперь есть
        # (editor_world_unit_add), и выбор снова осмыслен и РАБОТАЕТ:
        # draft-слой виден всем девяти героям, мир — только своему.
        self.assertIn('state.кудаЮнит = "world"', живость)
        self.assertIn('state.кудаЮнит = "draft"', живость)
        # донорские слоты писать нечем, и тумблер это говорит
        self.assertIn('мир (нет исходников)', живость)

    def test_pager_arrows_do_not_share_one_target(self) -> None:
        """Страница листалась ТОЛЬКО ВПЕРЁД, куда бы ни нажали.

        Обе стрелки макета лежат в одном ряду, и обработчик вешался на
        «ближайшего родителя» — у ‹ и › он ОБЩИЙ. Второй цикл затирал
        первый: `onclick` ряда становился «вперёд», и левая стрелка
        листала вперёд тоже. Симптом обманчив — кнопка нажимается,
        подпись «стр N/M» меняется, просто всегда не в ту сторону.

        Лечение: подниматься вверх только пока предок не захватил чужую
        стрелку. Проверено живьём на списке карт: 1 → 2 → 3 → 2 → 1.
        """
        живость = клиент('editor_live.js')
        self.assertIn("const arrowTarget = (el, others) =>", живость)
        self.assertIn("if (btn && !others.some(c3 => btn.contains(c3)))",
                      живость)
        self.assertIn("if (parent2 && !others.some(c3 => parent2.contains(c3)))", живость)
        self.assertIn("[[leftArrows, -1, rightArrows],", живость)
        #: прежнего «родитель как придётся» не осталось
        self.assertNotIn('const цель = у.closest("button") || у.parentElement',
                         живость)

    def test_area_fill_is_visible_not_only_on_shift(self) -> None:
        """Заливка прямоугольником была, но о ней нельзя было узнать.

        Режим набора области жил ТОЛЬКО на Shift+клике: кнопки не было,
        `state.areaMode` не включал никто, в подсказках он не значился.
        Прежнее решение звучало как «третьего способа не выдумываем», и
        оно оказалось неверным: человек, глядя на канонные карты, где
        переходы лежат целыми блоками, сделал единственно возможный
        вывод — «у нас такого нет, надо размечать каждую клетку».

        Плюс резинка: между двумя углами не показывалось НИЧЕГО, и что
        именно зальётся, выяснялось только после второго щелчка.
        """
        живость = клиент('editor_live.js')
        self.assertIn('insertOwn(brushColumn, btn, "кисть-область"',
                      живость)
        self.assertIn("state.areaMode = !state.areaMode", живость)
        self.assertIn("Область — залить прямоугольник", живость)
        #: резинка рисуется и для клеток, и для проёма выхода
        self.assertIn("const first = state.exitArm ? state.exitCorner "
                      ": state.area;", живость)
        self.assertIn("const currentCell = hoverPoint && cellAt(hoverPoint);",
                      живость)

    def test_exit_brush_writes_records_not_bits(self) -> None:
        """«Выход с карты» — кисть, но пишет ЗАПИСИ переходов, а не бит.

        История в три поворота. Сперва кисть красила бит 0x1000 —
        пустышку: его нет ни в одной из 2 129 920 клеток канона, сборка
        его не читает, а у донора он значит «мягкую глушь». Кисть
        отключили и заменили инструментом «Обвести проём» — и пользователь
        справедливо спросил, зачем выдуманы странные механики, когда
        хочется «нажать как на глушь и выделять зону».

        Итог обоих уроков: кисть ВЕРНУЛАСЬ — тот же жест, что у глуши
        (клик, область, ПКМ снимает), — но под капотом она создаёт и
        удаляет ЗАПИСИ переходов (прямоугольники exits), а не трогает
        мёртвый бит. Назначение по умолчанию — глобальная карта (-1),
        как у подавляющего большинства канонных переходов; список
        «Новый выход» остаётся выбором для дверей между картами.
        """
        живость = клиент('editor_live.js')
        self.assertIn('"Выход": "exit"', живость)
        #: ветка кисти уходит в записи ДО общего пути битов
        self.assertIn('if (state.cellBrush === "exit")', живость)
        self.assertIn("async function exitBrushApply(", живость)
        self.assertIn('await api(`/maps/${state.map}/exits`, "POST"', живость)
        #: назначение по умолчанию — глобальная карта
        self.assertIn("return { map: -1, name: \"глобальная карта\" };",
                      живость)
        self.assertIn('<option value="-1" selected>глобальная карта',
                      живость)
        #: ПКМ убирает запись, в которую попала клетка
        self.assertIn("нет выхода — снимать нечего", живость)
        self.assertIn("function brushCardOf(nodeEl, card)", живость)

    def test_mockup_images_never_show_as_broken(self) -> None:
        """Серые значки поломки по всему редактору — картинки МАКЕТА.

        В дизайне 89 тегов ``img`` с ОТНОСИТЕЛЬНЫМ путём ``assets/…``.
        Страница отдаётся с ``/editor.html``, браузер просит
        ``/assets/…`` — там 404. Это и были «битые иконки» в составе
        кучи и в карточках тайла воды: не наши списки, а неподменённая
        вёрстка макета.

        Часть путей живёт в паке (``/content/assets/icons/52.png``
        отдаётся), выдуманных дизайнером — ``assets/obj/100.png`` — нет
        нигде. Поэтому два шага: перенести ссылку в пак, а если и там
        пусто — убрать картинку совсем. Пустое место честнее значка
        поломки: по нему решают, что сломан редактор.
        """
        живость = клиент('editor_live.js')
        макет = клиент('editor_design_raw.html')
        self.assertGreater(макет.count('src="assets/'), 50)
        self.assertIn("""doc2.querySelectorAll('img[src^="assets/"]')""",
                      живость)
        self.assertIn('im.setAttribute("src", "/content/" + '
                      'im.getAttribute("src"))', живость)
        self.assertIn("function hideBrokenImages(card)", живость)
        self.assertIn('im.style.visibility = "hidden"', живость)

    def test_water_type_offers_both_kinds(self) -> None:
        """Переключатель типа воды предлагал «Lake» и «Lake».

        Тип один на карту (канон: OR всех 512 байтов подложки; 0x80
        Lake стоит, 0x40 Stream течёт), и в макете это сегментная пара
        кнопок. Но цикл живых чисел искал ЛЮБУЮ подпись вида
        «Lake|Stream · 0xNN» и переписывал её в НЫНЕШНИЙ тип — то есть
        оба узла пары. Выходил выбор из одинакового: жмёшь вторую, а
        она та же самая.

        Теперь пара подписана по местам, щелчок ставит СВОЙ тип (а не
        переворачивает текущий), а прочие такие подписи — строки
        состояния — показывают нынешний.
        """
        живость = клиент('editor_live.js')
        self.assertIn("const setWaterType = async (isStream) =>", живость)
        self.assertIn('nodeEl.textContent = isStream ? "Stream · 0x40" '
                      ': "Lake · 0x80"', живость)
        self.assertIn("nodeEl.onclick = () => setWaterType(isStream)", живость)
        self.assertIn("for (const nodeEl of waterTypes.slice(2))", живость)
        #: слепого переворота больше нет
        self.assertNotIn("{ stream: !тек }", живость)

    def test_right_panel_can_be_collapsed(self) -> None:
        """Правая панель занимала треть экрана даже пустой.

        Инспектор нужен — там числа юнита, состав кучи, биты клетки, — но
        висит он всегда, в том числе когда не выбрано ничего, а карта в
        это время ужата. Язычок у края сворачивает его и отдаёт место
        холсту; выбор держится между экранами.

        ХОЛСТ НАДО ПЕРЕСНЯТЬ: канва держит прежний размер, и без сигнала
        «lv-переснять» сворачивание отдавало пустоту, а карта оставалась
        в старой рамке. Проверено живьём: холст 612 → 957 точек и обратно.
        """
        живость = клиент('editor_live.js')
        self.assertIn("function rightPanelFolding(card)", живость)
        self.assertIn("state.правойПанелиНет = !state.правойПанелиНет",
                      живость)
        self.assertIn('insertOwn(frameBox, tab2, "язычок-инспектора")',
                      живость)
        self.assertIn('?.dispatchEvent(new CustomEvent("lv-переснять"))',
                      живость)

    def test_map_exits_can_be_written(self) -> None:
        """Выходы карты — то, чем карты вообще связываются между собой.

        Сборка УЖЕ умела читать `map.json["exits"]`
        (builder._project_exits) и даже проверяла поля, но ручки ЗАПИСИ
        не существовало вовсе: во всём server.py выходы только читались
        из уже собранного пака. Кисть «Выход» на экране проходимости
        красит лишь бит клетки, а бит без записи перехода никуда не
        ведёт — то есть создавала видимость двери там, где двери нет.
        Связать две карты мышью было нельзя в принципе, а это
        единственное, без чего игры не существует.

        Прямоугольник нормализуем сами: человек тянет рамку мышью в
        любую сторону, и требовать от него порядка углов незачем.
        """
        from knyaz2.web import server
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            for num_, name_ in ((61, "61_odna"), (62, "62_drugaya")):
                (root_ / name_).mkdir()
                (root_ / name_ / "map.json").write_text(
                    json.dumps({"map_number": num_, "name": name_,
                                "origin": {"editor": True}}),
                    encoding="utf-8")
            with mock.patch.object(server, "PROJECT_MAPS", root_):
                # углы нарочно вывернуты — ручка обязана прибрать
                ok_, _, reply = server.editor_exit_save(61, {"add": {
                    "to_map": 62, "to_name": "Другая",
                    "row1": 90, "row2": 80, "col1": 20, "col2": 10,
                    "entry_row": 85, "entry_col": 15}})
                self.assertTrue(ok_)
                self.assertEqual(reply["index"], 0)
                door = reply["exits"][0]
                self.assertEqual(
                    (door["row1"], door["row2"],
                     door["col1"], door["col2"]), (80, 90, 10, 20))
                # дверь в никуда не заводится
                missing, нота, _ = server.editor_exit_save(61, {"add": {
                    "to_map": 250, "row1": 1, "row2": 2,
                    "col1": 1, "col2": 2}})
                self.assertFalse(missing)
                self.assertIn("250", нота)
                # без обязательных полей — тоже
                missing, нота, _ = server.editor_exit_save(
                    61, {"add": {"to_map": 62}})
                self.assertFalse(missing)
                for field in ("row1", "row2", "col1", "col2"):
                    self.assertIn(field, нота)
                # правка по месту и удаление
                ok_, _, reply = server.editor_exit_save(
                    61, {"index": 0, "to_name": "Берег"})
                self.assertTrue(ok_)
                self.assertEqual(reply["exits"][0]["to_name"], "Берег")
                ok_, _, reply = server.editor_exit_save(
                    61, {"index": 0, "removed": True})
                self.assertTrue(ok_)
                self.assertEqual(reply["count"], 0)
                # канон по-прежнему не пишется — через диспетчер
                (root_ / "19_kanon").mkdir()
                (root_ / "19_kanon" / "map.json").write_text(
                    json.dumps({"map_number": 19}), encoding="utf-8")
                missing, нота, _ = server.api_dispatch_post(
                    "/editor/api/maps/19/exits",
                    {"add": {"to_map": 62, "row1": 1, "row2": 2,
                             "col1": 1, "col2": 2}}, None)
                self.assertFalse(missing)
                self.assertIn("канон", нота)

    def test_exit_fields_match_what_the_builder_demands(self) -> None:
        """Ручка требует ровно те поля, без которых сборка падает.

        builder._project_exits кидает ContentBuildError, если у выхода
        нет to_map/row1/row2/col1/col2 — редактор обязан сказать об этом
        сразу, а не через минуту неудачной выпечки.
        """
        from knyaz2.web import server
        билдер = (КОРЕНЬ / 'knyaz2' / 'content' / 'builder.py').read_text(
            encoding='utf-8')
        self.assertIn(
            'for key in ("to_map", "row1", "row2", "col1", "col2")', билдер)
        self.assertEqual(set(server.EXIT_REQUIRED),
                         {"to_map", "row1", "row2", "col1", "col2"})

    def test_warband_number_is_remembered_between_clicks(self) -> None:
        """Отряд из нескольких бойцов собирался в РАЗНЫЕ отряды по одному.

        Первый клик заводил отряд и получал его номер от сервера, но
        номер не сохранялся: на следующий клик `state.place.side` снова
        оказывался строкой «hostile», и сервер заводил ЕЩЁ ОДИН отряд —
        190, 191, 192… по бойцу в каждом. Засаду из пятерых собрать было
        нельзя в принципе: пятеро одиночек не воюют как отряд, и зона
        агрессии у каждого своя. Живой прогон после правки: пять кликов
        подряд → пять юнитов, один отряд (side 190, одна запись
        editor_warbands_add); кнопка смены стороны начинает новый (191).
        """
        живость = клиент('editor_live.js')
        self.assertIn('side = obj.warband.side;', живость)
        self.assertIn('state.place.side = side;', живость)

    def test_delete_is_one_implementation(self) -> None:
        """Клавиша Delete и кнопка «Убрать» делают одно и то же.

        Реализаций было две, и обе неполные: кнопка не знала про декор,
        а клавиша вдобавок читала ТОЛЬКО state.picked — куча, выбранная
        строкой списка на 1g, живёт в state.pickedPile, и Delete по ней
        не делал ничего; хуже, путь для неё сваливался в
        `/objects/undefined`, потому что у кучи нет slot.

        Объект и декор различаются НЕ по полям (у обоих только slot), а
        по запомненному виду выбранного: удаление не по той ручке стёрло
        бы чужую запись в соседней таблице.
        """
        живость = клиент('editor_live.js')
        self.assertIn('await removePicked(', живость)
        self.assertIn('choose(what.вид, what.объект);', живость)
        self.assertIn('вид === "decor"', живость)
        self.assertIn('`/maps/${state.map}/overlays/${p2.slot}`', живость)
        # житель пака приходит из сборки — его так не убрать
        self.assertIn('kindOf === "packUnit" || kindOf === "packLoot"', живость)
        # второй, урезанной копии удаления больше нет
        self.assertIn('if (!selectedOf()) return;', живость)

    def test_decor_places_only_from_its_own_catalogue(self) -> None:
        """Декор ставится СВОИМ номером, а объект в режиме декора — нет.

        Номера у них из РАЗНЫХ таблиц: у объекта это гнездо T_OBJECTS
        (на карте 23: sprite 129 → resource_slot 159), у декора — индекс
        спрайта GRAPH в T_DYNAMIC (там же: 247…256). Пока своего каталога
        не было, постановка стояла закрытой нарочно: подставив первое
        вторым, редактор положил бы в карту заведомо чужой спрайт — молча,
        и заметить это можно было только собрав пак и посмотрев в игре.

        Теперь каталог есть (server.editor_decor_page), и уговор другой:
        кладём ровно то, что выбрано в каталоге ДЕКОРА, а взведённый
        объект в этом режиме отправляем обратно на свою вкладку.
        """
        живость = клиент('editor_live.js')
        # ставим номером самого декора, а не гнездом объекта
        self.assertIn("{ add: { id: state.place.id,", живость)
        self.assertNotIn('add: { id: state.place.slot, kind: 0,', живость)
        # объект в режиме декора не кладётся — человека зовут на вкладку
        self.assertIn('выбран объект, а вкладка — «Декор»', живость)
        # а перенос уже стоящего — на месте
        self.assertIn('{ slot: obj.slot, x: Math.round(obj.x)', живость)

    def test_maps_say_whether_they_are_editable(self) -> None:
        """Список карт и состояние карты называют, можно ли её править.

        В project/maps полторы сотни карт ОБЕИХ игр вперемешку со своими,
        и признака не было ни в списке, ни в состоянии. Человек открывал
        «Морской лагерь», видел полностью живой на вид редактор — кисти
        активны, каталог полон, вещь под мышью едет за курсором, — а на
        записи сервер отказывал (_канон_под_защитой), холст перечитывался
        и вещь прыгала назад. Единственным следом была строка мелким
        шрифтом в подвале. Со стороны это ровно «объекты не
        перемещаются, половина редактора не работает».
        """
        from knyaz2.web import server
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            канон = root_ / "19_chernyy_bor"
            канон.mkdir()
            (канон / "map.json").write_text(
                json.dumps({"map_number": 19, "name": "Чёрный Бор",
                            "origin": {"game": "Кровь Титанов", "map": 19}}),
                encoding="utf-8")
            own_one = root_ / "63_moya"
            own_one.mkdir()
            (own_one / "map.json").write_text(
                json.dumps({"map_number": 63, "name": "Моя",
                            "origin": {"editor": True}}), encoding="utf-8")
            with mock.patch.object(server, "PROJECT_MAPS", root_):
                ok_, _, reply = server.api_maps(root_)
                self.assertTrue(ok_)
                признак = {k_["map"]: k_["editable"] for k_ in reply["maps"]}
                self.assertEqual(признак, {19: False, 63: True})

    def test_canon_map_can_be_copied_into_an_editable_one(self) -> None:
        """Копия — ЕДИНСТВЕННЫЙ путь работать по образцу канонной карты.

        Канон правится только для чтения, и из этого следовал тупик:
        открыть «Морской лагерь», чтобы сделать по его образцу свою
        деревню, было можно, а сделать хоть что-нибудь — нет, оставалось
        начинать с пустого поля. Копия снимает тупик: та же карта со
        всеми слоями и объектами, но своя.

        Сторожим три вещи: копия помечена origin.editor (иначе она сразу
        попадёт под ту же защиту); прежнее происхождение сохранено, но
        НЕ рядом с editor (карта не может быть одновременно своей и «из
        игры»); черновой слой донора не тянется — иначе в свежей карте
        оказались бы чужие незапечённые правки.
        """
        from knyaz2.web import server
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            donor_rec = root_ / "19_chernyy_bor"
            donor_rec.mkdir()
            (donor_rec / "map.json").write_text(
                json.dumps({"map_number": 19, "name": "Чёрный Бор",
                            "origin": {"game": "Кровь Титанов", "map": 19},
                            "objects": {"records": [{"slot": 0}]}}),
                encoding="utf-8")
            (donor_rec / "grid.txt").write_text("проба", encoding="utf-8")
            (donor_rec / "scenario.json").write_text(
                json.dumps({"editor_units_add": [{"id": "unit_new_1"}]}),
                encoding="utf-8")
            with mock.patch.object(server, "PROJECT_MAPS", root_):
                ok_, path_str, reply = server.editor_map_copy(19, 63, "Моя копия")
                self.assertTrue(ok_, path_str)
                копия = root_ / reply["dir"]
                document = json.loads(
                    (копия / "map.json").read_text(encoding="utf-8"))
                self.assertTrue(document["origin"]["editor"])
                self.assertEqual(document["origin"]["copied_from"]["map"], 19)
                self.assertEqual(
                    document["origin"]["copied_from"]["was"]["game"],
                    "Кровь Титанов")
                self.assertNotIn("game", document["origin"])
                self.assertEqual(document["map_number"], 63)
                self.assertEqual(document["name"], "Моя копия")
                # слои донора переехали целиком
                self.assertEqual(document["objects"]["records"],
                                 [{"slot": 0}])
                self.assertEqual((копия / "grid.txt").read_text(
                    encoding="utf-8"), "проба")
                # а его черновик — нет
                self.assertEqual((копия / "scenario.json").read_text(
                    encoding="utf-8"), "{}")
                # копия правится, донор — по-прежнему нет
                self.assertTrue(server._editor_map(63))
                self.assertFalse(server._editor_map(19))
                # занятый номер не перезаписывается молча
                снова, нота, _ = server.editor_map_copy(19, 63, "Ещё")
                self.assertFalse(снова)
                self.assertIn("63", нота)

    def test_hit_test_uses_the_sprite_not_a_blind_box(self) -> None:
        """Попадание по вещи меряется КАРТИНКОЙ, а не квадратом вокруг
        невидимого якоря.

        Стояло «мировая точка не дальше 40 единиц от привязки записи».
        Спрайт же рисуется со смещением offset_x/offset_y от якоря и
        бывает много больше: живой замер на «Морском лагере» — дом 95x113
        со смещением (-24,-76), то есть тело уходит на 76 единиц ВВЕРХ,
        вдвое дальше старого порога. Схватить его можно было, только
        угадав пятую часть ширины возле точки, которую не видно. Тот же
        замер после правки: точка захвата нашлась на 53 единицы выше
        якоря — старый порог её не поймал бы.

        Проверок к тому же было ДВЕ, с разными допусками (40 в
        чтоПодТочкой и 60 в выбратьНаХолсте) и разными наборами вещей:
        выделение и перенос ловили разное. Сторожим, что осталась одна.
        """
        живость = клиент('editor_live.js')
        # грубая рамка по кадру, затем проба альфы — как unitAt игры
        self.assertIn('function pixelOpaque(img, sx, sy)', живость)
        self.assertIn('getImageData(0, 0, 1, 1).data[3] > 8', живость)
        self.assertIn('left: obj.x + rec.offset_x', живость)
        # канонная рамка тела берётся из клиента игры, а не с потолка
        self.assertIn('left: anchor.x - 30, top: anchor.y - 92', живость)
        game_name = клиент('units.js')
        self.assertIn('const BODY_HALF_WIDTH = 30;', game_name)
        self.assertIn('const BODY_HEIGHT = 92;', game_name)
        self.assertIn('const BODY_BELOW = 14;', game_name)
        # второй, конкурирующей проверки больше нет
        self.assertNotIn('Math.abs(о.x - т.x) < 60', живость)
        self.assertIn('const what = hitAt(pt, kinds);', живость)
        # инструмент ловит СВОЁ, а не всё подряд
        self.assertIn('"1b": ["object", "decor"]', живость)
        self.assertIn('"1f": ["unit", "packUnit"]', живость)
        self.assertIn('"1g": ["loot", "packLoot"]', живость)

    def test_bootstrap_does_not_stomp_early_navigation(self) -> None:
        """загрузитьДизайн() грузит editor_design_raw.html асинхронно
        (внешний <script src> lucide в editor.html может держать
        исполнение секундами) и раньше в конце БЕЗУСЛОВНО звала
        показать("1a"). Рой воспроизвёл (3 из 3 холодных перезагрузок):
        холст 1c создаётся и через секунды пропадает без замены, пока
        повторный показать('1c') не чинит его вручную. Живой повтор в
        этой сессии подтвердил мягче (1 из 3 попыток из-за variance
        сетевого таймингa инструментов) — но сама гонка реальна: если
        кто-то (тест, авто-переход, второй заход на уже открытой
        вкладке) звал показать(имя) РАНЬШЕ готовности дизайна, то либо
        (а) ранний вызов бил по пустому state.screens и тихо терял
        намерение без повтора, либо (б) он успевал сработать первым, а
        бутстрап всё равно сносил #stage обратно на «1a» следом. Один
        флаг «показанУспешноХотьРаз» лечит оба хвоста: не сносит уже
        показанный экран, и честно доигрывает то, что просили показать
        до готовности дизайна, вместо молчаливого умолчания на 1a.
        """
        живость = клиент('editor_live.js')
        self.assertIn('let shownOnce = false;', живость)
        self.assertIn('state.желаемыйЭкран = nm;', живость)
        self.assertIn(
            'if (!shownOnce) showScreen(state.желаемыйЭкран || "1a");',
            живость)

    def test_validator_header_pills_survive_icon(self) -> None:
        """Заголовок карточки 1i «2 ошибки»/«3 предупр.» несёт внутри
        иконку lucide (octagon-alert/triangle-alert) — childElementCount
        этих пилюль РАВЕН 1, а не 0, и старый фильтр «детей нет ровно»
        их не находил вовсе: цифры из макета так и оставались навсегда,
        противореча соседнему живому бейджу «валидатор: N · M». Пишем в
        текстовый узел, а не в textContent — иначе перезапись сносит
        саму иконку вместе с числом."""
        живость = клиент('editor_live.js')
        self.assertIn(
            'if (nodeEl.childElementCount <= 1 && /^\\d+\\s+ошиб/.test(pt))',
            живость)
        self.assertIn(
            'if (nodeEl.childElementCount <= 1 && /^\\d+\\s+предупр/.test(pt))',
            живость)
        self.assertIn('n.nodeType === 3 && n.nodeValue.trim()', живость)

    def test_play_opens_tab_before_awaiting(self) -> None:
        """играть() открывала вкладку ПОСЛЕ await api(...) — вызов
        window.open() тогда стоит уже вне стека клика, и часть браузеров
        (в первую очередь Chrome) не считает его жестом пользователя и
        молча режет всплывающее окно: кнопка «Play» выглядит так, будто
        не делает ничего. Открываем пустую вкладку синхронно, в самом
        обработчике клика, наводим её на адрес уже после ответа сервера.
        """
        живость = клиент('editor_live.js')
        m_ = re.search(
            r'async function playIt\(\) \{(.*?)\n\}', живость, re.S)
        self.assertIsNotNone(m_)
        payload = m_.group(1)
        self.assertLess(
            payload.index('window.open("", "_blank")'),
            payload.index('await api(`/play/'),
            "вкладка обязана открываться ДО await")
        self.assertIn('win.location = resp.redirect', payload)
        self.assertIn('win.close()', payload)

    def test_build_badge_and_draft_counter_are_live(self) -> None:
        """1h: значок «building» в шапке был раскрашен ОДИН РАЗ при
        полифиле StatusBadge и больше не трогался — горел «идёт» вечно,
        даже когда сборка давно кончилась или не запускалась вовсе.
        Счётчик «N слоёв правок поедут в пак» нёс два независимых бага:
        (драфт[k] || []).length молчаливо давало undefined для слоёв,
        которые лежат СЛОВАРЁМ (editor_loot — {id: запись}), а не
        массивом (editor_units_add) — словарь с настоящими правками не
        считался вовсе; и регекс поиска строки искал «N правки поедут»
        (текст макета), а сама же перезапись меняла его на «N слоёв
        правок поедут» — на повторном заходе на экран регекс не находил
        свою же прошлую запись, и счётчик застывал."""
        живость = клиент('editor_live.js')
        self.assertIn('function paintBuildBadge()', живость)
        self.assertIn('[data-live-badge="building"]', живость)
        self.assertIn('state.buildRunning = true', живость)
        self.assertIn(
            'const nonEmpty = (it) => Array.isArray(it) ? it.length > 0', живость)
        self.assertIn(
            '/^\\d+\\s+(слоёв\\s+)?правки?\\s+поедут/', живость)

    def test_camera_clamp_centers_instead_of_pinning(self) -> None:
        """ограничить() на слабом зуме (видимая область больше поля
        160x256 клеток целиком) зажимала камеру строго в 0 — Math.max(0,
        мир - видно) вырождался в 0, и камеру НАВСЕГДА пришпиливало к
        левому верхнему углу. И вписывание по занятому прямоугольнику
        (центрирует его на экране), и зум колесом к точке под курсором
        (честно считает сдвиг) — оба гасились этим зажимом обратно в
        угол: первый щелчок колеса «дёргал» карту на десяток с лишним
        клеток вместо зума на месте (живой замер: ~37 клеток из угла,
        ~11 — из естественного отдыха, то же по порядку величины, что
        видел рой). Раз содержимое не заполняет экран целиком —
        центрируем его, а не пришпиливаем к 0."""
        живость = клиент('editor_live.js')
        self.assertIn(
            'kindOf.x = seenW >= worldW ? (worldW - seenW) / 2', живость)
        self.assertIn(
            'kindOf.y = seenH >= worldH ? (worldH - seenH) / 2', живость)

    def test_cell_panel_uses_real_canvas_node(self) -> None:
        """жизнь1d брала границу левой панели у {рисуй,вид} — возврата
        вживитьХолст(), а не у canvas: TypeError на КАЖДОМ заходе на
        экран «Проходимость» (щёлкнуть тихо, ошибка в консоли есть, а
        «Ставить/Снимать», кисти и «область» не отвечали вовсе — весь
        код после сломанной строки просто не выполнялся). Сторожим и
        то, что панель клетки справа теперь читает настоящие биты
        (CELL_*_BIT), а не подписи из макета.
        """
        живость = клиент('editor_live.js')
        # холстDOM — ИМЕННО ТАК названная переменная — снимает
        # неоднозначность с одноимённым «холст» (возврат вживитьХолст,
        # {рисуй,вид}), у которого getBoundingClientRect нет вовсе
        self.assertIn(
            'const canvasDom = card.querySelector("canvas");', живость)
        self.assertIn('canvasDom.getBoundingClientRect().left', живость)
        self.assertIn('(lo & 0x0FFF) === 0x0FFF', живость)
        self.assertIn('Boolean(lo & 0x4000)', живость)
        self.assertIn('Boolean(lo & 0x8000)', живость)
        self.assertIn('hi & 0x1F', живость)

    def test_shared_value_row_helper_is_reused(self) -> None:
        """значениеРяда — общий якорь «подпись слева, значение справа»
        инспекторов 1c/1d/1b/1f/1g. Раньше каждая панель справа стояла
        вписанной в макет намертво (курсор в 1c, клетка в 1d, объект в
        1b, юнит в 1f, куча в 1g) — какую вещь ни выбери, цифры не
        менялись."""
        живость = клиент('editor_live.js')
        self.assertIn('function rowValue(card, label)', живость)
        for функция in ('refreshCursorPanel', 'refreshCellPanel',
                        'refreshObjectPanel', 'refreshUnitPanel',
                        'refreshPilePanel'):
            self.assertIn(f'function {функция}(', живость)

    def test_clone_handles_loot_piles(self) -> None:
        """«Дубль · Ins» на 1g читал только state.picked — у выбранной
        через список кучи (state.pickedPile) своего значения там нет
        вовсе, и кнопка не делала ничего. убратьВыбранное() уже брала
        оба поля (state.picked || state.pickedPile), клонировать() —
        только половину дела."""
        живость = клиент('editor_live.js')
        self.assertIn('const p2 = selectedOf();', живость)
        self.assertIn('const kindOf = pickKind();', живость)
        self.assertIn('if (kindOf === "loot") {', живость)

    def test_toggle_falls_back_to_leaf_node(self) -> None:
        """тумблер() поднимался к рамке-предку в поисках «своей строки»,
        а группа сегментов (2-3 пилюли тумблера) сама укладывалась в
        ≤3 детей — все сегменты красили ОДИН общий узел позади пилюль,
        и подсветка нигде не двигалась (1a/1b/1c/1f). Красим лист узла,
        когда рамка сегмента общая с соседом."""
        живость = клиент('editor_live.js')
        self.assertIn('const frameTally = new Map();', живость)
        self.assertIn('ownFrame ? aim.рамка : aim.узел', живость)

    def test_loot_status_does_not_race_pack_fetch(self) -> None:
        """список() на 1g зовёт собрать() → api('/pack'), а на
        несобранной карте это 400: api() САМА пишет в статус-строку
        «✗ карта … не собрана в пак» — общий побочный эффект на любую
        неудачу. Верный статус («куча выбрана», «клад N:M · 25 монет»)
        ставили ДО этого асинхронного вызова, и провал переписывал его
        секунду спустя. Статус теперь ставится ПОСЛЕ ожидания список().
        """
        живость = клиент('editor_live.js')
        # Перенос кучи ПРОСТЫМ КЛИКОМ с тех пор убран целиком (один жест
        # на весь редактор — удержание), и вместе с ним ушёл один из трёх
        # случаев гонки. Сторожим оставшиеся: статус ставится ПОСЛЕ
        # ожидания список(), а не до него.
        self.assertIn('await openMap(state.map); await list();',
                      живость)
        # выбор кучи строкой списка: сперва дожидаемся список(), и только
        # потом ставим подсказку (поле выбора с тех пор одно — см.
        # test_selection_is_one_notion)
        self.assertIn('await list();\n', живость)


class PlayFromHereTest(unittest.TestCase):
    """«Играть отсюда»: проба начинается с указанной клетки.

    Проба всегда шла из точки входа карты, а правка обычно в другом
    конце: на карте 64 до жителя было восемь десятков клеток, и дорога
    стоила дороже самой правки. Клетка указывается в редакторе, уезжает
    в адрес игры и там становится записью прибытия.
    """

    @staticmethod
    def _карта(root_: pathlib.Path) -> pathlib.Path:
        """Проектная карта: первая строка глухая, остальные свободны."""
        folder = root_ / "64_test"
        folder.mkdir()
        (folder / "map.json").write_text(json.dumps(
            {"map_number": 64, "origin": {"editor": True}}), encoding="utf-8")
        free = " ".join(["0000:0000"] * 160)
        wall = " ".join(["4FFF:0000"] * 160)
        (folder / "grid.txt").write_text(
            chr(10).join(["# шапка", wall, *([free] * 255)]) + chr(10),
            encoding="utf-8")
        return folder

    def test_address_carries_map_fresh_and_cell(self) -> None:
        from knyaz2.web import server
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            pack = root_ / "pack"
            (pack / "maps" / "64").mkdir(parents=True)
            (pack / "maps" / "64" / "map.json").write_text(
                "{}", encoding="utf-8")
            maps_ = root_ / "project"
            maps_.mkdir()
            self._карта(maps_)
            with mock.patch.object(server, "PROJECT_MAPS", maps_):
                ok_, note_, data_ = server.api_play(64, pack)
                self.assertTrue(ok_)
                # проба ВСЕГДА с новой партии: память карты сильнее пака
                self.assertEqual(data_["redirect"], "/?map=64&fresh=1")
                self.assertIn("НОВАЯ партия", note_)
                # с клеткой — она едет в адрес и названа в ответе
                ok_, note_, data_ = server.api_play(64, pack, (49, 30))
                self.assertTrue(ok_)
                self.assertEqual(data_["redirect"],
                                 "/?map=64&fresh=1&at=49,30")
                self.assertIn("49:30", note_)
                self.assertNotIn("глухая", note_)
                # глухая клетка не запрещена, но названа: клиент поставит
                # героя рядом, и человек должен знать об этом заранее
                ok_, note_, _ = server.api_play(64, pack, (0, 3))
                self.assertTrue(ok_)
                self.assertIn("глухая", note_)
                # вне поля 256x160 — отказ, а не молчаливая подстановка
                ok_, note_, _ = server.api_play(64, pack, (999, 1))
                self.assertFalse(ok_)
                self.assertIn("вне карты", note_)
                # несобранной карты нет и в пробе
                ok_, note_, _ = server.api_play(65, pack, (1, 1))
                self.assertFalse(ok_)
                self.assertIn("не собрана", note_)

    def test_arrival_cell_is_not_blocked_by_the_hero_himself(self) -> None:
        """Клетка прибытия проверяется БЕЗ самого героя.

        `heroFree(r, c)` без третьего довода считает занятой и ту клетку,
        где стоит сам игрок (units.js unitBlocks: «игрок держит клетку
        наравне со всеми»), — а строкой выше герой на неё и поставлен.
        Объезд включался НА КАЖДОМ входе на карту и уводил его на первого
        соседа кольца, то есть ровно на клетку вверх-влево: и после двери,
        и по «играть отсюда» (замер: просили 49:30 — вставал 48:29,
        просили 41:36 — вставал 40:35).
        """
        app = клиент('app.js')
        self.assertIn('if (!heroFree(hero.cell.row, hero.cell.col, hero))',
                      app)
        self.assertIn('if (heroFree(row, col, hero)) spot = { row, col };',
                      app)
        # клетка приезжает адресом и подставляется записью прибытия
        self.assertIn('request.get("at")', app)
        self.assertIn('? { row: spot[0], col: spot[1] } : null', app)

    def test_editor_chip_arms_pick_and_sends_cell(self) -> None:
        живость = клиент('editor_live.js')
        # орган рядом с Build/Play, своя метка на холсте, перехват щелчка
        self.assertIn('chip.dataset.lv = "старт-пробы"', живость)
        self.assertIn('if (state.playPick) {', живость)
        self.assertIn('setPlayFrom(cellAt(worldNum(ev)));', живость)
        self.assertIn('overCtx.fillText("▶ старт пробы"', живость)
        # клетка уходит в ручку пробы
        self.assertIn('`?row=${at.row}&col=${at.col}`', живость)
        # старт — свойство карты: другая карта его сбрасывает
        self.assertIn('state.playFrom = null;', живость)


class DialogInEditorTest(unittest.TestCase):
    """Свой диалог заводится из редактора, а не пятью шагами вручную.

    Руками это было: написать .QST, дописать `#include` в KONUNG2.QST,
    скомпилировать, найти номер в QUESTS.LOG и вписать его юниту.
    """

    def test_file_name_is_latin_and_unique(self) -> None:
        from knyaz2.web import server
        self.assertEqual(
            server._story_file_name("Житель_Малого_Бора", set()),
            "ZHITELMA.QST")
        # занятое имя не перезаписывается, а получает счётчик
        self.assertEqual(
            server._story_file_name("Житель_Малого_Бора",
                                    {"ZHITELMA.QST"}), "ZHITELM1.QST")
        # имя без латиницы вовсе — всё равно даёт годный файл
        self.assertEqual(server._story_file_name("!!!", set()), "QUEST.QST")

    def test_typography_is_normalised_and_rest_refused(self) -> None:
        """В cp866 нет длинного тире и многоточия — их правим сами.

        Замена однозначная, а вот всё прочее незаписуемое возвращаем
        человеку списком: молча портить чужой текст нельзя.
        """
        from knyaz2.web import server
        # кавычки-ёлочки в cp866 ЕСТЬ (0xAE/0xAF) — их не трогаем;
        # длинное тире и многоточие правим
        body, bad = server._cp866_text("Слышь — вот… «так»")
        self.assertEqual(body, 'Слышь - вот... "так"')
        self.assertEqual(bad, "")
        # английские кавычки приводятся к простым
        body, _ = server._cp866_text("он сказал “да”")
        self.assertEqual(body, 'он сказал "да"')
        # прочее незаписуемое — списком человеку, а не молча
        _, bad = server._cp866_text("çşğ")
        self.assertEqual(set(bad), set("çşğ"))

    def test_squad_number_is_counted_from_the_pack(self) -> None:
        """Довод «карты зачищена» — карта + 256×место отряда.

        Место считается по НЕ своим сторонам, отсортированным по
        возрастанию (mapstate.js mapSquads): на своей карте 64 мирный
        житель занимал место 0, а скелет — место 1, хотя враждебный
        отряд там один. Руками это первое, где ошибаются.
        """
        from knyaz2.web import server
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            folder = root_ / "maps" / "64"
            folder.mkdir(parents=True)
            (folder / "map.json").write_text(json.dumps({
                "warbands": [{"side": 0, "player": True},
                             {"side": 185}, {"side": 186}],
                "units": [{"side": 0}, {"side": 185}, {"side": 186}],
            }), encoding="utf-8")
            self.assertEqual(server._squad_index(64, 185, root_), 0)
            self.assertEqual(server._squad_index(64, 186, root_), 1)
            self.assertIsNone(server._squad_index(64, 190, root_))
            self.assertIsNone(server._squad_index(65, 185, root_))

    def test_new_dialog_writes_include_compiles_and_drops(self) -> None:
        """Круговой прогон на КОПИИ сюжета: завести и убрать.

        Ворота — сам M_QUEST: сюжет собирается целиком, номер берётся из
        его же лога. Убрать можно только последний диалог — иначе номера
        всех, кто за ним, сдвинутся, а `dialog_number` у юнитов
        останется прежним.
        """
        import shutil
        from knyaz2.web import server
        from konung2 import story
        if not (story.QUESTS_DIR.parent / "RESOURCE" / "M_QUEST.exe").is_file():
            self.skipTest("посылка k2_tools не на месте")
        if not (server.PROJECT_STORY / "qst").is_dir():
            self.skipTest("сюжет проекта не экспортирован")
        with tempfile.TemporaryDirectory() as tmp_dir:
            room = pathlib.Path(tmp_dir) / "story"
            shutil.copytree(server.PROJECT_STORY / "qst", room / "qst")
            (room / "files").mkdir()
            with mock.patch.object(server, "PROJECT_STORY", room), \
                 mock.patch.object(story, "STORY_DIR", room):
                ok_, note_, data_ = server.api_story_dialog_new(
                    {"name": "Проба_Из_Теста", "comment": "тест",
                     "greeting": "Здравствуй — путник…",
                     "answer": "И тебе."}, None)
                self.assertTrue(ok_, note_)
                file_name = data_["file"]
                self.assertEqual(file_name, "PROBAIZTE.QST"[:8] + ".QST")
                made = (room / "qst" / file_name).read_bytes().decode("cp866")
                # типографика правится, реплика на месте, конец разговора тоже
                self.assertIn("Здравствуй - путник...", made)
                self.assertIn("GOTO=END_OF_DIALOG", made)
                # включение дописано в проект сборки
                project = (room / "qst" / "KONUNG2.QST").read_bytes().decode(
                    "cp866")
                self.assertIn(f"#include {file_name.lower()}", project)
                # номер пришёл из лога компилятора и он последний
                numbers = story.script_numbers()
                self.assertEqual(data_["number"], numbers["Проба_Из_Теста"])
                self.assertEqual(data_["number"], max(numbers.values()))
                # второй раз тем же именем — отказ, а не тихая перезапись
                ok_, note_, _ = server.api_story_dialog_new(
                    {"name": "Проба_Из_Теста"}, None)
                self.assertFalse(ok_)
                self.assertIn("уже есть", note_)
                # канонный файл не отдаём на удаление
                ok_, note_, _ = server.api_story_dialog_drop("Воин_алкоголик")
                self.assertFalse(ok_)
                self.assertIn("только для чтения", note_)
                # свой — убирается вместе с включением
                ok_, note_, _ = server.api_story_dialog_drop("Проба_Из_Теста")
                self.assertTrue(ok_, note_)
                self.assertFalse((room / "qst" / file_name).is_file())
                self.assertNotIn(file_name.lower(),
                                 (room / "qst" / "KONUNG2.QST").read_bytes()
                                 .decode("cp866"))

    def test_saving_a_dialog_does_not_grow_the_file(self) -> None:
        """Повторное сохранение без правок не меняет файл.

        Разбор забирает хвост файла как есть, а вывод дописывает свой
        перевод строки: файл рос на байт с каждой правкой (замер до
        починки: 2112 → 2113 → 2114), а реплика «Доброго дня.» обрастала
        пустыми строками внутри {TEXT}.
        """
        from knyaz2.web import server
        хвост = server._story_file_tail
        self.assertTrue(хвост("{SCRIPT=Тест\n}\n").endswith("}\n\x1a"))
        # сколько ни повторяй — вид один
        раз = хвост("{SCRIPT=Тест\n}\n\n\n\x1a")
        self.assertEqual(раз, хвост(раз))
        self.assertEqual(раз, хвост(раз + "\n\n"))

    def test_dialog_save_cleans_typography(self) -> None:
        """Текст из браузера пишется в cp866, где нет тире и ёлочек.

        Сохранение падало прямо на `encode` невнятным «charmap codec
        can't encode character», и человек терял набранную реплику.
        """
        from knyaz2.web import server
        источник = server.api_story_dialog_save.__doc__ or ""
        self.assertIn("ворота", источник.lower())
        text = pathlib.Path(server.__file__).read_text(encoding="utf-8")
        # чистка стоит ДО рендера файла, а не после
        self.assertIn("nodes = _plain(nodes)", text)
        self.assertIn('return False, ("эти знаки не пишутся в cp866: "',
                      text)
        self.assertIn("_story_file_tail(render_file(document))", text)

    def test_editor_edits_the_whole_dialog_tree(self) -> None:
        """Панель правит секции, ответы и ветки, а не одни реплики."""
        живость = клиент('editor_live.js')
        self.assertIn('function drawDialogTree(host, tree, editable, redraw)',
                      живость)
        # состав дерева меняется кнопками
        self.assertIn('storyAdd("+ ответ"', живость)
        self.assertIn('storyAdd("+ ветка"', живость)
        self.assertIn('storyAdd("+ секция"', живость)
        self.assertIn('storyKill("убрать секцию"', живость)
        self.assertIn('storyKill("убрать ответ"', живость)
        # цель ответа выбирается из секций этого же диалога плюс конец
        self.assertIn('const STORY_END = "END_OF_DIALOG";', живость)
        self.assertIn('function storyTargets(nodes, current)', живость)
        # чужая цель (@вход библиотеки) не теряется
        self.assertIn('if (current && !all.includes(current)) all.push(current);',
                      живость)
        # канонный диалог только читается: поля и кнопка сохранения глухи
        self.assertIn('persist.disabled = !card2.own;', живость)
        self.assertIn('drawDialogTree(treeZone, d2, Boolean(card2.own), redrawTree)',
                      живость)

    def test_saving_a_dialog_refreshes_the_compiled_story(self) -> None:
        """Правка диалога обязана доехать до собранного сюжета.

        Ворота собирали сюжет в песочнице и брали оттуда только вердикт,
        а project/story/QUESTS.RES оставался прежним — пак печёт деревья
        именно из него, и правка, показанная в панели, В ИГРУ НЕ
        ПОПАДАЛА. Поймано живым прогоном: в собранной карте не оказалось
        ветки, добавленной пять минут назад.
        """
        import shutil
        from knyaz2.web import server
        from konung2 import story
        if not (story.QUESTS_DIR.parent / "RESOURCE" / "M_QUEST.exe").is_file():
            self.skipTest("посылка k2_tools не на месте")
        if not (server.PROJECT_STORY / "qst").is_dir():
            self.skipTest("сюжет проекта не экспортирован")
        with tempfile.TemporaryDirectory() as tmp_dir:
            room = pathlib.Path(tmp_dir) / "story"
            shutil.copytree(server.PROJECT_STORY / "qst", room / "qst")
            (room / "files").mkdir()
            with mock.patch.object(server, "PROJECT_STORY", room), \
                 mock.patch.object(story, "STORY_DIR", room):
                ok_, note_, data_ = server.api_story_dialog_new(
                    {"name": "Проба_Сборки", "greeting": "Здравствуй."},
                    None)
                self.assertTrue(ok_, note_)
                # правим реплику и записываем — RES обязан обновиться
                ok_, _, tree = server.api_story_dialog("Проба_Сборки")
                self.assertTrue(ok_)
                nodes = tree["nodes"]
                nodes[0]["reply"]["texts"][0]["text"] = "Другое слово."
                было = (room / "QUESTS.RES").read_bytes()
                ok_, note_, _ = server.api_story_dialog_save(
                    "Проба_Сборки", {"nodes": nodes})
                self.assertTrue(ok_, note_)
                стало = (room / "QUESTS.RES").read_bytes()
                self.assertNotEqual(было, стало,
                                    "собранный сюжет не обновился")
                self.assertIn("Другое слово.".encode("cp866"), стало)

    def test_journal_lines_are_editable_in_the_panel(self) -> None:
        """Строка журнала — это текст токена, и она правится.

        Задать её можно было только при заведении квеста: токенов в
        панели не было, и в журнал игрока уходило машинное
        «Имя_Диалога: задание взято.» с подчёркиваниями.
        """
        import shutil
        from knyaz2.web import server
        from konung2 import story
        if not (story.QUESTS_DIR.parent / "RESOURCE" / "M_QUEST.exe").is_file():
            self.skipTest("посылка k2_tools не на месте")
        if not (server.PROJECT_STORY / "qst").is_dir():
            self.skipTest("сюжет проекта не экспортирован")
        with tempfile.TemporaryDirectory() as tmp_dir:
            room = pathlib.Path(tmp_dir) / "story"
            shutil.copytree(server.PROJECT_STORY / "qst", room / "qst")
            (room / "files").mkdir()
            with mock.patch.object(server, "PROJECT_STORY", room), \
                 mock.patch.object(story, "STORY_DIR", room):
                pack = pathlib.Path(tmp_dir) / "pack"
                (pack / "maps" / "64").mkdir(parents=True)
                (pack / "maps" / "64" / "map.json").write_text(json.dumps({
                    "warbands": [{"side": 0, "player": True}, {"side": 186}],
                    "units": [{"side": 0}, {"side": 186}]}), encoding="utf-8")
                ok_, note_, _ = server.api_story_dialog_new(
                    {"name": "Проба_Журнала", "kind": "quest",
                     "map": 64, "side": 186}, pack)
                self.assertTrue(ok_, note_)
                ok_, _, tree = server.api_story_dialog("Проба_Журнала")
                # токены отдаются наружу вместе с деревом
                names = [z_["name"] for z_ in tree["tokens"]]
                self.assertEqual(names, ["ПРОБА_ЖУРНАЛА_ЗАДАНИЕ",
                                         "ПРОБА_ЖУРНАЛА_СДЕЛАНО"])
                tree["tokens"][0]["text"] = "МАЛЫЙ БОР. Своя строка журнала."
                # и принимаются обратно
                ok_, note_, _ = server.api_story_dialog_save(
                    "Проба_Журнала", {"nodes": tree["nodes"],
                                      "tokens": tree["tokens"]})
                self.assertTrue(ok_, note_)
                текст = (room / "qst" / "PROBAZHU.QST").read_bytes().decode(
                    "cp866")
                self.assertIn("МАЛЫЙ БОР. Своя строка журнала.", текст)
                self.assertNotIn("Проба_Журнала: задание взято.", текст)
                # имя записи проверяется, а не пишется как попало
                ok_, note_, _ = server.api_story_dialog_save(
                    "Проба_Журнала",
                    {"nodes": tree["nodes"],
                     "tokens": [{"name": "плохое имя", "text": "…"}]})
                self.assertFalse(ok_)
                self.assertIn("только буквы", note_)

    def test_editor_shows_journal_lines(self) -> None:
        живость = клиент('editor_live.js')
        self.assertIn('function drawDialogTokens(host, tree, editable, redraw)',
                      живость)
        self.assertIn('textContent: "Записи журнала"', живость)
        self.assertIn('storyAdd("+ запись"', живость)
        # уходят на сервер вместе с деревом
        self.assertIn('tokens: d2.tokens || []', живость)

    def test_editor_shows_dialogs_by_name(self) -> None:
        живость = клиент('editor_live.js')
        # список: номер, имя, пометка «свой» и «не в сборке»
        self.assertIn('function dialogLabel(d2)', живость)
        self.assertIn('d2.own ? "  ✎ свой" : ""', живость)
        # форма нового диалога и её ручка
        self.assertIn('function newDialogForm(host, onDone)', живость)
        self.assertIn('api("/story/dialog/new", "POST", body)', живость)
        # отряды для условия «зачищено» берутся с карты, свой не в счёт
        self.assertIn('function hostileBands()', живость)
        self.assertIn('mapBands().filter(band => !band.player)', живость)
        # инспектор юнита говорит именем, а не одним числом
        self.assertIn('talkRow.textContent = "разговор: "', живость)
        self.assertIn('+ Новый диалог для этого юнита', живость)
        # свой диалог можно убрать прямо из панели, с переспросом
        self.assertIn('drop.textContent = "Убрать этот диалог"', живость)
        self.assertIn('"Точно убрать? (нажмите ещё раз)"', живость)
        self.assertIn('encodeURIComponent(nm)}`, "DELETE")', живость)


class InspectorMeaningTest(unittest.TestCase):
    """Инспектор говорит смыслами, а не числами записи.

    «отряд 186», «0x4c», «диалог 152» и «направление 6» — за каждым из
    них надо было идти на другой экран или считать в уме.
    """

    def test_compass_is_taken_from_pack_steps(self) -> None:
        """Стороны света сняты с `hero.direction_steps`, а не выдуманы.

        Шаги пака: 0 (-58,0) влево, 2 (0,-32) вверх, 4 (58,0) вправо,
        6 (0,32) вниз — значит 0 запад, 2 север, 4 восток, 6 юг.
        Проверяем и подпись, и сами шаги в собранном паке: разъедется
        одно — тест поймает.
        """
        живость = клиент('editor_live.js')
        self.assertIn('const COMPASS = ["запад", "северо-запад", "север", '
                      '"северо-восток",', живость)
        pack = КОРЕНЬ / "content_build" / "shared.json"
        if not pack.is_file():
            self.skipTest("пак не собран")
        steps = json.loads(pack.read_text(encoding="utf-8"))[
            "hero"]["direction_steps"]
        self.assertEqual(steps[0], [-58, 0])     # 0 — на запад
        self.assertEqual(steps[2], [0, -32])     # 2 — на север
        self.assertEqual(steps[4], [58, 0])      # 4 — на восток
        self.assertEqual(steps[6], [0, 32])      # 6 — на юг

    def test_unit_panel_speaks_meanings(self) -> None:
        живость = клиент('editor_live.js')
        # вражда — свойство ОТРЯДА, и панель юнита говорит это вслух
        self.assertIn('function bandMeaning(band)', живость)
        self.assertIn('"нападает на игрока (правило ОТРЯДА, не бойца)"',
                      живость)
        # номер отряда для условия квеста считается, а не выводится в уме
        self.assertIn('function squadPlace(sideNum)', живость)
        self.assertIn('«зачищено» для него — <?all_killed:', живость)
        # порода, масть и разговор — именами
        self.assertIn('rowEl("кто",', живость)
        self.assertIn('function dialogNameOf(number)', живость)

    def test_card_title_anchor_survives_its_own_text(self) -> None:
        """Якорь заголовка карточки не должен терять сам себя.

        Он искал «Юнит · <одно слово>», а перерисовка без выбора писала
        туда «Юнит · не выбран» — и со следующего показа экрана заголовок
        не находился вовсе: строки под ним менялись, а он навсегда
        оставался «не выбран».
        """
        живость = клиент('editor_live.js')
        self.assertNotIn(r'/^Юнит\s*·\s*\S+$/', живость)
        self.assertIn(r'/^Юнит\s*·/.test(el.textContent.trim())', живость)
        self.assertIn('state.промахи.push("карточка юнита: заголовок")',
                      живость)

    def test_war_flags_and_checkboxes_stay_in_one_truth(self) -> None:
        """Байт войны и разобранные галочки — один факт, а не два.

        Патч писал только присланное: снятая галочка «нападает на игрока»
        оставляла war_flags=1, и наш клиент считал отряд мирным
        (units.js смотрит on_player), а вывоз в формат игры пишет БАЙТ
        (konung2/worlds.py) — в самой игре отряд остался бы враждебным.
        """
        from knyaz2.web import server
        band = {"on_player": True, "war_flags": 0x01}
        # галочка снята — гаснет и бит
        band["on_player"] = False
        server._band_war_sync(band, {"on_player": False})
        self.assertEqual(band["war_flags"], 0)
        self.assertFalse(band["can_fight"])
        # пришёл байт — пересчитались галочки
        band["war_flags"] = 0x05
        server._band_war_sync(band, {"war_flags": 0x05})
        self.assertTrue(band["on_player"])
        self.assertTrue(band["on_parties"])
        self.assertFalse(band["on_special"])
        self.assertTrue(band["can_fight"])
        # правка чужого поля войну не трогает
        before = dict(band)
        server._band_war_sync(band, {"count": 3})
        self.assertEqual(band, before)

    def test_decor_catalogue_comes_from_the_game_itself(self) -> None:
        """Словарь декора собирается из карт игры, а не придуман.

        Декор — это спрайт GRAPH.RES, положенный в T_DYNAMIC; своего
        каталога у него не было, и постановка стояла закрытой: номера
        объектов из ДРУГОЙ таблицы, и подстановка одного вместо другого
        молча клала бы в карту чужой спрайт.
        """
        from knyaz2.web import server
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ = pathlib.Path(tmp_dir)
            for name_, number, game, ids in (
                    ("7_a", 7, "canon", [110, 110, 254]),
                    ("9_b", 9, "canon", [110, 254]),
                    ("160_c", 160, "legend", [111])):
                folder = root_ / name_
                folder.mkdir()
                origin = {"editor": False}
                if game == "legend":
                    from konung2 import donor
                    origin["game"] = donor.LEGEND_NAME
                (folder / "map.json").write_text(json.dumps({
                    "map_number": number, "origin": origin,
                    "dynamic": {"records": [
                        {"slot": i, "id": z_} for i, z_ in enumerate(ids)]},
                }), encoding="utf-8")
            with mock.patch.object(server, "PROJECT_MAPS", root_), \
                 mock.patch.dict(server._DECOR_VOCABULARY, {}, clear=True):
                canon = server._decor_vocabulary("canon")
                # порядок — по частоте: чем чаще игра им пользуется, тем
                # он ближе к началу каталога
                self.assertEqual([z_["id"] for z_ in canon], [110, 254])
                self.assertEqual(canon[0]["count"], 3)
                self.assertEqual(canon[0]["maps"], [7, 9])
                # каталоги игр РАЗДЕЛЬНЫЕ: спрайты GRAPH у них свои, и
                # общий список положил бы на пустынную карту чужой берег
                legend = server._decor_vocabulary("legend")
                self.assertEqual([z_["id"] for z_ in legend], [111])

    def test_decor_is_drawn_from_the_project_not_only_the_pack(self) -> None:
        """Поставленный декор виден сразу, а не после сборки.

        Холст рисовал его ТОЛЬКО из пака (снимок последней сборки), и
        запись, легшая в project/maps, не появлялась на карте вовсе —
        «поставил декор, ничего не произошло».
        """
        живость = клиент('editor_live.js')
        self.assertIn('function decorRows()', живость)
        self.assertIn('const own = state.mapState?.overlays?.records;',
                      живость)
        # и рисование, и подбор под курсором идут из одного источника
        self.assertEqual(живость.count('for (const d2 of decorRows())'), 2)
        # постановка кладёт СЕРЕДИНУ под курсор, в запись — левый верхний угол
        self.assertIn('x: Math.round(pt.x - w2 / 2),', живость)
        self.assertIn('function loadDecorCatalog(game)', живость)
        # старый отказ убран: каталог есть
        self.assertNotIn("постановка декора ещё не готова", живость)

    def test_legend_objects_have_their_own_groups(self) -> None:
        """У второй игры своя разметка каталога, а не канонная.

        OBJECT.RES у «Продолжения легенды» свой: одно и то же гнездо
        означает у игр разные вещи (30 в каноне — двор-загон, в легенде —
        сруб избы), и общая таблица подписывала бы чужое. До разметки все
        579 записей легенды лежали одной кучей «прочее».

        Числа снизу — не украшение: разметка сделана глазами по
        контактным листам всего каталога, и пересмотр листом на группу
        поймал чужаков внутри полос (мост среди изб, валуны среди
        изгородей, навесы среди ворот, шесты лагеря среди деревьев).
        """
        from knyaz2.web import server
        # одно гнездо — разные вещи у разных игр
        self.assertEqual(server.object_group(30, "canon"), "yards")
        self.assertEqual(server.object_group(30, "legend"), "buildings")
        # находки пересмотра
        for slot, group in ((65, "piers"), (66, "bones"), (67, "props"),
                            (235, "rocks"), (513, "sheds"), (524, "props"),
                            (526, "trees"), (551, "camp"), (580, "east")):
            self.assertEqual(server.object_group(slot, "legend"), group,
                             f"гнездо {slot}")
        # восточный город — своя группа второй игры, у канона её нет
        self.assertNotIn("east", {server.object_group(z_, "canon")
                                  for z_ in range(30, 600)})
        labels = dict(server.OBJECT_GROUP_LABELS)
        self.assertEqual(labels["east"], "восточный город")
        # у каждой группы разметки есть подпись — иначе чип выйдет пустым
        for spots, group in server.LEGEND_OBJECT_GROUPS:
            self.assertIn(group, labels, group)
        # свалки «прочее» больше нет: у канона 1%, у легенды должно быть
        # столько же по порядку величины
        rest = sum(1 for z_ in range(30, 588)
                   if server.object_group(z_, "legend") == "props")
        self.assertLess(rest, 40, "слишком много осталось в «прочем»")

    def test_zone_labels_are_words_not_identifiers(self) -> None:
        """Подписи зон пострадали от переименования имён: в UI ушли
        «зонаОтрядов появления» и «зонаОтрядов гуляния» — склейка
        идентификатора со словом."""
        живость = клиент('editor_live.js')
        self.assertNotIn("зонаОтрядов", живость)
        self.assertNotIn("зонаСуществ", живость)
        self.assertIn('["zone", "зона появления"]', живость)


if __name__ == '__main__':
    unittest.main()
