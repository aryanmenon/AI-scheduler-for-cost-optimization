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

## Security: this server speaks plain HTTP -- know what protects the token

`server.py` has no TLS of its own. `DASHBOARD_AUTH_TOKEN` (checked with a
constant-time comparison, see `_authorized()`) is a bearer token, and a
bearer token sent over a connection that isn't encrypted is exactly as
good as no token at all -- so what protects it depends entirely on how
you reach this server:

- **`kubectl port-forward` is safe as-is.** It's tunneled through the
  Kubernetes API server's own TLS/mTLS connection (kubectl authenticates
  to the API server over HTTPS, and the forwarded stream rides inside
  that same connection) -- the token and every cost figure in the report
  stay encrypted end to end. This is the deployment path the Helm chart
  defaults to (`dashboard.serviceType: ClusterIP`), and it needs nothing
  extra from you.
- **Anything else does not inherit that protection.** Setting
  `dashboard.serviceType` to `LoadBalancer`/`NodePort`, or putting an
  Ingress in front, exposes this server directly -- if that path isn't
  independently TLS-terminated (Ingress TLS, a load balancer with a real
  cert, a service mesh's mTLS, etc.), the bearer token and the full
  contents of the report travel in plaintext to anyone positioned to
  observe that connection.
- **No token configured at all** means the report is served to anyone
  who can reach the port, full stop -- `run_server()` logs a warning on
  startup if this is the case, but still starts. Set
  `dashboard.authToken` (or let the Helm chart auto-generate one; see its
  NOTES.txt) for anything beyond a disposable local/dev instance.

The short version: don't change `serviceType` away from `ClusterIP`
without first deciding, deliberately, where TLS gets terminated.
