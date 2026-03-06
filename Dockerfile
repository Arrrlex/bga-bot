FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    chromium chromium-driver \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml .
RUN pip install -e .
RUN playwright install chromium

COPY . .

CMD ["python", "-m", "bot.main"]
