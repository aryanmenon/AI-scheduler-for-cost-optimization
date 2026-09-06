from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    savings_sqlite_path: str
    report_output_path: str
    server_host: str
    server_port: int
    top_findings_limit: int
    # Optional shared-secret check on the live server: unset by default so
    # local/dev usage stays zero-config, but a customer deployment should
    # set DASHBOARD_AUTH_TOKEN so the report isn't served to anyone who can
    # merely reach the port.
    auth_token: str | None = None
    # A cheap in-memory per-IP cap: each request does a full SQLite read
    # and re-render (see server.py's docstring), and ThreadingHTTPServer
    # itself has no connection/thread cap, so an unauthenticated or
    # unthrottled deployment is a trivial CPU/thread-exhaustion target.
    rate_limit_max_requests: int = 60
    rate_limit_window_seconds: float = 60.0

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            savings_sqlite_path=os.environ.get(
                "SAVINGS_SQLITE_PATH", "/data/savings/savings.db"
            ),
            report_output_path=os.environ.get("REPORT_OUTPUT_PATH", "./report.html"),
            # Loopback by default -- kubectl port-forward reaches a pod's
            # own network namespace directly, so it works even when the
            # app binds only to 127.0.0.1 inside the container. Binding
            # wider (e.g. for a ClusterIP Service reaching it over the pod
            # network) is an explicit opt-in via DASHBOARD_HOST, not a
            # silent default.
            server_host=os.environ.get("DASHBOARD_HOST", "127.0.0.1"),
            server_port=int(os.environ.get("DASHBOARD_PORT", "8080")),
            top_findings_limit=int(os.environ.get("TOP_FINDINGS_LIMIT", "25")),
            auth_token=os.environ.get("DASHBOARD_AUTH_TOKEN") or None,
            rate_limit_max_requests=int(os.environ.get("DASHBOARD_RATE_LIMIT_MAX_REQUESTS", "60")),
            rate_limit_window_seconds=float(os.environ.get("DASHBOARD_RATE_LIMIT_WINDOW_SECONDS", "60")),
        )
