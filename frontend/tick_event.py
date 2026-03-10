"""Simple asyncio event to notify the frontend when a tick completes."""

import asyncio

_event = asyncio.Event()
_tick_count = 0


def notify_tick() -> None:
    """Called by the scheduler after each tick."""
    global _tick_count
    _tick_count += 1
    _event.set()


def get_tick_count() -> int:
    """Return the current tick count (for initializing SSE streams)."""
    return _tick_count


async def wait_for_tick(last_seen: int) -> int:
    """Block until a new tick fires. Returns the new tick count."""
    while _tick_count <= last_seen:
        _event.clear()
        await _event.wait()
    return _tick_count
