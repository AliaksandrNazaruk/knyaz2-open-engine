# -*- coding: utf-8 -*-
"""
Какая карта мира едет в пак: канонная или расширенная.

Канон принадлежит ``konung2/worldmap.py`` — он и остаётся единственным
владельцем правил движка. Расширение это НАБОР ДАННЫХ в ``project/worldmap``,
собранный ``tools/worldmap_build.py`` из нарисованной картинки; канонная
сетка 32x24 вложена в него как есть, без единой пересчитанной клетки.

Переключатель лежит в самих данных: ``project/worldmap/world.json`` с ключом
``enabled``. Нет файла или ``enabled`` ложно — едет канон. Так «вернуть
канон» это одно слово в данных, а не правка кода, и собранный пак всегда
говорит о себе сам: в правилах остаётся ``policy``, по которой видно, что
именно опубликовано.

УГОЛ СЕТКИ ЗДЕСЬ В КООРДИНАТАХ КАРТИНКИ, А НЕ ЭКРАНА. Канон хранит его
экранным (0xA7, 0x19), потому что движок рисует карту в окне мира и
отсчитывает от левого края ЭКРАНА; клиенту же карта приходит картинкой, и
вычитать ширину панели ему неоткуда — у нарисованной карты панели нет
вовсе. Поэтому пересчёт делается ровно один раз, здесь.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from konung2.interf import PANEL_WIDTH, VIEW_HEIGHT, VIEW_WIDTH
from konung2.worldmap import CELL_H, CELL_W, COLS, ORIGIN_X, ORIGIN_Y, ROWS
from konung2.worldmap import rules as canon_rules

from . import locations

#: Где лежит набор данных расширения относительно каталога проекта.
DATASET = Path("worldmap") / "world.json"


def _fits(document: dict[str, Any], width: int, height: int, where: str) -> None:
    """Сетка обязана умещаться в картинку — иначе угол не в тех координатах.

    Это не придирка, а единственная проверка, отличающая экранный угол от
    картиночного. Канон: 167 + 32*26 = 999 при ширине картинки 884 — не
    умещается; 27 + 832 = 859 умещается. Пак с экранным углом выглядит
    исправным, но в игре сетка, туман и все значки уезжают вправо на ширину
    панели, а часть их вылезает за край. Такой пак лучше не собрать вовсе,
    чем выпустить.
    """
    origin = document["origin"]
    cell = document.get("cell", [CELL_W, CELL_H])
    right = origin[0] + document["cols"] * cell[0]
    bottom = origin[1] + document["rows"] * cell[1]
    if right > width or bottom > height:
        raise ValueError(
            f"{where}: сетка {document['cols']}x{document['rows']} по клетке "
            f"{cell[0]}x{cell[1]} от угла {origin} занимает {right}x{bottom} "
            f"и не умещается в картинку {width}x{height} — "
            f"похоже, угол задан в координатах экрана, а не картинки")


def canon() -> dict[str, Any]:
    """Канонные правила с углом сетки, пересчитанным в координаты картинки."""
    rules = canon_rules()
    rules["origin"] = [ORIGIN_X - PANEL_WIDTH, ORIGIN_Y]
    # Картинка канона — спрайт 4 INTERF.RES, а он ровно в проём окна мира.
    _fits({"origin": rules["origin"], "cols": COLS, "rows": ROWS,
           "cell": [CELL_W, CELL_H]}, VIEW_WIDTH, VIEW_HEIGHT, "канон")
    return rules


def rules(project_dir: str | Path) -> dict[str, Any]:
    """Правила карты мира для пака: расширение, если включено, иначе канон."""
    path = Path(project_dir) / DATASET
    if not path.is_file():
        return canon()
    document = json.loads(path.read_text(encoding="utf-8"))
    if not document.get("enabled", True):
        return canon()
    # Расширение уже собрано в том же виде, что канонные правила: сборщик
    # берёт их за основу и меняет только размер, угол, сетку, маску и
    # картинку. Проверяем это здесь, а не в клиенте: пак с наполовину
    # собранной картой лучше не выпускать.
    for key in ("rows", "cols", "grid", "walk", "origin", "picture"):
        if key not in document:
            raise ValueError(f"{path}: в наборе нет ключа {key}")
    if len(document["grid"]) != document["rows"]:
        raise ValueError(f"{path}: строк в сетке {len(document['grid'])}, "
                         f"а объявлено {document['rows']}")
    if any(len(row) != document["cols"] for row in document["grid"]):
        raise ValueError(f"{path}: не все строки сетки длиной {document['cols']}")
    _fits(document, document["picture"]["width"], document["picture"]["height"],
          str(path))
    _place_project_locations(document, project_dir)
    _append_donor_terrain(document)
    return document


def _append_donor_terrain(document: dict[str, Any]) -> None:
    """Дописать местности донора за канонными.

    Сетка уже размечена его видами со сдвигом ``DONOR_TERRAIN_BASE``
    (tools/worldmap_build.py), и здесь появляются сами записи. Без них его
    земля молчала бы: клиент не находит местность и встречи не бросает.

    Форма записи подогнана под клиента, а не придумана заново. У канона
    номер отряда выбирается через класс опасности по телу героя, поэтому
    ``parties`` — шесть строк по пятнадцать. У донора класса нет, номера
    лежат в записи одним списком из двадцати: кладём ОДНУ строку, и правило
    клиента «строка по телу героя, но не дальше последней» само возьмёт её
    для любого тела.

    ``scene_from_cell`` — не украшение: у донора место боя берётся из байта 2
    самой клетки (FUN_00439B38), а не из пятнадцати сцен записи, как у
    канона. Клиент читает этот признак и не пытается искать сцены там, где
    их нет.
    """
    from konung2 import donor
    if not donor.available():
        return
    canon_terrain = document.get("terrain") or []
    if len(canon_terrain) != donor.DONOR_TERRAIN_BASE:
        raise ValueError(
            f"канонных местностей {len(canon_terrain)}, а сетка размечена от "
            f"{donor.DONOR_TERRAIN_BASE} — виды донора съехали бы на "
            f"{donor.DONOR_TERRAIN_BASE - len(canon_terrain)}")
    document["terrain"] = [*canon_terrain,
                           *({"calm": record["calm"],
                              "classes": [],
                              "parties": [record["parties"]],
                              "scenes": [],
                              "scene_from_cell": True}
                             for record in donor.terrain_table())]


def _place_project_locations(document: dict[str, Any],
                             project_dir: str | Path) -> None:
    """Посадить локации проекта на сетку и дополнить ими таблицы канона.

    Сетка карты мира — один владелец, и он здесь: реестр говорит, в какой
    клетке стоит локация, а проставляет номер в клетку эта функция. Так
    «где стоит» и «как называется» не расходятся.
    """
    entries = locations.registry(project_dir)
    if not entries:
        return
    document["grid"] = locations.stamp(document["grid"], document["walk"],
                                       entries, document["mask"]["land"],
                                       document["mask"]["sea"],
                                       document["flags"]["hidden"])
    document["names"] = locations.names(document.get("names", []), entries)
    document["markers"] = locations.markers(document.get("markers", {}), entries)
    document["arrivals"] = locations.arrivals(document.get("arrivals", {}),
                                              entries)
    #: Чью клетку заняла донорская локация — клиенту, чтобы канонный герой
    #: со значка попадал в канонную карту (locations.canon_instead).
    document["canon_instead"] = locations.canon_instead(entries)


def picture(project_dir: str | Path) -> dict[str, Any] | None:
    """Картинка расширенной карты; у канона её нет — там спрайт INTERF.RES."""
    document = rules(project_dir)
    return document.get("picture")
