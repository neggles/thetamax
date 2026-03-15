"""Options P&L calculations for ThetaMax."""

from __future__ import annotations

CONTRACT_MULTIPLIER = 100  # each contract covers 100 shares / index units


def intrinsic_value(option_type: str, strike: float, underlying_price: float) -> float:
    """Return the intrinsic value of an option at expiry.

    Args:
        option_type: ``"call"`` or ``"put"``
        strike: Strike price of the option.
        underlying_price: Underlying asset price at settlement / query time.

    Returns:
        Intrinsic value per share (never negative).
    """
    if option_type == "call":
        return max(0.0, underlying_price - strike)
    else:  # put
        return max(0.0, strike - underlying_price)


def settlement_pnl(
    option_type: str,
    strike: float,
    quantity: int,
    direction: str,
    entry_price: float,
    settlement_price: float,
) -> float:
    """Calculate P&L for a position at settlement (expiry).

    Args:
        option_type: ``"call"`` or ``"put"``
        strike: Strike price of the option.
        quantity: Number of contracts.
        direction: ``"long"`` (bought) or ``"short"`` (sold).
        entry_price: Premium paid/received per share when the position was opened.
        settlement_price: Underlying price at market close.

    Returns:
        Total P&L in dollars (positive = profit).
    """
    iv = intrinsic_value(option_type, strike, settlement_price)
    if direction == "long":
        return (iv - entry_price) * quantity * CONTRACT_MULTIPLIER
    else:  # short
        return (entry_price - iv) * quantity * CONTRACT_MULTIPLIER


def unrealized_pnl(
    direction: str,
    quantity: int,
    entry_price: float,
    current_price: float,
) -> float:
    """Calculate unrealized P&L based on the current option market price.

    Args:
        direction: ``"long"`` or ``"short"``
        quantity: Number of contracts.
        entry_price: Premium paid/received per share when opened.
        current_price: Current mid-market price of the option per share.

    Returns:
        Unrealized P&L in dollars.
    """
    if direction == "long":
        return (current_price - entry_price) * quantity * CONTRACT_MULTIPLIER
    else:  # short
        return (entry_price - current_price) * quantity * CONTRACT_MULTIPLIER


def position_cash_cost(direction: str, entry_price: float, quantity: int) -> float:
    """Return the cash impact (debit/credit) of opening a position.

    Buying (long) costs cash → negative.
    Selling (short) receives premium → positive.

    Args:
        direction: ``"long"`` or ``"short"``
        entry_price: Per-share option premium.
        quantity: Number of contracts.

    Returns:
        Net cash flow in dollars when the position is opened.
    """
    gross = entry_price * quantity * CONTRACT_MULTIPLIER
    return -gross if direction == "long" else gross


def format_pnl(pnl: float) -> str:
    """Format a P&L value as a signed dollar string with colour indicators."""
    if pnl >= 0:
        return f"+${pnl:,.2f} 📈"
    return f"-${abs(pnl):,.2f} 📉"
