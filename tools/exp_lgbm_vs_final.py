"""So LightGBM với model_final (MLP) trên cùng dataset horizon=80.

Cả hai chấm bằng backtest/engine.py trên tập test, 2 kịch bản phí:
taker 0.11% và maker 0.04% round-trip.

Dùng:
    python -m tools.exp_lgbm_vs_final --bars data/cache/backfill/dollar_bars.parquet \
        --features out/features_2y.parquet --ckpt out/train_final/model_final.pt
"""
from __future__ import annotations

import argparse

import lightgbm as lgb
import numpy as np
import pandas as pd
import torch

from backtest.engine import BacktestConfig, evaluate_thresholds
from model.dataset import DatasetConfig, build_dataset
from model.labels import LabelConfig, triple_barrier
from model.net import DirectionNet

FEES = {"taker 0.11%": 0.0011, "maker 0.04%": 0.0004}


def report(name: str, prob: np.ndarray, ret: np.ndarray, t: np.ndarray) -> None:
    pred = prob.argmax(1)
    conf = prob.max(1)
    ok = np.isfinite(ret)
    for fee_name, fee in FEES.items():
        df = evaluate_thresholds(pred[ok], conf[ok], ret[ok], t[ok],
                                 BacktestConfig(fee_round_trip=fee))
        print(f"\n  [{name}] phí {fee_name}:")
        print(df.to_string(index=False, float_format=lambda x: f"{x:.5f}"))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--bars", required=True)
    p.add_argument("--features", required=True)
    p.add_argument("--ckpt", required=True)
    a = p.parse_args()

    ck = torch.load(a.ckpt, map_location="cpu", weights_only=False)
    lcfg = LabelConfig(**ck["label_config"])
    print(f"1) labels horizon={lcfg.horizon} width_mult={lcfg.width_mult} + dataset...")
    bars = pd.read_parquet(a.bars)
    labels = triple_barrier(bars, lcfg)
    feats = pd.read_parquet(a.features)
    ds = build_dataset(feats, labels, DatasetConfig(
        purge=lcfg.horizon, feature_cols=list(ck["feature_cols"])))
    for part in ("train", "val", "test"):
        print(f"   {part}: {len(ds[f'y_{part}']):,}")

    # sanity: chuẩn hóa local phải khớp checkpoint (cùng data, cùng split)
    dm = np.abs(ds["norm_mean"] - ck["norm_mean"]).max()
    dstd = np.abs(ds["norm_std"] - ck["norm_std"]).max()
    print(f"   norm khớp checkpoint: d_mean={dm:.2e} d_std={dstd:.2e}")
    if max(dm, dstd) > 1e-6:
        raise SystemExit("norm không khớp — data local khác data train checkpoint, dừng.")

    print("2) MLP model_final...")
    net = DirectionNet(len(ck["feature_cols"]), hidden=tuple(ck["hidden"]),
                       dropout=ck["dropout"])
    net.load_state_dict(ck["state_dict"])
    net.eval()
    with torch.no_grad():
        logits = net(torch.from_numpy(ds["X_test"])).numpy()
    e = np.exp(logits - logits.max(1, keepdims=True))
    prob_mlp = e / e.sum(1, keepdims=True)

    print("3) LightGBM (train local)...")
    booster = lgb.train(
        {"objective": "multiclass", "num_class": 3, "metric": "multi_logloss",
         "learning_rate": 0.05, "num_leaves": 63, "feature_fraction": 0.8,
         "bagging_fraction": 0.8, "bagging_freq": 1, "min_data_in_leaf": 200,
         "verbosity": -1, "seed": 42},
        lgb.Dataset(ds["X_train"], label=ds["y_train"]),
        num_boost_round=2000,
        valid_sets=[lgb.Dataset(ds["X_val"], label=ds["y_val"])],
        callbacks=[lgb.early_stopping(50, verbose=False)])
    print(f"   best iteration: {booster.best_iteration}")
    prob_lgb = booster.predict(ds["X_test"], num_iteration=booster.best_iteration)
    booster.save_model("out/lgbm_h80.txt")
    imp = sorted(zip(ds["feature_cols"], booster.feature_importance("gain")),
                 key=lambda x: -x[1])
    print("   top features (gain):", [f"{k}={v:.0f}" for k, v in imp[:8]])

    print("\n===== BACKTEST TEST SET =====")
    for name, prob in (("MLP model_final", prob_mlp), ("LightGBM h80", prob_lgb)):
        acc = float((prob.argmax(1) == ds["y_test"]).mean())
        print(f"\n  {name}: test acc={acc:.4f}, pred dist="
              f"{np.bincount(prob.argmax(1), minlength=3).tolist()}")
        report(name, prob, ds["ret_test"], ds["t_test"])


if __name__ == "__main__":
    main()
