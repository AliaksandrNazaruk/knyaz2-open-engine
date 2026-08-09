# -*- coding: utf-8 -*-
"""Пути проекта. Меняйте GAME_DIR, если игра установлена в другое место."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

GAME_DIR = os.environ.get(
    'KONUNG2_DIR',
    r"C:\Program Files (x86)\Князь - Коллекционное издание\02. Князь 2 - Кровь Титанов")

PROJECT_DIR = os.path.join(ROOT, 'project')   # редактируемые исходники (текст)
BUILD_DIR = os.path.join(ROOT, 'build')       # собранные файлы игры
BACKUP_DIR = os.path.join(ROOT, 'backup')     # копии оригиналов


def game_file(name):
    return os.path.join(GAME_DIR, name)


def project_path(*parts):
    p = os.path.join(PROJECT_DIR, *parts)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    return p


def build_path(*parts):
    p = os.path.join(BUILD_DIR, *parts)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    return p


def read_game(name):
    with open(game_file(name), 'rb') as f:
        return f.read()
