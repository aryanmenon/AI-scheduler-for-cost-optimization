# Build from the REPO ROOT (the compile script lives in deploy/compile/):
#
#   docker build -f waste-detector/Dockerfile -t waste-detector .
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

COPY waste-detector /src/waste-detector
RUN /opt/venv/bin/pip install --no-cache-dir /src/waste-detector

COPY deploy/compile/compile_packages.py /build/compile_packages.py
RUN python /build/compile_packages.py /opt/venv/lib/python3.12/site-packages waste_detector

FROM python:3.12-slim

COPY --from=build /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN useradd --uid 10003 --no-create-home detector
USER 10003

VOLUME ["/data/normalized", "/data/findings"]
ENTRYPOINT ["waste-detector"]
