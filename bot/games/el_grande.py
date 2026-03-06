import json
import logging

from playwright.async_api import Page

from .base import GamePlugin, GameState, MoveResult

logger = logging.getLogger(__name__)


class ElGrandePlugin(GamePlugin):
    game_id = "elgrande"

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
                // Extract region caballero counts
                const regions = {};
                document.querySelectorAll('[id^="region_"], .region').forEach(r => {
                    const id = r.id || r.className;
                    const caballeros = r.querySelectorAll('.caballero, [class*="cube"]');
                    const counts = {};
                    caballeros.forEach(c => {
                        const color = c.className.match(/color_(\\w+)/) ||
                                     c.className.match(/(red|blue|green|yellow|purple)/);
                        if (color) {
                            const key = color[1];
                            counts[key] = (counts[key] || 0) + 1;
                        }
                    });
                    regions[id] = counts;
                });

                // Extract power cards in hand
                const powerCards = [];
                document.querySelectorAll('.powercard, .action_card, [id^="powercard_"]').forEach(c => {
                    powerCards.push({
                        id: c.id || '',
                        text: c.textContent.trim().substring(0, 100),
                        classes: c.className || '',
                    });
                });

                // Extract scores
                const scores = {};
                document.querySelectorAll('.player-name').forEach(el => {
                    const name = el.textContent.trim();
                    const scoreEl = el.closest('.player_board_content, .player-board')
                        ?.querySelector('.player_score, [id^="player_score_"]');
                    if (scoreEl) scores[name] = scoreEl.textContent.trim();
                });

                // Extract castillo count
                const castillo = document.querySelector('#castillo, .castillo, [id*="castillo"]');
                let castilloCount = 0;
                if (castillo) {
                    castilloCount = castillo.querySelectorAll('.caballero, [class*="cube"]').length;
                }

                // Current phase/action info
                const titleEl = document.querySelector('#pagemaintitletext');
                const title = titleEl ? titleEl.textContent : '';

                // Available actions
                const actionButtons = [];
                document.querySelectorAll('.action-button, [id^="button_"], .bgabutton').forEach(b => {
                    if (b.offsetParent !== null) {  // visible
                        actionButtons.push({
                            id: b.id || '',
                            text: b.textContent.trim(),
                        });
                    }
                });

                return {
                    regions: regions,
                    power_cards: powerCards,
                    scores: scores,
                    castillo_count: castilloCount,
                    title: title,
                    action_buttons: actionButtons,
                };
            }
        """)

        summary_parts = [f"Phase: {raw.get('title', 'unknown')}"]
        if raw.get("scores"):
            summary_parts.append(f"Scores: {json.dumps(raw['scores'])}")
        summary_parts.append(f"Regions with caballeros: {len(raw.get('regions', {}))}")
        summary_parts.append(f"Power cards in hand: {len(raw.get('power_cards', []))}")
        summary_parts.append(f"Castillo caballeros: {raw.get('castillo_count', 0)}")
        if raw.get("action_buttons"):
            buttons = [b["text"] for b in raw["action_buttons"]]
            summary_parts.append(f"Available actions: {', '.join(buttons)}")

        return GameState(raw=raw, summary="\n".join(summary_parts))

    def build_prompt(self, state: GameState) -> tuple[str, str]:
        system_prompt = """You are playing El Grande on BoardGameArena.

Rules:
- El Grande is an area-majority game set in medieval Spain
- Each round: choose a power card (determines turn order and number of caballeros from province to court), then choose an action card
- Action cards let you place caballeros from your court into regions and perform special actions
- The Castillo (castle) is a secret region scored during scoring rounds
- Scoring happens in rounds 3, 6, and 9: each region scores for 1st/2nd/3rd place majority
- The King marks one region where no caballeros can be placed or removed
- Grande (large piece) counts as a caballero for majority but cannot be moved
- Goal: most points at end of 9 rounds

Strategy tips:
- Diversify presence across regions rather than committing everything to one area
- The Castillo is powerful for swinging scores during scoring rounds
- Power cards with higher numbers give more caballeros but mean you act later
- Watch opponents' court sizes and region commitments

Respond with your action in this exact JSON format:
{"action": "<description>", "clicks": [{"selector": "<css_selector_or_id>"}]}

The clicks array should contain the CSS selectors or element IDs to click in order.
Be specific with selectors. If clicking a region, use the region's ID."""

        user_prompt = f"""Current game state:

{state.summary}

Full state data:
{json.dumps(state.raw, indent=2)}

What is your move?"""

        return system_prompt, user_prompt

    async def execute_move(self, page: Page, llm_response: str) -> MoveResult:
        try:
            response_text = llm_response.strip()
            start = response_text.find("{")
            end = response_text.rfind("}") + 1
            if start == -1 or end == 0:
                return MoveResult(
                    move_description="Failed to parse move",
                    success=False,
                    error=f"No JSON found in LLM response: {response_text[:200]}",
                )

            move_data = json.loads(response_text[start:end])
            action_desc = move_data.get("action", "unknown action")
            clicks = move_data.get("clicks", [])

            for click in clicks:
                selector = click.get("selector", "")
                if not selector:
                    continue

                # Try as ID first, then as CSS selector
                if not selector.startswith(("#", ".", "[")):
                    selector = f"#{selector}"

                el = await page.query_selector(selector)
                if el:
                    await el.click()
                    await page.wait_for_timeout(500)
                else:
                    return MoveResult(
                        move_description=action_desc,
                        success=False,
                        error=f"Element not found: {selector}",
                    )

            await page.wait_for_timeout(1000)

            return MoveResult(
                move_description=action_desc,
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
