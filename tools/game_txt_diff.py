# -*- coding: utf-8 -*-
"""Сверка боевых данных юнитов: авторские исходники против бинарных GAME.N.

В посылке сообщества (project/community/k2_tools/ucompiler) лежат ТЕКСТОВЫЕ
исходники расстановок «Крови Титанов»: GAME_0…5.TXT с #include на карты.
У каждого юнита там открытым текстом всё, из чего считается бой:

    UNIT.PARAMETERS=10,10,10,10,10,21      шесть характеристик
    UNIT.AXESKILL=10,40                    топор и ДВУРУЧНЫЙ топор
    UNIT.FIGHTSSKILL=30,0,10               рукопашный, смертельный удар,
                                           бой двумя руками
    UNIT.NATIVEARMOUR=10                   природная броня
    UNIT.ACCESSORY={ ARM=172 DURABILITY=6,6 … }

Наш пак печёт те же поля из двоичных записей GAME.N по смещениям, снятым
дизассемблером. Эта сверка — прямое доказательство разбора: каждое поле
каждого сматченного юнита сравнивается с авторским числом.

Порядок PARAMETERS и раскладка связок навыков проверены на Ратиборе
(мир 0) и Ярополке (мир 1, AXESKILL=10,40 -> топор 10, двуручный 40).

ВЕРДИКТ ПРОГОНА 2026-08-23 (docs/COMBAT_DATA_AUDIT.md): все 1617 юнитов
с клеткой сматчены по (карта, строка, столбец) без единого пропуска;
54 972 проверки полей, содержательных расхождений НОЛЬ. Расходятся два
артефакта АВТОРСКОГО конвейера, по всем шести мирам одинаково:

* NATIVEARMOUR=300 у трёх тварей карт 14/22/24 лежит в бинаре как 44 —
  поле байтовое, 300 & 0xFF = 44: обрезал их компилятор расстановок;
* одиночный BARGAINSKILL=N (без второго числа) даёт в бинаре
  «Управление деревней 80» — дефолт их компилятора (задан парой, как у
  Ратибора 30,50, — берётся заданное).

Запуск: python tools/game_txt_diff.py
"""
from __future__ import annotations

import pathlib
import re
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from konung2.gamefile import (T_ITEMS, _game_bytes, _npc_names,  # noqa: E402
                              item_class_of, unit_stats, unit_workplaces)

SOURCES = (ROOT / 'project' / 'community' / 'k2_tools' / 'ucompiler' /
           'KONUNG2' / 'RESOURCE' / 'GAME')

#: Порядок UNIT.PARAMETERS — установлен по Ратибору и Ярополку.
PARAMETER_ORDER = ['Харизма', 'Ловкость', 'Интеллект', 'Обучаемость',
                   'Сила', 'Выносливость']

#: Связки навыков исходника -> наши имена (порядок значений в строке).
SKILL_BUNDLES = {
    'FIGHTSSKILL': ['Рукопашный бой', 'Смертельный удар', 'Бой двумя руками'],
    'SWORDSKILL': ['Владение мечом', 'Владение двуручным мечом'],
    'AXESKILL': ['Владение топором', 'Владение двуручным топором'],
    'MACESKILL': ['Владение дубиной', 'Владение двуручной дубиной'],
    'BOWSKILL': ['Стрельба из лука', 'Стрельба из арбалета'],
    'CURESKILL': ['Знахарство', 'Приготовление смесей'],
    'BARGAINSKILL': ['Торговля', 'Управление деревней'],
    'IDENTIFYSKILL': ['Идентификация предметов'],
    'SCOUTSKILL': ['Следопыт'],
    'SMITHSKILL': ['Кузнечное дело'],
    'BUILDSKILL': ['Строительные навыки'],
}

#: Слоты снаряжения исходника -> ключи бинарного разбора (unit_stats).
ACCESSORY_SLOTS = {'ARM': 'hand', 'CUIRASS': 'body', 'HELMET': 'head',
                   'SHIELD': 'shield', 'BOW': 'ranged', 'ARROWS': 'ammo'}


def _read(path: pathlib.Path) -> str:
    return path.read_bytes().decode('cp866', 'replace')


def _find_file(name: str) -> pathlib.Path | None:
    """Инклюды пишутся в нижнем регистре, файлы лежат в верхнем."""
    wanted = name.strip().lower()
    for candidate in SOURCES.iterdir():
        if candidate.name.lower() == wanted:
            return candidate
    return None


def _source_text(world: int) -> str:
    """Мастер мира со всеми его #include, склеенный в один текст."""
    seen: set[str] = set()

    def include(name: str) -> str:
        path = _find_file(name)
        if path is None or path.name.lower() in seen:
            return ''
        seen.add(path.name.lower())
        out = []
        for line in _read(path).splitlines():
            stripped = line.strip()
            if stripped.lower().startswith('#include'):
                out.append(include(stripped.split(None, 1)[1]))
            else:
                out.append(line)
        return '\n'.join(out)

    return include(f'GAME_{world}.TXT')


def _blocks(text: str):
    """Верхнеуровневые блоки {GROUP …} с вложенными {UNIT …}.

    Разбор простой, по балансу фигурных скобок: значения-вложения
    (ACCESSORY={…}) остаются внутри тела юнита как есть.
    """
    groups = []
    position = 0
    while True:
        start = text.find('{GROUP', position)
        if start < 0:
            break
        depth = 0
        end = start
        for end in range(start, len(text)):
            if text[end] == '{':
                depth += 1
            elif text[end] == '}':
                depth -= 1
                if not depth:
                    break
        groups.append(text[start:end + 1])
        position = end + 1
    return groups


def _fields(body: str) -> dict:
    """Поля UNIT.X=… одного юнита; вложенные {…} — сырым текстом."""
    out: dict = {}
    for match in re.finditer(
            r'UNIT\.(\w+)=(\{.*?\}|[^\n]*)', body, re.S):
        key, value = match.group(1), match.group(2).strip()
        if not value.startswith('{'):
            # хвост после значения — авторская подпись табами («Ратибор»)
            value = value.split('\t')[0].strip()
        out[key] = value
    return out


def _units_of(world: int) -> list[dict]:
    """Юниты исходника мира: поля + карта своей группы."""
    units = []
    for group in _blocks(_source_text(world)):
        map_match = re.search(r'GROUP\.MAP=(\d+)', group)
        group_map = int(map_match.group(1)) if map_match else None
        # тела юнитов — вложенные блоки {UNIT …}
        position = 0
        while True:
            start = group.find('{UNIT', position)
            if start < 0:
                break
            depth = 0
            end = start
            for end in range(start, len(group)):
                if group[end] == '{':
                    depth += 1
                elif group[end] == '}':
                    depth -= 1
                    if not depth:
                        break
            fields = _fields(group[start:end + 1])
            fields['_map'] = group_map
            units.append(fields)
            position = end + 1
    return units


def _ints(value: str) -> list[int]:
    return [int(piece, 0) for piece in value.split(',') if piece.strip()]


def _gear(value: str) -> dict[str, dict]:
    """ACCESSORY/INVENTORY: слот -> {class, durability, bonus}."""
    out: dict[str, dict] = {}
    for line in value.strip('{}').splitlines():
        line = line.strip()
        if not line:
            continue
        pairs = dict(re.findall(r'(\w+)=([\w,x-]+)', line))
        slot = next((k for k in pairs if k in ACCESSORY_SLOTS or
                     k in ('MAGIC', 'QUEST')), None)
        if not slot:
            continue
        entry = {'class': int(pairs[slot], 0)}
        if 'DURABILITY' in pairs:
            entry['durability'] = _ints(pairs['DURABILITY'])
        if 'BONUS' in pairs:
            entry['bonus'] = _ints(pairs['BONUS'])
        # слот может повториться (две связки стрел) — храним списком
        out.setdefault(slot, []).append(entry)
    return out


def bonus_word(fields: list[int]) -> tuple[int, int]:
    """BONUS исходника -> (байт +0x01, слово чар +0x0E).

    Формат доказан пятью парами «TXT против бинаря» на ожерельях класса 62
    (кучи PCOMMON.TXT, карты 2/6/8/20/46/47): первое поле — байт +0x01 в
    младших восьми битах и флаг «не опознано» 0x8000 в старшем; дальше
    ПЯТЬ ГРУПП слова чар ОТ СТАРШИХ БИТ К МЛАДШИМ — броня (биты 12…14),
    удар (9…11), ловкость (6…8), сила (3…5), выносливость (0…2). Ряд
    групп тот же, что у магических камней 52…56.
    """
    head, groups = fields[0], fields[1:6]
    word = 0x8000 if head & 0x8000 else 0
    for at, value in enumerate(groups):
        word |= (value & 7) << ((4 - at) * 3)
    return head & 0xFF, word


def _binary_units(world: int) -> dict[tuple, dict]:
    """Бинарные юниты мира: ключ (карта отряда, строка, столбец)."""
    import struct
    data, layout = _game_bytes(world)
    names = _npc_names()
    parties_at, parties_n, parties_size = layout['parties']
    units_at, units_n, units_size = layout['units']
    out: dict[tuple, dict] = {}
    for party in range(parties_n):
        record = data[parties_at + party * parties_size:][:parties_size]
        if len(record) < parties_size:
            break
        party_map, = struct.unpack_from('<H', record, 0x08)
        first, = struct.unpack_from('<H', record, 0x00)
        count = record[0x1C]
        if not count:
            continue
        for index in range(first, min(first + count, units_n)):
            unit = data[units_at + index * units_size:][:units_size]
            stats = unit_stats(data, index, units_at)
            entry = {
                'index': index, 'map': party_map,
                'row': unit[0x12], 'col': unit[0x14],
                'name_id': unit[0xF0], 'dialog': unit[0xF2],
                'direction': unit[0x18],
                'name': names[unit[0xF0]] if unit[0xF0] < len(names) else '',
                'workplaces': unit_workplaces(unit),
                'stats': stats, 'data': data,
            }
            key = (party_map, entry['row'], entry['col'])
            # клетка 0:0 у зонных отрядов — не ключ
            if entry['row'] or entry['col']:
                out.setdefault(key, entry)
    return out


def compare_world(world: int) -> dict:
    """Сверка одного мира: счётчики и расхождения по полям."""
    verdict = {'world': world, 'matched': 0, 'placed': 0, 'unplaced': 0,
               'mismatch': [], 'checked': Counter(), 'failed': Counter()}
    binary = _binary_units(world)

    def note(unit, field, ours, theirs):
        verdict['failed'][field] += 1
        if len(verdict['mismatch']) < 400:
            verdict['mismatch'].append(
                (world, unit.get('NAME', '?').split(',')[0],
                 unit.get('_map'), field, theirs, ours))

    def check(unit, target, field, ours, theirs):
        verdict['checked'][field] += 1
        if ours != theirs:
            note(unit, field, ours, theirs)

    for unit in _units_of(world):
        place = unit.get('MAP')
        if not place:
            verdict['unplaced'] += 1
            continue
        verdict['placed'] += 1
        direction, row, col = _ints(place)
        key = (unit['_map'], row, col)
        target = binary.get(key)
        if target is None:
            verdict['failed']['—не найден—'] += 1
            continue
        verdict['matched'] += 1
        stats = target['stats']
        # характеристики
        if 'PARAMETERS' in unit:
            wanted = _ints(unit['PARAMETERS'])
            got = [stats['characteristics'][name] for name in PARAMETER_ORDER]
            check(unit, target, 'PARAMETERS', got, wanted)
        # поворот из UNIT.MAP — первый довод тройки
        check(unit, target, 'direction', target['direction'], direction)
        # навыки: названные — по связкам, неназванные обязаны быть нулями
        named: dict[str, int] = {}
        for bundle, our_names in SKILL_BUNDLES.items():
            values = _ints(unit[bundle]) if bundle in unit else []
            for at, skill in enumerate(our_names):
                named[skill] = values[at] if at < len(values) else 0
        for skill, wanted in named.items():
            check(unit, target, f'скилл:{skill}',
                  stats['skills'].get(skill, 0), wanted)
        # простые поля
        simple = [
            ('NATIVEARMOUR', 'armour', 0), ('FACE', 'face', 0),
            ('LEVEL', 'level', 1), ('MONEY', 'money', 0),
            ('FREEEXPERIENCE', 'free_xp', 0),
        ]
        for source_key, ours_key, default in simple:
            wanted = _ints(unit[source_key])[0] if source_key in unit else default
            check(unit, target, source_key, stats[ours_key], wanted)
        if 'QUEST' in unit:
            check(unit, target, 'QUEST', target['dialog'],
                  _ints(unit['QUEST'])[0])
        if 'MODEL' in unit:
            body = int(unit['MODEL'].split(',')[0])
            check(unit, target, 'MODEL.body', stats['body'], body)
        # рабочие места: PLACES=приказ0,…: -1 значит пусто (наш 255);
        # бинарный разбор пустой хвост обрезает — выравниваем длину
        if 'PLACES' in unit:
            wanted = [(place if place >= 0 else 0xFF)
                      for place in _ints(unit['PLACES'])]
            got = list(target['workplaces'])
            got += [0xFF] * (len(wanted) - len(got))
            check(unit, target, 'PLACES', got, wanted)
        # снаряжение: класс и крепость по слотам
        if 'ACCESSORY' in unit:
            for slot, entries in _gear(unit['ACCESSORY']).items():
                ours_slot = ACCESSORY_SLOTS.get(slot)
                if ours_slot is None:
                    continue
                record = stats['equipment'].get(ours_slot, 0)
                wanted = entries[0]
                if not record:
                    check(unit, target, f'слот:{slot}', None, wanted['class'])
                    continue
                found = item_class_of(target['data'], record)
                check(unit, target, f'слот:{slot}',
                      found.index if found else None, wanted['class'])
                if 'durability' in wanted and found is not None:
                    # крепость экземпляра: текущая f32 +4, полная f32 +8
                    import struct as _struct
                    at = T_ITEMS.offset + record * T_ITEMS.size
                    current, full = _struct.unpack_from(
                        '<2f', target['data'], at + 4)
                    got = [round(current), round(full)]
                    want = wanted['durability']
                    if len(want) == 1:
                        want = [want[0], want[0]]
                    check(unit, target, f'крепость:{slot}', got, want)
                if len(wanted.get('bonus') or []) >= 6 and found is not None:
                    # слово чар и байт +0x01 — из шести полей BONUS
                    import struct as _struct
                    at = T_ITEMS.offset + record * T_ITEMS.size
                    head, word = bonus_word(wanted['bonus'])
                    got_head = target['data'][at + 1]
                    got_word, = _struct.unpack_from(
                        '<H', target['data'], at + 0x0E)
                    check(unit, target, f'байт01:{slot}', got_head, head)
                    check(unit, target, f'чары:{slot}', got_word, word)
    return verdict


def main() -> None:
    totals = Counter()
    fails = Counter()
    rows = []
    for world in range(6):
        try:
            verdict = compare_world(world)
        except OSError as error:
            print(f'мир {world}: нет данных ({error})')
            continue
        rows.append(verdict)
        totals.update(verdict['checked'])
        fails.update(verdict['failed'])
        print(f"мир {world}: юнитов с клеткой {verdict['placed']}, "
              f"сматчено {verdict['matched']}, без клетки "
              f"{verdict['unplaced']}, не найдено "
              f"{verdict['failed'].get('—не найден—', 0)}")
    checked = sum(totals.values())
    failed = sum(fails.values()) - fails.get('—не найден—', 0)
    print(f'\nпроверок полей: {checked}, расхождений: {failed}')
    for field in sorted(set(totals) | set(fails)):
        bad = fails.get(field, 0)
        if bad:
            print(f'  {field}: {bad} из {totals.get(field, 0)}')
    shown = 0
    for verdict in rows:
        for world, name, map_number, field, wanted, got in verdict['mismatch']:
            print(f'  мир {world} карта {map_number} {name!r} {field}: '
                  f'у авторов {wanted}, в бинаре {got}')
            shown += 1
            if shown >= 40:
                return


if __name__ == '__main__':
    main()
