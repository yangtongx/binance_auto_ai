# ---- build stage ----
FROM python:3.12-slim AS builder

WORKDIR /build

COPY pyproject.toml requirements-lock.txt README.md ./
COPY src/ src/

RUN pip install --no-cache-dir --prefix=/install .

# ---- runtime stage ----
FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends gosu && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd --gid 1000 bot && \
    useradd --uid 1000 --gid bot --create-home bot && \
    mkdir -p /app/state && chown -R bot:bot /app

COPY --from=builder /install /usr/local
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

WORKDIR /app

# Entrypoint runs as root to read /run/secrets (mode 0600 root:root), then gosu bot.
# Sensible container defaults — override via env / compose / k8s.
ENV OBSERVABILITY_HOST=0.0.0.0 \
    OBSERVABILITY_PORT=8080 \
    STATE_FILE=/app/state/state.json

EXPOSE 8080
VOLUME ["/app/state"]
STOPSIGNAL SIGTERM

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["futures-llm-bot"]
