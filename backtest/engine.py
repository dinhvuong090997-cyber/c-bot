"""Backtest engine: lọc lệnh theo confidence threshold, trừ phí, tính
Sharpe/drawdown/turnover.

Đơn giản hoá v1: mỗi event triple-barrier được coi là 1 lệnh độc lập cỡ
100% vốn (không tính concurrent bet sizing kiểu AFML) — khớp với cách đo
"edge" đã dùng ở sweep. Return là log-return nên trừ phí trực tiếp (xấp xỉ
tốt cho phí nhỏ).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

MS_PER_DAY = 86_400_000


@dataclass
class BacktestConfig:
    fee_round_trip: float = 0.0011  # Bybit perp taker ~0.055%/bên x2
    conf_thresholds: tuple[float, ...] = field(
        default_factory=lambda: (0.0, 0.35, 0.40, 0.45, 0.50, 0.55))


def select_trades(pred: np.ndarray, prob: np.ndarray, ret: np.ndarray,
                  t_close: np.ndarray, conf_threshold: float) -> dict:
    """Lọc event model tự tin (pred != ngang, prob >= threshold).

    class: 0=xuống, 1=ngang, 2=lên. Trả về gross_ret (return thuận theo
    hướng model đoán, CHƯA trừ phí) và t_close tương ứng, đã sort theo t.
    """
    mask = (pred != 1) & (prob >= conf_threshold)
    order = np.argsort(t_close[mask], kind="stable")
    direction = np.where(pred[mask][order] == 2, 1.0, -1.0)
    gross = direction * ret[mask][order]
    return {"t": t_close[mask][order], "gross_ret": gross, "direction": direction}


def net_returns(gross_ret: np.ndarray, fee_round_trip: float) -> np.ndarray:
    return gross_ret - fee_round_trip


def equity_curve(net_ret: np.ndarray) -> np.ndarray:
    """Vốn ban đầu = 1, cộng dồn log-return -> equity theo từng lệnh."""
    return np.exp(np.cumsum(net_ret))


def max_drawdown(equity: np.ndarray) -> float:
    if len(equity) == 0:
        return float("nan")
    running_max = np.maximum.accumulate(equity)
    dd = (equity - running_max) / running_max
    return float(dd.min())


def sharpe_ratio(net_ret: np.ndarray, t_close: np.ndarray) -> float:
    """Annualize theo THỜI GIAN THỰC giữa lệnh đầu/cuối (dollar bar không
    đều nên không thể annualize theo số lệnh cố định/năm)."""
    if len(net_ret) < 2:
        return float("nan")
    span_days = (t_close[-1] - t_close[0]) / MS_PER_DAY
    if span_days <= 0:
        return float("nan")
    sigma = net_ret.std()
    if sigma == 0:
        return float("nan")
    trades_per_year = len(net_ret) / span_days * 365.0
    return float(net_ret.mean() / sigma * np.sqrt(trades_per_year))


def evaluate_thresholds(pred: np.ndarray, prob: np.ndarray, ret: np.ndarray,
                        t_close: np.ndarray, cfg: BacktestConfig) -> pd.DataFrame:
    rows = []
    for th in cfg.conf_thresholds:
        sel = select_trades(pred, prob, ret, t_close, th)
        net = net_returns(sel["gross_ret"], cfg.fee_round_trip)
        n = len(net)
        if n == 0:
            rows.append({"threshold": th, "n_trades": 0, "win_rate": float("nan"),
                        "mean_net_ret": float("nan"), "sharpe": float("nan"),
                        "max_drawdown": float("nan"), "total_return": float("nan"),
                        "trades_per_day": 0.0})
            continue
        eq = equity_curve(net)
        span_days = (sel["t"][-1] - sel["t"][0]) / MS_PER_DAY
        rows.append({
            "threshold": th,
            "n_trades": n,
            "win_rate": float((net > 0).mean()),
            "mean_net_ret": float(net.mean()),
            "sharpe": sharpe_ratio(net, sel["t"]),
            "max_drawdown": max_drawdown(eq),
            "total_return": float(eq[-1] - 1),
            "trades_per_day": n / span_days if span_days > 0 else float("nan"),
        })
    return pd.DataFrame(rows)
