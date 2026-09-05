import pytest

from waste_detector.findings import IDLE, OVER_PROVISIONED, FindingsStorage, WasteFinding


@pytest.fixture
def storage(tmp_path):
    s = FindingsStorage(str(tmp_path / "findings.db"))
    yield s
    s.close()


def _finding(category=IDLE, **overrides) -> WasteFinding:
    defaults = dict(
        category=category,
        node="gpu-node-1",
        gpu_index="0",
        gpu_instance_id=None,
        namespace="inference",
        workload="bert-large",
        window_start=0.0,
        window_end=3600.0,
        confidence=0.9,
        metric_value=4.0,
        detail="idle for 4 consecutive hours",
    )
    defaults.update(overrides)
    return WasteFinding(**defaults)


def test_insert_and_count(storage):
    storage.insert_findings([_finding()], detected_at=1000.0)
    assert storage.count() == 1


def test_all_findings_filters_by_category(storage):
    storage.insert_findings([_finding(category=IDLE), _finding(category=OVER_PROVISIONED)], detected_at=1000.0)
    assert len(storage.all_findings()) == 2
    assert len(storage.all_findings(category=IDLE)) == 1


def test_reinserting_same_window_replaces_not_duplicates(storage):
    f1 = _finding(metric_value=4.0)
    storage.insert_findings([f1], detected_at=1000.0)
    f2 = _finding(metric_value=5.0)  # same identity key, updated evidence
    storage.insert_findings([f2], detected_at=2000.0)

    assert storage.count() == 1
    row = storage.all_findings()[0]
    assert row["metric_value"] == 5.0


def test_distinct_gpu_instances_are_separate_findings(storage):
    storage.insert_findings(
        [
            _finding(gpu_instance_id="1", workload="small-model-a"),
            _finding(gpu_instance_id="2", workload="small-model-b"),
        ],
        detected_at=1000.0,
    )
    assert storage.count() == 2
