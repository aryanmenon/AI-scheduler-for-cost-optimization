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

`known` and `recommendable` are deliberately separate flags, not one.
`known` gates whether *this GPU's own telemetry* can be capacity-scaled
and priced -- being known is safe and desirable for any real GPU a
customer might have, consumer cards included. `recommendable` gates a
different question entirely: would this ever be sane advice to hand a
customer as an over-provisioned workload's *right-sizing target*
(ceiling.py searches every known capability for the smallest one that
fits). No real cluster racks consumer/gaming cards as a node pool option,
so recommending one is nonsensical regardless of how well its TFLOPS
number happens to fit -- conflating the two flags (as an earlier version
of this table did) let a consumer GPU's low price silently win the
right-sizing search for *any* over-provisioned finding, not just findings
on that hardware.
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
    # See module docstring: gates right-sizing *recommendations*
    # (ceiling.py), never gates pricing/normalization -- those only
    # depend on `known`.
    recommendable: bool = True

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
        recommendable=False,
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
    # Consumer/gaming SKUs -- known (priceable/normalizable) but never
    # recommendable (see module docstring). Figures are dense (non-sparse)
    # FP16 Tensor TFLOPS from NVIDIA's own spec sheets, same convention as
    # the datacenter SKUs above -- NOT the ~2x "with sparsity" numbers
    # NVIDIA markets these consumer cards with.
    (
        ("3090",),
        GPUCapability("NVIDIA GeForce RTX 3090", 71.0, 936.0, 24.0, recommendable=False),
    ),
    # "4060 TI" must come before the plain "4060" entry below -- its DCGM
    # modelName also contains "4060" as a substring, so the looser pattern
    # would otherwise shadow it and report the wrong TFLOPS/price (same
    # ordering rule as H100/A100's SXM-vs-PCIe entries above).
    (
        ("4060", "TI"),
        GPUCapability("NVIDIA GeForce RTX 4060 Ti", 88.25, 288.0, 16.0, recommendable=False),
    ),
    (
        ("4060",),
        GPUCapability("NVIDIA GeForce RTX 4060", 60.5, 272.0, 8.0, recommendable=False),
    ),
    (
        ("3060",),
        GPUCapability("NVIDIA GeForce RTX 3060", 51.0, 360.0, 12.0, recommendable=False),
    ),
    # RTX 4000 Ada is NVIDIA's professional/workstation Ada-Generation
    # line, not a GeForce gaming card -- genuinely different category, and
    # it does show up on some cloud GPU rental listings. Still marked
    # recommendable=False: NVIDIA markets it as a single-slot, 130W card
    # "from the desktop" for workstation deployment, not a datacenter rack
    # GPU in the same category as T4/A10/L4/A100/H100 -- suggesting it as
    # a real cluster's right-sizing target seems like the same bad advice
    # the GeForce exclusion protects against. fp16_tflops is derived
    # (NVIDIA's own datasheet only publishes FP8-with-sparsity peak =
    # 427.6 TFLOPS; halved for FP16-with-sparsity = 213.8, halved again
    # for dense = ~106.9), not a directly spec-sheet-published dense
    # figure like the other entries in this table -- flagged in case it
    # needs revisiting. Does not distinguish the smaller "RTX 4000 SFF Ada"
    # variant, which has different (lower) real specs -- its modelName
    # would also match this same pattern and get this entry's numbers
    # applied incorrectly; a known approximation, not fixed here since it
    # wasn't asked for.
    (
        ("4000", "ADA"),
        GPUCapability("NVIDIA RTX 4000 Ada Generation", 106.9, 360.0, 20.0, recommendable=False),
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
