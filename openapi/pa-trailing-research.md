# Swing high/low trailing experiment — 2026-11-14

**Kết luận:** trailing theo swing mới giúp range3/5 giảm lỗ trong các case PA diagnostic nhưng không biến thành chiến lược có lãi; range2 xấu hơn. Bộ đầy đủ regime+minimum3R vẫn0lệnh, nên chưa đo được hiệu quả trailing cho bộ đó.

## Quy tắc giữ cố định

BUY nângSL tới swinglow mới trừmax(spread,0.1range);SELL hạSL tới swinghigh mới cộngbuffer. Pivot strict2left/2right, barpivot đóng sauentry, confirmation trướcquoteápdụng. Mỗi pivot chỉ dờiSL thành công1lần, không nớiSL/épbreakeven, không dờiTP. OldSL/TP kiểm tra trước; newSL chỉ có hiệu lực ởquote tiếp theo. BUY rounddown/SELLroundup cent,SL luôn phía hợp lệ của executablequote. GiáfillSL/gaps/slippage giữ modelcũ. InitialStop/initialRR giữ riêng, không dùng SLđãdời để làm đẹpRR.

Vốn16707.35,risk1%,DDhalt20%,minimumSLentry3,Asia+NY,swap/commission,slip0.10and0.20. Primary fullgate, swing>=3R bỏregime và diagnostic khônggates được so mirrors với/khôngtrailing. Không sửa entry/target để tạo thêm lệnh. Các kỳ resetđộc lập, đều đãxemtrước nên không gọi là pristineholdout.

## Diagnostic PA có lệnh — slippage0.10

**Bảng này bỏ gate3R/regime chỉ để đo ảnh hưởng thoát lệnh; không phải thay đổi yêu cầu3R của bản chính.** Returnnetequity tínhfees/swap/slippage và vịthếcuối.

| Kỳ | Range | Static return | Trailing return | DD static → trail | Lệnh static / trail | Số lần dờiSL |
|---|---:|---:|---:|---:|---:|---:|
| Jan–Feb | 2 | -3.837% | -3.973% | 3.931% → 3.997% | 188 / 188 | 23 |
| Jan–Feb | 3 | -2.464% | -2.333% | 2.850% → 2.719% | 145 / 145 | 6 |
| Jan–Feb | 5 | -1.870% | -1.843% | 2.268% → 2.241% | 73 / 73 | 3 |
| Mar–Apr | 2 | -3.201% | -3.269% | 3.259% → 3.328% | 214 / 214 | 17 |
| Mar–Apr | 3 | -2.451% | -2.320% | 2.592% → 2.461% | 122 / 122 | 8 |
| Mar–Apr | 5 | -1.401% | -1.243% | 1.829% → 1.672% | 58 / 58 | 8 |
| May–Jun | 2 | -1.859% | -1.937% | 1.963% → 1.937% | 156 / 156 | 11 |
| May–Jun | 3 | -1.569% | -1.417% | 1.613% → 1.461% | 86 / 86 | 7 |
| May–Jun | 5 | -2.163% | -1.884% | 2.524% → 2.245% | 39 / 39 | 9 |

## Giữ minimum3R

Fullregime+minimum3R:0lệnh mọi range,hai slip,cả3kỳ, cảstatic vàtrail. Swing>=3R bỏregime chỉ1lệnh range3 Jan–Feb nhưtrước; không có pivotpost-entryđủđiềukiệntrướcTP nên0lầndờiSL,return+0.1824%slip0.10/+0.1806%slip0.20 khôngđổi. Các kỳkhác0lệnh. Trailing không làm tín hiệu banđầu đủ3R hơn; nó chỉ thay cách bảo vệ vịthế đã mở.

## Stress slippage0.20 — diagnostic

| Kỳ | Range | Static | Trail | Số lần dờiSL |
|---|---:|---:|---:|---:|
| Jan–Feb | 2 | -3.948% | -4.087% | 22 |
| Jan–Feb | 3 | -2.660% | -2.529% | 6 |
| Jan–Feb | 5 | -2.031% | -2.004% | 3 |
| Mar–Apr | 2 | -3.390% | -3.462% | 17 |
| Mar–Apr | 3 | -2.692% | -2.561% | 8 |
| Mar–Apr | 5 | -1.515% | -1.357% | 8 |
| May–Jun | 2 | -2.238% | -2.320% | 11 |
| May–Jun | 3 | -1.756% | -1.599% | 7 |
| May–Jun | 5 | -2.283% | -1.983% | 9 |

## Kiểm chứng và giới hạn

- Build0warnings/errors; testsBUY/SELL,outwardrounding,onlytighten,formation/confirmation timing,onlyonceperpivot,validprice vàoldSLfirst đạt; existingbacktest/SMC/range checks đạt.
- Ledgeraudit114scenario/control runs và183adjustmentrecords trên các sensitivity/modes (không phải183trades độc lập): entry<pivotbarend<=known<apply, khôngrepeatpivot, monotoneSL,quote/targetside đúng,TPfrozen vàinitialRR đúng.
- PAstaticcases Jan–Apr khớp exact8metrics cũ. LegacyAsia baseline đầuJan cóthêm warmupDec28–31/2025 do bộarchivevừa tải, nên không soexact baselineđó với bản cũ thiếuwarmup; currentstatic/trail pairs dùngcùng toàn bộinputs. MainJan–Apr tickfileSHA khôngđổi; Mar–Apr warmupcũngkhôngđổi.
- Draft cho spread thu hẹp dời lạiSL cùngpivot được giữriêng *-spread-draft đểaudit; kếtquả chính đãrerun đúng1successfulmove/pivot, không chọnrule theoP&L.
- Brokerstop-amend latency/min-distance/rejection/queue/partialfills chưađược môphỏng. DờiSL khôngbảođảmbreakeven/profit; gaps cóthểfillxấu hơn.
- So sánh cấpstrategy; exit sớm cóthể làm khác exposure/lệnh sau, không mặcđịnh attribution giốnghệt từngentry. Chưa có kiểmđịnh ýnghĩa/outofsamplemới.

CLI `backtest START END --config FILE --compare-pa-toolkit --trail-swings --output DIR`. ReportresearchOnly từchốiApply; runtimeaudit/trailing-runtime vàevidenceaudit/pa-trailing ignored. `python3 check_trailing_results.py audit/pa-trailing` kiểmtra. Không đổi botdemo/dashboard/recorderservices.

Final service read-only check: worker is faulted with TaskCanceledException logged2026-11-14 05:09:25UTC,pendingOrder=null. Configrevision/originalDLLhash unchanged. Broker monitor reports1existing position withSL/TP. No automatic restart/order/control action performed. Do not interpret completed offline backtests as confirmation the execution worker is currently trading.
