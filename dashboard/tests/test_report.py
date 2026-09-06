import json

from conftest import make_estimate, write_estimates

from dashboard.config import Config
from dashboard.report import generate_report_html


def _config(savings_path: str, tmp_path) -> Config:
    return Config(
        savings_sqlite_path=savings_path,
        report_output_path=str(tmp_path / "report.html"),
        server_host="127.0.0.1",
        server_port=0,
        top_findings_limit=25,
    )


def test_generate_report_html_emits_structured_cycle_complete_log(tmp_path, caplog):
    # Regression: an operator needs a consistent, parseable signal per
    # report generation without reading source code to learn what each
    # service's ad-hoc log message means. Schema shared across all five
    # services: event/component/duration_ms/rows_in/rows_out/errors.
    savings_path = str(tmp_path / "savings.db")
    write_estimates(savings_path, [make_estimate(1, category="idle", amount_inr=14.0)])
    config = _config(savings_path, tmp_path)

    with caplog.at_level("INFO", logger="dashboard.report"):
        generate_report_html(config)

    payloads = [json.loads(r.message) for r in caplog.records if r.message.startswith("{")]
    cycle_logs = [p for p in payloads if p.get("event") == "cycle_complete"]
    assert len(cycle_logs) == 1
    log = cycle_logs[0]
    assert log["component"] == "dashboard"
    assert log["rows_in"] == 1
    assert log["rows_out"] == 1
    assert log["priceable"] == 1
    assert log["errors"] == 0
