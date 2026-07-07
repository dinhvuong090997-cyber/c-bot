"""Thí nghiệm cải thiện model: chấm bằng PnL thay vì accuracy.

So 3 biến thể trên cùng dataset (data 2 năm local):
  A. MLP baseline (config hiện tại)
  B. MLP + class weights "balanced"
  C. LightGBM multiclass

Metric chính: PnL per trade trên tập test — long khi model nói lên, short khi
nói xuống, bỏ qua khi nói ngang; có quét ngưỡng confidence và trừ phí.

Dùng:
    python -m tools.exp_improve --bars data/cache/backfill/dollar_bars.parquet \
        --features out/features_2y.parquet
"""
from __future__ import annotations

import argparse

import lightgbm as lgb
import numpy as np
import pandas as pd
import torch

from model.dataset import DatasetConfig, build_dataset
from model.labels import LabelConfig, triple_barrier
from model.net import DirectionNet
from model.train import TrainConfig, train_model

# phí taker Bybit ~0.055%/chiều -> vòng vào+ra ~0.11% (đơn vị log-ret xấp xỉ)
FEE_ROUNDTRIP = 0.0011
THRESHOLDS = (0.0, 0.40, 0.45, 0.50)


def pnl_report(name: str, prob: np.ndarray, ret: np.ndarray) -> None:
    """prob: (n,3) xác suất [xuống, ngang, lên]; ret: log-ret entry -> t_end."""
    pred = prob.argmax(1)
    conf = prob.max(1)
    pos = np.where(pred == 2, 1.0, np.where(pred == 0, -1.0, 0.0))
    print(f"  {name}: pred dist [xuống, ngang, lên] = {np.bincount(pred, minlength=3).tolist()}")
    print(f"    {'thr':>5} {'trades':>7} {'hit%':>6} {'edge/trade':>11} {'net(phí)':>10} {'t-stat':>7}")
    for thr in THRESHOLDS:
        m = (pos != 0) & (conf >= thr) & np.isfinite(ret)
        n = int(m.sum())
        if n == 0:
            print(f"    {thr:>5.2f} {0:>7} {'—':>6} {'—':>11} {'—':>10} {'—':>7}")
            continue
        pnl = pos[m] * ret[m]
        edge = pnl.mean()
        tstat = edge / (pnl.std() / np.sqrt(n)) if n > 1 else float("nan")
        print(f"    {thr:>5.2f} {n:>7} {100 * (pnl > 0).mean():>5.1f}% "
              f"{edge:>+11.5f} {edge - FEE_ROUNDTRIP:>+10.5f} {tstat:>7.2f}")


def softmax_np(logits: np.ndarray) -> np.ndarray:
    e = np.exp(logits - logits.max(1, keepdims=True))
    return e / e.sum(1, keepdims=True)


def mlp_probs(state_dict: dict, hidden: tuple[int, ...], dropout: float,
              X: np.ndarray) -> np.ndarray:
    net = DirectionNet(X.shape[1], hidden=hidden, dropout=dropout)
    net.load_state_dict(state_dict)
    net.eval()
    with torch.no_grad():
        return softmax_np(net(torch.from_numpy(X)).numpy())


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--bars", required=True)
    p.add_argument("--features", required=True)
    p.add_argument("--horizon", type=int, default=50)
    p.add_argument("--width-mult", type=float, default=1.0)
    p.add_argument("--epochs", type=int, default=60)
    a = p.parse_args()

    print("1) labels + dataset...")
    bars = pd.read_parquet(a.bars)
    labels = triple_barrier(bars, LabelConfig(horizon=a.horizon, width_mult=a.width_mult))
    feats = pd.read_parquet(a.features)
    ds = build_dataset(feats, labels, DatasetConfig(purge=a.horizon))
    for part in ("train", "val", "test"):
        print(f"   {part}: {len(ds[f'y_{part}']):,}")

    results: dict[str, dict[str, np.ndarray]] = {}

    print("2) A. MLP baseline...")
    cfg = TrainConfig(epochs=a.epochs)
    r = train_model(ds["X_train"], ds["y_train"], ds["X_val"], ds["y_val"], cfg, log_every=5)
    print(f"   best epoch {r['best_epoch']}: val_loss={r['val_loss']:.4f} val_acc={r['val_acc']:.4f}")
    results["A. MLP baseline"] = {
        part: mlp_probs(r["state_dict"], cfg.hidden, cfg.dropout, ds[f"X_{part}"])
        for part in ("val", "test")}

    print("3) B. MLP + class weights...")
    cfg_w = TrainConfig(epochs=a.epochs, class_weight="balanced")
    r = train_model(ds["X_train"], ds["y_train"], ds["X_val"], ds["y_val"], cfg_w, log_every=5)
    print(f"   best epoch {r['best_epoch']}: val_loss={r['val_loss']:.4f} val_acc={r['val_acc']:.4f}")
    results["B. MLP balanced"] = {
        part: mlp_probs(r["state_dict"], cfg_w.hidden, cfg_w.dropout, ds[f"X_{part}"])
        for part in ("val", "test")}

    print("4) C. LightGBM...")
    booster = lgb.train(
        {"objective": "multiclass", "num_class": 3, "metric": "multi_logloss",
         "learning_rate": 0.05, "num_leaves": 63, "feature_fraction": 0.8,
         "bagging_fraction": 0.8, "bagging_freq": 1, "min_data_in_leaf": 200,
         "verbosity": -1, "seed": 42},
        lgb.Dataset(ds["X_train"], label=ds["y_train"]),
        num_boost_round=2000,
        valid_sets=[lgb.Dataset(ds["X_val"], label=ds["y_val"])],
        callbacks=[lgb.early_stopping(50, verbose=False), lgb.log_evaluation(100)])
    print(f"   best iteration: {booster.best_iteration}")
    results["C. LightGBM"] = {
        part: booster.predict(ds[f"X_{part}"], num_iteration=booster.best_iteration)
        for part in ("val", "test")}
    imp = sorted(zip(ds["feature_cols"], booster.feature_importance("gain")),
                 key=lambda x: -x[1])
    print("   top features (gain):", [f"{k}={v:.0f}" for k, v in imp[:8]])

    for part in ("val", "test"):
        print(f"\n===== PnL trên {part.upper()} (phí round-trip {FEE_ROUNDTRIP:.4f}) =====")
        for name, probs in results.items():
            acc = float((probs[part].argmax(1) == ds[f"y_{part}"]).mean())
            print(f"  [{name}] acc={acc:.4f}")
            pnl_report(name, probs[part], ds[f"ret_{part}"])


if __name__ == "__main__":
    main()
