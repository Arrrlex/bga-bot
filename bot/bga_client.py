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
        await page.goto("https://boardgamearena.com/player", wait_until="domcontentloaded", timeout=60000)
        # BGA redirects to /account if not logged in
        if "/account" in page.url:
            logger.info("Session expired or not logged in, logging in")
            await self._login(page)
        else:
            logger.info("Session valid, URL: %s", page.url)
        await page.close()

    async def _login(self, page: Page):
        """Login to BGA via the multi-step Svelte login form.

        Flow: /account -> fill email -> click Next -> fill password -> click Login
        """
        username = os.environ["BGA_USERNAME"]
        password = os.environ["BGA_PASSWORD"]

        # If we're already on the account page (redirected), just reload to ensure clean state
        if "/account" not in page.url:
            await page.goto("https://boardgamearena.com/account", wait_until="domcontentloaded", timeout=60000)
        else:
            # Already on account page from redirect, wait for JS to render
            await page.wait_for_timeout(2000)

        # Wait for the Svelte app to render the email input (may take a while on slow connections)
        await page.wait_for_selector('input[placeholder="Email or username"]', timeout=60000)

        # Dismiss cookie consent if present
        try:
            await page.click("#didomi-notice-agree-button", timeout=3000)
            await page.wait_for_timeout(500)
        except Exception:
            pass

        # Step 1: Fill email and click Next
        email_input = page.locator('input[placeholder="Email or username"]').first
        await email_input.fill(username)
        logger.info("Filled username")

        next_btn = page.locator('a:text("Next")').first
        await next_btn.click(force=True)
        logger.info("Clicked Next")

        # Step 2: Wait for password field and fill it
        pw_input = page.locator('input[type="password"]')
        await pw_input.wait_for(timeout=15000)
        await pw_input.fill(password)
        logger.info("Filled password")

        # Step 3: Click Login
        login_btn = page.locator('form:has(input[type="password"]) a:text("Login")')
        await login_btn.click(force=True)
        logger.info("Clicked Login")

        # Wait for redirect to player page or welcome page
        try:
            await page.wait_for_url("**/player**", timeout=30000)
        except Exception:
            # May redirect to welcome or lobby
            logger.info("Post-login URL: %s", page.url)

        # Save cookies
        cookies = await self._context.cookies()
        os.makedirs(os.path.dirname(self._cookies_path), exist_ok=True)
        with open(self._cookies_path, "w") as f:
            json.dump(cookies, f)
        logger.info("Saved cookies to %s", self._cookies_path)

    async def get_active_games(self) -> list[dict]:
        """Fetch list of active games from BGA.

        Returns list of dicts with keys: game_id, game_type, url, is_our_turn, player_name.
        Scrapes the gameinprogress page which lists all active turn-based games.
        """
        page = await self._context.new_page()
        try:
            await page.goto(
                "https://boardgamearena.com/gameinprogress",
                wait_until="domcontentloaded",
                timeout=60000,
            )
            # Wait for Svelte app to render game links
            await page.wait_for_timeout(3000)

            # Scrape game links from the Svelte-rendered list.
            # Links look like: /12/checkers?table=802685178
            # Text contains "It's your turn!" when it's our turn.
            games = await page.evaluate("""
                () => {
                    const seen = new Set();
                    const results = [];
                    document.querySelectorAll('a[href*="table="]').forEach(a => {
                        const href = a.href;
                        const tableMatch = href.match(/[?&]table=([0-9]+)/);
                        // URL format: /NUMBER/gamename?table=ID
                        const gameMatch = href.match(/\\/\\d+\\/([a-z_]+)\\?table=/);
                        if (tableMatch && gameMatch) {
                            const gameId = tableMatch[1];
                            if (seen.has(gameId)) return;
                            seen.add(gameId);
                            const text = a.textContent || '';
                            results.push({
                                game_id: gameId,
                                game_type: gameMatch[1],
                                url: href,
                                is_our_turn: text.includes("your turn"),
                                player_name: '',
                            });
                        }
                    });
                    return results;
                }
            """)
            return games
        finally:
            await page.close()

    async def navigate_to_game(self, url: str) -> Page:
        """Open a game page and wait for it to load."""
        page = await self._context.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        # Wait for the game area to appear
        await page.wait_for_selector("#overall-content, #game_play_area", timeout=60000)
        # The title text loads asynchronously via JS — wait for it to populate
        await page.wait_for_function(
            """() => {
                const el = document.querySelector('#pagemaintitletext');
                return el && el.textContent.trim().length > 0;
            }""",
            timeout=30000,
        )
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
