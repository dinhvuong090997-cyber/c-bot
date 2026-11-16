# Independent XAUUSD data collection

The read-only recorder is separate from the execution worker and dashboard. It keeps collecting even without a browser or an entry signal. Source identity is pinned to the saved FxPro demo account when first started; changes to another account fail closed rather than mixing datasets. It cannot send order/position/config mutation requests (deny-by-default connection wrapper). Credentials are mounted read-only; no token refresh or pairing changes.

## Operation

From openapi:

```bash
./api recorder                 # build isolated runtime, run checks, enable/start recorder only
./api recorder-status          # read persisted status, no broker request
systemctl --user status fxpro-data-recorder.service
journalctl --user -u fxpro-data-recorder.service -n 20
```

Updating its code requires stopping ONLY `fxpro-data-recorder.service`, then `./api recorder`. It refuses to overwrite an active recorder's runtime. Build output stays under ignored `audit/recorder-runtime/`; the execution/dashboard DLL under `bin/` is untouched. The installed unit uses a separate `fxpro-recorder` container, read-only source/credentials mounts, writable data mount, memory1GB/CPU1core caps, restart-on-failure, graceful SIGTERM and private umask. `tailscaled` is unrelated to data collection.

The user unit is enabled; `loginctl show-user fiaboo -p Linger` verified yes, so the user's service manager starts at boot and survives logout. Full machine reboot was not tested. Systemd restarts unexpected recorder exits; internal reconnect uses2–60second backoff and re-reads existing credentials on each connect. OAuth expiration still needs the normal cTrader reconnection, and status/logs expose the failure. There is no independent token rotation race.

## Files and coverage

- `data/recorder-xauusd/live/XAUUSD-DATE.csv`: append journal with receivedUTC, broker timestamp_ms, side1Bid/2Ask, raw price_1e5 and connection ID. Optional Bid/Ask fields are recorded independently; no fabricated opposite side. Duplicate/late events and cached subscription snapshots remain evidence, not certified fresh ticks. A torn trailing line is removed on reopen. Active data flushes each1s, API-loop boundaries and shutdown; a stalled request may delay an idle tail flush to the30s timeout. History recovery covers that tail later.
- `data/recorder-xauusd/history/XAUUSD-DATE-HOUR.csv.gz`: authoritative broker-queried UTC hours. Existing TickHistory pagination preserves duplicate-ms ticks and rejects stalled/invalid pages. Each hour fetches both sides, sorts, flushes/finalizes gzip and atomically renames before checkpointing. Live journals are NOT concatenated with history; this avoids counting the same event twice in research data. Retries replace the hour, not append.
- `coverage.json`: pinned identity/start and end-exclusive coverage watermark. Missing referenced hour rewinds coverage for refetch. Corrupt checkpoint is not silently reset. Corrupt gzip fails validation/publication; inspect/delete only the corrupt hour and restart recorder to rewind rather than marking it complete.
- `data/fxpro-v2/XAUUSD-DATE.csv.gz`: published only after24queried hours. Same schema as existing backtest/range readers. Atomic publish never replaces an existing daily cache, even if another downloader publishes concurrently. Existing Jan–Apr data and metadata are preserved.
- `status.json`: heartbeat, state, last broker/receive times, freshQuote, end-exclusive coverage, pending settled hours, unverified tail seconds, process-scoped counters and sanitized error type. A stale heartbeat means the status is historical. `recording` is the process state; it does not guarantee fresh market ticks.

One-hour intervals are fetched only when their end is at least60s old. The current/unsettled hour remains provisional: `pendingHours=0` does not mean the tail through now is verified; use `unverifiedTailSeconds`. Empty history is marked queried-empty, not proof that the market was closed or the provider has no missing ticks. Requests are paced by the existing transport at250ms minimum spacing; only read-only traffic is added. Broker data can still have omissions that this single source cannot independently verify.

First deployment started at2026-11-13UTC (yesterday), and coverage persists beyond restart. This does not backfill the missing May–Nov12 calendar period automatically. `record-data --from YYYY-MM-DD` selects a start only before the first checkpoint; it refuses to silently change an existing origin. Older research periods can use the existing historical exporter separately. Data, status and runtime evidence remain ignored by Git; no secrets are recorded.

## Verified deployment on2026-11-14

Real broker read-only startup/subscription and historical recovery succeeded:447638 raw side updates forNov13 (224283Bid/223355Ask). Complete daily gzip validated sorted timestamps, positive prices and expected schema. Covered hours throughNov14 01:00UTC; current hour pending. First live event was a cached Friday quote at21:59:35.680UTC, not a new weekend tick. Repeated recorder-only restart resumed original origin/watermark and left daily SHA unchanged. No live-market sustained stream, forced network loss, power failure or full reboot tested.

Fake checks (`check-recorder`) cover partial sides/rotation/torn tail, order allowlist, foreign account, second-side failure without coverage advance, settlement, tied ticks, 24hour publication, missing-file rewind, immutable existing cache and corrupt checkpoint. Build0warnings/errors; existing execution/history, market and backtest/SMC/range fake tests also pass. Evidence ignored `audit/recorder/verification.json`. Execution remains active/running1position, config revision and original runtime DLL hash unchanged.

PA chart remains a recorded Apr28–30 research view; the recorder does not automatically connect PA to realtime or activate a strategy.

Official protocol references: [spot subscriptions and optional sides](https://help.ctrader.com/open-api/symbol-data/), [message definitions](https://help.ctrader.com/open-api/messages/), [heartbeat guidance](https://help.ctrader.com/open-api/faq/). Uses the existing tested transport/history implementation.
