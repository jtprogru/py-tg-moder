FROM python:3.14-slim

# uv binary from the official distroless image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /bot

ARG TOKEN
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV TELEGRAM_BOT_TOKEN=$TOKEN
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

# Install runtime dependencies from the lock file (no dev group, no project itself)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY ./entrypoint.sh .
COPY ./src/ .

ENTRYPOINT ["/bot/entrypoint.sh"]
