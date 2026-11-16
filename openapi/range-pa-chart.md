# Range PA chart — 2026-11-14

Open Backtests → Range PA on the existing dashboard (or /preview/ read-only). This is rule-based PA on actual tick-built threshold range bars, not ML-generated zones. The view is independent of selected backtest P&L; its inspector does not offer Apply.

- Range $2/$3/$5 per oz; recorded snapshots currently2026-04-28 through2026-04-30.
- Green demand/red supply rectangles use the same RangeSupplyDemand engine as the offline strategy, with base+two departures and first-retest/rejection rules.
- A zone is revealed only at its departure confirmation. It is then anchored to the earlier base for geometry; it is not visible if replay is before confirmation.
- R=first retest, PA=confirmed rejection, X=invalidated. Dashed ended zones retain explicit labels. Confirmed PA is an observation, not a broker order or proof of RR>=3.
- Terminal states include confirmed, invalidated, expired, replaced by a newer zone and reset after missing quotes/day transition. Events are recorded at actual UTC and become visible at the next visible closed bar; replay advances closed range bars, not every raw tick.
- Equal bar spacing with ordinal #bar axis; hover/header show actual UTC. Multiple bars can close in one second, so event indices avoid duplicate time keys or invented clock times. Overshoot remains at actual Bid prices.
- Latest zone focuses the most recent known PA; Fit all shows the full snapshot. Zoom/pan/price scale and replay update rectangles with chart coordinates. No fabricated volume pane for range data.
- The latest four known zones also have text labels with bounds/states, and status summary supports non-color identification. Original selected backtest metrics are explicitly labeled as separate.

No backend service restart was needed. The existing static-asset GET route serves local generated snapshots; assets are ignored by Git and contain OHLC/PA events only, not credentials or account metadata. Canonical frontend remains openapi/dashboard. No second dashboard copy, listener or browser screen activation was added. The trading worker/config/runtime DLL were not changed by chart loading.

Generate fresh snapshots with a temporary-built DLL:

`dotnet /tmp/pa-bin/FxProOpenApi.dll export-range-pa 2026-04-28 2026-05-01 dashboard/assets`

START/END must have complete cache files; end exclusive; at most3days per export. The exporter creates three ranges per day and replaces range-pa-index.json with that batch. Existing old snapshot files remain on disk. New clones do not include these ignored data assets; generate them before using Range PA. This first view is recorded data, not a live range feed. Real-time range integration and strategy activation are later work.

Source: RangeSupplyDemand observation callbacks emit lifecycle events without changing strategy conditions; RangePaSnapshot creates JSON; financial-chart.js projects zones/markers and computes causal replay frames. SVG overlay uses public logicalToCoordinate and priceToCoordinate APIs, pointer-events:none, clipped to the price pane. A rule/source SHA identifies each cache input.

Checks: .NET build0warnings/errors; backtest/SMC/range checks including event confirmation/retest timing passed. Pure JS replay test covers unknown-before-confirmation, lifecycle, bounds and appending-future-event invariance. Headless Playwright on /preview/ verified real SVG regions, replay, dates/ranges, fit,1280desktop, switching to ordinary candle/equity modes; no page/console errors or POSTs. Screenshots/evidence stay ignored in audit/range-pa-ui/. No physical monitor, mobile or screen-reader interaction was exercised.

## PA toolkit prototype

The Structure checkbox adds strict confirmed swing HH/LH/HL/LL markers and close-only BOS/Shift markers. Latest swings focuses recent bars; Latest PA explicitly moves the replay cursor to the last rejection confirmation so its historical decision is inspectable. The inspector shows regime, exact swing evidence and historical entry/SL/TP/RR or blocking reason. A broken supporting swing changes trend to Transition. See SPEC-PA-TOOLKIT.md for rules; these are research definitions, not automatic SMC interpretation.

Pivots require2left+2right closed bars, appear only after right confirmation, and are drawn back at the original pivot. Context resets at UTCday/>60s boundary gap. Equal neighboring extremes are rejected. The last40pivots/15breaks in current context are shown to reduce clutter. Zone detection remains unchanged; its base rule is SMALL BODY<=0.35range (not small total high–low range), with existing overshoot safeguards.

Setup illustration uses Bid close at existing PA confirmation, a zone-external stop with0.1range buffer/minimum$3distance, nearest confirmed swing target ahead, aligned structure and minimum3R. This is separate from backend departure-high/low targeting and excludes spread/slippage/fees/latency. Decisions freeze at signal, future bars do not change them; old setup clears at context reset. No performance curve/trade simulation is produced. Across current9snapshots:22PA confirmations,0eligible under combined prototype filters. Not evidence of profitability or a completed backtest.

Pure JS price-action checks pass (confirmation, ties, future invariance, gap reset, mirrored trends/breaks/3R, absent targets, trend invalidation). Expanded read-only browser checks pass for inspector, toggle, latest-swings/latest-PA navigation, replay and existing modes; no POSTs/errors. Evidence audit/pa-toolkit-ui ignored. Native frontend available on reload; no backend build/deploy/restart, worker remains running1position. Remote phone layout/pairing not tested.
