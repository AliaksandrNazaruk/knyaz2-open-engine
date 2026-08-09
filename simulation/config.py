# -*- coding: utf-8 -*-
"""Настройки симуляции. Числовых констант в коде систем быть не должно."""
from __future__ import annotations

from dataclasses import dataclass

SIMULATION_TICK_SECONDS: float = 0.25


@dataclass(frozen=True)
class NeedsConfig:
    hunger_per_tick: float = 0.35
    energy_loss_per_tick: float = 0.15
    energy_regain_when_resting: float = 1.5
    starvation_threshold: float = 90.0
    starvation_damage: float = 1.0
    exhaustion_threshold: float = 5.0
    exhaustion_damage: float = 0.5
    max_value: float = 100.0


@dataclass(frozen=True)
class PerceptionConfig:
    sight_radius: int = 9
    #: во сколько раз медленнее стареет знание о неподвижных объектах
    memory_ttl_ticks: int = 400


@dataclass(frozen=True)
class DecisionConfig:
    hunger_search_threshold: float = 30.0
    rest_energy_threshold: float = 25.0
    #: разброс, внутри которого варианты считаются равноценными
    tie_epsilon: float = 0.5
    #: насколько страх отталкивает от источника угрозы
    fear_avoid_distance: int = 4


@dataclass(frozen=True)
class RelationshipConfig:
    min_value: int = -100
    max_value: int = 100
    take_seen_trust: int = -12
    take_seen_hostility: int = 6
    #: во сколько раз сильнее реакция, если наблюдатель голоден
    hungry_multiplier: float = 2.0
    give_trust: int = 20
    give_hostility: int = -8
    threat_fear: int = 15
    hostile_threshold: int = 40
    fear_threshold: int = 40


@dataclass(frozen=True)
class SimulationConfig:
    needs: NeedsConfig = NeedsConfig()
    perception: PerceptionConfig = PerceptionConfig()
    decision: DecisionConfig = DecisionConfig()
    relationships: RelationshipConfig = RelationshipConfig()
    #: расстояние, на котором можно взять/передать предмет
    reach: int = 1


DEFAULT_CONFIG = SimulationConfig()
