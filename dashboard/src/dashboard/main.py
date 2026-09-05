from __future__ import annotations

import logging
import sys

from dashboard.config import Config
from dashboard.report import generate_report_html
from dashboard.server import run_server


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )


def main() -> None:
    _setup_logging()
    config = Config.from_env()
    logging.getLogger(__name__).info(
        "starting dashboard server: savings=%s host=%s port=%d",
        config.savings_sqlite_path, config.server_host, config.server_port,
    )
    run_server(config)


def generate_report_cli() -> None:
    _setup_logging()
    config = Config.from_env()
    html_out = generate_report_html(config)
    with open(config.report_output_path, "w") as f:
        f.write(html_out)
    logging.getLogger(__name__).info("wrote report to %s", config.report_output_path)


if __name__ == "__main__":
    main()
