import os
import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from bot.db import get_all_games, get_game, get_moves_for_game, get_session

security = HTTPBasic()

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

_engine = None


def create_app(engine=None) -> FastAPI:
    global _engine
    _engine = engine

    app = FastAPI(title="BGA Bot Dashboard")

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    def get_db():
        session = get_session(_engine)
        try:
            yield session
        finally:
            session.close()

    def verify_password(credentials: HTTPBasicCredentials = Depends(security)):
        expected = os.environ.get("DASHBOARD_PASSWORD", "")
        if not expected:
            raise HTTPException(status_code=500, detail="DASHBOARD_PASSWORD not configured")
        if not secrets.compare_digest(credentials.password, expected):
            raise HTTPException(
                status_code=401,
                detail="Invalid credentials",
                headers={"WWW-Authenticate": "Basic"},
            )
        return credentials.username

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(
        request: Request,
        _user: str = Depends(verify_password),
        session: Session = Depends(get_db),
    ):
        games = get_all_games(session)
        active_games = [g for g in games if g.status == "active"]
        unconfigured_games = [g for g in games if g.status == "unknown"]
        finished_games = [g for g in games if g.status == "finished"]

        # Get last move for each game to check for failures
        game_last_moves: dict[str, object] = {}
        for g in games:
            moves = get_moves_for_game(session, g.id)
            if moves:
                game_last_moves[g.id] = moves[0]

        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "active_games": active_games,
                "unconfigured_games": unconfigured_games,
                "finished_games": finished_games,
                "game_last_moves": game_last_moves,
            },
        )

    @app.get("/game/{game_id}", response_class=HTMLResponse)
    async def game_detail(
        request: Request,
        game_id: str,
        _user: str = Depends(verify_password),
        session: Session = Depends(get_db),
    ):
        game = get_game(session, game_id)
        if game is None:
            raise HTTPException(status_code=404, detail="Game not found")

        moves = get_moves_for_game(session, game_id)

        return templates.TemplateResponse(
            "game_detail.html",
            {
                "request": request,
                "game": game,
                "moves": moves,
            },
        )

    data_dir = os.environ.get("DATA_DIR", "/data")
    screenshots_dir = os.path.join(data_dir, "screenshots")
    os.makedirs(screenshots_dir, exist_ok=True)

    @app.get("/screenshots/{path:path}")
    async def serve_screenshot(
        path: str,
        _user: str = Depends(verify_password),
    ):
        from fastapi.responses import FileResponse

        full_path = os.path.join(screenshots_dir, path)
        if not os.path.isfile(full_path):
            raise HTTPException(status_code=404, detail="Screenshot not found")
        return FileResponse(full_path)

    return app
