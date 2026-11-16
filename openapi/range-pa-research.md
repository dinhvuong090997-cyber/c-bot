# Range-bar cung–cầu PA và TP high/low — 2026-11-14

## Kết luận

Đã xây và thử offline bộ range bar từ quote tick, chiến lược base→departure→first-retest→rejection, rồi chuyển TP sang high/low theo yêu cầu người dùng. Các biến thể mới đều lỗ ở cả hai giai đoạn và ở hai mức chi phí. Không thay bot demo. Range builder có thể tái sử dụng cho nghiên cứu; thiết kế chiến lược này chưa có edge được chứng minh.

## Quy tắc bar để tái lập

Dùng Bid của quote snapshots được reader hiện tại merge theo millisecond. Một bar bắt đầu ở quote tiếp sau khi bar trước đóng; High/Low cập nhật từ giá thực. Bar đóng tại quote đầu tiên có High−Low≥range. Không cắt giá về ngưỡng, không tạo nhiều bar từ cùng tick, không giả tick/đường đi khi gap. Nến cuối chưa đủ range không phát tín hiệu. Do giá rời rạc, range thực có thể vượt ngưỡng. Đây là biến thể threshold thực giá, không phải bar synthetic luôn có biên độ đúng bằng ngưỡng. Ask vẫn dùng để khớp lệnh.

Reset phần bar chưa đóng và cấu trúc vùng khi đổi ngày UTC hoặc quote gap>60 giây. Không mang một mẫu qua khoảng thiếu giá dài. Gap nhỏ hơn ngưỡng vẫn có thể chứa thông tin thiếu; chưa chứng minh feed bao phủ mọi tick thị trường. Trong cùng millisecond, reader giữ minimum Bid/maximum Ask; do đó bar của nghiên cứu có thể khác bar dựng từ toàn bộ raw Bid event nguyên thứ tự.

Các nền tảng có nhiều quy tắc range bar khác nhau, nên định nghĩa phải cố định trước khi so sánh: [Sierra Chart — Range Bar variants](https://www.sierrachart.com/index.php?page=doc/ChartSettings.html#RangeBar). Không tuyên bố kết quả này tương đương mọi chart range bar khác.

## Thiết kế chiến lược đã chạy

Mọi ngưỡng dưới đây là giả thuyết nghiên cứu được chốt trước kết quả, không phải thông số được tối ưu. R là độ rộng range USD/oz; RR là reward/risk.

1. **Base:** một closed range bar có |Close−Open|≤0,35R.
2. **Departure:** hai closed bar tiếp theo cùng hướng, mỗi thân≥0,65R; close bar thứ hai vượt high base ít nhấtR cho demand, hoặc dưới low base ít nhấtR cho supply. Ba bar tạo vùng phải có range thực≤1,5R để loại outlier tạo mẫu.
3. **Zone:** lấy toàn bộ Low–High của base. Vùng mới nhất thay vùng trước; chưa quản lý nhiều vùng đồng thời. Vùng có hiệu lực từ close departure thứ hai, không vẽ như đã biết từ lúc base hình thành.
4. **First retest:** tick sau khi vùng được tạo chạm bên trong vùng Bid bắt đầu cửa sổ xác nhận. Xuyên distal trước xác nhận làm mất hiệu lực. Tối đa3 closed bars kể từ retest; không có xác nhận thì bỏ vùng, không chờ lần quay lại tốt hơn. Vùng cũng hết hạn sau50bar hoặc24h; reset UTC/gap có thể kết thúc sớm hơn.
5. **Rejection:** bar bắt đầu sau thời điểm xác nhận vùng, có giao vùng, thân≥0,35R cùng hướng departure, close vượt proximal edge, nhưng không đuổi quáR khỏi edge.
6. **Entry:** một lần thử mỗi vùng, tiếp tục giữ giới hạn một lần thử mỗi phút/một vị thế. Delay1giây như simulator gốc; pending tối đa thêm5giây. Signal có hiệu lực6giây, bị huỷ khi quá xa vùng, xuyên distal hoặc đã chạm TP high/low. Kiểm tra spread≤0,2R. Signal generation ID tránh pending dùng nhầm vùng mới.
7. **SL:** bên ngoài distal, buffer=max(spread tại fill,0,1R), khoảng stop tối thiểu3USD/oz theo config. Tính lại khoảng stop theo executable entry đã cộng adverse slippage, rồi làm tròn ra ngoài theo tick size. SL vẫn xử lý từng quote, không đợi range bar đóng.
8. **TP high/low theo yêu cầu mới:** BUY dùng high lớn nhất của hai departure bars, SELL dùng low nhỏ nhất. Mức này đã tồn tại lúc vùng được xác nhận. Entry đã vượt mục tiêu hoặc target sai phía sau slippage/rounding thì không mở lệnh. Đây là extreme quan sát được của nhịp đẩy; không dùng pivot tương lai. Đợt đầu không áp RR tối thiểu; đợt bổ sung theo yêu cầu người dùng áp RR≥3, xem mục cuối.
9. **RR:** tính từ entry/SL/TP thực tế, không ép2R/5R. `rr:null` ở run high/low thể hiện variable RR. `*-range-details.json` ghi zone, thời điểm tạo/xác nhận, high/low departure, target và initialRR từng lệnh.
10. **Risk/cost:** cùng sizing/cap/volume step, commission, swap, session windows và durable drawdown convention của simulator gốc. Bản mới tự chọn BUY/SELL theo vùng, không cần cùng hướng phiên Asia; vẫn giới hạn giờ vào như trước. Không BE/trailing/news filter.

## Thiết lập so sánh

Vốn16.707,35USD mỗi cửa sổ; risk cấu hình1%; closed-balance DD halt20%; spread multiplier baseline1,5; minimumSL3; swap on. Current Asia baseline giữ RR5. Jan1–Mar1 và Mar1–May1, end exclusive, vốn/risk state reset độc lập. Dữ liệu Jan–Apr2026 đã từng được nghiên cứu, không phải holdout mới.

Đợt đầu: R2/R3/R5 với fixedRR2, R3/fixedRR5 và baseline, mỗi loại slip0,10/0,20. Đợt sau theo người dùng: R2/R3/R5 với target high/low, R3/fixedRR5 control và baseline. Tổng40dòng so sánh, bao gồm control lặp lại;32cấu hình distinct theo cửa sổ. Một lần rerun kỹ thuật thêm chặn retry qua biên phút và thống kê overshoot, không chọn lại tham số theo lợi nhuận. Raw sơ bộ vẫn được giữ.

Return bên dưới là equity liquidation cuối kỳ, sau chi phí, gồm vị thế chưa đóng. MaxDD tính equity; PF và số lệnh là lệnh đã đóng. Slip USD/oz là giả định, không phải thống kê fill broker.

## Tất cả kết quả TP high/low

| Kỳ | Mô hình | Slip | Lệnh | Win rate | RR median | Equity return | MaxDD | PF | Vị thế cuối |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Jan–Feb | Asia gốc | 0.10 | 47 | 17.0% | — | +2.06% | 7.48% | 1.108 | 0 |
| Jan–Feb | Asia gốc | 0.20 | 48 | 16.7% | — | +1.89% | 7.59% | 1.098 | 0 |
| Jan–Feb | Range2 high/low | 0.10 | 258 | 52.7% | 0.623 | -4.67% | 4.89% | 0.484 | 0 |
| Jan–Feb | Range3 high/low | 0.10 | 187 | 56.1% | 0.663 | -3.08% | 3.49% | 0.635 | 0 |
| Jan–Feb | Range5 high/low | 0.10 | 85 | 48.2% | 0.666 | -3.76% | 3.97% | 0.488 | 0 |
| Jan–Feb | Range3 RR5 control | 0.10 | 179 | 16.2% | — | -4.08% | 5.21% | 0.750 | 0 |
| Jan–Feb | Range2 high/low | 0.20 | 258 | 50.0% | 0.581 | -5.39% | 5.55% | 0.428 | 0 |
| Jan–Feb | Range3 high/low | 0.20 | 186 | 54.8% | 0.630 | -3.68% | 4.06% | 0.581 | 0 |
| Jan–Feb | Range5 high/low | 0.20 | 85 | 48.2% | 0.650 | -3.98% | 4.19% | 0.468 | 0 |
| Jan–Feb | Range3 RR5 control | 0.20 | 177 | 14.7% | — | -5.56% | 6.51% | 0.670 | 0 |
| Mar–Apr | Asia gốc | 0.10 | 36 | 27.8% | — | +10.85% | 5.68% | 1.630 | 1 |
| Mar–Apr | Asia gốc | 0.20 | 36 | 27.8% | — | +10.86% | 5.71% | 1.631 | 1 |
| Mar–Apr | Range2 high/low | 0.10 | 291 | 56.4% | 0.580 | -3.95% | 4.00% | 0.560 | 0 |
| Mar–Apr | Range3 high/low | 0.10 | 150 | 50.0% | 0.622 | -3.90% | 4.06% | 0.480 | 0 |
| Mar–Apr | Range5 high/low | 0.10 | 67 | 55.2% | 0.636 | -1.82% | 2.59% | 0.637 | 0 |
| Mar–Apr | Range3 RR5 control | 0.10 | 148 | 14.2% | — | -3.32% | 3.99% | 0.754 | 0 |
| Mar–Apr | Range2 high/low | 0.20 | 288 | 55.2% | 0.550 | -4.61% | 4.66% | 0.507 | 0 |
| Mar–Apr | Range3 high/low | 0.20 | 150 | 50.0% | 0.588 | -4.30% | 4.45% | 0.447 | 0 |
| Mar–Apr | Range5 high/low | 0.20 | 67 | 55.2% | 0.618 | -2.00% | 2.71% | 0.611 | 0 |
| Mar–Apr | Range3 RR5 control | 0.20 | 148 | 14.2% | — | -3.59% | 4.20% | 0.743 | 0 |

## Đợt fixed RR ban đầu — giữ cả kết quả thất bại

| Kỳ | Mô hình | Slip | Lệnh | Equity return | MaxDD | PF |
|---|---|---:|---:|---:|---:|---:|
| Jan–Feb | Asia gốc | 0.10 | 47 | +2.06% | 7.48% | 1.108 |
| Jan–Feb | Asia gốc | 0.20 | 48 | +1.89% | 7.59% | 1.098 |
| Jan–Feb | Range2 RR2 | 0.10 | 257 | -5.09% | 5.62% | 0.639 |
| Jan–Feb | Range3 RR2 | 0.10 | 187 | -3.70% | 4.81% | 0.734 |
| Jan–Feb | Range5 RR2 | 0.10 | 84 | -2.71% | 3.62% | 0.731 |
| Jan–Feb | Range3 RR5 | 0.10 | 179 | -4.08% | 5.21% | 0.750 |
| Jan–Feb | Range2 RR2 | 0.20 | 257 | -6.12% | 6.41% | 0.578 |
| Jan–Feb | Range3 RR2 | 0.20 | 187 | -4.66% | 5.78% | 0.682 |
| Jan–Feb | Range5 RR2 | 0.20 | 84 | -3.22% | 4.11% | 0.692 |
| Jan–Feb | Range3 RR5 | 0.20 | 177 | -5.56% | 6.51% | 0.670 |
| Mar–Apr | Asia gốc | 0.10 | 36 | +10.85% | 5.68% | 1.630 |
| Mar–Apr | Asia gốc | 0.20 | 36 | +10.86% | 5.71% | 1.631 |
| Mar–Apr | Range2 RR2 | 0.10 | 287 | -3.86% | 3.97% | 0.745 |
| Mar–Apr | Range3 RR2 | 0.10 | 151 | -4.13% | 4.61% | 0.647 |
| Mar–Apr | Range5 RR2 | 0.10 | 66 | -1.91% | 2.97% | 0.754 |
| Mar–Apr | Range3 RR5 | 0.10 | 148 | -3.32% | 3.99% | 0.754 |
| Mar–Apr | Range2 RR2 | 0.20 | 287 | -5.23% | 5.33% | 0.676 |
| Mar–Apr | Range3 RR2 | 0.20 | 151 | -4.67% | 5.14% | 0.618 |
| Mar–Apr | Range5 RR2 | 0.20 | 66 | -2.01% | 3.06% | 0.748 |
| Mar–Apr | Range3 RR5 | 0.20 | 148 | -3.59% | 4.20% | 0.743 |

## Điều học được

Target high/low khiến RR thực tế trung vị khoảng0,55–0,67. Chờ rejection đóng ngoài zone rồi mới vào làm quãng đường tới extreme departure còn ngắn, trong khi stop phải vượt cả vùng và buffer. Win rate khoảng48–56% vẫn đi kèm PF<1; tăng tỷ lệ thắng đơn thuần không giải quyết payoff nhỏ. Không suy ra xác suất hoà vốn từ RR median vì mỗi lệnh có payoff/khối lượng khác nhau.

Range5 high/low lỗ ít hơn ở giai đoạn sau nhưng vẫn lỗ cả hai kỳ; không chọn nó làm cấu hình live chỉ vì đứng đầu nhóm lỗ. Primary Range3 không qua tiêu chí lợi nhuận/robustness. So với baseline ở hai kỳ, chưa có nâng cấp được chứng minh. Không thể quy mọi khác biệt cho range bars: logic vào, hướng và stop của chiến lược cũng thay đổi.

Risk cấu hình không bằng risk thực mỗi lệnh vì min/step/notional cap. Mọi biến thể mới không có vị thế mở cuối kỳ; baseline giai đoạn sau có1vị thế, đã tính mark-to-liquidation. Giữ DD20% không có nghĩa khuyên dùng mức đó, chỉ giữ cùng giả định so sánh.

## Chất lượng range bar và giới hạn

| Kỳ | R | Closed bars | Vượt ngưỡng bất kỳ | Vượt1,5R | Overshoot lớn nhất USD/oz | Reset |
|---|---:|---:|---:|---:|---:|
| Jan–Feb | 2 | 143506 | 136036 | 12289 | 52.14 | 81 |
| Jan–Feb | 3 | 78130 | 74378 | 3901 | 51.14 | 81 |
| Jan–Feb | 5 | 34438 | 32878 | 690 | 49.14 | 81 |
| Mar–Apr | 2 | 134724 | 126184 | 5004 | 88.93 | 91 |
| Mar–Apr | 3 | 69924 | 65610 | 1352 | 87.93 | 91 |
| Mar–Apr | 5 | 28837 | 27243 | 268 | 85.93 | 91 |

Bar diagnostics gồm warmup tối đa4ngày trước cửa sổ. Vượt ngưỡng một vài tick rất phổ biến; cột>1,5R tách outlier lớn. Đã có overshoot hàng chụcUSD/oz, nên tuyệt đối không giả khớp tại ngưỡng range lý tưởng. Những mức nhảy này cần kiểm chứng nguồn nếu tiếp tục phát triển; hiện giữ giá thực thay vì nội suy.

Dữ liệu chỉ4tháng đã xem, một broker CFD; chưa mô hình queue/liquidity/margin rejects, swap/commission lịch sử hoặc mất kết nối thực. First retest được định nghĩa bằng quote đã biết; không suy ra dòng tiền tổ chức từ vùng hình học. Chưa có chart range live hay mới thêm dashboard copy.

## Cách dùng cho trợ lý và tái lập

Đọc `*-range-details.json` để kiểm tra: zoneCreated≤confirmation≤entry; BUY target=departureHigh, SELL target=departureLow; stop ngoài distal; RR tính lại từ giá. Cùng một vùng không được retry qua biên phút, và tín hiệu mới không được thay stop/target của pending cũ. Thời điểm/giá trong report là lịch sử, không phải dữ liệu thị trường hiện tại.

`--compare-range-pa` chạy fixed-target; `--compare-range-hl` chạy high/low. Đều dùng `backtest START END --config FILE --output DIR`, config bắt buộc, slip>0 và≤1, không ghép comparison flags. Default output của range research ở ignored audit/, report đánh dấu researchOnly và bị execution từ chối Apply. High/low có rr:null; dùng báo cáo này và ledger riêng, chưa dùng generic make_report.py hoặc dashboard để diễn giải variable RR.

Source: `RangeSupplyDemand.cs`; tests: `RangeResearchChecks.cs`, tích hợp raw ticks→order/SL/TP/actualRR trong `BacktestChecks.cs`. Build offline output/tmp/pa-bin,0warning/error; backtest/SMC/range/fake execution/fake worker checks đạt. Baseline ở hai kỳ đối chiếu đúng các trường kết quả cũ, không thay logic chiến lược gốc.

Artifact riêng ở ignored `openapi/audit/range-pa/`: early/later sơ bộ; final-early/final-later fixed; hl-early/hl-later high/low; configs, logs và before/after state. Không commit credentials, raw broker metadata hoặc bằng chứng riêng.

Chưa nên triển khai. Nếu tiếp tục, giả thuyết cần kiểm định riêng là giá vào gần vùng hơn hoặc mục tiêu cấu trúc xa hơn; không tự sửa hai thứ cùng lúc rồi gọi là cải thiện range bar. Bot demo vẫn chạy bản cũ, không có Start/Stop/Apply hoặc lệnh thử trong nghiên cứu.

## Bổ sung theo yêu cầu người dùng: chỉ vào khi RR≥3

Giữ nguyên target high/low departure và SL ngoài zone. Tại quote khớp trễ, lấy executable entry đã gồm spread/slippage, target/SL đã làm tròn; chỉ cho mở nếu khoảng reward≥3×khoảng risk. Đúng3R được chấp nhận; dưới3R bị loại trước sizing/commission. Đây là RR hình học; commission và swap vẫn tính trong net P&L. Không đổi entry hay đẩy target cho đủ ngưỡng.

Lệnh: `backtest START END --config FILE --compare-range-hl --require-3r --output DIR`. Ngưỡng chỉ áp vào các case high/low; baseline/fixed-RR control giữ nguyên.

| Kỳ | Range USD/oz | Slip | Bị loại vì RR<3 | Lệnh đóng | Vị thế cuối | Equity return |
|---|---:|---:|---:|---:|---:|---:|
| Jan–Feb | 2 | 0.10 | 258 | 0 | 0 | +0.00% |
| Jan–Feb | 3 | 0.10 | 187 | 0 | 0 | +0.00% |
| Jan–Feb | 5 | 0.10 | 86 | 0 | 0 | +0.00% |
| Jan–Feb | 2 | 0.20 | 258 | 0 | 0 | +0.00% |
| Jan–Feb | 3 | 0.20 | 186 | 0 | 0 | +0.00% |
| Jan–Feb | 5 | 0.20 | 86 | 0 | 0 | +0.00% |
| Mar–Apr | 2 | 0.10 | 291 | 0 | 0 | +0.00% |
| Mar–Apr | 3 | 0.10 | 150 | 0 | 0 | +0.00% |
| Mar–Apr | 5 | 0.10 | 67 | 0 | 0 | +0.00% |
| Mar–Apr | 2 | 0.20 | 288 | 0 | 0 | +0.00% |
| Mar–Apr | 3 | 0.20 | 150 | 0 | 0 | +0.00% |
| Mar–Apr | 5 | 0.20 | 67 | 0 | 0 | +0.00% |

Cả12case high/low có ngưỡng3R đều0lệnh/0vị thế. Return0% là đứng ngoài, không phải chiến lược có lợi nhuận hoặc tỷ lệ thắng tốt hơn. Cách vào sau rejection và target departure hiện tại không cung cấp khoảng reward đủ xa. Chưa thay entry/target để ép có lệnh. Cần giả thuyết mới nếu muốn cấu trúc này tạo setup3R; bốn tháng đã xem không chứng minh tương lai sẽ không bao giờ xuất hiện.

Build0warnings/errors và tests boundary3R BUY/SELL, dưới3R, low-RR rejection trước phí/vị thế đều đạt. Baseline/fixed controls đối chiếu giữ nguyên các trường kết quả cũ. Evidence riêng: ignored `audit/range-pa/min3r-{early,later}`.
