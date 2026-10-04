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
"""
from __future__ import annotations

from dataclasses import dataclass

from ingestion_normalization.capability import GPUCapability, all_known_capabilities


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


def latency_note(factor: float | None) -> str:
    """Short customer-facing caution for a recommendation's latency impact."""
    if factor is None or factor <= 1.05:
        return "no per-request slowdown expected"
    return (f"each request may take up to ~{factor:.1f}x longer -- fine for batch/offline work, "
            f"check latency targets before moving an interactive service")


def right_sized_capability(
    current_fp16_tflops: float,
    observed_peak_utilization_pct: float,
    sla_target_utilization_pct: float,
    current_mem_bandwidth_gbps: float | None = None,
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
    ]

    needs = f"{required_fp16_tflops:.0f} TFLOPS"
    if required_bw:
        needs += f" and {required_bw:.0f} GB/s memory bandwidth"
    if not candidates:
        return RightSizingRecommendation(
            required_fp16_tflops=required_fp16_tflops,
            recommended=None,
            detail=f"no known SKU meets the required {needs} at a {sla_target_utilization_pct:.0f}% target ceiling",
            required_mem_bandwidth_gbps=required_bw,
        )

    # Smallest by compute, then by memory bandwidth (e.g. A10 before V100
    # at equal TFLOPS).
    smallest = min(candidates, key=lambda c: (c.fp16_tflops, c.mem_bandwidth_gbps or 0.0))
    drops = [current_fp16_tflops / smallest.fp16_tflops]
    if current_mem_bandwidth_gbps and smallest.mem_bandwidth_gbps:
        drops.append(current_mem_bandwidth_gbps / smallest.mem_bandwidth_gbps)
    latency_factor = max(1.0, *drops)
    detail = (
        f"peak demand sized to a {sla_target_utilization_pct:.0f}% ceiling needs {needs}; "
        f"recommends {smallest.canonical_name} ({smallest.fp16_tflops:.0f} TFLOPS"
        + (f", {smallest.mem_bandwidth_gbps:.0f} GB/s" if smallest.mem_bandwidth_gbps else "") + ")"
        + ("" if required_bw else " -- memory bandwidth not checked (unknown for the current GPU)")
        + f"; {latency_note(latency_factor)}"
    )
    return RightSizingRecommendation(
        required_fp16_tflops=required_fp16_tflops,
        recommended=smallest,
        detail=detail,
        required_mem_bandwidth_gbps=required_bw,
        expected_latency_factor=latency_factor,
    )
