# -*- coding: utf-8 -*-
"""Погода: project/weather/<имя> подшивается в shared.json.

У канона погоды нет вовсе (в KONUNG2.EXE ни дождя, ни снега), поэтому весь
слой наш. Закон снят с Diablo II — разбор в docs/RAIN.md.
"""
from __future__ import annotations

import contextlib
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


def кадр(x: int, size: int) -> dict:
    return {"x": x, "y": 0, "width": size, "height": size,
            "offset_x": -size // 2, "offset_y": -size // 2}


class WeatherSetTest(unittest.TestCase):
    @contextlib.contextmanager
    def собрать(self, document: dict | None, *, sheet: bool = True):
        """Прогнать шаг сборки на времянке.

        Именно менеджер контекста, а не простая функция: времянка живёт до
        конца проверки. С `return` из-под `with` папку сносило РАНЬШЕ, чем
        тест успевал заглянуть в неё за листом.
        """
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "pack"
            project = Path(raw) / "project"
            root.mkdir()
            folder = project / "weather" / "rain"
            folder.mkdir(parents=True)
            if sheet:
                (folder / "sheet.png").write_bytes(png(64, 16))
            if document is not None:
                (folder / "set.json").write_text(
                    json.dumps(document, ensure_ascii=False), encoding="utf-8")
            yield builder._custom_weather(root, project), root

    def test_набор_попадает_в_общий_список(self) -> None:
        """Имя, лист и размеры доезжают до клиента."""
        with self.собрать({
            "name": "rain", "title": "Круги по воде", "sheet": "sheet.png",
            "sizes": [[кадр(0, 16), кадр(16, 16)], [кадр(32, 8)]],
        }) as (out, _):
            self.проверить_набор(out)

    def проверить_набор(self, out) -> None:
        self.assertIn("rain", out["sets"])
        набор = out["sets"]["rain"]
        self.assertEqual(набор["title"], "Круги по воде")
        self.assertEqual(len(набор["sizes"]), 2)
        self.assertEqual(len(набор["sizes"][0]), 2)
        #: лист один и пронумерован, кадры на него ссылаются
        self.assertEqual(len(out["sheets"]), 1)
        self.assertEqual(out["sheets"][0]["width"], 64)
        for полоса in набор["sizes"]:
            for frame in полоса:
                self.assertEqual(frame["sheet"], 0)

    def test_сложение_по_умолчанию(self) -> None:
        """Кольцо нарисовано серой лесенкой, значит подсвечивает, а не мажет.

        В исходнике Diablo цвета колец — чистые серые 12…132. Серое поверх
        сцены имеет смысл только сложением; обычной альфой на тёмной земле
        выходит грязное пятно. Поэтому умолчание тут не «normal», как у
        снарядов, а именно «additive».
        """
        with self.собрать({"name": "rain", "sizes": [[кадр(0, 16)]]}) as (out, _):
            self.assertEqual(out["sets"]["rain"]["blend"], "additive")

    def test_размеров_должен_быть_хоть_один(self) -> None:
        for плохие in ([], [[]]):
            with self.assertRaises(ValueError):
                with self.собрать({"name": "rain", "sizes": плохие}):
                    pass

    def test_без_листа_не_собирается(self) -> None:
        with self.assertRaises(ValueError):
            with self.собрать({"name": "rain", "sizes": [[кадр(0, 16)]]},
                              sheet=False):
                pass

    def test_пустая_папка_ничего_не_ломает(self) -> None:
        """Нет set.json — шаг просто молчит, а не падает."""
        with self.собрать(None) as (out, _):
            self.assertEqual(out, {})

    def test_лист_ложится_в_пак(self) -> None:
        with self.собрать({"name": "rain", "sizes": [[кадр(0, 16)]]}) as (out, root):
            путь = root / out["sheets"][0]["path"]
            self.assertTrue(путь.is_file(), f"листа нет в паке: {путь}")


class ЗаконДождяТест(unittest.TestCase):
    """Дождь — это ветка АКТОВ 1–4, а кольцо лежит под землёй.

    Обе проверки написаны по следам живых ошибок, а не «на всякий случай».
    """

    def клиент(self, name: str) -> str:
        root = Path(__file__).resolve().parents[1]
        return (root / "knyaz2" / "web" / "static" / name).read_text(encoding="utf-8")

    def test_перенесён_дождь_а_не_снег(self) -> None:
        """Погодный код Diablo раздвоен флагом [0x7A8A14] = «это акт 5».

        Первый перенос прошёл по ветке с НЕнулевым флагом, то есть по снегу:
        скорость `8 + 28·глубина` (VA 0x47319E) и форма `7·глубина` из
        таблицы 0x6D6E78 (VA 0x4731B3). Дождь — другая ветка (VA 0x4731FC):
        длина `4 + 8·глубина` и скорость `15 + 15·глубина`.
        """
        текст = self.клиент("weather.js")
        начало = текст.index("function родить(")
        тело = текст[начало:текст.index("export function streaksTick(")]
        self.assertIn("4 + Math.floor(8 * глубина)", тело)
        self.assertIn("15 + Math.floor(15 * глубина)", тело)
        # снежные числа не должны вернуться в КОД (в пояснениях они уместны)
        self.assertNotIn("8 + 28", тело)
        self.assertNotIn("глубина * 7", тело)
        self.assertNotIn("ФОРМЫ[", текст)

    def test_оттенок_капли_жребием_из_двенадцати(self) -> None:
        """Яркость капли — жребий из 12 (VA 0x473213), не глубина.

        По глубине оттенок берёт снежная ветка (VA 0x473006, `1.5·форма`).
        """
        текст = self.клиент("weather.js")
        self.assertIn("Array.from({ length: 12 }", текст)
        self.assertIn("Math.random() * ЛЕСЕНКА.length", текст)

    def test_кольца_рисуются_до_земли(self) -> None:
        """Кольцо лежит НА ВОДЕ, а вода — нижний слой кадра.

        Земля кладётся поверх подложки со своей прозрачностью, значит и
        кольцо обязано уходить под неё. Рисовал после `renderGround` —
        круги шли поверх берега, в том числе по суше.
        """
        текст = self.клиент("scene.js")
        подложка = текст.index("for (const cell of world.underlay)")
        кольца = текст.index('probe(". дождь", renderRain)')
        земля = текст.index("probe(\". земля\", () => renderGround(visible))")
        self.assertLess(подложка, кольца, "кольца сеются раньше подложки")
        self.assertLess(кольца, земля, "кольца рисуются поверх земли")

    def test_густота_колец_по_площади_экрана(self) -> None:
        """Плитка у них ЭКРАННАЯ (160x80), а клетка у нас мировая.

        Без множителя зума густота колец ездила от приближения, причём
        наоборот здравому смыслу: вблизи их становилось меньше.
        """
        текст = self.клиент("weather.js")
        начало = текст.index("function born(")
        конец = текст.index("export function weatherTick(")
        тело = текст[начало:конец]
        self.assertIn("size * view.zoom", тело)


if __name__ == "__main__":
    unittest.main()
