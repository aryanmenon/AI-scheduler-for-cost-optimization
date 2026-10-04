"""The rupee-impact estimate produced for one waste finding."""
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

# A projected monthly figure for a signal that is visibility only: sized
# from evidence too weak to stand behind as a recommendation (see
# waste_detector.multi_gpu). Reported as an upper bound and kept out of the
# dashboard's headline savings total.
BASIS_VISIBILITY_UPPER_BOUND = "visibility_upper_bound"

# Waste that is detected and measured but has no reliable recommendation
# (see waste_detector.unrecommended). Priced like an idle finding -- money
# already spent on capacity below the efficient-use target during the
# observed window, not a projection -- and shown below the actionable
# findings, never in the headline totals.
BASIS_DETECTED_NO_RECOMMENDATION = "detected_no_recommendation"


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
    amount_inr: float | None
    recommended_action: str
    methodology: str
