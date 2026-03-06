import json
import logging

from playwright.async_api import Page

from .base import GamePlugin, GameState, MoveResult

logger = logging.getLogger(__name__)


class CheckersPlugin(GamePlugin):
    game_id = "checkers"

    async def is_our_turn(self, page: Page) -> bool:
        return await page.evaluate("""
            () => {
                const titleEl = document.querySelector('#pagemaintitletext');
                if (!titleEl) return false;
                const text = titleEl.textContent.toLowerCase();
                return text.includes('you must') || text.includes('your turn');
            }
        """)

    async def extract_state(self, page: Page) -> GameState:
        raw = await page.evaluate("""
            () => {
                const board = [];
                // BGA checkers uses an 8x8 grid with pieces as elements
                const pieces = document.querySelectorAll('.checkers_piece, [id^="piece_"]');
                pieces.forEach(p => {
                    const style = p.getAttribute('style') || '';
                    const classes = p.className || '';
                    const id = p.id || '';
                    board.push({
                        id: id,
                        classes: classes,
                        style: style,
                    });
                });

                // Get available moves if highlighted
                const highlights = document.querySelectorAll('.possibleMove, .possible_move, [class*="possible"]');
                const possibleMoves = [];
                highlights.forEach(h => {
                    possibleMoves.push({
                        id: h.id || '',
                        classes: h.className || '',
                    });
                });

                // Get current player info
                const titleEl = document.querySelector('#pagemaintitletext');
                const title = titleEl ? titleEl.textContent : '';

                // Get scores
                const scores = {};
                document.querySelectorAll('.player-name').forEach(el => {
                    const name = el.textContent.trim();
                    const scoreEl = el.closest('.player_board_content, .player-board')
                        ?.querySelector('.player_score, [id^="player_score_"]');
                    if (scoreEl) scores[name] = scoreEl.textContent.trim();
                });

                return {
                    board: board,
                    possible_moves: possibleMoves,
                    title: title,
                    scores: scores,
                };
            }
        """)

        summary_parts = [f"Title: {raw.get('title', 'unknown')}"]
        if raw.get("scores"):
            summary_parts.append(f"Scores: {json.dumps(raw['scores'])}")
        summary_parts.append(f"Pieces on board: {len(raw.get('board', []))}")
        summary_parts.append(f"Possible moves highlighted: {len(raw.get('possible_moves', []))}")

        return GameState(raw=raw, summary="\n".join(summary_parts))

    def build_prompt(self, state: GameState) -> tuple[str, str]:
        system_prompt = """You are playing Checkers (Draughts) on BoardGameArena.

Rules:
- Standard 8x8 checkers on dark squares only
- Regular pieces move diagonally forward one square
- Kings (promoted pieces) can move diagonally forward or backward
- Captures are mandatory: you must jump over opponent pieces when possible
- Multi-jumps: if after a capture another capture is available, you must continue
- A piece reaching the opposite back row is promoted to king
- You win by capturing all opponent pieces or leaving them with no legal moves

You will be given the current board state. Respond with your move in this exact JSON format:
{"from": "<square_id>", "to": "<square_id>"}

If multiple jumps are required, use:
{"moves": [{"from": "<id>", "to": "<id>"}, {"from": "<id>", "to": "<id>"}]}

Use the piece and square IDs from the board state. Pick the best strategic move available."""

        user_prompt = f"""Current board state:

{state.summary}

Full board data:
{json.dumps(state.raw, indent=2)}

What is your move?"""

        return system_prompt, user_prompt

    async def execute_move(self, page: Page, llm_response: str) -> MoveResult:
        try:
            # Parse LLM response - extract JSON
            response_text = llm_response.strip()
            # Find JSON in the response
            start = response_text.find("{")
            end = response_text.rfind("}") + 1
            if start == -1 or end == 0:
                return MoveResult(
                    move_description="Failed to parse move",
                    success=False,
                    error=f"No JSON found in LLM response: {response_text[:200]}",
                )

            move_data = json.loads(response_text[start:end])

            if "moves" in move_data:
                # Multi-jump
                moves = move_data["moves"]
            else:
                moves = [move_data]

            descriptions = []
            for move in moves:
                from_id = move["from"]
                to_id = move["to"]

                # Click the piece to select it
                from_el = await page.query_selector(f"#{from_id}, [id='{from_id}']")
                if from_el:
                    await from_el.click()
                    await page.wait_for_timeout(500)

                # Click the destination
                to_el = await page.query_selector(f"#{to_id}, [id='{to_id}']")
                if to_el:
                    await to_el.click()
                    await page.wait_for_timeout(500)

                descriptions.append(f"{from_id} -> {to_id}")

            # Wait for move to be processed
            await page.wait_for_timeout(1000)

            return MoveResult(
                move_description=", ".join(descriptions),
                success=True,
            )

        except json.JSONDecodeError as e:
            return MoveResult(
                move_description="Failed to parse move JSON",
                success=False,
                error=f"JSON parse error: {e}",
            )
        except Exception as e:
            return MoveResult(
                move_description="Move execution failed",
                success=False,
                error=str(e),
            )
