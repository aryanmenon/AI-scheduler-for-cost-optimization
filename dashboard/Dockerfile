FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir .

RUN useradd --uid 10005 --no-create-home dashboard
USER 10005

VOLUME ["/data/savings"]
EXPOSE 8080

ENTRYPOINT ["dashboard-server"]
