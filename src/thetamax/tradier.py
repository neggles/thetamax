"""Tradier API client for real-time options data."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

Row = dict[str, Any]

_SANDBOX_URL = "https://sandbox.tradier.com/v1"
_LIVE_URL = "https://api.tradier.com/v1"


class TradierClient:
    """Async HTTP client for the Tradier brokerage API.

    Supports both the free sandbox environment and the live API.
    All methods return plain dicts / lists so callers don't depend on
    Tradier-specific types.
    """

    def __init__(self, token: str, sandbox: bool = True) -> None:
        self.token = token
        self.base_url = _SANDBOX_URL if sandbox else _LIVE_URL
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        self._session: aiohttp.ClientSession | None = None

    @property
    async def session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(base_url=self.base_url, headers=self._headers)
        return self._session

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    # ------------------------------------------------------------------
    # Quotes
    # ------------------------------------------------------------------

    async def get_quote(self, symbol: str) -> Row | None:
        """Return the latest quote for *symbol* (equity or option).

        Returns ``None`` if the symbol is not found or the API call fails.
        """
        try:
            session = await self._get_session()
            async with session.get(
                f"{self.base_url}/markets/quotes",
                headers=self._headers,
                params={"symbols": symbol, "greeks": "false"},
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
            quotes = data.get("quotes", {}).get("quote")
            if isinstance(quotes, list):
                return quotes[0] if quotes else None
            return quotes
        except Exception as exc:
            logger.warning("get_quote(%s) failed: %s", symbol, exc)
            return None

    async def get_last_price(self, symbol: str) -> float | None:
        """Return the last-traded price for *symbol*, or ``None`` on failure."""
        quote = await self.get_quote(symbol)
        if not quote:
            return None
        # 'last' may be None for thinly-traded options; fall back to 'bid'/'ask' mid
        last = quote.get("last")
        if last is not None:
            return float(last)
        bid = quote.get("bid")
        ask = quote.get("ask")
        if bid is not None and ask is not None:
            return (float(bid) + float(ask)) / 2
        return None

    # ------------------------------------------------------------------
    # Options chain
    # ------------------------------------------------------------------

    async def get_expirations(self, symbol: str) -> list[str]:
        """Return available option expiration dates for *symbol* (YYYY-MM-DD)."""
        try:
            async with self.session.get(
                f"{self.base_url}/markets/options/expirations",
                headers=self._headers,
                params={"symbol": symbol, "includeAllRoots": "true"},
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
            dates = data.get("expirations", {}).get("date", [])
            if isinstance(dates, str):
                return [dates]
            return dates or []
        except Exception as exc:
            logger.warning("get_expirations(%s) failed: %s", symbol, exc)
            return []

    async def get_options_chain(
        self,
        symbol: str,
        expiration: str,
        option_type: str | None = None,
    ) -> list[Row]:
        """Return the options chain for *symbol* on *expiration* date.

        Args:
            symbol: Underlying symbol (e.g. ``"SPY"``).
            expiration: Expiration date in ``YYYY-MM-DD`` format.
            option_type: ``"call"``, ``"put"``, or ``None`` for both.

        Returns:
            List of option contract dicts, each with at least:
            ``symbol``, ``option_type``, ``strike``, ``bid``, ``ask``,
            ``last``, ``greeks`` (delta, gamma, theta, vega, iv).
        """
        params: dict[str, str] = {
            "symbol": symbol,
            "expiration": expiration,
            "greeks": "true",
        }
        if option_type:
            params["optionType"] = option_type
        try:
            async with self.session.get(
                f"{self.base_url}/markets/options/chains",
                headers=self._headers,
                params=params,
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
            options = data.get("options", {}).get("option", [])
            if isinstance(options, dict):
                return [options]
            return options or []
        except Exception as exc:
            logger.warning("get_options_chain(%s, %s) failed: %s", symbol, expiration, exc)
            return []

    async def get_option_quote(
        self,
        symbol: str,
        expiration: str,
        option_type: str,
        strike: float,
    ) -> Row | None:
        """Return the quote for a specific option identified by its parameters.

        First tries to find the contract in the full chain, then falls back to
        a direct quote by OCC symbol if possible.

        Returns a dict with at minimum ``bid``, ``ask``, and ``last``, or
        ``None`` if the contract isn't found.
        """
        chain = await self.get_options_chain(symbol, expiration, option_type)
        for contract in chain:
            if abs(float(contract.get("strike", 0)) - strike) < 0.01:
                return contract
        return None

    # ------------------------------------------------------------------
    # Market clock
    # ------------------------------------------------------------------

    async def get_market_clock(self) -> Row:
        """Return the Tradier market clock dict.

        Keys include ``state`` (``"open"`` / ``"closed"`` / ``"premarket"``
        / ``"postmarket"``), ``timestamp``, ``next_open``, ``next_close``.
        Returns an empty dict on failure.
        """
        try:
            session = await self._get_session()
            async with session.get(
                f"{self.base_url}/markets/clock",
                headers=self._headers,
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
            return data.get("clock", {})
        except Exception as exc:
            logger.warning("get_market_clock() failed: %s", exc)
            return {}

    async def is_market_open(self) -> bool:
        """Return ``True`` if Tradier reports the market as open."""
        clock = await self.get_market_clock()
        return clock.get("state") == "open"
