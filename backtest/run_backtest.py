"""CLI: đánh giá model đã train trên test set với các ngưỡng confidence
khác nhau + phí thật (Sharpe/drawdown/turnover).

Dùng:
    uv run python -m backtest.run_backtest \
        --bars data/cache/backfill/dollar_bars.parquet \
        --features out/features_2y.parquet \
        --model out/train_final/model_final.pt
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd
import torch

from backtest.engine import BacktestConfig, evaluate_thresholds
from model.dataset import DatasetConfig, build_dataset
from model.labels import LabelConfig, triple_barrier
from model.net import DirectionNet


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--bars", required=True)
    p.add_argument("--features", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--fee-round-trip", type=float, default=0.0011,
                    help="Bybit perp taker ~0.055%%/bên x2 (mặc định)")
    a = p.parse_args()

    ckpt = torch.load(a.model, map_location="cpu", weights_only=False)
    lcfg = LabelConfig(**ckpt["label_config"])
    print(f"label_config: {ckpt['label_config']}")

    bars = pd.read_parquet(a.bars)
    feats = pd.read_parquet(a.features)
    labels = triple_barrier(bars, lcfg)
    dcfg = DatasetConfig(purge=lcfg.horizon, feature_cols=ckpt["feature_cols"])
    ds = build_dataset(feats, labels, dcfg)

    # sanity check: stats fit lại từ đúng data/config phải khớp checkpoint,
    # nếu không thì test set đang bị đánh giá bằng chuẩn hoá sai
    if not np.allclose(ds["norm_mean"], ckpt["norm_mean"], rtol=1e-5, atol=1e-8):
        raise RuntimeError(
            "norm_mean lệch với checkpoint — bars/features không khớp lúc train")

    net = DirectionNet(len(ckpt["feature_cols"]), hidden=tuple(ckpt["hidden"]),
                       dropout=ckpt["dropout"])
    net.load_state_dict(ckpt["state_dict"])
    net.eval()

    with torch.no_grad():
        logits = net(torch.from_numpy(ds["X_test"]))
        probs = torch.softmax(logits, dim=1).numpy()
    pred = probs.argmax(axis=1)
    conf = probs.max(axis=1)

    cfg = BacktestConfig(fee_round_trip=a.fee_round_trip)
    df = evaluate_thresholds(pred, conf, ds["ret_test"], ds["t_test"], cfg)
    pd.set_option("display.width", 160)
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
