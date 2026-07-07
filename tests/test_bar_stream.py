"""Tests cho live/bar_stream.py — WS publicTrade -> clean -> dollar bars.

Yêu cầu cốt lõi: bar sinh từ stream (trades đến từng message nhỏ) phải
GIỐNG HỆT chạy batch trên cùng dãy trade — tính chất stateful đã có sẵn
của TradeCleaner/DollarBarBuilder, ở đây khóa lại ở tầng feed.
"""
import json

import numpy as np
import pandas as pd
import pytest

from bars.pipeline import Config, DollarBarBuilder, TradeCleaner
from live.bar_stream import LiveBarFeed, parse_trade_message


def ws_msg(trades):
    return json.dumps({
        "topic": "publicTrade.BTCUSDT", "type": "snapshot", "ts": trades[-1][0],
        "data": [{"T": t, "s": "BTCUSDT", "S": s, "v": str(v), "p": str(p),
                  "L": "PlusTick", "i": f"id-{t}-{k}", "BT": False}
                 for k, (t, p, v, s) in enumerate(trades)],
    })


class TestParse:
    def test_parses_trades_to_raw_schema(self):
        df = parse_trade_message(ws_msg([(1700000000000, 60000.5, 0.01, "Buy"),
                                         (1700000000100, 60001.0, 0.02, "Sell")]))
        assert list(df.columns) == ["ts", "price", "size", "side", "tid"]
        assert df["ts"].dtype == np.int64
        assert df["price"].iloc[0] == 60000.5
        assert df["side"].tolist() == ["Buy", "Sell"]
        assert df["tid"].iloc[0] == "id-1700000000000-0"

    def test_returns_none_for_non_trade_messages(self):
        assert parse_trade_message(json.dumps({"op": "pong"})) is None
        assert parse_trade_message(json.dumps(
            {"topic": "orderbook.50.BTCUSDT", "data": {}})) is None


class TestLiveBarFeed:
    def test_stream_bars_match_batch(self):
        rng = np.random.default_rng(3)
        n = 3000
        ts = 1_700_000_000_000 + np.cumsum(rng.integers(50, 500, n))
        price = 60_000 * np.exp(np.cumsum(rng.normal(0, 1e-4, n)))
        size = np.exp(rng.normal(-2, 1, n))
        side = np.where(rng.random(n) < 0.5, "Buy", "Sell")

        cfg = Config()
        cfg.DOLLAR_THRESHOLD = 2_000_000.0

        # batch: cả dãy qua cleaner + builder một lần
        raw = pd.DataFrame({"ts": ts, "price": price, "size": size,
                            "side": side, "tid": [f"id-{t}-0" for t in ts]})
        clean, _ = TradeCleaner(cfg).clean(raw)
        expect = DollarBarBuilder(cfg).update(clean)

        # stream: từng message 7 trade một
        got = []
        feed = LiveBarFeed(cfg, on_bar=got.append)
        for a in range(0, n, 7):
            chunk = [(int(ts[i]), float(price[i]), float(size[i]), str(side[i]))
                     for i in range(a, min(a + 7, n))]
            feed.on_message(ws_msg(chunk))
        bars = pd.concat(got, ignore_index=True)

        pd.testing.assert_frame_equal(bars, expect)

    def test_callback_only_fires_on_closed_bars(self):
        cfg = Config()
        cfg.DOLLAR_THRESHOLD = 1e12  # không bao giờ đóng bar
        got = []
        feed = LiveBarFeed(cfg, on_bar=got.append)
        feed.on_message(ws_msg([(1700000000000, 60000.0, 0.01, "Buy")]))
        assert got == []
        assert feed.n_trades_seen == 1
