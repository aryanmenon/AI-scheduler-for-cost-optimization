# Build from the REPO ROOT (the compile script lives in deploy/compile/):
#
#   docker build -f savings-estimator/Dockerfile -t savings-estimator .
#
# savings-estimator has real runtime dependencies on sibling packages
# (ingestion-normalization's capability table, waste-detector's category
# constants -- see pyproject.toml), so all three are installed and compiled.
#
# Stage 1 installs the package and compiles every module to a stripped
# native extension with Cython, deleting the .py source and bytecode
# (deploy/compile/compile_packages.py fails the build if any source
# survives). Stage 2 ships only that compiled result: the image contains no
# readable Python source. See docs/IP_PROTECTION.md.
FROM python:3.12-slim AS build

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir "cython==3.1.4" "setuptools>=68"
RUN python -m venv /opt/venv

COPY ingestion-normalization /src/ingestion-normalization
COPY waste-detector /src/waste-detector
COPY savings-estimator /src/savings-estimator
RUN /opt/venv/bin/pip install --no-cache-dir /src/ingestion-normalization /src/waste-detector /src/savings-estimator

COPY deploy/compile/compile_packages.py /build/compile_packages.py
RUN python /build/compile_packages.py /opt/venv/lib/python3.12/site-packages ingestion_normalization waste_detector savings_estimator

FROM python:3.12-slim

COPY --from=build /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN useradd --uid 10004 --no-create-home estimator
USER 10004

VOLUME ["/data/findings", "/data/normalized", "/data/savings"]
ENTRYPOINT ["savings-estimator"]
