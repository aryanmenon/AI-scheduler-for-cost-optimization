"""GPU capability reference table.

Raw DCGM_FI_DEV_GPU_UTIL is "% of the last sample period this GPU had at
least one kernel running" -- it means something very different on a T4
than on an H100. Comparing customers' fleets, or ranking waste across a
heterogeneous cluster, needs a capacity-normalized number: utilization %
scaled by what the GPU can actually do. This table -- and the
effective_tflops it enables in normalizer.py -- is that scaling factor.

Phase 3's power-hard-constraint scheduler is expected to reuse this same
table for heterogeneous-fleet capability reasoning (per the roadmap), so
it's kept slightly more general than component 2 strictly needs today:
memory bandwidth and capacity are included even though only compute
throughput is used downstream right now.

Figures are public spec-sheet dense (non-sparse) FP16 Tensor TFLOPS and
memory bandwidth from NVIDIA datasheets -- directional for cross-SKU
comparability, not a billing-grade ground truth.
"""
from __future__ import annotations

from dataclasses import dataclass

UNKNOWN_SOURCE = "unknown"
SPEC_SHEET_SOURCE = "public_spec_sheet"


@dataclass(frozen=True)
class GPUCapability:
    canonical_name: str
    fp16_tflops: float | None
    mem_bandwidth_gbps: float | None
    mem_capacity_gb: float | None
    source: str = SPEC_SHEET_SOURCE

    @property
    def known(self) -> bool:
        return self.source != UNKNOWN_SOURCE


def _unknown(model_name: str | None) -> GPUCapability:
    return GPUCapability(
        canonical_name=model_name or "unknown",
        fp16_tflops=None,
        mem_bandwidth_gbps=None,
        mem_capacity_gb=None,
        source=UNKNOWN_SOURCE,
    )


# Ordered (pattern, capability) pairs. Order matters: more specific
# patterns (e.g. "A100" + "40GB") must be checked before looser ones.
_CAPABILITY_TABLE: list[tuple[tuple[str, ...], GPUCapability]] = [
    (
        ("H100", "PCIE"),
        GPUCapability("NVIDIA H100 PCIe 80GB", 756.0, 2000.0, 80.0),
    ),
    (
        ("H100",),
        GPUCapability("NVIDIA H100 SXM5 80GB", 989.0, 3350.0, 80.0),
    ),
    (
        ("A100", "40GB"),
        GPUCapability("NVIDIA A100 40GB", 312.0, 1555.0, 40.0),
    ),
    (
        ("A100",),
        GPUCapability("NVIDIA A100 80GB", 312.0, 2039.0, 80.0),
    ),
    (
        ("L40S",),
        GPUCapability("NVIDIA L40S", 362.0, 864.0, 48.0),
    ),
    (
        ("L4",),
        GPUCapability("NVIDIA L4", 121.0, 300.0, 24.0),
    ),
    (
        ("A10",),
        GPUCapability("NVIDIA A10", 125.0, 600.0, 24.0),
    ),
    (
        ("V100",),
        GPUCapability("NVIDIA V100 16GB", 125.0, 900.0, 16.0),
    ),
    (
        ("T4",),
        GPUCapability("NVIDIA T4", 65.0, 320.0, 16.0),
    ),
]


def lookup_capability(model_name: str | None) -> GPUCapability:
    """Match a DCGM `modelName` label to a capability entry.

    Model name strings vary across DCGM/driver versions ("NVIDIA
    A100-SXM4-80GB", "NVIDIA A100 80GB PCIe", "Tesla T4"). Rather than
    require an exact string match, this does case-insensitive substring
    matching against short tokens that reliably identify the SKU family.

    An unrecognized model returns an explicit unknown entry (fp16_tflops
    etc. all None) rather than a guessed default -- silently attributing a
    wrong capability would corrupt every downstream savings estimate for
    that GPU, which is worse than admitting "we don't know" and excluding
    it from capacity-normalized comparisons.
    """
    if not model_name:
        return _unknown(model_name)

    upper = model_name.upper()
    for tokens, capability in _CAPABILITY_TABLE:
        if all(token in upper for token in tokens):
            return capability

    return _unknown(model_name)


def all_known_capabilities() -> list[GPUCapability]:
    """Every SKU this table can resolve to, deduplicated by canonical name.

    For consumers that need to search across known SKUs (e.g. the savings
    estimator picking the smallest capability meeting a target) rather
    than resolve one model-name string.
    """
    seen: dict[str, GPUCapability] = {}
    for _tokens, capability in _CAPABILITY_TABLE:
        seen[capability.canonical_name] = capability
    return list(seen.values())
