"""Informational commands for ThetaMax.

Slash commands:
    /leaderboard         – current game standings
    /quote <symbol>      – live underlying price
    /chain [underlying]  – options chain for today's expiry
    /season start <name> – (admin) start a new weekly season
    /season end          – (admin) end the current season
    /season leaderboard  – season cumulative standings
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from thetamax.config import config
from thetamax.market import today_iso

if TYPE_CHECKING:
    from thetamax.__main__ import ThetaMaxBot


def _is_admin(interaction: discord.Interaction) -> bool:
    if not isinstance(interaction.user, discord.Member):
        return False
    return any(r.name == config.ADMIN_ROLE_NAME for r in interaction.user.roles)


class InfoCog(commands.Cog):
    """Informational and leaderboard commands."""

    def __init__(self, bot: "ThetaMaxBot") -> None:
        self.bot = bot

    # ------------------------------------------------------------------
    # /leaderboard
    # ------------------------------------------------------------------

    @app_commands.command(name="leaderboard", description="View current game standings")
    async def leaderboard(self, interaction: discord.Interaction) -> None:
        guild_id = str(interaction.guild_id)
        game = await self.bot.db.get_active_game(guild_id)
        if not game:
            await interaction.response.send_message(
                "❌ No active game.", ephemeral=True
            )
            return

        players = await self.bot.db.get_players(game["id"])
        if not players:
            await interaction.response.send_message(
                "ℹ️  No players have joined yet.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title=f"📊 Leaderboard — Game #{game['id']} ({game['underlying']})",
            colour=discord.Colour.gold(),
        )
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, p in enumerate(players):
            medal = medals[i] if i < len(medals) else f"{i + 1}."
            net = p["bankroll"] - game["bankroll"]
            sign = "+" if net >= 0 else ""
            lines.append(
                f"{medal} **{p['user_name']}** — "
                f"${p['bankroll']:,.2f} ({sign}${net:,.2f})"
            )
        embed.description = "\n".join(lines)
        embed.set_footer(text=f"Starting bankroll: ${game['bankroll']:,.0f}")
        await interaction.response.send_message(embed=embed)

    # ------------------------------------------------------------------
    # /quote
    # ------------------------------------------------------------------

    @app_commands.command(name="quote", description="Get the current price of a stock or index")
    @app_commands.describe(symbol="Ticker symbol, e.g. SPY, QQQ, AAPL")
    async def quote(self, interaction: discord.Interaction, symbol: str) -> None:
        symbol = symbol.upper().strip()
        await interaction.response.defer()
        q = await self.bot.tradier.get_quote(symbol)
        if not q:
            await interaction.followup.send(
                f"❌ Could not fetch a quote for **{symbol}**.", ephemeral=True
            )
            return

        last = q.get("last") or q.get("close") or "N/A"
        change = q.get("change") or 0.0
        change_pct = q.get("change_percentage") or 0.0
        bid = q.get("bid", "N/A")
        ask = q.get("ask", "N/A")
        volume = q.get("volume", "N/A")

        colour = discord.Colour.green() if float(change or 0) >= 0 else discord.Colour.red()
        arrow = "▲" if float(change or 0) >= 0 else "▼"

        embed = discord.Embed(
            title=f"📈 {symbol}",
            description=f"**${last}** {arrow} {change:+.2f} ({change_pct:+.2f}%)",
            colour=colour,
        )
        embed.add_field(name="Bid", value=f"${bid}", inline=True)
        embed.add_field(name="Ask", value=f"${ask}", inline=True)
        embed.add_field(name="Volume", value=f"{volume:,}" if isinstance(volume, int) else str(volume), inline=True)
        await interaction.followup.send(embed=embed)

    # ------------------------------------------------------------------
    # /chain
    # ------------------------------------------------------------------

    @app_commands.command(
        name="chain",
        description="View the options chain for today's expiry",
    )
    @app_commands.describe(
        underlying="Symbol (defaults to the active game's underlying)",
        option_type="call, put, or both",
        near_strikes="Number of strikes to show each side of ATM (default 5)",
    )
    @app_commands.choices(
        option_type=[
            app_commands.Choice(name="both", value="both"),
            app_commands.Choice(name="call", value="call"),
            app_commands.Choice(name="put", value="put"),
        ]
    )
    async def chain(
        self,
        interaction: discord.Interaction,
        underlying: str = "",
        option_type: str = "both",
        near_strikes: int = 5,
    ) -> None:
        guild_id = str(interaction.guild_id)

        if not underlying:
            game = await self.bot.db.get_active_game(guild_id)
            underlying = game["underlying"] if game else config.DEFAULT_UNDERLYING
        underlying = underlying.upper().strip()

        expiration = today_iso()
        await interaction.response.defer()

        # Fetch the current underlying price (for ATM context)
        quote = await self.bot.tradier.get_quote(underlying)
        atm = float(quote["last"]) if quote and quote.get("last") else None

        # Fetch the chain
        ot = None if option_type == "both" else option_type
        chain = await self.bot.tradier.get_options_chain(underlying, expiration, ot)

        if not chain:
            await interaction.followup.send(
                f"❌ No options found for **{underlying}** expiring {expiration}.\n"
                "Note: The Tradier sandbox may not have data for all symbols or dates.",
                ephemeral=True,
            )
            return

        # Sort by strike and filter to near-ATM if we have an ATM price
        chain.sort(key=lambda c: float(c.get("strike", 0)))
        if atm and near_strikes > 0:
            strikes = sorted({float(c["strike"]) for c in chain})
            closest = min(strikes, key=lambda s: abs(s - atm))
            idx = strikes.index(closest)
            lo = max(0, idx - near_strikes)
            hi = min(len(strikes) - 1, idx + near_strikes)
            valid = set(strikes[lo : hi + 1])
            chain = [c for c in chain if float(c.get("strike", 0)) in valid]

        # Build compact table
        lines = [f"```{'Strike':>8}  {'Type':>4}  {'Bid':>6}  {'Ask':>6}  {'IV':>6}"]
        for c in chain:
            iv = c.get("greeks", {})
            iv_val = iv.get("smv_vol") or iv.get("bid_iv") or 0
            lines.append(
                f"{float(c.get('strike',0)):>8.2f}  "
                f"{str(c.get('option_type','?')):>4}  "
                f"{float(c.get('bid') or 0):>6.2f}  "
                f"{float(c.get('ask') or 0):>6.2f}  "
                f"{float(iv_val)*100:>5.1f}%"
            )
        lines.append("```")
        atm_str = f"${atm:,.2f}" if atm else "N/A"
        embed = discord.Embed(
            title=f"⛓️  Options Chain — {underlying} (exp. {expiration})",
            description="\n".join(lines),
            colour=discord.Colour.blue(),
        )
        embed.set_footer(text=f"Underlying last: {atm_str} | Showing up to {near_strikes} strikes each side of ATM")
        await interaction.followup.send(embed=embed)

    # ------------------------------------------------------------------
    # /season group
    # ------------------------------------------------------------------

    season_group = app_commands.Group(name="season", description="ThetaMax season management")

    @season_group.command(name="start", description="(Admin) Start a new weekly season")
    @app_commands.describe(name="Season name, e.g. 'Week 1'")
    async def season_start(self, interaction: discord.Interaction, name: str) -> None:
        if not _is_admin(interaction):
            await interaction.response.send_message(
                "❌ You need the **ThetaMax Admin** role.", ephemeral=True
            )
            return

        guild_id = str(interaction.guild_id)
        existing = await self.bot.db.get_active_season(guild_id)
        if existing:
            await interaction.response.send_message(
                f"⚠️  There is already an active season: **{existing['name']}**. "
                "End it first with `/season end`.",
                ephemeral=True,
            )
            return

        season_id = await self.bot.db.create_season(guild_id, name)
        await interaction.response.send_message(
            f"🏆 Season **{name}** started! (ID: {season_id})\n"
            "Daily game P&Ls will be tracked toward season totals."
        )

    @season_group.command(name="end", description="(Admin) End the current season")
    async def season_end(self, interaction: discord.Interaction) -> None:
        if not _is_admin(interaction):
            await interaction.response.send_message(
                "❌ You need the **ThetaMax Admin** role.", ephemeral=True
            )
            return

        guild_id = str(interaction.guild_id)
        season = await self.bot.db.get_active_season(guild_id)
        if not season:
            await interaction.response.send_message(
                "❌ No active season.", ephemeral=True
            )
            return

        scores = await self.bot.db.get_season_scores(season["id"])
        await self.bot.db.end_season(season["id"])

        embed = discord.Embed(
            title=f"🏆 Season **{season['name']}** — Final Standings",
            colour=discord.Colour.gold(),
        )
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, s in enumerate(scores):
            medal = medals[i] if i < len(medals) else f"{i + 1}."
            sign = "+" if s["total_pnl"] >= 0 else ""
            lines.append(
                f"{medal} **{s['user_name']}** — "
                f"{sign}${s['total_pnl']:,.2f} over {s['games_played']} game(s)"
            )
        embed.description = "\n".join(lines) or "_No scores recorded._"
        await interaction.response.send_message(embed=embed)

    @season_group.command(name="leaderboard", description="View the current season standings")
    async def season_leaderboard(self, interaction: discord.Interaction) -> None:
        guild_id = str(interaction.guild_id)
        season = await self.bot.db.get_active_season(guild_id)
        if not season:
            await interaction.response.send_message(
                "❌ No active season.", ephemeral=True
            )
            return

        scores = await self.bot.db.get_season_scores(season["id"])
        embed = discord.Embed(
            title=f"🏆 Season: **{season['name']}** — Leaderboard",
            colour=discord.Colour.gold(),
        )
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, s in enumerate(scores):
            medal = medals[i] if i < len(medals) else f"{i + 1}."
            sign = "+" if s["total_pnl"] >= 0 else ""
            lines.append(
                f"{medal} **{s['user_name']}** — "
                f"{sign}${s['total_pnl']:,.2f} ({s['games_played']} game(s))"
            )
        embed.description = "\n".join(lines) or "_No scores yet._"
        await interaction.response.send_message(embed=embed)


async def setup(bot: "ThetaMaxBot") -> None:
    await bot.add_cog(InfoCog(bot))
