"""Tests cho live/signal.py — từ feature row ra quyết định vào lệnh.

SignalEngine nhận proba_fn (inject được), normalize input đúng như lúc train
(z-score + clip), và tính barrier TP/SL đúng công thức của labels.py:
width = vol_50 * sqrt(horizon) * width_mult.
"""
import numpy as np
import pandas as pd
import pytest
import torch

from live.features_live import ALL_FEATURE_COLS
from live.signal import Signal, SignalConfig, SignalEngine, engine_from_mlp_checkpoint

N_FEAT = len(ALL_FEATURE_COLS)


def make_feat(close=60_000.0, vol_50=0.001):
    s = pd.Series(0.1, index=ALL_FEATURE_COLS, dtype=np.float64)
    s["vol_50"] = vol_50
    s["close"] = close
    s["t_close"] = 1_700_000_000_000
    return s


def make_engine(proba, thr=0.45, horizon=80, width_mult=1.0):
    return SignalEngine(
        proba_fn=lambda X: np.asarray(proba, dtype=np.float64),
        feature_cols=list(ALL_FEATURE_COLS),
        norm_mean=np.zeros(N_FEAT), norm_std=np.ones(N_FEAT),
        cfg=SignalConfig(conf_threshold=thr, horizon=horizon, width_mult=width_mult))


class TestDecide:
    def test_none_when_model_says_flat(self):
        assert make_engine([0.2, 0.6, 0.2]).decide(make_feat()) is None

    def test_none_when_confidence_below_threshold(self):
        assert make_engine([0.40, 0.30, 0.30], thr=0.45).decide(make_feat()) is None

    def test_buy_signal_with_barriers(self):
        feat = make_feat(close=60_000.0, vol_50=0.002)
        sig = make_engine([0.1, 0.3, 0.6], horizon=80).decide(feat)
        assert isinstance(sig, Signal)
        assert sig.side == "Buy"
        assert sig.conf == pytest.approx(0.6)
        width = 0.002 * np.sqrt(80)
        assert sig.tp_price == pytest.approx(60_000 * np.exp(width))
        assert sig.sl_price == pytest.approx(60_000 * np.exp(-width))
        assert sig.horizon_bars == 80

    def test_sell_signal_barriers_flipped(self):
        feat = make_feat(close=60_000.0, vol_50=0.002)
        sig = make_engine([0.6, 0.3, 0.1]).decide(feat)
        assert sig.side == "Sell"
        assert sig.tp_price < 60_000 < sig.sl_price

    def test_width_mult_scales_barriers(self):
        feat = make_feat(close=60_000.0, vol_50=0.002)
        s1 = make_engine([0.1, 0.3, 0.6], width_mult=1.0).decide(feat)
        s2 = make_engine([0.1, 0.3, 0.6], width_mult=2.0).decide(feat)
        assert np.log(s2.tp_price / 60_000) == pytest.approx(
            2 * np.log(s1.tp_price / 60_000))


class TestNormalization:
    def test_features_z_scored_and_clipped_before_proba(self):
        seen = {}

        def spy(X):
            seen["X"] = X.copy()
            return np.array([0.1, 0.8, 0.1])

        mean = np.full(N_FEAT, 2.0)
        std = np.full(N_FEAT, 0.5)
        eng = SignalEngine(proba_fn=spy, feature_cols=list(ALL_FEATURE_COLS),
                           norm_mean=mean, norm_std=std, cfg=SignalConfig())
        feat = make_feat()
        feat[ALL_FEATURE_COLS] = 2.0          # == mean -> z = 0
        feat[ALL_FEATURE_COLS[0]] = 100.0     # z thô = 196 -> clip 5
        eng.decide(feat)
        assert seen["X"][0] == pytest.approx(5.0)
        assert np.allclose(seen["X"][1:], 0.0)
        assert seen["X"].dtype == np.float32


class TestCheckpointLoader:
    def test_loads_and_predicts(self, tmp_path):
        from model.net import DirectionNet
        torch.manual_seed(0)
        net = DirectionNet(N_FEAT, hidden=(8,), dropout=0.0)
        ckpt = {
            "state_dict": net.state_dict(), "hidden": [8], "dropout": 0.0,
            "feature_cols": list(ALL_FEATURE_COLS),
            "norm_mean": np.zeros(N_FEAT), "norm_std": np.ones(N_FEAT),
            "label_config": {"horizon": 80, "width_mult": 1.0, "vol_window": 50},
        }
        path = tmp_path / "m.pt"
        torch.save(ckpt, path)
        eng = engine_from_mlp_checkpoint(str(path), conf_threshold=0.0)
        assert eng.cfg.horizon == 80
        prob = eng.proba_fn(np.zeros(N_FEAT, dtype=np.float32))
        assert prob.shape == (3,)
        assert prob.sum() == pytest.approx(1.0)
        # decide chạy end-to-end không lỗi (kết quả tùy weights)
        eng.decide(make_feat())
