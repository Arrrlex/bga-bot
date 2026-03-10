# BGA Bot

A self-hosted bot that plays board games on [BoardGameArena](https://boardgamearena.com) using LLM reasoning. It logs into BGA via browser automation, detects when it's your turn, extracts the board state, asks an LLM for a move, and executes it.

Comes with a web dashboard to monitor games, view move history with screenshots, and watch live logs.

## Supported games

- **International Draughts** (10x10 checkers)
- **El Grande**

Adding a new game:

1. Create a plugin class in `bot/games/` that inherits from `GamePlugin` (see `bot/games/base.py`)
2. Implement the four required methods:
   - `is_our_turn(page)` -- check if it's our turn via the DOM
   - `extract_state(page)` -- scrape the full board state from `gameui.gamedatas`
   - `build_prompt(state)` -- construct system + user prompts for the LLM
   - `execute_move(page, llm_response)` -- parse the LLM's JSON and click in the browser
3. Register it in `bot/games/__init__.py` by adding to `REGISTRY` with the BGA game slug as the key (the slug appears in BGA URLs, e.g. `checkers` from `/12/checkers?table=...`)

## Supported LLM providers

- **Moonshot** (Kimi K2.5) - default
- **Anthropic** (Claude)
- **OpenAI** (or any OpenAI-compatible endpoint)

## Setup

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/Arrrlex/bga-bot.git
cd bga-bot
uv sync
```

Playwright needs a Chromium browser installed:

```bash
uv run playwright install chromium
```

Copy `.env.example` to `.env` and fill in your credentials:

```
BGA_USERNAME=your-email@example.com
BGA_PASSWORD=your-bga-password
LLM_PROVIDER=moonshot
LLM_API_KEY=sk-...
DASHBOARD_PASSWORD=pick-a-password
```

## Running locally

```bash
uv run python start.py
```

This starts both the bot scheduler and the web dashboard on `http://localhost:8000`. Log in with any username and the `DASHBOARD_PASSWORD` you set.

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `BGA_USERNAME` | required | BGA login email or username |
| `BGA_PASSWORD` | required | BGA password |
| `LLM_PROVIDER` | `moonshot` | `moonshot`, `anthropic`, or `openai` |
| `LLM_API_KEY` | required | API key for the LLM provider |
| `LLM_MODEL` | provider default | Model ID (e.g. `kimi-k2.5`, `claude-sonnet-4-20250514`, `gpt-4o`) |
| `DASHBOARD_PASSWORD` | required | HTTP Basic Auth password for the dashboard |
| `POLL_INTERVAL_SECONDS` | | Tick interval in seconds (takes precedence over minutes) |
| `POLL_INTERVAL_MINUTES` | `5` | Tick interval in minutes |
| `DATA_DIR` | `/data` | Directory for SQLite DB, cookies, and screenshots |
| `PORT` | `8000` | Web server port |

## Testing

```bash
uv run pytest tests/ --ignore=tests/integration
```

Integration tests in `tests/integration/` require live BGA credentials and are excluded from CI.

CI runs automatically on push and PRs via GitHub Actions.

## Deploying on Railway

The bot is designed for [Railway](https://railway.com):

1. Link your GitHub repo to a Railway project
2. Railway auto-detects the Dockerfile and builds on each push to `main`
3. Set the environment variables above in the Railway service settings
4. Add a volume mounted at `/data` for persistent storage (database, cookies, screenshots)

Docker layer caching is enabled in `railway.toml` for fast rebuilds.
