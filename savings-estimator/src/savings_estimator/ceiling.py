"""SLA-aware achievable ceiling: right-sizing recommendation for an
over-provisioned workload.

The point of a ceiling isn't "run this GPU at 100%" -- that leaves no
headroom for a traffic spike or a latency-sensitive retry storm, and an
over-provisioning fix that causes an SLA breach costs a customer's trust
worse than the waste it fixed. Instead, the recommendation is: what's the
smallest known GPU SKU whose capacity, at the workload's already-observed
peak load, would land at or below a configured target utilization ceiling?

Capacity is checked on BOTH FP16 compute and memory bandwidth. Sizing on
TFLOPS alone was disproved on real hardware (2026-10-04,
testing/rightsizing-mini-test/): an LLM service moved from an RTX 3090 to
a T4 -- 1.09x less compute but 2.92x less memory bandwidth -- went from
21.4% to 54.3% mean busy (2.54x, where TFLOPS-only sizing predicted
1.09x) and its latency rose 2.3x. Token generation is bound by memory
bandwidth, compute-heavy work by TFLOPS; requiring the target to fit on
both is conservative for either kind of workload.

Even a capacity-correct downsize makes each request slower when the target
GPU is weaker on either axis, so every recommendation carries an expected
latency factor: the larger of the compute and memory-bandwidth drops.

GPU memory *capacity* is checked against the workload's peak memory used
(DCGM_FI_DEV_FB_USED, max per hourly rollup) plus MEMORY_HEADROOM: a
target whose usable memory can't hold that is skipped. Peak used memory is
an upper bound on real need (PyTorch's caching allocator keeps freed
blocks), so this errs toward bigger targets, never toward an OOM. It can't
see through pre-allocation, though: vLLM reserves ~90% of the GPU by
default (gpu_memory_utilization=0.9) and TensorFlow grabs all of it, so a
workload holding >= PREALLOCATED_FRACTION of its GPU tells us nothing
about need. For those, and when no memory data exists, a smaller-memory
target still carries an explicit "memory fit not checked" caution. A
target with at least as much memory as the current GPU always fits.
"""
from __future__ import annotations

from dataclasses import dataclass

from ingestion_normalization.capability import GPUCapability, all_known_capabilities

# Peak memory used x this must fit the target. Covers allocator
# fragmentation and a slightly larger batch than the busiest one observed.
MEMORY_HEADROOM = 1.10
# Holding at least this share of the GPU's memory looks like pre-allocation
# (vLLM default 0.9, TensorFlow default ~all), not need.
PREALLOCATED_FRACTION = 0.85
# Spec-sheet GB vs what the driver exposes: a "16 GB" T4 reports 15360 MiB
# (0.94 of 16 GiB). Applied to every target's spec capacity.
USABLE_FRACTION_OF_SPEC = 0.93


def _usable_mib(capacity_gb: float | None) -> float | None:
    return capacity_gb * 1024.0 * USABLE_FRACTION_OF_SPEC if capacity_gb else None


@dataclass
class RightSizingRecommendation:
    required_fp16_tflops: float
    recommended: GPUCapability | None
    detail: str
    # 0.0 when the current GPU's memory bandwidth is unknown (not checked).
    required_mem_bandwidth_gbps: float = 0.0
    # Upper estimate of how much slower each request gets on the
    # recommended GPU (>= 1.0); None when nothing is recommended.
    expected_latency_factor: float | None = None
    # True when the recommended GPU has less memory than the current one
    # and fit could not be checked (pre-allocation or no memory data).
    memory_fit_unchecked: bool = False
    # Peak memory used x MEMORY_HEADROOM, MiB; 0.0 when not used to size.
    required_memory_mib: float = 0.0


def latency_note(factor: float | None) -> str:
    """Short customer-facing caution for a recommendation's latency impact."""
    if factor is None or factor <= 1.05:
        return "no per-request slowdown expected"
    return (f"each request may take up to ~{factor:.1f}x longer -- fine for batch/offline work, "
            f"check latency targets before moving an interactive service")


def memory_note(current_gb: float | None, target_gb: float | None,
                reason: str = "no memory usage data for this workload") -> str | None:
    """Caution when the target GPU has less memory and fit couldn't be
    checked; None when it can't matter (target at least as large)."""
    if current_gb and target_gb and target_gb >= current_gb:
        return None
    sizes = f"the target has {target_gb:.0f} GB vs {current_gb:.0f} GB now; " if current_gb and target_gb else ""
    return f"memory fit not checked ({reason}) -- {sizes}confirm model weights and working memory fit"


def recommendation_cautions(rec: "RightSizingRecommendation") -> str:
    """The cautions every downsize recommendation carries, for one-line display."""
    parts = [latency_note(rec.expected_latency_factor)]
    if rec.memory_fit_unchecked:
        parts.append("memory fit not checked")
    return "; ".join(parts)


def right_sized_capability(
    current_fp16_tflops: float,
    observed_peak_utilization_pct: float,
    sla_target_utilization_pct: float,
    current_mem_bandwidth_gbps: float | None = None,
    current_mem_capacity_gb: float | None = None,
    peak_memory_used_mib: float | None = None,
    current_memory_total_mib: float | None = None,
) -> RightSizingRecommendation:
    """What's the smallest known SKU that keeps this workload's peak load
    at or below the SLA target, given its current peak on its current GPU?

    The workload's peak demand is estimated per resource as current
    capacity * observed_peak_utilization_pct / 100 -- what it actually
    asked for at its busiest observed moment -- for FP16 TFLOPS and, when
    known, memory bandwidth. Sizing a new GPU so that demand lands at
    exactly the SLA target (not 100%) is what keeps headroom:
    required = demand / (target / 100), and a candidate must meet the
    requirement on both resources.

    Memory capacity: given peak_memory_used_mib (and the current GPU's
    usable memory, current_memory_total_mib from DCGM used+free, falling
    back to its spec), a candidate must also hold peak x MEMORY_HEADROOM --
    unless the peak shows pre-allocation (see module docstring).
    """
    if observed_peak_utilization_pct <= 0:
        return RightSizingRecommendation(
            required_fp16_tflops=0.0,
            recommended=None,
            detail="no observed peak load to size against",
        )

    share = observed_peak_utilization_pct / 100.0
    headroom = sla_target_utilization_pct / 100.0
    peak_demand_tflops = current_fp16_tflops * share
    required_fp16_tflops = peak_demand_tflops / headroom
    required_bw = (current_mem_bandwidth_gbps * share / headroom) if current_mem_bandwidth_gbps else 0.0

    current_total = current_memory_total_mib or _usable_mib(current_mem_capacity_gb)
    if peak_memory_used_mib is None:
        memory_status, required_mem = "unknown", 0.0
    elif current_total and peak_memory_used_mib >= PREALLOCATED_FRACTION * current_total:
        memory_status, required_mem = "preallocated", 0.0
    else:
        memory_status, required_mem = "measured", peak_memory_used_mib * MEMORY_HEADROOM

    # recommendable excludes SKUs (consumer/gaming cards) that are safe to
    # price a customer's own telemetry against but nonsensical to suggest
    # as a right-sizing *target* -- no real cluster racks them as a node
    # pool option, however well their TFLOPS number happens to fit. See
    # capability.py's module docstring for why this is a separate flag
    # from `known`.
    candidates = [
        cap for cap in all_known_capabilities()
        if cap.fp16_tflops is not None
        and cap.fp16_tflops >= required_fp16_tflops
        and cap.recommendable
        and (not required_bw or (cap.mem_bandwidth_gbps is not None and cap.mem_bandwidth_gbps >= required_bw))
        and (not required_mem or (_usable_mib(cap.mem_capacity_gb) or 0.0) >= required_mem)
    ]

    needs = f"{required_fp16_tflops:.0f} TFLOPS"
    if required_bw:
        needs += f" and {required_bw:.0f} GB/s memory bandwidth"
    if required_mem:
        needs += f" and {required_mem / 1024:.1f} GiB of memory (peak {peak_memory_used_mib / 1024:.1f} GiB used + 10%)"
    if not candidates:
        return RightSizingRecommendation(
            required_fp16_tflops=required_fp16_tflops,
            recommended=None,
            detail=f"no known SKU meets the required {needs} at a {sla_target_utilization_pct:.0f}% target ceiling",
            required_mem_bandwidth_gbps=required_bw,
            required_memory_mib=required_mem,
        )

    # Smallest by compute, then by memory bandwidth (e.g. A10 before V100
    # at equal TFLOPS).
    smallest = min(candidates, key=lambda c: (c.fp16_tflops, c.mem_bandwidth_gbps or 0.0))
    drops = [current_fp16_tflops / smallest.fp16_tflops]
    if current_mem_bandwidth_gbps and smallest.mem_bandwidth_gbps:
        drops.append(current_mem_bandwidth_gbps / smallest.mem_bandwidth_gbps)
    latency_factor = max(1.0, *drops)
    if memory_status == "measured":
        mem_note = None  # checked: every candidate holds the peak + headroom
    elif memory_status == "preallocated":
        mem_note = memory_note(
            current_mem_capacity_gb, smallest.mem_capacity_gb,
            reason=f"the workload holds {peak_memory_used_mib / current_total:.0%} of GPU memory, typical of "
                   f"vLLM/TensorFlow pre-allocation, so its real need isn't visible",
        )
    else:
        mem_note = memory_note(current_mem_capacity_gb, smallest.mem_capacity_gb)
    detail = (
        f"peak demand sized to a {sla_target_utilization_pct:.0f}% ceiling needs {needs}; "
        f"recommends {smallest.canonical_name} ({smallest.fp16_tflops:.0f} TFLOPS"
        + (f", {smallest.mem_bandwidth_gbps:.0f} GB/s" if smallest.mem_bandwidth_gbps else "") + ")"
        + ("" if required_bw else " -- memory bandwidth not checked (unknown for the current GPU)")
        + f"; {latency_note(latency_factor)}"
        + (f"; {mem_note}" if mem_note else "")
    )
    return RightSizingRecommendation(
        required_fp16_tflops=required_fp16_tflops,
        recommended=smallest,
        detail=detail,
        required_mem_bandwidth_gbps=required_bw,
        expected_latency_factor=latency_factor,
        memory_fit_unchecked=mem_note is not None,
        required_memory_mib=required_mem,
    )
