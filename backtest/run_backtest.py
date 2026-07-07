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

from backtest.engine import BacktestConfig, evaluate_maker, evaluate_thresholds
from backtest.fills import FillConfig, simulate_trades
from model.dataset import DatasetConfig, build_dataset
from model.labels import LabelConfig, triple_barrier
from model.net import DirectionNet


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--bars", required=True)
    p.add_argument("--features", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--mode", choices=("maker", "taker"), default="maker",
                    help="maker = mô phỏng limit fill trên OHLC; taker = v1")
    p.add_argument("--entry-wait-bars", type=int, default=3)
    p.add_argument("--fee-round-trip", type=float, default=0.0011,
                    help="chỉ dùng cho --mode taker (0.055%%/bên x2)")
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
    pd.set_option("display.width", 200)

    if a.mode == "taker":
        df = evaluate_thresholds(pred, conf, ds["ret_test"], ds["t_test"], cfg)
        print(df.to_string(index=False))
        return

    # maker: map event test -> bar index rồi mô phỏng limit fill trên OHLC.
    # searchsorted thay vì index lookup: t_close có thể trùng giữa các bar
    # liên tiếp (khối lượng lớn), lấy bar đầu tiên khớp timestamp.
    bars = bars.sort_values("t_close", ignore_index=True)
    bars_t = bars["t_close"].to_numpy()
    directional = pred != 1
    bar_idx = np.searchsorted(bars_t, ds["t_test"][directional])
    assert (bars_t[bar_idx] == ds["t_test"][directional]).all()
    signals = pd.DataFrame({
        "bar_idx": bar_idx,
        "direction": np.where(pred[directional] == 2, 1, -1),
        "confidence": conf[directional],
    })
    fcfg = FillConfig(entry_wait_bars=a.entry_wait_bars)
    trades = simulate_trades(bars, signals, lcfg, fcfg)
    df = evaluate_maker(trades, cfg)
    if len(trades) and (fill_rate := trades["filled"].mean()) < 0.20:
        print(f"CẢNH BÁO: fill_rate tổng = {fill_rate:.1%} < 20% — nghi logic sai")
    print(f"mode=maker  entry_wait_bars={a.entry_wait_bars}  "
          f"maker={fcfg.maker_fee:.2%} taker={fcfg.taker_fee:.3%}")
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
