# Protecting the product's source code

Founder-only. Decided 2026-10-04: pilot customers must not be able to read
the product's source. Two layers: compiled images (technical) and a
written agreement (legal). Both must be in place before the first pilot.

## Layer 1 — Images ship compiled code, not source (built)

Every image's Dockerfile installs its package, then
`deploy/compile/compile_packages.py` compiles every module with Cython to a
native machine-code extension (`.so`, symbols stripped, docstrings
omitted) and deletes the `.py` source, the generated C and all bytecode.
The final image stage copies only that compiled result.

What a customer can and can't see in an image:

| | Visible? |
|---|---|
| Python source, comments, docstrings, formulas as written | **No** |
| Bytecode (`.pyc`, which free tools decompile) | **No** — deleted |
| Function and module names | Yes |
| Message text the product prints or shows in reports | Yes (customers see it in reports anyway) |
| Thresholds and the arithmetic itself | Only by disassembling machine code — expert, slow work |
| Helm chart, configuration values, logs | Yes, deliberately: security reviewers need them |
| Each package's `__init__.py` | Yes — it contains only the version string |

Checked on 2026-10-04: a comment sentence and a formula from `ceiling.py`
do not appear anywhere in the compiled module; its function names and
user-facing messages do.

How it stays true (all in CI, `.github/workflows/ci.yml`):

- `compile_packages.py` itself fails the build if any module is left
  uncompiled or any `.py` survives.
- **docker-build** runs each built image and fails if any `.py` (other
  than the version-only `__init__.py`) or any `.pyc` of ours is inside,
  then imports every compiled module.
- **test-compiled** re-runs every test suite against the compiled
  packages (`deploy/compile/test_compiled.sh`), so behavior can't silently
  differ between what's tested and what ships. Verified locally: all six
  suites pass compiled, and a probe confirms no product module loaded
  from source.

Limits, stated plainly: compiled code raises the cost of copying from
"open a file" to "reverse-engineer machine code". It does not make copying
impossible — nothing a customer runs on their own machines can. That is
what layer 2 is for.

Developer note: build images from the repo root, e.g.
`docker build -f waste-detector/Dockerfile -t waste-detector .`.

## Layer 2 — Pilot agreement (before the first pilot, with a lawyer)

Do not install at a customer without a signed agreement. Ask the lawyer
for a short pilot / evaluation licence covering at least:

1. **Licence scope** — a limited, non-exclusive, non-transferable right to
   install and use the software internally, only to evaluate it, only for
   the pilot period.
2. **No reverse engineering** — no decompiling, disassembling or otherwise
   trying to derive source code, algorithms or thresholds; no circumventing
   the compiled form. (Ask how Indian law, including the Copyright Act's
   interoperability exception, limits how far this clause reaches.)
3. **Confidentiality** — the software, its outputs' methodology, pricing
   and anything shared on calls are confidential, both ways (their cluster
   data stays theirs too).
4. **No copying or redistribution** — including the container images and
   chart, outside their own cluster.
5. **Ownership** — all IP stays with you; feedback can be used freely to
   improve the product.
6. **End of pilot** — uninstall and delete the images and chart within a
   set number of days, on request, and confirm in writing.
7. **No warranty and capped liability** — it's an evaluation: the software
   only recommends, never acts; their team decides what to change.
8. **Publicity** — no use of their name or results without written consent
   (PILOT_PLAN.md already promises this).
9. **Governing law and jurisdiction** — India, your city.

Bring this file, PILOT_PLAN.md and PILOT_GUIDE.md to the lawyer so the
agreement matches what the pilot actually involves.
