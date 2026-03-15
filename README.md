# thetamax
0DTE options poker

A Discord bot that runs a daily fake-money options trading tournament.
Players build positions using real 0-day options on stocks and indices,
then settle against the real market close price at 4:00 PM ET.

---

## Concept

| Term | What it means |
|------|---------------|
| **0DTE** | Option that expires *today* — your bet resolves at market close |
| **Call** | Bet the price goes **up** past a strike |
| **Put** | Bet the price goes **down** past a strike |
| **Long** | You *buy* the option (pay premium, limited downside) |
| **Short** | You *sell/write* the option (receive premium, unlimited downside) |

Players start with **$10,000** of fake money.  
Whoever has the most at settlement wins.

---

## Quick-start

### 1. Prerequisites

* Python ≥ 3.11
* A [Discord bot token](https://discord.com/developers/applications)
* A [Tradier API token](https://developer.tradier.com/) (free sandbox)

### 2. Install

```bash
git clone https://github.com/neggles/thetamax
cd thetamax
pip install -e ".[dev]"
```

### 3. Configure

```bash
cp .env.example .env
# Edit .env and fill in DISCORD_TOKEN and TRADIER_TOKEN
```

### 4. Run

```bash
python -m thetamax
# or after pip install:
thetamax
```

---

## Discord commands

### Game management (admin only)

| Command | Description |
|---------|-------------|
| `/game start [underlying]` | Create a new game (default: SPY) |
| `/game begin` | Open trading — players can now buy/sell |
| `/game settle <price>` | Manually settle all positions at *price* |
| `/game status` | Show game info and player list |

> **Admin role:** give your Discord role the name set in `ADMIN_ROLE_NAME`
> (default: `ThetaMax Admin`).

### Joining & trading

| Command | Description |
|---------|-------------|
| `/game join` | Join the current game |
| `/buy call <strike> <qty>` | Buy *qty* call contracts at *strike* |
| `/buy put <strike> <qty>` | Buy *qty* put contracts at *strike* |
| `/sell call <strike> <qty>` | Sell (write) *qty* call contracts |
| `/sell put <strike> <qty>` | Sell (write) *qty* put contracts |
| `/close <position_id>` | Close a position early at current market price |
| `/portfolio` | View your open positions and unrealized P&L |

### Information

| Command | Description |
|---------|-------------|
| `/leaderboard` | Current game standings |
| `/quote <symbol>` | Live price for any stock/ETF |
| `/chain [underlying]` | Options chain for today's expiry |

### Seasons

| Command | Description |
|---------|-------------|
| `/season start <name>` | (Admin) Start a weekly season |
| `/season end` | (Admin) End the current season |
| `/season leaderboard` | Cumulative season standings |

---

## How settlement works

1. At **4:00 PM ET** the bot fetches the real closing price via the Tradier API.
2. For every open position it calculates the intrinsic value:
   * Long call P&L = `(max(0, close − strike) − premium) × qty × 100`
   * Long put P&L  = `(max(0, strike − close) − premium) × qty × 100`
   * Short positions are the mirror.
3. Player bankrolls are updated and the final leaderboard is posted.
4. If the API call fails, an admin can settle manually with `/game settle <price>`.

---

## Project layout

```
thetamax/
├── src/
│   └── thetamax/
│       ├── __init__.py
│       ├── __main__.py      # entry point (python -m thetamax)
│       ├── config.py        # env-var configuration
│       ├── database.py      # async SQLite layer (aiosqlite)
│       ├── tradier.py       # Tradier API client (aiohttp)
│       ├── market.py        # market-hours / ET timezone helpers
│       ├── options.py       # P&L math
│       └── cogs/
│           ├── game.py      # /game commands
│           ├── trading.py   # /buy /sell /close /portfolio
│           └── info.py      # /leaderboard /quote /chain /season
├── tests/
│   ├── test_options.py
│   ├── test_market.py
│   └── test_database.py
├── .env.example
├── pyproject.toml
└── requirements.txt
```

---

## Running tests

```bash
pip install -e ".[dev]"
pytest
```

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DISCORD_TOKEN` | *(required)* | Discord bot token |
| `TRADIER_TOKEN` | *(required)* | Tradier API token |
| `TRADIER_SANDBOX` | `true` | Use Tradier sandbox vs live |
| `DATABASE_PATH` | `thetamax.db` | SQLite database file path |
| `STARTING_BANKROLL` | `10000` | Fake dollars each player starts with |
| `ADMIN_ROLE_NAME` | `ThetaMax Admin` | Discord role for admin commands |
| `DEFAULT_UNDERLYING` | `SPY` | Default symbol when none is given |

