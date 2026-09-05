# Unlike the other three components' Dockerfiles, this one has REAL
# runtime dependencies on sibling packages (ingestion-normalization's
# capability table, waste-detector's category constants -- see
# pyproject.toml). Build with the REPO ROOT as context, not this
# directory:
#
#   docker build -f savings-estimator/Dockerfile -t savings-estimator .
#
FROM python:3.12-slim

WORKDIR /app

COPY ingestion-normalization ./ingestion-normalization
COPY waste-detector ./waste-detector
COPY savings-estimator ./savings-estimator

RUN pip install --no-cache-dir ./ingestion-normalization ./waste-detector ./savings-estimator

RUN useradd --uid 10004 --no-create-home estimator
USER 10004

VOLUME ["/data/findings", "/data/normalized", "/data/savings"]

ENTRYPOINT ["savings-estimator"]
