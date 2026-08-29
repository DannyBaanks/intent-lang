"""Servidor local para la consola web de intent-lang."""
from __future__ import annotations

import json
import mimetypes
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from intentlang.relex import round_trip  # noqa: E402
from intentlang.resolve import resolve  # noqa: E402


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = "/index.html" if self.path == "/" else self.path
        if path not in {"/index.html", "/styles.css", "/app.js"}:
            self._send_json({"error": "not found"}, 404)
            return
        file_path = WEB / path.lstrip("/")
        self._send_bytes(file_path.read_bytes(), mimetypes.guess_type(file_path.name)[0] or "text/plain")

    def do_POST(self) -> None:
        if self.path != "/api/resolve":
            self._send_json({"error": "not found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length))
            text = payload.get("text", "").strip()
            lang = payload.get("lang", "es")
            if not text:
                raise ValueError("text vacío")
            intent = resolve(text, lang)
            self._send_json({"intent": intent.to_dict(), "round_trip": round_trip(intent, lang)})
        except Exception as error:  # local UI boundary: return a readable error
            self._send_json({"error": str(error)}, 400)

    def _send_json(self, payload: dict, status: int = 200) -> None:
        self._send_bytes(json.dumps(payload, ensure_ascii=False).encode(), "application/json", status)

    def _send_bytes(self, data: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:
        print(f"[web] {format % args}")


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 8765), Handler)
    print("intent-lang web: http://127.0.0.1:8765")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
