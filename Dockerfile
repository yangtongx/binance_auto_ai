# ---- build stage ----
FROM python:3.12-slim AS builder

WORKDIR /build

COPY pyproject.toml requirements-lock.txt README.md ./
COPY src/ src/

RUN pip install --no-cache-dir --prefix=/install .

# ---- runtime stage ----
FROM python:3.12-slim

RUN groupadd --gid 1000 bot && \
    useradd --uid 1000 --gid bot --create-home bot && \
    mkdir -p /app/state && chown -R bot:bot /app

COPY --from=builder /install /usr/local

WORKDIR /app

USER bot

# Sensible container defaults — override via env / compose / k8s.
# Bind on 0.0.0.0 so the host port mapping is reachable; STATE_FILE lives on the mounted volume.
ENV OBSERVABILITY_HOST=0.0.0.0 \
    OBSERVABILITY_PORT=8080 \
    STATE_FILE=/app/state/state.json

EXPOSE 8080
VOLUME ["/app/state"]
STOPSIGNAL SIGTERM

ENTRYPOINT ["futures-llm-bot"]
