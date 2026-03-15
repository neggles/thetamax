"""Trading commands for ThetaMax.

Slash commands:
    /buy  call|put <strike> <qty>  – buy option contracts
    /sell call|put <strike> <qty>  – sell (write) option contracts
    /close <position_id>           – close an open position at market price
    /portfolio                     – view your positions and P&L
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

import discord
from discord import app_commands
from discord.ext import commands

from thetamax import options as opts
from thetamax.config import config
from thetamax.market import is_market_open, today_iso

if TYPE_CHECKING:
    from bot import ThetaMaxBot

logger = logging.getLogger(__name__)

_OPTION_TYPE_CHOICES = [
    app_commands.Choice(name="call", value="call"),
    app_commands.Choice(name="put", value="put"),
]


class TradingCog(commands.Cog):
    """Buy/sell options and manage positions."""

    def __init__(self, bot: "ThetaMaxBot") -> None:
        self.bot = bot

    # ------------------------------------------------------------------
    # /buy
    # ------------------------------------------------------------------

    @app_commands.command(name="buy", description="Buy option contracts")
    @app_commands.describe(
        option_type="call or put",
        strike="Strike price (e.g. 548)",
        qty="Number of contracts (each = 100 shares)",
    )
    @app_commands.choices(option_type=_OPTION_TYPE_CHOICES)
    async def buy(
        self,
        interaction: discord.Interaction,
        option_type: str,
        strike: float,
        qty: int,
    ) -> None:
        await self._open_position(interaction, "long", option_type, strike, qty)

    # ------------------------------------------------------------------
    # /sell
    # ------------------------------------------------------------------

    @app_commands.command(name="sell", description="Sell (write) option contracts")
    @app_commands.describe(
        option_type="call or put",
        strike="Strike price (e.g. 548)",
        qty="Number of contracts (each = 100 shares)",
    )
    @app_commands.choices(option_type=_OPTION_TYPE_CHOICES)
    async def sell(
        self,
        interaction: discord.Interaction,
        option_type: str,
        strike: float,
        qty: int,
    ) -> None:
        await self._open_position(interaction, "short", option_type, strike, qty)

    # ------------------------------------------------------------------
    # /close
    # ------------------------------------------------------------------

    @app_commands.command(name="close", description="Close an open position at current market price")
    @app_commands.describe(position_id="Position ID (shown in /portfolio)")
    async def close_position(
        self, interaction: discord.Interaction, position_id: int
    ) -> None:
        guild_id = str(interaction.guild_id)
        user_id = str(interaction.user.id)

        game = await self.bot.db.get_active_game(guild_id)
        if not game or game["status"] != "active":
            await interaction.response.send_message(
                "❌ No active game right now.", ephemeral=True
            )
            return

        player = await self.bot.db.get_player(game["id"], user_id)
        if not player:
            await interaction.response.send_message(
                "❌ You're not in this game. Use `/game join` first.", ephemeral=True
            )
            return

        position = await self.bot.db.get_position(position_id, player["id"])
        if not position:
            await interaction.response.send_message(
                "❌ Position not found or doesn't belong to you.", ephemeral=True
            )
            return
        if position["status"] != "open":
            await interaction.response.send_message(
                f"⚠️  Position #{position_id} is already {position['status']}.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        # Fetch current option price
        current_price = await self._get_option_price(
            game["underlying"],
            position["expiration"],
            position["option_type"],
            position["strike"],
        )
        if current_price is None:
            await interaction.followup.send(
                "⚠️  Could not fetch a current price. Try again later.", ephemeral=True
            )
            return

        pnl = opts.unrealized_pnl(
            direction=position["direction"],
            quantity=position["quantity"],
            entry_price=position["entry_price"],
            current_price=current_price,
        )
        # When closing a long: sell at current_price → receive cash
        # When closing a short: buy back at current_price → pay cash
        # The net effect on bankroll is just the P&L delta
        new_bankroll = player["bankroll"] + pnl
        await self.bot.db.close_position(position_id, current_price, pnl)
        await self.bot.db.update_player_bankroll(player["id"], new_bankroll)

        direction_word = "long" if position["direction"] == "long" else "short"
        embed = discord.Embed(
            title=f"✅ Position #{position_id} Closed",
            colour=discord.Colour.green() if pnl >= 0 else discord.Colour.red(),
        )
        embed.add_field(
            name="Position",
            value=(
                f"{direction_word.upper()} {position['option_type'].upper()} "
                f"@ ${position['strike']:,.2f} × {position['quantity']}"
            ),
            inline=False,
        )
        embed.add_field(name="Entry price", value=f"${position['entry_price']:,.2f}", inline=True)
        embed.add_field(name="Exit price", value=f"${current_price:,.2f}", inline=True)
        embed.add_field(name="P&L", value=opts.format_pnl(pnl), inline=True)
        embed.add_field(name="New bankroll", value=f"${new_bankroll:,.2f}", inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------
    # /portfolio
    # ------------------------------------------------------------------

    @app_commands.command(name="portfolio", description="View your open positions and P&L")
    async def portfolio(self, interaction: discord.Interaction) -> None:
        guild_id = str(interaction.guild_id)
        user_id = str(interaction.user.id)

        game = await self.bot.db.get_active_game(guild_id)
        if not game:
            await interaction.response.send_message(
                "❌ No active game.", ephemeral=True
            )
            return

        player = await self.bot.db.get_player(game["id"], user_id)
        if not player:
            await interaction.response.send_message(
                "❌ You're not in this game.", ephemeral=True
            )
            return

        positions = await self.bot.db.get_positions(player["id"])
        open_positions = [p for p in positions if p["status"] == "open"]

        embed = discord.Embed(
            title=f"📊 {interaction.user.display_name}'s Portfolio",
            colour=discord.Colour.blue(),
        )
        embed.add_field(name="Bankroll", value=f"${player['bankroll']:,.2f}", inline=True)
        embed.add_field(name="Game", value=f"#{game['id']} — {game['underlying']}", inline=True)

        if not open_positions:
            embed.description = "_No open positions._"
        else:
            await interaction.response.defer(ephemeral=True)
            total_unrealized = 0.0
            lines = []
            for pos in open_positions:
                current_price = await self._get_option_price(
                    game["underlying"],
                    pos["expiration"],
                    pos["option_type"],
                    pos["strike"],
                )
                if current_price is not None:
                    upnl = opts.unrealized_pnl(
                        direction=pos["direction"],
                        quantity=pos["quantity"],
                        entry_price=pos["entry_price"],
                        current_price=current_price,
                    )
                    total_unrealized += upnl
                    upnl_str = opts.format_pnl(upnl)
                else:
                    upnl_str = "_n/a_"

                dir_str = "LONG" if pos["direction"] == "long" else "SHORT"
                lines.append(
                    f"**#{pos['id']}** {dir_str} {pos['option_type'].upper()} "
                    f"${pos['strike']:,.2f} × {pos['quantity']} "
                    f"(entry ${pos['entry_price']:,.2f}) → {upnl_str}"
                )
            embed.description = "\n".join(lines)
            embed.add_field(
                name="Unrealized P&L", value=opts.format_pnl(total_unrealized), inline=False
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _open_position(
        self,
        interaction: discord.Interaction,
        direction: str,
        option_type: str,
        strike: float,
        qty: int,
    ) -> None:
        """Core logic shared by /buy and /sell."""
        if qty < 1:
            await interaction.response.send_message(
                "❌ Quantity must be at least 1.", ephemeral=True
            )
            return

        guild_id = str(interaction.guild_id)
        user_id = str(interaction.user.id)
        user_name = interaction.user.display_name

        game = await self.bot.db.get_active_game(guild_id)
        if not game or game["status"] != "active":
            await interaction.response.send_message(
                "❌ No active game. Ask an admin to run `/game begin`.",
                ephemeral=True,
            )
            return

        player = await self.bot.db.get_player(game["id"], user_id)
        if not player:
            await interaction.response.send_message(
                "❌ You're not in this game. Use `/game join` first.", ephemeral=True
            )
            return

        expiration = today_iso()

        await interaction.response.defer(ephemeral=True)

        # Fetch the option's current price
        option_price = await self._get_option_price(
            game["underlying"], expiration, option_type, strike
        )
        if option_price is None or option_price <= 0:
            await interaction.followup.send(
                f"❌ Could not find a valid price for {option_type.upper()} @ "
                f"${strike:,.2f}. Check the strike price and try again.",
                ephemeral=True,
            )
            return

        # Calculate cash impact and check funds
        cash_impact = opts.position_cash_cost(direction, option_price, qty)
        new_bankroll = player["bankroll"] + cash_impact

        if new_bankroll < 0:
            await interaction.followup.send(
                f"❌ Insufficient funds.\n"
                f"This trade would cost **${abs(cash_impact):,.2f}** but you only have "
                f"**${player['bankroll']:,.2f}**.",
                ephemeral=True,
            )
            return

        # Persist the position
        option_symbol = None  # would need full OCC symbol in production
        pos_id = await self.bot.db.create_position(
            player_id=player["id"],
            option_type=option_type,
            strike=strike,
            quantity=qty,
            direction=direction,
            entry_price=option_price,
            expiration=expiration,
            option_symbol=option_symbol,
        )
        await self.bot.db.update_player_bankroll(player["id"], new_bankroll)

        direction_word = "Bought" if direction == "long" else "Sold"
        embed = discord.Embed(
            title=f"✅ {direction_word} {option_type.upper()} @ ${strike:,.2f}",
            colour=discord.Colour.green(),
        )
        embed.add_field(name="Contracts", value=str(qty), inline=True)
        embed.add_field(name="Premium/share", value=f"${option_price:,.2f}", inline=True)
        total_cost = option_price * qty * opts.CONTRACT_MULTIPLIER
        embed.add_field(
            name="Total " + ("debit" if direction == "long" else "credit"),
            value=f"${total_cost:,.2f}",
            inline=True,
        )
        embed.add_field(name="New bankroll", value=f"${new_bankroll:,.2f}", inline=True)
        embed.add_field(name="Position ID", value=f"#{pos_id}", inline=True)
        embed.set_footer(text=f"Expires {expiration} | Use /close {pos_id} to exit early")
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def _get_option_price(
        self,
        underlying: str,
        expiration: str,
        option_type: str,
        strike: float,
    ) -> float | None:
        """Return the mid-market price for a specific option contract."""
        contract = await self.bot.tradier.get_option_quote(
            underlying, expiration, option_type, strike
        )
        if not contract:
            return None
        bid = contract.get("bid")
        ask = contract.get("ask")
        if bid is not None and ask is not None:
            try:
                mid = (float(bid) + float(ask)) / 2
                return mid if mid > 0 else None
            except (TypeError, ValueError):
                pass
        last = contract.get("last")
        if last is not None:
            try:
                v = float(last)
                return v if v > 0 else None
            except (TypeError, ValueError):
                pass
        return None


async def setup(bot: "ThetaMaxBot") -> None:
    await bot.add_cog(TradingCog(bot))
