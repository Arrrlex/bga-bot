"""Integration tests for BGAClient. Requires live BGA credentials."""

import pytest

from bot.bga_client import BGAClient


@pytest.mark.asyncio
async def test_login_and_get_games():
    client = BGAClient()
    try:
        await client.start()
        games = await client.get_active_games()
        assert isinstance(games, list)
        for game in games:
            assert "game_id" in game
            assert "game_type" in game
            assert "url" in game
    finally:
        await client.close()
