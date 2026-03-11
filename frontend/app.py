import os
from pathlib import Path

import asyncio

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session
from sse_starlette.sse import EventSourceResponse
from starlette.middleware.base import BaseHTTPMiddleware

from bot.db import get_all_games, get_engine, get_game, get_moves_for_game, get_session
from frontend.auth import (
    COOKIE_NAME,
    check_credentials,
    clear_auth_cookie,
    set_auth_cookie,
    verify_token,
)
from frontend.log_buffer import log_buffer
from frontend.tick_event import wait_for_tick

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

PUBLIC_PATHS = {"/login", "/health"}


def create_app(engine=None) -> FastAPI:
    if engine is None:
        engine = get_engine()

    app = FastAPI(title="BGA Bot Dashboard")

    class AuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            path = request.url.path
            if path.startswith("/static") or path in PUBLIC_PATHS:
                return await call_next(request)
            token = request.cookies.get(COOKIE_NAME)
            if not token or not verify_token(token):
                # For SSE/API requests, return 401; for pages, redirect
                accept = request.headers.get("accept", "")
                if "text/html" in accept:
                    return RedirectResponse(url="/login", status_code=302)
                return HTMLResponse(status_code=401, content="Unauthorized")
            return await call_next(request)

    app.add_middleware(AuthMiddleware)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    refresh_seconds = int(os.environ.get("POLL_INTERVAL_SECONDS", "0"))
    if not refresh_seconds:
        refresh_seconds = int(os.environ.get("POLL_INTERVAL_MINUTES", "5")) * 60

    def get_db():
        session = get_session(engine)
        try:
            yield session
        finally:
            session.close()

    # --- Auth routes ---

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request):
        token = request.cookies.get(COOKIE_NAME)
        if token and verify_token(token):
            return RedirectResponse(url="/", status_code=302)
        return templates.TemplateResponse("login.html", {"request": request, "error": None})

    @app.post("/login", response_class=HTMLResponse)
    async def login(request: Request, email: str = Form(...), password: str = Form(...)):
        if check_credentials(email, password):
            response = RedirectResponse(url="/", status_code=302)
            set_auth_cookie(response, email)
            return response
        return templates.TemplateResponse(
            "login.html", {"request": request, "error": "Invalid email or password."}
        )

    @app.get("/logout")
    async def logout():
        response = RedirectResponse(url="/login", status_code=302)
        clear_auth_cookie(response)
        return response

    # --- App routes ---

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(
        request: Request,
        session: Session = Depends(get_db),
    ):
        games = get_all_games(session)
        active_games = [g for g in games if g.status == "active"]
        unconfigured_games = [g for g in games if g.status == "unknown"]
        finished_games = [g for g in games if g.status == "finished"]

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
                "refresh_seconds": refresh_seconds,
            },
        )

    @app.get("/game/{game_id}", response_class=HTMLResponse)
    async def game_detail(
        request: Request,
        game_id: str,
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
                "refresh_seconds": refresh_seconds,
            },
        )

    data_dir = os.environ.get("DATA_DIR", "/data")
    screenshots_dir = os.path.join(data_dir, "screenshots")
    os.makedirs(screenshots_dir, exist_ok=True)

    @app.get("/screenshots/{path:path}")
    async def serve_screenshot(path: str):
        from fastapi.responses import FileResponse

        full_path = os.path.join(screenshots_dir, path)
        if not os.path.isfile(full_path):
            raise HTTPException(status_code=404, detail="Screenshot not found")
        return FileResponse(full_path)

    @app.get("/logs", response_class=HTMLResponse)
    async def logs_page(request: Request):
        lines = log_buffer.get_lines()
        return templates.TemplateResponse(
            "logs.html",
            {
                "request": request,
                "lines": lines,
                "refresh_seconds": refresh_seconds,
            },
        )

    @app.get("/logs/stream")
    async def logs_stream(request: Request):
        async def generate():
            last_len = len(log_buffer.buffer)
            while True:
                await asyncio.sleep(1)
                current_len = len(log_buffer.buffer)
                if current_len > last_len:
                    new_lines = list(log_buffer.buffer)[last_len:]
                    for line in new_lines:
                        yield {"data": line}
                    last_len = current_len
                elif current_len < last_len:
                    # Buffer wrapped around
                    for line in log_buffer.buffer:
                        yield {"data": line}
                    last_len = len(log_buffer.buffer)

        return EventSourceResponse(generate())

    @app.get("/tick/stream")
    async def tick_stream(request: Request):
        async def generate():
            from frontend.tick_event import get_tick_count
            last_seen = get_tick_count()
            while True:
                last_seen = await wait_for_tick(last_seen)
                yield {"event": "tick", "data": str(last_seen)}

        return EventSourceResponse(generate())

    return app
