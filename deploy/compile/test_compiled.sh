#!/usr/bin/env bash
# Run every test suite against the Cython-COMPILED packages (what the
# images ship), not the source tree, so a compile-only behavior change
# can't reach a customer. Needs Cython and a C compiler; the components'
# third-party test dependencies must already be installed (CI installs
# them with `pip install -e "<component>[dev]"`; PYTHONPATH below takes
# precedence over those editable installs).
#
#   bash deploy/compile/test_compiled.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
SITE="$(mktemp -d)/site"
PKGS=(telemetry_collector ingestion_normalization waste_detector savings_estimator dashboard)

python -m pip install --quiet --no-deps --target "$SITE" \
  ./telemetry-collector ./ingestion-normalization ./waste-detector ./savings-estimator ./dashboard
python deploy/compile/compile_packages.py "$SITE" "${PKGS[@]}"

PROBE="$(mktemp -d)/test_compiled_probe.py"
cat > "$PROBE" <<'PY'
import sys
def test_every_product_module_loaded_is_compiled():
    names = ("telemetry_collector", "ingestion_normalization", "waste_detector", "savings_estimator", "dashboard")
    loaded = {n: m.__file__ for n, m in sys.modules.items()
              if n.split(".")[0] in names and getattr(m, "__file__", None)}
    source = {n: f for n, f in loaded.items() if f.endswith(".py") and not f.endswith("__init__.py")}
    assert loaded and not source, f"loaded from source: {source}"
PY

for suite in telemetry-collector ingestion-normalization waste-detector savings-estimator dashboard integration-tests; do
  echo "== $suite (compiled)"
  (cd "$suite/tests" && PYTHONPATH="$SITE" python -m pytest -q -p no:cacheprovider --rootdir=. . "$PROBE")
done
