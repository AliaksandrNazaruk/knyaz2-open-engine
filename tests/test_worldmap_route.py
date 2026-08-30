# -*- coding: utf-8 -*-
"""Маршрут по карте мира: дойти до перенесённой локации и оказаться в ней.

Проверка гоняет НАСТОЯЩИЙ knyaz2/web/static/worldmap.js через Node, а не
пересказ его правил на Python: иначе сверялись бы две наши выдумки, а не
код с данными. Из окружения модулю нужны только `world` и `contentUrl`, они
подменяются заглушками (tools/worldmap_route.js).

Чего проверка НЕ покрывает: вход в локацию и выход её краем — это уже
app.js и документ карты, для них нужен браузер.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tools" / "worldmap_route.js"
NODE = shutil.which("node")

#: Пробный пак с перенесёнными деревнями; собирается вручную, в проверке
#: не пересобирается — она про поведение, а не про сборку.
PACK = ROOT / "content_test_route"

needs_node = unittest.skipUnless(NODE, "нет node")
needs_pack = unittest.skipUnless(
    (PACK / "shared.json").is_file(), f"нет пробного пака {PACK.name}")


@needs_node
@needs_pack
class TestRouteToDonorVillages(unittest.TestCase):
    """От Борья до перенесённых деревень можно дойти ногами."""

    @classmethod
    def setUpClass(cls):
        rules = json.loads((PACK / "shared.json").read_text(encoding="utf-8"))
        cls.locations = sorted(
            {cell & 0xFF
             for row in rules["hero"]["rules"]["world_map"]["grid"]
             for cell in row if (cell & 0xFF) > 43}
            & {int(path.name)
               for path in (PACK / "maps").iterdir() if path.name.isdigit()})

    def test_pack_has_donor_villages(self):
        self.assertTrue(self.locations, "в паке нет ни одной перенесённой локации")

    def test_route_reaches_every_one(self):
        run = subprocess.run(
            [NODE, str(HARNESS), str(PACK), *map(str, self.locations)],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=600)
        self.assertEqual(run.returncode, 0,
                         f"маршрут не пройден:\n{run.stdout}\n{run.stderr}")
        for number in self.locations:
            with self.subTest(location=number):
                self.assertIn(f"({number})", run.stdout)
        self.assertIn("неудач: 0", run.stdout)


CELLS = ROOT / "tools" / "worldmap_cells.js"
BUILT = ROOT / "content_build"
needs_built = unittest.skipUnless(
    (BUILT / "shared.json").is_file(), f"нет собранного пака {BUILT.name}")


@needs_node
@needs_built
class TestSavedGridMeetsTheNewPack(unittest.TestCase):
    """Расклад локаций живёт в паке, туман — в сохранении.

    Клетка карты мира несёт и то и другое одним числом. Если при загрузке
    класть сохранённую сетку как есть, содержимое пака до начатой игры не
    доедет НИКОГДА, и молча: деревню перенесли на другую карту, а игрок
    по-прежнему входит в прежнюю. Именно так донорский Чёрный Бор остался бы
    невидимым у всех, кто уже играет.

    Гоняется настоящий worldmap.js через Node — как и маршрут выше.
    """

    def test_pack_wins_content_and_save_wins_progress(self):
        run = subprocess.run(
            [NODE, str(CELLS), str(BUILT)],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=600)
        self.assertEqual(run.returncode, 0,
                         f"перенос сетки сломан:\n{run.stdout}\n{run.stderr}")
        self.assertIn("неудач: 0", run.stdout)
        # Обе половины должны были отработать: без скрытых локаций вторая
        # молча пропускается, и правило про сюжет осталось бы непроверенным.
        self.assertIn("скрытая паком клетка", run.stdout)


AMBUSH = ROOT / "tools" / "worldmap_ambush.js"


@needs_node
@needs_built
class TestAmbushesStayInTheirGame(unittest.TestCase):
    """Чья земля — того и засада: отряды и место боя.

    Донорская половина карты мира несла канонные виды местности, и засада в
    пустыне уводила на русский лесной пруд. Теперь клетки размечены его
    видами (12…20), а его правило отличается от канонного дважды: класса
    опасности по телу героя у него нет, а место боя берётся из байта 2 самой
    клетки. Гоняется настоящий worldmap.js через Node.
    """

    def test_each_land_rolls_its_own_parties_and_scenes(self):
        run = subprocess.run(
            [NODE, str(AMBUSH), str(BUILT), "40000"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=600)
        self.assertEqual(run.returncode, 0,
                         f"засады ведут не туда:\n{run.stdout}\n{run.stderr}")
        self.assertIn("неудач: 0", run.stdout)
        # Обе половины должны были отработать НА ДЕЛЕ: если на одной из них
        # не выпало ни встречи, проверка прошла бы вхолостую.
        self.assertNotIn("встреч 0 из", run.stdout)


if __name__ == "__main__":
    unittest.main()
