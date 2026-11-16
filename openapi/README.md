# FxPro cTrader Open API

Công cụ C# .NET 8 chạy trên Fedora bằng Podman. Lưu Client ID/Client Secret từ ứng dụng Open API đã được duyệt, nhận token OAuth từ trình duyệt và liệt kê tài khoản được cấp quyền qua WebSocket JSON có TLS.

## Thiết lập

Trong [Applications](https://openapi.ctrader.com/apps) của cTrader, thêm Redirect URI chính xác:

```text
http://localhost:8787/callback
```

Tại Terminal, chạy các lệnh sau từ thư mục này:

```bash
./api setup
./api connect
```

Lệnh setup hỏi Client ID và Client Secret, ẩn ký tự secret. Khi connect in đường dẫn local, mở trong trình duyệt trên cùng máy, đăng nhập cTrader và chọn tài khoản cần cấp quyền. Token lưu tự động vào ~/.config/fxpro-openapi/tokens.json, quyền 600. Thông tin ứng dụng ở app.json cùng thư mục với quyền 600. Callback chỉ mở trên localhost của máy, dùng cookie phiên và đường dẫn kết nối ngẫu nhiên để xác minh luồng OAuth. Phiên hết hạn sau 10 phút.

Xem tài khoản sau khi kết nối:

```bash
./api accounts
```

CLI tự refresh token nếu sắp hết hạn, lưu cả refresh token mới theo cơ chế thay file nguyên tử. Tài khoản hiển thị số login broker và ctidTraderAccountId dùng trong API. Hai số có thể khác nhau. Tên môi trường trong kết quả dùng để chọn máy chủ kết nối.

## Trạng thái

Đã biên dịch công cụ và kiểm tra callback sai bị từ chối, redirect OAuth đúng scope trading và cookie phiên HttpOnly. Đã xác thực OAuth thật và lấy được tài khoản FxPro demo được cấp quyền. Phần nhận giá XAUUSD, đồng bộ vị thế, đặt lệnh và dashboard chưa nối vào công cụ này.

Lượt backtest cTrader CLI cũ dừng ở 0% sau đăng nhập. Các lượt chẩn đoán đã dừng khi chuyển sang Open API. Kiểm tra trực tiếp tiến trình host trong image thấy nó yêu cầu WindowsDesktop runtime trên Linux, nhưng thay file cấu hình chưa giải quyết được triệu chứng. Nguyên nhân đầy đủ của việc đứng 0% vẫn chưa xác minh.

## Trang cấu hình local

`./api start` mở dịch vụ nền tên `fxpro-openapi-auth` ở http://localhost:8787/. Trang này hoạt động cả khi chưa có app.json và cung cấp form nhập Client ID/Client Secret. Nút kết nối chuyển sang trang cTrader để chọn tài khoản và cấp quyền. Callback cũ thiếu phiên hợp lệ sẽ hiện liên kết quay lại trang cấu hình. Dịch vụ tiếp tục chạy sau khi lưu token.

Dừng dịch vụ bằng `podman stop fxpro-openapi-auth`. Khởi động lại bằng `./api start`. Cổng host chỉ bind 127.0.0.1.

## Dữ liệu và backtest local

```bash
./api export 2026-01-01 2026-05-01
./api check-backtest
./api backtest 2026-01-01 2026-05-01
```

Ngày bắt đầu bao gồm, ngày kết thúc không bao gồm; chỉ tải các ngày UTC hoàn tất. Lệnh export chỉ yêu cầu metadata và dữ liệu lịch sử, không gửi lệnh giao dịch. Tệp CSV gzip theo ngày ở `data/fxpro-v2`; dữ liệu hoàn tất được cache, không tải lại. Nếu kết nối gián đoạn, chạy lại cùng lệnh để tiếp tục từ ngày chưa có tệp hoàn chỉnh. Có thể xóa riêng tệp ngày cần tải lại. Tốc độ tối đa bốn yêu cầu mỗi giây trên mỗi tiến trình; không chạy nhiều downloader song song trên cùng ứng dụng.

Giá và thời gian tick được giải mã từ delta theo phản hồi thực tế. Bid/ask được tải riêng và ghép lại theo millisecond. Khi trang API còn dữ liệu, bỏ toàn bộ tick ở millisecond cuối của trang đó rồi yêu cầu lại với toTimestamp bằng mốc ấy cộng 1 ms, đồng thời lọc phần chồng lấn. Server thực tế loại cận trên, nên cộng 1 ms là cần thiết để tránh mất tick. Cache thử ban đầu ở data/fxpro thiếu tick ranh giới và không dùng cho báo cáo cuối. Tệp chưa hoàn tất dùng đuôi .tmp. `./api export audit` tải nến M1 ngày 02/01/2026 để đối chiếu độc lập với giá tick; `./api export probe` chẩn đoán định dạng phản hồi, không in thông tin xác thực.

Mô phỏng liên kết trực tiếp `../cbot/AsiaSession.cs`, không sao chép luật tín hiệu. Chạy RR 1,5/2 với vốn 50k/100k, trượt market 0/0,10 USD/oz, đồng thời có các lượt tắt swap để đo độ nhạy. Chạy cả kỳ liên tục và từng tháng độc lập. Khối lượng theo bước 1 oz của metadata broker, risk 0,25%, trần notional với đệm 1%, ngưỡng ngừng mở lệnh mới khi drawdown số dư chạm 5%. Giá khớp đầu vào sau trễ 1 giây, SL theo quote thực thi kế tiếp, TP theo giá limit; không đóng theo giờ hay ép đóng cuối kỳ. Khi bid/ask cùng millisecond có nhiều giá, dùng bid thấp nhất và ask cao nhất để tránh kết quả khớp có lợi do thứ tự không xác định.

Commission đọc từ metadata. Swap dùng mức hiện tại hồi chiếu cả kỳ, vì API metadata không cung cấp lịch sử mức swap. Rollover dùng 21:59 UK theo công bố FxPro, có DST, triple swap thứ Tư; chưa đối chiếu lịch sử thu phí của nền tảng. Giá trị equity cuối kỳ gồm ước tính phí đóng vị thế còn mở. Dữ liệu tick không chứng minh khả năng khớp thật. Giai đoạn 01–04/2026 không thuộc kỳ so RR trước đó, nhưng nghiên cứu cũ từng xem dữ liệu cùng giai đoạn nên không phải tập chưa từng quan sát.

`check-backtest` xác minh trễ vào lệnh, một vị thế, TP limit, SL gap, trượt giá, commission/khối lượng, triple swap, tín hiệu hết hạn, profile hoàn tất và DST. Kết quả ở `reports/fxpro-START-END/results.json`, cùng dữ liệu từng lệnh và equity ngày. `make_report.py` dùng matplotlib để tạo CSV, biểu đồ PNG và báo cáo Markdown từ các kết quả ấy.

Đối chiếu dữ liệu: chạy `./api export audit`, rồi `python3 audit_ticks.py`. Ngoài đối chiếu nến M1, bốn phút được tải riêng và so sánh từng tick, gồm cả tick ở ranh giới trang. Một số cực trị nến M1 do FxPro lưu khác tick endpoint vài cent/oz; báo cáo audit lưu chênh lệch này, không sửa tick theo nến.

## Dashboard (English, local)

```bash
./api ui
```

Open http://localhost:8788/. The service runs in the `fxpro-dashboard` container, published only to 127.0.0.1. It shares the existing private OAuth configuration, and never serves tokens or secrets. Manage OAuth separately at http://localhost:8787/.

- Execution Terminal reads broker balance, equity, net unrealized P&L and positions continuously (approximately every 2 seconds), with quote/account freshness indicators. Live bid candles support M1/M5/M15/H1, Entry/SL/TP overlays and chart fit. The separate read-only market connection cannot send trading requests.
- Backtests shows completed data-v2 reports, period/capital/slippage filters, interactive equity/daily-close drawdown curves, historical bid candles and recorded-bar replay and run comparison. Trades supports session/direction filters and CSV export.
- New backtest changes RR, capital, risk, drawdown halt, minimum SL, spread multiplier, slippage, swap and sessions. Dates must already have complete local tick files. Runs execute as local offline child processes and save a separate custom report, with up to four available prior days used only as signal warm-up.
- Save preset stores one research preset in the private configuration directory. Apply to bot selects a result/account; Start separately enables execution through the independent worker. Stop entries keeps existing broker SL/TP. The LIVE badge follows worker heartbeat.
- POST endpoints require JSON, same-origin checks and a CSRF token. Configs are bounded and validated; report and run paths are allowlisted. Only one custom replay can run at a time.

Dashboard assets are buildless HTML/CSS/JS under `dashboard/`; backend is `DashboardServer.cs`. Use `podman restart fxpro-dashboard` after a backend rebuild. Asset changes appear on reload. Desktop chart/replay navigation was verified with local Playwright. QA evidence is described in `design-qa.md`; private screenshots stay local.

## Private HTTPS through Tailscale

The phone gateway (`phone_proxy.py`, user service `fxpro-dashboard-phone.service`) binds to `127.0.0.1:8789`. Tailscale Serve exposes it only inside your tailnet over HTTPS; no public Funnel. Set `XAU_PHONE_ORIGIN` to your exact Tailscale HTTPS origin and `XAU_PHONE_BIND=127.0.0.1` in the service environment. `phone_tailscale.py` supports login, enable and status. Both devices must join the tailnet.

Open `/pair` on the Tailscale hostname. The eight-digit pairing code is private in `~/.config/fxpro-openapi/phone-pairing.json` (600). Pairing grants a one-day opaque session; failed attempts are rate limited. Account/report APIs require pairing, and forwarded writes retain origin and CSRF validation. OAuth is managed from the desktop at localhost:8787. Restarting the gateway invalidates its in-memory sessions.

Phone pairing compatibility: a valid pairing POST now returns the dashboard HTML directly (HTTP 200), without a 303 redirect. The page receives an opaque gateway session and uses an Authorization header for API requests; sessionStorage keeps it across reloads when available. This also works without cookies, while retaining the HttpOnly cookie path. The gateway session is not a cTrader token and never enters the URL. Only the static UI shell/assets are public; report/account APIs still require a valid paired session. Pair again at `/pair` after a gateway restart. The cookie-disabled path, protected APIs and POST validation were checked over HTTP.

Native-form origin fix: pairing pages now use `Referrer-Policy: same-origin`, since `no-referrer` can cause native form navigation to send `Origin: null`. Pairing additionally requires a signed, ten-minute, single-use hidden form token, allowing null/missing Origin without removing CSRF protection. Explicit foreign origins remain rejected. API writes with null/missing Origin require a valid explicit bearer session and the dashboard CSRF token. Run `python3 check_phone_pairing.py` to verify same/null/missing origins, cookie-free access, nonce replay rejection and protected API validation.

## Apply a backtest to execution

Select a completed run → **Apply to bot** → choose an authorized FxPro account → **Apply selected config**. Review the saved account number and parameters, then **Start bot** explicitly enables order routing. Apply alone never trades. Demo/live endpoint selection follows broker authorization internally. The green LIVE indicator is a recent worker heartbeat, not a promise of quote freshness or profitability.

Only RR, risk percent, closed-balance drawdown halt, minimum stop, spread multiplier and entry sessions transfer. Date range, simulated capital, swap switch and simulated slippage do not. Execution uses actual USD balance, broker commission/swap/fills, the original $0.17/oz sizing buffer and ~1× notional cap. Execution SL/TP distances are attached to the market request as broker-relative protection.

**Stop entries** finishes checking an in-flight order and stops further entries. It does not close protected positions or cancel broker SL/TP. There is no autostart after service/machine restart and no automatic resend/reconnect after ambiguous orders. A persistent unknown-order or risk/protection halt requires account/journal review before resetting; the UI deliberately has no blind reset. Use a dedicated account: manual/external trading can race the last exposure check. All existing account positions and orders block entries.

Startup downloads the latest valid Asia session within four calendar days and today’s Asia ticks from the selected account and endpoint. It builds profiles with the same delta decoder, tied-millisecond merge and AsiaSession rules as the replay. It then subscribes to live spots, backfills the startup gap and replays buffered spots in timestamp order. History never sends orders; entries need fresh updates of both bid and ask after bootstrap. Empty/holiday sessions do not create profiles. Incomplete pagination fails closed. Stop also cancels bootstrap between API requests. Connection loss stops entries; broker-side protection remains. Keep this Linux machine and execution service running; the dashboard is optional. USD full-access hedged/netted accounts only; guaranteed-stop accounts are unsupported. A protection failure requests emergency close, latches halt, and requires checking cTrader for final closure.

Offline execution checks: `./api check-execution`. Protocol source: https://github.com/spotware/openapi-proto-messages (market order relative protection, hundredth-unit volume, account routing and execution events). Real-money fills, partial fills, broker disconnections and physical mobile rendering still require broker/demo validation; tests never send trading requests.

## Independent execution service

`./api ui` now ensures two separate containers: `fxpro-dashboard` serves the UI and research APIs; `fxpro-execution` owns the trading worker. They communicate through an owner-only Unix socket in the private config directory, with no new public port. `./api worker` starts only the execution service in READY state.

Closing the browser, stopping/restarting `fxpro-dashboard`, or restarting the phone gateway does not stop an active execution worker. Reopening the dashboard reconnects to the existing worker and config; it does not require Start again. Only **Stop entries** explicitly stops entries. The worker still has no automatic order activation after its own process or machine restarts; existing broker-side SL/TP remain in place.

The first upgrade from the combined process requires stopping the old worker, restarting the dashboard once, and pressing Start once to activate execution in its new service. Check service logs with `podman logs fxpro-execution`; dashboard logs no longer contain the worker events. Restart the execution container only when intentionally updating/stopping the worker.

`./api check-execution-service` uses a fake broker and a private temporary socket to verify that an active worker survives closed dashboard connections and a new dashboard client, retains its config, accepts explicit Stop, and reports unavailable service correctly. No broker orders are sent by this test.

## Audit fixes and private phone access

Phone access now uses **https://fiaboo.mining-cobia.ts.net/pair** through Tailscale Serve. Both devices must use the same tailnet. The Python gateway binds only to 127.0.0.1:8789 and accepts the configured HTTPS origin, Secure cookies, and the existing bearer/CSRF checks. The old 192.168.1.81:8789 LAN URL is closed. No Funnel or public Internet endpoint is enabled.

`python3 phone_tailscale.py login` uses the existing native Tailscale daemon. After login, `python3 phone_tailscale.py enable` configures HTTPS Serve and the gateway user-service environment; `status` prints only state and phone URL. Native Tailscale manages its system state; old container state is retained only for rollback. Install Tailscale on the phone and sign in to the same account.

Regression checks now cover queued Stop versus Start, accepted/partial/full-fill and protection-order events, durable pending-order resolution after fresh protection checks, and account cache identity. `node dashboard/check_dashboard.mjs` checks request timeout, heartbeat expiry without responses, clearing previous trades, and ignoring late responses. `python3 ../check_research_sizing.py` verifies that the older Python studies size from signal prices rather than future fills; regenerate their old CSV results before comparing them. Their previous CSVs were not rewritten. The C# RR5 strategy/results are unchanged.

`make_report.py` accepts custom RR/capital/risk/DD/slippage and all-swap-off reports, including no-loss profit-factor values. It requires matplotlib in the reporting environment. Existing results.json files are never changed by report generation. A read-only-filesystem integration check verifies that failed backtest creation releases its job lock and starts no replay process.

## Verification

Run `./api check-execution`, `./api check-execution-service`, `./api check-backtest`, and `./api check-market`. These checks use fake broker connections and never place broker orders. `node dashboard/check_dashboard.mjs` covers UI deadlines, stale results, heartbeat and Stop acknowledgement races.

For desktop browser QA, use http://localhost:8788/preview/ on the running dashboard (all preview POSTs rejected), then run `node check_dashboard_browser.mjs` from this directory with Playwright/Chromium installed. Optional `PLAYWRIGHT_MODULE`, `CHROMIUM_PATH`, `DASHBOARD_URL` and `QA_OUTPUT` override module, executable, preview URL and evidence output. The test requires an authorized account and completed local reports/tick data. It refuses the writable root dashboard. Preview uses the same process, port and `dashboard/` assets; no preview container/listener is needed. `./api dashboard-preview` only prints this URL for compatibility.

Cached data/reports are intentionally retained locally during cleanup. Do not delete `bin/` while running containers use its DLLs. Build caches (`obj/`), Python caches, temporary logs and old source copies can be regenerated.


## Research-only M5 confirmation

`./api backtest 2026-01-01 2026-05-01 --compare-pa-m5` compares every original scenario with an otherwise identical M5-filtered scenario. Add `--config FILE` to compare one existing research configuration. Default comparison reports use a separate `-pa-m5` directory; `--output DIR` can select a private research directory.

The filter requires the immediately preceding UTC-aligned five-minute **bid** candle to close above its open for BUY, or below for SELL. Doji blocks both. Current-candle prices never confirm entries. Candles must have observations within five seconds of both boundaries; skipped buckets and partial startup candles do not confirm. This checks boundary coverage, not every internal tick gap. Confirmation is rechecked at the delayed entry quote. Spread, session, sizing, costs, exits and drawdown rules remain unchanged. This is a direction-only candle experiment, not an engulfing/pin-bar or Asia-breakout strategy.

Comparison reports are marked `researchOnly` and rejected by execution config mapping. No UI or live execution filter is enabled. A fresh initial balance is needed when comparing later subperiods after an earlier drawdown halt. Existing Jan–Apr 2026 data has already been researched; it is not pristine unseen validation.


## SMC research branch

`./api backtest START END --config CONFIG.json --compare-smc --output OUTPUT` runs baseline, M5 direction, M5 structure break, sweep and FVG-formation filters at configured slippage and 2x slippage. Requires a custom config with slippage > 0 and <= 1; do not combine `--compare-pa-m5`. The default output directory ends in `-smc`; reports are research-only and cannot be applied to execution. Existing live strategy and canonical dashboard remain unchanged. See [research results](smc-research.md) and [observational indicator design](SPEC-SMC.md). No SMC chart overlay or live signal integration is deployed.


## Range-bar supply/demand PA (offline only)

`./api backtest START END --config FILE --compare-range-pa --output DIR` compares range sizes 2/3/5 USD/oz at fixed RR2 and R3 at RR5 with the Asia baseline, at configured and 2x slippage. `--compare-range-hl` instead targets the known departure high for demand or departure low for supply; the R3/RR5 variant remains a fixed-target control. Do not combine comparison flags. Both require a custom config and slippage >0 and <=1. Default artifacts go under ignored `audit/`, not the dashboard report collection. While demo runs, build to `/tmp/pa-bin` in an offline container rather than overwriting runtime binaries.

These are real-price threshold range bars, not exact-size synthetic gap-fill bars. See [range PA design and all results](range-pa-research.md). High/low runs report `rr:null` because RR varies, with actual initial RR and zone/target evidence in `*-range-details.json`. Read the dedicated Markdown report; canonical dashboard and generic `make_report.py` do not present variable-RR range research. No range bar chart, strategy or execution config is deployed. Research-only reports cannot be applied to the worker.

Add `--require-3r` to `--compare-range-hl` to reject entries with actual rounded TP/SL reward/risk below3, using the delayed executable entry after spread/slippage. It applies only to the high/low variants; baseline and fixed-RR control stay unchanged. This geometric RR does not subtract commission/swap, which remain in net P&L. Runs expose `minimumEntryRR` and `skippedRR`, use separate names/directories and never alter the saved worker config.


## Kronos-small offline pilot

`export-kronos START END OUTPUT.json` exports causal H1 Bid bars/session cutoffs through the existing quote reader. `kronos_probe.py ROOT` runs reviewed pinned local model/tokenizer code and safetensors in a separate CPU container. Missing volume/amount is zero-filled per upstream OHLC-only API. `python3 -B check_kronos.py` checks preparation causality without ML dependencies. `backtest START END --config FILE --kronos-signals forecasts.json --output DIR` replays full baseline, forecast-coverage control and agreement filter at configured/2x slippage. It requires custom config and cannot combine comparison flags. Forecast timestamps/source cutoffs are validated; default reports are private audit artifacts and research-only. Do not attach this pilot to the trading worker. See [all results, pinned versions and limitations](kronos-research.md).


## Rule-based PA overlay on recorded range bars

Backtests → Range PA shows supply/demand rectangles and retest/confirmation/invalidation markers computed by the shared range engine. Date/range selection, Latest zone/Fit all and causal bar replay are read-only. Initial snapshots cover Apr28–30,2026 at $2/$3/$5; data JSONs under dashboard/assets are ignored and regenerated by `export-range-pa START END dashboard/assets` (up to3days). No live range feed or trading activation is added. See [chart behavior and verification](range-pa-chart.md).

Host Tailscale migration: `phone_tailscale.py` now uses the existing system Tailscale daemon and never creates a container. `status` is read-only. If Serve permission is denied, an administrator must run `sudo tailscale set --operator=fiaboo` before `python3 phone_tailscale.py enable`. Migration completed: native HTTPS verified, old container stopped with restart disabled. The old container URL is retired.

## Continuous live data recorder

`./api recorder` installs/starts the independent read-only XAUUSD collector; `./api recorder-status` reads its coverage and freshness. It journals live sides, recovers settled UTC hours after outages and publishes complete daily gzip caches without replacing existing reports/data or restarting trading. See [data-recorder.md](data-recorder.md) for paths, recovery, startup and limitations. The current PA chart is still recorded research.

PA toolkit offline comparison: `backtest START END --config FILE --compare-pa-toolkit --output DIR`; see [pa-toolkit-backtest.md](pa-toolkit-backtest.md). This uses confirmed swing targets and optional regime/minimum3R, separate from legacy departure-high/low tests. All comparison reports are research-only.

Bulk historical XAUUSD data: `./api archive` enables the independent resumable downloader; `./api archive-status` shows progress. It preserves existing data/metadata, fills current-year gaps then scans older intervals without assuming a retention cutoff. See [tick-archive.md](tick-archive.md).

User-supplied Quantt Mathematics/Finance PDFs were reviewed; [quantt-cheatsheet-notes.md](quantt-cheatsheet-notes.md) records applicable ideas, limitations and implementation status.

PA event outcome audit (not trading P&L): `audit-pa-paths START END OUTPUT` with frozen5/30minute horizons; see [pa-path-audit.md](pa-path-audit.md). Uses all confirmations and separately labels hypothetical3R vsSL vs time without changing the real swing-target strategy.

Swing trailing research: add `--trail-swings` to `--compare-pa-toolkit` for paired static/trailing comparisons. See [pa-trailing-research.md](pa-trailing-research.md); no execution activation.

## Direct Tailscale access (no pairing key)

The phone gateway now uses `XAU_PHONE_TAILNET_ONLY=1` behind native HTTPS Tailscale Serve. Open https://fiaboo.mining-cobia.ts.net directly; `/pair` also opens the dashboard. Tailnet network access replaces manual key entry; ephemeral secure browser/bearer sessions are created automatically, while Host/Origin and backend CSRF validation remain. This mode refuses plain LAN/non-HTTPS/non-ts.net configuration. Legacy pairing remains the default when the flag is absent. `check_phone_tailnet.py` uses a fake upstream and tests keyless/expiry/cookie/webview access, legacy form replay, guards and invalid deployment config. Existing `check_phone_pairing.py` applies only to a legacy paired-mode test gateway.
