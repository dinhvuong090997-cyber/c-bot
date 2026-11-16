# Nghiên cứu SMC/PA cho Aurum — 2026-11-14

## Kết luận

Chưa có bằng chứng nên đưa bộ lọc SMC đơn lẻ vào bot demo. Phá cấu trúc còn lợi nhuận nhưng kém bản gốc ở tháng 3–4; sweep và FVG chuyển sang lỗ. Nến M5 cùng hướng tốt hơn ở giai đoạn đầu, gần như ngang gốc ở giai đoạn sau; khi tăng trượt giá, giai đoạn sau kém gốc. Vì vậy bước tiếp theo phù hợp là bộ chỉ báo quan sát có bằng chứng và trạng thái, không phải tự động thay chiến lược.

## Cách thử

Tái sử dụng simulator C# và tick Bid/Ask FxPro hiện có. Chỉ dựng nến Bid cho nhận diện hình học; khớp lệnh vẫn dùng Bid/Ask, spread, commission, swap và trễ một giây như gốc. Vốn mỗi giai đoạn 16.707,35 USD, RR5, risk cấu hình1%, giới hạn drawdown20%, SL tối thiểu3 USD/oz, spread multiplier1,5, cả Asia và New York. Vốn/risk state khởi tạo độc lập ở mỗi giai đoạn. Đây là thông số chiến lược demo tại thời điểm đọc, không phải tái tạo toàn bộ lịch sử tài khoản demo. Trượt giá0,10 USD/oz là giả định nghiên cứu; stress0,20, không phải thống kê fill đo từ broker. Không tối ưu tham số.

Hai giai đoạn Jan1–Mar1 và Mar1–May1, ngày kết thúc không tính. 5 mô hình × 2 chi phí × 2 giai đoạn =20 phép thử; công bố tất cả. Khoảng21,83 triệu quote snapshots sau merge; không đồng nghĩa số tick nguyên thủy. Dữ liệu Jan–Apr đã từng dùng trong nghiên cứu, nên giai đoạn sau không phải holdout chưa từng xem.

## Định nghĩa thực nghiệm

- Gốc: hướng phiên Asia, lịch phiên và cơ chế tái vào lệnh hiện tại.
- M5: nến vừa đóng tăng cho BUY, giảm cho SELL; doji không cho vào.
- Structure: nến M5 đóng vượt pivot chưa từng bị đóng vượt. Pivot phải cao/thấp nghiêm ngặt hơn hai nến mỗi bên; biết pivot sau hai nến bên phải. Phá cùng hướng trạng thái cấu trúc là BOS, ngược là CHoCH; lần phá đầu là khởi tạo hướng.
- Sweep: wick xuyên pivot đã xác nhận, chưa bị close phá, nhưng close quay về phía trong. Quét đáy cho BUY, quét đỉnh cho SELL; quét hai phía trong một nến không cho tín hiệu. Có thể lặp lại sweep tại cùng mức trước khi mức đó bị close phá.
- FVG: ba nến liên tiếp, low nến3 > high nến1 cho BUY hoặc high nến3 < low nến1 cho SELL. Chỉ thử thời điểm hình thành, không thử lệnh limit/retest vùng.
- Mỗi sự kiện chỉ cho phép trong bucket M5 kế tiếp, kiểm tra lại ở quote khớp trễ. Nến cần quan sát trong5 giây ở hai biên; thiếu bucket hoặc nến biên thiếu reset cấu trúc. Không kiểm tra mọi lỗ hổng nội bộ nến.
- Bộ lọc chỉ chặn tín hiệu gốc, không đảo hướng. Giữ cơ chế một vị thế và một lần thử mỗi phút: có thể tái vào trong cùng bucket sau khi vị thế đóng. Không phải một giao dịch cho mỗi sự kiện SMC.

## Toàn bộ kết quả

Return bên dưới dùng liquidation equity cuối kỳ, gồm lãi/lỗ chưa đóng. PF và số lệnh chỉ tính lệnh đã đóng; maxDD dùng equity. Chi phí đơn vị USD/oz.

| Giai đoạn | Mô hình | Slip | Lệnh đóng | Thắng | Return equity | MaxDD equity | PF | Vị thế cuối | Dừng DD |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| Jan–Feb | Gốc | 0.10 | 47 | 8 | +2.06% | 7.48% | 1.108 | 0 | Không |
| Jan–Feb | Gốc | 0.20 | 48 | 8 | +1.89% | 7.59% | 1.098 | 0 | Không |
| Jan–Feb | Nến M5 cùng hướng | 0.10 | 45 | 9 | +6.82% | 6.11% | 1.419 | 0 | Không |
| Jan–Feb | Phá cấu trúc M5 | 0.10 | 28 | 6 | +3.85% | 7.69% | 1.316 | 0 | Không |
| Jan–Feb | Sweep M5 | 0.10 | 27 | 5 | +4.72% | 6.40% | 1.226 | 1 | Không |
| Jan–Feb | FVG hình thành | 0.10 | 44 | 8 | +4.38% | 6.98% | 1.261 | 0 | Không |
| Jan–Feb | Nến M5 cùng hướng | 0.20 | 46 | 9 | +6.00% | 6.16% | 1.352 | 0 | Không |
| Jan–Feb | Phá cấu trúc M5 | 0.20 | 28 | 6 | +3.84% | 7.70% | 1.315 | 0 | Không |
| Jan–Feb | Sweep M5 | 0.20 | 27 | 5 | +4.70% | 6.39% | 1.225 | 1 | Không |
| Jan–Feb | FVG hình thành | 0.20 | 44 | 8 | +4.31% | 6.99% | 1.256 | 0 | Không |
| Mar–Apr | Gốc | 0.10 | 36 | 10 | +10.85% | 5.68% | 1.630 | 1 | Không |
| Mar–Apr | Gốc | 0.20 | 36 | 10 | +10.86% | 5.71% | 1.631 | 1 | Không |
| Mar–Apr | Nến M5 cùng hướng | 0.10 | 38 | 11 | +10.90% | 6.26% | 1.654 | 1 | Không |
| Mar–Apr | Phá cấu trúc M5 | 0.10 | 34 | 8 | +2.92% | 7.11% | 1.161 | 1 | Không |
| Mar–Apr | Sweep M5 | 0.10 | 18 | 4 | -0.80% | 6.26% | 0.929 | 1 | Không |
| Mar–Apr | FVG hình thành | 0.10 | 32 | 6 | -3.24% | 9.88% | 0.813 | 1 | Không |
| Mar–Apr | Nến M5 cùng hướng | 0.20 | 39 | 11 | +10.58% | 6.25% | 1.623 | 1 | Không |
| Mar–Apr | Phá cấu trúc M5 | 0.20 | 34 | 8 | +2.87% | 7.13% | 1.157 | 1 | Không |
| Mar–Apr | Sweep M5 | 0.20 | 18 | 4 | -0.78% | 6.26% | 0.931 | 1 | Không |
| Mar–Apr | FVG hình thành | 0.20 | 32 | 6 | -3.30% | 9.91% | 0.810 | 1 | Không |

## Diễn giải và giới hạn

Không gọi M5 là chiến thắng mới: Mar–Apr tại slip0,10 chỉ hơn gốc khoảng8,33 USD trên vốn16.707,35, và ở slip0,20 kém gốc. Mỗi nhóm chỉ18–48 lệnh, một số nhóm dưới30; chưa đủ bằng chứng thống kê hay đa chế độ thị trường. Lợi nhuận nhạy với một vài lệnh RR5, cần dữ liệu mới và thử quan sát tiến về trước. Không gộp hai tỷ suất của hai tài khoản khởi tạo lại thành một equity curve liên tục.

Risk cấu hình1% không có nghĩa mỗi lệnh rủi ro thực1%: notional cap, min/step volume và stop làm giảm khối lượng hoặc bỏ lệnh. Đây là lý do không áp kết quả RR1,5/risk0,25% trước đó cho cấu hình hiện tại.

Tăng slip có thể đổi giá entry, stop, timing thoát, sizing và vị thế cuối; return có thể hơi tăng dù friction tăng. Điều đó không chứng minh trượt giá có lợi.

Bản simulator gốc trong runtime đã chạy offline cùng cấu hình Mar–Apr: toàn bộ trường kết quả baseline và file trades trùng chính xác với bản nghiên cứu. Tuy nhiên backtest vẫn không chứng minh fill thực, margin/rejection lịch sử, rate swap/commission lịch sử hay sự tương đương stop-relative lúc broker fill. Không sửa những giả định đó để làm đẹp kết quả.

Dữ liệu broker CFD và quote count không xác nhận giao dịch tổ chức hay volume futures; dấu hiệu SMC ở đây là hình học giá. Chưa thử H1 alignment, FVG retest, Order Block, killzone mới hoặc tổ hợp sweep→CHoCH→FVG; kết quả thất bại của từng gate không bác bỏ mọi biến thể SMC, nhưng cũng không cho phép khẳng định tổ hợp sẽ tốt hơn.

## Repo được dùng như thế nào

Áp dụng cách đặt giả thuyết trước, luật đo được, giữ chi phí, kiểm tra thời điểm có thông tin và báo cáo cả kết quả thất bại từ [backtest-expert](https://github.com/tradermonty/claude-trading-skills/blob/main/skills/backtest-expert/SKILL.md). Repo yêu cầu lịch sử dài và nhiều điều kiện để đánh giá triển khai; bốn tháng hiện có chỉ đủ sàng lọc sơ bộ. Không cài skill/script hay đem phần chấm điểm của repo thành quyết định giao dịch.

[technical-analyst](https://github.com/tradermonty/claude-trading-skills/blob/main/skills/technical-analyst/SKILL.md) thiên về biểu đồ tuần và kịch bản; không chuyển các đánh giá chủ quan/xác suất chưa hiệu chuẩn thành tín hiệu M5. [drawdown-circuit-breaker](https://github.com/tradermonty/claude-trading-skills/blob/main/skills/drawdown-circuit-breaker/SKILL.md) là tham khảo tách quyền mở risk mới khỏi nhận diện giá; Aurum đã có halt bền vững, chưa cần thay. [Canonical index](https://github.com/tradermonty/claude-trading-skills/blob/main/skills-index.yaml) phân biệt kiểm chứng từng mặt; nhãn production không phải chứng nhận lợi nhuận XAUUSD.

Đối chiếu thuật ngữ với [LuxAlgo SMC](https://www.luxalgo.com/library/indicator/smart-money-concepts-smc/) cho BOS/CHoCH và [Capital.com FVG](https://capital.com/en-eu/learn/trading-strategies/fair-value-gap) cho cấu trúc ba nến. Đây là nguồn định nghĩa, không phải bằng chứng edge. Mã nhận diện tự viết, không sao chép indicator bên ngoài. Tài liệu [cTrader ProtoTrendbar](https://help.ctrader.com/open-api/model-messages/#prototrendbar) dùng để đối chiếu dữ liệu bar; giá vào/ra lấy từ dữ liệu thực nghiệm của ứng dụng.

## Tái lập và an toàn

Lệnh nghiên cứu: `./api backtest START END --config CONFIG.json --compare-smc --output OUTPUT`. Config cần slip>0 và≤1 để có kịch bản2×; không kết hợp `--compare-pa-m5`. `--compare-smc` tự thêm baseline, M5 và ba gate ở hai mức slip. Báo cáo đánh dấu researchOnly, không cho Apply vào execution; default thư mục riêng có đuôi-smc. Dùng container offline và `dotnet build --no-restore -o /tmp/pa-bin` để không ghi đè DLL runtime.

Config, tick provenance/hash, log, full ledgers và kết quả thô: `openapi/audit/smc/` (ignored). Bản nguồn này chỉ giữ tổng hợp không chứa credentials. Build0 lỗi/cảnh báo; kiểm tra closed-bar/pivot/sweep/FVG/causality và integration gate→delayed entry đạt; fake execution đạt. Không đặt lệnh thử hoặc restart dịch vụ.

Thiết kế bộ chỉ báo quan sát tiếp theo: [SPEC-SMC.md](SPEC-SMC.md).
