from __future__ import annotations

import asyncio

from dotenv import load_dotenv

from .bot import BotDeps, OptionsPokerBot
from .config import Settings
from .db import Database
from .pricing import TradierClient


def main() -> None:
    load_dotenv()
    settings = Settings.from_env()

    db = Database(settings.database_url)
    pricing = TradierClient(token=settings.tradier_token, base_url=settings.tradier_base_url)
    bot = OptionsPokerBot(BotDeps(db=db, pricing=pricing))

    asyncio.run(bot.start(settings.discord_token))


if __name__ == "__main__":
    main()
