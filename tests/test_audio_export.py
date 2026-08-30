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
            # ЗВУК ДВУХ ИГР ЕДЕТ РЯДОМ. Наборы под общими номерами разные:
            # из 376 общих слотов не совпал байт в байт ни один, поэтому
            # донорский лежит под ключом `legend:<слот>` и своими файлами.
            from konung2 import donor
            ждём = {"6", "24"}
            if donor.available():
                ждём |= {"legend:6", "legend:24"}
                self.assertTrue((root / "assets" / "sfx"
                                 / "legend_006.opus").is_file())
                # У ДОНОРА МУЗЫКА В ДРУГИХ СЛОТАХ — 28…39, а не канонных
                # 20…30. Формат задаёт место вызова в движке: его музыку
                # заводит FUN_0042FED4 (обёртка FUN_0041FA40 зовёт её как
                # `слот + 0x1C`), и там же стереоформат 44100. Пока набор
                # брался канонный, его слот 24 ехал «дорожкой» в стерео и
                # выходил обрывком на 0.23 с — закольцованным навсегда.
                self.assertEqual(index["slots"]["legend:24"]["path"],
                                 "assets/sfx/legend_024.opus")
                self.assertNotEqual(index["slots"]["legend:6"]["pcm_sha"],
                                    index["slots"]["6"]["pcm_sha"])
            self.assertEqual(set(index["slots"]), ждём)
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

    def test_donor_map_takes_the_donor_ambient_base(self) -> None:
        """База восьмёрки амбиента у донора 300, а не канонные 256.

        Очереди загрузки у двух игр одинаковы с точностью до одного числа:
        канон `n + (карта−1)*8 + 0x100` (0x43DF48), донор `+ 300`
        (0x4417E0). Пока применялась канонная база, его карты озвучивались
        слотами на 44 раньше своих — чужими короткими вскриками помногу
        подряд (жалоба 17.08.2026, поймана хвостом sound.recent).

        Данные с дизасмом согласны независимо: с базой 300 полных восьмёрок
        у его карт 39 против 35, пустых 12 против 15.
        """
        from konung2 import donor
        if not donor.available():
            self.skipTest("донор недоступен")
        self.assertEqual(sounds.ambient_base(), 0x100)
        self.assertEqual(sounds.ambient_base("legend"), 300)
        # Его карта 14 «Военный лагерь Повелителя» — та самая, где слышали.
        self.assertEqual(sounds.ambient_slots(14, "legend").start, 404)
        self.assertEqual(sounds.ambient_slots(14).start, 360)

        base = {**self.base, "legend_occupied": self.occupied,
                "legend_tracks": []}
        block = audio_assets.map_audio_block(164, base, "legend", 14, False)
        eight = set(block["ambient"]["day"]) | set(block["ambient"]["night"])
        self.assertTrue(eight <= set(range(404, 412)),
                        f"амбиент взят не из его восьмёрки: {sorted(eight)}")
        self.assertLessEqual(eight, set(block["preload"]),
                             "восьмёрка не попала в предзагрузку")

    def test_donor_map_takes_the_donor_track_rule(self) -> None:
        """У донорской карты и правило выбора трека его, и слоты его.

        Канонное правило (0x437F48) выдаёт номер из канонного музыкального
        диапазона 20…30, а в донорском наборе под этими номерами лежат
        звуковые эффекты: слот 24 у него — 0.23 секунды. Закольцованный, он и
        давал «музыка зависает» на каждой перенесённой карте.

        Правило донора — 0x43BC94: поселение звучит слотом 0x20 (+ культура),
        дикая земля с битом 0 признаков локации — 0x23, прочее — 0x26,
        и отдельно карты 1, 2, 5, 29.
        """
        from konung2 import donor
        if not donor.available():
            self.skipTest("донор недоступен")
        base = {**self.base, "legend_occupied": self.occupied,
                "legend_tracks": []}
        # 169 = его 19 «Черный Бор», поселение
        village = audio_assets.map_audio_block(169, base, "legend", 19, True)
        self.assertEqual(village["map_track"], sounds.LEGEND_VILLAGE_TRACK_BASE)
        # 209 = его 59 «Берег», не поселение и с флагом
        self.assertTrue(donor.location_track_flag(59))
        wild = audio_assets.map_audio_block(209, base, "legend", 59, False)
        self.assertEqual(wild["map_track"], sounds.LEGEND_TRACK_FLAGGED)
        # 153 = его 3, не поселение и без флага
        self.assertFalse(donor.location_track_flag(3))
        plain = audio_assets.map_audio_block(153, base, "legend", 3, False)
        self.assertEqual(plain["map_track"], sounds.LEGEND_TRACK_PLAIN)
        # особые карты — прямо из FUN_0043BC94
        for native, track in sounds.LEGEND_TRACK_BY_MAP.items():
            with self.subTest(native=native):
                block = audio_assets.map_audio_block(
                    150 + native, base, "legend", native, False)
                self.assertEqual(block["map_track"], track)
        # и все они — из ЕГО музыкального диапазона
        for block in (village, wild, plain):
            self.assertIn(block["map_track"], sounds.LEGEND_MUSIC_SLOTS)

    def test_underground_map_has_no_day_night_split(self) -> None:
        block = audio_assets.map_audio_block(1, self.base)
        self.assertTrue(block["ambient"]["cave"])
        # у карт 1…5 амбиент в данных не записан
        self.assertEqual(block["ambient"]["day"], [])
        self.assertEqual(block["ambient"]["night"], [])


if __name__ == "__main__":
    unittest.main()
