"""Join raw per-scrape GPU samples into per-workload normalized records.

This is a 1:1 enrichment, not a grouping step: each raw sample already
represents one physical-or-MIG-instance GPU at one point in time (that
grouping happened in telemetry-collector's correlator, which is why it
needed gpu_instance_id in its key -- see correlator.py's docstring there).
What's added here is workload identity and capability-normalized capacity,
so a downstream consumer can compare "this workload's effective TFLOPS"
across a heterogeneous fleet instead of raw, SKU-incomparable percentages.

Time-sliced GPU sharing (multiple pods concurrently scheduled onto one
physical, non-MIG GPU) is not distinguishable at the DCGM level -- DCGM
reports one utilization/memory value per physical device, not per sharing
tenant. Where that's happening, the raw sample is attributed to whichever
single pod/namespace DCGM's pod-resources integration reported (typically
the most recently scheduled one) rather than split; that's a known
limitation of relying on DCGM alone, flagged here rather than silently
treated as exact per-tenant accounting.
"""
from __future__ import annotations

from dataclasses import dataclass

from ingestion_normalization.capability import GPUCapability, lookup_capability
from ingestion_normalization.raw_reader import RawGPUSample
from ingestion_normalization.workload import derive_workload_name

UNATTRIBUTED = "unattributed"


@dataclass
class NormalizedRecord:
    scrape_run_id: int
    scraped_at: float
    node: str
    gpu_index: str
    gpu_instance_id: str | None
    gpu_uuid: str | None
    gpu_model: str | None
    namespace: str
    workload: str | None
    pod: str | None
    container: str | None
    utilization_pct: float | None
    memory_used_mb: float | None
    memory_free_mb: float | None
    power_draw_w: float | None
    capability_known: bool
    fp16_tflops: float | None
    effective_tflops: float | None

    @property
    def attributed(self) -> bool:
        return self.namespace != UNATTRIBUTED


def _effective_tflops(utilization_pct: float | None, capability: GPUCapability) -> float | None:
    if utilization_pct is None or capability.fp16_tflops is None:
        return None
    return (utilization_pct / 100.0) * capability.fp16_tflops


def normalize_sample(raw: RawGPUSample) -> NormalizedRecord:
    capability = lookup_capability(raw.gpu_model)

    # A MIG instance's utilization_pct is relative to its own slice, not
    # the full physical GPU capability.fp16_tflops resolves to -- and DCGM
    # carries no MIG profile/fraction label (see module docstring) from
    # which to derive the slice's actual share of that capacity. Treating
    # a slice's utilization as if it applied to the whole GPU overcounts
    # capacity: summed effective_tflops across a GPU's slices could exceed
    # what the physical card can do. Until MIG profile data is available,
    # capacity-normalized figures are reported as unknown for these
    # samples -- the same "admit we don't know" choice this table already
    # makes for unrecognized models -- rather than silently wrong.
    is_mig_slice = raw.gpu_instance_id is not None
    capability_known = capability.known and not is_mig_slice
    fp16_tflops = None if is_mig_slice else capability.fp16_tflops
    effective_tflops = None if is_mig_slice else _effective_tflops(raw.utilization_pct, capability)

    return NormalizedRecord(
        scrape_run_id=raw.scrape_run_id,
        scraped_at=raw.scraped_at,
        node=raw.node,
        gpu_index=raw.gpu_index,
        gpu_instance_id=raw.gpu_instance_id,
        gpu_uuid=raw.gpu_uuid,
        gpu_model=raw.gpu_model,
        namespace=raw.namespace,
        workload=derive_workload_name(raw.pod),
        pod=raw.pod,
        container=raw.container,
        utilization_pct=raw.utilization_pct,
        memory_used_mb=raw.memory_used_mb,
        memory_free_mb=raw.memory_free_mb,
        power_draw_w=raw.power_draw_w,
        capability_known=capability_known,
        fp16_tflops=fp16_tflops,
        effective_tflops=effective_tflops,
    )


def normalize_samples(raw_samples: list[RawGPUSample]) -> list[NormalizedRecord]:
    return [normalize_sample(s) for s in raw_samples]
