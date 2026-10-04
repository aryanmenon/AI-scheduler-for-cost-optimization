# Build from the REPO ROOT (the compile script lives in deploy/compile/):
#
#   docker build -f ingestion-normalization/Dockerfile -t ingestion-normalization .
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
RUN /opt/venv/bin/pip install --no-cache-dir /src/ingestion-normalization

COPY deploy/compile/compile_packages.py /build/compile_packages.py
RUN python /build/compile_packages.py /opt/venv/lib/python3.12/site-packages ingestion_normalization

FROM python:3.12-slim

COPY --from=build /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN useradd --uid 10001 --no-create-home ingestion
USER 10001

VOLUME ["/data/raw", "/data/normalized"]
ENTRYPOINT ["ingestion-normalization"]
