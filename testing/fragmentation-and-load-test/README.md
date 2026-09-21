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

- A rented instance with **>= 2 GPUs**, a **Linux Virtual Machine**
  instance type (see step 0 below -- this matters, don't skip it), and
  Kubernetes + the NVIDIA device plugin installed on it per step 0.
- `kubectl` pointed at it.
- Confirm the device plugin is actually exposing GPUs before deploying
  anything: `kubectl get nodes -o json | jq '.items[].status.capacity."nvidia.com/gpu"'`
  should show a number >= 2. If it's missing or 0, the fragmentation test
  can't run no matter what else is correct -- fix the device plugin first.

## 0. Rent the box and bring up Kubernetes

**Rent a VM instance type, not the default container instance type.**
vast.ai's default/most common instance type is itself a Docker container --
it explicitly blocks nested virtualization, privileged workloads, and
kernel module loading. k3s needs to run its own containerd, manage its own
cgroups/CNI, and the NVIDIA device plugin needs a *second* layer of real
GPU passthrough into the pods k3s schedules -- none of that works inside
that container-instance type, no matter how correctly it's configured.
vast.ai separately offers a **Linux Virtual Machine** instance type (full
root, systemd, SSH-only access) whose own docs list Kubernetes and
Docker-in-Docker as supported use cases -- rent that type, with >= 2 GPUs,
for this test. (If this is why an earlier attempt at this stalled: this is
almost certainly it -- it's a platform restriction on the container
instance type, not a config mistake.)

Once SSH'd into the VM instance:

```bash
# 1. Install k3s (bundles containerd, so no separate Docker/Kubernetes install needed)
curl -sfL https://get.k3s.io | sh -

# 2. Install the NVIDIA Container Toolkit so containerd can talk to the GPUs
#    (see NVIDIA's current install docs for your distro's package manager;
#    on Ubuntu/Debian this is the nvidia-container-toolkit apt package)

# 3. Point k3s's bundled containerd at the nvidia runtime
sudo mkdir -p /var/lib/rancher/k3s/agent/etc/containerd
cat <<'EOF' | sudo tee /var/lib/rancher/k3s/agent/etc/containerd/config.toml.tmpl
{{ template "base" . }}

[plugins.'io.containerd.cri.v1.runtime'.containerd.runtimes.nvidia]
  runtime_type = "io.containerd.runc.v2"
  [plugins.'io.containerd.cri.v1.runtime'.containerd.runtimes.nvidia.options]
    BinaryName = "/usr/bin/nvidia-container-runtime"
EOF
sudo systemctl restart k3s

# 4. Deploy the NVIDIA device plugin DaemonSet (pick the current release tag
#    from https://github.com/NVIDIA/k8s-device-plugin -- version pinned
#    deliberately omitted here so this doesn't silently go stale)
kubectl apply -f https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/<release-tag>/deployments/static/nvidia-device-plugin.yml

# 5. Verify -- this must show a number >= 2 before going any further
kubectl get nodes -o json | jq '.items[].status.capacity."nvidia.com/gpu"'
```

If step 5 comes back missing or 0, don't proceed to the rest of this
runbook -- check `kubectl -n kube-system logs -l name=nvidia-device-plugin-ds`
first; the usual cause is the containerd runtime config in step 3 not
matching the actual `nvidia-container-runtime` binary path (`which
nvidia-container-runtime` to confirm) or the toolkit from step 2 not
actually being installed yet when k3s was restarted.

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
