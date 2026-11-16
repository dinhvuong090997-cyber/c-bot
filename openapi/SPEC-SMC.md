# Thiết kế bộ chỉ báo SMC Observer cho Aurum

Ngày: 2026-11-14. Nhánh: `research/smc-pa`.
Trạng thái: thiết kế v1 để review; đã có prototype nghiên cứu M5 cho cấu trúc/sweep/FVG formation, **chưa có observer H1, quản lý vùng FVG hoặc overlay hoàn chỉnh**. Không triển khai vào worker.

## Mục đích

Tạo bộ chỉ báo để trợ lý đọc, đối chiếu và giải thích cấu trúc XAUUSD bằng dữ liệu có thể kiểm tra lại. Người dùng có thể biết mức nào đang được theo dõi, mẫu gì vừa được xác nhận, bằng chứng đến từ nến nào và dữ liệu có đủ hay không. Không biến nhãn SMC thành lệnh giao dịch hoặc xác suất thắng tự gán.

Nghiên cứu đã hoàn tất ở [smc-research.md](smc-research.md). Kết quả các gate riêng lẻ chưa biện minh thay bot demo. Observer là công cụ mô tả; khả năng quan sát đúng và khả năng kiếm lợi nhuận là hai tiêu chí kiểm định riêng.

## Kiến trúc và phạm vi

Tận dụng C#/.NET8 và quote reader đang có, không thêm dependency:

1. Tick Bid theo timestamp UTC → nến M5 đã đóng.
2. 12 nến M5 liên tiếp, đúng biên giờ → nến H1 đã đóng.
3. Mỗi khung có trạng thái cấu trúc riêng; M5 thêm sweep và vòng đời FVG.
4. Snapshot JSON có version, as-of và evidence cho trợ lý; sau đó mới cân nhắc overlay trên `openapi/dashboard/`.

Không phụ thuộc vòng đời dashboard. Consumer không có phương thức Start/Stop/Apply, order hoặc sửa risk journal. Snapshot lịch sử đọc cache; observer trực tiếp nếu triển khai sau này chỉ dùng kết nối monitor read-only có allowlist sẵn có. Không để kết nối phân tích gửi broker order.

Giữ helper dựng nến và quy tắc nhận diện dùng chung giữa replay và observer để tránh hai bộ logic lệch nhau. Prototype hiện tại là `M5Confirmation`, `SmcResearch`, `SmcResearchChecks`; vòng đời vùng và H1 trong tài liệu này chưa được prototype kiểm định.

## Hợp đồng dữ liệu

- Instrument: XAUUSD theo symbol metadata broker, không hardcode futures contract size.
- Giá hình học: Bid; event không dựa trên Ask/midpoint. Ask và spread là dữ liệu thực thi riêng.
- Bar time là thời điểm **mở**, interval `[open, open + timeframe)`.
- Bar hoàn thành chỉ khi interval kết thúc và quan sát được timestamp tiếp theo; không dùng tick của nến kế tiếp cho OHLC cũ.
- Tick sai thứ tự, giá không hữu hạn/không dương, Ask<Bid bị từ chối/ghi data-quality, không sửa ngầm lịch sử.
- Đồng bộ H1/M5 theo event-time UTC. Khi cùng mốc đóng, xử lý H1 trước khi xuất snapshot M5; không lấy H1 đang chạy.
- Nến thiếu bucket không được tạo giả bằng nến phẳng. H1 cần đủ12 M5 hợp lệ, không dùng nến H1 tổng hợp từ phần dữ liệu còn lại.
- Prototype kiểm tra tick trong5 giây ở hai biên. Bản observer cần thêm trường `maxObservedQuoteGapSeconds`; lỗ hổng nội bộ phải hiện rõ, chưa có ngưỡng loại bỏ nội bộ đã hiệu chuẩn. Không gọi nến có coverage biên là dữ liệu hoàn hảo.
- Data state riêng cho mỗi khung: `warming`, `ready`, `gap`, `stale`, `unavailable`. Thiếu hoặc cũ luôn có quyền chặn nhãn phân tích hợp lệ.
- Replay: `asOfUtc` là cutoff dữ liệu, không phải đồng hồ máy hiện tại. Observer trực tiếp: quote quá5 giây là stale theo bảo vệ feed hiện tại; stale không có nghĩa thị trường biến thành bearish.

## Swing và cấu trúc giá

Dùng pivot strict hai nến trái/hai nến phải ở cả M5 và H1:

- Swing high: high nến trung tâm lớn hơn high cả4 nến còn lại.
- Swing low: low nến trung tâm nhỏ hơn low cả4 nến còn lại.
- Equal high/low không thành pivot strict. Phát hiện cụm equal liquidity để giai đoạn sau.
- Ví dụ pivot mở09:00 trên M5 chỉ được biết khi nến09:10 đóng lúc09:15. `pivotUtc=09:00`, `confirmedUtc=09:15`. Nếu tick xác nhận đến09:15:02, có thêm `observedUtc=09:15:02`.
- Snapshot lúc09:14 tuyệt đối không có pivot đó. Overlay tương lai có thể đặt marker tại09:00 nhưng phải cho thấy trễ xác nhận; không ghi đè lịch sử để giả nhận biết sớm.
- Sau5 nến đủ có thể có pivot hoặc vẫn không có; không ép dữ liệu thành xu hướng.

Structure break:

- Close vượt swing high đã được xác nhận trước đó, chưa bị close phá → break up.
- Close xuống dưới swing low tương ứng → break down.
- Wick xuyên mức nhưng close không vượt không phải break.
- Lần break đầu khởi tạo `structureDirection`; tên event `initial_break`.
- Break cùng direction đang giữ → `bos`; break ngược → `choch`, cập nhật direction tại thời điểm xác nhận, không sớm hơn.
- Một pivot chỉ phát close-break một lần. Pivot mới có ID mới, kể cả mức giá trùng pivot cũ.
- Hướng này chỉ là trạng thái của định nghĩa cấu trúc, không khẳng định xu hướng thật đã đảo hay CHoCH chắc chắn thành công.
- Lỗ hổng nến reset trạng thái cần chuỗi liên tục; kết quả lại `warming/unknown` thay vì kéo hướng cũ qua dữ liệu thiếu.

## Liquidity sweep M5

Dùng swing xác nhận đã tồn tại **trước** nến sweep và chưa bị close phá:

- Sweep đáy: Low < swingLow và Close > swingLow.
- Sweep đỉnh: High > swingHigh và Close < swingHigh.
- Close bằng mức không xác nhận quay lại. So sánh nghiêm ngặt theo giá đã chuẩn hoá tick size.
- Nến quét cả hai phía đánh dấu `ambiguous_sweep`, không tự chọn hướng.
- Event ghi target pivot ID/price và mức xuyên xa nhất. Không gọi đó là bằng chứng đã khớp stop của người khác.
- Có thể xuất các sweep lặp lại tại cùng mức; không gọi mỗi lần là thanh khoản mới. Event ID gắn bar/time/target để consumer không đếm cùng event nhiều lần.

## FVG M5 và vòng đời vùng

Ba nến A/B/C liên tiếp đã đóng:

- Bullish: C.Low > A.High → vùng `[A.High, C.Low]`.
- Bearish: C.High < A.Low → vùng `[C.High, A.Low]`.
- Xác nhận tại close C; lưu ID ba nến. Không xem gap cuối tuần hoặc thiếu nến là FVG.
- V1 không đặt tiêu chí displacement/ATR để tránh thêm ngưỡng chưa thử. Do đó gọi đúng là vùng hình học FVG, không gọi FVG chất lượng cao.
- Prototype chỉ thử formation. Vòng đời sau đây là thiết kế cho observer, chưa được backtest:

| State | Điều kiện sau xác nhận |
|---|---|
| fresh | Chưa có nến sau C chạm vùng |
| touched | Wick nến sau giao với biên gần vùng |
| partially_filled | Giá xuyên vào vùng nhưng chưa tới biên xa |
| filled | Wick đã tới biên xa |
| invalidated | Bullish có close < biên dưới; bearish có close > biên trên |
| expired | Sau24 M5 (2 giờ), chưa terminal; đây là giới hạn hiển thị cố định, không phải tham số lợi nhuận đã kiểm định |
| unknown_after_gap | Dữ liệu gián đoạn; không suy đoán thứ tự chạm/lấp |

Xử lý theo nến đóng; nếu cùng nến vừa filled vừa invalidated, terminal state là invalidated và giữ cả hai evidence. Chỉ biết điều kiện xảy ra trong nến, không suy đoán đường đi tick nội nến nếu không replay tick. Không cho C tự chạm/lấp vùng vừa tạo. Không hồi sinh vùng terminal. Mỗi snapshot tách vùng active khỏi event lịch sử, chỉ giữ24 giờ sự kiện cho snapshot thường; replay đầy đủ nằm trong artifact riêng.

Hai khái niệm khác nhau: `fill` hình học của vùng và `fill` lệnh broker. Observer không gửi lệnh limit tại50%FVG và không giả định gap sẽ được lấp.

## Kết hợp H1/M5 cho trợ lý

Không tạo score0–100 hoặc win probability. Xuất:

- `contextH1`: cấu trúc bullish/bearish/unknown và event làm thay đổi trạng thái.
- `structureM5`: trạng thái tương tự, pivots đang theo dõi, break gần nhất.
- `recentSweeps`: danh sách evidence, bao gồm mơ hồ và lặp lại.
- `activeFvgZones`: vùng chưa terminal, tuổi và trạng thái lấp.
- `alignment`: `aligned`, `conflict`, `unknown`. Chỉ so hai direction đã biết, dữ liệu ready; data-quality kém trả unknown.
- `summary`: mô tả bằng tiếng Anh cho UI; trợ lý giải thích lại tiếng Việt. Ví dụ: “H1 structure bullish; M5 bearish CHoCH confirmed at14:35 UTC; bullish FVG partially filled. Context conflicts.”

Nhãn aligned không phải quyền BUY/SELL. Có thể trình bày chuỗi sweep→CHoCH→FVG theo timestamp nếu thật sự tồn tại, nhưng v1 không mặc định ba sự kiện độc lập là một setup và không khẳng định đã có lợi thế giao dịch.

## Snapshot schema v1

Đây là hợp đồng **dự kiến**, không phải endpoint đã chạy. JSON ví dụ chỉ minh hoạ hình dạng, không chứa số liệu thị trường hiện tại:

```json
{
  "schemaVersion": 1,
  "instrument": "XAUUSD",
  "source": "fxpro-cached-bid-ask-ticks",
  "asOfUtc": "2026-01-05T14:35:00Z",
  "priceBasis": "bid",
  "contextH1": {"dataState": "warming", "direction": "unknown", "lastClosedBarUtc": "2026-01-05T13:00:00Z"},
  "structureM5": {"dataState": "ready", "direction": "bullish", "lastClosedBarUtc": "2026-01-05T14:30:00Z"},
  "alignment": "unknown",
  "events": [],
  "activeFvgZones": [],
  "dataQuality": {"missingBuckets": 0, "maxObservedQuoteGapSeconds": 2.1},
  "limitations": ["Price geometry does not identify institutional orders."],
  "ordersEnabled": false
}
```

Event phải có `id`, `timeframe`, `kind`, `direction`, `barOpenUtc`, `confirmedUtc`, `observedUtc`, `level/zone`, `targetPivotId`, `evidenceBarTimes`, `ruleVersion`. Không event nào có confirmedUtc > asOfUtc. Evidence luôn chứa đủ nến và mức để tính lại; cùng input/ruleVersion cho cùng ID/event.

## Cách trợ lý sử dụng

1. Xác nhận source, cutoff, price basis và dataState; không lấy snapshot cũ làm hiện tại.
2. Đọc bối cảnh H1 trước, rồi cấu trúc M5; nêu xung đột thay vì bỏ qua.
3. Trích sự kiện bằng confirmedUtc và mức giá; phân biệt observed time với pivot time.
4. Nêu điều kiện làm nhận định không còn đúng: close qua pivot đối diện, vùng invalidated, dữ liệu stale/gap.
5. Nếu được hỏi giao dịch, phân biệt chỉ báo mô tả với chiến lược chưa kiểm định; không tự bật Start/Apply.

## Kiểm thử nghiệm thu trước khi hiện lên chart

- Prefix invariance: snapshot tạiT từ dữ liệu≤T phải giống snapshot tạiT khi replay cả file dài hơn. Không đổi pivot/event quá khứ khi thêm tương lai.
- Pivot chỉ xuất sau hai right bars; equal highs/lows không sinh pivot strict.
- Wick không sinh BOS; BOS/CHoCH mirror chính xác; pivot chỉ break một lần.
- Sweep hai phía mơ hồ; event trùng không bị nhân đôi khi reconnect.
- FVG cần đủ3 closed bars; kiểm tra mọi vòng đời, expired và gap, không có tự-fill bởi nếnC.
- H1 thiếu1/12M5 không được ready; H1 đang chạy không được ảnh hưởng snapshot M5.
- Reconnect/replay với cùng event-time cho snapshot giống nhau; thiếu lịch sử trả warming.
- Golden OHLC so với tick aggregator hiện có; live broker M1 chỉ để đối chiếu sai số/source, không trộn lẫn OHLC hai nguồn mà không gắn nhãn.
- Trước/sau nghiên cứu: config revision, worker PID, binary hash và trạng thái exposure không bị hành động observer thay đổi.

Prototype M5 hiện đã có kiểm thử pivots, mirrored sweep/FVG, expiration, gap reset, exclude next-bar tick và gate→delayed entry. Các test observer H1/zones/reconnect nêu trên là acceptance cho bước triển khai sau, chưa tuyên bố đã đạt.

## Lệnh và thay đổi sau này

Hiện có: `./api backtest START END --config FILE --compare-smc --output DIR`. Trên máy đang chạy demo, build/test bản nghiên cứu bằng container offline với `dotnet build --no-restore -o /tmp/pa-bin`, rồi `dotnet /tmp/pa-bin/FxProOpenApi.dll check-backtest`; không build đè DLL runtime.

Dự kiến bước triển khai: lệnh offline `smc-snapshot` đọc cache, cutoff rõ và xuất JSON; lệnh này **chưa tồn tại**. Sau nghiệm thu offline mới xây overlay trong frontend canonical, bằng snapshot endpoint read-only. Chưa tạo API/live command hay overlay trong mục tiêu thiết kế này.

Phạm vi để sau: Order Block/Breaker, equal liquidity clusters, premium/discount, SMT divergence, economic-news filter, compound trade setup, stop/target mới, auto parameter optimization. Không thêm chúng trước khi có yêu cầu và cách kiểm chứng cụ thể.

## Nguồn và lý do lựa chọn

- [Repo backtest-expert](https://github.com/tradermonty/claude-trading-skills/blob/main/skills/backtest-expert/SKILL.md): dùng tinh thần luật rõ, kiểm tra thiên lệch/chi phí và độ bền; không dùng skill như mô hình dự báo.
- [LuxAlgo SMC](https://www.luxalgo.com/library/indicator/smart-money-concepts-smc/): đối chiếu tên cấu trúc BOS/CHoCH; thiết kế này tự định nghĩa pivot/lifetime, không tuyên bố tương đương indicator đó và không chép mã.
- [Capital.com FVG](https://capital.com/en-eu/learn/trading-strategies/fair-value-gap): đối chiếu hình học ba nến; không suy ra tỷ lệ thành công.
- [cTrader model messages](https://help.ctrader.com/open-api/model-messages/#prototrendbar): đối chiếu bar timestamp/volume trong nguồn; quote-count của cache vẫn không phải volume giao dịch tập trung.

Thành công của thiết kế: quy tắc đủ rõ để hai implementation độc lập cho cùng event/snapshot; trợ lý giải thích được nguồn, thời điểm biết và điều kiện mất hiệu lực; chưa cần lợi nhuận hay quyền giao dịch để chỉ báo tồn tại.
