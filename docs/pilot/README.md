# Pilot pack

| File | For | What |
|---|---|---|
| `PILOT_PLAN.md` | Prospect | The free 3–4 week pilot: what they get, what we ask, timeline, success criteria |
| `PILOT_GUIDE.md` | Prospect's engineer | What it does and doesn't, security and data, install, verify, read, uninstall |
| `sample-report.html` | Prospect | What a report looks like — real product pipeline over a fictional 7-GPU cluster (`make_sample_report.py` regenerates it) |
| `OUTREACH.md` | Founder only | Who to approach, honest claims and their evidence, email/LinkedIn templates, discovery questions, objections |

## Before the first pilot install — founder decisions and actions

These can't be done from the codebase:

1. **How pilots get the images.** They are private on GHCR, and Python
   images contain readable source code, so making them public publishes
   the code. Options: (a) a dedicated GitHub machine account with read-only
   package access and a token per pilot, revoked after; (b) ship the images
   as `docker save` tarballs the customer loads into their own registry;
   (c) make the packages public and accept the code being visible.
2. **How pilots get the chart.** `helm package deploy/helm/gpu-telemetry-collector`
   produces a `.tgz` to send (the repository is private).
3. **Rotate the GitHub tokens pasted into chat earlier in this project**
   before issuing any new credentials. They should be treated as exposed.
4. **Post-pilot pricing.** PILOT_PLAN.md promises only a proposal based on
   measured savings; decide the model before the week 4 call.
5. **A short pilot agreement / NDA**, reviewed by a lawyer once.
6. **Startup cloud credits** (Google for Startups, AWS Activate, Microsoft
   for Startups, NVIDIA Inception) to fund the paid client-cluster test and
   pilot support.
