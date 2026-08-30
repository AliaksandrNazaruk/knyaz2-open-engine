# -*- coding: utf-8 -*-
"""Сверка отгруженного QUESTS.RES с перекомпиляцией из исходников сообщества.

В посылке «К2_инстументы» (project/community/k2_tools) лежат исходники всех
квестов «Крови Титанов» на языке QST, их компилятор M_QUEST.exe и уже
скомпилированный им QUESTS.RES (2021 год). Побайтово он с отгруженным НЕ
совпадает, но побайтовая сверка и не нужна: вставка одной строки сдвигает
смещения всего блока текстов. Честная сверка — структурная: оба файла
разбираются нашим же konung2.quests.Dialogs, каждый диалог сериализуется в
нормальную форму (номера узлов заменены порядком обхода), и формы
сравниваются.

Вердикты по диалогу:
  СОВПАЛ     — граф, тексты, условия и действия неотличимы;
  ТЕКСТЫ     — граф и команды те же, отличаются только строки (список);
  СТРУКТУРА  — разошёлся сам граф или команды.

Запуск:  python tools/qst_source_diff.py [--doc]
С ключом --doc пишет docs/QUEST_SOURCES_AUDIT.md.
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from konung2.profile import CANON            # noqa: E402
from konung2.quests import Dialogs           # noqa: E402

PARCEL = ROOT / 'project' / 'community' / 'k2_tools' / 'user' / 'Konung2' / 'QUESTS'

#: Диалогов в игре — по логу компилятора (Scripts=152).
SCRIPTS = 152


def _command(c: dict) -> tuple:
    """Команда без raw: raw включает биты, уже разложенные по полям."""
    return (c['kind'], c.get('handler'), c.get('bit'), c.get('quest'),
            c.get('argument'), c['set'], c['and'])


def normal_form(d: Dialogs, number: int) -> list:
    """Дерево диалога с узлами, перенумерованными порядком обхода.

    Ссылки «куда дальше» заменяются порядковыми номерами, поэтому формы
    двух файлов сравнимы, даже когда абсолютные номера узлов разъехались.
    """
    order: dict[int, int] = {}

    def ordinal(index: int) -> int:
        if index < 0:
            return -1
        return order.setdefault(index, len(order))

    form: list = []
    queue = [d.root(number)]
    seen: set[int] = set()
    while queue:
        index = queue.pop(0)
        if index < 0 or index in seen:
            continue
        seen.add(index)
        node = d.node(index)
        if node['phrase'] != -1:
            spoken = d.phrase(node['phrase'])
            options = []
            step = index + 1
            while step < d.node_count:
                answer = d.node(step)
                if answer['phrase'] == -1:
                    break
                options.append((
                    d.phrase(answer['phrase'])['text'],
                    tuple(_command(c) for c in d.conditions(answer['condition'])),
                    tuple(_command(c) for c in d.actions(answer['action'])),
                    ordinal(answer['next']),
                ))
                queue.append(answer['next'])
                step += 1
            form.append((
                ordinal(index), 'line', spoken['text'], spoken['voice'],
                tuple(_command(c) for c in d.actions(node['action'])),
                tuple(options),
            ))
        else:
            branches = []
            for branch in d.branches(index):
                branches.append((
                    tuple(_command(c) for c in branch['condition']),
                    ordinal(branch['next']),
                ))
                queue.append(branch['next'])
            form.append((ordinal(index), 'fork', tuple(branches)))
        queue.append(node['next'])
    return form


def _textless(form: list) -> list:
    """Та же форма, но все строки заменены заглушкой."""
    out = []
    for node in form:
        if node[1] == 'line':
            out.append((node[0], node[1], '·', node[3], node[4],
                        tuple(('·',) + option[1:] for option in node[5])))
        else:
            out.append(node)
    return out


def _texts(form: list) -> list[str]:
    out = []
    for node in form:
        if node[1] == 'line':
            out.append(node[2])
            out.extend(option[0] for option in node[5])
    return out


def compare() -> dict:
    # Сверка РЕВИЗИЙ: отгруженный канон против компиляции исходников.
    # Оверлей редактора (project/story/QUESTS.RES) здесь ни при чём —
    # без overlay=False сверка мерила бы текущие правки сюжета.
    shipped = Dialogs.from_game(CANON, overlay=False)
    rebuilt = Dialogs((PARCEL / 'QUESTS.RES').read_bytes(), CANON)
    verdicts = {'same': [], 'texts': {}, 'structure': []}
    for number in range(SCRIPTS):
        a = normal_form(shipped, number)
        b = normal_form(rebuilt, number)
        if a == b:
            verdicts['same'].append(number)
        elif _textless(a) == _textless(b):
            pairs = [(x, y) for x, y in zip(_texts(a), _texts(b)) if x != y]
            verdicts['texts'][number] = pairs
        else:
            verdicts['structure'].append(number)
    return verdicts


def script_names() -> list[str]:
    """Имена диалогов из лога компилятора — авторская таблица номеров."""
    log = (PARCEL / 'QUESTS.LOG').read_bytes().decode('cp866')
    names: list[str] = []
    for line in log.splitlines():
        m = re.match(r'^(\d+) (\S.*)$', line.strip())
        if m and int(m.group(1)) == len(names):
            names.append(m.group(2))
    return names


def tokens() -> list[tuple[str, str | None]]:
    """Токены мастера: имя и журнальный текст, порядок = номер квеста."""
    master = (PARCEL / 'KONUNG2.QST').read_bytes().decode('cp866')
    out = []
    for m in re.finditer(r'\{TOKEN=([^\s{}]+)\s*(\{TEXT(.*?)\})?\s*\}',
                         master, re.S):
        text = m.group(3)
        out.append((m.group(1), ' '.join(text.split()) if text else None))
    return out


#: Разбор 47 структурных расхождений по существу (2026-08-24). Даты файлов
#: посылки: .QST — январь-февраль 2003, релиз игры — 2004: исходники РАНЬШЕ
#: диска, правки диска — авторские доводки к выпуску.
DELTA_NOTES = """## Разбор структурных расхождений (24.08)

Дельта каждой пары форм разобрана по мультимножествам команд
(`tools/qst_delta.py`); все 47 сводятся к пяти правкам релиза.

* **44 диалога: возврат долга заклада стал платным дважды.** У каждого
  говорящего жителя есть общий узел «тебе одолжено 1200 монет» (ветка
  открыта условием 8 «деревня заложена»). Релиз добавил в ответ «Да, я
  хочу вернуть долг» списание 60(−120) — но обработчик 41(0), стоящий
  там же, ПО ДИЗАСМУ (0x433818) сам снимает 0x4B0=1200 при снятом бите
  заклада. Итог релиза: заклад даёт +1000, возврат стоит **2400** при
  проверке «денег ≥ 1200» (условие 20(120)) — можно уйти в минус.
  Ранняя ревизия списывала честные 1200 (один 41(0)). Порт следует
  диску: дерево пака несёт оба действия (проверено на Белуне, карта 18),
  клиентские обработчики 60 и 41 повторяют движок — двойное списание
  унаследовано как канон релиза.
* **Купцы 80–88: грузовые токены живы в обеих ревизиях.** SET-цепочки
  идентичны; релиз сократил дубли СНЯТИЙ (у купца Чёрного Бора квесты
  9/10/11/12/90 снимались трижды, стало по разу). Механика перевозок
  цела, отличие только в уборке повторов.
* **Оборотень (7):** релиз заменил «удалить собеседника» 46(0) на
  «удалить юнита №7» 46(7) в обеих концовках Ольги (при прощании с
  мёртвой собеседник — не она) и добавил 100 опыта за ветку смерти.
* **Шпион Повелителя (43):** релиз добавил в узел «подожди, я вернусь с
  компаньоном» три изъятия 48(0)/48(21)/48(22) — шпион освобождает свой
  мешок от квестовых бумаг (грамоты 21/22), чтобы их нельзя было снять
  с его трупа; ранний дубль «открыть локацию 6» убран.
* **Мелочь:** у Подруги Хельги (21/22) релиз снял условие «квест 62
  взведён» с одной ветки; Рыбак у Чёрного Бора (64) больше не трогает
  токен 86 «ЗНАЕТ_О_СОМЕ»; у Кузнеца Лесного лагеря реплика «Беглое мне
  совсем не по пути» стала «Борье…».

"""


def main() -> None:
    verdicts = compare()
    names = script_names()
    print(f'диалогов сверено: {SCRIPTS}')
    print(f'совпали целиком:  {len(verdicts["same"])}')
    print(f'только тексты:    {len(verdicts["texts"])} — '
          f'{sorted(verdicts["texts"])}')
    print(f'структура:        {len(verdicts["structure"])} — '
          f'{verdicts["structure"]}')
    for number, pairs in sorted(verdicts['texts'].items()):
        title = names[number] if number < len(names) else ''
        print(f'--- диалог {number} {title}: {len(pairs)} строк')
        for shipped_text, source_text in pairs[:3]:
            print(f'    отгружено:   {shipped_text[:70]}')
            print(f'    в исходнике: {source_text[:70]}')
    if '--doc' in sys.argv:
        write_report(verdicts, names)


def write_report(verdicts: dict, names: list[str]) -> None:
    token_list = tokens()
    path = ROOT / 'docs' / 'QUEST_SOURCES_AUDIT.md'
    with path.open('w', encoding='utf-8') as f:
        f.write('# Исходники квестов «Крови Титанов»: сверка с игрой\n\n')
        f.write('Автосводка `tools/qst_source_diff.py --doc`. '
                'Как читать — в конце файла.\n\n')
        f.write(f'* Диалогов сверено: **{SCRIPTS}**\n')
        f.write(f'* Совпали целиком: **{len(verdicts["same"])}**\n')
        f.write(f'* Отличаются только строками: **{len(verdicts["texts"])}** — '
                f'{sorted(verdicts["texts"])}\n')
        f.write(f'* Разошлись структурой или командами: '
                f'**{len(verdicts["structure"])}** — '
                f'{verdicts["structure"]}\n\n')
        f.write('## Вердикт\n\n')
        f.write('Исходники — РАННЯЯ ревизия игры (даты .QST: январь-'
                'февраль 2003; релиз — 2004), диск позже: расхождения — '
                'авторские доводки к выпуску, разобраны ниже. Для порта '
                'канон — ОТГРУЖЕННЫЙ файл; исходники — словарь языка, '
                'имена номеров и журналы, но не арбитр команд. Где они '
                'спорят с байтами диска, правы байты.\n\n')
        f.write(DELTA_NOTES)
        if verdicts['texts']:
            f.write('## Отличия в строках\n\n')
            for number, pairs in sorted(verdicts['texts'].items()):
                f.write(f'### Диалог {number} — {names[number]}\n\n')
                for shipped_text, source_text in pairs:
                    f.write(f'* отгружено: «{shipped_text}»\n'
                            f'  в исходнике: «{source_text}»\n')
                f.write('\n')
        if verdicts['structure']:
            f.write('## Разошедшиеся диалоги\n\n')
            for number in verdicts['structure']:
                title = names[number] if number < len(names) else '?'
                f.write(f'* {number} — {title}\n')
            f.write('\n')
        f.write('## Диалоги по номерам (лог компилятора)\n\n')
        for i, name in enumerate(names):
            f.write(f'* {i} — {name}\n')
        f.write('\n## Квесты по номерам (токены мастера)\n\n')
        f.write('Порядок определений в KONUNG2.QST = номер состояния; '
                'проверено битами SCRIPTACTIVE и текстом токена 0.\n\n')
        for i, (name, text) in enumerate(token_list):
            mark = '' if text else ' — журнала нет'
            f.write(f'* {i} — {name}{mark}\n')
        f.write('\n## Как читать\n\n')
        f.write('Сверка структурная: оба файла разобраны одним парсером, '
                'узлы перенумерованы порядком обхода, сравниваются графы, '
                'команды и строки. Побайтово файлы не совпадают из-за '
                'сдвига смещений в блоке текстов — это не различие '
                'содержания.\n')
    print('записано:', path)


if __name__ == '__main__':
    main()
