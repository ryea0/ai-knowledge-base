# Dockerfile - AI 知识库助手
# 多阶段构建：builder 安装依赖，runtime 精简镜像

FROM python:3.12-slim AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_INSTALLER_METADATA=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src/ src/
RUN uv sync --frozen --no-dev

# ---- runtime ----
FROM python:3.12-slim AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN groupadd --gid 1000 kb && \
    useradd --uid 1000 --gid kb --home-dir /app --shell /bin/bash kb

WORKDIR /app

COPY --from=builder --chown=kb:kb /app/.venv /app/.venv
COPY --from=builder --chown=kb:kb /app/src /app/src
COPY --chown=kb:kb pyproject.toml ./

USER kb

ENTRYPOINT ["python", "-m", "src.main"]
