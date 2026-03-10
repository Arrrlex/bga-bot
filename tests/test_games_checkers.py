import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.games.base import GameState
from bot.games.checkers import CheckersPlugin


@pytest.fixture
def plugin():
    return CheckersPlugin()


@pytest.fixture
def sample_state():
    return GameState(
        raw={
            "board_size": 10,
            "pieces": {
                "1": {"x": 2, "y": 7, "type": "man", "color": "white", "player_id": "100", "is_ours": True},
                "2": {"x": 3, "y": 2, "type": "man", "color": "black", "player_id": "200", "is_ours": False},
            },
            "valid_moves": {
                "1": [{"dest_x": 3, "dest_y": 6, "captures": False, "successive": []}],
            },
            "players": {"100": {"name": "us", "score": "0", "color": "ffffff"}, "200": {"name": "them", "score": "0", "color": "000000"}},
            "our_player_id": "100",
            "title": "You must select a piece",
        },
        summary="Board: 10x10 International Draughts\nStatus: You must select a piece\nWe are white, moving UP (toward row 0, our home is rows 6-9)\n\nOur pieces (1):\n  Piece 1 (man) at (2,7)\n\nOpponent pieces (1):\n  Piece 2 (man) at (3,2)\n\nValid moves (1 pieces can move):\n  Piece 1 (man) at (2,7) -> (3,6)",
    )


class TestBuildPrompt:
    def test_returns_tuple_of_strings(self, plugin, sample_state):
        result = plugin.build_prompt(sample_state)
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], str)
        assert isinstance(result[1], str)

    def test_system_prompt_contains_game_rules(self, plugin, sample_state):
        system, _ = plugin.build_prompt(sample_state)
        assert "Checkers" in system or "checkers" in system.lower()
        assert "capture" in system.lower()
        assert "king" in system.lower()
        assert "JSON" in system

    def test_user_prompt_contains_board_state(self, plugin, sample_state):
        _, user = plugin.build_prompt(sample_state)
        assert "You must select a piece" in user
        assert "Piece 1" in user

    def test_prompts_are_nonempty(self, plugin, sample_state):
        system, user = plugin.build_prompt(sample_state)
        assert len(system) > 50
        assert len(user) > 20


class TestIsOurTurn:
    @pytest.mark.asyncio
    async def test_our_turn(self, plugin):
        page = AsyncMock()
        page.evaluate = AsyncMock(return_value=True)
        assert await plugin.is_our_turn(page) is True

    @pytest.mark.asyncio
    async def test_not_our_turn(self, plugin):
        page = AsyncMock()
        page.evaluate = AsyncMock(return_value=False)
        assert await plugin.is_our_turn(page) is False


class TestExtractState:
    @pytest.mark.asyncio
    async def test_returns_game_state(self, plugin):
        page = AsyncMock()
        page.evaluate = AsyncMock(
            return_value={
                "board_size": 10,
                "pieces": {
                    "1": {"x": 0, "y": 7, "type": "man", "color": "white", "player_id": "100", "is_ours": True},
                },
                "valid_moves": {},
                "players": {"100": {"name": "us", "score": "0", "color": "ffffff"}},
                "our_player_id": "100",
                "title": "Your turn",
            }
        )
        state = await plugin.extract_state(page)
        assert isinstance(state, GameState)
        assert "1" in state.raw["pieces"]
        assert len(state.summary) > 0


class TestExecuteMove:
    @pytest.mark.asyncio
    async def test_valid_move(self, plugin):
        page = AsyncMock()
        page.click = AsyncMock()
        page.wait_for_timeout = AsyncMock()
        page.evaluate = AsyncMock(return_value="Waiting for opponent")

        llm_response = '{"piece_id": "1", "dest_x": 3, "dest_y": 6}'
        result = await plugin.execute_move(page, llm_response)
        assert result.success is True
        assert "piece_1" in result.move_description

    @pytest.mark.asyncio
    async def test_multi_jump(self, plugin):
        page = AsyncMock()
        page.click = AsyncMock()
        page.wait_for_timeout = AsyncMock()
        # First evaluate returns "must continue", second returns successive moves
        page.evaluate = AsyncMock(
            side_effect=[
                "You must continue jumping",
                {"1": [{"dest_x": 5, "dest_y": 4}]},
            ]
        )

        llm_response = '{"piece_id": "1", "dest_x": 3, "dest_y": 6}'
        result = await plugin.execute_move(page, llm_response)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_no_json_in_response(self, plugin):
        page = AsyncMock()
        result = await plugin.execute_move(page, "I don't know what to do")
        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_invalid_json(self, plugin):
        page = AsyncMock()
        result = await plugin.execute_move(page, '{"piece_id": broken}')
        assert result.success is False

    @pytest.mark.asyncio
    async def test_playwright_error(self, plugin):
        page = AsyncMock()
        page.click = AsyncMock(side_effect=RuntimeError("Timeout"))
        page.wait_for_timeout = AsyncMock()

        llm_response = '{"piece_id": "1", "dest_x": 3, "dest_y": 6}'
        result = await plugin.execute_move(page, llm_response)
        assert result.success is False
        assert "Timeout" in result.error
