# Background FxPro tick archive

User authorized downloading available XAUUSD Bid/Ask history while market is closed. `./api archive` builds/checks an isolated runtime and enables `fxpro-tick-archive.service`; `./api archive-status` reads progress. This is separate from `fxpro-data-recorder.service` and the trading worker. No dashboard/worker/live-recorder restart or config/order changes.

The archive first fills missing complete UTC days fromJan1 of the current year through today's midnight (fixed end snapshot). Existing daily caches are skipped and never overwritten. For this deployment, end2026-11-14 and120Jan–Apr cached days were found. After current-year gaps it scans backwards in blocks of up to6UTCdays, down to the non-negative Unix timestamp boundary1970-01-01. This is a protocol search floor, not a claim that FxPro has data since1970. It does not infer a retention boundary from the first empty interval.

Each old block is probed via existing read-only Open API connection at250ms request pacing. A positive probe triggers full day-by-day Bid+Ask pagination. A negative block requires empty responses from BOTH sides and hasMore=false; proof intervals are persisted in data/archive-xauusd/empty-weeks. Six-day blocks allow inclusive-start/exclusive-end adjustments without exceeding the API week limit. Empty responses mean queried-empty, not verified market closure or independently complete historical data. No fake tick/volume is generated.

Missing days use the existing TickHistory pagination, sorted raw side rows and atomic gzip publishing with no replacement, matching the backtest cache schema. Failed/cancelled second-side fetch cannot publish a partial day. Existing metadata/cost snapshots remain unchanged. Already-existing files are trusted as prior cache; this is not a fresh independent audit of all old files. A block is checkpointed only after all its days finish; restart rechecks that block and skips previously saved days. Cached counters describe processed cache visits, not necessarily unique dates across interruptions; count files/manifests for physical inventory.

Checkpoint/status/lock under ignored data/archive-xauusd; isolated DLL under audit/archive-runtime. Source account pinned to saved FxPro demo; credentials/source mounted read-only, data mount writable, request wrapper rejects order mutations. Unexpected exits restart through systemd; internal reconnect2–60seconds. Resumes after network errors/machine restart, provided OAuth remains valid. Existing user linger=yes. End date stays fixed; independent live recorder covers future dates. Storage reserve10GB, memory2GB/CPU1core. Disk-space/permission/broker errors retry and expose status error type; they do not mark a day complete. If a provider rejects very old queries rather than returning empty, inspect status/logs rather than claim completion.

During initial validation archive reached lateMay2026 with millions of new raw side updates and no errors. Exact latest progress is in `./api archive-status`, not this document. A controlled ARCHIVE-ONLY restart checked resume and immutable prior cache/metadata. Unit/fake checks cover both-side empty proof, truncated empty rejection, atomic compatible daily cache, skipping cached data and side failure safety; recorder fake regression also passed. Build0warnings/errors, Python/Bash/systemd/diff checks pass. Evidence ignored audit/tick-archive/. Full archive/earliest available data boundary is NOT yet verified; process continues in background. No strategy re-test on newly downloaded data was performed as part of collection.

Commands:

```bash
./api archive-status
systemctl --user status fxpro-tick-archive.service
journalctl --user -u fxpro-tick-archive.service -n 20
```

Stop/update only this archive unit before rebuilding it. Do not restart execution, dashboard or live recorder to manage history collection. Completion is `completed=true`, not merely `active` container status. Empty intervals outside actual history remain proof JSON rather than thousands of fabricated empty daily research files. Source data/proofs remain local and ignored by Git.
