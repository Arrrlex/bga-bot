import json
from unittest.mock import AsyncMock

import pytest

from bot.games.base import GameState
from bot.games.el_grande import ElGrandePlugin


@pytest.fixture
def plugin():
    return ElGrandePlugin()


@pytest.fixture
def sample_state():
    return GameState(
        raw={
            "regions": {
                "region_1": {"red": 3, "blue": 2},
                "region_2": {"red": 1, "green": 4},
            },
            "power_cards": [
                {"id": "powercard_1", "text": "Move 3 caballeros", "classes": "powercard"},
            ],
            "scores": {"Alice": "25", "Bob": "18"},
            "castillo_count": 5,
            "title": "You must choose a power card",
            "action_buttons": [
                {"id": "button_1", "text": "Select"},
            ],
        },
        summary="Phase: You must choose a power card\nScores: {}\nRegions: 2\nPower cards: 1",
    )


class TestBuildPrompt:
    def test_returns_tuple_of_strings(self, plugin, sample_state):
        result = plugin.build_prompt(sample_state)
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], str)
        assert isinstance(result[1], str)

    def test_system_prompt_contains_game_info(self, plugin, sample_state):
        system, _ = plugin.build_prompt(sample_state)
        assert "El Grande" in system
        assert "caballero" in system.lower()
        assert "Castillo" in system
        assert "JSON" in system

    def test_user_prompt_contains_state(self, plugin, sample_state):
        _, user = plugin.build_prompt(sample_state)
        assert "power card" in user
        assert "region_1" in user or "regions" in user

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
                "regions": {"r1": {"red": 2}},
                "power_cards": [],
                "scores": {"me": "10"},
                "castillo_count": 3,
                "title": "Your turn",
                "action_buttons": [],
            }
        )
        state = await plugin.extract_state(page)
        assert isinstance(state, GameState)
        assert "r1" in state.raw["regions"]
        assert len(state.summary) > 0


class TestExecuteMove:
    @pytest.mark.asyncio
    async def test_valid_move(self, plugin):
        page = AsyncMock()
        el = AsyncMock()
        page.query_selector = AsyncMock(return_value=el)
        page.wait_for_timeout = AsyncMock()

        llm_response = '{"action": "Select power card 5", "clicks": [{"selector": "powercard_5"}]}'
        result = await plugin.execute_move(page, llm_response)
        assert result.success is True
        assert "power card" in result.move_description

    @pytest.mark.asyncio
    async def test_element_not_found(self, plugin):
        page = AsyncMock()
        page.query_selector = AsyncMock(return_value=None)
        page.wait_for_timeout = AsyncMock()

        llm_response = '{"action": "click missing", "clicks": [{"selector": "#missing"}]}'
        result = await plugin.execute_move(page, llm_response)
        assert result.success is False
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_no_json_response(self, plugin):
        page = AsyncMock()
        result = await plugin.execute_move(page, "I want to place caballeros")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_invalid_json(self, plugin):
        page = AsyncMock()
        result = await plugin.execute_move(page, '{"action": broken json}')
        assert result.success is False

    @pytest.mark.asyncio
    async def test_playwright_error(self, plugin):
        page = AsyncMock()
        page.query_selector = AsyncMock(side_effect=RuntimeError("Browser crashed"))

        llm_response = '{"action": "test", "clicks": [{"selector": "#btn"}]}'
        result = await plugin.execute_move(page, llm_response)
        assert result.success is False
        assert "Browser crashed" in result.error

    @pytest.mark.asyncio
    async def test_multiple_clicks(self, plugin):
        page = AsyncMock()
        el = AsyncMock()
        page.query_selector = AsyncMock(return_value=el)
        page.wait_for_timeout = AsyncMock()

        llm_response = '{"action": "multi-step", "clicks": [{"selector": "#a"}, {"selector": "#b"}]}'
        result = await plugin.execute_move(page, llm_response)
        assert result.success is True
        assert page.query_selector.call_count == 2

    @pytest.mark.asyncio
    async def test_selector_prefix_added(self, plugin):
        """Bare IDs get # prefix added."""
        page = AsyncMock()
        el = AsyncMock()
        page.query_selector = AsyncMock(return_value=el)
        page.wait_for_timeout = AsyncMock()

        llm_response = '{"action": "click", "clicks": [{"selector": "mybutton"}]}'
        result = await plugin.execute_move(page, llm_response)
        assert result.success is True
        page.query_selector.assert_called_with("#mybutton")
