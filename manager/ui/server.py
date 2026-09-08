"""Minimal HTTP server for the game.

Serves the frontend from ``static/`` and exposes JSON API routes. All gameplay
routes delegate to the :class:`GameService`, keeping HTTP and game logic
separate.
"""

from __future__ import annotations

import json
import mimetypes
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from manager.api.sessions import SessionService

DEFAULT_STATIC_DIR = Path(__file__).parent / "static"


class GameHttpServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], static_dir: Path, routes: dict, handlers: dict):
        self.static_dir = Path(static_dir)
        self.routes = routes
        self.handlers = handlers
        super().__init__(address, GameHandler)


class GameHandler(BaseHTTPRequestHandler):
    server_version = "TouchlineManager/0.1"

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        try:
            if path.startswith("/api/"):
                self._handle_api("GET", path)
            else:
                self._handle_static(path)
        except Exception as exc:
            self.send_json(500, {"error": str(exc)})

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        try:
            self._handle_api("POST", path)
        except Exception as exc:
            self.send_json(500, {"error": str(exc)})

    def _handle_api(self, method: str, path: str) -> None:
        parsed = urllib.parse.urlparse(self.path)
        query_params = dict(urllib.parse.parse_qsl(parsed.query))
        key = f"{method} {path}"
        handler = self.server.routes.get(key)
        if handler is None:
            self.send_json(404, {"error": f"unknown route {key}"})
            return
        body = {}
        if method == "POST":
            try:
                raw = self._read_body()
                if raw:
                    body = json.loads(raw)
            except json.JSONDecodeError as exc:
                self.send_json(400, {"error": f"invalid JSON body: {exc}"})
                return
        try:
            self.send_json(200, handler(body, query_params, self.headers))
        except Exception as exc:
            self.send_json(400, {"error": str(exc)})

    def _read_body(self) -> str:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length <= 0:
            return ""
        return self.rfile.read(length).decode("utf-8")

    def _handle_static(self, path: str) -> None:
        if path in ("", "/"):
            path = "/index.html"
        root = self.server.static_dir.resolve()
        candidate = (root / path.lstrip("/")).resolve()
        if not str(candidate).startswith(str(root)) or not candidate.is_file():
            self.send_error(404, "Not Found")
            return
        content_type, _ = mimetypes.guess_type(str(candidate))
        if candidate.suffix == ".webmanifest":
            content_type = "application/manifest+json"
        self.send_response(200)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        with candidate.open("rb") as handle:
            self.wfile.write(handle.read())

    def send_json(self, status: int, payload) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        pass


def build_routes(sessions: SessionService) -> dict:
    """Map HTTP routes to per-user service calls (device-scoped)."""
    def status(body, params, headers=None):
        from manager.data.world import cached_world

        seed = int(params.get("seed", 42))
        world = cached_world(seed)
        apex = next(c for c in world.competitions if c.id == "apex_division")
        return {
            "game": "Touchline Manager",
            "phase": 2,
            "version": "0.1.0",
            "seed": seed,
            "season": world.season_id,
            "federation": "Super League",
            "clubs": len(world.clubs),
            "players": len(world.players),
        }

    def _device_id(params, headers) -> str:
        for source in (headers, params):
            if source is None:
                continue
            try:
                value = source.get("X-Device-Id") or source.get("device_id")
            except AttributeError:
                value = None
            if value:
                return str(value)
        return ""

    def service_of(params, headers) -> "GameService":
        return sessions.service_for(_device_id(params, headers))

    def query(body, params, headers=None):
        name = params.get("name", "")
        if not name:
            raise ValueError("missing query name")
        return service_of(params, headers).query(name, params)

    def action(body, params, headers=None):
        command = params.get("command", "")
        if not command:
            raise ValueError("missing action command")
        return service_of(params, headers).action(command, body)

    return {
        "GET /api/status": status,
        "GET /api/query": query,
        "POST /api/action": action,
        "POST /api/careers": lambda body, params, headers=None: service_of(params, headers).create_career(body),
        "POST /api/career/load": lambda body, params, headers=None: service_of(params, headers).load_career(body),
        "POST /api/career/delete": lambda body, params, headers=None: service_of(params, headers).delete(body),
        "POST /api/session": lambda body, params, headers=None: service_of(params, headers).reset_session(body),
    }


def create_server(
    service,
    address: tuple[str, int] = ("127.0.0.1", 8765),
    static_dir: Path | None = None,
) -> GameHttpServer:
    sessions = service if isinstance(service, SessionService) else SessionService(legacy=service)
    routes = build_routes(sessions)
    handlers = {}
    return GameHttpServer(address, static_dir or DEFAULT_STATIC_DIR, routes, handlers)


def open_browser(url: str) -> None:
    try:
        webbrowser.open(url)
    except Exception:
        pass