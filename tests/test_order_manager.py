"""Tests cho execution/order_manager.py — state machine 1 vị thế.

IDLE -> submit(signal) -> ENTRY_PENDING -> khớp -> IN_POSITION -> TP/SL sàn
tự đóng hoặc time-exit khi hết horizon -> IDLE. Exchange được inject (fake
trong test) — TradeManager chỉ là logic thuần, gọi được từ vòng lặp on_bar.
"""
import numpy as np
import pytest

from execution.order_manager import ExecConfig, TradeManager
from live.signal import Signal


class FakeExchange:
    def __init__(self):
        self.orders_placed = []
        self.cancelled = []
        self.pos = {}  # {} = flat

    def place_order(self, order):
        self.orders_placed.append(order)
        return {"orderId": f"oid-{len(self.orders_placed)}",
                "orderLinkId": order.get("orderLinkId", "")}

    def cancel_order(self, symbol, order_link_id):
        self.cancelled.append(order_link_id)

    def position(self, symbol):
        return self.pos


def sig(side="Buy", entry=60_000.0, horizon=3):
    return Signal(side=side, conf=0.5, entry_ref=entry,
                  tp_price=entry * 1.01, sl_price=entry * 0.99,
                  horizon_bars=horizon, t_close=1_700_000_000_000)


def bar(close=60_000.0, t=1_700_000_060_000):
    return {"close": close, "t_close": t}


def mk(horizon=3, ttl=2):
    ex = FakeExchange()
    tm = TradeManager(ex, ExecConfig(symbol="BTCUSDT", qty=0.001,
                                     entry_ttl_bars=ttl))
    return ex, tm


class TestSubmit:
    def test_places_post_only_entry(self):
        ex, tm = mk()
        assert tm.submit(sig(side="Buy", entry=60_000.15))
        assert tm.state == "ENTRY_PENDING"
        o = ex.orders_placed[0]
        assert o["timeInForce"] == "PostOnly"
        assert o["side"] == "Buy"
        assert o["price"] == "60000.1"
        assert o["takeProfit"] and o["stopLoss"]

    def test_rejects_submit_when_not_idle(self):
        ex, tm = mk()
        tm.submit(sig())
        assert not tm.submit(sig())
        assert len(ex.orders_placed) == 1


class TestEntryPending:
    def test_fill_moves_to_in_position(self):
        ex, tm = mk()
        tm.submit(sig(side="Buy"))
        ex.pos = {"size": "0.001", "side": "Buy", "avgPrice": "60000.2"}
        events = tm.on_bar(bar())
        assert tm.state == "IN_POSITION"
        assert events[0]["event"] == "entry_filled"
        assert events[0]["avg_price"] == pytest.approx(60000.2)

    def test_cancels_after_ttl_bars(self):
        ex, tm = mk(ttl=2)
        tm.submit(sig())
        assert tm.on_bar(bar()) == []          # bar 1: chờ
        events = tm.on_bar(bar())              # bar 2: hết TTL
        assert tm.state == "IDLE"
        assert ex.cancelled == [ex.orders_placed[0]["orderLinkId"]]
        assert events[0]["event"] == "entry_cancelled"


class TestInPosition:
    def _enter(self, ex, tm, side="Buy", avg=60_000.0):
        tm.submit(sig(side=side, entry=avg))
        ex.pos = {"size": "0.001", "side": side, "avgPrice": str(avg)}
        tm.on_bar(bar())

    def test_barrier_exit_detected_when_position_flat(self):
        ex, tm = mk()
        self._enter(ex, tm, side="Buy", avg=60_000.0)
        ex.pos = {}  # TP/SL trên sàn đã khớp
        events = tm.on_bar(bar(close=60_600.0))
        assert tm.state == "IDLE"
        assert events[0]["event"] == "exited"
        # pnl xấp xỉ bằng close bar hiện tại (proxy, fill thật lấy từ journal)
        assert events[0]["pnl_approx"] == pytest.approx(np.log(60_600 / 60_000))

    def test_short_position_pnl_sign_flipped(self):
        ex, tm = mk()
        self._enter(ex, tm, side="Sell", avg=60_000.0)
        ex.pos = {}
        events = tm.on_bar(bar(close=59_400.0))
        assert events[0]["pnl_approx"] == pytest.approx(np.log(60_000 / 59_400))

    def test_time_exit_after_horizon_bars(self):
        ex, tm = mk(horizon=3)
        self._enter(ex, tm, side="Buy")  # signal horizon=3
        for _ in range(2):
            assert tm.on_bar(bar()) == []
        events = tm.on_bar(bar(close=60_100.0))  # bar thứ 3 sau khi vào
        assert events[0]["event"] == "time_exit"
        close_order = ex.orders_placed[-1]
        assert close_order["orderType"] == "Market"
        assert close_order["reduceOnly"] is True
        assert close_order["side"] == "Sell"
        assert tm.state == "IDLE"
