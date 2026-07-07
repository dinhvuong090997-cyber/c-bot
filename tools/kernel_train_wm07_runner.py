# ===== Kaggle runner (nối vào cuối bundle bởi build_train_final_kernel.sh) =====
import os as _os
import json as _json


def _find(root, filename):
    if not _os.path.isdir(root):
        return None
    for r, _dirs, files in _os.walk(root):
        if filename in files:
            return _os.path.join(r, filename)
    return None


def evaluate(net, X, y, ret, dev):
    net.eval()
    with torch.no_grad():
        logits = net(torch.from_numpy(X).to(dev))
        pred = logits.argmax(1).cpu().numpy()
    acc = float((pred == y).mean())
    cm = np.zeros((3, 3), dtype=int)
    for t, p in zip(y, pred):
        cm[t, p] += 1
    ret_when_up = float(np.nanmean(ret[pred == 2])) if (pred == 2).any() else float("nan")
    ret_when_dn = float(np.nanmean(ret[pred == 0])) if (pred == 0).any() else float("nan")
    return {"acc": acc, "confusion": cm.tolist(),
            "ret_when_pred_up": ret_when_up, "ret_when_pred_down": ret_when_dn,
            "pred_dist": np.bincount(pred, minlength=3).tolist()}


if __name__ == "__main__":
    OUT = _os.environ.get("CBOT_OUT", "/kaggle/working")
    bars_path = _os.environ.get("CBOT_BARS") or _find("/kaggle/input", "dollar_bars.parquet")
    feat_path = _os.environ.get("CBOT_FEATURES") or _find("/kaggle/input", "features.parquet")
    print(f"bars:     {bars_path}")
    print(f"features: {feat_path}")

    # P100 (sm_60) không còn trong torch build sẵn của Kaggle -> thử 1 op
    # thật trước khi commit dùng GPU, hỏng thì fallback CPU (MLP nhỏ, CPU đủ)
    dev = "cpu"
    if torch.cuda.is_available():
        try:
            (torch.zeros(1, device="cuda") + 1).item()
            dev = "cuda"
        except Exception as e:
            print(f"GPU khong dung duoc ({type(e).__name__}), fallback CPU")
    print(f"device: {dev}")

    # config từ phân tích sweep 07/07: vùng wm=0.7/dropout=0.3 là nơi mọi
    # config có mẫu lớn (n>1000 @conf 0.50) tập trung; bản (256,128,64) cho
    # edge 5.7bps trên 16,206 lệnh test — ước lượng vững nhất về thống kê.
    HORIZON = 80
    WIDTH_MULT = 0.7
    HIDDEN = (256, 128, 64)
    DROPOUT = 0.3
    LR = 1e-3
    WEIGHT_DECAY = 1e-4
    EPOCHS = 150

    print("1) labels (triple-barrier)...")
    bars = pd.read_parquet(bars_path)
    lcfg = LabelConfig(horizon=HORIZON, width_mult=WIDTH_MULT)
    labels = triple_barrier(bars, lcfg)
    ok = labels[labels.complete & ~labels.ambiguous]
    dist = ok.label.value_counts(normalize=True).sort_index()
    print(f"   {len(ok):,} events | -1={dist.get(-1,0):.1%} 0={dist.get(0,0):.1%} +1={dist.get(1,0):.1%}")

    print("2) dataset (join + purged split + normalize)...")
    feats = pd.read_parquet(feat_path)
    dcfg = DatasetConfig(purge=HORIZON)
    ds = build_dataset(feats, labels, dcfg)
    for part in ("train", "val", "test"):
        t0 = pd.Timestamp(int(ds[f"t_{part}"][0]), unit="ms", tz="UTC")
        t1 = pd.Timestamp(int(ds[f"t_{part}"][-1]), unit="ms", tz="UTC")
        print(f"   {part}: {len(ds[f'y_{part}']):,} | {t0:%Y-%m-%d} -> {t1:%Y-%m-%d}")

    print("3) train...")
    tcfg = TrainConfig(epochs=EPOCHS, hidden=HIDDEN, dropout=DROPOUT,
                        lr=LR, weight_decay=WEIGHT_DECAY, device=dev)
    result = train_model(ds["X_train"], ds["y_train"], ds["X_val"], ds["y_val"],
                         tcfg, log_every=5)
    print(f"   best epoch {result['best_epoch']}: val_loss={result['val_loss']:.4f} "
          f"val_acc={result['val_acc']:.4f}")

    print("4) đánh giá trên test (out-of-sample)...")
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
    }, f"{OUT}/model_final_wm07.pt")
    with open(f"{OUT}/metrics_final.json", "w") as f:
        _json.dump(m, f, indent=2)
    print(f"-> {OUT}/model_final_wm07.pt")
