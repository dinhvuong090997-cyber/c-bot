"""Tests cho model/sweep.py — build lưới hyperparameter + chạy song song nhiều device.

Không cần GPU thật để test: dùng devices=['cpu','cpu'] để verify logic dispatch
(mỗi trial độc lập, không đụng state của nhau, thu đủ kết quả).
"""
import numpy as np
import pytest

from model.dataset import DatasetConfig, build_dataset
from model.sweep import Trial, build_grid, run_sweep


class TestBuildGrid:
    def test_grid_size_is_cartesian_product(self):
        grid = build_grid(
            horizons=[30, 50], width_mults=[1.0],
            hiddens=[(32,), (64, 32)], dropouts=[0.1, 0.3],
            lrs=[1e-3], weight_decays=[1e-4])
        assert len(grid) == 2 * 1 * 2 * 2 * 1 * 1

    def test_each_trial_has_expected_fields(self):
        grid = build_grid(horizons=[50], width_mults=[1.0], hiddens=[(32,)],
                          dropouts=[0.2], lrs=[1e-3], weight_decays=[1e-4])
        t = grid[0]
        assert isinstance(t, Trial)
        assert t.horizon == 50 and t.width_mult == 1.0
        assert t.hidden == (32,) and t.dropout == 0.2


def make_dataset(n=800, n_feat=4, seed=0):
    rng = np.random.default_rng(seed)
    import pandas as pd
    t = np.arange(n, dtype=np.int64) * 60_000
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.001, n)))
    feats = pd.DataFrame({"t_close": t, "close": close})
    for k in range(n_feat):
        feats[f"f{k}"] = rng.normal(0, 1, n)
    from model.labels import LabelConfig, triple_barrier
    bars = pd.DataFrame({"t_close": t, "close": close, "high": close, "low": close})
    labels = triple_barrier(bars, LabelConfig(horizon=20, width_mult=1.0))
    return build_dataset(feats, labels, DatasetConfig(purge=20, feature_cols=[f"f{k}" for k in range(n_feat)]))


class TestRunSweep:
    def test_returns_one_row_per_trial(self):
        ds = make_dataset()
        datasets = {(20, 1.0): ds}
        grid = build_grid(horizons=[20], width_mults=[1.0], hiddens=[(8,), (16, 8)],
                          dropouts=[0.1], lrs=[1e-3], weight_decays=[1e-4])
        results = run_sweep(datasets, grid, devices=["cpu", "cpu"],
                           train_overrides={"epochs": 3, "patience": 3})
        assert len(results) == len(grid)
        for col in ("horizon", "width_mult", "hidden", "dropout", "val_acc", "test_acc"):
            assert col in results.columns

    def test_all_trials_complete_even_with_more_devices_than_trials(self):
        ds = make_dataset()
        datasets = {(20, 1.0): ds}
        grid = build_grid(horizons=[20], width_mults=[1.0], hiddens=[(8,)],
                          dropouts=[0.1], lrs=[1e-3], weight_decays=[1e-4])
        results = run_sweep(datasets, grid, devices=["cpu", "cpu", "cpu"],
                           train_overrides={"epochs": 2, "patience": 2})
        assert len(results) == 1

    def test_raises_on_missing_dataset_key(self):
        ds = make_dataset()
        datasets = {(20, 1.0): ds}
        grid = build_grid(horizons=[999], width_mults=[1.0], hiddens=[(8,)],
                          dropouts=[0.1], lrs=[1e-3], weight_decays=[1e-4])
        with pytest.raises(KeyError):
            run_sweep(datasets, grid, devices=["cpu"], train_overrides={"epochs": 1})
