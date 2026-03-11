import json
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlmodel import Session

from bot.db import Game, Move, get_moves_for_game, upsert_game
from bot.games.base import GameState, MoveResult
from bot.scheduler import _cleanup_screenshots, run_tick


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.accept_pending_invitations = AsyncMock(return_value=[])
    client.get_active_games = AsyncMock(return_value=[])
    client.navigate_to_game = AsyncMock()
    client.capture_screenshot = AsyncMock()
    return client


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value='{"from": "a1", "to": "b2"}')
    return llm


@pytest.fixture
def mock_page():
    page = AsyncMock()
    page.close = AsyncMock()
    page.evaluate = AsyncMock(return_value="")
    return page


@pytest.mark.asyncio
async def test_no_active_games(mock_client, mock_llm, session, tmp_path):
    mock_client.get_active_games.return_value = []
    await run_tick(mock_client, mock_llm, session, str(tmp_path))
    # No errors, nothing to do


@pytest.mark.asyncio
async def test_unknown_game_type(mock_client, mock_llm, session, tmp_path):
    mock_client.get_active_games.return_value = [
        {
            "game_id": "500",
            "game_type": "unknown_game_xyz",
            "url": "https://bga.com/unknown_game_xyz?table=500",
            "is_our_turn": True,
            "player_name": "me",
        }
    ]
    await run_tick(mock_client, mock_llm, session, str(tmp_path))

    game = session.get(Game, "500")
    assert game is not None
    assert game.status == "unknown"


@pytest.mark.asyncio
async def test_not_our_turn(mock_client, mock_llm, session, mock_page, tmp_path):
    mock_client.get_active_games.return_value = [
        {
            "game_id": "600",
            "game_type": "checkers",
            "url": "https://bga.com/checkers?table=600",
            "is_our_turn": True,
            "player_name": "me",
        }
    ]
    mock_client.navigate_to_game.return_value = mock_page

    with patch("bot.scheduler.REGISTRY") as mock_registry:
        mock_plugin = MagicMock()
        mock_plugin.return_value.is_our_turn = AsyncMock(return_value=False)
        mock_registry.get.return_value = mock_plugin

        await run_tick(mock_client, mock_llm, session, str(tmp_path))

    # No move should be recorded
    moves = get_moves_for_game(session, "600")
    assert len(moves) == 0


@pytest.mark.asyncio
async def test_successful_turn(mock_client, mock_llm, session, mock_page, tmp_path):
    mock_client.get_active_games.return_value = [
        {
            "game_id": "700",
            "game_type": "checkers",
            "url": "https://bga.com/checkers?table=700",
            "is_our_turn": True,
            "player_name": "me",
        }
    ]
    mock_client.navigate_to_game.return_value = mock_page

    mock_state = GameState(raw={"board": []}, summary="test board")
    mock_result = MoveResult(move_description="a1 -> b2", success=True)

    with patch("bot.scheduler.REGISTRY") as mock_registry:
        mock_plugin_instance = MagicMock()
        mock_plugin_instance.is_our_turn = AsyncMock(return_value=True)
        mock_plugin_instance.extract_state = AsyncMock(return_value=mock_state)
        mock_plugin_instance.build_prompt = MagicMock(return_value=("system", "user"))
        mock_plugin_instance.execute_move = AsyncMock(return_value=mock_result)

        mock_plugin_class = MagicMock(return_value=mock_plugin_instance)
        mock_registry.get.return_value = mock_plugin_class

        await run_tick(mock_client, mock_llm, session, str(tmp_path))

    moves = get_moves_for_game(session, "700")
    assert len(moves) == 1
    move = moves[0]
    assert move.success is True
    assert move.move_executed == "a1 -> b2"
    assert move.llm_reasoning == '{"from": "a1", "to": "b2"}'
    assert "system" in move.llm_prompt
    assert "user" in move.llm_prompt
    assert move.screenshot_path is not None


@pytest.mark.asyncio
async def test_plugin_exception_records_failure(mock_client, mock_llm, session, mock_page, tmp_path):
    mock_client.get_active_games.return_value = [
        {
            "game_id": "800",
            "game_type": "checkers",
            "url": "https://bga.com/checkers?table=800",
            "is_our_turn": True,
            "player_name": "me",
        }
    ]
    mock_client.navigate_to_game.return_value = mock_page

    with patch("bot.scheduler.REGISTRY") as mock_registry:
        mock_plugin_instance = MagicMock()
        mock_plugin_instance.is_our_turn = AsyncMock(return_value=True)
        mock_plugin_instance.extract_state = AsyncMock(side_effect=RuntimeError("DOM parse error"))

        mock_plugin_class = MagicMock(return_value=mock_plugin_instance)
        mock_registry.get.return_value = mock_plugin_class

        await run_tick(mock_client, mock_llm, session, str(tmp_path))

    moves = get_moves_for_game(session, "800")
    assert len(moves) == 1
    assert moves[0].success is False


@pytest.mark.asyncio
async def test_failed_move_recorded(mock_client, mock_llm, session, mock_page, tmp_path):
    mock_client.get_active_games.return_value = [
        {
            "game_id": "900",
            "game_type": "checkers",
            "url": "https://bga.com/checkers?table=900",
            "is_our_turn": True,
            "player_name": "me",
        }
    ]
    mock_client.navigate_to_game.return_value = mock_page

    mock_state = GameState(raw={"board": []}, summary="test")
    mock_result = MoveResult(
        move_description="bad move", success=False, error="Element not found"
    )

    with patch("bot.scheduler.REGISTRY") as mock_registry:
        mock_plugin_instance = MagicMock()
        mock_plugin_instance.is_our_turn = AsyncMock(return_value=True)
        mock_plugin_instance.extract_state = AsyncMock(return_value=mock_state)
        mock_plugin_instance.build_prompt = MagicMock(return_value=("sys", "usr"))
        mock_plugin_instance.execute_move = AsyncMock(return_value=mock_result)

        mock_plugin_class = MagicMock(return_value=mock_plugin_instance)
        mock_registry.get.return_value = mock_plugin_class

        await run_tick(mock_client, mock_llm, session, str(tmp_path))

    moves = get_moves_for_game(session, "900")
    assert len(moves) == 1
    assert moves[0].success is False
    assert moves[0].error_message == "Element not found"


@pytest.mark.asyncio
async def test_screenshot_captured_before_move(mock_client, mock_llm, session, mock_page, tmp_path):
    """Screenshot should be captured before execute_move is called."""
    call_order = []

    mock_client.get_active_games.return_value = [
        {
            "game_id": "1000",
            "game_type": "checkers",
            "url": "https://bga.com/checkers?table=1000",
            "is_our_turn": True,
            "player_name": "me",
        }
    ]
    mock_client.navigate_to_game.return_value = mock_page

    async def track_screenshot(*args, **kwargs):
        call_order.append("screenshot")

    mock_client.capture_screenshot = AsyncMock(side_effect=track_screenshot)

    mock_state = GameState(raw={}, summary="test")
    mock_result = MoveResult(move_description="move", success=True)

    with patch("bot.scheduler.REGISTRY") as mock_registry:
        mock_plugin_instance = MagicMock()
        mock_plugin_instance.is_our_turn = AsyncMock(return_value=True)
        mock_plugin_instance.extract_state = AsyncMock(return_value=mock_state)
        mock_plugin_instance.build_prompt = MagicMock(return_value=("s", "u"))

        async def track_execute(*args, **kwargs):
            call_order.append("execute")
            return mock_result

        mock_plugin_instance.execute_move = AsyncMock(side_effect=track_execute)

        mock_plugin_class = MagicMock(return_value=mock_plugin_instance)
        mock_registry.get.return_value = mock_plugin_class

        await run_tick(mock_client, mock_llm, session, str(tmp_path))

    assert call_order == ["screenshot", "execute"]


@pytest.mark.asyncio
async def test_get_active_games_failure(mock_client, mock_llm, session, tmp_path):
    mock_client.get_active_games = AsyncMock(side_effect=RuntimeError("Connection failed"))
    await run_tick(mock_client, mock_llm, session, str(tmp_path))
    # Should not crash


@pytest.mark.asyncio
async def test_invitations_accepted_before_games(mock_client, mock_llm, session, tmp_path):
    """accept_pending_invitations should be called before get_active_games."""
    call_order = []

    async def track_invitations():
        call_order.append("invitations")
        return []

    async def track_games():
        call_order.append("games")
        return []

    mock_client.accept_pending_invitations = AsyncMock(side_effect=track_invitations)
    mock_client.get_active_games = AsyncMock(side_effect=track_games)

    await run_tick(mock_client, mock_llm, session, str(tmp_path))
    assert call_order == ["invitations", "games"]


@pytest.mark.asyncio
async def test_invitation_failure_does_not_block_tick(mock_client, mock_llm, session, tmp_path):
    """If accept_pending_invitations fails, the tick should still check active games."""
    mock_client.accept_pending_invitations = AsyncMock(
        side_effect=RuntimeError("Toast not found")
    )
    mock_client.get_active_games.return_value = []

    await run_tick(mock_client, mock_llm, session, str(tmp_path))
    mock_client.get_active_games.assert_awaited_once()


@pytest.mark.asyncio
async def test_finished_game_screenshots_deleted(mock_client, mock_llm, session, tmp_path):
    """Screenshots for a game should be deleted when it's detected as finished."""
    # Pre-create a game that was previously active
    game = Game(
        id="999",
        game_type="checkers",
        bga_url="https://bga.com/checkers?table=999",
        status="active",
    )
    session.add(game)
    session.commit()

    # Create some screenshot files for this game
    screenshots_dir = tmp_path / "screenshots"
    screenshots_dir.mkdir(exist_ok=True)
    for ts in ["100", "200", "300"]:
        (screenshots_dir / f"999_{ts}.png").write_bytes(b"fake png")
    # Also create a screenshot for a different game that should NOT be deleted
    (screenshots_dir / f"888_100.png").write_bytes(b"other game")

    # Return no active games so game 999 is detected as finished
    mock_client.get_active_games.return_value = []
    mock_client.get_game_result = AsyncMock(return_value={"winner": "bob"})

    await run_tick(mock_client, mock_llm, session, str(tmp_path))

    # Game 999 screenshots should be gone
    remaining = list(screenshots_dir.iterdir())
    assert len(remaining) == 1
    assert remaining[0].name == "888_100.png"

    # Game should be marked finished
    session.refresh(game)
    assert game.status == "finished"
