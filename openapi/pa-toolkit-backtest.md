# Backtest PA toolkit — 2026-11-14

**Kết luận:** bản PA đầy đủ (cung–cầu + swing target + cùng chiều regime + minimum3R) không mở lệnh ở cả ba range2/3/5, hai mức slippage, Jan–Feb/Mar–Apr và ngàyNov13. Không có lợi nhuận được chứng minh; return0% là đứng ngoài.

## Thiết lập cố định

Vốn16,707.35USD giống nghiên cứu range trước và số dư demo quan sát; risk1%, DDhalt20%, minimumSL3USD/oz, spread multiplier1.5, Asia+NY, swap bật, commission broker,1sentrydelay, slippage0.10 và0.20USD/oz. Các kỳ reset vốn và trạng thái độc lập; không cộng/ghép return. Dữ liệu Jan–Apr đã xem trước, không gọi là pristine holdout. Nov13 chỉ một ngày mới, không đủ thống kê; thiếu warmup Nov9–12 và simulation bắt đầu flat nên không so trực tiếp với P&L demo có vị thế sẵn.

Bản mới dùng pivot strict2left/2right trên chính threshold range bars; regime mất hiệu lực khi supporting swing bị close phá. Freeze target swing gần nhất phía trước và regime tại confirmation, chỉ dùng pivot đã biết. Entry chờ1s và dùng giá thực thi sau spread/slippage; SL ngoài vùng + buffer, min3USD; làm tròn giá rồi kiểm tra>=3R. Không đẩy TP/đổi entry cho đủRR. Bid-close illustration trên chart không phải giáfill. Entry guards/6ssignalexpiry/once-minute/once-zone kế thừa bản range.

Bốn nhóm: baseline cBot gốc; supply/demand+swing target bỏ gate (diagnostic); swing target+>=3R bỏ regime (diagnostic); full toolkit cùng chiều+>=3R (primary). Không điều chỉnh tham số theo kết quả.

## Jan–Feb 2026

10,375,207 merged Bid/Ask snapshots. Bảng dưới slippage0.10; net equity đã tính costs và mark-to-liquidation vị thế cuối kỳ.

| Bộ quy tắc | Range | Lệnh đóng | Return | Max equity DD | PF | Vị thế cuối |
|---|---:|---:|---:|---:|---:|---:|
| Baseline RR5 | — | 47 | +2.057% | 7.483% | 1.108 | 0 |
| Swing TP, bỏ gates | 2 | 188 | -3.837% | 3.931% | 0.313 | 0 |
| Swing TP + ≥3R | 2 | 0 | +0.000% | 0.000% | — | 0 |
| Full PA: regime + ≥3R | 2 | 0 | +0.000% | 0.000% | — | 0 |
| Swing TP, bỏ gates | 3 | 145 | -2.464% | 2.850% | 0.458 | 0 |
| Swing TP + ≥3R | 3 | 1 | +0.182% | 0.046% | — | 0 |
| Full PA: regime + ≥3R | 3 | 0 | +0.000% | 0.000% | — | 0 |
| Swing TP, bỏ gates | 5 | 73 | -1.870% | 2.268% | 0.490 | 0 |
| Swing TP + ≥3R | 5 | 0 | +0.000% | 0.000% | — | 0 |
| Full PA: regime + ≥3R | 5 | 0 | +0.000% | 0.000% | — | 0 |
## Mar–Apr 2026

11,459,291 merged Bid/Ask snapshots. Bảng dưới slippage0.10; net equity đã tính costs và mark-to-liquidation vị thế cuối kỳ.

| Bộ quy tắc | Range | Lệnh đóng | Return | Max equity DD | PF | Vị thế cuối |
|---|---:|---:|---:|---:|---:|---:|
| Baseline RR5 | — | 36 | +10.852% | 5.678% | 1.630 | 1 |
| Swing TP, bỏ gates | 2 | 214 | -3.201% | 3.259% | 0.354 | 0 |
| Swing TP + ≥3R | 2 | 0 | +0.000% | 0.000% | — | 0 |
| Full PA: regime + ≥3R | 2 | 0 | +0.000% | 0.000% | — | 0 |
| Swing TP, bỏ gates | 3 | 122 | -2.451% | 2.592% | 0.404 | 0 |
| Swing TP + ≥3R | 3 | 0 | +0.000% | 0.000% | — | 0 |
| Full PA: regime + ≥3R | 3 | 0 | +0.000% | 0.000% | — | 0 |
| Swing TP, bỏ gates | 5 | 58 | -1.401% | 1.829% | 0.524 | 0 |
| Swing TP + ≥3R | 5 | 0 | +0.000% | 0.000% | — | 0 |
| Full PA: regime + ≥3R | 5 | 0 | +0.000% | 0.000% | — | 0 |

## Chẩn đoán

Không chỉ riêng regime làm ít lệnh: bỏ regime nhưng giữ3R chỉ có1lệnh range3 trong Jan–Feb, không có lệnh nào trong Mar–Apr. Lệnh BUY Jan30 18:22:27UTC có entry4707.59/SL4704.33/TP4718.08, RR3.218, net+30.48USD (+0.1824% vốn). Regime tại signal là Downtrend nên full toolkit chặn BUY. Một lệnh thắng không chứng minh edge; PF không có mẫu lỗ được hiển thị —, không coi là vượt trội. Với slip0.20, lệnh này vẫn1lệnh,+0.1806%; toàn bộ full toolkit vẫn0lệnh.

Bỏ cả3R/regime: cả3range đều lỗ cảhai kỳ. Range3 RR thực trung vị chỉ0.222R Jan–Feb và0.242R Mar–Apr. Mục tiêu swing gần thường quá gần so với SL sau khi chờ nến rejection; thay departure target bằng nearest swing không tự giải quyết payoff. Đây là mô tả dữ liệu, không chứng minh rằng chỉ thay target xa hơn sẽ có lãi.

| Kỳ | Range | PA xác nhận | Full: chặn regime | Full: chặn RR | Full: thiếu target |
|---|---:|---:|---:|---:|---:|
| early | 2 | 428 | 185 | 58 | 0 |
| early | 3 | 259 | 140 | 34 | 0 |
| early | 5 | 124 | 52 | 27 | 1 |
| later | 2 | 464 | 218 | 54 | 0 |
| later | 3 | 233 | 113 | 30 | 1 |
| later | 5 | 97 | 45 | 19 | 0 |

Counts là các attempts trong từng scenario, không phải các nhóm tín hiệu độc lập và không cộng được thành tổng confirm: session/spread/pending/expiry/price guards loại thêm trước fill; các gate khác nhau làm khác trạng thái position/attempt. Ledger lưu lý do tại từng attempt.

## Ngày dữ liệu mới: Nov13 2026

234,265 merged quote snapshots từ447,638raw side updates. Full toolkit và swing>=3R đều0lệnh ở mọi range/slip. Diagnostic range2 bỏgates có2lệnh thắng,+0.0521% ởslip0.10; range3/5 không có lệnh. Chỉ là smoke test, chưa đủ kết luận hoặc chọn chiến lược. Không tải/bù thêm lịch sử May–Nov12 trong thử nghiệm này.

## Kiểm chứng và tái lập

CLI: `backtest START END --config CONFIG.json --compare-pa-toolkit --output DIR`. Report researchOnly=true và bị execution từ chối Apply. Thêm RangePaStructure.cs và frozen-decision ledgers; không thay bot live.

- C# parity vs JS chart:7425prefixes trên9snapshots, regime/pivots và tất cả confirmation targets khớp.
- Unit: causal pivots, known/frozen targets, gap/transition; integration3R dùng entry thực thi trước fees; existing backtest/SMC/range và fake execution/history/recorder checks đạt.
- `python3 check_pa_toolkit_results.py audit/pa-toolkit-backtest`:60runs,1560opened entries trên các scenario/sensitivity (không phải1560lệnh độc lập), targetknown≤confirmation≤entry, SL đúng phía/min3USD, actualRR>=gate, correct regime và sốopen/closed khớp. Baseline khớp exact8metric với report cũ cùng config.
- Build0warnings/errors; JS tests và diff checks đạt. Không thử broker order.

Evidence ignored `audit/pa-toolkit-backtest/{early,later,new-day}` gồm config, inputfileSHA, cost metadata, attempts/signals/closed trades/daily equity. Lượt50k sơ bộ được giữ riêng trong *-50k, không dùng làm primary vì vốn/lot constraints khác thử nghiệm trước. Source hashes ởsource-hashes.json. Dữ liệu một CFD broker có overshoot/ties/gaps; commission/swap dùng metadata hiện tại; không mô phỏng orderbook/liquidity/margin rejects hoặc kết nối lỗi. Không triển khai strategy hay restart worker/recorder.
