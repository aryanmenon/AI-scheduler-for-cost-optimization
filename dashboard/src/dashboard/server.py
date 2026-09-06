"""A minimal, dependency-free live dashboard: regenerates the report from
current data on every request rather than caching it, since this is a
low-traffic internal tool where "always current" matters more than
avoiding a re-render.
"""
from __future__ import annotations

import hmac
import json
import logging
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from dashboard.config import Config
from dashboard.report import generate_report_html

logger = logging.getLogger(__name__)


def _send_alert(webhook_url: str | None, message: str) -> None:
    """Best-effort POST to a Slack-compatible incoming webhook (a plain
    {"text": ...} JSON body). A structured log line only reaches someone
    who's already looking; this is for the case where nobody is. Alerting
    must never be allowed to take down report serving, so any failure
    here is logged and swallowed, never raised.
    """
    if not webhook_url:
        return
    try:
        req = urllib.request.Request(
            webhook_url,
            data=json.dumps({"text": message}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        logger.warning("failed to send alert webhook", exc_info=True)


class _FailureAlerter:
    """Tracks consecutive report-generation failures across requests
    (ThreadingHTTPServer serves them concurrently, hence the lock) and
    fires a human-visible webhook alert once they cross a threshold --
    edge-triggered, once on crossing it and once again on recovery, not on
    every failed request past it.
    """

    def __init__(self, webhook_url: str | None, threshold: int):
        self._webhook_url = webhook_url
        self._threshold = threshold
        self._lock = threading.Lock()
        self._consecutive_failures = 0

    def record_failure(self) -> None:
        if not self._webhook_url:
            return
        with self._lock:
            self._consecutive_failures += 1
            n = self._consecutive_failures
        if n == self._threshold:
            _send_alert(
                self._webhook_url,
                f"[gpu-cost-optimizer] dashboard: "
                f"{n} consecutive failed report-generation requests -- investigate.",
            )

    def record_success(self) -> None:
        if not self._webhook_url:
            return
        with self._lock:
            n = self._consecutive_failures
            self._consecutive_failures = 0
        if n >= self._threshold:
            _send_alert(
                self._webhook_url,
                f"[gpu-cost-optimizer] dashboard: recovered after {n} consecutive failed requests.",
            )


class _RateLimiter:
    """A cheap fixed-window cap, keyed by client IP.

    Every request re-reads the whole SQLite file and re-renders the report
    (see module docstring), and ThreadingHTTPServer itself imposes no
    connection or thread cap -- without this, an unauthenticated or
    unthrottled client can drive unbounded thread creation and repeated
    full-table scans. Stdlib-only, matching this module's zero-dependency
    design.
    """

    def __init__(self, max_requests: int, window_seconds: float):
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._lock = threading.Lock()
        self._hits: dict[str, list[float]] = {}

    def allow(self, key: str) -> bool:
        if self._max_requests <= 0:
            return True
        now = time.time()
        with self._lock:
            recent = [t for t in self._hits.get(key, []) if now - t < self._window_seconds]
            if len(recent) >= self._max_requests:
                self._hits[key] = recent
                return False
            recent.append(now)
            self._hits[key] = recent
            return True


def make_handler(config: Config) -> type[BaseHTTPRequestHandler]:
    limiter = _RateLimiter(config.rate_limit_max_requests, config.rate_limit_window_seconds)
    alerter = _FailureAlerter(config.alert_webhook_url, config.alert_consecutive_failure_threshold)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path in ("/", "/index.html"):
                if not self._authorized():
                    self._respond(401, b"unauthorized", "text/plain; charset=utf-8")
                    return
                if not limiter.allow(self.client_address[0]):
                    self._respond(429, b"too many requests", "text/plain; charset=utf-8")
                    return
                self._serve_report()
            elif self.path == "/healthz":
                self._respond(200, b"ok", "text/plain; charset=utf-8")
            else:
                self._respond(404, b"not found", "text/plain; charset=utf-8")

        def _authorized(self) -> bool:
            if not config.auth_token:
                # No token configured: local/dev default, documented in
                # Config.auth_token -- a real deployment sets one.
                return True
            presented = self.headers.get("Authorization", "")
            expected = f"Bearer {config.auth_token}"
            # Constant-time comparison: this guards a secret token, and a
            # naive `==` leaks how many leading characters matched via
            # response timing.
            return hmac.compare_digest(presented, expected)

        def _serve_report(self) -> None:
            try:
                body = generate_report_html(config).encode("utf-8")
            except Exception:
                logger.exception("failed to generate report")
                alerter.record_failure()
                self._respond(500, b"failed to generate report", "text/plain; charset=utf-8")
                return
            alerter.record_success()
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
    if not config.auth_token:
        logger.warning(
            "DASHBOARD_AUTH_TOKEN is not set -- the report is served to anyone who can reach %s:%d",
            *server.server_address[:2],
        )
    logger.info("dashboard serving on %s:%d", *server.server_address[:2])
    try:
        server.serve_forever()
    finally:
        server.server_close()
