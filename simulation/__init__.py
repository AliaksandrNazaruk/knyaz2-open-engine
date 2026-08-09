# -*- coding: utf-8 -*-
"""
Многослойный причинный автомат: мир, где поведение возникает из правил.

Слои: пространство, тело, потребности, восприятие, знания, отношения,
намерения, действия. Каждый слой имеет своё состояние и влияет на соседние.
Сюжетных переключателей и заранее заданных маршрутов здесь нет.
"""
from .config import DEFAULT_CONFIG, SimulationConfig
from .simulation_loop import Simulation, TickReport
from .world_state import (ActorState, ItemState, ItemType, Position, TerrainType,
                          WorldState, check_invariants)

__all__ = ['Simulation', 'TickReport', 'WorldState', 'ActorState', 'ItemState',
           'ItemType', 'Position', 'TerrainType', 'SimulationConfig',
           'DEFAULT_CONFIG', 'check_invariants']
