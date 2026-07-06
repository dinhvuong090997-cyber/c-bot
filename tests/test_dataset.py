"""Tests cho model/dataset.py — join features+labels, purged time split, normalize.

Hai điểm sống còn:
1. Split theo THỜI GIAN (không shuffle) + purge: event của train có cửa sổ
   thò sang val thì phải bỏ (label nhìn thấy giá của val = leakage).
2. Chuẩn hóa fit CHỈ trên train — dùng thống kê của val/test là leakage.
"""
import numpy as np
import pandas as pd
import pytest

from model.dataset import DatasetConfig, build_dataset


def make_inputs(n=1000, n_feat=3, seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(n, dtype=np.int64) * 60_000
    feats = pd.DataFrame({"t_close": t, "close": 100.0 + rng.normal(0, 1, n)})
    for k in range(n_feat):
        feats[f"f{k}"] = rng.normal(k, 1 + k, n)  # mean/std khác nhau theo cột
    horizon = 20
    labels = pd.DataFrame({
        "t_close": t,
        "label": rng.choice([-1, 0, 1], n).astype(np.int8),
        "t_end_idx": np.minimum(np.arange(n) + horizon, n - 1),
        "t_end": t[np.minimum(np.arange(n) + horizon, n - 1)],
        "ret": rng.normal(0, 0.01, n),
        "ambiguous": np.zeros(n, dtype=bool),
        "complete": np.arange(n) + horizon <= n - 1,
    })
    return feats, labels


CFG = DatasetConfig(train_frac=0.7, val_frac=0.15, feature_cols=["f0", "f1", "f2"])


class TestJoinAndFilter:
    def test_output_shapes_and_label_mapping(self):
        feats, labels = make_inputs()
        ds = build_dataset(feats, labels, CFG)
        assert ds["X_train"].shape[1] == 3
        # label -1,0,+1 -> class 0,1,2
        for part in ("train", "val", "test"):
            assert set(np.unique(ds[f"y_{part}"])) <= {0, 1, 2}

    def test_incomplete_and_ambiguous_dropped(self):
        feats, labels = make_inputs()
        labels.loc[10, "ambiguous"] = True
        ds = build_dataset(feats, labels, CFG)
        n_events = int(labels["complete"].sum()) - 1  # trừ event ambiguous
        total = sum(len(ds[f"y_{p}"]) for p in ("train", "val", "test"))
        # tổng sample = số event hợp lệ trừ đi các event bị purge ở biên
        assert total <= n_events
        assert total >= n_events - 3 * CFG.purge

    def test_inner_join_on_t_close(self):
        feats, labels = make_inputs()
        feats2 = feats.iloc[100:].reset_index(drop=True)  # thiếu 100 hàng đầu
        ds = build_dataset(feats2, labels, CFG)
        ds_full = build_dataset(feats, labels, CFG)
        assert len(ds["y_train"]) < len(ds_full["y_train"])


class TestChronologicalPurgedSplit:
    def test_splits_are_chronological_and_disjoint(self):
        feats, labels = make_inputs()
        ds = build_dataset(feats, labels, CFG)
        assert ds["t_train"].max() < ds["t_val"].min()
        assert ds["t_val"].max() < ds["t_test"].min()

    def test_purge_drops_events_spanning_boundary(self):
        feats, labels = make_inputs()
        ds = build_dataset(feats, labels, CFG)
        # event cuối của train phải kết thúc TRƯỚC khi val bắt đầu
        train_mask = labels["t_close"].isin(ds["t_train"])
        assert labels.loc[train_mask, "t_end"].max() < ds["t_val"].min()
        val_mask = labels["t_close"].isin(ds["t_val"])
        assert labels.loc[val_mask, "t_end"].max() < ds["t_test"].min()


class TestNormalization:
    def test_train_normalized_to_zero_mean_unit_std(self):
        feats, labels = make_inputs(n=2000)
        ds = build_dataset(feats, labels, CFG)
        assert np.abs(ds["X_train"].mean(axis=0)).max() < 0.05
        assert np.abs(ds["X_train"].std(axis=0) - 1).max() < 0.05

    def test_stats_fitted_on_train_only(self):
        feats, labels = make_inputs(n=2000)
        # cho phần test lệch hẳn phân phối
        feats.loc[1700:, ["f0", "f1", "f2"]] += 50.0
        ds = build_dataset(feats, labels, CFG)
        # nếu stats fit cả data thì X_train sẽ lệch âm rõ rệt; fit đúng thì ~0
        assert np.abs(ds["X_train"].mean(axis=0)).max() < 0.1
        # còn X_test phải lệch dương to (chuẩn hóa bằng stats của train)
        assert ds["X_test"].mean() > 3

    def test_clipping_bounds(self):
        feats, labels = make_inputs(n=2000)
        feats.loc[1900, "f0"] = 1e9  # outlier khủng trong test
        ds = build_dataset(feats, labels, CFG)
        assert ds["X_test"].max() <= CFG.clip
        assert ds["X_train"].min() >= -CFG.clip

    def test_no_nan_anywhere(self):
        feats, labels = make_inputs()
        ds = build_dataset(feats, labels, CFG)
        for p in ("train", "val", "test"):
            assert np.isfinite(ds[f"X_{p}"]).all()
