"""Entrypoint: runs the bot scheduler (no frontend)."""

import asyncio
import logging
import os

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

from .bga_client import BGAClient
from .db import get_engine, get_session
from .llm import get_provider
from .scheduler import run_tick

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    data_dir = os.environ.get("DATA_DIR", "/data")
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(os.path.join(data_dir, "screenshots"), exist_ok=True)

    engine = get_engine()
    llm = get_provider()
    client = BGAClient()

    logger.info("Starting BGA client...")
    await client.start()

    interval_seconds = int(os.environ.get("POLL_INTERVAL_SECONDS", "0"))
    interval_minutes = int(os.environ.get("POLL_INTERVAL_MINUTES", "5"))
    if interval_seconds:
        interval_kwargs = {"seconds": interval_seconds}
        interval_desc = f"{interval_seconds}s"
    else:
        interval_kwargs = {"minutes": interval_minutes}
        interval_desc = f"{interval_minutes}m"

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_tick,
        "interval",
        **interval_kwargs,
        args=[client, llm, get_session(engine), data_dir],
        id="run_tick",
        max_instances=1,
    )
    scheduler.start()
    logger.info("Scheduler started with %s interval", interval_desc)

    # Run initial tick immediately
    try:
        await run_tick(client, llm, get_session(engine), data_dir)
    except Exception:
        logger.exception("Initial tick failed")

    # Keep the process alive
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down...")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
