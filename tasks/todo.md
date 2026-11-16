# SMC research
- [x] Read sources, current strategy, data scope and saved demo settings.
- [x] Implement and test causal research-only events.
- [x] Run fixed paired subperiod and cost-stress comparisons.
- [x] Record every result, limitations, recommendation and unchanged service state.

- [x] Deliver SMC Observer v1 design: H1 context, M5 causal structure/sweep, FVG lifecycle and snapshot contract. Full observer/overlay implementation is a later scope, not reported as shipped.

# Range-bar supply/demand PA
- [x] Test and implement threshold range bars with real tick prices.
- [x] Test and implement causal base/departure/first-retest strategy.
- [x] Integrate with shared simulator; run fixed sensitivity/cost comparisons.
- [x] Publish design/results and verify unchanged live demo.

- [x] Apply requested high/low TP in offline strategy; test actual variable RR, publish all HL runs.

# Minimum3R user experiment
- [x] Add inclusive entry-time RR>=3 gate and rejection counter; preserve controls.
- [x] Run both subperiods and2xslip; all12filtered cases have0trades; controls unchanged.

# Kronos-small pilot
- [x] Inspect/pin upstream code and safetensors; install isolated CPU deps.
- [x] Export H1/session data via existing quote reader and test cutoff preprocessing.
- [x] Run local pretrained inference and score forecasts.
- [x] Replay fixed agreement filter vs full/coverage controls; document limitations and unchanged demo.

# Range PA visual layer
- [x] Emit shared-engine zone lifecycle events and recorded range snapshots.
- [x] Add range PA rectangles/markers and causal replay to canonical chart.
- [x] Verify browser visuals,1280desktop, no POSTs and preserve demo.
