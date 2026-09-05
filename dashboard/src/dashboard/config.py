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

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            savings_sqlite_path=os.environ.get(
                "SAVINGS_SQLITE_PATH", "/data/savings/savings.db"
            ),
            report_output_path=os.environ.get("REPORT_OUTPUT_PATH", "./report.html"),
            server_host=os.environ.get("DASHBOARD_HOST", "0.0.0.0"),
            server_port=int(os.environ.get("DASHBOARD_PORT", "8080")),
            top_findings_limit=int(os.environ.get("TOP_FINDINGS_LIMIT", "25")),
        )
