# -*- coding: utf-8 -*-
"""
Сборка расширенной карты мира из нарисованной картинки.

Канон живёт в ``konung2/worldmap.py`` и остаётся единственным владельцем
правил движка. Здесь из картинки делается НАБОР ДАННЫХ проекта: сетка
клеток, маска проходимости и геометрия. Канонная сетка 32x24 вкладывается
в него как есть — ни одна её клетка не пересчитывается.

Посадка канона замерена, а не назначена: перебор всех сдвигов дал резкий
пик на (строка 0, столбец 22) с совпадением суши 99.0% при случайном
уровне 59%. Размер клетки 26x28 взят из движка (VA 0x4277F4), и картинка
1404x952 делится на него без остатка: 54 на 34.

Суша отличается от моря по ЦВЕТУ, а не по яркости: суша тёплая (красного
заметно больше синего), море серо-синее. Порог R-B>30 проверен на каноне:
из 768 клеток разошлось восемь, и семь из них — «движок море, нарисована
суша», то есть берег чуть шире.

ВИД МЕСТНОСТИ НОВЫМ КЛЕТКАМ НЕ УГАДЫВАЕТСЯ. Замер показал, что по картинке
он неразличим: у всех сухопутных видов 2..11 средний цвет около 150/120/86
с разбросом 6..24, они перекрываются полностью. Отделяется только море.
Поэтому новой суше ставится один вид (LAND_KIND), морю — морской. Разделять
новые земли по видам это решение про встречи, а не измерение.

Запуск:
    python tools/worldmap_build.py <картинка.png>
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

from konung2 import donor
from konung2 import worldmap as canon

#: Куда кладётся набор данных проекта.
OUT_DIR = Path(__file__).resolve().parent.parent / "project" / "worldmap"

#: Посадка канона в расширенной сетке (замер, см. заголовок).
CANON_ROW, CANON_COL = 0, 22

#: Порог «тёплого» цвета: суша минус море по каналам R и B.
WARM_THRESHOLD = 30

#: Вид местности новым клеткам. Морской — тот же, что у канонного моря;
#: сухопутный — самый частый сухопутный вид канона (127 клеток из 768).
SEA_KIND, LAND_KIND = 1, 4

#: БРОДЫ: клетки воды, куда ходят и ПЕШКОМ. «Переправа через реку» из
#: «Продолжения легенды» стоит на самой воде — это место, где строят мост
#: на другой берег, — и у неё есть свой значок (спрайт 233), то есть это
#: настоящая мировая локация, а не промах рисунка. Цветовой порог такую
#: клетку честно считает морем, поэтому суша добавляется здесь, поимённо:
#: клетка получает ОБА бита — пеший доходит строить мост, корабль проходит
#: как проходил.
FORDS = {(17, 16): "Переправа через реку (186)"}

#: Разбор dword клетки — те же сдвиги, что в каноне.
LOCATION, TERRAIN, SCENE, FLAGS = (canon.CELL_LOCATION, canon.CELL_TERRAIN,
                                   canon.CELL_SCENE, canon.CELL_FLAGS)


def warm(image, row: int, col: int) -> float:
    """Насколько клетка «тёплая»: среднее R-B по её середине."""
    pixels = image.load()
    total = count = 0
    for dy in range(3, canon.CELL_H, 4):
        for dx in range(3, canon.CELL_W, 4):
            red, _, blue = pixels[col * canon.CELL_W + dx, row * canon.CELL_H + dy]
            total += red - blue
            count += 1
    return total / count


def build(picture_path: Path) -> dict:
    image = Image.open(picture_path).convert("RGB")
    width, height = image.size
    if width % canon.CELL_W or height % canon.CELL_H:
        raise SystemExit(
            f"картинка {width}x{height} не делится на клетку "
            f"{canon.CELL_W}x{canon.CELL_H} без остатка")
    cols, rows = width // canon.CELL_W, height // canon.CELL_H

    canon_grid = canon.grid()
    canon_walk = canon.rules()["walk"]
    land_bit, sea_bit = canon.MASK_LAND, canon.MASK_SEA

    # Сетка донора и её посадка на общую карту — тем же сдвигом, каким
    # переносятся его локации (замерен по картинкам, konung2/donor.py).
    his_terrain = donor.world_terrain() if donor.available() else None
    his_row0, his_col0 = donor.DONOR_WORLD_AT

    def donor_cell(row: int, col: int):
        """Местность и сцена донора для клетки общей карты; нет — None."""
        if his_terrain is None:
            return None
        r, c = row - his_row0, col - his_col0
        if not (0 <= r < len(his_terrain) and 0 <= c < len(his_terrain[r])):
            return None
        return his_terrain[r][c]

    cells: list[list[int]] = []
    walk: list[list[int]] = []
    inherited = 0
    for row in range(rows):
        cell_row, walk_row = [], []
        for col in range(cols):
            inside = (CANON_ROW <= row < CANON_ROW + canon.ROWS and
                      CANON_COL <= col < CANON_COL + canon.COLS)
            if inside:
                # Канон переезжает БЕЗ ИЗМЕНЕНИЙ: и клетка, и маска.
                cell_row.append(canon_grid[row - CANON_ROW][col - CANON_COL])
                walk_row.append(canon_walk[row - CANON_ROW][col - CANON_COL])
                inherited += 1
                continue
            land = warm(image, row, col) > WARM_THRESHOLD
            kind = LAND_KIND if land else SEA_KIND
            scene = 0
            # ЗЕМЛЯ ДОНОРА ЗВУЧИТ ЕГО ЗАСАДАМИ. Там, где общая карта накрывает
            # его сетку, местность и место боя берутся у него, а не гадаются
            # по цвету: иначе на его земле выпадали бы канонные отряды и
            # канонные сцены — та самая «засада ведёт не туда». Вид местности
            # сдвигается на DONOR_TERRAIN_BASE, сцена — это ЕГО номер карты,
            # у нас она 150 + номер.
            his = donor_cell(row, col)
            if his is not None:
                his_kind, his_scene = his
                kind = donor.DONOR_TERRAIN_BASE + his_kind
                # НОМЕР ЕГО КАРТЫ ПЕРЕВОДИТСЯ ТАБЛИЦЕЙ, А НЕ СДВИГОМ: у карт
                # 1 и 2 есть наши двойники (26 «Корабль в пути» и 27 «Бой на
                # корабле»), и они ввезены не были. Со сдвигом 221 клетка его
                # моря указывала бы на карту 151, которой в паке нет.
                if his_scene:
                    scene = donor.our_map_number(his_scene)
            # Новая клетка: локации нет, тумана нет.
            cell_row.append((kind << TERRAIN) | (scene << SCENE))
            mask = land_bit if land else sea_bit
            if (row, col) in FORDS:
                mask = land_bit | sea_bit
            walk_row.append(mask)
        cells.append(cell_row)
        walk.append(walk_row)

    rules = canon.rules()
    # Всё, что не про размер и не про картинку, канон отдаёт как есть:
    # флаги тумана, сцены, виды местности, скорость похода, значки, имена,
    # построение отряда, бродячие отряды, прибытия и спрайты.
    rules.update({
        "rows": rows,
        "cols": cols,
        # УГОЛ СЕТКИ ВНУТРИ КАРТИНКИ, а не на экране. У канона он равен
        # (0xA7 - panel_width, 0x19) = (27, 25); у нарисованной карты сетка
        # начинается прямо с левого верхнего угла.
        "origin": [0, 0],
        "grid": cells,
        "walk": walk,
        "picture": {"path": "assets/worldmap/map.png",
                    "width": width, "height": height},
        # Переключатель канон/расширение живёт в самих данных: одно слово
        # здесь возвращает игру на канонную сетку 32x24 без правки кода.
        "enabled": True,
        "policy": "project_extended_over_konung2_exe_0x460174",
        "canon_at": [CANON_ROW, CANON_COL],
    })
    print(f"сетка {cols}x{rows}, канонных клеток перенесено {inherited} "
          f"из {canon.ROWS * canon.COLS}")
    land_cells = sum(1 for r in walk for v in r if v & land_bit)
    print(f"суши {land_cells}, моря {rows * cols - land_cells}")
    return rules


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    picture = Path(sys.argv[1])
    rules = build(picture)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # Пересборка из уже лежащей здесь картинки — обычное дело: она и есть
    # часть набора. Копировать файл сам в себя не надо, а падать тем более.
    if picture.resolve() != (OUT_DIR / "map.png").resolve():
        shutil.copyfile(picture, OUT_DIR / "map.png")
    target = OUT_DIR / "world.json"
    target.write_text(json.dumps(rules, ensure_ascii=False), encoding="utf-8")
    print(f"-> {target} ({target.stat().st_size} байт)")
    print(f"-> {OUT_DIR / 'map.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
