"""Hyperparameter sweep: build lưới combo, chạy song song trên nhiều GPU.

Model quá nhỏ để 1 trial cần cả GPU (13k-100k tham số) -> tận dụng nhiều
GPU bằng cách chạy NHIỀU TRIAL cùng lúc, mỗi trial ghim vào 1 device,
thay vì chia 1 trial ra nhiều GPU (DataParallel vô nghĩa ở quy mô này).

ThreadPoolExecutor (không phải multiprocessing) vì:
- CUDA context không fork được sau khi đã init -> multiprocessing cần
  spawn + set CUDA_VISIBLE_DEVICES trước khi import torch, phức tạp.
- PyTorch hỗ trợ nhiều CUDA device trong cùng 1 process; mỗi trial chỉ
  đụng đúng device được gán, không share state với trial khác.
- Phần lâu nhất (forward/backward) release GIL trong lúc chạy CUDA kernel
  nên threads vẫn chạy được thật sự song song trên các GPU khác nhau.
"""
from __future__ import annotations

import itertools
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import numpy as np
import pandas as pd
import torch

from model.dataset import DatasetConfig
from model.net import DirectionNet
from model.train import TrainConfig, train_model


@dataclass(frozen=True)
class Trial:
    horizon: int
    width_mult: float
    hidden: tuple[int, ...]
    dropout: float
    lr: float
    weight_decay: float


def build_grid(horizons, width_mults, hiddens, dropouts, lrs, weight_decays) -> list[Trial]:
    return [Trial(*combo) for combo in itertools.product(
        horizons, width_mults, hiddens, dropouts, lrs, weight_decays)]


def _run_one(trial: Trial, ds: dict, device: str, train_overrides: dict) -> dict:
    cfg = TrainConfig(hidden=trial.hidden, dropout=trial.dropout, lr=trial.lr,
                      weight_decay=trial.weight_decay, device=device, **train_overrides)
    result = train_model(ds["X_train"], ds["y_train"], ds["X_val"], ds["y_val"], cfg)

    net = DirectionNet(ds["X_train"].shape[1], hidden=trial.hidden, dropout=trial.dropout).to(device)
    net.load_state_dict(result["state_dict"])
    net.eval()
    with torch.no_grad():
        logits = net(torch.from_numpy(ds["X_test"]).to(device))
        prob = torch.softmax(logits, 1).cpu().numpy()
    pred = prob.argmax(1)
    conf = prob.max(1)
    y_test = ds["y_test"]
    ret_test = ds["ret_test"]
    test_acc = float((pred == y_test).mean())

    row = {
        "horizon": trial.horizon, "width_mult": trial.width_mult,
        "hidden": str(trial.hidden), "dropout": trial.dropout,
        "lr": trial.lr, "weight_decay": trial.weight_decay,
        "best_epoch": result["best_epoch"], "val_loss": result["val_loss"],
        "val_acc": result["val_acc"], "test_acc": test_acc,
        "n_train": len(ds["y_train"]),
    }
    for th in (0.0, 0.40, 0.45, 0.50):
        m_up = (pred == 2) & (conf >= th)
        m_dn = (pred == 0) & (conf >= th)
        n = int(m_up.sum() + m_dn.sum())
        edge = float(np.concatenate([ret_test[m_up], -ret_test[m_dn]]).mean()) if n else float("nan")
        row[f"edge_conf{th:.2f}"] = edge
        row[f"n_conf{th:.2f}"] = n
    return row


def run_sweep(datasets: dict[tuple[int, float], dict], grid: list[Trial],
             devices: list[str], train_overrides: dict | None = None) -> pd.DataFrame:
    """datasets keyed bởi (horizon, width_mult) -> dict từ build_dataset.
    Trial nào không tìm thấy dataset khớp sẽ raise KeyError ngay (fail fast,
    không âm thầm bỏ qua trial)."""
    train_overrides = train_overrides or {}
    for t in grid:
        if (t.horizon, t.width_mult) not in datasets:
            raise KeyError(f"thiếu dataset cho (horizon={t.horizon}, width_mult={t.width_mult})")

    rows = [None] * len(grid)
    with ThreadPoolExecutor(max_workers=len(devices)) as ex:
        futs = {
            ex.submit(_run_one, t, datasets[(t.horizon, t.width_mult)],
                     devices[i % len(devices)], train_overrides): i
            for i, t in enumerate(grid)
        }
        for fut in as_completed(futs):
            rows[futs[fut]] = fut.result()
    return pd.DataFrame(rows)
