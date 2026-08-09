# -*- coding: utf-8 -*-
"""Договор аудио: канон konung2/sounds.py и voices.py против самого exe.

Аудиосистема снята с дизассемблера (docs/AUDIO_AUDIT.md), и первая же
арифметическая описка нашлась ещё при написании этого договора: «шанс звука
стойки зверя 40 %» — а в коде 0x60 = 96, то есть 4 %. Поэтому каждая
константа канона проверяется по месту в коде: тест дизассемблирует нужное
окно и требует, чтобы число там реально встречалось, а данные (SOUNDS.RES,
voices.res, QUESTS.RES, _VOICES) сходились с формулами.
"""
from __future__ import annotations

import json
import os
import struct
import unittest

from konung2 import sounds
from konung2.exetables import va_to_foff
from konung2.paths import game_file
from konung2.quests import Dialogs
from konung2.sounds import SoundsRes
from konung2.voices import (GREETING_BASE, GREETINGS_PER_ACTOR, VOICE_TABLE_SIZE,
                            VoicesRes, greeting_index)

GAME_AVAILABLE = os.path.isfile(game_file("konung2.exe"))
needs_game = unittest.skipUnless(GAME_AVAILABLE, "игра недоступна: нет konung2.exe")

_EXE: bytes | None = None


def exe_bytes() -> bytes:
    global _EXE
    if _EXE is None:
        with open(game_file("konung2.exe"), "rb") as stream:
            _EXE = stream.read()
    return _EXE


def constants_in(va_from: int, va_to: int) -> set[int]:
    """Все непосредственные значения и смещения в окне кода.

    Линейный дизасм без остановки на ret: лишние числа не мешают проверке
    «константа встречается», а границы функций знать не требуется.
    """
    from capstone import CS_ARCH_X86, CS_MODE_32, Cs
    from capstone.x86 import X86_OP_IMM, X86_OP_MEM

    data = exe_bytes()[va_to_foff(va_from):va_to_foff(va_to)]
    engine = Cs(CS_ARCH_X86, CS_MODE_32)
    engine.detail = True
    found: set[int] = set()

    def put(value: int) -> None:
        found.add(value)
        found.add(value & 0xFFFFFFFF)
        if value > 0x7FFFFFFF:
            found.add(value - 0x100000000)

    for instruction in engine.disasm(data, va_from):
        for operand in instruction.operands:
            if operand.type == X86_OP_IMM:
                put(operand.imm)
            elif operand.type == X86_OP_MEM:
                put(operand.mem.disp)
    return found


@needs_game
class MixerContractTest(unittest.TestCase):
    """Проигрыватель эффектов 0x42D660 и его пороги."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.body = constants_in(0x42D660, 0x42D9FC)

    def test_buffer_limit_and_gates(self) -> None:
        self.assertIn(sounds.MAX_BUFFERS, self.body)          # 0x2D
        self.assertIn(sounds.VOLUME_GATE, self.body)          # −4000
        self.assertIn(sounds.PITCH_SLOT_TO, self.body)        # 700
        self.assertIn(sounds.PITCH_SLOT_FROM, self.body)      # 0x20

    def test_pitch_exceptions_are_the_hit_slots(self) -> None:
        for slot in sounds.PITCH_UI_SLOTS:
            self.assertIn(slot, self.body)
        # исключения — ровно звуки попаданий (плюс сироты той же серии)
        hits = {sounds.HIT_MISS_SLOT, sounds.HIT_ARMOR_SLOTS[1],
                sounds.HIT_ARMOR_SLOTS[5]}
        self.assertTrue(hits < sounds.PITCH_UI_SLOTS)

    def test_pitch_formats_come_from_the_init(self) -> None:
        # nAvgBytesPerSec движок вычисляет в регистре (mov [...], edx),
        # поэтому проверяются сами частоты и адреса трёх WAVEFORMATEX.
        init = constants_in(0x42CE0C, 0x42D0E8)
        for rate in sounds.PITCH_RATES:                       # 22050, 19050, 25050
            self.assertIn(rate, init)
        self.assertIn(sounds.MUSIC_RATE, init)                # 44100
        self.assertIn(0x8A77F8, init)                         # форматы эффектов
        self.assertIn(0x8A7A10, init)                         # формат музыки

    def test_music_volume_is_binary(self) -> None:
        self.assertIn(sounds.SILENCE, constants_in(0x42D0E8, 0x42D13C))


@needs_game
class PositionContractTest(unittest.TestCase):
    """Позиционная громкость (0x43BC74) и панорама (0x43BC20)."""

    def test_volume_fades_to_the_hearing_radius(self) -> None:
        body = constants_in(0x43BC74, 0x43BD0E)
        self.assertIn(sounds.HEARING_RADIUS, body)            # 0x800
        self.assertIn(sounds.SILENCE, body)                   # −10000
        self.assertIn(sounds.SCREEN_CENTER[0], body)          # 0x1BA
        self.assertIn(sounds.SCREEN_CENTER[1], body)          # 0x162

    def test_pan_multiplier_is_the_product_of_two_doubles(self) -> None:
        data = exe_bytes()
        big = struct.unpack_from("<d", data, va_to_foff(0x45933A))[0]
        small = struct.unpack_from("<d", data, va_to_foff(0x459342))[0]
        self.assertEqual(big * small, sounds.PAN_PER_COLUMN)  # 10000 · 0.00625
        self.assertIn(sounds.PAN_CENTER_SHIFT,
                      constants_in(0x43BC20, 0x43BC74))       # +5 к колонке

    def test_python_mirrors_the_integer_math(self) -> None:
        self.assertEqual(sounds.position_volume(0), 0)
        self.assertEqual(sounds.position_volume(1024), -5000)
        self.assertEqual(sounds.position_volume(2048), -10000)
        self.assertEqual(sounds.position_volume(2049), -10000)
        self.assertEqual(sounds.position_volume(819), -3999)  # ещё слышно
        self.assertEqual(sounds.position_volume(820), -4003)  # уже за гейтом
        self.assertEqual(sounds.position_pan(0), 0)
        self.assertEqual(sounds.position_pan(4), 250)
        self.assertEqual(sounds.position_pan(-4), -250)
        self.assertEqual(sounds.position_pan(1), 62)          # банковское округление
        self.assertEqual(sounds.position_pan(3), 188)


@needs_game
class EventContractTest(unittest.TestCase):
    """Формулы событий по местам вызовов."""

    def test_unit_response(self) -> None:
        body = constants_in(0x42D308, 0x42D660)
        self.assertIn(sounds.RESPONSE_BASE + sounds.RESPONSE_OFFSET, body)  # 0x25
        self.assertIn(sounds.RESPONSE_VARIANTS, body)
        self.assertIn(sounds.MAX_BUFFERS, body)

    def test_talk_request(self) -> None:
        # case 2 «подойти и заговорить»: базы 700/702 и пороги близости
        body = constants_in(0x410A08, 0x410F00)
        self.assertIn(sounds.TALK_REQUEST_BASE, body)         # 700
        self.assertIn(sounds.TALK_REQUEST_BASE_ALT, body)     # 702
        # компилятор пишет «< 7» как «<= 6» (и «< 4» как «<= 3»)
        self.assertTrue({sounds.TALK_NEAR_ROWS, sounds.TALK_NEAR_ROWS - 1} & body)
        self.assertTrue({sounds.TALK_NEAR_COLS, sounds.TALK_NEAR_COLS - 1} & body)
        # база по типу собеседника: байт 0x45FE90[тип] ненулевой -> 702
        data = exe_bytes()
        table = data[va_to_foff(0x45FE90):va_to_foff(0x45FE90) + 0x18]
        alt = {kind for kind in range(0x18) if table[kind] >= 1}
        self.assertEqual(alt, set(sounds.TALK_ALT_BASE_TYPES))
        self.assertEqual(sounds.talk_request_slot(0, 0, 0), 700)
        self.assertEqual(sounds.talk_request_slot(0, 1, 1), 703)
        self.assertEqual(sounds.talk_request_slot(5, 9, 0), 722)

    def test_ambient_day_night(self) -> None:
        body = constants_in(0x438DC0, 0x438E70)
        self.assertIn(100 - 1 - sounds.AMBIENT_CHANCE_PERCENT, body)   # 0x62
        self.assertIn(sounds.AMBIENT_BASE, body)              # 0x100
        self.assertIn(sounds.AMBIENT_DAY_VARIANTS, body)      # rand%5
        self.assertIn(sounds.AMBIENT_NIGHT_VARIANTS, body)    # rand%3

    def test_companion_greeting(self) -> None:
        body = constants_in(0x438E70, 0x438FD0)
        self.assertIn(GREETING_BASE, body)                    # 0x157C
        self.assertIn(GREETINGS_PER_ACTOR, body)
        self.assertIn(0x3FF, body)                            # раз в 1024 тика
        self.assertEqual(greeting_index(3, 7), 5500 + 15 + 2)

    def test_creature_actions_and_chances(self) -> None:
        body = constants_in(0x429B2C, 0x42A234)
        for offset in (sounds.CREATURE_DEATH, sounds.CREATURE_ATTACK,
                       sounds.CREATURE_IDLE, sounds.CREATURE_RUN):
            self.assertIn(sounds.CREATURE_BASE + offset, body)  # 0x50..0x54
        # компилятор переписал «< 96» как «<= 95» (и «< 76» как «<= 75»)
        idle = 100 - sounds.IDLE_SOUND_PERCENT
        walk = 100 - sounds.WALK_SOUND_PERCENT
        self.assertTrue({idle, idle - 1} & body)              # 96/95
        self.assertTrue({walk, walk - 1} & body)              # 76/75

    def test_human_pose_sounds(self) -> None:
        # ветка людей 0x429B2C: кряхтенье +0x23, боль +0x24, смерть +0x22,
        # шаги героя 0xD, выстрел по классу 0x15 — самострел 1, лук 5
        body = constants_in(0x429B2C, 0x42A234)
        base = sounds.RESPONSE_BASE
        self.assertIn(base + sounds.IDLE_VOICE_OFFSET, body)   # 0x23
        self.assertIn(base + sounds.HURT_CRY_OFFSET, body)     # 0x24
        self.assertIn(base + sounds.DEATH_CRY_OFFSET, body)    # 0x22
        self.assertIn(sounds.HERO_STEPS_SLOT, body)            # 0xD
        self.assertIn(sounds.CROSSBOW_CLASS_LAYER, body)       # 0x15
        self.assertIn(sounds.SHOT_BOW_SLOT, body)
        self.assertIn(sounds.SHOT_CROSSBOW_SLOT, body)
        self.assertEqual(sounds.hurt_cry_slot(0), 36)
        self.assertEqual(sounds.death_cry_slot(0), 34)
        for slot in sounds.SWING_SLOTS.values():              # 16 и 4
            self.assertIn(slot, body)
        self.assertIn(sounds.SWING_DEFAULT, body)

    def test_creature_special_state_sound(self) -> None:
        body = constants_in(0x414700, 0x414870)
        # слот = порода*8 − 463; вычитание кладёт константу положительной
        self.assertTrue({-463, 463} & body)
        self.assertEqual(sounds.special_slot(9), 121)
        self.assertEqual(sounds.special_slot(15), 169)
        self.assertEqual((0x40 | 9) * 8 - 463, sounds.special_slot(9))

    def test_hits_by_armor_type(self) -> None:
        body = constants_in(0x412570, 0x4126C0)
        self.assertIn(sounds.HIT_MISS_SLOT, body)
        self.assertIn(sounds.HIT_BODY_SLOT, body)
        for slot in sounds.HIT_ARMOR_SLOTS.values():
            self.assertIn(slot, body)
        self.assertIn(sounds.HIT_ARMOR_DEFAULT, body)
        self.assertIn(0x45DB08, body)                         # таблица классов

    def test_level_up_slot(self) -> None:
        self.assertIn(sounds.LEVEL_UP_SLOT, constants_in(0x413110, 0x4131F0))

    def test_menu_click_pushes_the_ui_slot(self) -> None:
        # прямо перед call 0x42D660 @0x439251 лежит push 6 (6A 06)
        data = exe_bytes()
        window = data[va_to_foff(0x439240):va_to_foff(0x439252)]
        self.assertIn(bytes((0x6A, sounds.CLICK_SLOT)), window)


@needs_game
class StreamingContractTest(unittest.TestCase):
    """Предзагрузка и очередь догрузки."""

    def test_startup_preload(self) -> None:
        body = constants_in(0x43C228, 0x43C560)
        self.assertIn(sounds.SOUND_TABLE_SIZE, body)          # 8000
        self.assertIn(VOICE_TABLE_SIZE, body)                 # 48000
        self.assertIn(sounds.PRELOAD_UI.stop, body)           # 0x14
        self.assertIn(sounds.PRELOAD_RESPONSES.start, body)   # 0x20
        self.assertIn(sounds.SOUND_ARENA_BYTES, body)         # 3.5 МБ

    def test_save_load_preloads_hero_quad(self) -> None:
        self.assertIn(sounds.TALK_REQUEST_BASE,
                      constants_in(0x43D898, 0x43DF48))       # 700 + актёр*4

    def test_map_queue_feeds_ambient_and_creatures(self) -> None:
        body = constants_in(0x43DF48, 0x43F07C)
        self.assertIn(sounds.AMBIENT_BASE, body)              # (карта−1)*8+0x100
        self.assertIn(sounds.CREATURE_BASE, body)             # запись*8+0x50
        self.assertIn(30, body)                               # записей динамики


@needs_game
class AudioDataTest(unittest.TestCase):
    """Инварианты самих данных: SOUNDS.RES, voices.res, QUESTS.RES, _VOICES."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.sounds = SoundsRes.from_game()
        cls.voices = VoicesRes.from_game()

    def occupied(self) -> set[int]:
        return {i for i, e in enumerate(self.sounds.entries) if e and e[1] > 1}

    def test_voices_table_is_absolute_and_dense(self) -> None:
        used = self.voices.used()
        self.assertEqual(len(used), 1245)
        offsets = [self.voices.entries[i] for i in used]
        self.assertEqual(min(off for off, _ in offsets), VOICE_TABLE_SIZE)
        end = max(off + size for off, size in offsets)
        self.assertEqual(end, len(self.voices.data))

    def test_every_quest_voice_exists_and_vice_versa(self) -> None:
        dialogs = Dialogs.from_game()
        spoken = set()
        for index in range(6000):
            voice = dialogs.phrase(index)['voice']
            if voice > 0:
                spoken.add(voice)
        recorded = set(self.voices.used())
        greetings = {greeting_index(actor, n)
                     for actor in range(6) for n in range(GREETINGS_PER_ACTOR)}
        self.assertEqual(len(spoken), 1215)
        self.assertEqual(spoken - recorded, set(), "фразы без записи")
        self.assertEqual(recorded - spoken - greetings, set(), "висячие записи")
        self.assertEqual(greetings - recorded, set(), "приветствия без записи")

    def test_slot_layout_matches_the_census(self) -> None:
        occupied = self.occupied()
        self.assertEqual(len(occupied), 494)
        self.assertEqual(sounds.SILENT_SLOTS & occupied, set())
        self.assertLess(sounds.ORPHAN_SLOTS, occupied)
        self.assertEqual({s for s in occupied if 20 <= s <= 31},
                         set(sounds.MUSIC_SLOTS) - {31})
        # отклики: в каждой восьмёрке актёра заняты +2, +4…+7
        for actor in range(sounds.RESPONSE_ACTORS):
            base = sounds.RESPONSE_BASE + actor * sounds.RESPONSE_STRIDE
            self.assertEqual({s - base for s in occupied if base <= s < base + 8},
                             {2, 4, 5, 6, 7}, f"актёр {actor}")
        # «Эй, есть разговор!»: сетка 700…723 закрывается формулой целиком —
        # 6 актёров × 2 базы (по типу собеседника) × 2 варианта, дублей нет
        self.assertTrue(all(700 + i in occupied for i in range(24)))
        played = {sounds.talk_request_slot(actor, target_type, roll)
                  for actor in range(6)
                  for target_type in (0, 1)
                  for roll in range(2)}
        self.assertEqual(played, set(range(700, 724)))
        # амбиент лежит только в восьмёрках существующих карт 6…54
        ambient = {s for s in occupied if 256 <= s <= 699}
        for slot in ambient:
            map_number = (slot - 256) // 8 + 1
            self.assertTrue(6 <= map_number <= 54, f"слот {slot}")
        # спец-звуки зверей: ровно лодка и дух
        self.assertIn(sounds.special_slot(9), occupied)
        self.assertIn(sounds.special_slot(15), occupied)
        specials = {s for s in occupied if 80 <= s <= 255 and (s - 49) % 8 == 0}
        self.assertEqual(specials, {121, 169})

    def test_voice_rates_parse_the_original_file(self) -> None:
        rates = sounds.voice_rates()
        self.assertEqual(len(rates), 21)
        self.assertTrue(all(0 <= voice < 256 for voice in rates))
        self.assertTrue(all(19000 < rate < 25100 for rate in rates.values()))
        self.assertEqual(rates[19], 21050)      # первая строка файла: 19,-1000
        self.assertEqual(rates[17], 24550)      # 17,+2500

    def test_rules_are_json_ready(self) -> None:
        packed = json.loads(json.dumps(sounds.rules()))
        for key in ('mixer', 'pitch', 'position', 'ui', 'combat', 'voices',
                    'creatures', 'ambient', 'streaming', 'tracks'):
            self.assertIn(key, packed)
        self.assertEqual(packed['mixer']['max_buffers'], 45)
        self.assertEqual(packed['voices']['rates']['19'], 21050)


if __name__ == "__main__":
    unittest.main()
