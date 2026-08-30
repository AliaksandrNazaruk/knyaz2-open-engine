# -*- coding: utf-8 -*-
"""Свои наборы тварей: project/creatures/<имя> подшивается к канонным."""
from __future__ import annotations

import json
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from knyaz2.content import builder


def png(width: int, height: int) -> bytes:
    """Настоящий PNG — сборка читает из него размер по IHDR."""
    rows = b"".join(b"\x00" + b"\x00\x00\x00\x00" * width for _ in range(height))

    def chunk(tag: bytes, body: bytes) -> bytes:
        return (struct.pack(">I", len(body)) + tag + body
                + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows))
            + chunk(b"IEND", b""))


def canon_creatures() -> dict:
    """Кусок shared.json с одним канонным набором."""
    frame = {"sheet": 0, "x": 0, "y": 0, "width": 4, "height": 4,
             "offset_x": -2, "offset_y": -3}
    return {"sheets": [{"path": "assets/creatures/creature_0.png",
                        "width": 10, "height": 10, "indexed": True}],
            "sets": {"6": {"62": {"stand": [[dict(frame)] for _ in range(8)]}}}}


class PngSizeTest(unittest.TestCase):
    def test_size_comes_from_ihdr(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sheet.png"
            path.write_bytes(png(64, 32))
            self.assertEqual(builder._png_size(path), (64, 32))

    def test_not_a_png_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sheet.png"
            path.write_bytes(b"GIF89a" + b"\x00" * 32)
            with self.assertRaises(ValueError):
                builder._png_size(path)


class CustomCreatureLayerTest(unittest.TestCase):
    def make_set(self, project: Path, body: int = 200,
                 name: str = "sorceress") -> None:
        folder = project / "creatures" / name
        folder.mkdir(parents=True)
        (folder / "sheet.png").write_bytes(png(64, 32))
        frame = {"x": 1, "y": 2, "width": 8, "height": 16,
                 "offset_x": -4, "offset_y": -15}
        (folder / "set.json").write_text(json.dumps({
            "name": name, "body": body, "palette": "0", "sheet": "sheet.png",
            "poses": {"stand": [[dict(frame)] for _ in range(8)],
                      "walk": [[dict(frame)] for _ in range(8)]},
        }, ensure_ascii=False), encoding="utf-8")

    def test_own_set_lands_next_to_canon(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root, project = Path(folder) / "pack", Path(folder) / "project"
            root.mkdir()
            project.mkdir()
            self.make_set(project)
            out = builder._custom_creatures(root, project, canon_creatures())

            # лист подшит следующим номером, и кадры смотрят именно на него
            self.assertEqual(len(out["sheets"]), 2)
            sheet = out["sheets"][1]
            self.assertEqual(sheet["path"], "assets/creatures/custom_sorceress.png")
            self.assertEqual((sheet["width"], sheet["height"]), (64, 32))
            self.assertTrue((root / sheet["path"]).is_file())

            own = out["sets"]["200"]["0"]
            self.assertEqual(sorted(own), ["stand", "walk"])
            self.assertEqual([len(direction) for direction in own["stand"]], [1] * 8)
            self.assertEqual({shot["sheet"] for direction in own["stand"]
                              for shot in direction}, {1})
            # смещение донесено без правок: это якорь под ногами
            self.assertEqual(own["stand"][0][0]["offset_x"], -4)
            self.assertEqual(own["stand"][0][0]["offset_y"], -15)

            # канон не тронут ни листом, ни номером
            self.assertEqual(out["sets"]["6"]["62"]["stand"][0][0]["sheet"], 0)
            self.assertEqual(out["sheets"][0], canon_creatures()["sheets"][0])

    def test_two_sets_get_their_own_sheets(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root, project = Path(folder) / "pack", Path(folder) / "project"
            root.mkdir()
            project.mkdir()
            self.make_set(project, body=200, name="sorceress")
            self.make_set(project, body=201, name="barbarian")
            out = builder._custom_creatures(root, project, canon_creatures())
            self.assertEqual(len(out["sheets"]), 3)
            # у каждого набора свой номер листа, и они не совпадают
            numbers = {body: {shot["sheet"]
                              for direction in out["sets"][body]["0"]["stand"]
                              for shot in direction}
                       for body in ("200", "201")}
            self.assertEqual(len(numbers["200"]), 1)
            self.assertEqual(len(numbers["201"]), 1)
            self.assertNotEqual(numbers["200"], numbers["201"])

    def test_canon_body_cannot_be_taken(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root, project = Path(folder) / "pack", Path(folder) / "project"
            root.mkdir()
            project.mkdir()
            self.make_set(project, body=6)
            with self.assertRaises(ValueError):
                builder._custom_creatures(root, project, canon_creatures())

    def test_set_without_a_sheet_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root, project = Path(folder) / "pack", Path(folder) / "project"
            root.mkdir()
            project.mkdir()
            self.make_set(project)
            (project / "creatures" / "sorceress" / "sheet.png").unlink()
            with self.assertRaises(ValueError):
                builder._custom_creatures(root, project, canon_creatures())

    def test_set_without_poses_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root, project = Path(folder) / "pack", Path(folder) / "project"
            root.mkdir()
            project.mkdir()
            self.make_set(project)
            path = project / "creatures" / "sorceress" / "set.json"
            document = json.loads(path.read_text(encoding="utf-8"))
            document["poses"] = {}
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(ValueError):
                builder._custom_creatures(root, project, canon_creatures())

    def test_without_the_folder_nothing_changes(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "pack"
            root.mkdir()
            canon = canon_creatures()
            self.assertEqual(
                builder._custom_creatures(root, Path(folder) / "project", canon),
                canon)


class ShippedSorceressTest(unittest.TestCase):
    """Набор, который лежит в проекте, должен быть годным на вид."""

    ROOT = Path(__file__).resolve().parent.parent / "project" / "creatures"
    POSES = ("stand", "walk", "hit", "death_1", "rise", "attack")
    #: столько кадров в направлении держит таблица анимаций движка
    MAX_FRAMES = 18

    def test_every_shipped_set_fits_the_engine(self) -> None:
        if not self.ROOT.is_dir():
            self.skipTest("своих наборов в проекте нет")
        folders = [p for p in sorted(self.ROOT.iterdir()) if (p / "set.json").is_file()]
        if not folders:
            self.skipTest("своих наборов в проекте нет")
        for folder in folders:
            with self.subTest(folder.name):
                document = json.loads((folder / "set.json").read_text(encoding="utf-8"))
                width, height = builder._png_size(folder / document.get("sheet", "sheet.png"))
                self.assertGreaterEqual(int(document["body"]), 30,
                                        "тела 0…29 заняты канонными наборами")
                poses = document["poses"]
                for pose in self.POSES:
                    self.assertIn(pose, poses, "поза движка должна быть в наборе")
                for pose, directions in poses.items():
                    self.assertEqual(len(directions), 8, f"{pose}: направлений не восемь")
                    for index, frames in enumerate(directions):
                        self.assertTrue(frames, f"{pose}[{index}]: пусто")
                        self.assertLessEqual(len(frames), self.MAX_FRAMES,
                                             f"{pose}[{index}]: кадров больше таблицы")
                        for shot in frames:
                            self.assertLessEqual(shot["x"] + shot["width"], width,
                                                 f"{pose}[{index}]: кадр за листом")
                            self.assertLessEqual(shot["y"] + shot["height"], height,
                                                 f"{pose}[{index}]: кадр за листом")
                            # якорь под ногами: верхний угол выше и левее точки
                            self.assertLess(shot["offset_y"], 0)


class CustomHeroChoiceTest(unittest.TestCase):
    """Свой персонаж встаёт РЯДОМ с канонными, а не поверх них."""

    @staticmethod
    def canon_choices() -> list:
        template = {"body": 0, "palette": 70, "face": 0, "world": 0,
                    "characteristics": [10, 10, 10, 10, 10, 21], "level": 1}
        return [{"slot": 0, "world": 0, "game": "canon", "map": 33,
                 "name": "Ратибор", "story": "...", "template": dict(template)},
                {"slot": 1, "world": 1, "game": "legend", "map": 169,
                 "name": "Велиславна", "story": "...",
                 "template": {**template, "world": 1, "palette": 80}}]

    def make_playable(self, project: Path, world: int = 0) -> None:
        folder = project / "creatures" / "sorceress"
        folder.mkdir(parents=True)
        (folder / "sheet.png").write_bytes(png(16, 16))
        frame = {"x": 0, "y": 0, "width": 8, "height": 8,
                 "offset_x": -4, "offset_y": -7}
        (folder / "set.json").write_text(json.dumps({
            "name": "sorceress", "title": "Волшебница", "body": 200, "palette": "0",
            "sheet": "sheet.png",
            "poses": {"stand": [[dict(frame)] for _ in range(8)]},
            "playable": {"name": "Волшебница", "story": "пришлая", "world": world,
                         "breed": 0x40,
                         "characteristics": {"Ловкость": 50, "Выносливость": 50}},
        }, ensure_ascii=False), encoding="utf-8")

    def test_canon_choices_are_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder) / "project"
            project.mkdir()
            self.make_playable(project)
            canon = self.canon_choices()
            out = builder._custom_hero_choices(project, self.canon_choices())
            self.assertEqual(len(out), len(canon) + 1)
            self.assertEqual(out[:len(canon)], canon)

    def test_own_slot_carries_the_set(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder) / "project"
            project.mkdir()
            self.make_playable(project)
            own = builder._custom_hero_choices(project, self.canon_choices())[-1]
            self.assertEqual(own["slot"], 2)
            self.assertEqual(own["name"], "Волшебница")
            template = own["template"]
            self.assertEqual(template["body"], 200)
            self.assertEqual(template["palette"], 0)
            # без бита твари отрисовка пойдёт слоями и тела не найдёт
            self.assertTrue(template["breed"] & 0x40)
            # мир остаётся базовым: своего населения у нового слота нет
            self.assertEqual(template["world"], 0)
            # а слот в шаблоне нужен подписи под курсором
            self.assertEqual(template["slot"], 2)

    def test_speed_comes_from_characteristics(self) -> None:
        """Скорость героя движок считает сам; правим не формулу, а героя."""
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder) / "project"
            project.mkdir()
            self.make_playable(project)
            own = builder._custom_hero_choices(project, self.canon_choices())[-1]
            traits = own["template"]["characteristics"]
            agility, stamina = traits[1], traits[5]
            self.assertEqual(min(2, (agility + stamina) // 50), 2,
                             "сумма ловкости и выносливости должна давать потолок 2")

    def test_unknown_base_world_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder) / "project"
            project.mkdir()
            self.make_playable(project, world=7)
            with self.assertRaises(ValueError):
                builder._custom_hero_choices(project, self.canon_choices())

    def test_set_without_playable_adds_nobody(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder) / "project"
            project.mkdir()
            self.make_playable(project)
            path = project / "creatures" / "sorceress" / "set.json"
            document = json.loads(path.read_text(encoding="utf-8"))
            del document["playable"]
            path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
            canon = self.canon_choices()
            self.assertEqual(builder._custom_hero_choices(project, canon), canon)


if __name__ == "__main__":
    unittest.main()
