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
        self.assertIn("uiEscape()", esc, "ESC открывает меню, не закрыв экраны")
        # Меню теперь НАКЛАДКА, а не переход на страницу: уход означал бы
        # полную перезагрузку пака и карты (gamemenu.js). Проверяем порядок:
        # сперва закрываются экраны, и только потом поднимается меню.
        self.assertIn("gameMenuToggle()", esc, "ESC не поднимает меню")
        self.assertLess(esc.index("uiEscape()"), esc.index("gameMenuToggle()"))
        self.assertNotIn("menu.html", esc,
                         "ESC уводит страницу — это стоит перезагрузки всего")

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


class CarryTargetsContractTest(unittest.TestCase):
    """Куда движок пускает вещь из руки — по разборщику щелчков 0x421690.

    Первый бета-тестер (отчёт Александра С., 09.08.2026) поймал сразу две
    ошибки переноса: применить вещь было нечем вовсе, а два одинаковых корня,
    положенные друг на друга в мешке, сваривались в смесь. Оба места в
    оригинале устроены иначе, и проверяется здесь именно это.
    """

    def client(self, name: str) -> str:
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        return (root / "knyaz2" / "web" / "static" / name).read_text(encoding="utf-8")

    def test_the_bag_only_inserts_and_never_brews(self) -> None:
        """Бросок в ячейку мешка — код 0x40 -> 0x423218: вставка со сдвигом.

        FUN_00423218 делает ровно три вещи: гонит квестовую вещь чужому
        спутнику, проверяет вес и зовёт FUN_00423538. Занятость ячейки его не
        интересует — вставка двигает остальные вправо. Ни варки, ни стопок.
        """
        carry = self.client("carry.js")
        начало = carry.index("export function carryPlaceBag")
        конец = carry.index("export function carryDrop")
        тело = carry[начало:конец]
        self.assertNotIn("carryPotionOnBag", тело,
                         "варка вернулась в мешок: в движке она под кодом 0x1C")
        self.assertNotIn("carryOntoStack", тело,
                         "складывание пачек вернулось в мешок, а оно в гнезде")
        self.assertIn("bagInsert(", тело, "вставки нет вовсе")
        # вес проверяется ДО вставки и всегда, как в 0x423218
        self.assertLess(тело.index('refuse("weight")'), тело.index("bagInsert("))

    def test_stacking_lives_in_the_mixing_socket(self) -> None:
        """Пачки складываются в гнезде смешивания (0x421690, ветка 0x1C)."""
        carry = self.client("carry.js")
        начало = carry.index("export function carryMixing")
        конец = carry.index("export function carryApplyTo")
        self.assertIn("carryOntoStack", carry[начало:конец],
                      "складывание пачек потерялось вместе с правкой мешка")

    def test_applying_an_item_to_a_character_exists_and_takes_potions_only(self) -> None:
        """Портрет с вещью в руке — 0x41F55C: вид 9 пьётся, прочее отвергается.

        Виды не выдуманы: `trade.item_kinds` пака даёт potion=9, coin=11,
        stack=12, а классы 84…92 из `effects.potions` — случаи switch внутри
        FUN_0041D954 с нулевой целью.
        """
        carry = self.client("carry.js")
        self.assertIn("export function carryApplyTo", carry)
        начало = carry.index("export function carryApplyTo")
        конец = carry.index("export function carryTake")
        тело = carry[начало:конец]
        self.assertIn("isPotionItem", тело)
        self.assertIn("potionDrink", тело)
        self.assertIn("return refuse()", тело, "не-зелье должно получать отказ")

    def test_the_portraits_are_wired_to_carrying(self) -> None:
        """Полоса портретов: свой — применить, чужой — положить в его мешок."""
        ui = self.client("ui.js")
        self.assertIn("carryApplyTo(hero)", ui)
        self.assertIn("carryPlaceBag(-1, hero)", ui)
        self.assertIn("carryApplyTo(mate)", ui)
        self.assertIn("carryPlaceBag(-1, mate)", ui)

    def test_the_potion_kinds_come_from_the_pack(self) -> None:
        """Вид зелья и класс-диапазон читаются из правил, а не вбиты в код."""
        import json
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        общий = root / "content_build" / "shared.json"
        if not общий.is_file():
            self.skipTest("нет собранного пака")
        правила = json.loads(общий.read_text(encoding="utf-8"))["hero"]["rules"]
        self.assertEqual(правила["trade"]["item_kinds"]["potion"], 9)
        self.assertEqual(правила["trade"]["item_kinds"]["coin"], 11)
        self.assertEqual(правила["trade"]["item_kinds"]["stack"], 12)
        зелья = правила["effects"]["potions"]
        self.assertEqual(зелья["halve"], 84)
        self.assertEqual(зелья["wisdom"], 92)


class RightButtonContractTest(unittest.TestCase):
    """Правая кнопка — VA 0x42F22C (сообщение 0x204) -> FUN_00422AFC.

    В оригинале это ГЛАВНЫЙ способ применить вещь. Разбор там такой:

        вещь в руке        -> FUN_0042944C(1), перенос отменяется;
        рука пуста, щелчок -> switch по виду записи (+0x00):
        по списку мешка       виды 0…4 и 0x0C — надеть в свой слот,
        (код попадания 0x41)  вид 6 — в гнездо украшений (0x41E8D8(0x17)),
                              вид 9 — выпить прямо из мешка (0x41D954),
                              вид 0x0B — 0x436C48, прочее — ничего.

    Гнёзд снаряжения в этом switch нет вовсе: правая кнопка по надетой вещи
    не делает ничего. У нас же она роняла на землю что угодно и откуда
    угодно — из-за этого первый бета-тестер не смог применить ни одного
    предмета (отчёт Александра С., 09.08.2026).
    """

    def client(self, name: str) -> str:
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        return (root / "knyaz2" / "web" / "static" / name).read_text(encoding="utf-8")

    def test_the_right_button_uses_instead_of_dropping(self) -> None:
        carry = self.client("carry.js")
        self.assertIn("export function carryUse", carry)
        начало = carry.index("export function carryUse")
        конец = carry.index("export function carryTake")
        тело = carry[начало:конец]
        # вещь в руке — отмена переноса, и это ПЕРВОЕ, что делает разбор
        self.assertIn("carryCancel()", тело)
        self.assertLess(тело.index("carryCancel()"), тело.index("carryPlaceSlot"))
        # питьё прямо из мешка и надевание по виду
        self.assertIn("carryApplyTo", тело)
        self.assertIn("SLOTS[kind]", тело)

    def test_no_cell_drops_items_on_the_ground_any_more(self) -> None:
        """Ни одна ячейка больше не роняет вещь по правой кнопке."""
        ui = self.client("ui.js")
        self.assertNotIn("dropFromBag", ui)
        self.assertNotIn("dropFromSlot", ui)
        self.assertIn("carryUse(index, panelUnit())", ui)
        # надетое: правая кнопка только отменяет перенос
        self.assertIn("carryUse(-1, panelUnit())", ui)

    def test_the_dead_drop_helpers_are_gone(self) -> None:
        """Функции нашей выдуманной правой кнопки удалены, а не оставлены."""
        inventory = self.client("inventory.js")
        self.assertNotIn("export function dropFromBag", inventory)
        self.assertNotIn("export function dropFromSlot", inventory)

    def test_the_equipment_slot_order_matches_the_kinds(self) -> None:
        """Виды 0…4 — это НОМЕРА гнёзд: 0x41E280 зовут и кодом, и видом."""
        inventory = self.client("inventory.js")
        начало = inventory.index("export const SLOTS")
        строка = inventory[начало:inventory.index("]", начало)]
        for место, имя in enumerate(["hand", "ranged", "body", "head", "off_hand"]):
            self.assertLess(строка.index(f'"{имя}"'),
                            строка.index('"ammo"') if имя != "off_hand"
                            else len(строка),
                            f"гнездо {имя} должно идти {место}-м")


class VillageByWorldContractTest(unittest.TestCase):
    """Запись поселения своя в каждом GAME.N — как и отряды.

    Должностные лица деревни (пятёрка номеров с +0x3D0) отличаются от мира к
    миру, а на них держится маршрутизация разговора: корневая ветвь спрашивает
    обработчиком 30 «занимает ли собеседник должность N» (VA 0x435550). Пока
    пак вёз ратиборовскую запись всем, за любого другого героя ни одна ветвь
    не совпадала и разговор проваливался в последнюю, безусловную — реплику
    наёмника «Я отдохнул и готов идти за тобой». Первый бета-тестер поймал это
    Александром в Борье (отчёт от 09.08.2026).
    """

    @needs_game
    def test_the_officials_differ_between_worlds(self) -> None:
        from konung2.gamefile import village
        по_мирам = {мир: village(33, мир)["officials"] for мир in range(6)}
        # ратиборовская пятёрка не годится Александру
        self.assertEqual(по_мирам[0][:4], [236, 237, 238, 239])
        self.assertEqual(по_мирам[4][:4], [229, 230, 231, 232])
        self.assertNotEqual(по_мирам[0], по_мирам[4],
                            "если записи совпали, весь этот механизм не нужен")

    def test_the_builder_exports_every_world(self) -> None:
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        сборщик = (root / "knyaz2" / "content" / "builder.py").read_text(encoding="utf-8")
        self.assertIn("village_by_world", сборщик)
        self.assertIn("village(number, game_world)", сборщик)

    def test_the_client_picks_the_record_of_its_own_world(self) -> None:
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        мир = (root / "knyaz2" / "web" / "static" / "world.js").read_text(encoding="utf-8")
        self.assertIn("village_by_world", мир)
        # подмена делается ОДИН раз при загрузке карты, а не в каждом читателе
        self.assertEqual(мир.count("village_by_world"), 1)

    def test_the_pack_carries_the_record_for_every_world(self) -> None:
        import json
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        карта = root / "content_build" / "maps" / "33" / "map.json"
        if not карта.is_file():
            self.skipTest("нет собранного пака")
        документ = json.loads(карта.read_text(encoding="utf-8"))
        по_мирам = документ.get("village_by_world")
        if not по_мирам:
            self.skipTest("пак собран до этой правки — нужна пересборка карты 33")
        self.assertEqual(sorted(по_мирам), [str(i) for i in range(6)])
        self.assertEqual(по_мирам["4"]["officials"][:4], [229, 230, 231, 232])


class MixingSocketVisibilityContractTest(unittest.TestCase):
    """Помеченная гнездом вещь не видна в мешке (VA 0x420890, 0x420E88).

    Гнездо смешивания вещь себе не забирает — она лежит в мешке, а гнездо
    только помечает её словом 0x849668. Чтобы её не было в двух местах разом,
    движок ВЕЗДЕ читает такую ячейку как пустую: и предикат прокрутки пояса
    (0x420890), и подсказка (0x420E88) сравнивают запись с этим словом
    наравне с нулём.

    Без правила бета-тестер положил единственную банку в гнездо, увидел её же
    в поясе, взял оттуда и смешал саму с собой — банка застряла навсегда.
    """

    def client(self, name: str) -> str:
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        return (root / "knyaz2" / "web" / "static" / name).read_text(encoding="utf-8")

    def test_the_rule_exists_in_one_place(self) -> None:
        craft = self.client("craft.js")
        self.assertIn("export function mixingHides", craft)
        self.assertIn("name === mixing.name", craft)

    def test_the_belt_reads_the_marked_cell_as_empty(self) -> None:
        ui = self.client("ui.js")
        self.assertIn("mixingHides(held) ? null : held", ui)

    def test_the_marked_item_cannot_be_taken_from_the_bag(self) -> None:
        carry = self.client("carry.js")
        начало = carry.index("export function carryTake")
        конец = carry.index("export function carryCancel")
        self.assertIn("mixingHides(actor.bag?.[index])", carry[начало:конец])

    def test_the_right_button_on_the_world_belongs_to_the_game(self) -> None:
        """Меню браузера по миру гасится, а щелчок разбирается по 0x422AFC."""
        inp = self.client("input.js")
        self.assertIn('canvas.addEventListener("contextmenu"', inp)
        self.assertIn("event.preventDefault()", inp)
        self.assertIn("carryCancel()", inp)
        self.assertIn("panelToHero()", inp)


class CarryCursorContractTest(unittest.TestCase):
    """Несомая вещь видна поверх всего экрана, и её можно вынуть из гнезда."""

    def client(self, name: str) -> str:
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        return (root / "knyaz2" / "web" / "static" / name).read_text(encoding="utf-8")

    def test_the_carried_icon_covers_the_panels_too(self) -> None:
        """Перенос — режим курсора (VA 0x42DDA0), панели ему не помеха.

        Картинка вешалась на холст мира, а пояс и гнёзда — отдельные узлы со
        своим `cursor: pointer`: стоило увести мышь на панель, и вещь с
        курсора пропадала, хотя оставалась в руке.
        """
        cursors = self.client("cursors.js")
        self.assertIn("export function carryCursorSync", cursors)
        self.assertIn('querySelector("#game")', cursors)
        styles = self.client("styles.css")
        self.assertIn("#game.carrying *", styles)
        self.assertIn("var(--carry-cursor) !important", styles)
        # синхронизация идёт на каждой перерисовке интерфейса
        self.assertIn("carryCursorSync();", self.client("ui.js"))

    def test_the_socket_mark_is_cleared_before_taking(self) -> None:
        """Вынуть вещь из гнезда можно, хотя её ячейка читается пустой.

        Ячейка помеченной вещи считается пустой (VA 0x420890), и взятие из неё
        запрещено. Значит пометку надо снять ПЕРВОЙ, иначе законный путь —
        щелчок по самому гнезду — тоже перестаёт работать: на этом я и
        споткнулся, поставив охрану в carryTake.
        """
        carry = self.client("carry.js")
        начало = carry.index("export function carryMixing")
        конец = carry.index("export function carryUse")
        тело = carry[начало:конец]
        self.assertLess(тело.index("mixingTake()"), тело.index("carryTake(found.from"),
                        "пометку снимают ПОСЛЕ взятия — вынуть вещь станет нечем")
        self.assertIn("mixingPlace(held.name, held.strength)",
                      тело, "не вышло взять — пометку надо вернуть")


class ShopStockContractTest(unittest.TestCase):
    """Наполнение лавок — перенос FUN_0041896C (см. docs/SHOP_STOCK_SPEC.md).

    Генератор зовёт загрузчик карты FUN_0043DF48 последней строкой, поэтому
    прилавки набиваются на КАЖДОМ входе. В самих GAME.N они пусты, и пока
    вызова не было, все лавки в игре стояли пустыми — на это и пожаловался
    первый бета-тестер (отчёт Александра С., 09.08.2026).
    """

    def client(self, name: str) -> str:
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        return (root / "knyaz2" / "web" / "static" / name).read_text(encoding="utf-8")

    def test_the_restock_runs_on_every_map_entry(self) -> None:
        app = self.client("app.js")
        self.assertIn("shopsRestock()", app)
        # обе точки входа на карту: обычная и после сейва
        self.assertEqual(app.count("shopsRestock();"), 2)
        # рядом с расстановкой построек, как в 0x43DF48
        self.assertIn("buildingsSetup();\n  //", app)

    def test_the_group_sizes_and_odds_match_the_disassembly(self) -> None:
        """Границы 3/2/3/6 и пороги 0x46/0x32/0x1e/0x32.

        Сняты с цикла по местам: граница `[ebp-8]` наращивается на 3, 2, 3 и 6
        (VA 0x418A36, 0x418C62, 0x418D27, 0x418E78), а порог сравнивается с
        остатком rand()%100 (0x418A76, 0x418C9F, 0x418D64, 0x418EB5).
        """
        shops = self.client("shops.js")
        начало = shops.index("const GROUPS")
        конец = shops.index("]", начало)
        группы = shops[начало:конец]
        for размер, порог in (("3", "0x46"), ("2", "0x32"), ("3", "0x1e"), ("6", "0x32")):
            self.assertIn(f"size: {размер}, over: {порог}", группы)

    def test_the_level_is_capped_at_thirteen(self) -> None:
        """Уровень режется потолком 13 (VA 0x00418A22, снято дизассемблером)."""
        shops = self.client("shops.js")
        self.assertIn("const LEVEL_CAP = 13", shops)
        self.assertIn("Math.min(hero.level ?? 1, LEVEL_CAP)", shops)

    def test_the_smith_counter_is_not_touched(self) -> None:
        """Прилавок кузнеца (+0x44E) наполняет мастерская, а не этот генератор.

        Проверено по дизассемблеру: обращений к +0x3E0 — два, к +0x40E —
        двадцать шесть, к +0x44E — ни одного.
        """
        shops = self.client("shops.js")
        self.assertIn("role === 2", shops)
        self.assertIn("role === 3", shops)
        self.assertNotIn("role === 4", shops)

    def test_the_named_classes_exist_in_the_pack_with_the_right_kinds(self) -> None:
        """Классы, которые называет генератор, сходятся с паком по видам.

        Это независимая проверка расшифровки: номера взяты из дизассемблера,
        а виды — из данных игры, и они обязаны совпасть.
        """
        import json
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        карта = root / "content_build" / "maps" / "33" / "map.json"
        if not карта.is_file():
            self.skipTest("нет собранного пака")
        предметы = json.loads(карта.read_text(encoding="utf-8"))["items"]
        по_индексу = {v["index"]: v for v in предметы.values()
                      if isinstance(v.get("index"), int)}
        ожидаем = {83: 9,     # пустая банка — вид зелья
                   60: 6, 63: 7, 66: 8,   # ожерелье, браслет, кольцо
                   30: 11,    # вино (вид 0x0B), а НЕ монета
                   101: 0,    # оружие, база 0x65
                   115: 1,    # метательное, база 0x73
                   120: 2,    # броня, база 0x78
                   124: 4,    # щит, база 0x7C
                   129: 3}    # шлем, база 0x81
        for индекс, вид in ожидаем.items():
            запись = по_индексу.get(индекс)
            self.assertIsNotNone(запись, f"класса {индекс} нет в паке")
            self.assertEqual(запись.get("kind"), вид,
                             f"класс {индекс} ({запись.get('name')}) не того вида")


class ImageCacheContractTest(unittest.TestCase):
    """Память под картинки: не грузить дважды и не копить чужое.

    Лист актёра — 4095x1700, в распакованном виде около 26 МБ. Между картами
    `world.images` не чистился вовсе, и листы прежних карт оставались в памяти
    навсегда: на телефоне вкладку убивало раньше, чем кончался трафик.
    """

    def client(self, name: str) -> str:
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        return (root / "knyaz2" / "web" / "static" / name).read_text(encoding="utf-8")

    def test_preload_skips_what_is_already_loaded(self) -> None:
        content = self.client("content.js")
        начало = content.index("export async function preload")
        конец = content.index("}", content.index("await Promise.all", начало))
        self.assertIn("!world.images.has(path)", content[начало:конец])

    def test_foreign_sheets_are_dropped_on_every_map_entry(self) -> None:
        app = self.client("app.js")
        self.assertIn("function forgetForeignSheets", app)
        # обе точки входа на карту
        self.assertEqual(app.count("forgetForeignSheets(map.hero"), 2)

    def test_only_actor_sheets_are_dropped(self) -> None:
        """Землю и постройки не трогаем: они мелкие, а перезагрузка их дорога."""
        app = self.client("app.js")
        начало = app.index("function forgetForeignSheets")
        конец = app.index("\n}", начало)
        тело = app[начало:конец]
        self.assertIn('path.includes("/units/")', тело)
        self.assertIn("actorSheetPaths(data, actors)", тело)

    def test_the_sheet_set_does_not_depend_on_the_pose(self) -> None:
        """Основание выброса: набор листов актёра одинаков для всех поз.

        Замер на живой карте 23: `stand` из 16 записей требует те же 24 листа,
        что и `walk` из 224 и что все шестнадцать поз вместе. Лист хранит одну
        пару «слой + палитра» целиком. Поэтому `actorSheetPaths`, который
        смотрит только записи `stand`, и есть ПОЛНЫЙ список нужного, а всё
        сверх него осталось от прежней карты.

        Здесь проверяется, что это свойство пака не изменилось: у любого
        набора кадров одной пары «слой + палитра» лист один и тот же.

        Делить лист по позам пробовали 2026-08-10: вход дешевел впятеро, но
        кадры удара уезжали на отдельный лист, и пока он ехал, юнит бился без
        доспеха. Правка снята целиком; разбор лежит в docs/LOADING_PLAN.md.
        """
        import json
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        общий = root / "content_build" / "shared.json"
        if not общий.is_file():
            self.skipTest("нет собранного пака")
        герой = json.loads(общий.read_text(encoding="utf-8"))["hero"]
        расходятся = []
        for имя, набор in list((герой.get("equipment") or {}).items())[:40]:
            листы = {кадр["sheet"] for кадр in (набор.get("frames") or {}).values()
                     if isinstance(кадр, dict) and кадр.get("sheet") is not None}
            if len(листы) > 1:
                расходятся.append((имя, sorted(листы)))
        self.assertEqual(расходятся, [],
                         "пара «слой+палитра» разъехалась по нескольким листам — "
                         "выброс листов между картами больше не безопасен")


class VillagePostsContractTest(unittest.TestCase):
    """Должности деревни: назначение (74) и вывод роли (VA 0x415190).

    Пятёрка должностей лежит по u16 с +0x3D0 записи поселения. Роль
    собеседника движок НЕ хранит: FUN_00415190 перебирает эту пятёрку и
    отдаёт «место + 1» — отсюда у знахаря 2, у купца 3, у кузнеца 4.

    Занимает должность действие разговора 74 (FUN_00435D4C, запись 74 таблицы
    0x462E90). Оно не было перенесено, а значит НИ ОДНА должность не могла
    быть занята: без воеводы некому обучать в казарме, без кузнеца стоит
    мастерская. Казарма при этом ни на одной карте и ни в одном мире не
    построена изначально — её сперва надо возвести.
    """

    def client(self, name: str) -> str:
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        return (root / "knyaz2" / "web" / "static" / name).read_text(encoding="utf-8")

    def test_appointment_handler_exists_and_guards_the_post(self) -> None:
        dialog = self.client("dialog.js")
        self.assertIn("  74: (post) =>", dialog)
        начало = dialog.index("  74: (post) =>")
        конец = dialog.index("  75:", начало)
        тело = dialog[начало:конец]
        self.assertIn("if (officials[post]) return false", тело,
                      "занятую должность движок не перезаписывает")
        self.assertIn("officials[post] = unit.slot", тело)
        # поле role не пишем: роль выводится из этого же списка
        self.assertNotIn("unit.role = post + 1", тело)

    def test_the_role_is_derived_in_one_place(self) -> None:
        village = self.client("village.js")
        self.assertIn("export function officialRole", village)
        self.assertIn("officials.indexOf(number)", village)
        self.assertIn("place + 1", village)

    def test_the_shops_use_the_derived_role(self) -> None:
        """Лавки ключуются выведенной ролью, а не полем пака.

        Поле `role` в паке проставлено по МИРУ 0. За любого другого героя оно
        равно нулю у всех должностных — и лавки молчали бы, как и молчали.
        """
        shops = self.client("shops.js")
        self.assertIn("officialRole(unit)", shops)
        self.assertNotIn("unit.role ===", shops)

    def test_the_pack_role_field_disagrees_with_other_worlds(self) -> None:
        """Основание вывода: поле пака сходится только с миром 0."""
        import json
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        карта = root / "content_build" / "maps" / "33" / "map.json"
        if not карта.is_file():
            self.skipTest("нет собранного пака")
        документ = json.loads(карта.read_text(encoding="utf-8"))
        по_мирам = документ.get("village_by_world") or {}
        if not по_мирам:
            self.skipTest("пак собран до village_by_world")
        роли = {ю["id"]: ю.get("role", 0) for ю in документ["units"]}
        номер = lambda id_: int(str(id_).replace("unit_", ""))

        def выведено(мир, id_):
            места = по_мирам[мир]["officials"]
            место = места.index(номер(id_)) if номер(id_) in места else -1
            return место + 1 if место >= 0 else 0

        сходится_0 = [id_ for id_, роль in роли.items() if роль
                      and выведено("0", id_) == роль]
        self.assertTrue(сходится_0, "в мире 0 поле и вывод обязаны совпадать")
        расходится_4 = [id_ for id_, роль in роли.items()
                        if роль and выведено("4", id_) != роль]
        self.assertTrue(расходится_4,
                        "если поле годится и другим мирам, вывод не нужен")

    def test_the_barracks_is_never_prebuilt(self) -> None:
        """Казарма (вид 13) нигде не построена изначально — её строит игрок."""
        import json
        import os
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        каталог = root / "content_build" / "maps"
        if not каталог.is_dir():
            self.skipTest("нет собранного пака")
        с_казармой, построенных = 0, 0
        for имя in os.listdir(каталог):
            файл = каталог / имя / "map.json"
            if not файл.is_file():
                continue
            документ = json.loads(файл.read_text(encoding="utf-8"))
            for запись in ((документ.get("village") or {}).get("buildings") or []):
                if запись.get("kind") != 13:
                    continue
                с_казармой += 1
                if запись.get("built"):
                    построенных += 1
        self.assertEqual(с_казармой, 3, "казарма есть ровно на трёх картах")
        self.assertEqual(построенных, 0)


class VillagePlotsContractTest(unittest.TestCase):
    """Пустые места деревни: лестница состояний и ссылка на место.

    Постройку рисует картинка «спрайт вида + состояние» (VA 0x4171CC), а
    закладка (действие 40, FUN_00433730) только ставит срок в поле +0x1E
    записи места. Дальше стройку двигает ОБЪЕКТ КАРТЫ — значит объект обязан
    знать своё место деревни и иметь картинки всех семи ступеней.

    Сборщик отбрасывал непостроенные места и искал объект только среди
    построек. Из-за этого казарму нельзя было построить ни на одной карте, а
    изначально она не построена нигде.
    """

    def map33(self) -> dict:
        import json
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        файл = root / "content_build" / "maps" / "33" / "map.json"
        if not файл.is_file():
            self.skipTest("нет собранного пака")
        return json.loads(файл.read_text(encoding="utf-8"))

    def test_the_unbuilt_plot_carries_its_states(self) -> None:
        документ = self.map33()
        все = [*документ.get("buildings", []), *документ.get("props", [])]
        казарма = [o for o in все if o.get("village_slot") == 4]
        if not казарма:
            self.skipTest("карта собрана до правки площадок")
        запись = казарма[0]
        self.assertEqual(запись.get("village_state"), 0, "площадка не застроена")
        self.assertEqual(len(запись.get("states") or {}), 7,
                         "у вида семь ступеней: стройка, готово, пожар, пепелище")

    def test_the_object_number_spans_buildings_and_props(self) -> None:
        """Номер объекта в записи поселения сквозной по всей карте.

        На Борье постройки занимают 0…8, реквизит 9…132. Площадка казармы —
        реквизит 9, колодца — реквизит 123. Пока лестницу раздавали по одному
        списку построек, такие места не находились вовсе.
        """
        документ = self.map33()
        реквизит = документ.get("props", [])
        связанный = [o for o in реквизит if o.get("village_slot") is not None]
        if not связанный:
            self.skipTest("карта собрана до правки площадок")
        self.assertTrue(связанный, "среди реквизита обязаны быть места деревни")

    def test_the_empty_kind_does_not_steal_object_zero(self) -> None:
        """У вида 0xFF номер объекта нулевой — это «ничего», а не объект ноль.

        Пустое место 5 Борья затирало собой дом старосты, который объектом
        ноль владеет по-настоящему.
        """
        документ = self.map33()
        все = [*документ.get("buildings", []), *документ.get("props", [])]
        места = {o.get("village_slot") for o in все if o.get("village_slot") is not None}
        if not места:
            self.skipTest("карта собрана до правки площадок")
        self.assertIn(0, места, "дом старосты потерял своё место")
        self.assertNotIn(5, места, "пустое место не должно получать объект")

    def test_the_sprite_ladder_matches_the_kind_table(self) -> None:
        """Сверка нумерации: ресурс объекта = спрайт вида + состояние + 30.

        Проверяется на построенных, где ответ известен заранее, и служит
        основанием тому, что лестница отсчитывается от собственного ресурса.
        """
        from konung2.gamefile import building_kinds, village
        if not GAME_AVAILABLE:
            self.skipTest("игра недоступна")
        виды = {k["kind"]: k for k in building_kinds()}
        поселение = village(33, 0)
        сдвиги = set()
        документ = self.map33()
        все = {o.get("record_slot"): o
               for o in [*документ.get("buildings", []), *документ.get("props", [])]}
        for место in поселение["buildings"]:
            вид = виды.get(место["kind"])
            объект = все.get(место["object"])
            if not вид or not объект or место["kind"] == 0xFF:
                continue
            сдвиги.add(объект["resource_slot"] - (вид["sprite"] + место["state"]))
        self.assertEqual(сдвиги, {30}, "сдвиг нумерации перестал быть постоянным")


class VillageBuildContractTest(unittest.TestCase):
    """Стройка доходит до записи места, а не живёт в одном объекте карты.

    В движке ступень одна: байт +0x19 записи поселения, и объект карты
    рисуется по ней же. У нас копии две, и пока ступень жила только в объекте,
    деревня не замечала построенного — условие разговора 4 «есть ли постройка»
    (VA 0x434AF0) отвечало нет и на готовой казарме.
    """

    def client(self, name: str) -> str:
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        return (root / "knyaz2" / "web" / "static" / name).read_text(encoding="utf-8")

    def test_the_tick_writes_the_stage_back_to_the_village(self) -> None:
        buildings = self.client("buildings.js")
        self.assertIn("place.state = object.state", buildings)
        self.assertIn("place.built = Boolean(object.state || object.timer)", buildings,
                      "«есть» решается по двум полям: ступень или срок ненулевые")

    def test_the_place_follows_the_object_every_tick(self) -> None:
        """Счётчик места идёт КАЖДЫЙ такт, а не только на смене ступени.

        В движке копии нет вовсе: ступень (+0x19) и счётчик (+0x1E) живут в
        самой записи места, и условия разговора читают их. Пока у нас счётчик
        до конца стройки оставался в объекте, место стояло с тем сроком, что
        положил обработчик 40, и староста продолжал предлагать заложить уже
        строящееся.
        """
        buildings = self.client("buildings.js")
        self.assertIn("function placeFollow", buildings)
        начало = buildings.index("object.timer -= 1;")
        конец = buildings.index("if (object.timer > 0) continue;", начало)
        self.assertIn("placeFollow(object)", buildings[начало:конец],
                      "место снова узнаёт о стройке только на смене ступени")
        # И условия разговора читают ЖИВУЮ пару, а не поле пака `built`.
        dialog = self.client("dialog.js")
        начало = dialog.index("  4: (argument) =>")
        конец = dialog.index("  6: (argument) =>", начало)
        self.assertIn("(found.state ?? 0) || (found.timer ?? 0)",
                      dialog[начало:конец])
        конец6 = dialog.index("  17: (klass)", конец)
        self.assertIn("(found.state ?? 0) || (found.timer ?? 0)",
                      dialog[конец:конец6])


class CtrlTalkContractTest(unittest.TestCase):
    """Ctrl по своему юниту — заговорить, а не выбрать (VA 0x421690:279).

    Разбор щелчка смотрит на флаг 0x8495AC. Какая это клавиша — снято с
    главного цикла (VA 0x438A00:44): виртуальный код 0x11 (Ctrl) поднимает
    0x8495AC, а 0x10 (Shift) — другой флаг, 0x849608, «добавить к выбору».
    С зажатым Ctrl движок пишет ИГРОКУ целый байт приказа 0x22 и номер этого
    юнита целью, то есть игрок идёт разговаривать.

    Через этот разговор спутника и назначают на должность в деревне: действие
    74 работает с собеседником, и назначенный уходит из отряда.
    """

    def client(self, name: str) -> str:
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        return (root / "knyaz2" / "web" / "static" / name).read_text(encoding="utf-8")

    def test_the_click_carries_the_ctrl_flag(self) -> None:
        inp = self.client("input.js")
        self.assertIn("event.shiftKey, event.ctrlKey", inp)
        combat = self.client("combat.js")
        self.assertIn("running = false, add = false, talk = false", combat)

    def test_ctrl_on_an_ally_talks_before_selecting(self) -> None:
        combat = self.client("combat.js")
        разговор = combat.index("talk && orderTalkTo(who, running)")
        выбор = combat.index("// Свой — это ВЫБОР")
        self.assertLess(разговор, выбор,
                        "ветка Ctrl обязана стоять ДО обычного выбора")
        начало = combat.index("export function orderTalkTo")
        конец = combat.index("export function orderAt")
        self.assertIn("hero.orderByte = 0x22", combat[начало:конец],
                      "движок пишет байт приказа целиком, а не одну половину")

    def test_ctrl_on_the_panel_portrait_talks_too(self) -> None:
        """VA 0x421690:349 — щелчок по портрету идёт той же веткой, что и по миру.

        Попадание ищется по таблице прямоугольников панели (0x460EB4,
        VA 0x43AEF0): портрет отряда даёт код ``место * 0x100 + 1``, и
        младший байт меньше двух отправляет разбор в ту же ветку, где стоит
        проверка флага Ctrl (0x8495AC) и запись приказа 0x22 игроку.
        Значит и у нас это должен быть ОДИН код на оба щелчка.
        """
        combat = self.client("combat.js")
        ui = self.client("ui.js")
        # Ветка живёт в combat.js одной функцией и вывезена наружу.
        self.assertIn("export function orderTalkTo", combat)
        self.assertIn("orderTalkTo", ui.split("import")[1:][0] + ui)
        # Панель зовёт ЕЁ, а не свою копию приказа.
        self.assertNotIn("hero.orderByte = 0x22", ui,
                         "панель обязана звать общую ветку, а не копировать её")
        начало = ui.index("onClick: mate ?")
        конец = ui.index("onDoubleClick: mate ?", начало)
        ветка = ui[начало:конец]
        self.assertIn("keyHeld.ctrl && orderTalkTo(mate)", ветка)
        # Ctrl проверяется ДО выбора: в движке ветка выбора стоит следом.
        self.assertLess(ветка.index("orderTalkTo(mate)"),
                        ветка.index("selectUnit(mate"))
        # Модификатор берётся и с клавиатуры, и с самого щелчка.
        self.assertIn("keyHeld = { shift: false, ctrl: false }", ui)
        self.assertIn("keyHeldFrom(event)", ui)

    def test_the_appointee_leaves_the_party(self) -> None:
        """VA 0x435D4C зовёт 0x4338B0 и без его успеха НЕ занимает должность."""
        units = self.client("units.js")
        self.assertIn("export function partyRelease", units)
        dialog = self.client("dialog.js")
        начало = dialog.index("  74: (post) =>")
        конец = dialog.index("  75:", начало)
        тело = dialog[начало:конец]
        # Переезд в деревню — общий с «Останься здесь» обработчик 43.
        self.assertIn("if (!HANDLERS[43](0)) return false;", тело)
        # Должность занимается ПОСЛЕ переезда, как в 0x435D4C.
        self.assertLess(тело.index("HANDLERS[43](0)"),
                        тело.index("officials[post] = unit.slot"))
        # Сам уход из отряда — в теле 43.
        начало = dialog.index("  43: (argument) =>")
        конец = dialog.index("  44:", начало)
        уход = dialog[начало:конец]
        self.assertIn("partyRelease(unit)", уход)
        self.assertIn("unit.ally = false", уход)

    def test_the_companion_can_be_left_as_a_villager(self) -> None:
        """VA 0x4338B0 — «Останься здесь, пока я не хочу рисковать тобой».

        Реплика стоит под условием 28(0) «на карте есть поселение»
        (0x4354A8, первая ветка), а само действие: отказ без деревни, отказ
        при полном отряде деревни (+0x1C == +0x1A), иначе сторона деревни,
        приказ в ноль вместе с битом 0x10 «за вожаком», вычёркивание из
        отряда игрока и починка панели девяти.
        """
        dialog = self.client("dialog.js")
        начало = dialog.index("  43: (argument) =>")
        конец = dialog.index("  44:", начало)
        тело = dialog[начало:конец]
        # Гейт по деревне и по её вместимости.
        self.assertIn("world.map?.village", тело)
        self.assertIn("squad_places", тело)
        self.assertIn("people >= places", тело)
        # Приказ снимается ЦЕЛИКОМ: бит «за вожаком» переживает любой другой.
        self.assertIn("unit.orderByte = 0;", тело)
        # Панель девяти (0x420644 -> 0x43AE14).
        self.assertIn("deselect(unit)", тело)
        self.assertIn("import { deselect, orderKinds, orderUnit }", dialog)
        # Числа запаса — из GAME.0, а не из головы: Борье 14 занято из 17.
        from konung2.gamefile import village
        борье = village(33)
        self.assertEqual((борье["squad_people"], борье["squad_places"]),
                         (14, 17))

    def test_the_modifier_codes_come_from_the_engine(self) -> None:
        """Сверка по байтам: 0x10 поднимает один флаг, 0x11 — другой."""
        if not GAME_AVAILABLE:
            self.skipTest("игра недоступна")
        from konung2.exetables import va_to_foff
        from konung2.paths import game_file
        blob = open(game_file("konung2.exe"), "rb").read()
        окно = blob[va_to_foff(0x00438A00):va_to_foff(0x00438A00) + 0x120]
        # адреса обоих флагов обязаны встретиться в этом окне
        self.assertIn((0x008495AC).to_bytes(4, "little"), окно)
        self.assertIn((0x00849608).to_bytes(4, "little"), окно)


class BarracksContractTest(unittest.TestCase):
    """Казарма целиком: клетки, крыша, воевода и спарринг.

    Все четыре наблюдения бета-тестера («внутрь не зайти», «крыша не
    убирается», «воевода не стоит у казармы», «никто не тренируется»)
    оказались разными недоделками порта, и каждая доказана по движку.
    """

    def client(self, name: str) -> str:
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        return (root / "knyaz2" / "web" / "static" / name).read_text(encoding="utf-8")

    def test_cells_are_restamped_by_the_stage(self) -> None:
        """VA 0x43F178: ступени 3 и 4 открывают клетки, прочие — глушат."""
        hero = self.client("hero.js")
        self.assertIn("export function heroStampBuilding", hero)
        начало = hero.index("export function heroStampBuilding")
        конец = hero.index("\n}", начало)
        тело = hero[начало:конец]
        self.assertIn("object.state === ready || object.state === ready + 1", тело)
        self.assertIn("open ? 0 : CELL_WALL", тело)
        buildings = self.client("buildings.js")
        self.assertIn("heroStampBuilding(object, ready)", buildings)

    def test_props_with_cells_join_the_building_index(self) -> None:
        """Крыша прячется по клетке юнита (VA 0x428282), а площадка — реквизит."""
        hero = self.client("hero.js")
        self.assertIn("...(map.buildings ?? []), ...(map.props ?? [])", hero)

    def test_the_order_comes_from_the_workplace_kind(self) -> None:
        """VA 0x412C0C: 0x90/0xA0 -> 9, 0x70/0x80 -> 10, иначе 7."""
        units = self.client("units.js")
        начало = units.index("function orderFromWorkplace")
        конец = units.index("\n}", начало)
        тело = units[начало:конец]
        self.assertIn("high === 0x90 || high === 0xA0", тело)
        self.assertIn("high === 0x70 || high === 0x80", тело)
        self.assertIn("workplace?.kind ?? 0) & 0xF0", тело)

    def test_sparring_grants_experience_to_the_partner(self) -> None:
        """VA 0x413894: напарник через клетку, разворот навстречу, +1 за 1024."""
        units = self.client("units.js")
        self.assertIn("const SPARRING_ORDER = 9", units)
        self.assertIn("const SPARRING_PHASE = 0x3FF", units)
        начало = units.index("function sparringTick")
        конец = units.index("\n}", units.index("grantExperience(mate, 1)", начало))
        тело = units[начало:конец]
        # два шага в свою сторону
        self.assertEqual(тело.count("heroNeighbor("), 2)
        self.assertIn("((unit.direction ?? 0) + 4) & 7", тело)
        self.assertIn("mate.side !== unit.side", тело)

    def test_the_appointee_walks_to_the_post_spot(self) -> None:
        """VA 0x435D4C: место должности N — строка и столбец рабочего места N.

        Байты записи культуры +0x21 и +0x22 со сдвигом «должность × 4» — это
        та же память, где лежит таблица рабочих мест (WORKPLACE_TABLE_AT=0x20,
        шаг 4: вид, строка, столбец, вес).
        """
        dialog = self.client("dialog.js")
        начало = dialog.index("  74: (post) =>")
        конец = dialog.index("  75:", начало)
        тело = dialog[начало:конец]
        self.assertIn("village.workplaces ?? []", тело)
        self.assertIn("place.slot === post", тело)
        self.assertIn("unitSendTo(unit, spot.row, spot.col, 0x0B)", тело)
        from konung2.gamefile import WORKPLACE_STRIDE, WORKPLACE_TABLE_AT
        self.assertEqual((WORKPLACE_TABLE_AT, WORKPLACE_STRIDE), (0x20, 4))


class WaitTalkReleaseContractTest(unittest.TestCase):
    """«Стой, с тобой говорят» ОТПУСКАЕТ (VA 0x413894, случай 0x0C).

    Приказ 0x0C держится ровно пока идёт разговор: экран открыт с этим
    юнитом либо игрок идёт к нему с приказом «заговорить» (младшая половина
    2, цель — он). Иначе движок зовёт FUN_00416E24: цель в ноль, занятие
    снимается маской 0xB0.

    У нас счётчик `waitTalk` ставился и не убирался никем — собеседник
    навсегда оставался с занятием 0x0C. Отсюда «спутник стоит как вкопанный»
    и «после разговора не поговорить со старостой».
    """

    def client(self, name: str) -> str:
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        return (root / "knyaz2" / "web" / "static" / name).read_text(encoding="utf-8")

    def test_the_release_exists_and_runs_every_tick(self) -> None:
        units = self.client("units.js")
        self.assertIn("function waitTalkTick", units)
        self.assertIn("waitTalkTick(unit);", units)

    def test_it_holds_only_while_the_talk_is_on(self) -> None:
        units = self.client("units.js")
        начало = units.index("function waitTalkTick")
        конец = units.index("\n}", units.index("orderClear(unit)", начало))
        тело = units[начало:конец]
        self.assertIn("world.talking?.unit === unit", тело)
        self.assertIn("hero.orderTarget === unit", тело)
        self.assertIn("orderClear(unit)", тело)

    def test_the_clear_uses_the_engine_mask(self) -> None:
        """FUN_00416E24 снимает занятие маской 0xB0 — это и делает orderClear."""
        orders = self.client("orders.js")
        начало = orders.index("export function orderClear")
        конец = orders.index("\n}", начало)
        self.assertIn("& 0xB0", orders[начало:конец])


class RightButtonSelectsHeroContractTest(unittest.TestCase):
    """Правая кнопка по миру выделяет главного (VA 0x422AFC -> 0x420644).

    Разбор второй кнопки пустой рукой обнуляет структуру у 0x840B94, кладёт
    туда самого игрока и зовёт FUN_00420644, а тот ставит указатель панели
    `_DAT_00849514` на него. У нас панель выводится из выбора, поэтому
    «панель игроку» и значит «выбран один главный».
    """

    def client(self, name: str) -> str:
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        return (root / "knyaz2" / "web" / "static" / name).read_text(encoding="utf-8")

    def test_the_context_menu_selects_the_hero(self) -> None:
        inp = self.client("input.js")
        начало = inp.index('canvas.addEventListener("contextmenu"')
        конец = inp.index("});", начало)
        тело = inp[начало:конец]
        self.assertIn("selectUnit(hero)", тело)
        self.assertIn("panelToHero()", тело)
        # с вещью в руке — отмена переноса, и она стоит РАНЬШЕ выбора
        self.assertLess(тело.index("carryCancel()"), тело.index("selectUnit(hero)"))


class ContainerContractTest(unittest.TestCase):
    """Контейнеры на земле: деньги, гнёзда и что в данных есть на самом деле.

    Запись 101 байт, таблица GAME.N по 0x2C800, тысяча штук. Поле +0x0F —
    деньги, и обыск берёт их ПО МОДУЛЮ (VA 0x4115AC: `FUN_00442B7E` это
    abs()). Отрицательное значит «клад зарыт» — такой обыскивается только с
    Лопатой (класс 0x20).
    """

    def client(self, name: str) -> str:
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        return (root / "knyaz2" / "web" / "static" / name).read_text(encoding="utf-8")

    def test_money_is_taken_by_absolute_value(self) -> None:
        combat = self.client("combat.js")
        self.assertIn("const taken = Math.abs(pile.money);", combat)
        self.assertIn("hero.money = (hero.money ?? 0) + taken;", combat)
        #: Прежняя строка отнимала бы монеты у зарытого клада.
        self.assertNotIn("hero.money = (hero.money ?? 0) + pile.money;", combat)

    def test_the_pile_limits_match_the_engine(self) -> None:
        """42 гнезда в записи и 200 живых записей — оба числа из движка."""
        loot = self.client("loot.js")
        self.assertIn("export const PILE_SLOTS = 42;", loot)
        self.assertIn("export const PILE_LIMIT = 200;", loot)

    def test_hidden_containers_point_at_real_furniture(self) -> None:
        """Сундук внутри объекта адресуется парой (объект, гнездо).

        Байт +0x09 записи кучи — номер объекта, +0x0A — гнездо в нём, а сама
        обстановка лежит в карте: блок 0x3D384 файла .KN2, тридцать объектов
        по шестнадцать гнёзд по 12 байт. Загрузчик (VA 0x43DF48) кладёт номер
        живого контейнера в старший байт слова гнезда:

            0x6AE45C + place * 0xC0 + slot * 0x0C

        Проверяем, что связка не висит в воздухе: каждый непольный контейнер
        указывает на ЗАНЯТОЕ гнездо.
        """
        from konung2.gamefile import ground_items
        from konung2.kn2 import KN2Map, interior_slots
        проверено = 0
        for номер in (33, 19, 23):
            гнёзда = interior_slots(KN2Map.from_game(номер))
            self.assertTrue(гнёзда, f"на карте {номер} нет обстановки вовсе")
            for мир in range(6):
                for куча in ground_items(номер, мир):
                    if куча["on_floor"]:
                        continue
                    ключ = (куча["place"], куча["slot"])
                    self.assertIn(ключ, гнёзда,
                                  f"карта {номер}, мир {мир}: гнездо {ключ} пусто")
                    проверено += 1
        self.assertGreater(проверено, 0, "непольных контейнеров не нашлось")

    def test_buried_caches_are_read_from_the_sign(self) -> None:
        """Клады есть, и их много: знак поля +0x0F — признак «спрятана».

        Читать надо СЫРОЙ байт: сумма берётся по модулю только при обыске
        (VA 0x4115DE зовёт abs), а знак живёт в записи и решает видимость.
        Однажды я просканировал данные через `ground_items`, где модуль уже
        применён, и объявил механику мёртвой — ошибка ровно в этом.
        """
        import os
        import re
        import struct
        from konung2.gamefile import (GROUND_ITEMS_AT, GROUND_ITEMS_COUNT,
                                      GROUND_ITEMS_SIZE, GROUND_MONEY_AT,
                                      ground_items)
        from konung2.paths import GAME_DIR, game_file
        всего = спрятанных = не_на_полу = 0
        for мир in range(6):
            with open(game_file(f"GAME.{мир}"), "rb") as поток:
                data = поток.read()
            for номер in range(GROUND_ITEMS_COUNT):
                начало = GROUND_ITEMS_AT + номер * GROUND_ITEMS_SIZE
                запись = data[начало:начало + GROUND_ITEMS_SIZE]
                if запись[8] == 0:
                    continue
                всего += 1
                сумма = struct.unpack_from("<h", запись, GROUND_MONEY_AT)[0]
                if сумма < 0:
                    спрятанных += 1
                    место = struct.unpack_from("<i", запись, 6)[0] >> 24
                    if место != -1:
                        не_на_полу += 1
        self.assertEqual(всего, 2052)
        self.assertEqual(спрятанных, 570, "клады пропали из данных")
        self.assertEqual(не_на_полу, 0, "клад оказался внутри объекта")
        #: И разбор обязан отдавать этот признак наружу.
        куча = next(к for к in ground_items(19, 0) if к["buried"])
        self.assertGreater(куча["money"], 0, "сумма клада отдаётся по модулю")

    def test_the_builder_keeps_the_buried_flag(self) -> None:
        """Знак поля +0x0F должен доехать до пака, иначе тайники на виду."""
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        builder = (root / "knyaz2" / "content" / "builder.py").read_text(encoding="utf-8")
        self.assertIn('"buried": pile["buried"],', builder)

    def test_the_client_hides_buried_piles(self) -> None:
        """Спрятанная не рисуется, не ищется и не отдаётся без Лопаты."""
        loot = self.client("loot.js")
        self.assertIn("export function lootHidden", loot)
        self.assertIn("if (lootHidden(pile)) continue;", loot)
        self.assertIn("if (!hidden && lootHidden(pile)) continue;", loot)
        self.assertIn("if (entry.buried) pile.buried = true;", loot)
        #: Зеркало раскрывает все спрятанные кучи карты.
        self.assertIn("export function lootReveal", loot)
        combat = self.client("combat.js")
        self.assertIn("if (found && lootHidden(found) && !hasShovel()) return null;",
                      combat)
        self.assertIn("function hasShovel", combat)

    def test_hidden_container_count_stays_known(self) -> None:
        """Контейнеров ВНУТРИ объектов — 366; это отдельная от кладов вещь."""
        import os
        import re
        from konung2.gamefile import ground_items
        from konung2.paths import GAME_DIR
        карты = sorted(int(m.group(1)) for имя in os.listdir(GAME_DIR)
                       if (m := re.fullmatch(r"(\d+)\.KN2", имя, re.I)))
        внутри = 0
        for мир in range(6):
            for номер in карты:
                try:
                    записи = ground_items(номер, мир)
                except (OSError, ValueError, IndexError, KeyError):
                    continue
                внутри += sum(1 for к in записи if not к["on_floor"])
        self.assertEqual(внутри, 366)


class ConcentrationContractTest(unittest.TestCase):
    """Концентрация снадобья показывается, как её печатает движок.

    VA 0x4322A1: признак — ОТРИЦАТЕЛЬНАЯ ЦЕНА в записи класса (знаковое поле
    +0x12). При минусе к названию дописывается ``", концентрация %5.2f"`` из
    float +0x04 записи предмета, а цена не печатается вовсе — ветка кончается
    весом. Ниже порога добавляется ``", недостаточная концентрация"``
    (VA 0x432303 и 0x432324).

    Сам счёт концентрации уже был перенесён (craft.js, brewStrength), но
    нигде не показывался — отсюда и «в смесях не вижу концентрации».
    """

    def client(self, name: str) -> str:
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        return (root / "knyaz2" / "web" / "static" / name).read_text(encoding="utf-8")

    def test_only_the_brewed_potions_carry_a_negative_price(self) -> None:
        """Минус стоит ровно у восьми варимых снадобий, классы 85…92."""
        from konung2.items import read_items
        строки = read_items()
        минус = [номер for номер, вещь in enumerate(строки) if вещь.price < 0]
        self.assertEqual(минус, list(range(85, 93)))

    def test_identical_potions_sum_their_concentration(self) -> None:
        """Режим 2 таблицы рецептов — сложение, и он стоит у одинаковых пар."""
        from konung2.craft import BREW_SUM, recipes
        книга = recipes()
        одинаковые = [строка for строка in книга
                      if строка["target"] == строка["poured"]]
        self.assertTrue(одинаковые)
        for строка in одинаковые:
            self.assertEqual(строка["strength"], BREW_SUM, строка)
            #: Из пары одинаковых выходит она же.
            self.assertEqual(строка["result"], строка["target"], строка)

    def test_the_brew_constants_match_the_engine(self) -> None:
        """Шаг навыка 0.01 и потолок 15.0 — оба double в exe."""
        from konung2.craft import BREW_MAX, BREW_STEP
        self.assertAlmostEqual(BREW_STEP, 0.01)
        self.assertAlmostEqual(BREW_MAX, 15.0)

    def test_the_brewed_bottle_stays_where_it_lay(self) -> None:
        """Варка меняет КЛАСС на месте, а не переставляет вещь.

        Движок пишет байт класса прямо в запись предмета (VA 0x41B930:
        ``цель+3 = таблица[i][2]``), гнездо смешивания её не хранит — оно
        только помечает (VA 0x420890). Мы же подменяли ссылку в гнезде, а
        ячейку мешка оставляли со старой: после варки В ДРУГОЙ КЛАСС банка
        не бралась из гнезда и не клалась в мешок. Одинаковые зелья это
        переживали, потому что класс не менялся и ссылка оставалась той же.
        """
        carry = self.client("carry.js")
        self.assertIn("const at = whereIs(targetName, actor);", carry)
        self.assertIn("if (at?.from === \"bag\") actor.bag[at.index] = mixed.result;",
                      carry)
        self.assertIn("else if (at) actor.equipment[at.from] = mixed.result;", carry)

    def test_a_changed_class_leaves_an_empty_bottle(self) -> None:
        """У пар с разным классом остаток — пустая банка (класс 83)."""
        from konung2.craft import recipes
        разные = [строка for строка in recipes()
                  if строка["target"] != строка["poured"]
                  and строка["result"] != строка["target"]]
        self.assertTrue(разные)
        for строка in разные:
            self.assertIn(строка["left"], (None, 83), строка)

    def test_the_tooltip_shows_concentration_instead_of_price(self) -> None:
        ui = self.client("ui.js")
        self.assertIn("if (item.price < 0)", ui)
        self.assertIn("концентрация ${value.toFixed(2)}", ui)
        self.assertIn("недостаточная концентрация", ui)
        #: Пороги слабости — из движка, а не на глаз.
        self.assertIn("{ 87: 10.0, 92: 6.0, 93: 10.0 }", ui)


class MovementContractTest(unittest.TestCase):
    """Клетка длится «база блока минус скорость» тактов.

    Цепочка движка, снятая по байтам юнита:

        FUN_00416C84  — по битам +0x19 выбирает блок хода: 0x80 бег,
                        0x04 боевая стойка;
        FUN_00429B2C  — VA 0x429B3E кладёт ПОХОДКУ:
                        `юнит[0xFD] = DAT_0045FE90[блок] − юнит[0x1D]`;
        FUN_0041611C  — VA 0x41612B каждый такт `inc byte ptr [eax + 0xFB]`;
        FUN_00413894  — `if (юнит[0xFD] <= юнит[0xFB])` обнуляет +0xFB и
                        переводит юнита в следующую клетку.

    Число кадров блока (+0xFE) крутит спрайты и на скорость не влияет.
    Прежняя модель «клетка = кадры × такт» здесь и была закреплена — она
    давала бегу 702 мс вместо 156…312 и была неотличима от канонной ходьбы.

    Блоки хода подтверждены дизассемблером FUN_00416C84: пары 1/7 (боевая)
    и 17/19 (мирная) совпадают со STANCE_BLOCKS нашего пакета.
    """

    def client(self, name: str) -> str:
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        return (root / "knyaz2" / "web" / "static" / name).read_text(encoding="utf-8")

    def test_the_cell_lasts_the_block_base_minus_the_speed(self) -> None:
        hero = self.client("hero.js")
        self.assertIn("unitCellTicks(unit) * tickSeconds()", hero)
        self.assertIn("ticks - (world.unitSpeed?.(unit) ?? 0)", hero)

    def test_the_frame_count_no_longer_times_the_cell(self) -> None:
        """Снимаю свою же неверную модель: кадры больше не задают клетку."""
        hero = self.client("hero.js")
        self.assertNotIn("frames * tickSeconds()", hero)
        self.assertNotIn("heroFrames(unitMovePose(unit), direction)", hero)

    def test_the_invented_duration_model_is_gone(self) -> None:
        hero = self.client("hero.js")
        self.assertNotIn("export const SPEED_SCALE", hero)
        self.assertNotIn("export function heroStepFrames", hero)

    def test_the_block_bases_come_from_the_engine_table(self) -> None:
        """DAT_0045FE90: ходьба 10/11, бег 4/5 — мирный и боевой."""
        from konung2.heroes import move_block_ticks
        self.assertEqual(move_block_ticks(),
                         {"walk": 10, "run": 4,
                          "combat_walk": 11, "combat_run": 5})

    def test_the_gait_table_divides_the_cell_exactly(self) -> None:
        """Независимая проверка: шаг × походка = переход в соседнюю клетку.

        Таблицы 0x459AD4 (X) и 0x459D14 (Y) индексируются самой походкой
        (VA 0x416157: `shl eax, 5` по байту +0xFD). Если походка — это число
        тактов на клетку, то смещение подшага обязано быть «клетка/походка»;
        сверяем с таблицей соседних клеток DIRECTION_STEPS.
        """
        from konung2.heroes import DIRECTION_STEPS, gait_steps
        таблица = gait_steps()
        self.assertEqual(len(таблица), 18)
        for походка in range(1, 18):
            #: gait_steps округляет до трёх знаков, и умножение на походку
            #: разгоняет остаток — допуск берём по нему.
            допуск = 0.0005 * походка + 1e-9
            for направление, (шаг_x, шаг_y) in enumerate(таблица[походка]):
                клетка_x, клетка_y = DIRECTION_STEPS[направление]
                self.assertAlmostEqual(шаг_x * походка, клетка_x, delta=допуск)
                self.assertAlmostEqual(шаг_y * походка, клетка_y, delta=допуск)

    def test_a_new_order_retimes_the_step_at_once(self) -> None:
        """FUN_00416574 -> FUN_00416740: +0xFB = 0 и якорь на клетку юнита.

        Из-за этого двойной щелчок в оригинале даёт бег с первой же клетки,
        а не после того, как доиграет начатая клетка ходьбы.
        """
        hero = self.client("hero.js")
        self.assertIn("export function unitRetime", hero)
        self.assertIn("world.unitRetime = unitRetime", hero)
        #: Перетаймливается только удавшийся приказ — ветка «путь найден».
        self.assertIn("if (hero.path.length) unitRetime(hero);", hero)
        self.assertIn("world.unitRetime?.(unit)", self.client("orders.js"))

    def test_repeated_clicks_do_not_jump_the_unit(self) -> None:
        """Сброс — только при СМЕНЕ блока хода. Отступление от канона.

        В движке FUN_00416740 обнуляет +0xFB и переставляет якорь на каждый
        приказ, а раздача приказов FUN_004240BC шлёт его на каждый щелчок без
        всякой сверки с текущей целью; хвост той же функции у идущего юнита
        вдобавок сразу сдвигает +0x12/+0x14 в соседнюю клетку. Отсюда в
        оригинале спам щелчками гонит персонажа скачками.

        Берём условие, которое у движка стоит строкой выше — пересчёт походки
        сделан только при смене блока, — и распространяем на сброс.
        """
        hero = self.client("hero.js")
        self.assertIn("export function unitMoveBlock", hero)
        self.assertIn("if (unit.step.block === unitMoveBlock(unit)) return;", hero)
        #: Блок запоминается при начале шага, иначе сравнивать не с чем.
        self.assertIn("block: unitMoveBlock(unit),", hero)
        #: И длительность, и перетайминг берут блок из одного места.
        self.assertIn("const key = BLOCK_KEYS[unitMoveBlock(unit)];", hero)

    def test_a_repeated_click_keeps_the_run(self) -> None:
        """Спам щелчками держит БЕГ. Отступление от канона, намеренное.

        Браузер на пару щелчков шлёт `click, click, dblclick`, и одиночные
        гасят бег между двойными. В движке то же чередование: ветка 0x401
        функции FUN_0042F22C снимает бит `юнит[0x19] &= 0x7F`, а двойной
        щелчок 0x203 его ставит, — поэтому спам в оригинале держит ходьбу.
        """
        input_js = self.client("input.js")
        # Слагаемых в этой строке стало больше — добавилась настройка «всегда
        # бегом» (settings.js), — поэтому проверяем не всю строку целиком, а
        # что повтор приказа В ТУ ЖЕ КЛЕТКУ по-прежнему держит бег.
        строка = next((s for s in input_js.splitlines()
                       if s.strip().startswith("running = running ||")), "")
        self.assertTrue(строка, "нет строки, решающей бег на повторном щелчке")
        self.assertIn("Boolean(repeat && hero.running)", строка)
        self.assertIn("lastGoal.row === cell.row && lastGoal.col === cell.col", input_js)

    def test_the_move_blocks_agree_between_ticks_and_names(self) -> None:
        """BLOCK_KEYS клиента и MOVE_BLOCKS пака называют одни и те же блоки."""
        import re
        from konung2.heroes import MOVE_BLOCKS
        hero = self.client("hero.js")
        кусок = re.search(r"const BLOCK_KEYS = \{(.+?)\};", hero, re.S)
        self.assertIsNotNone(кусок)
        пары = dict(re.findall(r"(0x[0-9a-fA-F]+):\s*\"(\w+)\"", кусок.group(1)))
        self.assertEqual({int(k, 16): v for k, v in пары.items()},
                         {block: name for name, block in MOVE_BLOCKS.items()})

    def test_the_overloaded_unit_may_not_run(self) -> None:
        """VA 0x42F22C ставит бит бега только при ноше не свыше предела."""
        carry = self.client("carry.js")
        self.assertIn("export function unitCanRun", carry)
        self.assertIn("carriedWeight(unit) <= weightLimit(unit)", carry)
        self.assertIn("world.unitCanRun = unitCanRun", carry)
        for name in ("hero.js", "orders.js", "units.js"):
            self.assertIn("world.unitCanRun?.(", self.client(name), name)

    def test_the_canon_cell_times_in_milliseconds(self) -> None:
        """Пересчёт таблицы в миллисекунды при такте 78 мс.

        Скорость (+0x1D) зажата в 0…2 (FUN_0041B3B8), поэтому клетка ходьбы
        идёт 780…624 мс, а бега — 312…156 мс.
        """
        from konung2.heroes import move_block_ticks
        такт = 78
        база = move_block_ticks()
        ходьба = [(база["walk"] - s) * такт for s in (0, 1, 2)]
        бег = [(база["run"] - s) * такт for s in (0, 1, 2)]
        self.assertEqual(ходьба, [780, 702, 624])
        self.assertEqual(бег, [312, 234, 156])
        #: Бег быстрее ходьбы при любой скорости, и разрыв растёт.
        for шаг, бегом in zip(ходьба, бег):
            self.assertLess(бегом, шаг)
        self.assertAlmostEqual(ходьба[0] / бег[0], 2.5, places=2)
        self.assertAlmostEqual(ходьба[2] / бег[2], 4.0, places=2)

    def test_the_movement_blocks_match_the_engine(self) -> None:
        """FUN_00416C84: боевая 1/7, мирная 0x11/0x13 — шаг и бег."""
        from konung2.heroes import STANCE_BLOCKS
        self.assertEqual(STANCE_BLOCKS["combat"]["walk"], 1)
        self.assertEqual(STANCE_BLOCKS["combat"]["run"], 7)
        self.assertEqual(STANCE_BLOCKS["peace"]["walk"], 0x11)
        self.assertEqual(STANCE_BLOCKS["peace"]["run"], 0x13)

    def test_the_frame_equals_the_world_tick(self) -> None:
        """Кадр анимации и мировой такт — одно и то же число, 78 мс."""
        import json
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        общий = root / "content_build" / "shared.json"
        if not общий.is_file():
            self.skipTest("нет собранного пака")
        герой = json.loads(общий.read_text(encoding="utf-8"))["hero"]
        self.assertEqual(герой["tick_ms"], 78)
        self.assertAlmostEqual(герой["frame_seconds"], 0.078, places=3)


class ItemWeightSignContractTest(unittest.TestCase):
    """Вес предмета читается СО ЗНАКОМ (VA 0x41B218).

    Движок складывает ноши арифметическим сдвигом `*(int *)(...) >> 0x10`,
    то есть старшее слово знаковое. Беззнаковое чтение делало «Сына Луны»
    (класс 43) грузом в 55.5 кг вместо облегчения на 10: 55536 = 65536 − 10000.
    Бета-тестер заметил это как «+55 кг вместо минуса».

    Строкой выше в том же разборе цена уже читалась со знаком, с
    комментарием ровно про этот случай, — вес прошёл мимо.
    """

    @needs_game
    def test_the_moon_son_makes_you_lighter(self) -> None:
        from konung2.items import read_items
        вещи = {item.index: item for item in read_items()}
        self.assertEqual(вещи[43].name, "Сын Луны")
        self.assertEqual(вещи[43].weight, -10000)

    @needs_game
    def test_only_that_one_item_is_negative(self) -> None:
        """Знаковое чтение не поехало по остальной таблице."""
        from konung2.items import read_items
        отрицательные = [i.index for i in read_items() if i.weight < 0]
        self.assertEqual(отрицательные, [43])

    def test_the_pack_carries_the_negative_weight(self) -> None:
        import json
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        карта = root / "content_build" / "maps" / "33" / "map.json"
        if not карта.is_file():
            self.skipTest("нет собранного пака")
        предметы = json.loads(карта.read_text(encoding="utf-8"))["items"]
        запись = предметы.get("class:43")
        if not запись:
            self.skipTest("на этой карте класса 43 нет")
        self.assertEqual(запись["weight"], -10000)


class MeleeAdjacencyContractTest(unittest.TestCase):
    """Ближний бой меряется СОСЕДСТВОМ, а не расстоянием в клетках.

    Ошибка, которую не поймал ни один прежний тест и ни один замер: юниты,
    стоящие строго севернее или южнее цели, замирали навсегда и не дрались.
    Со стороны это выглядело как «некоторые враги застыли».

    Причина в сетке. Она изометрическая, ряды идут вполовину, и вертикальный
    сосед отстоит на ДВА ряда (таблица соседей движка 0x49CF68, смещения
    ±0x500). А мерка расстояния 0x43B670 меряет клетки и для такой пары
    честно возвращает двойку. Ближний бой стоял на этой мерке — `distance <=
    actorReach`, дальность руки единица, — поэтому 2 > 1, удара нет; шагнуть
    в клетку цели тоже нельзя, она занята. Тупик навсегда.

    Движок так не считает вовсе: ближнюю цель он берёт ПЕРЕБОРОМ ВОСЬМИ
    НАПРАВЛЕНИЙ (VA 0x4107EC зовёт 0x441344 на каждое), а дальность в
    клетках нужна ему только для стрельбы (VA 0x414AF8).
    """

    def client(self, name: str) -> str:
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        return (root / "knyaz2" / "web" / "static" / name).read_text(encoding="utf-8")

    @staticmethod
    def сосед(row: int, col: int, direction: int) -> tuple[int, int]:
        """Соседняя клетка по таблице движка — копия heroNeighbor."""
        odd = row & 1
        return {
            0: (row, col - 1),                      # запад
            4: (row, col + 1),                      # восток
            2: (row - 2, col),                      # север
            6: (row + 2, col),                      # юг
            1: (row - 1, col - (1 if odd else 0)),  # СЗ
            3: (row - 1, col + (0 if odd else 1)),  # СВ
            5: (row + 1, col + (0 if odd else 1)),  # ЮВ
            7: (row + 1, col - (1 if odd else 0)),  # ЮЗ
        }[direction]

    @staticmethod
    def мерка(a: tuple[int, int], b: tuple[int, int]) -> int:
        """Расстояние в клетках по VA 0x43B670 — копия cellRange."""
        rows = abs(a[0] - b[0])
        cols = abs(a[1] - b[1])
        if rows < cols:
            return cols + 1 if rows > 1 else cols
        return rows + 1 if cols > 1 else rows

    def test_vertical_neighbour_measures_two_cells(self) -> None:
        """Вот из-за чего всё сломалось: сосед, а мерка даёт двойку."""
        подводные = []
        for row in (10, 11):                      # чётный ряд и нечётный
            for direction in range(8):
                клетка = self.сосед(row, 27, direction)
                if self.мерка((row, 27), клетка) > 1:
                    подводные.append((row, direction, клетка))
        # север (2) и юг (6) — ровно те направления, где мерка врёт
        self.assertEqual([(d) for _, d, _ in подводные], [2, 6, 2, 6],
                         "ожидались ровно север и юг для обоих рядов")

    def test_melee_uses_adjacency_not_distance(self) -> None:
        """Ветка боя юнита спрашивает соседство, а не мерку."""
        units = self.client("units.js")
        self.assertIn("export function adjacentCell", units)
        self.assertIn("export function withinReach", units)
        начало = units.index("export function withinReach")
        тело = units[начало:units.index("\n}", начало)]
        self.assertIn("adjacentCell", тело,
                      "рукой достаём по соседству")
        self.assertIn("distance <= reach", тело,
                      "метательным — по дальности")
        # сама ветка боя
        self.assertIn("withinReach(unit, target, distance, actorReach(unit))", units)
        self.assertNotIn("distance <= actorReach(unit)", units,
                         "мерка расстояния для ближнего боя вернулась")

    def test_hero_melee_uses_adjacency_too(self) -> None:
        """Герой — такой же юнит: у него то же правило (VA 0x421690)."""
        combat = self.client("combat.js")
        self.assertIn("withinReach(hero, target, distance, reachOf(hero))", combat)
        self.assertNotIn("distance <= reachOf(hero)", combat,
                         "герой снова меряет ближний бой расстоянием")


class VillageMemoryContractTest(unittest.TestCase):
    """Запись поселения переживает уход с карты (VA 0x83D408).

    Массив поселений движок читает ОДИН РАЗ — при новой игре (0x43D898) или
    из сейва (0x4236E0) — и целиком пишет в сейв (0x423CB8). Вход на карту
    его не перезагружает: 0x43DF48 лишь находит запись своей карты и по ней
    переставляет картинки объектов (строки 222-231). У нас карта читается из
    пака при каждом входе, поэтому запись поселения обязана жить отдельно.
    """

    def client(self, name: str) -> str:
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        return (root / "knyaz2" / "web" / "static" / name).read_text(encoding="utf-8")

    def test_the_settlement_store_survives_map_changes(self) -> None:
        village = self.client("village.js")
        self.assertIn("const settlements = new Map()", village)
        for name in ("villageCapture", "villagePack", "villageUnpack",
                     "villageReset"):
            self.assertIn(f"export function {name}", village)
        # Возврат на свою карту берёт запись из склада и подменяет ею пак.
        self.assertIn("map.village = kept.data", village)

    def test_the_map_entry_captures_and_resets(self) -> None:
        app = self.client("app.js")
        # Уход с карты складывает хозяйство деревни.
        self.assertIn("villageCapture();", app)
        # Новая игра чистит склад, как 0x43D898 перечитывает блок из GAME.x.
        self.assertIn("villageReset();", app)

    def test_the_building_takes_its_stage_from_the_place(self) -> None:
        buildings = self.client("buildings.js")
        начало = buildings.index("export function buildingsSetup")
        конец = buildings.index("\n}", начало)
        тело = buildings[начало:конец]
        self.assertIn("world.map?.village?.buildings", тело)
        self.assertIn("row.slot === object.village_slot", тело)
        self.assertIn("object.state = place.state ?? 0", тело)

    def test_the_save_keeps_every_settlement(self) -> None:
        save = self.client("save.js")
        self.assertIn("villages: villagePack()", save)
        self.assertIn("villageUnpack(saved.villages)", save)

    def test_the_pack_carries_the_village_squad_reserve(self) -> None:
        """Запас мест отряда деревни: +0x1A против +0x1C записи отряда."""
        from konung2.gamefile import village
        for карта, запас, людей in ((33, 17, 14), (13, 24, 8), (19, 20, 9)):
            запись = village(карта)
            self.assertEqual((запись["squad_places"], запись["squad_people"]),
                             (запас, людей), f"карта {карта}")

    def test_a_loaded_save_reaches_villages_visited_later(self) -> None:
        """Сохранённая деревня накладывается при ПЕРВОМ входе после загрузки.

        Записи поселений приезжают из пака только при входе на карту, а сейв
        читается раньше — поэтому отложенное надо накладывать в villageSetup.
        """
        village = self.client("village.js")
        начало = village.index("export function villageSetup")
        конец = village.index("\n}", village.index("villageApply", начало))
        тело = village[начало:конец]
        self.assertIn("villageApply(number, entry)", тело)


class BuildPaceContractTest(unittest.TestCase):
    """Стройка идёт по МИРОВЫМ ТАКТАМ и по жителям деревни (VA 0x41C944).

    Тестер: «казарма строится мгновенно». Причин было две, обе замерены на
    живом движке: тик деревни считался по кадрам rAF (60…144 в секунду
    против 12.82 мировых тактов), а работники — по всем живым юнитам карты
    вместо бойцов отряда поселения.
    """

    def client(self, name: str) -> str:
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        return (root / "knyaz2" / "web" / "static" / name).read_text(encoding="utf-8")

    def test_the_tick_counts_world_ticks_not_frames(self) -> None:
        effects = self.client("effects.js")
        self.assertIn('import { clockPhaseHits } from "./clock.js"', effects)
        self.assertIn("clockPhaseHits(mask, BUILD_PHASE_SHIFT)", effects)
        self.assertNotIn("frames += 1", effects,
                         "стройка снова считает кадры вместо мировых тактов")

    def test_the_workers_are_the_village_squad(self) -> None:
        effects = self.client("effects.js")
        начало = effects.index("function workersOf")
        тело = effects[начало:effects.index("\n}", начало)]
        self.assertIn("unit.side === data.side", тело)
        self.assertIn("(unit.body ?? 0) < 6", тело)          # облик +0xFC
        self.assertIn("officials", тело)                      # минус должности
        self.assertNotIn("Math.max(1,", тело,
                         "нижней границы у движка нет: при нуле работа стоит")

    def test_the_kind_table_matches_the_exe(self) -> None:
        """Сроки видов в паке — это dword +0x08 записи 0x45D840."""
        import json, pathlib, struct
        from konung2.exetables import va_to_foff
        from konung2.paths import game_file
        root = pathlib.Path(__file__).resolve().parents[1]
        shared = json.loads((root / "content_build" / "shared.json")
                            .read_text(encoding="utf-8"))
        kinds = shared["hero"]["rules"]["buildings"].get("kinds", {})
        if not kinds:
            self.skipTest("пак не собран")
        blob = open(game_file("konung2.exe"), "rb").read()
        offset = va_to_foff(0x45D840)
        for number, row in kinds.items():
            at = offset + int(number) * 0x10
            эталон, = struct.unpack_from("<i", blob, at + 8)
            self.assertEqual(row.get("build_time"), эталон,
                             f"вид {number}: срок разошёлся с таблицей")


class BarracksTrainingContractTest(unittest.TestCase):
    """Обучение у воеводы (VA 0x4181E8) — то, чего не было в казарме.

    Спарринга в этой ветке нет вовсе. Раз в 0x4B0 тактов деревни движок идёт
    по бойцам её отряда и даёт каждому, чей уровень не выше уровня воеводы,
    сто опыта; дошедшему до порога — уровень, свободные очки и ДВЕ попытки
    роста: Выносливость, Сила, Ловкость и одиннадцать навыков. Условия:
    должность воеводы занята (слово +0x3D8, место 4) и в этот же такт стройка
    не сдвинулась (0x41C944:513).
    """

    def client(self, name: str) -> str:
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        return (root / "knyaz2" / "web" / "static" / name).read_text(encoding="utf-8")

    def test_the_numbers_come_from_the_engine(self) -> None:
        village = self.client("village.js")
        self.assertIn("const TRAIN_PERIOD = 0x4B0", village)
        self.assertIn("const TRAIN_XP = 100", village)
        self.assertIn("const TRAIN_ROUNDS = 2", village)
        self.assertIn("const TRAIN_SKILLS = 11", village)
        self.assertIn("const TRAIN_POST = 4", village)          # воевода
        self.assertIn("const TRAIN_CHARACTERISTICS = [5, 4, 1]", village)

    def test_the_teacher_gates_it(self) -> None:
        village = self.client("village.js")
        начало = village.index("export function villageTraining")
        тело = village[начало:village.index("\n}", начало)]
        self.assertIn("officials ?? [])[TRAIN_POST]", тело)
        # Ученик не выше учителя, и сам учитель не учится.
        учёба = village[village.index("function trainOnce"):]
        учёба = учёба[:учёба.index("\n}")]
        self.assertIn("(unit.level ?? 1) > ceiling", учёба)
        self.assertIn("unit === teacher", учёба)
        self.assertIn("unit.beast", учёба)

    def test_building_and_training_never_share_a_tick(self) -> None:
        effects = self.client("effects.js")
        self.assertIn("else if (villageTraining(1))", effects,
                      "обучение должно идти только в такт без сдвига стройки")


class WorkplaceChoiceContractTest(unittest.TestCase):
    """Выбор рабочего места жителем (VA 0x412C0C).

    Отсюда берутся приказы 7, 9 и 10 — в том числе девятка, на которой стоит
    спарринг у казармы. Три правила движка, которых не хватало: обычная работа
    (старшая половина вида ноль) годится всегда, дневные и ночные места
    делятся битом 0x10 В ОБРАТНУЮ сторону, а боевые места (вид от 0x70)
    открывает воевода.
    """

    def client(self, name: str) -> str:
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        return (root / "knyaz2" / "web" / "static" / name).read_text(encoding="utf-8")

    def test_the_rules_of_choice(self) -> None:
        units = self.client("units.js")
        начало = units.index("function pickWorkplace")
        тело = units[начало:units.index("\n}", начало)]
        # обычная работа мимо всех гейтов
        self.assertIn("(kind & 0xF0) === 0", тело)
        # полярность дня и ночи — прямая, как в движке
        self.assertIn("atNight === Boolean(kind & WORKPLACE_NIGHT_BIT)", тело)
        # боевые места под воеводой
        self.assertIn("WORKPLACE_COMBAT_FROM && !warlord", тело)
        # веса без выдуманного минимума
        self.assertNotIn("Math.max(1, place.weight)", тело)

    def test_the_numbers_match_the_python_side(self) -> None:
        from konung2.gamefile import (WORKPLACE_NIGHT_BIT, WORKPLACE_STRIDE,
                                      WORKPLACE_TABLE_AT, WORKPLACES_MAX)
        self.assertEqual((WORKPLACE_NIGHT_BIT, WORKPLACE_TABLE_AT,
                          WORKPLACE_STRIDE, WORKPLACES_MAX), (0x10, 0x20, 4, 8))
        units = self.client("units.js")
        self.assertIn("const WORKPLACE_NIGHT_BIT = 0x10", units)
        self.assertIn("const WORKPLACE_COMBAT_FROM = 0x70", units)

    def test_the_chosen_place_goes_first(self) -> None:
        """Движок переставляет выбранное место в начало списка (+0xE6)."""
        units = self.client("units.js")
        self.assertIn("unit.workplaces = [workplace.slot,", units)


class BeastPoseContractTest(unittest.TestCase):
    """Поза расстановки и счётчик породы (VA 0x410010, 0x413894:275).

    Скелеты, ичетики и кикиморы лежат в мире в ПОЗЕ 4 — из неё разбор занятия
    уводит их в проигрывание анимации, и только доиграв, они начинают
    действовать. У скелета в байте +0xEE лежит число подъёмов: при смерти он
    уменьшается, здоровье возвращается полным, поза снова 4.
    """

    def test_the_reader_exposes_both_fields(self) -> None:
        from konung2.gamefile import T_UNITS, unit_stats
        from konung2.paths import game_file
        blob = open(game_file("GAME.0"), "rb").read()
        нашли = {}
        for index in range(T_UNITS.count):
            at = T_UNITS.offset + index * T_UNITS.size
            record = blob[at:at + T_UNITS.size]
            if len(record) < T_UNITS.size:
                break
            breed = record[0x1A]
            if not (breed & 0x40) or (breed & 0x80):
                continue
            нашли.setdefault(breed & 0x7F, unit_stats(blob, index))
        # Скелет 0x4C: поза 4 и ненулевой счётчик подъёмов.
        скелет = нашли.get(0x4C)
        self.assertIsNotNone(скелет, "скелетов в GAME.0 не нашлось")
        self.assertEqual(скелет["pose"], 4)
        self.assertGreater(скелет["breed_counter"], 0)
        # Аспид 0x42 — обычная тварь: поза 0, счётчик пуст.
        аспид = нашли.get(0x42)
        self.assertEqual((аспид["pose"], аспид["breed_counter"]), (0, 0))

    def test_the_builder_carries_them(self) -> None:
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        builder = (root / "knyaz2" / "content" / "builder.py").read_text(encoding="utf-8")
        self.assertIn('"pose": unit.get("pose", 0)', builder)
        self.assertIn('"breed_counter": unit.get("breed_counter", 0)', builder)


class SkeletonRiseContractTest(unittest.TestCase):
    """Скелет встаёт снова (VA 0x413894:275).

    На кадре «всего − 2» предсмертной анимации: порода 0x4C и счётчик +0xEE
    не пуст — здоровье возвращается полным (0x640), приказ становится
    единицей, счётчик убавляется, поза снова 4, смерть отменяется. Поза 4 у
    твари — шестой блок анимации, которого выпечка раньше не вывозила вовсе.
    """

    def client(self, name: str) -> str:
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        return (root / "knyaz2" / "web" / "static" / name).read_text(encoding="utf-8")

    def test_the_pack_carries_the_rise_block(self) -> None:
        import pathlib, json
        root = pathlib.Path(__file__).resolve().parents[1]
        from knyaz2.content.builder import CREATURE_POSES
        self.assertEqual(CREATURE_POSES.get("rise"), 4)
        shared = root / "content_build" / "shared.json"
        if not shared.exists():
            self.skipTest("пак не собран")
        sets = (json.loads(shared.read_text(encoding="utf-8"))
                .get("creatures") or {}).get("sets") or {}
        есть = any("rise" in палитра
                   for облик in sets.values() for палитра in облик.values())
        self.assertTrue(есть, "в паке нет ни одной твари с позой подъёма")

    def test_the_client_rises_instead_of_dying(self) -> None:
        units = self.client("units.js")
        self.assertIn("const BREED_SKELETON = 0x4C", units)
        self.assertIn("const CREATURE_RISE_POSE = 4", units)
        начало = units.index("function skeletonRises")
        тело = units[начало:units.index("\n}", начало)]
        self.assertIn("BREED_SKELETON", тело)
        self.assertIn("breedCounter ?? 0) < 1", тело)
        # Подъём стоит ПЕРЕД веткой зверя, иначе труп замрёт раньше.
        self.assertLess(units.index("if (skeletonRises(unit))"),
                        units.index("} else if (isBeast(unit)) {"))


class KikimoraSpitContractTest(unittest.TestCase):
    """Бросок Кикиморы (VA 0x41BB10, ветка породы 0x53).

    Условие запуска — «порода 0x53 ИЛИ в руке что-то есть»: ей одной оружие
    не нужно. Снаряд собирается по своим правилам: отрава её собственная
    (+0xF6), точность — Ловкость как есть (+0xCD), дальность константой 0x28,
    а сила считается на FPU, которую Ghidra съела: снято дизассемблером
    0x41BC21-0x41BC3D — fild [+0xD0]; fmul 0.04; fild [+0x4E]; fmulp;
    fmul 0.0625; fistp.
    """

    def client(self, name: str) -> str:
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        return (root / "knyaz2" / "web" / "static" / name).read_text(encoding="utf-8")

    def test_the_constants_come_from_the_engine(self) -> None:
        combat = self.client("combat.js")
        self.assertIn("const BREED_KIKIMORA = 0x53", combat)
        self.assertIn("const KIKIMORA_RANGE = 0x28", combat)
        начало = combat.index("function kikimoraStrength")
        тело = combat[начало:combat.index("\n}", начало)]
        self.assertIn("0.04", тело)
        self.assertIn("0.0625", тело)
        self.assertIn("roundHalfEven", тело)

    def test_the_multipliers_are_really_in_the_exe(self) -> None:
        """0.04 и 0.0625 лежат в exe как double по 0x450114 и 0x45011C."""
        import struct
        from konung2.exetables import va_to_foff
        from konung2.paths import game_file
        blob = open(game_file("konung2.exe"), "rb").read()
        для = {0x450114: 0.04, 0x45011C: 0.0625}
        for va, ожидание in для.items():
            значение, = struct.unpack_from("<d", blob, va_to_foff(va))
            self.assertAlmostEqual(значение, ожидание, places=9)

    def test_she_needs_no_weapon(self) -> None:
        combat = self.client("combat.js")
        # Бросок стоит ДО проверки лука: ей оружие не нужно.
        self.assertLess(combat.index("if (kikimoraSpits(unit) && target)"),
                        combat.index("if (unit.rangedMode && unit.equipment?.ranged"))


class SpawnCollisionContractTest(unittest.TestCase):
    """Расстановка не ставит двоих на одну клетку (VA 0x415764).

    Движок ищет клетку, у которой младшие 12 бит нулевые, а в них лежит и
    непроходимость (0xFFF), и НОМЕР стоящего юнита плюс один — его пишет туда
    сама расстановка (0x433070, 0x4338B0). Значит занятая клетка не годится.
    Проверялась одна проходимость земли, и на одиннадцати картах твари
    вставали друг на друга, до четырёх на клетку.
    """

    def test_the_builder_tracks_taken_cells(self) -> None:
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        builder = (root / "knyaz2" / "content" / "builder.py").read_text(encoding="utf-8")
        self.assertIn("def _spawn_cell(world_model, resident: dict,", builder)
        self.assertIn("taken: set | None = None", builder)
        self.assertIn("_spawn_cell(world, resident, taken_cells)", builder)

    def test_no_two_units_share_a_cell(self) -> None:
        import collections, glob, io, json, os, pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        maps = sorted(glob.glob(str(root / "content_build" / "maps" / "*" / "map.json")))
        if not maps:
            self.skipTest("пак не собран")
        плохо = {}
        for path in maps:
            номер = os.path.basename(os.path.dirname(path))
            карта = json.loads(io.open(path, encoding="utf-8").read())
            счёт = collections.Counter()
            for unit in карта.get("units") or []:
                cell = unit.get("cell") or {}
                if cell.get("row") is None:
                    continue
                счёт[(cell["row"], cell["col"])] += 1
            лишние = sum(v - 1 for v in счёт.values() if v > 1)
            if лишние:
                плохо[номер] = лишние
        self.assertEqual(плохо, {}, f"юниты стоят друг на друге: {плохо}")


class PartyTransitionContractTest(unittest.TestCase):
    """Отряд уходит по переходу вместе с вожаком (VA 0x420900, 0x415238).

    Две вещи, и обе доказаны в декомпиляте:

    1. Переход пускает дальше не только вожака. Разбор дошедшего юнита зовёт
       его для КАЖДОГО, кто встал на клетку с битом 0x1000 (0x4115AC, ветка
       по умолчанию), а сам переход сверяет так (0x420900:11)::

           if (юнит == вожак ||
               (вожак[+0x13] == юнит[+0x12] && вожак[+0x15] == юнит[+0x14]))

       Вторая половина — про спутника, занявшего клетку, КУДА ШЁЛ вожак.

    2. Расстановка отряда вокруг вожака стоит в загрузчике карты БЕЗ условий:
       ``FUN_00415238(отряд_игрока, карта, 1)`` (0x43DF48:294). Гейт по клетке
       прибытия стоил отряда на картах без записи в таблице 0x460028.
    """

    def client(self, name: str) -> str:
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        return (root / "knyaz2" / "web" / "static" / name).read_text(encoding="utf-8")

    def test_a_companion_on_the_leaders_goal_opens_the_door(self) -> None:
        exits = self.client("exits.js")
        ветка = exits[exits.index("export function exitsTick"):]
        # Сверка идёт с ЦЕЛЬЮ вожака, а не с его клеткой (0x420900:11).
        self.assertIn("atGoal(mate, hero.orderRow, hero.orderCol)", ветка)
        # И только со своими.
        self.assertIn("mate?.ally", ветка)

    def test_the_door_opens_on_arrival_not_on_passing_through(self) -> None:
        """Разбор прибытия зовут ПОСЛЕ ШАГА и только с пустым буфером.

        ``FUN_004115AC`` весь стоит под двумя проверками — ``юнит[+0x00] == -1``
        (шагов больше нет) и ``+0x12 == +0x13 && +0x14 == +0x15`` (клетка равна
        клетке назначения), — а зовут его из хода: ``0x413894:217`` сдвигает
        буфер шагов и тут же спрашивает разбор. Значит переход бывает ровно на
        последнем шаге пути, а не на любом шаге через клетку выхода.
        """
        exits = self.client("exits.js")
        ветка = exits[exits.index("export function exitsTick"):]
        # Кромка «шёл → встал», а не «пиксели внутри прямоугольника».
        self.assertIn("arrivalOf(hero, heroWas)", ветка)
        self.assertIn("atGoal(hero, hero.orderRow, hero.orderCol)", ветка)
        # Приход на карту кромки не даёт: расстановка разбор не зовёт.
        setup = exits[exits.index("export function exitsSetup"):
                      exits.index("export function exitAt")]
        self.assertIn("heroWas = { walked: false, cell: null }", setup)
        self.assertIn("mateWas.clear()", setup)

    def test_the_party_regroups_on_every_entry(self) -> None:
        app = self.client("app.js")
        entry = app.index("if (entry) {")
        regroup = app.index("partyRegroup();", entry)
        # Вызов стоит ПОСЛЕ закрывающей скобки гейта `if (entry)`.
        закрытие = app.index("\n  }\n", entry)
        self.assertLess(закрытие, regroup,
                        "расстановка отряда не должна висеть под `if (entry)`")

    def test_the_arrival_ring_is_the_near_one(self) -> None:
        units = self.client("units.js")
        self.assertIn("const ARRIVAL_SLOTS = 6", units)
        self.assertIn("const ARRIVAL_TRIES = 8", units)
        начало = units.index("export function partyRegroup")
        конец = units.index("\n}", начало)
        ветка = units[начало:конец]
        # Сторона — ПРОТИВОПОЛОЖНАЯ взгляду вожака (0x415238:97-102).
        self.assertIn("facing < DIRECTIONS / 2", ветка)
        self.assertIn("facing + DIRECTIONS / 2", ветка)
        self.assertIn("facing - DIRECTIONS / 2", ветка)
        # Приказ гаснет общим сбросом — см. test_the_leader_loses_his_order_too.
        self.assertIn("arrivalReset(unit, spot)", ветка)
        # Таблица построения общая, а срез — свой.
        self.assertIn("slots: ARRIVAL_SLOTS", ветка)
        self.assertIn("options.slots ? all.slice(0, options.slots) : all", units)

    def test_the_leader_loses_his_order_too(self) -> None:
        """VA 0x415238:67 — вожаку гасят приказ той же маской, что и остальным.

        `юнит[+0x16] &= 0xF0` стоит ДВАЖДЫ: строка 67 для вожака и строка 133
        для прочих. Заодно клетка назначения приравнивается к клетке, где юнит
        встал (`+0x13 = +0x12`, `+0x15 = +0x14`), а буфер шагов обнуляется
        (`юнит[+0x00] = 0xFF`). Без этого приказ прошлой карты переезжает
        вместе с героем, и он с порога уходит к клетке, которой тут нет.
        """
        units = self.client("units.js")
        self.assertIn("function arrivalReset(unit, cell)", units)
        начало = units.index("function arrivalReset(unit, cell)")
        конец = units.index("export function partyRegroup", начало)
        сброс = units[начало:конец]
        for поле in ("unit.path = []", "unit.goal = null", "unit.goalTarget = null",
                     "unit.orderTarget = null",
                     "unit.orderByte = (unit.orderByte ?? 0) & 0xF0"):
            self.assertIn(поле, сброс)
        # Клетка назначения = клетка, где встали.
        self.assertIn("unit.orderRow = cell.row", сброс)
        self.assertIn("unit.orderCol = cell.col", сброс)
        # Вожак проходит через ТОТ ЖЕ сброс, и раньше отряда.
        тело = units[units.index("export function partyRegroup"):]
        self.assertIn("arrivalReset(hero, hero.cell)", тело)
        self.assertLess(тело.index("arrivalReset(hero, hero.cell)"),
                        тело.index("mates.forEach"))

    def test_the_fight_does_not_travel(self) -> None:
        """Ссылки боя — те же поля приказа движка, и гаснут они там же.

        В движке цель боя живёт в `+0x10` и младшей половине `+0x16`, которые
        расстановка отряда гасит всем. У порта они разнесены по модулям,
        поэтому сброс ссылок вынесен в одну функцию на оба места вызова.
        """
        combat = self.client("combat.js")
        app = self.client("app.js")
        self.assertIn("export function combatDropTargets", combat)
        # Вход на карту и выход на глобальную зовут ОДНУ функцию, а не копии.
        self.assertEqual(app.count("combatDropTargets()"), 2)
        self.assertNotIn("combat.pendingHit = null", app)
        self.assertLess(app.index("partyRegroup();"), app.index("combatDropTargets()"))


class ContainerFurnitureContractTest(unittest.TestCase):
    """Сундук — это гнездо обстановки, а не объект (docs/CONTAINERS_SPEC.md).

    Блок 0x3D384 карты: тридцать зон по шестнадцать гнёзд, гнездо 12 байт.
    Зона — номер записи объекта карты (VA 0x425AA8:29). Загрузчик вписывает
    номер кучи в старший байт гнезда по паре байтов самой кучи: `+0x09` зона
    и `+0x0A` гнездо (VA 0x43DF48:344-352). Щелчок по гнезду даёт приказ с
    ОТРИЦАТЕЛЬНОЙ целью (VA 0x421690:213), а открытие идёт по номеру, потому
    что поиск по клетке берёт только напольные — `FUN_004149F8` сверяет
    `+0x09 == 0xFF`.
    """

    def client(self, name: str) -> str:
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        return (root / "knyaz2" / "web" / "static" / name).read_text(encoding="utf-8")

    def test_the_builder_keeps_the_inside_piles(self) -> None:
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        builder = (root / "knyaz2" / "content" / "builder.py").read_text(encoding="utf-8")
        # Отбраковки непольных куч быть не должно.
        self.assertNotIn('if not pile["on_floor"]:', builder)
        # Пара (зона, гнездо) едет в пак.
        self.assertIn('"zone": int(pile["place"])', builder)
        self.assertIn('"nest": int(pile["slot"])', builder)
        # Проходимость спрашиваем только у напольной.
        self.assertIn('if pile["on_floor"] and not world.terrain.passable(cell)', builder)
        # Обстановка тоже.
        self.assertIn("for (zone, nest), slot_data in interior_slots(kn2).items()", builder)

    def test_the_pack_binds_every_container_to_a_nest(self) -> None:
        import glob, io, json, os, pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        maps = sorted(glob.glob(str(root / "content_build" / "maps" / "*" / "map.json")))
        if not maps:
            self.skipTest("пак не собран")
        гнёзд = сундуков = связанных = 0
        безкартинки = 0
        плохо = []
        for path in maps:
            карта = json.loads(io.open(path, encoding="utf-8").read())
            мебель = (карта.get("terrain") or {}).get("furniture") or []
            гнёзд += len(мебель)
            безкартинки += sum(1 for x in мебель if not x.get("frame"))
            пары = {(x["zone"], x["nest"]) for x in мебель}
            for мир, кучи in (карта.get("loot_by_world") or {}).items():
                for куча in кучи:
                    if куча.get("zone") is None:
                        continue
                    сундуков += 1
                    if (куча["zone"], куча["nest"]) in пары:
                        связанных += 1
                    else:
                        плохо.append((os.path.basename(os.path.dirname(path)),
                                      мир, куча["id"]))
        self.assertGreater(гнёзд, 0, "обстановка не попала в пак")
        self.assertGreater(сундуков, 0, "кучи в гнёздах не попали в пак")
        self.assertEqual(безкартинки, 0, "у гнезда нет картинки")
        self.assertEqual(плохо, [], f"сундук без гнезда: {плохо[:5]}")

    def test_the_client_draws_and_opens_them(self) -> None:
        # Рисуются в проходе нутра постройки, между полом и стенами.
        entities = self.client("entities.js")
        пол = entities.index("drawFrame(object, frames.main, brightMain)")
        мебель = entities.index("furnitureOf(object.record_slot)")
        стены = entities.index("if (frames.walls) drawFrame(object, frames.walls)")
        self.assertLess(пол, мебель)
        self.assertLess(мебель, стены)
        # Щелчок даёт приказ «обыскать» с КЛЕТКОЙ САМОЙ КУЧИ.
        combat = self.client("combat.js")
        начало = combat.index("const chest = furnitureAt(x, y);")
        конец = combat.index("const pile = lootNear(x, y);", начало)
        ветка = combat[начало:конец]
        self.assertIn("kinds.take", ветка)
        self.assertIn("chest.pile.cell.row, chest.pile.cell.col", ветка)
        # Ловится только гнездо С КУЧЕЙ — пустая лавка курсор не берёт.
        furniture = self.client("furniture.js")
        self.assertIn("if (!nest.pile || nest.pile.taken || !nest.frame) continue",
                      furniture)

    def test_a_nest_pile_never_lies_on_the_floor(self) -> None:
        """VA 0x43DF48:328 — бит клетки и экранную точку получают ТОЛЬКО напольные.

        Загрузчик карты считает экранную точку кучи и ставит её клетке бит
        0x2000 в ветке `+0x09 == 0xFF`; куче в гнезде он не даёт ни того ни
        другого. Обе дороги дальше идут через этот бит: отрисовка перебирает
        клетки с ним (VA 0x424514:137), а поиск по клетке `FUN_004149F8` сам
        сверяет `+0x09 == 0xFF`. Значит сундук не рисуется на полу и по клетке
        не находится — иначе его содержимое лежало бы рядом с ним мешком.
        """
        loot = self.client("loot.js")
        self.assertIn("export function lootInNest", loot)
        # Три потребителя: поиск под мышью, список внутри постройки, отрисовка.
        self.assertEqual(loot.count("lootInNest(pile)"), 4)
        combat = self.client("combat.js")
        начало = combat.index("function pileAtCell(row, col)")
        конец = combat.index("function hasShovel", начало)
        self.assertIn("!lootInNest(pile)", combat[начало:конец])

    def test_the_cursor_over_a_container_says_take(self) -> None:
        """VA 0x428B88:44-88 — порядок разбора курсора: куча, юнит, контейнер, клетка.

        Ветка контейнера безоговорочна: `local_28 = 5`, то есть тот же курсор
        «взять», что и у кучи на земле. Без неё разбор доходил до клетки, а
        клетка у сундука непроходима — он стоит у стены, — и выходил
        перечёркнутый курсор.
        """
        cursors = self.client("cursors.js")
        куча = cursors.index("if (lootNear(x, y)) return kind.take;")
        юнит = cursors.index("const unit = unitAt(x, y, true);")
        сундук = cursors.index("if (furnitureAt(x, y)) return kind.take;")
        клетка = cursors.index("const cell = heroCellAt(x, y);", сундук)
        self.assertLess(куча, юнит)
        self.assertLess(юнит, сундук)
        self.assertLess(сундук, клетка)


class UnknownPlaceContractTest(unittest.TestCase):
    """Имя показывается только у ИЗВЕСТНОГО места (VA 0x420E88, код 0x42).

    `FUN_00436908(номер)` делает две разные вещи: помечает место известным
    (`*(u8 *)(0x8442A0 + номер) = 1`) и снимает туман со значка (бит 0x40 в
    клетке, снятие 0x80). Подпись под курсором смотрит ПЕРВОЕ::

        if (*(char *)(место + 0x8442A0) == '\\0')  «Неизвестное место»
        else                                       имя из 0x4616D4[место]

    Порт знал только про туман и брал имя прямо из номера клетки — на карте
    писалось «Черный Бор» над местом, где игрок ни разу не был.
    """

    def client(self, name: str) -> str:
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        return (root / "knyaz2" / "web" / "static" / name).read_text(encoding="utf-8")

    def test_the_string_comes_from_the_engine(self) -> None:
        world = self.client("worldmap.js")
        self.assertIn('UNKNOWN_PLACE = "Неизвестное место"', world)

    def test_opening_a_place_makes_it_known(self) -> None:
        world = self.client("worldmap.js")
        начало = world.index("export function openLocation")
        конец = world.index("\n}", начало)
        self.assertIn("known.add(Number(location))", world[начало:конец])

    def test_one_owner_decides_the_name(self) -> None:
        """Подпись карты, наведение, вход и приход — все через одну функцию."""
        ui = self.client("ui.js")
        app = self.client("app.js")
        self.assertIn("return locationName(here);", ui)          # подпись карты
        self.assertIn("under && locationName(under)", ui)        # наведение
        self.assertIn("Входим: ${locationName(number)}", ui)     # вход
        self.assertIn("return locationName(number);", app)       # приход в клетку
        # Прежнего пути «имя прямо из номера» остаться не должно.
        self.assertNotIn("rules.names?.[here]", ui)
        self.assertNotIn("worldMap.rules.names?.[under]", ui)

    def test_knowledge_survives_the_save(self) -> None:
        save = self.client("save.js")
        self.assertIn("known: knownPack()", save)
        self.assertIn("knownUnpack(saved.worldMap.known)", save)
        # А новая игра забывает всё.
        app = self.client("app.js")
        self.assertIn("knownReset();", app)


class WhistleContractTest(unittest.TestCase):
    """Свисток разгоняет зверей (VA 0x436C48, случаи класса 31 и 38).

    Ветка целиком::

        отряд = FUN_0041ED18(отряд игрока)     # ±0x27 строк, ±0x10 столбцов
        если (отряд[+0x1F] & 0x80) == 0:
            для каждого бойца отряда:
                живой, поза не 3/0x0B/0x0C,
                ЗВЕРЬ (+0x1A бит 0x40), порода не 0x44, 0x52, 0x56
                -> цель = 0, байт приказа = 0x28

    Приказ 8 — бегство (VA 0x410A08, случай 8): бросок из четырёх сторон,
    уход на 0x34 строк вверх или вниз либо на 0x16 столбцов вбок, вдоль края
    ищется свободная клетка (0x1A шагов по строкам, 0x0B по столбцам). Не
    нашлось — приказ снимается. Три глухие породы: 0x44 Цветок-людоед (не
    ходит вовсе), 0x52 Дракон и 0x56.
    """

    def client(self, name: str) -> str:
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        return (root / "knyaz2" / "web" / "static" / name).read_text(encoding="utf-8")

    def test_the_numbers_come_from_the_engine(self) -> None:
        units = self.client("units.js")
        for имя, значение in (("WHISTLE_ROWS", "0x27"), ("WHISTLE_COLS", "0x10"),
                              ("FLEE_ROWS", "0x34"), ("FLEE_COLS", "0x16"),
                              ("FLEE_ROW_TRIES", "0x1A"), ("FLEE_COL_TRIES", "0x0B")):
            self.assertIn(f"const {имя} = {значение}", units)
        self.assertIn("FLEE_DEAF = new Set([0x44, 0x52, 0x56])", units)

    def test_only_beasts_run(self) -> None:
        units = self.client("units.js")
        начало = units.index("export function scareBeasts")
        конец = units.index("\n}", units.index("return scared;"))
        ветка = units[начало:конец]
        self.assertIn("unit.ally || unit.alive === false", ветка)
        self.assertIn("unit.beast && !(unit.breed & 0x40)", ветка)
        self.assertIn("FLEE_DEAF.has", ветка)
        self.assertIn("CORPSE_POSES.has", ветка)
        # Бежать некуда — приказ снимается, а не остаётся висеть.
        self.assertIn("if (!spot) { orderClear(unit); continue; }", ветка)
        # Байт приказа именно 0x28.
        self.assertIn("unit.orderByte = 0x28", ветка)

    def test_the_whistle_is_not_spent(self) -> None:
        """В ветке свистка нет `*param_3 = -1`, в отличие от зеркала."""
        carry = self.client("carry.js")
        начало = carry.index("set.whistle_class ?? 38")
        конец = carry.index("set.mirror_class ?? 35", начало)
        ветка = carry[начало:конец]
        self.assertNotIn("bagTake(", ветка)
        self.assertIn("world.scareBeasts?.()", ветка)


class EquipmentSheetContractTest(unittest.TestCase):
    """Лист слоя снаряжения заказывается так же, как лист тела.

    Листы тянутся по требованию, и заказывает их РОВНО ОДНО место —
    `spriteReady` в viewport.js; там об этом и написано «в единственном месте,
    где спрашивают „картинка готова?“». Слои снаряжения шли мимо неё, прямо в
    `drawSprite`, а тот на отсутствующей картинке молча возвращает false и ни
    о чём не просит — поэтому оружие и щиты, чьи листы не попали в
    предзагрузку карты, не появлялись никогда.
    """

    def client(self, name: str) -> str:
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        return (root / "knyaz2" / "web" / "static" / name).read_text(encoding="utf-8")

    def test_the_layer_asks_for_its_sheet(self) -> None:
        actor = self.client("actor.js")
        начало = actor.index("export function drawLayerFrame")
        конец = actor.index("export function drawActor", начало)
        ветка = actor[начало:конец]
        self.assertIn("spriteReady(world.images, set, frame)", ветка)
        # Запрос идёт ДО отрисовки, иначе первый кадр опять пропадёт.
        self.assertLess(ветка.index("spriteReady("), ветка.index("drawSprite("))

    def test_only_sprite_ready_orders_sheets(self) -> None:
        """Заказчик листа один — если появится второй, они разъедутся."""
        viewport = self.client("viewport.js")
        self.assertEqual(viewport.count("world.requestAsset?.("), 2)
        начало = viewport.index("export function spriteReady")
        конец = viewport.index("export const band", начало)
        # Оба вызова — внутри spriteReady: для кадра с листа и для кадра-файла.
        self.assertEqual(viewport[начало:конец].count("world.requestAsset?.("), 2)


class InsideDepthContractTest(unittest.TestCase):
    """Внутри постройки юниты идут ПО ГЛУБИНЕ (VA 0x424514:28-66).

    Проход содержимого не рисует их подряд: он раскладывает юнитов по таблице
    строк (`0x84F53C`, 2000 записей по 16 байт, переполнение в `0x85723C`) и
    ключом берёт НИЗ СПРАЙТА — экранный Y плюс высота холста
    (`local_14 + юнит[+0x54]`), — а потом идёт по строкам сверху вниз. Ключ
    тот же, что у общего прохода сцены: у человека холст 256 на 150 с якорем
    ног (127, 144), то есть ноги плюс шесть.

    В порте герой рисовался ПЕРВЫМ, а жители за ним в порядке списка — любой
    стоящий в доме житель закрывал героя собой, даже стоящий дальше.
    """

    def client(self, name: str) -> str:
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        return (root / "knyaz2" / "web" / "static" / name).read_text(encoding="utf-8")

    def test_the_hero_is_not_drawn_first_unconditionally(self) -> None:
        entities = self.client("entities.js")
        начало = entities.index("const inside = [];")
        конец = entities.index("if (frames.walls) drawFrame", начало)
        ветка = entities[начало:конец]
        # Сортировка есть, и герой в общем списке.
        self.assertIn("inside.sort(", ветка)
        self.assertIn("entry.player) drawHeroAtDepth()", ветка)
        # Прежнего безусловного порядка быть не должно.
        self.assertNotIn("if (heroInside) drawHeroAtDepth();", ветка)
        # Ключ — тот же, что у сцены.
        self.assertIn("UNIT_SORT_BIAS", ветка)

    def test_the_sort_bias_has_one_owner(self) -> None:
        actor = self.client("actor.js")
        self.assertIn("export const UNIT_SORT_BIAS = 6", actor)
        # Ни в сцене, ни в объектах числа больше нет.
        for name in ("scene.js", "entities.js"):
            текст = self.client(name)
            self.assertNotIn("Math.round(hero.y) + 6", текст)
            self.assertNotIn("Math.round(unit.y) + 6", текст)
            self.assertIn("UNIT_SORT_BIAS", текст)


class ShopCounterOwnerContractTest(unittest.TestCase):
    """Прилавок принадлежит ПОСЕЛЕНИЮ, а не торговцу (VA 0x41896C).

    Генератор берёт аргументом запись поселения: загрузчик карты находит её
    перебором `0x83D408` по номеру карты и зовёт `FUN_0041896C(запись)`
    (0x43DF48:210-232). Места прилавка — поля этой записи (`+0x3E0`, `+0x40E`,
    `+0x44E`), а запись живёт весь сеанс и целиком уезжает в сохранение.

    Наполняются ТОЛЬКО ПУСТЫЕ места: в каждом условии генератора стоит
    сравнение слота с нулём (`*(short *)(... + 0x3e0) == 0` и
    `*(short *)(... + 0x40e) == 0`). Поэтому купленное не возвращается, а
    товар копится между заходами.
    """

    def client(self, name: str) -> str:
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        return (root / "knyaz2" / "web" / "static" / name).read_text(encoding="utf-8")

    def test_the_counter_lives_in_the_settlement(self) -> None:
        shops = self.client("shops.js")
        self.assertIn("function counterBox(unit, role)", shops)
        начало = shops.index("function counterBox(unit, role)")
        конец = shops.index("function place(unit, box", начало)
        ветка = shops[начало:конец]
        self.assertIn("world.map?.village", ветка)
        self.assertIn("village.counters", ветка)
        # Торговцу отдаётся ССЫЛКА на список мест, а не копия.
        self.assertIn("unit.counter = box.slots", ветка)

    def test_only_empty_slots_are_filled(self) -> None:
        shops = self.client("shops.js")
        self.assertIn("if (!left || box.slots[slot]) continue;", shops)
        self.assertIn("if (box.slots[slot]) continue;", shops)

    def test_the_counter_rides_in_the_save(self) -> None:
        village = self.client("village.js")
        self.assertIn("counters: kept.data?.counters", village)
        # Наложение сохранённого НЕ подменяет объект: ссылка у торговца.
        начало = village.index("for (const [role, box] of Object.entries(saved.counters ?? {}))")
        конец = village.index("for (const place of saved.places", начало)
        ветка = village[начало:конец]
        self.assertIn("live.slots.length = 0", ветка)
        self.assertIn("live.slots.push(", ветка)
        self.assertNotIn("data.counters = JSON.parse", ветка)

    def test_the_settlements_are_unpacked_before_the_first_map(self) -> None:
        app = self.client("app.js")
        boot = app[app.index("async function boot()"):]
        рано = boot.index("if (Array.isArray(saved?.villages)) villageUnpack(saved.villages);")
        карта = boot.index("const map = await readJson(contentUrl(path));")
        self.assertLess(рано, карта)


class MapResidentsContractTest(unittest.TestCase):
    """Оставленный в деревне спутник переживает уход с карты (VA 0x43A628).

    В движке памяти карты нет вовсе: запись юнита лежит в общем массиве
    `0x7B3C08` и никуда не девается. Свёртка карты `FUN_0043A628` проходит по
    отрядам этой карты и удаляет из массива ТОЛЬКО мёртвых (`+0x1A & 0x80`) —
    высыпает их вещи на землю, добавляет деньги в кучу под ними, вычёркивает
    из пятёрки должностей поселения и сдвигает хвост отряда на `0x100`. Живых
    она не трогает, поэтому бывший спутник, которому обработчик 43 переписал
    сторону, просто остаётся лежать в массиве.

    Порт пересоздаёт юнитов карты из пака при каждом входе, а пак про бывшего
    спутника не знает ничего — отсюда и «оставленный воеводой спутник пропал».
    """

    def client(self, name: str) -> str:
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        return (root / "knyaz2" / "web" / "static" / name).read_text(encoding="utf-8")

    def test_the_memory_keeps_joined_units(self) -> None:
        state = self.client("mapstate.js")
        self.assertIn("export function mapStateJoin", state)
        self.assertIn("export function mapStateJoined", state)
        # Запись, по которой поднимать, и то, чем юнит отличается от исходного.
        начало = state.index("function packJoined")
        конец = state.index("export function mapStateJoin")
        for поле in ("slot:", "member:", "side:", "ally:", "cell:", "orderByte:"):
            self.assertIn(поле, state[начало:конец])
        # Едет в сохранение и обратно.
        self.assertIn("joined: entry.joined ? entry.joined.map(packJoined) : null", state)
        self.assertIn("joined: Array.isArray(entry.joined)", state)

    def test_the_roster_yields_to_the_memory(self) -> None:
        units = self.client("units.js")
        начало = units.index("const joined = mapStateJoined(")
        конец = units.index("for (const unit of units) unitUpdateBuilding(unit);", начало)
        ветка = units[начало:конец]
        # Пачного поднимаем как обычно, память лишь правит ему поля.
        self.assertIn("applyJoined(units[units.length - 1], remembered)", ветка)
        self.assertIn("joined.delete(slot)", ветка)
        # Кого в паке нет — поднимаем из его записи отряда.
        self.assertIn("spawnCompanion(remembered.member, map, extra)", ветка)
        # Мёртвого не поднимаем ни тем, ни другим путём.
        self.assertIn("fallen.has(remembered.slot)", ветка)

    def test_the_handler_records_the_join(self) -> None:
        dialog = self.client("dialog.js")
        начало = dialog.index("  43: (argument) =>")
        конец = dialog.index("  44:", начало)
        ветка = dialog[начало:конец]
        self.assertIn("mapStateJoin(world.map?.legacy?.map_number, unit, member)", ветка)
        # Запись отряда снимается ДО вычёркивания из него.
        self.assertLess(ветка.index("hero.party?.members ?? []"),
                        ветка.index("partyRelease(unit)"))

    def test_the_memory_is_unpacked_before_the_first_map(self) -> None:
        """Иначе стартовая карта собирается на пустой памяти."""
        app = self.client("app.js")
        #: Строка чтения карты есть и в `enterMapInner`, поэтому ищем внутри
        #: самого `boot` — иначе сравнение попадёт на первую попавшуюся.
        boot = app[app.index("async function boot()"):]
        рано = boot.index("if (Array.isArray(saved?.mapState)) mapStateUnpack(saved.mapState);")
        карта = boot.index("const map = await readJson(contentUrl(path));")
        self.assertLess(рано, карта)


class PileOnArrivalContractTest(unittest.TestCase):
    """Куча открывается только по прибытии (VA 0x4115AC:22).

    Весь разбор приказа в движке стоит под одной проверкой::

        if (юнит[+0x12] == юнит[+0x13] && юнит[+0x14] == юнит[+0x15])

    то есть клетка юнита совпала с клеткой назначения. Не совпала — идёт не
    разбор, а перестройка пути (0x416574), и её провал СНИМАЕТ приказ
    (``if (путь == 0) FUN_00416E24(юнит)``). Гейт «юнит не идёт» этого не
    заменяет: путь к клетке кучи может не построиться вовсе.
    """

    def client(self, name: str) -> str:
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        return (root / "knyaz2" / "web" / "static" / name).read_text(encoding="utf-8")

    def test_the_take_order_needs_the_target_cell(self) -> None:
        orders = self.client("orders.js")
        начало = orders.index("if (kind === kinds.take)")
        конец = orders.index("if (kind === kinds.go)", начало)
        ветка = orders[начало:конец]
        self.assertIn("unit.cell.row !== row || unit.cell.col !== col", ветка)
        # Не дошёл — приказ снимается, а обработчик НЕ зовётся.
        self.assertLess(ветка.index("orderClear(unit);\n      return null;"),
                        ветка.index("handlers.take?."))

    def test_the_hero_parses_the_order_on_an_empty_path(self) -> None:
        combat = self.client("combat.js")
        self.assertIn("if (hero.orderKind && !hero.moving && !hero.path?.length)",
                      combat)

    def test_a_blocked_goal_cell_ends_the_walk(self) -> None:
        """VA 0x415090 — шаг в занятую клетку цели снимает НЕ боевой приказ.

        Планировщик клетку цели принимает: ему передают того, кто её занял
        (0x441441 сверяет её с полем `+0x10`). А шаг в неё отдельный разбор
        отвергает и для не боевого приказа возвращает ноль — юнит встаёт
        рядом, откуда разговор уже достаёт (мерка 7 на 4, 0x4115AC).
        У нас путь в один шаг иначе строится заново каждый кадр.
        """
        hero = self.client("hero.js")
        начало = hero.index("if (unitTryStep(unit, direction,")
        конец = hero.index("// кусок кончился", начало)
        ветка = hero[начало:конец]
        self.assertIn("unit.goalTarget.cell?.row === next.row", ветка)
        self.assertIn("unit.goalTarget.cell?.col === next.col", ветка)
        # Ветка стоит ДО перестройки пути, иначе круг не разрывается.
        self.assertLess(ветка.index("unit.goalTarget.cell?.row"),
                        ветка.index("unit.path = heroPlanPath("))

    def test_the_walk_targets_the_pile_cell(self) -> None:
        combat = self.client("combat.js")
        начало = combat.index("const pile = lootNear(x, y);")
        конец = combat.index("// ПУСТАЯ КЛЕТКА", начало)
        ветка = combat[начало:конец]
        self.assertIn("heroAnchor(pile.cell.row, pile.cell.col)", ветка)
        self.assertNotIn("heroOrderTo(pile.x, pile.y", ветка,
                         "путь строится к КЛЕТКЕ приказа, а не к пикселям кучи")
