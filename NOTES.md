# BGA Implementation Notes

## Endpoints

- Login: `POST https://boardgamearena.com/account` with form fields `username`, `password`
- Active games: `GET /player/player/getGamesInProgress.html` (returns JSON with status/data fields)
- Game page: `https://boardgamearena.com/{game_type}?table={table_id}`

## DOM Selectors

- Turn indicator: `#pagemaintitletext` contains "You must" or "your turn" when it's our turn
- Game area: `#overall-content`, `#game_play_area`
- Player scores: `.player-name` + nearby `.player_score`

## Cookie Persistence

Cookies saved to `{DATA_DIR}/cookies.json`. On startup, loaded and validated by navigating to `/player`. If redirected to `/welcome` or `/account`, session is expired and re-login is triggered.

## Notes for Future Development

- BGA uses WebSocket for real-time updates. Could monitor `page.on('websocket')` for turn notifications instead of polling.
- Game-specific DOM structures vary significantly. Each plugin needs its own selectors validated against live games.
- Screenshot captured before move execution (what the LLM "saw").
