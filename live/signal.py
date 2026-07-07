"""Từ feature row của bar vừa đóng ra quyết định vào lệnh.

SignalEngine tách phần model (proba_fn inject được — MLP checkpoint hay
gì khác) khỏi phần quyết định: normalize input GIỐNG HỆT lúc train
(z-score bằng norm_mean/std của checkpoint + clip ±5), rồi nếu model nói
lên/xuống với confidence >= ngưỡng thì phát Signal kèm barrier TP/SL
đúng công thức triple-barrier của model/labels.py:
    width = vol_50 * sqrt(horizon) * width_mult
(vol_50 trong feature row chính là rolling_std(logret_1, 50) mà labels.py
dùng làm width mặc định).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

_CLIP = 5.0  # khớp DatasetConfig.clip lúc train


@dataclass
class SignalConfig:
    conf_threshold: float = 0.45
    horizon: int = 80
    width_mult: float = 1.0


@dataclass
class Signal:
    side: str            # "Buy" | "Sell"
    conf: float
    entry_ref: float     # close của bar phát tín hiệu
    tp_price: float
    sl_price: float
    horizon_bars: int
    t_close: int         # ms, bar phát tín hiệu
    prob: tuple[float, float, float] = (0.0, 0.0, 0.0)


class SignalEngine:
    def __init__(self, proba_fn: Callable[[np.ndarray], np.ndarray],
                 feature_cols: list[str], norm_mean: np.ndarray,
                 norm_std: np.ndarray, cfg: SignalConfig = SignalConfig()):
        self.proba_fn = proba_fn
        self.feature_cols = feature_cols
        self.norm_mean = np.asarray(norm_mean, dtype=np.float64)
        self.norm_std = np.asarray(norm_std, dtype=np.float64)
        self.cfg = cfg

    def decide(self, feat: pd.Series) -> Signal | None:
        x = feat[self.feature_cols].to_numpy(dtype=np.float64)
        z = np.clip((x - self.norm_mean) / self.norm_std, -_CLIP, _CLIP)
        prob = np.asarray(self.proba_fn(z.astype(np.float32)), dtype=np.float64)
        pred = int(prob.argmax())
        conf = float(prob[pred])
        if pred == 1 or conf < self.cfg.conf_threshold:
            return None

        close = float(feat["close"])
        width = float(feat["vol_50"]) * np.sqrt(self.cfg.horizon) * self.cfg.width_mult
        up, dn = close * np.exp(width), close * np.exp(-width)
        side = "Buy" if pred == 2 else "Sell"
        return Signal(
            side=side, conf=conf, entry_ref=close,
            tp_price=up if side == "Buy" else dn,
            sl_price=dn if side == "Buy" else up,
            horizon_bars=self.cfg.horizon, t_close=int(feat["t_close"]),
            prob=tuple(prob.tolist()))


def engine_from_mlp_checkpoint(path: str, conf_threshold: float = 0.45) -> SignalEngine:
    """Load checkpoint kiểu model/run_training.py (model_final.pt)."""
    import torch

    from model.net import DirectionNet

    ck = torch.load(path, map_location="cpu", weights_only=False)
    net = DirectionNet(len(ck["feature_cols"]), hidden=tuple(ck["hidden"]),
                       dropout=ck["dropout"])
    net.load_state_dict(ck["state_dict"])
    net.eval()

    def proba(z: np.ndarray) -> np.ndarray:
        with torch.no_grad():
            logits = net(torch.from_numpy(z[None, :])).numpy()[0]
        e = np.exp(logits - logits.max())
        return e / e.sum()

    lc = ck["label_config"]
    return SignalEngine(
        proba_fn=proba, feature_cols=list(ck["feature_cols"]),
        norm_mean=ck["norm_mean"], norm_std=ck["norm_std"],
        cfg=SignalConfig(conf_threshold=conf_threshold,
                         horizon=lc["horizon"], width_mult=lc["width_mult"]))
