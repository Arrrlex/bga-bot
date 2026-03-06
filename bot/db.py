import os
from datetime import datetime, timezone

from sqlmodel import Field, Session, SQLModel, create_engine, select


class Game(SQLModel, table=True):
    id: str = Field(primary_key=True)
    game_type: str
    bga_url: str
    status: str = "active"  # "active" | "finished" | "unknown"
    player_name: str = ""
    last_checked: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Move(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    game_id: str = Field(foreign_key="game.id")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    board_state_json: str = ""
    llm_prompt: str = ""
    llm_reasoning: str = ""
    move_executed: str = ""
    screenshot_path: str | None = None
    success: bool = True
    error_message: str | None = None


def get_data_dir() -> str:
    return os.environ.get("DATA_DIR", "/data")


def get_engine(db_url: str | None = None):
    if db_url is None:
        data_dir = get_data_dir()
        os.makedirs(data_dir, exist_ok=True)
        db_url = f"sqlite:///{data_dir}/bga_bot.db"
    engine = create_engine(db_url)
    SQLModel.metadata.create_all(engine)
    return engine


def get_session(engine) -> Session:
    return Session(engine)


def upsert_game(session: Session, game_info: dict) -> Game:
    """Create or update a game from BGA game info dict."""
    game = session.get(Game, game_info["game_id"])
    if game is None:
        game = Game(
            id=game_info["game_id"],
            game_type=game_info["game_type"],
            bga_url=game_info["url"],
            player_name=game_info.get("player_name", ""),
            status="active",
        )
        session.add(game)
    else:
        game.bga_url = game_info["url"]
        game.last_checked = datetime.now(timezone.utc)
    session.commit()
    session.refresh(game)
    return game


def record_move(session: Session, move: Move) -> Move:
    """Insert a move record."""
    session.add(move)
    session.commit()
    session.refresh(move)
    return move


def get_all_games(session: Session) -> list[Game]:
    return list(session.exec(select(Game).order_by(Game.last_checked.desc())).all())


def get_game(session: Session, game_id: str) -> Game | None:
    return session.get(Game, game_id)


def get_moves_for_game(session: Session, game_id: str) -> list[Move]:
    return list(
        session.exec(
            select(Move)
            .where(Move.game_id == game_id)
            .order_by(Move.timestamp.desc())
        ).all()
    )
