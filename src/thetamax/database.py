"""Async SQLite database layer for ThetaMax."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import aiosqlite

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
_SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id        TEXT    NOT NULL,
    channel_id      TEXT    NOT NULL,
    underlying      TEXT    NOT NULL DEFAULT 'SPY',
    status          TEXT    NOT NULL DEFAULT 'pending',
    bankroll        REAL    NOT NULL DEFAULT 10000,
    start_time      TEXT,
    end_time        TEXT,
    settlement_price REAL,
    created_at      TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS players (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id     INTEGER NOT NULL REFERENCES games(id),
    user_id     TEXT    NOT NULL,
    user_name   TEXT    NOT NULL,
    bankroll    REAL    NOT NULL,
    joined_at   TEXT    NOT NULL,
    UNIQUE(game_id, user_id)
);

CREATE TABLE IF NOT EXISTS positions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id       INTEGER NOT NULL REFERENCES players(id),
    option_type     TEXT    NOT NULL,
    strike          REAL    NOT NULL,
    quantity        INTEGER NOT NULL,
    direction       TEXT    NOT NULL,
    entry_price     REAL    NOT NULL,
    exit_price      REAL,
    status          TEXT    NOT NULL DEFAULT 'open',
    expiration      TEXT    NOT NULL,
    option_symbol   TEXT,
    pnl             REAL,
    created_at      TEXT    NOT NULL,
    closed_at       TEXT
);

CREATE TABLE IF NOT EXISTS seasons (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    TEXT    NOT NULL,
    name        TEXT    NOT NULL,
    start_date  TEXT    NOT NULL,
    end_date    TEXT,
    status      TEXT    NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS season_scores (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    season_id    INTEGER NOT NULL REFERENCES seasons(id),
    user_id      TEXT    NOT NULL,
    user_name    TEXT    NOT NULL,
    total_pnl    REAL    NOT NULL DEFAULT 0,
    games_played INTEGER NOT NULL DEFAULT 0,
    UNIQUE(season_id, user_id)
);
"""

Row = dict[str, Any]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


class Database:
    """Wrapper around an aiosqlite connection with helpers for ThetaMax data."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._conn: aiosqlite.Connection | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Open the database connection and initialise the schema."""
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(_SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database is not connected. Call connect() first.")
        return self._conn

    # ------------------------------------------------------------------
    # Games
    # ------------------------------------------------------------------

    async def create_game(
        self,
        guild_id: str,
        channel_id: str,
        underlying: str,
        bankroll: float,
    ) -> int:
        """Insert a new game record and return its id."""
        cur = await self.conn.execute(
            """INSERT INTO games (guild_id, channel_id, underlying, status, bankroll, created_at)
               VALUES (?, ?, ?, 'pending', ?, ?)""",
            (guild_id, channel_id, underlying, bankroll, _now()),
        )
        await self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    async def get_active_game(self, guild_id: str) -> Row | None:
        """Return the most-recent pending or active game for a guild."""
        cur = await self.conn.execute(
            """SELECT * FROM games
               WHERE guild_id = ? AND status IN ('pending', 'active')
               ORDER BY id DESC LIMIT 1""",
            (guild_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def get_game(self, game_id: int) -> Row | None:
        cur = await self.conn.execute("SELECT * FROM games WHERE id = ?", (game_id,))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def update_game(self, game_id: int, **fields: Any) -> None:
        """Update arbitrary fields on a game row."""
        if not fields:
            return
        cols = ", ".join(f"{k} = ?" for k in fields)
        await self.conn.execute(
            f"UPDATE games SET {cols} WHERE id = ?",
            (*fields.values(), game_id),
        )
        await self.conn.commit()

    # ------------------------------------------------------------------
    # Players
    # ------------------------------------------------------------------

    async def add_player(
        self,
        game_id: int,
        user_id: str,
        user_name: str,
        bankroll: float,
    ) -> int | None:
        """Add a player to a game. Returns the new player id, or ``None`` if
        the player already joined."""
        try:
            cur = await self.conn.execute(
                """INSERT INTO players (game_id, user_id, user_name, bankroll, joined_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (game_id, user_id, user_name, bankroll, _now()),
            )
            await self.conn.commit()
            return cur.lastrowid  # type: ignore[return-value]
        except aiosqlite.IntegrityError:
            return None

    async def get_player(self, game_id: int, user_id: str) -> Row | None:
        cur = await self.conn.execute(
            "SELECT * FROM players WHERE game_id = ? AND user_id = ?",
            (game_id, user_id),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def get_player_by_id(self, player_id: int) -> Row | None:
        cur = await self.conn.execute("SELECT * FROM players WHERE id = ?", (player_id,))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def get_players(self, game_id: int) -> list[Row]:
        cur = await self.conn.execute(
            "SELECT * FROM players WHERE game_id = ? ORDER BY bankroll DESC",
            (game_id,),
        )
        return [dict(r) for r in await cur.fetchall()]

    async def update_player_bankroll(self, player_id: int, bankroll: float) -> None:
        await self.conn.execute(
            "UPDATE players SET bankroll = ? WHERE id = ?",
            (bankroll, player_id),
        )
        await self.conn.commit()

    # ------------------------------------------------------------------
    # Positions
    # ------------------------------------------------------------------

    async def create_position(
        self,
        player_id: int,
        option_type: str,
        strike: float,
        quantity: int,
        direction: str,
        entry_price: float,
        expiration: str,
        option_symbol: str | None = None,
    ) -> int:
        cur = await self.conn.execute(
            """INSERT INTO positions
                   (player_id, option_type, strike, quantity, direction,
                    entry_price, expiration, option_symbol, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)""",
            (
                player_id,
                option_type,
                strike,
                quantity,
                direction,
                entry_price,
                expiration,
                option_symbol,
                _now(),
            ),
        )
        await self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    async def get_positions(
        self,
        player_id: int,
        status: str | None = None,
    ) -> list[Row]:
        if status:
            cur = await self.conn.execute(
                "SELECT * FROM positions WHERE player_id = ? AND status = ? ORDER BY created_at",
                (player_id, status),
            )
        else:
            cur = await self.conn.execute(
                "SELECT * FROM positions WHERE player_id = ? ORDER BY created_at",
                (player_id,),
            )
        return [dict(r) for r in await cur.fetchall()]

    async def get_position(self, position_id: int, player_id: int) -> Row | None:
        cur = await self.conn.execute(
            "SELECT * FROM positions WHERE id = ? AND player_id = ?",
            (position_id, player_id),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def close_position(
        self,
        position_id: int,
        exit_price: float,
        pnl: float,
    ) -> None:
        """Mark a position as manually closed at *exit_price*."""
        await self.conn.execute(
            """UPDATE positions
               SET status = 'closed', exit_price = ?, pnl = ?, closed_at = ?
               WHERE id = ?""",
            (exit_price, pnl, _now(), position_id),
        )
        await self.conn.commit()

    async def settle_position(
        self,
        position_id: int,
        exit_price: float,
        pnl: float,
    ) -> None:
        """Mark a position as expired/settled at *exit_price*."""
        await self.conn.execute(
            """UPDATE positions
               SET status = 'expired', exit_price = ?, pnl = ?, closed_at = ?
               WHERE id = ?""",
            (exit_price, pnl, _now(), position_id),
        )
        await self.conn.commit()

    async def get_all_open_positions_for_game(self, game_id: int) -> list[Row]:
        """Return all open positions across all players in *game_id*."""
        cur = await self.conn.execute(
            """SELECT pos.*, pl.user_id, pl.user_name
               FROM positions pos
               JOIN players pl ON pos.player_id = pl.id
               WHERE pl.game_id = ? AND pos.status = 'open'""",
            (game_id,),
        )
        return [dict(r) for r in await cur.fetchall()]

    # ------------------------------------------------------------------
    # Seasons
    # ------------------------------------------------------------------

    async def create_season(self, guild_id: str, name: str) -> int:
        cur = await self.conn.execute(
            "INSERT INTO seasons (guild_id, name, start_date, status) VALUES (?, ?, ?, 'active')",
            (guild_id, name, _today()),
        )
        await self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    async def get_active_season(self, guild_id: str) -> Row | None:
        cur = await self.conn.execute(
            """SELECT * FROM seasons
               WHERE guild_id = ? AND status = 'active'
               ORDER BY id DESC LIMIT 1""",
            (guild_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def end_season(self, season_id: int) -> None:
        await self.conn.execute(
            "UPDATE seasons SET status = 'ended', end_date = ? WHERE id = ?",
            (_today(), season_id),
        )
        await self.conn.commit()

    async def upsert_season_score(
        self,
        season_id: int,
        user_id: str,
        user_name: str,
        pnl_delta: float,
    ) -> None:
        """Add *pnl_delta* to the player's season total, creating the row if needed."""
        await self.conn.execute(
            """INSERT INTO season_scores (season_id, user_id, user_name, total_pnl, games_played)
               VALUES (?, ?, ?, ?, 1)
               ON CONFLICT(season_id, user_id) DO UPDATE SET
                   total_pnl    = total_pnl + excluded.total_pnl,
                   games_played = games_played + 1,
                   user_name    = excluded.user_name""",
            (season_id, user_id, user_name, pnl_delta),
        )
        await self.conn.commit()

    async def get_season_scores(self, season_id: int) -> list[Row]:
        cur = await self.conn.execute(
            """SELECT * FROM season_scores
               WHERE season_id = ?
               ORDER BY total_pnl DESC""",
            (season_id,),
        )
        return [dict(r) for r in await cur.fetchall()]
