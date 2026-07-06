"""Join features + labels, split theo thời gian có purge, chuẩn hóa.

- Split: train/val/test theo THỜI GIAN (không shuffle — time series).
- Purge: event nào có t_end vượt qua ranh giới split thì bỏ — label của nó
  nhìn thấy giá thuộc split sau (leakage).
- Chuẩn hóa: z-score với mean/std fit CHỈ trên train, clip ±clip.
- Label -1/0/+1 -> class 0/1/2 (CrossEntropyLoss).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class DatasetConfig:
    train_frac: float = 0.7
    val_frac: float = 0.15
    purge: int = 50            # số bar đệm tại ranh giới (>= horizon của label)
    clip: float = 5.0
    feature_cols: list[str] = field(default_factory=list)  # rỗng = tự suy ra


def build_dataset(features: pd.DataFrame, labels: pd.DataFrame,
                  cfg: DatasetConfig) -> dict:
    """Trả về dict: X_/y_/t_ cho train/val/test (numpy), norm_mean/std, feature_cols."""
    lab_cols = ["t_close", "label", "t_end", "ret"]
    df = features.merge(
        labels.loc[labels["complete"] & ~labels["ambiguous"], lab_cols],
        on="t_close", how="inner").sort_values("t_close", ignore_index=True)

    feat_cols = cfg.feature_cols or [
        c for c in features.columns if c not in ("t_close", "close")]

    n = len(df)
    a = int(n * cfg.train_frac)
    b = int(n * (cfg.train_frac + cfg.val_frac))
    t = df["t_close"].to_numpy()
    t_end = df["t_end"].to_numpy()

    idx = np.arange(n)
    parts = {
        "train": (idx < a) & (t_end < t[a]) if a < n else idx < a,
        "val": (idx >= a) & (idx < b) & (t_end < t[b]) if b < n else (idx >= a) & (idx < b),
        "test": idx >= b,
    }

    tr = df.loc[parts["train"], feat_cols].to_numpy(dtype=np.float64)
    mean, std = tr.mean(axis=0), tr.std(axis=0)
    std = np.where(std < 1e-12, 1.0, std)

    out = {"feature_cols": feat_cols, "norm_mean": mean, "norm_std": std}
    for name, mask in parts.items():
        X = df.loc[mask, feat_cols].to_numpy(dtype=np.float64)
        X = np.clip((X - mean) / std, -cfg.clip, cfg.clip)
        out[f"X_{name}"] = X.astype(np.float32)
        out[f"y_{name}"] = (df.loc[mask, "label"].to_numpy() + 1).astype(np.int64)
        out[f"t_{name}"] = df.loc[mask, "t_close"].to_numpy()
        out[f"ret_{name}"] = df.loc[mask, "ret"].to_numpy(dtype=np.float64)
    return out
