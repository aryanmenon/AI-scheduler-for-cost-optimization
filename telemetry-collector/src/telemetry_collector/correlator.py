"""Correlate raw DCGM GPU samples into per-GPU records attributed to a
workload.

DCGM exporter's built-in kubernetes-pod-resources integration already
attaches `namespace`/`pod`/`container` labels to each GPU sample on most
clusters (it reads /var/lib/kubelet/pod-resources under the hood). Where
that integration isn't enabled, DCGM has no way to know which pod owns a
GPU -- rather than guess with a fragile node/index heuristic, we record
those GPUs explicitly as unattributed so downstream waste-detection never
mistakes "we don't know" for "idle".
"""
from __future__ import annotations

from dataclasses import dataclass

from telemetry_collector.metrics_client import MetricSample

UNATTRIBUTED = "unattributed"

# DCGM field -> the GPUMetricRecord attribute it fills.
_METRIC_FIELD_MAP = {
    "DCGM_FI_DEV_GPU_UTIL": "utilization_pct",
    "DCGM_FI_DEV_FB_USED": "memory_used_mb",
    "DCGM_FI_DEV_FB_FREE": "memory_free_mb",
    "DCGM_FI_DEV_POWER_USAGE": "power_draw_w",
    "DCGM_FI_DEV_SM_CLOCK": "sm_clock_mhz",
}

# Label keys DCGM exporter may use across versions for the same concept.
_GPU_INDEX_LABEL_ALIASES = ("gpu", "device")
_UUID_LABEL_ALIASES = ("UUID", "uuid")
_HOSTNAME_LABEL_ALIASES = ("Hostname", "instance", "kubernetes_node")
_MODEL_LABEL_ALIASES = ("modelName", "model")
# When MIG is enabled, DCGM reports one sample set per MIG instance, all
# sharing the same parent `gpu` index -- GPU_I_ID is what actually
# distinguishes them. Without it in the grouping key, instances collide
# into a single overwritten record.
_INSTANCE_ID_LABEL_ALIASES = ("GPU_I_ID", "gpu_i_id", "migprofile")


def _first_label(labels: dict, aliases: tuple[str, ...]) -> str | None:
    for key in aliases:
        if labels.get(key):
            return labels[key]
    return None


@dataclass
class GPUMetricRecord:
    node: str
    gpu_index: str
    gpu_uuid: str | None
    gpu_model: str | None
    namespace: str
    pod: str | None
    container: str | None
    gpu_instance_id: str | None = None
    utilization_pct: float | None = None
    memory_used_mb: float | None = None
    memory_free_mb: float | None = None
    power_draw_w: float | None = None
    sm_clock_mhz: float | None = None

    @property
    def attributed(self) -> bool:
        return self.namespace != UNATTRIBUTED


def correlate(dcgm_samples: list[MetricSample]) -> list[GPUMetricRecord]:
    """Group flat DCGM samples into one record per physical GPU per scrape."""
    by_gpu: dict[tuple, GPUMetricRecord] = {}

    for sample in dcgm_samples:
        field_name = _METRIC_FIELD_MAP.get(sample.name)
        if field_name is None:
            continue  # not one of the fields this collector tracks

        labels = sample.labels
        node = _first_label(labels, _HOSTNAME_LABEL_ALIASES) or "unknown-node"
        gpu_index = _first_label(labels, _GPU_INDEX_LABEL_ALIASES) or "unknown-index"
        gpu_instance_id = _first_label(labels, _INSTANCE_ID_LABEL_ALIASES)
        key = (node, gpu_index, gpu_instance_id)

        record = by_gpu.get(key)
        if record is None:
            namespace = labels.get("namespace") or UNATTRIBUTED
            pod = labels.get("pod") or None
            container = labels.get("container") or None
            # A pod label with no namespace (or vice versa) is not a
            # trustworthy attribution -- treat as unattributed rather than
            # emit a half-populated record a customer might act on.
            if not namespace or namespace == UNATTRIBUTED or not pod:
                namespace, pod, container = UNATTRIBUTED, None, None

            record = GPUMetricRecord(
                node=node,
                gpu_index=gpu_index,
                gpu_uuid=_first_label(labels, _UUID_LABEL_ALIASES),
                gpu_model=_first_label(labels, _MODEL_LABEL_ALIASES),
                namespace=namespace,
                pod=pod,
                container=container,
                gpu_instance_id=gpu_instance_id,
            )
            by_gpu[key] = record

        setattr(record, field_name, sample.value)

    return list(by_gpu.values())
