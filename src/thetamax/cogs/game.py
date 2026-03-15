"""Game management commands for ThetaMax.

Provides the ``/game`` command group:
    /game start [underlying]  – (admin) create and open registration for a new game
    /game join               – join the current game
    /game begin              – (admin) manually move the game to active state
    /game settle [price]     – (admin) manually settle all positions at *price*
    /game status             – display current game info
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from thetamax import options as opts
from thetamax.config import config
from thetamax.market import is_market_open, today_iso, today_market_close

if TYPE_CHECKING:
    from bot import ThetaMaxBot

logger = logging.getLogger(__name__)


def _is_admin(interaction: discord.Interaction) -> bool:
    """Return ``True`` if the invoking member has the admin role."""
    if not isinstance(interaction.user, discord.Member):
        return False
    return any(r.name == config.ADMIN_ROLE_NAME for r in interaction.user.roles)


class GameCog(commands.Cog):
    """Commands for managing a ThetaMax game session."""

    def __init__(self, bot: "ThetaMaxBot") -> None:
        self.bot = bot

    game_group = app_commands.Group(name="game", description="ThetaMax game management")

    # ------------------------------------------------------------------
    # /game start
    # ------------------------------------------------------------------

    @game_group.command(name="start", description="(Admin) Start a new ThetaMax game")
    @app_commands.describe(underlying="Underlying symbol, e.g. SPY, QQQ, SPX")
    async def game_start(
        self,
        interaction: discord.Interaction,
        underlying: str = "",
    ) -> None:
        if not _is_admin(interaction):
            await interaction.response.send_message(
                "❌ You need the **ThetaMax Admin** role to start a game.", ephemeral=True
            )
            return

        guild_id = str(interaction.guild_id)
        channel_id = str(interaction.channel_id)
        underlying = (underlying.upper() or config.DEFAULT_UNDERLYING).strip()

        # Check there isn't already an active game
        existing = await self.bot.db.get_active_game(guild_id)
        if existing:
            await interaction.response.send_message(
                f"⚠️  There is already a **{existing['status']}** game running "
                f"(Game #{existing['id']}). Settle it first.",
                ephemeral=True,
            )
            return

        game_id = await self.bot.db.create_game(
            guild_id,
            channel_id,
            underlying,
            config.STARTING_BANKROLL,
        )

        embed = discord.Embed(
            title="🎰 ThetaMax — New Game Created!",
            description=(
                f"**Underlying:** {underlying}\n"
                f"**Starting bankroll:** ${config.STARTING_BANKROLL:,.0f}\n\n"
                "Use `/game join` to enter.\n"
                "Use `/game begin` to open trading when everyone has joined.\n\n"
                "_Positions settle at 4:00 PM ET today._"
            ),
            colour=discord.Colour.gold(),
        )
        embed.set_footer(text=f"Game #{game_id}")
        await interaction.response.send_message(embed=embed)

    # ------------------------------------------------------------------
    # /game join
    # ------------------------------------------------------------------

    @game_group.command(name="join", description="Join the current ThetaMax game")
    async def game_join(self, interaction: discord.Interaction) -> None:
        guild_id = str(interaction.guild_id)
        user_id = str(interaction.user.id)
        user_name = interaction.user.display_name

        game = await self.bot.db.get_active_game(guild_id)
        if not game:
            await interaction.response.send_message(
                "❌ No active game found. Ask an admin to run `/game start`.",
                ephemeral=True,
            )
            return

        if game["status"] == "active":
            await interaction.response.send_message(
                "⚠️  The game has already started — you can't join mid-game.",
                ephemeral=True,
            )
            return

        player_id = await self.bot.db.add_player(
            game["id"], user_id, user_name, config.STARTING_BANKROLL
        )
        if player_id is None:
            await interaction.response.send_message(
                "ℹ️  You've already joined this game!", ephemeral=True
            )
            return

        players = await self.bot.db.get_players(game["id"])
        await interaction.response.send_message(
            f"✅ **{user_name}** joined Game #{game['id']}! "
            f"Bankroll: **${config.STARTING_BANKROLL:,.0f}**\n"
            f"_{len(players)} player(s) registered so far._"
        )

    # ------------------------------------------------------------------
    # /game begin
    # ------------------------------------------------------------------

    @game_group.command(
        name="begin", description="(Admin) Open trading for the current game"
    )
    async def game_begin(self, interaction: discord.Interaction) -> None:
        if not _is_admin(interaction):
            await interaction.response.send_message(
                "❌ You need the **ThetaMax Admin** role.", ephemeral=True
            )
            return

        guild_id = str(interaction.guild_id)
        game = await self.bot.db.get_active_game(guild_id)
        if not game:
            await interaction.response.send_message(
                "❌ No pending game found.", ephemeral=True
            )
            return
        if game["status"] == "active":
            await interaction.response.send_message(
                "⚠️  The game is already active.", ephemeral=True
            )
            return

        close_dt = today_market_close()
        await self.bot.db.update_game(
            game["id"],
            status="active",
            start_time=datetime.now(timezone.utc).isoformat(),
        )

        players = await self.bot.db.get_players(game["id"])
        embed = discord.Embed(
            title="🔔 Trading is NOW OPEN!",
            description=(
                f"**Game #{game['id']}** — underlying: **{game['underlying']}**\n"
                f"**{len(players)}** player(s) competing\n\n"
                f"Positions settle at **{close_dt.strftime('%I:%M %p ET')}**.\n\n"
                "**Commands:**\n"
                "`/buy call <strike> <qty>` — buy call options\n"
                "`/buy put <strike> <qty>` — buy put options\n"
                "`/sell call <strike> <qty>` — sell (write) call options\n"
                "`/sell put <strike> <qty>` — sell (write) put options\n"
                "`/close <id>` — close a position at market price\n"
                "`/portfolio` — view your positions\n"
                "`/leaderboard` — view standings\n"
            ),
            colour=discord.Colour.green(),
        )
        await interaction.response.send_message(embed=embed)

    # ------------------------------------------------------------------
    # /game settle
    # ------------------------------------------------------------------

    @game_group.command(
        name="settle",
        description="(Admin) Settle all positions at the given closing price",
    )
    @app_commands.describe(price="Closing price of the underlying (e.g. 548.72)")
    async def game_settle(
        self, interaction: discord.Interaction, price: float
    ) -> None:
        if not _is_admin(interaction):
            await interaction.response.send_message(
                "❌ You need the **ThetaMax Admin** role.", ephemeral=True
            )
            return

        guild_id = str(interaction.guild_id)
        game = await self.bot.db.get_active_game(guild_id)
        if not game:
            await interaction.response.send_message(
                "❌ No active game to settle.", ephemeral=True
            )
            return

        await interaction.response.defer()  # settlement takes a moment
        await self._settle_game(game, price, interaction)

    # ------------------------------------------------------------------
    # Internal settlement logic (also called by the scheduler)
    # ------------------------------------------------------------------

    async def settle_game(
        self,
        game: dict,
        settlement_price: float,
        channel: discord.TextChannel | None = None,
    ) -> None:
        """Settle all open positions in *game* at *settlement_price*."""
        await self._settle_game(game, settlement_price, channel=channel)

    async def _settle_game(
        self,
        game: dict,
        settlement_price: float,
        interaction: discord.Interaction | None = None,
        channel: discord.TextChannel | None = None,
    ) -> None:
        game_id = game["id"]
        guild_id = game["guild_id"]

        # Fetch all open positions
        positions = await self.bot.db.get_all_open_positions_for_game(game_id)
        player_pnls: dict[str, float] = {}

        for pos in positions:
            pnl = opts.settlement_pnl(
                option_type=pos["option_type"],
                strike=pos["strike"],
                quantity=pos["quantity"],
                direction=pos["direction"],
                entry_price=pos["entry_price"],
                settlement_price=settlement_price,
            )
            await self.bot.db.settle_position(pos["id"], settlement_price, pnl)
            uid = pos["user_id"]
            player_pnls[uid] = player_pnls.get(uid, 0) + pnl

        # Update player bankrolls
        players = await self.bot.db.get_players(game_id)
        player_map = {p["user_id"]: p for p in players}
        for uid, pnl in player_pnls.items():
            player = player_map.get(uid)
            if player:
                new_bankroll = player["bankroll"] + pnl
                await self.bot.db.update_player_bankroll(player["id"], new_bankroll)
                player_map[uid]["bankroll"] = new_bankroll

        # Update season scores if a season is active
        season = await self.bot.db.get_active_season(guild_id)
        if season:
            for uid, pnl_delta in player_pnls.items():
                player = player_map.get(uid)
                if player:
                    net = player["bankroll"] - config.STARTING_BANKROLL
                    await self.bot.db.upsert_season_score(
                        season["id"], uid, player["user_name"], net
                    )

        # Mark game as settled
        await self.bot.db.update_game(
            game_id,
            status="settled",
            end_time=datetime.now(timezone.utc).isoformat(),
            settlement_price=settlement_price,
        )

        # Build leaderboard embed
        fresh_players = await self.bot.db.get_players(game_id)
        leaderboard = sorted(fresh_players, key=lambda p: p["bankroll"], reverse=True)

        embed = discord.Embed(
            title="🏁 Game Settled — Final Leaderboard",
            description=f"**{game['underlying']}** settled at **${settlement_price:,.2f}**",
            colour=discord.Colour.blurple(),
        )
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, p in enumerate(leaderboard):
            medal = medals[i] if i < len(medals) else f"{i + 1}."
            net = p["bankroll"] - config.STARTING_BANKROLL
            sign = "+" if net >= 0 else ""
            lines.append(
                f"{medal} **{p['user_name']}** — "
                f"${p['bankroll']:,.2f} ({sign}${net:,.2f})"
            )
        embed.add_field(name="Rankings", value="\n".join(lines) or "_No players_", inline=False)
        embed.set_footer(text=f"Game #{game_id}")

        if interaction:
            await interaction.followup.send(embed=embed)
        elif channel:
            await channel.send(embed=embed)

    # ------------------------------------------------------------------
    # /game status
    # ------------------------------------------------------------------

    @game_group.command(name="status", description="Show current game information")
    async def game_status(self, interaction: discord.Interaction) -> None:
        guild_id = str(interaction.guild_id)
        game = await self.bot.db.get_active_game(guild_id)
        if not game:
            await interaction.response.send_message(
                "ℹ️  No active game. Use `/game start` to create one.", ephemeral=True
            )
            return

        players = await self.bot.db.get_players(game["id"])
        status_emoji = {"pending": "⏳", "active": "✅", "settling": "⌛"}.get(
            game["status"], "❓"
        )

        embed = discord.Embed(
            title=f"{status_emoji} Game #{game['id']} — {game['underlying']}",
            colour=discord.Colour.gold(),
        )
        embed.add_field(name="Status", value=game["status"].capitalize(), inline=True)
        embed.add_field(name="Underlying", value=game["underlying"], inline=True)
        embed.add_field(
            name="Bankroll", value=f"${game['bankroll']:,.0f}", inline=True
        )
        embed.add_field(
            name=f"Players ({len(players)})",
            value=", ".join(p["user_name"] for p in players) or "_None yet_",
            inline=False,
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot: "ThetaMaxBot") -> None:
    await bot.add_cog(GameCog(bot))
