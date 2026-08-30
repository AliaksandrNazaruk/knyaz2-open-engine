"""Пакетная съёмка эталонов всех экранов через мост DesignAgent.

Список кадров берётся из .fig (все полноэкранные 1920x1080 в секциях),
каждый снимается вызовом figbridge и ложится в figrefs/<имя>.png.
Уже снятые пропускаются, чтобы прогон можно было продолжить после обрыва.

    python tools/figshots.py --fig "…3.fig"          # снять всё, чего нет
    python tools/figshots.py --fig … --only loadgame # только один
    python tools/figshots.py --list                  # показать план
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import figdump   # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
REFS = ROOT / 'figrefs'
CATALOG = REFS / 'screens.json'


def slug(name: str, section: str) -> str:
    """Имя файла: секция+кадр латиницей, без пробелов и мусора."""
    raw = f'{section}-{name}'.lower()
    raw = raw.replace('ё', 'e')
    raw = re.sub(r'[^a-z0-9]+', '-', raw).strip('-')
    return raw or 'screen'


def catalog(fig: Path) -> list[dict]:
    nodes = figdump.load_nodes(fig)
    by_id = {figdump.node_id(n): n for n in nodes}
    out, seen = [], {}
    for node in nodes:
        if node.get('type') != 'FRAME':
            continue
        size = node.get('size') or {}
        if abs((size.get('x') or 0) - 1920) > 1 or abs((size.get('y') or 0) - 1080) > 1:
            continue
        parent = (node.get('parentIndex') or {}).get('guid') or {}
        pid = f"{parent.get('sessionID')}:{parent.get('localID')}"
        section = by_id.get(pid, {})
        if section.get('type') not in ('SECTION', 'CANVAS'):
            continue
        name = slug(node.get('name') or 'screen', section.get('name') or '')
        seen[name] = seen.get(name, 0) + 1
        if seen[name] > 1:                      # одноимённые кадры в секции
            name = f'{name}-{seen[name]}'
        out.append({'id': figdump.node_id(node), 'file': name,
                    'name': node.get('name'), 'section': section.get('name')})
    out.sort(key=lambda item: item['file'])
    return out


def shoot(item: dict, tries: int = 2) -> bool:
    target = REFS / f"{item['file']}.png"
    for attempt in range(tries):
        done = subprocess.run(
            [sys.executable, str(ROOT / 'tools/figbridge.py'), 'take_screenshot',
             f"nodeId={item['id']}", 'scale=1', '--save', str(target),
             '--timeout', '90'],
            capture_output=True, text=True, encoding='utf-8', errors='replace')
        line = (done.stdout or '').strip().splitlines()[-1] if done.stdout else ''
        if '"saved"' in line and target.exists() and target.stat().st_size > 10_000:
            return True
        if attempt + 1 < tries:
            time.sleep(3)
    print(f"    ! не снялся: {line[:160] or (done.stderr or '')[:160]}")
    return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--fig', default=r'C:\Users\User\Downloads\Game UI Dark fantasy RPG (Community)3.fig')
    ap.add_argument('--only', help='подстрока имени файла эталона')
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--force', action='store_true', help='пересматривать уже снятые')
    args = ap.parse_args()

    REFS.mkdir(exist_ok=True)
    plan = catalog(Path(args.fig))
    CATALOG.write_text(json.dumps(plan, ensure_ascii=False, indent=1), 'utf-8')
    if args.only:
        plan = [item for item in plan if args.only in item['file']]
    if args.list:
        for item in plan:
            print(f"{item['id']:14} {item['file']}")
        print(f'всего: {len(plan)}')
        return

    todo = [item for item in plan
            if args.force or not (REFS / f"{item['file']}.png").exists()]
    print(f'к съёмке: {len(todo)} из {len(plan)}', flush=True)
    good, bad = 0, []
    for index, item in enumerate(todo, 1):
        print(f"[{index}/{len(todo)}] {item['file']} ({item['id']})", flush=True)
        if shoot(item):
            good += 1
        else:
            bad.append(item['file'])
    print(f'снято: {good}, не вышло: {len(bad)}')
    if bad:
        print('  ' + ', '.join(bad))


if __name__ == '__main__':
    main()
