# -*- coding: utf-8 -*-
"""Соприсутствие: игроки на одной карте видят друг друга.

ЧТО ЭТО И ЧЕГО ЭТО НЕ ЕСТЬ. Сервер здесь — ТУПОЙ РЕТРАНСЛЯТОР. Он не считает
мир, не хранит его и ничего не решает: принял от клиента его собственную позу,
разослал остальным на той же карте. Мир по-прежнему целиком живёт в браузере
у каждого. Поэтому чужой игрок виден, но ни ударить, ни обменяться, ни помешать
он не может — это призрак.

Общий мир (одни и те же жители, лут, лавки) требует сервера, который миром
ВЛАДЕЕТ, и это отдельная большая работа. Здесь её нет намеренно.

ЗАВИСИМОСТЕЙ НЕТ. Рукопожатие и кадры RFC 6455 разобраны вручную, на голом
asyncio: сервер общий с другими службами, и ставить туда пакеты ради одной
игры незачем. Нам нужны только текстовые кадры небольшого размера — этого и
хватает.

    python -m knyaz2.web.presence --host 127.0.0.1 --port 8766
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import struct
import time

#: Волшебная строка рукопожатия (RFC 6455, 1.3).
GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

#: Опкоды кадров.
OP_TEXT, OP_CLOSE, OP_PING, OP_PONG = 0x1, 0x8, 0x9, 0xA

#: Потолки, чтобы одна вкладка не завалила сервер.
MAX_FRAME = 4096            # поза весит десятки байт, тысячи хватит с запасом
MAX_ROOM = 32               # столько призраков на карте ещё осмысленно рисовать
MAX_CLIENTS = 200
IDLE_SECONDS = 90           # молчит дольше — считаем ушедшим

#: Сцены встреч (26…32 и 44…54) у каждого свои: в оригинале это временные
#: карты боя, и делить их не с кем. Соприсутствие только в локациях.
PRIVATE_MAPS = set(range(26, 33)) | set(range(44, 55))


class Client:
    """Одно соединение: кто это, где он и что о нём знают соседи."""

    __slots__ = ("writer", "ident", "room", "state", "seen")

    def __init__(self, writer: asyncio.StreamWriter, ident: str) -> None:
        self.writer = writer
        self.ident = ident
        self.room: int | None = None
        self.state: dict = {}
        self.seen = time.monotonic()


class Relay:
    def __init__(self) -> None:
        self.clients: dict[str, Client] = {}
        self.rooms: dict[int, set[str]] = {}

    # ---- комнаты ----------------------------------------------------------

    def join(self, client: Client, room: int | None) -> None:
        if client.room == room:
            return
        self.leave(client)
        if room is None:
            return
        mates = self.rooms.setdefault(room, set())
        if len(mates) >= MAX_ROOM:
            return                      # комната полна — гость просто не виден
        mates.add(client.ident)
        client.room = room

    def leave(self, client: Client) -> None:
        if client.room is None:
            return
        mates = self.rooms.get(client.room)
        if mates:
            mates.discard(client.ident)
            if not mates:
                self.rooms.pop(client.room, None)
        # Соседям — весть об уходе, иначе призрак застынет на месте навсегда.
        self.send_room(client.room, {"gone": client.ident}, skip=client.ident)
        client.room = None

    def send_room(self, room: int | None, message: dict, skip: str = "") -> None:
        for ident in tuple(self.rooms.get(room, ())):
            if ident == skip:
                continue
            other = self.clients.get(ident)
            if other:
                send(other.writer, message)

    # ---- разбор сообщения клиента ----------------------------------------

    def update(self, client: Client, raw: str) -> None:
        try:
            packet = json.loads(raw)
        except ValueError:
            return
        if not isinstance(packet, dict):
            return
        client.seen = time.monotonic()
        room = packet.get("m")
        room = int(room) if isinstance(room, (int, float)) else None
        if room in PRIVATE_MAPS:
            room = None                 # сцена боя — она у каждого своя
        if room != client.room:
            self.join(client, room)
            # Новичку — все, кто уже здесь: иначе он увидит соседей только
            # когда те шевельнутся.
            for ident in self.rooms.get(client.room, ()):
                if ident == client.ident:
                    continue
                other = self.clients.get(ident)
                if other and other.state:
                    send(client.writer, {"id": ident, "s": other.state})
        # Наружу отдаём ТОЛЬКО известные поля: чужой клиент не должен уметь
        # прислать сюда что угодно и заставить нас это разослать.
        client.state = {key: packet[key] for key in
                        ("x", "y", "d", "p", "f", "b", "pal", "n")
                        if key in packet}
        self.send_room(client.room, {"id": client.ident, "s": client.state},
                       skip=client.ident)


# ---- кадры RFC 6455 --------------------------------------------------------

def send(writer: asyncio.StreamWriter, message: dict) -> None:
    """Отправить текстовый кадр. Сервер не маскирует — так велит стандарт."""
    body = json.dumps(message, separators=(",", ":")).encode("utf-8")
    head = bytearray([0x80 | OP_TEXT])
    size = len(body)
    if size < 126:
        head.append(size)
    elif size < 1 << 16:
        head.append(126)
        head += struct.pack(">H", size)
    else:
        head.append(127)
        head += struct.pack(">Q", size)
    try:
        writer.write(bytes(head) + body)
    except Exception:
        pass                            # соединение уже рвётся — не наша беда


async def read_frame(reader: asyncio.StreamReader) -> tuple[int, bytes] | None:
    """Прочитать один кадр. Возвращает опкод и тело либо None на конце."""
    head = await reader.readexactly(2)
    opcode = head[0] & 0x0F
    masked = bool(head[1] & 0x80)
    size = head[1] & 0x7F
    if size == 126:
        size = struct.unpack(">H", await reader.readexactly(2))[0]
    elif size == 127:
        size = struct.unpack(">Q", await reader.readexactly(8))[0]
    if size > MAX_FRAME:
        return None                     # великан — рвём, разбираться не о чем
    mask = await reader.readexactly(4) if masked else b""
    body = await reader.readexactly(size) if size else b""
    if masked:
        body = bytes(b ^ mask[i % 4] for i, b in enumerate(body))
    return opcode, body


def accept_key(key: str) -> str:
    digest = hashlib.sha1(key.encode("ascii") + GUID).digest()
    return base64.b64encode(digest).decode("ascii")


# ---- соединение ------------------------------------------------------------

async def serve_client(reader, writer, relay: Relay) -> None:
    client: Client | None = None
    try:
        # Рукопожатие: обычный HTTP-запрос с Upgrade.
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 10)
        lines = head.decode("latin-1").split("\r\n")
        headers = {}
        for line in lines[1:]:
            name, _, value = line.partition(":")
            if name:
                headers[name.strip().lower()] = value.strip()
        key = headers.get("sec-websocket-key")
        if not key or "websocket" not in headers.get("upgrade", "").lower():
            writer.write(b"HTTP/1.1 400 Bad Request\r\n\r\n")
            await writer.drain()
            return
        if len(relay.clients) >= MAX_CLIENTS:
            writer.write(b"HTTP/1.1 503 Service Unavailable\r\n\r\n")
            await writer.drain()
            return
        writer.write(
            b"HTTP/1.1 101 Switching Protocols\r\n"
            b"Upgrade: websocket\r\nConnection: Upgrade\r\n"
            b"Sec-WebSocket-Accept: " + accept_key(key).encode("ascii")
            + b"\r\n\r\n")
        await writer.drain()

        ident = base64.urlsafe_b64encode(os.urandom(6)).decode("ascii")
        client = Client(writer, ident)
        relay.clients[ident] = client
        send(writer, {"you": ident})

        while True:
            frame = await asyncio.wait_for(read_frame(reader), IDLE_SECONDS)
            if frame is None:
                break
            opcode, body = frame
            if opcode == OP_CLOSE:
                break
            if opcode == OP_PING:
                writer.write(bytes([0x80 | OP_PONG, len(body)]) + body)
                continue
            if opcode == OP_TEXT:
                relay.update(client, body.decode("utf-8", "replace"))
    except (asyncio.IncompleteReadError, asyncio.TimeoutError,
            ConnectionError, UnicodeDecodeError):
        pass
    finally:
        if client:
            relay.leave(client)
            relay.clients.pop(client.ident, None)
        try:
            writer.close()
        except Exception:
            pass


async def main_async(host: str, port: int) -> None:
    relay = Relay()
    server = await asyncio.start_server(
        lambda r, w: serve_client(r, w, relay), host, port)
    where = ", ".join(str(s.getsockname()) for s in server.sockets or ())
    print(f"соприсутствие слушает {where}", flush=True)
    async with server:
        await server.serve_forever()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="knyaz2-presence")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args(argv)
    try:
        asyncio.run(main_async(args.host, args.port))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
