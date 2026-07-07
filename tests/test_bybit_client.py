"""Tests cho execution/bybit_client.py — ký request v5 + build payload lệnh.

Phần thuần (ký HMAC, làm tròn tick, build payload) test kỹ; phần HTTP là
wrapper mỏng không unit test. Vector chữ ký tính độc lập bằng hmac/hashlib.
"""
import pytest

from execution.bybit_client import (build_entry_order, build_market_close,
                                    round_to_step, sign_v5)


class TestSignV5:
    # hmac.new(b"testsecret", b"1700000000000testkey5000category=linear&symbol=BTCUSDT", sha256)
    KNOWN = "f2f79889fd1201752936b389c890e9d393e01e0311a6d8785fb80753aa26c69b"

    def test_known_vector(self):
        assert sign_v5("testsecret", 1700000000000, "testkey", 5000,
                       "category=linear&symbol=BTCUSDT") == self.KNOWN

    def test_changes_with_payload(self):
        a = sign_v5("testsecret", 1700000000000, "testkey", 5000, "a=1")
        b = sign_v5("testsecret", 1700000000000, "testkey", 5000, "a=2")
        assert a != b


class TestRoundToStep:
    def test_price_tick(self):
        assert round_to_step(60123.4567, 0.1) == pytest.approx(60123.4)

    def test_qty_step(self):
        assert round_to_step(0.0123456, 0.001) == pytest.approx(0.012)

    def test_rounds_down_never_up(self):
        assert round_to_step(0.0999, 0.001) == pytest.approx(0.099)

    def test_no_float_dust(self):
        # 0.1 nhị phân không biểu diễn được — kết quả phải là chuỗi thập phân sạch
        assert str(round_to_step(60123.45, 0.1)) == "60123.4"


class TestBuildEntryOrder:
    def test_post_only_limit_with_tpsl(self):
        o = build_entry_order(symbol="BTCUSDT", side="Buy", qty=0.01,
                              price=60000.15, tp=61000.27, sl=59000.33,
                              link_id="cbot-1")
        assert o["category"] == "linear"
        assert o["orderType"] == "Limit"
        assert o["timeInForce"] == "PostOnly"
        assert o["side"] == "Buy"
        # API v5 nhận số dạng chuỗi, đã làm tròn tick 0.1 / step 0.001
        assert o["qty"] == "0.01"
        assert o["price"] == "60000.1"
        assert o["takeProfit"] == "61000.2"
        assert o["stopLoss"] == "59000.3"
        assert o["tpslMode"] == "Full"
        assert o["orderLinkId"] == "cbot-1"
        assert "reduceOnly" not in o

    def test_sell_side(self):
        o = build_entry_order(symbol="BTCUSDT", side="Sell", qty=0.01,
                              price=60000.0, tp=59000.0, sl=61000.0,
                              link_id="x")
        assert o["side"] == "Sell"


class TestBuildMarketClose:
    def test_reduce_only_market(self):
        o = build_market_close(symbol="BTCUSDT", position_side="Buy", qty=0.01)
        assert o["orderType"] == "Market"
        assert o["side"] == "Sell"  # đóng vị thế Buy = bán
        assert o["reduceOnly"] is True
        assert o["qty"] == "0.01"

    def test_closes_sell_position_with_buy(self):
        o = build_market_close(symbol="BTCUSDT", position_side="Sell", qty=0.01)
        assert o["side"] == "Buy"
