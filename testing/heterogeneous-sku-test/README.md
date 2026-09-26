# Heterogeneous GPU SKU test

Item 2 of the 3-item pre-pilot list, decoupled from item 3 (real managed
cluster) per the split-plan decision -- see `PROGRESS.md`. This test
targets a different thing than `../fragmentation-and-load-test/`:

- That test proved detection logic (Fragmented/Over-provisioned) fires
  correctly under real load and real thresholds, on identical GPUs.
- This test proves the layer *above* detection: that
  `ingestion-normalization/capability.py` correctly identifies two
  **different** real GPU models from real DCGM output, that
  `effective_tflops` scales correctly per model, and that
  `savings-estimator` prices each one at its own correct rate rather than
  conflating them.

Because of that, this test does **not** need 2 GPUs on one node (that's
fragmentation's setup) -- it needs 2 *different* GPU models, one per node,
in the same cluster. Also does not need a 24h+ run: idle/over-provisioned
only need their (lowered, smoke-test) thresholds met, not a re-proof of
the real 24h floor already proven by the other test.

**If the only available recognized SKUs (T4/A10/L4/V100/L40S/A100/H100)
are unavailable again and you're using consumer GPUs instead** (e.g. RTX
3090 + RTX 3060): `capability.py` now recognizes these too
(`GPUCapability.recommendable=False` keeps them out of right-sizing
recommendations elsewhere, but they're still priced like any other known
GPU -- see `PROGRESS.md` section 2 for why this needed a real fix, not
just adding table entries). Step 8's "two distinct priced INR rates"
success criterion still applies as written.

## 0. Check availability and rent two different recognized GPU types

Recognized by `capability.py` (only these get priced): `T4`, `A10`, `L4`,
`V100`, `L40S`, `A100`, `H100`. Cheapest-first is the likely order to find
available on vast.ai:

```bash
vastai search offers 'vms_enabled=true num_gpus>=1' -o 'dph_total'
```

Pick **two different** recognized types from whatever's actually
available today (availability has been inconsistent every time this has
been checked). Rent both as **VM instance type** (not the default
container instance -- same reasoning as the fragmentation test: k3s needs
real nested virtualization). Add your SSH key before renting either.

No need to expose any extra port for this -- vast.ai only lets you add
exposed ports at template configuration time, before an instance launches,
not to an already-running one. Step 2 below uses an SSH tunnel instead,
which works against SSH alone (every VM instance already has it) and
needs no template changes either way. It's also the better choice
regardless: it keeps k3s's API server off the public internet entirely,
rather than exposing it and relying on the join token alone as the
security boundary.

Don't use vast.ai's own native multi-node "Clusters" feature for this --
it requires specific machines with non-NATed IPs in a shared subnet,
which isn't reliably available for two independently-rented instances.

## 0.5. Both instances' SSH info

Once both are running, note each one's SSH connection details (host +
port) from the vast.ai console -- you'll need node A's to open the tunnel
in step 2.

## 1. Bring up k3s on node A (the server)

SSH into the first instance and follow `../fragmentation-and-load-test/README.md`
step 0's sequence (k3s install, NVIDIA Container Toolkit, containerd
runtime config, device plugin DaemonSet) -- identical process, just this
node becomes the cluster's server instead of a single-node cluster.

Then get the join token for step 2:
```bash
sudo cat /var/lib/rancher/k3s/server/node-token
```

## 2. Join node B (the agent)

SSH into the second instance. Install the NVIDIA Container Toolkit +
containerd runtime config the same way (steps 2-3 of the fragmentation
README's step 0). Before joining, open an SSH tunnel from this instance
to node A so k3s's API server is reachable without exposing it publicly:

```bash
ssh -N -L 6443:localhost:6443 -p <NODE_A_SSH_PORT> root@<NODE_A_SSH_HOST> &
```

Then install k3s as an **agent**, joining through the tunnel (`127.0.0.1`
here means "through the tunnel to node A", not node B itself):

```bash
curl -sfL https://get.k3s.io | K3S_URL=https://127.0.0.1:6443 \
  K3S_TOKEN=<token from step 1> sh -
```

Keep the SSH tunnel (the `ssh -N -L ...` from above) running in the
background for as long as this test runs -- if it drops, node B loses
contact with the cluster's API server. Reopen it if your session gets
interrupted.

The device plugin DaemonSet from step 1 will automatically schedule a
copy onto this new node once it joins -- no need to redeploy it.

## 3. Verify both nodes and note their names

From node A (the server):
```bash
kubectl get nodes -o wide
kubectl get nodes -o json | jq '.items[].status.capacity."nvidia.com/gpu"'
```
Should show 2 nodes, each with `nvidia.com/gpu: "1"`. Note each node's
`NAME` column -- you'll substitute these for `NODE_A_NAME`/`NODE_B_NAME`
in `k8s/workload-a.yaml`/`k8s/workload-b.yaml` in step 5.

**Also verify the dcgm-exporter NODE_NAME fix here** (see `PROGRESS.md`'s
4th bug, fixed but never confirmed against live hardware):
```bash
kubectl -n gpu-optimizer get pods -o wide | grep dcgm-exporter
# for each dcgm-exporter pod:
kubectl -n gpu-optimizer exec <pod-name> -- curl -s localhost:9400/metrics | grep -m1 Hostname
```
Each should show that pod's real node name (matching `kubectl get nodes`),
not another `gpu-telemetry-dcgm-exporter-<random-suffix>` pod name. If it
still shows a pod name, stop and fix that before trusting any per-node
finding in this test -- the whole point of this test collapses if `node`
identity is wrong.

(Chart isn't installed yet at this point in the sequence -- these
`kubectl` commands assume you've done step 6 first, or just check the raw
DCGM metrics endpoint directly via `kubectl port-forward` against the
DaemonSet pods once they exist. Reorder as convenient; the check itself
matters more than exactly when you run it.)

## 4. Build the test image on BOTH nodes

Unlike the single-node fragmentation test, there's no shared local image
cache here -- build (or import) the same image on each node separately:

```bash
cd testing/fragmentation-and-load-test   # reusing that test's Dockerfile/server.py as-is
docker build -t tiny-model-server:test .
docker save tiny-model-server:test | k3s ctr images import -
```
Repeat on both node A and node B.

## 5. Deploy the node-pinned workloads

Edit `k8s/workload-a.yaml` and `k8s/workload-b.yaml`, replacing
`NODE_A_NAME`/`NODE_B_NAME` with the real node names from step 3. Then:

```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/workload-a.yaml
kubectl apply -f k8s/workload-b.yaml
kubectl -n inference get pods -o wide   # confirm each landed on the right node
```

## 6. Deploy the product

From the repo root, with the fast smoke-test overlay (this test doesn't
need the real 24h/4h floors -- those are already proven; here you just
need idle/over-provisioned to fire quickly so you can see two distinct
priced GPU rows):

```bash
helm install gpu-telemetry deploy/helm/gpu-telemetry-collector \
  --namespace gpu-optimizer --create-namespace \
  -f deploy/helm/gpu-telemetry-collector/values.yaml \
  -f deploy/helm/gpu-telemetry-collector/values-smoke-test.yaml
```
Don't forget the GHCR pull secret and GPU node label steps from the root
README's prerequisites section if you haven't already -- both nodes need
`nvidia.com/gpu.present=true` labeled (repeat the `kubectl label node`
command for each node name).

## 7. Start bursty load on both

```bash
kubectl -n inference port-forward svc/tiny-model-a 8001:8000 &
kubectl -n inference port-forward svc/tiny-model-b 8002:8000 &

cd testing/fragmentation-and-load-test
pip install requests
python load_generator.py \
  --target a=http://localhost:8001/generate \
  --target b=http://localhost:8002/generate \
  --duration-hours 4
```
4 hours is enough here -- smoke-test thresholds need only ~1h streaks.

## 8. What to check

```bash
kubectl -n gpu-optimizer exec deploy/gpu-telemetry-collector -c waste-detector -- python3 -c "
import sqlite3
conn = sqlite3.connect('/data/findings/findings.db')
cur = conn.cursor()
cur.execute('SELECT category, node, gpu_index, workload, metric_value FROM waste_findings ORDER BY id DESC')
for row in cur.fetchall(): print(row)
"
```
You're looking for: two findings on two different `node` values (the real
node names, per step 3's verification), each tied to a different GPU
model. Then check the dashboard (root README's auth-token command) shows
**two distinct priced INR rates**, not the same rate twice and not both
landing in "Not priced."

## 9. Teardown

```bash
kubectl delete -f k8s/workload-a.yaml -f k8s/workload-b.yaml
helm uninstall gpu-telemetry -n gpu-optimizer
```
Then destroy both vast.ai instances from the console to actually stop
billing.
