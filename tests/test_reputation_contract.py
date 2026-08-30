# -*- coding: utf-8 -*-
"""Репутация «Продолжения легенды»: числа из exe и правило из движка.

Механики этой в каноне НЕТ ВОВСЕ — строка «Репутация» есть только в exe
донора. Разбор лежит в `konung2/reputation.py` и `docs/DONOR_REPUTATION.md`.

Тест сторожит три вещи:

* числа читаются из exe, а не подобраны руками (цены и стартовые);
* пак их несёт — иначе клиент молча останется с пустой таблицей;
* САМО ПРАВИЛО делает то же, что VA 0x00418554, — и проверяется оно
  прогоном настоящего `reputation.js` в node, а не пересказом его логики
  на Python. Пересказ доказывал бы только то, что я дважды написал одно
  и то же.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import unittest

КОРЕНЬ = pathlib.Path(__file__).resolve().parents[1]
СТАТИКА = КОРЕНЬ / "knyaz2" / "web" / "static"


class ReputationTablesTest(unittest.TestCase):
    """Числа приходят из exe донора."""

    def setUp(self) -> None:
        from konung2 import donor
        if not donor.available():
            self.skipTest("exe «Продолжения легенды» недоступен")

    def test_kill_costs_match_known_characters(self) -> None:
        """Цены сверены с именами, а не приняты на веру.

        Эти семь строк — те самые, по которым таблица и была опознана:
        смысл сошёлся сразу у всех, и ни одна цена не выпала из него.
        """
        from konung2 import reputation
        costs = reputation.kill_costs()
        self.assertEqual(costs.get(28), 120, "Королева Нежити")
        self.assertEqual(costs.get(75), 50, "Чёрный маг")
        self.assertEqual(costs.get(8), 30, "Предводитель Жёлтых собак")
        self.assertEqual(costs.get(11), -120, "Глеб")
        self.assertEqual(costs.get(20), -120, "Всеслав")
        self.assertEqual(costs.get(138), -60, "именованные женщины")
        self.assertEqual(costs.get(95), -5, "Никита, рядовой именованный")

    def test_starts_are_four_and_signed(self) -> None:
        from konung2 import reputation
        self.assertEqual(reputation.starts(), [-30, 0, -100, 30])
        # Велиславна — его номер 1; у неё же в движке стоит признак пола,
        # и это независимо подтверждает, что порядок прочитан верно.
        self.assertEqual(reputation.start_for("legend", 1), 0)
        self.assertEqual(reputation.start_for("legend", 2), -100, "Драгомир")
        # Канону ноль: репутации в его игре не существует.
        self.assertEqual(reputation.start_for("canon", 0), 0)

    def test_nameless_prices_agree_with_named(self) -> None:
        """Безымянный дороже именованного, а не наоборот.

        Это проверка на здравый смысл обеих ветвей сразу: если бы я
        перепутал тела или знак, согласованность −120/−140 и −60/−70
        сломалась бы.
        """
        from konung2 import reputation
        costs = reputation.kill_costs()
        self.assertLess(reputation.NAMELESS_NOBLE_SET, costs[20], "князь")
        self.assertLess(reputation.NAMELESS_WOMAN_ADD, costs[138], "женщина")


class ReputationPackTest(unittest.TestCase):
    """Пак несёт правила: без них клиент молчит."""

    def setUp(self) -> None:
        self.shared = КОРЕНЬ / "content_build" / "shared.json"
        if not self.shared.is_file():
            self.skipTest("пак не собран")
        self.document = json.loads(self.shared.read_text(encoding="utf-8"))

    def test_rules_are_in_shared(self) -> None:
        rules = self.document.get("reputation") or {}
        self.assertTrue(rules.get("kill_costs"), "цены убийства не в паке")
        nameless = rules.get("nameless") or {}
        self.assertEqual(nameless.get("noble_body"), 15)
        self.assertEqual(nameless.get("noble_set"), -140)
        self.assertEqual(nameless.get("woman_body"), 14)
        self.assertEqual(nameless.get("woman_add"), -70)

    def test_starts_carry_reputation(self) -> None:
        starts = self.document.get("hero", {}).get("starts") or []
        self.assertTrue(starts, "стартов нет")
        for start in starts:
            self.assertIn("reputation", start, start.get("name"))
            if start.get("game") != "legend":
                self.assertEqual(start["reputation"], 0, start.get("name"))


class ReputationRuleTest(unittest.TestCase):
    """Правило проверяется прогоном настоящего модуля клиента."""

    #: Подсовываем модулю те же правила, что печёт сборщик, и гоняем на
    #: выдуманных юнитах: настоящий пак сюда тянуть незачем, а вот код —
    #: именно настоящий.
    ПОДГОТОВКА = """
    import { loadShared } from "./world.js";
    import { reputationKill, reputationStart } from "./reputation.js";
    loadShared({ reputation: {
      kill_costs: { "28": 120, "11": -120, "95": -5 },
      nameless: { noble_body: 15, noble_set: -140,
                  woman_body: 14, woman_add: -70 },
    } });
    const player = { side: 1, reputation: 0 };
    const ours = { side: 1 };
    const theirs = { side: 2 };
    """

    def прогнать(self, script: str) -> dict:
        node = shutil.which("node")
        if not node:
            self.skipTest("node не найден")
        done = subprocess.run(
            [node, "--input-type=module", "-e", self.ПОДГОТОВКА + script],
            cwd=СТАТИКА, capture_output=True, text=True,
            encoding="utf-8", errors="replace")
        self.assertEqual(done.returncode, 0, done.stderr[:600])
        return json.loads(done.stdout.strip().splitlines()[-1])

    def test_named_victim_costs_by_table(self) -> None:
        итог = self.прогнать("""
        const out = {};
        player.reputation = 0;
        reputationKill(ours, { game: "legend", dialogNumber: 11 }, player);
        out.gleb = player.reputation;
        player.reputation = 0;
        reputationKill(ours, { game: "legend", dialogNumber: 28 }, player);
        out.queen = player.reputation;
        console.log(JSON.stringify(out));
        """)
        self.assertEqual(итог["gleb"], -120)
        self.assertEqual(итог["queen"], 120)

    def test_canon_victim_has_no_price(self) -> None:
        """Канонная жертва с ТЕМ ЖЕ номером разговора цены не имеет.

        Номера обеих игр лежат вперемешку и один номер значит в них разных
        людей; цена ищется по паре «игра + номер».
        """
        итог = self.прогнать("""
        player.reputation = 7;
        const changed = reputationKill(
          ours, { game: null, dialogNumber: 11 }, player);
        console.log(JSON.stringify({ changed, score: player.reputation }));
        """)
        self.assertFalse(итог["changed"])
        self.assertEqual(итог["score"], 7)

    def test_foreign_killer_does_not_count(self) -> None:
        """Убил не наш — счёт не трогается (байты +0x1B не совпали)."""
        итог = self.прогнать("""
        player.reputation = 5;
        const changed = reputationKill(
          theirs, { game: "legend", dialogNumber: 11 }, player);
        console.log(JSON.stringify({ changed, score: player.reputation }));
        """)
        self.assertFalse(итог["changed"])
        self.assertEqual(итог["score"], 5)

    def test_nameless_noble_is_assigned_not_subtracted(self) -> None:
        """У безымянного знатного счёт ПРИСВАИВАЕТСЯ: `= -0x8c`.

        Разница видна только на высокой репутации: вычитание оставило бы
        860, присваивание роняет до −140.
        """
        итог = self.прогнать("""
        const out = {};
        player.reputation = 1000;
        reputationKill(ours, { breed: 84, body: 15, dialogNumber: 0xFF }, player);
        out.noble = player.reputation;
        player.reputation = 1000;
        reputationKill(ours, { breed: 85, body: 14, dialogNumber: 0xFF }, player);
        out.woman = player.reputation;
        console.log(JSON.stringify(out));
        """)
        self.assertEqual(итог["noble"], -140)
        self.assertEqual(итог["woman"], 930)

    def test_nameless_without_breed_mark_is_ignored(self) -> None:
        """Без бита 0x40 в породе вторая ветвь не срабатывает вовсе."""
        итог = self.прогнать("""
        player.reputation = 3;
        const changed = reputationKill(
          ours, { breed: 1, body: 15, dialogNumber: 0xFF }, player);
        console.log(JSON.stringify({ changed, score: player.reputation }));
        """)
        self.assertFalse(итог["changed"])
        self.assertEqual(итог["score"], 3)

    def test_start_comes_from_the_chosen_hero(self) -> None:
        итог = self.прогнать("""
        const out = {};
        reputationStart(player, { reputation: -100 });
        out.dragomir = player.reputation;
        reputationStart(player, { reputation: 0 });
        out.canon = player.reputation;
        console.log(JSON.stringify(out));
        """)
        self.assertEqual(итог["dragomir"], -100)
        self.assertEqual(итог["canon"], 0)


if __name__ == "__main__":
    unittest.main()
