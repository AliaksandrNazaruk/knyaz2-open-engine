# -*- coding: utf-8 -*-
"""
Сплошная проверка собранного пака: все карты, все правила разом.

Зачем: выборочный осмотр трёх карт 16.08.2026 дал шесть настоящих поломок, и
четыре из них были системными — то есть сидели и на остальных ста тридцати
шести. Каждая проверка ниже — не выдумка, а ровно тот замер, которым эта
поломка ловилась.

    python tools/pack_selfcheck.py [content_build] [--verbose]

Печатает по строке на правило: сколько карт задето и первые примеры. Код
возврата — число нарушенных правил.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

HEROES = {"Ратибор", "Велиславна", "Эйнар", "Хельга", "Александр",
          "Анастасия", "Иззарк", "Драгомир", "Гильдис"}

#: Низ холста человека относительно якоря ног — слагаемое ключа глубины
#: юнита. Движок держит верхний угол холста в +0x3A (на 144 выше ног) и
#: высоту 150 в +0x54, отсюда шестёрка. Клиентский владелец —
#: actor.unitSortKey, разбор — docs/RENDER_DEPTH.md.
ХОЛСТ = 6


def body_key(unit: dict) -> str:
    body, palette = unit.get("body", 0) or 0, unit.get("palette", 0) or 0
    game = unit.get("game")
    return f"{game}:{body}:{palette}" if game else f"{body}:{palette}"


def main() -> int:
    pack = Path(sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-")
                else "content_build")
    verbose = "--verbose" in sys.argv
    shared = json.loads((pack / "shared.json").read_text(encoding="utf-8"))
    hero = shared.get("hero") or {}
    sets = hero.get("body_layers") or {}
    bodies = hero.get("bodies") or {}
    audio_index = json.loads((pack / "assets" / "audio.json").read_text(encoding="utf-8"))
    slots = audio_index.get("slots") or {}

    beda: dict[str, list[str]] = defaultdict(list)
    карт = 0

    for folder in sorted((pack / "maps").iterdir(), key=lambda p: int(p.name)):
        number = int(folder.name)
        m = json.loads((folder / "map.json").read_text(encoding="utf-8"))
        карт += 1
        имя = f"{number} {m.get('name')}"
        units = m.get("units") or []
        village = m.get("village") or {}
        по_отрядам = m.get("workplaces_by_party") or {}

        # 1. Крыша, которую нечем спрятать: у постройки есть кадр крыши, но
        #    нет ни одной клетки footprint (так вскрылся шестибитный номер).
        без_клеток = [b for b in (m.get("buildings") or [])
                      if (b.get("frames") or {}).get("roof")
                      and not (b.get("cells") or {}).get("footprint")]
        if без_клеток:
            beda["крыша без клеток — не спрячется"].append(
                f"{имя}: {len(без_клеток)} из {len(m.get('buildings') or [])}")

        # 2. Юнит без кадров тела: ключ «игра:тело:палитра» не найден в паке
        #    (так вскрылось потерянное поле игры — 52 юнита из 57 в Тиграте).
        #    Звери сюда не идут: у них свой набор кадров из OBJECTS.RES, а не
        #    слои человека (бит 0x40 породы).
        #
        #    ТЕЛО 0 ЖИВЁТ В ДРУГОЙ ТАБЛИЦЕ. Базовое тело клиент ищет в
        #    `bodies` по одной палитре (actor.js), а тела 1…7 — в
        #    `body_layers` по паре. Первая редакция правила этого не знала и
        #    ругалась на всех подряд.
        люди = [u for u in units if not (u.get("breed", 0) or 0) & 0x40]
        нет_кадров = set()
        for u in люди:
            if u.get("body"):
                if body_key(u) not in sets:
                    нет_кадров.add(body_key(u))
            else:
                палитра = str(u.get("palette", 0) or 0)
                if палитра != "0" and палитра not in bodies:
                    нет_кадров.add(f"тело 0, масть {палитра}")
        if нет_кадров:
            beda["юнит без кадров тела"].append(
                f"{имя}: ключи {sorted(нет_кадров)[:3]}")

        # 3. Портрет лица: у панели должен быть спрайт своей игры
        #    (так вскрылась иконка ключа вместо лица Иззарка).
        портреты = (m.get("interface") or {}).get("portraits") or {}
        нет_лиц = set()
        for u in units:
            лицо = u.get("face", 0) or 0
            ключ = f"{u['game']}:{лицо}" if u.get("game") else str(лицо)
            if ключ not in портреты:
                нет_лиц.add(ключ)
        if нет_лиц:
            beda["нет портрета лица"].append(f"{имя}: {sorted(нет_лиц)[:4]}")

        # 4. Рабочее место, которого нет в таблице своего отряда (так
        #    вскрылось, что знахарь с кузнецом уходят работать к Хрофту).
        мимо = set()
        for u in units:
            места = u.get("workplaces") or []
            if not места:
                continue
            таблица = по_отрядам.get(str(u.get("party"))) or village.get("workplaces") or []
            есть = {row.get("slot") for row in таблица}
            мимо |= {slot for slot in места if slot not in есть}
        if мимо:
            beda["рабочее место вне своей таблицы"].append(
                f"{имя}: слоты {sorted(мимо)[:5]}")

        # 4б. ЖИТЕЛЬ НА КЛЕТКЕ ПОСТРОЙКИ, НО НЕ «ВНУТРИ», И ПРИ ЭТОМ ПОЗЖЕ ЕЁ.
        #
        #     Постройка рисует своего юнита сама — сразу после пола и до стен,
        #     — но только если клетка маршрутная (бит 21) или пол (бит 15). На
        #     голой клетке следа юнит идёт общим проходом по глубине.
        #
        #     САМ ПО СЕБЕ ЭТО ЕЩЁ НЕ БЕДА: чаще ключ дома больше, дом рисуется
        #     позже и честно накрывает жителя. Поэтому сравниваем ключи, а не
        #     гадаем — правило docs/RENDER_DEPTH.md, ключ юнита это якорь ног
        #     плюс полная высота холста (150 у человека). Раньше здесь стояла
        #     догадка от поры, когда ключ построек считался неверно.
        след, внутрь = {}, set()
        for b in (m.get("buildings") or []):
            c = b.get("cells") or {}
            for пара in (c.get("footprint") or []):
                след[tuple(пара)] = b
            for пара in (c.get("routed") or []) + (c.get("floor") or []):
                внутрь.add(tuple(пара))
        поверх = []
        for u in units:
            клетка = (u["cell"]["row"], u["cell"]["col"])
            дом = след.get(клетка)
            if дом is None or клетка in внутрь:
                continue
            ключ_дома = (дом.get("bounds") or {}).get("sort_y")
            ключ_юнита = (u.get("position") or {}).get("y")
            if ключ_дома is None or ключ_юнита is None:
                continue
            if ключ_юнита + ХОЛСТ > ключ_дома:      # рисуется ПОСЛЕ дома
                поверх.append(f"{u['name']} (+{ключ_юнита + ХОЛСТ - ключ_дома})")
        if поверх:
            beda["житель рисуется позже своей постройки — ляжет поверх"].append(
                f"{имя}: {len(поверх)} — {поверх[:3]}")

        # 5. Играбельный герой стоит жителем — сюжет протёк в общий мир.
        свои = sorted({u["name"] for u in units if u["name"] in HEROES})
        if свои:
            beda["играбельный герой среди жителей"].append(f"{имя}: {свои}")

        # 6. Нейтральный мир: по мирам не должно быть отличий, пока сюжетов
        #    нет. Ключ есть — значит мир чем-то отличается от общего.
        #
        #    ОТРЯДЫ СЮДА НЕ ИДУТ: запись отряда игрока это сам герой (у
        #    Ратибора трое, у остальных один), и одинаковой она быть не
        #    обязана. Сверяем всё, кроме своего отряда.
        отличия = [k for k in ("units_by_world", "loot_by_world",
                               "village_by_world") if m.get(k)]
        чужие_отряды = [b for b in (m.get("warbands") or [])
                        if not b.get("player")]
        for мир, банды in (m.get("warbands_by_world") or {}).items():
            if [b for b in (банды or []) if not b.get("player")] != чужие_отряды:
                отличия.append(f"warbands[{мир}]")
        if отличия:
            beda["мир отличается от общего"].append(f"{имя}: {отличия}")

        # 7. Сундук без гнезда обстановки: открыть его будет нечем.
        гнёзда = {(x["zone"], x["nest"])
                  for x in ((m.get("terrain") or {}).get("furniture") or [])}
        сироты = [p["id"] for p in (m.get("loot") or [])
                  if p.get("zone") is not None
                  and (p["zone"], p["nest"]) not in гнёзда]
        if сироты:
            beda["сундук без гнезда"].append(f"{имя}: {сироты[:4]}")

        # 8. Непереведённый довод чужой игры: перевод пометил его честно,
        #    и метка обязана быть пустой.
        чужие = set()

        def обойти(node):
            for команда in (node.get("actions") or []):
                if "foreign_item" in команда:
                    чужие.add(f"вещь {команда['foreign_item']}")
                if "foreign_map" in команда:
                    чужие.add(f"карта {команда['foreign_map']}")

        for u in units:
            дерево = u.get("dialog") or {}
            for узел in (дерево.get("nodes") or []):
                обойти(узел)
                for выбор in (узел.get("options") or []):
                    обойти(выбор)
        if чужие:
            beda["непереведённый довод разговора"].append(
                f"{имя}: {sorted(чужие)[:4]}")

        # 9. Звук: слот из предзагрузки карты обязан быть в описи — своей
        #    игры или канонной (наборы двух игр разные).
        игра = (m.get("audio") or {}).get("game")
        немые = [s for s in ((m.get("audio") or {}).get("preload") or [])
                 if str(s) not in slots
                 and not (игра and f"{игра}:{s}" in slots)]
        if немые:
            beda["звук предзагрузки не найден"].append(f"{имя}: {немые[:5]}")

        # 10. Должностное лицо, которого нет среди жителей: разговор о
        #     должности не с кем вести.
        живые = {int(u["id"].removeprefix("unit_")) for u in units
                 if str(u.get("id", "")).startswith("unit_")}
        пропали = [i for i in (village.get("officials") or []) if i and i not in живые]
        if пропали:
            beda["должностное лицо не стоит на карте"].append(f"{имя}: {пропали}")

    print(f"карт проверено: {карт}\n")
    for правило, случаи in sorted(beda.items(), key=lambda kv: -len(kv[1])):
        print(f"{правило}: {len(случаи)} карт")
        for строка in случаи[:(None if verbose else 4)]:
            print("   ", строка)
        if not verbose and len(случаи) > 4:
            print(f"    … ещё {len(случаи) - 4}")
    if not beda:
        print("нарушений нет")
    return len(beda)


if __name__ == "__main__":
    raise SystemExit(main())
