import json
import logging
import time
from datetime import datetime, timezone

from sqlmodel import Session

from .bga_client import BGAClient
from .db import Game, Move, get_all_games, record_move, upsert_game
from .games import REGISTRY
from .llm import LLMProvider

logger = logging.getLogger(__name__)


def _timestamp() -> str:
    return str(int(time.time()))


async def run_tick(client: BGAClient, llm: LLMProvider, session: Session, data_dir: str = "/data"):
    """Main loop: check all active games, play turns where it's our move."""
    logger.info("Starting tick")

    # Accept any pending game invitations before checking active games
    try:
        accepted = await client.accept_pending_invitations()
        if accepted:
            logger.info("Accepted %d invitation(s): %s", len(accepted), accepted)
    except Exception:
        logger.exception("Failed to check/accept invitations")

    try:
        active_games = await client.get_active_games()
    except Exception:
        logger.exception("Failed to fetch active games")
        return

    logger.info("Found %d active games", len(active_games))

    for game_info in active_games:
        game_id = game_info["game_id"]
        game_type = game_info["game_type"]

        try:
            db_game = upsert_game(session, game_info)

            plugin_class = REGISTRY.get(game_type)
            if plugin_class is None:
                logger.warning("No plugin for game type: %s (game %s)", game_type, game_id)
                db_game.status = "unknown"
                session.commit()
                continue

            plugin = plugin_class()
            page = await client.navigate_to_game(game_info["url"])

            try:
                # Extract player names from gameui (authoritative source)
                if not db_game.players:
                    players = await page.evaluate("""
                        () => {
                            try {
                                return Object.values(gameui.gamedatas.players)
                                    .map(p => p.name).join(', ');
                            } catch(e) { return ''; }
                        }
                    """)
                    if players:
                        db_game.players = players
                        session.commit()

                if not await plugin.is_our_turn(page):
                    logger.info("Not our turn in game %s", game_id)
                    continue

                state = await plugin.extract_state(page)
                system_prompt, user_prompt = plugin.build_prompt(state)

                screenshot_path = f"screenshots/{game_id}_{_timestamp()}.png"
                await client.capture_screenshot(page, f"{data_dir}/{screenshot_path}")

                llm_response = await llm.complete(system_prompt, user_prompt)
                result = await plugin.execute_move(page, llm_response)

                record_move(
                    session,
                    Move(
                        game_id=game_id,
                        timestamp=datetime.now(timezone.utc),
                        board_state_json=json.dumps(state.raw),
                        llm_prompt=f"SYSTEM:\n{system_prompt}\n\nUSER:\n{user_prompt}",
                        llm_reasoning=llm_response,
                        move_executed=result.move_description,
                        screenshot_path=screenshot_path,
                        success=result.success,
                        error_message=result.error,
                    ),
                )
                logger.info(
                    "Game %s: move=%s success=%s", game_id, result.move_description, result.success
                )

            finally:
                await page.close()

        except Exception:
            logger.exception("Error processing game %s", game_id)
            try:
                record_move(
                    session,
                    Move(
                        game_id=game_id,
                        timestamp=datetime.now(timezone.utc),
                        move_executed="Error during processing",
                        success=False,
                        error_message=f"Unhandled exception in game {game_id}",
                    ),
                )
            except Exception:
                logger.exception("Failed to record error move for game %s", game_id)

    # Detect finished games: active in DB but not in BGA active list
    active_ids = {g["game_id"] for g in active_games}
    db_games = get_all_games(session)
    for db_game in db_games:
        if db_game.status == "active" and db_game.id not in active_ids:
            logger.info("Game %s no longer active, checking result", db_game.id)
            try:
                result = await client.get_game_result(db_game.bga_url)
                db_game.status = "finished"
                if result.get("winner"):
                    db_game.winner = result["winner"]
                if result.get("players") and not db_game.players:
                    db_game.players = result["players"]
                session.commit()
                logger.info("Game %s finished, winner: %s", db_game.id, db_game.winner or "unknown")
            except Exception:
                logger.exception("Failed to get result for game %s", db_game.id)
                db_game.status = "finished"
                session.commit()

    logger.info("Tick complete")
