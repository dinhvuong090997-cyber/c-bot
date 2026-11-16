# M5 confirmation experiment — 2026-11-14

Research only. Initial capital $50,000; RR 1.5; risk 0.25%; closed-balance drawdown halt 5%; slippage $0.10/oz; swap enabled.

| Period | Mode | Closed return | Equity return | Max equity DD | Trades | Profit factor | Halted |
|---|---|---:|---:|---:|---:|---:|---|
| 2026-01-01 to 2026-05-01 exclusive | Baseline | -4.79% | -4.79% | 5.23% | 64 | 0.555 | True |
| 2026-01-01 to 2026-05-01 exclusive | M5 | -4.69% | -4.69% | 5.24% | 100 | 0.678 | True |
| 2026-03-01 to 2026-05-01 exclusive | Baseline | -2.15% | -2.18% | 4.19% | 175 | 0.911 | False |
| 2026-03-01 to 2026-05-01 exclusive | M5 | -3.01% | -3.01% | 5.27% | 157 | 0.863 | True |

The later period resets capital and risk state; its baseline has one open position at the end. Both full-period simulations halted early, so four calendar months do not represent four months of active trading. M5 is worse in the later subperiod and is not recommended for activation. No parameter optimization performed. Data was previously researched and is not a pristine unseen holdout. Tick replay does not verify real fills. Boundary coverage does not detect all internal data gaps.

Build, backtest checks, fake execution and fake service checks passed. No broker connection, order or service restart was used.
