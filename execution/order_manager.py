"""State machine vào/ra lệnh — 1 vị thế, bar-driven.

    IDLE --submit(signal)--> ENTRY_PENDING --khớp--> IN_POSITION --> IDLE
                                  |                       |
                                  +--hết TTL: hủy         +--TP/SL sàn khớp (exited)
                                                          +--hết horizon: market close

Barrier TP/SL gắn ngay trên entry order nên sàn tự xử — on_bar chỉ cần
phát hiện vị thế đã flat. TradeManager thuần logic: exchange inject được
(cần place_order/cancel_order/position), mọi chuyển trạng thái trả về
list event dict để caller ghi journal + báo RiskManager.

pnl_approx trong event exit dùng close của bar hiện tại làm proxy giá
thoát (đủ cho kill switch); fill thật đối chiếu sau qua /v5/execution/list.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from execution.bybit_client import build_entry_order, build_market_close
from live.signal import Signal


@dataclass
class ExecConfig:
    symbol: str = "BTCUSDT"
    qty: float = 0.001
    entry_ttl_bars: int = 3   # entry post-only chưa khớp sau N bar -> hủy


class TradeManager:
    def __init__(self, exchange, cfg: ExecConfig = ExecConfig()):
        self.ex = exchange
        self.cfg = cfg
        self.state = "IDLE"
        self._sig: Signal | None = None
        self._link_id = ""
        self._n_orders = 0
        self._bars_waited = 0
        self._bars_held = 0
        self._entry_price = 0.0

    def submit(self, signal: Signal) -> bool:
        """Đặt entry post-only tại close bar tín hiệu. False nếu đang bận."""
        if self.state != "IDLE":
            return False
        self._n_orders += 1
        self._link_id = f"cbot-{signal.t_close}-{self._n_orders}"
        self.ex.place_order(build_entry_order(
            symbol=self.cfg.symbol, side=signal.side, qty=self.cfg.qty,
            price=signal.entry_ref, tp=signal.tp_price, sl=signal.sl_price,
            link_id=self._link_id))
        self._sig = signal
        self._bars_waited = 0
        self.state = "ENTRY_PENDING"
        return True

    def on_bar(self, bar: dict) -> list[dict]:
        """Gọi mỗi khi 1 dollar bar đóng. Trả về events cho journal/risk."""
        if self.state == "ENTRY_PENDING":
            return self._tick_pending(bar)
        if self.state == "IN_POSITION":
            return self._tick_position(bar)
        return []

    # --- helpers ---
    def _flat(self) -> bool:
        pos = self.ex.position(self.cfg.symbol)
        return not pos or float(pos.get("size") or 0) == 0

    def _pnl_approx(self, close: float) -> float:
        d = 1.0 if self._sig.side == "Buy" else -1.0
        return float(d * np.log(close / self._entry_price))

    def _tick_pending(self, bar: dict) -> list[dict]:
        pos = self.ex.position(self.cfg.symbol)
        if pos and float(pos.get("size") or 0) > 0:
            self._entry_price = float(pos["avgPrice"])
            self._bars_held = 0
            self.state = "IN_POSITION"
            return [{"event": "entry_filled", "t": bar["t_close"],
                     "side": self._sig.side, "avg_price": self._entry_price,
                     "link_id": self._link_id}]
        self._bars_waited += 1
        if self._bars_waited >= self.cfg.entry_ttl_bars:
            self.ex.cancel_order(self.cfg.symbol, self._link_id)
            self.state = "IDLE"
            return [{"event": "entry_cancelled", "t": bar["t_close"],
                     "side": self._sig.side, "link_id": self._link_id,
                     "reason": f"chưa khớp sau {self._bars_waited} bars"}]
        return []

    def _tick_position(self, bar: dict) -> list[dict]:
        if self._flat():  # TP hoặc SL trên sàn đã khớp
            self.state = "IDLE"
            return [{"event": "exited", "t": bar["t_close"],
                     "side": self._sig.side, "entry_price": self._entry_price,
                     "pnl_approx": self._pnl_approx(bar["close"]),
                     "link_id": self._link_id}]
        self._bars_held += 1
        if self._bars_held >= self._sig.horizon_bars:
            self.ex.place_order(build_market_close(
                symbol=self.cfg.symbol, position_side=self._sig.side,
                qty=self.cfg.qty))
            self.state = "IDLE"
            return [{"event": "time_exit", "t": bar["t_close"],
                     "side": self._sig.side, "entry_price": self._entry_price,
                     "pnl_approx": self._pnl_approx(bar["close"]),
                     "link_id": self._link_id}]
        return []
