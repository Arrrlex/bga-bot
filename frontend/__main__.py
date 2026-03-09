"""Run the dashboard frontend as a standalone process."""

import os

import uvicorn
from dotenv import load_dotenv

load_dotenv()

os.environ.setdefault("DATA_DIR", "./data")

from .app import create_app

app = create_app()

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
    )
