from conftest import make_estimate, write_estimates

from dashboard.main import generate_report_cli


def test_generate_report_cli_writes_html_file(tmp_path, monkeypatch):
    savings_path = str(tmp_path / "savings.db")
    write_estimates(savings_path, [make_estimate(1, amount_usd=42.0)])
    output_path = str(tmp_path / "report.html")

    monkeypatch.setenv("SAVINGS_SQLITE_PATH", savings_path)
    monkeypatch.setenv("REPORT_OUTPUT_PATH", output_path)

    generate_report_cli()

    with open(output_path) as f:
        content = f.read()
    assert "<!doctype html>" in content
    assert "$42.00" in content
