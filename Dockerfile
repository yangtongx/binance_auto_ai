# ---- build stage ----
FROM python:3.12-slim AS builder

WORKDIR /build

COPY pyproject.toml requirements-lock.txt ./
COPY src/ src/

RUN pip install --no-cache-dir --prefix=/install .

# ---- runtime stage ----
FROM python:3.12-slim

RUN groupadd --gid 1000 bot && \
    useradd --uid 1000 --gid bot --create-home bot

COPY --from=builder /install /usr/local

WORKDIR /app
COPY src/ src/
COPY pyproject.toml ./

RUN pip install --no-cache-dir -e . 2>/dev/null || true

USER bot

VOLUME ["/app/state"]

ENTRYPOINT ["futures-llm-bot"]
