"""Мост DesignAgent: разовые вызовы к открытому файлу Figma.

Брокер моста (designagent-figma) слушает 127.0.0.1:3790; плагин в Figma —
его клиент, а «сессия» — второй клиент. Держать сессию демоном оказалось
вредно: каждая новая регистрация заставляет плагин переспариваться и
ронять запросы. Поэтому здесь один вызов = одно короткое подключение.

Скриншоты пишутся прямо в файл — base64 не попадает в контекст агента.

    python tools/figbridge.py take_screenshot nodeId=1221:41387 \
        scale=1 --save figrefs/loadgame.png
    python tools/figbridge.py list_page_nodes
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys
import time
import uuid
from pathlib import Path

import websockets

BROKER = 'ws://127.0.0.1:3790'
ROOT = Path(__file__).resolve().parents[1]
#: сборка настоящего MCP-сервера моста: брокер сверяет её со своей и уходит
#: в отставку, если сессия «новее» — поэтому берём его же mtime, минус миг
SERVER_JS = Path(
    'C:/Users/User/AppData/Local/Temp/claude/'
    'C--Program-Files--x86--------------------------------02--------2----------------/'
    '2f20b869-86a9-4879-9a79-2cbf71e5519f/scratchpad/'
    'designagent-figma/claude-plugin/mcp/server.js')


def build_stamp() -> int:
    try:
        return int(SERVER_JS.stat().st_mtime * 1000) - 1
    except OSError:
        return 1


async def call(command: str, params: dict, timeout: float) -> dict:
    async with websockets.connect(BROKER, max_size=256 * 1024 * 1024) as ws:
        await ws.send(json.dumps({
            'type': 'register', 'role': 'mcp-server', 'version': 2,
            'buildMtime': build_stamp(), 'sessionId': str(uuid.uuid4()),
            'root': str(ROOT), 'label': 'knyaz2', 'pluginVersion': ''}))
        call_id = str(uuid.uuid4())
        sent = False
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=2)
            except asyncio.TimeoutError:
                if not sent:
                    # пауза перед выстрелом: плагин должен переспариться
                    # на нашу сессию, иначе запрос попадёт под сброс
                    await ws.send(json.dumps({'type': 'request', 'id': call_id,
                                              'command': command, 'params': params}))
                    sent = True
                continue
            msg = json.loads(raw)
            kind = msg.get('type')
            if kind == 'ping':
                await ws.send(json.dumps({'type': 'pong'}))
            elif kind in ('request', 'server_request'):
                # обратный канал (плагин спрашивает про файлы проекта):
                # молчать нельзя — пайринг подвиснет
                await ws.send(json.dumps({
                    'type': 'server_response', 'id': msg.get('id'), 'ok': True,
                    'result': {'exists': False, 'root': str(ROOT),
                               'path': 'DESIGN.md', 'files': []}}))
            elif kind == 'response' and msg.get('id') == call_id:
                return msg
        return {'ok': False, 'error': f'таймаут {timeout}с'}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('command')
    ap.add_argument('params', nargs='*', help='пары вида ключ=значение')
    ap.add_argument('--save', help='куда положить картинку из ответа')
    ap.add_argument('--timeout', type=float, default=60)
    args = ap.parse_args()

    params: dict = {}
    for pair in args.params:
        key, _, value = pair.partition('=')
        if value.lstrip('-').replace('.', '', 1).isdigit():
            value = float(value) if '.' in value else int(value)
        elif value in ('true', 'false'):
            value = value == 'true'
        params[key] = value

    out = asyncio.run(call(args.command, params, args.timeout))
    result = out.get('result') if isinstance(out.get('result'), dict) else out
    if args.save and isinstance(result, dict) and result.get('base64'):
        path = Path(args.save)
        if not path.is_absolute():
            path = ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(result['base64']))
        size = path.stat().st_size
        print(json.dumps({'saved': str(path), 'bytes': size,
                          'width': result.get('width'),
                          'height': result.get('height'),
                          'name': result.get('name')}, ensure_ascii=False))
        return
    text = json.dumps(out, ensure_ascii=False)
    if len(text) > 8000:
        spill = ROOT / 'figrefs' / '_last_reply.json'
        spill.parent.mkdir(parents=True, exist_ok=True)
        spill.write_text(text, 'utf-8')
        print(json.dumps({'spilled': str(spill), 'bytes': len(text)},
                         ensure_ascii=False))
    else:
        print(text)
    if out.get('ok') is False:
        sys.exit(1)


if __name__ == '__main__':
    main()
