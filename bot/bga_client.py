"""BGA session management via Playwright.

See NOTES.md for documentation of BGA endpoints, DOM selectors, and WS message shapes
discovered during implementation.
"""

import json
import logging
import os

from playwright.async_api import Browser, Page, async_playwright

logger = logging.getLogger(__name__)


class BGAClient:
    def __init__(self):
        self._playwright = None
        self._browser: Browser | None = None
        self._context = None
        self._data_dir = os.environ.get("DATA_DIR", "/data")
        self._cookies_path = os.path.join(self._data_dir, "cookies.json")

    async def start(self):
        """Launch browser, load cookies or login."""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 900},
        )

        if os.path.exists(self._cookies_path):
            with open(self._cookies_path) as f:
                cookies = json.load(f)
            await self._context.add_cookies(cookies)
            logger.info("Loaded cookies from %s", self._cookies_path)

        # Verify session or re-login
        page = await self._context.new_page()
        await page.goto("https://boardgamearena.com/player")
        if "/welcome" in page.url or "/account/account" in page.url:
            logger.info("Session expired, logging in")
            await self._login(page)
        else:
            logger.info("Session valid")
        await page.close()

    async def _login(self, page: Page):
        """Login to BGA and save cookies."""
        username = os.environ["BGA_USERNAME"]
        password = os.environ["BGA_PASSWORD"]

        await page.goto("https://boardgamearena.com/account")
        await page.fill('input[name="username"], #username_input', username)
        await page.fill('input[name="password"], #password_input', password)
        await page.click('#submit_login_button, button[type="submit"]')
        await page.wait_for_url("**/welcome**", timeout=15000)

        # Save cookies
        cookies = await self._context.cookies()
        os.makedirs(os.path.dirname(self._cookies_path), exist_ok=True)
        with open(self._cookies_path, "w") as f:
            json.dump(cookies, f)
        logger.info("Saved cookies to %s", self._cookies_path)

    async def get_active_games(self) -> list[dict]:
        """Fetch list of active games from BGA.

        Returns list of dicts with keys: game_id, game_type, url, is_our_turn, player_name.
        Uses BGA's table manager API endpoint.
        """
        page = await self._context.new_page()
        try:
            # Navigate to the "play" page which lists current games
            await page.goto("https://boardgamearena.com/player")
            await page.wait_for_load_state("networkidle")

            # Use BGA's internal API to get current tables
            # This calls the same endpoint the BGA frontend uses
            games = await page.evaluate("""
                async () => {
                    try {
                        const resp = await fetch('/player/player/getGamesInProgress.html', {
                            method: 'GET',
                            credentials: 'include',
                        });
                        const data = await resp.json();
                        if (data.status === '1' && data.data) {
                            const tables = data.data;
                            return Object.values(tables).map(t => ({
                                game_id: String(t.id),
                                game_type: t.game_name,
                                url: `https://boardgamearena.com/${t.game_name}?table=${t.id}`,
                                is_our_turn: t.is_my_turn || false,
                                player_name: t.player_name || '',
                            }));
                        }
                        return [];
                    } catch (e) {
                        return [];
                    }
                }
            """)
            return games
        finally:
            await page.close()

    async def navigate_to_game(self, url: str) -> Page:
        """Open a game page and wait for it to load."""
        page = await self._context.new_page()
        await page.goto(url)
        await page.wait_for_load_state("networkidle")
        # Wait for the game area to appear
        await page.wait_for_selector("#overall-content, #game_play_area", timeout=30000)
        return page

    async def capture_screenshot(self, page: Page, path: str):
        """Capture a screenshot of the current page."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        await page.screenshot(path=path, full_page=False)

    async def close(self):
        """Shut down browser."""
        if self._context:
            # Save cookies before closing
            try:
                cookies = await self._context.cookies()
                os.makedirs(os.path.dirname(self._cookies_path), exist_ok=True)
                with open(self._cookies_path, "w") as f:
                    json.dump(cookies, f)
            except Exception:
                logger.exception("Failed to save cookies on close")
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
