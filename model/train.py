"""Train loop cho DirectionNet: Adam + cross-entropy + early stopping theo val loss.

train_model() là hàm thuần (numpy vào, dict ra) để test được;
CLI ở cuối file gọi nó với features/labels parquet thật.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

from model.net import DirectionNet


@dataclass
class TrainConfig:
    epochs: int = 100
    batch_size: int = 1024
    lr: float = 1e-3
    weight_decay: float = 1e-4
    patience: int = 10          # early stopping theo val loss
    hidden: tuple[int, ...] = (128, 64)
    dropout: float = 0.2
    seed: int = 42
    device: str = ""            # "" = tự chọn cuda nếu có


def train_model(X_train: np.ndarray, y_train: np.ndarray,
                X_val: np.ndarray, y_val: np.ndarray,
                cfg: TrainConfig, log_every: int = 0) -> dict:
    torch.manual_seed(cfg.seed)
    dev = cfg.device or ("cuda" if torch.cuda.is_available() else "cpu")

    net = DirectionNet(X_train.shape[1], hidden=cfg.hidden, dropout=cfg.dropout).to(dev)
    opt = torch.optim.Adam(net.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay)
    loss_fn = nn.CrossEntropyLoss()

    train_dl = DataLoader(
        TensorDataset(torch.from_numpy(X_train), torch.from_numpy(y_train)),
        batch_size=cfg.batch_size, shuffle=True)
    Xv = torch.from_numpy(X_val).to(dev)
    yv = torch.from_numpy(y_val).to(dev)

    best = {"val_loss": float("inf"), "val_acc": 0.0, "state_dict": None, "best_epoch": 0}
    bad = 0
    epoch = 0
    for epoch in range(1, cfg.epochs + 1):
        net.train()
        for xb, yb in train_dl:
            xb, yb = xb.to(dev), yb.to(dev)
            opt.zero_grad()
            loss_fn(net(xb), yb).backward()
            opt.step()

        net.eval()
        with torch.no_grad():
            logits = net(Xv)
            val_loss = float(loss_fn(logits, yv))
            val_acc = float((logits.argmax(1) == yv).float().mean())
        if log_every and epoch % log_every == 0:
            print(f"  epoch {epoch:3d}: val_loss={val_loss:.4f} val_acc={val_acc:.4f}")

        if val_loss < best["val_loss"]:
            best.update(val_loss=val_loss, val_acc=val_acc, best_epoch=epoch,
                        state_dict=copy.deepcopy(
                            {k: v.cpu() for k, v in net.state_dict().items()}))
            bad = 0
        else:
            bad += 1
            if bad >= cfg.patience:
                break

    best["last_epoch"] = epoch
    return best
