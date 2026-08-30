# -*- coding: utf-8 -*-
# Разбор 47 структурных расхождений отгруженного QUESTS.RES с
# перекомпиляцией исходников: что именно правилось между ревизиями.
import pathlib
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tools'))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from konung2.profile import CANON                      # noqa: E402
from konung2.quests import Dialogs                     # noqa: E402
from qst_source_diff import (PARCEL, normal_form,      # noqa: E402
                             script_names, compare)


def commands_of(form):
    """Мультимножество команд формы: и действия узлов, и команды ответов."""
    bag = Counter()
    for node in form:
        if node[1] == 'line':
            for c in node[4]:
                bag[('действие', c)] += 1
            for text, conds, acts, _next in node[5]:
                for c in conds:
                    bag[('условие', c)] += 1
                for c in acts:
                    bag[('действие', c)] += 1
        else:
            for conds, _next in node[2]:
                for c in conds:
                    bag[('условие', c)] += 1
    return bag


def texts_of(form):
    bag = Counter()
    for node in form:
        if node[1] == 'line':
            bag[node[2]] += 1
            for text, *_ in node[5]:
                bag[text] += 1
    return bag


def node_counts(form):
    lines = sum(1 for n in form if n[1] == 'line')
    forks = sum(1 for n in form if n[1] == 'fork')
    return lines, forks


shipped = Dialogs.from_game(CANON)
rebuilt = Dialogs((PARCEL / 'QUESTS.RES').read_bytes(), CANON)
names = script_names()
verdicts = compare()

сводка_команд = Counter()
for number in verdicts['structure']:
    a = normal_form(shipped, number)     # отгружено (канон)
    b = normal_form(rebuilt, number)     # исходники
    ca, cb = commands_of(a), commands_of(b)
    та, тб = texts_of(a), texts_of(b)
    лишние_на_диске = ca - cb            # чего нет в исходниках
    лишние_в_исходнике = cb - ca         # чего нет на диске
    тексты_диска = та - тб
    тексты_исходника = тб - та
    la, fa = node_counts(a)
    lb, fb = node_counts(b)
    print(f'=== {number} {names[number]}')
    print(f'  узлы диск {la}+{fa} / исходник {lb}+{fb};'
          f' команд {sum(ca.values())} / {sum(cb.values())};'
          f' текстов различных {len(тексты_диска)}/{len(тексты_исходника)}')
    for метка, bag in (('только на диске', лишние_на_диске),
                       ('только в исходнике', лишние_в_исходнике)):
        for (род, cmd), n in sorted(bag.items(), key=lambda kv: -kv[1]):
            print(f'  {метка}: {род} {cmd} ×{n}')
            сводка_команд[(метка, род, cmd[0], cmd[1])] += n
    for текст in list(тексты_диска)[:2]:
        print(f'  текст только на диске: «{текст[:60]}»')
    for текст in list(тексты_исходника)[:2]:
        print(f'  текст только в исходнике: «{текст[:60]}»')

print()
print('#### СВОДКА по (сторона, род, kind, handler):')
for ключ, n in sorted(сводка_команд.items(), key=lambda kv: -kv[1]):
    print(' ', ключ, '×', n)
