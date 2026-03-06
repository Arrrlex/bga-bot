"""Entrypoint: starts scheduler + frontend in a single process."""

import asyncio
import logging
import os

import uvicorn
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

    interval = int(os.environ.get("POLL_INTERVAL_MINUTES", "5"))
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_tick,
        "interval",
        minutes=interval,
        args=[client, llm, get_session(engine), data_dir],
        id="run_tick",
        max_instances=1,
    )
    scheduler.start()
    logger.info("Scheduler started with %d minute interval", interval)

    # Run initial tick immediately
    try:
        await run_tick(client, llm, get_session(engine), data_dir)
    except Exception:
        logger.exception("Initial tick failed")

    # Start FastAPI in the same event loop
    # Import here to avoid circular imports
    from frontend.app import create_app

    app = create_app(engine)
    config = uvicorn.Config(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
