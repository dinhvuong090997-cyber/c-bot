# Execution Terminal design QA

Final result: passed

Source visual truth: `audit/before-terminal/selected-design.png` (selected direction 1, Execution Terminal). Original source 1487 × 1058 px, normalized to 1440 × 1024 for comparison. Browser CSS viewport 1440 × 1024, deviceScaleFactor 1. Additional desktop 1280 × 900 checked. Dark theme, connected FxPro account, running worker with one position. Source financial numbers are illustrative; implementation uses actual read-only broker data. Preview disables financial controls intentionally.

## Evidence and comparison history

- First comparison: `audit/terminal/comparison-1.jpg`, source and rendered Live in one input. P2: inspector stretched the main chart and pushed journal rows below the 1024px fold. P2: completed research banner consumed chart/replay space. Fixed inspector padding/line spacing, bounded journal scrolling, and hide completed progress banner. Earlier CSP and candle pagination failures were fixed before the connected-state comparison.
- Post-fix full comparison: `audit/terminal/comparison-2.jpg`; focused header and inspector comparisons: `comparison-header.jpg`, `comparison-inspector.jpg`. These show source and implementation together. Source normalized equally for the full/header comparison; inspector crops magnified independently for reading, not pixel measurement. Revised rendered Live: `live-2.png`. Journal rows now visible at 1440 × 1024.
- Other rendered states: `equity.png`, `drawdown.png`, `price.png`, `settings.png`, `config.png`, `live-1280.png` under `audit/terminal/`. Equity/Drawdown captures wait for canvas paint. At 1280 × 900 the page scrolls vertically to journal rows; persistent controls remain visible and no horizontal overflow occurs.

## Required fidelity surfaces

- Typography: locally hosted Inter; compact metadata, clear title/quote/P&L hierarchy, consistent tabular financial numbers. No clipped labels in tested desktop sizes. Heading 28px, chart labels 11px; source family inferred visually rather than asserted from an unavailable font spec.
- Spacing/layout: 205px sidebar, large primary chart, 330px inspector, compact account strip and journal below. Post-fix major region proportions follow the reference. Backtest adds report selectors and research metrics; chart/replay remain accessible.
- Colors/tokens: charcoal background #101214, panel #171b1e, muted borders, warm gold #d4b477, green #7bd3a7 and red #e7868b. Disabled preview controls intentionally dim; production uses normal enabled color.
- Images/icons: generated transparent Aurum logo inspected at display size, library Phosphor SVG icons with local assets/licenses. No handcrafted replacement logo/icons. TradingView attribution preserved.
- Copy/content: English UI; actual account/quote/position/fills replace illustrative numbers. Tick activity is labeled, daily-close drawdown distinguished from intraday maximum, recorded replay distinguished from rerunning a strategy. Stop explains that it stops entries and retains broker SL/TP.

## Interaction and runtime checks

Playwright local, HTTP localhost preview, actual market/cache data. Live M1/M5/M15/H1, chart fit including trade levels, Equity/Drawdown/Trade price, full-period candle aggregation, H1, trade selection, replay play/pause/scrub, trade-row navigation, settings, configuration drawer and 1280px overflow checked. No browser POST requests, no financial controls activated. Console errors/page errors/failed HTTP responses: none in final run (`audit/terminal/browser-results.json`). Keyboard focus styles and semantic buttons/selects retained; no screen-reader session performed.

Backend build: zero warnings/errors. Market checks verify prohibited trading messages, candle decoding, chronological aggregation, account isolation and cached OHLC/missing-day handling. Existing execution/history, service isolation, backtest and Stop-race regression checks pass with fake connections; no real orders sent.

## Findings

No actionable P0/P1/P2 findings remain for the desktop scope. Expected differences: actual prices change chart shape; journal lists real broker fills, not invented SL/TP/quote events; no account selector in account strip (selection remains in Settings). TP can be outside the current price view; Fit includes all levels and inspector always shows values.

## Follow-up polish / limits

P3: logo typography/crop is close to the supplied visual direction but not a recoverable original vector asset. Phone and assistive-technology QA are outside the PC-focused visual acceptance. Trading Start/Stop/Apply was not exercised against the real broker; Stop behavior is covered by the existing fake UI/backend regression tests.

## Implementation checklist

- [x] Source/rendered comparison and post-fix capture
- [x] Five required visual surfaces
- [x] Desktop chart/replay interactions and browser console
- [x] Existing safety regressions and read-only feed tests
- [x] No strategy/config or worker lifecycle changes

## Local deployment verification

Updated dashboard at http://localhost:8788/. Production browser capture: `audit/terminal/live-production.png` (1440 × 1024, connected, real position); zero console/page errors and no horizontal overflow. Worker PID, active state and config revision remained unchanged (`audit/terminal/deployment.json`). Gateway updated; phone pairing/security regression checks pass. Preview container stopped.
