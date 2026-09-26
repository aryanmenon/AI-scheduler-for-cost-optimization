"""SLA-aware achievable ceiling: right-sizing recommendation for an
over-provisioned workload.

The point of a ceiling isn't "run this GPU at 100%" -- that leaves no
headroom for a traffic spike or a latency-sensitive retry storm, and an
over-provisioning fix that causes an SLA breach costs a customer's trust
worse than the waste it fixed. Instead, the recommendation is: what's the
smallest known GPU SKU whose capacity, at the workload's already-observed
peak load, would land at or below a configured target utilization ceiling?
"""
from __future__ import annotations

from dataclasses import dataclass

from ingestion_normalization.capability import GPUCapability, all_known_capabilities


@dataclass
class RightSizingRecommendation:
    required_fp16_tflops: float
    recommended: GPUCapability | None
    detail: str


def right_sized_capability(
    current_fp16_tflops: float,
    observed_peak_utilization_pct: float,
    sla_target_utilization_pct: float,
) -> RightSizingRecommendation:
    """What's the smallest known SKU that keeps this workload's peak load
    at or below the SLA target, given its current peak on its current GPU?

    The workload's peak *compute demand* (in TFLOPS) is estimated as
    current_fp16_tflops * observed_peak_utilization_pct / 100 -- i.e. what
    it actually asked for at its busiest observed moment. Sizing a new GPU
    so that demand lands at exactly the SLA target (not 100%) is what
    keeps headroom: required = demand / (target / 100).
    """
    if observed_peak_utilization_pct <= 0:
        return RightSizingRecommendation(
            required_fp16_tflops=0.0,
            recommended=None,
            detail="no observed peak load to size against",
        )

    peak_demand_tflops = current_fp16_tflops * (observed_peak_utilization_pct / 100.0)
    required_fp16_tflops = peak_demand_tflops / (sla_target_utilization_pct / 100.0)

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
    ]

    if not candidates:
        return RightSizingRecommendation(
            required_fp16_tflops=required_fp16_tflops,
            recommended=None,
            detail=(
                f"no known SKU meets the required {required_fp16_tflops:.0f} TFLOPS "
                f"at a {sla_target_utilization_pct:.0f}% target ceiling"
            ),
        )

    smallest = min(candidates, key=lambda c: c.fp16_tflops)
    return RightSizingRecommendation(
        required_fp16_tflops=required_fp16_tflops,
        recommended=smallest,
        detail=(
            f"peak demand ~{peak_demand_tflops:.0f} TFLOPS sized to a "
            f"{sla_target_utilization_pct:.0f}% ceiling recommends {smallest.canonical_name} "
            f"({smallest.fp16_tflops:.0f} TFLOPS)"
        ),
    )
