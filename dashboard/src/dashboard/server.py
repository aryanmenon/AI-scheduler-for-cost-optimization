"""A minimal, dependency-free live dashboard: regenerates the report from
current data on every request rather than caching it, since this is a
low-traffic internal tool where "always current" matters more than
avoiding a re-render.
"""
from __future__ import annotations

import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from dashboard.config import Config
from dashboard.report import generate_report_html

logger = logging.getLogger(__name__)


def make_handler(config: Config) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path in ("/", "/index.html"):
                self._serve_report()
            elif self.path == "/healthz":
                self._respond(200, b"ok", "text/plain; charset=utf-8")
            else:
                self._respond(404, b"not found", "text/plain; charset=utf-8")

        def _serve_report(self) -> None:
            try:
                body = generate_report_html(config).encode("utf-8")
            except Exception:
                logger.exception("failed to generate report")
                self._respond(500, b"failed to generate report", "text/plain; charset=utf-8")
                return
            self._respond(200, body, "text/html; charset=utf-8")

        def _respond(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args) -> None:
            logger.info("%s - %s", self.address_string(), fmt % args)

    return Handler


def build_server(config: Config) -> ThreadingHTTPServer:
    handler = make_handler(config)
    return ThreadingHTTPServer((config.server_host, config.server_port), handler)


def run_server(config: Config) -> None:
    server = build_server(config)
    logger.info("dashboard serving on %s:%d", *server.server_address[:2])
    try:
        server.serve_forever()
    finally:
        server.server_close()
