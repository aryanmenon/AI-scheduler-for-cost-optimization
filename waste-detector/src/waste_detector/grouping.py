"""Shared filter + group-by-key helpers used by every detector.

idle.py, over_provisioning.py, fragmentation.py, and patterns.py each
partition the same kind of "usable" rollup rows (attributed, sufficiently
covered, and -- for detectors whose math needs it -- a present
avg_utilization_pct) by their own grouping key before walking streaks or
computing an average. Centralizing the filter and the grouping mechanics
here means the shared predicate can't drift between detectors
independently, while each detector still owns its own key function.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Callable, Hashable, TypeVar

from waste_detector.config import Config
from waste_detector.rollup_reader import RollupRow

K = TypeVar("K", bound=Hashable)


def usable_rows(rows: list[RollupRow], config: Config, require_utilization: bool = False) -> list[RollupRow]:
    """Rows worth evaluating at all: attributed to a real workload, with
    enough coverage to trust. require_utilization additionally excludes
    rows with no avg_utilization_pct, for detectors that average it.
    """
    return [
        r for r in rows
        if r.attributed
        and r.coverage_ratio >= config.min_coverage_ratio
        and (not require_utilization or r.avg_utilization_pct is not None)
    ]


def group_by(rows: list[RollupRow], key_fn: Callable[[RollupRow], K]) -> dict[K, list[RollupRow]]:
    groups: dict[K, list[RollupRow]] = defaultdict(list)
    for row in rows:
        groups[key_fn(row)].append(row)
    return groups
