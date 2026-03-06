from abc import ABC, abstractmethod
from dataclasses import dataclass

from playwright.async_api import Page


@dataclass
class GameState:
    """Structured representation of board state, passed to LLM."""
    raw: dict
    summary: str


@dataclass
class MoveResult:
    move_description: str
    success: bool
    error: str | None = None


class GamePlugin(ABC):
    game_id: str

    @abstractmethod
    async def is_our_turn(self, page: Page) -> bool:
        """Return True if it is currently our turn."""
        ...

    @abstractmethod
    async def extract_state(self, page: Page) -> GameState:
        """Parse the current board state from the DOM."""
        ...

    @abstractmethod
    def build_prompt(self, state: GameState) -> tuple[str, str]:
        """Return (system_prompt, user_prompt) for the LLM."""
        ...

    @abstractmethod
    async def execute_move(self, page: Page, llm_response: str) -> MoveResult:
        """Parse LLM response and execute the move via Playwright."""
        ...
