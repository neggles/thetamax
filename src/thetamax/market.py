"""Market hours and Eastern-Time utilities for ThetaMax."""

from __future__ import annotations

from datetime import datetime, time, timedelta

import pytz

ET = pytz.timezone("America/New_York")

MARKET_OPEN_TIME = time(9, 30)
MARKET_CLOSE_TIME = time(16, 0)


def now_et() -> datetime:
    """Return the current datetime in US/Eastern time."""
    return datetime.now(ET)


def is_market_open() -> bool:
    """Return ``True`` if the US equity market is currently open.

    Checks weekday (Mon–Fri) and time (09:30–15:59:59 ET).
    Does **not** account for market holidays.
    """
    now = now_et()
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    t = now.time()
    return MARKET_OPEN_TIME <= t < MARKET_CLOSE_TIME


def is_trading_day() -> bool:
    """Return ``True`` if today is a weekday (Mon–Fri).

    Does **not** account for market holidays.
    """
    return now_et().weekday() < 5


def today_market_open() -> datetime:
    """Return today's market-open time (09:30 ET) as an aware datetime."""
    n = now_et()
    naive = datetime(n.year, n.month, n.day, MARKET_OPEN_TIME.hour, MARKET_OPEN_TIME.minute)
    return ET.localize(naive)


def today_market_close() -> datetime:
    """Return today's market-close time (16:00 ET) as an aware datetime."""
    n = now_et()
    naive = datetime(n.year, n.month, n.day, MARKET_CLOSE_TIME.hour, MARKET_CLOSE_TIME.minute)
    return ET.localize(naive)


def next_market_open() -> datetime:
    """Return the next market-open datetime (skips weekends).

    If the market is currently open, returns tomorrow's open (or the next
    trading day's open).
    """
    n = now_et()
    today_open = today_market_open()

    # If it's a weekday and we're before today's market open, return today's open.
    if n.weekday() < 5 and n < today_open:
        return today_open

    # Otherwise, return the next trading day's open (skipping weekends).
    candidate = n + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    naive = datetime(
        candidate.year,
        candidate.month,
        candidate.day,
        MARKET_OPEN_TIME.hour,
        MARKET_OPEN_TIME.minute,
    )
    return ET.localize(naive)


def today_iso() -> str:
    """Return today's date (ET) in ISO-8601 format (``YYYY-MM-DD``)."""
    return now_et().date().isoformat()


def time_until_close() -> timedelta:
    """Return a :class:`timedelta` until today's market close.

    Returns a zero-duration timedelta if the market is already closed.
    """
    close = today_market_close()
    now = now_et()
    delta = close - now
    return delta if delta.total_seconds() > 0 else timedelta(0)
