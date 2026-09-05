FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir .

RUN useradd --uid 10003 --no-create-home detector
USER 10003

VOLUME ["/data/normalized", "/data/findings"]

ENTRYPOINT ["waste-detector"]
