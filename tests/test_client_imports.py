# -*- coding: utf-8 -*-
"""Импорты клиента: каждое имя должно быть кем-то экспортировано.

Разбор такое НЕ ловит: файл остаётся синтаксически верным, а браузер
падает уже на загрузке с «does not provide an export named». Так однажды
потерялся ``export`` у ``drawObject`` — вставка комментария разрезала
объявление, — и вся страница встала на «Загрузка мира» с пустой консолью.
"""
import re
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "knyaz2" / "web" / "static"

EXPORT_PATTERNS = (
    r"export\s+(?:async\s+)?function\s+(\w+)",
    r"export\s+(?:const|let|var|class)\s+(\w+)",
)
IMPORT_PATTERN = r'import\s*\{([^}]*)\}\s*from\s*"\./([\w.]+)\.js"'
REEXPORT_PATTERN = r"export\s*\{([^}]*)\}"


def _names(block: str) -> list[str]:
    """Имена из фигурных скобок: учитываем `как` и лишние пробелы."""
    out = []
    for part in block.split(","):
        part = part.strip()
        if part:
            out.append(part)
    return out


class ClientImportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.modules = sorted(STATIC.glob("*.js"))
        self.assertGreater(len(self.modules), 20, "модули клиента не найдены")

    def _exports(self) -> dict[str, set[str]]:
        found: dict[str, set[str]] = {}
        for path in self.modules:
            text = path.read_text(encoding="utf-8")
            names: set[str] = set()
            for pattern in EXPORT_PATTERNS:
                names.update(re.findall(pattern, text))
            # реэкспорт `export { a, b as c } from "./x.js"` тоже считается
            for block in re.findall(REEXPORT_PATTERN, text, re.S):
                for part in _names(block):
                    names.add(part.split(" as ")[-1].strip())
            found[path.stem] = names
        return found

    def test_every_import_resolves_to_a_real_export(self) -> None:
        exports = self._exports()
        dangling = []
        for path in self.modules:
            text = path.read_text(encoding="utf-8")
            for block, module in re.findall(IMPORT_PATTERN, text, re.S):
                if module not in exports:
                    continue
                for part in _names(block):
                    name = part.split(" as ")[0].strip()
                    if name and name not in exports[module]:
                        dangling.append(f"{path.name}: «{name}» нет в {module}.js")
        self.assertEqual(dangling, [], "импорт ссылается на несуществующий экспорт")

    def test_import_graph_has_no_cycles(self) -> None:
        """Петля в импортах ломает порядок инициализации модулей."""
        graph = {
            path.stem: set(re.findall(r'from\s+"\./([\w.]+)\.js"',
                                      path.read_text(encoding="utf-8")))
            for path in self.modules
        }
        cycles = []

        def walk(node: str, stack: list[str], seen: set[str]) -> None:
            if node in stack:
                cycles.append(stack[stack.index(node):] + [node])
                return
            if node in seen:
                return
            seen.add(node)
            stack.append(node)
            for other in sorted(graph.get(node, ())):
                if other in graph:
                    walk(other, stack, seen)
            stack.pop()

        for node in sorted(graph):
            walk(node, [], set())
        unique = {tuple(sorted(set(chain))) for chain in cycles}
        self.assertEqual(unique, set(), "в графе импортов есть петля")


if __name__ == "__main__":
    unittest.main()
