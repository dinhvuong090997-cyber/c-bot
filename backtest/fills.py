"""Mô phỏng khớp lệnh maker mức OHLC bar (spec 2026-07-07).

Entry: limit tại close[i] của bar tín hiệu, chờ tối đa entry_wait_bars bar.
Long khớp nếu low chạm limit, short nếu high chạm. Không khớp -> bỏ tín hiệu.

Khác với label triple-barrier: barrier neo quanh GIÁ ENTRY THỰC (width vẫn
lấy tại bar tín hiệu như label), vertical tính từ bar khớp. Vì entry có thể
khớp trễ, return của label không dùng lại được — phải quét lại OHLC.

Quy tắc conservative:
- TP là limit maker: chỉ khớp khi giá VƯỢT QUA barrier (>, không phải >=)
  — chạm đúng giá không đảm bảo đến lượt mình trong queue.
- SL là stop taker: chạm là dính, thoát tại giá barrier.
- 1 bar dính cả TP lẫn SL -> tính SL.
- Bar khớp entry chỉ xét SL (giá vừa xuyên limit có thể xuyên luôn stop),
  không cho TP trong bar đó.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from model.labels import LabelConfig


@dataclass
class FillConfig:
    entry_wait_bars: int = 3      # số bar tối đa chờ limit entry khớp
    maker_fee: float = 0.0002     # Bybit perp maker 0.02%
    taker_fee: float = 0.00055    # Bybit perp taker 0.055%


def simulate_trades(bars: pd.DataFrame, signals: pd.DataFrame,
                    lcfg: LabelConfig, fcfg: FillConfig,
                    width: np.ndarray | None = None) -> pd.DataFrame:
    """signals cần bar_idx/direction(±1)/confidence. Trả về 1 dòng/tín hiệu:
    filled, complete, fill_idx, entry_price, exit_idx, exit_type
    (tp/sl/vertical), exit_price, gross_ret, fee, net_ret, t_entry, t_exit
    (+ bar_idx/direction/confidence gốc). Trade dùng được cho thống kê =
    filled & complete."""
    c = bars["close"].to_numpy(dtype=np.float64)
    h = bars["high"].to_numpy(dtype=np.float64)
    l = bars["low"].to_numpy(dtype=np.float64)
    t = bars["t_close"].to_numpy()
    n = len(c)

    if width is None:
        logret = np.diff(np.log(c), prepend=np.nan)
        vol = pd.Series(logret).rolling(lcfg.vol_window).std().to_numpy()
        width = vol * np.sqrt(lcfg.horizon) * lcfg.width_mult
    else:
        width = np.asarray(width, dtype=np.float64) * lcfg.width_mult

    rows = []
    for bar_idx, direction, conf in zip(
            signals["bar_idx"].to_numpy(), signals["direction"].to_numpy(),
            signals["confidence"].to_numpy()):
        i = int(bar_idx)
        row = {"bar_idx": i, "direction": int(direction), "confidence": conf,
               "filled": False, "complete": True, "fill_idx": -1,
               "entry_price": np.nan, "exit_idx": -1, "exit_type": None,
               "exit_price": np.nan, "gross_ret": np.nan, "fee": np.nan,
               "net_ret": np.nan, "t_entry": -1, "t_exit": -1}
        w = width[i]
        if not np.isfinite(w):
            row["complete"] = False
            rows.append(row)
            continue

        # --- entry: limit tại close[i], quét i+1..i+k ---
        limit = c[i]
        lo_win, hi_win = i + 1, min(i + fcfg.entry_wait_bars, n - 1)
        f = -1
        for j in range(lo_win, hi_win + 1):
            touched = l[j] <= limit if direction > 0 else h[j] >= limit
            if touched:
                f = j
                break
        if f < 0:
            rows.append(row)  # missed — không khớp trong k bar
            continue

        entry = limit
        if direction > 0:
            tp, sl = entry * np.exp(w), entry * np.exp(-w)
        else:
            tp, sl = entry * np.exp(-w), entry * np.exp(w)

        row.update(filled=True, fill_idx=f, entry_price=entry, t_entry=t[f])

        if f + lcfg.horizon > n - 1:
            row["complete"] = False
            rows.append(row)
            continue

        # --- exit: quét f..f+horizon (bar f chỉ xét SL) ---
        exit_idx, exit_type = f + lcfg.horizon, "vertical"
        exit_price = c[f + lcfg.horizon]
        for j in range(f, f + lcfg.horizon + 1):
            sl_hit = (l[j] <= sl) if direction > 0 else (h[j] >= sl)
            tp_hit = j > f and ((h[j] > tp) if direction > 0 else (l[j] < tp))
            if sl_hit:  # SL thắng khi cùng bar với TP
                exit_idx, exit_type, exit_price = j, "sl", sl
                break
            if tp_hit:
                exit_idx, exit_type, exit_price = j, "tp", tp
                break

        gross = direction * np.log(exit_price / entry)
        fee = fcfg.maker_fee + (fcfg.maker_fee if exit_type == "tp"
                                else fcfg.taker_fee)
        row.update(exit_idx=exit_idx, exit_type=exit_type,
                   exit_price=exit_price, gross_ret=gross, fee=fee,
                   net_ret=gross - fee, t_exit=t[exit_idx])
        rows.append(row)

    return pd.DataFrame(rows)
