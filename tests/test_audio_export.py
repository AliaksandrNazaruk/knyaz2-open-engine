# -*- coding: utf-8 -*-
"""Экспорт звука в пак: Opus, реестры, инкрементальность, блок карты.

Полный прогон (494 слота и 1245 реплик) — дело сборки; здесь всё то же
самое проверяется на выборке: короткий синус, пара слотов, одна реплика.
"""
from __future__ import annotations

import json
import math
import os
import struct
import tempfile
import unittest
from pathlib import Path

from konung2 import sounds
from konung2.paths import game_file
from konung2.sounds import SoundsRes
from knyaz2.content import audio as audio_assets

GAME_AVAILABLE = os.path.isfile(game_file("SOUNDS.RES"))
needs_game = unittest.skipUnless(GAME_AVAILABLE, "игра недоступна: нет SOUNDS.RES")


class EncodeOpusTest(unittest.TestCase):
    def test_sine_roundtrip_duration(self) -> None:
        rate, seconds = 22050, 0.5
        count = int(rate * seconds)
        pcm = b"".join(struct.pack("<h", int(12000 * math.sin(2 * math.pi * 440 * i / rate)))
                       for i in range(count))
        with tempfile.TemporaryDirectory() as home:
            destination = Path(home) / "sine.opus"
            measured = audio_assets.encode_opus(pcm, rate, 1, 48, destination)
            self.assertAlmostEqual(measured, seconds, places=3)
            self.assertTrue(destination.is_file())
            self.assertLess(destination.stat().st_size, len(pcm) // 2,
                            "Opus обязан быть кратно меньше PCM")


@needs_game
class PackAudioTest(unittest.TestCase):
    SLOTS = (6, 24)          # щелчок интерфейса и трек Чёрного Бора

    def test_export_registry_and_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            root = Path(home)
            base = audio_assets.export_pack_audio(root, slots=self.SLOTS)

            sfx = root / "assets" / "sfx" / "006.opus"
            track = root / "assets" / "audio" / "track_024.opus"
            self.assertTrue(sfx.is_file() and track.is_file())

            index = json.loads((root / "assets" / "audio.json").read_text("utf-8"))
            self.assertEqual(index["encoder"]["codec"], "libopus")
            self.assertEqual(index["rules"]["mixer"]["max_buffers"], 45)
            self.assertEqual(set(index["slots"]), {"6", "24"})
            self.assertEqual(index["slots"]["24"]["path"],
                             "assets/audio/track_024.opus")

            # длительность из реестра совпадает с PCM-исходником
            res = SoundsRes.from_game()
            for slot in self.SLOTS:
                self.assertAlmostEqual(index["slots"][str(slot)]["seconds"],
                                       res.duration(slot), delta=0.01)

            # трек попал в список для клиента
            self.assertEqual([track["slot"] for track in base["tracks"]], [24])

            # повторный вызов ничего не перекодирует
            stamps = (sfx.stat().st_mtime_ns, track.stat().st_mtime_ns)
            audio_assets.export_pack_audio(root, slots=self.SLOTS)
            self.assertEqual((sfx.stat().st_mtime_ns, track.stat().st_mtime_ns),
                             stamps)

    def test_voice_line_export(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            root = Path(home)
            registry = audio_assets.export_voice_lines(root, lines=(1,))
            self.assertEqual(set(registry["lines"]), {"1"})
            line = registry["lines"]["1"]
            self.assertEqual(line["path"], "assets/voices/0001.opus")
            self.assertTrue((root / line["path"]).is_file())
            self.assertEqual(registry["base_rate"], 22050)

    def test_previous_pack_files_are_copied_not_encoded(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            old_root, new_root = Path(home) / "old", Path(home) / "new"
            audio_assets.export_pack_audio(old_root, slots=(6,))
            source = old_root / "assets" / "sfx" / "006.opus"
            stamp = source.stat().st_mtime_ns

            audio_assets.export_pack_audio(new_root, previous=old_root, slots=(6,))
            copied = new_root / "assets" / "sfx" / "006.opus"
            self.assertTrue(copied.is_file())
            # копия байт в байт, а исходник не тронут
            self.assertEqual(copied.read_bytes(), source.read_bytes())
            self.assertEqual(source.stat().st_mtime_ns, stamp)


@needs_game
class MapAudioBlockTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        res = SoundsRes.from_game()
        cls.occupied = {i for i, e in enumerate(res.entries) if e and e[1] > 1}
        cls.base = {"occupied": cls.occupied, "tracks": [],
                    "index": "assets/audio.json"}

    def test_black_bor_block(self) -> None:
        block = audio_assets.map_audio_block(19, self.base)
        self.assertEqual(block["map_track"], 24)
        self.assertFalse(block["ambient"]["cave"])

        eight = set(sounds.ambient_slots(19))
        day, night = set(block["ambient"]["day"]), set(block["ambient"]["night"])
        self.assertEqual(day | night, eight & self.occupied)
        night_from = sounds.ambient_slots(19).start + sounds.AMBIENT_NIGHT_OFFSET
        self.assertTrue(all(slot < night_from for slot in day))
        self.assertTrue(all(slot >= night_from for slot in night))

        preload = set(block["preload"])
        self.assertLessEqual(day | night, preload)
        # принудительные записи 14 и 15 (0x43DF48) — их занятые слоты в списке
        for record in sounds.PRELOAD_FORCED_RECORDS:
            expected = set(sounds.creature_preload_slots(record)) & self.occupied
            self.assertLessEqual(expected, preload, f"запись {record}")
        # все слоты предзагрузки реально существуют в SOUNDS.RES
        self.assertLessEqual(preload, self.occupied)

    def test_underground_map_has_no_day_night_split(self) -> None:
        block = audio_assets.map_audio_block(1, self.base)
        self.assertTrue(block["ambient"]["cave"])
        # у карт 1…5 амбиент в данных не записан
        self.assertEqual(block["ambient"]["day"], [])
        self.assertEqual(block["ambient"]["night"], [])


if __name__ == "__main__":
    unittest.main()
