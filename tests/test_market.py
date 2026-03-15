"""Tests for thetamax.market — timezone and hours helpers."""

from datetime import time, timedelta
from unittest.mock import patch

import pytest
import pytz

from thetamax.market import (
    ET,
    MARKET_CLOSE_TIME,
    MARKET_OPEN_TIME,
    is_market_open,
    is_trading_day,
    next_market_open,
    time_until_close,
    today_iso,
    today_market_close,
    today_market_open,
)


def _make_dt(weekday: int, hour: int, minute: int = 0):
    """Build an ET-aware datetime with the given weekday and time.

    weekday: 0=Mon … 4=Fri, 5=Sat, 6=Sun
    """
    from datetime import datetime

    # Start from a known Monday (2024-01-08 = Monday)
    base = ET.localize(datetime(2024, 1, 8, hour, minute))  # Monday
    delta = timedelta(days=weekday)
    return base + delta


class TestMarketConstants:
    def test_open_time(self) -> None:
        assert MARKET_OPEN_TIME == time(9, 30)

    def test_close_time(self) -> None:
        assert MARKET_CLOSE_TIME == time(16, 0)


class TestIsMarketOpen:
    def test_open_during_hours_weekday(self) -> None:
        dt = _make_dt(0, 10, 0)  # Monday 10:00 ET
        with patch("thetamax.market.now_et", return_value=dt):
            assert is_market_open() is True

    def test_closed_before_open(self) -> None:
        dt = _make_dt(0, 9, 0)  # Monday 09:00 ET
        with patch("thetamax.market.now_et", return_value=dt):
            assert is_market_open() is False

    def test_closed_at_market_close(self) -> None:
        dt = _make_dt(0, 16, 0)  # Monday 16:00 ET — market is closed at/after 16:00
        with patch("thetamax.market.now_et", return_value=dt):
            assert is_market_open() is False

    def test_closed_after_close(self) -> None:
        dt = _make_dt(0, 17, 0)  # Monday 17:00 ET
        with patch("thetamax.market.now_et", return_value=dt):
            assert is_market_open() is False

    def test_closed_on_saturday(self) -> None:
        dt = _make_dt(5, 12, 0)  # Saturday noon
        with patch("thetamax.market.now_et", return_value=dt):
            assert is_market_open() is False

    def test_closed_on_sunday(self) -> None:
        dt = _make_dt(6, 12, 0)  # Sunday noon
        with patch("thetamax.market.now_et", return_value=dt):
            assert is_market_open() is False

    def test_open_at_market_open(self) -> None:
        dt = _make_dt(1, 9, 30)  # Tuesday 09:30 ET
        with patch("thetamax.market.now_et", return_value=dt):
            assert is_market_open() is True

    def test_open_one_minute_before_close(self) -> None:
        dt = _make_dt(2, 15, 59)  # Wednesday 15:59 ET
        with patch("thetamax.market.now_et", return_value=dt):
            assert is_market_open() is True


class TestIsTradingDay:
    def test_monday_is_trading_day(self) -> None:
        dt = _make_dt(0, 12, 0)
        with patch("thetamax.market.now_et", return_value=dt):
            assert is_trading_day() is True

    def test_friday_is_trading_day(self) -> None:
        dt = _make_dt(4, 12, 0)
        with patch("thetamax.market.now_et", return_value=dt):
            assert is_trading_day() is True

    def test_saturday_is_not_trading_day(self) -> None:
        dt = _make_dt(5, 12, 0)
        with patch("thetamax.market.now_et", return_value=dt):
            assert is_trading_day() is False

    def test_sunday_is_not_trading_day(self) -> None:
        dt = _make_dt(6, 12, 0)
        with patch("thetamax.market.now_et", return_value=dt):
            assert is_trading_day() is False


class TestTodayMarketTimes:
    def test_market_open_time(self) -> None:
        dt = _make_dt(0, 12, 0)  # Monday noon
        with patch("thetamax.market.now_et", return_value=dt):
            open_dt = today_market_open()
        assert open_dt.hour == 9
        assert open_dt.minute == 30
        assert open_dt.tzinfo is not None

    def test_market_close_time(self) -> None:
        dt = _make_dt(0, 12, 0)
        with patch("thetamax.market.now_et", return_value=dt):
            close_dt = today_market_close()
        assert close_dt.hour == 16
        assert close_dt.minute == 0
        assert close_dt.tzinfo is not None


class TestTimeUntilClose:
    def test_positive_during_market_hours(self) -> None:
        dt = _make_dt(0, 10, 0)  # 6 hours before close
        with patch("thetamax.market.now_et", return_value=dt):
            delta = time_until_close()
        assert delta.total_seconds() > 0

    def test_zero_after_close(self) -> None:
        dt = _make_dt(0, 17, 0)  # after close
        with patch("thetamax.market.now_et", return_value=dt):
            delta = time_until_close()
        assert delta.total_seconds() == 0


class TestTodayIso:
    def test_returns_string(self) -> None:
        result = today_iso()
        assert isinstance(result, str)
        # YYYY-MM-DD format
        assert len(result) == 10
        assert result[4] == "-"
        assert result[7] == "-"
