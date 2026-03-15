"""Tests for thetamax.options — P&L calculations."""

import pytest

from thetamax.options import (
    CONTRACT_MULTIPLIER,
    format_pnl,
    intrinsic_value,
    position_cash_cost,
    settlement_pnl,
    unrealized_pnl,
)


def test_contract_multiplier_applied():
    # Example: Buy 1 call at strike 500, pay $2.00 premium, settle at 510
    # Intrinsic = 10, P&L = (10 - 2) * 1 * CONTRACT_MULTIPLIER
    expected_pnl = (10.0 - 2.0) * 1 * CONTRACT_MULTIPLIER
    actual_pnl = settlement_pnl("call", 500, 1, "long", 2.0, 510.0)
    assert actual_pnl == expected_pnl


class TestIntrinsicValue:
    def test_call_in_the_money(self) -> None:
        assert intrinsic_value("call", strike=500.0, underlying_price=510.0) == pytest.approx(10.0)

    def test_call_at_the_money(self) -> None:
        assert intrinsic_value("call", strike=500.0, underlying_price=500.0) == pytest.approx(0.0)

    def test_call_out_of_the_money(self) -> None:
        assert intrinsic_value("call", strike=500.0, underlying_price=490.0) == pytest.approx(0.0)

    def test_put_in_the_money(self) -> None:
        assert intrinsic_value("put", strike=500.0, underlying_price=490.0) == pytest.approx(10.0)

    def test_put_at_the_money(self) -> None:
        assert intrinsic_value("put", strike=500.0, underlying_price=500.0) == pytest.approx(0.0)

    def test_put_out_of_the_money(self) -> None:
        assert intrinsic_value("put", strike=500.0, underlying_price=510.0) == pytest.approx(0.0)

    def test_never_negative_call(self) -> None:
        assert intrinsic_value("call", strike=600.0, underlying_price=400.0) >= 0

    def test_never_negative_put(self) -> None:
        assert intrinsic_value("put", strike=400.0, underlying_price=600.0) >= 0


class TestSettlementPnl:
    """P&L at expiry for long/short calls and puts."""

    def test_long_call_itm(self) -> None:
        # Buy 1 call at strike 500, pay $2.00 premium, settle at 510
        # Intrinsic = 10, P&L = (10 - 2) * 1 * 100 = $800
        pnl = settlement_pnl("call", 500, 1, "long", 2.0, 510.0)
        assert pnl == pytest.approx(800.0)

    def test_long_call_otm(self) -> None:
        # Call expires worthless
        pnl = settlement_pnl("call", 500, 1, "long", 2.0, 490.0)
        assert pnl == pytest.approx(-200.0)  # lose entire premium

    def test_long_put_itm(self) -> None:
        pnl = settlement_pnl("put", 500, 1, "long", 3.0, 490.0)
        assert pnl == pytest.approx(700.0)  # (10 - 3) * 100

    def test_long_put_otm(self) -> None:
        pnl = settlement_pnl("put", 500, 1, "long", 3.0, 510.0)
        assert pnl == pytest.approx(-300.0)

    def test_short_call_itm(self) -> None:
        # Sell 1 call at 500 for $2.00, settle at 510 → pay out $10 intrinsic
        # P&L = (2 - 10) * 100 = -$800
        pnl = settlement_pnl("call", 500, 1, "short", 2.0, 510.0)
        assert pnl == pytest.approx(-800.0)

    def test_short_call_otm(self) -> None:
        pnl = settlement_pnl("call", 500, 1, "short", 2.0, 490.0)
        assert pnl == pytest.approx(200.0)  # keep entire premium

    def test_short_put_itm(self) -> None:
        pnl = settlement_pnl("put", 500, 1, "short", 3.0, 490.0)
        assert pnl == pytest.approx(-700.0)

    def test_short_put_otm(self) -> None:
        pnl = settlement_pnl("put", 500, 1, "short", 3.0, 510.0)
        assert pnl == pytest.approx(300.0)

    def test_multiple_contracts(self) -> None:
        pnl = settlement_pnl("call", 500, 5, "long", 2.0, 510.0)
        assert pnl == pytest.approx(4000.0)  # (10 - 2) * 5 * 100

    def test_long_short_are_mirror(self) -> None:
        """Long and short of the same trade should sum to zero."""
        long_pnl = settlement_pnl("call", 500, 1, "long", 2.0, 512.0)
        short_pnl = settlement_pnl("call", 500, 1, "short", 2.0, 512.0)
        assert long_pnl + short_pnl == pytest.approx(0.0)


class TestUnrealizedPnl:
    def test_long_profit(self) -> None:
        # Bought at 2.00, now worth 3.00
        pnl = unrealized_pnl("long", 1, 2.0, 3.0)
        assert pnl == pytest.approx(100.0)

    def test_long_loss(self) -> None:
        pnl = unrealized_pnl("long", 1, 2.0, 1.0)
        assert pnl == pytest.approx(-100.0)

    def test_short_profit(self) -> None:
        # Sold at 2.00, now worth 1.00 (dropped in value)
        pnl = unrealized_pnl("short", 1, 2.0, 1.0)
        assert pnl == pytest.approx(100.0)

    def test_short_loss(self) -> None:
        pnl = unrealized_pnl("short", 1, 2.0, 3.0)
        assert pnl == pytest.approx(-100.0)


class TestPositionCashCost:
    def test_long_costs_money(self) -> None:
        cost = position_cash_cost("long", 2.0, 1)
        assert cost == pytest.approx(-200.0)

    def test_short_receives_premium(self) -> None:
        cost = position_cash_cost("short", 2.0, 1)
        assert cost == pytest.approx(200.0)

    def test_multiple_contracts(self) -> None:
        cost = position_cash_cost("long", 2.0, 5)
        assert cost == pytest.approx(-1000.0)


class TestFormatPnl:
    def test_profit(self) -> None:
        result = format_pnl(500.0)
        assert "+$500.00" in result
        assert "📈" in result

    def test_loss(self) -> None:
        result = format_pnl(-250.50)
        assert "-$250.50" in result
        assert "📉" in result

    def test_zero(self) -> None:
        result = format_pnl(0.0)
        assert "+" in result  # zero is treated as non-negative
