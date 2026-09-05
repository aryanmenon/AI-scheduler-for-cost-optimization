"""GPU hourly cost lookup, keyed to capability.py's canonical SKU names.

The defaults below are illustrative public on-demand list-price
approximations -- directional for a rough first estimate, not a
customer's actual contracted rate (reserved pricing, committed-use
discounts, and on-prem amortized cost all differ, often substantially).
A real deployment should always set GPU_HOURLY_RATES_JSON to the
customer's own rate card; shipping a wrong "savings" number computed
against a rate the customer doesn't actually pay would undermine the
one thing this whole product is selling: trustworthy dollar figures.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from ingestion_normalization.capability import GPUCapability

ILLUSTRATIVE_DEFAULT_SOURCE = "illustrative_public_list_price"
CUSTOMER_PROVIDED_SOURCE = "customer_provided_rate"
UNKNOWN_SOURCE = "unknown"

# $/hour, keyed by GPUCapability.canonical_name. Approximate, directional
# public on-demand figures -- see module docstring.
_ILLUSTRATIVE_DEFAULT_RATES: dict[str, float] = {
    "NVIDIA H100 SXM5 80GB": 6.00,
    "NVIDIA H100 PCIe 80GB": 4.50,
    "NVIDIA A100 80GB": 3.50,
    "NVIDIA A100 40GB": 2.50,
    "NVIDIA L40S": 2.00,
    "NVIDIA L4": 0.80,
    "NVIDIA A10": 1.20,
    "NVIDIA V100 16GB": 2.00,
    "NVIDIA T4": 0.50,
}


@dataclass(frozen=True)
class GPUPrice:
    canonical_name: str
    hourly_usd: float | None
    source: str

    @property
    def known(self) -> bool:
        return self.source != UNKNOWN_SOURCE


def parse_rate_overrides(gpu_hourly_rates_json: str | None) -> dict[str, float]:
    if not gpu_hourly_rates_json:
        return {}
    try:
        parsed = json.loads(gpu_hourly_rates_json)
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(k): float(v) for k, v in parsed.items()}


def lookup_price(capability: GPUCapability, rate_overrides: dict[str, float]) -> GPUPrice:
    """Price a GPU by its capability-table canonical name.

    An unknown GPU model (capability.known is False) or a model with no
    rate in either the customer's overrides or the illustrative defaults
    returns an explicit unknown price rather than a guessed one -- a
    finding tied to it should be reported as unpriceable, not silently
    priced at $0 or some arbitrary default.
    """
    if not capability.known:
        return GPUPrice(canonical_name=capability.canonical_name, hourly_usd=None, source=UNKNOWN_SOURCE)

    if capability.canonical_name in rate_overrides:
        return GPUPrice(
            canonical_name=capability.canonical_name,
            hourly_usd=rate_overrides[capability.canonical_name],
            source=CUSTOMER_PROVIDED_SOURCE,
        )

    if capability.canonical_name in _ILLUSTRATIVE_DEFAULT_RATES:
        return GPUPrice(
            canonical_name=capability.canonical_name,
            hourly_usd=_ILLUSTRATIVE_DEFAULT_RATES[capability.canonical_name],
            source=ILLUSTRATIVE_DEFAULT_SOURCE,
        )

    return GPUPrice(canonical_name=capability.canonical_name, hourly_usd=None, source=UNKNOWN_SOURCE)
