"""Configuration management for ThetaMax bot."""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    """Bot configuration loaded from environment variables."""

    DISCORD_TOKEN: str = os.environ.get("DISCORD_TOKEN", "")
    TRADIER_TOKEN: str = os.environ.get("TRADIER_TOKEN", "")
    TRADIER_SANDBOX: bool = os.environ.get("TRADIER_SANDBOX", "true").lower() == "true"
    DATABASE_PATH: str = os.environ.get("DATABASE_PATH", "thetamax.db")
    STARTING_BANKROLL: float = float(os.environ.get("STARTING_BANKROLL", "10000"))
    ADMIN_ROLE_NAME: str = os.environ.get("ADMIN_ROLE_NAME", "ThetaMax Admin")
    DEFAULT_UNDERLYING: str = os.environ.get("DEFAULT_UNDERLYING", "SPY")

    # Each option contract covers 100 shares / index points
    CONTRACT_MULTIPLIER: int = 100


config = Config()
