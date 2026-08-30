# -*- coding: utf-8 -*-
"""Сюжет как исходники: .QST ↔ JSON (EDITOR_VISION E3).

Авторский конвейер: 156 файлов .QST (корень KONUNG2.QST: голоса,
токены, #include диалогов) → M_QUEST.exe → QUESTS.RES. Здесь —
двусторонний конвертер поверх той же грамматики (дока QUEST.TXT):

    {SCRIPT=Имя [комментарий]
      {SWITCH=Имя CASE=(условие) Цель ... }        условный переключатель
      {SECTION=Имя
        {REPLY [DO=<действия>] {TEXT[=голос] ...текст... } ... }
        {ANSWER [IF=(условие)] [DO=...] GOTO=Цель {TEXT ... } } ...
      }
    }

Имя * — начало диалога; GOTO=END_OF_DIALOG — конец; цель @Имя — переход
в чужой скрипт. Условия: <[!][?]имя[:арг]> через & и |; действия —
последовательность <...>; +ТОКЕН/-ТОКЕН правят квестовые переменные.

ROUND-TRIP КАК У МИРОВ: каждый элемент несёт `raw` — нетронутый рендер
отдаёт файл байт-в-байт; правленый узел сериализуется канонически, и
арбитром остаётся M_QUEST: собранный из перерендеренных исходников
QUESTS.RES обязан быть побайтово равен эталону (закреплено тестом).
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

#: Родная посылка сообщества — ЧИТАЕМ, никогда не пишем.
QUESTS_DIR = (Path(__file__).resolve().parents[1] / "project" / "community"
              / "k2_tools" / "qcompiler" / "KONUNG2" / "QUESTS")
#: Исходники сюжета проекта (экспорт и правки редактора).
STORY_DIR = Path(__file__).resolve().parents[1] / "project" / "story"

END = "END_OF_DIALOG"


# ── разбор ───────────────────────────────────────────────────────────────

def _blocks(text: str, at: int = 0):
    """Верхнеуровневые блоки {…} с позициями; скобки в текстах реплик
    не встречаются (проверено балансом по всем 156 файлам)."""
    out = []
    i = at
    while True:
        start = text.find("{", i)
        if start < 0:
            break
        depth = 0
        j = start
        while j < len(text):
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        out.append((start, j + 1))
        i = j + 1
    return out


_HEAD = re.compile(r"^\{(\w+)(?:=([^\s{}]*))?")


def _head(block: str):
    m = _HEAD.match(block)
    return (m.group(1), m.group(2) or "") if m else ("", "")


def _texts_of(block: str) -> list[dict]:
    """{TEXT[=голос] …} внутри блока (реплика может нести варианты)."""
    body = block[block.find("{") + 1:block.rfind("}")]
    out = []
    for a, b in _blocks(body):
        kind, value = _head(body[a:b])
        if kind != "TEXT":
            continue
        inner = body[a:b]
        text = inner[inner.find("\n") + 1:inner.rfind("}")]
        out.append({"voice": value or None, "text": text.strip("\n")})
    return out


_ATTRS = re.compile(r"(IF|DO|GOTO)=(\([^()]*(?:\([^()]*\)[^()]*)*\)|\S+)")


def _attrs(header: str) -> dict:
    return {m.group(1).lower(): m.group(2) for m in _ATTRS.finditer(header)}


def parse_file(text: str, name: str = "?") -> dict:
    """Файл .QST → элементы в исходном порядке (порядок держит raw)."""
    items = []
    cursor = 0
    for a, b in _blocks(text):
        gap = text[cursor:a]
        if gap.strip():
            items.append({"kind": "plain", "raw": gap})
        elif gap:
            items.append({"kind": "gap", "raw": gap})
        raw = text[a:b]
        kind, value = _head(raw)
        if kind == "TOKEN":
            texts = _texts_of(raw)
            items.append({"kind": "token", "name": value,
                          "text": texts[0]["text"] if texts else None,
                          "raw": raw})
        elif kind == "SCRIPT":
            items.append(_parse_script(raw))
        else:
            items.append({"kind": "block", "raw": raw})
        cursor = b
    tail = text[cursor:]
    if tail:
        items.append({"kind": "gap" if not tail.strip() else "plain",
                      "raw": tail})
    return {"file": name, "items": items}


def _parse_script(raw: str) -> dict:
    header_line = raw[:raw.find("\n")]
    name = _head(raw)[1]
    body = raw[raw.find("\n") + 1:raw.rfind("}")]
    nodes = []
    for a, b in _blocks(body):
        chunk = body[a:b]
        kind, value = _head(chunk)
        if kind == "SWITCH":
            cases = [{"cond": m.group(1), "target": m.group(2)}
                     for m in re.finditer(
                         r"CASE=(\([^)]*\))\s+(\S+)", chunk)]
            nodes.append({"type": "switch", "name": value,
                          "cases": cases, "raw": chunk})
        elif kind == "SECTION":
            nodes.append(_parse_section(chunk))
        else:
            nodes.append({"type": "block", "raw": chunk})
    return {"kind": "script", "name": name, "header": header_line,
            "nodes": nodes, "raw": raw}


def _parse_section(raw: str) -> dict:
    name = _head(raw)[1]
    body = raw[raw.find("\n") + 1:raw.rfind("}")]
    reply = None
    answers = []
    for a, b in _blocks(body):
        chunk = body[a:b]
        kind, _ = _head(chunk)
        header = chunk[:chunk.find("\n")]
        fields = _attrs(header)
        if kind == "REPLY":
            reply = {"do": fields.get("do"), "texts": _texts_of(chunk)}
        elif kind == "ANSWER":
            answers.append({"cond": fields.get("if"),
                            "do": fields.get("do"),
                            "target": fields.get("goto") or END,
                            "texts": _texts_of(chunk)})
    return {"type": "section", "name": name, "reply": reply,
            "answers": answers, "raw": raw}


# ── обратная сериализация ────────────────────────────────────────────────

def render_file(doc: dict) -> str:
    """Элементы → текст .QST. Нетронутые узлы (raw на месте) пишутся
    байт-в-байт; правленые — канонической формой."""
    out = []
    for item in doc["items"]:
        if item["kind"] == "script":
            out.append(_render_script(item))
        elif item.get("raw") is not None:
            out.append(item["raw"])
        elif item["kind"] == "token":
            out.append(_render_token(item))
    return "".join(out)


def _render_token(t: dict) -> str:
    if t.get("text"):
        return "{TOKEN=%s\n {TEXT\n%s\n }\n}\n" % (t["name"], t["text"])
    return "{TOKEN=%s\n}\n" % t["name"]


def _render_script(s: dict) -> str:
    if s.get("raw") is not None and not s.get("dirty"):
        return s["raw"]
    head = s.get("header") or ("{SCRIPT=%s" % s["name"])
    lines = [head, ""]
    for node in s["nodes"]:
        if node.get("raw") is not None and not node.get("dirty"):
            lines.append(node["raw"])
        elif node["type"] == "switch":
            lines.append(_render_switch(node))
        elif node["type"] == "section":
            lines.append(_render_section(node))
        lines.append("")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _render_switch(node: dict) -> str:
    lines = [" {SWITCH=%s" % node["name"]]
    for case in node["cases"]:
        lines.append("  CASE=%s %s" % (case["cond"], case["target"]))
    lines.append(" }")
    return "\n".join(lines)


def _render_text(t: dict, indent: str) -> str:
    voice = "=%s" % t["voice"] if t.get("voice") else ""
    return "%s{TEXT%s\n%s\n%s}" % (indent, voice, t["text"], indent)


def _render_section(node: dict) -> str:
    lines = [" {SECTION=%s" % node["name"]]
    reply = node.get("reply")
    if reply:
        do = " DO=%s" % reply["do"] if reply.get("do") else ""
        lines.append("  {REPLY%s" % do)
        for t in reply.get("texts") or []:
            lines.append(_render_text(t, "   "))
        lines.append("  }")
    for ans in node.get("answers") or []:
        fields = ""
        if ans.get("cond"):
            fields += " IF=%s" % ans["cond"]
        if ans.get("do"):
            fields += " DO=%s" % ans["do"]
        fields += " GOTO=%s" % (ans.get("target") or END)
        lines.append("  {ANSWER%s" % fields)
        for t in ans.get("texts") or []:
            lines.append(_render_text(t, "   "))
        lines.append("  }")
    lines.append(" }")
    return "\n".join(lines)


# ── валидатор достижимости ───────────────────────────────────────────────

_COND_NAMES = re.compile(r"<(!?)(\??)([\w:А-Яа-яЁё_]+)>")


def _tokens_in_cond(cond: str | None):
    """Имена квестовых переменных в условии (встроенные ?ф-ции — мимо)."""
    for m in _COND_NAMES.finditer(cond or ""):
        if not m.group(2):                     # без ? — переменная
            yield m.group(3).split(":")[0]


def _tokens_in_do(do: str | None):
    for m in re.finditer(r"<([+-])([\w А-Яа-яЁё_]+)>", do or ""):
        yield m.group(2)


def validate_dialog(script: dict) -> dict:
    """Достижимость от * и висячие цели одного диалога."""
    names = {n["name"]: n for n in script["nodes"]
             if n.get("type") in ("switch", "section")}
    edges: dict[str, list[str]] = {}
    for n in script["nodes"]:
        if n.get("type") == "switch":
            edges[n["name"]] = [c["target"] for c in n["cases"]]
        elif n.get("type") == "section":
            edges[n["name"]] = [a.get("target") or END
                                for a in n.get("answers") or []]
    errors, troubles = [], []
    if "*" not in names:
        errors.append("нет стартовой позиции * — диалог не открыть")
    # @Имя — ГЛОБАЛЬНЫЙ вход: в такие секции прыгают из чужих скриптов
    # (COM_* — библиотеки общих кусков), от локального * они и не должны
    # достигаться. Каждый @-вход — дополнительный старт обхода.
    reached = set()
    stack = [name for name in names if name.startswith("@")]
    if "*" in names:
        stack.append("*")
    while stack:
        name = stack.pop()
        if name in reached:
            continue
        reached.add(name)
        for target in edges.get(name, []):
            if target == END or target.startswith("@"):
                continue
            if target not in names:
                errors.append(f"«{name}» ведёт в несуществующую "
                              f"позицию «{target}»")
            else:
                stack.append(target)
    for name, node in names.items():
        if name not in reached:
            troubles.append(f"позиция «{name}» недостижима от старта")
        if node.get("type") == "section" and not node.get("answers"):
            errors.append(f"секция «{name}» без единого ответа — "
                          f"из неё не выйти")
    return {"errors": errors, "warnings": troubles,
            "reachable": sorted(reached),
            "nodes": len(names)}


#: Встроенные семейства переменных компилятора: живут вне {TOKEN=…}.
#: NPC_QV<n> — квестовая переменная СОБЕСЕДНИКА (по одной на юнита).
_BUILTIN_TOKEN = re.compile(r"^NPC_QV\d+$")


def validate_story(files: dict[str, dict]) -> dict:
    """Весь сюжет: диалоги, сквозные токены и глобальные @-входы."""
    declared, used = set(), set()
    global_entries, global_targets = set(), set()
    summary = {}
    for file_name, document in files.items():
        for item in document["items"]:
            if item["kind"] == "token":
                declared.add(item["name"])
            elif item["kind"] == "script":
                for node in item["nodes"]:
                    if node.get("name", "").startswith("@"):
                        global_entries.add(node["name"])
                    if node.get("type") == "switch":
                        global_targets.update(
                            c["target"] for c in node["cases"]
                            if c["target"].startswith("@"))
                    elif node.get("type") == "section":
                        global_targets.update(
                            (a.get("target") or END)
                            for a in node.get("answers") or []
                            if (a.get("target") or "").startswith("@"))
                result = validate_dialog(item)
                if result["errors"] or result["warnings"]:
                    summary[f"{file_name}:{item['name']}"] = {
                        "errors": result["errors"],
                        "warnings": result["warnings"]}
                for node in item["nodes"]:
                    if node.get("type") == "switch":
                        for c in node["cases"]:
                            used.update(
                                _tokens_in_cond(c["cond"]))
                    elif node.get("type") == "section":
                        r = node.get("reply") or {}
                        used.update(_tokens_in_do(r.get("do")))
                        for a in node.get("answers") or []:
                            used.update(
                                _tokens_in_cond(a.get("cond")))
                            used.update(
                                _tokens_in_do(a.get("do")))
    return {
        "dialogs": summary,
        "unknown_tokens": sorted(
            name for name in used - declared
            if not _BUILTIN_TOKEN.match(name)),
        "unused_tokens": sorted(declared - used),
        # @-цель без @-определения где-либо — обрыв меж скриптов
        "unknown_globals": sorted(global_targets - global_entries),
        "global_entries": len(global_entries),
        "declared": len(declared),
    }


# ── экспорт и сборка ─────────────────────────────────────────────────────

def load_sources(src: Path | None = None) -> dict[str, dict]:
    """Все .QST посылки (или каталога проекта) разобранными."""
    root = Path(src) if src else QUESTS_DIR
    out = {}
    for file in sorted(root.glob("*.QST")):
        text = file.read_bytes().decode("cp866")
        out[file.name] = parse_file(text, file.name)
    return out


def export_story(out_dir: Path | None = None,
                 src: Path | None = None) -> dict:
    """Посылка → project/story: qst/ (правимая копия исходников,
    cp866 как у компилятора) + files/*.json (разбор) + summary."""
    root = Path(out_dir) if out_dir else STORY_DIR
    (root / "files").mkdir(parents=True, exist_ok=True)
    (root / "qst").mkdir(parents=True, exist_ok=True)
    files = load_sources(src)
    dialog_count = 0
    for name, document in files.items():
        (root / "files" / f"{name}.json").write_text(
            json.dumps(document, ensure_ascii=False, indent=1),
            encoding="utf-8")
        (root / "qst" / name).write_bytes(
            render_file(document).encode("cp866"))
        dialog_count += sum(1 for i in document["items"]
                        if i["kind"] == "script")
    summary = validate_story(files)
    summary["files"] = len(files)
    summary["scripts"] = dialog_count
    (root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1),
        encoding="utf-8")
    return summary


def script_numbers(log_path: Path | None = None) -> dict[str, int]:
    """Имя скрипта -> НОМЕР ДЕРЕВА движка. Нумерацию задаёт порядок
    компиляции, и M_QUEST печатает её в QUESTS.LOG (секция SCRIPTS) —
    берём свежий лог project/story, иначе эталонный из посылки."""
    if log_path is None:
        own = STORY_DIR / "QUESTS.LOG"
        log_path = own if own.is_file() else QUESTS_DIR / "QUESTS.LOG"
    numbers: dict[str, int] = {}
    for line in log_path.read_bytes().decode(
            "cp866", errors="replace").splitlines():
        m = re.match(r"^(\d+)\s+(\S+)", line)
        if m:
            numbers.setdefault(m.group(2), int(m.group(1)))
    return numbers


def main(argv: list[str] | None = None) -> int:
    parsed = argparse.ArgumentParser(prog="konung2-story")
    parsed.add_argument("--out", type=Path, default=None)
    args = parsed.parse_args(argv)
    summary = export_story(args.out)
    print(f"файлов {summary['files']}, диалогов {summary['scripts']}, "
          f"токенов {summary['declared']}; болеющих диалогов "
          f"{len(summary['dialogs'])}, неизвестных токенов "
          f"{len(summary['unknown_tokens'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
