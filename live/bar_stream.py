"""WS publicTrade Bybit -> TradeCleaner -> DollarBarBuilder -> callback.

parse_trade_message là pure function (test bằng fixture JSON). LiveBarFeed
ghép cleaner + builder stateful sẵn có của bars/pipeline.py — bar từ stream
giống hệt chạy batch (khóa bằng test đối chiếu). run_ws là vòng lặp mạng
mỏng (websocket-client, tự reconnect), không unit test.
"""
from __future__ import annotations

import json
import time
from typing import Callable

import numpy as np
import pandas as pd

from bars.pipeline import Config, DollarBarBuilder, TradeCleaner

WS_URL = "wss://stream.bybit.com/v5/public/linear"


def parse_trade_message(raw: str) -> pd.DataFrame | None:
    """Message publicTrade -> DataFrame schema raw (ts/price/size/side/tid).
    None nếu không phải message trade (pong, subscribe ack, topic khác)."""
    msg = json.loads(raw)
    if not str(msg.get("topic", "")).startswith("publicTrade."):
        return None
    data = msg.get("data") or []
    return pd.DataFrame({
        "ts": np.array([int(d["T"]) for d in data], dtype=np.int64),
        "price": np.array([float(d["p"]) for d in data], dtype=np.float64),
        "size": np.array([float(d["v"]) for d in data], dtype=np.float64),
        "side": [str(d["S"]) for d in data],
        "tid": [str(d["i"]) for d in data],
    })


class LiveBarFeed:
    """Nạp message WS, phát bars VỪA ĐÓNG qua on_bar(DataFrame)."""

    def __init__(self, cfg: Config, on_bar: Callable[[pd.DataFrame], None]):
        self._cleaner = TradeCleaner(cfg)
        self._builder = DollarBarBuilder(cfg)
        self._on_bar = on_bar
        self.n_trades_seen = 0

    def on_message(self, raw: str) -> None:
        df = parse_trade_message(raw)
        if df is None or df.empty:
            return
        self.n_trades_seen += len(df)
        clean, _ = self._cleaner.clean(df)
        bars = self._builder.update(clean)
        if len(bars):
            self._on_bar(bars)

    @property
    def partial_dollar(self) -> float:
        return self._builder.partial_dollar


def run_ws(feed: LiveBarFeed, symbol: str = "BTCUSDT",
           url: str = WS_URL, log=print) -> None:
    """Vòng lặp WS blocking, tự reconnect. Ctrl-C để dừng."""
    import websocket  # websocket-client

    def on_open(ws):
        ws.send(json.dumps({"op": "subscribe",
                            "args": [f"publicTrade.{symbol}"]}))
        log(f"WS đã subscribe publicTrade.{symbol}")

    def on_message(ws, raw):
        feed.on_message(raw)

    while True:
        try:
            ws = websocket.WebSocketApp(url, on_open=on_open,
                                        on_message=on_message)
            ws.run_forever(ping_interval=20, ping_timeout=10)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            log(f"WS lỗi: {e}")
        log("WS ngắt — reconnect sau 3s...")
        time.sleep(3)
