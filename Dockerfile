FROM python:3.14-slim

# uv binary from the official distroless image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /bot

# The bot token is a runtime secret and is intentionally NOT baked into the
# image — supply TELEGRAM_BOT_TOKEN via env at run time (compose env_file,
# k8s secret, `docker run -e`). Keeps the published image safe to share.
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

# Install runtime dependencies from the lock file (no dev group, no project itself)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY ./entrypoint.sh .
COPY ./src/ .

# Web admin dashboard (active only when web.enabled / WEB_ENABLED is set).
EXPOSE 8080

ENTRYPOINT ["/bot/entrypoint.sh"]
