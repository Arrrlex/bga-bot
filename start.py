"""Production entrypoint: runs bot scheduler + frontend together."""

import asyncio
import logging
import os

import uvicorn
from dotenv import load_dotenv

load_dotenv()

os.environ.setdefault("DATA_DIR", "/data")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

from frontend.log_buffer import install as install_log_buffer
install_log_buffer()

from bot.bga_client import BGAClient
from bot.db import get_engine, get_session
from bot.llm import get_provider
from bot.scheduler import run_tick
from frontend.app import create_app

from apscheduler.schedulers.asyncio import AsyncIOScheduler

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

    # Start frontend (scheduler handles first tick in the background)
    app = create_app(engine)
    config = uvicorn.Config(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
