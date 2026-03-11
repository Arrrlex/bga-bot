import os
from datetime import datetime, timezone

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from bot.db import Game, Move


@pytest.fixture
def engine():
    """In-memory SQLite engine for testing.

    Uses StaticPool so all threads share the same connection (required for
    in-memory SQLite with FastAPI TestClient which runs in a separate thread).
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture
def session(engine):
    with Session(engine) as session:
        yield session


@pytest.fixture
def sample_game(session):
    game = Game(
        id="12345",
        game_type="checkers",
        bga_url="https://boardgamearena.com/checkers?table=12345",
        status="active",
        player_name="testplayer",
        last_checked=datetime(2024, 1, 1, tzinfo=timezone.utc),
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    session.add(game)
    session.commit()
    session.refresh(game)
    return game


@pytest.fixture
def sample_move(session, sample_game):
    move = Move(
        game_id=sample_game.id,
        timestamp=datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc),
        board_state_json='{"board": []}',
        llm_prompt="SYSTEM:\nPlay checkers\n\nUSER:\nBoard state",
        llm_reasoning="I will move piece A to B",
        move_executed="piece_1 -> square_5",
        screenshot_path="screenshots/12345_1704067200.png",
        success=True,
    )
    session.add(move)
    session.commit()
    session.refresh(move)
    return move


@pytest.fixture
def mock_game_info():
    return {
        "game_id": "99999",
        "game_type": "checkers",
        "url": "https://boardgamearena.com/checkers?table=99999",
        "is_our_turn": True,
        "player_name": "botplayer",
    }


@pytest.fixture(autouse=True)
def set_env(tmp_path, monkeypatch):
    """Set required env vars for tests."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AUTH_SECRET", "test-secret")
    monkeypatch.setenv("AUTH_EMAIL", "test@example.com")
    os.makedirs(tmp_path / "screenshots", exist_ok=True)
