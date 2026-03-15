"""ThetaMax Discord bot — entry point.

Run with:
    python -m thetamax

or via the installed script:
    thetamax
"""

from __future__ import annotations

import asyncio
import logging

import discord
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from discord.ext import commands

from thetamax.config import config
from thetamax.database import Database
from thetamax.market import ET
from thetamax.tradier import TradierClient

logger = logging.getLogger(__name__)


class ThetaMaxBot(commands.Bot):
    """The main ThetaMax Discord bot."""

    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

        self.db = Database(config.DATABASE_PATH)
        self.tradier = TradierClient(config.TRADIER_TOKEN, config.TRADIER_SANDBOX)
        self.scheduler = AsyncIOScheduler(timezone=ET)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def setup_hook(self) -> None:
        await self.db.connect()

        await self.load_extension("thetamax.cogs.game")
        await self.load_extension("thetamax.cogs.trading")
        await self.load_extension("thetamax.cogs.info")

        # Sync slash commands globally
        await self.tree.sync()

        # Schedule automated market-open / market-close handling (Mon–Fri ET)
        self.scheduler.add_job(
            self._on_market_open,
            CronTrigger(day_of_week="mon-fri", hour=9, minute=30, timezone=ET),
        )
        self.scheduler.add_job(
            self._on_market_close,
            CronTrigger(day_of_week="mon-fri", hour=16, minute=0, timezone=ET),
        )
        self.scheduler.start()

    async def close(self) -> None:
        self.scheduler.shutdown(wait=False)
        await self.db.close()
        await super().close()

    async def on_ready(self) -> None:
        logger.info("Logged in as %s (ID: %s)", self.user, self.user.id if self.user else "?")
        await self.change_presence(
            activity=discord.Activity(type=discord.ActivityType.watching, name="the options market")
        )

    # ------------------------------------------------------------------
    # Scheduled handlers
    # ------------------------------------------------------------------

    async def _on_market_open(self) -> None:
        """Notify guilds with pending games that trading will begin."""
        logger.info("Market opened (9:30 ET) — announcing pending games")
        for guild in self.guilds:
            game = await self.db.get_active_game(str(guild.id))
            if not game or game["status"] != "pending":
                continue
            channel = self.get_channel(int(game["channel_id"]))
            if isinstance(channel, discord.TextChannel):
                await channel.send(
                    "🔔 **Market is open!** Use `/game begin` to start trading in "
                    f"Game #{game['id']} — **{game['underlying']}**."
                )

    async def _on_market_close(self) -> None:
        """Auto-settle all active games at the real closing price."""
        logger.info("Market closed (16:00 ET) — settling active games")
        game_cog = self.cogs.get("GameCog")
        if game_cog is None:
            logger.error("GameCog not loaded — cannot auto-settle")
            return

        for guild in self.guilds:
            game = await self.db.get_active_game(str(guild.id))
            if not game or game["status"] != "active":
                continue

            channel = self.get_channel(int(game["channel_id"]))
            underlying = game["underlying"]

            price = await self.tradier.get_last_price(underlying)
            if price is None:
                msg = (
                    f"⚠️  Could not fetch closing price for **{underlying}**. "
                    "An admin must settle manually with `/game settle <price>`."
                )
                if isinstance(channel, discord.TextChannel):
                    await channel.send(msg)
                logger.warning(
                    "Could not fetch closing price for %s (game #%d)", underlying, game["id"]
                )
                continue

            logger.info("Settling game #%d (%s) at %.4f", game["id"], underlying, price)
            await game_cog.settle_game(  # type: ignore[attr-defined]
                game, price, channel=channel if isinstance(channel, discord.TextChannel) else None
            )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
    )
    if not config.DISCORD_TOKEN:
        raise RuntimeError("DISCORD_TOKEN is not set. Copy .env.example to .env and fill it in.")

    bot = ThetaMaxBot()

    async def runner() -> None:
        async with bot:
            await bot.start(config.DISCORD_TOKEN)

    asyncio.run(runner())


if __name__ == "__main__":
    main()
