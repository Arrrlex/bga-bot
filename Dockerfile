FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    chromium chromium-driver \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .
RUN uv run playwright install chromium

# SERVICE env var selects which process to run: "bot" or "frontend"
ENV SERVICE=bot
CMD uv run python -m $SERVICE
