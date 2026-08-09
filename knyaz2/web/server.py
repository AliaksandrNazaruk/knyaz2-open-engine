"""Минимальный локальный сервер web-адаптера и content pack."""
from __future__ import annotations

import argparse
import gzip
import mimetypes
import shutil
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import BinaryIO
from urllib.parse import unquote, urlsplit


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WEB_ROOT = Path(__file__).resolve().with_name("static")
DEFAULT_CONTENT_ROOT = REPOSITORY_ROOT / "content_build"

# Python не знает .opus, а без верного Content-Type <audio> может отказаться.
mimetypes.add_type("audio/ogg", ".opus")


def resolve_request(path: str, web_root: Path,
                    content_root: Path) -> Path | None:
    """Безопасно сопоставить URL с одним из двух доступных корней."""
    url_path = unquote(urlsplit(path).path)
    if url_path.startswith("/content/"):
        root = content_root.resolve()
        relative = url_path.removeprefix("/content/")
    else:
        root = web_root.resolve()
        relative = url_path.lstrip("/") or "index.html"

    raw = Path(relative)
    if raw.is_absolute() or ".." in raw.parts:
        return None
    candidate = (root / raw).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    if candidate.is_dir():
        candidate = candidate / "index.html"
    return candidate if candidate.is_file() else None


class _Handler(BaseHTTPRequestHandler):
    server_version = "Knyaz2DevServer/0.1"

    def __init__(self, *args, web_root: Path, content_root: Path, **kwargs) -> None:
        self.web_root = web_root
        self.content_root = content_root
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:  # noqa: N802
        self._serve(send_body=True)

    def do_HEAD(self) -> None:  # noqa: N802
        self._serve(send_body=False)

    def _serve(self, send_body: bool) -> None:
        path = resolve_request(self.path, self.web_root, self.content_root)
        if path is None:
            self.send_error(404, "Not found")
            return
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        body = self._packed(path, content_type)
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        if body is None:
            self.send_header("Content-Length", str(path.stat().st_size))
        else:
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        if not send_body:
            return
        if body is not None:
            self.wfile.write(body)
            return
        with path.open("rb") as stream:
            self._copy(stream)

    #: Что жать. Картинки и звук уже сжаты своими форматами — их трогать
    #: незачем, а вот описания карт это текст из мелких чисел, и он ужимается
    #: примерно вдесятеро. Именно за него платит игрок при каждом переходе.
    PACKABLE = ("application/json", "text/", "application/javascript",
                "image/svg+xml")
    #: Мелочь жать дороже, чем отдать как есть.
    PACK_FROM = 1024

    def _packed(self, path: Path, content_type: str) -> bytes | None:
        """Сжатое тело, если клиент его примёт и файл того стоит."""
        if "gzip" not in self.headers.get("Accept-Encoding", ""):
            return None
        if not content_type.startswith(self.PACKABLE):
            return None
        if path.stat().st_size < self.PACK_FROM:
            return None
        return gzip.compress(path.read_bytes(), 6)

    def _copy(self, stream: BinaryIO) -> None:
        shutil.copyfileobj(stream, self.wfile)


def serve(host: str = "127.0.0.1", port: int = 8765,
          web_root: Path = DEFAULT_WEB_ROOT,
          content_root: Path = DEFAULT_CONTENT_ROOT) -> None:
    if not (web_root / "index.html").is_file():
        raise FileNotFoundError(f"нет web-приложения: {web_root}")
    if not (content_root / "manifest.json").is_file():
        raise FileNotFoundError(
            f"нет content pack: {content_root}; сначала выполните knyaz2-content build")

    def handler(*args, **kwargs):
        return _Handler(*args, web_root=web_root, content_root=content_root, **kwargs)

    server = ThreadingHTTPServer((host, port), handler)
    actual_host, actual_port = server.server_address[:2]
    print(f"Knyaz2 web: http://{actual_host}:{actual_port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="knyaz2-web")
    result.add_argument("--host", default="127.0.0.1")
    result.add_argument("--port", type=int, default=8765)
    result.add_argument("--web-root", type=Path, default=DEFAULT_WEB_ROOT)
    result.add_argument("--content", type=Path, default=DEFAULT_CONTENT_ROOT)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    serve(args.host, args.port, args.web_root.resolve(), args.content.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
