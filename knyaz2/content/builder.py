"""Сборка браузерного content pack из редактируемого проекта и ресурсов игры."""
from __future__ import annotations

import hashlib
import json
import random
import os
import shutil
import struct
import tempfile
from pathlib import Path
from typing import Any, Iterable

from konung2.graph import (ANIMATED_TILE_SIZE, ANIMATED_WAVE_PERIOD, GROUND_ROWS,
                           GROUND_STRIDE, LIGHT_FROM_TICK, NIGHT_LEVEL_BLUE,
                           NIGHT_LEVEL_GREEN, NIGHT_LEVEL_RED, TILE_HEIGHT,
                           TILE_ODD_SHIFT, TILE_STEP_X, TILE_STEP_Y, TILE_WIDTH,
                           GraphRes, cell_position, fixed_light, fixed_light_map,
                           ground_cells, read_light_masks)
from konung2.grid import CELL_H, CELL_W
from konung2.interf import (BELT, BELT_ARROWS, BUTTON_ACTIONS, BUTTON_SPRITES,
                            CELL_SPRITE, EQUIPMENT_WINDOW, FRAME_BOTTOM,
                            FRAME_SPRITE, HEALTH_BAR, PANEL_WIDTH, PORTRAIT_BASE,
                            SCREEN, STANCE_SPRITES, VIEW_HEIGHT, VIEW_WIDTH,
                            WEAPON_FACES, WEAPON_FACE_FAMILIES, InterfRes,
                            EPITHET_CHARACTERISTICS, EPITHET_STEP,
                            character_screen, epithets, panel_rects, slot_rects)
from konung2.items import (BAG_SLOTS, GROUND_PILE_SPRITE, REQUIREMENT_STATS,
                           SLOT_FIELDS, ItemClass, read_items, tooltip_strings)
#: Первый хвостовой класс каталога — донорские сюжетные вещи (211+).
from konung2.donor import PROJECT_ITEM_BASE as DONOR_ITEM_BASE
from konung2.world import Building, Cell, Entity, MapModel
from konung2.kn2 import (GRID_H, GRID_W, KN2Map, SEC_FLAG, T_DYNAMIC, T_LIGHT,
                         interior_slots)
from konung2.paths import BUILD_DIR, PROJECT_DIR, game_file
from konung2.progress import CHARACTERISTICS
from konung2.progress import rules as progression_rules
from konung2.trade import rules as trade_rules
from konung2.combat import rules as accuracy_rules
from konung2.effects import (EMPTY_JAR_CLASS, POTION_WISDOM,
                             rules as effect_rules)
from konung2.buildings import rules as building_rules
from konung2.carry import rules as carry_rules
from konung2.jewellery import rules as jewellery_rules
from konung2.craft import rules as craft_rules
from konung2.piles import rules as pile_rules
from konung2.orders import rules as order_rules
from knyaz2.content.atlas import AtlasWriter
from konung2.orders import SELECTION_SPRITES
from konung2.heroes import (beast_move_ticks, gait_steps, move_block_ticks,
                            ANCHOR_X as HERO_ANCHOR_X,
                            ANCHOR_Y as HERO_ANCHOR_Y)
from konung2.cells import rules as cell_rules
from konung2.creatures import rules as creature_rules
from konung2.worldmap import MAP_SPRITE, PARTY_SPRITE, PLAYER_SPRITE
from konung2.worldmap import encounter_templates
from konung2.worldmap import markers as world_markers
from . import worldmap as worldmap_pack
from .locations import LEGEND as LEGEND_MARKER, MARKER_GAME
from .locations import markers as location_markers
from .locations import registry as location_registry
from .objects import catalogue as object_catalogue, missing_slots
from konung2.res import ObjectsRes, read_palettes
from konung2.heroes import (ACTION_BLOCKS, CROSSBOW_GROUP, DEATH_VARIANTS,
                            DIRECTION_STEPS, DIRECTIONS,
                            IDLE_CHANCE, LAYER_AT_REST, LAYER_IN_HAND,
                            LAYER_OFF_HAND, LAYER_OFF_REST, LAYER_SHIELD_BACK,
                            SHIELD_KIND, STANCE_BLOCKS, TWO_HAND_GROUP,
                            HeroesRes, draw_script)
from . import audio as audio_assets
from .schema import ContentManifest, ContentMap, PackedFile


PACK_MARKER = ".knyaz2-content-pack"
#: Схема документа карты: 0.2 — сущностная (buildings/props/terrain).
CONTENT_MAP_SCHEMA = "0.2"
DEFAULT_CONTENT_ID = "konung2-base"
ITEM_REF_PREFIX = "class:"
INSTANCE_REF_PREFIX = "instance:"


def _item_ref(item: ItemClass | int) -> str:
    """Устойчивый ключ класса предмета; имя остаётся только подписью UI."""
    index = item.index if isinstance(item, ItemClass) else int(item)
    return f"{ITEM_REF_PREFIX}{index}"


def _instance_ref(item: ItemClass | int, identity: str) -> str:
    """Ссылка на конкретную запись предмета с доступным в ней классом."""
    index = item.index if isinstance(item, ItemClass) else int(item)
    return f"{INSTANCE_REF_PREFIX}{index}:{identity}"


def _game_item_ref(item: ItemClass | int, record: int | None,
                   world: int = 0, origin: str = "game") -> str:
    """Канонический экземпляр GAME.x; fallback класса — для старых данных.

    ``origin`` разводит пространства экземпляров двух игр: запись №5 из
    нашего GAME.1 и из его game.1 — разные предметы, и под общим ключом
    ``game:1:5`` они бы слиплись. Донорские живут под ``legend:<мир>:<№>``.
    """
    if record:
        return _instance_ref(item, f"{origin}:{world}:{int(record)}")
    return _item_ref(item)



class ContentBuildError(RuntimeError):
    """Content pack нельзя безопасно или корректно собрать."""


def donor_tiles_boundary() -> int:
    """Последний тайл, которым владеет канон (konung2/donor.py)."""
    from konung2 import donor
    return donor.CANON_LAST_TILE


class _AssetExporter:
    """Картинки пака. У каждой карты СВОЯ игра-источник.

    ГНЁЗДА И ПЛИТКИ ОДНОГО НОМЕРА У ДВУХ ИГР — РАЗНЫЕ КАРТИНКИ. Прежде
    донорские карты рисовались нашим OBJECTS.RES и нашим GRAPH.RES: сверка
    мерила заголовки записей (вид, число кадров, группа) и решила, что
    каталоги «слот в слот». Побайтная сверка это опровергает — совпадает
    112 гнёзд из 480, 218 палитр из 256 и 126 плиток земли из 362. Отсюда
    и приходили жалобы: кусок канонного Дворца Повелителя в порту Тиграта
    (его гнездо 314 — портовые своды), чёрные навесы и пятна земли, дома
    без крыш (слои чужого варианта не совпадают) и цветная рябь на
    частоколе с печью (палитра не та).

    Перенумеровать нельзя: номер плитки лежит в карте БАЙТОМ, а палитра —
    смещением в блоке из 256 записей. Поэтому источник выбирается по игре
    карты, а имя файла несёт приставку — картинки двух игр под одним
    номером живут рядом и не затирают друг друга.
    """

    #: Приставка к имени файла для карт «Продолжения легенды».
    LEGEND_PREFIX = "legend_"

    def __init__(self, root: Path) -> None:
        self.root = root
        self.canon_graph = GraphRes.from_game()
        # Каталог объектов с продолжением: гнёзда 30..509 наши, 510..587 —
        # из «Продолжения легенды», если оно установлено. Решает
        # knyaz2/content/objects.py, здесь только берём готовое.
        self.canon_objects = object_catalogue()
        self.canon_palettes = read_palettes()
        #: Чью графику берём сейчас: None — канон, иначе имя игры донора.
        self.game: str | None = None
        self.ground_cache: dict[tuple[Any, ...], str | None] = {}
        self.underlay_cache: dict[tuple[Any, ...], dict[str, Any] | None] = {}
        self.overlay_cache: dict[tuple[Any, ...], dict[str, Any] | None] = {}
        self.object_cache: dict[tuple[Any, ...], dict[str, Any] | None] = {}
        self.light_cache: dict[tuple[Any, ...], str | None] = {}
        self.light_masks: list[bytes] | None = None
        self._object_index_cache: dict[str, Any] | None = None
        self._object_index_dirty = False
        #: Источники донора — лениво: без установленной игры их просто нет.
        self._donor_graph_cache: Any = False
        self._donor_objects_cache: Any = False
        self._donor_palettes_cache: Any = False

    def select(self, game: str | None) -> None:
        """Чью графику брать дальше. Зовётся на каждую карту перед вывозом."""
        from konung2 import donor as donor_module
        self.game = game if game and donor_module.available() else None

    #: Паспорт разобранных объектов: ключ -> геометрия и пути. Разбор одного
    #: объекта со всеми слоями стоит четверть секунды, картинки при этом от
    #: сборки к сборке те же — держим их геометрию рядом с ними.
    OBJECT_INDEX = Path("assets") / "objects" / "index.json"

    @staticmethod
    def _object_key(key: tuple[Any, ...]) -> str:
        game, slot, palette, state = key
        return f"{game or 'canon'}:{slot}:{palette}:{state}"

    def _object_index(self) -> dict[str, Any]:
        if self._object_index_cache is None:
            path = self.root / self.OBJECT_INDEX
            try:
                self._object_index_cache = json.loads(
                    path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._object_index_cache = {}
        return self._object_index_cache

    def _object_files_ready(self, entry: dict[str, Any]) -> bool:
        paths = [entry.get("path")]
        paths += [layer.get("path")
                  for layer in (entry.get("layers") or {}).values()]
        return all(name and (self.root / name).is_file() for name in paths)

    def flush_object_index(self) -> None:
        """Записать паспорт объектов рядом с картинками."""
        if not self._object_index_dirty:
            return
        path = self.root / self.OBJECT_INDEX
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self._object_index(), ensure_ascii=False),
                        encoding="utf-8")
        self._object_index_dirty = False

    @property
    def legend(self) -> bool:
        return self.game is not None

    @property
    def prefix(self) -> str:
        return self.LEGEND_PREFIX if self.legend else ""

    @property
    def graph(self):
        theirs = self._donor_graph() if self.legend else None
        return theirs if theirs is not None else self.canon_graph

    @property
    def objects(self):
        theirs = self._donor_objects() if self.legend else None
        return theirs if theirs is not None else self.canon_objects

    @property
    def palettes(self):
        theirs = self._donor_palettes() if self.legend else None
        return theirs if theirs is not None else self.canon_palettes

    def _donor_graph(self):
        if self._donor_graph_cache is False:
            from konung2 import donor as donor_module
            try:
                self._donor_graph_cache = (donor_module.graph()
                                           if donor_module.available() else None)
            except OSError:
                self._donor_graph_cache = None
        return self._donor_graph_cache

    def _donor_objects(self):
        if self._donor_objects_cache is False:
            from konung2 import donor as donor_module
            try:
                self._donor_objects_cache = (donor_module.objects()
                                             if donor_module.available() else None)
            except OSError:
                self._donor_objects_cache = None
        return self._donor_objects_cache

    def _donor_palettes(self):
        if self._donor_palettes_cache is False:
            from konung2 import donor as donor_module
            try:
                self._donor_palettes_cache = (
                    read_palettes(donor_module.graph_palette_block())
                    if donor_module.available() else None)
            except OSError:
                self._donor_palettes_cache = None
        return self._donor_palettes_cache

    def ground(self, lower: int | None, upper: int | None,
               light: int | None) -> str | None:
        # Browser-0 is the daylight/static renderer. VA 0x424FD8 uses the
        # ordinary two-draw path unless both runtime lighting flags are set;
        # the KN2 light-mask id is exported as metadata for that future state.
        key = (self.game, lower, upper, None)
        if key in self.ground_cache:
            return self.ground_cache[key]

        sprite = self.graph.compose_cell(lower, upper)

        if sprite is None:
            self.ground_cache[key] = None
            return None

        name = self.prefix + "_".join(
            "none" if value is None else str(value) for value in key[1:]) + ".png"
        relative = Path("assets") / "ground" / name
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.is_file():
            sprite.save(str(path))
        result = relative.as_posix()
        self.ground_cache[key] = result
        return result

    def light_glow(self, lower: int | None, upper: int | None,
                   light: int | None) -> str | None:
        """Прибавка локального света для клетки — проход VA 0x43FD70.

        Закон снят с КОДА, а не подобран. Освещённую клетку движок рисует той
        же парой тайлов, но выбирает канальные таблицы по байту маски:

            синий    [0x58E2C4]                       — маска не влияет
            зелёный  0x476AD0[m] по компоненте 0x476A50  (VA 0x43FEB0)
            красный  0x49D0AC[m] по компоненте 0x49D02C  (VA 0x43FEC6)

        Массивы строятся при каждой отрисовке земли (VA 0x44283A, 0x442865):
        строка m — это таблица «минус» для уровня ``уровень канала + m``,
        а неотрицательный уровень даёт строку 0, то есть дневную яркость.
        Компонента перед этим осветляется «плюсом» мерцания (VA 0x442890,
        значения 8..11 зелёному и 16..23 красному, VA 0x428628). При m = 0
        движок идёт обычной веткой (VA 0x43FEAE) — там ни плюса, ни сдвига
        уровня, поэтому у ауры нет края.

        В пак пишется РАЗНОСТЬ «с маской минус без маски»: клиент кладёт её
        поверх собранного кадра сложением (``lighter``). При m = 0 разность
        равна нулю, значит тёмной каймы у ауры не возникает в принципе, а
        главный член разности (m/100 * компонента) от времени суток не зависит.
        """
        if light is None:
            return None
        key = (self.game, lower, upper, light)
        if key in self.light_cache:
            return self.light_cache[key]
        if self.light_masks is None:
            self.light_masks = read_light_masks()
        if not 0 <= light < len(self.light_masks):
            self.light_cache[key] = None
            return None
        sprite = self.graph.light_delta_cell(lower, upper, self.light_masks[light])
        if sprite is None:
            self.light_cache[key] = None
            return None
        name = f"{self.prefix}{'none' if lower is None else lower}_" \
               f"{'none' if upper is None else upper}_{light}.png"
        relative = Path("assets") / "light" / name
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        sprite.save(str(path))
        result = relative.as_posix()
        self.light_cache[key] = result
        return result

    def underlay(self, tile: int, horizontal_scroll: bool) -> dict[str, Any] | None:
        """Export the first frame of the .KN2 animated 256x256 underlay."""
        key = (self.game, tile, horizontal_scroll)
        if key in self.underlay_cache:
            return self.underlay_cache[key]
        sprite = self.graph.animate_underlay(
            tile, wave_phase=1, scroll_phase=1,
            horizontal_scroll=horizontal_scroll,
        )
        if sprite is None:
            self.underlay_cache[key] = None
            return None
        suffix = "scroll" if horizontal_scroll else "fixed"
        relative = (Path("assets") / "underlay" /
                    f"{self.prefix}{tile}_phase1_{suffix}.png")
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        sprite.save(str(path))
        result = {
            "path": relative.as_posix(),
            "width": sprite.width,
            "height": sprite.height,
            "wave_phase": 1,
            "scroll_phase": 1 if horizontal_scroll else 0,
        }
        source = self.graph.decode_tile(tile)
        if source is not None and source.width == ANIMATED_TILE_SIZE \
                and source.height == ANIMATED_TILE_SIZE:
            source_relative = (Path("assets") / "underlay" /
                               f"{self.prefix}{tile}_source.png")
            source.save(str(self.root / source_relative))
            # The client replays VA 0x43F46E/0x43F4D9 exactly: remap the
            # source through the sine displacement table each frame and
            # advance both phases by one per engine tick.
            result["animation"] = {
                "source": source_relative.as_posix(),
                "wave_period": ANIMATED_WAVE_PERIOD,
                "horizontal_scroll": horizontal_scroll,
                "displacement": "trunc((sin(i*2*3.14159/128)+1)*524288) >> 16, i in 0..255",
            }
        self.underlay_cache[key] = result
        return result

    def terrain_overlay(self, resource_slot: int) -> dict[str, Any] | None:
        """Export a GRAPH.RES frame used by the first 12-byte map table."""
        key = (self.game, resource_slot)
        if key in self.overlay_cache:
            return self.overlay_cache[key]
        sprite = self.graph.decode_tile(resource_slot)
        # ПЛИТКИ СВЕРХ НАШЕГО КАТАЛОГА — ИЗ ДОНОРА. Его годные тайлы идут до
        # 410 против наших 361, и в хвосте живёт обстановка его домов; без
        # дозаписи 88 гнёзд Кирингхольма оставались без картинки. На его
        # картах весь GRAPH.RES и так его (см. select), эта ветка нужна
        # канонной карте, если она когда-нибудь сошлётся на хвост.
        if sprite is None and resource_slot > donor_tiles_boundary():
            theirs = self._donor_graph()
            if theirs is not None:
                sprite = theirs.decode_tile(resource_slot)
        if sprite is None:
            self.overlay_cache[key] = None
            return None
        relative = (Path("assets") / "terrain_overlays" /
                    f"{self.prefix}{resource_slot}.png")
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        sprite.save(str(path))
        result = {
            "path": relative.as_posix(),
            "width": sprite.width,
            "height": sprite.height,
        }
        self.overlay_cache[key] = result
        return result

    def object(self, resource_slot: int, palette_index: int,
               state: int = 0) -> dict[str, Any] | None:
        key = (self.game, resource_slot, palette_index, state)
        if key in self.object_cache:
            return self.object_cache[key]
        # ГОТОВОЕ НЕ ПЕРЕРИСОВЫВАЕМ. Разбор одного объекта со всеми слоями
        # стоит четверть секунды, а на крупной карте их под тысячу — вместе
        # это минуты на каждой сборке, хотя картинка та же самая. Рядом с
        # картинками лежит паспорт: если файлы на месте и геометрия
        # записана, декодировать нечего.
        ready = self._object_index().get(self._object_key(key))
        if ready is not None and self._object_files_ready(ready):
            self.object_cache[key] = ready
            return ready
        if not 0 <= resource_slot < len(self.objects.entries):
            self.object_cache[key] = None
            return None
        if self.objects.entries[resource_slot] is None:
            self.object_cache[key] = None
            return None

        if not 0 <= palette_index < len(self.palettes):
            palette_index = 0
        sprite, dx, dy = self.objects.decode_building(
            resource_slot, self.palettes[palette_index], state=state)
        if sprite is None:
            self.object_cache[key] = None
            return None

        relative = (Path("assets") / "objects" /
                    f"{self.prefix}{resource_slot}_{palette_index}_{state}.png")
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        sprite.save(str(path))
        result = {
            "path": relative.as_posix(),
            "width": sprite.width,
            "height": sprite.height,
            "offset_x": dx,
            "offset_y": dy,
        }
        layers: dict[str, dict[str, Any]] = {}
        for name, (layer, layer_dx, layer_dy) in self.objects.decode_building_layers(
                resource_slot, self.palettes[palette_index], state=state).items():
            layer_relative = (
                Path("assets") / "objects" /
                f"{self.prefix}{resource_slot}_{palette_index}_{state}_{name}.png")
            layer_path = self.root / layer_relative
            layer_path.parent.mkdir(parents=True, exist_ok=True)
            layer.save(str(layer_path))
            layers[name] = {
                "path": layer_relative.as_posix(),
                "width": layer.width,
                "height": layer.height,
                "offset_x": layer_dx,
                "offset_y": layer_dy,
            }
        result["layers"] = layers
        # Ключ глубины и правило палитры живут на сущности (konung2.world):
        # здесь только картинки и их геометрия.
        self.object_cache[key] = result
        self._object_index()[self._object_key(key)] = result
        self._object_index_dirty = True
        return result


def build_content_pack(map_numbers: Iterable[int], output: str | Path,
                       project_dir: str | Path = PROJECT_DIR,
                       content_id: str = DEFAULT_CONTENT_ID) -> ContentManifest:
    """Атомарно собрать content pack и вернуть его манифест."""
    numbers = tuple(sorted(set(int(number) for number in map_numbers)))

    project = Path(project_dir).resolve()
    destination = Path(output).resolve()
    _validate_destination(destination, project)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # БЕЗ КАРТ — ТОЛЬКО ПОВЕРХ ГОТОВОГО ПАКА. Правки в правилах (они лежат в
    # одном shared.json) не трогают ни одной карты, а полный проход по ним
    # стоит часы: ради одного поля мы гоняли 140 карт и 15 тысяч файлов.
    # Всё, что для этого нужно, у сборщика уже есть — частичная сборка сливает
    # карты из прежнего манифеста и не переназначает стартовую, — не хватало
    # только разрешения на пустой список.
    #
    # На чистом месте карты по-прежнему обязательны: пак без них не пак.
    if not numbers and not (destination / PACK_MARKER).is_file():
        raise ContentBuildError("не указано ни одной карты")

    # Пересобирать пак целиком ради правки одного числа — это десять минут и
    # 12 тысяч файлов туда-обратно. Если по этому пути уже лежит наш пак,
    # пишем прямо в него: имена файлов детерминированы, поэтому «собрать
    # заново» и «переписать поверх» дают один и тот же результат.
    in_place = (destination / PACK_MARKER).is_file()
    stage = destination if in_place else Path(tempfile.mkdtemp(
        prefix=f".{destination.name}.stage-", dir=destination.parent))
    try:
        (stage / PACK_MARKER).write_text("generated content pack\n", encoding="utf-8")
        assets = _AssetExporter(stage)
        # Прежний пак — источник готовых Opus: при чистом stage совпавшие
        # по sha исходного PCM файлы переносятся, а не кодируются заново.
        previous = destination if destination.is_dir() else None
        audio = audio_assets.export_pack_audio(stage, previous=previous)
        audio_assets.export_voice_lines(stage, previous=previous)
        daylight = _export_daylight(stage)
        # Встречные отряды приписаны к несуществующим «картам» 100…140, и
        # их бойцов надо одеть так же, как жителей: иначе в пути на нас
        # выйдет невидимка.
        encounters = _encounter_numbers()
        # ОБЩИЕ АССЕТЫ СЧИТАЮТСЯ ПО ВСЕМУ ПАКУ, А НЕ ПО СОБИРАЕМЫМ КАРТАМ.
        # Кадры тел, слои снаряжения и наборы тварей лежат в shared.json
        # одним списком на всю игру, и списки эти собираются по картам.
        # Пока брались только карты текущего вызова, пересборка одной карты
        # ВЫКИДЫВАЛА чужие наборы: после `--map 19` в паке оставалось 14
        # наборов тел из 72, и жители прочих карт теряли облик. Берём
        # объединение: собираемые карты плюс те, что уже лежат в паке.
        shared_numbers = _pack_map_numbers(destination, numbers)
        # Вклад КАЖДОЙ карты в эти четыре списка помнится рядом с паком
        # (SCENARIO_INDEX): пересборка одной карты не перечитывает жителей
        # остальных ста сорока по всем мирам выбора.
        (layers, body_palettes, body_shapes, body_pairs,
         creature_sets) = _shared_inputs(
            project, shared_numbers, encounters,
            destination if destination.is_dir() else None)
        hero = _export_hero(stage, layers, body_palettes, body_shapes,
                            body_pairs,
                            reuse=destination if destination.is_dir() else None,
                            project=project)
        # Расширенная карта мира приходит картинкой из проекта, а не спрайтом
        # INTERF.RES: копируем её рядом с правилами, куда указывает `picture`.
        _export_world_picture(project, stage)
        # Стартовое состояние героя — запись юнита №0 из GAME.0 (уровень,
        # характеристики, навыки, снаряжение, деньги, отряд). Оно одно на
        # весь пак и потому живёт рядом с кадрами в shared.json.
        # ВЫБОР ПЕРСОНАЖА — ЭТО ВЫБОР МИРА. «Новая игра» в движке открывает
        # GAME.<номер> и читает оттуда запись юнита 0 прямо в героя:
        #   FUN_00443211(файл, 0x46322, 0);            // к массиву юнитов
        #   FUN_00442fdc(файл, _DAT_0084951c, 0x100);  // запись героя
        #   FUN_00442c10(0x8442d8, 0, 6);              // счётчики характеристик
        #   FUN_00442c10(0x8442e0, 0, 0x14);           // счётчики навыков
        # (VA 0x4387CC). Шесть миров — шесть разных героев, и у каждого СВОЯ
        # стартовая карта: 0 → 33, 1 → 19 (Чёрный Бор), 2 → 23, 3 → 37,
        # 4 → 45, 5 → 1. Поэтому экран выбора решает не только, кем играть,
        # но и где начинать.
        hero = {**hero, "template": _hero_template(), "starts": _custom_hero_choices(project, _hero_choices()),
                # экран создания: фон и портреты из NEWHERO.RES, разметка из exe
                "creation": _export_creation(stage)}
        # ОБЩЕЕ — ОДИН РАЗ. Кадры героя, слои снаряжения и наборы тварей
        # одинаковы на всех картах: раньше они лежали в КАЖДОМ map.json и
        # весили там 9 МБ из 10. Теперь они выносятся в один файл, который
        # клиент тянет однажды, а карта остаётся при своём.
        creatures = _export_creatures(stage, creature_sets, reuse=previous)
        # Свои наборы подшиваются ПОСЛЕ канонных и мимо паспорта кадров:
        # тот считается по OBJECTS.RES, и своего набора там нет, а значит
        # готовый пак переиспользуется как обычно.
        creatures = _custom_creatures(stage, project, creatures)
        # Свои снаряды — тем же слоем, что и свои твари, и рядом с ними.
        projectiles = _custom_projectiles(stage, project)
        weather = _custom_weather(stage, project)
        shared = {"schema_version": CONTENT_MAP_SCHEMA,
                  "hero": hero, "creatures": creatures,
                  # Палитры обеих игр картинкой: цвет для бесцветных слоёв
                  # подставляет клиент (docs/INDEXED_UNITS_PLAN.md).
                  "palettes": _export_palettes(stage),
                  # СОСТОЯНИЕ ВСЕХ ПОСЕЛЕНИЙ, А НЕ ТОЛЬКО ПОСЕЩЁННЫХ.
                  "settlements": _settlements_index(project),
                  # Цены убийства для репутации — механика «Продолжения
                  # легенды», которой у канона нет (konung2/reputation.py).
                  "reputation": _reputation_rules(),
                  # Кадры огней на объектах (konung2/objectanim.py; кадры —
                  # выверенный вход project/fire_frames, провенанс в модуле).
                  "effects": _effects_rules(stage)}
        if projectiles:
            shared["projectiles"] = projectiles
        if weather:
            shared["weather"] = weather
        _write_json(stage / "shared.json", shared)
        maps = tuple(_export_map(number, project, stage, assets, audio, daylight,
                                 hero)
                     for number in numbers)
        # Паспорт разобранных объектов — рядом с картинками, до описи файлов.
        assets.flush_object_index()
        files = _collect_files(stage)
        # Откуда начинать без выбора персонажа. Стартовых клеток шесть, по
        # одной на мир; берём мир 0, а если ЕГО КАРТЫ В ПАКЕ НЕТ — первый
        # мир, чья карта собрана.
        #
        # Раньше здесь стоял просто `next(... world == 0, None)`, и при
        # неполном паке поле уезжало в null. Клиент в этом случае берёт
        # первую карту манифеста, то есть карту 1 «Дворец Повелителя», —
        # ровно та поломка, от которой предостерегает комментарий в boot().
        packed = {number: (_hero_start(number) or {}).get("world")
                  for number in numbers}
        start_map = next((number for number, world in packed.items()
                          if world == 0), None)
        # ЧАСТИЧНАЯ СБОРКА НЕ ТЕРЯЕТ ЧУЖИХ КАРТ. При правке поверх живого
        # пака манифест раньше писался только с картами текущего вызова:
        # пересборка одной карты оставляла игру «с одной картой», и полный
        # список чинила лишь следующая полная сборка. Файлы каталога
        # _collect_files и так собирает все — сливаем и список карт.
        if in_place:
            previous_manifest = destination / "manifest.json"
            if previous_manifest.is_file():
                try:
                    old = ContentManifest.from_dict(json.loads(
                        previous_manifest.read_text(encoding="utf-8")))
                    fresh = {item.legacy_number for item in maps}
                    kept = tuple(item for item in old.maps
                                 if item.legacy_number not in fresh
                                 and (destination / item.path).is_file())
                    maps = tuple(sorted(maps + kept,
                                        key=lambda item: item.legacy_number))
                    # СТАРТОВУЮ ЧАСТИЧНАЯ СБОРКА НЕ ПЕРЕНАЗНАЧАЕТ. Запасная
                    # ветка «первая карта с героем» ниже честна для новой
                    # сборки, но при правке одной карты она отдавала ИМЕННО
                    # ЭТУ карту: после `--map 19` в манифесте оказалось 19
                    # вместо Борья 33, и «Новая игра» без выбора начиналась
                    # в Чёрном Бору.
                    if start_map is None:
                        start_map = old.start_map
                except (ValueError, OSError):
                    pass
        if start_map is None:
            start_map = next((number for number, world in packed.items()
                              if world is not None), None)
        manifest = ContentManifest(content_id=content_id, maps=maps, files=files,
                                   start_map=start_map)
        _write_json(stage / "manifest.json", manifest.to_dict(), pretty=True)
        if not in_place:
            _publish(stage, destination)
        return manifest
    except Exception:
        if not in_place and stage.exists():
            shutil.rmtree(stage)
        raise


#: Что редактору можно трогать у реквизита: палитра, состояние
#: (лестница построек), позиция и рамка отрисовки. Позиция и рамка
#: правятся ВМЕСТЕ — сборка предвычисляет draw_x/draw_y, и перенос
#: обязан сдвинуть обе, иначе картинка разъедется с точкой.
EDITOR_PROP_FIELDS = frozenset({"palette", "state", "removed"})
EDITOR_PROP_DICTS = frozenset({"position", "bounds"})


def _editor_props_apply(props: list, patches: dict,
                        added: list) -> list:
    """Реквизит карты с правками редактора."""
    out = []
    for prop in props:
        patch = patches.get(prop.get("id"))
        if patch:
            if patch.get("removed"):
                continue
            for key, value in patch.items():
                if key in EDITOR_PROP_FIELDS and key != "removed":
                    prop[key] = value
                elif key in EDITOR_PROP_DICTS and isinstance(value, dict):
                    target = prop.setdefault(key, {})
                    if isinstance(target, dict):
                        target.update(value)
        out.append(prop)
    for entry in added:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        out.append({"kind": "prop", "state": 0, **entry})
    return out


#: Что редактору можно трогать у кучи. `items` и `details` пишутся
#: ЦЕЛИКОМ (панель шлёт оба списка разом — они параллельны, и латать их
#: поштучно значило бы разъехаться), `removed` выкидывает кучу.
EDITOR_LOOT_FIELDS = frozenset({"money", "buried", "items", "details",
                                "removed"})
EDITOR_LOOT_DICTS = frozenset({"cell"})

#: Что редактору можно трогать у ОТРЯДА. Плоские поля пишутся как есть,
#: зоны сливаются по ключам — чтобы правка «сдвинуть верхнюю границу»
#: не съедала остальные три числа прямоугольника.
#: `side` в список НЕ входит: это ключ записи и он же номер стороны
#: юнитов (gamefile.map_parties), сменив его, мы оторвали бы отряд от
#: собственных бойцов.
EDITOR_WARBAND_FIELDS = frozenset({
    "war_flags", "on_player", "on_parties", "on_special",
    "only_if_fighting", "can_fight", "enemy_side", "fighting", "player",
})
EDITOR_WARBAND_DICTS = frozenset({"zone", "roam"})

#: Что редактору можно трогать у ПОСЕЛЕНИЯ. Зеркало server.ДЕРЕВНЯ_ПОЛЯ.
#: Номера жителей (master/officials/people) и сторона деревни сюда не
#: входят: первые — индексы юнитов, на которых держится маршрутизация
#: разговоров, вторая — ключ, которым движок индексирует таблицу отрядов.
EDITOR_VILLAGE_FIELDS = frozenset({
    "owned", "owner", "wealth", "status", "flags", "treasury",
    "slots_a", "slots_b",
})
EDITOR_VILLAGE_BUILDING = frozenset({"built", "state", "object"})


def _editor_village_apply(record: dict, patch: dict) -> None:
    """Наложить правки редактора на запись поселения, на месте.

    Постройки адресуются СЛОТОМ, а не местом в списке: слот — это номер
    места в деревне (первые семь особые), и он же лежит в записи
    постройки на карте (`village_slot`). Порядок в списке — дело сборки.
    """
    if not isinstance(record, dict) or not isinstance(patch, dict):
        return
    for key, value in patch.items():
        if key == "buildings" and isinstance(value, dict):
            spots = {int(p_.get("slot", -1)): p_
                     for p_ in record.get("buildings") or []}
            for slot, edit in value.items():
                at = spots.get(int(slot))
                if at is None or not isinstance(edit, dict):
                    continue
                for name, zn in edit.items():
                    if name in EDITOR_VILLAGE_BUILDING:
                        at[name] = zn
        elif key in EDITOR_VILLAGE_FIELDS:
            record[key] = value


def _editor_loot_apply(piles: list, patches: dict,
                       added: list) -> list:
    """Кучи мира с применёнными правками редактора."""
    out = []
    for pile in piles:
        patch = patches.get(pile.get("id"))
        if patch:
            if patch.get("removed"):
                continue
            for key, value in patch.items():
                if key in EDITOR_LOOT_FIELDS and key != "removed":
                    pile[key] = value
                elif key in EDITOR_LOOT_DICTS and isinstance(value, dict):
                    target = pile.setdefault(key, {})
                    if isinstance(target, dict):
                        target.update(value)
            if pile.get("items"):
                pile["item"] = pile["items"][0]
        out.append(pile)
    for entry in added:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        pile = {"on_floor": True, "buried": False, "money": 0,
                "details": [], **entry}
        pile.setdefault("items", [])
        if pile["items"]:
            pile.setdefault("item", pile["items"][0])
        # У куч из KN2 позиция лежит в самой записи; кучам редактора её
        # считаем из шаговой клетки (без позиции клиент падал на входе:
        # lootSetup читает entry.position.x). Ось Y у куч — в ПОЛУСТРОКАХ
        # по канону данных: у куч 19-й карты pos.y = row*16+16 при том же
        # 32-пиксельном номере строки (рендер удваивает при выводе).
        cell = pile.get("cell") or {}
        if "position" not in pile and cell:
            row, col = int(cell.get("row", 0)), int(cell.get("col", 0))
            pile["position"] = {
                "x": col * 58 + (29 if row % 2 else 58),
                "y": row * 16 + 16,
            }
        out.append(pile)
    return out


#: Что редактору можно трогать у юнита. Плоские поля пишутся как есть,
#: словарные (stats, characteristics, cell) сливаются по ключам — чтобы
#: патч «здоровье 800» не съедал остальные пять чисел.
EDITOR_UNIT_FIELDS = frozenset({
    "name", "level", "money", "palette", "direction", "venom",
    "breed", "body", "face", "speed", "pinned", "dialog_number",
    #: ЧЬИ КАДРЫ РИСОВАТЬ. Тела 6 и 7 (народ пустыни) есть только у
    #: «Продолжения легенды», и клиент выбирает набор по этому полю
    #: (actor.js bodyKey): без него такой житель на нашей карте
    #: рисовался базовым телом в чужой палитре — цветным шумом.
    "game",
    #: ПОЯС — это `bag`: сорок две ячейки, двенадцать видимых
    #: (konung2/interf.py BELT). Списком, а не словарём: порядок ячеек
    #: значим, и `bag_details` идут параллельно — прочность, заряды,
    #: слово чар. Без них правка пояса не доезжала до пака.
    "bag", "bag_details",
    #: номера имени: строки имени в GAME.<мир> нет, есть номера в
    #: таблицах exe (0xF0 и 0xF1)
    "name_id", "nick_id",
})
#: `removed` — не поле, а приговор: юнит выкидывается из мира (см.
#: _editor_units_apply); в _editor_unit_apply он не попадает никогда.
#: `equipment` — надетое: слот -> ссылка на класс вещи («class:209»).
#: Правится словарём, как характеристики: сборка кладёт ссылку в запись,
#: а слои отрисовки считаются из класса (layer + palette), поэтому смена
#: доспеха сразу видна и в игре, и на холсте редактора.
EDITOR_UNIT_DICTS = frozenset({"stats", "characteristics", "current",
                               "cell", "home", "skills", "equipment",
                               "equipment_classes"})


def _bake_dialog_tree(game, project, number: int):
    """Дерево разговора по номеру — тем же путём, что у жителей
    (перевод донорских доводов-карт и классов включён)."""
    if number is None or number == 0xFF:
        return None
    try:
        from konung2.profile import CANON as _CANON
        from konung2.quests import Dialogs
        talk = Dialogs.from_game(game).tree(number)
        if game is not _CANON and talk:
            from konung2 import donor as _donor
            talk = _translate_tree_arguments(
                talk, _foreign_numbering(project, game.name),
                _donor.item_class_map())
        return talk
    except (OSError, ValueError, IndexError, LookupError, struct.error):
        return None


def _editor_units_apply(units: list, patches: dict,
                        added: list) -> list:
    """Юниты мира с правками редактора: патчи, удаления, добавленные.

    Добавленные (id вида unit_new_*) — записи целиком, как их снял
    клиент с живого клона; недостающему даются мирные умолчания."""
    out = []
    for unit in units:
        patch = patches.get(unit.get("id"))
        if patch and patch.get("removed"):
            continue
        _editor_unit_apply(unit, patch)
        out.append(unit)
    for entry in added:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        unit = {"dialog_number": 0xFF, "equipment": {}, "bag": [],
                "skills": {}, "workplaces": [], "pinned": False,
                "direction": 6, **entry}
        out.append(unit)
    return out


def _editor_unit_apply(unit: dict[str, Any],
                       patch: dict[str, Any] | None) -> None:
    """Применить редакторский патч к юниту пака (по белому списку)."""
    if not patch:
        return
    for key, value in patch.items():
        if key in EDITOR_UNIT_FIELDS:
            unit[key] = value
        elif key in EDITOR_UNIT_DICTS and isinstance(value, dict):
            target = unit.setdefault(key, {})
            if isinstance(target, dict):
                target.update(value)


def verify_content_pack(root: str | Path) -> list[str]:
    """Вернуть список ошибок целостности; пустой список означает успех."""
    pack = Path(root)
    manifest_path = pack / "manifest.json"
    if not manifest_path.is_file():
        return ["нет manifest.json"]
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = ContentManifest.from_dict(raw)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        return [f"некорректный manifest.json: {exc}"]

    errors: list[str] = []
    declared: set[str] = set()
    for item in manifest.files:
        try:
            path = _contained_path(pack, item.path)
        except ContentBuildError as exc:
            errors.append(str(exc))
            continue
        if item.path in declared:
            errors.append(f"файл объявлен дважды: {item.path}")
            continue
        declared.add(item.path)
        if not path.is_file():
            errors.append(f"нет файла: {item.path}")
            continue
        size = path.stat().st_size
        if size != item.bytes:
            errors.append(f"размер {item.path}: {size}, ожидалось {item.bytes}")
        digest = _sha256(path)
        if digest != item.sha256:
            errors.append(f"sha256 не совпал: {item.path}")

    for item in manifest.maps:
        if item.path not in declared:
            errors.append(f"карта отсутствует в files: {item.path}")
    return errors


def _export_palettes(root: Path) -> dict[str, Any]:
    """Палитры обеих игр — картинкой 256x256: строка p, столбец i — цвет.

    Хранить цвет впечённым в кадры значит держать одну и ту же геометрию
    столько раз, сколько у неё мастей: у тела 2 их девять, у слоя оружия
    одиннадцать. Палитра при этом стоит 512 байт, а всего их 256 на игру —
    вместе с донорскими это 384 КБ картинкой против 205 МБ цветных листов.

    Картинка, а не JSON: браузер читает её родными средствами, а числа в
    JSON заняли бы вчетверо больше и разбирались бы вручную.
    """
    from PIL import Image

    from konung2 import donor as donor_games
    out: dict[str, Any] = {}
    folder = Path("assets")
    (root / folder).mkdir(parents=True, exist_ok=True)
    sources = [("canon", read_palettes())]
    if donor_games.available():
        try:
            sources.append(("legend", read_palettes(
                donor_games.graph_palette_block())))
        except OSError:
            pass
    for name, palettes in sources:
        picture = Image.new("RGB", (256, len(palettes)))
        picture.putdata([tuple(colour) for table in palettes for colour in table])
        relative = folder / f"palettes_{name}.png"
        picture.save(str(root / relative))
        out[name] = {"path": relative.as_posix(),
                     "count": len(palettes), "size": 256}
    return out


def _export_daylight(root: Path) -> str | None:
    """Кривая дня и ночи — артефакт эмуляции VA 0x4295D8."""
    source = Path(__file__).resolve().parents[2] / "konung2" / "data" / "daylight.json"
    if not source.is_file():
        return None
    relative = Path("assets") / "daylight.json"
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, path)
    return relative.as_posix()


def _canon_map_name(number: int, project: Path | None = None) -> str | None:
    """Каноничное имя локации из таблицы имён exe, а за каноном — из реестра.

    Имена карт в проекте правятся руками, и тестовое имя оттуда утекало в
    игру. Таблица же неизменна, поэтому имя берём из неё.

    За канонными номерами таблицы нет, и имя владеет реестр локаций — тот
    же, что называет локацию на карте мира. Иначе одна карта звалась бы в
    двух местах по-разному: на глобальной так, а войдя в неё — иначе.
    """
    if project is not None:
        for entry in location_registry(project):
            if int(entry["number"]) == number:
                return str(entry["name"])
    try:
        from konung2.worldmap import location_names
        names = location_names()
    except (OSError, ValueError, IndexError, ImportError):
        return None
    if isinstance(names, dict):
        return names.get(number) or names.get(str(number))
    if 0 <= number < len(names):
        return names[number] or None
    return None


#: Описания шести героев экрана создания: шесть указателей на строки по
#: VA 0x462CDC, печатает их 0x431548 с переносом по ширине. Первое
#: предложение каждой строки — это и есть имя с званием («Князь деревни
#: Борье Ратибор.», «Княгиня Велиславна — последняя из рода…»).
HERO_STORY_VA = 0x462CDC


def _hero_stories() -> list[str]:
    """Полные описания шестерых, как их печатает экран создания."""
    from konung2.exetables import va_to_foff
    out: list[str] = []
    try:
        with open(game_file("konung2.exe"), "rb") as stream:
            blob = stream.read()
    except OSError:
        return out
    table = va_to_foff(HERO_STORY_VA)
    for index in range(6):
        pointer = struct.unpack_from("<I", blob, table + index * 4)[0]
        if not 0x440000 < pointer < 0x470000:
            out.append("")
            continue
        at = va_to_foff(pointer)
        out.append(blob[at:blob.index(bytes(1), at)].decode("cp866", "replace"))
    return out


def _effects_rules(stage: Path) -> dict[str, Any]:
    """Раздел effects: кадры семи анимаций огня, скопированные в пак."""
    from konung2 import objectanim

    target = stage / "assets" / "effects"
    target.mkdir(parents=True, exist_ok=True)
    source = Path("project") / "fire_frames"
    for n in range(74):
        frame = source / f"anim_{n:02}.png"
        if frame.is_file():
            shutil.copyfile(frame, target / frame.name)
    return objectanim.export()


def _reputation_rules() -> dict[str, Any]:
    """Правила репутации из exe донора; без него раздел пуст.

    Держим их в паке, а не в клиенте, по той же причине, что и всё
    остальное из exe: числа принадлежат игре, а не порту, и подделать их
    руками — значит потерять сверку с оригиналом.
    """
    from konung2 import reputation

    return reputation.export()


def _hero_choices() -> list[dict[str, Any]]:
    """Девять героев экрана «Новая игра» — по правилу donor.HERO_SLOTS.

    Движок при выборе персонажа читает запись юнита 0 из GAME.<номер>
    (VA 0x4387CC), а карту, где этот герой начинает, хранит запись отряда
    игрока (+0x08 таблицы отрядов). NEWHERO.RES тут ни при чём: в нём лежит
    только картинка самого экрана.

    Слоты 0…5 — канон (слот 1 занимает Велиславна «Продолжения легенды»:
    та же героиня на той же карте 19, история продолжается его миром 1),
    слоты 6…8 — Иззарк, Драгомир и Гильдис из его миров 0/2/3. Стартовые
    карты донорских переводятся в нашу нумерацию (150 + его номер,
    двойники — наши же карты), биографии — из его exe (cp866).
    """
    import struct as _struct

    from konung2 import donor, reputation
    from konung2.profile import LEGEND

    stories = _hero_stories()
    out: list[dict[str, Any]] = []
    for slot, (game, index) in enumerate(donor.HERO_SLOTS):
        legend = game == "legend"
        if legend and not donor.available():
            continue
        if not legend and not (Path(BUILD_DIR) / f"GAME.{index}").is_file():
            continue
        template = _hero_template(index, LEGEND if legend else None)
        if not template:
            continue
        if legend:
            from konung2.gamefile import _game_bytes
            data, layout = _game_bytes(index, LEGEND)
            at, _, _size = layout["parties"]
            party = data[at:at + _size]
            story = donor.hero_story(index)
            map_number = donor.our_map_number(
                int(_struct.unpack_from("<H", party, 0x08)[0]))
        else:
            from konung2.gamefile import T_PARTIES
            data = (Path(BUILD_DIR) / f"GAME.{index}").read_bytes()
            party = data[T_PARTIES.offset:T_PARTIES.offset + T_PARTIES.size]
            story = stories[index] if index < len(stories) else ""
            map_number = int(_struct.unpack_from("<H", party, 0x08)[0])
        # МИР ШАБЛОНА — НОМЕР СЛОТА, А НЕ РОДНОЙ НОМЕР ЕГО ИГРЫ. Панель ищет
        # героя в списке выбора по `template.world` (cursors.js, heroName),
        # и у Иззарка с его родным нулём находился наш нулевой — «Князь
        # деревни Борье Ратибор». Метка игры нужна отрисовке: тела и палитры
        # у донора свои (actor.js, bodyKey).
        template = {**template, "world": slot,
                    **({"game": "legend"} if legend else {})}
        out.append({
            "slot": slot,
            "world": slot,
            "game": "legend" if legend else "canon",
            "native_world": index,
            "map": map_number,
            "row": int(_struct.unpack_from("<H", party, 0x0C)[0]),
            "col": int(party[0x14]),
            # Имя — первое предложение описания: движок печатает описание
            # целиком, а имя отдельным полем нигде не держит. У его героев
            # первое предложение — «Воин Жёлтых собак пустыни Иззарк», имя
            # в нём последнее слово; короткую подпись берём из известной
            # четвёрки, а не режем наугад.
            "name": (donor.HERO_NAMES[index] if legend
                     else (story.split(".", 1)[0].strip() if story else "")),
            "story": story,
            # СТАРТОВАЯ РЕПУТАЦИЯ — ХАРАКТЕР ГЕРОЯ, А НЕ НОЛЬ ДЛЯ ВСЕХ.
            # Донор кладёт её при выборе персонажа из таблицы 0x465A28
            # (VA 0x0043C4AC): Драгомир начинает при −100, Гильдис при
            # +30. Канону ставим ноль: у него этой механики нет вовсе.
            "reputation": reputation.start_for(
                "legend" if legend else "canon", index),
            "template": template,
        })
    return out


def _custom_hero_choices(project: Path, choices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Свои персонажи на экране «Новая игра» — из project/creatures/*/set.json.

    Канонные записи НЕ ТРОГАЮТСЯ: свой герой становится отдельной строкой со
    своим слотом, и выбор Велиславны остаётся выбором Велиславны.

    Содержимое мира свой герой берёт у канонного: жители, кучи, деревни и
    отряды разложены в паке по мирам (`units_by_world` и соседи), и у нового
    слота своего мира нет и взяться ему неоткуда. Поэтому `template.world`
    остаётся базовым, а для подписи под курсором в шаблон кладётся `slot` —
    по нему `heroName` отличает своего героя от того, чей мир он занял.

    Облик приходит из набора: тело, масть и порода с битом твари 0x40 — тем
    же способом, каким набор надевается на любого юнита (actor.js). Скорость
    же остаётся канонной механикой: движок считает её игроку из Ловкости и
    Выносливости (carry.js unitSpeed, VA 0x41B3B8), поэтому «быстрый герой» —
    это характеристики в наборе, а не правка формулы.
    """
    source = Path(project) / "creatures"
    if not source.is_dir() or not choices:
        return choices
    out = list(choices)
    for folder in sorted(p for p in source.iterdir() if p.is_dir()):
        path = folder / "set.json"
        if not path.is_file():
            continue
        document = json.loads(path.read_text(encoding="utf-8"))
        playable = document.get("playable")
        if not playable:
            continue
        name = str(document.get("name") or folder.name)
        base_world = int(playable.get("world", 0))
        base = next((c for c in out if int(c.get("world", -1)) == base_world), None)
        if base is None:
            raise ValueError(f"персонаж {name}: мира {base_world} на экране выбора нет")
        slot = max(int(c["slot"]) for c in out) + 1
        template = dict(base.get("template") or {})
        template["body"] = int(document["body"])
        template["palette"] = int(document.get("palette", 0))
        #: БЕЗ БИТА ТВАРИ ГЕРОЙ ПОЙДЁТ СЛОЯМИ HEROES.RES и не найдёт нашего
        #: тела вовсе: набор ищут только по этому биту (actor.js isBeast).
        template["breed"] = int(playable.get("breed", 0x40))
        template["slot"] = slot
        traits = list(template.get("characteristics") or [])
        for trait, value in (playable.get("characteristics") or {}).items():
            if trait in CHARACTERISTICS and traits:
                traits[CHARACTERISTICS.index(trait)] = int(value)
        if traits:
            template["characteristics"] = traits
            template["current"] = list(traits)
        out.append({**base, "slot": slot,
                    "name": playable.get("name") or document.get("title") or name,
                    "story": playable.get("story") or "",
                    "template": template})
    return out


def _hero_start(map_number: int) -> dict[str, Any] | None:
    """Стартовая клетка героя на этой карте — из GAME.x его игры.

    Отряд игрока (запись 0 таблицы отрядов) хранит карту в +0x08 и клетку в
    +0x0C/+0x14. Перебираются все ДЕВЯТЬ слотов выбора: у донорских героев
    клетка лежит в его game.<мир>, а номер карты переводится в наш. Без
    этого новый герой вставал не в свою точку, а в середину застройки —
    Гильдис появлялась посреди Кирингхольма вместо родного дома.
    """
    import struct as _struct

    from konung2 import donor
    from konung2.gamefile import T_PARTIES, _game_bytes
    from konung2.profile import LEGEND

    for slot, (game, index) in enumerate(donor.HERO_SLOTS):
        if game == "legend":
            if not donor.available():
                continue
            data, layout = _game_bytes(index, LEGEND)
            at, _, size = layout["parties"]
            party = data[at:at + size]
            his_map = _struct.unpack_from('<H', party, 0x08)[0]
            if donor.our_map_number(his_map) != map_number:
                continue
        else:
            path = Path(BUILD_DIR) / f"GAME.{index}"
            if not path.is_file():
                continue
            data = path.read_bytes()
            party = data[T_PARTIES.offset:T_PARTIES.offset + T_PARTIES.size]
            if _struct.unpack_from('<H', party, 0x08)[0] != map_number:
                continue
        return {
            "world": slot,
            "row": int(_struct.unpack_from('<H', party, 0x0C)[0]),
            "col": int(party[0x14]),
        }
    return None


#: ВКЛАД КАРТЫ В ОБЩИЕ СПИСКИ ВЫПЕЧКИ — РЯДОМ С ПАКОМ.
#:
#: Формы тел, палитры, пары «тело + палитра» и слои снаряжения общие на
#: всю игру, а собираются они обходом жителей КАЖДОЙ карты по всем мирам
#: выбора. При сборке одной карты это 141 карта x 9 миров x 3 сборщика —
#: две с половиной тысячи разборов GAME.x, и они съедали две трети
#: времени: замер сборки карты 63 дал 468 с из 694 в четырёх сборщиках
#: против 29 с в самой карте.
#:
#: Вклад карты меняется только вместе с её файлами и мирами, поэтому его
#: можно помнить: индекс держит отпечаток общих источников (поколение) и
#: отпечатки файлов каждой карты. Сменились миры — пересчитываются все,
#: сменилась карта — только она.
SCENARIO_INDEX = ".knyaz2-scenario-index.json"


def _file_stamp(path: Path) -> list | None:
    """Отпечаток файла: размер и время правки (как в описи файлов пака)."""
    try:
        stat = path.stat()
    except OSError:
        return None
    return [stat.st_size, int(stat.st_mtime_ns)]


def _shared_generation() -> str:
    """Отпечаток источников, общих ВСЕМ картам: миры обеих игр и их
    оверлеи (project/worlds/build — наш M_UNIT, konung2/worlds.py).

    Правка мира меняет жителей сразу всех карт, поэтому она обязана
    обесценить весь индекс вкладов, а не только тронутую карту.
    """
    from konung2.profile import CANON, LEGEND
    from konung2 import donor
    roots = [Path(__file__).resolve().parents[2] / "project" / "worlds" / "build"]
    for profile in (CANON, LEGEND if donor.available() else None):
        if profile is None:
            continue
        try:
            roots.append(Path(profile.file("GAME.0")).parent)
        except (OSError, ValueError, KeyError, AssertionError):
            continue
    marks: list = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.glob("GAME.*")):
            marks.append([str(path), *(_file_stamp(path) or [])])
    return hashlib.sha256(
        json.dumps(marks, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def _map_stamp(project: Path | None, number: int) -> list | None:
    """Отпечаток файлов карты. None — карты нет в проекте (встречные
    отряды 100…146 читаются прямо из канона и держатся на поколении)."""
    if project is None:
        return None
    try:
        source = _find_map_source(project, number)
    except ContentBuildError:
        return None
    return [_file_stamp(source / "map.json"),
            _file_stamp(source / "scenario.json")]


def _map_contribution(project: Path | None, number: int) -> dict[str, Any]:
    """Что ОДНА карта добавляет в общие списки выпечки кадров.

    Четыре списка собираются одним обходом жителей, потому что обход и
    есть дорогая часть: раньше формы, палитры и пары читали одних и тех
    же жителей по три раза подряд.

    * **shapes** — тела (байт unit+0xFC). Звери рисуются своим набором
      из OBJECTS.RES, слоя тела у них нет — их отсеивает бит 0x40 породы.
    * **palettes** — палитры тела: движок красит юнита целиком, подставляя
      её перед блиттером ([0x8A7318], VA 0x426707). Без них ВСЕ НПЦ выходят
      в базовой палитре героя и оттого на одно лицо.
    * **pairs** — тройки «игра + форма + палитра». ИГРА В КЛЮЧЕ, ПОТОМУ ЧТО
      ПАЛИТРЫ РАЗНЫЕ: из 256 палитр GRAPH.RES у двух игр совпадают 218, и
      жители «Продолжения легенды» под своим номером выходили красными с
      цветным шумом. ФОРМА И ПАЛИТРА НЕЗАВИСИМЫ (VA 0x425DB4: сперва
      палитра юнита, потом его слой тела) — порт же пёк формы одной
      палитрой и выбирал ОДНО ИЗ ДВУХ, отчего пятеро стартовых героев
      выходили в базовой раскраске. Берутся ИМЕННО ПАРЫ, а не произведение
      форм на палитры: последнее раздуло бы выпечку в разы без пользы.
    * **equipment** — имена надетых вещей, из них считаются слои.
      ЖИТЕЛИ СОБИРАЮТСЯ ВСЕГДА, А НЕ ТОЛЬКО ПРИ scenario.json: тот есть
      ровно у одной карты из 52, и раньше снаряжение прочих не
      запрашивалось ни разу — воины Повелителя оставались без щита и шлема.
      Здесь карта читается КАНОННЫМ номером и нулевым миром, как и было.
    * **creatures** — пары «тело + масть» ТВАРЕЙ (бит 0x40 породы). Набор
      нужен ОДИН на весь пак, а не на карту: раньше каждая карта звала свой
      экспорт и писала в одни и те же creature_N.png, так что наборы карт
      затирали друг друга.
    """
    from konung2 import donor
    shapes: set[int] = set()
    palettes: set[int] = set()
    pairs: set[tuple[str, int, int]] = set()
    creatures: set[tuple[int, int]] = set()
    equipment: list[Any] = []
    source: Path | None = None
    if project is not None:
        try:
            source = _find_map_source(project, number)
        except ContentBuildError:
            source = None

    game = ""
    if source is not None:
        origin = (json.loads((source / "map.json").read_text(encoding="utf-8"))
                  .get("origin") or {}).get("game")
        game = "legend" if origin == donor.LEGEND_NAME else ""
        # Снаряжение жителей карты — канонным номером и нулевым миром.
        try:
            from konung2.gamefile import map_units
            for resident in map_units(number, 0):
                equipment.extend((resident.get("equipment_classes") or
                                  resident.get("equipment") or {}).values())
        except (OSError, ValueError, IndexError, KeyError):
            pass
        path = source / "scenario.json"
        if path.is_file():
            document = json.loads(path.read_text(encoding="utf-8"))
            equipment.extend(entry["item"] for entry in document.get("loot", []))
            #: ПОСТАВЛЕННЫЕ РЕДАКТОРОМ — ТОЖЕ ЖИТЕЛИ. Читались только
            #: `units` (правки уже существующих), а `editor_units_add` —
            #: новые — не читались вовсе: их тело и масть не попадали в
            #: списки выпечки, кадров не пеклось, и житель выходил
            #: цветным шумом (базовое тело чужой палитрой).
            #: ИГРА У ЖИТЕЛЯ СВОЯ: народ пустыни (тела 6 и 7) есть только
            #: в «Продолжении легенды» — в каноне таких слоёв нет вовсе, —
            #: и поставить его на нашу карту можно лишь его же кадрами.
            for entry in (list(document.get("units", []))
                          + list(document.get("editor_units_add", []))):
                equipment.extend((entry.get("equipment") or {}).values())
                palette = int(entry.get("palette", 0))
                if palette:
                    palettes.add(palette)
                body = int(entry.get("body") or 0)
                if int(entry.get("breed") or 0) & 0x40:
                    creatures.add((body, palette))
                    continue
                if body:
                    shapes.add(body)
                if body and palette:
                    pairs.add((str(entry.get("game") or game), body, palette))

    # ЖИТЕЛИ ВО ВСЕХ МИРАХ ВЫБОРА, а не только в нулевом: миры расходятся,
    # и житель, стоящий лишь в мире Драгомира, уезжал в пак без слоя кадров
    # и без портрета — молча, как и всё, что теряется по недосмотру охвата.
    for resident in _project_residents_all(project, number):
        breed = int(resident.get("breed", 0) or 0)
        body = int(resident.get("body", 0) or 0)
        palette = int(resident.get("palette", 0) or 0)
        # звери рисуются своим набором из OBJECTS.RES, слоя тела у них нет
        if breed & 0x40:
            creatures.add((body, palette))
            continue
        if body:
            shapes.add(body)
        if palette:
            palettes.add(palette)
        if body and palette:
            pairs.add((game, body, palette))
    return {"shapes": sorted(shapes), "palettes": sorted(palettes),
            "pairs": sorted([list(pair) for pair in pairs]),
            "creatures": sorted([list(pair) for pair in creatures]),
            "equipment": equipment, "sourced": source is not None}


def _scenario_contributions(project: Path | None, numbers: Iterable[int],
                            destination: Path | None) -> dict[int, dict]:
    """Вклады карт с памятью рядом с паком.

    Считается только то, что изменилось: поколение сторожит миры,
    отпечаток файлов — саму карту.
    """
    numbers = tuple(sorted(set(int(number) for number in numbers)))
    index_path = (destination / SCENARIO_INDEX) if destination else None
    generation = _shared_generation()
    known: dict[str, Any] = {}
    if index_path is not None and index_path.is_file():
        try:
            document = json.loads(index_path.read_text(encoding="utf-8"))
            if document.get("generation") == generation:
                known = document.get("maps") or {}
        except (OSError, ValueError):
            known = {}
    fresh: dict[str, Any] = {}
    out: dict[int, dict] = {}
    for number in numbers:
        stamp = _map_stamp(project, number)
        cached = known.get(str(number))
        if cached is not None and cached.get("stamp") == stamp:
            entry = cached
        else:
            entry = {"stamp": stamp, **_map_contribution(project, number)}
        fresh[str(number)] = entry
        out[number] = entry
    if index_path is not None:
        try:
            _write_json(index_path, {"generation": generation, "maps": fresh})
        except OSError:
            pass
    return out


def _hero_extra_shapes() -> set[int]:
    """Тела шести стартовых героев (1…5; нулевое — базовый набор кадров).

    Их нет ни в одной расстановке, а без слоёв выбранный герой выходит
    болванчиком.
    """
    shapes: set[int] = set()
    for index in range(6):
        try:
            from konung2.gamefile import hero_stats
            shape = int(hero_stats(index).get("body", 0) or 0)
            if shape:
                shapes.add(shape)
        except (OSError, ValueError, IndexError, KeyError, AssertionError):
            continue
    return shapes


def _hero_extra_palettes() -> set[int]:
    """Палитры шести стартовых героев — 70, 28, 31, 34.

    «Новая игра» даёт выбрать одного из них (VA 0x4387CC читает запись
    героя из GAME.<номер>); ни в одной расстановке карт они не
    встречаются, поэтому без этой добавки герой оставался без раскраски.
    """
    palettes: set[int] = set()
    for index in range(6):
        try:
            from konung2.gamefile import hero_stats
            palette = int(hero_stats(index).get("palette", 0) or 0)
            if palette:
                palettes.add(palette)
        except (OSError, ValueError, IndexError, KeyError, AssertionError):
            continue
    return palettes


def _hero_extra_pairs() -> set[tuple[str, int, int]]:
    """Пары стартовых героев: слоты выбора помнят, чей мир читать."""
    from konung2 import donor
    from konung2.profile import LEGEND
    pairs: set[tuple[str, int, int]] = set()
    for hero_game, index in donor.HERO_SLOTS:
        legend = hero_game == "legend"
        if legend and not donor.available():
            continue
        try:
            from konung2.gamefile import hero_stats
            stats = hero_stats(index, LEGEND if legend else None)
            shape = int(stats.get("body") or 0)
            palette = int(stats.get("palette") or 0)
            if shape and palette:
                pairs.add(("legend" if legend else "", shape, palette))
        except (OSError, ValueError, IndexError, KeyError, AssertionError):
            continue
    return pairs


def _hero_extra_equipment() -> list[Any]:
    """Снаряжение, общее всем картам: герой выходит в мир уже одетым
    (GAME.0), и его доспех, шлем и щит рисуются такими же слоями, как
    поднятое с земли; отряд игрока — тем же порядком."""
    names: list[Any] = []
    template = _hero_template()
    names.extend(name for name in (template or {}).get("equipment", {}).values()
                 if name)
    try:
        from konung2.gamefile import party
        for member in party(0, 0).get("members", []):
            names.extend((member.get("equipment_classes") or
                          member.get("equipment") or {}).values())
    except (OSError, ValueError, IndexError, KeyError):
        pass
    return names


def _layers_of(names: Iterable[Any]) -> dict[int, list[int]]:
    """Слои экипировки по именам вещей: слой -> СПИСОК палитр.

    Выгружать все 54 слоя незачем — берём только те, что называет
    расстановка, плюс «в покое» для метательного (лук 19 -> 20,
    самострел 21 -> 22).

    ПАЛИТРА У ПРЕДМЕТА СВОЯ, И НА ОДНОМ СЛОЕ ИХ БЫВАЕТ НЕСКОЛЬКО. Движок
    переставляет палитру перед КАЖДЫМ слоем и берёт её из записи класса
    предмета, а не из юнита (VA 0x425DB4):

        [0x8A7318] = юнит+0x2E;                       // палитра ТЕЛА
        рисуем тело;
        если надет доспех:
            [0x8A7318] = [0x45DB0C + вид * 0x20];     // палитра ПРЕДМЕТА
            рисуем его слой [0x45DB08 + вид * 0x20];

    (У оружия палитра вообще зашита числом 0x400.) Слой 23 делят кожаные
    доспехи с палитрой 3 и ДОСПЕХ ВОИНА ПОВЕЛИТЕЛЯ с палитрой 9 — та самая
    чёрная броня. Раньше здесь стоял `layers[слой] = палитра`, и в словаре
    выигрывала записанная последней: воинов Повелителя красило палитрой
    обычной кожанки. Всего таких слоёв шесть: 23, 24, 25, 26, 27 и 28.
    """
    items = read_items()
    by_index = {item.index: item for item in items}
    by_name: dict[str, ItemClass] = {}
    for item in items:
        by_name.setdefault(item.name.lower(), item)

    def resolve(value: str | int) -> ItemClass | None:
        if isinstance(value, int):
            return by_index.get(value)
        text = str(value)
        if text.startswith(ITEM_REF_PREFIX):
            try:
                return by_index.get(int(text[len(ITEM_REF_PREFIX):]))
            except ValueError:
                return None
        if text.startswith(INSTANCE_REF_PREFIX):
            try:
                return by_index.get(int(text.split(":", 2)[1]))
            except (ValueError, IndexError):
                return None
        return by_name.get(text.lower())

    layers: dict[int, set[int]] = {}
    for name in names:
        item = resolve(name)
        if item is None or not item.wearable:
            continue
        # Варианты слоя из отрисовки VA 0x425DB4: оружие живёт четырьмя
        # (в руке, убрано, во второй руке, убрано во второй), щит двумя
        # (в руке и за спиной), доспех и шлем — одним.
        if item.slot == "off_hand":
            offsets = (0, LAYER_SHIELD_BACK)
        elif item.slot in ("hand", "ranged"):
            offsets = (LAYER_IN_HAND, LAYER_AT_REST,
                       LAYER_OFF_HAND, LAYER_OFF_REST)
        else:
            offsets = (0,)
        for offset in offsets:
            layers.setdefault(item.layer + offset, set()).add(item.palette)
    return {layer: sorted(palettes)
            for layer, palettes in sorted(layers.items())}


def _shared_inputs(project: Path | None, numbers: Iterable[int],
                   encounters: Iterable[int],
                   destination: Path | None) -> tuple:
    """Пять списков для выпечки кадров: слои, палитры, формы, пары, твари.

    Формы и твари считаются и по встречным отрядам (их бойцов надо одеть
    так же, как жителей), остальное — по картам пака.
    """
    numbers = tuple(numbers)
    encounters = tuple(encounters)
    parts = _scenario_contributions(project, numbers + encounters, destination)

    shapes: set[int] = set(_hero_extra_shapes())
    palettes: set[int] = set(_hero_extra_palettes())
    pairs: set[tuple[str, int, int]] = set(_hero_extra_pairs())
    creatures: set[tuple[int, int]] = set()
    names: list[Any] = []
    sourced = False
    for number in set(numbers + encounters):
        entry = parts.get(number) or {}
        shapes.update(int(shape) for shape in entry.get("shapes") or ())
    for number in set(numbers):
        entry = parts.get(number) or {}
        palettes.update(int(palette) for palette in entry.get("palettes") or ())
        for pair in entry.get("pairs") or ():
            game, shape, palette = pair
            pairs.add((str(game), int(shape), int(palette)))
        for pair in entry.get("creatures") or ():
            body, palette = pair
            creatures.add((int(body), int(palette)))
        if entry.get("sourced"):
            sourced = True
            names.extend(entry.get("equipment") or ())
    if sourced:
        names.extend(_hero_extra_equipment())
    # Твари встречных отрядов — из их же расстановки, а не из карт.
    for unit in _encounter_units():
        if int(unit.get("breed", 0) or 0) & 0x40:
            creatures.add((int(unit.get("body", 0) or 0),
                           int(unit.get("palette", 0) or 0)))
    return _layers_of(names), palettes, shapes, pairs, creatures




def _all_encounter_templates() -> dict[int, Any]:
    """Встречные отряды ОБЕИХ игр: канонные 100…146 и донорские 1000…1717.

    Один список на всех, потому что таблица местностей у каждой игры своя, а
    номера не пересекаются. Владелец списка тут один — иначе легко подключить
    донорские отряды к встречам и забыть про их графику.
    """
    try:
        templates: dict[int, Any] = dict(encounter_templates())
    except (OSError, ValueError, IndexError, struct.error):
        templates = {}
    try:
        from konung2 import donor
        if donor.available():
            templates.update(donor.encounter_templates())
    except (OSError, ValueError, IndexError, struct.error):
        pass
    return templates


def _encounter_numbers() -> tuple[int, ...]:
    """«Номера карт», под которыми лежат шаблоны встречных отрядов."""
    return tuple(sorted(_all_encounter_templates()))


def _encounter_units() -> list[dict[str, Any]]:
    """Все бойцы встречных отрядов — одним списком, для разбора графики."""
    out: list[dict[str, Any]] = []
    for template in _all_encounter_templates().values():
        out.extend(template["units"])
    return out


def _encounter_roster(resolve, remember) -> dict[str, Any]:
    """Кого мы встретим в пути: состав каждого шаблона.

    Движок хранит эти отряды как обычные (VA 0x4360A8 ищет отряд, у
    которого номер карты равен номеру группы) и на встрече копирует
    целиком. Здесь тот же состав в том же виде, что и жители карты, —
    клиенту остаётся расставить их вокруг вожака.
    """
    # ЗАСАДЫ НА ЗЕМЛЕ ДОНОРА — ЕГО. Его таблица местностей называет отряды
    # номерами 1000…1717, и лежат они в ЕГО GAME.<мир>; наши 100…146 с ними
    # не пересекаются, поэтому реестр общий. Без этого на его земле выпадал
    # бы номер, которого в паке нет, и встреча не случалась вовсе.
    roster: dict[str, Any] = {}
    templates = _all_encounter_templates()
    for group, template in sorted(templates.items()):
        units = []
        for order, unit in enumerate(template["units"]):
            equipment = {}
            source_equipment = (unit.get("equipment_classes") or
                                unit.get("equipment") or {})
            source_records = unit.get("equipment_item_records") or {}
            for slot, name in source_equipment.items():
                if name is None:
                    continue
                item = resolve(name)
                if item is None:
                    continue
                remember(item)
                equipment["off_hand" if slot == "shield" else slot] = \
                    _game_item_ref(item, source_records.get(slot))
            second_equipment = unit.get("second_classes") or unit.get("second") or {}
            second_records = unit.get("second_item_records") or {}
            for slot, name in second_equipment.items():
                if name is None:
                    continue
                item = resolve(name)
                remember(item)
                equipment[slot] = _game_item_ref(item, second_records.get(slot))
            bag = []
            source_bag = unit.get("bag_classes") or unit.get("bag") or []
            bag_records = unit.get("bag_item_records") or []
            for at, name in enumerate(source_bag):
                if name is None:
                    continue
                item = resolve(name)
                remember(item)
                record = bag_records[at] if at < len(bag_records) else None
                bag.append(_game_item_ref(item, record))
            current = unit.get("current", {})
            units.append({
                "id": f"foe_{group}_{order}",
                "name": unit["name"],
                "side": unit["side"], "face": unit["face"],
                "level": unit["level"], "hostile": True,
                "venom": unit.get("venom", 0),
                "breed": unit.get("breed", 0), "body": unit.get("body", 0),
                # поза расстановки (+0x17) и счётчик подъёмов (+0xEE):
                # на них держатся «встающие» твари, см. docs/BESTIARY.md
                "pose": unit.get("pose", 0),
                "breed_counter": unit.get("breed_counter", 0),
                "palette": unit.get("palette", 0),
                "ranged_mode": unit.get("ranged_mode", False),
                "poison_on": unit.get("poison_on", {}),
                "money": unit.get("money", 0),
                "bag": bag,
                "bag_details": unit.get("bag_details") or [],
                "stats": {
                    "health": unit["health"], "armour": unit["armour"],
                    "parry": current.get("Ловкость", 10),
                    "toughness": current.get("Выносливость", 10),
                    "strength": current.get("Сила", 10),
                    "accuracy": unit.get("accuracy", 60),
                },
                # Шесть характеристик целиком — см. пояснение у жителей: байты
                # +0xC0 и +0xCC есть в записи любого юнита.
                "characteristics": unit.get("characteristics", {}),
                "current": current,
                # РАДИУСА ОБЗОРА В ПАКЕ НЕТ. Здесь стояло `sight_cells: 10` —
                # число, взятое из головы: в данных игры такого поля нет, и в
                # движке предела расстояния тоже нет ни в одной функции боя.
                # Бой начинает и кончает ОТРЯД: зона (VA 0x415B20) и 840
                # пикселей (VA 0x410784). См. docs/COMBAT_SPEC.md, раздел 11.
                #
                # СКОРОСТЬ — ИЗ ЗАПИСИ (+0x1D), а не «2 из головы»: формулу
                # из характеристик движок считает только отряду игрока
                # (0x41C944:305), NPC живут со значением данных — в стартовых
                # мирах это ноль. Двойка делала врагов равными герою в беге.
                "speed": int(unit.get("speed", 0)),
                "skills": unit.get("skills", {}),
                "equipment": equipment,
                "equipment_details": {
                    ("off_hand" if slot == "shield" else slot): detail
                    for slot, detail in
                    (unit.get("equipment_details") or {}).items()
                    if detail
                } | (unit.get("second_details") or {}),
            })
        if units:
            roster[str(group)] = {"party": template["party"], "units": units}
    return roster


def _spawn_cell(world_model, resident: dict,
                taken: set | None = None) -> "Cell | None":
    """Куда встанет юнит: канон VA 0x415764.

    Центр зоны отряда плюс случайное смещение в её половину, знак каждой
    оси — свой бросок. До ста попыток найти проходимую клетку; не нашлось —
    юнита на карте не будет, как и в движке.

    КЛЕТКА СЧИТАЕТСЯ СВОБОДНОЙ ПО МЛАДШИМ 12 БИТАМ, а в них движок держит и
    непроходимость (0xFFF), и НОМЕР СТОЯЩЕГО ЮНИТА плюс один: расстановка
    пишет его туда сама (0x433070, 0x4338B0). Значит уже занятая клетка для
    следующего юнита не годится. Здесь проверялась одна проходимость земли —
    и на одиннадцати картах твари вставали друг на друга, до четырёх на
    клетку; тестер это и назвал «персонажи налазят».
    """
    zone = resident.get("spawn_zone") or {}
    # Бит «координаты в силе» — юнит встаёт ровно туда, где записан
    # (VA 0x43DF9C). Так стоят жители деревень; рассыпают только тех, у
    # кого бит снят, — звериные отряды с нулями в записи.
    if zone.get("keep_cells"):
        #: Записанные координаты в силе — движок ставит ровно туда и чужой
        #: занятости не смотрит (0x43DF9C). Так стоят жители деревень.
        cell = Cell(int(resident["row"]), int(resident["col"]))
        if taken is not None:
            taken.add((cell.row, cell.col))
        return cell
    row_from = int(zone.get("row_from", 0))
    row_to = int(zone.get("row_to", 0))
    col_from = int(zone.get("col_from", 0))
    col_to = int(zone.get("col_to", 0))
    half_rows = (row_to - row_from) // 2
    half_cols = (col_to - col_from) // 2
    middle_row = (row_to + row_from + 1) // 2
    middle_col = (col_to + col_from + 1) // 2
    # Бросок повторяем тем же порядком, что движок: сперва смещение, потом
    # знак, и так по каждой оси.
    picker = random.Random(resident.get("index", 0))
    for _ in range(int(zone.get("tries", 100)) or 100):
        drow = 0 if half_rows < 2 else picker.randrange(half_rows)
        row = middle_row + (-1 if picker.randrange(2) == 0 else 1) * drow
        dcol = 0 if half_cols < 2 else picker.randrange(half_cols)
        col = middle_col + (-1 if picker.randrange(2) == 0 else 1) * dcol
        cell = Cell(row, col)
        if not world_model.terrain.passable(cell):
            continue
        if taken is not None and (cell.row, cell.col) in taken:
            continue
        if taken is not None:
            taken.add((cell.row, cell.col))
        return cell
    return None


def _project_residents(project: Path | None, number: int,
                       world: int = 0) -> list[dict[str, Any]]:
    """Жители карты по НАШЕМУ номеру — из своей игры.

    Сборщики форм, палитр и лиц звали `map_units(number)` напрямую, то есть
    всегда канон: по донорским номерам (150+) в каноне пусто, и тела его
    жителей в листы кадров не попадали — Позвизд с телом 24 оставался без
    слоя. Здесь номер сперва переводится через `origin` карты; номер без
    папки проекта (встречные отряды 100…146) честно читается из канона.
    """
    from konung2.gamefile import map_units
    try:
        source = _find_map_source(project, number) if project else None
    except ContentBuildError:
        source = None
    if source is None:
        try:
            return map_units(number, world)
        except (OSError, ValueError, IndexError):
            return []
    game, native = _map_source(source, number)
    try:
        return map_units(native, _world_of(game, world, native), profile=game)
    except (OSError, ValueError, IndexError, LookupError):
        return []


def _project_residents_all(project: Path | None,
                           number: int) -> list[dict[str, Any]]:
    """Жители карты во ВСЕХ мирах выбора — для сборщиков тел, палитр и лиц.

    Сборщики смотрели только нулевой мир, а миры расходятся. Замер по всем
    картам обеих игр: в каноне 9 пар «тело + палитра» и 6 лиц, у донора 5 пар
    и 11 лиц, которых в нулевом мире НЕТ ВОВСЕ. Такой житель уезжал в пак без
    слоя кадров и без портрета — молча, как и всё, что теряется по недосмотру
    охвата. Пары героев добираются отдельно (donor.HERO_SLOTS), а вот жители
    вроде тех, что стоят только в мирах Драгомира и Гильдис, — нет.
    """
    out: list[dict[str, Any]] = []
    for slot in range(_hero_worlds()):
        out.extend(_project_residents(project, number, slot))
    return out






def _export_world_picture(project: Path, root: Path) -> None:
    """Картинка расширенной карты мира — из проекта прямо в пак.

    У канона картинки нет: там спрайт 4 INTERF.RES, и он уже уезжает в
    `interface.map`. У расширения своя, нарисованная, и путь к ней объявлен
    в самих данных — копируем ровно туда, куда он указывает, чтобы клиенту
    не пришлось знать про два разных места.
    """
    picture = worldmap_pack.picture(project)
    if not picture:
        return
    source = project / "worldmap" / "map.png"
    if not source.is_file():
        raise ContentBuildError(
            f"расширенная карта мира включена, но картинки нет: {source}")
    target = root / picture["path"]
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def _hero_rules(project: Path | None = None) -> dict[str, Any]:
    """Правила движка: они собираются из кода и в кэш кадров не идут."""
    return {
        # Мировой такт движка — 78 мс (12.82 такта в секунду), НЕ 18.
        # Доказано по машинному коду, а не по догадке: оконный цикл
        # VA 0x42F1EF сравнивает `timeGetTime() - последний` с 0x4E и при
        # `jl` пропускает такт, то есть шлёт WM_USER(0x400) не чаще чем раз
        # в 78 мс (VA 0x42F200 push 0x400 → SendMessageA). Обработчик этого
        # сообщения VA 0x42F913 делает `call 0x438A00` — главный цикл, где
        # `_DAT_0084962c` (мировой такт) увеличивается на единицу и следом
        # идут снаряды, юниты, мировая фаза и очередь разговоров.
        # Проверено сканом всей секции кода: `call 0x438A00` встречается
        # РОВНО ОДИН РАЗ, из 0x42F913, — других источников такта нет.
        # Прежнее значение 1/18 (55.6 мс) держалось на комментарии «~18
        # тиков/с» и гнало игру на 40% быстрее оригинала.
        "frame_seconds": round(78 / 1000, 4),
        # Тот же такт в миллисекундах — для счётчика фаз (& 0xF и т.п.).
        "tick_ms": 78,
        # шаг по направлениям — таблицы движка 0x459AD4/0x459D14
        "direction_steps": [list(step) for step in DIRECTION_STEPS],
        # Правила движка, а не наши: по ним клиент решает, что играть.
        "rules": {
            "policy": "konung2_exe_0x4166A5_0x416D92_0x416C2C",
            "blocks": {stance: dict(poses) for stance, poses in STANCE_BLOCKS.items()},
            "actions": dict(ACTION_BLOCKS),
            # какую анимацию удара играть — решает группа предмета в руке
            # (ближний бой VA 0x416B50, стрельба VA 0x416AC8)
            "attack_by_item": {
                "two_hand_from_group": TWO_HAND_GROUP,
                "crossbow_group": CROSSBOW_GROUP,
                # у одноручного выбор идёт не по «занята ли левая рука»:
                # сперва навык «Бой двумя руками» (unit+0xD3, он же навык 1),
                # и только при ненулевом — вид предмета во второй руке
                "melee": {"two_hand": "attack_two_hand",
                          "second_hand_busy": "attack_shield",
                          "second_hand_free": "attack_one_hand",
                          "skill": 1},
                "ranged": {"crossbow": "shoot_crossbow", "other": "shoot_bow"},
            },
            # Отрисовка снаряжения — VA 0x425DB4: тело и доспех кладутся
            # первыми, дальше пять шагов сценария своего направления
            # (таблица 0x4627D0). Каждый шаг — свой предмет и своё смещение
            # слоя, поэтому надетое видно на персонаже целиком: доспех,
            # шлем, щит, оружие в руке и убранное.
            "equipment_draw": {
                "policy": "konung2_exe_0x425DB4_0x4627D0",
                "before": [
                    {"step": "body"},
                    {"step": "layer", "slot": "body", "offset": 0},
                ],
                "script": draw_script(),
                "steps": {
                    "3": [{"step": "layer", "slot": "head", "offset": 0}],
                    "100": [{"step": "layer", "slot": "off_hand", "offset": 0,
                             "kind": SHIELD_KIND, "when": "in_hand"}],
                    "101": [{"step": "layer", "slot": "hand", "offset": LAYER_IN_HAND,
                             "when": "melee"},
                            {"step": "layer", "slot": "off_hand", "offset": LAYER_OFF_HAND,
                             "not_kind": SHIELD_KIND, "when": "melee"},
                            {"step": "layer", "slot": "ranged", "offset": LAYER_IN_HAND,
                             "when": "shooting"}],
                    "110": [{"step": "layer", "slot": "off_hand",
                             "offset": LAYER_SHIELD_BACK,
                             "kind": SHIELD_KIND, "when": "at_rest"}],
                    "111": [{"step": "layer", "slot": "hand", "offset": LAYER_AT_REST,
                             "when": "at_rest"},
                            {"step": "layer", "slot": "ranged", "offset": LAYER_AT_REST,
                             "when": "not_shooting"},
                            {"step": "layer", "slot": "off_hand", "offset": LAYER_OFF_REST,
                             "not_kind": SHIELD_KIND, "when": "at_rest"}],
                },
            },
            # Торговля: экран обмена, деньги и множители цены (VA 0x43346C,
            # 0x41A6CC, 0x41AF3C).
            "trade": trade_rules(),
            # точность удара: навык оружия (VA 0x41B4CC) и поправка на
            # дальность при стрельбе (VA 0x41ADD8)
            "accuracy": accuracy_rules(),
            "effects": effect_rules(),
            "buildings": building_rules(),
            "carry": carry_rules(),
            "jewellery": jewellery_rules(),
            "craft": craft_rules(),
            "piles": pile_rules(),
            "orders": order_rules(),
            # ГРАФ ПЕРЕХОДОВ ЦЕЛИКОМ — 250 записей, номер = место в таблице
            # 0x7B2B6C. Покарточные списки для действия 69 не годятся: оно
            # адресует запись номером и может назвать переход чужой карты.
            "transitions": _transitions(),
            # ГРАФ КАЖДОЙ ИГРЫ ОТДЕЛЬНО. Номер записи у донора значит другой
            # переход: его таблица на 350 записей против наших 250. Дерево
            # разговора несёт имя своей игры (`game`), по нему клиент и
            # выбирает граф. `transitions` остаётся канонным — на него
            # смотрят старые сейвы и тесты.
            "transitions_by_game": _transitions_by_game(project),
            # Начальное состояние трёхсот квестов — хвост QUESTS.RES, тот же
            # блок, что движок держит в 0x6A50E8 и пишет в сейв (0x423CB8).
            "quests": _quest_state(project),
            "cells": cell_rules(),
            "creatures": creature_rules(),
            # Глобальная карта: сетка 24x32 из exe, туман, значки локаций
            # и проходимость (konung2/worldmap.py, VA 0x4277F4).
            "world_map": worldmap_pack.rules(project) if project else worldmap_pack.canon(),
            # Инвентарь юнита: пять слотов экипировки и мешок на 42 ячейки
            # (смещения полей — konung2/items.py, VA 0x4129AB и 0x4394BA).
            "inventory": {
                "policy": "konung2_exe_0x4394BA_0x4129AB",
                "slots": dict(SLOT_FIELDS),
                "bag_slots": BAG_SLOTS,
                # строки подсказки предмета (печатник 0x4315A0): короткие
                # имена полей и виды отравы — дословно из exe
                "tooltip": tooltip_strings(),
            },
            # Опыт, уровни и прокачка — konung2/progress.py: пороги, цена
            # подъёма, потолки и предел роста навыков сняты с кода движка.
            "progression": progression_rules(),
            # Смерть (VA 0x416A00). У ЧЕЛОВЕКА жребий из трёх блоков —
            # 3, 11 и 12, выбор по остатку от деления на три. У ТВАРИ
            # вариант всегда один, блок 3: та же функция сразу за проверкой
            # бита 0x40 кладёт тройку без всякого жребия.
            "death_variants": DEATH_VARIANTS,
            "beast_death_variants": 1,
            # шанс простоя — жребий 1 из N, пока играет стойка (VA 0x416D92)
            "idle_chance": IDLE_CHANCE,
            # СКОЛЬКО ТАКТОВ ЗАНИМАЕТ КЛЕТКА, по блокам хода — таблица
            # 0x45FE90. Движок кладёт в походку юнита (+0xFD) разность
            # «база блока минус скорость (+0x1D)» (VA 0x429B3E) и переводит
            # юнита в следующую клетку, когда счётчик подшагов +0xFB до неё
            # дорос (VA 0x41612B прибавляет, VA 0x4143xx сравнивает).
            "move_block_ticks": move_block_ticks(),
            # ТВАРЬ ходит своей таблицей 0x462734 по ТЕЛУ (+0xFC), а не
            # четырьмя блоками: FUN_00429B2C (VA 0x429B93) кладёт в походку
            # `таблица[тело] − скорость`. У большинства тел 12 тактов на
            # клетку, у тела 17 — 7, нули у неходячих. Бега у тварей нет.
            "beast_move_ticks": beast_move_ticks(),
            # Смещения подшагов: таблицы 0x459AD4 (X) и 0x459D14 (Y), по
            # восемь чисел на походку в порядке W, NW, N, NE, E, SE, S, SW.
            # Каждый такт движок прибавляет готовое смещение своего
            # направления, поэтому смещение × походка — это ровно переход в
            # соседнюю клетку.
            "gait_steps": gait_steps(),
        },
    }


def _hero_signature(equipment_layers, body_palettes, body_shapes=None,
                    body_pairs=None) -> dict[str, Any]:
    """Из чего собран набор кадров: файл игры плюс список слоёв и палитр."""
    source = Path(game_file("HEROES.RES"))
    stat = source.stat()
    return {
        "source": {"size": stat.st_size, "mtime": int(stat.st_mtime)},
        "layers": {str(k): v for k, v in sorted((equipment_layers or {}).items())},
        "palettes": sorted(body_palettes or ()),
        "shapes": sorted(body_shapes or ()),
        # пары «форма + палитра»: их появление обязано пересобрать кадры
        "body_pairs": sorted(map(list, body_pairs or ())),
        # ВЕРСИЯ САМОЙ ВЫПЕЧКИ, а не только её входных данных. Паспорт
        # перечисляет слои, палитры и формы — и при неизменных списках сборка
        # берёт готовые кадры из прошлого пака. Поэтому правку ЛОГИКИ обязан
        # сопровождать подъём этого числа, иначе она молча не доедет.
        #
        # 3 — кеш выпечки слоя стал учитывать палитру: до того ключ был
        # (запись, слой), и все палитры слоя делили один кадр. Правка ключа
        # сама по себе ничего не изменила ровно потому, что паспорт совпал и
        # кадры переиспользовались.
        # 4 — лист на НАБОР, а не на палитру: ключ снаряжения стал
        # `eq{слой}p{палитра}`, тела-палитры отделены в `bodypal{палитра}`.
        # Без подъёма этого числа сборка отдала бы старые листы из кеша.
        # 5 — пара «форма + палитра» стала ТРОЙКОЙ с игрой: тела и палитры
        # «Продолжения легенды» пекутся его HEROES.RES и его блоком палитр
        # (218 палитр из 256 общие, форм у него больше), ключ набора —
        # `legend:{форма}:{палитра}`.
        "format": 7,
    }


def _reuse_hero(root: Path, reuse: Path | None,
                signature: dict[str, Any]) -> dict[str, Any] | None:
    """Взять готовые кадры из прошлой сборки, если собраны из того же самого.

    Кадры героя — это 12 тысяч файлов и почти вся длительность сборки, а
    зависят они только от HEROES.RES и списка нужных слоёв. Пересобирать их
    из-за правки одного числа в расстановке — бессмысленно долго.
    """
    if reuse is None:
        return None
    cache_path = reuse / "assets" / "units" / "index.json"
    if not cache_path.is_file():
        return None
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if cached.get("signature") != signature:
        return None
    if "frames" not in cached:          # старый кэш, до разделения
        return None
    source = reuse / "assets" / "units"
    target = root / "assets" / "units"
    if source.resolve() == target.resolve():
        return cached.get("frames")
    target.mkdir(parents=True, exist_ok=True)
    for path in source.iterdir():
        if not path.is_file():
            continue
        destination = target / path.name
        try:
            os.link(path, destination)          # жёсткая ссылка: мгновенно
        except OSError:
            shutil.copy2(path, destination)
    return cached.get("frames")


#: Тело слоем: ноль — обычное, иначе 0x30 плюс номер (VA 0x424200).
BODY_LAYER_BASE = 0x30
#: Блоки анимаций тварей — та же нумерация, что у людей в боевой стойке.
#: Классы квестовых вещей, которые игра создаёт по ходу, а не раскладывает
#: по картам: без них ветка применения обрывается. Номера — из разбора
#: VA 0x436C48:
#:
#:     0, 21   Береста и Уголёк — из них выходит класс 24
#:     24      Донесение Повелителю о капище (его несёт Почтовый ястреб)
#:     9…12    карты островов, открывающие локации 20, 13, 23 и 19
#:     22      Почтовый ястреб
QUEST_ITEM_CLASSES = (0, 9, 10, 11, 12, 21, 22, 24)
#: Группа квестовых вещей — с неё начинается разбор применения.
QUEST_ITEM_GROUP = 11
POTION_ITEM_CLASSES = range(EMPTY_JAR_CLASS, POTION_WISDOM + 1)
POTION_ITEM_GROUP = 9

# У твари блоков анимации шесть (0…5), и БЛОК 4 мы не вывозили вовсе — а это
# ровно та поза, в которой лежат «встающие»: скелеты, ичетики и кикиморы
# расставлены в мире с `pose == 4` (VA 0x410010 начинает разбор с проверки
# «поза 4 и кадр 0 — доигрывай анимацию»). Имя своё: в движке блоки безымянны.
CREATURE_POSES = {"stand": 0, "walk": 1, "hit": 2, "death_1": 3,
                  "rise": 4, "attack": 5}


def _creature_signature(wanted) -> dict[str, Any]:
    """Из чего собраны наборы тварей: файлы игр плюс список пар.

    Тот же паспорт, что у кадров героя (_hero_signature), и по той же
    причине: наборы зависят только от OBJECTS.RES обеих игр и от списка
    «порода + масть», а стоят они три минуты на каждой сборке — сборка
    одной карты уходила в восемь минут почти целиком на них.
    """
    from konung2 import donor as donor_games
    out: dict[str, Any] = {"pairs": sorted(map(list, wanted or ()))}
    sources = [("canon", Path(game_file("OBJECTS.RES")))]
    if donor_games.available():
        sources.append(("legend", Path(donor_games.donor_file("OBJECTS.RES"))))
    for name, path in sources:
        try:
            stat = path.stat()
            out[name] = {"size": stat.st_size, "mtime": int(stat.st_mtime)}
        except OSError:
            out[name] = None
    #: ВЕРСИЯ ВЫПЕЧКИ НАБОРОВ — поднимать при правке ЛОГИКИ, иначе она
    #: молча не доедет: паспорт совпадёт и наборы возьмутся из прошлого пака.
    out["format"] = 1
    return out


def _reuse_creatures(root: Path, reuse: Path | None,
                     signature: dict[str, Any]) -> dict[str, Any] | None:
    """Взять готовые наборы тварей из прошлой сборки, если те же входные."""
    if reuse is None:
        return None
    cache_path = reuse / "assets" / "creatures" / "index.json"
    if not cache_path.is_file():
        return None
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if cached.get("signature") != signature or "sets" not in cached:
        return None
    source = reuse / "assets" / "creatures"
    target = root / "assets" / "creatures"
    if source.resolve() != target.resolve():
        target.mkdir(parents=True, exist_ok=True)
        for path in source.iterdir():
            if path.is_file() and not (target / path.name).is_file():
                shutil.copy2(path, target / path.name)
    return {"sheets": cached["sheets"], "sets": cached["sets"]}


def _export_creatures(root: Path, wanted, reuse: Path | None = None) -> dict[str, Any]:
    """Кадры тварей: свой набор на породу и на масть.

    Человек собирается из слоёв, а тварь рисуется целым набором из
    OBJECTS.RES (записи 0…29). Набор выбирает байт unit+0xFC, масть —
    палитра unit+0x2E; см. konung2/creatures.py.
    """
    from konung2.creatures import CreatureRes, DIRECTIONS
    from konung2.res import read_palettes
    if not wanted:
        return {}
    signature = _creature_signature(wanted)
    ready = _reuse_creatures(root, reuse, signature)
    if ready is not None:
        return ready
    res = CreatureRes.from_game()
    # ТВАРНЫЕ НАБОРЫ 23 И 24 ЕСТЬ ТОЛЬКО У ДОНОРА — у нас эти гнёзда пусты
    # (konung2/donor.py: DONOR_CREATURE_SLOTS). Ими нарисованы и его «люди-
    # наборы»: жители пустыни с породами 0x54+ рисуются целым набором кадров,
    # как звери, — Позвизд в Дубках ходит набором 24.
    from konung2 import donor as donor_games
    donor_creatures = None
    if donor_games.available():
        try:
            with open(donor_games.donor_file("OBJECTS.RES"), "rb") as stream:
                donor_creatures = CreatureRes(stream.read())
        except OSError:
            donor_creatures = None

    def source_of(body: int) -> CreatureRes:
        if donor_creatures is not None and body in donor_games.DONOR_CREATURE_SLOTS:
            return donor_creatures
        return res
    palettes = read_palettes()
    out_dir = Path("assets") / "creatures"
    (root / out_dir).mkdir(parents=True, exist_ok=True)
    # Кадры тварей идут на общие ЛИСТЫ, как и кадры героя: движок держит
    # OBJECTS.RES одним куском, а не файлами на кадр. Лист заводится на
    # каждую пару «порода, масть» — тогда цветов на нём не больше 256 и он
    # пишется индексированным PNG без потерь.
    sheets = AtlasWriter(root, out_dir, "creature")
    creatures: dict[str, Any] = {}
    # ТЕНЬ ОТ МАСТИ НЕ ЗАВИСИТ: это чёрная маска спанов, палитру она не
    # трогает вовсе. Поэтому распаковывается она один раз на пару «порода,
    # кадр» и кладётся на общий лист теней — иначе одна и та же маска
    # разбиралась бы заново для каждой масти (у иных пород их шесть).
    shadow_cache: dict[tuple[int, int], dict[str, Any]] = {}
    for body, palette_index in sorted(wanted):
        keeper = source_of(body)
        try:
            table = keeper.animations(body)
            frames = keeper.frames(body)
        except (ValueError, IndexError, struct.error):
            continue
        palette = palettes[palette_index % len(palettes)]
        exported: dict[str, Any] = {}
        cache: dict[int, dict[str, Any]] = {}

        def frame_of(number: int) -> dict[str, Any] | None:
            if number in cache:
                return cache[number]
            if not 0 <= number < len(frames):
                return None
            sprite, dx, dy = keeper.decode(body, number, palette=palette)
            if sprite is None:
                return None
            key = f"c{body}p{palette_index}"
            shot = {**sheets.add(sprite, key), "offset_x": dx, "offset_y": dy}
            # Тень — отдельная МАСКА со своим смещением, и объявлена она не у
            # каждого кадра (в дескрипторе тогда стоит −1). Палитра ей не
            # нужна: маска чёрная, поэтому она общая на все масти породы.
            shadow_key = (body, number)
            if shadow_key not in shadow_cache:
                mask, sdx, sdy = keeper.decode(body, number, shadow=True)
                shadow_cache[shadow_key] = (
                    {**sheets.add(mask, "shadow"), "offset_x": sdx, "offset_y": sdy}
                    if mask is not None else None)
            if shadow_cache[shadow_key] is not None:
                shot["shadow"] = shadow_cache[shadow_key]
            cache[number] = shot
            return cache[number]

        for pose, block in CREATURE_POSES.items():
            if block >= len(table):
                continue
            directions = []
            for direction in range(DIRECTIONS):
                numbers = table[block][direction]
                shots = [frame_of(number) for number in numbers]
                directions.append([shot for shot in shots if shot])
            if any(directions):
                exported[pose] = directions
        if exported:
            creatures.setdefault(str(body), {})[str(palette_index)] = exported
    # Листы кладём рядом с наборами: клиент тянет их и режет сам.
    result = {"sheets": sheets.flush(), "sets": creatures}
    # Паспорт рядом с листами — по нему следующая сборка возьмёт готовое.
    index = root / "assets" / "creatures" / "index.json"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text(json.dumps({"signature": signature, **result},
                                ensure_ascii=False), encoding="utf-8")
    return result


def _png_size(path: Path) -> tuple[int, int]:
    """Ширина и высота PNG из IHDR — без графических библиотек."""
    with open(path, "rb") as stream:
        head = stream.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        raise ValueError(f"{path}: не PNG")
    return struct.unpack(">II", head[16:24])


def _custom_creatures(root: Path, project: Path,
                      creatures: dict[str, Any]) -> dict[str, Any]:
    """Свои наборы тварей — из ``project/creatures/<имя>/set.json``.

    Канон рисует тварь набором из OBJECTS.RES, и больше тридцати пород туда
    не положишь. Этот слой — способ поставить в игру существо, которого в
    игре нет: кадры приходят готовым листом со своей разметкой и
    подшиваются к общим листам ещё одним номером.

    Набор описывает сам себя: тело, масть, лист и позы «поза -> восемь
    направлений -> кадры». Кадр — тот же прямоугольник со смещением, что и у
    канонных, поэтому клиенту разница не видна вовсе: он читает
    ``creatures.sets`` и не спрашивает, откуда набор взялся.

    Номера листов внутри набора свои, от нуля, — здесь они сдвигаются на
    место в общем списке.
    """
    source = Path(project) / "creatures"
    if not source.is_dir():
        return creatures
    sheets = list(creatures.get("sheets") or [])
    sets: dict[str, Any] = {body: dict(palettes) for body, palettes
                            in (creatures.get("sets") or {}).items()}
    #: Опись своих наборов по имени: по ней клиент находит набор, не зная
    #: номера тела. Нужна, чтобы набор можно было НАДЕТЬ НА ИГРОКА: герой
    #: спрашивает кадры тем же `actorFrames`, а тот первым делом смотрит в
    #: наборы тварей, так что хватает тела, масти и бита 0x40 в породе.
    custom: dict[str, Any] = dict(creatures.get("custom") or {})
    out_dir = Path("assets") / "creatures"
    (root / out_dir).mkdir(parents=True, exist_ok=True)
    for folder in sorted(p for p in source.iterdir() if p.is_dir()):
        document_path = folder / "set.json"
        if not document_path.is_file():
            continue
        document = json.loads(document_path.read_text(encoding="utf-8"))
        name = str(document.get("name") or folder.name)
        image = folder / str(document.get("sheet") or "sheet.png")
        if not image.is_file():
            raise ValueError(f"набор {name}: нет листа {image}")
        body = str(document["body"])
        if body in sets:
            raise ValueError(f"набор {name}: тело {body} уже занято канонным")
        target = out_dir / f"custom_{name}.png"
        shutil.copyfile(image, root / target)
        width, height = _png_size(image)
        number = len(sheets)
        sheets.append({"path": target.as_posix(), "width": width,
                       "height": height, "indexed": False, "custom": name})
        def renumber(frame: dict[str, Any]) -> dict[str, Any]:
            #: тень лежит на том же листе, что и тело, и номер ей нужен свой
            shot = {**frame, "sheet": number}
            if isinstance(frame.get("shadow"), dict):
                shot["shadow"] = {**frame["shadow"], "sheet": number}
            return shot

        poses = {pose: [[renumber(frame) for frame in frames]
                        for frames in directions]
                 for pose, directions in (document.get("poses") or {}).items()}
        if not poses:
            raise ValueError(f"набор {name}: ни одной позы")
        palette = str(document.get("palette", 0))
        sets.setdefault(body, {})[palette] = poses
        custom[name] = {"body": int(body), "palette": palette,
                        "title": document.get("title") or name,
                        "poses": sorted(poses),
                        "source": document.get("source") or {}}
    out = {"sheets": sheets, "sets": sets}
    if custom:
        out["custom"] = custom
    return out


def _custom_projectiles(root: Path, project: Path) -> dict[str, Any]:
    """Свои снаряды — из ``project/projectiles/<имя>/set.json``.

    Канонная стрела берёт спрайты из INTERF.RES: пара кадров на направление,
    и лежат они в интерфейсе карты. Этот слой кладёт рядом снаряд со своим
    набором — восемь направлений с любым числом кадров плюс вспышка попадания.
    Клиент находит набор по имени, которое несёт сам выстрел.
    """
    source = Path(project) / "projectiles"
    if not source.is_dir():
        return {}
    sheets: list[dict[str, Any]] = []
    sets: dict[str, Any] = {}
    out_dir = Path("assets") / "projectiles"
    (root / out_dir).mkdir(parents=True, exist_ok=True)
    for folder in sorted(p for p in source.iterdir() if p.is_dir()):
        document_path = folder / "set.json"
        if not document_path.is_file():
            continue
        document = json.loads(document_path.read_text(encoding="utf-8"))
        name = str(document.get("name") or folder.name)
        image = folder / str(document.get("sheet") or "sheet.png")
        if not image.is_file():
            raise ValueError(f"снаряд {name}: нет листа {image}")
        directions = document.get("directions") or []
        if len(directions) != 8 or not all(directions):
            raise ValueError(f"снаряд {name}: нужно восемь непустых направлений")
        target = out_dir / f"{name}.png"
        shutil.copyfile(image, root / target)
        width, height = _png_size(image)
        number = len(sheets)
        sheets.append({"path": target.as_posix(), "width": width,
                       "height": height, "indexed": False, "custom": name})
        sets[name] = {
            "title": document.get("title") or name,
            #: чем рисовать: огонь в оригинале идёт сложением (Trans 1 у
            #: снарядов), обычной альфой у него вылезает чёрная кайма
            "blend": document.get("blend") or "normal",
            "trans": document.get("trans"),
            "directions": [[{**frame, "sheet": number} for frame in frames]
                           for frames in directions],
            "burst": [{**frame, "sheet": number}
                      for frame in (document.get("burst") or [])],
            "source": document.get("source") or {},
        }
    return {"sheets": sheets, "sets": sets} if sets else {}


def _custom_weather(root: Path, project: Path) -> dict[str, Any]:
    """Погода — из ``project/weather/<имя>/set.json``.

    У канона погоды нет вовсе: в KONUNG2.EXE ни дождя, ни снега. Это наша
    добавка, и закон у неё снят с Diablo II (разбор в docs/RAIN.md).

    Набор отличается от снаряда одним: вместо восьми НАПРАВЛЕНИЙ у него
    несколько РАЗМЕРОВ. У колец дождя это глубина — движок держит четыре
    набора кадров, от крупного к мелкому, и берёт тем мельче, чем дальше
    кольцо от зрителя.
    """
    source = Path(project) / "weather"
    if not source.is_dir():
        return {}
    sheets: list[dict[str, Any]] = []
    sets: dict[str, Any] = {}
    out_dir = Path("assets") / "weather"
    (root / out_dir).mkdir(parents=True, exist_ok=True)
    for folder in sorted(p for p in source.iterdir() if p.is_dir()):
        document_path = folder / "set.json"
        if not document_path.is_file():
            continue
        document = json.loads(document_path.read_text(encoding="utf-8"))
        name = str(document.get("name") or folder.name)
        image = folder / str(document.get("sheet") or "sheet.png")
        if not image.is_file():
            raise ValueError(f"погода {name}: нет листа {image}")
        sizes = document.get("sizes") or []
        if not sizes or not all(sizes):
            raise ValueError(f"погода {name}: нужен хотя бы один непустой размер")
        target = out_dir / f"{name}.png"
        shutil.copyfile(image, root / target)
        width, height = _png_size(image)
        number = len(sheets)
        sheets.append({"path": target.as_posix(), "width": width,
                       "height": height, "indexed": False, "custom": name})
        sets[name] = {
            "title": document.get("title") or name,
            #: серая лесенка исходника значит сложение, а не краску
            "blend": document.get("blend") or "additive",
            "sizes": [[{**frame, "sheet": number} for frame in frames]
                      for frames in sizes],
            "source": document.get("source") or {},
        }
    return {"sheets": sheets, "sets": sets} if sets else {}


def _export_hero(root: Path, equipment_layers: dict[int, list[int]] | None = None,
                 body_palettes: set[int] | None = None,
                 body_shapes: set[int] | None = None,
                 body_pairs: set[tuple[int, int]] | None = None,
                 reuse: Path | None = None,
                 project: Path | None = None) -> dict[str, Any]:
    """Кадры героя: тело всех двадцати блоков плюс слои экипировки.

    Кадр — запись HEROES.RES на холсте 256×150 с якорем ног (127, 144);
    offset_x/offset_y кадра и его теневой маски заданы форматом (см.
    konung2/heroes.py), поэтому анимация не дрожит по построению. Предмет в
    руке — та же запись, но другой слой и своя палитра из класса предмета.
    """
    signature = _hero_signature(equipment_layers, body_palettes, body_shapes,
                                body_pairs)
    frames = _reuse_hero(root, reuse, signature)
    if frames is not None:
        return {**frames, **_hero_rules(project)}

    heroes = HeroesRes.from_game()
    palette = read_palettes()[0]
    # ВТОРАЯ ИГРА — ВТОРОЙ ФАЙЛ КАДРОВ И ВТОРОЙ БЛОК ПАЛИТР. Формат у него
    # тот же, но с двумя поправками (konung2/heroes.py, LegendHeroesRes):
    # таблица смещений записей на 0x3628 вместо 0x33E0, а слои сдвинуты на
    # два. Таблицы анимации при этом побайтно общие, поэтому кадры берутся
    # по НАШИМ номерам записей. Палитр расходится 38 из 256.
    from konung2 import donor as _donor
    from konung2.heroes import LegendHeroesRes
    legend_heroes = legend_palettes = None
    if _donor.available():
        try:
            legend_heroes = LegendHeroesRes.from_game()
            legend_palettes = read_palettes(_donor.graph_palette_block())
        except OSError:
            legend_heroes = legend_palettes = None

    out_dir = Path("assets") / "units"
    (root / out_dir).mkdir(parents=True, exist_ok=True)
    # Все кадры героя, его тел и слоёв экипировки идут на ОБЩИЕ ЛИСТЫ —
    # так же, как движок держит весь HEROES.RES одним куском памяти с
    # таблицей смещений (VA 0x43C2E8). Иначе пак разворачивается в десятки
    # тысяч отдельных файлов, и браузер делает столько же запросов.
    sheets = AtlasWriter(root, out_dir, "hero")
    cache: dict[int, dict[str, Any]] = {}

    def export_record(record: int) -> dict[str, Any]:
        if record in cache:
            return cache[record]
        sprite, dx, dy = heroes.decode_layer(record, palette=palette)
        if sprite is None:
            raise ContentBuildError(f"кадр героя {record} не декодируется")
        frame: dict[str, Any] = {
            # номер записи нужен клиенту, чтобы взять слой экипировки того же
            # кадра: оружие и тело так не могут разъехаться по определению
            "record": record,
            **sheets.add(sprite, "hero"),
            "offset_x": dx,
            "offset_y": dy,
        }
        shadow, sdx, sdy = heroes.decode_shadow(record)
        if shadow is not None:
            frame["shadow"] = {**sheets.add(shadow, "shadow"),
                               "offset_x": sdx, "offset_y": sdy}
        cache[record] = frame
        return frame

    # Экипировка — те же записи, но другой слой и своя палитра. Номер слоя
    # хранится в классе предмета (konung2/items.py), палитра — там же
    # байтовым смещением, поэтому индекс = смещение // 0x200.
    palettes = read_palettes()
    layer_cache: dict[tuple[int, int], dict[str, Any] | None] = {}

    def export_layer(record: int, layer: int, palette_index: int) -> dict[str, Any] | None:
        # КЛЮЧ ВКЛЮЧАЕТ ПАЛИТРУ. Раньше здесь стояло `key = (record, layer)`,
        # и кеш возвращал кадр ПЕРВОЙ испечённой палитры слоя всем остальным.
        # Пока набор был один на слой, это не мешало; с парами «слой+палитра»
        # ключи 23, 23:3 и 23:9 стали указывать на один и тот же участок листа,
        # и чёрная броня воина Повелителя рисовалась палитрой кожанки — то
        # есть правка по палитрам молча не работала.
        key = (record, layer, palette_index)
        if key in layer_cache:
            return layer_cache[key]
        sprite, dx, dy = heroes.decode_layer(
            record, layer=layer,
            palette=palettes[palette_index if palette_index < len(palettes) else 0])
        if sprite is None:
            layer_cache[key] = None
            return None
        # Кадр не ложится отдельным файлом: он идёт НА ЛИСТ, как в движке
        # спрайт ложится в общую арену (VA 0x43C2E8), а вместо смещения в
        # арене мы запоминаем прямоугольник на листе.
        # ЛИСТ НА НАБОР, А НЕ НА ПАЛИТРУ. Ключ раньше был `pal{палитра}`, и
        # все слои одного цвета сваливались на один лист: у hero_65 их
        # оказалось шестнадцать штук на 5.78 МБ. Юниту нужен ОДИН набор, а
        # качал он весь лист.
        #
        # Заодно это чинит и вес: на смешанном листе набегало 256 цветов плюс
        # прозрачный, палитра не влезала на единицу, и лист писался
        # полноцветным. У отдельного набора цветов заметно меньше (у чёрной
        # брони 23:9 — двадцать шесть), и PNG выходит индексированным без
        # единой потери.
        layer_cache[key] = {**sheets.add(sprite, f"eq{layer}p{palette_index}"),
                            "offset_x": dx, "offset_y": dy}
        return layer_cache[key]

    # Восемь наборов: четыре позы в двух стойках. Номера блоков и правила
    # перехода между ними сняты с таблиц движка, см. konung2/heroes.py.
    animations: dict[str, Any] = {}
    for stance, poses in STANCE_BLOCKS.items():
        animations[stance] = {
            pose: [[export_record(record)
                    for record in heroes.animation(kind, direction)]
                   for direction in range(DIRECTIONS)]
            for pose, kind in poses.items()
        }
    # Действия общие для обеих стоек: пары у них нет ни в одной из таблиц.
    animations["actions"] = {
        name: [[export_record(record)
                for record in heroes.animation(kind, direction)]
               for direction in range(DIRECTIONS)]
        for name, kind in ACTION_BLOCKS.items()
    }
    # НАБОР КОНЧИЛСЯ — ЛИСТЫ НА ДИСК. Дальше кадры анимации не добавляются, а
    # держать их лист в памяти до конца сборки не на что: наборов больше сотни,
    # и вместе они в память не влезают. Такой же `seal` стоит после каждого
    # следующего набора.
    sheets.seal()
    # Тело в чужой палитре: движок красит юнита целиком, подставляя палитру
    # перед блиттером ([0x8A7318], VA 0x426707), — так один набор кадров
    # служит всем. Мы делаем ровно это: те же записи, другая палитра.
    # Тело слоем: байт unit+0xFC выбирает не палитру, а СЛОЙ записи —
    # ноль это обычное мужское тело, а дальше 0x30 + число (VA 0x424200).
    # У Велиславны там единица, и рисуется она слоем 49.
    body_layers: dict[str, Any] = {}
    for body in sorted(body_shapes or ()):
        if not body:
            continue
        frames = {}
        for record in sorted(cache):
            sprite, dx, dy = heroes.decode_layer(
                record, layer=BODY_LAYER_BASE + body, palette=palette)
            if sprite is None:
                continue
            frames[str(record)] = {**sheets.add(sprite, f"body{body}"),
                                   "offset_x": dx, "offset_y": dy}
        sheets.seal()
        if frames:
            body_layers[str(body)] = {"layer": BODY_LAYER_BASE + body, "frames": frames}

    # ФОРМА В СВОЕЙ ПАЛИТРЕ. Движок ставит палитру юнита и уже ею рисует слой
    # тела (VA 0x425DB4), то есть форма и цвет независимы. Ключ «1:70» —
    # форма 1 в палитре 70; ключ без палитры остался набором по умолчанию,
    # чтобы старые паки продолжали работать.
    for pair in sorted(body_pairs or ()):
        # Старые паки звали пары двойками, новые — тройками с игрой.
        game, body, palette_index = pair if len(pair) == 3 else ("", *pair)
        if not body:
            continue
        # ЕГО КАДРЫ И ЕГО ПАЛИТРА. Читатель знает две поправки его файла
        # (LegendHeroesRes): таблица смещений на 0x3628 и сдвиг слоёв на
        # два. Без них его записи по канонным адресам либо пусты, либо
        # отдают обрывки — на этом я едва не выпек мусор. Номера записей
        # берутся НАШИ: таблицы анимации у игр побайтно одинаковы.
        legend = game == "legend" and legend_heroes is not None
        source = legend_heroes if legend else heroes
        block = legend_palettes if legend else palettes
        prefix = "legend" if legend else ""
        frames = {}
        for record in sorted(cache):
            sprite, dx, dy = source.decode_layer(
                record, layer=BODY_LAYER_BASE + body,
                palette=block[palette_index % len(block)])
            if sprite is None:
                continue
            frames[str(record)] = {
                **sheets.add(sprite, f"{prefix}body{body}pal{palette_index}"),
                "offset_x": dx, "offset_y": dy}
        sheets.seal()
        if frames:
            key = (f"legend:{body}:{palette_index}" if legend
                   else f"{body}:{palette_index}")
            body_layers[key] = {
                "layer": BODY_LAYER_BASE + body,
                "palette": palette_index, "frames": frames}
            if legend:
                body_layers[key]["game"] = "legend"

    bodies: dict[str, Any] = {}
    for palette_index in sorted(body_palettes or ()):
        frames = {}
        for record in sorted(cache):
            sprite, dx, dy = heroes.decode_layer(
                record, palette=palettes[palette_index % len(palettes)])
            if sprite is None:
                continue
            # Ключ отличается от снаряжения: раньше и тела, и слои
            # ложились под `pal{палитра}` и делили лист.
            frames[str(record)] = {**sheets.add(sprite, f"bodypal{palette_index}"),
                                   "offset_x": dx, "offset_y": dy}
        sheets.seal()
        bodies[str(palette_index)] = {"frames": frames}

    # Слои экипировки: тот же кадр, другой слой записи. Ключ — номер записи,
    # клиент берёт его из кадра тела, поэтому оружие не может разъехаться.
    # Ключей у слоя теперь два вида: «23» — набор по умолчанию (первая
    # палитра слоя, как было раньше) и «23:9» — набор под конкретную палитру.
    # Клиент спрашивает точный ключ и откатывается на слой без палитры, если
    # такого нет; старые паки от этого не ломаются.
    equipment: dict[str, Any] = {}
    # ИМЯ ЗДЕСЬ НЕ `palettes`: так зовутся цветовые палитры HEROES.RES, их
    # читает замыкание export_layer. Переиспользование имени подсовывало ему
    # список номеров вместо палитры и роняло сборку.
    for layer, layer_palettes in (equipment_layers or {}).items():
        # старая форма звала это поле одним числом — принимаем и её
        indices = ([layer_palettes] if isinstance(layer_palettes, int)
                   else list(layer_palettes))
        for position, palette_index in enumerate(indices):
            frames = {}
            for record in sorted(cache):
                frame = export_layer(record, layer, palette_index)
                if frame is not None:
                    frames[str(record)] = frame
            sheets.seal()
            entry = {"palette": palette_index, "frames": frames}
            equipment[f"{layer}:{palette_index}"] = entry
            if position == 0:
                equipment[str(layer)] = entry
        # СТРАХОВКА ОТ МОЛЧАЛИВОГО СЛИЯНИЯ. Дважды подряд правка по палитрам
        # не доезжала незаметно: сперва кеш выпечки не учитывал палитру, потом
        # паспорт набора совпал и кадры переиспользовались из прошлого пака.
        # В обоих случаях ключи в паке ПОЯВЛЯЛИСЬ, а кадры за ними были одни и
        # те же. Теперь сборка об этом кричит в лог.
        if len(indices) > 1:
            slots = {json.dumps(equipment[f"{layer}:{p}"]["frames"].get(
                next(iter(equipment[f"{layer}:{p}"]["frames"]), ""), None),
                sort_keys=True) for p in indices}
            if len(slots) == 1:
                print(f"ВНИМАНИЕ: слой {layer} в палитрах {indices} дал "
                      f"одинаковые кадры — палитра не применилась")

    # БЕСЦВЕТНЫЕ СЛОИ — по одному разу на слой, без умножения на масти.
    # Спрайты в HEROES.RES палитровые, цвет подставляется после (VA
    # 0x425DB4), поэтому геометрию можно вывезти один раз, а палитру отдать
    # клиенту таблицей. Пекутся РЯДОМ со старыми наборами: пока обе выпечки
    # живы, их можно сверить кадр в кадр, и только потом переключать.
    # Пиксель листа несёт НОМЕР ПАЛИТРЫ в яркости — палитра-тождество.
    identity = [(value, value, value) for value in range(256)]
    plain_sheets = AtlasWriter(root, out_dir, "plain")
    plain: dict[str, Any] = {}
    wanted_layers: dict[str, set[int]] = {"canon": set(), "legend": set()}
    for pair in sorted(body_pairs or ()):
        game, body, _ = pair if len(pair) == 3 else ("", *pair)
        key = "legend" if game == "legend" and legend_heroes is not None else "canon"
        wanted_layers[key].add(0 if not body else BODY_LAYER_BASE + body)
    for layer in (equipment_layers or {}):
        wanted_layers["canon"].add(int(layer))
        if legend_heroes is not None:
            wanted_layers["legend"].add(int(layer))
    for game, layers in wanted_layers.items():
        source = legend_heroes if game == "legend" else heroes
        if source is None:
            continue
        for layer in sorted(layers):
            found = {}
            for record in sorted(cache):
                sprite, dx, dy = source.decode_layer(record, layer=layer,
                                                     palette=identity)
                if sprite is None:
                    continue
                found[str(record)] = {
                    **plain_sheets.add(sprite, f"{game}{layer}"),
                    "offset_x": dx, "offset_y": dy}
            plain_sheets.seal()
            if found:
                plain[f"{game}:{layer}"] = {"frames": found}

    frames = {
        "id": "hero",
        # Листы — это и есть «арена»: клиент тянет их и режет по
        # прямоугольникам, а не запрашивает файл на каждый кадр.
        "sheets": sheets.flush(),
        "animations": animations,
        "equipment": equipment,
        "bodies": bodies,
        "body_layers": body_layers,
        # Бесцветные слои и их листы: ключ «игра:слой», пиксель — номер
        # палитры. Красит клиент, палитры лежат в assets/palettes_*.png.
        "plain_layers": plain,
        "plain_sheets": plain_sheets.flush(),
    }

    # Рядом с кадрами кладём их «паспорт»: следующая сборка с тем же
    # HEROES.RES и тем же набором слоёв возьмёт всё готовым.
    _write_json(root / out_dir / "index.json",
                {"signature": signature, "frames": frames})
    return {**frames, **_hero_rules(project)}


_CLASS_KINDS: dict[int, int] | None = None


def _class_kinds() -> dict[int, int]:
    """Вид записи по классу — читается один раз."""
    global _CLASS_KINDS
    if _CLASS_KINDS is None:
        from konung2.gamefile import class_kinds
        try:
            _CLASS_KINDS = class_kinds()
        except (OSError, ValueError, IndexError):
            _CLASS_KINDS = {}
    return _CLASS_KINDS


def _unit_role(unit_index: int, map_number: int | None) -> int:
    """Должность жителя в поселении, ноль — обычный."""
    if map_number is None or not unit_index:
        return 0
    try:
        from konung2.gamefile import unit_role
        return unit_role(unit_index, map_number)
    except (OSError, ValueError, IndexError):
        return 0


def _village_counter(map_number: int | None, role: int) -> list[tuple[int, int, dict]]:
    """Прилавок должности: свой список товара на каждую (VA 0x43346C)."""
    if map_number is None or role not in (2, 3, 4):
        return []
    try:
        from konung2.gamefile import item_class_of, item_instance, village
        from konung2.paths import game_file
        settlement = village(map_number)
        if not settlement:
            return []
        with open(game_file("GAME.0"), "rb") as stream:
            data = stream.read()
        classes = []
        for item in settlement.get("goods", {}).get(role, []):
            item_class = item_class_of(data, item)
            if item_class:
                classes.append((item_class.index, item, item_instance(data, item)))
        return classes
    except (OSError, ValueError, IndexError, KeyError):
        return []


def _cursors(root: Path) -> dict[str, Any]:
    """Курсоры в пак: девять картинок и правила выбора."""
    from konung2.cursors import COUNT, image, rules
    folder = root / "assets" / "cursors"
    folder.mkdir(parents=True, exist_ok=True)
    pictures = []
    for index in range(COUNT):
        picture = image(index)
        relative = Path("assets") / "cursors" / f"{index}.png"
        picture.save(str(root / relative))
        pictures.append({"path": relative.as_posix(),
                         "width": picture.width, "height": picture.height})
    return {**rules(), "images": pictures}


def _add_building_states(documents: list[dict[str, Any]],
                         settlement: dict[str, Any] | None,
                         assets: _AssetExporter) -> None:
    """Дать постройке картинки всех её состояний.

    Состояние — не значок, а ступень: движок рисует постройку картинкой
    ``спрайт вида + состояние`` (VA 0x4171CC), и каждому виду отведено семь
    подряд идущих ресурсов — стройка, готово, пожар, пепелище. В карте
    лежит ресурс той ступени, на которой постройка сейчас, поэтому соседние
    берутся отсчётом от него. Смещения кадров у всех семи одни и те же —
    они и в заголовке карты, и в самом ресурсе совпадают.

    НЕПОСТРОЕННЫЕ МЕСТА ТОЖЕ НУЖНЫ. Здесь стоял отбор ``if entry["built"]``, и
    пустая площадка оставалась без лестницы состояний и без ссылки на место
    деревни. Заложить на ней постройку было можно — действие разговора 40
    ставит срок, — а вырасти ей было нечем: стройку двигает объект карты, а он
    про своё место ничего не знал. Из-за этого казарму нельзя было построить
    ни на одной карте, а изначально она не построена нигде.

    ИСКАТЬ НАДО И СРЕДИ РЕКВИЗИТА. Номер объекта в записи поселения сквозной по
    всей карте: на Борье постройки занимают 0…8, реквизит 9…132, и площадка
    казармы — это реквизит 9, колодца — реквизит 123. Пока сюда передавали один
    список построек, такие места не находились вовсе.

    Сопоставление проверено на построенных: ``ресурс объекта`` минус
    ``спрайт вида + состояние`` даёт ровно 30 у всех семи мест Борья. Отсчёт
    лестницы идёт от собственного ресурса объекта, поэтому этот сдвиг сюда не
    входит.
    """
    from konung2.buildings import EMPTY_KIND, STATE_SPRITES
    # ПУСТОЕ МЕСТО В СЧЁТ НЕ ИДЁТ. У вида 0xFF номер объекта нулевой — это
    # «ничего не назначено», а не объект ноль. Пока такие места попадали в
    # словарь, пустое место 5 Борья затирало собой дом старосты, который
    # объектом ноль владеет по-настоящему.
    entries = {entry["object"]: entry
               for entry in (settlement or {}).get("buildings", [])
               if entry.get("kind") != EMPTY_KIND}
    for document in documents:
        entry = entries.get(document.get("record_slot"))
        if entry is None:
            continue
        base = document["resource_slot"] - int(entry["state"])
        ladder: dict[str, Any] = {}
        for state in range(STATE_SPRITES):
            visual = assets.object(base + state, document["palette"], 0)
            layers = (visual or {}).get("layers") or {}
            if not layers:
                continue
            ladder[str(state)] = {part: {
                "asset": layer["path"], "width": layer["width"],
                "height": layer["height"], "offset_x": layer["offset_x"],
                "offset_y": layer["offset_y"],
            } for part, layer in layers.items()}
        if ladder:
            document["village_slot"] = entry["slot"]
            document["village_state"] = entry["state"]
            document["states"] = ladder


#: Точки огня по слотам OBJECTS.RES — по разу на игру (konung2/objectanim.py).
_FIRE_POINTS: dict[str, dict[int, list[dict[str, int]]]] = {}


def _fire_points_of(game) -> dict[int, list[dict[str, int]]]:
    key = "legend" if game == "legend" else "canon"
    if key not in _FIRE_POINTS:
        from konung2 import objectanim
        try:
            _FIRE_POINTS[key] = objectanim.fire_points(key)
        except OSError:
            _FIRE_POINTS[key] = {}
    return _FIRE_POINTS[key]


def _serialize_entity(entity: Entity, assets: _AssetExporter) -> dict[str, Any]:
    """Сущность мира -> запись content pack.

    Геометрия, ключ глубины и правила света уже посчитаны доменной моделью;
    сборщик только выгружает картинки и подставляет пути. Если распакованный
    кадр разойдётся с заголовком ресурса, сборка падает — молча разъехавшийся
    якорь дороже, чем остановленная сборка.
    """
    visual = assets.object(entity.resource_slot, entity.palette, entity.state)
    layers = (visual or {}).get("layers") or {}
    frames: dict[str, Any] = {}
    for part, frame in entity.frames.items():
        layer = layers.get(part)
        if layer is None:
            continue
        if (int(layer["width"]), int(layer["height"])) != (frame.width, frame.height):
            raise ContentBuildError(
                f"{entity.id}: кадр {part} распакован как "
                f"{layer['width']}x{layer['height']}, заголовок обещал "
                f"{frame.width}x{frame.height}")
        frames[part] = {
            "asset": layer["path"],
            "width": frame.width,
            "height": frame.height,
            "offset_x": frame.offset_x,
            "offset_y": frame.offset_y,
        }
    bounds, origin = entity.bounds, entity.draw_origin
    document: dict[str, Any] = {
        "id": entity.id,
        "kind": entity.kind,
        "record_slot": entity.record_slot,
        "resource_slot": entity.resource_slot,
        "palette": entity.palette,
        "state": entity.state,
        # Огни на объекте: до восьми точек «анимация + смещение» из
        # заголовка OBJECTS.RES (konung2/objectanim.py). Кадры лежат в
        # shared.effects, клиент листает их от мировых часов.
        **({"fire": _fire_points_of(assets.game)[entity.resource_slot]}
           if entity.resource_slot in _fire_points_of(assets.game) else {}),
        "position": {"x": entity.position.x, "y": entity.position.y},
        "bounds": {
            "width": bounds.width,
            "height": bounds.height,
            "offset_x": bounds.offset_x,
            "offset_y": bounds.offset_y,
            "draw_x": origin.x,
            "draw_y": origin.y,
            "sort_height": bounds.sort_height,
            "sort_bias": bounds.sort_bias,
            "sort_y": entity.sort_key,
        },
        "frames": frames,
        # Бит 0x04 байта hdr+0xFE: кадр main блитится исходной палитрой
        # (VA 0x425B0C), то есть интерьер постройки не темнеет никогда.
        "lighting": {"main_static_palette": entity.lighting.main_static_palette},
        "render_debug": {
            "available_states": [frame["state"] for frame
                                 in assets.objects.simple_frames(entity.resource_slot)],
            "parts": [name for name, _ in assets.objects.simple_parts(entity.resource_slot)],
            "resolved": bool(frames),
        },
    }
    # Клетки выгружаем и у реквизита, если они у него есть: пустая площадка
    # под стройку — реквизит (у её состояния нет стен), но след в сетке за ней
    # закреплён, и без него достроенную казарму не открыть (VA 0x43F178).
    if getattr(entity, "cells", None) and (entity.cells.footprint
                                           or entity.cells.floor
                                           or entity.cells.routed):
        document["cells"] = {
            "footprint": [[cell.row, cell.col] for cell in entity.cells.footprint],
            "floor": [[cell.row, cell.col] for cell in entity.cells.floor],
            "routed": [[cell.row, cell.col] for cell in entity.cells.routed],
        }
    return document


def _export_map(number: int, project: Path, root: Path,
                assets: _AssetExporter, audio: dict[str, Any],
                daylight: str | None = None,
                hero: dict[str, Any] | None = None) -> ContentMap:
    source = _find_map_source(project, number)
    metadata = json.loads((source / "map.json").read_text(encoding="utf-8"))
    # ЧЬЕЙ ГРАФИКОЙ РИСУЕТСЯ ЭТА КАРТА. Гнёзда объектов, палитры и плитки
    # земли одного номера у двух игр значат разные картинки (см.
    # _AssetExporter), поэтому источник выбирается по `origin` карты.
    assets.select((metadata.get("origin") or {}).get("game"))
    kn2 = KN2Map.pack(str(source), number)
    # ИМЯ ЛОКАЦИИ — КАНОННОЕ, из таблицы имён exe, а не из проекта. В
    # project/maps/*/map.json имя можно переписать под свои опыты, и такое
    # имя утекало в игру: у карты 32 там стояла наша тестовая «Новая Весь»
    # вместо «Местность у лесной просеки», и она показывалась игроку при
    # случайной встрече. Имя из проекта остаётся запасным — для карт,
    # которых в таблице нет.
    name = str(_canon_map_name(number, project) or metadata.get("name")
               or f"Map {number}")

    # ОБЪЕКТ НЕ ДОЛЖЕН ПРОПАДАТЬ МОЛЧА. На неизвестном гнезде и сборщик, и
    # модель карты просто возвращают None: постройки нет, ошибки нет, следа
    # нет. На наших 52 картах не теряется ни одного объекта, значит потеря
    # это всегда неисправность. У донорских карт без ввоза гнёзд 510..587
    # теряют объекты 50 карт из 90 — вот их и надо поймать здесь, а не
    # разглядывать потом пустое место посреди деревни.
    wanted = {ObjectsRes.slot_of(record) for record in kn2.objects()
              if record.get("kind", 0xFFFF) not in (0xFFFF, 0xFFFFFFFF)}
    lost = missing_slots(assets.objects, wanted)
    if lost:
        raise ValueError(
            f"карта {number}: в каталоге объектов нет гнёзд {lost[:12]}"
            f"{'…' if len(lost) > 12 else ''} — "
            f"без них постройки пропали бы с карты незаметно")

    # Модель мира собирается один раз и дальше только сериализуется: правила
    # (что прячет крышу, что не темнеет, где проходимо) живут в konung2.world,
    # а не расползаются по сборщику и клиенту.
    # РАСКЛАДКА КЛЕТКИ У ДОНОРСКОЙ КАРТЫ СВОЯ: номер постройки шестибитный,
    # флаги следом. Переводить её в нашу нельзя — 58 построек Кирингхольма в
    # пять бит не влезают, — поэтому читаем его карту его же мерой.
    from konung2.world.model import CANON_CELLS, LEGEND_CELLS
    world = MapModel.from_kn2(kn2, number, assets.objects,
                              LEGEND_CELLS if assets.legend else CANON_CELLS)
    scenario = _export_scenario(source, world, root, hero, number, project)

    ground = []
    for tile in world.terrain:
        position = tile.position
        tile.asset = assets.ground(tile.lower_tile, tile.upper_tile, tile.light_mask)
        tile.glow = assets.light_glow(tile.lower_tile, tile.upper_tile, tile.light_mask)
        ground.append({
            "row": tile.cell.row,
            "col": tile.cell.col,
            "x": position.x,
            "y": position.y,
            "tiles": {"lower": tile.lower_tile, "upper": tile.upper_tile},
            "asset": tile.asset,
            # Локальный свет: разность «клетка с маской минус клетка без
            # маски», клиент складывает её с кадром (см. light_glow).
            "light": ({"mask": tile.light_mask, "glow": tile.glow}
                      if tile.lit else None),
        })

    underlay_tile = int.from_bytes(
        kn2.data[SEC_FLAG[0]:SEC_FLAG[0] + SEC_FLAG[1]], "little")
    underlay_mask = bytes(
        kn2.data[T_LIGHT.offset:T_LIGHT.offset + T_LIGHT.count * T_LIGHT.size])
    # Тип воды решает OR ВСЕХ 512 байтов, не первый байт: загрузчик карты
    # (VA 0x43DF48) складывает таблицу в один байт 0x84961C, и отрисовщик
    # (VA 0x428240) по его биту 0x80 выбирает стоячую волну (Lake, VA
    # 0x43F46E) или волну со сдвигом буфера (Stream, VA 0x43F4D9). Клетки
    # Lake-карт несут 0x80, Stream-карт — 0x40; проверка первого байта
    # ошибочно гнала 12 стоячих карт (болота, озёра, Борье) течением.
    underlay_or = 0
    for underlay_byte in underlay_mask:
        underlay_or |= underlay_byte
    underlay_scroll = not bool(underlay_or & 0x80)
    underlay_visual = (
        assets.underlay(underlay_tile, underlay_scroll) if underlay_tile else None
    )
    underlay_cells = [
        [row, col, underlay_mask[row * T_LIGHT.size + col]]
        for row in range(T_LIGHT.count)
        for col in range(T_LIGHT.size)
        if underlay_mask[row * T_LIGHT.size + col]
    ]

    overlays: list[dict[str, Any]] = []
    unresolved_overlays = 0
    for record in T_DYNAMIC.unpack(kn2.data)["records"]:
        resource_slot = int(record.get("id", 0xFFFF))
        if resource_slot == 0xFFFF:
            continue
        visual = assets.terrain_overlay(resource_slot)
        if visual is None:
            unresolved_overlays += 1
        overlays.append({
            "id": f"legacy:{number}:overlay:{record['slot']}",
            "record_slot": int(record["slot"]),
            "resource_slot": resource_slot,
            # VA 0x43E4E9 подменяет запись+4 палитрой самого GRAPH.RES
            # прежде, чем VA 0x42543D рисует кадр: сырое значение из .KN2
            # доверия не заслуживает.
            "palette": int(assets.graph.tile_palette(resource_slot) or 0),
            "position": {"x": int(record["pixel_x"]), "y": int(record["pixel_y"])},
            "frame": ({"asset": visual["path"], "width": visual["width"],
                       "height": visual["height"]} if visual else None),
        })

    # ОБСТАНОВКА ИНТЕРЬЕРА (docs/CONTAINERS_SPEC.md). Блок 0x3D384 карты:
    # тридцать объектов по шестнадцать гнёзд, гнездо 12 байт. Формат тот же,
    # что у раннего прохода оверлеев, и разбирает их движок одним кодом
    # (VA 0x43DF48:158-172), поэтому и картинка берётся тем же путём.
    #
    # Номер зоны — это НОМЕР ЗАПИСИ ОБЪЕКТА карты: VA 0x425AA8:29 считает его
    # как `(запись − 0x834768) / 0x24` и зовёт отрисовщик нутра. Рисуются
    # гнёзда между главным спрайтом постройки и её стенами.
    #
    # Палитра из файла не годится: загрузчик перезаписывает её палитрой
    # самого спрайта — ровно как у оверлеев.
    furniture: list[dict[str, Any]] = []
    unresolved_furniture = 0
    for (zone, nest), slot_data in interior_slots(kn2).items():
        visual = assets.terrain_overlay(slot_data["sprite"])
        if visual is None:
            unresolved_furniture += 1
        furniture.append({
            "id": f"legacy:{number}:furniture:{zone}:{nest}",
            "zone": zone,
            "nest": nest,
            "resource_slot": int(slot_data["sprite"]),
            "palette": int(assets.graph.tile_palette(slot_data["sprite"]) or 0),
            "position": {"x": int(slot_data["x"]), "y": int(slot_data["y"])},
            "frame": ({"asset": visual["path"], "width": visual["width"],
                       "height": visual["height"]} if visual else None),
        })
    furniture.sort(key=lambda row: (row["zone"], row["nest"]))

    buildings = [_serialize_entity(entity, assets) for entity in world.buildings]
    props = [_serialize_entity(entity, assets) for entity in world.props]
    # Наборы тварей теперь общие на весь пак и лежат в shared.json — здесь
    # их больше нет (см. _creature_sets).
    #
    # Лестницу состояний раздаём ПО ОБОИМ спискам: номер объекта в записи
    # поселения сквозной, и пустые площадки под стройку лежат среди реквизита.
    _add_building_states([*buildings, *props], scenario.get("village"), assets)
    # ПРАВКИ РЕДАКТОРА ПО РЕКВИЗИТУ — из того же scenario.json, что и
    # слои юнитов с кучами (сборка сценария его уже читала, но реквизит
    # собирается здесь, в _export_map, — читаем сами).
    _scenario_path = source / "scenario.json"
    if _scenario_path.is_file():
        _layers = json.loads(_scenario_path.read_text(encoding="utf-8"))
        props = _editor_props_apply(props,
                                    _layers.get("editor_props") or {},
                                    _layers.get("editor_props_add") or [])
    unresolved = sum(1 for item in (*buildings, *props)
                     if not item["render_debug"]["resolved"])

    map_id = f"legacy:{number}"
    relative = Path("maps") / str(number) / "map.json"
    document = {
        "schema_version": CONTENT_MAP_SCHEMA,
        "id": map_id,
        "name": name,
        "legacy": {
            "map_number": number,
            "packed_sha256": hashlib.sha256(bytes(kn2.data)).hexdigest(),
            "source": source.relative_to(project).as_posix(),
        },
        "coordinates": {
            # Преобразования клетка<->пиксель сняты с движка:
            # якорь юнита (VA 0x43B974): x = col*58 + (row нечёт ? 29 : 58),
            #                            y = row*16 + 16;
            # клетка по точке (VA 0x43B9B0): полоса берётся делением
            #   y на 16 и x на 58, а потом правится ромбической
            #   поправкой — клиент делает это в heroCellAt.
            # Рамка, за которую камера не выезжает (VA 0x43DF48 считает,
            # 0x4291B4 и 0x437CD0 применяют). У порта клампа не было вовсе.
            "camera": _camera_bounds(kn2),
            "navigation_grid": {
                "rows": GRID_H,
                "columns": GRID_W,
                "cell_width": CELL_W,
                "cell_height": CELL_H,
                "anchor_x_odd": 29,
                "anchor_x_even": CELL_W,
                "anchor_y": CELL_H,
            },
            "ground_grid": {
                "rows": GROUND_ROWS,
                "columns": GROUND_STRIDE // 2,
                "step_x": TILE_STEP_X,
                "step_y": TILE_STEP_Y,
                "odd_row_offset": TILE_ODD_SHIFT,
                "tile_width": TILE_WIDTH,
                "tile_height": TILE_HEIGHT,
            },
        },
        # Когда движок вообще включает локальный свет: ветка «ночь» ставит
        # [0x8495CC] = 1 при t >= 8100 (VA 0x429806), а карты с записью в
        # таблице 0x4617B0 светят всегда (VA 0x4295E4).
        "lighting": {
            "policy": "konung2_exe_0x424FFA_0x429806",
            "from_tick": world.lighting.from_tick,
            "always": world.lighting.always,
            "baked_levels": {"blue": NIGHT_LEVEL_BLUE,
                             "green": NIGHT_LEVEL_GREEN,
                             "red": NIGHT_LEVEL_RED},
            # ПОСТОЯННОЕ ОСВЕЩЕНИЕ КАРТЫ — запись таблицы 0x4617B0 ЦЕЛИКОМ.
            #
            # Расчёт света идёт по суточной кривой ТОЛЬКО когда запись нулевая
            # (VA 0x4295D8: `if ([0x8495A4] == 0)`), иначе уровень берётся из
            # неё же — `таблица[карта] & 0xFFFFFF` — и часы не спрашиваются.
            # Записи у семи карт: 1 и 2 — вечная глубокая ночь, 45..49 —
            # ровный свет подземелий.
            #
            # Раньше в пак уезжали только `always` (старший байт) и глобальная
            # константа `baked_levels`, одна на все карты. Из-за этого во
            # Дворце Повелителя днём было светло, а пещерам 45..49 доставались
            # уровни −70/−50/−50 вместо их собственных −1/−1/−1.
            "fixed": fixed_light(number),
        },
        "terrain": {
            # Проходимость по движку (VA 0x4414A7): клетка свободна, когда
            # младшие 12 бит слова нулевые. Стены и вода несут 0xFFF, клетки
            # внутри построек в этих битах пусты — поэтому в дом можно войти.
            "policy": "legacy_low12_nonzero_is_blocked",
            "ground": ground,
            "overlays": overlays,
            "furniture": furniture,
            "underlay": {
                "policy": "konung2_exe_0x428505_0x4288D4",
                "tile": underlay_tile or None,
                "visual": underlay_visual,
                "cell_size": 256,
                "cells": underlay_cells,
            },
            "blocked": [[cell.row, cell.col] for cell in world.terrain.blocked],
            # МЯГКАЯ ГЛУШЬ ДОНОРА — подмножество blocked. Его карты кодируют
            # непроходимость битом 0x1000 при пустом низе, и после перевода
            # в наш формат (donor.to_canon_cells) она неотличима от стены
            # 0xFFF. Различие каноничное: шаг туда запрещён у обоих движков,
            # а вот канонный отказ волны «цель — стена» ловит ТОЛЬКО низ
            # 0xFFF — потому оригинал доводит юнита до цели на такой клетке
            # (финиш волны не проверяется), и там стоит третья бочка
            # Кирингхольма. Канонные карты поля не несут.
            **({"blocked_soft": _donor_soft_cells(source, number)}
               if assets.legend else {}),
            # глухие клетки (бит 0x4000): по ним обрывается траектория
            # выстрела и считается попадание зажигательной стрелы
            "solid": [[cell.row, cell.col] for cell in world.terrain.solid],
            # Бит 22 клетки: юнит на ней блитится статичной палитрой
            # (VA 0x425E81), то есть в ауре света остаётся дневным.
            "daylit_cells": [[cell.row, cell.col] for cell in world.terrain.bright],
        },
        "buildings": buildings,
        "props": props,
        # кого встретим в пути по глобальной карте (VA 0x4360A8)
        "encounters": scenario.get("encounters") or {},
        **scenario,
        # Звук донорской карты — ЕГО набор и ЕГО номер карты: наборы двух игр
        # под общими номерами не совпали ни разу из 376.
        "audio": audio_assets.map_audio_block(
            number, audio,
            "legend" if assets.legend else None,
            (metadata.get("origin") or {}).get("map"),
            # Поселение или нет — это ветка выбора трека у донора: у него
            # деревня звучит своим набором, а прочая земля — общим.
            bool(scenario.get("village"))),
        "daylight": daylight,
        # У карты своё только место прихода героя: всё остальное — кадры,
        # слои снаряжения, правила — общее и лежит в shared.json.
        "hero": {"start": _hero_start(number)} if hero else None,
        "render_debug": {
            "ground_legend": ["row", "col", "lower_tile", "upper_tile", "light_mask"],
            "entity_sort": "draw_y_plus_max_main_walls_height_minus_bias_then_draw_x",
        },
        "statistics": {
            "ground_cells": len(ground),
            "lit_cells": len(world.terrain.lit_tiles),
            "underlay_cells": len(underlay_cells),
            "terrain_overlays": len(overlays),
            "unresolved_terrain_overlays": unresolved_overlays,
            "furniture": len(furniture),
            "unresolved_furniture": unresolved_furniture,
            "buildings": len(buildings),
            "props": len(props),
            "unresolved_entities": unresolved,
            "blocked_cells": len(world.terrain.blocked),
            "daylit_cells": len(world.terrain.bright),
        },
    }
    _write_json(root / relative, document)
    return ContentMap(map_id=map_id, legacy_number=number, name=name,
                      path=relative.as_posix())


#: Куда ведёт выход: −1 «на карту мира», −2 особый переход (VA 0x43DF48).
EXIT_TO_WORLD_MAP = -1


def _project_exits(source: Path, number: int) -> list[dict[str, Any]]:
    """Выходы, объявленные самой картой проекта.

    Поля те же, что у канонной записи (konung2/gamefile.py: map_exits), но
    проверяем их здесь: у канона они пришли из движка и заведомо целы, а
    эти написаны руками. Выход без прямоугольника или с чужим номером
    карты — это дверь, которая никуда не ведёт, и молчать о ней нельзя.
    """
    path = source / "map.json"
    if not path.is_file():
        return []
    declared = json.loads(path.read_text(encoding="utf-8")).get("exits") or []
    out = []
    for index, door in enumerate(declared):
        missing = [key for key in ("to_map", "row1", "row2", "col1", "col2")
                   if key not in door]
        if missing:
            raise ContentBuildError(
                f"карта {number}: у выхода {index} нет полей {missing}")
        entry = {"index": 1000 + index, "facing": int(door.get("facing", 0)),
                 "to_map": int(door["to_map"]),
                 "to_name": str(door.get("to_name", "")),
                 "entry_row": int(door.get("entry_row", 0)),
                 "entry_col": int(door.get("entry_col", 0))}
        rows = sorted((int(door["row1"]), int(door["row2"])))
        cols = sorted((int(door["col1"]), int(door["col2"])))
        entry.update(row1=rows[0], row2=rows[1], col1=cols[0], col2=cols[1])
        out.append(entry)
    return out


#: ОТКУДА У КАРТЫ ЖИТЕЛИ. Перенесённая карта помечена в своём map.json полем
#: `origin`: чья игра и какой номер там. Её жители лежат в GAME.<мир> ДОНОРА
#: и под ЕГО номером — читать их нашими смещениями и нашим номером значит не
#: найти никого, и деревня приезжает пустой.
def _map_source(source: Path, number: int | None):
    """Профиль игры и номер карты в ней: (профиль, номер)."""
    from konung2.profile import CANON, PROFILES
    path = source / "map.json"
    if path.is_file():
        origin = json.loads(path.read_text(encoding="utf-8")).get("origin")
        if origin and origin.get("game") in PROFILES:
            return PROFILES[origin["game"]], int(origin["map"])
    return CANON, number


def _donor_soft_cells(source: Path, number: int | None) -> list[list[int]]:
    """Мягкая глушь донорской карты — из ЕГО сырого .KN2 (см. terrain)."""
    from konung2 import donor
    game, native = _map_source(source, number)
    if game.name != donor.LEGEND_NAME:
        return []
    try:
        return [[row, col] for row, col in donor.soft_cells(native)]
    except OSError:
        return []


#: ДОВОДЫ ОБРАБОТЧИКОВ, НЕСУЩИЕ НОМЕР КАРТЫ. Номера обработчиков здесь УЖЕ
#: наши (перевод сделал разбор разговоров), а вот доводы — ещё той игры:
#: «мы на карте N» из донорского дерева называет ЕГО N, у нас это 150+N.
#: Ключ — наш номер обработчика, значение — какая часть довода карта.
MAP_ARGUMENT_HANDLERS = {
    0: "low",       # карта зачищена: младший байт — карта, старший — пропуск
    19: "all",      # мы на карте
    23: "all",      # жив отряд события (0 — текущая карта)
    63: "all",      # открыть локацию
    28: "high",     # есть поселение и оно спокойно: старший байт — карта
}

#: ДОВОД — НОМЕР КЛАССА ПРЕДМЕТА, И У ДВУХ ИГР ОН ЗНАЧИТ РАЗНОЕ. Классы
#: донора приезжают под своими номерами (PROJECT_ITEM_BASE и дальше), а в
#: его разговорах остаются его собственные. Без перевода Магнус вручал
#: Гильдис не ключ от родного дома, а нашу «Колдовскую приваду» — класс с
#: тем же номером в нашей таблице.
ITEM_ARGUMENT_HANDLERS = {
    17,     # есть ли у игрока предмет этого класса (VA 0x434F8C)
    35,     # дать игроку предмет класса (VA 0x432F1C)
    45,     # забрать у игрока предмет класса (VA 0x433D38)
    48,     # забрать у собеседника предмет группы 11 класса
    # НАДЕТО ЛИ УКРАШЕНИЕ ЭТОГО КЛАССА — донорский 128+21 (его VA
    # 0x4384B0). Его нет в каноне, а довод — класс: без перевода все 148
    # проверок Грани Махкама спрашивали про ЕГО класс 3 «Браслет
    # Владыка» НАШИМ номером 3 «Волшебный фиал с кровью Титанов» — и
    # были вечно ложны, аравийский сюжет Тиграта молчал.
    128 + 21,
}


def _translate_tree_arguments(tree: dict[str, Any],
                              numbering: dict[int, int],
                              items: dict[int, int] | None = None
                              ) -> dict[str, Any]:
    """Перевести номера карт в доводах дерева чужой игры в наши.

    Дерево к этому месту уже с нашими номерами ОБРАБОТЧИКОВ, но доводы в
    нём — родной игры. Без перевода «мы на карте 16» донорских Дубков
    спрашивало бы про наш «Вход в подземную тюрьму». Непереводимый номер
    (карты нет в реестре) помечается, а не подменяется нулём: пусть условие
    честно провалится и след останется в дереве.
    """
    def translate(command: dict[str, Any]) -> None:
        if command.get("kind") != "handler":
            return
        if "native_argument" in command or "foreign_map" in command:
            return                        # уже переведено: второй раз нельзя
        if command.get("handler") in ITEM_ARGUMENT_HANDLERS:
            his = int(command.get("argument", 0))
            ours = items.get(his) if items else None
            if his and ours is not None:
                command["native_argument"] = his
                command["argument"] = ours
            elif his:
                command["foreign_item"] = his
            return
        part = MAP_ARGUMENT_HANDLERS.get(command.get("handler"))
        if part is None:
            return
        value = int(command.get("argument", 0))
        native = value if part == "all" else (
            value & 0xFF if part == "low" else (value >> 8) & 0xFF)
        if not native:
            return                        # ноль значит «текущая», не карта
        ours = numbering.get(native)
        if ours is None:
            command["foreign_map"] = native
            return
        command["native_argument"] = value
        if part == "all":
            command["argument"] = ours
        elif part == "low":
            command["argument"] = (value & ~0xFF) | ours
        else:
            command["argument"] = (value & 0xFF) | (ours << 8)

    for node in tree.get("nodes") or []:
        for command in node.get("actions") or []:
            translate(command)
        for option in node.get("options") or []:
            for command in option.get("actions") or []:
                translate(command)
            for command in option.get("condition") or []:
                translate(command)
        for branch in node.get("branches") or []:
            for command in branch.get("condition") or []:
                translate(command)
    return tree


#: МИР ДЛЯ ЧУЖОЙ ИГРЫ, КОГДА У ГЕРОЯ ТАМ СВОЕГО НЕТ. Выбор замерен, а не
#: угадан: по 49 донорским картам жителей в мирах 773/751/764/761, из них с
#: разговором 225/225/235/224. То есть миры одной игры несут ОДНО И ТО ЖЕ
#: население — расходятся только сюжетные лица, и то на двух картах из 49.
#: Значит цена выбора почти нулевая; берём мир 1, он в обеих играх
#: Велиславнин — Лесная страна без завязки на чужой сюжет. Поменять решение
#: = поменять эту цифру.
NEUTRAL_WORLD = 1


#: КАКОЙ МИР ЧИТАТЬ ДЛЯ СЛОТА ВЫБОРА. Слот экрана «Новая игра» — НЕ номер
#: мира: девять слотов раскиданы по двум играм (donor.HERO_SLOTS), у нас
#: миров шесть, у донора четыре. Прежний код возвращал слот как есть для
#: канона и ноль для донора — и это была ровно та тихая подмена, из-за
#: которой Драгомир на своём же Военном лагере попадал в мир Иззарка: там
#: все тринадцать жителей немые (разговор 127), а сам Драгомир стоит
#: чужим NPC.
#: НЕЙТРАЛЬНЫЙ МИР — ОДИН НА ВСЕХ ДЕВЯТЕРЫХ. Пока сюжетные линии не
#: написаны, выбор героя обязан менять ТОЛЬКО точку старта. Значит все девять
#: слотов читают один мир своей игры, а из него вычищается всё сюжетное:
#:
#:   * житель, которого нет хотя бы в одном мире своей игры, — по построению
#:     это чья-то завязка (таких 27 у канона и 18 у донора);
#:   * любой из девяти играбельных героев. Первым правилом они не ловятся:
#:     Ратибор, Александр и Анастасия стоят у донора во ВСЕХ его четырёх
#:     мирах, то есть входят в его «общее» ядро.
#:
#: Ставится False — и каждый слот снова читает свой мир (`_world_of`).
STORY_FREE_WORLD = True

#: Мир, с которого снимается нейтральное состояние. Нулевой: он не пуст ни
#: на одной карте ни у канона, ни у донора — проверено перебором.
BASE_WORLD = 0

#: Карты, на которых у мира нет ни одного жителя. Заведено ради одной
#: находки: у донора мир Велиславны не держит на его карте 14 (наш 164,
#: Военный лагерь) НИ ОДНОГО юнита. Взяли бы этот мир общим не глядя — и
#: все шесть наших героев пришли бы в безлюдный лагерь. По остальным картам
#: обеих игр такого нет ни разу, но проверять надо, а не надеяться.
_POPULATED: dict[tuple[str, int, int], bool] = {}
_HERO_NAMES: frozenset[str] | None = None
_NEUTRAL_CORE: dict[tuple[str, int], frozenset[tuple] | None] = {}


def _unit_key(unit: dict[str, Any]) -> tuple:
    """Чем житель опознаётся между мирами: имя и клетка.

    Номер юнита не годится — он у каждого мира свой: те же должностные лица
    Борья лежат в мире 0 под 236…239, а в мире 1 под 227…230.

    Клетка лежит по-разному: у сырой записи `map_units` это поля `row`/`col`
    прямо в юните, а у собранного для пака жителя — вложенный `cell`. Первая
    редакция смотрела только во вложенный, получала (имя, None, None) и
    сравнивала миры ПО ОДНОМУ ИМЕНИ. Совпадало это не потому, что верно, а
    потому, что обе стороны врали одинаково.
    """
    row, col = unit.get("row"), unit.get("col")
    if row is None and col is None:
        cell = unit.get("cell") or {}
        row = getattr(cell, "row", None) if not isinstance(cell, dict) \
            else cell.get("row")
        col = getattr(cell, "col", None) if not isinstance(cell, dict) \
            else cell.get("col")
    name = unit.get("name")
    # БЕЗЫМЯННЫМ ИМЯ НЕ СУДЬЯ. «житель N» — не имя из данных, а наша
    # подпись по НОМЕРУ ЗАПИСИ, и номера у каждого мира свои. Гигантский
    # дракон ущелья (порода 88) стоит во всех четырёх GAME донора на одной
    # клетке, но звался «житель 813/822/810/801» — ключ плясал, нейтральное
    # ядро его выбрасывало, и страж гнезда не попадал в пак ВООБЩЕ.
    # Породы и тела вместе с клеткой хватает: подписи врут, данные нет.
    if isinstance(name, str) and name.startswith("житель "):
        name = ("nameless", unit.get("breed"), unit.get("body"))
    return (name, row, col)


def _hero_unit_names() -> frozenset[str]:
    """Имена девяти играбельных — из данных, а не списком в коде.

    Герой это первый спутник отряда своего мира: `party(0, мир)` отдаёт
    «Ратибор», «Велиславна», «Иззарк» и так далее — ровно те строки, под
    которыми они же стоят чужими NPC на других картах.

    Опознавать их по внешности НЕЛЬЗЯ, это проверено: пара «тело + палитра»
    героя встречается у 14 обычных жителей канона и 9 донора — Скоморох,
    Жрец Огня, Аринбьорн Деревянный зуб и прочие.
    """
    global _HERO_NAMES
    if _HERO_NAMES is None:
        from konung2 import donor
        from konung2.gamefile import party
        from konung2.profile import LEGEND
        names: set[str] = set()
        for owner, world in donor.HERO_SLOTS:
            if owner == "legend" and not donor.available():
                continue
            try:
                band = party(0, world, LEGEND if owner == "legend" else None)
            except (OSError, ValueError, IndexError, LookupError):
                continue
            members = band.get("members") or []
            if members and members[0].get("name"):
                names.add(members[0]["name"])
        _HERO_NAMES = frozenset(names)
    return _HERO_NAMES


def _neutral_core(game, native: int) -> frozenset[tuple] | None:
    """Жители, стоящие во ВСЕХ мирах своей игры на этой карте.

    Всё, чего хоть в одном мире нет, — сюжетное: расстановка заводит таких
    под конкретного героя. Возвращает None, если сравнивать не с чем.
    """
    from konung2.gamefile import map_units
    from konung2.profile import CANON
    key = (getattr(game, "name", "canon"), native)
    if key not in _NEUTRAL_CORE:
        worlds = range(6) if game is CANON or game is None else range(4)
        seen: list[set[tuple]] = []
        for world in worlds:
            try:
                units = map_units(native, world, profile=game)
            except (OSError, ValueError, IndexError, LookupError):
                continue
            # ОТРЯД ИГРОКА СЧИТАТЬ ЖИТЕЛЕМ НЕЛЬЗЯ. Без этого Драгомир на
            # своей карте 14 попадал в «общее ядро»: в мирах 0 и 3 он стоит
            # чужим NPC, а в мире 2 он сам игрок — и выходило, что он есть
            # везде, то есть нейтрален.
            units = [unit for unit in units
                     if not _in_player_party(unit.get("index"), world, game)]
            if units:
                seen.append({_unit_key(unit) for unit in units})
        _NEUTRAL_CORE[key] = (frozenset(set.intersection(*seen))
                              if len(seen) > 1 else None)
    return _NEUTRAL_CORE[key]


def _populated(game, world: int, native: int) -> bool:
    from konung2.gamefile import map_units
    key = (getattr(game, "name", "canon"), world, native)
    if key not in _POPULATED:
        try:
            _POPULATED[key] = bool(map_units(native, world, profile=game))
        except (OSError, ValueError, IndexError, LookupError):
            _POPULATED[key] = False
    return _POPULATED[key]


#: СВОЯ ЛИ ЭТО ИГРА ДЛЯ СЛОТА. Девять слотов раскиданы по двум играм, и от
#: этого зависит и мир, и состав жителей: дома герой видит своё, в гостях —
#: общее.
def _own_game(game, slot: int) -> bool:
    from konung2 import donor
    from konung2.profile import CANON
    slots = donor.HERO_SLOTS
    owner = (slots[slot][0] if 0 <= slot < len(slots) else "canon")
    return (game is CANON) == (owner == "canon")


def _world_of(game, slot: int, native: int | None = None) -> int:
    from konung2 import donor
    slots = donor.HERO_SLOTS
    owner, home = slots[slot] if 0 <= slot < len(slots) else ("canon", 0)
    # НА СВОИХ КАРТАХ — СВОЙ МИР, ВСЕГДА.
    #
    # Общий мир на всех девятерых брался нулевым, а нулевой у донора — мир
    # Иззарка. От этого Драгомир на СВОЁМ Военном лагере оказывался среди
    # чужой расстановки: в его мире лагерь это два отряда (116 на двенадцать
    # человек и 117 на одного), отряд игрока стоит прямо на карте, а нападает
    # только третий, 118; в нулевом же лагерь слит в один отряд из тринадцати
    # и своего места у героя нет вовсе. Оттого ссора с одним поднимала весь
    # лагерь, и «его» люди не признавали в нём хозяина.
    #
    # Это ровно тот симптом, что уже ловили однажды (см. комментарий к
    # STORY_FREE_WORLD): тогда лечили общим миром, а он его и вернул.
    if _own_game(game, slot):
        return home
    # ПОКА СЮЖЕТОВ НЕТ — НА ЧУЖИХ КАРТАХ МИР ОДИН НА ВСЕХ.
    if STORY_FREE_WORLD:
        return BASE_WORLD
    if native is not None and not _populated(game, NEUTRAL_WORLD, native):
        return 0
    return NEUTRAL_WORLD


#: Сколько ключей в каждом `*_by_world` — ровно столько, сколько слотов на
#: экране выбора. Стояла шестёрка, и миры 6-8 (Иззарк, Драгомир, Гильдис)
#: молча проваливались в мир 0 у всех четырёх читателей клиента.
def _hero_worlds() -> int:
    from konung2 import donor
    return len(donor.HERO_SLOTS)


#: ПЕРЕВОД НОМЕРОВ КАРТ ЧУЖОЙ ИГРЫ В НАШИ. Выход донора называет карту ЕГО
#: номером, и в паке такой номер значит совсем другое место: его 37 «Пещера
#: у Дубков» — это наш «Морской лагерь».
#:
#: Таблица не задаётся правилом «150 + номер», а СОБИРАЕТСЯ ИЗ САМОГО
#: ПРОЕКТА: чей номер какой, объявлено в `origin` каждой перенесённой карты.
#: Так у правила один владелец, и перенумеруй мы что-нибудь — перевод
#: поедет следом. Сверх этого есть двойники: карты, которые в обеих играх
#: одни и те же, и у них наш номер СВОЙ, а не 150 + донорский.
def _foreign_numbering(project: Path | None, game_name: str) -> dict[int, int]:
    """Номер карты в чужой игре -> её номер у нас."""
    from konung2 import donor
    out: dict[int, int] = {}
    if game_name == donor.LEGEND_NAME:
        out.update(donor.TWIN_MAPS)
    if project is None:
        return out
    for path in sorted((project / "maps").glob("*/map.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        origin = document.get("origin")
        if not origin or origin.get("game") != game_name:
            continue
        if "map_number" not in document:
            continue
        out[int(origin["map"])] = int(document["map_number"])
    return out


def _export_scenario(source: Path, world: MapModel, root: Path,
                     hero_records: dict[str, Any] | None = None,
                     number: int | None = None,
                     project: Path | None = None) -> dict[str, Any]:
    """Население, выходы и лут локации.

    Жители и выходы — НАСТОЯЩИЕ, из стартового мира GAME.0: юниты живут в
    отрядах, отряд называет карту, а выходы лежат отдельной таблицей и
    задают прямоугольник-триггер в клетках (konung2/gamefile.py). Лут на
    земле — наша расстановка из ``scenario.json``, потому что в .KN2 его
    нет, а классы предметов всё равно настоящие.
    """
    # Файл расстановки нужен только под НАШ лут: жители, выходы, поселение
    # и события лежат в стартовом мире и от него не зависят. Раньше без
    # файла карта уезжала в пак вообще без сценария — и с неё нельзя было
    # даже уйти обратно.
    path = source / "scenario.json"
    document = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    catalogue = read_items()
    # Имена в таблице повторяются: «Двуручный меч» это и класс 108 (сила 120,
    # требует Силу 5), и класс 217 (сила 632, требует 83). По имени берётся
    # ПЕРВЫЙ такой класс, а если расстановке нужен конкретный — она называет
    # его номером.
    by_name: dict[str, ItemClass] = {}
    for item in catalogue:
        by_name.setdefault(item.name.lower(), item)
    by_index = {item.index: item for item in catalogue}

    def resolve(name: str | int) -> ItemClass:
        if isinstance(name, int):
            item = by_index.get(name)
        else:
            text = str(name)
            if text.startswith(ITEM_REF_PREFIX):
                try:
                    item = by_index.get(int(text[len(ITEM_REF_PREFIX):]))
                except ValueError:
                    item = None
            elif text.startswith(INSTANCE_REF_PREFIX):
                try:
                    item = by_index.get(int(text.split(":", 2)[1]))
                except (ValueError, IndexError):
                    item = None
            else:
                item = by_name.get(text.lower())
        if item is None:
            raise ContentBuildError(f"нет такого предмета в konung2.exe: {name}")
        return item

    # Картинка предмета — его собственная иконка из INTERF.RES (номер лежит
    # в классе полем +0x16). Ею движок рисует предмет и в окне снаряжения, и
    # это же изображение предмета, а не кадр «оружие в руке».
    interf = InterfRes.from_game()
    palettes = read_palettes()
    icons_dir = Path("assets") / "icons"
    (root / icons_dir).mkdir(parents=True, exist_ok=True)

    def icon_of(item: ItemClass) -> dict[str, Any] | None:
        if not item.icon:
            return None
        # ХВОСТОВЫЕ КЛАССЫ (211+) — донорские: их иконки лежат в ЕГО
        # INTERF.RES под ЕГО номерами (Ключ Воды 261 у канона — портрет!).
        if item.index >= DONOR_ITEM_BASE:
            return legend_icon_of(item)
        relative = icons_dir / f"{item.icon}.png"
        target = root / relative
        size = interf.frame_size(item.icon)
        if size is None:
            return None
        if not target.is_file():
            sprite = interf.sprite(item.icon, palettes)
            if sprite is None:
                return None
            sprite.save(str(target))
        return {"path": relative.as_posix(), "width": size[0], "height": size[1],
                "index": item.icon}

    def legend_icon_of(item: ItemClass) -> dict[str, Any] | None:
        entry = legend_sprite(item.icon)
        if entry is None:
            return None
        return {**entry, "index": item.icon}

    def interface_sprite(index: int | None) -> dict[str, Any] | None:
        if index is None:
            return None
        size = interf.frame_size(index)
        if size is None:
            return None
        relative = icons_dir / f"ui_{index}.png"
        target = root / relative
        if not target.is_file():
            sprite = interf.sprite(index, palettes)
            if sprite is None:
                return None
            sprite.save(str(target))
        return {"path": relative.as_posix(), "width": size[0], "height": size[1]}

    # КРАСКА ЯЧЕЙКИ ПОД ВЕЩЬ — перенос разбора мешка и пояса (VA 0x42BFE8 и
    # 0x43096C): движок рисует спрайт-ПОДЛОЖКУ ячейки перекрашенной палитрой
    # (0x42FF20 выбирает ряды, 0x441DF9 гонит каналы), а сам значок кладёт
    # поверх родными цветами. Красится вся ячейка, не кайма.
    #
    # Краска табличная: видеоинициализация 0x43C228 строит ряды с шагом
    # 0.01 (float 0x4593A8) — ряд N тянет канал на N сотых остатка до
    # максимума: new = v + round(N/100 * (max - v)). «Нельзя надеть» — ряд
    # 0x18 красного канала (FUN_0044293F(0x18,0,0)), «с чарами» — ряд 0x0C
    # зелёного (FUN_0044293F(0,0x0C,0)); каналы экрана 5-6-5.
    def tinted_cell(tag: str, red_row: int, green_row: int) -> dict[str, Any] | None:
        size = interf.frame_size(CELL_SPRITE)
        if size is None:
            return None
        relative = icons_dir / f"ui_{CELL_SPRITE}_{tag}.png"
        target = root / relative
        if not target.is_file():
            sprite = interf.sprite(CELL_SPRITE, palettes)
            if sprite is None:
                return None
            image = sprite.to_image()
            painted = []
            for red, green, blue, alpha in image.getdata():
                r5, g6 = red >> 3, green >> 2
                r5 += round(red_row * 0.01 * (31 - r5))
                g6 += round(green_row * 0.01 * (63 - g6))
                painted.append(((r5 << 3) | (r5 >> 2),
                                (g6 << 2) | (g6 >> 4), blue, alpha))
            image.putdata(painted)
            image.save(str(target))
        return {"path": relative.as_posix(), "width": size[0], "height": size[1]}

    #: ПОРТРЕТЫ ДОНОРА — ИЗ ЕГО INTERF.RES. Номер спрайта тот же («лицо +
    #: 261»), но лица под этими номерами у игр РАЗНЫЕ: за Иззарка (лицо 0)
    #: панель показывала нашего Ратибора, за Гильдис (лицо 3) — Хельгу.
    #: Ключ портрета несёт игру, как и ключ тела.
    _legend_interf: list[Any] = []

    def legend_sprite(index: int | None) -> dict[str, Any] | None:
        if index is None:
            return None
        if not _legend_interf:
            from konung2 import donor as _donor
            try:
                _legend_interf.append(
                    InterfRes(Path(_donor.donor_file("interf.res")).read_bytes())
                    if _donor.available() else None)
                _legend_interf.append(
                    read_palettes(_donor.graph_palette_block())
                    if _donor.available() else None)
            except OSError:
                _legend_interf.extend([None, None])
        source, block = _legend_interf[0], _legend_interf[1]
        if source is None:
            return None
        size = source.frame_size(index)
        if size is None:
            return None
        relative = icons_dir / f"legend_ui_{index}.png"
        target = root / relative
        if not target.is_file():
            sprite = source.sprite(index, block)
            if sprite is None:
                return None
            sprite.save(str(target))
        return {"path": relative.as_posix(), "width": size[0], "height": size[1]}

    def glow_sprite() -> dict[str, Any] | None:
        """Дымка свечения Факела и Чистой слезы (В11): маска 64x43 из
        LIGHTS.RES, белый цвет, альфа — яркость с сатурацией 5-битного
        света (значения выше 31 упираются в потолок, как в каналах)."""
        from konung2.graph import (GLOW_HEIGHT, GLOW_OFFSET, GLOW_WIDTH,
                                   glow_mask)
        from PIL import Image
        relative = icons_dir / "lights_glow.png"
        target = root / relative
        if not target.is_file():
            mask = glow_mask()
            image = Image.new("RGBA", (GLOW_WIDTH, GLOW_HEIGHT))
            image.putdata([(255, 255, 255,
                            min(255, round(min(31, value) * 255 / 31)))
                           for value in mask])
            image.save(str(target))
        return {"path": relative.as_posix(),
                "width": GLOW_WIDTH, "height": GLOW_HEIGHT,
                "offset": list(GLOW_OFFSET)}

    def interface() -> dict[str, Any]:
        from konung2 import donor           # его база портретов — 274, не 261
        window = interface_sprite(EQUIPMENT_WINDOW)
        if window is not None:
            window["slots"] = slot_rects()
        return {
            # Экран игры целиком: рамка 1024x768, левая панель 140, окно
            # мира 884x709 — отсюда и размеры всех окон интерфейса. Ниже
            # 709-й строки рамка сплошная: это её нижняя полоса.
            "screen": {"width": SCREEN[0], "height": SCREEN[1],
                       "panel_width": PANEL_WIDTH, "view_width": VIEW_WIDTH,
                       "view_height": VIEW_HEIGHT, "frame_bottom": FRAME_BOTTOM},
            "frame": interface_sprite(FRAME_SPRITE),
            # пояс: ряд ячеек мешка внизу окна мира и стрелки прокрутки
            "belt": {**BELT, "arrows": {name: interface_sprite(sprite)
                                        for name, sprite in BELT_ARROWS.items()}},
            "equipment_window": window,
            # раскладка левой панели — таблица 0x460EB4: девять портретов и
            # семь кнопок, никаких гнёзд под предметы там нет
            "panel": panel_rects(),
            # дымка свечения при флаге 0x849610 (Факел, Чистая слеза):
            # ПОДСВЕТКА КУЧ — оба прохода отрисовки лута (0x424514:146 и
            # 0x424FD8:220) кладут её под каждую кучу и рисуют спрайт кучи
            # базовой палитрой, мимо суточного пересчёта
            "glow": glow_sprite(),
            # Круг под выбранным юнитом (VA 0x425DB4). Спрайт выбирается
            # по здоровью, поэтому кругов три: красный, жёлтый и зелёный.
            # Это НЕ тень — круг появляется только под выбранными.
            #
            # Кольцо лежит в холсте по тому же якорю ног (127, 144), что и
            # тело юнита: у зелёного круга центр кольца приходится ровно на
            # (128, 145). Поэтому смещение кадра — минус якорь, и клиент
            # рисует круг там же, где начинает тело.
            "selection_circle": {
                name: {**(interface_sprite(index) or {}),
                       "offset_x": -HERO_ANCHOR_X, "offset_y": -HERO_ANCHOR_Y}
                for name, index in SELECTION_SPRITES.items()
            },
            "buttons": [{**(interface_sprite(sprite) or {}), **dict(action)}
                        for sprite, action in zip(BUTTON_SPRITES, BUTTON_ACTIONS)],
            # вторая кнопка меняет лицо по стойке, первая — по оружию
            "stance_faces": {state: interface_sprite(sprite)
                             for state, sprite in STANCE_SPRITES.items()},
            "weapon_faces": {name: interface_sprite(sprite)
                             for name, sprite in WEAPON_FACES.items()},
            "weapon_face_families": dict(WEAPON_FACE_FAMILIES),
            "cell": interface_sprite(CELL_SPRITE),
            # ячейка под вещью, которую не надеть, и под вещью с чарами:
            # краска подложки, как красит движок (см. tinted_cell)
            "cell_unusable": tinted_cell("unusable", 0x18, 0),
            "cell_special": tinted_cell("special", 0, 0x0C),
            # карта мира — спрайт 4 во весь проём (VA 0x4277F4 рисует её
            # затемнённой на (-20,-20,-20) и уже поверх ставит значки)
            "map": interface_sprite(MAP_SPRITE),
            # Свой отряд на глобальной карте — щит с руной (спрайт 179),
            # а рогатый шлем над костями (235) это ЧУЖОЙ отряд: движок
            # рисует их разными спрайтами и в разных местах (VA 0x4277F4).
            "world_player": interface_sprite(PLAYER_SPRITE),
            "world_party": interface_sprite(PARTY_SPRITE),
            # Значки локаций: свой спрайт и свой сдвиг внутри клетки
            # (таблица 0x4615CC по шесть байт на локацию).
            # Значки канона плюс значки локаций проекта: реестр лежит в
            # project/locations.json, а решает, что с ним делать,
            # knyaz2/content/locations.py — здесь только раскрываем спрайт
            # в путь к картинке.
            # Номер спрайта значка сам по себе ничего не значит: у локаций
            # донора он взят из ЕГО записи (+0x08) и указывает в ЕГО лист.
            # В канонном листе с 261 начинаются портреты, поэтому донорский
            # 265 рисовал на карте мира лицо. Банк несёт поле `game`.
            "world_markers": {
                location: {**marker,
                           **((legend_sprite(marker["sprite"])
                               if marker.get(MARKER_GAME) == LEGEND_MARKER
                               else interface_sprite(marker["sprite"])) or {})}
                for location, marker in location_markers(
                    {str(number): marker
                     for number, marker in world_markers().items()},
                    location_registry(project) if project else []).items()
            },
            # куча из нескольких предметов лежит мешочком (VA 0x43BBC4)
            "ground_pile": interface_sprite(GROUND_PILE_SPRITE),
            # летящие стрелы: по два кадра на каждое из восьми направлений
            # (спрайты INTERF.RES 184…199, VA 0x424454)
            "projectiles": [[interface_sprite(sprite) for sprite in pair]
                            for pair in accuracy_rules()["projectiles"]["sprites"]],
            # курсоры: девять картинок из GRAPH.RES, остриё в левом
            # верхнем углу (VA 0x43C228 читает, 0x428B88 выбирает)
            "cursors": _cursors(root),
            # экран персонажа: числа и подписи по таблицам 0x4612E4 и 0x46140C
            "character": character_screen(),
            # ПРОЗВИЩЕ ИГРОКА (VA 0x42FDC0): подсказка о своём герое
            # начинается не с имени, а с прозвища по двум сильнейшим
            # характеристикам. Сто строк таблицы 0x462B4C плюс два числа
            # правила: какие пять характеристик участвуют (Обучаемость нет)
            # и на сколько делится значение второй, выбирая ступень.
            "epithets": {
                "policy": "konung2_exe_0x42FDC0",
                "characteristics": list(EPITHET_CHARACTERISTICS),
                "step": EPITHET_STEP,
                "names": epithets(),
            },
            # обработчики команд разговора: что уже разобрано, а что нет
            "dialog_handlers": [
                {"index": row["index"], "name": row["name"]}
                for row in _dialog_handlers() if row["name"]
            ],
            # портрет героя это лицо 0 (VA 0x430631: лицо + 261)
            "portrait": interface_sprite(PORTRAIT_BASE),
            "portrait_base": PORTRAIT_BASE,
            # портреты всех лиц, которые встречаются в отряде и на карте:
            # номер спрайта — лицо юнита плюс 261 (VA 0x430631)
            "portraits": {
                **{str(face): interface_sprite(PORTRAIT_BASE + face)
                   for face in sorted(_faces_in_use(
                       maps=[number] if number else [], project=project))},
                # ЛИЦА ДОНОРА — ПОД СВОИМ КЛЮЧОМ И СО СВОЕГО НОМЕРА. Прежняя
                # запись брала канонную базу 261, а у донора под ней лежит
                # ИКОНКА КЛЮЧА 68x68 — её и показывала панель за Иззарка.
                **{f"legend:{face}": legend_sprite(donor.PORTRAIT_BASE + face)
                   for face in sorted(_legend_faces_in_use(
                       maps=[number] if number else [], project=project))},
            },
            "health_bar": dict(HEALTH_BAR),
        }

    def describe(item: ItemClass) -> dict[str, Any]:
        ground = icon_of(item)
        return {
            "index": item.index, "name": item.name, "slot": item.slot,
            "layer": item.layer, "palette": item.palette,
            # вес в граммах (+0x14), цена в монетах (+0x12), прочность
            # (+0x08) и требование «характеристика: сколько» (+0x0C и +0x0E)
            "power": item.power, "weight": item.weight,
            "durability": item.durability,
            "requires": REQUIREMENT_STATS.get(item.requires),
            "requirement": item.requirement,
            # вид записи — из самих вещей мира: в таблице классов его нет
            "range_cells": item.range_cells,
            # Вид записи берётся из вещей мира; у квестовых, которых игра
            # ещё не создала, его там нет — но он известен из кода: разбор
            # применения проверяет группу 11 (VA 0x436C48).
            "kind": (QUEST_ITEM_GROUP if item.index in QUEST_ITEM_CLASSES
                     else POTION_ITEM_GROUP if item.index in POTION_ITEM_CLASSES
                     else _class_kinds().get(item.index, item.kind_slot)),
            # стрелы и болты: их слот отдельный (unit+0x50)
            "ammo": item.ammo,
            # тем же числом предмет и лежит на земле, и смотрит с кнопки
            # оружия: 166 клинок, 154 топор, 163 мешочек (VA 0x43BBC4);
            # у хвостовых (донорских) классов номер целит в ЕГО лист
            "ground_sprite": item.ground,
            "ground": (legend_sprite(item.ground)
                       if item.index >= DONOR_ITEM_BASE
                       else interface_sprite(item.ground)),
            "price": item.price, "icon": ground,
            "attack_pose": item.attack_pose,
            # то же оружие «в покое» — соседний слой сверху (меч 1 -> 2,
            # лук 19 -> 20): в мирной стойке кадры несут только чётные
            "rest_layer": item.rest_layer,
        }

    def place(entry: dict[str, Any]) -> dict[str, Any]:
        cell = Cell(int(entry["row"]), int(entry["col"]))
        if not world.terrain.passable(cell):
            raise ContentBuildError(f"клетка вне карты или занята стеной: {entry}")
        anchor = cell.anchor()
        return {"cell": {"row": cell.row, "col": cell.col},
                "position": {"x": anchor.x, "y": anchor.y}}

    used: dict[str, ItemClass] = {}

    def remember(item: ItemClass) -> str:
        ref = _item_ref(item)
        used[ref] = item
        return ref

    def scenario_item(item: ItemClass, identity: str) -> str:
        """Новая запись, которую задаёт сценарий, а не стартовый GAME.0."""
        remember(item)
        return _instance_ref(item, f"scenario:{number if number is not None else 'custom'}:{identity}")

    # В оригинале каталог классов глобален: вещь, поднятая на одной карте,
    # не теряет механику после перехода на другую. Пока описания лежат в
    # документе карты, каждая карта должна нести весь компактный каталог.
    for item in catalogue:
        remember(item)
    # КВЕСТОВЫЕ ВЕЩИ, КОТОРЫХ В МИРЕ ЕЩЁ НЕТ. Вид записи (группу) сборщик
    # берёт из самих вещей мира, поэтому классы, которые игра СОЗДАЁТ по
    # ходу, остаются без вида и в пак не попадают вовсе. А без них рвётся
    # ветка: уголёк некуда превращать («Донесение Повелителю о капище»),
    # а карты островов, открывающие локации, недостижимы. Их группа
    # известна из кода: разбор применения начинается с проверки группы 11
    # (VA 0x436C48), и дальше действие выбирает класс.
    for index in QUEST_ITEM_CLASSES:
        try:
            item = resolve(index)
        except ContentBuildError:
            continue
        remember(item)

    # Порошки навыков, характеристик и опыта — те же «создаваемые игрой»
    # классы (ветки применения VA 0x436C48): без описаний их некому съесть.
    # Точильный камень (класс 51) и магические камни (52…56) в списке по
    # той же причине: принесённые с другой карты, они должны работать и
    # здесь (гнездо смешивания, VA 0x436C48 случаи «3»…«8»).
    from konung2.craft import (FAILED_MIX_CLASS, POWDER_CHARACTERISTICS,
                               POWDER_SKILLS, POWDER_XP_CLASS, STONE_GROUPS,
                               WHETSTONE_CLASS)
    for index in [*POWDER_SKILLS, *POWDER_CHARACTERISTICS, POWDER_XP_CLASS,
                  WHETSTONE_CLASS, *STONE_GROUPS, FAILED_MIX_CLASS]:
        try:
            item = resolve(index)
        except ContentBuildError:
            continue
        remember(item)

    # ХВОСТ ДОНОРА (211+): его собственные сюжетные классы — Браслет
    # Владыка, три Ключа, Книга Мудрых, Ларец Живой Воды, Амулет и Доспех
    # Дракона… Деревья разговоров уже зовут их ПЕРЕВЕДЁННЫМИ номерами
    # (donor.item_class_map), и без записей класса «дать»/«есть»/«забрать»
    # молчат, а Ключи Воды/Луны/Огня не открывают своих дверей. Вид записи
    # снят с ЕГО миров; иконки и вид на земле — из ЕГО INTERF (см.
    # icon_of/describe: ветка хвостовых классов).
    from konung2 import donor as _donor_tail
    if _donor_tail.available():
        for item, kind in _donor_tail.tail_classes():
            remember(item)
            _class_kinds().setdefault(
                item.index, kind if kind is not None else QUEST_ITEM_GROUP)
        # ОБЩИЕ классы без канонного вида (Финики, Нож, Пятак, Сын Луны,
        # Грамота на корабль…) получают вид из ЕГО миров — иначе их
        # применение спотыкается о гейт группы 11 (donor.shared_class_kinds).
        for cls, kind in _donor_tail.shared_class_kinds().items():
            _class_kinds().setdefault(cls, kind)

    # Снаряжение героя из GAME.0 — такие же предметы, как лут: без их
    # описания у надетого доспеха не будет ни брони, ни веса, ни иконки.
    template = _hero_template()
    for name in (template or {}).get("equipment", {}).values():
        if not name:
            continue
        item = resolve(name)
        remember(item)
    # Собственный мешок и снаряжение каждого члена стартового отряда тоже
    # путешествуют между картами. Их классы обязаны быть описаны в паке.
    for member in ((template or {}).get("party") or {}).get("members", []):
        carried = [*(member.get("equipment") or {}).values(),
                   *(member.get("second") or {}).values(),
                   *(member.get("bag") or [])]
        for name in carried:
            if not name:
                continue
            remember(resolve(name))

    # Снадобья, которые можно сварить, тоже должны быть в паке: без них
    # рецепт варится «в никуда» (konung2/craft.py).
    try:
        from konung2.craft import recipes as _recipes
        for row in _recipes():
            # переменная нарочно не «number»: так зовётся номер карты
            for potion in (row["target"], row["poured"], row["result"], row["left"]):
                brewed = by_index.get(potion) if potion is not None else None
                if brewed is not None:
                    remember(brewed)
    except (OSError, ValueError, IndexError):
        pass

    loot = []
    for entry in document.get("loot", []):
        item = resolve(entry["item"])
        ref = scenario_item(item, f"loot:{len(loot)}")
        loot.append({"id": f"loot_{len(loot)}", "item": ref, **place(entry)})

    # Куча, положенная под сюжет ОДНОГО героя. Экземпляр вещи именуется со
    # слотом, иначе две сюжетные кучи разных героев поделят одну запись.
    def scenario_pile(slot: str, at: int, entry: dict[str, Any]) -> dict[str, Any]:
        item = resolve(entry["item"])
        ref = scenario_item(item, f"loot:{slot}:{at}")
        return {"id": f"loot_{slot}_{at}", "item": ref, **place(entry)}

    # НАСТОЯЩИЕ КУЧИ МИРА — ягоды, грибы, кошели, связки стрел. Они лежат
    # своей таблицей в GAME.x (1000 записей по 101 байту), и загрузчик
    # карты отбирает те, у кого совпал номер карты (VA 0x43DF48). Без них
    # локация пуста: раньше в пак ехали только наши четыре предмета из
    # scenario.json.
    # КУЧИ ЗАВИСЯТ ОТ МИРА — ровно как жители. Клетки у них общие, а
    # содержимое своё: на карте 19 в мире Ратибора лежат 1500 монет и Медное
    # зеркало колдуна, а в мире Велиславны на том же месте 700 монет и
    # Эликсир Мудрости. Пока здесь стоял мир 0, за Велиславну в родном
    # Чёрном Бору попадался чужой, куда более богатый лут.
    def piles_of(game_world):
        out = []
        if number is None:
            return out
        try:
            from konung2.gamefile import ground_items
            # Тайники донорской карты — в ЕГО GAME и под ЕГО номером: по
            # нашему номеру в каноне их просто нет, и сундук Кирингхольма
            # (25 монет в постройке 39) не приезжал вовсе.
            game, native = _map_source(source, number)
            for pile in ground_items(native, _world_of(game, game_world, native),
                                     profile=game):
                names = []
                details = []
                pile_details = pile.get("details") or []
                pile_items = pile.get("classes") or pile["items"]
                pile_records = pile.get("item_records") or []
                for at, name in enumerate(pile_items):
                    try:
                        found = resolve(name)
                    except (ContentBuildError, KeyError):
                        continue
                    remember(found)
                    record = pile_records[at] if at < len(pile_records) else None
                    names.append(_game_item_ref(found, record))
                    details.append(pile_details[at]
                                   if at < len(pile_details) else {})
                # РАЗГОВОР ПЕЧЁТСЯ НАПОЛЬНОЙ КУЧЕ — И «ЛОДКАМ». Гнездо
                # 0xFF при заданной зоне — донорская связка «разговор
                # всего ОБЪЕКТА»: его загрузчик (0x4417E0:403) пишет номер
                # такой кучи в запись объекта зоны, и щелчок по лодке
                # открывает разговор перевозчика. Таких куч 26 на 17
                # картах (диалоги 256…284 — весь его транспорт), раньше
                # они молча отсеивались. У нас связь через ОБЪЕКТ не
                # ведётся — куча печётся напольной разговорной на клетке
                # самого объекта (все 26 клеток проходимы), и щелчок по
                # лодке попадает в её клетку тем же жестом.
                talkative = "dialog" in pile and (
                    pile["on_floor"] or pile["slot"] == 0xFF)
                if not names and not pile["money"] and not talkative:
                    continue
                cell = Cell(pile["row"], pile["col"])
                # ПРОХОДИМОСТЬ КУЧУ НЕ ОТСЕИВАЕТ — движок такой проверки не
                # делает вовсе: загрузчик 0x43DF48 ставит бит «здесь куча»
                # любой клетке, волна доводит юнита до цели и на мягкой
                # глуши (третья бочка Кирингхольма), а на глухой куча просто
                # лежит недостижимой. Прежний отсев молча ТЕРЯЛ лут: на
                # карте 6 в (46,18) исчезали Самострел боевой и три болта —
                # клетка проходима в сетке-источнике, глушь на неё навесил
                # объект. Теперь такие кучи едут в пак, а сборка их только
                # пересчитывает вслух.
                if (pile["on_floor"] and not talkative
                        and not world.terrain.passable(cell)):
                    print(f"    куча на глухой клетке: карта {number} "
                          f"{cell.row}:{cell.col} классы {pile['classes']}")
                anchor = cell.anchor()
                # РАЗГОВОРНАЯ КУЧА: приказ «обыскать» на её клетке открывает
                # диалог без собеседника (0x411BC6: байт +0x07 < 0xFE ->
                # разговор 0x100 + байт). Дерево печём как юнитам — из СВОЕЙ
                # игры, номер уезжает в проектную нумерацию внутри tree().
                talk = {}
                if talkative:
                    try:
                        from konung2.quests import Dialogs
                        tree = Dialogs.from_game(game).tree(pile["dialog"])
                        talk = {"dialog_number": tree["number"],
                                "dialog_tree": tree}
                    except (OSError, ValueError, IndexError, struct.error):
                        talk = {}
                out.append({
                    "id": f"pile_{pile['index']}",
                    "item": names[0] if names else None,
                    "items": names,
                    **talk,
                    # экземплярные крепость/чары/отрава вещей кучи (В10)
                    "details": details,
                    "money": pile["money"],
                    # СПРЯТАННАЯ КУЧА. Знак поля +0x0F записи (GAME.N,
                    # таблица 0x2C800) — это не долг, а признак «лежит под
                    # землёй»: такую не видно и не поднять, пока её не
                    # раскроет Медное зеркало колдуна или не откопает Лопата
                    # (VA 0x4115AC, проверка FUN_00434F8C(0x20)).
                    # На игру их девяносто пять на тридцати двух картах.
                    # Раньше знак терялся, и все тайники лежали на виду.
                    "buried": pile["buried"],
                    # ГДЕ КУЧА ЛЕЖИТ. Байт +0x09 записи: 0xFF — на полу,
                    # иначе номер ЗОНЫ обстановки, а +0x0A — номер гнезда в
                    # ней. Загрузчик карты по этой паре вписывает номер кучи
                    # в само гнездо (VA 0x43DF48:344-352), и через него
                    # сундук и открывается. Подробности —
                    # docs/CONTAINERS_SPEC.md.
                    # «лодочная» разговорная (гнездо 0xFF) едет НАПОЛЬНОЙ:
                    # зона у неё — номер объекта, а не контейнерное гнездо
                    **({} if pile["on_floor"] or pile["slot"] == 0xFF
                       else {"zone": int(pile["place"]),
                             "nest": int(pile["slot"])}),
                    "cell": {"row": cell.row, "col": cell.col},
                    "position": {"x": anchor.x, "y": anchor.y},
                })
        except (OSError, ValueError, IndexError, KeyError):
            pass
        return out

    # Кучи проекта — теми же тремя слоями, что и жители: общая часть всем,
    # `loot_by_world` только своему слоту (место под сюжетную вещь).
    own_loot = {str(slot): [scenario_pile(str(slot), at, entry)
                            for at, entry in enumerate(entries or [])]
                for slot, entries
                in (document.get("loot_by_world") or {}).items()}
    loot_by_world = {str(game_world): [*loot, *piles_of(game_world),
                                       *(own_loot.get(str(game_world)) or [])]
                     for game_world in range(_hero_worlds())}
    loot = loot_by_world["0"]

    # ПРАВКИ РЕДАКТОРА ПО КУЧАМ — тем же слоем, что editor_units: патчи по
    # id из project/maps/<карта>/map.json (`editor_loot`), плюс целиком
    # новые кучи (`editor_loot_add`). Применяются каждому миру.
    editor_loot = document.get("editor_loot") or {}
    editor_loot_add = document.get("editor_loot_add") or []
    if editor_loot or editor_loot_add:
        for game_world in list(loot_by_world):
            loot_by_world[game_world] = _editor_loot_apply(
                loot_by_world[game_world], editor_loot, editor_loot_add)
        loot = loot_by_world["0"]

    # ЖИТЕЛИ КАРТЫ ЗАВИСЯТ ОТ МИРА. Раньше здесь всегда стоял мир 0, и в
    # чужой игре на карте оказывался двойник героя: за Велиславну в Чёрном
    # Бору стояла вторая Велиславна, с ней можно было заговорить. В её
    # собственном мире её среди жителей нет — первая запись карты 19 в
    # GAME.1 это сам герой (слот 0, сторона 0). Наборы и правда разные:
    # на карте 33 у мира 0 их семнадцать, у остальных четырнадцать.
    #
    # Поэтому выгружаем жителей ПО ВСЕМ ШЕСТИ МИРАМ, а клиент берёт набор
    # выбранного героя.
    def residents_of(game_world):
        units = []
        # Чья это карта — нужно и жителям, и их разговорам, поэтому берётся
        # до попытки чтения, а не внутри неё.
        from konung2.profile import CANON as _CANON
        game = _CANON
        # Настоящие жители карты из GAME.0 — с именами, местом, характеристиками
        # и снаряжением. Они мирные: сторона у них своя (55 у Черного Бора),
        # а нападать первыми в разборе движка мы правила пока не нашли.
        if number is not None:
            try:
                from konung2.gamefile import map_units
                game, native = _map_source(source, number)
                residents = map_units(native, _world_of(game, game_world, native),
                                      profile=game)
            except (OSError, ValueError, IndexError, LookupError):
                residents = []
            # ОТРЯД ИГРОКА — НЕ ЖИТЕЛИ. Запись отряда 0 владеет непрерывным
            # срезом массива юнитов: первый номер лежит в +0x00,длина в
            # +0x1C. Эти юниты и есть герой со спутниками, их ставит на карту
            # спавн отряда, а не расстановка жителей.
            #
            # Без этого фильтра за Велиславну в Чёрном Бору стоял её
            # ДВОЙНИК: в GAME.1 отряд игрока — юнит 0 на карте 19, и он же
            # приходил в список жителей. В мире Ратибора отряд стоит на
            # карте 33, поэтому там двойника и не было.
            residents = [entry for entry in residents
                         if not _in_player_party(entry.get("index"),
                                                 _world_of(game, game_world,
                                                           native),
                                                 game)]
            # НЕЙТРАЛЬНЫЙ МИР БЕЗ ЧУЖИХ ЗАВЯЗОК. Играбельный герой чужим
            # NPC не стоит нигде, и сюжетное лицо одного мира не мозолит
            # глаза остальным восьми: разница между героями — только точка
            # старта. Цена известна и принята: в Нижнем лагере викингов
            # (карта 37) пустует место знахарки — его занимала Хельга.
            # ДОМА ЧИСТКИ НЕТ. На картах своей игры герой читает свой мир
            # (см. `_world_of`), и вычищать из него сюжетные лица значило бы
            # ломать собственную завязку героя: у Драгомира это его лагерь.
            # В гостях всё по-прежнему — общий мир без чужих завязок.
            if STORY_FREE_WORLD and not _own_game(game, game_world):
                core = _neutral_core(game, native)
                heroes = _hero_unit_names()
                residents = [entry for entry in residents
                             if entry.get("name") not in heroes
                             and (core is None or _unit_key(entry) in core)]
            #: Занятые клетки этой карты: движок держит номер стоящего юнита
            #: в младших 12 битах клетки, и второй туда уже не встанет.
            taken_cells: set[tuple[int, int]] = set()
            for resident in residents:
                equipment = {}
                source_equipment = (resident.get("equipment_classes") or
                                    resident.get("equipment") or {})
                equipment_records = resident.get("equipment_item_records") or {}
                for slot, name in source_equipment.items():
                    if name is None:
                        continue
                    item = resolve(name)
                    remember(item)
                    equipment["off_hand" if slot == "shield" else slot] = \
                        _game_item_ref(item, equipment_records.get(slot))
                second_equipment = resident.get("second_classes") or resident.get("second") or {}
                second_records = resident.get("second_item_records") or {}
                for slot, name in second_equipment.items():
                    if name is None:
                        continue
                    item = resolve(name)
                    remember(item)
                    equipment[slot] = _game_item_ref(item, second_records.get(slot))
                # То, чем житель торгует, тоже должно приехать в пак: без
                # этого его мешок в обмене окажется пустым.
                bag = []
                source_bag = resident.get("bag_classes") or resident.get("bag", [])
                bag_records = resident.get("bag_item_records") or []
                for at, name in enumerate(source_bag):
                    if name is None:
                        continue
                    goods = resolve(name)
                    if goods:
                        remember(goods)
                        record = bag_records[at] if at < len(bag_records) else None
                        bag.append(_game_item_ref(goods, record))
                role = _unit_role(resident.get("index", 0), number)
                counter = []
                counter_details = []
                for name, record, detail in _village_counter(number, role):
                    goods = resolve(name)
                    remember(goods)
                    counter.append(_game_item_ref(goods, record))
                    counter_details.append(detail)
                # МЕСТО ЮНИТА. Записанные координаты движок при свежем входе
                # игнорирует: он рассыпает отряд по ЗОНЕ из его записи
                # (VA 0x415764) и берёт первую проходимую клетку из ста
                # попыток. У зверей в GAME.x стоят нули — без зоны они все
                # оказывались в углу карты.
                cell = _spawn_cell(world, resident, taken_cells)
                if cell is None:
                    continue
                anchor = cell.anchor()
                current = resident.get("current", {})
                # Разговор: номер диалога лежит в юните (+0xF2), сам диалог — в
                # QUESTS.RES деревом узлов (konung2/quests.py).
                #
                # ДЕРЕВО БЕРЁТСЯ ИЗ СВОЕЙ ИГРЫ. Номер разговора у жителя
                # донора — донорский, и по нашему файлу он читается как
                # ЧУЖАЯ реплика: его 9 это «Купец не отвечает, он уже
                # мертв», а у нас под тем же номером «Говори скорее, я
                # просто сгораю от нетерпения». Ничего при этом не падает —
                # оттого и не было видно, что все 264 его жителя говорили
                # нашими словами.
                talk = None
                if resident.get("dialog", 0xFF) != 0xFF:
                    try:
                        from konung2.profile import CANON as _CANON
                        from konung2.quests import Dialogs
                        talk = Dialogs.from_game(game).tree(resident["dialog"])
                        # Доводы-карты в дереве — родной игры; переводим их
                        # нашим же реестром, что и выходы. Классы предметов
                        # там тоже свои: без перевода Магнус вручал Гильдис
                        # нашу «Колдовскую приваду» вместо ключа.
                        if game is not _CANON and talk:
                            from konung2 import donor as _donor
                            talk = _translate_tree_arguments(
                                talk, _foreign_numbering(project, game.name),
                                _donor.item_class_map())
                    except (OSError, ValueError, IndexError, LookupError,
                            struct.error):
                        talk = None
                units.append({
                    "id": f"unit_{resident['index']}",
                    "name": resident["name"],
                    # ПОСТАВЛЕН РОВНО В ЗАПИСАННУЮ КЛЕТКУ (бит «координаты в
                    # силе», VA 0x43DF9C — движок при нём чужой занятости не
                    # смотрит). Такие юниты МОГУТ законно совпасть клеткой:
                    # на донорской карте 18 Садык и Воин записаны в одну.
                    "pinned": bool((resident.get("spawn_zone") or {})
                                   .get("keep_cells")),
                    # Рабочие места жителя: по ним он и ходит по деревне
                    # (VA 0x412C0C), а не стоит столбом. Числа здесь —
                    # НОМЕРА СЛОТОВ В ТАБЛИЦЕ СВОЕГО ОТРЯДА, поэтому рядом
                    # едет и номер отряда: без него слот 0 читался бы по
                    # чужой таблице.
                    "workplaces": resident.get("workplaces") or [],
                    "party": resident.get("party"),
                    # масть: палитра юнита из его записи (+0x2E / 512)
                    "palette": resident.get("palette", 0),
                    "side": resident["side"],
                    "face": resident["face"],
                    "level": resident["level"],
                    # своя отрава твари: у людей ноль, у гадов не ноль
                    "venom": resident.get("venom", 0),
                    # порода и тело: по ним юнит и выглядит собой (VA 0x424200)
                    "breed": resident.get("breed", 0),
                    "body": resident.get("body", 0),
                    # ЧЬЯ ИГРА — ЧЬИ ТЕЛА И ПАЛИТРЫ. Форм у «Продолжения
                    # легенды» больше, а из 256 палитр совпадают 218:
                    # его жители по общему ключу выходили красными с
                    # шумом (см. bodyKey в actor.js).
                    **({"game": "legend"} if game is not _CANON else {}),
                    # поза расстановки и счётчик породы: скелеты, ичетики и
                    # кикиморы лежат в позе 4 и встают своей анимацией
                    "pose": resident.get("pose", 0),
                    # ПОВОРОТ ИЗ РАССТАНОВКИ (+0x18, konung2/gamefile.py).
                    # Без него клиент ставил своё умолчание, и вся деревня
                    # встречала игрока лицом вниз.
                    "direction": resident.get("direction", 0),
                    "breed_counter": resident.get("breed_counter", 0),
                    # отрава на самих вещах: она в записи предмета, не в классе
                    "poison_on": resident.get("poison_on", {}),
                    # чем торговать: деньги, мешок и должность в деревне
                    "money": resident.get("money", 0),
                    "bag": bag,
                    "role": role,
                    "counter": counter,
                    "counter_details": counter_details,
                    # стреляет ли житель: движок смотрит только на то, есть ли
                    # метательное и есть ли боеприпас (VA 0x412FF4)
                    "ranged_mode": resident.get("ranged_mode", False),
                    "stats": {
                        "health": resident["health"],
                        "armour": resident["armour"],
                        "parry": current.get("Ловкость", 10),
                        "toughness": current.get("Выносливость", 10),
                        "strength": current.get("Сила", 10),
                        "accuracy": resident.get("accuracy", 60),
                    },
                    # ШЕСТЬ ХАРАКТЕРИСТИК ЦЕЛИКОМ, а не три из них в `stats`.
                    # В записи юнита это байты +0xC0 (свои) и +0xCC (с
                    # прибавками вещей), и они есть у КАЖДОГО: обучение у
                    # воеводы (0x4181E8) поднимает их обычному жителю.
                    "characteristics": resident.get("characteristics", {}),
                    "current": current,
                    # скорость записи (+0x1D): формула — только отряду игрока
                    # (0x41C944:305), житель ходит со значением из GAME.x
                    "speed": int(resident.get("speed", 0)),
                    # навыки нужны для точности: она считается по владению
                    # тем, чем юнит бьётся (VA 0x41B4CC)
                    "skills": resident.get("skills", {}),
                    "equipment": equipment,
                    # экземплярные крепость/чары вещей юнита (В10)
                    "bag_details": resident.get("bag_details", []),
                    "equipment_details": {
                        ("off_hand" if slot == "shield" else slot): detail
                        for slot, detail in
                        (resident.get("equipment_details") or {}).items()
                        if detail
                    } | (resident.get("second_details") or {}),
                    "cell": {"row": cell.row, "col": cell.col},
                    "position": {"x": anchor.x, "y": anchor.y},
                    "dialog": talk,
                    # НОМЕР разговора (unit+0xF2), а не его дерево: курсор над
                    # лежачим смотрит именно на число — заговорить с ним можно,
                    # только пока оно меньше восьми (VA 0x428B88).
                    "dialog_number": resident.get("dialog", 0xFF),
                })

        return units

    units_by_world = {index: residents_of(index)
                      for index in range(_hero_worlds())}
    units = list(units_by_world.get(0, []))

    def scenario_unit(entry: dict[str, Any]) -> dict[str, Any]:
        equipment = {}
        for slot, name in (entry.get("equipment") or {}).items():
            item = resolve(name)
            equipment[slot] = scenario_item(item, f"unit:{entry['id']}:{slot}")
        return {
            "id": entry["id"],
            "name": entry.get("name") or entry["id"],
            "palette": int(entry.get("palette", 0)),
            # Характеристики — поля юнита движка (+0x4E здоровье, +0x1F
            # точность, +0xCD стойкость, +0xD1 выносливость, +0xF4 броня);
            # значения приходят из расстановки, потому что настоящие лежат
            # в состоянии игры, а не в exe.
            "stats": {key: int(value)
                      for key, value in (entry.get("stats") or {}).items()},
            # умолчание скорости — ноль, как у всех записей GAME.x
            "speed": int(entry.get("speed", 0)),
            "equipment": equipment,
            **place(entry),
        }

    # РАСКЛАДКА ПРОЕКТА. Три слоя, и путать их нельзя:
    #   `units`          — общее для всех девяти героев;
    #   `units_by_world` — только своему слоту, это место под сюжет героя;
    #   `hide_by_world`  — кого из ОРИГИНАЛЬНОЙ расстановки убрать этому
    #                      слоту (ключ — `unit_<номер>`, как в паке).
    # Без второго и третьего поля сюжет писать некуда: своя расстановка
    # встала бы перед всеми девятью, а лишнее сюжетное лицо оригинала
    # (вроде Драгомира, который у Иззарка стоит на его же карте) убрать
    # было бы нечем.
    scenario_from = len(units)
    for entry in document.get("units", []):
        units.append(scenario_unit(entry))
    shared_units = units[scenario_from:]
    own_units = {str(slot): [scenario_unit(entry) for entry in (entries or [])]
                 for slot, entries
                 in (document.get("units_by_world") or {}).items()}
    hidden = {str(slot): set(names or ())
              for slot, names in (document.get("hide_by_world") or {}).items()}
    for slot, entries in units_by_world.items():
        gone = hidden.get(str(slot)) or set()
        if gone:
            entries[:] = [unit for unit in entries if unit.get("id") not in gone]
        entries.extend(shared_units)
        entries.extend(own_units.get(str(slot)) or [])
    # Запасной список читают только паки, собранные до девяти миров, но врать
    # он не должен: у него та же судьба, что у нулевого слота.
    gone_zero = hidden.get("0") or set()
    if gone_zero:
        units = [unit for unit in units if unit.get("id") not in gone_zero]
    units.extend(own_units.get("0") or [])

    # ПРАВКИ РЕДАКТОРА. Новый редактор (браузерный, поверх нашего ядра)
    # пишет ключ `editor_units` в project/maps/<карта>/scenario.json —
    # именно туда, а не в map.json: тот несёт метаданные карты, а
    # расстановку читает эта функция и только из scenario.json
    # (server.py, _editor_layer_file). Патчи по id юнита применяются
    # ПОВЕРХ канонной расстановки — и общей, и каждого мира. Белый список
    # полей держит патчи в рамках: редактор правит ДАННЫЕ юнита, а не его
    # устройство.
    editor_units = document.get("editor_units") or {}
    editor_units_add = document.get("editor_units_add") or []
    if editor_units or editor_units_add:
        units = _editor_units_apply(units, editor_units, editor_units_add)
        for slot in list(units_by_world):
            units_by_world[slot] = _editor_units_apply(
                units_by_world[slot], editor_units, editor_units_add)
        # СМЕНА НОМЕРА ДИАЛОГА ПЕРЕПЕКАЕТ ДЕРЕВО: оно испечено раньше
        # слоя, и без этого юнит говорил бы старыми словами под новым
        # номером. Добавленным юнитам дерево печётся их номером.
        talkers = {uid for uid, patch in editor_units.items()
                   if "dialog_number" in patch}
        talkers |= {entry.get("id") for entry in editor_units_add
                    if isinstance(entry, dict)
                    and entry.get("dialog_number", 0xFF) != 0xFF}
        if talkers:
            game, _native = _map_source(source, number)
            trees = {}
            for bunch in (units, *units_by_world.values()):
                for unit in bunch:
                    if unit.get("id") not in talkers:
                        continue
                    talk_number = unit.get("dialog_number", 0xFF)
                    if talk_number not in trees:
                        trees[talk_number] = _bake_dialog_tree(
                            game, project, talk_number)
                    unit["dialog"] = trees[talk_number]

    # Выходы с карты: прямоугольник в клетках переводим в мировые
    # координаты, чтобы клиенту было чем ловить героя.
    exits = []
    pending_exits: list[dict[str, Any]] = []
    if number is not None:
        from konung2.profile import CANON
        game, native = _map_source(source, number)
        try:
            from konung2.gamefile import map_exits
            found = map_exits(native, 0, profile=game)
        except (OSError, ValueError, IndexError, LookupError):
            found = []
        # ВЫХОДЫ ЧУЖОЙ ИГРЫ НАЗЫВАЮТ ЧУЖИЕ НОМЕРА. Переводим их в наши, а
        # дверь, которой у нас пока некуда вести — карта ещё не перенесена, —
        # НЕ выбрасываем молча: она уходит отдельным списком в сценарий, и
        # видно, сколько работы осталось. Открывать её нельзя: номер значил
        # бы у нас другое место.
        if game is not CANON:
            numbering = _foreign_numbering(project, game.name)
            translated = []
            for door in found:
                target = int(door["to_map"])
                # −1 «на карту мира» и −2 «особый переход» — это не номера, а
                # служебные значения, и переводить их нечем. А вот ЗАПЕРТАЯ
                # ДВЕРЬ хранит номер тем же полем, только отрицательным
                # (0x420900 тратит на неё связку ключей), и её перевести надо
                # — иначе донорская дверь откроется в нашу карту N.
                if target in (EXIT_TO_WORLD_MAP, -2):
                    translated.append(door)
                    continue
                sign = 1 if target > 0 else -1
                native_target = abs(target)
                if native_target in numbering:
                    translated.append({**door,
                                       "to_map": sign * numbering[native_target],
                                       "from_foreign_map": target})
                else:
                    pending_exits.append({**door, "foreign_map": native_target,
                                          "locked": sign < 0,
                                          "game": game.name})
            found = translated
        # ВЫХОДЫ ПРОЕКТА. У карты, которой нет в GAME.<мир>, выходов нет
        # вовсе: сочинённая с нуля локация открывается, и из неё некуда
        # деться. Поэтому карта проекта может объявить свои выходы прямо в
        # map.json — тем же набором полей, что и канонные.
        found = list(found) + _project_exits(source, number)
        for door in found:
            top_left = Cell(door["row1"], door["col1"]).anchor()
            bottom_right = Cell(door["row2"], door["col2"]).anchor()
            exits.append({**door,
                          "left": min(top_left.x, bottom_right.x),
                          "right": max(top_left.x, bottom_right.x),
                          "top": min(top_left.y, bottom_right.y),
                          "bottom": max(top_left.y, bottom_right.y)})

    # СЛОТЫ ЗАВОДЧИКА БРОДЯЧИХ ОТРЯДОВ этой карты. В отгруженных мирах ни
    # один не заведён — слоты ждут жребия, — но условие разговора 23 и гейт
    # раздачи у кузнеца про них спрашивают (docs/LOCATION_SPEC.md, разрез 2).
    #
    # ПО МИРАМ, как поселения: таблицы у GAME.N РАЗНЫЕ — в нулевом занято
    # семь слотов, в первом пять, в остальных четыре. Прежде события всегда
    # читались из GAME.0, и герой любого другого мира получал чужие.
    events = []
    events_by_world: dict[str, list] = {}
    if number is not None:
        try:
            from konung2.gamefile import map_events
            game, native = _map_source(source, number)
            for game_world in range(_hero_worlds()):
                events_by_world[str(game_world)] = map_events(
                    native, _world_of(game, game_world, native), profile=game)
            events = events_by_world.get("0", [])
        except (OSError, ValueError, IndexError, LookupError):
            events = []
            events_by_world = {}

    # ОТРЯДЫ КАРТЫ. Враждебность в движке принадлежит отряду, а не юниту:
    # один проход по отрядам (VA 0x415B20) смотрит их флаги и зону и решает,
    # объявлять ли бой. Сторона юнита (+0x1B) равна номеру отряда, поэтому
    # клиенту хватает этого списка, чтобы связать зверя с его стаей.
    #
    # ОТРЯДЫ ЗАВИСЯТ ОТ МИРА — как жители и кучи. Здесь стоял мир по
    # умолчанию, то есть нулевой, и наборы расходились: на карте 23 в мире
    # Ратибора стоят отряды 1, 30 и 65, а в мире Эйнара — 0, 1, 2, 31 и 66.
    # Сторона юнита равна НОМЕРУ его отряда (движок прямо индексирует ею
    # таблицу: `0x4333A4` берёт `+0x1B` юнита), поэтому у Асбада со стороной
    # 2 отряда просто не находилось — и действие 37 «поднять отряд
    # собеседника» поднимать было некого. Стражник не нападал.
    def warbands_of(game_world):
        if number is None:
            return []
        try:
            from konung2.gamefile import map_parties, player_party
            game, native = _map_source(source, number)
            bands = map_parties(native, _world_of(game, game_world, native),
                                profile=game)
            # ОТРЯД ИГРОКА (запись №0) ЕСТЬ НА ЛЮБОЙ КАРТЕ: движок держит
            # массив 0x71E56C глобально, и именно в запись №0 замах врага
            # по нашему юниту пишет войну (0x413894 кадр 2 -> 0x4159DC,
            # гейт +0x1F & 0x4F проходит — в данных стоит бит 0x40).
            # Фильтр map_parties по номеру карты терял её везде, кроме
            # стартовой карты мира, — и автоответ отряда был мёртв.
            if not any(band.get("side") == 0 for band in bands):
                # ОТРЯД ИГРОКА БЕРЁТСЯ ИЗ ЕГО СОБСТВЕННОЙ ИГРЫ И МИРА, а не
                # по номеру слота: слоты 6…8 это герои донора, и канонного
                # `GAME.6` не существует. Читалось по слоту — файл не
                # открывался, исключение уносило ВЕСЬ список, и на канонных
                # картах у миров 6…8 не оставалось ни одного отряда, а на
                # донорских — у миров 4…8.
                from konung2 import donor
                from konung2.profile import LEGEND
                slots = donor.HERO_SLOTS
                owner, home = (slots[game_world]
                               if 0 <= game_world < len(slots)
                               else ("canon", 0))
                band = player_party(home,
                                    profile=LEGEND if owner == "legend"
                                    else None)
                if band:
                    bands.insert(0, band)
            return bands
        except (OSError, ValueError, IndexError, LookupError):
            return []

    warbands_by_world = {str(game_world): warbands_of(game_world)
                         for game_world in range(_hero_worlds())}
    # ДОБАВЛЕННЫЕ РЕДАКТОРОМ ОТРЯДЫ — во все миры разом: отряды миров
    # разные, а добавка редактора одна на карту (scenario.json,
    # editor_warbands_add; ручка editor_warband_add дев-сервера).
    editor_warbands = document.get("editor_warbands_add") or []
    for band in editor_warbands:
        if not isinstance(band, dict) or "side" not in band:
            continue
        for bunch in warbands_by_world.values():
            if not any(int(entry.get("side", -1)) == int(band["side"])
                       for entry in bunch):
                bunch.append(dict(band))
    # ПРАВКИ ОТРЯДОВ ИГРЫ — отдельным слоем, как у куч и юнитов
    # (`editor_warbands`, ключ — НОМЕР СТОРОНЫ строкой). Прежде редактор
    # умел отряд только завести и удалить: сделать существующий отряд
    # мирным или подвинуть его зону было нечем, а это половина работы со
    # стычками. Слой ложится ПОВЕРХ отрядов каждого мира — как и
    # добавка: отряды у миров разные, а правка редактора одна на карту.
    editor_band_patches = document.get("editor_warbands") or {}
    if editor_band_patches:
        for bunch in warbands_by_world.values():
            for entry in bunch:
                patch = editor_band_patches.get(str(entry.get("side")))
                if not isinstance(patch, dict):
                    continue
                for key, value in patch.items():
                    if key in EDITOR_WARBAND_DICTS and isinstance(value, dict):
                        target = entry.setdefault(key, {})
                        if isinstance(target, dict):
                            target.update(value)
                    elif key in EDITOR_WARBAND_FIELDS:
                        entry[key] = value
    warbands = warbands_by_world["0"]

    # Поселение карты: постройки, люди и казна (запись 0x4A1 байт).
    #
    # ЗАПИСЬ СВОЯ В КАЖДОМ МИРЕ. Здесь стояло `village(number)` — то есть
    # всегда мир 0, ратиборовский. Разница не косметическая: должностные лица
    # деревни (пятёрка номеров с +0x3D0) в каждом GAME.N другие — на Борье это
    # [236,237,238,239] у Ратибора против [229,230,231,232] у Александра.
    #
    # На них держится маршрутизация разговора: корневая ветвь спрашивает
    # обработчиком 30 «занимает ли собеседник должность N» (VA 0x435550), и
    # если номера чужого мира не совпали ни с одним, разговор проваливается в
    # последнюю ветвь — безусловную. У деревенских это «Я отдохнул и готов
    # идти за тобой», реплика наёмника. Первый бета-тестер играл Александром и
    # получил ровно это от всех торговцев Борья.
    settlements_by_world: dict[str, dict] = {}
    settlement = None
    #: Таблицы рабочих мест по номеру отряда: у каждого отряда карты своя,
    #: и номера в записи жителя — слоты ИМЕННО ЕГО таблицы.
    workplaces_by_party: dict[str, list] = {}
    if number is not None:
        try:
            from konung2.gamefile import village
            game, native = _map_source(source, number)
            for game_world in range(_hero_worlds()):
                # Поселение донорской карты лежит в ЕГО GAME и под ЕГО
                # номером; какой из его миров достаётся слоту — см. _world_of.
                record = village(native, _world_of(game, game_world, native),
                                 profile=game)
                if record:
                    settlements_by_world[str(game_world)] = record
            settlement = settlements_by_world.get("0")
        except (OSError, ValueError, IndexError, LookupError):
            settlement = None
        # Продукция мастерской обязана приехать в пак классами: мастер куёт
        # стрелы, болты и снаряжение культуры (VA 0x417BD8), и без их
        # описаний деревне нечего ковать и нечем одаривать жителей.
        if settlement:
            from konung2.buildings import (WORKSHOP_AMMO_CLASSES,
                                           WORKSHOP_CULTURE_BASE,
                                           WORKSHOP_CULTURE_STEP,
                                           WORKSHOP_GEAR_SHIFT,
                                           WORKSHOP_GOODS)
            gear_first = (WORKSHOP_CULTURE_BASE +
                          settlement.get("culture", 0) * WORKSHOP_CULTURE_STEP)
            for class_number in [*WORKSHOP_AMMO_CLASSES,
                                 *range(gear_first,
                                        gear_first + WORKSHOP_GOODS
                                        - WORKSHOP_GEAR_SHIFT)]:
                try:
                    goods = resolve(class_number)
                except ContentBuildError:
                    continue
                if goods:
                    remember(goods)
        # Таблица рабочих мест лежит не в записи поселения, а в записи
        # ОТРЯДА жителей (VA 0x412C0C читает её оттуда). Кладём её рядом:
        # без неё жители не знают, куда ходить.
        #
        # КЛАСТЬ НАДО В КАЖДЫЙ МИР. Раньше строка писала только в `settlement`,
        # а это тот же объект, что мир «0», — и записи миров 1…8 уезжали в пак
        # БЕЗ рабочих мест. Клиент подменяет `map.village` записью своего мира
        # (world.js), так что за любого героя, кроме Ратибора, жители деревни
        # не знали, куда ходить.
        #
        # Файл берётся СВОЕЙ игры: на донорской карте канонный GAME.0 отвечает
        # про чужую деревню (и попадает по номеру только случайно).
        #
        # ТАБЛИЦА У КАЖДОГО ОТРЯДА СВОЯ, И БРАТЬ ПЕРВУЮ ПОПАВШУЮСЯ НЕЛЬЗЯ.
        # На Морском лагере (карта 23) записей отряда три: тройка Хрофта с
        # восемью местами, трое скоморохов без мест и сама деревня — 13
        # человек и 29 мест. Сюда попадала первая, Хрофтова, а числа в записи
        # жителя — это НОМЕРА СЛОТОВ ЕГО СОБСТВЕННОЙ таблицы. Оттого знахарь,
        # купец, староста и кузнец деревни, чьи слоты 0…2, уходили работать
        # на клетки Хрофта, Хрорара и Эгиля — то есть кучковались у Хрофта
        # вместо своих мест. Поэтому в пак едут ВСЕ таблицы карты, по номеру
        # отряда, а поселению достаётся та, которой владеют его должностные.
        try:
            import struct as _struct
            from konung2.gamefile import _game_bytes, workplaces
            game, native = _map_source(source, number)
            blob, layout = _game_bytes(BASE_WORLD, game)
            at, count, size = layout["parties"]
            owners = {}
            for party_index in range(count):
                record = blob[at + party_index * size:][:size]
                if _struct.unpack_from("<H", record, 0x08)[0] != native:
                    continue
                places = workplaces(record)
                first = _struct.unpack_from("<H", record, 0x00)[0]
                owners[party_index] = {
                    "places": places,
                    "units": range(first, first + record[0x1C]),
                }
            workplaces_by_party = {str(index): band["places"]
                                   for index, band in owners.items()
                                   if band["places"]}
            # Хозяин деревни — тот отряд, в чьём срезе лежат её должностные.
            officials = [number for number in
                         ((settlement or {}).get("officials") or []) if number]
            village_band = next(
                (band for band in owners.values()
                 if band["places"] and officials
                 and all(who in band["units"] for who in officials)), None)
            if village_band:
                if settlement is None:
                    settlement = {}
                settlement["workplaces"] = village_band["places"]
                for record_of_world in settlements_by_world.values():
                    record_of_world["workplaces"] = village_band["places"]
        except (OSError, ValueError, IndexError, KeyError, LookupError):
            workplaces_by_party = {}

    # Кого встретим в пути по глобальной карте (VA 0x4360A8). Считается
    # здесь, а не в сборке карты, потому что снаряжение встречных должно
    # попасть в тот же список предметов, что и у жителей.
    encounters = _encounter_roster(resolve, remember)

    def only_different(by_world: dict, default) -> dict:
        """Мир пишем в карту, ТОЛЬКО если он отличается от общего.

        Пока сюжетов нет, все девять слотов несут одно и то же, и девять
        одинаковых списков раздували карту: у Тиграта жители занимали
        2,3 МБ из 4,5, с девятью ключами вышло бы вдвое больше. Клиент на
        отсутствующий ключ берёт общий список — `units.js:382`,
        `warband.js:80`, `loot.js:88`, `world.js:77`, — так что это не
        потеря данных, а отсутствие копии. Появится сюжет — появится и
        ключ, сам собой.
        """
        same = json.dumps(default, ensure_ascii=False, sort_keys=True)
        return {str(world): entries
                for world, entries in by_world.items()
                if json.dumps(entries, ensure_ascii=False,
                              sort_keys=True) != same}

    #: ПРАВКИ ПОСЕЛЕНИЯ — слоем `editor_village`, поверх записи КАЖДОГО
    #: мира. Поселение в проекте не лежит: оно читается из GAME.<мир>
    #: при сборке, и трогать его там нельзя. Поэтому единственный способ
    #: дать редактору править деревню — этот слой, как у куч и отрядов.
    editor_village = document.get("editor_village") or {}
    if editor_village:
        _editor_village_apply(settlement, editor_village)
        for world_record in settlements_by_world.values():
            _editor_village_apply(world_record, editor_village)

    return {
        "village": settlement,
        #: То же поселение по мирам: клиент берёт запись мира своего героя,
        #: а `village` остаётся ратиборовским для старых сейвов и тестов.
        "village_by_world": only_different(settlements_by_world, settlement),
        #: Рабочие места по отрядам карты. Житель ходит по слотам СВОЕЙ
        #: таблицы, а `village.workplaces` — таблица деревни, для тех, у кого
        #: отряд не назван.
        "workplaces_by_party": workplaces_by_party,
        "events": events,
        #: То же по мирам — клиент подменяет список записью своего мира
        #: (world.js, рядом с поселением).
        "events_by_world": only_different(events_by_world, events),
        "exits": exits,
        #: Двери чужой игры, которым у нас пока некуда вести: карта, куда
        #: они ведут, ещё не перенесена. Список пустой — мердж по этой карте
        #: закрыт; непустой — видно, каких карт не хватает.
        "pending_exits": pending_exits,
        "encounters": encounters,
        "items": {name: describe(item) for name, item in sorted(used.items())},
        # КВЕСТОВЫЕ ВЕЩИ И ЗЕЛЬЯ, КОТОРЫХ В ЭТОМ МИРЕ ЕЩЁ НЕТ. Обычно вид
        # записи берётся из class_kinds по всем GAME.x, а для создаваемых по
        # ходу классов он закреплён каноном: группа 11 у квестовых веток
        # 0x436C48 и группа 9 у банок 83…92, которые разбирает 0x41D954.
        # Интерфейс игры: рамка, полоса пояса, окно снаряжения и раскладка
        # левой панели — картинки из INTERF.RES, координаты из exe.
        "interface": interface(),
        "loot": loot,
        # Кучи выбранного мира; `loot` остаётся миром 0 для старых клиентов.
        "loot_by_world": only_different(loot_by_world, loot),
        "units": units,
        # Жители по мирам: клиент берёт набор ВЫБРАННОГО героя, иначе на
        # карте появляется двойник (см. residents_of выше). Расстановка из
        # scenario.json общая и добавляется поверх каждого набора.
        "units_by_world": only_different(units_by_world, units),
        "warbands": warbands,
        # Отряды выбранного мира; `warbands` остаётся миром 0 для старых клиентов.
        "warbands_by_world": only_different(warbands_by_world, warbands),
    }


def _faces_in_use(world: int = 0, maps: Iterable[int] = (),
                  project: Path | None = None) -> set[int]:
    """Лица, которые понадобятся: свой отряд, жители карт и все шесть героев."""
    faces = {0}
    try:
        from konung2.gamefile import party
        for member in party(0, world).get("members", []):
            faces.add(int(member.get("face", 0)))
    except (OSError, ValueError, IndexError):
        pass
    for number in maps:
        for resident in _project_residents_all(project, number):
            faces.add(int(resident.get("face", 0)))
    # ЛИЦА ШЕСТИ СТАРТОВЫХ ГЕРОЕВ. Портрет любого юнита — спрайт «лицо + 261»
    # (VA 0x430631), и у героев миров 0…5 лица тоже 0…5. Собирались они
    # только по отряду и жителям СВОЕЙ карты, поэтому в паке лежал один
    # ui_261, а панель выбранного героя просила ui_262 и получала 404 —
    # отсюда и чужая иконка на месте своей.
    for index in range(6):
        try:
            from konung2.gamefile import hero_stats
            faces.add(int(hero_stats(index).get("face", 0) or 0))
        except (OSError, ValueError, IndexError, KeyError, AssertionError):
            continue
    return faces


def _legend_faces_in_use(world: int = 0, maps: Iterable[int] = (),
                         project: Path | None = None) -> set[int]:
    """Лица «Продолжения легенды»: его герои и жители его карт.

    Номер лица у обеих игр индексирует спрайт «лицо + 261», но портреты под
    этими номерами разные — поэтому и собираются отдельно.
    """
    from konung2 import donor
    from konung2.profile import LEGEND
    if not donor.available():
        return set()
    faces: set[int] = set()
    for game, index in donor.HERO_SLOTS:
        if game != "legend":
            continue
        try:
            from konung2.gamefile import hero_stats
            faces.add(int(hero_stats(index, LEGEND).get("face", 0) or 0))
        except (OSError, ValueError, IndexError, KeyError, AssertionError):
            continue
    for number in maps:
        try:
            source = _find_map_source(project, number) if project else None
        except ContentBuildError:
            continue
        if source is None:
            continue
        origin = (json.loads((source / "map.json").read_text(encoding="utf-8"))
                  .get("origin") or {}).get("game")
        if origin != donor.LEGEND_NAME:
            continue
        for resident in _project_residents_all(project, number):
            faces.add(int(resident.get("face", 0) or 0))
    return faces


def _hero_party(world: int = 0, profile=None) -> dict[str, Any] | None:
    """Отряд игрока из стартового мира: спутники и вместимость."""
    try:
        from konung2.gamefile import party
        result = party(0, world, profile)
        legend = profile is not None
        translate = {}
        if legend:
            from konung2 import donor
            translate = donor.item_class_map()
        origin = "legend" if legend else "game"

        def our_class(number):
            if number is None:
                return None
            return translate.get(number, number) if legend else number

        # В GAME.x слоты ссылаются на экземпляры, чей байт +3 содержит
        # класс СВОЕЙ игры. Имена не уникальны и в runtime не годятся;
        # донорские классы здесь же переводятся в наши номера.
        for member in result.get("members", []):
            equipment_classes = member.get("equipment_classes") or {}
            equipment_records = member.get("equipment_item_records") or {}
            member["equipment"] = {
                slot: (_game_item_ref(our_class(index),
                                      equipment_records.get(slot), world, origin)
                       if index is not None else None)
                for slot, index in equipment_classes.items()
            }
            bag_classes = member.get("bag_classes") or []
            bag_records = member.get("bag_item_records") or []
            member["bag"] = [
                (_game_item_ref(our_class(index),
                                bag_records[at] if at < len(bag_records) else None,
                                world, origin)
                 if index is not None else None)
                for at, index in enumerate(bag_classes)
            ]
            second_classes = member.get("second_classes") or {}
            second_records = member.get("second_item_records") or {}
            member["second"] = {
                slot: (_game_item_ref(our_class(index),
                                      second_records.get(slot), world, origin)
                       if index is not None else None)
                for slot, index in second_classes.items()
            }
            # Второй набор в runtime является продолжением equipment.
            member["equipment"].update(member["second"])
            member["equipment_details"] = {
                **(member.get("equipment_details") or {}),
                **(member.get("second_details") or {}),
            }
            # ДЕРЕВО РАЗГОВОРА СПУТНИКА. У него, как у любого юнита, есть
            # номер диалога в +0xF2, и в паке он ехал — а само дерево нет.
            # Из-за этого с собственными спутниками нельзя было заговорить
            # вовсе: Ctrl по ним ничего не давал, а значит и назначить их на
            # должность в деревне было нельзя — назначение идёт через разговор
            # (действие 74). Деревья лежат в QUESTS.RES, и номера спутников
            # (118 у Путяты, 144 у Тура) на картах не встречаются, взять их
            # оттуда было неоткуда. Дерево — из СВОЕЙ игры (у донора номера
            # значат его деревья).
            if member.get("dialog", 0xFF) != 0xFF:
                try:
                    from konung2.quests import Dialogs
                    member["dialog_tree"] = Dialogs.from_game(
                        profile if legend else None).tree(member["dialog"])
                except (OSError, ValueError, IndexError, struct.error):
                    member["dialog_tree"] = None
        return result
    except (OSError, ValueError, IndexError):
        return None


def _party_money(world: int = 0) -> int:
    try:
        from konung2.gamefile import party_money
        return party_money(0, world)
    except (OSError, ValueError, IndexError):
        return 0


def _dialog_handlers() -> list[dict[str, Any]]:
    """Разобранные обработчики разговора (konung2/quests.py)."""
    try:
        from konung2.quests import handler_table
        return [row for row in handler_table() if row["verified"]]
    except (OSError, ValueError):
        return []


def _hero_template(index: int = 0, profile=None) -> dict[str, Any] | None:
    """Настоящий герой из стартового мира GAME.<index>.

    Характеристики, навыки, здоровье, свободный опыт и снаряжение — не наши
    числа, а запись юнита №0 из GAME.x (konung2/gamefile.py). Именно эти
    файлы, а не NEWHERO.RES, держат стартовое состояние: в NEWHERO лежит
    только картинка экрана выбора героя.
    """
    try:
        from konung2.gamefile import hero_stats
        stats = hero_stats(index, profile)
    except (OSError, AssertionError, ValueError):
        return None
    # Донорские классы предметов переводятся в НАШИ номера здесь же: клиент
    # знает один каталог, и его 19 «Амулет Дракона» обязан стать нашим
    # хвостовым, а не нашей 19 «Рубахой».
    legend = profile is not None
    translate = {}
    if legend:
        from konung2 import donor
        translate = donor.item_class_map()
    origin = "legend" if legend else "game"

    def our_class(number):
        if number is None:
            return None
        return translate.get(number, number) if legend else number

    equipment = {
        slot: (_game_item_ref(
            our_class(class_number),
            (stats.get("equipment_item_records") or {}).get(slot), index,
            origin)
               if class_number is not None else None)
        for slot, class_number in stats["equipment_classes"].items()
    }
    equipment.update({
        slot: (_game_item_ref(
            our_class(class_number),
            (stats.get("second_item_records") or {}).get(slot), index,
            origin)
               if class_number is not None else None)
        for slot, class_number in (stats.get("second_classes") or {}).items()
    })
    bag_records = stats.get("bag_item_records") or []
    bag = [
        (_game_item_ref(our_class(class_number),
                        bag_records[at] if at < len(bag_records) else None,
                        index, origin)
         if class_number is not None else None)
        for at, class_number in enumerate(stats.get("bag_classes") or [])
    ]
    return {
        "world": index,
        "level": stats["level"], "face": stats["face"],
        # ОБЛИК ГЕРОЯ. Тело (+0x17) выбирает набор слоёв, палитра (+0x2E) —
        # раскраску; у шести стартовых героев тела 0…5, и без этого поля
        # клиент искал слои по `undefined` и рисовал болванчика, а панель
        # показывала лицо героя мира 0 всем подряд.
        "body": stats.get("body", 0), "palette": stats.get("palette", 0),
        "health": stats["health"], "free_xp": stats["free_xp"],
        "armour": stats["armour"], "experience": stats["experience"],
        "characteristics": [stats["characteristics"][name] for name in CHARACTERISTICS],
        # текущие (+0xCC) отдельно от базовых (+0xC0): экран показывает обе
        # колонки, а пределы навыков движок считает по текущим (VA 0x413268)
        "current": [stats["current"][name] for name in CHARACTERISTICS],
        "skills": stats["skills"],
        "equipment": equipment,
        "bag": bag,
        "bag_details": stats.get("bag_details") or [],
        "equipment_details": {
            **(stats.get("equipment_details") or {}),
            **(stats.get("second_details") or {}),
        },
        "poison_on": stats.get("poison_on") or {},
        # чем герой бьётся на старте: байт unit+0xEE
        "ranged_mode": stats["ranged_mode"],
        # КОШЕЛЁК ЛЕЖИТ В ЗАПИСИ ГЕРОЯ, а не отряда: движок адресует его как
        # `0x84951C + 0x26`, где 0x84951C — указатель на запись юнита-героя
        # (тот же, через который идут торговля и обыск куч). В записи ОТРЯДА
        # по тому же смещению лежит ноль во всех шести мирах, и пока деньги
        # брались оттуда, герой начинал игру без единой монеты. Настоящие
        # стартовые суммы: мир 0 — 3000, мир 1 — 500, мир 2 — 3, остальные
        # по 100.
        "money": stats["money"],
        # весь отряд: герой и спутники, с вместимостью из записи отряда
        "party": _hero_party(index, profile),
    }


#: ПОСЕЛЕНИЯ — БЛОК, А НЕ ПРИЛОЖЕНИЕ К КАРТЕ. Движок читает весь массив
#: записей один раз (0x43D898 при новой игре, 0x4236E0 из сейва) и держит его
#: в памяти всё время; вход на карту лишь НАХОДИТ в нём свою запись по байту
#: +0x03. Поэтому разговор может спросить про деревню, где игрок не был:
#: обработчик 35 «Продолжения легенды» ровно это и делает — ищет поселение по
#: номеру карты среди двадцати (FUN_0043f670) и спрашивает его флаги.
#:
#: У нас же запись приезжала только вместе со своей картой, то есть про
#: непосещённую деревню ответить было нечем. Отсюда этот указатель: СКАЛЯРНОЕ
#: состояние всех поселений, по мирам. Постройки и жители сюда не идут — они
#: тяжёлые (девять с половиной килобайт на запись) и спрашивают их только на
#: своей карте.
SETTLEMENT_STATE_FIELDS = ("map", "index", "flags", "status", "owner",
                           "owned", "treasury", "officials", "squad_people",
                           "side", "wealth", "culture", "master")

#: Ключей в указателе поселений ровно столько, сколько слотов на экране
#: выбора (см. _hero_worlds): указатель читают обработчики разговоров, и
#: герою нужен ЕГО мир, а не нулевой.


def _settlements_index(project: Path | None) -> dict[str, list[dict[str, Any]]]:
    """Скалярное состояние всех поселений обеих игр, по мирам."""
    from konung2.gamefile import village, villages
    from konung2.profile import CANON

    def state(record: dict[str, Any] | None) -> dict[str, Any] | None:
        if not record:
            return None
        return {key: record[key] for key in SETTLEMENT_STATE_FIELDS
                if key in record}

    out: dict[str, list[dict[str, Any]]] = {}
    for world in range(_hero_worlds()):
        try:
            found = [state(record) for record in villages(_world_of(CANON,
                                                                    world))]
        except (OSError, ValueError, IndexError, KeyError):
            found = []
        out[str(world)] = [entry for entry in found if entry]
    # ПОСЕЛЕНИЯ ПЕРЕНЕСЁННЫХ КАРТ. Они лежат в GAME.<мир> ДОНОРА и под ЕГО
    # номером, а в паке карта зовётся по-нашему — значит и номер в указателе
    # должен быть наш, иначе обработчик будет искать не то.
    if project is None:
        return out
    for path in sorted((project / "maps").glob("*/map.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        profile, native = _map_source(path.parent, None)
        if profile is CANON or native is None:
            continue
        # ЗАПИСЬ СВОЯ У КАЖДОГО СЛОТА. Здесь стоял его нулевой мир на всех,
        # и Драгомир получал состояние поселений мира Иззарка. Слот помнит,
        # чей мир читать (_world_of), а копия на слот, а не общий объект:
        # иначе правка одного мира тронет все девять.
        for world in out:
            try:
                entry = state(village(native, _world_of(profile, int(world), native),
                                      profile=profile))
            except (OSError, ValueError, IndexError, KeyError, LookupError):
                continue
            if not entry:
                continue
            entry["map"] = int(document["map_number"])
            entry["game"] = profile.name
            out[world].append(entry)
    return out


def _find_map_source(project: Path, number: int) -> Path:
    index_path = project / "index.json"
    if index_path.is_file():
        index = json.loads(index_path.read_text(encoding="utf-8"))
        for item in index.get("maps", []):
            if int(item.get("map", -1)) == number:
                candidate = project / str(item["dir"])
                if candidate.is_dir():
                    return candidate
    candidates = sorted((project / "maps").glob(f"{number:02d}_*"))
    if len(candidates) == 1:
        return candidates[0]
    raise ContentBuildError(
        f"карта {number}: ожидалась одна папка проекта, найдено {len(candidates)}")


#: Опись файлов с их хэшами — пятнадцать секунд на каждую сборку: sha256
#: считается для всех двенадцати тысяч файлов, хотя меняются единицы.
#: Держим прошлые хэши рядом с паком и берём готовый, если размер и время
#: правки файла те же.
FILE_INDEX = ".knyaz2-file-index.json"


def _pack_map_numbers(destination: Path, numbers: tuple[int, ...]) -> tuple[int, ...]:
    """Карты, по которым считаются ОБЩИЕ ассеты: собираемые плюс лежащие в паке.

    Кадры тел, слои снаряжения и наборы тварей общие на всю игру, а списки
    для них собираются по картам. Считая только по картам текущего вызова,
    сборка одной карты выкидывала чужие наборы из shared.json.
    """
    known: set[int] = set(numbers)
    manifest_path = destination / "manifest.json"
    if manifest_path.is_file():
        try:
            document = json.loads(manifest_path.read_text(encoding="utf-8"))
            for item in document.get("maps") or []:
                number = item.get("legacy_number")
                if isinstance(number, int):
                    known.add(number)
        except (OSError, ValueError):
            pass
    return tuple(sorted(known))


def _collect_files(root: Path) -> tuple[PackedFile, ...]:
    index_path = root / FILE_INDEX
    try:
        known = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        known = {}
    fresh: dict[str, list[Any]] = {}
    result = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if relative in (PACK_MARKER, "manifest.json", FILE_INDEX):
            continue
        stat = path.stat()
        stamp = [stat.st_size, int(stat.st_mtime_ns)]
        cached = known.get(relative)
        if cached and cached[:2] == stamp:
            digest = cached[2]
        else:
            digest = _sha256(path)
        fresh[relative] = [*stamp, digest]
        result.append(PackedFile(relative, stat.st_size, digest))
    try:
        index_path.write_text(json.dumps(fresh), encoding="utf-8")
    except OSError:
        pass
    return tuple(result)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, document: Any, pretty: bool = False) -> None:
    """Записать документ пака.

    БЕЗ ОТСТУПОВ. Описания карт — это миллионы мелких чисел, и отступы в два
    пробела раздували их ВДВОЕ С ЛИШНИМ: одна карта весила 25.5 МБ вместо
    10.0 МБ. Читать их глазами всё равно незачем, а по сети это платит
    игрок. Отступы оставлены только там, где документ мелкий и его правда
    читают руками (manifest).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if pretty:
        text = json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2)
    else:
        text = json.dumps(document, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"))
    path.write_text(text + "\n", encoding="utf-8", newline="\n")


def _validate_destination(destination: Path, project: Path) -> None:
    dangerous = {Path(destination.anchor).resolve(), Path.home().resolve(),
                 Path.cwd().resolve(), project.resolve()}
    if destination in dangerous:
        raise ContentBuildError(f"опасный путь для generated content pack: {destination}")
    if destination.exists() and not (destination / PACK_MARKER).is_file():
        raise ContentBuildError(
            f"папка {destination} не помечена как generated content pack; очистка запрещена")


def _publish(stage: Path, destination: Path) -> None:
    backup: Path | None = None
    if destination.exists():
        backup = Path(tempfile.mkdtemp(prefix=f".{destination.name}.previous-",
                                       dir=destination.parent))
        backup.rmdir()
        try:
            os.replace(destination, backup)
        except OSError:
            # Windows не даёт переименовать папку, пока её держит чужой
            # процесс — например запущенный `python -m knyaz2.web`. Тогда
            # переносим содержимое внутрь существующей папки: она уже
            # проверена как generated content pack.
            backup.mkdir(exist_ok=True)
            backup.rmdir()
            _publish_in_place(stage, destination)
            return
    try:
        os.replace(stage, destination)
    except Exception:
        if backup is not None and backup.exists() and not destination.exists():
            os.replace(backup, destination)
        raise
    if backup is not None:
        shutil.rmtree(backup)


def _publish_in_place(stage: Path, destination: Path) -> None:
    """Перенести собранный pack в уже существующую папку без переименования."""
    fresh = {path.relative_to(stage).as_posix()
             for path in stage.rglob("*") if path.is_file()}
    for relative in sorted(fresh):
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(stage / relative, target)
    for path in sorted((p for p in destination.rglob("*") if p.is_file()),
                       key=lambda p: len(p.parts), reverse=True):
        if path.relative_to(destination).as_posix() not in fresh:
            path.unlink()
    for path in sorted((p for p in destination.rglob("*") if p.is_dir()),
                       key=lambda p: len(p.parts), reverse=True):
        if not any(path.iterdir()):
            path.rmdir()
    shutil.rmtree(stage, ignore_errors=True)


def _contained_path(root: Path, relative: str) -> Path:
    raw = Path(relative)
    if raw.is_absolute() or ".." in raw.parts:
        raise ContentBuildError(f"опасный путь в manifest: {relative}")
    path = (root / raw).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ContentBuildError(f"путь выходит из content pack: {relative}") from exc
    return path


#: Экран создания героя: таблица прямоугольников (VA 0x461D44) и точки, по
#: которым движок ставит кнопки и портрет (0x4622B4, 0x4622C4, 0x4622D4).
CREATION_RECTS_VA = 0x461D44
CREATION_PLAY_AT_VA, CREATION_CANCEL_AT_VA = 0x4622B4, 0x4622C4
CREATION_PORTRAIT_AT_VA = 0x4622D4
#: Рамка описания героя: 0x431548 печатает строку с переносом от x 0x4622E4
#: до x 0x4622EC, начиная с y 0x4622E8. Нижней границы в коде нет — текст
#: течёт вниз, а visually его держит рамка фона; снизу стоят кнопки (y 699).
CREATION_STORY_X_VA, CREATION_STORY_Y_VA = 0x4622E4, 0x4622E8
CREATION_STORY_X2_VA = 0x4622EC
#: Коды щелчков (они же номера прямоугольников), разбор — 0x438A00, case 2.
CREATION_CODES = {
    "portraits": [0, 5], "characteristic_raise": [6, 11],
    "characteristic_lower": [12, 17], "skill_raise": [18, 37],
    "skill_lower": [38, 57], "play": 87, "cancel": 88,
}



def _in_player_party(index: int | None, world: int = 0, game=None) -> bool:
    """Принадлежит ли юнит отряду игрока в этом мире.

    Запись отряда 0 владеет непрерывным срезом массива юнитов: первый номер
    в +0x00, длина в +0x1C. Это герой и его спутники — на карту их ставит
    спавн отряда, и в списке жителей им делать нечего.

    Срез берётся из ТОЙ ЖЕ игры, что и карта. Раньше файл открывался жёстко
    канонным `GAME.<мир>`, и на донорских картах фильтр мерил чужой линейкой.
    Убытка это пока не приносило (у обеих игр отряд начинается с юнита 0, а
    юниты 1-2 на его картах жителями не выходят — проверено по всем 90), но
    держалось на совпадении, а с приходом его миров 1-3 совпадение кончается.
    """
    if index is None:
        return False
    try:
        from konung2.gamefile import player_party
        band = player_party(world, profile=game)
    except (OSError, ValueError, IndexError, LookupError):
        return False
    if not band:
        return False
    first = int(band.get("first_unit") or 0)
    return first <= int(index) < first + max(0, int(band.get("count") or 0))

#: Сетка девяти портретов на перерисованном фоне: столбцы родные (движок
#: держал их в 0x461D44), ряды пересчитаны, чтобы третий не налез на рамку
#: описания (её верх на y=390 фона). Ключ — номер СЛОТА выбора: верхний ряд
#: остался женским (Велиславна-Хельга-Анастасия), средний — бывший нижний,
#: нижний — герои «Продолжения легенды».
CREATION_GRID_COLS = (104, 266, 429)
CREATION_GRID_ROWS = (95, 195, 295)
CREATION_CELL = (79, 91)
CREATION_SLOT_CELLS = {
    1: (0, 0), 3: (1, 0), 5: (2, 0),
    0: (0, 1), 2: (1, 1), 4: (2, 1),
    6: (0, 2), 7: (1, 2), 8: (2, 2),
}
#: Тусклые лица на фоне против ярких блоков: средняя разница 10…16 из 255
#: (сверено пиксельно на родном фоне), приглушаем той же величиной.
CREATION_DIM = 0.94


def _creation_grid_rects() -> list[list[int]]:
    """Девять зон выбора, индекс — слот экрана."""
    out = []
    for slot in range(9):
        col, row = CREATION_SLOT_CELLS[slot]
        x1 = CREATION_GRID_COLS[col]
        y1 = CREATION_GRID_ROWS[row]
        out.append([x1, y1, x1 + CREATION_CELL[0], y1 + CREATION_CELL[1]])
    return out


def _export_creation(root: Path) -> dict[str, Any]:
    """Экран создания героя: фон, девять портретов и разметка щелчков.

    Картинки — из NEWHERO.RES обеих игр (см. konung2/res.py). Фон
    перерисовывается: у родного вшито шесть рамок с тусклыми лицами и
    именами, а слотов теперь девять. Портретная зона заливается плиткой
    чистого неба с того же фона, рамка клонируется с первой родной
    позиции, лица вписываются приглушёнными — как это делает движок
    (яркая версия ложится поверх только у выбранного). Имена печатает
    клиент шрифтом.

    Разметка щелчков — из exe: 91 прямоугольник по 0x461D44; первые шесть
    (зоны портретов) заменяются девятью, поэтому все коды после них
    сдвигаются на три.
    """
    from PIL import Image

    from konung2 import donor
    from konung2.exetables import va_to_foff
    from konung2.res import newhero_blocks, newhero_sprite

    folder = root / "assets" / "creation"
    folder.mkdir(parents=True, exist_ok=True)

    def sprite(index: int, data: bytes | None = None) -> Image.Image | None:
        shot = newhero_sprite(index, data)
        if not shot:
            return None
        width, height, pixels = shot
        picture = Image.new("RGBA", (width, height))
        picture.putdata(pixels)
        return picture

    def save(picture: Image.Image | None, name: str) -> dict[str, Any] | None:
        if picture is None:
            return None
        relative = Path("assets") / "creation" / f"{name}.png"
        picture.save(str(root / relative))
        return {"path": relative.as_posix(),
                "width": picture.width, "height": picture.height}

    blocks = newhero_blocks()
    legend_raw = (Path(donor.donor_file("newhero.res")).read_bytes()
                  if donor.available() else None)

    # Портреты по слотам: канонные — наши блоки 1+мир, донорские — его.
    portraits: list[dict[str, Any] | None] = []
    shots: list[Image.Image | None] = []
    for slot, (game, native) in enumerate(donor.HERO_SLOTS):
        if game == "legend" and legend_raw is not None:
            picture = sprite(1 + native, legend_raw)
        elif game == "canon" and 1 + native < len(blocks):
            picture = sprite(1 + native)
        else:
            picture = None
        shots.append(picture)
        portraits.append(save(picture, f"hero_{slot}"))

    # Фон: чистим родную портретную зону и штампуем девять рамок.
    background_image = sprite(0) if blocks else None
    grid = _creation_grid_rects()
    if background_image is not None:
        base = background_image.convert("RGB")
        # Плитка чистого неба — зазор между родными столбцами ВЫШЕ вшитых
        # имён (первое имя начинается около y=204; плитка с именем внутри
        # разносила его обрывки по всей зоне).
        tile = base.crop((196, 118, 258, 196))
        # Чистка НИЖЕ драконьей арки заголовка (она кончается на y≈90) и до
        # рамки описания (y=390); слева с запасом — вшитые имена шире рамок.
        clear_area = (80, 90, 522, 390)
        for x in range(clear_area[0], clear_area[2], tile.width):
            for y in range(clear_area[1], clear_area[3], tile.height):
                base.paste(tile.crop((0, 0, min(tile.width, clear_area[2] - x),
                                      min(tile.height, clear_area[3] - y))),
                           (x, y))
        # пустая рамка — родная верхне-левая позиция с замазанным лицом
        margin = 9
        old = [104, 109, 183, 200]
        frame_src = background_image.convert("RGB").crop(
            (old[0] - margin, old[1] - margin,
             old[2] + margin, old[3] + margin))
        inner = tile.crop((0, 0, old[2] - old[0], old[3] - old[1]))
        frame_src.paste(inner, (margin, margin))
        for slot, rect in enumerate(grid):
            base.paste(frame_src, (rect[0] - margin, rect[1] - margin))
            face = shots[slot]
            if face is None:
                continue
            dimmed = face.convert("RGB").point(
                lambda value: int(value * CREATION_DIM))
            base.paste(dimmed, (rect[0] + 1, rect[1] + 2))
        background_image = base.convert("RGBA")
    background = save(background_image, "background")

    with open(game_file("konung2.exe"), "rb") as stream:
        blob = stream.read()
    at = va_to_foff(CREATION_RECTS_VA)
    rects: list[list[int]] = []
    while True:
        x1, y1, x2, y2 = struct.unpack_from("<4i", blob, at + len(rects) * 16)
        if x1 == -1:
            break
        rects.append([x1, y1, x2, y2])
    # первые шесть зон — портреты; их место занимает наша сетка на девять,
    # хвост таблицы жив, но каждый код за портретами вырос на три
    shift = len(grid) - 6
    rects = grid + rects[6:]

    def moved(code: int) -> int:
        return code + shift if code > 5 else code

    codes = {}
    for key, value in CREATION_CODES.items():
        if isinstance(value, list):
            codes[key] = [moved(code) for code in value]
        else:
            codes[key] = moved(value)
    codes["portraits"] = [0, len(grid) - 1]

    def point(va: int) -> list[int]:
        return list(struct.unpack_from("<2i", blob, va_to_foff(va)))

    return {
        "screen": {"width": 1024, "height": 768},
        "background": background,
        "portraits": portraits,
        "rects": rects,
        "codes": codes,
        "play_at": point(CREATION_PLAY_AT_VA),
        "cancel_at": point(CREATION_CANCEL_AT_VA),
        "portrait_at": point(CREATION_PORTRAIT_AT_VA),
        "story_box": {
            "x": struct.unpack_from("<i", blob,
                                    va_to_foff(CREATION_STORY_X_VA))[0],
            "y": struct.unpack_from("<i", blob,
                                    va_to_foff(CREATION_STORY_Y_VA))[0],
            "x2": struct.unpack_from("<i", blob,
                                     va_to_foff(CREATION_STORY_X2_VA))[0],
            # снизу текст упирается в кнопки
            "y2": struct.unpack_from("<2i", blob,
                                     va_to_foff(CREATION_PLAY_AT_VA))[1],
        },
    }


#: Окно карты в оригинале: экран 1024x768 минус левая панель 140 и нижняя
#: полоса 60 (её движок рисует в (140, 708) — VA 0x438A00:204).
CAMERA_VIEW_W, CAMERA_VIEW_H = 0x374, 0x2C4
#: Верхняя граница — константа (VA 0x4291B4).
CAMERA_TOP = 0x20


def _camera_bounds(kn2: KN2Map) -> dict[str, int]:
    """Границы камеры карты — как их считает загрузчик (VA 0x43DF48:108-148).

    Движок сканирует сетку клеток на крайние НЕПУСТЫЕ строку и столбцы и
    переводит их в пиксели шагом клетки (58 по X, 16 по Y — VA 0x43B974):

        низ   = (последняя непустая строка − 1) * 16
        лево  = (первый непустой столбец + 1) * 58
        право = (последний непустой столбец − 2) * 58

    Верх — константа 0x20. «Плюс одна» и «минус две» — не описка: рамка
    намеренно уже сетки.

    Кламп (VA 0x4291B4 и 0x437CD0, дословно одинаковые) держит ЛЕВЫЙ ВЕРХ
    камеры: `x < лево -> лево`, иначе `право < x + 0x374 -> право − 0x374`;
    по Y так же с 0x20 и 0x2C4. Порядок веток важен: на карте меньше окна
    выигрывает первая, и камера просто прижимается к левому верхнему углу.
    """
    empty = {"left": 0, "right": 0, "top": CAMERA_TOP, "bottom": 0,
             "view_width": CAMERA_VIEW_W, "view_height": CAMERA_VIEW_H}
    # ПУСТОТА — ЭТО ВЕСЬ DWORD, а не младшее слово. Снято дизассемблером
    # (0x43E340 `cmp dword ptr [eax], 0`): клетка занимает четыре байта, шаг
    # строки 0x280, шаг столбца 4. Декомпилят показывал шаг строки 0x140 и
    # указатель `int*` — это его артефакт типизации, в машинном коде 0x280.
    # На собранных картах младшее слово даёт те же границы, но полагаться на
    # такое совпадение нельзя.
    filled = lambda x, y: any(kn2.cell(x, y))
    try:
        rows = [y for y in range(GRID_H)
                if any(filled(x, y) for x in range(GRID_W))]
        columns = [x for x in range(GRID_W)
                   if any(filled(x, y) for y in range(GRID_H))]
    except (struct.error, IndexError):
        return empty
    if not rows or not columns:
        return empty
    return {
        "left": (columns[0] + 1) * CELL_W,
        "right": (columns[-1] - 2) * CELL_W,
        "top": CAMERA_TOP,
        "bottom": (rows[-1] - 1) * CELL_H,
        "view_width": CAMERA_VIEW_W,
        "view_height": CAMERA_VIEW_H,
    }


def _transitions() -> list[dict[str, Any]]:
    """Граф переходов из GAME.0 — общий на пак, адресуется номером записи."""
    try:
        from konung2.gamefile import all_exits
        return all_exits(0)
    except (OSError, ValueError, IndexError, struct.error):
        return []


def _transitions_by_game(project: Path | None) -> dict[str, list[dict[str, Any]]]:
    """Граф переходов каждой игры, номер записи — её собственный.

    Действие разговора «перенести отряд игрока по переходу» адресует запись
    НОМЕРОМ в таблице выходов (VA 0x435AA0). Таблицы у игр разные: у нас 250
    записей по 17 байт, у донора 350 по 16. Один общий граф означал бы, что
    донорский разговор переносит героя по НАШЕЙ записи под тем же номером —
    то есть в случайное место, и молча.

    Карты назначения переводятся в наши номера тем же реестром, что и
    выходы; непереводимая цель остаётся, но помечается — открывать её
    нельзя, а знать о ней надо.
    """
    from konung2.gamefile import all_exits
    from konung2.profile import CANON, PROFILES
    out: dict[str, list[dict[str, Any]]] = {}
    for profile in PROFILES.values():
        if not profile.available():
            continue
        try:
            graph = all_exits(0, profile=profile)
        except (OSError, ValueError, IndexError, LookupError, struct.error):
            continue
        if profile is CANON:
            out[profile.name] = graph
            continue
        numbering = _foreign_numbering(project, profile.name)
        records = []
        for door in graph:
            target = int(door["to_map"])
            if target in (EXIT_TO_WORLD_MAP, -2):
                records.append(door)
                continue
            sign = 1 if target > 0 else -1
            native = abs(target)
            if native in numbering:
                records.append({**door, "to_map": sign * numbering[native],
                                "from_foreign_map": target})
            else:
                records.append({**door, "to_map": 0,
                                "foreign_map": native, "game": profile.name})
        out[profile.name] = records
    return out


def _quest_state(project: Path | None = None,
                 overlay: bool = True) -> dict[str, Any]:
    """Начальное состояние квестов — хвост QUESTS.RES.

    `overlay=False` берёт ОТГРУЖЕННЫЙ сюжет игры, без собранного нами
    (project/story/QUESTS.RES): свой квест добавляет в эту же таблицу свои
    токены и строки журнала, и сверкам канона нужен файл без них.

    Триста dword по смещению 0x72358 движок целиком кладёт в 0x6A50E8
    (konung2/quests.py: STATE_OFF/STATE_SIZE), и оттуда же их сохраняет и
    читает сейв (`FUN_004432c4(файл, &DAT_006a50e8, 0x4b0)` в 0x423CB8 и
    парная ей 0x4236E0).

    В младшем байте два рабочих бита:

    * 0x80 — «квест отмечен». Его спрашивает условие разговора
      `(&DAT_006a50e8)[номер * 4] & 0x80` (VA 0x436664), по нему же строится
      журнал. В ФАЙЛЕ ЭТОТ БИТ НЕ ВЗВЕДЁН НИ У ОДНОГО из трёхсот — игра
      начинается с пустым журналом, и это канон.
    * 0x01 — «подойди и заговори». Не «с этим уже говорили»: его ставит
      действие 62 (0x4357B4) и снимает действие 61 (0x435750), а читает его
      0x410684 — NPC с этим битом, оказавшись в шести клетках по X и трёх по
      Y от игрока, САМ переводит игрока в приказ 0x22 на себя. В файле взведён
      у шести диалогов: 8 Мунд, 16 Верховный Палач, 26 Константин,
      36 Повелитель, 50 Хакон Всеслав, 60 Воин Повелителя.

    Слово по +2 — номер ФРАЗЫ журнала (та же таблица, что у реплик), −1 значит
    «в журнале не показывать». Записи, чей текст начинается с «MAP=», движок
    тоже пропускает (strncmp по 0x4524BD в 0x42A8F4) — это скрипт-команды.

    Порт не читал блок вовсе: не было ни авто-подхода, ни журнала.
    """
    from konung2 import donor
    from konung2.profile import LEGEND
    from konung2.quests import Dialogs
    empty = {"flags": [], "journal": [], "text": {}}
    try:
        dialogs = Dialogs.from_game(overlay=overlay)
    except OSError:
        return empty

    def words_of(source):
        at, size = source.profile.quests_layout()["quest_states"]
        block = source.data[at:at + size]
        if len(block) < size:
            return None
        return struct.unpack(f"<{size // 4}I", block)

    words = words_of(dialogs)
    if words is None:
        return empty
    # КВЕСТЫ ОБЕИХ ИГР В ОДНОЙ ТАБЛИЦЕ. Обе считают с нуля — занято у канона
    # 0…102, у донора 0…161, — поэтому его состояния кладутся со сдвигом
    # PROJECT_QUEST_BASE, тем же, каким разбор разговоров уводит его номера.
    #
    # ТАБЛИЦА РАСТЁТ. У движка её мест 300, и обе игры в них не влезают:
    # 152 + 161 = 313. База считается по номерам РАЗГОВОРОВ (их у канона
    # 151), а не по занятым квестам, — иначе донорский квест ложится на
    # канонный разговор, и его житель начинает вести себя по чужой заявке.
    # Таблица у нас своя: клиент читает её по номеру, сейв хранит словарём.
    size = max(len(words), donor.QUEST_SLOTS if donor.available() else 0)
    flags = [word & 0xFF for word in words] + [0] * (size - len(words))
    journal, text = [-1] * size, {}
    scripts: dict[str, dict[str, Any]] = {}
    numbering = (_foreign_numbering(project, donor.LEGEND_NAME)
                 if project is not None else {})
    sources = [(dialogs, 0, words)]
    if donor.available():
        try:
            theirs = Dialogs.from_game(LEGEND, overlay=overlay)
        except (OSError, LookupError):
            theirs = None
        their_words = words_of(theirs) if theirs else None
        if their_words:
            sources.append((theirs, donor.PROJECT_QUEST_BASE, their_words))
    for source, shift, block in sources:
        for native, word in enumerate(block):
            # НУЛЕВОЕ СЛОВО — СВОБОДНОЕ МЕСТО, а не «квест с фразой 0»:
            # прежний код и для пустого хвоста заводил записи журнала.
            if not word:
                continue
            index = native + shift
            if index >= len(flags):
                break
            if shift:
                # Заявка донора не должна тереть канон; выше 128 канонные
                # места пусты, так что спорить тут некому — но проверяем.
                if flags[index] or journal[index] != -1:
                    raise ContentBuildError(
                        f"квест {index}: место занято каноном, сдвиг мал")
                flags[index] = word & 0xFF
            phrase = (word >> 16) & 0xFFFF
            if phrase == 0xFFFF:
                continue
            try:
                # Текст журнала — из СВОЕГО файла: номер фразы у каждой
                # игры свой.
                line = source.phrase(phrase)["text"]
            except (IndexError, ValueError):
                continue
            # Скрипт-команды, а не текст задания. Канон знал одну «MAP=»,
            # донор добавил ещё две: «взвести квест» у него значит поставить
            # бит 0x80 И исполнить эту строку (его 0x4399C8 зовёт 0x439864).
            # MAP=карта,строка,столбец,значение пишет клетку сетки — так по
            # сюжету открываются проходы; OBJECT= переставляет объект в
            # состояние. В журнал они не идут, а в пак едут разобранными.
            if line.startswith(("MAP=", "OBJECT=", "LANDSCAPE=")):
                kind, _, tail = line.partition("=")
                try:
                    arguments = [int(piece, 0) for piece
                                 in tail.replace(";", ",").split(",")
                                 if piece.strip()]
                except ValueError:
                    continue
                entry: dict[str, Any] = {"kind": kind.lower(),
                                         "args": arguments}
                # ПЕРВЫЙ ДОВОД ЛЮБОЙ ИЗ ТРЁХ КОМАНД — НОМЕР КАРТЫ: его
                # 0x439864 сверяет его с текущей картой у всех трёх, а не
                # только у MAP=. У донора номер донорский — переводим.
                if arguments and shift:
                    ours = numbering.get(arguments[0])
                    if ours is None:
                        entry["foreign_map"] = arguments[0]
                    else:
                        entry["native_map"] = arguments[0]
                        entry["args"] = [ours, *arguments[1:]]
                scripts[str(index)] = entry
                continue
            journal[index] = phrase
            text[str(index)] = line
    return {
        "flags": flags,
        "journal": journal,
        "text": text,
        # Скрипты квестов: номер -> {kind, args}; исполняются при взводе.
        "scripts": scripts,
        "known_bit": 0x80,
        "approach_bit": 0x01,
        # окно журнала: шаг строки и нижняя граница (0x42A8F4)
        "line_step": 6,
        "bottom": 0x251,
    }
