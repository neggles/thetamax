from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    discord_token: str
    tradier_token: str
    tradier_base_url: str
    database_url: str


    @classmethod
    def from_env(cls) -> "Settings":
        discord_token = os.getenv("DISCORD_TOKEN", "")
        tradier_token = os.getenv("TRADIER_TOKEN", "")
        tradier_base_url = os.getenv("TRADIER_BASE_URL", "https://api.tradier.com")
        database_url = os.getenv("DATABASE_URL", "options_poker.db")

        if not discord_token:
            raise ValueError("DISCORD_TOKEN is required")
        if not tradier_token:
            raise ValueError("TRADIER_TOKEN is required")

        return cls(
            discord_token=discord_token,
            tradier_token=tradier_token,
            tradier_base_url=tradier_base_url,
            database_url=database_url,
        )
