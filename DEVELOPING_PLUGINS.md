# Developing Game Plugins

This guide walks through adding support for a new BGA game. Follow these steps in order — the process is designed to catch issues early with real HTML fixtures, before writing any plugin logic.

## Prerequisites

- BGA credentials in `.env` (see README)
- A second BGA account to create game invitations (or ask a friend)
- `uv run playwright install chromium`

## Step 1: Learn the rules

Read the full rules for the game on BGA. Understand:

- All possible player actions and when they occur
- Turn structure (phases, rounds, mandatory vs optional actions)
- Win conditions
- Any forced moves (e.g. mandatory captures in checkers)
- Multi-step turns (e.g. multi-jump chains, place-then-act sequences)

Don't skim — misunderstanding a rule leads to broken plugins. Pay particular attention to edge cases like forced continuations, timeouts, and draw conditions.

## Step 2: Collect real HTML fixtures

This is the most important step. You need real BGA DOM snapshots for every distinct game state the plugin will encounter.

### 2a: Get into a game

Ask the user to create a game invitation on BGA (or use a second account). Then accept it:

```python
# In a Python REPL or script:
from bot.bga_client import BGAClient
client = BGAClient()
await client.start()
await client.accept_pending_invitations()
```

### 2b: Play several turns, saving HTML at each state

Navigate to the game and save the full page HTML at every distinct state you encounter. You want coverage of:

- **Every game phase** (e.g. piece selection, destination selection, card choice, placement)
- **Edge cases** (forced moves, multi-step continuations, game end)
- **Not-our-turn states** (to test `is_our_turn` returns False)

```python
page = await client.navigate_to_game("https://boardgamearena.com/...")

# Save full HTML
html = await page.content()
with open("tests/fixtures/mygame_phase_name.html", "w") as f:
    f.write(html)

# Also dump gameui.gamedatas to understand the JS data model
import json
gamedatas = await page.evaluate("() => JSON.parse(JSON.stringify(gameui.gamedatas))")
with open("tests/fixtures/mygame_phase_name_gamedatas.json", "w") as f:
    json.dump(gamedatas, f, indent=2)

# Play a move manually to advance to the next state
await page.click("#some_element")
```

Play through several complete turns. Make moves manually via Playwright (clicking elements) so you experience the full flow the bot will need to automate.

### 2c: Anonymize the fixtures

Remove or replace all identifying information from saved HTML and JSON:

- Player usernames → `Player1`, `Player2`, etc.
- Player IDs → `100001`, `100002`, etc.
- Avatar URLs → remove or replace with placeholder
- Any personal data (email, profile links)

Keep game-relevant data intact (piece positions, scores, game state, region names, etc.).

### 2d: Catalog what you found

For each saved state, document:

- The game phase / state name (from `gameui.gamedatas.gamestate.name`)
- What `#pagemaintitletext` says
- What actions are available (`gamestate.possibleactions`)
- What the correct move would be (what you'd click)
- The structure of `gamestate.args` (this is where valid moves/options live)

This catalog becomes the basis for your tests and your `build_prompt` state-specific instructions.

## Step 3: Write tests first

Create `tests/test_games_mygame.py` using the real HTML fixtures and gamedatas JSON. Write tests for all four plugin methods before writing any plugin code.

### Test structure

```python
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from bot.games.base import GameState
from bot.games.mygame import MyGamePlugin

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def plugin():
    return MyGamePlugin()


def _make_page_with_gamedatas(fixture_name: str) -> AsyncMock:
    """Create a mock page whose evaluate() returns data from a fixture."""
    gamedatas = json.loads((FIXTURES / f"{fixture_name}_gamedatas.json").read_text())
    page = AsyncMock()
    # evaluate() calls in the plugin will receive this gamedatas
    # You may need to customize side_effect for plugins that call
    # evaluate() multiple times with different JS
    page.evaluate = AsyncMock(return_value=gamedatas)
    return page


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
    async def test_returns_game_state_phase_foo(self, plugin):
        """Test extraction from a real 'foo' phase snapshot."""
        gamedatas = json.loads(
            (FIXTURES / "mygame_foo_gamedatas.json").read_text()
        )
        page = AsyncMock()
        page.evaluate = AsyncMock(return_value=_transform_gamedatas(gamedatas))
        state = await plugin.extract_state(page)
        assert isinstance(state, GameState)
        # Assert specific fields from the real fixture
        assert state.raw["some_field"] == "expected_value"
        assert "key phrase" in state.summary


class TestBuildPrompt:
    def test_phase_foo_prompt(self, plugin):
        """Prompt for phase 'foo' should include relevant instructions."""
        state = GameState(raw={"state_name": "foo", ...}, summary="...")
        system, user = plugin.build_prompt(state)
        assert "expected instruction" in system
        assert "state info" in user

    def test_phase_bar_prompt(self, plugin):
        """Each distinct phase should get tailored instructions."""
        # ...


class TestExecuteMove:
    @pytest.mark.asyncio
    async def test_phase_foo_move(self, plugin):
        """Execute a move from real phase 'foo' state."""
        page = AsyncMock()
        page.click = AsyncMock()
        page.wait_for_timeout = AsyncMock()
        page.evaluate = AsyncMock(return_value="done")
        page.query_selector = AsyncMock(return_value=AsyncMock())

        result = await plugin.execute_move(page, '{"action": "value"}')
        assert result.success is True

    @pytest.mark.asyncio
    async def test_invalid_json(self, plugin):
        page = AsyncMock()
        result = await plugin.execute_move(page, "not json")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_playwright_error(self, plugin):
        page = AsyncMock()
        page.click = AsyncMock(side_effect=RuntimeError("Timeout"))
        page.wait_for_timeout = AsyncMock()
        result = await plugin.execute_move(page, '{"action": "value"}')
        assert result.success is False
```

### What to test

For **each game phase** you captured in Step 2:

- `extract_state` correctly parses the gamedatas into `GameState` with accurate `raw` and `summary`
- `build_prompt` returns phase-appropriate instructions
- `execute_move` clicks the right elements for a valid move
- `execute_move` handles the element not being found
- `execute_move` handles invalid/missing JSON gracefully

Also test:

- Multi-step sequences (e.g. multi-jump chains — mock `evaluate` with `side_effect` list)
- Error paths (Playwright exceptions, malformed LLM output)
- Edge cases from your rule reading (forced moves, game end)

## Step 4: Write the plugin

Create `bot/games/mygame.py` implementing `GamePlugin`. Make the tests pass.

### Plugin skeleton

```python
import json
import logging

from playwright.async_api import Page

from .base import GamePlugin, GameState, MoveResult, extract_json

logger = logging.getLogger(__name__)


class MyGamePlugin(GamePlugin):
    game_id = "mygame"  # BGA URL slug

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
                // Extract all game-relevant data here
                return { ... };
            }
        """)
        summary = _build_summary(raw)
        return GameState(raw=raw, summary=summary)

    def build_prompt(self, state: GameState) -> tuple[str, str]:
        # System prompt: game rules, response format
        # User prompt: current state + phase-specific action instructions
        # Customize instructions per state_name / possible_actions
        ...

    async def execute_move(self, page: Page, llm_response: str) -> MoveResult:
        try:
            move_data = extract_json(llm_response)
            # Click the right elements based on move_data
            # Handle multi-step sequences (loop until complete)
            ...
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
```

### Key patterns

**`extract_state`**: Pull everything from `gameui.gamedatas` in a single `page.evaluate()` call. Include all information the LLM needs to make a decision. The `summary` string is what the LLM actually reads — make it complete and unambiguous.

**`build_prompt`**: Customize the user prompt per game phase (`state_name`). Tell the LLM exactly what JSON format to respond with for each action type. Always include "Respond with ONLY a JSON object" to avoid reasoning preamble eating the token budget.

**`execute_move`**: Use `extract_json()` from `base.py` to parse the LLM response (handles markdown fences, reasoning blocks). For multi-step actions, loop until complete — don't assume a single click suffices. Always return `MoveResult` with `success=False` on errors rather than raising.

**Multi-step handling**: If the game has forced continuations (like multi-jump captures in checkers), loop in `execute_move` checking the title text after each click:

```python
for step in range(20):  # safety limit
    await page.wait_for_timeout(500)
    title = await page.evaluate(
        "() => document.querySelector('#pagemaintitletext')?.textContent?.trim() || ''"
    )
    if "must continue" not in title.lower():
        break
    # Find and click the next destination
    ...
```

## Step 5: Register the plugin

Add to `bot/games/__init__.py`:

```python
from .mygame import MyGamePlugin

REGISTRY: dict[str, type[GamePlugin]] = {
    "checkers": CheckersPlugin,
    "elgrande": ElGrandePlugin,
    "mygame": MyGamePlugin,  # BGA URL slug as key
}
```

The slug is what appears in BGA URLs: `boardgamearena.com/123/mygame?table=...`

## Step 6: Verify end-to-end

Run all tests:

```bash
uv run pytest tests/ --ignore=tests/integration -q
```

Then do a live test against a real game (integration test or just run the bot):

```bash
uv run python start.py
```

Watch the logs for the first few turns to confirm the full cycle works: state extraction, LLM call, move execution.

## Common pitfalls

- **Incomplete state**: If the LLM doesn't have enough info, it guesses wrong. Include ALL visible game information in `extract_state`, even if it seems obvious.
- **Contradictory prompts**: If valid moves are empty but the title says "your turn", the LLM spirals. Add sanity checks.
- **Assuming single-click moves**: Many games require multiple clicks per turn. Always check if the game is waiting for more input after each click.
- **Fragile selectors**: BGA DOM varies between games. Use `gameui.gamedatas` (JS data) over DOM scraping wherever possible — it's the authoritative source.
- **Token budget exhaustion**: If the prompt is confusing, the LLM may use all tokens on reasoning. Keep prompts clear and unambiguous. Always specify the exact JSON response format.
