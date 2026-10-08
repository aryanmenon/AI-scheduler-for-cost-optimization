"""The pilot sample report as a regression test of the money figures.

docs/pilot/make_sample_report.py runs the real waste-detector,
savings-estimator and dashboard aggregation over a fixed fictional cluster.
Its figures were checked by hand on 2026-10-04 (see the comments below), and
building that report is what exposed two headline bugs 345 unit tests had
missed. Pinning them here means any change that shifts a rupee figure on
this cluster fails CI and has to be re-checked by a person.
"""
import importlib.util
import os

import pytest

_SCRIPT = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "pilot", "make_sample_report.py")


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    spec = importlib.util.spec_from_file_location("make_sample_report", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build(str(tmp_path_factory.mktemp("sample")))


def test_headline_matches_the_hand_checked_figure(report):
    _, summary = report
    # over-provisioned embeddings -> V100: (300-175) x 730        =  91,250
    # oversized-by-average llm-chat-api -> A100 40GB: (300-220) x 730 = 58,400
    # oversized-by-average ocr-worker, reranker -> T4: 2 x (70-45) x 730 = 36,500
    # recurring pattern, 10 quiet hours x 30 days x Rs300          =  90,000
    assert summary.projected_monthly_total_inr == pytest.approx(276_150.0)
    # notebook idle 144h x Rs300, already spent
    assert summary.observed_window_total_inr == pytest.approx(43_200.0)


def test_recommendations_on_each_gpu(report):
    estimates, _ = report
    by = {}
    for e in estimates:
        by.setdefault((e.category, e.workload), []).append(e)
    embeddings = by[("over_provisioned", "embeddings")][0]
    assert embeddings.recommended_action.startswith("right-size to NVIDIA V100 16GB (")
    chat = by[("oversized_by_average", "llm-chat-api")][0]
    # 90% of memory held -> pre-allocation: fit can't be checked, and says so
    assert chat.recommended_action.startswith("right-size to NVIDIA A100 40GB (")
    assert chat.recommended_action.endswith("; memory fit not checked)")
    for wl in ("ocr-worker", "reranker"):
        assert by[("oversized_by_average", wl)][0].recommended_action.startswith("right-size to NVIDIA T4 (")
    assert len(by[("recurring_pattern", "finetune-runner")]) == 10
    assert len(by[("idle", "notebook-priya")]) == 1


def test_fragmentation_stays_out_of_the_headline(report):
    estimates, summary = report
    fragmented = [e for e in estimates if e.category == "fragmented"]
    assert fragmented and all(e.basis == "visibility_upper_bound" for e in fragmented)
    assert summary.top_findings[0].category != "fragmented"


def test_nothing_unpriceable(report):
    estimates, _ = report
    assert all(e.priceable for e in estimates)


def test_recoverable_ceiling_on_the_sample_cluster(report):
    _, summary = report
    c = summary.ceiling
    # Newest 7 days of the 8: 7 GPUs x 168 h. Hourly spend 4 x Rs300 (A100)
    # + 2 x Rs70 (L4) + Rs45 (T4) = Rs1,385 -> Rs2,32,680 observed and
    # Rs10,11,050 a month at that run rate.
    assert c.observed_gpu_hours == 1176
    assert c.observed_spend_inr == pytest.approx(232_680.0)
    assert c.monthly_spend_inr == pytest.approx(1_011_050.0)
    assert c.excluded_gpu_hours == 0
    # Share of that spend below the 70% target (depends on the seeded
    # utilization, so pinned to the value it produced on 2026-10-08).
    assert c.fraction == pytest.approx(0.7261, abs=1e-4)
    # The headline captures ~38% of the ceiling.
    assert summary.projected_monthly_total_inr / c.monthly_recoverable_inr == pytest.approx(0.376, abs=1e-3)
