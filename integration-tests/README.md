# integration-tests

End-to-end proof that the five Phase 1 services actually work together, not
just that each one's own test suite is internally consistent.

## Why this exists

Every component's own tests (telemetry-collector, ingestion-normalization,
waste-detector, savings-estimator, dashboard) exercise it against
hand-built fixtures or a mocked upstream database -- each one *assumes* a
particular shape for its neighbor's schema rather than proving it. Five
green test suites don't tell you the five services actually agree on what
they're handing each other.

This suite wires each module's real `run_once`/entrypoint functions
together against real, on-disk SQLite files -- the same files a real
deployment would produce -- from a raw DCGM scrape all the way to a
rendered rupee figure in the dashboard's HTML. If a schema-boundary
assumption between two components is wrong, this is what catches it; a
unit test in either component individually cannot.

## Running it

Every component needs to be installed editable first (same requirement
each component's own README already states for cross-package imports):

```bash
pip install \
  -e ../telemetry-collector \
  -e ../ingestion-normalization \
  -e ../waste-detector \
  -e ../savings-estimator \
  -e ../dashboard \
  -e ".[dev]"
pytest
```

## What it does not replace

This is one golden-path scenario (a sustained idle GPU, end to end), not a
substitute for each component's own unit tests -- those still own
correctness of their internal logic (threshold semantics, pricing math,
escaping, etc.). This suite's only job is proving the handoffs between
components are real.
