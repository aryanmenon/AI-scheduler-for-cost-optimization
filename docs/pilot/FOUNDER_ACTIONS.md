# Founder actions before the first pilot

Status as of 2026-10-04. Only you can do these; the product side is done.

| # | Action | Status |
|---|---|---|
| 1 | Decide how pilots get the images | **Open** — see below |
| 2 | Chart delivery | Ready — one command |
| 3 | Revoke the GitHub tokens pasted into chat earlier | **Do now** — steps below |
| 4 | Post-pilot pricing | Decided: set after the first pilot's results |
| 5 | Pilot agreement / NDA | Deferred: with a lawyer, before the first install |
| 6 | Startup cloud credits | Apply — table below |

## 1. Image access for pilots

The images are private on GHCR. Either way the customer can read the
Python source, because the images run in their cluster — so the choice is
about install effort versus managing a credential.

| | Machine-account token | Offline bundle |
|---|---|---|
| Customer effort | `kubectl create secret` + `helm install` | Load ~1 GB of images into their own registry first |
| You manage | One token per pilot, revoked at the end | Nothing |
| Updates mid-pilot | `helm upgrade` | Send a new bundle |
| Air-gapped / strict clusters | Fails if they can't reach ghcr.io | Works |

Recommendation: token for most pilots, bundle only if a customer's security
team asks for it (the bundle script can be built when that happens).

Token setup, if chosen:
1. Create a separate GitHub account for pilots (e.g. `<you>-pilot-bot`); check
   GitHub's current terms on machine accounts.
2. Give it read access to the five `ai-scheduler-for-cost-optimization/*`
   packages only (each package's settings → Manage access).
3. Per pilot, from that account, create a token with only `read:packages`,
   with an expiry date at the end of the pilot. Note which customer has it.
4. Send it to the customer through a channel other than the install guide.
   Revoke it when the pilot ends.

## 2. Chart delivery

```bash
helm package deploy/helm/gpu-telemetry-collector   # -> gpu-telemetry-collector-0.4.0.tgz
```

Send the `.tgz` with PILOT_GUIDE.md (install with `helm install gpu-optimizer
./gpu-telemetry-collector-0.4.0.tgz ...`).

## 3. Revoke the tokens pasted into chat

Treat every GitHub token that was ever pasted into a chat as exposed.

1. github.com → your avatar → **Settings → Developer settings → Personal
   access tokens**. Check both **Tokens (classic)** and **Fine-grained tokens**.
2. Delete every token created for this project (and any you don't recognise).
3. **Settings → Security log**: look for activity you don't recognise.
4. Nothing in CI depends on them: the workflows only use GitHub's built-in
   per-run `GITHUB_TOKEN` (checked in `.github/workflows/ci.yml`).
5. Create new tokens only when needed, never paste them into chats, and
   type them only into masked prompts.

## 4. Pricing

PILOT_PLAN.md says pricing is proposed at the week 4 results call, after
seeing what the pilot measured. Earlier analysis (PROGRESS.md section 8) for
reference: ~1% of monitored GPU spend with a ₹9,999/month floor, toward 2%
only once a pilot proves >=15% savings; keep the "detects and recommends,
never acts" positioning (no fee tied to verified savings).

## 6. Startup cloud credits

Figures below are from third-party summaries dated 2026; only Microsoft's
"up to $150,000" headline was confirmed on an official page from here.
**Check each official page before applying.** Note: several programs need
an incorporated company and a working website, and credits for GPU
instances may also need a GPU quota request on that cloud.

| Program | Reported offer | Likely fit for a self-funded solo founder | Official page |
|---|---|---|---|
| Microsoft for Startups | Up to $150,000 Azure credits (confirmed headline); small starting levels reported for unfunded startups | Reported open to bootstrapped founders — apply first | https://www.microsoft.com/en-us/startups |
| AWS Activate Founders | Reported $1,000 for self-funded startups with a website; Portfolio tier (up to $200,000) needs an Activate Provider | Founders tier | https://aws.amazon.com/startups/credits |
| Google for Startups Cloud | Reported up to $200,000 ($350,000 AI-first) for seed to Series A with VC funding; a small ideation-stage tier reported | Small tier only, until funded | https://cloud.google.com/startup |
| NVIDIA Inception | Free, no equity; partner cloud-credit offers and discounts reported; requires incorporation, a website and at least one developer | Yes, once incorporated | https://www.nvidia.com/en-us/startups/ |

What to say in applications (adapt per form):

> We build GPU cost optimization for Kubernetes: a read-only, in-cluster
> tool that finds idle, oversized and under-used GPUs and prices the waste,
> with each recommendation checked for compute, memory bandwidth and memory
> fit. Credits fund (1) validation runs on datacenter GPUs (A100/L4/T4) that
> apply our recommendations and measure latency and cost before and after,
> and (2) pilot support infrastructure. Stage: product built and tested on
> real clusters and public production GPU traces; starting design-partner
> pilots.
