FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir .

RUN useradd --uid 10001 --no-create-home ingestion
USER 10001

VOLUME ["/data/raw", "/data/normalized"]

ENTRYPOINT ["ingestion-normalization"]
