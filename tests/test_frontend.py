import os
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from bot.db import Game, Move
from frontend.app import create_app
from frontend.auth import COOKIE_NAME, create_token


@pytest.fixture
def app(engine):
    return create_app(engine)


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def auth_cookies():
    token = create_token("test@example.com")
    return {COOKIE_NAME: token}


@pytest.fixture
def bad_auth_cookies():
    return {COOKIE_NAME: "invalid-token"}


def test_unauthenticated_returns_401(client):
    response = client.get("/")
    assert response.status_code == 401


def test_wrong_password_returns_401(client, bad_auth_cookies):
    response = client.get("/", cookies=bad_auth_cookies)
    assert response.status_code == 401


def test_dashboard_empty(client, auth_cookies):
    response = client.get("/", cookies=auth_cookies)
    assert response.status_code == 200
    assert "No active games" in response.text


def test_dashboard_shows_active_games(client, auth_cookies, session):
    game = Game(
        id="111",
        game_type="checkers",
        bga_url="https://bga.com/checkers?table=111",
        status="active",
        player_name="me",
    )
    session.add(game)
    session.commit()

    response = client.get("/", cookies=auth_cookies)
    assert response.status_code == 200
    assert "111" in response.text
    assert "checkers" in response.text


def test_dashboard_unconfigured_games_section(client, auth_cookies, session):
    game = Game(
        id="222",
        game_type="obscure_game",
        bga_url="https://bga.com/obscure_game?table=222",
        status="unknown",
        player_name="me",
    )
    session.add(game)
    session.commit()

    response = client.get("/", cookies=auth_cookies)
    assert response.status_code == 200
    assert "Unconfigured Games" in response.text
    assert "obscure_game" in response.text


def test_dashboard_failed_move_flagged(client, auth_cookies, session):
    game = Game(
        id="333",
        game_type="checkers",
        bga_url="https://bga.com/checkers?table=333",
        status="active",
    )
    session.add(game)
    session.commit()

    move = Move(
        game_id="333",
        timestamp=datetime.now(timezone.utc),
        move_executed="bad move",
        success=False,
        error_message="click failed",
    )
    session.add(move)
    session.commit()

    response = client.get("/", cookies=auth_cookies)
    assert response.status_code == 200
    assert "Failed" in response.text


def test_game_detail_page(client, auth_cookies, session):
    game = Game(
        id="444",
        game_type="checkers",
        bga_url="https://bga.com/checkers?table=444",
        status="active",
        player_name="botplayer",
    )
    session.add(game)
    session.commit()

    move = Move(
        game_id="444",
        timestamp=datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc),
        board_state_json='{"board": []}',
        llm_prompt="test prompt",
        llm_reasoning="I chose to move A to B because...",
        move_executed="A -> B",
        success=True,
    )
    session.add(move)
    session.commit()

    response = client.get("/game/444", cookies=auth_cookies)
    assert response.status_code == 200
    assert "444" in response.text
    assert "A -&gt; B" in response.text  # HTML-escaped
    assert "I chose to move A to B" in response.text


def test_game_detail_moves_newest_first(client, auth_cookies, session):
    game = Game(
        id="555", game_type="checkers", bga_url="https://bga.com/checkers?table=555"
    )
    session.add(game)
    session.commit()

    m1 = Move(
        game_id="555",
        timestamp=datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc),
        move_executed="first_move",
        success=True,
    )
    m2 = Move(
        game_id="555",
        timestamp=datetime(2024, 1, 1, 14, 0, tzinfo=timezone.utc),
        move_executed="second_move",
        success=True,
    )
    session.add(m1)
    session.add(m2)
    session.commit()

    response = client.get("/game/555", cookies=auth_cookies)
    assert response.status_code == 200
    text = response.text
    # second_move should appear before first_move
    assert text.index("second_move") < text.index("first_move")


def test_game_detail_missing_returns_404(client, auth_cookies):
    response = client.get("/game/nonexistent", cookies=auth_cookies)
    assert response.status_code == 404


def test_game_detail_failed_move_flagged(client, auth_cookies, session):
    game = Game(
        id="666", game_type="checkers", bga_url="https://bga.com/checkers?table=666"
    )
    session.add(game)
    session.commit()

    move = Move(
        game_id="666",
        timestamp=datetime.now(timezone.utc),
        move_executed="failed_move",
        success=False,
        error_message="Element not found",
    )
    session.add(move)
    session.commit()

    response = client.get("/game/666", cookies=auth_cookies)
    assert response.status_code == 200
    assert "Failed" in response.text
    assert "Element not found" in response.text


def test_screenshot_route_missing_file(client, auth_cookies):
    response = client.get("/screenshots/nonexistent.png", cookies=auth_cookies)
    assert response.status_code == 404


def test_screenshot_route_serves_file(client, auth_cookies, tmp_path):
    # Create a fake screenshot
    screenshots_dir = tmp_path / "screenshots"
    screenshots_dir.mkdir(exist_ok=True)
    test_file = screenshots_dir / "test.png"
    test_file.write_bytes(b"fake png data")

    response = client.get("/screenshots/test.png", cookies=auth_cookies)
    assert response.status_code == 200
    assert response.content == b"fake png data"
