from __future__ import annotations

from dataclasses import dataclass

import discord
from discord import app_commands
from discord.ext import commands

from .db import Database
from .pricing import TradierClient, build_occ_option_symbol, intrinsic_value


@dataclass
class BotDeps:
    db: Database
    pricing: TradierClient


class OptionsPokerBot(commands.Bot):
    def __init__(self, deps: BotDeps) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)
        self.deps = deps

    async def setup_hook(self) -> None:
        self.tree.add_command(start_game)
        self.tree.add_command(buy)
        self.tree.add_command(sell)
        self.tree.add_command(portfolio)
        self.tree.add_command(leaderboard)
        self.tree.add_command(settle)
        await self.tree.sync()


async def _active_game_or_error(interaction: discord.Interaction):
    bot: OptionsPokerBot = interaction.client  # type: ignore[assignment]
    assert interaction.guild_id is not None
    game = bot.deps.db.get_today_game(interaction.guild_id)
    if game is None or int(game["is_open"]) != 1:
        await interaction.response.send_message("No active game for today. Use /start_game first.", ephemeral=True)
        return None
    return game


@app_commands.command(name="start_game", description="Start or reset today's 0DTE game")
@app_commands.describe(symbol="Underlying ticker (e.g., SPY, QQQ, IWM)", starting_bankroll="Fake dollars per player")
async def start_game(interaction: discord.Interaction, symbol: str, starting_bankroll: float = 10_000.0):
    bot: OptionsPokerBot = interaction.client  # type: ignore[assignment]
    assert interaction.guild_id is not None
    game_id = bot.deps.db.upsert_game(interaction.guild_id, symbol, starting_bankroll)
    await interaction.response.send_message(
        f"Game #{game_id} is open for **{symbol.upper()}** with starting bankroll ${starting_bankroll:,.2f}."
    )


async def _execute_trade(
    interaction: discord.Interaction,
    side: str,
    option_type: str,
    strike: float,
    qty: int,
):
    if qty <= 0:
        await interaction.response.send_message("Quantity must be > 0.", ephemeral=True)
        return

    game = await _active_game_or_error(interaction)
    if game is None:
        return

    bot: OptionsPokerBot = interaction.client  # type: ignore[assignment]
    player_id = bot.deps.db.ensure_player(int(game["id"]), interaction.user.id, float(game["starting_bankroll"]))

    option_symbol = build_occ_option_symbol(game["underlying"], strike, option_type)
    try:
        premium = await bot.deps.pricing.get_option_mid_price(option_symbol)
    except Exception as exc:
        await interaction.response.send_message(f"Failed to fetch option price: {exc}", ephemeral=True)
        return

    player = bot.deps.db.get_player(int(game["id"]), interaction.user.id)
    assert player is not None
    cash = float(player["cash"])
    if side == "buy":
        total_cost = premium * qty * 100
        if total_cost > cash:
            await interaction.response.send_message(
                f"Not enough cash. Need ${total_cost:,.2f}, have ${cash:,.2f}.", ephemeral=True
            )
            return

    bot.deps.db.apply_trade(
        player_id=player_id,
        side=side,
        option_symbol=option_symbol,
        option_type=option_type,
        strike=strike,
        qty=qty,
        premium=premium,
    )
    await interaction.response.send_message(
        f"{interaction.user.mention} {side.upper()} {qty} {option_type.upper()} @ {strike:.2f} for ${premium:.2f}/contract"
    )


@app_commands.command(name="buy", description="Buy 0DTE call/put")
async def buy(interaction: discord.Interaction, option_type: str, strike: float, qty: int):
    option_type = option_type.lower()
    if option_type not in {"call", "put"}:
        await interaction.response.send_message("option_type must be call or put", ephemeral=True)
        return
    await _execute_trade(interaction, "buy", option_type, strike, qty)


@app_commands.command(name="sell", description="Sell 0DTE call/put")
async def sell(interaction: discord.Interaction, option_type: str, strike: float, qty: int):
    option_type = option_type.lower()
    if option_type not in {"call", "put"}:
        await interaction.response.send_message("option_type must be call or put", ephemeral=True)
        return
    await _execute_trade(interaction, "sell", option_type, strike, qty)


@app_commands.command(name="portfolio", description="Show your live portfolio and mark-to-market equity")
async def portfolio(interaction: discord.Interaction):
    game = await _active_game_or_error(interaction)
    if game is None:
        return

    bot: OptionsPokerBot = interaction.client  # type: ignore[assignment]
    player = bot.deps.db.get_player(int(game["id"]), interaction.user.id)
    if player is None:
        await interaction.response.send_message("No positions yet.", ephemeral=True)
        return

    cash = float(player["cash"])
    positions = bot.deps.db.list_positions(int(player["id"]))
    mark_value = 0.0
    lines = []
    for pos in positions:
        try:
            mark = await bot.deps.pricing.get_option_mid_price(pos.option_symbol)
        except Exception:
            mark = pos.avg_price
        position_value = pos.quantity * mark * 100
        mark_value += position_value
        lines.append(
            f"{pos.option_symbol}: qty {pos.quantity:+d}, avg ${pos.avg_price:.2f}, mark ${mark:.2f}, value ${position_value:,.2f}"
        )

    equity = cash + mark_value
    body = "\n".join(lines) if lines else "No open positions"
    await interaction.response.send_message(
        f"**{interaction.user.display_name} Portfolio**\nCash: ${cash:,.2f}\nEquity: ${equity:,.2f}\n{body}",
        ephemeral=True,
    )


@app_commands.command(name="leaderboard", description="Current cash leaderboard")
async def leaderboard(interaction: discord.Interaction):
    game = await _active_game_or_error(interaction)
    if game is None:
        return
    bot: OptionsPokerBot = interaction.client  # type: ignore[assignment]
    players = bot.deps.db.list_players(int(game["id"]))
    if not players:
        await interaction.response.send_message("No players yet.")
        return

    lines = []
    for idx, row in enumerate(players, start=1):
        member = interaction.guild.get_member(int(row["user_id"])) if interaction.guild else None
        name = member.display_name if member else str(row["user_id"])
        lines.append(f"{idx}. {name} — ${float(row['cash']):,.2f} cash")
    await interaction.response.send_message("**Leaderboard (cash only)**\n" + "\n".join(lines))


@app_commands.command(name="settle", description="Settle today's game using underlying close")
async def settle(interaction: discord.Interaction):
    game = await _active_game_or_error(interaction)
    if game is None:
        return
    bot: OptionsPokerBot = interaction.client  # type: ignore[assignment]

    try:
        close = await bot.deps.pricing.get_underlying_price(game["underlying"])
    except Exception as exc:
        await interaction.response.send_message(f"Failed to fetch close: {exc}", ephemeral=True)
        return

    players = bot.deps.db.list_players(int(game["id"]))
    ranking: list[tuple[str, float]] = []
    for row in players:
        player_id = int(row["id"])
        cash = float(row["cash"])
        positions = bot.deps.db.list_positions(player_id)
        payoff = 0.0
        for pos in positions:
            payoff += pos.quantity * intrinsic_value(pos.option_type, pos.strike, close) * 100
        final_equity = cash + payoff
        member = interaction.guild.get_member(int(row["user_id"])) if interaction.guild else None
        name = member.display_name if member else str(row["user_id"])
        ranking.append((name, final_equity))

    ranking.sort(key=lambda x: x[1], reverse=True)
    bot.deps.db.close_game(int(game["id"]))

    lines = [f"Underlying close ({game['underlying']}): **${close:.2f}**"]
    for idx, (name, score) in enumerate(ranking, start=1):
        lines.append(f"{idx}. {name} — ${score:,.2f}")
    await interaction.response.send_message("**FINAL RESULTS**\n" + "\n".join(lines))
