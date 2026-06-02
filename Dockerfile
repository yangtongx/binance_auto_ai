# ---- 构建阶段 ----
FROM python:3.12-slim AS builder

WORKDIR /build

# ccxt 依赖 coincurve，在 slim 上需要编译工具
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libc6-dev && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml requirements-lock.txt README.md ./
COPY src/ src/

RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir --prefix=/install . && \
    pip install --no-cache-dir --prefix=/install "requests>=2.31.0"

# ---- 运行阶段 ----
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

# 入口以 root 读取 /run/secrets（0600 root:root），再通过 gosu 降权为 bot
# 以下 ENV 为容器合理默认，可在 compose / k8s 中覆盖
ENV OBSERVABILITY_HOST=0.0.0.0 \
    OBSERVABILITY_PORT=8080 \
    STATE_FILE=/app/state/state.json

EXPOSE 8080
VOLUME ["/app/state"]
STOPSIGNAL SIGTERM

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["binance-auto-ai"]
