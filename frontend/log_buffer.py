"""In-memory ring buffer that captures log records for the dashboard."""

import logging
from collections import deque
from datetime import datetime, timezone


class LogBuffer(logging.Handler):
    def __init__(self, capacity: int = 2000):
        super().__init__()
        self.buffer: deque[str] = deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
            self.buffer.append(line)
        except Exception:
            self.handleError(record)

    def get_lines(self, n: int | None = None) -> list[str]:
        if n is None:
            return list(self.buffer)
        return list(self.buffer)[-n:]


# Singleton
log_buffer = LogBuffer()
log_buffer.setFormatter(
    logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
)


def install() -> None:
    """Attach the buffer handler to the root logger."""
    logging.getLogger().addHandler(log_buffer)
