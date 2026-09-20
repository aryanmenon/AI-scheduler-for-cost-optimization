# Fragmentation / realistic-traffic / real-duration test

Covers three items from the pre-pilot list in one rental:

1. **Fragmentation** — needs >= 2 GPUs and >= 2 distinct workloads
   underutilized on the same node at once. No amount of threshold-lowering
   can substitute for this; it's a scenario requirement, not a time one.
2. **Realistic traffic** — a real tiny model actually doing inference,
   hit with a randomized bursty load, instead of a scripted idle/stress
   toggle.
3. **Real duration** — run against the *real* pilot-default thresholds
   (`values-extended-test.yaml` changes nothing but poll cadence), so a
   finding here means the actual evidence bar was met, not a lowered one.

What this does **not** cover: heterogeneous GPU SKUs, or a real managed
Kubernetes cluster's own quirks (StorageClass, RBAC, network policy).
Those need a different rental shape — see the root README's pilot-gap
discussion.

## Prerequisites

- A rented instance with **>= 2 GPUs** and a working Kubernetes
  distribution + NVIDIA device plugin already installed (however you set
  up the collector-only smoke test, just with a multi-GPU instance type
  this time).
- `kubectl` pointed at it.
- Confirm the device plugin is actually exposing GPUs before deploying
  anything: `kubectl get nodes -o json | jq '.items[].status.capacity."nvidia.com/gpu"'`
  should show a number >= 2. If it's missing or 0, the fragmentation test
  can't run no matter what else is correct -- fix the device plugin first.

## 1. Build the test model server (on the rented box, no registry needed)

```bash
cd testing/fragmentation-and-load-test
docker build -t tiny-model-server:test .
```

Single-node cluster assumption: the image just needs to exist in the
node's local image cache for `imagePullPolicy: IfNotPresent` to find it.
If your Kubernetes distribution uses a separate container runtime
namespace from plain `docker` (k3s with containerd, for example), import
it explicitly instead, e.g.:

```bash
docker save tiny-model-server:test | k3s ctr images import -
```

## 2. Deploy the two workloads

```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/workload-a.yaml
kubectl apply -f k8s/workload-b.yaml
kubectl -n inference get pods -o wide   # confirm each pod landed and is Running
```

Confirm they actually got assigned to *different* GPUs (this is normally
automatic with 2 single-GPU requests and >= 2 GPUs on one node, but worth
checking once):

```bash
kubectl -n inference exec deploy/tiny-model-a -- nvidia-smi -L
kubectl -n inference exec deploy/tiny-model-b -- nvidia-smi -L
```

## 3. Deploy the actual product

Run this from the repo root (not from `testing/fragmentation-and-load-test/`):

```bash
helm install gpu-telemetry deploy/helm/gpu-telemetry-collector \
  --namespace gpu-optimizer --create-namespace \
  -f deploy/helm/gpu-telemetry-collector/values.yaml \
  -f deploy/helm/gpu-telemetry-collector/values-extended-test.yaml
```

## 4. Start the bursty load

From outside the cluster (your own machine, or a shell on the rented box),
back in `testing/fragmentation-and-load-test/`:

```bash
kubectl -n inference port-forward svc/tiny-model-a 8001:8000 &
kubectl -n inference port-forward svc/tiny-model-b 8002:8000 &

pip install requests
python load_generator.py \
  --target a=http://localhost:8001/generate \
  --target b=http://localhost:8002/generate \
  --duration-hours 24
```

Leave it running. Both workloads get independent, randomized burst/quiet
cycles (default: 60-300s bursts, 300-1800s quiet) -- enough variation that
neither should sit at a suspiciously constant utilization level.

## 5. What to expect, and when

| Detector | Real-time floor | What you're looking for |
|---|---|---|
| Idle | never (unless a quiet gap happens to exceed 4h) | Not the target of this test -- if it fires, a burst/quiet gap ran long by chance |
| Over-provisioned | 24h | Peak utilization across a full day never exceeding 30% -- plausible for a tiny model under bursty load |
| Fragmented | 4h | The one this test is built for: 2 GPUs, 2 workloads, both underutilized at once |
| Recurring pattern | 7 calendar days | Only if you leave it running that long, and only if the random schedule happens to leave a consistent low-usage hour-of-day -- not guaranteed by this generator's pure randomness |

Check progress via the dashboard (see the root README for the auth-token
retrieval command) or directly:

```bash
kubectl -n gpu-optimizer logs deploy/gpu-telemetry-collector -c waste-detector -f
```

## 6. Tear down

```bash
kubectl delete -f k8s/workload-a.yaml -f k8s/workload-b.yaml
helm uninstall gpu-telemetry -n gpu-optimizer
```
