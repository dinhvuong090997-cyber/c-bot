"""Hard rules — cổng cuối cùng trước khi đặt lệnh.

Ba luật v1, cố ý đơn giản và không có ngoại lệ:
  1. Tối đa 1 vị thế mở tại một thời điểm.
  2. Giới hạn số lệnh vào trong một ngày UTC.
  3. Kill switch: tổng pnl (log-return) trong ngày chạm -daily_loss_limit
     thì khóa VĨNH VIỄN trong đời process — chỉ restart tay mới chạy lại.

Mọi timestamp là ms UTC (khớp t_close của bars).
"""
from __future__ import annotations

from dataclasses import dataclass

_DAY_MS = 86_400_000


@dataclass
class RiskConfig:
    max_trades_per_day: int = 30
    daily_loss_limit: float = 0.02   # tổng log-return âm trong ngày UTC
    max_positions: int = 1


class RiskManager:
    def __init__(self, cfg: RiskConfig = RiskConfig()):
        self.cfg = cfg
        self.killed = False
        self._open_positions = 0
        self._day: int | None = None      # ngày UTC đang đếm
        self._trades_today = 0
        self._pnl_today = 0.0

    def _roll_day(self, now_ms: int) -> None:
        day = now_ms // _DAY_MS
        if day != self._day:
            self._day = day
            self._trades_today = 0
            self._pnl_today = 0.0

    def allow_entry(self, now_ms: int) -> tuple[bool, str]:
        """(ok, lý do). reason rỗng khi ok."""
        self._roll_day(now_ms)
        if self.killed:
            return False, "kill switch đã kích hoạt — cần restart tay"
        if self._open_positions >= self.cfg.max_positions:
            return False, "đang có vị thế mở"
        if self._trades_today >= self.cfg.max_trades_per_day:
            return False, f"đã chạm giới hạn {self.cfg.max_trades_per_day} lệnh/ngày"
        return True, ""

    def on_entry(self, now_ms: int) -> None:
        self._roll_day(now_ms)
        self._open_positions += 1
        self._trades_today += 1

    def on_exit(self, now_ms: int, pnl: float) -> None:
        """pnl = log-return net của lệnh vừa đóng."""
        self._roll_day(now_ms)
        self._open_positions = max(0, self._open_positions - 1)
        self._pnl_today += pnl
        if self._pnl_today <= -self.cfg.daily_loss_limit:
            self.killed = True
