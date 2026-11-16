# Saved demo strategy: structure and timescale — 2026-11-14 local

Read-only observation: demo active/running with one position, fresh heartbeat/quote. Selected execution settings: RR5, risk1%, balance drawdown halt20%, minimum stop3USD/oz, spread multiplier1.5, Asia and NewYork enabled. No explicit candle timeframe in execution config. Backtest slippage0.1 belongs to the selected research report; live ExecutionConfig does not impose that fixed fill slippage.

## What the code observes

`cbot/AsiaSession.cs` uses valid bid/ask ticks and midpoint=(bid+ask)/2 over00:00–08:00UTC (07:00–15:00 Asia/Vientiane). It records first/last midpoint, midpoint high/low and median spread sampled07:55–08:00UTC. Complete coverage checks precede profile creation. Last>first gives BUY bias; last<first SELL; equal yields no profile. This is signed session movement, not confirmed HH/HL structure or an Asia-range breakout requirement.

Stop distance=max(3, half the Asia midpoint high-low range), rounded outward to symbol precision by ExecutionOrder. Target distance=5times stop. When the3USD floor is inactive, planned TP is about2.5times the Asia range away from the fill; stops/targets are relative to broker fill, not pinned to an old swing price. The size of the session supplies volatility scale, not a guarantee that a future move will cover the target.

Entries during00:00–08:00UTC use the previous completed profile, allowed age1–4calendar days. NewYork08:00–17:00 local uses the current day's completed Asia profile; DST conversion is historical. On UTC+7, NewYork window is19:00–04:00next day in US daylight time,20:00–05:00next day in standard time. Weekend new entries are disabled.

ExecutionSignal checks fresh quotes/spread, one attempt per UTC minute, one-second pending delay and stale-signal rejection. No M1 candle close, M5 pattern or H1 structure is required; the chart's selected timeframe does not alter execution. Any existing account position/order blocks a new entry. Existing exposure retains broker SL/TP outside entry sessions; balance drawdown halt blocks new entries, does not automatically liquidate every open position.

## Selected original report, not current demo P&L

Read the selected custom report/run referenced by live config: Jan1–May1 2026 exclusive, research initial capital50,000USD, RR5/risk1%/DD20%/minimumSL3/slip0.1/swap on/both sessions. It is a different starting capital from the16,707.35balance seen on the demo account and in the later research comparisons. Do not call the report's return actual demo performance, or compare it directly with independently reset16.7k subperiod runs as if they were the same equity curve.

-87closed trades:18wins,69losses, win rate20.69%;1position open at report end.
-Closed net+5,056.69USD; liquidation-equity net+5,003.29USD (+10.01%).
-Profit factor1.214; max equity drawdown11.59%; no20%halt.
-Median stop28.41USD/oz; median holding4.79h, mean31.50h, maximum583.88h (~24.33days).
-Grouped by entry session, closed trades only: Asia46trades/11wins/+7,398.80USD; NewYork41trades/7wins/−2,340.33USD. Open final position is excluded from session closed-net breakdown. Session describes entry eligibility, not where all profit occurred.

These are descriptive counts from an already-selected, previously researched four-month sample, not proof Asia-only will generalize or that this is the global best config. Changing sessions changes position overlap and subsequent eligible trades; cannot simply remove NewYork rows and call the sum a valid new backtest.

## Interpretation for FIAB research

The hypothesis encoded here is session-direction persistence with session-range-scaled protection and asymmetric5R payouts. A low win rate can coexist with net profit in this sample because larger winners offset many stops, subject to costs and changing volume. Risk1% is a sizing ceiling/setting, not1%actual risk on every order because min/step/notional/margin constraints can change eligibility.

The timescales are: tick execution; one-minute attempt cadence; eight-hour Asia context; exits can run across hours/days. This is a better starting description than calling it an M1/M5 scalper. Supply/demand range experiments instead used a much shorter local departure target; requiring3R on those near targets eliminated every entry. If researching FIAB further, preserve this proven-in-sample baseline and test session context/volatility scale separately from entry timing. No strategy change or session removal has been authorized/executed in this read-only analysis.

Sources: `cbot/AsiaSession.cs`, `openapi/ExecutionModel.cs`, `openapi/ExecutionBot.cs`, selected report and trade ledger under ignored `openapi/reports/`. No credentials copied. No builds, restarts, broker commands, new backtest or live-market chart analysis performed for this inspection.
