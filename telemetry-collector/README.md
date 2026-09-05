# telemetry-collector

Phase 1, Component 1 of the GPU cost-optimization SaaS: a read-only agent
that scrapes DCGM exporter and kube-state-metrics on a customer's cluster,
correlates each GPU's utilization/memory/power to the pod that owns it, and
stores a time series in SQLite for the downstream waste-detector and
savings-estimator to consume.

## Local development

```bash
pip install -e ".[dev]"
pytest
```

## Running standalone

```bash
export DCGM_EXPORTER_URL=http://localhost:9400/metrics
export KUBE_STATE_METRICS_URL=http://localhost:8080/metrics
export TELEMETRY_SQLITE_PATH=./telemetry.db
telemetry-collector
```

## Design notes

- **Attribution over guessing**: DCGM exporter's kubernetes-pod-resources
  integration attaches `namespace`/`pod`/`container` labels directly to GPU
  samples on most clusters. Where that isn't enabled, a GPU is recorded as
  `unattributed` rather than heuristically guessed — a wrong attribution is
  worse than an honest "we don't know" for a product whose job is to tell
  customers where their money is going.
- **A secondary-source failure never loses primary data**: if
  kube-state-metrics is unreachable, DCGM's GPU metrics are still stored;
  only a DCGM scrape failure marks the whole cycle failed.
- **SQLite in WAL mode**: safe for a dashboard to read concurrently while
  the collector writes every scrape interval, and crash-safe if the pod is
  killed mid-write.

See `../deploy/helm/gpu-telemetry-collector` for the one-command cluster
install.
