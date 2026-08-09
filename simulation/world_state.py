# -*- coding: utf-8 -*-
"""
Состояние мира: позиции, тела, предметы, знания, отношения.

Мир хранит только состояние. Никаких стадий квестов, флагов «предал» и
прочих готовых сюжетных объяснений здесь нет и быть не должно: история
получается как след последствий, а не как заранее записанный сценарий.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, NamedTuple


class Position(NamedTuple):
    """Клетка сетки. Порядок (строка, столбец) — как в файлах игры."""
    row: int
    col: int

    def neighbours(self) -> list["Position"]:
        return [Position(self.row + dr, self.col + dc)
                for dr in (-1, 0, 1) for dc in (-1, 0, 1) if dr or dc]

    def chebyshev(self, other: "Position") -> int:
        return max(abs(self.row - other.row), abs(self.col - other.col))


class TerrainType(Enum):
    GROUND = 0        # проходимо
    OBSTACLE = 1      # непроходимо и не пропускает взгляд
    VOID = 2          # вне карты


class ItemType(Enum):
    FOOD = 0


class FactType(Enum):
    ITEM_AT = 0          # предмет наблюдался в клетке
    ITEM_TAKEN_BY = 1    # предмет наблюдался в руках у кого-то
    ACTOR_AT = 2         # персонаж наблюдался в клетке
    ITEM_ABSENT = 3      # в клетке предмета не оказалось


@dataclass(frozen=True)
class KnownFact:
    fact_type: FactType
    subject_id: str
    value: object
    observed_tick: int
    confidence: float


@dataclass
class KnowledgeState:
    """Личная картина мира персонажа. Может устаревать и быть неверной."""
    facts: dict[tuple[FactType, str], KnownFact] = field(default_factory=dict)

    def remember(self, fact: KnownFact) -> None:
        self.facts[(fact.fact_type, fact.subject_id)] = fact

    def forget(self, fact_type: FactType, subject_id: str) -> None:
        self.facts.pop((fact_type, subject_id), None)

    def get(self, fact_type: FactType, subject_id: str) -> KnownFact | None:
        return self.facts.get((fact_type, subject_id))

    def by_type(self, fact_type: FactType) -> list[KnownFact]:
        return [f for (t, _), f in self.facts.items() if t == fact_type]


@dataclass
class RelationshipState:
    """Три независимые шкалы: одной «любит — ненавидит» недостаточно."""
    trust: int = 0
    fear: int = 0
    hostility: int = 0


@dataclass
class ActorState:
    """Общая структура для игрока и NPC. Роль различает только источник намерения."""
    actor_id: str
    position: Position

    health: float = 100.0
    energy: float = 100.0
    hunger: float = 0.0

    strength: int = 10
    agility: int = 10

    alive: bool = True
    is_player: bool = False
    current_intention: str | None = None

    knowledge: KnowledgeState = field(default_factory=KnowledgeState)
    relationships: dict[str, RelationshipState] = field(default_factory=dict)

    def relation_to(self, other_id: str) -> RelationshipState:
        return self.relationships.setdefault(other_id, RelationshipState())


@dataclass
class ItemState:
    """Предмет либо лежит на карте, либо у владельца, но не то и другое сразу."""
    item_id: str
    item_type: ItemType
    position: Position | None = None
    owner_id: str | None = None
    nutrition: float = 40.0

    def validate(self) -> None:
        on_map = self.position is not None
        carried = self.owner_id is not None
        if on_map == carried:
            raise InvariantError(
                f'предмет {self.item_id}: position={self.position} owner={self.owner_id} — '
                'должно выполняться ровно одно из двух')


@dataclass
class WorldState:
    tick: int
    width: int
    height: int
    terrain: list[list[TerrainType]]
    actors: dict[str, ActorState] = field(default_factory=dict)
    items: dict[str, ItemState] = field(default_factory=dict)
    random_seed: int = 0

    # --- доступ ---------------------------------------------------------
    def terrain_at(self, pos: Position) -> TerrainType:
        if 0 <= pos.row < self.height and 0 <= pos.col < self.width:
            return self.terrain[pos.row][pos.col]
        return TerrainType.VOID

    def is_passable(self, pos: Position) -> bool:
        return self.terrain_at(pos) is TerrainType.GROUND

    def blocks_sight(self, pos: Position) -> bool:
        return self.terrain_at(pos) is not TerrainType.GROUND

    def actor_at(self, pos: Position) -> ActorState | None:
        for a in self.actors.values():
            if a.alive and a.position == pos:
                return a
        return None

    def items_at(self, pos: Position) -> list[ItemState]:
        return [i for i in self.items.values() if i.position == pos]

    def carried_by(self, actor_id: str) -> list[ItemState]:
        return [i for i in self.items.values() if i.owner_id == actor_id]

    def living_actors(self) -> Iterable[ActorState]:
        return (a for a in self.actors.values() if a.alive)

    def snapshot(self) -> "WorldState":
        """Неизменяемый для систем срез начала тика (глубокая копия)."""
        return copy.deepcopy(self)


class InvariantError(RuntimeError):
    """Нарушен инвариант мира — это ошибка модели, а не игровая ситуация."""


def check_invariants(world: WorldState) -> None:
    for item in world.items.values():
        item.validate()
        if item.owner_id is not None and item.owner_id not in world.actors:
            raise InvariantError(f'предмет {item.item_id} принадлежит неизвестному {item.owner_id}')
        if item.position is not None and world.terrain_at(item.position) is TerrainType.VOID:
            raise InvariantError(f'предмет {item.item_id} вне карты: {item.position}')

    seen: dict[Position, str] = {}
    for actor in world.actors.values():
        if not actor.alive:
            continue
        if not world.is_passable(actor.position):
            raise InvariantError(
                f'{actor.actor_id} стоит в непроходимой клетке {actor.position}')
        if actor.position in seen:
            raise InvariantError(
                f'{actor.actor_id} и {seen[actor.position]} в одной клетке {actor.position}')
        seen[actor.position] = actor.actor_id
        for name, value, hi in (('health', actor.health, 100.0),
                                ('energy', actor.energy, 100.0),
                                ('hunger', actor.hunger, 100.0)):
            if not 0.0 <= value <= hi:
                raise InvariantError(f'{actor.actor_id}: {name}={value} вне диапазона 0..{hi}')
