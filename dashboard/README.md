# dashboard

Phase 1, Component 5 of the GPU cost-optimization SaaS: the self-serve
sales artifact. Renders savings-estimator's priced findings as a report --
both as a live page (for the customer to check anytime) and as a
standalone HTML file (for a salesperson to attach to an email).

## Two ways to get the report

**Live, always-current:**

```bash
dashboard-server
# serves on :8080 (DASHBOARD_PORT), regenerating from current data on every request
```

**A static file to hand someone:**

```bash
generate-report
# writes REPORT_OUTPUT_PATH (default ./report.html) -- self-contained,
# no external requests, opens in any browser offline
```

Both share the exact same read → aggregate → render path (`report.py`), so
they're always identical for the same underlying data.

## What the report shows, and why it's split the way it is

- **Two headline numbers, never added together**: "Projected Monthly
  Savings" (over-provisioned/fragmented/recurring-pattern findings,
  extrapolated from a sustained observed rate) and "Already-Wasted Spend
  Observed" (idle findings, priced strictly against their own observed
  window). Combining a monthly rate with a one-off observed figure would
  produce a number that overstates both -- see
  `../savings-estimator/README.md`'s basis table for the full reasoning
  this report inherits.
- **A "not priced" section**, not a silent omission, for findings whose
  GPU model or rate is unknown -- the point is to be auditable, not to
  make the biggest number possible.
- **Methodology text inline** under every top finding, so whoever's
  championing this internally can explain any number without having to
  come back and ask.

## Local development

```bash
pip install -e ../savings-estimator -e ".[dev]"  # dev-only, for test fixtures
pytest
```

Note: dashboard's production code has zero runtime dependencies (stdlib
only -- `http.server` for the live page, plain f-string HTML rendering, no
templating engine). The savings-estimator install above is only for
building realistic test fixtures against its real SQLite schema.

## Design notes

- **Component boundary is the schema, not shared code**, same as every
  reader before this one: `report_reader.py` connects to
  savings-estimator's `savings.db` read-only.
- **HTML-escaped throughout.** Workload/namespace/node names ultimately
  come from a customer's own cluster and aren't trusted as safe markup.
- **No caching, no build step.** This is a low-traffic internal tool
  where "always reflects the latest data" matters more than avoiding a
  cheap re-render on each request.

See `../deploy/helm/gpu-telemetry-collector` for how this is exposed
in-cluster (a Service in front of the collector pod, so `kubectl
port-forward` reaches it without any extra infrastructure).
