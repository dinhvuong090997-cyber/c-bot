"""CLI stage 3: bars + features -> labels -> train DirectionNet -> checkpoint.

Dùng:
    python -m model.run_training --bars data/cache/backfill/dollar_bars.parquet \
        --features out/features_2y.parquet --out out/model_v1.pt
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd
import torch

from model.dataset import DatasetConfig, build_dataset
from model.labels import LabelConfig, triple_barrier
from model.net import DirectionNet
from model.train import TrainConfig, train_model


def evaluate(net: DirectionNet, X: np.ndarray, y: np.ndarray,
             ret: np.ndarray, dev: str) -> dict:
    net.eval()
    with torch.no_grad():
        logits = net(torch.from_numpy(X).to(dev))
        pred = logits.argmax(1).cpu().numpy()
    acc = float((pred == y).mean())
    cm = np.zeros((3, 3), dtype=int)  # hàng = thật, cột = dự đoán
    for t, p in zip(y, pred):
        cm[t, p] += 1
    # kiểm tra "edge": return thực tế trung bình của event khi model nói lên/xuống
    ret_when_up = float(np.nanmean(ret[pred == 2])) if (pred == 2).any() else float("nan")
    ret_when_dn = float(np.nanmean(ret[pred == 0])) if (pred == 0).any() else float("nan")
    return {"acc": acc, "confusion": cm.tolist(),
            "ret_when_pred_up": ret_when_up, "ret_when_pred_down": ret_when_dn,
            "pred_dist": np.bincount(pred, minlength=3).tolist()}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--bars", required=True)
    p.add_argument("--features", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--horizon", type=int, default=50)
    p.add_argument("--epochs", type=int, default=100)
    a = p.parse_args()

    print("1) labels (triple-barrier)...")
    bars = pd.read_parquet(a.bars)
    lcfg = LabelConfig(horizon=a.horizon, width_mult=1.0)
    labels = triple_barrier(bars, lcfg)
    ok = labels[labels.complete & ~labels.ambiguous]
    dist = ok.label.value_counts(normalize=True).sort_index()
    print(f"   {len(ok):,} events | -1={dist.get(-1,0):.1%} 0={dist.get(0,0):.1%} +1={dist.get(1,0):.1%}")

    print("2) dataset (join + purged split + normalize)...")
    feats = pd.read_parquet(a.features)
    dcfg = DatasetConfig(purge=a.horizon)
    ds = build_dataset(feats, labels, dcfg)
    for part in ("train", "val", "test"):
        t0 = pd.Timestamp(int(ds[f"t_{part}"][0]), unit="ms", tz="UTC")
        t1 = pd.Timestamp(int(ds[f"t_{part}"][-1]), unit="ms", tz="UTC")
        print(f"   {part}: {len(ds[f'y_{part}']):,} | {t0:%Y-%m-%d} -> {t1:%Y-%m-%d}")

    print("3) train...")
    tcfg = TrainConfig(epochs=a.epochs)
    result = train_model(ds["X_train"], ds["y_train"], ds["X_val"], ds["y_val"],
                         tcfg, log_every=1)
    print(f"   best epoch {result['best_epoch']}: val_loss={result['val_loss']:.4f} "
          f"val_acc={result['val_acc']:.4f}")

    print("4) đánh giá trên test (out-of-sample)...")
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    net = DirectionNet(ds["X_train"].shape[1], hidden=tcfg.hidden, dropout=tcfg.dropout).to(dev)
    net.load_state_dict(result["state_dict"])
    m = evaluate(net, ds["X_test"], ds["y_test"], ds["ret_test"], dev)
    print(f"   test acc: {m['acc']:.4f} (baseline đoán bừa ~0.33, đoán toàn class lớn nhất ~0.37)")
    print(f"   pred dist [xuống, ngang, lên]: {m['pred_dist']}")
    print(f"   confusion (hàng=thật, cột=dự đoán):")
    for row in m["confusion"]:
        print(f"     {row}")
    print(f"   ret thực khi model nói LÊN:   {m['ret_when_pred_up']:+.5f}")
    print(f"   ret thực khi model nói XUỐNG: {m['ret_when_pred_down']:+.5f}")

    torch.save({
        "state_dict": result["state_dict"],
        "hidden": list(tcfg.hidden),
        "dropout": tcfg.dropout,
        "feature_cols": ds["feature_cols"],
        "norm_mean": ds["norm_mean"], "norm_std": ds["norm_std"],
        "label_config": vars(lcfg), "metrics": m,
    }, a.out)
    print(f"-> {a.out}")


if __name__ == "__main__":
    main()
