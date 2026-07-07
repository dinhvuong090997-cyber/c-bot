"""Tests cho risk/rules.py — hard rules trước khi đặt lệnh.

RiskManager là cổng cuối cùng trước execution: 1 vị thế duy nhất,
giới hạn số lệnh/ngày (UTC), kill switch theo tổng lỗ trong ngày.
Kill switch là VĨNH VIỄN trong đời process — chỉ restart tay mới reset.
"""
import pytest

from risk.rules import RiskConfig, RiskManager

DAY = 86_400_000
T0 = 1_700_000_000_000  # mốc ms bất kỳ


def mk(**kw):
    return RiskManager(RiskConfig(**kw))


class TestPositionLimit:
    def test_allows_entry_when_idle(self):
        rm = mk()
        ok, reason = rm.allow_entry(T0)
        assert ok and reason == ""

    def test_blocks_second_entry_while_position_open(self):
        rm = mk()
        rm.on_entry(T0)
        ok, reason = rm.allow_entry(T0 + 1)
        assert not ok
        assert "vị thế" in reason

    def test_allows_again_after_exit(self):
        rm = mk()
        rm.on_entry(T0)
        rm.on_exit(T0 + 1000, pnl=0.001)
        ok, _ = rm.allow_entry(T0 + 2000)
        assert ok


class TestDailyTradeLimit:
    def test_blocks_after_max_trades_per_day(self):
        rm = mk(max_trades_per_day=2)
        for i in range(2):
            assert rm.allow_entry(T0 + i * 1000)[0]
            rm.on_entry(T0 + i * 1000)
            rm.on_exit(T0 + i * 1000 + 500, pnl=0.0)
        ok, reason = rm.allow_entry(T0 + 5000)
        assert not ok
        assert "lệnh/ngày" in reason

    def test_counter_resets_next_utc_day(self):
        rm = mk(max_trades_per_day=1)
        rm.on_entry(T0)
        rm.on_exit(T0 + 500, pnl=0.0)
        assert not rm.allow_entry(T0 + 1000)[0]
        next_day = (T0 // DAY + 1) * DAY
        assert rm.allow_entry(next_day)[0]


class TestKillSwitch:
    def test_kills_after_daily_loss_limit(self):
        rm = mk(daily_loss_limit=0.02)
        rm.on_entry(T0)
        rm.on_exit(T0 + 500, pnl=-0.025)
        ok, reason = rm.allow_entry(T0 + 1000)
        assert not ok
        assert "kill" in reason.lower()
        assert rm.killed

    def test_kill_is_permanent_across_days(self):
        rm = mk(daily_loss_limit=0.02)
        rm.on_entry(T0)
        rm.on_exit(T0 + 500, pnl=-0.03)
        next_day = (T0 // DAY + 1) * DAY
        assert not rm.allow_entry(next_day)[0]

    def test_losses_accumulate_within_day(self):
        rm = mk(daily_loss_limit=0.02, max_trades_per_day=100)
        for i in range(2):
            rm.on_entry(T0 + i * 1000)
            rm.on_exit(T0 + i * 1000 + 500, pnl=-0.012)
        assert rm.killed

    def test_daily_loss_resets_next_day(self):
        rm = mk(daily_loss_limit=0.02, max_trades_per_day=100)
        rm.on_entry(T0)
        rm.on_exit(T0 + 500, pnl=-0.015)
        next_day = (T0 // DAY + 1) * DAY
        rm.on_entry(next_day)
        rm.on_exit(next_day + 500, pnl=-0.015)  # -0.015 hôm nay < limit
        assert not rm.killed

    def test_profit_does_not_kill(self):
        rm = mk(daily_loss_limit=0.02, max_trades_per_day=100)
        rm.on_entry(T0)
        rm.on_exit(T0 + 500, pnl=0.05)
        assert not rm.killed
        assert rm.allow_entry(T0 + 1000)[0]
