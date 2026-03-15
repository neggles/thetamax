from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import aiohttp


@dataclass(frozen=True)
class OptionQuote:
    symbol: str
    bid: float
    ask: float
    last: float

    @property
    def mid(self) -> float:
        if self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2
        return self.last


class TradierClient:
    def __init__(self, token: str, base_url: str = "https://api.tradier.com") -> None:
        self.token = token
        self.base_url = base_url.rstrip("/")

    async def _get(self, path: str, params: dict[str, str]) -> dict:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(f"{self.base_url}{path}", params=params, timeout=20) as response:
                response.raise_for_status()
                return await response.json()

    async def get_underlying_price(self, symbol: str) -> float:
        data = await self._get("/v1/markets/quotes", {"symbols": symbol.upper()})
        quote = data["quotes"]["quote"]
        last = quote.get("last") or quote.get("close")
        if last is None:
            raise ValueError(f"No quote found for {symbol}")
        return float(last)

    async def get_option_mid_price(self, option_symbol: str) -> float:
        data = await self._get("/v1/markets/quotes", {"symbols": option_symbol, "greeks": "false"})
        quote = data["quotes"]["quote"]
        oq = OptionQuote(
            symbol=option_symbol,
            bid=float(quote.get("bid") or 0.0),
            ask=float(quote.get("ask") or 0.0),
            last=float(quote.get("last") or 0.0),
        )
        mid = oq.mid
        if mid <= 0:
            raise ValueError(f"No reliable option quote for {option_symbol}")
        return mid


def build_occ_option_symbol(underlying: str, strike: float, option_type: str, expiry: datetime | None = None) -> str:
    expiry = expiry or datetime.now()
    option_flag = "C" if option_type == "call" else "P"
    root = underlying.upper().ljust(6)
    strike_int = int(round(strike * 1000))
    return f"{root}{expiry:%y%m%d}{option_flag}{strike_int:08d}".replace(" ", "")


def intrinsic_value(option_type: str, strike: float, underlying_close: float) -> float:
    if option_type == "call":
        return max(0.0, underlying_close - strike)
    return max(0.0, strike - underlying_close)
