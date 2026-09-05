"""The dollar-impact estimate produced for one waste finding."""
from __future__ import annotations

from dataclasses import dataclass

# The finding's window already happened: this is money already spent with
# no value produced during it. No extrapolation -- it's a lower bound on
# actual, already-incurred waste.
BASIS_OBSERVED_WINDOW = "observed_window"

# Extrapolated from an observed rate (a persistent over-provisioned state,
# a fragmentation pattern, or a recurring calendar pattern), assuming it
# continues. Always labeled as a projection, never presented as certain.
BASIS_PROJECTED_MONTHLY = "projected_monthly"


@dataclass
class SavingsEstimate:
    finding_id: int
    category: str
    node: str
    gpu_index: str
    gpu_instance_id: str | None
    namespace: str
    workload: str | None
    window_start: float
    window_end: float
    confidence: float
    priceable: bool
    basis: str | None
    amount_usd: float | None
    recommended_action: str
    methodology: str
