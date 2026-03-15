# 0DTE Options Poker Discord Bot

A Discord bot for running daily 0DTE options poker tournaments with fake bankrolls, live Tradier option quotes, and SQLite persistence.

## Stack

- Python 3.11+
- `discord.py`
- Tradier API (sandbox or production)
- SQLite
- `uv` package management
- `src/` project layout

## Quick start

```bash
uv sync
cp .env.example .env
# set DISCORD_TOKEN + TRADIER_TOKEN
uv run options-poker-bot
```

## Environment variables

| Variable | Required | Default | Notes |
|---|---|---|---|
| `DISCORD_TOKEN` | yes | - | Discord bot token |
| `TRADIER_TOKEN` | yes | - | Tradier API token |
| `TRADIER_BASE_URL` | no | `https://api.tradier.com` | Use `https://sandbox.tradier.com` for sandbox |
| `DATABASE_URL` | no | `options_poker.db` | SQLite database path |

## Slash commands

- `/start_game symbol:SPY starting_bankroll:10000`
- `/buy option_type:call strike:580 qty:2`
- `/sell option_type:put strike:575 qty:1`
- `/portfolio`
- `/leaderboard`
- `/settle`

## Notes

- Options are priced from Tradier quote endpoints using OCC option symbols for today's expiry.
- Positions are marked with option mid-price (`(bid + ask)/2`) when available.
- Settlement calculates intrinsic value at close (per contract multiplier 100).
