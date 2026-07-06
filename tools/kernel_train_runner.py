# ===== Kaggle runner (nối vào cuối bundle bởi build_train_kernel.sh) =====
import os as _os


def _find(root, filename):
    if not _os.path.isdir(root):
        return None
    for r, _dirs, files in _os.walk(root):
        if filename in files:
            return _os.path.join(r, filename)
    return None


if __name__ == "__main__":
    OUT = _os.environ.get("CBOT_OUT", "/kaggle/working")
    bars_path = _os.environ.get("CBOT_BARS") or _find("/kaggle/input", "dollar_bars.parquet")
    feat_path = _os.environ.get("CBOT_FEATURES") or _find("/kaggle/input", "features.parquet")
    print(f"bars:     {bars_path}")
    print(f"features: {feat_path}")

    n_gpu = torch.cuda.device_count()
    devices = [f"cuda:{i}" for i in range(n_gpu)] if n_gpu else ["cpu"]
    print(f"devices: {devices}")

    bars = pd.read_parquet(bars_path)
    feats = pd.read_parquet(feat_path)

    HORIZONS = [30, 50, 80]
    WIDTH_MULTS = [0.7, 1.0, 1.3]
    print("1) build dataset cho từng (horizon, width_mult)...")
    datasets = {}
    for hz in HORIZONS:
        for wm in WIDTH_MULTS:
            labels = triple_barrier(bars, LabelConfig(horizon=hz, width_mult=wm))
            ds = build_dataset(feats, labels, DatasetConfig(purge=hz))
            datasets[(hz, wm)] = ds
            print(f"   hz={hz} wm={wm}: train={len(ds['y_train']):,} val={len(ds['y_val']):,} test={len(ds['y_test']):,}")

    grid = build_grid(
        horizons=HORIZONS, width_mults=WIDTH_MULTS,
        hiddens=[(64, 32), (128, 64), (256, 128, 64)],
        dropouts=[0.1, 0.3], lrs=[1e-3, 3e-4], weight_decays=[1e-4, 1e-3])
    print(f"2) sweep {len(grid)} trials trên {len(devices)} device(s)...")

    results = run_sweep(datasets, grid, devices=devices,
                        train_overrides={"epochs": 60, "patience": 8})
    results.to_csv(f"{OUT}/sweep_results.csv", index=False)

    # xếp hạng: ưu tiên edge ở ngưỡng conf 0.40 (đủ volume ~vài chục lệnh/ngày),
    # loại trial có quá ít lệnh test (thống kê không đáng tin)
    ranked = results[results["n_conf0.40"] >= 200].sort_values("edge_conf0.40", ascending=False)
    print("3) top 15 theo edge_conf0.40 (đủ n_conf0.40>=200):")
    cols = ["horizon", "width_mult", "hidden", "dropout", "lr", "weight_decay",
           "val_acc", "test_acc", "edge_conf0.40", "n_conf0.40", "edge_conf0.45", "n_conf0.45"]
    print(ranked[cols].head(15).to_string(index=False))
    print(f"-> {OUT}/sweep_results.csv")
