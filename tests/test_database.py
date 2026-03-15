"""Tests for thetamax.database — async SQLite layer."""


import pytest
import pytest_asyncio

from thetamax.database import Database


@pytest_asyncio.fixture
async def db(tmp_path):
    """Provide a fresh in-memory-equivalent database for each test."""
    db_path = str(tmp_path / "test.db")
    database = Database(db_path)
    await database.connect()
    yield database
    await database.close()


class TestGames:
    async def test_create_and_fetch_game(self, db: Database) -> None:
        game_id = await db.create_game("guild1", "chan1", "SPY", 10000)
        assert game_id is not None and game_id > 0

        game = await db.get_game(game_id)
        assert game is not None
        assert game["underlying"] == "SPY"
        assert game["status"] == "pending"
        assert game["bankroll"] == pytest.approx(10000)

    async def test_get_active_game_returns_pending_or_active(self, db: Database) -> None:
        gid = await db.create_game("guild2", "chan2", "QQQ", 5000)
        game = await db.get_active_game("guild2")
        assert game is not None
        assert game["id"] == gid

    async def test_get_active_game_returns_none_after_settle(self, db: Database) -> None:
        gid = await db.create_game("guild3", "chan3", "SPY", 10000)
        await db.update_game(gid, status="settled")
        game = await db.get_active_game("guild3")
        assert game is None

    async def test_update_game_status(self, db: Database) -> None:
        gid = await db.create_game("guild4", "chan4", "SPY", 10000)
        await db.update_game(gid, status="active", settlement_price=548.72)
        game = await db.get_game(gid)
        assert game["status"] == "active"
        assert game["settlement_price"] == pytest.approx(548.72)


class TestPlayers:
    async def test_add_and_fetch_player(self, db: Database) -> None:
        gid = await db.create_game("g", "c", "SPY", 10000)
        pid = await db.add_player(gid, "user1", "Alice", 10000)
        assert pid is not None

        player = await db.get_player(gid, "user1")
        assert player is not None
        assert player["user_name"] == "Alice"
        assert player["bankroll"] == pytest.approx(10000)

    async def test_duplicate_join_returns_none(self, db: Database) -> None:
        gid = await db.create_game("g2", "c2", "SPY", 10000)
        await db.add_player(gid, "user2", "Bob", 10000)
        result = await db.add_player(gid, "user2", "Bob", 10000)
        assert result is None

    async def test_get_players_sorted_by_bankroll(self, db: Database) -> None:
        gid = await db.create_game("g3", "c3", "SPY", 10000)
        await db.add_player(gid, "u1", "Low", 5000)
        await db.add_player(gid, "u2", "High", 15000)
        await db.add_player(gid, "u3", "Mid", 10000)

        players = await db.get_players(gid)
        bankrolls = [p["bankroll"] for p in players]
        assert bankrolls == sorted(bankrolls, reverse=True)

    async def test_update_bankroll(self, db: Database) -> None:
        gid = await db.create_game("g4", "c4", "SPY", 10000)
        pid = await db.add_player(gid, "u4", "Carol", 10000)
        player = await db.get_player(gid, "u4")
        await db.update_player_bankroll(player["id"], 12500)
        updated = await db.get_player(gid, "u4")
        assert updated["bankroll"] == pytest.approx(12500)


class TestPositions:
    async def _setup_player(self, db: Database) -> tuple[int, int]:
        gid = await db.create_game("gp", "cp", "SPY", 10000)
        pid = await db.add_player(gid, "trader1", "Dave", 10000)
        player = await db.get_player(gid, "trader1")
        return gid, player["id"]

    async def test_create_and_fetch_position(self, db: Database) -> None:
        _, player_id = await self._setup_player(db)
        pos_id = await db.create_position(
            player_id=player_id,
            option_type="call",
            strike=548.0,
            quantity=2,
            direction="long",
            entry_price=2.50,
            expiration="2024-01-08",
        )
        assert pos_id is not None

        positions = await db.get_positions(player_id)
        assert len(positions) == 1
        pos = positions[0]
        assert pos["option_type"] == "call"
        assert pos["strike"] == pytest.approx(548.0)
        assert pos["quantity"] == 2
        assert pos["direction"] == "long"
        assert pos["status"] == "open"

    async def test_close_position(self, db: Database) -> None:
        _, player_id = await self._setup_player(db)
        pos_id = await db.create_position(player_id, "put", 540.0, 1, "long", 1.50, "2024-01-08")
        await db.close_position(pos_id, 3.00, 150.0)

        positions = await db.get_positions(player_id, status="closed")
        assert len(positions) == 1
        assert positions[0]["exit_price"] == pytest.approx(3.00)
        assert positions[0]["pnl"] == pytest.approx(150.0)

    async def test_settle_position(self, db: Database) -> None:
        _, player_id = await self._setup_player(db)
        pos_id = await db.create_position(player_id, "call", 550.0, 1, "short", 2.00, "2024-01-08")
        await db.settle_position(pos_id, 548.0, 200.0)

        positions = await db.get_positions(player_id, status="expired")
        assert len(positions) == 1
        assert positions[0]["pnl"] == pytest.approx(200.0)

    async def test_get_all_open_positions_for_game(self, db: Database) -> None:
        gid = await db.create_game("gg", "cc", "SPY", 10000)
        pid1 = await db.add_player(gid, "u1", "Alice", 10000)
        pid2 = await db.add_player(gid, "u2", "Bob", 10000)
        p1 = await db.get_player(gid, "u1")
        p2 = await db.get_player(gid, "u2")

        await db.create_position(p1["id"], "call", 548.0, 1, "long", 2.0, "2024-01-08")
        await db.create_position(p2["id"], "put", 540.0, 1, "short", 1.5, "2024-01-08")

        all_positions = await db.get_all_open_positions_for_game(gid)
        assert len(all_positions) == 2
        user_names = {pos["user_name"] for pos in all_positions}
        assert user_names == {"Alice", "Bob"}


class TestSeasons:
    async def test_create_and_fetch_season(self, db: Database) -> None:
        sid = await db.create_season("guild1", "Week 1")
        season = await db.get_active_season("guild1")
        assert season is not None
        assert season["name"] == "Week 1"
        assert season["status"] == "active"

    async def test_end_season(self, db: Database) -> None:
        sid = await db.create_season("guild2", "Week 2")
        await db.end_season(sid)
        season = await db.get_active_season("guild2")
        assert season is None

    async def test_upsert_season_score_creates_row(self, db: Database) -> None:
        sid = await db.create_season("guild3", "Week 3")
        await db.upsert_season_score(sid, "user1", "Alice", 500.0)
        scores = await db.get_season_scores(sid)
        assert len(scores) == 1
        assert scores[0]["total_pnl"] == pytest.approx(500.0)
        assert scores[0]["games_played"] == 1

    async def test_upsert_season_score_accumulates(self, db: Database) -> None:
        sid = await db.create_season("guild4", "Week 4")
        await db.upsert_season_score(sid, "user1", "Alice", 500.0)
        await db.upsert_season_score(sid, "user1", "Alice", -200.0)
        scores = await db.get_season_scores(sid)
        assert scores[0]["total_pnl"] == pytest.approx(300.0)
        assert scores[0]["games_played"] == 2

    async def test_season_scores_sorted_desc(self, db: Database) -> None:
        sid = await db.create_season("guild5", "Week 5")
        await db.upsert_season_score(sid, "u1", "Low", -100.0)
        await db.upsert_season_score(sid, "u2", "High", 800.0)
        await db.upsert_season_score(sid, "u3", "Mid", 300.0)
        scores = await db.get_season_scores(sid)
        pnls = [s["total_pnl"] for s in scores]
        assert pnls == sorted(pnls, reverse=True)
