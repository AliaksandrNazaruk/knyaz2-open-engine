# -*- coding: utf-8 -*-
"""Исходники квестов «Крови Титанов» (посылка сообщества) против игры.

Что здесь закреплено и почему это важно:

* НУМЕРАЦИЯ РАСКРЫТА ПЕРВОИСТОЧНИКОМ. Лог компилятора называет все 152
  диалога по номерам, мастер KONUNG2.QST определяет 103 токена в порядке
  номеров квестов. Это те самые таблицы, которые мы восстанавливали по
  ассемблеру, — теперь они авторские.
* ПОРЯДОК ТОКЕНОВ ПРОВЕРЕН, а не принят на веру: биты SCRIPTACTIVE из
  мастера совпали с байтами таблицы состояний отгруженного файла, и текст
  токена 0 равен журнальной фразе квеста 0.
* ИСХОДНИКИ — ДРУГАЯ РЕВИЗИЯ. 47 диалогов из 152 расходятся с диском, и
  расхождения содержательные (опыт оборотня, деньги за выкуп дома).
  Канон порта — отгруженный файл; исходники — словарь, а не арбитр.
  Сводка — docs/QUEST_SOURCES_AUDIT.md.
"""
from __future__ import annotations

import importlib.util
import pathlib
import struct
import unittest

КОРЕНЬ = pathlib.Path(__file__).resolve().parents[1]
ПОСЫЛКА = (КОРЕНЬ / 'project' / 'community' / 'k2_tools' / 'user' /
           'Konung2' / 'QUESTS')


def _средство():
    spec = importlib.util.spec_from_file_location(
        'qst_source_diff', КОРЕНЬ / 'tools' / 'qst_source_diff.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class QuestSourcesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not (ПОСЫЛКА / 'QUESTS.LOG').is_file():
            raise unittest.SkipTest('посылка сообщества не распакована')
        cls.tool = _средство()

    def test_scripts_are_152_and_named(self) -> None:
        """Лог компилятора называет все диалоги; номера — авторские."""
        имена = self.tool.script_names()
        self.assertEqual(len(имена), 152)
        self.assertTrue(имена[6].startswith('Гилли_Кормчий'))
        self.assertTrue(имена[36].startswith('Повелитель'))
        self.assertTrue(имена[138].startswith('Герой'))

    def test_tokens_are_103_and_ordered(self) -> None:
        """Порядок токенов мастера = номер квеста, доказано двумя путями."""
        токены = self.tool.tokens()
        self.assertEqual(len(токены), 103)
        с_журналом = [i for i, (_, текст) in enumerate(токены) if текст]
        self.assertEqual(len(с_журналом), 76)
        self.assertEqual(токены[0][0], 'БЕРЕСТЯНАЯ_ГРАМОТА')

        from konung2.profile import CANON
        from konung2.quests import Dialogs
        d = Dialogs.from_game(CANON)
        s_at, s_size = d.profile.quests_layout()['quest_states']
        # SCRIPTACTIVE=8,16,26,36,50,60 из мастера — байты бита 1 на диске
        активные = [q for q in range(s_size // 4) if d.data[s_at + q * 4]]
        self.assertEqual(активные, [8, 16, 26, 36, 50, 60])
        # текст токена 0 — журнальная фраза квеста 0
        фраза = struct.unpack_from('<h', d.data, s_at + 2)[0]
        self.assertEqual(' '.join(d.phrase(фраза)['text'].split()),
                         токены[0][1])
        # у квестов без журнала фразы нет (−1), заливка пустых мест — 0
        for q in range(103):
            ph = struct.unpack_from('<h', d.data, s_at + q * 4 + 2)[0]
            if токены[q][1]:
                self.assertGreater(ph, 0, токены[q][0])
            else:
                self.assertEqual(ph, -1, токены[q][0])

    def test_shipped_differs_from_sources_as_measured(self) -> None:
        """Ревизии разные, и мера расхождения зафиксирована.

        Если пак, парсер или посылка поедут — числа сдвинутся, и это
        повод перечитать docs/QUEST_SOURCES_AUDIT.md, а не подгонять тест.
        """
        итог = self.tool.compare()
        self.assertEqual(len(итог['same']), 105)
        self.assertEqual(итог['texts'], {})
        self.assertEqual(len(итог['structure']), 47)
        # единственный диалог с другим ГРАФОМ, остальные — команды
        self.assertIn(88, итог['structure'])


if __name__ == '__main__':
    unittest.main()
