# GPU Cost Optimizer — Pilot Guide

For the engineer who installs and evaluates the product during a pilot.

## What it does

Finds GPU waste in a Kubernetes cluster and prices it in ₹:

| Finding | What it means | Shown as |
|---|---|---|
| Idle GPU | A GPU allocated to a workload but essentially unused for 4+ hours | ₹ already wasted in that window |
| Over-provisioned | A workload whose peak load never needs its GPU over 24+ hours | ₹/month saved by a smaller GPU |
| Oversized for its average load | A request-serving workload (e.g. an LLM server) whose busiest hour averages low, though momentary peaks look high | ₹/month saved by a smaller GPU |
| Recurring low-usage pattern | The same hours of the day are quiet on most of 7+ days | ₹/month saved by scaling down in those hours |
| Fragmented capacity | Several underused GPUs on one node that might share GPUs | Review candidate (see limits) |
| Multi-GPU job could use fewer GPUs | A job's GPUs are mostly idle | Review candidate, upper bound |
| Detected, no recommendation yet | Below-target GPU time nothing above explains, incl. GPU time with no pod | ₹ already wasted |

Every recommendation to move to a smaller GPU is checked against three
things the workload can run out of — compute, memory bandwidth and memory
capacity — and states what it costs you:

> right-size to NVIDIA A10 (each request may take up to ~1.6x longer -- fine
> for batch/offline work, check latency targets before moving an interactive
> service)

When memory fit can't be determined (vLLM and TensorFlow pre-allocate most
of the GPU, hiding real need), the recommendation says "memory fit not
checked" instead of guessing.

## What it does not do

- **It changes nothing in your cluster.** It only observes and reports.
  Acting on a recommendation is always your decision and your change.
- It does not see inside your application (latency, request rates). Latency
  impact is a stated estimate, not a measurement.
- "Fragmented capacity" does not check whether your cluster has GPU sharing
  (time-slicing, MPS, MIG) enabled or whether the workloads' memory fits
  together. Treat those as questions to review, not actions.

## Security and data

- **No data leaves your cluster.** All telemetry, findings and estimates
  live in SQLite files on a PersistentVolume in the product's namespace.
  The only outbound call the product can make is an optional alert webhook
  you configure yourself (`alerting.webhookUrl`, empty by default).
- **Read-only Kubernetes access.** The only RBAC granted is
  `get/list/watch` on `pods`, `nodes`, `namespaces` (for kube-state-metrics,
  to attribute GPUs to workloads). Nothing can create, update or delete.
  The collector itself gets no Kubernetes API token at all.
- **One privileged component, and how to avoid it.** To read GPU metrics,
  the chart's own dcgm-exporter (NVIDIA's standard exporter) runs
  `privileged` with `SYS_ADMIN` and host mounts of `/dev` and the kubelet's
  pod-resources socket — the same access NVIDIA's own exporter needs. If
  your cluster already runs NVIDIA's dcgm-exporter (GPU Operator), install
  with `--set dcgmExporter.enabled=false` and the product deploys **no
  privileged pod**: it reads your existing exporter instead.
- **Dashboard access** is a bearer token generated at install, reached via
  `kubectl port-forward` (encrypted through the API server). The Service is
  `ClusterIP` by default — not exposed outside the cluster.
- Every product container runs as non-root with a read-only root
  filesystem.
- The product ships as compiled code. Everything you'd review for
  security — the Helm chart, every Kubernetes resource and permission it
  creates, configuration and logs — is plain text.

## Requirements

- Kubernetes with NVIDIA GPU nodes (driver + NVIDIA device plugin, or the
  GPU Operator), Helm 3, `kubectl` access to create one namespace.
- GPU nodes labeled `nvidia.com/gpu.present=true` (set automatically by
  NVIDIA GPU Feature Discovery / GPU Operator).
- A StorageClass for a 5 GiB PersistentVolumeClaim.
- Footprint: one pod running five small containers (requests ~0.2 CPU,
  ~0.6 GiB memory in total), plus kube-state-metrics, plus one dcgm-exporter
  per GPU node unless you reuse yours.

## Install (about 15 minutes)

You'll receive the chart and an image pull credential from us.

```bash
kubectl create namespace gpu-optimizer
kubectl create secret docker-registry ghcr-secret -n gpu-optimizer \
  --docker-server=ghcr.io --docker-username=<from us> --docker-password=<from us>

# Your real ₹/hour per GPU model, so every rupee figure is yours, not a list price:
cat > rates.yaml <<'YAML'
savingsEstimator:
  gpuHourlyRatesJson: '{"NVIDIA A100 80GB": 300, "NVIDIA L4": 70}'
global:
  imagePullSecrets:
    - name: ghcr-secret
YAML

helm install gpu-optimizer ./gpu-telemetry-collector -n gpu-optimizer -f rates.yaml
# Already running NVIDIA's dcgm-exporter (GPU Operator)? add:
#   --set dcgmExporter.enabled=false
```

## Check it's working (first hour)

```bash
kubectl -n gpu-optimizer get pods            # all Running
kubectl -n gpu-optimizer logs deploy/gpu-optimizer-collector -c telemetry-collector --tail=5
```

The collector logs one JSON line per scrape (`"event": "cycle_complete"`)
with `rows_out` (GPU samples stored), `errors`, and how many samples were
`attributed` to a pod versus `unattributed`. GPUs running workloads should
be attributed; if `attributed` stays 0 while workloads run, tell us — on
some clusters one setting (`dcgmExporter.kubernetesGpuIdType`) needs
changing.

## When findings appear

| Finding | Earliest |
|---|---|
| Idle, fragmented | ~4 hours |
| Over-provisioned, oversized by average load | ~24 hours |
| Recurring patterns | ~7 days |

Run the pilot for at least 7 days before the review.

## Reading the report

```bash
kubectl -n gpu-optimizer get secret gpu-optimizer-dashboard-auth \
  -o jsonpath='{.data.DASHBOARD_AUTH_TOKEN}' | base64 -d; echo
kubectl -n gpu-optimizer port-forward svc/gpu-optimizer-dashboard 8080:8080
curl -H "Authorization: Bearer <token>" http://localhost:8080/ > report.html
```

The headline counts each GPU once. "Already wasted" figures are money
spent in the observed window; "/mo" figures assume today's usage continues.
**Recoverable Ceiling** is the most any optimization could save on the last
7 days observed: the cost of GPU capacity below 70% busy, as if every
workload could be packed perfectly. It's a ceiling, not a forecast, shown next
to how much of it the recommendations capture.
See `sample-report.html` for what a report looks like.

## Uninstall (2 minutes, leaves nothing behind)

```bash
helm uninstall gpu-optimizer -n gpu-optimizer
kubectl delete namespace gpu-optimizer        # also deletes the stored data
```

`helm uninstall` reports that it kept `gpu-optimizer-dashboard-auth`: the
chart keeps the dashboard token across upgrades on purpose. Deleting the
namespace removes it.

With `dcgmExporter.enabled=false`, the small headless Service the chart
placed next to your existing exporter is removed by `helm uninstall` too.

The product's images stay in your nodes' image cache until the container
runtime garbage-collects them. To remove them right away, on each GPU
node:

```bash
crictl images | awk '/ai-scheduler-for-cost-optimization/{print $3}' | xargs -r crictl rmi
```

(Rehearsed end to end on a live GPU cluster on 2026-10-04: nothing left
behind.)

## If a finding looks wrong

Tell us the finding (copy its row). We will explain exactly which numbers
produced it, and if it is wrong we fix the product, not the report. Wrong
findings during a pilot are the most useful thing you can give us.
