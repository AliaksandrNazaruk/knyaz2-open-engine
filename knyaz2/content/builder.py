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
                           SLOT_FIELDS, ItemClass, read_items)
from konung2.world import Building, Cell, Entity, MapModel
from konung2.kn2 import GRID_H, GRID_W, KN2Map, SEC_FLAG, T_DYNAMIC, T_LIGHT
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
from konung2.heroes import ANCHOR_X as HERO_ANCHOR_X, ANCHOR_Y as HERO_ANCHOR_Y
from konung2.cells import rules as cell_rules
from konung2.creatures import rules as creature_rules
from konung2.worldmap import MAP_SPRITE, PARTY_SPRITE, PLAYER_SPRITE
from konung2.worldmap import encounter_templates
from konung2.worldmap import markers as world_markers
from konung2.worldmap import rules as worldmap_rules
from konung2.res import ObjectsRes, read_palettes
from konung2.heroes import (ACTION_BLOCKS, CROSSBOW_GROUP, DEATH_VARIANTS,
                            DIRECTION_STEPS, DIRECTIONS, GAIT_CELL_FRACTION,
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
                   world: int = 0) -> str:
    """Канонический экземпляр GAME.x; fallback класса — для старых данных."""
    if record:
        return _instance_ref(item, f"game:{world}:{int(record)}")
    return _item_ref(item)



class ContentBuildError(RuntimeError):
    """Content pack нельзя безопасно или корректно собрать."""


class _AssetExporter:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.graph = GraphRes.from_game()
        self.objects = ObjectsRes.from_game()
        self.palettes = read_palettes()
        self.ground_cache: dict[tuple[int | None, int | None, int | None], str | None] = {}
        self.underlay_cache: dict[tuple[int, bool], dict[str, Any] | None] = {}
        self.overlay_cache: dict[int, dict[str, Any] | None] = {}
        self.object_cache: dict[tuple[int, int, int], dict[str, Any] | None] = {}
        self.light_cache: dict[tuple[int | None, int | None, int], str | None] = {}
        self.light_masks: list[bytes] | None = None

    def ground(self, lower: int | None, upper: int | None,
               light: int | None) -> str | None:
        # Browser-0 is the daylight/static renderer. VA 0x424FD8 uses the
        # ordinary two-draw path unless both runtime lighting flags are set;
        # the KN2 light-mask id is exported as metadata for that future state.
        key = (lower, upper, None)
        if key in self.ground_cache:
            return self.ground_cache[key]

        sprite = self.graph.compose_cell(lower, upper)

        if sprite is None:
            self.ground_cache[key] = None
            return None

        name = "_".join("none" if value is None else str(value) for value in key) + ".png"
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
        key = (lower, upper, light)
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
        name = f"{'none' if lower is None else lower}_" \
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
        key = (tile, horizontal_scroll)
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
        relative = Path("assets") / "underlay" / f"{tile}_phase1_{suffix}.png"
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
            source_relative = Path("assets") / "underlay" / f"{tile}_source.png"
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
        if resource_slot in self.overlay_cache:
            return self.overlay_cache[resource_slot]
        sprite = self.graph.decode_tile(resource_slot)
        if sprite is None:
            self.overlay_cache[resource_slot] = None
            return None
        relative = Path("assets") / "terrain_overlays" / f"{resource_slot}.png"
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        sprite.save(str(path))
        result = {
            "path": relative.as_posix(),
            "width": sprite.width,
            "height": sprite.height,
        }
        self.overlay_cache[resource_slot] = result
        return result

    def object(self, resource_slot: int, palette_index: int,
               state: int = 0) -> dict[str, Any] | None:
        key = (resource_slot, palette_index, state)
        if key in self.object_cache:
            return self.object_cache[key]
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
                    f"{resource_slot}_{palette_index}_{state}.png")
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
            layer_relative = (Path("assets") / "objects" /
                              f"{resource_slot}_{palette_index}_{state}_{name}.png")
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
        return result


def build_content_pack(map_numbers: Iterable[int], output: str | Path,
                       project_dir: str | Path = PROJECT_DIR,
                       content_id: str = DEFAULT_CONTENT_ID) -> ContentManifest:
    """Атомарно собрать content pack и вернуть его манифест."""
    numbers = tuple(sorted(set(int(number) for number in map_numbers)))
    if not numbers:
        raise ContentBuildError("не указано ни одной карты")

    project = Path(project_dir).resolve()
    destination = Path(output).resolve()
    _validate_destination(destination, project)
    destination.parent.mkdir(parents=True, exist_ok=True)

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
        hero = _export_hero(stage, _scenario_layers(project, numbers),
                            _scenario_body_palettes(project, numbers),
                            _scenario_body_shapes(numbers + encounters),
                            _scenario_body_pairs(project, numbers),
                            reuse=destination if destination.is_dir() else None)
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
        hero = {**hero, "template": _hero_template(), "starts": _hero_choices(),
                # экран создания: фон и портреты из NEWHERO.RES, разметка из exe
                "creation": _export_creation(stage)}
        # ОБЩЕЕ — ОДИН РАЗ. Кадры героя, слои снаряжения и наборы тварей
        # одинаковы на всех картах: раньше они лежали в КАЖДОМ map.json и
        # весили там 9 МБ из 10. Теперь они выносятся в один файл, который
        # клиент тянет однажды, а карта остаётся при своём.
        creatures = _export_creatures(stage, _creature_sets(numbers))
        shared = {"schema_version": CONTENT_MAP_SCHEMA,
                  "hero": hero, "creatures": creatures}
        _write_json(stage / "shared.json", shared)
        maps = tuple(_export_map(number, project, stage, assets, audio, daylight,
                                 hero)
                     for number in numbers)
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


def _canon_map_name(number: int) -> str | None:
    """Каноничное имя локации из таблицы имён exe.

    Имена карт в проекте правятся руками, и тестовое имя оттуда утекало в
    игру. Таблица же неизменна, поэтому имя берём из неё.
    """
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


def _hero_choices() -> list[dict[str, Any]]:
    """Шесть героев экрана «Новая игра» — по одному на стартовый мир.

    Движок при выборе персонажа читает запись юнита 0 из GAME.<номер>
    (VA 0x4387CC), а карту, где этот герой начинает, хранит запись отряда
    игрока (+0x08 таблицы отрядов). NEWHERO.RES тут ни при чём: в нём лежит
    только картинка самого экрана.
    """
    import struct as _struct

    from konung2.gamefile import T_PARTIES

    stories = _hero_stories()
    out: list[dict[str, Any]] = []
    for index in range(6):
        path = Path(BUILD_DIR) / f"GAME.{index}"
        if not path.is_file():
            continue
        template = _hero_template(index)
        if not template:
            continue
        data = path.read_bytes()
        party = data[T_PARTIES.offset:T_PARTIES.offset + T_PARTIES.size]
        story = stories[index] if index < len(stories) else ""
        out.append({
            "world": index,
            "map": int(_struct.unpack_from("<H", party, 0x08)[0]),
            "row": int(_struct.unpack_from("<H", party, 0x0C)[0]),
            "col": int(party[0x14]),
            # Имя — первое предложение описания: движок печатает описание
            # целиком, а имя отдельным полем нигде не держит.
            "name": story.split(".", 1)[0].strip() if story else "",
            "story": story,
            "template": template,
        })
    return out


def _hero_start(map_number: int) -> dict[str, Any] | None:
    """Канонная стартовая клетка героя на этой карте — из GAME.x.

    Отряд игрока (запись 0 таблицы отрядов) хранит карту в +0x08 и клетку в
    +0x0C/+0x14. Берём тот мир, чей герой начинает именно здесь.
    """
    import struct as _struct

    from konung2.gamefile import GameWorld, T_PARTIES

    for index in range(6):
        path = Path(BUILD_DIR) / f"GAME.{index}"
        if not path.is_file():
            continue
        world = GameWorld(index, path.read_bytes())
        party = world.data[T_PARTIES.offset:T_PARTIES.offset + T_PARTIES.size]
        if _struct.unpack_from('<H', party, 0x08)[0] != map_number:
            continue
        return {
            "world": index,
            "row": int(_struct.unpack_from('<H', party, 0x0C)[0]),
            "col": int(party[0x14]),
        }
    return None


def _scenario_layers(project: Path,
                     numbers: Iterable[int]) -> dict[int, list[int]]:
    """Слои экипировки, которые понадобятся картам: слой -> СПИСОК палитр.

    Выгружать все 54 слоя незачем — берём только те, что называет расстановка,
    плюс «в покое» для метательного (лук 19 -> 20, самострел 21 -> 22).

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
    # Герой выходит в мир уже одетым (GAME.0), и его доспех, шлем и щит
    # рисуются на нём такими же слоями, как поднятое с земли.
    template = _hero_template()
    start = [name for name in (template or {}).get("equipment", {}).values() if name]
    for number in numbers:
        try:
            source = _find_map_source(project, number)
        except ContentBuildError:
            continue
        names = list(start)
        # ЖИТЕЛИ СОБИРАЮТСЯ ВСЕГДА, А НЕ ТОЛЬКО ПРИ scenario.json.
        #
        # Раньше весь разбор карты стоял под `if not path.is_file(): continue`,
        # а scenario.json есть РОВНО У ОДНОЙ карты из 52 (19, Чёрный Бор).
        # Экипировка жителей остальных карт не запрашивалась ни разу, и её
        # слои в пак не попадали: воины Повелителя (карты 1, 3, 6, 14, 15)
        # оставались без щита, шлема и двуручного оружия — те просто не
        # рисовались. Соседняя `_scenario_body_palettes` обходит жителей вне
        # гейта, поэтому тела красились верно, а снаряжение пропадало.
        try:
            from konung2.gamefile import map_units, party
            for resident in map_units(number, 0):
                names.extend((resident.get("equipment_classes") or
                              resident.get("equipment") or {}).values())
            for member in party(0, 0).get("members", []):
                names.extend((member.get("equipment_classes") or
                              member.get("equipment") or {}).values())
        except (OSError, ValueError, IndexError, KeyError):
            pass
        path = source / "scenario.json"
        if path.is_file():
            document = json.loads(path.read_text(encoding="utf-8"))
            names.extend(entry["item"] for entry in document.get("loot", []))
            for entry in document.get("units", []):
                names.extend((entry.get("equipment") or {}).values())
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


def _encounter_numbers() -> tuple[int, ...]:
    """«Номера карт», под которыми лежат шаблоны встречных отрядов."""
    try:
        return tuple(sorted(encounter_templates()))
    except (OSError, ValueError, IndexError, struct.error):
        return ()


def _encounter_units() -> list[dict[str, Any]]:
    """Все бойцы встречных отрядов — одним списком, для разбора графики."""
    out: list[dict[str, Any]] = []
    try:
        for template in encounter_templates().values():
            out.extend(template["units"])
    except (OSError, ValueError, IndexError, struct.error):
        pass
    return out


def _encounter_roster(resolve, remember) -> dict[str, Any]:
    """Кого мы встретим в пути: состав каждого шаблона.

    Движок хранит эти отряды как обычные (VA 0x4360A8 ищет отряд, у
    которого номер карты равен номеру группы) и на встрече копирует
    целиком. Здесь тот же состав в том же виде, что и жители карты, —
    клиенту остаётся расставить их вокруг вожака.
    """
    roster: dict[str, Any] = {}
    try:
        templates = encounter_templates()
    except (OSError, ValueError, IndexError, struct.error):
        return roster
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
                "speed": 2, "sight_cells": 10,
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


def _creature_sets(numbers: Iterable[int]) -> set[tuple[int, int]]:
    """Все пары «тело + масть» тварей на этих картах и во встречных отрядах.

    Набор нужен ОДИН на весь пак, а не на карту. Раньше каждая карта звала
    свой экспорт и писала в одни и те же ``assets/creatures/creature_N.png``,
    так что наборы карт затирали друг друга: у всех карт, кроме собранной
    последней, номера листов указывали на чужие спрайты.
    """
    out: set[tuple[int, int]] = set()
    for unit in _encounter_units():
        if int(unit.get("breed", 0) or 0) & 0x40:
            out.add((int(unit.get("body", 0) or 0), int(unit.get("palette", 0) or 0)))
    try:
        from konung2.gamefile import map_units
        for number in numbers:
            for resident in map_units(number):
                if int(resident.get("breed", 0) or 0) & 0x40:
                    out.add((int(resident.get("body", 0) or 0),
                             int(resident.get("palette", 0) or 0)))
    except (OSError, ValueError, IndexError):
        pass
    return out


def _scenario_body_shapes(numbers: Iterable[int]) -> set[int]:
    """Какие тела встречаются на этих картах (байт unit+0xFC)."""
    shapes: set[int] = set()
    try:
        from konung2.gamefile import map_units
        for number in numbers:
            for resident in map_units(number):
                shape = int(resident.get("body", 0) or 0)
                # звери рисуются своим набором, а не слоем человека
                if shape and not (int(resident.get("breed", 0) or 0) & 0x40):
                    shapes.add(shape)
    except (OSError, ValueError, IndexError):
        pass
    # Тела шести стартовых героев (1…5; нулевое — базовый набор кадров).
    # Их тоже нет ни в одной расстановке, а без слоёв выбранный герой
    # выходит болванчиком.
    for index in range(6):
        try:
            from konung2.gamefile import hero_stats
            shape = int(hero_stats(index).get("body", 0) or 0)
            if shape:
                shapes.add(shape)
        except (OSError, ValueError, IndexError, KeyError, AssertionError):
            continue
    return shapes


def _spawn_cell(world_model, resident: dict) -> "Cell | None":
    """Куда встанет юнит: канон VA 0x415764.

    Центр зоны отряда плюс случайное смещение в её половину, знак каждой
    оси — свой бросок. До ста попыток найти проходимую клетку; не нашлось —
    юнита на карте не будет, как и в движке.
    """
    zone = resident.get("spawn_zone") or {}
    # Бит «координаты в силе» — юнит встаёт ровно туда, где записан
    # (VA 0x43DF9C). Так стоят жители деревень; рассыпают только тех, у
    # кого бит снят, — звериные отряды с нулями в записи.
    if zone.get("keep_cells"):
        return Cell(int(resident["row"]), int(resident["col"]))
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
        if world_model.terrain.passable(cell):
            return cell
    return None


def _scenario_body_pairs(project: Path,
                         numbers: Iterable[int]) -> set[tuple[int, int]]:
    """Пары «форма тела + палитра», которые реально просят юниты.

    ФОРМА И ПАЛИТРА НЕЗАВИСИМЫ. Движок сперва ставит палитру ЮНИТА, и только
    потом рисует его слой тела (VA 0x425DB4):

        [0x8A7318] = юнит+0x2E;                    // палитра
        слой = юнит+0xF9 >> 0x18; если слой -> += 0x30;
        рисуем(юнит, слой);                        // тело В ЭТОЙ палитре

    Порт же пёк формы одной палитрой (`body_layers[форма]`), а палитры —
    только для базового тела (`bodies[палитра]`), и выбирал ОДНО ИЗ ДВУХ.
    Из шести стартовых героев форму имеют пятеро, и все пятеро выходили в
    базовой раскраске: Велиславна (1/70), Эйнар (2/28), Хельга (3/31),
    Александр (4/34), Анастасия (5/34). Отсюда «одинаковый болванчик».

    Берутся ИМЕННО ПАРЫ, а не произведение форм на палитры: последнее
    раздуло бы выпечку в разы без всякой пользы.
    """
    pairs: set[tuple[int, int]] = set()

    def add(shape: Any, palette: Any, breed: Any = 0) -> None:
        shape, palette = int(shape or 0), int(palette or 0)
        # звери рисуются своим набором из OBJECTS.RES, слоя тела у них нет
        if shape and palette and not (int(breed or 0) & 0x40):
            pairs.add((shape, palette))

    for number in numbers:
        try:
            source = _find_map_source(project, number)
        except ContentBuildError:
            continue
        path = source / "scenario.json"
        if path.is_file():
            document = json.loads(path.read_text(encoding="utf-8"))
            for entry in document.get("units", []):
                add(entry.get("body"), entry.get("palette"))
        try:
            from konung2.gamefile import map_units
            for resident in map_units(number, 0):
                add(resident.get("body"), resident.get("palette"),
                    resident.get("breed"))
        except (OSError, ValueError, IndexError, KeyError):
            continue
    # Шесть стартовых героев: их пары не встречаются ни в одной расстановке.
    for index in range(6):
        try:
            from konung2.gamefile import hero_stats
            stats = hero_stats(index)
            add(stats.get("body"), stats.get("palette"))
        except (OSError, ValueError, IndexError, KeyError, AssertionError):
            continue
    return pairs


def _scenario_body_palettes(project: Path, numbers: Iterable[int]) -> set[int]:
    """Палитры тела, которые просят юниты карт. Палитра юнита — [0x8A7318]."""
    palettes: set[int] = set()
    for number in numbers:
        try:
            source = _find_map_source(project, number)
        except ContentBuildError:
            continue
        path = source / "scenario.json"
        if not path.is_file():
            continue
        document = json.loads(path.read_text(encoding="utf-8"))
        for entry in document.get("units", []):
            palette = int(entry.get("palette", 0))
            if palette:
                palettes.add(palette)
    # Жители карт приезжают не из scenario.json, а прямо из GAME.x, и
    # палитра у каждого своя (движок красит юнита целиком, подставляя её
    # перед блиттером — [0x8A7318], VA 0x426707). Без них ВСЕ НПЦ выходят
    # в базовой палитре героя и оттого на одно лицо.
    #
    # Звери сюда не идут: у них свой набор кадров из OBJECTS.RES.
    for number in numbers:
        try:
            from konung2.gamefile import map_units
            for resident in map_units(number, 0):
                if int(resident.get("breed", 0) or 0) & 0x40:
                    continue
                palette = int(resident.get("palette", 0) or 0)
                if palette:
                    palettes.add(palette)
        except (OSError, ValueError, IndexError, KeyError):
            continue
    # ШЕСТЬ СТАРТОВЫХ ГЕРОЕВ. «Новая игра» даёт выбрать одного из них
    # (VA 0x4387CC читает запись героя из GAME.<номер>), и палитры у них
    # свои — 70, 28, 31, 34. Ни в одной расстановке карт они не встречаются,
    # поэтому без этой добавки выбранный герой оставался без раскраски.
    for index in range(6):
        try:
            from konung2.gamefile import hero_stats
            palette = int(hero_stats(index).get("palette", 0) or 0)
            if palette:
                palettes.add(palette)
        except (OSError, ValueError, IndexError, KeyError, AssertionError):
            continue
    return palettes


def _hero_rules() -> dict[str, Any]:
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
            # Начальное состояние трёхсот квестов — хвост QUESTS.RES, тот же
            # блок, что движок держит в 0x6A50E8 и пишет в сейв (0x423CB8).
            "quests": _quest_state(),
            "cells": cell_rules(),
            "creatures": creature_rules(),
            # Глобальная карта: сетка 24x32 из exe, туман, значки локаций
            # и проходимость (konung2/worldmap.py, VA 0x4277F4).
            "world_map": worldmap_rules(),
            # Инвентарь юнита: пять слотов экипировки и мешок на 42 ячейки
            # (смещения полей — konung2/items.py, VA 0x4129AB и 0x4394BA).
            "inventory": {
                "policy": "konung2_exe_0x4394BA_0x4129AB",
                "slots": dict(SLOT_FIELDS),
                "bag_slots": BAG_SLOTS,
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
            # доля клетки за такт по походкам (VA 0x41615A и 0x416C2C)
            "gait_cell_fraction": {str(k): v for k, v in GAIT_CELL_FRACTION.items()},
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
        "format": 4,
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

CREATURE_POSES = {"stand": 0, "walk": 1, "hit": 2, "death_1": 3, "attack": 5}


def _export_creatures(root: Path, wanted) -> dict[str, Any]:
    """Кадры тварей: свой набор на породу и на масть.

    Человек собирается из слоёв, а тварь рисуется целым набором из
    OBJECTS.RES (записи 0…29). Набор выбирает байт unit+0xFC, масть —
    палитра unit+0x2E; см. konung2/creatures.py.
    """
    from konung2.creatures import CreatureRes, DIRECTIONS
    from konung2.res import read_palettes
    if not wanted:
        return {}
    res = CreatureRes.from_game()
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
        try:
            table = res.animations(body)
            frames = res.frames(body)
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
            sprite, dx, dy = res.decode(body, number, palette=palette)
            if sprite is None:
                return None
            key = f"c{body}p{palette_index}"
            shot = {**sheets.add(sprite, key), "offset_x": dx, "offset_y": dy}
            # Тень — отдельная МАСКА со своим смещением, и объявлена она не у
            # каждого кадра (в дескрипторе тогда стоит −1). Палитра ей не
            # нужна: маска чёрная, поэтому она общая на все масти породы.
            shadow_key = (body, number)
            if shadow_key not in shadow_cache:
                mask, sdx, sdy = res.decode(body, number, shadow=True)
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
    return {"sheets": sheets.flush(), "sets": creatures}


def _export_hero(root: Path, equipment_layers: dict[int, list[int]] | None = None,
                 body_palettes: set[int] | None = None,
                 body_shapes: set[int] | None = None,
                 body_pairs: set[tuple[int, int]] | None = None,
                 reuse: Path | None = None) -> dict[str, Any]:
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
        return {**frames, **_hero_rules()}

    heroes = HeroesRes.from_game()
    palette = read_palettes()[0]
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
        if frames:
            body_layers[str(body)] = {"layer": BODY_LAYER_BASE + body, "frames": frames}

    # ФОРМА В СВОЕЙ ПАЛИТРЕ. Движок ставит палитру юнита и уже ею рисует слой
    # тела (VA 0x425DB4), то есть форма и цвет независимы. Ключ «1:70» —
    # форма 1 в палитре 70; ключ без палитры остался набором по умолчанию,
    # чтобы старые паки продолжали работать.
    for body, palette_index in sorted(body_pairs or ()):
        if not body:
            continue
        frames = {}
        for record in sorted(cache):
            sprite, dx, dy = heroes.decode_layer(
                record, layer=BODY_LAYER_BASE + body,
                palette=palettes[palette_index % len(palettes)])
            if sprite is None:
                continue
            frames[str(record)] = {
                **sheets.add(sprite, f"body{body}pal{palette_index}"),
                "offset_x": dx, "offset_y": dy}
        if frames:
            body_layers[f"{body}:{palette_index}"] = {
                "layer": BODY_LAYER_BASE + body,
                "palette": palette_index, "frames": frames}

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
            слоты = {json.dumps(equipment[f"{layer}:{p}"]["frames"].get(
                next(iter(equipment[f"{layer}:{p}"]["frames"]), ""), None),
                sort_keys=True) for p in indices}
            if len(слоты) == 1:
                print(f"ВНИМАНИЕ: слой {layer} в палитрах {indices} дал "
                      f"одинаковые кадры — палитра не применилась")

    frames = {
        "id": "hero",
        # Листы — это и есть «арена»: клиент тянет их и режет по
        # прямоугольникам, а не запрашивает файл на каждый кадр.
        "sheets": sheets.flush(),
        "animations": animations,
        "equipment": equipment,
        "bodies": bodies,
        "body_layers": body_layers,
    }

    # Рядом с кадрами кладём их «паспорт»: следующая сборка с тем же
    # HEROES.RES и тем же набором слоёв возьмёт всё готовым.
    _write_json(root / out_dir / "index.json",
                {"signature": signature, "frames": frames})
    return {**frames, **_hero_rules()}


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


def _add_building_states(buildings: list[dict[str, Any]],
                         settlement: dict[str, Any] | None,
                         assets: _AssetExporter) -> None:
    """Дать постройке картинки всех её состояний.

    Состояние — не значок, а ступень: движок рисует постройку картинкой
    ``спрайт вида + состояние`` (VA 0x4171CC), и каждому виду отведено семь
    подряд идущих ресурсов — стройка, готово, пожар, пепелище. В карте
    лежит ресурс той ступени, на которой постройка сейчас, поэтому соседние
    берутся отсчётом от него. Смещения кадров у всех семи одни и те же —
    они и в заголовке карты, и в самом ресурсе совпадают.
    """
    from konung2.buildings import STATE_SPRITES
    entries = {entry["object"]: entry for entry in (settlement or {}).get("buildings", [])
               if entry.get("built")}
    for document in buildings:
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
    if isinstance(entity, Building):
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
    kn2 = KN2Map.pack(str(source), number)
    # ИМЯ ЛОКАЦИИ — КАНОННОЕ, из таблицы имён exe, а не из проекта. В
    # project/maps/*/map.json имя можно переписать под свои опыты, и такое
    # имя утекало в игру: у карты 32 там стояла наша тестовая «Новая Весь»
    # вместо «Местность у лесной просеки», и она показывалась игроку при
    # случайной встрече. Имя из проекта остаётся запасным — для карт,
    # которых в таблице нет.
    name = str(_canon_map_name(number) or metadata.get("name") or f"Map {number}")

    # Модель мира собирается один раз и дальше только сериализуется: правила
    # (что прячет крышу, что не темнеет, где проходимо) живут в konung2.world,
    # а не расползаются по сборщику и клиенту.
    world = MapModel.from_kn2(kn2, number, assets.objects)
    scenario = _export_scenario(source, world, root, hero, number)

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
    underlay_scroll = not bool(underlay_mask[0] & 0x80) if underlay_mask else False
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

    buildings = [_serialize_entity(entity, assets) for entity in world.buildings]
    # Наборы тварей теперь общие на весь пак и лежат в shared.json — здесь
    # их больше нет (см. _creature_sets).
    _add_building_states(buildings, scenario.get("village"), assets)
    props = [_serialize_entity(entity, assets) for entity in world.props]
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
            "underlay": {
                "policy": "konung2_exe_0x428505_0x4288D4",
                "tile": underlay_tile or None,
                "visual": underlay_visual,
                "cell_size": 256,
                "cells": underlay_cells,
            },
            "blocked": [[cell.row, cell.col] for cell in world.terrain.blocked],
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
        "audio": audio_assets.map_audio_block(number, audio),
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


def _export_scenario(source: Path, world: MapModel, root: Path,
                     hero_records: dict[str, Any] | None = None,
                     number: int | None = None) -> dict[str, Any]:
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
            # рисуется вокруг круга выделения (0x424514, 0x424FD8)
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
            "world_markers": {
                str(location): {**marker,
                                **(interface_sprite(marker["sprite"]) or {})}
                for location, marker in world_markers().items()
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
            "portraits": {str(face): interface_sprite(PORTRAIT_BASE + face)
                          for face in sorted(_faces_in_use(maps=[number] if number else []))},
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
            # оружия: 166 клинок, 154 топор, 163 мешочек (VA 0x43BBC4)
            "ground_sprite": item.ground,
            "ground": interface_sprite(item.ground),
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
            for pile in ground_items(number, game_world):
                # Куча внутри объекта достаётся обыском его самого, а не
                # лежит на виду — на карту кладём только напольные.
                if not pile["on_floor"]:
                    continue
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
                if not names and not pile["money"]:
                    continue
                cell = Cell(pile["row"], pile["col"])
                if not world.terrain.passable(cell):
                    continue
                anchor = cell.anchor()
                out.append({
                    "id": f"pile_{pile['index']}",
                    "item": names[0] if names else None,
                    "items": names,
                    # экземплярные крепость/чары/отрава вещей кучи (В10)
                    "details": details,
                    "money": pile["money"],
                    "cell": {"row": cell.row, "col": cell.col},
                    "position": {"x": anchor.x, "y": anchor.y},
                })
        except (OSError, ValueError, IndexError, KeyError):
            pass
        return out

    loot_by_world = {str(game_world): [*loot, *piles_of(game_world)]
                     for game_world in range(6)}
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
        # Настоящие жители карты из GAME.0 — с именами, местом, характеристиками
        # и снаряжением. Они мирные: сторона у них своя (55 у Черного Бора),
        # а нападать первыми в разборе движка мы правила пока не нашли.
        if number is not None:
            try:
                from konung2.gamefile import map_units
                residents = map_units(number, game_world)
            except (OSError, ValueError, IndexError):
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
                         if not _in_player_party(entry.get("index"), game_world)]
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
                cell = _spawn_cell(world, resident)
                if cell is None:
                    continue
                anchor = cell.anchor()
                current = resident.get("current", {})
                # Разговор: номер диалога лежит в юните (+0xF2), сам диалог — в
                # QUESTS.RES деревом узлов (konung2/quests.py).
                talk = None
                if resident.get("dialog", 0xFF) != 0xFF:
                    try:
                        from konung2.quests import Dialogs
                        talk = Dialogs.from_game().tree(resident["dialog"])
                    except (OSError, ValueError, IndexError, struct.error):
                        talk = None
                units.append({
                    "id": f"unit_{resident['index']}",
                    "name": resident["name"],
                    # Рабочие места жителя: по ним он и ходит по деревне
                    # (VA 0x412C0C), а не стоит столбом.
                    "workplaces": resident.get("workplaces") or [],
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
                    "speed": 2,
                    "sight_cells": 10,
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

    units_by_world = {index: residents_of(index) for index in range(6)}
    units = list(units_by_world.get(0, []))

    # Расстановка из scenario.json общая для всех миров: она наша, а не из
    # GAME.x, и добавляется поверх любого набора жителей.
    scenario_from = len(units)
    for entry in document.get("units", []):
        equipment = {}
        for slot, name in (entry.get("equipment") or {}).items():
            item = resolve(name)
            equipment[slot] = scenario_item(item, f"unit:{entry['id']}:{slot}")
        units.append({
            "id": entry["id"],
            "name": entry.get("name") or entry["id"],
            "palette": int(entry.get("palette", 0)),
            # Характеристики — поля юнита движка (+0x4E здоровье, +0x1F
            # точность, +0xCD стойкость, +0xD1 выносливость, +0xF4 броня);
            # значения приходят из расстановки, потому что настоящие лежат
            # в состоянии игры, а не в exe.
            "stats": {key: int(value)
                      for key, value in (entry.get("stats") or {}).items()},
            "speed": int(entry.get("speed", 2)),
            "sight_cells": int(entry.get("sight_cells", 10)),
            "equipment": equipment,
            **place(entry),
        })
    for entries in units_by_world.values():
        entries.extend(units[scenario_from:])

    # Выходы с карты: прямоугольник в клетках переводим в мировые
    # координаты, чтобы клиенту было чем ловить героя.
    exits = []
    if number is not None:
        try:
            from konung2.gamefile import map_exits
            found = map_exits(number)
        except (OSError, ValueError, IndexError):
            found = []
        for door in found:
            top_left = Cell(door["row1"], door["col1"]).anchor()
            bottom_right = Cell(door["row2"], door["col2"]).anchor()
            exits.append({**door,
                          "left": min(top_left.x, bottom_right.x),
                          "right": max(top_left.x, bottom_right.x),
                          "top": min(top_left.y, bottom_right.y),
                          "bottom": max(top_left.y, bottom_right.y)})

    # События (рейды) этой карты: в стартовом мире они ещё не запущены,
    # но условия разговоров про них спрашивают.
    events = []
    if number is not None:
        try:
            from konung2.gamefile import map_events
            events = map_events(number)
        except (OSError, ValueError, IndexError):
            events = []

    # ОТРЯДЫ КАРТЫ. Враждебность в движке принадлежит отряду, а не юниту:
    # один проход по отрядам (VA 0x415B20) смотрит их флаги и зону и решает,
    # объявлять ли бой. Сторона юнита (+0x1B) равна номеру отряда, поэтому
    # клиенту хватает этого списка, чтобы связать зверя с его стаей.
    warbands = []
    if number is not None:
        try:
            from konung2.gamefile import map_parties
            warbands = map_parties(number)
        except (OSError, ValueError, IndexError):
            warbands = []

    # Поселение карты: постройки, люди и казна (запись 0x4A1 байт).
    settlement = None
    if number is not None:
        try:
            from konung2.gamefile import village
            settlement = village(number)
        except (OSError, ValueError, IndexError):
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
        try:
            import struct as _struct
            from konung2.gamefile import T_PARTIES, workplaces
            from konung2.paths import game_file as _game_file
            with open(_game_file("GAME.0"), "rb") as stream:
                blob = stream.read()
            for party_index in range(T_PARTIES.count):
                record = blob[T_PARTIES.offset + party_index * T_PARTIES.size:][:T_PARTIES.size]
                if _struct.unpack_from("<H", record, 0x08)[0] != number:
                    continue
                places = workplaces(record)
                if not places:
                    continue
                if settlement is None:
                    settlement = {}
                settlement["workplaces"] = places
                break
        except (OSError, ValueError, IndexError, KeyError):
            pass

    # Кого встретим в пути по глобальной карте (VA 0x4360A8). Считается
    # здесь, а не в сборке карты, потому что снаряжение встречных должно
    # попасть в тот же список предметов, что и у жителей.
    encounters = _encounter_roster(resolve, remember)

    return {
        "village": settlement,
        "events": events,
        "exits": exits,
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
        "loot_by_world": loot_by_world,
        "units": units,
        # Жители по мирам: клиент берёт набор ВЫБРАННОГО героя, иначе на
        # карте появляется двойник (см. residents_of выше). Расстановка из
        # scenario.json общая и добавляется поверх каждого набора.
        "units_by_world": {str(world): entries
                           for world, entries in units_by_world.items()},
        "warbands": warbands,
    }


def _faces_in_use(world: int = 0, maps: Iterable[int] = ()) -> set[int]:
    """Лица, которые понадобятся: свой отряд, жители карт и все шесть героев."""
    faces = {0}
    try:
        from konung2.gamefile import map_units, party
        for member in party(0, world).get("members", []):
            faces.add(int(member.get("face", 0)))
        for number in maps:
            for resident in map_units(number, world):
                faces.add(int(resident.get("face", 0)))
    except (OSError, ValueError, IndexError):
        pass
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


def _hero_party(world: int = 0) -> dict[str, Any] | None:
    """Отряд игрока из стартового мира: спутники и вместимость."""
    try:
        from konung2.gamefile import party
        result = party(0, world)
        # В GAME.x слоты ссылаются на экземпляры, чей байт +3 содержит
        # канонический класс. Имена не уникальны и в runtime не годятся.
        for member in result.get("members", []):
            equipment_classes = member.get("equipment_classes") or {}
            equipment_records = member.get("equipment_item_records") or {}
            member["equipment"] = {
                slot: (_game_item_ref(index, equipment_records.get(slot), world)
                       if index is not None else None)
                for slot, index in equipment_classes.items()
            }
            bag_classes = member.get("bag_classes") or []
            bag_records = member.get("bag_item_records") or []
            member["bag"] = [
                (_game_item_ref(index,
                                bag_records[at] if at < len(bag_records) else None,
                                world)
                 if index is not None else None)
                for at, index in enumerate(bag_classes)
            ]
            second_classes = member.get("second_classes") or {}
            second_records = member.get("second_item_records") or {}
            member["second"] = {
                slot: (_game_item_ref(index, second_records.get(slot), world)
                       if index is not None else None)
                for slot, index in second_classes.items()
            }
            # Второй набор в runtime является продолжением equipment.
            member["equipment"].update(member["second"])
            member["equipment_details"] = {
                **(member.get("equipment_details") or {}),
                **(member.get("second_details") or {}),
            }
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


def _hero_template(index: int = 0) -> dict[str, Any] | None:
    """Настоящий герой из стартового мира GAME.<index>.

    Характеристики, навыки, здоровье, свободный опыт и снаряжение — не наши
    числа, а запись юнита №0 из GAME.x (konung2/gamefile.py). Именно эти
    файлы, а не NEWHERO.RES, держат стартовое состояние: в NEWHERO лежит
    только картинка экрана выбора героя.
    """
    try:
        from konung2.gamefile import hero_stats
        stats = hero_stats(index)
    except (OSError, AssertionError, ValueError):
        return None
    equipment = {
        slot: (_game_item_ref(
            class_number,
            (stats.get("equipment_item_records") or {}).get(slot), index)
               if class_number is not None else None)
        for slot, class_number in stats["equipment_classes"].items()
    }
    equipment.update({
        slot: (_game_item_ref(
            class_number,
            (stats.get("second_item_records") or {}).get(slot), index)
               if class_number is not None else None)
        for slot, class_number in (stats.get("second_classes") or {}).items()
    })
    bag_records = stats.get("bag_item_records") or []
    bag = [
        (_game_item_ref(class_number,
                        bag_records[at] if at < len(bag_records) else None,
                        index)
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
        "party": _hero_party(index),
    }


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


def _collect_files(root: Path) -> tuple[PackedFile, ...]:
    result = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if relative in (PACK_MARKER, "manifest.json"):
            continue
        result.append(PackedFile(relative, path.stat().st_size, _sha256(path)))
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



def _in_player_party(index: int | None, world: int = 0) -> bool:
    """Принадлежит ли юнит отряду игрока в этом мире.

    Запись отряда 0 владеет непрерывным срезом массива юнитов: первый номер
    в +0x00, длина в +0x1C. Это герой и его спутники — на карту их ставит
    спавн отряда, и в списке жителей им делать нечего.
    """
    if index is None:
        return False
    try:
        from konung2.gamefile import T_PARTIES, game_file as source
        with open(source(f"GAME.{world}"), "rb") as stream:
            data = stream.read()
    except (OSError, ValueError):
        return False
    record = data[T_PARTIES.offset:T_PARTIES.offset + T_PARTIES.size]
    first = struct.unpack_from("<H", record, 0x00)[0]
    count = record[0x1C]
    return first <= int(index) < first + max(0, count)

def _export_creation(root: Path) -> dict[str, Any]:
    """Экран создания героя: фон, шесть портретов и разметка щелчков.

    Картинки — из NEWHERO.RES (см. konung2/res.py: шестнадцатибитный RLE,
    формат сходится до последнего байта). Разметка — из exe: 91
    прямоугольник по 0x461D44 и три точки под кнопки и портрет.
    """
    from PIL import Image

    from konung2.exetables import va_to_foff
    from konung2.res import newhero_blocks, newhero_sprite

    folder = root / "assets" / "creation"
    folder.mkdir(parents=True, exist_ok=True)

    def save(index: int, name: str) -> dict[str, Any] | None:
        shot = newhero_sprite(index)
        if not shot:
            return None
        width, height, pixels = shot
        picture = Image.new("RGBA", (width, height))
        picture.putdata(pixels)
        relative = Path("assets") / "creation" / f"{name}.png"
        picture.save(str(root / relative))
        return {"path": relative.as_posix(), "width": width, "height": height}

    blocks = newhero_blocks()
    background = save(0, "background") if blocks else None
    portraits = [save(1 + index, f"hero_{index}") for index in range(6)
                 if 1 + index < len(blocks)]

    with open(game_file("konung2.exe"), "rb") as stream:
        blob = stream.read()
    at = va_to_foff(CREATION_RECTS_VA)
    rects: list[list[int]] = []
    while True:
        x1, y1, x2, y2 = struct.unpack_from("<4i", blob, at + len(rects) * 16)
        if x1 == -1:
            break
        rects.append([x1, y1, x2, y2])

    def point(va: int) -> list[int]:
        return list(struct.unpack_from("<2i", blob, va_to_foff(va)))

    return {
        "screen": {"width": 1024, "height": 768},
        "background": background,
        "portraits": [shot for shot in portraits if shot],
        "rects": rects,
        "codes": CREATION_CODES,
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


def _quest_state() -> dict[str, Any]:
    """Начальное состояние квестов — хвост QUESTS.RES.

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
    from konung2.quests import Dialogs, STATE_OFF, STATE_SIZE
    empty = {"flags": [], "journal": [], "text": {}}
    try:
        dialogs = Dialogs.from_game()
    except OSError:
        return empty
    block = dialogs.data[STATE_OFF:STATE_OFF + STATE_SIZE]
    if len(block) < STATE_SIZE:
        return empty
    words = struct.unpack(f"<{STATE_SIZE // 4}I", block)
    journal, text = [], {}
    for index, word in enumerate(words):
        phrase = (word >> 16) & 0xFFFF
        if phrase == 0xFFFF:
            journal.append(-1)
            continue
        try:
            line = dialogs.phrase(phrase)["text"]
        except (IndexError, ValueError):
            journal.append(-1)
            continue
        if line.startswith("MAP="):     # скрипт-команда, не текст задания
            journal.append(-1)
            continue
        journal.append(phrase)
        text[str(index)] = line
    return {
        "flags": [word & 0xFF for word in words],
        "journal": journal,
        "text": text,
        "known_bit": 0x80,
        "approach_bit": 0x01,
        # окно журнала: шаг строки и нижняя граница (0x42A8F4)
        "line_step": 6,
        "bottom": 0x251,
    }
