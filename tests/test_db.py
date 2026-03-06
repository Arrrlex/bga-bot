from datetime import datetime, timezone

import pytest
from sqlmodel import Session

from bot.db import (
    Game,
    Move,
    get_all_games,
    get_game,
    get_moves_for_game,
    record_move,
    upsert_game,
)


def test_create_game(session: Session):
    game = Game(
        id="100",
        game_type="checkers",
        bga_url="https://bga.com/checkers?table=100",
        player_name="me",
    )
    session.add(game)
    session.commit()

    fetched = session.get(Game, "100")
    assert fetched is not None
    assert fetched.game_type == "checkers"
    assert fetched.status == "active"


def test_create_move(session: Session, sample_game):
    move = Move(
        game_id=sample_game.id,
        timestamp=datetime.now(timezone.utc),
        board_state_json="{}",
        llm_prompt="test prompt",
        llm_reasoning="test reasoning",
        move_executed="a -> b",
        success=True,
    )
    session.add(move)
    session.commit()
    session.refresh(move)

    assert move.id is not None
    assert move.game_id == sample_game.id


def test_move_foreign_key(engine):
    """Move referencing non-existent game should fail with FK enforcement."""
    from sqlalchemy import event, text

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    with Session(engine) as fk_session:
        fk_session.exec(text("PRAGMA foreign_keys=ON"))
        move = Move(
            game_id="nonexistent",
            timestamp=datetime.now(timezone.utc),
            move_executed="a -> b",
            success=False,
        )
        fk_session.add(move)
        with pytest.raises(Exception):
            fk_session.commit()


def test_upsert_game_creates(session: Session):
    info = {
        "game_id": "200",
        "game_type": "elgrande",
        "url": "https://bga.com/elgrande?table=200",
        "player_name": "me",
    }
    game = upsert_game(session, info)
    assert game.id == "200"
    assert game.game_type == "elgrande"
    assert game.status == "active"


def test_upsert_game_updates(session: Session, sample_game):
    old_checked = sample_game.last_checked
    info = {
        "game_id": sample_game.id,
        "game_type": sample_game.game_type,
        "url": "https://bga.com/checkers?table=12345&updated",
        "player_name": sample_game.player_name,
    }
    game = upsert_game(session, info)
    assert game.id == sample_game.id
    assert game.bga_url == "https://bga.com/checkers?table=12345&updated"
    assert game.last_checked > old_checked


def test_record_move(session: Session, sample_game):
    move = record_move(
        session,
        Move(
            game_id=sample_game.id,
            timestamp=datetime.now(timezone.utc),
            move_executed="test move",
            success=True,
        ),
    )
    assert move.id is not None


def test_get_all_games(session: Session, sample_game):
    games = get_all_games(session)
    assert len(games) == 1
    assert games[0].id == sample_game.id


def test_get_all_games_empty(session: Session):
    games = get_all_games(session)
    assert games == []


def test_get_game(session: Session, sample_game):
    game = get_game(session, sample_game.id)
    assert game is not None
    assert game.id == sample_game.id


def test_get_game_missing(session: Session):
    game = get_game(session, "nonexistent")
    assert game is None


def test_get_moves_for_game(session: Session, sample_game, sample_move):
    moves = get_moves_for_game(session, sample_game.id)
    assert len(moves) == 1
    assert moves[0].id == sample_move.id


def test_get_moves_for_game_empty(session: Session, sample_game):
    moves = get_moves_for_game(session, sample_game.id)
    assert moves == []


def test_get_moves_ordered_newest_first(session: Session, sample_game):
    m1 = Move(
        game_id=sample_game.id,
        timestamp=datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc),
        move_executed="first",
        success=True,
    )
    m2 = Move(
        game_id=sample_game.id,
        timestamp=datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc),
        move_executed="second",
        success=True,
    )
    session.add(m1)
    session.add(m2)
    session.commit()

    moves = get_moves_for_game(session, sample_game.id)
    assert len(moves) == 2
    assert moves[0].move_executed == "second"
    assert moves[1].move_executed == "first"


def test_game_default_status(session: Session):
    game = Game(id="300", game_type="test", bga_url="https://bga.com/test")
    session.add(game)
    session.commit()
    session.refresh(game)
    assert game.status == "active"


def test_move_error_fields(session: Session, sample_game):
    move = Move(
        game_id=sample_game.id,
        timestamp=datetime.now(timezone.utc),
        move_executed="bad move",
        success=False,
        error_message="Click failed: element not found",
    )
    session.add(move)
    session.commit()
    session.refresh(move)
    assert move.success is False
    assert move.error_message == "Click failed: element not found"
