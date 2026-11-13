# Working on Aurum

Read `WORKSPACE.md` for architecture and commands, then `MEMORY.md` for the last verified state and outstanding work. Confirm the current Git status and service state before relying on a previous session snapshot.

- The user communicates in Vietnamese and prefers concise updates and completed actions. The product UI is English and prioritizes desktop.
- Reuse the existing C#/vanilla JS application. `openapi/dashboard/` is the only frontend source; do not recreate a second dashboard copy.
- The execution worker is independent of the dashboard. UI changes must preserve its process, selected config and open positions. Restart only the service being changed.
- UI QA is read-only: do not activate Start/Stop/Apply or place broker orders unless the user explicitly requests the action. Fake broker regression tests are available.
- Credentials belong in the private configuration directory outside this repo. Keep the existing Git ignores for broker data, reports, logs, caches and private evidence.
- Use expected-head checks for GitHub updates; preserve existing commit history. The old project was replaced by explicit user request, not by rewriting history.
- Add meaningful checks for changed logic. Do not claim a real-broker trading scenario was tested when only fake connections or read-only browser checks ran.
- Before handing work off, update `MEMORY.md` with concrete changes, checks, deployment state and unresolved issues. Never store secrets or pairing codes in memory.
