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

1. Resolved preview port issue: preview now uses `http://localhost:8788/preview/` in the existing dashboard process. `/preview/api/` is read-only per request; normal `/api/` remains writable with its existing protections. Removed the separate C# preview command/listener; the wrapper alias only prints the URL. No extra container/port is needed. OAuth 8787 stays because its callback is registered with cTrader; 8789 stays as the private Tailscale gateway backend. Do not change the registered redirect URI implicitly.
2. Physical phone rendering, screen-reader behavior, real partial fills and live-broker failure scenarios were not exercised by this desktop QA. Fake checks cover the existing safety paths.
3. Historical Python research has external sibling/dataset dependencies; it is not the primary app setup path. Some old CSV results predate sizing corrections and were not regenerated.
4. Private screenshot/report evidence is intentionally not on GitHub. Do not claim a fresh clone contains the tick cache or completed backtest results.

## Next session

Inspect Git status, read these docs, and check service heartbeat before changing anything. Preview consolidation is deployed; use the shared-port URL for future QA. Keep changes scoped to the requested service and update this file when done. Never store credentials, account passwords, access/refresh tokens or pairing codes here.

## Preview consolidation verification

Build and UI Stop/routing checks passed. HTTP checks confirmed preview HTML/status, rejection of preview POSTs, and independent normal-mode status. Dashboard-only restart preserved execution PID, config revision and active state. No broker control action was performed. Playwright on the shared-port preview passed all chart/replay/navigation checks with zero console errors or browser POSTs. Browser QA uses the existing 8788 service and requires no preview container. The user asked to simplify the number of ports; keep routine access on the dashboard URL.

## Canonical project move — 2026-11-13

The user requested moving the repo out of the generated Codex workspace. Its canonical location is now `/home/fiaboo/Projects/xauusd-system` (`~/Projects/xauusd-system`); open that folder directly next session. All source, `.git`, tick data, reports and private QA artifacts moved together by same-filesystem rename, without copying or dropping data. Credentials remain outside the repo in their original private config directory.

The old workspace `work/xauusd-system` is a compatibility symlink. Existing execution/dashboard/OAuth container definitions still name that path; their live bind mounts retain the same directory inode. Keep the old symlink until those containers are deliberately recreated with canonical mounts during planned maintenance. No worker restart or trading control action occurred during this move. New containers launched from the canonical repo path use the new paths.

Updated the phone gateway user service ExecStart to the canonical source path and ran daemon-reload without restarting the gateway, preserving paired sessions. Added `~/Projects/xauusd-news` as a symlink to the original optional historical dataset so sibling research paths continue to resolve. The original dataset itself was not moved.

Verification: Git head preserved; worker PID, active state and execution revision unchanged; gateway PID unchanged. Dashboard, read-only preview and phone gateway assets/pair page responded successfully; market feed connected. A temporary container using the new canonical bind mounts passed the fake backtest checks and was removed automatically. UI Stop/routing regression checks passed from the new directory. No physical phone interaction or real trading order was part of this migration verification.
