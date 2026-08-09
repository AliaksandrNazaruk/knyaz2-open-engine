# -*- coding: utf-8 -*-
"""
konung2 — библиотека для чтения и записи файлов игры «Князь 2: Кровь Титанов».

Главный принцип: любой распакованный ресурс должен собираться обратно
БАЙТ В БАЙТ. Всё, что ещё не расшифровано, сохраняется как raw-hex, поэтому
неполное знание формата никогда не приводит к потере данных.
"""
from .paths import GAME_DIR, PROJECT_DIR, BUILD_DIR, game_file, project_path
from .kn2 import KN2Map
from .gamefile import GameWorld
from .quests import QuestsFile
from .exetables import ExeTables

__all__ = [
    'GAME_DIR', 'PROJECT_DIR', 'BUILD_DIR', 'game_file', 'project_path',
    'KN2Map', 'GameWorld', 'QuestsFile', 'ExeTables',
]
__version__ = '0.1.0'
