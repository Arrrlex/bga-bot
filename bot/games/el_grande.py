import json
import logging

from playwright.async_api import Page

from .base import GamePlugin, GameState, MoveResult, extract_json

logger = logging.getLogger(__name__)

REGION_NAMES = [
    "castillo", "galicia", "paisvasco", "aragon", "cataluna",
    "castilla_la_vieja", "castilla_la_nueva", "sevilla", "granada", "valencia",
]


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
                const gd = gameui.gamedatas;
                const gs = gd.gamestate;
                const globals = gd.globals;

                // Player info with caballero counts per region
                const players = {};
                for (const [pid, p] of Object.entries(gd.players)) {
                    players[pid] = {
                        name: p.name,
                        color: p.color,
                        score: p.score,
                        court: p.court,
                        province: p.province,
                        castillo: p.castillo,
                        grande: p.grande,
                        regions: {},
                    };
                    // Region counts are stored directly on the player object
                    const regionNames = [
                        'galicia', 'paisvasco', 'aragon', 'cataluna',
                        'castilla_la_vieja', 'castilla_la_nueva',
                        'sevilla', 'granada', 'valencia',
                    ];
                    for (const r of regionNames) {
                        if (p[r] !== undefined) {
                            players[pid].regions[r] = parseInt(p[r]);
                        }
                    }
                }

                // Region scoring info
                const regions = {};
                if (gd.regions) {
                    for (const [rId, r] of Object.entries(gd.regions)) {
                        regions[rId] = {
                            name: r.name,
                            score: r.score,
                            neighbours: r.neighbours,
                        };
                    }
                }

                // Our power cards in hand
                const hand = [];
                if (gd.hand) {
                    for (const [cId, c] of Object.entries(gd.hand)) {
                        // Power card type maps to caballero count via powerCards table
                        const pcValue = gd.powerCards?.[c.type];
                        hand.push({
                            id: cId,
                            type: c.type,
                            caballeros_from_province: pcValue !== undefined ? pcValue : '?',
                        });
                    }
                }

                // Discarded power cards
                const discarded = [];
                if (gd.hand_discard) {
                    for (const [cId, c] of Object.entries(gd.hand_discard)) {
                        discarded.push({id: cId, type: c.type});
                    }
                }

                // Action cards on display
                const actionCards = [];
                if (gd.action) {
                    for (const [aId, a] of Object.entries(gd.action)) {
                        const cardDef = gd.actionCards?.[a.type] || {};
                        actionCards.push({
                            id: aId,
                            type: a.type,
                            title: cardDef.title || '',
                            description: cardDef.description || '',
                            taken_by: a.location_arg || null,
                        });
                    }
                }

                return {
                    round: gd.round,
                    king_region: globals?.king || '',
                    state_name: gs.name,
                    state_description: gs.descriptionmyturn || gs.description || '',
                    possible_actions: gs.possibleactions || [],
                    state_args: gs.args || {},
                    players: players,
                    regions: regions,
                    hand: hand,
                    hand_discarded: discarded,
                    action_cards: actionCards,
                    title: document.querySelector('#pagemaintitletext')?.textContent?.trim() || '',
                };
            }
        """)

        # Build readable summary
        parts = [
            f"Round: {raw.get('round', '?')} | King in: {raw.get('king_region', '?')}",
            f"Phase: {raw.get('title', '')}",
            f"State: {raw.get('state_name', '')} | Actions: {raw.get('possible_actions', [])}",
        ]

        # State-specific args (e.g. number of caballeros to place, allowed regions)
        state_args = raw.get("state_args", {})
        if state_args:
            parts.append(f"State args: {json.dumps(state_args)}")

        # Player summary
        parts.append("\nPlayers:")
        for pid, p in raw.get("players", {}).items():
            parts.append(
                f"  {p['name']} (#{p['color']}): score={p['score']}, "
                f"court={p.get('court', 0)}, province={p.get('province', 0)}, "
                f"castillo={p.get('castillo', 0)}, grande={p.get('grande', '')}"
            )
            # Always show all regions, even if 0, so the model has full board info
            regions = p.get("regions", {})
            if regions:
                region_str = ", ".join(f"{r}:{c}" for r, c in regions.items())
                parts.append(f"    Regions: {region_str}")

        # Region scoring
        parts.append("\nRegion scores (1st/2nd/3rd):")
        for rId, r in raw.get("regions", {}).items():
            neighbours = r.get("neighbours", [])
            neighbour_str = f" (neighbours: {', '.join(neighbours)})" if neighbours else ""
            parts.append(f"  {r['name']}: {r['score']}{neighbour_str}")

        # Power cards in hand
        if raw.get("hand"):
            parts.append("\nPower cards in hand:")
            for c in raw["hand"]:
                parts.append(f"  Card {c['id']}: power={c['type']} (moves {c['caballeros_from_province']} from province)")

        # Discarded power cards
        if raw.get("hand_discarded"):
            parts.append("\nDiscarded power cards:")
            for c in raw["hand_discarded"]:
                parts.append(f"  Card {c['id']}: power={c['type']}")

        # Action cards
        if raw.get("action_cards"):
            parts.append("\nAction cards this round:")
            for c in raw["action_cards"]:
                taken = f" [TAKEN by player {c['taken_by']}]" if c["taken_by"] else " [AVAILABLE]"
                desc = f" - {c['description']}" if c["description"] else ""
                parts.append(f"  Card {c['id']} \"{c['title']}\"{desc}{taken}")

        return GameState(raw=raw, summary="\n".join(parts))

    def build_prompt(self, state: GameState) -> tuple[str, str]:
        state_name = state.raw.get("state_name", "")
        possible_actions = state.raw.get("possible_actions", [])

        system_prompt = """You are playing El Grande on BoardGameArena.

El Grande is an area-majority game set in medieval Spain with 9 regions.
- Each round: choose a power card (determines turn order + caballeros moved from province to court), then choose an action card
- Action cards let you place caballeros from court into regions adjacent to the King, plus a special action
- The Castillo is a secret region scored during scoring rounds (3, 6, 9)
- When the Castillo scores, each player secretly picks a region to receive their castillo caballeros
- The King marks a region where no caballeros can be placed or removed
- Grande counts for majority but cannot be moved

The 9 regions are: Galicia, Pais Vasco, Aragon, Cataluna, Castilla la Vieja, Castilla la Nueva, Sevilla, Granada, Valencia.

Region IDs (for your response): galicia, paisvasco, aragon, cataluna, castilla_la_vieja, castilla_la_nueva, sevilla, granada, valencia, castillo

Strategy: Control high-value regions, use the Castillo strategically during scoring rounds, diversify presence.

IMPORTANT: Respond with ONLY a JSON object. The format depends on the current action required."""

        # Customize instructions based on current state
        if state_name == "chooseRegion":
            action_prompt = """Current action: Choose a secret region for the Castillo scoring.
Your castillo caballeros will be placed in the region you choose.
Pick the region where the extra caballeros will give you the best majority advantage.

Respond with: {"region": "<region_id>"}
Example: {"region": "valencia"}"""
        elif "powerCard" in state_name.lower() or "choosePowerCard" in possible_actions:
            action_prompt = """Current action: Choose a power card.
Higher power = more caballeros from province to court, but you act later.
Lower power = fewer caballeros but you act first.

Respond with: {"card_id": "<id>"}"""
        elif "actionCard" in state_name.lower() or "chooseActionCard" in possible_actions:
            action_prompt = """Current action: Choose an action card.
Pick the card whose special action benefits you most.

Respond with: {"card_id": "<id>"}"""
        elif "placeCaballeros" in state_name.lower() or "placeCaballeros" in possible_actions:
            action_prompt = """Current action: Place caballeros from your court into regions.
You can place into regions adjacent to the King's region.

Respond with: {"region": "<region_id>", "count": <number>}"""
        else:
            action_prompt = f"""Current action: {state.raw.get('title', 'unknown')}
Possible actions: {possible_actions}

Respond with the appropriate action as a JSON object.
For clicking a region: {{"region": "<region_id>"}}
For clicking a button/card: {{"click": "<element_description>"}}"""

        user_prompt = f"""{action_prompt}

{state.summary}

Respond with ONLY the JSON object."""

        return system_prompt, user_prompt

    async def execute_move(self, page: Page, llm_response: str) -> MoveResult:
        try:
            move_data = extract_json(llm_response)
            state_name = await page.evaluate("() => gameui.gamedatas.gamestate.name")

            if "region" in move_data:
                region = move_data["region"]
                # Click the SVG region path or the stock div
                clicked = await page.evaluate(f"""
                    () => {{
                        // Try SVG path first (for region selection)
                        const path = document.querySelector('#{region}');
                        if (path) {{ path.dispatchEvent(new Event('click', {{bubbles: true}})); return 'svg'; }}
                        // Try stock div
                        const stock = document.querySelector('.stock.{region}, #stock_{region}');
                        if (stock) {{ stock.click(); return 'stock'; }}
                        return null;
                    }}
                """)
                if not clicked:
                    return MoveResult(
                        move_description=f"Select region {region}",
                        success=False,
                        error=f"Region element not found: {region}",
                    )
                await page.wait_for_timeout(1000)

                # For chooseRegion, we may need to confirm
                try:
                    confirm = await page.query_selector('#confirmRegionChoice, .bgabutton_blue:visible')
                    if confirm:
                        await confirm.click(force=True)
                        await page.wait_for_timeout(500)
                except Exception:
                    pass

                return MoveResult(
                    move_description=f"Selected region: {region}",
                    success=True,
                )

            elif "card_id" in move_data:
                card_id = move_data["card_id"]
                # Click action or power card
                selectors = [
                    f"#actioncards_item_{card_id}",
                    f"#powercards_item_{card_id}",
                    f"[id$='_item_{card_id}']",
                ]
                for sel in selectors:
                    el = await page.query_selector(sel)
                    if el:
                        await el.click(force=True)
                        await page.wait_for_timeout(1000)
                        return MoveResult(
                            move_description=f"Selected card: {card_id}",
                            success=True,
                        )
                return MoveResult(
                    move_description=f"Select card {card_id}",
                    success=False,
                    error=f"Card element not found: {card_id}",
                )

            elif "count" in move_data:
                region = move_data.get("region", "")
                count = move_data.get("count", 1)
                # Click region to place caballeros
                for _ in range(count):
                    await page.click(f"#{region}", force=True)
                    await page.wait_for_timeout(300)
                await page.wait_for_timeout(500)
                return MoveResult(
                    move_description=f"Placed {count} caballeros in {region}",
                    success=True,
                )

            else:
                return MoveResult(
                    move_description="Unknown move format",
                    success=False,
                    error=f"Unrecognized move data: {move_data}",
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
