from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from typing import Iterator


@dataclass
class Position:
    option_symbol: str
    option_type: str
    strike: float
    quantity: int
    avg_price: float


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        self._init_schema()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS games (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    game_date TEXT NOT NULL,
                    underlying TEXT NOT NULL,
                    starting_bankroll REAL NOT NULL,
                    is_open INTEGER NOT NULL DEFAULT 1,
                    UNIQUE(guild_id, game_date)
                );

                CREATE TABLE IF NOT EXISTS players (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    game_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    cash REAL NOT NULL,
                    UNIQUE(game_id, user_id),
                    FOREIGN KEY(game_id) REFERENCES games(id)
                );

                CREATE TABLE IF NOT EXISTS positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    player_id INTEGER NOT NULL,
                    option_symbol TEXT NOT NULL,
                    option_type TEXT NOT NULL,
                    strike REAL NOT NULL,
                    quantity INTEGER NOT NULL,
                    avg_price REAL NOT NULL,
                    UNIQUE(player_id, option_symbol),
                    FOREIGN KEY(player_id) REFERENCES players(id)
                );

                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    player_id INTEGER NOT NULL,
                    side TEXT NOT NULL,
                    option_symbol TEXT NOT NULL,
                    option_type TEXT NOT NULL,
                    strike REAL NOT NULL,
                    qty INTEGER NOT NULL,
                    premium REAL NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(player_id) REFERENCES players(id)
                );
                """
            )

    def upsert_game(self, guild_id: int, underlying: str, starting_bankroll: float) -> int:
        today = date.today().isoformat()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO games (guild_id, game_date, underlying, starting_bankroll, is_open)
                VALUES (?, ?, ?, ?, 1)
                ON CONFLICT(guild_id, game_date)
                DO UPDATE SET underlying=excluded.underlying,
                              starting_bankroll=excluded.starting_bankroll,
                              is_open=1
                """,
                (guild_id, today, underlying.upper(), starting_bankroll),
            )
            row = conn.execute(
                "SELECT id FROM games WHERE guild_id = ? AND game_date = ?",
                (guild_id, today),
            ).fetchone()
            assert row is not None
            return int(row["id"])

    def get_today_game(self, guild_id: int):
        today = date.today().isoformat()
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM games WHERE guild_id = ? AND game_date = ?",
                (guild_id, today),
            ).fetchone()

    def ensure_player(self, game_id: int, user_id: int, starting_bankroll: float) -> int:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO players(game_id, user_id, cash)
                VALUES (?, ?, ?)
                ON CONFLICT(game_id, user_id) DO NOTHING
                """,
                (game_id, user_id, starting_bankroll),
            )
            row = conn.execute(
                "SELECT id FROM players WHERE game_id = ? AND user_id = ?",
                (game_id, user_id),
            ).fetchone()
            assert row is not None
            return int(row["id"])

    def get_player(self, game_id: int, user_id: int):
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM players WHERE game_id = ? AND user_id = ?",
                (game_id, user_id),
            ).fetchone()

    def list_positions(self, player_id: int) -> list[Position]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM positions WHERE player_id = ? ORDER BY option_symbol",
                (player_id,),
            ).fetchall()
        return [
            Position(
                option_symbol=row["option_symbol"],
                option_type=row["option_type"],
                strike=row["strike"],
                quantity=row["quantity"],
                avg_price=row["avg_price"],
            )
            for row in rows
        ]

    def apply_trade(
        self,
        player_id: int,
        side: str,
        option_symbol: str,
        option_type: str,
        strike: float,
        qty: int,
        premium: float,
    ) -> None:
        signed_qty = qty if side == "buy" else -qty
        cash_delta = -premium * qty * 100 if side == "buy" else premium * qty * 100

        with self.connect() as conn:
            conn.execute("UPDATE players SET cash = cash + ? WHERE id = ?", (cash_delta, player_id))
            row = conn.execute(
                "SELECT quantity, avg_price FROM positions WHERE player_id = ? AND option_symbol = ?",
                (player_id, option_symbol),
            ).fetchone()

            if row is None:
                conn.execute(
                    """
                    INSERT INTO positions(player_id, option_symbol, option_type, strike, quantity, avg_price)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (player_id, option_symbol, option_type, strike, signed_qty, premium),
                )
            else:
                new_qty = row["quantity"] + signed_qty
                old_qty = row["quantity"]
                old_avg = row["avg_price"]
                if new_qty == 0:
                    conn.execute(
                        "DELETE FROM positions WHERE player_id = ? AND option_symbol = ?",
                        (player_id, option_symbol),
                    )
                else:
                    weighted_notional = old_qty * old_avg + signed_qty * premium
                    new_avg = weighted_notional / new_qty
                    conn.execute(
                        """
                        UPDATE positions
                        SET quantity = ?, avg_price = ?
                        WHERE player_id = ? AND option_symbol = ?
                        """,
                        (new_qty, new_avg, player_id, option_symbol),
                    )

            conn.execute(
                """
                INSERT INTO trades(player_id, side, option_symbol, option_type, strike, qty, premium)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (player_id, side, option_symbol, option_type, strike, qty, premium),
            )

    def close_game(self, game_id: int) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE games SET is_open = 0 WHERE id = ?", (game_id,))

    def list_players(self, game_id: int):
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM players WHERE game_id = ? ORDER BY cash DESC",
                (game_id,),
            ).fetchall()
