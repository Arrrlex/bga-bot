import json
import logging

from playwright.async_api import Page

from .base import GamePlugin, GameState, MoveResult, extract_json

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
                const gd = gameui.gamedatas;
                const gs = gd.gamestate;
                const players = gd.players;

                // Find our player ID
                const ourId = gs.active_player ||
                    (gs.multiactive && gs.multiactive[0]) || '';

                // Build board: active pieces with positions
                const pieces = {};
                for (const [id, p] of Object.entries(gd.pieces)) {
                    if (p.piece_captured === "1" || p.piece_removed === "1") continue;
                    pieces[id] = {
                        x: parseInt(p.piece_x),
                        y: parseInt(p.piece_y),
                        type: p.piece_type,
                        color: p.piece_color,
                        player_id: p.player_id,
                        is_ours: p.player_id === ourId,
                    };
                }

                // Valid moves from gamestate args
                const moves = {};
                const destsByPiece = gs.args?.destinations_by_piece || {};
                for (const [pieceId, dests] of Object.entries(destsByPiece)) {
                    moves[pieceId] = dests.map(d => ({
                        dest_x: d.dest_x !== undefined ? d.dest_x : d.x,
                        dest_y: d.dest_y !== undefined ? d.dest_y : d.y,
                        captures: (d.jumped_over || []).length > 0,
                        successive: d.successive_cells || [],
                    }));
                }
                // Also check possible_destinations (used during multi-jump continuations)
                if (Object.keys(moves).length === 0 && gs.args?.possible_destinations) {
                    const pd = gs.args.possible_destinations;
                    // possible_destinations may be an array of {x, y} or keyed by piece
                    if (Array.isArray(pd)) {
                        moves['_active'] = pd.map(d => ({
                            dest_x: d.dest_x !== undefined ? d.dest_x : d.x,
                            dest_y: d.dest_y !== undefined ? d.dest_y : d.y,
                            captures: true,
                            successive: [],
                        }));
                    } else {
                        for (const [k, v] of Object.entries(pd)) {
                            const dests = Array.isArray(v) ? v : [v];
                            moves[k] = dests.map(d => ({
                                dest_x: d.dest_x !== undefined ? d.dest_x : d.x,
                                dest_y: d.dest_y !== undefined ? d.dest_y : d.y,
                                captures: true,
                                successive: [],
                            }));
                        }
                    }
                }

                // Player info
                const playerInfo = {};
                for (const [pid, p] of Object.entries(players)) {
                    playerInfo[pid] = {name: p.name, score: p.score, color: p.color};
                }

                return {
                    board_size: gd.constants?.BOARD_SIZE || 10,
                    pieces: pieces,
                    valid_moves: moves,
                    players: playerInfo,
                    our_player_id: ourId,
                    title: document.querySelector('#pagemaintitletext')?.textContent?.trim() || '',
                };
            }
        """)

        # Build a readable summary
        pieces = raw.get("pieces", {})
        our_pieces = {pid: p for pid, p in pieces.items() if p["is_ours"]}
        opp_pieces = {pid: p for pid, p in pieces.items() if not p["is_ours"]}
        valid_moves = raw.get("valid_moves", {})

        # Determine our color and movement direction
        our_color = next(iter(our_pieces.values()), {}).get("color", "?")
        # In international draughts on BGA, white starts at bottom (high y) and moves
        # toward low y; black starts at top (low y) and moves toward high y.
        if our_color == "white":
            direction = "moving UP (toward row 0, our home is rows 6-9)"
        elif our_color == "black":
            direction = "moving DOWN (toward row 9, our home is rows 0-3)"
        else:
            direction = "unknown"

        # Player info
        players = raw.get("players", {})
        our_pid = raw.get("our_player_id", "")

        summary_parts = [
            f"Board: {raw.get('board_size', 10)}x{raw.get('board_size', 10)} International Draughts",
            f"Status: {raw.get('title', '')}",
            f"We are {our_color}, {direction}",
        ]

        # Player scores
        for pid, p in players.items():
            ours = " (us)" if pid == our_pid else ""
            summary_parts.append(f"  {p['name']}{ours}: score={p['score']}")

        # All our pieces
        summary_parts.append(f"\nOur pieces ({len(our_pieces)}):")
        for pid, p in sorted(our_pieces.items(), key=lambda x: (x[1]["y"], x[1]["x"])):
            summary_parts.append(
                f"  Piece {pid} ({p['type']}) at ({p['x']},{p['y']})"
            )

        # All opponent pieces
        summary_parts.append(f"\nOpponent pieces ({len(opp_pieces)}):")
        for pid, p in sorted(opp_pieces.items(), key=lambda x: (x[1]["y"], x[1]["x"])):
            summary_parts.append(
                f"  Piece {pid} ({p['type']}) at ({p['x']},{p['y']})"
            )

        # List each valid move
        summary_parts.append(f"\nValid moves ({len(valid_moves)} pieces can move):")
        for piece_id, dests in valid_moves.items():
            p = pieces.get(piece_id, {})
            for d in dests:
                capture_str = " (CAPTURE)" if d["captures"] else ""
                summary_parts.append(
                    f"  Piece {piece_id} ({p.get('type', '?')}) at ({p.get('x')},{p.get('y')}) "
                    f"-> ({d['dest_x']},{d['dest_y']}){capture_str}"
                )

        return GameState(raw=raw, summary="\n".join(summary_parts))

    def build_prompt(self, state: GameState) -> tuple[str, str]:
        system_prompt = """You are playing International Draughts (10x10 checkers) on BoardGameArena.

Rules:
- 10x10 board, pieces on dark squares only
- Regular pieces (men) move diagonally forward one square
- Kings can move diagonally any number of squares in any direction
- Captures are mandatory and you must jump over opponent pieces
- Multi-jumps: if after a capture another capture is available, you must continue
- A piece reaching the opposite back row is promoted to king
- You win by capturing all opponent pieces or leaving them with no legal moves

You will be given the board state with piece positions as (x, y) coordinates where x=column (0-9, left to right) and y=row (0-9, top to bottom).

You will also be given the list of ALL valid moves. You MUST pick one of these moves.

Respond with ONLY a JSON object in this exact format:
{"piece_id": "<id>", "dest_x": <x>, "dest_y": <y>}

Pick the strategically best move. Prefer captures, advancing toward promotion, and controlling the center."""

        user_prompt = f"""Current board state:

{state.summary}

Pick your move. Respond with ONLY the JSON object."""

        return system_prompt, user_prompt

    async def execute_move(self, page: Page, llm_response: str) -> MoveResult:
        try:
            move_data = extract_json(llm_response)
            piece_id = str(move_data["piece_id"])
            dest_x = int(move_data["dest_x"])
            dest_y = int(move_data["dest_y"])

            # Click the piece to select it
            await page.click(f"#piece_{piece_id}", force=True)
            await page.wait_for_timeout(800)

            # Click the destination cell
            cell_id = f"cell_{dest_x}_{dest_y}"
            await page.click(f"#{cell_id}", force=True)
            await page.wait_for_timeout(1000)

            # Handle multi-jump chains: keep jumping until the chain is complete
            for jump_num in range(20):  # safety limit
                await page.wait_for_timeout(500)
                title = await page.evaluate(
                    "() => document.querySelector('#pagemaintitletext')?.textContent?.trim() || ''"
                )
                if not ("must continue" in title.lower() or "must jump" in title.lower()
                        or "must move again" in title.lower()):
                    break

                logger.info("Multi-jump continuation #%d detected", jump_num + 1)
                succ = await page.evaluate("""
                    () => {
                        const gs = gameui.gamedatas.gamestate;
                        const dests = gs.args?.destinations_by_piece || {};
                        // Also check for possible_destinations (alternative BGA format)
                        if (Object.keys(dests).length === 0 && gs.args?.possible_destinations) {
                            return {'_continuation': gs.args.possible_destinations};
                        }
                        return dests;
                    }
                """)
                if not succ:
                    logger.warning("No successive destinations found, breaking")
                    break

                jumped = False
                for pid, moves in succ.items():
                    if moves and isinstance(moves, list) and len(moves) > 0:
                        m = moves[0]
                        dx = m.get('dest_x', m.get('x'))
                        dy = m.get('dest_y', m.get('y'))
                        if dx is not None and dy is not None:
                            await page.click(f"#cell_{dx}_{dy}", force=True)
                            await page.wait_for_timeout(800)
                            jumped = True
                            break
                if not jumped:
                    logger.warning("Could not find a valid continuation move")
                    break

            desc = f"piece_{piece_id} ({dest_x},{dest_y})"
            return MoveResult(move_description=desc, success=True)

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
