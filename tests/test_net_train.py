"""Tests cho model/net.py + model/train.py."""
import numpy as np
import pytest
import torch

from model.net import DirectionNet
from model.train import TrainConfig, train_model


class TestNet:
    def test_forward_shape(self):
        net = DirectionNet(n_features=29)
        x = torch.randn(64, 29)
        out = net(x)
        assert out.shape == (64, 3)
        assert torch.isfinite(out).all()

    def test_dropout_off_in_eval(self):
        net = DirectionNet(n_features=8)
        net.eval()
        x = torch.randn(16, 8)
        assert torch.equal(net(x), net(x))  # eval phải deterministic


def make_learnable(n=3000, n_feat=6, seed=0):
    """Data có pattern tuyến tính rõ để test loop học được."""
    rng = np.random.default_rng(seed)
    X = rng.normal(0, 1, (n, n_feat)).astype(np.float32)
    score = X[:, 0] - X[:, 1] + 0.5 * X[:, 2]
    y = np.digitize(score, [-0.7, 0.7]).astype(np.int64)  # 0/1/2
    return X, y


class TestTrainLoop:
    def test_learns_separable_pattern(self):
        X, y = make_learnable()
        Xv, yv = make_learnable(n=800, seed=1)
        cfg = TrainConfig(epochs=30, batch_size=256, lr=1e-3, patience=10, hidden=(32, 16))
        result = train_model(X, y, Xv, yv, cfg)
        assert result["val_acc"] > 0.85  # baseline ngẫu nhiên ~0.33

    def test_early_stopping_returns_best_not_last(self):
        X, y = make_learnable(n=1000)
        Xv, yv = make_learnable(n=400, seed=2)
        cfg = TrainConfig(epochs=50, batch_size=256, lr=1e-3, patience=3, hidden=(16,))
        result = train_model(X, y, Xv, yv, cfg)
        assert result["best_epoch"] <= result["last_epoch"]
        assert "state_dict" in result

    def test_checkpoint_roundtrip_same_predictions(self, tmp_path):
        X, y = make_learnable(n=1000)
        Xv, yv = make_learnable(n=400, seed=3)
        cfg = TrainConfig(epochs=5, batch_size=256, hidden=(16,))
        result = train_model(X, y, Xv, yv, cfg)

        net = DirectionNet(n_features=X.shape[1], hidden=cfg.hidden)
        net.load_state_dict(result["state_dict"])
        net.eval()
        p1 = net(torch.from_numpy(Xv)).argmax(1)

        path = tmp_path / "ckpt.pt"
        torch.save({"state_dict": result["state_dict"], "hidden": cfg.hidden}, path)
        ck = torch.load(path, weights_only=True)
        net2 = DirectionNet(n_features=X.shape[1], hidden=tuple(ck["hidden"]))
        net2.load_state_dict(ck["state_dict"])
        net2.eval()
        p2 = net2(torch.from_numpy(Xv)).argmax(1)
        assert torch.equal(p1, p2)
