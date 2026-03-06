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
            "board": [
                {"id": "piece_1", "classes": "checkers_piece white", "style": "top:0px;left:0px"},
                {"id": "piece_2", "classes": "checkers_piece black", "style": "top:100px;left:100px"},
            ],
            "possible_moves": [
                {"id": "square_10", "classes": "possibleMove"},
            ],
            "title": "You must play",
            "scores": {"player1": "2", "player2": "1"},
        },
        summary="Title: You must play\nScores: {}\nPieces on board: 2\nPossible moves highlighted: 1",
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
        assert "You must play" in user
        assert "piece_1" in user or "board" in user

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
                "board": [{"id": "p1", "classes": "piece", "style": ""}],
                "possible_moves": [],
                "title": "Your turn",
                "scores": {"me": "3"},
            }
        )
        state = await plugin.extract_state(page)
        assert isinstance(state, GameState)
        assert state.raw["board"]
        assert len(state.summary) > 0


class TestExecuteMove:
    @pytest.mark.asyncio
    async def test_valid_move(self, plugin):
        page = AsyncMock()
        from_el = AsyncMock()
        to_el = AsyncMock()
        page.query_selector = AsyncMock(side_effect=[from_el, to_el])
        page.wait_for_timeout = AsyncMock()

        llm_response = '{"from": "piece_1", "to": "square_10"}'
        result = await plugin.execute_move(page, llm_response)
        assert result.success is True
        assert "piece_1" in result.move_description
        assert "square_10" in result.move_description

    @pytest.mark.asyncio
    async def test_multi_jump(self, plugin):
        page = AsyncMock()
        elements = [AsyncMock() for _ in range(4)]
        page.query_selector = AsyncMock(side_effect=elements)
        page.wait_for_timeout = AsyncMock()

        llm_response = '{"moves": [{"from": "p1", "to": "s1"}, {"from": "s1", "to": "s2"}]}'
        result = await plugin.execute_move(page, llm_response)
        assert result.success is True
        assert "p1" in result.move_description

    @pytest.mark.asyncio
    async def test_no_json_in_response(self, plugin):
        page = AsyncMock()
        result = await plugin.execute_move(page, "I don't know what to do")
        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_invalid_json(self, plugin):
        page = AsyncMock()
        result = await plugin.execute_move(page, '{"from": broken}')
        assert result.success is False

    @pytest.mark.asyncio
    async def test_playwright_error(self, plugin):
        page = AsyncMock()
        page.query_selector = AsyncMock(side_effect=RuntimeError("Timeout"))

        llm_response = '{"from": "p1", "to": "s1"}'
        result = await plugin.execute_move(page, llm_response)
        assert result.success is False
        assert "Timeout" in result.error
