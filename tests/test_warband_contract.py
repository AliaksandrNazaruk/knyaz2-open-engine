# -*- coding: utf-8 -*-
"""Вражда отрядов: сверка с числами из konung2.exe и GAME.0.

Всё, что здесь проверяется, снято с четырёх функций движка:

    VA 0x415B20  проход по отряду: кого он видит в своей зоне
    VA 0x4159DC  объявление боя: маска 0x4F, враг в +0x06, флаг в +0x1D
    VA 0x410784  бой держится: 840 пикселей по КАЖДОЙ оси
    VA 0x416A00  смерть: у человека жребий из трёх, у твари всегда одна
"""
import struct
import unittest

from konung2 import creatures
from konung2.gamefile import (PARTY_IS_PLAYER, WAR_ANY, WAR_KEEP_RANGE,
                              WAR_ON_PARTIES, WAR_ON_PLAYER,
                              WAR_ONLY_IF_FIGHTING, map_parties)


class WarbandFlags(unittest.TestCase):
    def test_bit_values_come_from_the_code(self) -> None:
        # Разбор веток VA 0x415B20 и маска из VA 0x4159DC.
        self.assertEqual(PARTY_IS_PLAYER, 0x01)
        self.assertEqual(WAR_ON_PLAYER, 0x01)
        self.assertEqual(WAR_ON_PARTIES, 0x04)
        self.assertEqual(WAR_ONLY_IF_FIGHTING, 0x08)
        self.assertEqual(WAR_ANY, 0x4F)
        # VA 0x410784 сравнивает обе оси с одним и тем же числом.
        self.assertEqual(WAR_KEEP_RANGE, 840)

    def test_there_is_exactly_one_player_party(self) -> None:
        """Бит 0x01 в +0x1E — признак отряда игрока, и он единственный."""
        players = []
        for number in range(64):
            for party in map_parties(number):
                if party["player"]:
                    players.append((number, party["side"]))
        self.assertEqual(len(players), 1, f"отрядов игрока: {players}")
        self.assertEqual(players[0][1], 0, "отряд игрока — нулевой")


class WarbandData(unittest.TestCase):
    def test_black_bor_village_is_peaceful(self) -> None:
        """У деревни нет ни одного бита нападения — жители не бросаются."""
        parties = map_parties(19)
        self.assertTrue(parties, "на карте 19 должен быть хоть один отряд")
        for party in parties:
            self.assertFalse(party["on_player"], f"сторона {party['side']}")
            self.assertFalse(party["on_parties"], f"сторона {party['side']}")

    def test_volhv_map_has_packs_hunting_the_player(self) -> None:
        """Доп локация: звериные стаи с битом «нападать на игрока»."""
        parties = map_parties(34)
        hunters = [p for p in parties if p["on_player"]]
        self.assertGreaterEqual(len(hunters), 3, "стай, идущих на игрока")
        for party in hunters:
            zone = party["zone"]
            self.assertGreaterEqual(zone["row_to"], zone["row_from"])
            self.assertGreaterEqual(zone["col_to"], zone["col_from"])
            self.assertGreater(party["count"], 0)

    def test_aggression_zone_is_the_spawn_zone(self) -> None:
        """VA 0x415B20 читает те же +0x0C/+0x10/+0x14/+0x16, что и 0x415764."""
        for party in map_parties(34):
            zone = party["zone"]
            self.assertIn("row_from", zone)
            self.assertIn("col_to", zone)

    def test_nobody_is_fighting_in_the_starting_world(self) -> None:
        """В GAME.0 никто ещё не воюет: +0x1D у всех ноль."""
        for number in (19, 34, 20, 23):
            for party in map_parties(number):
                self.assertFalse(party["fighting"],
                                 f"карта {number}, сторона {party['side']}")


class BeastDeath(unittest.TestCase):
    def test_beasts_have_no_corpse_blocks(self) -> None:
        """Таблица анимаций твари — шесть блоков, а труп у людей 13…15.

        Отсюда и правило порта: труп твари это удержанный последний кадр
        её единственной смерти (блок 3, VA 0x416A00).
        """
        self.assertEqual(creatures.ANIMATION_BLOCKS, 6)

    def test_people_have_three_deaths_and_three_corpses(self) -> None:
        from konung2.heroes import ACTION_BLOCKS, DEATH_VARIANTS
        self.assertEqual(DEATH_VARIANTS, 3)
        self.assertEqual(ACTION_BLOCKS["death_1"], 3)
        self.assertEqual(ACTION_BLOCKS["death_2"], 11)
        self.assertEqual(ACTION_BLOCKS["death_3"], 12)
        self.assertEqual(ACTION_BLOCKS["corpse_1"], 13)
        self.assertEqual(ACTION_BLOCKS["corpse_2"], 14)
        self.assertEqual(ACTION_BLOCKS["corpse_3"], 15)


class BeastShadow(unittest.TestCase):
    """Тень твари — маска спанов, а не спрайт.

    Раньше её гоняли через распаковщик пикселей, и она почти всегда выходила
    пустой: твари ходили без теней, хотя в ресурсе тень есть почти у каждого
    кадра. Пропуски бывают, но они ЯВНЫЕ — в дескрипторе стоит −1.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.res = creatures.CreatureRes.from_game()

    def test_no_shadow_is_always_an_explicit_minus_one(self) -> None:
        """Тень пропадает только по пометке в ресурсе, не по сбою разбора."""
        broken = []
        for body in range(30):
            try:
                block = self.res.entry(body)
            except (ValueError, IndexError, struct.error):
                continue
            for number in range(creatures.DESCRIPTOR_COUNT):
                at = creatures.DESCRIPTORS_AT + number * creatures.DESCRIPTOR_STRIDE
                if at + creatures.DESCRIPTOR_STRIDE > len(block):
                    break
                shadow_off, record_off = struct.unpack_from("<2i", block, at)
                if shadow_off == 0 and record_off == 0 and number:
                    break
                if shadow_off == creatures.NO_SHADOW:
                    continue
                if self.res._sprite_span(block, creatures.BLOCK_SIZE + shadow_off) is None:
                    broken.append((body, number))
        self.assertEqual(broken, [], "тени, которые не удалось разобрать")

    def test_declared_shadows_decode_and_are_not_empty(self) -> None:
        for body in (1, 8, 10, 16):
            frames = self.res.frames(body)
            declared = [f for f in frames if f["shadow_at"] is not None]
            self.assertGreater(len(declared), len(frames) * 0.8,
                               f"тело {body}: тень должна быть почти у всех кадров")
            for frame in declared[:24]:
                mask, dx, dy = self.res.decode(body, frame["index"], shadow=True)
                self.assertIsNotNone(mask, f"тело {body}, кадр {frame['index']}")
                opaque = sum(1 for pixel in mask.pixels if pixel[3])
                self.assertGreater(opaque, 0,
                                   f"тело {body}, кадр {frame['index']}: тень пустая")

    def test_shadow_lies_below_the_body(self) -> None:
        """Тень ложится под ноги: её смещение по Y ближе к нулю, чем у тела."""
        for body in (1, 10):
            mask, sdx, sdy = self.res.decode(body, 0, shadow=True)
            sprite, dx, dy = self.res.decode(body, 0)
            self.assertIsNotNone(mask)
            self.assertIsNotNone(sprite)
            self.assertGreater(sdy, dy, f"тело {body}: тень должна быть ниже")


class PlayerCommandBit(unittest.TestCase):
    """Бит «этим юнитом распоряжается игрок» — unit+0x19 & 0x40.

    Разобрано по пяти функциям:

        VA 0x4111E8  рассудок: ВСЯ ветка под `(unit[0x19] & 0x40) == 0`
        VA 0x410A08  случай 1: со стоящим битом — только сосед (0x4107EC),
                     а к дальней цели не идут, приказ снимается (0x416E24)
        VA 0x4240BC  щелчок по земле: цель в ноль и `+0x19 |= 0x40`
        VA 0x420BFC  «Все ко мне»: война снята, у спутников `+0x19 &= 0xBF`
        VA 0x416E24  завершение приказа: пишет ТОЛЬКО +0x10 и +0x16

    Из последней и растёт всё правило: раз завершение приказа байта
    состояния не касается, рука игрока лежит на герое и ПОСЛЕ того, как он
    дошёл. Иначе каждый дошедший герой возвращался под рассудок, тот брал
    ближайшего врага и гнал героя на него — «агро висит, гг сам бежит».
    """

    def client(self, name: str) -> str:
        from pathlib import Path
        return (Path("knyaz2/web/static") / name).read_text(encoding="utf-8")

    def test_order_clear_does_not_touch_the_state_byte(self) -> None:
        source = self.client("orders.js")
        body = source.split("export function orderClear(unit) {")[1]
        body = body.split("}")[0]
        # 0x416E24 пишет цель, вид приказа и сам байт приказа — и ничего больше
        self.assertIn("unit.orderTarget = null", body)
        self.assertIn("0xB0", body)
        # …а «занят» живёт в ДРУГОМ байте, и маска 0xB0 до него не достаёт
        self.assertNotIn("busy", body)

    def test_only_the_players_own_units_get_the_bit(self) -> None:
        source = self.client("orders.js")
        # Оба движковых места ставят бит по списку выбранных игроком
        # (0x840B94); деревенскому наряду по хозяйству он не достаётся.
        self.assertIn("unit === fallbackUnit", source)
        self.assertIn("if (ofPlayer) unit.busy =", source)

    def test_the_bit_locks_both_choosing_and_chasing(self) -> None:
        source = self.client("units.js")
        # выбор цели: со стоящим битом — только сосед 0x4107EC
        self.assertIn("unit.busy ? adjacentFoe(unit) : enemyOf(unit)", source)
        # …и погоня заперта тем же битом, причём цель ОТБРАСЫВАЕТСЯ
        self.assertIn("} else if (sees && unit.busy) {", source)
        chase = source.split("} else if (sees && unit.busy) {")[1]
        chase = chase.split("} else if (sees) {")[0]
        self.assertIn("orderClear(unit)", chase)
        self.assertIn("unit.target = null", chase)
        # Держать цель нельзя: отряд игрока выходит из боя только когда вида
        # приказа 1 нет ни у кого — иначе война не кончилась бы никогда.
        self.assertNotIn("combatOrder(unit, target)", chase)

    def test_the_rally_button_releases_the_party(self) -> None:
        source = self.client("ui.js")
        # 0x420BFC: третья строка тела гасит войну, а в цикле по спутникам
        # стоит `+0x19 &= 0xBF`
        call = source.split("call_party: {")[1].split("},")[0]
        self.assertIn("ours.fighting = false", call)
        self.assertIn("mate.busy = false", call)

    def test_a_quarrel_in_talk_releases_the_hero(self) -> None:
        source = self.client("warband.js")
        # 0x4333A4 пишет герою цель 0, приказ 0x21 и снимает бит
        alarm = source.split("export function warbandAlarm(")[1]
        alarm = alarm.split("export function")[0]
        self.assertIn("attacker.busy = false", alarm)



if __name__ == "__main__":
    unittest.main()
