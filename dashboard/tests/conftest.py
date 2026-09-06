"""Test-only dependency on savings-estimator's real storage, so reader
tests exercise the actual schema (see report_reader.py's docstring on why
production code reads it directly rather than importing savings_estimator).

pip install -e ../savings-estimator -e ".[dev]" before running tests.
Note: only savings_estimator.storage/estimate are imported here, which do
NOT transitively import ingestion_normalization or waste_detector, so
those two don't need to be installed just for dashboard's tests.
"""
from savings_estimator.estimate import SavingsEstimate
from savings_estimator.storage import SavingsStorage


def make_estimate(
    finding_id: int,
    category: str = "idle",
    node: str = "gpu-node-1",
    gpu_index: str = "0",
    gpu_instance_id: str | None = None,
    namespace: str = "inference",
    workload: str | None = "bert-large",
    window_start: float = 0.0,
    window_end: float = 3600.0,
    confidence: float = 0.9,
    priceable: bool = True,
    basis: str | None = "observed_window",
    amount_inr: float | None = 14.0,
    recommended_action: str = "terminate",
    methodology: str = "test methodology",
) -> SavingsEstimate:
    return SavingsEstimate(
        finding_id=finding_id,
        category=category,
        node=node,
        gpu_index=gpu_index,
        gpu_instance_id=gpu_instance_id,
        namespace=namespace,
        workload=workload,
        window_start=window_start,
        window_end=window_end,
        confidence=confidence,
        priceable=priceable,
        basis=basis if priceable else None,
        amount_inr=amount_inr if priceable else None,
        recommended_action=recommended_action,
        methodology=methodology,
    )


def write_estimates(path: str, estimates: list[SavingsEstimate], estimated_at: float = 1000.0) -> None:
    storage = SavingsStorage(path)
    storage.insert_estimates(estimates, estimated_at=estimated_at)
    storage.close()
