"""GPU hourly cost lookup, keyed to capability.py's canonical SKU names.

All figures are INR (Indian Rupees) per hour -- this product is sold to
Indian customers, and a dollar figure they'd have to convert themselves
defeats the point of a ready-to-use savings estimate. The defaults below
are illustrative Indian GPU-cloud on-demand list-price approximations --
directional for a rough first estimate, not a customer's actual
contracted rate (reserved pricing, committed-use discounts, and on-prem
amortized cost all differ, often substantially). A real deployment
should always set GPU_HOURLY_RATES_JSON to the customer's own rate card;
shipping a wrong "savings" number computed against a rate the customer
doesn't actually pay would undermine the one thing this whole product is
selling: trustworthy rupee figures.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from ingestion_normalization.capability import GPUCapability

logger = logging.getLogger(__name__)

ILLUSTRATIVE_DEFAULT_SOURCE = "illustrative_public_list_price"
CUSTOMER_PROVIDED_SOURCE = "customer_provided_rate"
UNKNOWN_SOURCE = "unknown"

# INR/hour, keyed by GPUCapability.canonical_name. Approximate, directional
# Indian GPU-cloud on-demand figures -- see module docstring.
_ILLUSTRATIVE_DEFAULT_RATES: dict[str, float] = {
    "NVIDIA H100 SXM5 80GB": 520.00,
    "NVIDIA H100 PCIe 80GB": 390.00,
    "NVIDIA A100 80GB": 300.00,
    "NVIDIA A100 40GB": 220.00,
    "NVIDIA L40S": 175.00,
    "NVIDIA L4": 70.00,
    "NVIDIA A10": 105.00,
    "NVIDIA V100 16GB": 175.00,
    "NVIDIA T4": 45.00,
    # Consumer/gaming SKUs -- priceable (capability.recommendable=False
    # keeps them out of right-sizing recommendations elsewhere, see
    # ceiling.py) but real customer hardware nonetheless, worth pricing
    # correctly for their own findings. Rougher estimates than the
    # datacenter rows above: RTX 4060 anchored to a real vast.ai on-demand
    # rate actually seen this session (~$0.24/GPU/hr); the other two are
    # directional guesses scaled off that anchor, not independently
    # verified against live listings.
    "NVIDIA GeForce RTX 3090": 35.00,
    "NVIDIA GeForce RTX 4060": 20.00,
    "NVIDIA GeForce RTX 4060 Ti": 28.00,
    "NVIDIA GeForce RTX 3060": 18.00,
    # Professional/workstation Ada card, not a GeForce gaming card -- see
    # capability.py's comment. No real rental rate observed this session
    # to anchor against; a rough guess between the GeForce range above and
    # true datacenter L4 pricing (NVIDIA T4).
    "NVIDIA RTX 4000 Ada Generation": 40.00,
}


@dataclass(frozen=True)
class GPUPrice:
    canonical_name: str
    hourly_inr: float | None
    source: str

    @property
    def known(self) -> bool:
        return self.source != UNKNOWN_SOURCE


def parse_rate_overrides(gpu_hourly_rates_json: str | None) -> dict[str, float]:
    """Parse GPU_HOURLY_RATES_JSON into a {canonical_name: hourly_inr} map.

    This runs once per pricing cycle (see pipeline.run_once), not once at
    startup -- so a single bad entry (valid JSON, non-numeric value; an easy
    admin typo) must never raise. Raising here would propagate out of
    run_once and, since the value doesn't change between cycles, silently
    zero out every future estimate forever rather than failing once and
    getting noticed. Bad entries are dropped and logged instead; the rest
    of a customer's rate card still takes effect.
    """
    if not gpu_hourly_rates_json:
        return {}
    try:
        parsed = json.loads(gpu_hourly_rates_json)
    except (json.JSONDecodeError, TypeError):
        logger.warning("GPU_HOURLY_RATES_JSON is not valid JSON; ignoring overrides")
        return {}
    if not isinstance(parsed, dict):
        logger.warning("GPU_HOURLY_RATES_JSON must be a JSON object; ignoring overrides")
        return {}

    overrides: dict[str, float] = {}
    for key, value in parsed.items():
        try:
            overrides[str(key)] = float(value)
        except (TypeError, ValueError):
            logger.warning(
                "GPU_HOURLY_RATES_JSON entry %r has a non-numeric value %r; skipping it",
                key, value,
            )
    return overrides


def lookup_price(capability: GPUCapability, rate_overrides: dict[str, float]) -> GPUPrice:
    """Price a GPU by its capability-table canonical name.

    An unknown GPU model (capability.known is False) or a model with no
    rate in either the customer's overrides or the illustrative defaults
    returns an explicit unknown price rather than a guessed one -- a
    finding tied to it should be reported as unpriceable, not silently
    priced at ₹0 or some arbitrary default.
    """
    if not capability.known:
        return GPUPrice(canonical_name=capability.canonical_name, hourly_inr=None, source=UNKNOWN_SOURCE)

    if capability.canonical_name in rate_overrides:
        return GPUPrice(
            canonical_name=capability.canonical_name,
            hourly_inr=rate_overrides[capability.canonical_name],
            source=CUSTOMER_PROVIDED_SOURCE,
        )

    if capability.canonical_name in _ILLUSTRATIVE_DEFAULT_RATES:
        return GPUPrice(
            canonical_name=capability.canonical_name,
            hourly_inr=_ILLUSTRATIVE_DEFAULT_RATES[capability.canonical_name],
            source=ILLUSTRATIVE_DEFAULT_SOURCE,
        )

    return GPUPrice(canonical_name=capability.canonical_name, hourly_inr=None, source=UNKNOWN_SOURCE)
