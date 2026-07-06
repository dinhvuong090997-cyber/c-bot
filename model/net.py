"""MLP baseline dự đoán hướng 3 class (xuống/đi ngang/lên).

Giữ đơn giản có chủ đích — baseline phải chạy được trước khi nghĩ tới
kiến trúc phức tạp (sequence model để v2).
"""
from __future__ import annotations

import torch
import torch.nn as nn


class DirectionNet(nn.Module):
    def __init__(self, n_features: int, hidden: tuple[int, ...] = (128, 64),
                 dropout: float = 0.2, n_classes: int = 3):
        super().__init__()
        layers: list[nn.Module] = []
        prev = n_features
        for h in hidden:
            layers += [nn.Linear(prev, h), nn.LayerNorm(h), nn.ReLU(), nn.Dropout(dropout)]
            prev = h
        layers.append(nn.Linear(prev, n_classes))
        self.net = nn.Sequential(*layers)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)
