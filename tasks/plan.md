# Kronos-small offline pilot

User authorized trying a pretrained Transformer; preserve live demo and screen state. All model/source/deps/tick evidence private under ignored audit/kronos. External code pinned/reviewed, safetensors only. No host install or model execution in trading worker.

Fixed test: Kronos-small (24.7M), OHLC-only H1 Bid bars, lookback128closed valid bars, session-open prediction at Asia00UTC and NewYork08local (DST), next9H forecast (8H used for Asia). Missing volume/amount zero per upstream API; quote count not trade volume. No finetuning/parameter search. Seed20261114,3paths averaged, temperature1/top_p0.9. Input cutoff before decision, incomplete hours excluded, no synthetic weekend bars. Predictions may cross calendar gaps in context; report domain limitations.

Evaluate directional/MAE vs actual session close and naive past movement; fixed agreement filter replays all tick entries. Full baseline vs same-forecast-coverage baseline vs forecast-agreement. No future truth reaches model. Forecast only usable60s after session open (verify inference runtime); absent forecast blocks both coverage controls. Saved RR5/risk1%/DD20%/SL3, initial50k selected report; slip0.1 plus0.2stress. Previously studied4months, not pristine holdout. No direct TP5R probability claim from sampled forecasts.

Tasks: export shared-reader bars/session cutoffs; causal preprocessing unit checks; local model smoke; batched fixed inference; read-only tick simulation with immutable forecasts; results and demo invariant check. Network off during inference and backtest; resource cap4CPU/4GB.
