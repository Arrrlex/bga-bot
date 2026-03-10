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
            "round": 3,
            "king_region": "cataluna",
            "state_name": "powerCard",
            "state_description": "You must choose a power card",
            "possible_actions": ["choosePowerCard"],
            "state_args": {},
            "players": {
                "100": {
                    "name": "Alice", "color": "ff0000", "score": "25",
                    "court": "4", "province": "8", "castillo": "2", "grande": "galicia",
                    "regions": {"galicia": 3, "valencia": 2},
                },
            },
            "regions": {"1": {"name": "Galicia", "score": "4/2/1", "neighbours": ["paisvasco"]}},
            "hand": [{"id": "42", "type": "6", "caballeros_from_province": 3}],
            "hand_discarded": [],
            "action_cards": [],
            "title": "You must choose a power card",
        },
        summary="Round: 3 | King in: cataluna\nPhase: You must choose a power card\nState: powerCard | Actions: ['choosePowerCard']\n\nPlayers:\n  Alice (#ff0000): score=25, court=4, province=8, castillo=2, grande=galicia\n    Regions: galicia:3, valencia:2\n\nRegion scores (1st/2nd/3rd):\n  Galicia: 4/2/1 (neighbours: paisvasco)\n\nPower cards in hand:\n  Card 42: power=6 (moves 3 from province)",
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
        assert "power card" in user.lower()
        assert "Round: 3" in user

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
                "round": 1,
                "king_region": "galicia",
                "state_name": "powerCard",
                "state_description": "Choose a power card",
                "possible_actions": ["choosePowerCard"],
                "state_args": {},
                "players": {
                    "100": {
                        "name": "me", "color": "ff0000", "score": "10",
                        "court": "3", "province": "5", "castillo": "1", "grande": "aragon",
                        "regions": {"aragon": 2},
                    },
                },
                "regions": {"1": {"name": "Galicia", "score": "4/2/1", "neighbours": []}},
                "hand": [],
                "hand_discarded": [],
                "action_cards": [],
                "title": "Your turn",
            }
        )
        state = await plugin.extract_state(page)
        assert isinstance(state, GameState)
        assert state.raw["king_region"] == "galicia"
        assert len(state.summary) > 0


class TestExecuteMove:
    @pytest.mark.asyncio
    async def test_select_region(self, plugin):
        page = AsyncMock()
        page.evaluate = AsyncMock(return_value="svg")
        page.wait_for_timeout = AsyncMock()
        page.query_selector = AsyncMock(return_value=None)

        llm_response = '{"region": "valencia"}'
        result = await plugin.execute_move(page, llm_response)
        assert result.success is True
        assert "valencia" in result.move_description

    @pytest.mark.asyncio
    async def test_select_card(self, plugin):
        page = AsyncMock()
        el = AsyncMock()
        page.query_selector = AsyncMock(return_value=el)
        page.wait_for_timeout = AsyncMock()

        llm_response = '{"card_id": "42"}'
        result = await plugin.execute_move(page, llm_response)
        assert result.success is True
        assert "42" in result.move_description

    @pytest.mark.asyncio
    async def test_region_not_found(self, plugin):
        page = AsyncMock()
        page.evaluate = AsyncMock(return_value=None)
        page.wait_for_timeout = AsyncMock()

        llm_response = '{"region": "nonexistent"}'
        result = await plugin.execute_move(page, llm_response)
        assert result.success is False
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_card_not_found(self, plugin):
        page = AsyncMock()
        page.query_selector = AsyncMock(return_value=None)
        page.wait_for_timeout = AsyncMock()

        llm_response = '{"card_id": "999"}'
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
        page.evaluate = AsyncMock(side_effect=RuntimeError("Browser crashed"))

        llm_response = '{"region": "galicia"}'
        result = await plugin.execute_move(page, llm_response)
        assert result.success is False
        assert "Browser crashed" in result.error

    @pytest.mark.asyncio
    async def test_place_caballeros(self, plugin):
        page = AsyncMock()
        page.click = AsyncMock()
        page.wait_for_timeout = AsyncMock()
        page.evaluate = AsyncMock(return_value="")

        llm_response = '{"count": 3}'
        result = await plugin.execute_move(page, llm_response)
        assert result.success is True
        assert "3" in result.move_description
