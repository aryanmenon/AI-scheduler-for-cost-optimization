from telemetry_collector.correlator import UNATTRIBUTED, correlate
from telemetry_collector.metrics_client import parse_metrics


def test_correlate_produces_one_record_per_physical_gpu(dcgm_text):
    samples = parse_metrics(dcgm_text)
    records = correlate(samples)
    assert len(records) == 5


def test_correlate_attributes_pod_when_dcgm_labels_present(dcgm_text):
    samples = parse_metrics(dcgm_text)
    records = correlate(samples)
    bert = next(r for r in records if r.node == "gpu-node-1" and r.gpu_index == "0")
    assert bert.namespace == "inference"
    assert bert.pod == "bert-large-7d4f-xk2p9"
    assert bert.container == "model-server"
    assert bert.attributed is True
    assert bert.utilization_pct == 87
    assert bert.memory_used_mb == 61440
    assert bert.power_draw_w == 312.5
    assert bert.gpu_model == "NVIDIA A100-SXM4-80GB"


def test_correlate_falls_back_to_unattributed_when_no_pod_labels(dcgm_text):
    samples = parse_metrics(dcgm_text)
    records = correlate(samples)
    idle_h100 = next(r for r in records if r.node == "gpu-node-2" and r.gpu_index == "1")
    assert idle_h100.namespace == UNATTRIBUTED
    assert idle_h100.pod is None
    assert idle_h100.container is None
    assert idle_h100.attributed is False
    assert idle_h100.utilization_pct == 0


def test_correlate_handles_heterogeneous_skus(dcgm_text):
    samples = parse_metrics(dcgm_text)
    records = correlate(samples)
    models = {r.gpu_model for r in records}
    assert models == {"NVIDIA A100-SXM4-80GB", "NVIDIA H100-SXM5-80GB", "Tesla T4"}


def test_correlate_ignores_unknown_metric_names():
    from telemetry_collector.metrics_client import MetricSample

    samples = [
        MetricSample(name="DCGM_FI_DEV_GPU_UTIL", value=50, labels={"gpu": "0", "Hostname": "n1"}),
        MetricSample(name="some_unrelated_metric", value=1, labels={"gpu": "0", "Hostname": "n1"}),
    ]
    records = correlate(samples)
    assert len(records) == 1
    assert records[0].utilization_pct == 50


def test_correlate_keeps_mig_instances_on_same_physical_gpu_distinct(dcgm_mig_text):
    samples = parse_metrics(dcgm_mig_text)
    records = correlate(samples)

    # Both MIG slices share node + gpu index "0" -- only GPU_I_ID tells them apart.
    assert len(records) == 2
    by_pod = {r.pod: r for r in records}
    assert set(by_pod) == {"small-model-a-7d4f-x1y2z", "small-model-b-9c1d-p3q4r"}

    a = by_pod["small-model-a-7d4f-x1y2z"]
    b = by_pod["small-model-b-9c1d-p3q4r"]
    assert a.node == b.node == "gpu-node-4"
    assert a.gpu_index == b.gpu_index == "0"
    assert a.gpu_instance_id == "1"
    assert b.gpu_instance_id == "2"
    assert a.utilization_pct == 72
    assert b.utilization_pct == 15


def test_correlate_treats_pod_without_namespace_as_unattributed():
    from telemetry_collector.metrics_client import MetricSample

    samples = [
        MetricSample(
            name="DCGM_FI_DEV_GPU_UTIL",
            value=50,
            labels={"gpu": "0", "Hostname": "n1", "pod": "orphan-pod"},
        ),
    ]
    records = correlate(samples)
    assert records[0].namespace == UNATTRIBUTED
    assert records[0].pod is None
