import pytest

from bot.games.base import GamePlugin, GameState, MoveResult


def test_cannot_instantiate_abstract_plugin():
    """A concrete plugin missing any abstract method raises TypeError."""
    with pytest.raises(TypeError):
        GamePlugin()


def test_incomplete_plugin_raises():
    """A subclass that doesn't implement all methods raises TypeError."""

    class PartialPlugin(GamePlugin):
        game_id = "test"

        async def is_our_turn(self, page):
            return True

        # Missing extract_state, build_prompt, execute_move

    with pytest.raises(TypeError):
        PartialPlugin()


def test_complete_plugin_instantiates():
    """A fully implemented subclass can be instantiated."""

    class CompletePlugin(GamePlugin):
        game_id = "test"

        async def is_our_turn(self, page):
            return True

        async def extract_state(self, page):
            return GameState(raw={}, summary="")

        def build_prompt(self, state):
            return ("system", "user")

        async def execute_move(self, page, llm_response):
            return MoveResult(move_description="test", success=True)

    plugin = CompletePlugin()
    assert plugin.game_id == "test"


def test_game_state_dataclass():
    state = GameState(raw={"key": "value"}, summary="A summary")
    assert state.raw == {"key": "value"}
    assert state.summary == "A summary"


def test_move_result_dataclass():
    result = MoveResult(move_description="a -> b", success=True)
    assert result.error is None

    result2 = MoveResult(move_description="bad", success=False, error="oops")
    assert result2.error == "oops"
