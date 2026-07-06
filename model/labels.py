"""Triple-barrier labeling (AFML ch.3).

Mỗi bar i là 1 event: entry = close[i].
  barrier trên  = close[i] * exp(+width[i])
  barrier dưới  = close[i] * exp(-width[i])
  vertical      = bar i + horizon
width mặc định = rolling_std(logret, vol_window) * sqrt(horizon) * width_mult
(vol theo bar nhân sqrt(horizon) ≈ vol của cả quãng event — barrier cân với horizon).

Label: +1 chạm trên trước, -1 chạm dưới trước, 0 hết giờ.
Chạm xét bằng high/low các bar i+1..i+horizon. Nếu 1 bar chạm CẢ 2 barrier
thì không biết cái nào trước (không có dữ liệu trong bar) -> label 0 + cờ
`ambiguous` để downstream tự quyết lọc hay giữ.

Event thiếu đường chạy (gần cuối data / width NaN) -> `complete=False`,
label giữ 0 làm placeholder — KHÔNG được dùng để train.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class LabelConfig:
    horizon: int = 50        # vertical barrier, tính bằng số bars
    width_mult: float = 1.0  # hệ số nhân width
    vol_window: int = 50     # cửa sổ vol khi width không truyền vào


def triple_barrier(bars: pd.DataFrame, cfg: LabelConfig,
                   width: np.ndarray | None = None) -> pd.DataFrame:
    """bars cần close/high/low/t_close. Trả về DataFrame cùng index:
    t_close, label(int8), t_end_idx, t_end, ret, ambiguous, complete."""
    c = bars["close"].to_numpy(dtype=np.float64)
    h = bars["high"].to_numpy(dtype=np.float64)
    l = bars["low"].to_numpy(dtype=np.float64)
    n = len(c)
    idx = np.arange(n)

    if width is None:
        logret = np.diff(np.log(c), prepend=np.nan)
        vol = pd.Series(logret).rolling(cfg.vol_window).std().to_numpy()
        width = vol * np.sqrt(cfg.horizon) * cfg.width_mult
    else:
        width = np.asarray(width, dtype=np.float64) * cfg.width_mult

    up = c * np.exp(width)
    dn = c * np.exp(-width)

    complete = np.isfinite(width) & (idx + cfg.horizon <= n - 1)
    label = np.zeros(n, dtype=np.int8)
    ambiguous = np.zeros(n, dtype=bool)
    resolved = np.zeros(n, dtype=bool)
    t_end_idx = np.minimum(idx + cfg.horizon, n - 1)

    # quét theo offset: mỗi vòng xử lý "bar thứ off sau entry" cho MỌI event
    # cùng lúc (O(horizon) vòng numpy thay vì O(n*horizon) python)
    for off in range(1, cfg.horizon + 1):
        j = np.minimum(idx + off, n - 1)
        active = complete & ~resolved & (idx + off <= n - 1)
        up_hit = active & (h[j] >= up)
        dn_hit = active & (l[j] <= dn)
        both = up_hit & dn_hit
        label[up_hit & ~both] = 1
        label[dn_hit & ~both] = -1
        ambiguous[both] = True  # label giữ 0
        hit = up_hit | dn_hit
        t_end_idx[hit] = idx[hit] + off
        resolved |= hit

    ret = np.log(c[t_end_idx] / c)
    ret[~complete] = np.nan

    return pd.DataFrame({
        "t_close": bars["t_close"].to_numpy(),
        "label": label,
        "t_end_idx": t_end_idx,
        "t_end": bars["t_close"].to_numpy()[t_end_idx],
        "ret": ret,
        "ambiguous": ambiguous,
        "complete": complete,
    }, index=bars.index)
