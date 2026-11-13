# Session memory — 2026-11-13

Read `WORKSPACE.md` first for stable architecture. This file is a last-session snapshot; recheck live state.

## User decisions

- Desktop is the priority. English UI, chosen direction 1: Execution Terminal, dark charcoal/gold.
- Live and Backtest share the chart implementation with separate modes/data.
- Show worker heartbeat/status independently of demo/live account labeling; retain correct routing internally.
- Dashboard/browser closure must not stop execution or require Start again.
- Phone access uses Tailscale private HTTPS. No public tunnel.
- User explicitly asked to overwrite the old private `c-bot` repository with this project. Old commit history was preserved.

## Last completed work

- Deployed desktop Live chart M1/M5/M15/H1, real bid/ask, position Entry/SL/TP and account equity/P&L sampled approximately every 2 seconds.
- Backtest Equity, daily-close Drawdown, selected-trade/full-period candle charts and recorded candle replay.
- Fixed chart CSP, history pagination bounds, stale selection handling, short replay restart and desktop layout density. Stop acknowledgement/race protections retained.
- Removed `dashboard-next`, redundant source backups, old logs/Python caches, temporary QA scripts and the stopped preview container. About 2.3 MB removed. Tick data, reports, credentials and runtime binaries retained.
- Consolidated portable browser QA as `openapi/check_dashboard_browser.mjs`; added root Git ignores and refreshed setup docs.
- Published 77 source/assets files to private `dinhvuong090997-cyber/c-bot`, `master`, commit `93c79ad77915907aea05e4211e9496cc3ff564f2`. Tree `c8b5f1d0be503b6630b524e16694f0d1721ae151` matched local exactly. Parent is the old project head `82e84cd8633c03b48b259d7cd0522a0da362a604`.
- Local Git was synchronized to that exact commit as a shallow checkout; working tree was clean before adding these handoff documents.

## Verification and service snapshot

.NET build passed with zero warnings/errors. Execution/history, worker isolation, backtest, market, Stop UI race, research sizing, Python/shell syntax and phone pairing checks passed. Playwright passed Live timeframes/fit, Equity/Drawdown, trade/full-period candles, H1, replay, trade navigation, settings/config drawer and 1280px layout. Final browser run had no console/page errors or POST requests. Staged source was checked against actual private cTrader secrets and token/key patterns; none found. Private artifacts were verified ignored.

Last read-only production check: worker active/running, heartbeat age 0.2s; market connected, quote age 0.3s. Worker was not restarted during cleanup/publishing. These are historical observations, not a promise of current state. No real broker order was placed as verification.

## Known follow-ups and limits

1. `openapi/api` currently publishes a port only for OAuth connect/UI paths; `./api dashboard-preview` does not yet map host port 8791 despite the README suggesting it. Fix the wrapper by adding the localhost 8791 mapping for that mode before relying on the documented preview command. Previous browser QA used a dedicated container with explicit port mapping, now removed. The backend preview/read-only behavior itself was tested.
2. Physical phone rendering, screen-reader behavior, real partial fills and live-broker failure scenarios were not exercised by this desktop QA. Fake checks cover the existing safety paths.
3. Historical Python research has external sibling/dataset dependencies; it is not the primary app setup path. Some old CSV results predate sizing corrections and were not regenerated.
4. Private screenshot/report evidence is intentionally not on GitHub. Do not claim a fresh clone contains the tick cache or completed backtest results.

## Next session

Inspect Git status, read these docs, and check service heartbeat before changing anything. If the user asks to continue verification, address the preview wrapper port mapping first. Keep changes scoped to the requested service and update this file when done. Never store credentials, account passwords, access/refresh tokens or pairing codes here.
