# Aurum workspace

## Project and repository

Canonical project root on this machine: `/home/fiaboo/Projects/xauusd-system` (`~/Projects/xauusd-system`). Open this directory directly in future Codex sessions. Git remote: https://github.com/dinhvuong090997-cyber/c-bot (private), default branch `master`.

The current machine runs Linux with rootless Podman. This workspace tool shell is Bash; the user's interactive terminal may use Fish. GitHub writes currently use the connected GitHub plugin, account `dinhvuong090997-cyber`. GitHub CLI and local Git credential helper were absent at the last check. Do not infer browser login from plugin login.

## Architecture

- `openapi/`: .NET 8 C# app, OAuth, dashboard API, backtest and independent execution service.
- `openapi/dashboard/`: buildless English HTML/CSS/JS UI and self-hosted chart/font/icon assets. This is the canonical frontend.
- `cbot/AsiaSession.cs`: shared strategy rules compiled into the Open API app. The other cbot files are the earlier cTrader Automate variant.
- `MarketMonitor.cs`: separate read-only broker connection with an explicit request allowlist; price candles, position/account snapshots and recent fills.
- `ChartHistory.cs`: historical bid candles from local tick cache. Recorded-bar replay is visualization, not a new strategy simulation.
- Python scripts at the root are historical research. Some require the sibling `../xauusd-news` project and dataset; they are not the live execution engine.

## Services and private state

- `fxpro-execution`: trading worker, private Unix socket. Closing/restarting the dashboard does not stop this worker. No automatic trading activation after its own restart.
- `fxpro-dashboard`: HTTP on `127.0.0.1:8788`.
- User service `fxpro-data-recorder.service` / `fxpro-recorder` container: independent read-only live tick journal and hourly history recovery. See `openapi/data-recorder.md`; isolated runtime, never restart execution for data changes.
- User service `fxpro-tick-archive.service`: bulk read-only history downloader, current-year gaps then older interval scan. `./api archive-status`; see `openapi/tick-archive.md`. Independent of live recording/trading.
- `fxpro-openapi-auth`: OAuth UI on `127.0.0.1:8787`.
- Native system `tailscaled` and user service `fxpro-dashboard-phone.service`: private tailnet HTTPS, gateway on `127.0.0.1:8789`. No public Funnel.

Phone dashboard access: `https://fiaboo.mining-cobia.ts.net` now opens directly on allowed tailnet devices, no manual pairing key (`XAU_PHONE_TAILNET_ONLY=1`). Loopback gateway still enforces Host/Origin/CSRF and internal browser sessions. `/pair` is a compatibility entry to the same dashboard.

Private state is under `~/.config/fxpro-openapi/`: application credentials, OAuth tokens, execution config/risk journal, Unix socket and phone pairing data. Never print or commit those values. Pairing codes are not source code. Read-only monitoring does not alter account routing.

## Build and verification

From `openapi/`, `./api ui` builds with the pinned .NET SDK image and ensures worker/dashboard containers exist. It does not replace an already running process with the rebuilt DLL. Explicitly restart only the intended service after a backend change. A frontend-only change appears on reload.

With the existing dashboard container running:

```bash
podman exec fxpro-dashboard dotnet build FxProOpenApi.csproj --nologo
podman exec fxpro-dashboard dotnet bin/Debug/net8.0/FxProOpenApi.dll check-execution
podman exec fxpro-dashboard dotnet bin/Debug/net8.0/FxProOpenApi.dll check-execution-service
podman exec fxpro-dashboard dotnet bin/Debug/net8.0/FxProOpenApi.dll check-backtest
podman exec fxpro-dashboard dotnet bin/Debug/net8.0/FxProOpenApi.dll check-market
node dashboard/check_dashboard.mjs
```

These execution checks use fake broker connections. Browser QA is `check_dashboard_browser.mjs`; it refuses a writable production URL. Use `http://localhost:8788/preview/` on the running dashboard. Preview requests use `/preview/api/` and all writes are rejected server-side, without changing normal `/api/` mode. Preview shares the same process, port and canonical assets; there is no 8791 listener/container. `./api dashboard-preview` only prints the URL.

Local Playwright previously used module `/usr/lib/chatgpt/resources/cua_node/lib/node_modules/playwright/index.mjs`, Node `/usr/lib/chatgpt/resources/cua_node/bin/node`, and Chromium `/home/fiaboo/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome`. Override with `PLAYWRIGHT_MODULE` and `CHROMIUM_PATH`; check that these paths still exist. The user authorized local Playwright for UI QA without trading actions.

## Data and evidence

Tick cache: `openapi/data/`. Reports: `openapi/reports/`. Private QA screenshots: `openapi/audit/`. All stay local and are ignored by Git. `openapi/design-qa.md` describes the completed desktop comparison. Do not remove these datasets/results during routine cleanup. Keep runtime `bin/` files while services use them.

## GitHub workflow

The local repository is a shallow checkout of the published commit, with `origin/master` tracking it. Prefer normal Git when authenticated; the connected GitHub plugin can create blobs/tree/commit and update the branch with an expected SHA. Verify the remote head and tree after publishing. Do not force-reset/reinitialize this checkout or replace remote content again unless the user requests it.

## Local path migration

The repo was moved on the same filesystem to `~/Projects/xauusd-system` without restarting execution. The old Codex workspace path remains a compatibility symlink because existing Podman container mount definitions reference it; active mounts still point to the same directory inode. Do not remove that symlink until every dependent container has been recreated with canonical mounts during planned maintenance. New containers started through `openapi/api` from the canonical directory use the new paths. The phone gateway systemd ExecStart uses the canonical path; daemon-reload was sufficient, preserving paired sessions.

The optional historical `~/Projects/xauusd-news` path is a symlink to the original sibling research dataset; its files were not moved or copied. This keeps the existing research scripts usable.
