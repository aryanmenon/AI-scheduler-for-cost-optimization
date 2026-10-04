# Founder actions before the first pilot

Status as of 2026-10-04. Only you can do these; the product side is done.

| # | Action | Status |
|---|---|---|
| 0 | Protect the source code | Built: images ship compiled code only (`docs/IP_PROTECTION.md`) |
| 1 | How pilots get the images | Decided 2026-10-04: **machine-account token**, one per pilot — set up the account (steps below) |
| 2 | Chart delivery | Ready — one command |
| 3 | Revoke the GitHub tokens pasted into chat earlier | Done 2026-10-04 (founder deleted all of them) |
| 4 | Post-pilot pricing | Decided: set after the first pilot's results |
| 5 | Pilot agreement with IP clauses | **Required before the first install** — with a lawyer; clause list in `docs/IP_PROTECTION.md` (layer 2) |
| 6 | Startup cloud credits | Apply — table below |

## 1. Image access for pilots

The images are private on GHCR and, since 2026-10-04, contain only
compiled code (no readable source) — so whichever route a pilot gets them
by, they can't read your source; the signed agreement covers the rest. The
choice is about install effort versus managing a credential.

| | Machine-account token | Offline bundle |
|---|---|---|
| Customer effort | `kubectl create secret` + `helm install` | Load ~1 GB of images into their own registry first |
| You manage | One token per pilot, revoked at the end | Nothing |
| Updates mid-pilot | `helm upgrade` | Send a new bundle |
| Air-gapped / strict clusters | Fails if they can't reach ghcr.io | Works |

Recommendation: token for most pilots, bundle only if a customer's security
team asks for it (the bundle script can be built when that happens).

**Decision (2026-10-04): machine-account token.** The offline bundle stays
an option only if a customer's security team requires it.

Token setup (once):
1. Create a separate GitHub account for pilots (e.g. `<you>-pilot-bot`),
   with its own email and 2FA. Check GitHub's current terms on machine
   accounts.
2. **Do not add it as a collaborator on the repository** — the code stays
   out of its reach entirely.
3. For each of the five packages (your profile → Packages →
   `ai-scheduler-for-cost-optimization/<component>` → Package settings):
   under "Manage access", turn off inheriting access from the repository
   if it's on, and add the bot account with **Read**. (GitHub moves these
   settings occasionally; their docs page "Configuring a package's access
   control and visibility" has the current path.)
4. Confirm each package's visibility is **Private**.

Per pilot:
1. Signed pilot agreement first (`docs/IP_PROTECTION.md`, layer 2).
2. Signed in as the bot, create a **classic** personal access token with
   only the `read:packages` scope, an expiry at the pilot's end, and a note
   naming the customer. (Container registry access has historically needed
   a classic token; check GitHub's docs if fine-grained tokens now cover it.)
3. Send the bot's username and the token to the customer's engineer by a
   different channel from the install guide (e.g. a one-time secret link),
   for the `kubectl create secret docker-registry` step in PILOT_GUIDE.md.
4. When the pilot ends — or anything looks wrong — delete that token.
   Keep a short list: customer, token note, created, expires, revoked.

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
