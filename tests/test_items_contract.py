# -*- coding: utf-8 -*-
"""Договор предметов: таблица классов и слои экипировки против konung2.exe.

Слой экипировки — то же число, по которому движок выбирает анимацию удара,
и на нём же держится отрисовка оружия в руке. Если таблица сдвинется хоть на
запись, персонаж начнёт махать чужим мечом, поэтому проверяем прямо по байтам
игры и по кадрам HEROES.RES.
"""
from __future__ import annotations

import os
import struct
import unittest

from konung2.exetables import va_to_foff
from konung2.heroes import ACTION_BLOCKS, STANCE_BLOCKS, HeroesRes
from konung2.items import (BOW_LAYER, CROSSBOW_LAYER, PALETTE_STRIDE, STRIDE,
                           TABLE_VA, TWO_HAND_LAYERS, WEAPON_LAYERS, find,
                           read_items)
from konung2.paths import game_file

GAME_AVAILABLE = os.path.isfile(game_file("konung2.exe"))
needs_game = unittest.skipUnless(GAME_AVAILABLE, "игра недоступна: нет konung2.exe")


@needs_game
class ItemTableTest(unittest.TestCase):
    def setUp(self) -> None:
        self.items = read_items()

    def test_table_stops_where_names_stop(self) -> None:
        """Таблица кончается там, где указатель на название уходит из данных."""
        with open(game_file("konung2.exe"), "rb") as stream:
            blob = stream.read()
        offset = va_to_foff(TABLE_VA)
        after = struct.unpack_from("<I", blob, offset + len(self.items) * STRIDE)[0]
        self.assertFalse(0x450000 <= after < 0x460000)
        self.assertEqual(len(self.items), 211)

    def test_named_items_keep_their_layer(self) -> None:
        """Опорные предметы: имя -> слой. Сдвиг таблицы ломает этот тест."""
        for name, layer in (("Меч", 1), ("Длинный меч", 1), ("Топор", 5),
                            ("Палица", 9), ("Двуручный меч", 13),
                            ("Двуручный топор", 15), ("Двуручная палица", 17),
                            ("Составной лук", BOW_LAYER),
                            ("Самострел боевой", CROSSBOW_LAYER)):
            with self.subTest(name):
                self.assertEqual(find(name, self.items).layer, layer)

    def test_weapon_layers_are_odd(self) -> None:
        """Оружие живёт только на нечётных слоях — чётный сосед это «в покое»."""
        weapons = {item.layer for item in self.items
                   if item.wearable and item.layer < 23}
        self.assertEqual(weapons, set(WEAPON_LAYERS))
        self.assertTrue(all(layer % 2 for layer in weapons))

    def test_range_comes_from_the_item(self) -> None:
        """Дальность боя — поле +0x10 записи (VA 0x414C01): меч 1, лук далеко."""
        for name, cells in (("Меч", 1), ("Двуручный меч", 1), ("Палица", 1),
                            ("Составной лук", 15), ("Длинный лук", 18)):
            with self.subTest(name):
                self.assertEqual(find(name, self.items).range_cells, cells)
        for item in self.items:
            if item.shield or item.layer in range(23, 27):
                self.assertEqual(item.range_cells, 0, item.name)

    def test_weight_is_grams_and_price_is_coins(self) -> None:
        """Поле +0x14 — вес в граммах, +0x12 — цена.

        Подсказка предмета (VA 0x4315A0) печатает «, вес » и ``%4.2f`` от
        +0x14, умноженного на 0.001, а цену считает VA 0x41ABBC по +0x12.
        Числа это подтверждают: лопата весит килограмм, заячий хвост сто
        граммов, двуручная металлическая палица — четыре с лишним кило.
        """
        weights = {"Лопата": 1000, "Заячий хвост": 100,
                   "Двуручная металлическая палица": 4400, "Доспех кожаный": 2800}
        for name, grams in weights.items():
            with self.subTest(name):
                self.assertEqual(find(name, self.items).weight, grams)
        # цена у оружия соразмерна, а у хлама мала
        self.assertGreater(find("Меч", self.items).price, 0)
        self.assertLess(find("Лопата", self.items).price,
                        find("Составной лук", self.items).price)

    def test_requirement_names_a_characteristic(self) -> None:
        """+0x0C — какая характеристика нужна, +0x0E — сколько.

        Проверка перед надеванием (VA 0x418648) сравнивает характеристику
        юнита с этим числом. Сходится с текстами игры: топор требует
        выносливости, лук — ловкости, меч — силы.
        """
        from konung2.items import REQUIREMENT_STATS
        expected = {"Топор": "Выносливость", "Составной лук": "Ловкость",
                    "Меч": "Сила"}
        for name, stat in expected.items():
            with self.subTest(name):
                item = find(name, self.items)
                self.assertEqual(REQUIREMENT_STATS.get(item.requires), stat)
                self.assertGreater(item.requirement, 0)
        # у безобидной лопаты требований нет
        self.assertEqual(find("Лопата", self.items).requires, 0)

    def test_durability_starts_the_wear(self) -> None:
        """+0x08 — прочность: с неё начинается износ (VA 0x41BF54)."""
        for name in ("Меч", "Доспех кожаный", "Деревянный щит"):
            with self.subTest(name):
                self.assertGreater(find(name, self.items).durability, 0)

    def test_power_is_the_combat_value(self) -> None:
        """Поле +0x04 — сила: его читают и удар (0x41A59E), и броня (0x41A460)."""
        self.assertGreater(find("Двуручный топор", self.items).power,
                           find("Нож", self.items).power)
        for name in ("Доспех кожаный", "Щит кожаный", "Шлем кожаный"):
            with self.subTest(name):
                self.assertGreater(find(name, self.items).power, 0)

    def test_palette_offset_is_a_byte_offset(self) -> None:
        """Палитра слоя — смещение в блоке палитр, кратное 0x200 (VA 0x426707)."""
        for item in self.items:
            with self.subTest(item.name):
                self.assertEqual(item.palette_offset % PALETTE_STRIDE, 0)
                self.assertEqual(item.palette, item.palette_offset // PALETTE_STRIDE)

    def test_attack_pose_follows_engine_thresholds(self) -> None:
        """Выбор анимации: >= 0x0D двуручная, 0x15 самострел (VA 0x416BC2/0x416B28)."""
        for item in self.items:
            if not item.weapon:
                continue
            with self.subTest(item.name):
                if item.layer == CROSSBOW_LAYER:
                    self.assertEqual(item.attack_pose, "shoot_crossbow")
                elif item.layer == BOW_LAYER:
                    self.assertEqual(item.attack_pose, "shoot_bow")
                elif item.layer in TWO_HAND_LAYERS:
                    self.assertEqual(item.attack_pose, "attack_two_hand")
                else:
                    self.assertEqual(item.attack_pose, "attack_one_hand")


@needs_game
class EquipmentFramesTest(unittest.TestCase):
    """Слои из таблицы предметов должны существовать в кадрах HEROES.RES."""

    def setUp(self) -> None:
        self.heroes = HeroesRes.from_game()

    def layers_of(self, block: int, limit: int = 23) -> set[int]:
        """Слои, занятые кадрами блока. По умолчанию только оружие (1…22)."""
        found: set[int] = set()
        for record in self.heroes.animation(block, 0):
            found.update(layer for layer in range(1, limit)
                         if self.heroes.layer_entry(record, layer))
        return found

    def test_peace_stance_carries_only_rest_layers(self) -> None:
        """Мирная стойка и шаг несут только чётные слои — оружие убрано."""
        for pose in ("stand", "walk"):
            with self.subTest(pose):
                layers = self.layers_of(STANCE_BLOCKS["peace"][pose])
                self.assertTrue(layers)
                self.assertTrue(all(layer % 2 == 0 for layer in layers))

    def test_melee_attacks_carry_working_layers(self) -> None:
        """Удары несут рабочие слои: одной рукой нечётные, двуручный 13/15/17."""
        one_hand = self.layers_of(ACTION_BLOCKS["attack_one_hand"])
        self.assertTrue({1, 5, 9} <= one_hand)
        two_hand = self.layers_of(ACTION_BLOCKS["attack_two_hand"])
        self.assertEqual(set(TWO_HAND_LAYERS) & two_hand, set(TWO_HAND_LAYERS))

    def test_bow_shot_draws_bow_and_keeps_melee_at_rest(self) -> None:
        """В выстреле лук натянут (19), а меч на поясе — чётным слоем."""
        layers = self.layers_of(ACTION_BLOCKS["shoot_bow"])
        self.assertIn(BOW_LAYER, layers)
        self.assertIn(2, layers)
        self.assertNotIn(1, layers)

    def test_weapon_has_a_layer_for_each_hand(self) -> None:
        """У одноручного четыре слоя подряд: правая, убрано, левая, убрано.

        Отрисовка (VA 0x425DB4) рисует второе оружие слоем +2, а убранное
        +3 — значит эти кадры обязаны быть. Удар одной рукой их и несёт.
        """
        layers = self.layers_of(ACTION_BLOCKS["attack_one_hand"])
        self.assertTrue({1, 3, 5, 7, 9, 11} <= layers)

    def test_shield_has_a_second_layer_on_the_back(self) -> None:
        """Щит живёт двумя слоями: в руке и за спиной, ровно плюс шесть.

        В мирной стойке кадры несут ТОЛЬКО «за спиной» (33…38), а в ударе
        со щитом — и то и другое (27…38): щит в руке появляется вместе с
        достанным оружием, как и говорит сценарий отрисовки.
        """
        from konung2.heroes import LAYER_SHIELD_BACK
        peace = self.layers_of(STANCE_BLOCKS["peace"]["stand"], limit=54)
        shielded = self.layers_of(ACTION_BLOCKS["attack_shield"], limit=54)
        in_hand = set(range(27, 33))
        on_back = {layer + LAYER_SHIELD_BACK for layer in in_hand}
        self.assertTrue(on_back <= peace)
        self.assertFalse(in_hand & peace)
        self.assertTrue((in_hand | on_back) <= shielded)

    def test_draw_script_is_five_steps_per_direction(self) -> None:
        """Сценарий отрисовки: пять шагов на направление, шлем посередине."""
        from konung2.heroes import draw_script
        script = draw_script()
        self.assertEqual(len(script), 8)
        self.assertTrue(all(len(row) == 5 for row in script))
        self.assertEqual(script[0], [100, 101, 3, 111, 110])
        # направления 0…4 одинаковы, 5…7 — тот же список наоборот
        self.assertTrue(all(row == script[0] for row in script[:5]))
        self.assertTrue(all(row == list(reversed(script[0])) for row in script[5:]))
        self.assertTrue(all(row[2] == 3 for row in script))


if __name__ == "__main__":
    unittest.main()


@needs_game
class ProgressionContractTest(unittest.TestCase):
    """Опыт и прокачка: наши правила против байтов konung2.exe."""

    def test_level_thresholds_follow_the_engine_sum(self) -> None:
        """Порог уровня N — сумма i*100 (VA 0x41AA34)."""
        from konung2.progress import level_threshold
        self.assertEqual([level_threshold(n) for n in range(1, 6)],
                         [100, 300, 600, 1000, 1500])

    def test_costs_and_caps_match_the_code(self) -> None:
        """Цена и потолки: характеристика 2 и 150, навык 1 и 100."""
        from konung2.progress import (CHARACTERISTIC_CAP, CHARACTERISTIC_COST,
                                      SKILL_CAP, SKILL_COST, FREE_XP_PER_LEVEL)
        with open(game_file("konung2.exe"), "rb") as stream:
            blob = stream.read()
        # 0x413246: cmp eax, 0x96 (3d 96 …) — потолок характеристики
        self.assertEqual(blob[va_to_foff(0x413246) + 1], CHARACTERISTIC_CAP)
        # 0x4132B8: cmp eax, 0x64 (83 f8 64) — потолок навыка
        self.assertEqual(blob[va_to_foff(0x4132B8) + 2], SKILL_CAP)
        # 0x41315A: add word [eax+0x48], 0x19 — свободный опыт за уровень
        self.assertEqual(blob[va_to_foff(0x413157) + 7], FREE_XP_PER_LEVEL)
        self.assertEqual((CHARACTERISTIC_COST, SKILL_COST), (2, 1))

    def test_names_come_from_the_exe(self) -> None:
        """Названия характеристик и навыков — строки из самой игры."""
        from konung2.progress import CHARACTERISTICS, SKILLS
        with open(game_file("konung2.exe"), "rb") as stream:
            blob = stream.read()
        block = blob[va_to_foff(0x451600):va_to_foff(0x4519A0)].decode("cp866", "replace")
        for name in CHARACTERISTICS:
            self.assertIn(name, block, name)
        for name in SKILLS:
            self.assertIn(name, block, name)
        self.assertEqual(len(SKILLS), 20)

    def test_kill_experience_weights_are_the_doubles_in_the_exe(self) -> None:
        """Веса опыта за убитого — восьмибайтовые константы 0x4500AC…0x4500EC."""
        from konung2.progress import (KILL_XP_WEAPON_WEIGHT, KILL_XP_WEIGHTS,
                                      KILL_XP_WEIGHTS_HUMAN)
        with open(game_file("konung2.exe"), "rb") as stream:
            blob = stream.read()

        def double_at(va: int) -> float:
            return struct.unpack_from("<d", blob, va_to_foff(va))[0]

        # зверь (VA 0x41B059…0x41B0C8): Ловкость 0.2, Сила и Выносливость 0.3,
        # броня 0.1 — и никаких навыков
        self.assertEqual(KILL_XP_WEIGHTS["parry"], double_at(0x4500AC))
        self.assertEqual(KILL_XP_WEIGHTS["strength"], double_at(0x4500B4))
        self.assertEqual(KILL_XP_WEIGHTS["endurance"], double_at(0x4500B4))
        self.assertEqual(KILL_XP_WEIGHTS["armour"], double_at(0x4500BC))
        # человек (VA 0x41B0CD…0x41B185): те же три плюс два навыковых слагаемых
        self.assertEqual(KILL_XP_WEIGHTS_HUMAN["parry"], double_at(0x4500C4))
        self.assertEqual(KILL_XP_WEIGHTS_HUMAN["strength"], double_at(0x4500CC))
        self.assertEqual(KILL_XP_WEIGHTS_HUMAN["endurance"], double_at(0x4500CC))
        self.assertEqual(KILL_XP_WEIGHTS_HUMAN["melee_skill"], double_at(0x4500D4))
        self.assertEqual(KILL_XP_WEIGHTS_HUMAN["ranged_skill"], double_at(0x4500DC))
        self.assertEqual(KILL_XP_WEIGHTS_HUMAN["armour"], double_at(0x4500E4))
        self.assertEqual(KILL_XP_WEAPON_WEIGHT, double_at(0x4500EC))
        # разница веток не косметическая: у человека навыки весят больше всего
        self.assertGreater(KILL_XP_WEIGHTS_HUMAN["ranged_skill"], 1.0)
        self.assertNotIn("melee_skill", KILL_XP_WEIGHTS)

    def test_the_killer_gets_a_truncated_quarter(self) -> None:
        """Четверть опыта — целочисленная, к нулю, без нижней границы (VA 0x414150)."""
        from konung2.progress import kill_share
        with open(game_file("konung2.exe"), "rb") as stream:
            blob = stream.read()
        # 0x41425A: sar eax, 2 (c1 f8 02) — деление на четыре сдвигом
        self.assertEqual(blob[va_to_foff(0x414150):va_to_foff(0x414150) + 0x120].count(
            bytes.fromhex("c1f802")), 1)
        self.assertEqual(kill_share(3), 0)      # не 1: нижней границы нет
        self.assertEqual(kill_share(7), 1)
        self.assertEqual(kill_share(100), 25)

    def test_small_experience_is_multiplied_by_the_setting(self) -> None:
        """Опыт не больше 2000 умножается на «настройка + 2» (VA 0x413110)."""
        from konung2.progress import (XP_MULTIPLIER_LIMIT,
                                      gain_experience, xp_multiplier_setting)
        with open(game_file("konung2.exe"), "rb") as stream:
            blob = stream.read()
        # 0x413110+6: cmp dword [ebp+0x18], 0x7d0 — граница множителя
        self.assertIn(struct.pack("<I", XP_MULTIPLIER_LIMIT),
                      blob[va_to_foff(0x413110):va_to_foff(0x413110) + 0x20])
        # настройка живёт первым полем KONUNG2.CFG (VA 0x84958C, чтение
        # 0x42EBD0) — читатель обязан брать именно его
        with open(game_file("KONUNG2.CFG"), "rb") as stream:
            self.assertEqual(struct.unpack("<i", stream.read(4))[0],
                             xp_multiplier_setting())
        self.assertEqual(gain_experience(10, setting=0), 20)
        self.assertEqual(gain_experience(10, setting=1), 30)
        self.assertEqual(gain_experience(2000, setting=1), 6000)   # ровно граница — ещё множится
        self.assertEqual(gain_experience(2001, setting=1), 2001)   # выше границы — как есть

    def test_skill_limits_follow_the_switch_in_the_engine(self) -> None:
        """Пределы навыков — три вида выражения из switch VA 0x413268."""
        from konung2.progress import SKILL_LIMITS, SKILLS, skill_limit
        self.assertEqual(len(SKILL_LIMITS), len(SKILLS))
        # характеристики: 0 Харизма, 1 Ловкость, 2 Интеллект, 3 Обучаемость,
        # 4 Сила, 5 Выносливость
        chars = [40, 60, 80, 40, 50, 30]
        skills = [0] * 20
        base = chars[3] // 4                                     # Обучаемость >> 2
        # «Рукопашный бой» (case 0): основа + среднее Силы и Ловкости
        self.assertEqual(skill_limit(0, chars, skills), base + (50 + 60) // 2)
        # «Стрельба из арбалета» (case 9): основа + одна Ловкость целиком
        self.assertEqual(skill_limit(9, chars, skills), base + 60)
        # «Знахарство» (case 0xB): удвоенная сумма Интеллекта с основой
        self.assertEqual(skill_limit(11, chars, skills), min(100, (80 + base) * 2))
        # «Владение двуручным мечом» (case 6): среднее трёх характеристик
        self.assertEqual(skill_limit(6, chars, skills), base + (60 + 30 + 50) // 3)
        # «Бой двумя руками» (case 1) заперт, пока ни один из 0/4/5/3 не дорос до 25
        self.assertEqual(skill_limit(1, chars, skills), 0)
        skills[4] = 25
        self.assertEqual(skill_limit(1, chars, skills), base + (50 + 60) // 2)
        # «Смертельный удар» (case 2) заперт до 50 и считается половиной суммы
        self.assertEqual(skill_limit(2, chars, skills), 0)
        skills[9] = 50
        self.assertEqual(skill_limit(2, chars, skills), (60 + base) // 2)


@needs_game
class BeltContractTest(unittest.TestCase):
    """Пояс: где стоит ряд ячеек мешка и почему не у самого низа экрана.

    Отрисовка пояса — VA 0x43096C, и все числа взяты из её же байтов.
    """

    def setUp(self) -> None:
        with open(game_file("konung2.exe"), "rb") as stream:
            self.blob = stream.read()

    def imm32(self, va: int, skip: int) -> int:
        return struct.unpack_from("<I", self.blob, va_to_foff(va) + skip)[0]

    def test_row_geometry_matches_the_drawing_code(self) -> None:
        """Строка 639, первая ячейка x=168, шаг 69, сторона 70, двенадцать."""
        from konung2.interf import BELT
        # C7 45 F0 A8 00 00 00   mov [ebp-0x10], 0xA8  — x первой ячейки
        self.assertEqual(self.imm32(0x430AB0, 3), BELT["first_x"])
        # C7 45 F8 7F 02 00 00   mov [ebp-8], 0x27F    — строка ряда
        self.assertEqual(self.imm32(0x430AB7, 3), BELT["y"])
        # 83 45 F0 45            add [ebp-0x10], 0x45  — шаг ячеек
        self.assertEqual(self.blob[va_to_foff(0x430ACE) + 3], BELT["pitch"])
        # B8 46 00 00 00         mov eax, 0x46         — сторона ячейки
        self.assertEqual(self.imm32(0x430C1A, 1), BELT["cell"])
        # 83 C0 0C               add eax, 0xC          — ячеек в окне
        self.assertEqual(self.blob[va_to_foff(0x4309DD) + 2], BELT["cells"])
        # 68 8C 00 00 00         push 0x8C             — x левой стрелки
        self.assertEqual(self.imm32(0x430A09, 1), BELT["left_x"])

    def test_row_stands_on_the_bottom_of_the_world_window(self) -> None:
        """Ряд упирается в низ проёма (708), а ниже идёт полоса рамки.

        Отсюда и берётся зазор между ячейками и краем экрана: он не наш,
        а рамки — 59 пикселей, строки 709..767.
        """
        from konung2.interf import BELT, FRAME_BOTTOM, SCREEN, VIEW_HEIGHT
        # 68 C4 02 00 00   push 0x2C4 — низ отсечки пояса
        clip_bottom = self.imm32(0x430B45, 1)
        self.assertEqual(clip_bottom, 708)
        self.assertEqual(BELT["y"] + BELT["height"] - 1, clip_bottom)
        self.assertEqual(VIEW_HEIGHT, clip_bottom + 1)
        self.assertEqual(SCREEN[1] - FRAME_BOTTOM, 59)

    def test_row_fills_the_width_of_the_world_window(self) -> None:
        """Стрелки и двенадцать ячеек ровно покрывают ширину окна мира."""
        from konung2.interf import (BELT, BELT_ARROWS, FRAME_SPRITE,
                                    PANEL_WIDTH, SCREEN, VIEW_WIDTH, InterfRes)
        interf = InterfRes.from_game()
        self.assertEqual(interf.frame_size(FRAME_SPRITE), SCREEN)
        left = interf.frame_size(BELT_ARROWS["left"])
        right = interf.frame_size(BELT_ARROWS["right"])
        self.assertEqual(left, (28, BELT["height"]))
        self.assertEqual(right, (27, BELT["height"]))
        # 140 + 28 = 168 — первая ячейка начинается сразу за левой стрелкой
        self.assertEqual(PANEL_WIDTH + left[0], BELT["first_x"])
        row = left[0] + BELT["cells"] * BELT["pitch"] + right[0]
        self.assertEqual(row, VIEW_WIDTH - 1)
        self.assertEqual(BELT["right_x"] - right[0] + 1,
                         BELT["first_x"] + BELT["cells"] * BELT["pitch"] + 1)

    def test_bag_window_is_twelve_of_forty_two(self) -> None:
        """В поясе видно двенадцать ячеек из сорока двух (unit+0x62)."""
        from konung2.items import BAG_SLOTS
        from konung2.interf import BELT
        # 83 7D E4 2A   cmp [ebp-0x1C], 0x2A — дальше 42-й ячейки не рисуем
        self.assertEqual(self.blob[va_to_foff(0x430ADE) + 3], BAG_SLOTS)
        self.assertEqual(BELT["cells"], 12)
        self.assertLess(BELT["cells"], BAG_SLOTS)

    def test_panel_is_nine_portraits_and_seven_buttons(self) -> None:
        """В левой панели нет гнёзд под предметы: портреты и кнопки.

        Кнопки движок рисует по той же таблице со смещения 0x460F44 — это
        ровно десятая запись, а всего их шестнадцать (VA 0x430794).
        """
        from konung2.interf import (BUTTON_ACTIONS, BUTTON_RECTS_VA, BUTTON_SPRITES,
                                    PANEL_LAYOUT, PANEL_RECTS_VA, panel_rects)
        self.assertEqual(len(PANEL_LAYOUT), 16)
        self.assertEqual(BUTTON_RECTS_VA, PANEL_RECTS_VA + 9 * 16)
        self.assertEqual(len(BUTTON_ACTIONS), 7)
        self.assertEqual(len(BUTTON_SPRITES), 7)
        # 68 8C 00 00 00 push 0x8C и 68 FF 02 00 00 push 0x2FF — отсечка
        # рисования кнопок по левой панели
        self.assertEqual(self.imm32(0x430803, 1), 0x8C)
        # cmp [ebp-4], 7 — семь кнопок в цикле (83 7D FC 07)
        self.assertEqual(self.blob[va_to_foff(0x4307E8) + 3], 7)
        rects = panel_rects()
        portraits = [r for r in rects if not r["name"].startswith("button_")]
        buttons = [r for r in rects if r["name"].startswith("button_")]
        self.assertEqual(len(portraits), 9)
        self.assertEqual(len(buttons), 7)
        # первая кнопка широкая, остальные — две колонки по три ряда
        self.assertGreater(buttons[0]["width"], 120)
        self.assertTrue(all(r["width"] < 80 for r in buttons[1:]))

    def test_weapon_face_rule_matches_the_code(self) -> None:
        """Лицо кнопки оружия: арбалет, лук, клинок, топор, дубина, кулак."""
        from konung2.interf import WEAPON_FACES, WEAPON_FACE_FAMILIES
        # mov byte [0x844288], imm — сами номера спрайтов из VA 0x4292DC
        faces = {va: self.blob[va_to_foff(va) + 6] for va in
                 (0x429360, 0x429369, 0x429372, 0x4293D9, 0x4293EB, 0x4293F4)}
        self.assertEqual(faces[0x429360], WEAPON_FACES["crossbow"])
        self.assertEqual(faces[0x429369], WEAPON_FACES["bow"])
        self.assertEqual(faces[0x429372], WEAPON_FACES["empty"])
        self.assertEqual(faces[0x4293D9], WEAPON_FACES["blade"])
        self.assertEqual(faces[0x4293EB], WEAPON_FACES["axe"])
        self.assertEqual(faces[0x4293F4], WEAPON_FACES["other"])
        # cmp [ebp-4], 0xA6 и 0x9A — семейства клинков и топоров
        self.assertEqual(struct.unpack_from("<i", self.blob, va_to_foff(0x4293D0) + 3)[0],
                         WEAPON_FACE_FAMILIES["blade"])
        self.assertEqual(struct.unpack_from("<i", self.blob, va_to_foff(0x4293E2) + 3)[0],
                         WEAPON_FACE_FAMILIES["axe"])
        # и эти семейства должны совпасть с самими предметами
        items = read_items()
        self.assertEqual(find("Меч", items).ground, WEAPON_FACE_FAMILIES["blade"])
        self.assertEqual(find("Топор", items).ground, WEAPON_FACE_FAMILIES["axe"])

    def test_stance_button_follows_the_stance_bit(self) -> None:
        """Вторая кнопка: кулак с достанным оружием, ладонь с убранным."""
        from konung2.interf import STANCE_SPRITES
        # VA 0x429407: test byte [eax+0x19], 4 -> 0x0A иначе 0x0F
        self.assertEqual(self.blob[va_to_foff(0x42940D) + 6], STANCE_SPRITES["combat"])
        self.assertEqual(self.blob[va_to_foff(0x429416) + 6], STANCE_SPRITES["peace"])

    def test_equipment_slots_are_x_then_y(self) -> None:
        """Гнёзда окна снаряжения читаются как (x1, y1, x2, y2).

        Цикл отрисовки складывает поля +0x00 и +0x08 с ШИРИНОЙ спрайта, а
        +0x04 и +0x0C с ВЫСОТОЙ (VA 0x42B16C), поэтому первое поле — x.
        Проверка по смыслу: шлем выше доспеха, рука левее щита.
        """
        from konung2.interf import slot_rects
        rects = {r["slot"]: r for r in slot_rects()}
        self.assertLess(rects["head"]["y"], rects["body"]["y"])
        self.assertLess(rects["hand"]["x"], rects["off_hand"]["x"])
        self.assertGreater(rects["ranged"]["y"], rects["body"]["y"])
        # гнёзда должны помещаться в само окно 884x638
        for rect in rects.values():
            self.assertLess(rect["x"] + rect["width"], 884)
            self.assertLess(rect["y"] + rect["height"], 638)
        # подсказки — строки игры, каждая про свой слот
        self.assertIn("правой руке", rects["hand"]["hint"])
        self.assertIn("лука", rects["ranged"]["hint"])
        self.assertIn("шлем", rects["head"]["hint"])
        self.assertIn("левой руке", rects["off_hand"]["hint"])

    def test_jewel_slots_are_wearable_with_game_hints(self) -> None:
        """Пятёрка украшений — живые гнёзда с подсказками кодов 7…11.

        Раздачу по видам делает VA 0x41E8D8 (6 ожерелье, 7 браслет, 8
        кольцо), лежат они в юните с +0xB6 — гнёзда не витрина. Мёртвым
        остаётся только место смешивания: у него свой код мыши 0x1C.
        """
        from konung2.interf import slot_rects
        rects = {r["slot"]: r for r in slot_rects()}
        for slot in ("necklace", "bracelet_1", "bracelet_2", "ring_1", "ring_2"):
            self.assertTrue(rects[slot]["wearable"], slot)
        self.assertIn("ожерель", rects["necklace"]["hint"])
        self.assertIn("браслет", rects["bracelet_1"]["hint"])
        self.assertIn("кольц", rects["ring_1"]["hint"])
        # парные гнёзда делят одну подсказку своего вида
        self.assertEqual(rects["bracelet_1"]["hint"], rects["bracelet_2"]["hint"])
        self.assertEqual(rects["ring_1"]["hint"], rects["ring_2"]["hint"])
        self.assertFalse(rects["mixing"]["wearable"])

    def test_equipment_window_has_twelve_slots(self) -> None:
        """Гнёзд двенадцать: пять надетых, боеприпас, пять украшений и курсор.

        Разбор VA 0x42A8F4: пятёрка с unit+0x58, отдельное гнездо unit+0x50,
        пятёрка украшений с unit+0xB6 и ячейка предмета, который держит
        курсор. Прямоугольники стоят симметрично телу — по ним и проверяем.
        """
        from konung2.interf import (AMMO_SLOT_RECT, CURSOR_SLOT_RECT,
                                    JEWELLERY_RECTS, SLOT_RECTS_COUNT,
                                    SLOT_RECTS_VA)
        rects = []
        for index in range(SLOT_RECTS_COUNT):
            x1, y1, x2, y2 = struct.unpack_from(
                "<4i", self.blob, va_to_foff(SLOT_RECTS_VA) + index * 16)
            rects.append({"x": x1, "y": y1, "width": x2 - x1, "height": y2 - y1})
        # боеприпас стоит вплотную к метательному, на той же строке
        self.assertEqual(rects[AMMO_SLOT_RECT]["y"], rects[1]["y"])
        self.assertGreater(rects[AMMO_SLOT_RECT]["x"], rects[1]["x"])
        # украшения мельче надетого
        for index in JEWELLERY_RECTS:
            self.assertLess(rects[index]["width"], rects[0]["width"])
        # браслеты и кольца стоят парами по сторонам от тела
        self.assertEqual(rects[7]["y"], rects[8]["y"])
        self.assertEqual(rects[9]["y"], rects[10]["y"])
        self.assertLess(rects[7]["x"], rects[2]["x"])
        self.assertGreater(rects[8]["x"], rects[2]["x"])
        # ячейка курсора вынесена вниз, под саму куклу
        self.assertGreater(rects[CURSOR_SLOT_RECT]["y"], rects[1]["y"])

    def test_frame_leaves_the_world_window_open_to_row_708(self) -> None:
        """Сама рамка: проём прозрачен по 708-ю строку, ниже она сплошная."""
        from konung2.interf import (FRAME_BOTTOM, FRAME_SPRITE, PANEL_WIDTH,
                                    SCREEN, VIEW_WIDTH, InterfRes)
        from konung2.res import read_palettes
        sprite = InterfRes.from_game().sprite(FRAME_SPRITE, read_palettes())
        width = sprite.width

        def clear_in_row(y: int) -> int:
            row = sprite.pixels[y * width:(y + 1) * width]
            return sum(1 for pixel in row if pixel[3] == 0)

        for y in (0, 320, FRAME_BOTTOM - 1):
            self.assertEqual(clear_in_row(y), VIEW_WIDTH, f"строка {y}")
        for y in (FRAME_BOTTOM, SCREEN[1] - 1):
            self.assertEqual(clear_in_row(y), 0, f"строка {y}")
        # проём начинается ровно там, где кончается левая панель
        row = sprite.pixels[320 * width:321 * width]
        self.assertEqual(next(x for x in range(width) if row[x][3] == 0), PANEL_WIDTH)


@needs_game
class TradeContractTest(unittest.TestCase):
    """Торговля: множители цены против байтов konung2.exe."""

    def test_price_constants_come_from_the_exe(self) -> None:
        """0.002 за пункт навыка, половина при продаже, 1.5 и 2/3 в деревне."""
        from konung2.trade import constants
        numbers = constants()
        self.assertAlmostEqual(numbers["skill_step_sell"], 0.002)
        self.assertAlmostEqual(numbers["skill_step_buy"], 0.002)
        self.assertAlmostEqual(numbers["half"], 0.5)
        self.assertAlmostEqual(numbers["village_buy"], 1.5)
        self.assertAlmostEqual(numbers["village_sell"], 2 / 3, places=5)

    def test_trade_skill_is_the_fourteenth(self) -> None:
        """Навык торговли — байт unit+0xE0, он же четырнадцатый с +0xD2."""
        from konung2.progress import SKILLS, SKILLS_AT
        from konung2.trade import TRADE_SKILL_AT, TRADE_SKILL_INDEX
        self.assertEqual(SKILLS_AT + TRADE_SKILL_INDEX, TRADE_SKILL_AT)
        self.assertEqual(SKILLS[TRADE_SKILL_INDEX], "Торговля")

    def test_buying_costs_more_than_selling_brings(self) -> None:
        """У деревенского торговца купить всегда дороже, чем продать ему."""
        from konung2.trade import buy_price, sell_price
        for base in (100, 500, 1740):
            with self.subTest(base):
                self.assertGreater(buy_price(base, 0, 0), sell_price(base, 0, 0))

    def test_trade_skill_moves_the_price(self) -> None:
        """Выше своя торговля — дают больше и просят меньше."""
        from konung2.trade import buy_price, sell_price
        self.assertGreater(sell_price(1000, 60, 10), sell_price(1000, 10, 60))
        self.assertLess(buy_price(1000, 60, 10), buy_price(1000, 10, 60))


class PoisonContractTest(unittest.TestCase):
    """Отрава: числа сверены с кодом и с данными стартового мира."""

    def test_potion_class_numbers_are_the_effect_codes(self) -> None:
        """Номер класса и есть код действия зелья (switch в VA 0x41D954)."""
        from konung2.effects import (EMPTY_JAR_CLASS, POTION_ANTIDOTE, POTION_HEAL,
                                     POTION_POISON)
        from konung2.items import read_items
        classes = read_items()
        self.assertEqual(classes[EMPTY_JAR_CLASS].name, "Пустая банка")
        self.assertEqual(classes[POTION_HEAL].name, "Лечебный бальзам")
        self.assertEqual(classes[POTION_POISON].name, "Яд")
        self.assertEqual(classes[POTION_ANTIDOTE].name, "Противоядие")

    def test_potion_numbers_are_the_doubles_in_the_exe(self) -> None:
        """Числа зелий — восьмибайтовые константы 0x4501EB…0x45022B."""
        from konung2.effects import POTION_NUMBERS_VA, potion_numbers
        numbers = potion_numbers()
        self.assertEqual(numbers, {
            "heal_base": 100.0, "heal_step": 0.1, "heal_gain": 160.0,
            "heal_spent": 0.01, "smear_spent": 0.01, "oil_needs": 10.0,
            "antidote_step": 0.1, "antidote_gain": 10.0, "antidote_spent": 0.01,
        })
        # константы лежат подряд по восемь байт, начиная с лечения
        self.assertEqual(sorted(POTION_NUMBERS_VA.values()),
                         [0x4501EB + 8 * n for n in range(len(POTION_NUMBERS_VA))])

    def test_healing_spends_strength_instead_of_emptying_the_jar(self) -> None:
        """Бальзам лечит на (100 − здоровье/16)*0.1 крепости, по 160 за единицу."""
        from konung2.effects import HEAL_HEALTH_DIVISOR, HEALTH_MAX, potion_numbers
        numbers = potion_numbers()
        # раненый на 800: цена (100 − 50) * 0.1 = 5 крепости, лечит 800 единиц
        cost = (numbers["heal_base"] - 800 // HEAL_HEALTH_DIVISOR) * numbers["heal_step"]
        self.assertEqual(cost, 5.0)
        self.assertEqual(round(800 + cost * numbers["heal_gain"]), HEALTH_MAX)
        # целому лечение почти бесплатно — и потолок держит
        whole = (numbers["heal_base"] - HEALTH_MAX // HEAL_HEALTH_DIVISOR) * numbers["heal_step"]
        self.assertEqual(whole, 0.0)

    def test_poison_lives_in_the_item_record_not_in_the_class(self) -> None:
        """Отрава — поле записи предмета +0x0C, а не класса."""
        from konung2.effects import ITEM_POISON_AT
        from konung2.items import STRIDE
        self.assertEqual(ITEM_POISON_AT, 0x0C)
        self.assertLess(ITEM_POISON_AT, 16)    # запись предмета шестнадцать байт
        self.assertEqual(STRIDE, 32)           # класс вдвое шире

    def test_poisoned_ammo_exists_in_the_starting_world(self) -> None:
        """Отравленные стрелы в мире есть, и отрава у них маленькая.

        Это и есть проверка, что +0x0C — именно отрава: движок читает это
        поле только у предмета в руке и у боеприпаса, и ровно там оно
        осмысленное — у оружия и щитов ноль, у боеприпаса ноль либо 1, 5,
        10. У прочих видов там 0xFFFF, то есть поле не про них.
        """
        import struct
        from konung2.effects import ITEM_POISON_AT
        from konung2.gamefile import T_ITEMS
        from konung2.paths import game_file
        from konung2.combat import AMMO_COUNT_AT, AMMO_STACK
        data = open(game_file("GAME.0"), "rb").read()
        packs, poisoned, values = 0, 0, set()
        for index in range(1, 4000):
            record = data[T_ITEMS.offset + index * 16:][:16]
            if record[0] not in (0x01, 0x04, 0x0C):
                continue                             # прочим видам это поле не про отраву
            poison = struct.unpack_from("<H", record, ITEM_POISON_AT)[0]
            if record[0] == 0x0C:
                packs += 1
                self.assertEqual(struct.unpack_from("<i", record, AMMO_COUNT_AT)[0], AMMO_STACK)
            else:
                self.assertEqual(poison, 0)          # оружие и щиты в мире чистые
            if poison:
                poisoned += 1
                values.add(poison)
        self.assertGreater(packs, 300)
        self.assertGreater(poisoned, 0)
        self.assertEqual(values, {1, 5, 10})

    def test_world_tick_runs_every_sixteenth_frame(self) -> None:
        """Отрава грызёт не каждый кадр, а по маске 0x0F (VA 0x41C944)."""
        from konung2.effects import WORLD_TICK_EVERY, WORLD_TICK_MASK
        self.assertEqual(WORLD_TICK_MASK, 0x0F)
        self.assertEqual(WORLD_TICK_EVERY, 16)

    def test_poisoned_portrait_differs_only_in_blue(self) -> None:
        """Раненый портрет красный, отравленный — лиловый (VA 0x4305A4)."""
        from konung2.effects import PORTRAIT_HURT, PORTRAIT_POISONED
        self.assertEqual(PORTRAIT_HURT[:2], PORTRAIT_POISONED[:2])
        self.assertLess(PORTRAIT_HURT[2], 0)
        self.assertGreater(PORTRAIT_POISONED[2], 0)


class BuildingContractTest(unittest.TestCase):
    """Постройки: таблица видов, лестница состояний и масло."""

    def test_every_special_slot_has_one_purpose(self) -> None:
        """Проверка базы таблицы видов.

        Первые семь мест поселения — особые, и у каждого одно назначение.
        При верной базе (0x45D840) так и выходит: дом старосты, изба
        знахаря, лавка, кузница, казарма, причал, колодец. Сдвиг на запись
        сразу смешивает казарму с кузницей — поэтому тест и стоит.
        """
        from konung2.gamefile import T_VILLAGES, building_kinds, village
        from konung2.paths import game_file
        names = {kind["kind"]: kind["name"] for kind in building_kinds()}
        data = open(game_file("GAME.0"), "rb").read()
        purpose: dict[int, set[str]] = {slot: set() for slot in range(7)}
        for index in range(T_VILLAGES.count):
            record = data[T_VILLAGES.offset + index * T_VILLAGES.size:][:T_VILLAGES.size]
            if not record[3]:
                continue
            for slot in range(7):
                kind = record[0x18 + slot * 8]
                if kind != 0xFF:
                    purpose[slot].add(names[kind])
        expected = ["Дом старосты", "Изба знахаря", None, "Кузница",
                    "Казарма", "Причал", "Колодец"]
        for slot, name in enumerate(expected):
            with self.subTest(slot=slot):
                if name is None:                      # лавка бывает и палаткой
                    self.assertTrue(purpose[slot] <= {"Лавка купца", "Торговая палатка"})
                else:
                    self.assertEqual(purpose[slot], {name})
        self.assertEqual(village(19)["buildings"][3]["name"], "Кузница")

    def test_each_building_has_a_picture_for_every_state(self) -> None:
        """У постройки есть картинка на каждую ступень — все семь подряд.

        Отсчёт ведётся от того ресурса, что лежит в карте: он и есть
        картинка нынешнего состояния, поэтому соседние берутся сдвигом.
        """
        import json
        from pathlib import Path
        from konung2.buildings import STATE_SPRITES
        from konung2.gamefile import village
        from konung2.res import ObjectsRes
        pack = Path("content_build/maps/19/map.json")
        if not pack.exists():
            self.skipTest("пак не собран")
        document = json.loads(pack.read_text(encoding="utf-8"))
        entries = {row["object"]: row for row in village(19)["buildings"] if row["built"]}
        objects = ObjectsRes.from_game()
        checked = 0
        for building in document["buildings"]:
            entry = entries.get(building["record_slot"])
            if entry is None:
                continue
            base = building["resource_slot"] - entry["state"]
            for state in range(STATE_SPRITES):
                with self.subTest(building=building["record_slot"], state=state):
                    self.assertIsNotNone(objects.entries[base + state])
            checked += 1
        self.assertGreater(checked, 5)

    def test_map_objects_sit_on_their_kind_ladder(self) -> None:
        """Ресурс постройки на карте — это картинка её нынешней ступени.

        У всех построек Чёрного Бора разность «ресурс минус состояние минус
        спрайт вида» одна и та же, а значит лестница читается верно и
        соседние ступени берутся простым отсчётом.
        """
        import json
        from pathlib import Path
        from konung2.gamefile import building_kinds, village
        pack = Path("content_build/maps/19/map.json")
        if not pack.exists():
            self.skipTest("пак не собран")
        document = json.loads(pack.read_text(encoding="utf-8"))
        kinds = {kind["kind"]: kind for kind in building_kinds()}
        entries = {row["object"]: row for row in village(19)["buildings"] if row["built"]}
        shifts = set()
        for building in document["buildings"]:
            entry = entries.get(building["record_slot"])
            if entry is None:
                continue
            shifts.add(building["resource_slot"] - entry["state"] - kinds[entry["kind"]]["sprite"])
        self.assertEqual(len(shifts), 1, f"разъехались: {shifts}")

    def test_oil_is_a_potion_class_and_fire_is_a_gamble(self) -> None:
        """Масло — класс 87, а поджог удаётся не всегда."""
        from konung2.buildings import (AMMO_KIND, IGNITE_CHANCE, OIL_CLASS,
                                       OIL_CLEAN, OIL_MARK, STATE_ASHES, STATE_READY)
        from konung2.effects import POTION_OIL
        from konung2.items import read_items
        self.assertEqual(OIL_CLASS, POTION_OIL)
        self.assertEqual(read_items()[OIL_CLASS].name, "Масло")
        self.assertEqual(AMMO_KIND, 0x0C)
        self.assertEqual((OIL_MARK, OIL_CLEAN), (0, 0xFF))
        self.assertEqual(IGNITE_CHANCE, 21)
        self.assertLess(STATE_READY, STATE_ASHES)

    def test_burning_is_slower_than_building_for_the_stockade(self) -> None:
        """У частокола горение дольше стройки — числа берутся из разных полей."""
        from konung2.gamefile import building_kinds
        stockade = next(k for k in building_kinds() if k["name"] == "Частокол")
        self.assertEqual((stockade["build_time"], stockade["burn_step"]), (12, 45))


class CursorContractTest(unittest.TestCase):
    """Курсоры: девять картинок из GRAPH.RES и правила выбора."""

    def test_graph_res_holds_nine_cursors_of_one_size(self) -> None:
        """Девять кусков за палитрами — это и есть курсоры, все 32x32."""
        import struct
        from konung2.cursors import COUNT
        from konung2.graph import GraphRes
        graph = GraphRes.from_game()
        self.assertEqual(len(graph.blocks), COUNT)
        for index, (start, length) in enumerate(graph.blocks):
            with self.subTest(cursor=index):
                width, height = struct.unpack_from("<2H", graph.data, start)
                self.assertEqual((width, height), (32, 32))
                # длина куска обязана сойтись: заголовок, таблица строк и сами строки
                rows = struct.unpack_from(f"<{height}H", graph.data, start + 4)
                self.assertEqual(4 + 2 * height + sum(rows), length)

    def test_every_cursor_row_decodes_to_full_width(self) -> None:
        """Разбор строки сходится точка в точку, а остриё лежит в углу."""
        from konung2.cursors import COUNT, decode
        for index in range(COUNT):
            rows = decode(index)
            with self.subTest(cursor=index):
                self.assertEqual(len(rows), 32)
                self.assertTrue(all(len(row) == 32 for row in rows))
                # горячая точка — левый верхний угол, и она непрозрачная
                self.assertIsNotNone(rows[0][0])

    def test_carry_cursor_is_the_plain_one(self) -> None:
        """Курсор переноса — то же копьё: вместо него рисуется иконка вещи."""
        from konung2.cursors import CARRY, NORMAL, decode
        self.assertEqual(decode(NORMAL), decode(CARRY))

    def test_exit_cursor_follows_the_target(self) -> None:
        """−1 уводит на глобальную карту, −2 курсор не меняет, номер — переход."""
        from konung2.cursors import TRAVEL, WORLD_MAP, exit_cursor
        self.assertEqual(exit_cursor(-1), WORLD_MAP)
        self.assertIsNone(exit_cursor(-2))
        self.assertEqual(exit_cursor(34), TRAVEL)

    def test_chernyy_bor_exits_ask_for_the_map_cursor(self) -> None:
        """У Чёрного Бора края карты — выход на глобальную (курсор со свитком)."""
        from konung2.cursors import WORLD_MAP, exit_cursor
        from konung2.gamefile import map_exits
        cursors = {exit_cursor(door["to_map"]) for door in map_exits(19)}
        self.assertIn(WORLD_MAP, cursors)


class CarryContractTest(unittest.TestCase):
    """Перенос вещей: вес, гнёзда, стопки и квестовые вещи."""

    def test_weight_limit_grows_with_stamina(self) -> None:
        """Предел веса — двадцать кило плюс треть кило за выносливость."""
        from konung2.carry import weight_limit
        self.assertEqual(weight_limit(0), 20000)
        self.assertEqual(weight_limit(21), 27000)
        self.assertEqual(weight_limit(60), 40000)

    def test_stamina_is_the_sixth_current_characteristic(self) -> None:
        """Тот же байт unit+0xD1 делит урон и держит вес."""
        from konung2.carry import CURRENT_AT, STAMINA_AT
        from konung2.gamefile import UNIT_CURRENT_AT
        from konung2.progress import CHARACTERISTICS
        self.assertEqual(CURRENT_AT, UNIT_CURRENT_AT)
        self.assertEqual(STAMINA_AT - CURRENT_AT, len(CHARACTERISTICS) - 1)
        self.assertEqual(CHARACTERISTICS[-1], "Выносливость")

    def test_bolt_boundary_matches_the_item_names(self) -> None:
        """Граница 0xCD делит боеприпас ровно по названиям.

        Всё, что до неё, зовётся «для лука», всё, что после, — «для
        арбалета». Значит правило движка про самострел и болты прочитано
        верно, а не подогнано.
        """
        from konung2.carry import BOLT_CLASS_FROM, ammo_fits, is_bolt
        from konung2.combat import CROSSBOW_LAYER
        from konung2.items import read_items
        for index, item in enumerate(read_items()):
            if "для лука" in item.name:
                with self.subTest(item.name):
                    self.assertFalse(is_bolt(index))
            elif "для арбалета" in item.name:
                with self.subTest(item.name):
                    self.assertTrue(is_bolt(index))
        self.assertEqual(BOLT_CLASS_FROM, 205)
        self.assertTrue(ammo_fits(CROSSBOW_LAYER, 207))     # самострелу болты
        self.assertFalse(ammo_fits(CROSSBOW_LAYER, 204))    # но не стрелы
        self.assertTrue(ammo_fits(19, 204))                 # луку стрелы
        self.assertFalse(ammo_fits(19, 207))                # но не болты

    def test_stacks_never_grow_past_thirty(self) -> None:
        """Пачка режется по тридцати, остаток остаётся в руке."""
        from konung2.carry import STACK_MAX, merge_stacks
        from konung2.combat import AMMO_STACK
        self.assertEqual(STACK_MAX, AMMO_STACK)
        self.assertEqual(merge_stacks(10, 15), (25, 0))
        self.assertEqual(merge_stacks(20, 20), (30, 10))
        self.assertEqual(merge_stacks(30, 30), (30, 30))

    def test_quest_items_are_the_ones_without_a_price(self) -> None:
        """Нулевая цена — признак квестовой вещи, её нельзя бросить."""
        from konung2.carry import QUEST_PRICE
        from konung2.items import read_items
        free = [item.name for item in read_items()
                if item.price == QUEST_PRICE and item.name.strip()]
        self.assertGreater(len(free), 20)
        self.assertIn("Берестяная грамота", free)
        self.assertIn("Волшебный фиал с кровью Титанов", free)
        # а обычное снаряжение цену имеет
        priced = {item.name: item.price for item in read_items()}
        self.assertGreater(priced["Кинжал"], 0)

    def test_messages_are_the_engine_strings(self) -> None:
        """Сообщения переноса — строки из exe, слово в слово."""
        import struct
        from konung2.carry import MESSAGES
        from konung2.exetables import va_to_foff
        from konung2.paths import game_file
        blob = open(game_file("konung2.exe"), "rb").read()
        for va, key in ((0x4504E2, "weight"), (0x4504EF, "bag_full"),
                        (0x45024C, "requirement")):
            with self.subTest(key):
                at = va_to_foff(va)
                text = blob[at:blob.index(b"\x00", at)].decode("cp866")
                self.assertEqual(text, MESSAGES[key])


class JewelleryContractTest(unittest.TestCase):
    """Второй набор гнёзд: украшения и их прибавки."""

    def test_five_slots_split_as_one_two_two(self) -> None:
        """Ожерелье одно, браслета два, кольца два — всего пять."""
        from konung2.jewellery import (KIND_BRACELET, KIND_NECKLACE, KIND_RING,
                                       SECOND_SLOTS, slots_for)
        self.assertEqual(len(slots_for(KIND_NECKLACE)), 1)
        self.assertEqual(len(slots_for(KIND_BRACELET)), 2)
        self.assertEqual(len(slots_for(KIND_RING)), 2)
        total = sum(len(slots_for(kind)) for kind in (KIND_NECKLACE, KIND_BRACELET, KIND_RING))
        self.assertEqual(total, SECOND_SLOTS)

    def test_slot_names_match_the_equipment_window(self) -> None:
        """Имена гнёзд сходятся с раскладкой окна снаряжения.

        Раскладку я разбирал по таблице окна, а виды — по обработчику
        второго набора; то, что они совпали, и есть проверка обоих.
        """
        from konung2.interf import SLOT_LAYOUT
        from konung2.jewellery import NAMES
        self.assertEqual([NAMES[code] for code in sorted(NAMES)],
                         [name for name in SLOT_LAYOUT
                          if name in set(NAMES.values())])

    def test_kinds_six_seven_eight_are_the_adornments(self) -> None:
        """Вид 6 — ожерелье, 7 — браслет, 8 — кольцо, по самим вещам мира."""
        from konung2.gamefile import class_kinds
        from konung2.items import read_items
        from konung2.jewellery import KIND_BRACELET, KIND_NECKLACE, KIND_RING
        classes = read_items()
        names = {}
        for class_index, kind in class_kinds().items():
            if kind in (KIND_NECKLACE, KIND_BRACELET, KIND_RING):
                names.setdefault(kind, set()).add(classes[class_index].name)
        self.assertEqual(names[KIND_NECKLACE], {"Ожерелье"})
        self.assertEqual(names[KIND_BRACELET], {"Браслет"})
        self.assertEqual(names[KIND_RING], {"Кольцо"})

    def test_enchant_levels_grow_by_the_table(self) -> None:
        """Характеристикам от +1 до +6, урону от +4 до +48."""
        from konung2.enchant import GROUPS, GROUP_LEVELS, table
        rows = table()
        for shift, section in GROUPS:
            values = [rows[section + level]["value"] for level in range(GROUP_LEVELS)]
            with self.subTest(shift=shift):
                self.assertEqual(values, sorted(values))       # растут
                self.assertIn(values, ([1, 2, 3, 4, 5, 6], [4, 12, 20, 28, 40, 48]))

    def test_dormant_magic_gives_nothing_until_opened(self) -> None:
        """Со старшим битом прибавок нет, без него — есть."""
        from konung2.enchant import DORMANT, bonuses
        word = 0x3028
        self.assertEqual(bonuses(word), {7: 20, 5: 5})
        self.assertEqual(bonuses(word | DORMANT), {})

    def test_world_adornments_carry_real_bonuses(self) -> None:
        """У украшений мира прибавки настоящие, и часть из них не опознана."""
        import struct
        from konung2.gamefile import T_ITEMS
        from konung2.enchant import DORMANT, ENCHANT_AT, bonuses, table
        from konung2.paths import game_file
        data = open(game_file("GAME.0"), "rb").read()
        rows = table()
        total, dormant, fields = 0, 0, set()
        for index in range(1, 4000):
            record = data[T_ITEMS.offset + index * 16:][:16]
            if record[0] not in (6, 7, 8):
                continue
            total += 1
            word = struct.unpack_from("<H", record, ENCHANT_AT)[0]
            if word & DORMANT:
                dormant += 1
                self.assertEqual(bonuses(word, rows), {})
            else:
                self.assertTrue(bonuses(word, rows), f"украшение #{index} без прибавок")
                fields.update(bonuses(word, rows))
        self.assertGreater(total, 20)
        self.assertGreater(dormant, 0)
        self.assertTrue(fields <= {2, 5, 6, 7, 8})

    def test_identify_raises_the_right_skill(self) -> None:
        """Опознание поднимает пятнадцатый навык — «Идентификация предметов»."""
        from konung2.enchant import IDENTIFY_CAP, IDENTIFY_SKILL
        from konung2.progress import SKILLS
        self.assertEqual(SKILLS[IDENTIFY_SKILL], "Идентификация предметов")
        self.assertEqual(IDENTIFY_CAP, 100)


class EnchantContractTest(unittest.TestCase):
    """Зачарование: поля, цена и опознание."""

    def test_fields_land_in_their_unit_slots(self) -> None:
        """Поле 7 — броня, 8 — сила удара, 9 — точность."""
        from konung2.enchant import (FIELD_ACCURACY, FIELD_ARMOUR, FIELD_STRIKE,
                                     FIELD_UNIT_AT, MODE_BIT)
        self.assertEqual(FIELD_UNIT_AT[FIELD_ARMOUR], 0x42)
        self.assertEqual(FIELD_UNIT_AT[FIELD_STRIKE], 0x44)
        self.assertEqual(FIELD_UNIT_AT[FIELD_ACCURACY], 0x46)
        self.assertEqual(sorted(MODE_BIT.values()), [1, 2, 4])

    def test_armour_pieces_never_get_the_strike_bonus(self) -> None:
        """Проверка того, что поля не перепутаны.

        Если бы 7 и 8 стояли наоборот, кольчуга давала бы +28 к удару, а
        арбалет +48 брони. В самих вещах мира этого нет: доспехам, шлемам
        и щитам достаётся только броня, метательному — только сила удара.
        """
        import struct
        from konung2.enchant import (ENCHANT_AT, FIELD_ARMOUR, FIELD_STRIKE,
                                     bonuses, table)
        from konung2.gamefile import T_ITEMS
        from konung2.paths import game_file
        data = open(game_file("GAME.0"), "rb").read()
        rows = table()
        armour_kinds, weapon_kinds = {2, 3, 4}, {1}
        seen_armour = seen_strike = 0
        for index in range(1, 4000):
            record = data[T_ITEMS.offset + index * 16:][:16]
            if record[0] in (0, 0xFF):
                continue
            fields = bonuses(struct.unpack_from("<H", record, ENCHANT_AT)[0], rows)
            if record[0] in armour_kinds:
                with self.subTest(index=index):
                    self.assertNotIn(FIELD_STRIKE, fields)
                seen_armour += FIELD_ARMOUR in fields
            elif record[0] in weapon_kinds:
                with self.subTest(index=index):
                    self.assertNotIn(FIELD_ARMOUR, fields)
                seen_strike += FIELD_STRIKE in fields
        self.assertGreater(seen_armour, 0)
        self.assertGreater(seen_strike, 0)

    def test_enchant_raises_the_price_only_when_identified(self) -> None:
        """Неопознанная магия продаётся как простая железка (VA 0x41ABBC)."""
        from konung2.enchant import DORMANT, price_bonus
        from konung2.trade import item_price
        self.assertEqual(price_bonus(0x4000), 140)
        self.assertEqual(price_bonus(0x4000 | DORMANT), 0)
        self.assertEqual(item_price(1000, 0x4000), 1140)
        self.assertEqual(item_price(1000, 0x4000 | DORMANT), 1000)

    def test_the_second_table_is_switched_off_in_every_world(self) -> None:
        """Байт +0x01 со своей таблицей прибавок нигде не задействован."""
        from konung2.enchant import SECOND_BYTE_AT
        from konung2.gamefile import T_ITEMS
        from konung2.paths import game_file
        for world in range(4):
            values = set()
            data = open(game_file(f"GAME.{world}"), "rb").read()
            for index in range(1, 4000):
                record = data[T_ITEMS.offset + index * 16:][:16]
                if record[0] in (0, 0xFF):
                    continue
                values.add(record[SECOND_BYTE_AT])
            with self.subTest(world=world):
                self.assertEqual(values, {0xFF})     # 0xFF — «выключено»

    def test_most_magic_in_the_world_is_unidentified(self) -> None:
        """Больше половины зачарованных вещей лежат неопознанными."""
        import struct
        from konung2.enchant import DORMANT, ENCHANT_AT
        from konung2.gamefile import T_ITEMS
        from konung2.paths import game_file
        data = open(game_file("GAME.0"), "rb").read()
        total = dormant = 0
        for index in range(1, 4000):
            record = data[T_ITEMS.offset + index * 16:][:16]
            if record[0] in (0, 0xFF):
                continue
            word = struct.unpack_from("<H", record, ENCHANT_AT)[0]
            if not word:
                continue
            total += 1
            dormant += bool(word & DORMANT)
        self.assertGreater(total, 100)
        self.assertGreater(dormant, total // 2)


class TradeScreenContractTest(unittest.TestCase):
    """Торговый экран: раскладка из exe."""

    def test_four_rows_of_nine_cells(self) -> None:
        """Четыре ряда по девять видимых ячеек, ячейка и шаг как у пояса."""
        from konung2.interf import BELT
        from konung2.trade import screen
        layout = screen()
        self.assertEqual(len(layout["columns"]), 4)
        self.assertEqual(layout["visible"], 9)
        self.assertEqual(layout["slots"], 42)
        self.assertEqual(layout["cell"]["pitch"], BELT["pitch"])
        self.assertEqual(layout["cell"]["width"], BELT["cell"])

    def test_rows_run_his_stock_then_mine(self) -> None:
        """Сверху вниз: его товар, его выкладка, моя выкладка, мой мешок."""
        from konung2.trade import screen
        layout = screen()
        rows = {row["column"]: row for row in layout["columns"]}
        order = layout["order"]
        self.assertEqual(order, [2, 3, 1, 0])
        heights = [rows[column]["y"] for column in order]
        self.assertEqual(heights, sorted(heights))       # и правда сверху вниз
        # ряды одной ширины и стоят друг под другом
        self.assertEqual({rows[column]["x"] for column in order}, {288})

    def test_nine_cells_fit_the_row(self) -> None:
        """Девять ячеек с шагом 69 умещаются в ряд вместе со стрелками."""
        from konung2.trade import COLUMN_VISIBLE, CELL_PITCH, screen
        row = screen()["columns"][0]
        self.assertLessEqual(COLUMN_VISIBLE * CELL_PITCH, row["width"])

    def test_two_buttons_with_engine_codes(self) -> None:
        """Кнопок две: «Ok» закрывает сделку, «Закрыть» возвращает всё."""
        from konung2.trade import screen
        buttons = screen()["buttons"]
        self.assertEqual([button["code"] for button in buttons], [200, 201])
        deal = next(button for button in buttons if button["action"] == "deal")
        self.assertEqual((deal["code"], deal["sprite"]), (201, 182))
        refuse = next(button for button in buttons if button["action"] == "refuse")
        self.assertEqual((refuse["code"], refuse["sprite"]), (200, 180))

    def test_six_numbers_are_on_the_screen(self) -> None:
        """Шесть чисел: два кошелька, два стола и два итога."""
        from konung2.trade import screen
        numbers = screen()["numbers"]
        self.assertEqual(len(numbers), 6)
        for rect in numbers:
            with self.subTest(rect=rect):
                self.assertGreater(rect["width"], 0)
                self.assertGreater(rect["height"], 0)

    def test_deal_teaches_both_sides(self) -> None:
        """Навык торговли растёт на сумму сделки, делённую на 1024."""
        from konung2.trade import SKILL_CAP, SKILL_PER_DEAL
        self.assertEqual(SKILL_PER_DEAL, 1024)
        self.assertEqual(SKILL_CAP, 100)

    def test_trade_messages_are_the_engine_strings(self) -> None:
        """Сообщения экрана — строки из exe."""
        from konung2.trade import MESSAGES
        from konung2.exetables import va_to_foff
        from konung2.paths import game_file
        blob = open(game_file("konung2.exe"), "rb").read()
        for va, key in ((0x4502B3, "weight"), (0x4502C0, "pile_full"),
                        (0x4502E7, "too_little")):
            with self.subTest(key):
                at = va_to_foff(va)
                self.assertEqual(blob[at:blob.index(b"\x00", at)].decode("cp866"),
                                 MESSAGES[key])


class CraftContractTest(unittest.TestCase):
    """Камни и снадобья: где их применяют и что выходит."""

    def test_stone_names_match_the_fields_they_raise(self) -> None:
        """Окончательная проверка полей зачарования.

        Камни названы своими словами, и каждый пишет ровно в ту группу
        битов, которую я по коду назвал бронёй, силой удара, ловкостью,
        силой и выносливостью.
        """
        from konung2.craft import STONE_GROUPS
        from konung2.enchant import GROUPS, table
        from konung2.items import read_items
        classes = read_items()
        rows = table()
        section = {shift: start for shift, start in GROUPS}
        expect = {
            "Магический камень брони": 7,
            "Магический камень удара": 8,
            "Магический камень ловкости": 2,
            "Магический камень силы": 5,
            "Магический камень выносливости": 6,
        }
        for item_class, shift in STONE_GROUPS.items():
            name = classes[item_class].name
            field = rows[section[shift]]["field"]
            with self.subTest(name):
                self.assertEqual(field, expect[name])

    def test_stone_needs_sorcery_and_an_identified_item(self) -> None:
        """Камень берёт только опознанную вещь и поднимает на навык/16."""
        from konung2.craft import enchant_with_stone, stone_step
        self.assertEqual(stone_step(0), 0)
        self.assertEqual(stone_step(50), 3)
        self.assertEqual(stone_step(100), 6)
        # чистая вещь при волховании 50 получает третий уровень брони
        self.assertEqual(enchant_with_stone(0x0000, 52, 50), 0x3000)
        # неопознанную не тронуть
        self.assertIsNone(enchant_with_stone(0x8000, 52, 50))
        # шестой уровень уже не поднять
        self.assertIsNone(enchant_with_stone(0x6000, 52, 50))
        # а при нулевом навыке камень пропадает впустую
        self.assertEqual(enchant_with_stone(0x0000, 52, 10), 0x0000)

    def test_three_herbs_make_three_potions(self) -> None:
        """Основа книги рецептов: три сырья в пустую банку."""
        from konung2.craft import mix, recipes
        from konung2.items import read_items
        classes = read_items()
        rows = recipes()
        self.assertEqual(len(rows), 30)
        empty = next(index for index, item in enumerate(classes)
                     if item.name == "Пустая банка")
        made = {}
        for row in rows:
            if row["target"] == empty:
                made[classes[row["poured"]].name] = classes[row["result"]].name
        self.assertEqual(made["Ядовитое жало"], "Яд")
        self.assertEqual(made["Земляной орех"], "Масло")
        self.assertEqual(made["Белый корень"], "Лечебный бальзам")
        # и смеси второго круга
        balm = next(index for index, item in enumerate(classes)
                    if item.name == "Лечебный бальзам")
        poison = next(index for index, item in enumerate(classes)
                      if item.name == "Яд")
        self.assertEqual(classes[mix(balm, poison)["result"]].name, "Противоядие")

    def test_a_failed_mix_is_the_strange_brew(self) -> None:
        """Не нашлось рецепта — выходит «Непонятная смесь», а она бьёт по здоровью."""
        from konung2.craft import FAILED_MIX_CLASS, mix
        from konung2.effects import POTION_HALVE
        from konung2.items import read_items
        self.assertEqual(FAILED_MIX_CLASS, POTION_HALVE)
        self.assertEqual(read_items()[FAILED_MIX_CLASS].name, "Непонятная смесь")
        self.assertIsNone(mix(86, 83))          # яд в пустую банку не льют

    def test_the_twelfth_slot_is_the_mixing_place(self) -> None:
        """Двенадцатое гнездо окна — место смешивания, и подсказка своя."""
        from konung2.craft import MIXING_CODE, MIXING_SLOT, rules
        from konung2.interf import SLOT_LAYOUT
        self.assertEqual(SLOT_LAYOUT[MIXING_SLOT], "mixing")
        self.assertEqual(MIXING_CODE, 0x1C)
        self.assertIn("волшебные камни", rules()["slot"]["hint"])

    def test_the_two_crafting_skills_are_named(self) -> None:
        """Навык 12 варит, навык 16 зачаровывает."""
        from konung2.craft import BREW_SKILL, SORCERY_SKILL
        from konung2.progress import SKILLS, SKILLS_AT
        from konung2.craft import BREW_SKILL_AT, SORCERY_SKILL_AT
        self.assertEqual(SKILLS[BREW_SKILL], "Приготовление смесей")
        self.assertEqual(SKILLS[SORCERY_SKILL], "Волхование")
        self.assertEqual(SKILLS_AT + BREW_SKILL, BREW_SKILL_AT)
        self.assertEqual(SKILLS_AT + SORCERY_SKILL, SORCERY_SKILL_AT)


class GroundPileContractTest(unittest.TestCase):
    """Кучи на земле: запись на клетку, а не на предмет."""

    def test_pile_record_is_a_cell_with_forty_two_places(self) -> None:
        """Куча — запись 101 байт: клетка, деньги и сорок два места."""
        from konung2.carry import BAG_SLOTS, GROUND_PILES
        from konung2.piles import PILE_ITEMS_AT, PILE_MONEY_AT, PILE_SLOTS, PILE_STRIDE
        self.assertEqual(PILE_STRIDE, 0x65)
        self.assertEqual(PILE_SLOTS, BAG_SLOTS)
        self.assertEqual(PILE_ITEMS_AT + PILE_SLOTS * 2, PILE_STRIDE)
        self.assertLess(PILE_MONEY_AT, PILE_ITEMS_AT)
        self.assertEqual(GROUND_PILES, 200)

    def test_single_item_shows_its_own_sprite(self) -> None:
        """Одна вещь без денег лежит собой, две и больше — мешочком."""
        from konung2.items import GROUND_PILE_SPRITE
        from konung2.piles import pile_sprite
        self.assertEqual(pile_sprite(["Нож"], 0, 166), 166)
        self.assertEqual(pile_sprite(["Нож", "Меч"], 0, 166), GROUND_PILE_SPRITE)
        self.assertEqual(pile_sprite(["Нож"], 40, 166), GROUND_PILE_SPRITE)
        self.assertEqual(GROUND_PILE_SPRITE, 163)


class DialogueHandlerContractTest(unittest.TestCase):
    """Обработчики разговора, без которых Чёрный Бор молчит по-ночному."""

    def test_handler_21_is_the_night_flag(self) -> None:
        """21 отдаёт флаг ночи — тот же, что ставит расчёт неба."""
        from konung2.quests import handler_table
        self.assertEqual(handler_table()[21]["address"], 0x4350C0)

    def test_handler_24_is_a_one_in_n_roll(self) -> None:
        """24 — бросок «один к N»; меньше двух всегда мимо."""
        from konung2.quests import handler_table
        self.assertEqual(handler_table()[24]["address"], 0x435340)

    def test_the_dispatch_table_is_identified(self) -> None:
        """В5: таблица 0x462E90 — 76 записей, опознаны все, кроме №25.

        Каждое имя в HANDLER_NAMES обязано совпасть адресом с exe —
        расхождение значит, что запись прибита к чужому слоту.
        """
        from konung2.quests import HANDLER_NAMES, handler_table
        table = handler_table()
        self.assertEqual(len(table), 76)
        named = [row for row in table if row["name"]]
        self.assertGreaterEqual(len(named), 75)
        for row in named:
            self.assertTrue(row["verified"], (row["index"], row["name"]))
        # выборочные якоря новых опознаний
        self.assertEqual(table[54]["address"], 0x4345A4)   # лечит игрока
        self.assertEqual(table[65]["address"], 0x4358BC)   # чинит отряд
        self.assertEqual(table[67]["address"], 0x435A2C)   # метка времени
        self.assertEqual(table[40]["address"], 0x433730)   # заложить постройку
        self.assertEqual(len(HANDLER_NAMES), 75)

    def test_skill_gate_handlers_sit_in_their_slots(self) -> None:
        """Гейты навыков: 5 — Строительные, 10 — Знахарство, 26 — Кузнечное."""
        from konung2.quests import handler_table
        table = handler_table()
        self.assertEqual(table[5]["address"], 0x434B88)
        self.assertEqual(table[10]["address"], 0x434DEC)
        self.assertEqual(table[26]["address"], 0x4353FC)
        for index in (5, 10, 26):
            self.assertTrue(table[index]["verified"], index)

    def test_potion_price_is_per_strength(self) -> None:
        """У зелий цена отрицательная: столько за единицу крепости."""
        from konung2.items import POTION_PRICE_SCALE, read_items
        classes = {item.name: item for item in read_items()}
        balm = classes["Лечебный бальзам"]
        self.assertLess(balm.price, 0)
        self.assertEqual(balm.cost(strength=3), -balm.price * 3 * POTION_PRICE_SCALE)
        # у обычной вещи цена как есть
        self.assertEqual(classes["Кинжал"].cost(), classes["Кинжал"].price)
        # у стопки — за штуку
        arrows = classes["Железные стрелы для лука:"]
        self.assertEqual(arrows.cost(count=30), arrows.price * 30)

    def test_black_forest_has_someone_to_trade_with(self) -> None:
        """На Чёрном Бору есть у кого купить: деньги и товар настоящие."""
        from konung2.gamefile import map_units
        traders = [unit for unit in map_units(19) if unit["bag"] or unit["money"]]
        self.assertGreater(len(traders), 3)
        names = {unit["name"]: unit for unit in map_units(19)}
        self.assertIn("Ядовитое жало", names["Святовит"]["bag"])
        self.assertIn("Пустая банка", names["Добрыня"]["bag"])


class OrderContractTest(unittest.TestCase):
    """Приказы: байт делится пополам, и половины не мешают друг другу."""

    def test_order_byte_splits_into_kind_and_mode(self) -> None:
        """Знакомые числа собираются из битов режима и вида действия."""
        from konung2.orders import (KIND_GO, KIND_NONE, KIND_TALK, MODE_FOLLOW,
                                    MODE_PLAYER, ORDER_FOLLOW, ORDER_FOLLOW_ORDERED,
                                    ORDER_GO, ORDER_TALK, follows, order_byte,
                                    order_kind, order_mode)
        self.assertEqual(order_byte(KIND_NONE, MODE_FOLLOW), ORDER_FOLLOW)
        self.assertEqual(order_byte(KIND_GO, MODE_PLAYER), ORDER_GO)
        self.assertEqual(order_byte(KIND_TALK, MODE_PLAYER), ORDER_TALK)
        self.assertEqual((ORDER_FOLLOW, ORDER_FOLLOW_ORDERED, ORDER_GO, ORDER_TALK),
                         (0x10, 0x30, 0x26, 0x22))
        self.assertEqual(order_kind(ORDER_GO), KIND_GO)
        self.assertEqual(order_mode(ORDER_GO), MODE_PLAYER)
        # бит «за вожаком» стоит и в 0x10, и в 0x30 — движок смотрит только его
        self.assertTrue(follows(ORDER_FOLLOW))
        self.assertTrue(follows(ORDER_FOLLOW_ORDERED))
        self.assertFalse(follows(ORDER_GO))

    def test_follow_distance_differs_by_side(self) -> None:
        """Свои догоняют вожака с десяти клеток, чужие с пяти (VA 0x41209C)."""
        from konung2.orders import follow_distance
        self.assertEqual(follow_distance(True), 10)
        self.assertEqual(follow_distance(False), 5)

    def test_giving_an_order_keeps_the_mode(self) -> None:
        """Выдача приказа меняет только младшую половину (VA 0x416574)."""
        from konung2.orders import KIND_GO, ORDER_FOLLOW, give, order_mode
        after = give(ORDER_FOLLOW, KIND_GO)
        self.assertEqual(order_mode(after), order_mode(ORDER_FOLLOW))
        self.assertEqual(after & 0x0F, KIND_GO)

    def test_talk_needs_the_hero_to_come_close(self) -> None:
        """Разговор начинается в семи строках и четырёх столбцах, не раньше."""
        from konung2.orders import TALK_COLS, TALK_ROWS, can_talk
        self.assertTrue(can_talk(6, 3))
        self.assertFalse(can_talk(7, 0))
        self.assertFalse(can_talk(0, 4))
        self.assertEqual((TALK_ROWS, TALK_COLS), (7, 4))

    def test_selection_holds_nine(self) -> None:
        """Список выбора — девять мест, как массив 0x840B94."""
        from konung2.orders import SELECTION_MAX
        self.assertEqual(SELECTION_MAX, 9)


class CellRangeContractTest(unittest.TestCase):
    """Мера расстояния: движок считает клетками, а не пикселями."""

    def test_range_is_king_move_plus_diagonal(self) -> None:
        """Берётся большая разница, и за диагональ прибавляется единица."""
        from konung2.cells import cell_range
        self.assertEqual(cell_range(0, 0, 0, 5), 5)        # по прямой
        self.assertEqual(cell_range(0, 0, 5, 0), 5)
        self.assertEqual(cell_range(0, 0, 1, 5), 5)        # меньшая сторона 1
        self.assertEqual(cell_range(0, 0, 2, 5), 6)        # меньшая больше 1
        self.assertEqual(cell_range(3, 3, 3, 3), 0)
        self.assertEqual(cell_range(0, 0, 1, 1), 1)

    def test_range_is_symmetric(self) -> None:
        """Мера не зависит от того, кто кого меряет."""
        from konung2.cells import cell_range
        for a, b, c, d in ((0, 0, 7, 3), (11, 2, 4, 9), (5, 5, 5, 12)):
            with self.subTest((a, b, c, d)):
                self.assertEqual(cell_range(a, b, c, d), cell_range(c, d, a, b))


class PileExchangeContractTest(unittest.TestCase):
    """Что остаётся в куче после обмена — по VA 0x41F638."""

    def test_pile_keeps_what_was_not_taken(self) -> None:
        """В кучу возвращаются МОЯ выкладка и её нетронутое, взятое уходит.

        Движок переписывает список кучи целиком: сперва ряд 1 (что игрок
        выложил), потом ряд 2 (что в куче не тронули). Ряд 3 к этому
        моменту уже уехал в мешок игрока, поэтому взятое из кучи
        пропадает — ровно этого не хватало.
        """
        from konung2.piles import PILE_ITEMS_AT, PILE_SLOTS
        # ряды обмена в памяти движка идут подряд по 0x54 байта
        row0, row1, row2, row3 = 0x843DF4, 0x843E48, 0x843E9C, 0x843EF0
        self.assertEqual(row1 - row0, PILE_SLOTS * 2)
        self.assertEqual(row2 - row1, PILE_SLOTS * 2)
        self.assertEqual(row3 - row2, PILE_SLOTS * 2)
        # а в самой куче список начинается с +0x11
        self.assertEqual(PILE_ITEMS_AT, 0x11)

    def test_empty_pile_leaves_the_ground(self) -> None:
        """Пустая куча снимается с клетки: бит 0x20 гасится (VA 0x4136A8)."""
        from konung2.piles import CELL_BIT
        self.assertEqual(CELL_BIT, 0x20)


class UnitLookContractTest(unittest.TestCase):
    """Чем юниты отличаются друг от друга внешне."""

    def test_body_byte_picks_a_layer_for_people(self) -> None:
        """Тело человека — слой 0x30 + число из unit+0xFC (VA 0x424200)."""
        from konung2.heroes import BODY_LAYER_FIELD, HeroesRes, LAYER_COUNT
        self.assertEqual(BODY_LAYER_FIELD, 0xFC)
        # слой женского тела существует и не пустой
        res = HeroesRes.from_game()
        sprite, _, _ = res.decode_layer(0, layer=0x30 + 1)
        self.assertIsNotNone(sprite)
        self.assertGreater(sprite.width, 8)
        self.assertLess(0x30 + 1, LAYER_COUNT)

    def test_velislavna_is_the_only_woman_of_black_forest(self) -> None:
        """У Велиславны тело единица, у остальных ноль — оттого она и женщина."""
        from konung2.gamefile import map_units
        bodies = {unit["name"]: unit["body"] for unit in map_units(19)}
        self.assertEqual(bodies["Велиславна"], 1)
        for name, body in bodies.items():
            if name != "Велиславна":
                with self.subTest(name):
                    self.assertEqual(body, 0)

    def test_beasts_are_marked_by_the_breed_byte(self) -> None:
        """Зверь помечен битом 0x40 породы, и рисуется он не слоем, а набором."""
        from konung2.gamefile import map_units
        breeds = {unit["breed"] for unit in map_units(34)}
        self.assertTrue({66, 73, 75, 86} <= breeds)      # у Волхва четыре породы
        for breed in breeds:
            if breed > 0x40:
                with self.subTest(breed=breed):
                    self.assertTrue(breed & 0x40)
        # а на Чёрном Бору зверей нет вовсе
        self.assertTrue(all(unit["breed"] < 0x40 for unit in map_units(19)))


class CreatureContractTest(unittest.TestCase):
    """Кадры тварей: OBJECTS.RES, записи 0…29."""

    def test_first_thirty_entries_are_creatures(self) -> None:
        """Записи до тридцатой — огромные наборы кадров, дальше объекты карты."""
        from konung2.creatures import CREATURE_ENTRIES, catalogue
        rows = catalogue()
        for body in range(CREATURE_ENTRIES):
            with self.subTest(body=body):
                # самый скромный набор (пятнадцатый) — 124 килобайта,
                # остальные от трети мегабайта и выше
                self.assertGreater(rows[body][1], 100_000)
        self.assertLess(rows[CREATURE_ENTRIES][1], 100_000)    # а объект куда меньше

    def test_creature_entry_has_table_then_frames(self) -> None:
        """В записи сперва таблица анимаций, а кадры ровно с 0x1728."""
        import struct
        from konung2.creatures import BLOCK_SIZE, CreatureRes
        res = CreatureRes.from_game()
        block = res.entry(8)
        self.assertEqual(struct.unpack_from("<I", block, 0)[0], 0)
        self.assertEqual(struct.unpack_from("<I", block, 4)[0], len(block))
        # первый кадр начинается сразу за шапкой, и он не пустой
        width, height = struct.unpack_from("<2H", block, BLOCK_SIZE + 8)
        self.assertGreater(width, 8)
        self.assertGreater(height, 8)

    def test_creatures_of_the_volhv_map_decode(self) -> None:
        """Все четыре породы у Волхва распаковываются со своей мастью."""
        from konung2.creatures import CreatureRes
        from konung2.gamefile import map_units
        from konung2.res import read_palettes
        res = CreatureRes.from_game()
        palettes = read_palettes()
        beasts = {(unit["body"], unit["palette"]) for unit in map_units(34)
                  if unit["breed"] & 0x40}
        self.assertGreaterEqual(len(beasts), 4)
        for body, palette in sorted(beasts)[:4]:
            with self.subTest(body=body, palette=palette):
                stand = res.animations(body)[0][0]
                self.assertTrue(stand)
                sprite, _, _ = res.decode(body, stand[0],
                                          palette=palettes[palette % len(palettes)])
                self.assertIsNotNone(sprite)
                self.assertGreater(sprite.width, 8)

    def test_unit_palette_is_a_byte_offset(self) -> None:
        """Масть юнита — смещение, а не номер: делится на 512 (VA 0x425DB4)."""
        from konung2.creatures import PALETTE_STRIDE, UNIT_PALETTE_AT
        self.assertEqual((UNIT_PALETTE_AT, PALETTE_STRIDE), (0x2E, 512))


class WorldMapContractTest(unittest.TestCase):
    """Глобальная карта: сетка 24x32, туман, значки и проходимость."""

    def test_start_grid_comes_from_the_exe(self) -> None:
        """На новой игре сетка копируется из exe целиком (VA 0x438A00)."""
        from konung2.worldmap import GRID_SIZE, ROWS, COLS, grid
        self.assertEqual(GRID_SIZE, 0xC00)          # столько движок и копирует
        cells = grid()
        self.assertEqual(len(cells), ROWS)
        self.assertTrue(all(len(row) == COLS for row in cells))

    def test_every_location_stands_on_exactly_one_cell(self) -> None:
        """Шестнадцать локаций, и каждая занимает ровно одну клетку."""
        from collections import Counter
        from konung2.worldmap import grid
        счёт = Counter(cell & 0xFF for row in grid() for cell in row if cell & 0xFF)
        self.assertEqual(len(счёт), 16)
        self.assertEqual(set(счёт.values()), {1})

    def test_markers_match_the_location_pictures(self) -> None:
        """У каждой локации сетки есть значок — и картинка PICS/m<N>.res."""
        from pathlib import Path

        from konung2.paths import game_file
        from konung2.worldmap import markers
        таблица = markers()
        self.assertEqual(len(таблица), 16)
        for location, marker in таблица.items():
            with self.subTest(location=location):
                self.assertGreater(marker["sprite"], 0)
                # движок грузит картинку локации файлом M<n>.RES
                self.assertTrue(Path(game_file(f"PICS/m{location}.res")).is_file())

    def test_marker_shows_only_after_the_fog_lifts(self) -> None:
        """Значок ждёт двух вещей: клетку увидели и локацию открыли."""
        from konung2.worldmap import (FLAG_HIDDEN, grid, marker_visible,
                                      open_location, reveal)
        cells = grid()
        место = next((row, col) for row in range(24) for col in range(32)
                     if cells[row][col] & 0xFF == 19)
        row, col = место
        self.assertTrue(cells[row][col] >> 24 & FLAG_HIDDEN)  # Чёрный Бор закрыт
        self.assertFalse(marker_visible(cells[row][col]))
        reveal(cells, row, col)                    # пришли на клетку — мало
        self.assertFalse(marker_visible(cells[row][col]))
        open_location(cells, 19)                   # открыли по сюжету — видно
        self.assertTrue(marker_visible(cells[row][col]))

    def test_reveal_lights_the_cell_and_its_neighbours(self) -> None:
        """Своя клетка пройдена, восемь соседних — только видны (VA 0x437ABC)."""
        from konung2.worldmap import FLAG_EXPLORED, FLAG_SEEN, grid, reveal
        cells = grid()
        reveal(cells, 10, 10)
        self.assertTrue(cells[10][10] >> 24 & FLAG_EXPLORED)
        for row, col in ((9, 9), (9, 10), (9, 11), (10, 9),
                         (10, 11), (11, 9), (11, 10), (11, 11)):
            with self.subTest(cell=(row, col)):
                self.assertTrue(cells[row][col] >> 24 & FLAG_SEEN)
                self.assertFalse(cells[row][col] >> 24 & FLAG_EXPLORED)
        self.assertFalse(cells[8][10] >> 24 & (FLAG_EXPLORED | FLAG_SEEN))

    def test_every_location_cell_is_reachable_on_foot(self) -> None:
        """До любой локации можно дойти посуху: маска пускает."""
        from konung2.worldmap import grid, passable
        for row, line in enumerate(grid()):
            for col, cell in enumerate(line):
                if cell & 0xFF:
                    with self.subTest(location=cell & 0xFF):
                        self.assertTrue(passable(row, col))

    def test_party_stands_in_the_middle_of_its_cell(self) -> None:
        """Отряд в клетке (0,0) стоит на (0xB4, 0x27) — как в VA 0x437EA8."""
        from konung2.worldmap import cell_centre, cell_at
        self.assertEqual(cell_centre(0, 0), (0xB4, 0x27))
        self.assertEqual(cell_centre(23, 31), (31 * 0x1A + 0xB4, 23 * 0x1C + 0x27))
        self.assertEqual(cell_at(*cell_centre(7, 12)), (7, 12))

    def test_location_cells_never_spring_random_battles(self) -> None:
        """На клетке локации местность нулевая, а у неё спокойствие 1000/1000."""
        from konung2.worldmap import grid, terrain_table
        table = terrain_table()
        self.assertEqual(table[0]["calm"], 1000)
        for row in grid():
            for cell in row:
                if cell & 0xFF:
                    self.assertEqual((cell >> 8) & 0xFF, 0)

    def test_sea_terrain_fights_on_the_ship(self) -> None:
        """Единственная морская местность дерётся сценой «Корабль в пути»."""
        from konung2.gamefile import location_names
        from konung2.worldmap import SCENE_SEA, terrain_table
        морская = [kind for kind, row in enumerate(terrain_table())
                   if set(row["scenes"]) == {SCENE_SEA}]
        self.assertEqual(морская, [1])
        self.assertEqual(location_names()[SCENE_SEA], "Корабль в пути")

    def test_own_party_and_strangers_use_different_markers(self) -> None:
        """Свой отряд — щит (179), чужой — рогатый шлем в клетку (235)."""
        from konung2.interf import InterfRes
        from konung2.worldmap import PARTY_SPRITE, PLAYER_OFFSET, PLAYER_SPRITE
        self.assertNotEqual(PLAYER_SPRITE, PARTY_SPRITE)
        res = InterfRes.from_game()
        # щит маленький, и сдвиг -7 ставит его серединой в место отряда
        self.assertEqual(res.frame_size(PLAYER_SPRITE), (15, 15))
        self.assertEqual(PLAYER_OFFSET, -(15 - 1) // 2)
        # чужой отряд рисуется по углу клетки, поэтому он ровно с клетку
        from konung2.worldmap import CELL_H, CELL_W
        self.assertEqual(res.frame_size(PARTY_SPRITE), (CELL_W, CELL_H))

    def test_formation_puts_the_first_companion_next_to_the_leader(self) -> None:
        """Первое место расстановки — соседнее с вожаком (таблица 0x461BC0)."""
        from konung2.worldmap import (FORMATION_DIRECTIONS, FORMATION_SLOTS,
                                      formation)
        table = formation()
        self.assertEqual(len(table), 2)                      # чёт и нечет строки
        for parity in range(2):
            self.assertEqual(len(table[parity]), FORMATION_DIRECTIONS)
            for direction in range(FORMATION_DIRECTIONS):
                slots = table[parity][direction]
                self.assertEqual(len(slots), FORMATION_SLOTS)
                first = slots[0]
                with self.subTest(parity=parity, direction=direction):
                    self.assertLessEqual(max(abs(first[0]), abs(first[1])), 2)

    def test_every_encounter_group_has_a_party_behind_it(self) -> None:
        """Каждый номер из таблицы групп 0x45FD90 находит свой отряд."""
        from konung2.worldmap import encounter_templates, terrain_table
        templates = encounter_templates()
        # 33 терраиновые группы плюс шесть ролей бродячих отрядов 141…146
        # (140 общая): движок и их находит тем же поиском по «номеру карты».
        self.assertEqual(len(templates), 39)
        нужные = {group for row in terrain_table() for danger in row["parties"]
                  for group in danger if group}
        self.assertTrue(нужные)
        self.assertFalse(нужные - set(templates))

    def test_encounter_parties_are_the_enemies_of_the_road(self) -> None:
        """В шаблонах стоят разбойники и воины Повелителя, а не жители."""
        from konung2.worldmap import encounter_templates
        имена = {unit["name"] for template in encounter_templates().values()
                 for unit in template["units"]}
        self.assertIn("Разбойник", имена)
        self.assertIn("Воин Повелителя", имена)
        # у каждого шаблона есть хоть один боец, и их не больше восьми
        for group, template in encounter_templates().items():
            with self.subTest(group=group):
                self.assertGreaterEqual(len(template["units"]), 1)
                self.assertLessEqual(len(template["units"]), 8)

    def test_travel_is_measured_in_pixels_not_cells(self) -> None:
        """Длина похода — пиксели между серединами клеток (VA 0x421690)."""
        from konung2.worldmap import CELL_W, TRAVEL_SPEED_SCALE, cell_centre
        left, _ = cell_centre(0, 0)
        right, _ = cell_centre(0, 1)
        self.assertEqual(right - left, CELL_W)
        # кадров на клетку при нулевой прыти: (100*0.01 + 1) * 26 = 52
        frames = round(((100 - 0) * TRAVEL_SPEED_SCALE + 1) * CELL_W)
        self.assertEqual(frames, 52)

    def test_every_world_location_knows_where_the_party_lands(self) -> None:
        """У каждой локации карты мира есть своя клетка прибытия (0x460028)."""
        from konung2.worldmap import arrivals, grid
        table = arrivals()
        локации = {cell & 0xFF for row in grid() for cell in row if cell & 0xFF}
        self.assertFalse(локации - set(table))
        for location in sorted(локации):
            with self.subTest(location=location):
                place = table[location]
                # клетка внутри сетки карты: 255 строк и 159 столбцов
                self.assertTrue(0 < place["row"] < 255)
                self.assertTrue(0 < place["col"] < 159)
                self.assertTrue(0 <= place["facing"] < 8)

    def test_battle_scenes_have_landing_spots_too(self) -> None:
        """Местности случайных боёв — это настоящие карты со своим входом."""
        from konung2.worldmap import arrivals, terrain_table
        table = arrivals()
        сцены = {scene for row in terrain_table() for scene in row["scenes"] if scene}
        self.assertFalse(сцены - set(table))


@needs_game
class DialogCommandContractTest(unittest.TestCase):
    """Язык команд разговора: сборка условий и знаковый аргумент."""

    def test_handler_argument_is_signed(self) -> None:
        """Аргумент приходит в обработчик как (short), а не как u16."""
        from konung2.quests import (CMD_HANDLER, Dialogs, QuestsFile, _commands)
        import struct as _struct
        # искусственная команда с аргументом 0xFFFF: движок передаёт -1
        blob = _struct.pack("<2I", CMD_HANDLER | (0xFFFF << 8) | 24, 0x7FFFFFFF)
        command = _commands(blob, 0, 0)[0]
        self.assertEqual(command["argument"], -1)
        # и настоящие данные: отрицательных аргументов в файле правда много
        quests = Dialogs(QuestsFile.from_game().dialogs)
        negative = 0
        for index in range(600):
            for command in quests.conditions(index) + quests.actions(index):
                if command.get("kind") == "handler" and command["argument"] < 0:
                    negative += 1
        self.assertGreater(negative, 0)

    def test_branch_walk_stops_only_on_a_record_without_condition(self) -> None:
        """Развилка идёт, пока у записей есть условие (VA 0x436478)."""
        from konung2.quests import Dialogs, QuestsFile
        quests = Dialogs(QuestsFile.from_game().dialogs)
        for root in range(150):
            chain = quests.branches(root)
            self.assertTrue(chain)
            # закрывает развилку только запись без условия
            self.assertTrue(chain[-1]["always"] or len(chain) > 1)
            for record in chain[:-1]:
                self.assertFalse(record["always"])


@needs_game
class TradePriceGateContractTest(unittest.TestCase):
    """Кто торгует по настоящим ценам, а кто по базовым."""

    def test_price_gate_bytes_match_the_three_call_sites(self) -> None:
        """Проверка собеседника одинакова в 0x41A6CC, 0x41AF3C и 0x43346C."""
        from konung2.trade import (PRICE_GATE_FLAG, PRICE_GATE_FLAG_AT,
                                   PRICE_GATE_TYPES)
        with open(game_file("konung2.exe"), "rb") as stream:
            blob = stream.read()
        # test byte [eax+0x1a], 0x80 — байт флага и его маска
        pattern = bytes([0xF6, 0x40, PRICE_GATE_FLAG_AT, PRICE_GATE_FLAG])
        for va in (0x41A6CC, 0x41AF3C, 0x43346C):
            at = va_to_foff(va)
            with self.subTest(hex(va)):
                self.assertIn(pattern, blob[at:at + 0x120])
        self.assertEqual(PRICE_GATE_TYPES, (3, 0x0B, 0x0C))

    def test_village_counters_have_their_own_sizes(self) -> None:
        """Прилавок у каждой должности свой: 22, 32 и 39 мест (VA 0x43346C)."""
        from konung2.trade import COUNTERS
        self.assertEqual(COUNTERS, {2: (0x3E0, 0x16), 3: (0x40E, 0x20),
                                    4: (0x44E, 0x27)})
        # прилавки не налезают друг на друга: у должности 3 запас в одно
        # место, у должности 4 её прилавок начинается сразу за прежним
        self.assertLessEqual(0x3E0 + 0x16 * 2, 0x40E)
        self.assertEqual(0x40E + 0x20 * 2, 0x44E)


@needs_game
class CreatureFrameContractTest(unittest.TestCase):
    """Кадры тварей: таблица дескрипторов против байтов OBJECTS.RES."""

    def test_header_is_six_animation_blocks_then_512_descriptors(self) -> None:
        """Шапка: 8 + 6*0x130 = 0x728, дальше 512 дескрипторов до 0x1728."""
        from konung2.creatures import (ANIMATION_BLOCKS, ANIMATION_STRIDE,
                                       BLOCK_SIZE, DESCRIPTORS_AT,
                                       DESCRIPTOR_COUNT, DESCRIPTOR_STRIDE,
                                       TABLE_AT)
        self.assertEqual(ANIMATION_BLOCKS, 6)
        self.assertEqual(TABLE_AT + ANIMATION_BLOCKS * ANIMATION_STRIDE, DESCRIPTORS_AT)
        self.assertEqual(DESCRIPTORS_AT + DESCRIPTOR_COUNT * DESCRIPTOR_STRIDE, BLOCK_SIZE)
        self.assertEqual(DESCRIPTOR_COUNT, 512)

    def test_frames_come_from_the_descriptor_table_not_in_a_row(self) -> None:
        """Кадры берутся по номеру; часть их без тени, и терять их нельзя."""
        from konung2.creatures import CreatureRes, NO_SHADOW
        res = CreatureRes.from_game()
        # тела, которые встречаются на разобранных картах
        for body, expected in ((1, 272), (8, 335), (9, 336), (11, 459), (19, 434)):
            with self.subTest(body=body):
                frames = res.frames(body)
                self.assertEqual(len(frames), expected)
                # номер кадра — это его место в таблице дескрипторов
                self.assertEqual([f["index"] for f in frames], list(range(expected)))
        # у тела 8 кадры без тени есть, и последовательный разбор обрывался
        # ровно на первом из них (220-м)
        frames = res.frames(8)
        self.assertIsNone(frames[220]["shadow_at"])
        self.assertGreater(sum(1 for f in frames if f["shadow_at"] is None), 0)
        entry = res.entry(8)
        shadow_off = struct.unpack_from("<i", entry, 0x728 + 220 * 8)[0]
        self.assertEqual(shadow_off, NO_SHADOW)

    def test_animation_table_only_points_at_frames_that_exist(self) -> None:
        """Все номера из таблицы анимаций разрешаются в настоящие кадры."""
        from konung2.creatures import CreatureRes
        res = CreatureRes.from_game()
        for body in (1, 8, 9, 11, 19):
            with self.subTest(body=body):
                known = {f["index"] for f in res.frames(body)}
                for block in res.animations(body):
                    for direction in block:
                        for number in direction:
                            self.assertIn(number, known)

    def test_shadow_offsets_come_first_in_the_frame_record(self) -> None:
        """Первая пара i16 — тень, вторая — картинка (VA 0x4267E5 и 0x426841)."""
        from konung2.creatures import CreatureRes
        res = CreatureRes.from_game()
        frames = res.frames(1)
        # тень стелется по земле: она шире и ниже картинки, поэтому её
        # смещение по X дальше влево, а по Y — заметно ближе к ногам
        first = frames[0]
        self.assertEqual((first["shadow_dx"], first["shadow_dy"]), (-81, -23))
        self.assertEqual((first["dx"], first["dy"]), (-27, -69))
        self.assertLess(first["shadow_dx"], first["dx"])
        self.assertGreater(first["shadow_dy"], first["dy"])


@needs_game
class LineOfFireContractTest(unittest.TestCase):
    """Можно ли выстрелить: минимум три клетки и чистая траектория."""

    def test_minimum_range_and_blocker_bit_are_in_the_code(self) -> None:
        """VA 0x414AF8: `< 3` отказывает, а путь рвёт бит 0x40 байта +1."""
        from konung2.combat import (BEAST_RANGE_CELLS, LINE_OF_FIRE_BLOCKER,
                                    RANGED_MIN_CELLS)
        from konung2.grid import SOLID
        with open(game_file("konung2.exe"), "rb") as stream:
            blob = stream.read()
        window = blob[va_to_foff(0x414AF8):va_to_foff(0x414AF8) + 0x180]
        # cmp eax, 3 / jge — нижняя граница дальности
        self.assertIn(bytes([0x83, 0xF8, RANGED_MIN_CELLS]), window)
        # у зверей вместо дальности оружия жёсткие 0x28
        self.assertIn(bytes([BEAST_RANGE_CELLS]), window)
        # рвёт траекторию тот же бит, что считает попадание в постройку
        self.assertEqual(LINE_OF_FIRE_BLOCKER, SOLID)

    def test_solid_cells_are_not_the_same_as_impassable(self) -> None:
        """Глухих клеток меньше, чем непроходимых: вода стрелу пропускает."""
        from konung2.world.model import MapModel
        model = MapModel.from_game(19)
        solid = set(model.terrain.solid)
        blocked = set(model.terrain.blocked)
        self.assertTrue(solid)
        self.assertLess(len(solid), len(blocked))
        # почти все глухие клетки заодно непроходимы — это стены построек
        self.assertGreater(len(solid & blocked) / len(solid), 0.9)


@needs_game
class TemporaryPotionContractTest(unittest.TestCase):
    """Временные зелья 89…92: сроки, пороги и что они правят."""

    def test_lock_and_saved_slots_match_the_unit_record(self) -> None:
        """Замок в +0x4A, спрятанные характеристики в +0xC6 (VA 0x41DC5D)."""
        from konung2.effects import TEMP_LOCK_AT, TEMP_SAVED_AT, TEMP_SAVED_SIZE
        from konung2.progress import BASE_AT, CHARACTERISTICS, LOCK_FIELD
        self.assertEqual(TEMP_LOCK_AT, LOCK_FIELD)
        # прячутся ровно шесть базовых характеристик, сразу за ними
        self.assertEqual(TEMP_SAVED_SIZE, len(CHARACTERISTICS))
        self.assertEqual(BASE_AT + TEMP_SAVED_SIZE, TEMP_SAVED_AT)

    def test_durations_and_threshold_are_the_engine_numbers(self) -> None:
        """Срок 0x1E за единицу, у Мудрости 0x3C, и порог шесть."""
        from konung2.effects import TEMP_TICKS, TEMP_TICKS_LONG, WISDOM_MIN
        with open(game_file("konung2.exe"), "rb") as stream:
            blob = stream.read()
        window = blob[va_to_foff(0x41DC14):va_to_foff(0x41DE60)]
        # imul eax, [ebp-8], 0x1e — срок обычного зелья
        self.assertIn(bytes([0x6B, 0x45, 0xF8, TEMP_TICKS]), window)
        # imul eax, [ebp-8], 0x3c — вдвое дольше у Эликсира Мудрости
        self.assertIn(bytes([0x6B, 0x45, 0xF8, TEMP_TICKS_LONG]), window)
        # cmp dword [ebp-8], 6 — слабее шести Мудрость не действует
        self.assertIn(bytes([0x83, 0x7D, 0xF8, WISDOM_MIN]), window)
        self.assertEqual(TEMP_TICKS_LONG, TEMP_TICKS * 2)

    def test_booze_drains_dexterity_not_intellect(self) -> None:
        """Брага бьёт по ЛОВКОСТИ (+0xC1), а не по уму (VA 0x41DCA1)."""
        from konung2.effects import (BOOZE_DIVISOR, POTION_BOOZE,
                                     TEMP_POTION_EFFECTS)
        from konung2.progress import BASE_AT, CHARACTERISTICS
        effect = TEMP_POTION_EFFECTS[POTION_BOOZE]
        drained = [index for index, value in effect.items() if value < 0]
        self.assertEqual(drained, [1])
        self.assertEqual(CHARACTERISTICS[1], "Ловкость")
        self.assertEqual(BASE_AT + 1, 0xC1)
        # вверх идут обаяние, сила и выносливость
        self.assertEqual(sorted(i for i, v in effect.items() if v > 0), [0, 4, 5])
        self.assertEqual(BOOZE_DIVISOR, 3)

    def test_wisdom_experience_is_sqrt_scaled_by_the_engine_double(self) -> None:
        """Опыт Эликсира: round(sqrt(k − 5) · 100), хвост ветки 0x41DEAE."""
        from konung2.effects import (WISDOM_XP_SCALE, WISDOM_XP_SCALE_VA,
                                     WISDOM_XP_SHIFT)
        with open(game_file("konung2.exe"), "rb") as stream:
            blob = stream.read()
        # множитель — восьмибайтовая константа по 0x450243
        self.assertEqual(
            struct.unpack_from("<d", blob, va_to_foff(WISDOM_XP_SCALE_VA))[0],
            WISDOM_XP_SCALE)
        window = blob[va_to_foff(0x41DEAE):va_to_foff(0x41DED9)]
        # sub eax, 5 — сдвиг крепости перед корнем
        self.assertIn(bytes([0x83, 0xE8, WISDOM_XP_SHIFT]), window)
        # call 0x442C6C (fsqrt-хелпер Watcom) и call 0x413110 (начисление)
        for target in (0x442C6C, 0x413110):
            called = any(window[i] == 0xE8 and
                         0x41DEAE + i + 5 +
                         struct.unpack_from("<i", window, i + 1)[0] == target
                         for i in range(len(window) - 4))
            self.assertTrue(called, hex(target))


@needs_game
class StrikeFrameContractTest(unittest.TestCase):
    """На каком кадре анимации приходит удар и срывается выстрел."""

    def test_melee_lands_on_the_second_to_last_frame(self) -> None:
        """Урон ближнего боя — на предпоследнем кадре (VA 0x413894)."""
        from konung2.combat import (AMMO_SHOT_FRAME_FROM_END,
                                    MELEE_HIT_FRAME_FROM_END)
        with open(game_file("konung2.exe"), "rb") as stream:
            blob = stream.read()
        window = blob[va_to_foff(0x413894):va_to_foff(0x413894) + 0x1120]
        # sub edx, N ; cmp eax, edx — сверка текущего кадра с «конец минус N»
        for value in (MELEE_HIT_FRAME_FROM_END, AMMO_SHOT_FRAME_FROM_END):
            with self.subTest(value):
                self.assertIn(bytes([0x83, 0xEA, value, 0x39, 0xD0]), window)
        # выстрел срывается раньше удара: лук виден натянутым дольше
        self.assertGreater(AMMO_SHOT_FRAME_FROM_END, MELEE_HIT_FRAME_FROM_END)


class EngineReferenceTest(unittest.TestCase):
    """Правило проекта: за каждым числом в порте стоит адрес движка.

    Проверяем обратное направление: каждый адрес, на который ссылается
    порт, действительно попадает внутрь разобранной функции. Ссылка «в
    никуда» значит, что комментарий отстал от кода или адрес выдуман.
    """

    #: Секция кода konung2.exe.
    CODE_LO, CODE_HI = 0x410000, 0x44B800
    #: Две функции, которых нет в выгрузке Ghidra: разобраны дизассемблером
    #: вручную (см. комментарии в knyaz2/web/static/dialog.js).
    #: Функции, до которых Ghidra не добралась: разбирались дизассемблером
    #: (tools/disasm.py), поэтому в index.json их нет, а ссылки честные.
    #: 0x435724 — обработчик разговора 60 «дать или забрать деньги»: он в
    #: семнадцать команд, и Ghidra его не выгрузила. Снят дизассемблером:
    #: `imul edx, [ebp+0x14], 0xa; add [eax+0x26], edx` при eax = игрок.
    #: Вторая волна (В5, 2026-08-08): опознание всей таблицы 0x462E90 —
    #: тридцать два обработчика без выгрузки Ghidra сняты капстоуном
    #: (scratchpad handlers_disasm.txt той сессии), имена и разборы в
    #: konung2/quests.py HANDLER_NAMES.
    KNOWN_MISSING = {
        0x4350C0, 0x435340, 0x435500, 0x43552B, 0x435724,
        0x432F1C, 0x4336F0, 0x433730, 0x433818, 0x433C30, 0x433E30,
        0x434334, 0x434364, 0x434444, 0x434478, 0x4345A4, 0x434630,
        0x43473C, 0x434850, 0x434A2C, 0x434AA4, 0x434D68, 0x434DB0,
        0x434EDC, 0x434F14, 0x435058, 0x4350E0, 0x4356B8, 0x435750,
        0x435844, 0x4358BC, 0x435A2C, 0x435AA0, 0x435B60, 0x435C18,
        0x435D4C, 0x435EA4,
        #: Оконная процедура 0x42F22C в выгрузку Ghidra не попала, поэтому
        #: её адреса сняты капстоуном прямо из konung2.exe:
        #:   0042F913  call 0x438a00  — обработчик WM_USER(0x400) зовёт
        #:   главный цикл, где увеличивается мировой такт _DAT_0084962c.
        #: Отправитель этого сообщения лежит уже внутри разобранной 0x42EBD0:
        #:   0042F1EF  cmp eax, 0x4E / jl  — такт не чаще чем раз в 78 мс,
        #:   0042F200  push 0x400 → SendMessageA.
        #: Скан всей секции кода: `call 0x438A00` встречается ровно один раз.
        0x42F913,
    }

    def test_every_engine_address_lands_in_a_known_function(self) -> None:
        import json
        import pathlib
        import re
        root = pathlib.Path(__file__).resolve().parent.parent
        index_path = root / "engine" / "decompiled" / "index.json"
        if not index_path.is_file():
            self.skipTest("декомпилят недоступен: нет engine/decompiled/index.json")
        index = json.loads(index_path.read_text(encoding="utf-8"))
        spans = sorted((int(f["entry"], 16), f["size"]) for f in index)
        starts = [start for start, _ in spans]

        def inside(va: int) -> bool:
            import bisect
            at = bisect.bisect_right(starts, va) - 1
            if at < 0:
                return False
            start, size = spans[at]
            return va < start + size

        sources = [*(root / "konung2").rglob("*.py"),
                   *(root / "knyaz2").rglob("*.py"),
                   *(root / "knyaz2" / "web" / "static").glob("*.js")]
        dangling: dict[int, str] = {}
        checked = 0
        for path in sources:
            text = path.read_text(encoding="utf-8", errors="replace")
            for match in re.finditer(r"0x(?:00)?(4[0-9A-Fa-f]{5})\b", text):
                va = int(match.group(1), 16)
                if not self.CODE_LO <= va < self.CODE_HI:
                    continue                      # это данные, а не код
                checked += 1
                if not inside(va) and va not in self.KNOWN_MISSING:
                    dangling.setdefault(va, str(path.relative_to(root)))
        self.assertGreater(checked, 500, "ссылок на движок подозрительно мало")
        self.assertEqual(dangling, {},
                         "адреса не попадают ни в одну разобранную функцию")


class ClientSyntaxTest(unittest.TestCase):
    """Клиентские модули должны разбираться как ES-модули.

    Это не придирка: `node --check` на файле с расширением .js разбирает
    его как CommonJS и молча пропускает ошибки, которые браузер считает
    синтаксическими. Так в порт однажды уехало `a ?? b || c` — смешение
    `??` и `||` без скобок, — и вся страница переставала грузиться, а
    консоль оставалась пустой, потому что падал сам разбор модуля.
    """

    def test_every_client_module_parses_as_a_module(self) -> None:
        import shutil
        import subprocess
        import tempfile
        from pathlib import Path
        node = shutil.which("node")
        if not node:
            self.skipTest("node недоступен")
        static = Path(__file__).resolve().parent.parent / "knyaz2" / "web" / "static"
        modules = sorted(static.glob("*.js"))
        self.assertGreater(len(modules), 20, "модули клиента не найдены")
        broken = {}
        with tempfile.TemporaryDirectory() as tmp:
            for path in modules:
                # расширение .mjs заставляет node разбирать файл как модуль
                copy = Path(tmp) / f"{path.stem}.mjs"
                copy.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
                done = subprocess.run([node, "--check", str(copy)],
                                      capture_output=True, text=True)
                if done.returncode:
                    broken[path.name] = done.stderr.strip().splitlines()[:3]
        self.assertEqual(broken, {}, "модули не разбираются как ES-модули")




@needs_game
class SelectionContractTest(unittest.TestCase):
    """Выделение отряда: круг под выбранным и правила списка."""

    def test_circle_sprites_are_health_graded_and_green_when_whole(self) -> None:
        """Три круга из INTERF.RES: красный, жёлтый и зелёный (VA 0x425DB4)."""
        from konung2.orders import (SELECTION_HEALTH_STEPS, SELECTION_PALETTE,
                                    SELECTION_SPRITES)
        from konung2.paths import game_file as file_of
        from konung2.res import decode_rle, read_palettes
        with open(file_of("INTERF.RES"), "rb") as stream:
            blob = stream.read()
        palettes = read_palettes()
        base = 4 + 8000                      # u32 размер + таблица 1000x8
        expected = {"hurt": (255, 49, 49), "half": (255, 230, 57),
                    "whole": (0, 255, 0)}
        for name, index in SELECTION_SPRITES.items():
            with self.subTest(name):
                offset, palette = struct.unpack_from("<2I", blob, 4 + index * 8)
                self.assertEqual(palette // 512, SELECTION_PALETTE)
                sprite = decode_rle(blob, base + offset,
                                    palette=palettes[SELECTION_PALETTE], mode=8)
                colours = {p[:3] for p in sprite.pixels if p is not None and p[3] > 0}
                # кольцо одноцветное — в этом весь смысл градации по здоровью
                self.assertEqual(colours, {expected[name]})
        # пороги здоровья: полное здоровье 1600, значит зелёный у здорового
        self.assertEqual(SELECTION_HEALTH_STEPS, (0x191, 0x321))

    def test_ring_sits_on_the_same_feet_anchor_as_the_body(self) -> None:
        """Кольцо лежит в холсте по якорю ног (127, 144) — как тело юнита."""
        from konung2.heroes import ANCHOR_X, ANCHOR_Y
        from konung2.orders import SELECTION_PALETTE, SELECTION_SPRITES
        from konung2.paths import game_file as file_of
        from konung2.res import decode_rle, read_palettes
        with open(file_of("INTERF.RES"), "rb") as stream:
            blob = stream.read()
        palettes = read_palettes()
        offset, _ = struct.unpack_from("<2I", blob, 4 + SELECTION_SPRITES["whole"] * 8)
        sprite = decode_rle(blob, 4 + 8000 + offset,
                            palette=palettes[SELECTION_PALETTE], mode=8)
        xs, ys = [], []
        for y in range(sprite.height):
            for x in range(sprite.width):
                pixel = sprite.pixels[y * sprite.width + x]
                if pixel is not None and pixel[3] > 0:
                    xs.append(x)
                    ys.append(y)
        centre = ((min(xs) + max(xs)) // 2, (min(ys) + max(ys)) // 2)
        # центр кольца совпадает с якорем ног с точностью до пикселя
        self.assertLessEqual(abs(centre[0] - ANCHOR_X), 1)
        self.assertLessEqual(abs(centre[1] - ANCHOR_Y), 1)
        # и это именно кольцо: плоское и широкое, а не заливка
        self.assertGreater(max(xs) - min(xs), 2 * (max(ys) - min(ys)))

    def test_orders_go_to_the_selection_list_only(self) -> None:
        """VA 0x4240BC перебирает только список выбора — героя там нет даром."""
        with open(game_file("konung2.exe"), "rb") as stream:
            blob = stream.read()
        window = blob[va_to_foff(0x4240BC):va_to_foff(0x4240BC) + 0x80]
        # список 0x840B94 адресуется прямо в цикле
        self.assertIn(struct.pack("<I", 0x840B94), window)
        # и каждому выбранному ставится бит «занят приказом»
        self.assertIn(bytes([0x80, 0x48, 0x19, 0x40]), window)


@needs_game
class ControlCanonTest(unittest.TestCase):
    """Требования из docs/CONTROL_CANON.md против байтов игры."""

    def test_camera_is_centred_only_on_load(self) -> None:
        """К1.2/К1.3: наведение центрирует и зовётся не из кадра (VA 0x4291B4)."""
        with open(game_file("konung2.exe"), "rb") as stream:
            blob = stream.read()
        window = blob[va_to_foff(0x4291B4):va_to_foff(0x4291B4) + 0x80]
        # sub eax, 0x200 и sub eax, 0x180 — половина экрана 1024x768
        self.assertIn(bytes([0x2D, 0x00, 0x02, 0x00, 0x00]), window)
        self.assertIn(bytes([0x2D, 0x80, 0x01, 0x00, 0x00]), window)
        # окно мира 884x708 — зажимы 0x374 и 0x2C4
        self.assertIn(struct.pack("<i", 0x374), window)
        self.assertIn(struct.pack("<i", 0x2C4), window)

    def test_edge_scroll_steps_differ_by_axis(self) -> None:
        """К1.4: курсор у края двигает камеру на 57 и 32 (VA 0x437CD0)."""
        with open(game_file("konung2.exe"), "rb") as stream:
            blob = stream.read()
        window = blob[va_to_foff(0x437CD0):va_to_foff(0x437CD0) + 0xE0]
        # 0x3FF и 0x2FF — правый и нижний край экрана 1024x768
        self.assertIn(struct.pack("<i", 0x3FF), window)
        self.assertIn(struct.pack("<i", 0x2FF), window)
        # Шаги разные по осям, и назад компилятор кодирует не вычитанием, а
        # сложением с отрицательным: add [ebp-8], ±57 и add [ebp-4], ±32.
        self.assertIn(bytes([0x83, 0x45, 0xF8, 0x39]), window)   # вправо +57
        self.assertIn(bytes([0x83, 0x45, 0xF8, 0xC7]), window)   # влево  −57
        self.assertIn(bytes([0x83, 0x45, 0xFC, 0x20]), window)   # вниз   +32
        self.assertIn(bytes([0x83, 0x45, 0xFC, 0xE0]), window)   # вверх  −32

    def test_formation_table_puts_mates_around_the_leader(self) -> None:
        """К5.3: таблица 0x461BC4 — 2 чётности x 8 направлений x 12 мест."""
        from konung2.orders import (FORMATION_DIRECTIONS, FORMATION_SLOTS,
                                    formation)
        table = formation()
        self.assertEqual(len(table), 2)
        for parity in table:
            self.assertEqual(len(parity), FORMATION_DIRECTIONS)
            for direction in parity:
                self.assertEqual(len(direction), FORMATION_SLOTS)
        # ни одно место не совпадает с клеткой вожака — иначе отряд толкался бы
        for parity in table:
            for direction in parity:
                self.assertNotIn((0, 0), direction)
        # места идут от вожака наружу: первое ближе последнего
        for parity in table:
            for direction in parity:
                near = abs(direction[0][0]) + abs(direction[0][1])
                far = abs(direction[-1][0]) + abs(direction[-1][1])
                self.assertLess(near, far)

    def test_follow_thresholds_are_the_engine_numbers(self) -> None:
        """К5.2/К5.4: догон с десяти клеток, бег дальше пятнадцати."""
        from konung2.orders import (FOLLOW_CELLS_OTHER, FOLLOW_CELLS_OWN,
                                    FOLLOW_RUN_CELLS)
        with open(game_file("konung2.exe"), "rb") as stream:
            blob = stream.read()
        window = blob[va_to_foff(0x41209C):va_to_foff(0x41209C) + 0x120]
        # mov [ebp-0x14], 10 и 5 — пороги догона для своего и чужого отряда
        self.assertIn(bytes([0xC7, 0x45, 0xEC, FOLLOW_CELLS_OWN, 0, 0, 0]), window)
        self.assertIn(bytes([0xC7, 0x45, 0xEC, FOLLOW_CELLS_OTHER, 0, 0, 0]), window)
        # cmp [ebp-0x18], 0xF — дальше пятнадцати спутник бежит
        self.assertIn(bytes([0x83, 0x7D, 0xE8, FOLLOW_RUN_CELLS]), window)


@needs_game
class SpawnZoneContractTest(unittest.TestCase):
    """Где юнит встаёт при входе на карту (VA 0x415764 и 0x43DF9C)."""

    def test_beasts_have_no_written_cells_but_a_zone(self) -> None:
        """У звериных отрядов координаты нулевые — место назначает зона."""
        from konung2.gamefile import map_units
        beasts = [unit for unit in map_units(34, 0)
                  if int(unit.get("breed", 0)) & 0x40]
        self.assertGreater(len(beasts), 10, "звери карты 34 не найдены")
        scattered = [unit for unit in beasts if not unit["spawn_zone"]["keep_cells"]]
        self.assertGreater(len(scattered), 10, "рассыпаемых зверей нет")
        for unit in scattered:
            with self.subTest(unit["name"]):
                # координат у них не записано — место назначает зона
                self.assertEqual((unit["row"], unit["col"]), (0, 0))
                # и зона настоящая: полоса, а не точка
                self.assertGreater(unit["spawn_zone"]["row_to"]
                                   - unit["spawn_zone"]["row_from"], 1)

    def test_village_residents_keep_their_written_cells(self) -> None:
        """У жителей бит 0x10 стоит — они встают ровно там, где записаны."""
        from konung2.gamefile import map_units
        residents = map_units(19, 0)
        self.assertEqual(len(residents), 9)
        for unit in residents:
            with self.subTest(unit["name"]):
                self.assertTrue(unit["spawn_zone"]["keep_cells"])
                self.assertNotEqual((unit["row"], unit["col"]), (0, 0))

    def test_scatter_stays_inside_the_zone(self) -> None:
        """Рассыпка не выходит за половину зоны от её центра."""
        from knyaz2.content.builder import _spawn_cell
        from konung2.gamefile import map_units
        from konung2.world.model import MapModel
        model = MapModel.from_game(34)
        for unit in map_units(34, 0):
            zone = unit["spawn_zone"]
            if zone["keep_cells"]:
                continue
            cell = _spawn_cell(model, unit)
            with self.subTest(unit["name"]):
                self.assertIsNotNone(cell, "не нашлось проходимой клетки")
                middle_row = (zone["row_to"] + zone["row_from"] + 1) // 2
                middle_col = (zone["col_to"] + zone["col_from"] + 1) // 2
                self.assertLessEqual(abs(cell.row - middle_row),
                                     (zone["row_to"] - zone["row_from"]) // 2)
                self.assertLessEqual(abs(cell.col - middle_col),
                                     (zone["col_to"] - zone["col_from"]) // 2)
                # и это не угол карты, куда они падали раньше
                self.assertNotEqual((cell.row, cell.col), (0, 0))

    def test_party_flag_byte_is_the_one_the_loader_reads(self) -> None:
        """Байт +0x1E: ноль — отряда нет, бит 0x10 — координаты в силе."""
        from konung2.gamefile import PARTY_FLAGS_AT, PARTY_KEEP_CELLS, T_PARTIES
        with open(game_file("GAME.0"), "rb") as stream:
            blob = stream.read()
        self.assertEqual((PARTY_FLAGS_AT, PARTY_KEEP_CELLS), (0x1E, 0x10))
        village = blob[T_PARTIES.offset + 55 * T_PARTIES.size:][:T_PARTIES.size]
        self.assertTrue(village[PARTY_FLAGS_AT] & PARTY_KEEP_CELLS)
        for party in (3, 4, 5):
            record = blob[T_PARTIES.offset + party * T_PARTIES.size:][:T_PARTIES.size]
            with self.subTest(party):
                self.assertTrue(record[PARTY_FLAGS_AT])          # отряд есть
                self.assertFalse(record[PARTY_FLAGS_AT] & PARTY_KEEP_CELLS)


class CharacterScreenContractTest(unittest.TestCase):
    """Экран персонажа: таблица чисел 0x4612E4 против байтов konung2.exe."""

    def test_number_table_holds_thirty_seven_pairs(self) -> None:
        """Пар (x, y) ровно 37: таблица упирается в таблицу подписей."""
        from konung2.interf import (CHARACTER_EXTRA_FIELDS, CHARACTER_FIELDS_VA,
                                    CHARACTER_LABELS_VA, character_screen)
        pairs = (CHARACTER_LABELS_VA - CHARACTER_FIELDS_VA) // 8
        self.assertEqual(pairs, 37)
        self.assertEqual((CHARACTER_LABELS_VA - CHARACTER_FIELDS_VA) % 8, 0)
        screen = character_screen()
        self.assertEqual(len(screen["numbers"]), pairs)
        # семь итоговых полей — хвост той же таблицы, столбец x=590
        tail = screen["numbers"][-len(CHARACTER_EXTRA_FIELDS):]
        self.assertEqual([entry["field"] for entry in tail],
                         list(CHARACTER_EXTRA_FIELDS))
        self.assertEqual([(entry["x"], entry["y"]) for entry in tail],
                         [(590, 480 + 20 * step) for step in range(7)])

    def test_weight_rows_use_the_engine_format_and_scale(self) -> None:
        """Обе весовые строки — «%4.1f» от граммов на double 0.001."""
        from konung2.interf import CHARACTER_WEIGHT_SCALE
        with open(game_file("konung2.exe"), "rb") as stream:
            blob = stream.read()
        # 0x42BB08/0x42BB3C зовут printf с форматами 0x4524C6 и 0x4524CC
        for va in (0x4524C6, 0x4524CC):
            self.assertEqual(blob[va_to_foff(va):va_to_foff(va) + 6],
                             b"%4.1f\0")
        scale = struct.unpack_from("<d", blob, va_to_foff(0x4524D2))[0]
        self.assertEqual(scale, CHARACTER_WEIGHT_SCALE)


class DeadlyStrikeContractTest(unittest.TestCase):
    """«Смертельный удар» и удар двумя руками — байты ближнего резолвера."""

    def test_deadly_strike_reads_skill_two_and_rolls_percent(self) -> None:
        """0x41C268: навык атакующего +0xD4, rand % 100 против навык / 10."""
        from konung2.combat import DEADLY_DIVISOR, DEADLY_SKILL
        from konung2.progress import SKILLS, SKILLS_AT
        self.assertEqual(SKILLS[DEADLY_SKILL], "Смертельный удар")
        self.assertEqual(SKILLS_AT + DEADLY_SKILL, 0xD4)
        with open(game_file("konung2.exe"), "rb") as stream:
            blob = stream.read()
        window = blob[va_to_foff(0x41C268):va_to_foff(0x41C2B8)]
        # mov al, [edx+0xD4] — навык «Смертельный удар» атакующего
        self.assertIn(bytes([0x8A, 0x82, 0xD4, 0x00, 0x00, 0x00]), window)
        # mov ebx, 0x64 — модуль броска (rand % 100)
        self.assertIn(bytes([0xBB, 0x64, 0x00, 0x00, 0x00]), window)
        # mov ecx, 0x0A — делитель навыка
        self.assertIn(bytes([0xB9, DEADLY_DIVISOR, 0x00, 0x00, 0x00]), window)
        # mov dword [ebp-0x20], 1 — код «жертва умерла», минуя урон
        self.assertIn(bytes([0xC7, 0x45, 0xE0, 0x01, 0x00, 0x00, 0x00]), window)

    def test_double_strike_frames_come_from_the_nibbles(self) -> None:
        """Блок 9 бьёт дважды: кадры правой и левой — полубайты 0x45FE98."""
        from konung2.combat import (DOUBLE_STRIKE_FRAMES_VA,
                                    DOUBLE_STRIKE_MAIN_FRAME,
                                    DOUBLE_STRIKE_OFF_FRAME)
        with open(game_file("konung2.exe"), "rb") as stream:
            blob = stream.read()
        packed = blob[va_to_foff(DOUBLE_STRIKE_FRAMES_VA)]
        self.assertEqual((packed & 0x70) >> 4, DOUBLE_STRIKE_MAIN_FRAME)
        self.assertEqual(packed & 0x0F, DOUBLE_STRIKE_OFF_FRAME)


class ParryDirectionsContractTest(unittest.TestCase):
    """Парирование ближнего удара: таблица направлений и обе константы."""

    def test_directions_form_a_facing_band(self) -> None:
        """0x459F94: в каждой строке ровно три единицы напротив лица."""
        from konung2.combat import parry_directions
        table = parry_directions()
        self.assertEqual(len(table), 8)
        for victim, row in enumerate(table):
            self.assertEqual(sum(row), 3, row)
            # полоса сдвигается вместе с направлением жертвы: парируются
            # удары от направлений «жертва + 3..5 по кругу»
            expected = {(victim + shift) % 8 for shift in (3, 4, 5)}
            self.assertEqual({col for col, hit in enumerate(row) if hit},
                             expected)
            # удар в спину (то же направление) не парируется никогда
            self.assertEqual(row[victim], 0)

    def test_scales_are_the_engine_doubles(self) -> None:
        """Ближний порог — 0.5 по 0x450160, стрелковый — 0.1 по 0x450138."""
        from konung2.combat import PARRY_MELEE_SCALE, PARRY_RANGED_SCALE
        with open(game_file("konung2.exe"), "rb") as stream:
            blob = stream.read()
        self.assertEqual(struct.unpack_from("<d", blob, va_to_foff(0x450160))[0],
                         PARRY_MELEE_SCALE)
        self.assertEqual(struct.unpack_from("<d", blob, va_to_foff(0x450138))[0],
                         PARRY_RANGED_SCALE)


class WanderingPartiesContractTest(unittest.TestCase):
    """Бродячие отряды: хвост GAME.x и роли-шаблоны 140…146."""

    def test_tail_records_hold_thresholds_and_homes(self) -> None:
        """Последние 0xA0 байт GAME.0 — записи с порогом и домашней клеткой."""
        from konung2.worldmap import COLS, ROWS, wandering
        records = wandering()
        self.assertEqual(len(records), 7)
        for record in records:
            # порог возрождения — почти вся тысяча долей: отряды редки
            self.assertIn(record["threshold"], (9996, 9997))
            self.assertLess(record["home_row"], ROWS)
            self.assertLess(record["home_col"], COLS)

    def test_roles_come_in_template_pairs(self) -> None:
        """Семь ролей 0x8C…0x92: по отряду-шаблону и слоту копии на каждую."""
        from konung2.gamefile import T_PARTIES
        from konung2.worldmap import (TEMPLATE_LAST, WANDER_ROLES,
                                      WANDER_ROLE_FIRST)
        self.assertEqual(WANDER_ROLE_FIRST + WANDER_ROLES - 1, TEMPLATE_LAST)
        with open(game_file("GAME.0"), "rb") as stream:
            blob = stream.read()
        for role in range(WANDER_ROLES):
            group = WANDER_ROLE_FIRST + role
            owners = []
            for party in range(T_PARTIES.count):
                record = blob[T_PARTIES.offset + party * T_PARTIES.size:][
                    :T_PARTIES.size]
                if struct.unpack_from("<H", record, 0x08)[0] == group:
                    owners.append(party)
            self.assertEqual(len(owners), 2, (group, owners))


class VillageEconomyContractTest(unittest.TestCase):
    """Казна владения, мастерская и точило — байты движка."""

    def test_treasury_formula_constants(self) -> None:
        """Период 0x2760, богатство ×50, доход капает в +0x10."""
        from konung2.buildings import (TREASURY_PERIOD, TREASURY_PER_PERSON,
                                       TREASURY_WEALTH_SCALE)
        with open(game_file("konung2.exe"), "rb") as stream:
            blob = stream.read()
        # 0x41D55C: cmp eax, 0x2760 — неделя игрового времени
        self.assertEqual(blob[va_to_foff(0x41D55C):va_to_foff(0x41D55C) + 5],
                         bytes([0x3D]) + struct.pack("<I", TREASURY_PERIOD))
        # 0x41D571: imul eax, eax, 0x32 — богатство на пятьдесят
        self.assertEqual(blob[va_to_foff(0x41D571):va_to_foff(0x41D571) + 3],
                         bytes([0x6B, 0xC0, TREASURY_WEALTH_SCALE]))
        # 0x41D5AA: imul eax, eax, 0x0A — жители на десять
        self.assertEqual(blob[va_to_foff(0x41D5AA):va_to_foff(0x41D5AA) + 3],
                         bytes([0x6B, 0xC0, TREASURY_PER_PERSON]))
        # 0x41D728: add [edx+0x10], eax — доход в казну владения
        self.assertEqual(blob[va_to_foff(0x41D728):va_to_foff(0x41D728) + 3],
                         bytes([0x01, 0x42, 0x10]))

    def test_workshop_calls_sqrt_and_scales_culture(self) -> None:
        """Мастерская: классы культуры ×34 + 100 и корень в обеих формулах."""
        from konung2.buildings import (WORKSHOP_CULTURE_BASE,
                                       WORKSHOP_CULTURE_STEP)
        with open(game_file("konung2.exe"), "rb") as stream:
            blob = stream.read()
        window = blob[va_to_foff(0x417BD8):va_to_foff(0x417BD8) + 0x600]
        # imul eax, eax, 0x22; add eax, 0x64 — класс = культура*34 + 100
        self.assertIn(bytes([0x6B, 0xC0, WORKSHOP_CULTURE_STEP,
                             0x83, 0xC0, WORKSHOP_CULTURE_BASE]), window)
        # fsqrt-хелпер 0x442C6C зовётся из функции (сроки и рост мастера)
        called = any(window[i] == 0xE8 and
                     0x417BD8 + i + 5 +
                     struct.unpack_from("<i", window, i + 1)[0] == 0x442C6C
                     for i in range(len(window) - 4))
        self.assertTrue(called)

    def test_whetstone_doubles_match_the_engine(self) -> None:
        """Точило: потолок навык × 2.0, деградация × 0.7 (0x459198/0x4591A0)."""
        from konung2.craft import (WHETSTONE_CEILING_PER_SKILL,
                                   WHETSTONE_DECAY)
        with open(game_file("konung2.exe"), "rb") as stream:
            blob = stream.read()
        self.assertEqual(struct.unpack_from("<d", blob, va_to_foff(0x459198))[0],
                         WHETSTONE_CEILING_PER_SKILL)
        self.assertEqual(struct.unpack_from("<d", blob, va_to_foff(0x4591A0))[0],
                         WHETSTONE_DECAY)


class PowderContractTest(unittest.TestCase):
    """Порошки: соответствие класс -> навык и строки движка (VA 0x436C48)."""

    def test_skill_powders_match_names_and_messages(self) -> None:
        """Каждый порошок растит СВОЙ навык, сообщение — строка exe."""
        from konung2.craft import (POWDER_SKILLS, POWDER_XP_SCALE,
                                   POWDER_XP_SKILL)
        from konung2.progress import SKILLS
        expected = {0x28: ("Кузнечное дело", 5), 0x2C: ("Торговля", 10),
                    0x2D: ("Знахарство", 10), 0x30: ("Строительные навыки", 10),
                    0x32: ("Идентификация предметов", 10)}
        for klass, (skill_name, gain) in expected.items():
            row = POWDER_SKILLS[klass]
            self.assertEqual(SKILLS[row["skill"]], skill_name)
            self.assertEqual(row["gain"], gain)
        self.assertEqual(SKILLS[POWDER_XP_SKILL], "Волхование")
        self.assertEqual(POWDER_XP_SCALE, 3)
        with open(game_file("konung2.exe"), "rb") as stream:
            blob = stream.read()
        for va, klass in ((0x4591F4, 0x28), (0x459216, 0x2C),
                          (0x459242, 0x2D), (0x45926F, 0x30),
                          (0x459299, 0x32)):
            offset = va_to_foff(va)
            text = blob[offset:blob.index(b"\x00", offset)].decode("cp866")
            self.assertEqual(text, POWDER_SKILLS[klass]["message"])

    def test_characteristic_powders_lift_base_for_good(self) -> None:
        """0x2A и 0x2F зовут FUN_00436BA8: базу и спрятанную копию, кламп 150."""
        from konung2.craft import POWDER_CHARACTERISTICS
        from konung2.progress import CHARACTERISTICS
        self.assertEqual(
            CHARACTERISTICS[POWDER_CHARACTERISTICS[0x2A]["characteristic"]],
            "Сила")
        self.assertEqual(POWDER_CHARACTERISTICS[0x2A]["gain"], 3)
        self.assertEqual(
            CHARACTERISTICS[POWDER_CHARACTERISTICS[0x2F]["characteristic"]],
            "Харизма")
        self.assertEqual(POWDER_CHARACTERISTICS[0x2F]["gain"], 10)
        with open(game_file("konung2.exe"), "rb") as stream:
            blob = stream.read()
        # тело 0x436BA8: оба клампа 0x96 (потолок 150) — cmp с 0x96
        window = blob[va_to_foff(0x436BA8):va_to_foff(0x436BA8) + 0x80]
        self.assertGreaterEqual(window.count(bytes([0x96])), 2)


class ClassKindsContractTest(unittest.TestCase):
    """Вид класса един по всем мирам, и прорехи мира 0 закрыты чужими."""

    def test_kinds_agree_across_worlds_and_cover_jewels(self) -> None:
        """Ни один класс не носит два вида; ожерелья 60…62 — вид 6.

        В мире 0 класс 60 лежит только в добыче сценария, вещи-инстанса
        у него нет — вид приезжает из миров 1…5 (везде байт +0 равен 6).

        Пустой записью считается ТОЛЬКО 0xFF — движок так и чистит гнездо
        (``(&DAT_006f956c)[iVar2] = -1``, VA 0x41C194). Вид 0 — это оружие,
        первый из носимых видов 0…4, и записи с ним настоящие: у них есть
        класс, крепость и максимум (напр. класс 208 — 95.0/95.0, отрава 10).
        Пока отсюда отбрасывался и ноль, порт не знал НИ ОДНОГО класса
        оружия, и всё, что гейтится видом 0 (точило VA 0x436C48 case '3',
        двуручность, выбор анимации удара), работало на пустом множестве.
        """
        import konung2.gamefile as gamefile
        merged: dict[int, int] = {}
        for world in range(gamefile.WORLD_COUNT):
            with open(game_file(f"GAME.{world}"), "rb") as stream:
                data = stream.read()
            table = gamefile.T_ITEMS
            for index in range(1, table.count):
                record = data[table.offset + index * table.size:][:table.size]
                if len(record) < 4 or record[0] == 0xFF:
                    continue
                seen = merged.setdefault(record[3], record[0])
                self.assertEqual(seen, record[0],
                                 f"класс {record[3]} в мире {world}")
        kinds = gamefile.class_kinds(0)
        self.assertEqual(kinds, merged)
        for klass, kind in ((60, 6), (61, 6), (62, 6), (63, 7), (64, 7),
                            (65, 7), (66, 8), (67, 8), (68, 8)):
            self.assertEqual(kinds.get(klass), kind, klass)
        weapons = sorted(klass for klass, kind in kinds.items() if kind == 0)
        self.assertGreater(len(weapons), 20,
                           "классы оружия (вид 0) снова потерялись")


class EatenFormulaeContractTest(unittest.TestCase):
    """В3: четыре FP-цепочки, съеденные Ghidra, закреплены байтами asm."""

    def setUp(self) -> None:
        with open(game_file("konung2.exe"), "rb") as stream:
            self.blob = stream.read()

    def test_balm_heal_chain(self) -> None:
        """Бальзам: цена (100−здоровье/16)·0.1 float'ом, итог ROUND, кламп.

        0x41DA0A: fild зд/16; fsubr 100.0 (0x4501EB); fmul 0.1 (0x4501F3);
        fstp DWORD (одинарная точность!); кап крепостью; fild здоровье;
        fmul 160.0 (0x4501FB); faddp; ROUND; кламп 0x640 ПОСЛЕ округления.
        """
        window = self.blob[va_to_foff(0x41DA0A):va_to_foff(0x41DA0A) + 0x60]
        self.assertIn(bytes.fromhex("dc2deb014500"), window)  # fsubr 100.0
        self.assertIn(bytes.fromhex("dc0df3014500"), window)  # fmul 0.1
        self.assertIn(bytes.fromhex("d95dec"), window)        # fstp dword!
        self.assertIn(bytes.fromhex("dc0dfb014500"), window)  # fmul 160.0
        # кламп 1600 ПОСЛЕ округления: cmp dword [ebp-8], 0x640
        self.assertIn(bytes.fromhex("817df840060000"), window)

    def test_treasury_income_chain(self) -> None:
        """Казна: round(богатство·50·√(навык 19 вожака) + жители·10 + 1).

        0x41D57A: fild богатство·50; байт вожака +0xE5 (навык 19
        «Управление деревней»); fsqrt-хелпер; fmulp; жители·10; faddp;
        fld1; faddp; ROUND.
        """
        window = self.blob[va_to_foff(0x41D571):va_to_foff(0x41D571) + 0x60]
        self.assertIn(bytes.fromhex("8a82e5000000"), window)  # навык +0xE5
        called = any(window[i] == 0xE8 and
                     0x41D571 + i + 5 +
                     struct.unpack_from("<i", window, i + 1)[0] == 0x442C6C
                     for i in range(len(window) - 4))
        self.assertTrue(called)                                # fsqrt
        self.assertIn(bytes.fromhex("d9e8dec1"), window)       # fld1; faddp

    def test_workshop_has_two_order_formulae(self) -> None:
        """Срок заказа: ПЕРВЫЙ — √(навык/10+1) ПОД корнем (0x417CF3), а
        ПЕРЕЗАКАЗ после выдачи — √(навык/10)+1 ПОСЛЕ корня (0x417F42,
        0x41802A), числитель — прочность класса (0x45DAF8 = база+8)·60.
        """
        first = self.blob[va_to_foff(0x417CF3):va_to_foff(0x417CF3) + 0x20]
        # idiv ebx; inc eax; …; fild; call fsqrt — единица до корня
        self.assertTrue(first.startswith(bytes.fromhex("f7fb40")))
        for site in (0x417F42, 0x41802A):
            tail = self.blob[va_to_foff(site):va_to_foff(site) + 0x10]
            # fild; call fsqrt; fld1; faddp; fdivp — единица после корня
            self.assertEqual(tail[:3], bytes.fromhex("db45a4"), hex(site))
            self.assertIn(bytes.fromhex("d9e8dec1def9"), tail, hex(site))
        # числитель перезаказа: imul eax, [eax+0x45DAF8], 0x3C
        window = self.blob[va_to_foff(0x417F14):va_to_foff(0x417F14) + 0x20]
        self.assertIn(bytes.fromhex("6b80f8da45003c"), window)

    def test_parry_rolls_read_current_dexterity(self) -> None:
        """Парирование: ближнее round(тек.Ловкость·0.5) против rand%101
        ВКЛЮЧИТЕЛЬНО (0x41C1F7), стрелковое Ловкость·0.1 БЕЗ округления,
        сравнение во float (0x41BFB7). Источник — байт +0xCD (текущий блок).
        """
        melee = self.blob[va_to_foff(0x41C1F2):va_to_foff(0x41C1F2) + 0x40]
        self.assertIn(bytes.fromhex("8a82cd000000"), melee)   # тек. Ловкость
        self.assertIn(bytes.fromhex("dc0d60014500"), melee)   # fmul 0.5
        self.assertIn(bytes.fromhex("bb65000000"), melee)     # % 101
        ranged = self.blob[va_to_foff(0x41BFB2):va_to_foff(0x41BFB2) + 0x40]
        self.assertIn(bytes.fromhex("8a82cd000000"), ranged)
        self.assertIn(bytes.fromhex("dc0d38014500"), ranged)  # fmul 0.1
        self.assertIn(bytes.fromhex("dd5dd8"), ranged)        # fstp qword


class SlayersAndMightContractTest(unittest.TestCase):
    """В8: сила удара 0x41A7D0 — член Силы·здоровья и спящие убийцы пород."""

    def setUp(self) -> None:
        with open(game_file("konung2.exe"), "rb") as stream:
            self.blob = stream.read()

    def test_strength_term_doubles(self) -> None:
        """Оружие 0.04/0.0625, кулак 0.02/0.0625, зверь 0.04/0.0625."""
        from konung2.combat import (STRENGTH_TERM_FIST,
                                    STRENGTH_TERM_HEALTH,
                                    STRENGTH_TERM_WEAPON)
        pairs = ((0x450054, 0.04), (0x45005C, 0.0625),   # зверь
                 (0x450064, STRENGTH_TERM_WEAPON),
                 (0x45006C, STRENGTH_TERM_HEALTH),
                 (0x450074, STRENGTH_TERM_FIST),
                 (0x45007C, STRENGTH_TERM_HEALTH))
        for va, expected in pairs:
            self.assertEqual(
                struct.unpack_from("<d", self.blob, va_to_foff(va))[0],
                expected, hex(va))
        window = self.blob[va_to_foff(0x41A7D0):va_to_foff(0x41A7D0) + 0x200]
        for pattern in ("dc0d64004500", "dc0d6c004500", "dc0d74004500"):
            self.assertIn(bytes.fromhex(pattern), window)

    def test_slayer_table_is_dormant(self) -> None:
        """Таблица 0x4624F8: семь убийц пород; индекс +2 записи никем не
        ставится — аллокатор 0x43B6D8 кладёт туда минус единицу.
        """
        from konung2.combat import SLAYER_TABLE
        for index, (power, breed) in enumerate(SLAYER_TABLE):
            at = va_to_foff(0x4624F8 + index * 0x20)
            self.assertEqual(struct.unpack_from("<i", self.blob, at)[0],
                             power, index)
            self.assertEqual(struct.unpack_from("<i", self.blob, at + 4)[0],
                             breed, index)
        # ветка выбора особой силы в 0x41A7D0
        window = self.blob[va_to_foff(0x41A7D0):va_to_foff(0x41A7D0) + 0x200]
        self.assertIn(bytes.fromhex("0fbe4002"), window)      # movsx +2
        self.assertIn(bytes.fromhex("3b82fc244600"), window)  # порода?
        self.assertIn(bytes.fromhex("8b80f8244600"), window)  # особая сила
        # аллокатор записей: mov byte [eax+2], 0xFF
        boot = self.blob[va_to_foff(0x43B6D8):va_to_foff(0x43B6D8) + 0x60]
        self.assertIn(bytes.fromhex("c64002ff"), boot)

    def test_wandering_movement_bytes(self) -> None:
        """В9: шаг бродячих — rand % 60 и запрет клеток с битом 0x10."""
        from konung2.worldmap import WANDER_BLOCK_FLAG, WANDER_MOVE_DIE
        window = self.blob[va_to_foff(0x41C944):va_to_foff(0x41C944) + 0x800]
        self.assertIn(bytes([0xBB, WANDER_MOVE_DIE, 0, 0, 0]), window)
        # test byte [eax+0x460177], 0x10 — флаги клетки глобальной карты
        self.assertIn(bytes.fromhex("f68077014600") +
                      bytes([WANDER_BLOCK_FLAG]), window)


class CorpseLootContractTest(unittest.TestCase):
    """Обыск убитого БЕСПЛАТЕН: гейт цен — «партнёр жив»."""

    def test_price_gate_is_the_corpse_check(self) -> None:
        """0x41A6CC, 0x41AF3C и 0x41F638 стерегут одно и то же: порода без
        бита 0x80 и поза не 3/0xB/0xC. У трупа наценок нет, и проверка
        «Слишком мало даешь!» (0x4502E7) не выполняется вовсе.
        """
        with open(game_file("konung2.exe"), "rb") as stream:
            blob = stream.read()
        gate = bytes.fromhex("f6401a80")     # test byte [eax+0x1A], 0x80
        for va, span in ((0x41A6CC, 0x60), (0x41AF3C, 0x60),
                         (0x41F638, 0x900)):
            window = blob[va_to_foff(va):va_to_foff(va) + span]
            self.assertIn(gate, window, hex(va))
        # позы смерти в гейте: cmp eax, 3 / 0xB / 0xC подряд
        window = blob[va_to_foff(0x41A6CC):va_to_foff(0x41A6CC) + 0x60]
        for code in (0x03, 0x0B, 0x0C):
            self.assertIn(bytes([0x83, 0xF8, code]), window)
        # сообщение «Слишком мало даешь!» лежит по своему адресу
        at = va_to_foff(0x4502E7)
        self.assertEqual(blob[at:at + 7].decode("cp866")[:7], "Слишком")


class TearLookContractTest(unittest.TestCase):
    """В1: байт +0xF8 — бонус точности Чистой слезы, а не «облик»."""

    def setUp(self) -> None:
        with open(game_file("konung2.exe"), "rb") as stream:
            self.blob = stream.read()

    def test_tear_writes_accuracy_bonus_not_shape(self) -> None:
        """Слеза: +0xF8 = round(sqrt(k)·0.1), флаг свечения 0x849610.

        Ветка 0x41DD86…0x41DDF7: mov [0x849610],1; таймер k·30; fild k;
        fsqrt-хелпер 0x442C6C; fmul double 0.1 (0x45023B); ROUND;
        mov [edx+0xF8], al. Записи тела (+0xFC) в ветке НЕТ.
        """
        window = self.blob[va_to_foff(0x41DD86):va_to_foff(0x41DD86) + 0x72]
        # mov dword [0x849610], 1 — флаг свечения
        self.assertIn(bytes.fromhex("c7051096840001000000"), window)
        # fmul qword [0x45023B] — множитель 0.1
        self.assertIn(bytes.fromhex("dc0d3b024500"), window)
        import struct
        self.assertEqual(
            struct.unpack_from("<d", self.blob, va_to_foff(0x45023B))[0], 0.1)
        # mov [edx+0xF8], al — бонус ложится в +0xF8
        self.assertIn(bytes.fromhex("8882f8000000"), window)
        # тела (+0xFC) ветка не трогает
        self.assertNotIn(bytes.fromhex("fc000000"), window)

    def test_accuracy_reads_the_bonus_while_potion_ticks(self) -> None:
        """0x41ADD8 прибавляет ЗНАКОВЫЙ байт +0xF8, пока тикает +0x4A.

        0x41AED1: mov eax,[eax+0xF5]; sar eax,0x18; add [ebp-8],eax —
        подписанное расширение старшего байта dword с +0xF5 и есть +0xF8.
        """
        window = self.blob[va_to_foff(0x41ADD8):va_to_foff(0x41ADD8) + 0x180]
        self.assertIn(bytes.fromhex("8b80f5000000c1f8180145f8"), window)

    def test_torch_sets_the_same_glow_flag(self) -> None:
        """Факел (класс 46, ветка 0x2E в 0x436C48) зажигает тот же флаг.

        Запись mov [0x849610],1 встречается в exe ровно дважды: Слеза
        (0x41DD86) и Факел (0x4374C2, внутри разбора применения 0x436C48);
        загрузчик карты 0x43DF48 кладёт туда ноль.
        """
        flag_store = bytes.fromhex("c7051096840001000000")
        hits = []
        start = 0
        while True:
            at = self.blob.find(flag_store, start)
            if at < 0:
                break
            hits.append(at)
            start = at + 1
        from konung2.exetables import foff_to_va
        self.assertEqual(sorted(foff_to_va(at) for at in hits),
                         [0x41DD86, 0x4374C2])

    def test_wine_is_a_strengthless_booze(self) -> None:
        """Вино (класс 30): сила = Ловкость/3, но не больше пяти.

        0x436F92: mov dl,[edx+0xC1]; and edx,0xFF; mov ebx,3; idiv;
        cmp [ebp-4],5 — дальше ветка кладёт нули в +0xF8 и правит те же
        четыре характеристики, что Брага.
        """
        window = self.blob[va_to_foff(0x436F92):va_to_foff(0x436F92) + 0x20]
        self.assertTrue(window.startswith(bytes.fromhex(
            "8a92c100000081e2ff000000bb03000000")))
        self.assertIn(bytes.fromhex("837dfc05"), window)


class ShapeActionContractTest(unittest.TestCase):
    """В1: облик — это ТЕЛО (+0xFC), и меняет его действие разговора 59."""

    def setUp(self) -> None:
        with open(game_file("konung2.exe"), "rb") as stream:
            self.blob = stream.read()

    def test_action_59_rewrites_body_palette_and_breed(self) -> None:
        """0x43487C: тело = арг%10, палитра +0x2E = арг/10·512, порода 0.

        Целевой юнит — указатель 0x849524 (по умолчанию собеседник).
        """
        from konung2.quests import handler_table
        self.assertEqual(handler_table()[59]["address"], 0x43487C)
        window = self.blob[va_to_foff(0x43487C):va_to_foff(0x43487C) + 0x50]
        self.assertIn(bytes.fromhex("a124958400"), window)      # юнит 0x849524
        self.assertIn(bytes.fromhex("8890fc000000"), window)    # тело +0xFC
        self.assertIn(bytes.fromhex("c1e009"), window)          # частное << 9
        self.assertIn(bytes.fromhex("89422e"), window)          # палитра +0x2E
        self.assertIn(bytes.fromhex("c6401a00"), window)        # порода в ноль

    def test_condition_13_reads_the_leader_body(self) -> None:
        """Условие 13 (0x434EA0) сравнивает тело ВОЖАКА с аргументом."""
        from konung2.quests import handler_table
        self.assertEqual(handler_table()[13]["address"], 0x434EA0)


class BeastBitContractTest(unittest.TestCase):
    """В2: бит 0x40 породы (+0x1A) — «зверь»: другой конвейер целиком."""

    def test_beast_gate_opens_the_accuracy_function(self) -> None:
        """0x41ADD8 первым делом ветвится по биту: у зверя точность
        считается из ТЕКУЩЕЙ Ловкости (+0xCD) как 100−(100−Л·0.5)·0.5.
        """
        with open(game_file("konung2.exe"), "rb") as stream:
            blob = stream.read()
        window = blob[va_to_foff(0x41ADD8):va_to_foff(0x41ADD8) + 0x60]
        self.assertIn(bytes.fromhex("f6401a40"), window)   # test +0x1A, 0x40
        self.assertIn(bytes.fromhex("8a82cd000000"), window)  # Ловкость +0xCD
        import struct
        self.assertEqual(
            struct.unpack_from("<d", blob, va_to_foff(0x450084))[0], 0.5)
        self.assertEqual(
            struct.unpack_from("<d", blob, va_to_foff(0x45008C))[0], 100.0)

    def test_start_worlds_split_bodies_by_the_bit(self) -> None:
        """Данные GAME.0: без бита — только людские тела (0…9), с битом —
        и звериные (больше девяти); тварей сотни.
        """
        from konung2.gamefile import game_file as world_file
        with open(world_file("GAME.0"), "rb") as stream:
            data = stream.read()
        units_off, unit_size, unit_count = 0x46322, 256, 2000
        beast_bodies, human_bodies = set(), set()
        beasts = 0
        for index in range(unit_count):
            record = data[units_off + index * unit_size:][:unit_size]
            if len(record) < 256 or not any(record[:32]):
                continue
            if record[0x1A] & 0x40:
                beast_bodies.add(record[0xFC])
                beasts += 1
            else:
                human_bodies.add(record[0xFC])
        self.assertTrue(all(body <= 9 for body in human_bodies), human_bodies)
        self.assertTrue(any(body > 9 for body in beast_bodies))
        self.assertGreater(beasts, 500)


class PartyCapacityContractTest(unittest.TestCase):
    """Вместимость отряда: обработчик 7 (VA 0x434CD0) считает её из Харизмы."""

    def test_capacity_reads_current_charisma(self) -> None:
        """Байт вожака +0xCC — ТЕКУЩАЯ Харизма, не базовая (+0xC0).

        Тело 0x434CD0: mov edx,[0x84951C]; mov dl,[edx+0xCC]; …
        sar eax,4; inc eax; cmp eax,9 — то есть (Харизма >> 4) + 1,
        не больше девяти.
        """
        with open(game_file("konung2.exe"), "rb") as stream:
            blob = stream.read()
        window = blob[va_to_foff(0x434CD0):va_to_foff(0x434CD0) + 0x60]
        # mov dl, byte [edx+0xCC] — чтение текущей Харизмы вожака
        self.assertIn(bytes.fromhex("8a 92 cc 00 00 00"), window)
        # sar eax,4; inc eax; cmp eax,9 — формула и потолок
        self.assertIn(bytes.fromhex("c1 f8 04 40 83 f8 09"), window)
        # указатель вожака 0x84951C
        self.assertIn(bytes.fromhex("8b 15 1c 95 84 00"), window)


@unittest.skipUnless(GAME_AVAILABLE, "нет установленной игры")
class WorldTickContractTest(unittest.TestCase):
    """Мировой такт: 78 мс, один счётчик, один источник.

    Это фундамент всей периодики (счётчик работы жителя `& 0xF`, фаза
    построек `+7 & 0xF`, отрава, время суток), поэтому константа проверяется
    по машинному коду, а не по комментарию. Прежнее значение 1/18 держалось
    на догадке «~18 тиков/с» и гнало игру на 40% быстрее оригинала.
    """

    #: Период такта в миллисекундах: `cmp eax, 0x4E` + `jl` пропускает такт,
    #: пока с прошлого не прошло 78 мс.
    TICK_MS = 78

    def test_gate_in_the_message_pump_is_78_ms(self) -> None:
        with open(game_file("konung2.exe"), "rb") as stream:
            blob = stream.read()
        # 0x42F1E7: mov eax,[0x849728]; sub eax,[ebp-4]; cmp eax,0x4E; jl …
        window = blob[va_to_foff(0x42F1E7):va_to_foff(0x42F1E7) + 13]
        self.assertEqual(window[:5], bytes.fromhex("a1 28 97 84 00"))
        self.assertEqual(window[5:8], bytes.fromhex("2b 45 fc"))
        self.assertEqual(window[8:10], bytes.fromhex("83 f8"))
        self.assertEqual(window[10], self.TICK_MS)
        self.assertEqual(window[11], 0x7C)          # jl — меньше, значит мимо

    def test_the_gate_sends_wm_user_and_that_calls_the_master_loop(self) -> None:
        with open(game_file("konung2.exe"), "rb") as stream:
            blob = stream.read()
        # 0x42F200: push 0x400 → SendMessageA главному окну
        at = va_to_foff(0x42F200)
        self.assertEqual(blob[at:at + 5], bytes.fromhex("68 00 04 00 00"))
        # 0x42F913: call rel32 — обработчик WM_USER зовёт главный цикл
        at = va_to_foff(0x42F913)
        self.assertEqual(blob[at], 0xE8)
        rel = struct.unpack_from("<i", blob, at + 1)[0]
        self.assertEqual(0x42F913 + 5 + rel, 0x438A00)

    def test_master_loop_has_exactly_one_caller(self) -> None:
        """Иначе частота такта не выводится из одного гейта."""
        with open(game_file("konung2.exe"), "rb") as stream:
            blob = stream.read()
        lo, hi = 0x410000, 0x44B800          # секция BEGTEXT
        base = va_to_foff(lo)
        code = blob[base:base + (hi - lo)]
        callers = []
        for at in range(len(code) - 5):
            if code[at] != 0xE8:
                continue
            rel = struct.unpack_from("<i", code, at + 1)[0]
            if lo + at + 5 + rel == 0x438A00:
                callers.append(lo + at)
        self.assertEqual(callers, [0x42F913])

    def test_the_pack_ships_the_canonical_tick(self) -> None:
        from knyaz2.content.builder import _hero_rules
        rules = _hero_rules()
        self.assertEqual(rules["tick_ms"], self.TICK_MS)
        self.assertAlmostEqual(rules["frame_seconds"], self.TICK_MS / 1000, 4)
        # сутки движка — 21600 тактов (пороги 0x45FC3C заданы в них же)
        self.assertAlmostEqual(21600 * rules["frame_seconds"], 1684.8, 1)


@unittest.skipUnless(GAME_AVAILABLE, "нет установленной игры")
class RangedAndShieldContractTest(unittest.TestCase):
    """Стрельба юнита и броня щита — по байтам exe.

    Обе величины лежали в порте неверно: стрелки-NPC не стреляли вовсе
    (гейт позы), а второе гнездо давало броню без проверки вида, из-за чего
    одноручное оружие в левой руке считалось щитом.
    """

    def test_shot_frame_is_six_from_the_end_and_spends_an_arrow(self) -> None:
        from konung2.combat import AMMO_SHOT_FRAME_FROM_END
        with open(game_file("konung2.exe"), "rb") as stream:
            blob = stream.read()
        # 0x4148CA: mov edx,[eax+0xFB]; sar edx,0x18   — всего кадров блока
        #           mov al,[unit+0x1C]; and eax,0xFF    — текущий кадр
        #           sub edx,6; cmp eax,edx              — «всего − 6»
        at = va_to_foff(0x4148CA)
        window = blob[at:at + 25]
        self.assertEqual(window[:9],
                         bytes.fromhex("8b 90 fb 00 00 00 c1 fa 18"))
        self.assertEqual(window[9:20],
                         bytes.fromhex("8b 45 d4 8a 40 1c 25 ff 00 00 00"))
        self.assertEqual(window[20:22], bytes.fromhex("83 ea"))
        self.assertEqual(window[22], AMMO_SHOT_FRAME_FROM_END)
        self.assertEqual(window[23:25], bytes.fromhex("39 d0"))
        # следом идёт запуск снаряда 0x41BB10
        at = va_to_foff(0x4148E9)
        self.assertEqual(blob[at], 0xE8)
        rel = struct.unpack_from("<i", blob, at + 1)[0]
        self.assertEqual(0x4148E9 + 5 + rel, 0x41BB10)

    def test_only_a_real_shield_adds_armour(self) -> None:
        from konung2.combat import SHIELD_KIND
        with open(game_file("konung2.exe"), "rb") as stream:
            blob = stream.read()
        # 0x41A4B6: sar eax,0x18; cmp eax,4 — вид записи второго гнезда
        at = va_to_foff(0x41A4B6)
        self.assertEqual(blob[at:at + 3], bytes.fromhex("c1 f8 18"))
        self.assertEqual(blob[at + 3:at + 5], bytes.fromhex("83 f8"))
        self.assertEqual(blob[at + 5], SHIELD_KIND)
        # У одежды и доспеха такой проверки нет: их ветки идут выше и
        # прибавляют силу сразу после sar eax,0x10.
        for va in (0x41A440, 0x41A46F):
            self.assertEqual(blob[va_to_foff(va):va_to_foff(va) + 3],
                             bytes.fromhex("c1 f8 10"))

    def test_village_side_is_byte_two_and_matches_its_people(self) -> None:
        """Тревогу поднимает ОДИН отряд — сторона деревни из байта +0x02."""
        from konung2 import gamefile
        settlement = gamefile.village(19)
        self.assertIsNotNone(settlement)
        sides = {unit["side"] for unit in gamefile.map_units(19)
                 if unit.get("side") is not None}
        self.assertIn(settlement["side"], sides)


@unittest.skipUnless(GAME_AVAILABLE, "нет установленной игры")
class EquipmentWearContractTest(unittest.TestCase):
    """Износ снаряжения при попадании — множители из самого exe."""

    def test_wear_scales_are_the_doubles_in_the_exe(self) -> None:
        from konung2.combat import ARMOUR_WEAR_SCALE, WEAPON_WEAR_SCALE
        with open(game_file("konung2.exe"), "rb") as stream:
            blob = stream.read()
        # 0x450180 и 0x450158 — доля брони, 0x450188 — доля оружия
        for va, expected in ((0x450180, ARMOUR_WEAR_SCALE),
                             (0x450158, ARMOUR_WEAR_SCALE),
                             (0x450188, WEAPON_WEAR_SCALE)):
            value = struct.unpack_from("<d", blob, va_to_foff(va))[0]
            self.assertEqual(value, expected, hex(va))

    def test_worn_slots_are_the_same_three_that_give_armour(self) -> None:
        """Цикл износа читает те же гнёзда, что и подсчёт брони.

        `for (local_1c = 2; local_1c < 5; ...)` берёт u16 по
        +0x5C, +0x5E и +0x60 — одежда, доспех и щит.
        """
        from konung2.combat import WEAR_SLOTS
        self.assertEqual(len(WEAR_SLOTS), 3)
        with open(game_file("konung2.exe"), "rb") as stream:
            blob = stream.read()
        # 0x41C1F1: cmp dword [ebp-0x1c], 5 — верхняя граница цикла гнёзд
        window = blob[va_to_foff(0x41C194):va_to_foff(0x41C194) + 0x400]
        self.assertIn(bytes.fromhex("c1 f8 10"), window)   # >> 0x10 у гнезда


class SaveCoverageContractTest(unittest.TestCase):
    """Сейв обязан нести то же, что движок пишет в KONUNG2.SA<N>.

    Движок сохраняет блоки целиком: запись юнита 0x7B3C08 (0x7D000 байт),
    поселения 0x83D408 (0x378C), предметы 0x6F956C (0x20000), отряды
    0x71E56C (0xC800) — VA 0x423CB8. Порт пишет выборочно, поэтому здесь
    проверяется, что ни одно поле не потерялось по дороге: упакованное
    обязано и восстанавливаться, а канонический минимум — присутствовать.
    """

    def _save_source(self) -> str:
        import pathlib
        root = pathlib.Path(__file__).resolve().parent.parent
        return (root / "knyaz2" / "web" / "static" / "save.js").read_text(
            encoding="utf-8")

    def _pack_actor_fields(self, text: str) -> set[str]:
        import re
        body = text.split("function packActor(actor)", 1)[1]
        body = body.split("\nfunction ", 1)[0]
        return set(re.findall(r"^\s{4}(\w+):", body, re.M))

    def test_actor_keeps_the_fields_the_unit_record_holds(self) -> None:
        text = self._save_source()
        packed = self._pack_actor_fields(text)
        # три блока характеристик (+0xC0, +0xC6, +0xCC), счётчик зелья
        # (+0x4A), облик (+0xF8), отрава (+0x52) и квестовые флаги (+0xF9)
        for field in ("characteristics", "baseCharacteristics",
                      "savedCharacteristics", "potionTicks", "progressLock",
                      "look", "poison", "flags", "skills"):
            self.assertIn(field, packed, f"packActor не пакует {field}")

    def test_everything_packed_is_also_restored(self) -> None:
        text = self._save_source()
        packed = self._pack_actor_fields(text)
        apply_body = text.split("function applyActor(actor, saved)", 1)[1]
        apply_body = apply_body.split("\nexport function ", 1)[0]
        # эти поля восстанавливать нечего: они либо адресуют юнита, либо
        # заново выводятся при входе на карту
        skip = {"id", "name", "slot", "breed", "body", "palette", "ally"}
        missing = sorted(field for field in packed - skip
                         if f"saved.{field}" not in apply_body)
        self.assertEqual(missing, [], "упаковано, но не восстанавливается")

    def test_world_blocks_are_saved_and_restored(self) -> None:
        text = self._save_source()
        state = text.split("export function saveState", 1)[1].split(
            "\nexport function ", 1)[0]
        apply_body = text.split("export function applySave", 1)[1]
        for field in ("village", "buildings", "wandering", "loot"):
            self.assertRegex(state, rf"\n\s*{field}:",
                             f"saveState не пишет {field}")
            self.assertIn(f"saved.{field}", apply_body,
                          f"applySave не читает {field}")


class CreationScreenContractTest(unittest.TestCase):
    """Откат прибавок принадлежит экрану СОЗДАНИЯ, а не игровой панели.

    В движке это разные функции: экран создания рисует 0x430DF4 (там «+» по
    x = 0x3B6 и «−» по x = 0x3CA), счётчики прибавок 0x8442D8[6] и
    0x8442E0[20] ведутся только там, а обнуляет их выбор архетипа
    (0x4387CC). Игровой экран персонажа — рендер 0x42A8F4, он печатает
    ТОЛЬКО «+», и обработчик щелчков 0x421690 знает лишь ветки поднятия.
    """

    def _static(self, name: str) -> str:
        import pathlib
        root = pathlib.Path(__file__).resolve().parent.parent
        return (root / "knyaz2" / "web" / "static" / name).read_text(
            encoding="utf-8")

    def test_game_panel_has_no_lower_buttons(self) -> None:
        source = self._static("ui.js")
        for name in ("lowerCharacteristic(", "lowerSkill("):
            self.assertNotIn(name, source,
                             f"на игровой панели снова появился откат: {name}")

    def test_counters_grow_only_on_the_creation_screen(self) -> None:
        source = self._static("progress.js")
        for name in ("raiseCharacteristic", "raiseSkill"):
            head = source.split(f"export function {name}(", 1)[1]
            body = head.split("\nexport ", 1)[0]
            self.assertIn("creation", body.split("{", 1)[0] + body[:400],
                          f"{name} должен принимать признак экрана создания")
        # сами счётчики поднимаются только под этим признаком
        for counter in ("raisedCharacteristics[index] += 1",
                        "raisedSkills[index] += 1"):
            at = source.index(counter)
            self.assertIn("if (creation)", source[max(0, at - 260):at],
                          f"счётчик {counter} растёт вне экрана создания")

    def test_cascade_refund_is_ported(self) -> None:
        """Понижение характеристики возвращает переросшие навыки (0x437C48)."""
        source = self._static("progress.js")
        self.assertIn("export function trimOvergrownSkills", source)
        self.assertIn("trimOvergrownSkills(unit)", source)
        body = source.split("export function trimOvergrownSkills", 1)[1]
        body = body.split("\nexport ", 1)[0]
        # шаг назад, проверка «снова можно», откат последнего шага
        self.assertIn("canRaiseSkill(index, unit)", body)
        self.assertIn("break", body)
        self.assertIn("export function creationReset", source)


class EscapeContractTest(unittest.TestCase):
    """ESC разбирается по состоянию экрана (VA 0x438A00, ветка кода 0x1B).

    В игре: сперва отменяется перенос вещи (`FUN_0042944c(1)`), затем
    закрывается открытый экран, и только когда не открыто ничего — переход
    в меню (состояние 7). В меню: возврат в игру (case 1).
    """

    def _static(self, name: str) -> str:
        import pathlib
        root = pathlib.Path(__file__).resolve().parent.parent
        return (root / "knyaz2" / "web" / "static" / name).read_text(
            encoding="utf-8")

    def test_escape_closes_screens_before_leaving_the_game(self) -> None:
        ui = self._static("ui.js")
        self.assertIn("export function uiEscape", ui)
        body = ui.split("export function uiEscape", 1)[1].split("\n}", 1)[0]
        # порядок канона: перенос вещи, экран персонажа, глобальная карта
        self.assertLess(body.index("carrying()"), body.index("windowNode"))
        self.assertLess(body.index("windowNode"), body.index("mapOpen"))
        app = self._static("app.js")
        esc = app.split('event.code !== "Escape"', 1)[1].split("});", 1)[0]
        self.assertIn("uiEscape()", esc, "ESC уводит в меню, не закрыв экраны")
        self.assertLess(esc.index("uiEscape()"), esc.index("menu.html"))

    def test_menu_escape_returns_to_the_game(self) -> None:
        menu = self._static("menu.js")
        # Веток две: первая закрывает открытый экран, вторая — из главного
        # меню — возвращает в игру. Проверяем именно вторую.
        parts = menu.split("if (event.key === 'Escape') {")
        self.assertGreaterEqual(len(parts), 3, "нет ветки ESC главного меню")
        self.assertIn("/index.html", parts[2][:600])


class MenuScreenVisibilityTest(unittest.TestCase):
    """Экраны меню обязаны прятаться атрибутом hidden.

    Своё правило `display` перебивает `display: none` браузерной таблицы
    стилей, и тогда все экраны рисуются друг поверх друга — заголовок
    одного с содержимым другого. Ловим это статически: любое правило,
    задающее display экрану, должно сопровождаться правилом для [hidden].
    """

    def test_hidden_screens_are_not_displayed(self) -> None:
        import pathlib
        import re
        root = pathlib.Path(__file__).resolve().parent.parent
        css = (root / "knyaz2" / "web" / "static" / "menu.css").read_text(
            encoding="utf-8")
        self.assertRegex(css, r"\.screen\[hidden\][^{]*\{[^}]*display:\s*none",
                         "нет правила, прячущего экраны меню")
        self.assertRegex(css, r"\.menu\[hidden\][^{]*\{[^}]*display:\s*none",
                         "нет правила, прячущего список пунктов")
        # и сам класс действительно задаёт display — иначе правило не нужно
        self.assertRegex(css, r"\.screen\s*\{[^}]*display:\s*flex")


@unittest.skipUnless(GAME_AVAILABLE, "нет установленной игры")
class NewHeroResContractTest(unittest.TestCase):
    """NEWHERO.RES: формат экрана создания героя.

        блок:  u32 размер = 4 + 2*h + сумма длин строк
               u16 w, u16 h
               u16 длины_строк[h]
               RLE: 0 — конец строки; &0x80 — пропуск (n & 0x7F);
                    иначе серия n пикселей, следом 2*n байт X1R5G5B5

    Пиксели ШЕСТНАДЦАТИБИТНЫЕ — палитры в файле нет.
    """

    def test_file_parses_to_the_last_byte(self) -> None:
        from konung2.paths import game_file as source
        from konung2.res import newhero_blocks
        with open(source("NEWHERO.RES"), "rb") as stream:
            data = stream.read()
        blocks = newhero_blocks(data)
        self.assertEqual(len(blocks), 11)
        last = blocks[-1]
        end = last[3] + sum(last[4])
        self.assertEqual(end, len(data), "файл разобран не до конца")
        sizes = [(block[1], block[2]) for block in blocks]
        self.assertEqual(sizes[0], (1024, 768), "первый блок — фон экрана")
        self.assertEqual(sizes[1:7], [(76, 87)] * 6, "шесть портретов героев")

    def test_every_row_decodes_to_the_declared_width(self) -> None:
        """Это и есть доказательство, что пиксели по два байта."""
        from konung2.paths import game_file as source
        from konung2.res import newhero_blocks
        with open(source("NEWHERO.RES"), "rb") as stream:
            data = stream.read()
        for at, width, height, start, rows in newhero_blocks(data):
            pos = start
            for y in range(height):
                end = pos + rows[y]
                x = 0
                while pos < end:
                    control = data[pos]
                    pos += 1
                    if control == 0:
                        break
                    if control & 0x80:
                        x += control & 0x7F
                        continue
                    pos += control * 2
                    x += control
                self.assertEqual(x, width, f"блок {at}, строка {y}")
                pos = end

    def test_background_is_a_picture_not_noise(self) -> None:
        from konung2.res import newhero_sprite
        width, height, pixels = newhero_sprite(0)
        opaque = sum(1 for pixel in pixels if pixel[3])
        self.assertEqual(opaque, width * height, "фон должен быть непрозрачен")
        close = total = 0
        for y in range(0, height, 4):
            for x in range(width - 1):
                left, right = pixels[y * width + x], pixels[y * width + x + 1]
                total += 1
                if sum(abs(a - b) for a, b in zip(left[:3], right[:3])) < 30:
                    close += 1
        self.assertGreater(close / total, 0.6, "фон похож на шум, а не на кадр")


@unittest.skipUnless(GAME_AVAILABLE, "нет установленной игры")
class CreationLayoutContractTest(unittest.TestCase):
    """Разметка экрана создания: таблица 0x461D44 и точки кнопок."""

    def test_ninety_one_rectangles_and_the_two_buttons(self) -> None:
        from knyaz2.content.builder import (CREATION_CODES, _export_creation)
        import tempfile
        import pathlib
        layout = _export_creation(pathlib.Path(tempfile.mkdtemp()))
        self.assertEqual(len(layout["rects"]), 91)
        play = layout["rects"][CREATION_CODES["play"]]
        cancel = layout["rects"][CREATION_CODES["cancel"]]
        # прямоугольник кнопки начинается ровно в точке, куда движок ставит её спрайт
        self.assertEqual(play[:2], layout["play_at"])
        self.assertEqual(cancel[:2], layout["cancel_at"])
        self.assertEqual(play, [100, 699, 243, 717])
        self.assertEqual(cancel, [380, 699, 520, 717])
        # Шесть портретов стоят двумя рядами по три: три колонки x и два
        # ряда y. Ширина 79 или 80 — в самих данных так, ровнять нельзя.
        faces = [layout["rects"][i] for i in range(6)]
        self.assertEqual(sorted({rect[0] for rect in faces}), [104, 266, 429])
        self.assertEqual(sorted({rect[1] for rect in faces}), [109, 244])
        self.assertEqual({rect[2] - rect[0] for rect in faces}, {79, 80})
        self.assertEqual({rect[3] - rect[1] for rect in faces}, {91})
        # картинка 76x87 меньше своего места 80x91 — ставится в левый верх
        self.assertEqual(len(layout["portraits"]), 6)
        self.assertEqual({(shot["width"], shot["height"])
                          for shot in layout["portraits"]}, {(76, 87)})


class QuestStateContractTest(unittest.TestCase):
    """Начальное состояние квестов и сюжетная встреча.

    Порт не читал хвост QUESTS.RES вовсе, и из-за этого терялись ДВЕ вещи
    сразу: журнал заданий (был заглушкой «Записей пока нет») и авто-подход —
    механизм, которым в оригинале начинаются сюжетные встречи.

    Проверяется здесь и то, что БИТ 0x80 НЕ ВЗВЕДЁН НИ У ОДНОГО квеста:
    пустой журнал в начале игры — канон, а не потеря данных. Это прямо
    опровергает ходившую до того догадку, будто выбранному герою не хватает
    заранее отмеченного стартового квеста.
    """

    #: Диалоги, у которых бит 0x01 «подойди и заговори» взведён в файле.
    #: По картам это Мунд и Повелитель (карта 1), Верховный Палач (6),
    #: Воин Повелителя (15), Хакон Всеслав и Константин (20).
    APPROACH = {8, 16, 26, 36, 50, 60}
    #: Окно подхода: не дальше шести клеток по строке (+0x12) и трёх по
    #: столбцу (+0x14) — VA 0x410711 и 0x410736.
    APPROACH_ROWS, APPROACH_COLS = 6, 3
    #: Карты, на которых движок авто-подход не запускает (VA 0x4106B3/0x4106BE).
    SKIP_MAPS = (0x1A, 0x1B)

    def _state(self) -> tuple[int, ...]:
        from konung2.quests import STATE_OFF, STATE_SIZE
        with open(game_file("QUESTS.RES"), "rb") as stream:
            blob = stream.read()
        block = blob[STATE_OFF:STATE_OFF + STATE_SIZE]
        self.assertEqual(len(block), STATE_SIZE)
        return struct.unpack(f"<{STATE_SIZE // 4}I", block)

    def test_no_quest_starts_marked_and_six_units_start_armed(self) -> None:
        words = self._state()
        self.assertEqual(len(words), 300)
        self.assertEqual([i for i, w in enumerate(words) if w & 0x80], [],
                         "бит 0x80 в файле не взведён ни у одного квеста — "
                         "игра начинается с пустым журналом")
        self.assertEqual({i for i, w in enumerate(words) if w & 1}, self.APPROACH)

    def test_actions_62_and_61_arm_and_disarm_the_same_bit(self) -> None:
        """62 ставит бит 1, 61 его гасит — обе по номеру диалога цели.

        Функции 61 в декомпиляте нет, поэтому обе снимаются с байтов exe.
        """
        with open(game_file("konung2.exe"), "rb") as stream:
            blob = stream.read()
        table = va_to_foff(0x462E90)
        arm = struct.unpack_from("<I", blob, table + 62 * 4)[0]
        disarm = struct.unpack_from("<I", blob, table + 61 * 4)[0]
        self.assertEqual((disarm, arm), (0x435750, 0x4357B4))
        # or byte ptr [eax + 0x6a50e8], 1   /   and byte ptr [...], 0xfe
        self.assertIn(bytes.fromhex("80 88 e8 50 6a 00 01"),
                      blob[va_to_foff(arm):va_to_foff(arm) + 100])
        self.assertIn(bytes.fromhex("80 a0 e8 50 6a 00 fe"),
                      blob[va_to_foff(disarm):va_to_foff(disarm) + 100])

    def test_the_approach_window_and_the_order_it_gives(self) -> None:
        with open(game_file("konung2.exe"), "rb") as stream:
            blob = stream.read()
        def at(va: int, size: int) -> bytes:
            return blob[va_to_foff(va):va_to_foff(va) + size]
        # cmp dword ptr [0x8496c8], 0x1a / 0x1b — текущая карта
        self.assertEqual(at(0x4106B3, 11),
                         bytes.fromhex("83 3d c8 96 84 00 1a") + at(0x4106BA, 4))
        self.assertEqual(at(0x4106BE, 7), bytes.fromhex("83 3d c8 96 84 00 1b"))
        self.assertEqual(at(0x410711, 3),
                         bytes.fromhex("83 f8") + bytes([self.APPROACH_ROWS]))
        self.assertEqual(at(0x410736, 3),
                         bytes.fromhex("83 f8") + bytes([self.APPROACH_COLS]))
        # mov byte ptr [eax + 0x16], 0x22 — игроку целый байт приказа
        self.assertEqual(at(0x410742, 4), bytes.fromhex("c6 40 16 22"))

    def test_builder_exports_the_block_with_journal_texts(self) -> None:
        from knyaz2.content.builder import _quest_state
        state = _quest_state()
        self.assertEqual(len(state["flags"]), 300)
        self.assertEqual(len(state["journal"]), 300)
        self.assertEqual({i for i, f in enumerate(state["flags"]) if f & 1},
                         self.APPROACH)
        self.assertEqual([i for i, f in enumerate(state["flags"]) if f & 0x80], [])
        # Тексты журнала берутся из той же таблицы фраз, что и реплики;
        # строки «MAP=» отсеиваются, поэтому записей на одну меньше.
        self.assertEqual(len(state["text"]), 272)
        self.assertTrue(state["text"]["0"].startswith("МИССИЯ ТИТАНОВ"))
        self.assertTrue(all(not text.startswith("MAP=")
                            for text in state["text"].values()))


class HealthCeilingContractTest(unittest.TestCase):
    """Потолок здоровья один на всех, а стартовое здоровье — нет.

    Порт ставил `maxHealth = стартовое здоровье`, и на Ратиборе это сходилось
    случайно: у него ровно 1600. На остальных мирах правило разваливается —
    ЭЙНАР В GAME.2 НАЧИНАЕТ РАНЕНЫМ И БЕЗ ВЕЩЕЙ, а порт показывал его целым.
    """

    #: 0x640 = 1600. Движок обрезает им пересчёт здоровья (VA 0x41C494) и
    #: этим же числом лечит досыта (VA 0x4347D8).
    CEILING = 0x640

    def test_engine_clamps_health_at_0x640(self) -> None:
        """Пересчёт здоровья: сравнить с 0x640 и записать его же в +0x4E.

        Декомпилятор показывает условие как `< 0x641`, но в коде стоит
        `cmp …, 0x640` — проверяем по настоящим байтам, а не по чтению
        декомпилята.
        """
        with open(game_file("konung2.exe"), "rb") as stream:
            blob = stream.read()
        def at(va: int, size: int) -> bytes:
            return blob[va_to_foff(va):va_to_foff(va) + size]
        # cmp dword ptr [ebp - 8], 0x640
        self.assertEqual(at(0x41C7FD, 7), bytes.fromhex("81 7d f8 40 06 00 00"))
        # mov word ptr [eax + 0x4e], 0x640 — здоровье юнита +0x4E
        self.assertEqual(at(0x41C809, 6), bytes.fromhex("66 c7 40 4e 40 06"))
        self.assertEqual(
            struct.unpack_from("<H", at(0x41C809, 6), 4)[0], self.CEILING)

    def test_the_pack_already_carries_the_ceiling(self) -> None:
        from konung2.effects import HEALTH_MAX, rules as effect_rules
        self.assertEqual(HEALTH_MAX, self.CEILING)
        self.assertEqual(effect_rules()["health"]["max"], self.CEILING)

    def test_only_einar_starts_wounded_and_empty_handed(self) -> None:
        """Стартовое состояние шести героев — из GAME.<мир>, не из GAME.0."""
        from konung2.gamefile import party, unit_stats
        здоровье, снаряжение = {}, {}
        for world in range(6):
            first = party(0, world)["first"]
            with open(game_file(f"GAME.{world}"), "rb") as stream:
                stats = unit_stats(stream.read(), first)
            здоровье[world] = stats["health"]
            снаряжение[world] = sum(1 for value in stats["equipment"].values()
                                    if value)
        self.assertEqual(здоровье[2], 640, "Эйнар начинает раненым")
        self.assertEqual(снаряжение[2], 0, "у Эйнара пустые слоты")
        for world in (0, 1, 3, 4, 5):
            self.assertEqual(здоровье[world], self.CEILING)
            self.assertGreater(снаряжение[world], 0)


class FixedLightingContractTest(unittest.TestCase):
    """Карты без суточного цикла — таблица 0x4617B0.

    Порт крутил сутки везде, и во Дворце Повелителя днём было светло, хотя в
    оригинале там круглосуточный полумрак. Из таблицы до пака доезжал только
    СТАРШИЙ БАЙТ (`fixed_light_map`), а уровни подставлялись глобальной
    константой −70/−50/−50 — одной на все карты.
    """

    #: Семь карт с записью: 1 и 2 — вечная ночь, 45..49 — свет подземелий.
    EXPECTED = {1: 0x01CECEBA, 2: 0x01CECEBA,
                45: 0x00FFFFFF, 46: 0x00FFFFFF, 47: 0x00FFFFFF,
                48: 0x00FFFFFF, 49: 0x00FFFFFF}

    def test_the_table_has_exactly_these_seven_entries(self) -> None:
        from konung2.graph import FIXED_LIGHT_VA
        with open(game_file("konung2.exe"), "rb") as stream:
            blob = stream.read()
        offset = va_to_foff(FIXED_LIGHT_VA)
        table = {number: struct.unpack_from("<I", blob, offset + number * 4)[0]
                 for number in range(53)}
        self.assertEqual({n: v for n, v in table.items() if v}, self.EXPECTED)

    def test_the_cycle_is_skipped_on_the_whole_dword_not_the_top_byte(self) -> None:
        """`if ([0x8495A4] == 0)` — сравнивается ВЕСЬ dword (VA 0x4295D8).

        Отсюда и правка: у карт 45..49 старший байт нулевой, но суток там
        всё равно нет. Загрузчик карты кладёт запись целиком (VA 0x43DF48).
        """
        from konung2.graph import fixed_light, fixed_light_map
        for number, value in self.EXPECTED.items():
            with self.subTest(map=number):
                self.assertTrue(fixed_light(number)["frozen"])
                self.assertEqual(fixed_light(number)["value"], value)
                # старший байт — это ФЛАГ НОЧИ, а не признак «суток нет»
                self.assertEqual(fixed_light_map(number), number in (1, 2))
        for number in (19, 33, 52):
            with self.subTest(map=number):
                self.assertFalse(fixed_light(number)["frozen"])

    def test_levels_are_signed_bytes(self) -> None:
        from konung2.graph import (NIGHT_LEVEL_BLUE, NIGHT_LEVEL_GREEN,
                                   NIGHT_LEVEL_RED, fixed_light)
        # 0xBA -> −70, 0xCE -> −50: у карт 1 и 2 это совпадает с глобальной
        # константой самой тёмной точки кривой — потому ошибка и не бросалась
        # в глаза именно во дворце.
        self.assertEqual(fixed_light(1)["levels"],
                         {"blue": NIGHT_LEVEL_BLUE, "green": NIGHT_LEVEL_GREEN,
                          "red": NIGHT_LEVEL_RED})
        # а вот пещерам доставались чужие уровни: у них 0xFF -> −1
        self.assertEqual(fixed_light(45)["levels"],
                         {"blue": -1, "green": -1, "red": -1})


class BodyPaletteContractTest(unittest.TestCase):
    """Форма тела и палитра НЕЗАВИСИМЫ — как у брони Повелителя, но на теле.

    Движок ставит палитру юнита и уже ею рисует слой тела (VA 0x425DB4):
    сначала `[0x8A7318] = юнит+0x2E`, потом слой `0x30 + (юнит+0xFC)`.
    Порт же пёк формы ОДНОЙ палитрой, а палитры — только для базового тела,
    и выбирал одно из двух; из шести стартовых героев форму имеют пятеро, и
    все пятеро выходили в базовой раскраске.
    """

    #: Облик шести стартовых героев: (форма, палитра).
    LOOKS = {0: (0, 70), 1: (1, 70), 2: (2, 28),
             3: (3, 31), 4: (4, 34), 5: (5, 34)}

    def test_six_heroes_have_five_distinct_shapes_and_four_palettes(self) -> None:
        from konung2.gamefile import hero_stats
        actual = {world: (int(hero_stats(world)["body"]),
                          int(hero_stats(world)["palette"]))
                  for world in range(6)}
        self.assertEqual(actual, self.LOOKS)
        # именно поэтому «одна палитра на форму» и не работает: у форм 1..5
        # палитры разные, а базовой раскраской они все выглядят одинаково
        self.assertEqual(len({palette for _, palette in self.LOOKS.values()}), 4)

    def test_companions_carry_their_own_palette(self) -> None:
        """У спутников палитра тоже своя — раньше разбор её не доставал."""
        from konung2.gamefile import party
        members = party(0, 0).get("members", [])
        self.assertTrue(members)
        for member in members:
            with self.subTest(name=member.get("name")):
                self.assertIsNotNone(member.get("palette"))
        self.assertEqual({int(m["palette"]) for m in members}, {70, 71, 73})

    def test_the_engine_sets_the_palette_before_drawing_the_body(self) -> None:
        """Порядок в 0x425DB4: палитра из +0x2E, потом слой тела."""
        import pathlib
        source = pathlib.Path(__file__).resolve().parents[1] / "engine"
        text = (source / "decompiled" / "functions" /
                "0x00425db4.c").read_text(encoding="utf-8")
        palette_at = text.index("_DAT_008a7318 = *(undefined4 *)(param_2 + 0x2e)")
        body_at = text.index("FUN_00426698(param_2,local_18)")
        self.assertLess(palette_at, body_at,
                        "палитра ставится ДО отрисовки тела")


class LayerCacheContractTest(unittest.TestCase):
    """Кадр слоя зависит ОТ ПАЛИТРЫ, и кеш обязан это учитывать.

    Ловушка, которая молча обнулила всю правку по палитрам снаряжения: кеш
    выпечки в `_export_hero` ключевался парой «запись + слой», без палитры.
    Первая испечённая палитра слоя доставалась всем остальным, и в паке
    ключи 23, 23:3 и 23:9 указывали на ОДИН участок листа — чёрная броня
    воина Повелителя рисовалась палитрой обычной кожанки.

    Тест смотрит не на пак (его надо пересобирать), а на исходные данные:
    один и тот же слой в разных палитрах даёт РАЗНЫЕ пиксели.
    """

    RECORD, LAYER = 1139, 23
    #: 3 — кожаный доспех, 9 — доспех воина Повелителя (чёрный).
    PALETTES = (2, 3, 9)

    def test_the_same_layer_differs_between_palettes(self) -> None:
        from konung2.heroes import HeroesRes
        from konung2.res import read_palettes
        palettes = read_palettes()
        heroes = HeroesRes.from_game()
        seen = {}
        for index in self.PALETTES:
            sprite, _, _ = heroes.decode_layer(
                self.RECORD, layer=self.LAYER, palette=palettes[index])
            self.assertIsNotNone(sprite, f"палитра {index}: слой не декодировался")
            seen[index] = repr(sprite.pixels)
        self.assertEqual(len(set(seen.values())), len(self.PALETTES),
                         "разные палитры дали одинаковые пиксели — "
                         "значит палитра не применяется")

    def test_the_black_armour_palette_is_actually_grey(self) -> None:
        """Палитра 9 — чёрно-серая, у неё нет насыщенных цветов в начале."""
        from konung2.res import read_palettes
        palettes = read_palettes()
        for red, green, blue in palettes[9][1:8]:
            with self.subTest(colour=(red, green, blue)):
                self.assertEqual(red, green)
                self.assertEqual(green, blue)

    def test_the_builder_cache_key_carries_the_palette(self) -> None:
        import pathlib
        source = (pathlib.Path(__file__).resolve().parents[1] /
                  "knyaz2" / "content" / "builder.py").read_text(encoding="utf-8")
        self.assertIn("key = (record, layer, palette_index)", source)
        self.assertNotIn("key = (record, layer)\n", source)


class HeroLifecycleContractTest(unittest.TestCase):
    """Герой появляется вместе со своим миром, и второго героя не бывает.

    «Играть» (VA 0x438A00, состояние 8) снимает копию записи героя в 0x844A4C
    и зовёт 0x43D898. Тот открывает `GAME.<байт +0xFC копии>` и перечитывает
    мир ЦЕЛИКОМ — в том числе массив юнитов 0x7B3C08 на 0x7D000 байт. Юнит №0
    этого массива и есть герой: облик, снаряжение и отряд пришли из файла.
    Обратно из копии движок берёт только правки экрана создания.

    Порт же держал испечённый шаблон мира 0 как героя «по умолчанию»,
    собирал его, показывал и лишь потом правил облик — отсюда «два
    экземпляра героя» и мужской болванчик за Анастасию.
    """

    #: Что движок возвращает из копии: (смещение в записи, сколько байт).
    RESTORED = ((0xC0, 6), (0xCC, 6), (0xD2, 0x14))
    #: Стартовая карта каждого мира — из записи его отряда, не из манифеста.
    START_MAPS = {0: 33, 1: 19, 2: 23, 3: 37, 4: 45, 5: 1}

    def test_the_world_loader_rereads_the_whole_unit_array(self) -> None:
        import pathlib
        source = (pathlib.Path(__file__).resolve().parents[1] / "engine" /
                  "decompiled" / "functions" / "0x0043d898.c")
        text = source.read_text(encoding="utf-8")
        # массив юнитов и поселения читаются целиком из GAME.<N>
        self.assertIn("&DAT_007b3c08,0x7d000", text.replace(" ", ""))
        self.assertIn("&DAT_0083d408,0x378c", text.replace(" ", ""))
        # имя файла собирается из байта архетипа: 0x844B45 >> 0x18 = снимок+0xFC
        self.assertIn("_DAT_00844b45>>0x18", text.replace(" ", ""))

    def test_only_the_creation_edits_survive_the_world_load(self) -> None:
        """Из копии возвращаются ровно три блока — и облика среди них нет."""
        import pathlib
        source = (pathlib.Path(__file__).resolve().parents[1] / "engine" /
                  "decompiled" / "functions" / "0x00438a00.c")
        text = source.read_text(encoding="utf-8").replace(" ", "")
        for offset, size in self.RESTORED:
            with self.subTest(offset=hex(offset)):
                self.assertIn(f"0x844b{0x0C + offset - 0xC0:02x}", text.lower())
        # тело (+0xFC), палитра (+0x2E) и лицо (+0xEF) из копии НЕ пишутся
        self.assertNotIn("0x844b48,", text)

    def test_every_world_names_its_own_start_map(self) -> None:
        from knyaz2.content.builder import _hero_choices
        actual = {int(choice["world"]): int(choice["map"])
                  for choice in _hero_choices()}
        self.assertEqual(actual, self.START_MAPS)

    def test_the_client_has_no_default_hero_and_no_invented_world_key(self) -> None:
        import pathlib
        client = pathlib.Path(__file__).resolve().parents[1] / "knyaz2" / "web" / "static"
        boot = (client / "app.js").read_text(encoding="utf-8")
        # выдуманный ключ архетипа убран: он живёт в записи героя, то есть в сейве
        self.assertNotIn('localStorage.setItem("knyaz2.world"', boot)
        self.assertNotIn('localStorage.getItem("knyaz2.world")', boot)
        # карта берётся у выбранного старта, а не только из манифеста
        self.assertIn("mapPaths.get(Number(start?.map))", boot)
        # сейв несёт номер мира — как байт +0xFC несёт его в записи героя
        save = (client / "save.js").read_text(encoding="utf-8")
        self.assertIn("world: hero.data?.template?.world", save)


class PovelitelAudienceContractTest(unittest.TestCase):
    """Защита от боя с боссом у Повелителя — из данных диалога 36.

    Корневая развилка смотрит ОБЛИК ИГРОКА (обработчик 13, байт +0xFC):

        -> 2135  если НЕ (облик == 5)          не Анастасия — сразу бой
        -> 2152  если облик == 5 И флаг0       Анастасия, но уже приходила
        -> 2125  иначе                         мирная аудиенция

    Мирная ветка кончается ответом «Слава Повелителю!», и он поднимает флаг 0,
    затемняет экран, ПЕРЕНОСИТ отряд переходом 18 и просветляет. То есть
    защита держится на переносе: героиню физически уводят от трона, и второй
    разговор — уже с поднятым флагом — случиться не может.

    Порт ронял этот перенос: переход 18 ведёт с карты 1 на карту 1, а он шёл
    через выход в дверь с гейтом «уже на этой карте».
    """

    DIALOG, ROOT = 36, 2122
    #: Облик Анастасии: тело 5.
    ANASTASIA_BODY = 5
    #: Номер записи графа переходов, которым Повелитель отсылает от трона.
    EXIT_TRANSITION = 18

    def _tree(self):
        from konung2.quests import Dialogs
        return Dialogs.from_game().tree(self.DIALOG, limit=400)

    def test_the_root_branch_checks_the_players_body(self) -> None:
        tree = self._tree()
        root = next(node for node in tree["nodes"] if node["node"] == self.ROOT)
        self.assertEqual(root["kind"], "branch")
        branches = root["branches"]
        self.assertEqual(len(branches), 3)
        # первая: НЕ Анастасия -> враждебная ветка
        first = branches[0]["condition"][0]
        self.assertEqual((first["kind"], first["handler"], first["argument"]),
                         ("handler", 13, self.ANASTASIA_BODY))
        self.assertTrue(first["set"], "у первой ветки условие ОТРИЦАЕТСЯ")
        # вторая: Анастасия И флаг 0 собеседника
        kinds = [command["kind"] for command in branches[1]["condition"]]
        self.assertEqual(kinds, ["handler", "unit_flag"])
        # третья: без условия — мирная аудиенция
        self.assertTrue(branches[2]["always"])

    def test_the_peaceful_answer_flags_and_teleports(self) -> None:
        tree = self._tree()
        actions = None
        for node in tree["nodes"]:
            for option in node.get("options", []):
                names = [(c.get("kind"), c.get("handler"), c.get("argument"))
                         for c in option.get("actions") or []]
                if ("handler", 69, self.EXIT_TRANSITION) in names:
                    actions = names
        self.assertIsNotNone(actions, "перенос из мирной ветки пропал")
        self.assertIn(("unit_flag", None, None),
                      [(k, None, None) for k, _, _ in actions])
        # затемнить (52), перенести (69), просветлить (66) — именно в таком порядке
        порядок = [h for k, h, _ in actions if k == "handler"]
        self.assertEqual(порядок, [52, 69, 66])

    def test_that_transition_stays_on_the_palace_map(self) -> None:
        from konung2.gamefile import all_exits
        door = all_exits(0)[self.EXIT_TRANSITION]
        self.assertEqual(door["to_map"], 1, "переход ведёт на ту же карту")
        self.assertEqual((door["entry_row"], door["entry_col"]), (29, 21))
