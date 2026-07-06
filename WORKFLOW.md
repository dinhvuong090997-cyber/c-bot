# c-bot workflow

Bot giao dịch BTCUSDT perp (Bybit). Kiến trúc: model NN quyết định hướng,
LLM chỉ lọc/veto (không bao giờ tự quyết). v1 = research + backtest, chưa
có execution/live.

Toàn bộ xử lý nặng chạy trên **Kaggle kernels** (script, có internet),
mỗi kernel ghi output ra **Kaggle dataset** để kernel sau đọc lại — máy
local chỉ giữ code + cache nhỏ để dev/test nhanh.

```
public.bybit.com (raw trades, .csv.gz/ngày)
        │
        ▼
kernel: cbot-dollar-bars          bars/pipeline.py
        │  → dollar_bars.parquet, clean_reports.json, verify_stats.json
        ▼
dataset: cbot-btcusdt-dollar-bars (bars + funding.parquet + oi.parquet)
        │
        ▼
kernel: cbot-features             features/bar_features.py, features/aux_features.py
        │  → features.parquet (29 cột, causal, point-in-time)
        ▼
kernel: cbot-train-sweep          model/labels.py, dataset.py, net.py, train.py, sweep.py
        │  đọc dataset (bars) + kernel_sources (features)
        │  → sweep_results.csv (216 trials, xếp hạng theo edge)
        ▼
(tiếp theo) chọn config tốt nhất → train bản final → backtest/
```

## 1. Dollar bars — kernel `cbot-dollar-bars`

Gom trades tới khi đủ **$10,000,000** giá trị khớp lệnh thì đóng 1 bar
(dollar bars, AFML — phân phối return gần Gaussian hơn time bars).
`TradeCleaner` + `DollarBarBuilder` là class có state, xử lý streaming
từng file/ngày một, chunked == whole bit-exact (test đảm bảo).

```bash
cd ~/projects/c-bot
tools/build_features_kernel.sh   # (nếu sửa code) rebuild bundle trước
uvx kaggle kernels push -p kernel_features  # ví dụ tương tự cho bars nếu cần sửa

# theo dõi
uvx kaggle kernels status vuongnguyen0909/cbot-dollar-bars
```

Đổi số ngày backfill: sửa `N_DAYS` trong
`/tmp/.../scratchpad/cbot-review/kernel/cbot_dollar_bars.py` (kernel bars
hiện chưa dọn vào repo chính thức — TODO nếu cần chạy lại từ đầu).

## 2. Features — kernel `cbot-features`

29 features: 21 từ bar (logret, vol, zret, OFI, tốc độ bar, range/close-pos,
giờ/thứ sin-cos) + 4 funding + 4 OI. Tất cả causal (asof backward, không
lookahead — có test `TestCausality` chống regression).

```bash
tools/build_features_kernel.sh          # gộp source -> kernel_features/cbot_features.py
uvx kaggle kernels push -p kernel_features
uvx kaggle kernels status vuongnguyen0909/cbot-features
uvx kaggle kernels output vuongnguyen0909/cbot-features -p out/
```

**Gotcha quan trọng**: Bybit chặn IP Mỹ của Kaggle nên funding/OI KHÔNG
fetch được trên kernel — phải fetch ở máy local rồi đóng gói kèm bars vào
dataset. Kernel chỉ đọc cache (`funding.parquet`, `oi.parquet` trong
dataset), không gọi API.

## 3. Sau khi backfill xong: `tools/after_backfill.sh`

Script 1 lệnh làm trọn gói khi kernel bars vừa `COMPLETE`:

```bash
tools/after_backfill.sh
```

Các bước bên trong: tải bars → fetch funding/OI local (Bybit v5 public
API, `data/bybit_api.py`) → `kaggle datasets version` (đợi tới khi
`ready` mới đi tiếp — tránh race khiến kernel sau đọc dataset rỗng) →
build + push kernel features.

## 4. Model — `model/`

- `labels.py`: **triple-barrier** (AFML). Barrier trên/dưới = `close *
  exp(±width)`, width mặc định = rolling_vol × √horizon × width_mult;
  vertical barrier = horizon bars. Vectorized, 583k bars label trong ~1.6s.
- `dataset.py`: join features+labels theo `t_close`, split **theo thời
  gian** (train/val/test liên tục, không shuffle) + **purge** (event có
  cửa sổ label thò qua ranh giới split thì bỏ — chống leakage), chuẩn hóa
  z-score fit **chỉ trên train**.
- `net.py`: MLP baseline (`DirectionNet`) — Linear→LayerNorm→ReLU→Dropout
  nhiều tầng, output 3 class (xuống/ngang/lên).
- `train.py`: Adam + CrossEntropy + early stopping theo val loss.
- `sweep.py`: build lưới hyperparameter (horizon × width_mult × hidden ×
  dropout × lr × weight_decay) + chạy **song song trên nhiều GPU**
  (ThreadPoolExecutor, mỗi trial ghim 1 device — model nhỏ nên tận dụng
  GPU bằng cách chạy nhiều trial cùng lúc, không phải chia 1 trial ra
  nhiều GPU).
- `run_training.py`: CLI train 1 lần với 1 config, in confusion matrix +
  "ret thực khi model nói LÊN/XUỐNG" (đo edge, không chỉ accuracy).

```bash
# train nhanh local (CPU, 1 config) để smoke-test
uv run python -m model.run_training \
    --bars data/cache/backfill/dollar_bars.parquet \
    --features out/features_2y.parquet --out out/model_v1.pt

# sweep 216 configs trên Kaggle (2×T4)
tools/build_train_kernel.sh
uvx kaggle kernels push -p kernel_train
uvx kaggle kernels status vuongnguyen0909/cbot-train-sweep
uvx kaggle kernels output vuongnguyen0909/cbot-train-sweep -p out/sweep/
```

Metric đánh giá không chỉ accuracy (baseline đoán bừa ~33%, đoán toàn
class lớn nhất ~36.5%) mà còn **edge theo ngưỡng confidence**: với mỗi
threshold, lọc dự đoán có `conf >= th`, tính return thực trung bình khi
model nói LÊN (dương là tốt) trừ khi nói XUỐNG. `edge_conf0.40` là cột
dùng để xếp hạng sweep (đủ volume lệnh để thống kê đáng tin, lọc trial có
`n_conf0.40 < 200`).

## Test

```bash
uv run pytest tests/ -q        # 71 tests, TDD toàn bộ, ~11s
```

## Việc còn lại (chưa làm)

- Chọn config tốt nhất từ `sweep_results.csv`, train bản "final" full data
- Dọn kernel `cbot-dollar-bars` vào repo chính thức `bars/` thay vì nằm ở
  scratchpad (hiện tại `bars/pipeline.py` là logic core, nhưng script
  Kaggle runner riêng vẫn ở ngoài repo)
- `llm/`: prompt + parse cho lớp veto
- `risk/`: hard rules (position size, max drawdown, ...)
- `backtest/`: engine chạy model + LLM veto + risk trên test set, tính
  Sharpe/drawdown/turnover có tính phí
- `execution/`, `live/`: để sau, ngoài scope v1
