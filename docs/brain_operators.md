# WorldQuant Brain FASTEXPR Operator Notes

This is a compact operator guide for AI proposal generation. It is not a full
official reference. Use it to choose simple, interpretable transforms.

## Field Preprocessing

- `ts_backfill(x, d)`: fills missing values using recent history.
- `winsorize(x, std=4)`: clips extreme values.

Default pattern for raw MATRIX fields:

```text
winsorize(ts_backfill(FIELD, 120), std=4)
```

## Cross-Sectional Operators

- `rank(x)`: cross-sectional rank. Useful for making signals comparable across stocks.
- `zscore(x)`: cross-sectional standardization.
- `normalize(x)`: normalization transform.
- `quantile(x)`: quantile transform.

## Time-Series Operators

- `ts_rank(x, d)`: ranks the current value against its own recent history.
- `ts_delta(x, d)`: current value minus value d days ago; useful for change/momentum.
- `ts_mean(x, d)`: smooths noisy fields.
- `ts_sum(x, d)`: cumulative signal over a window.
- `ts_zscore(x, d)`: time-series z-score.
- `ts_std_dev(x, d)`: time-series volatility/noise measure.
- `ts_delay(x, d)`: lagged value.
- `ts_arg_min(x, d)`, `ts_arg_max(x, d)`: location of recent min/max.

Suggested windows:

```text
5, 22, 66, 120, 240
```

## Group Operators

- `group_neutralize(x, densify(group))`: removes group-level exposure.
- `group_rank(x, densify(group))`: ranks within group.
- `group_zscore(x, densify(group))`: z-scores within group.

Common groups:

```text
market, sector, industry, subindustry
```

Use group operators when a signal may be dominated by sector, industry, size,
liquidity, or broad market exposure.

## Trade Event Operator

- `trade_when(event, alpha, exit_event)`: holds alpha only when event is true.

Use it after a base alpha has promise but needs lower noise or lower turnover.

## Heuristics

- Fundamental level fields: try `rank`, `zscore`, `ts_rank`, and sector neutralization.
- Fundamental change fields: try `ts_delta`, `ts_rank(ts_delta(...))`, or `ts_mean(ts_delta(...))`.
- Noisy high-frequency fields: smooth with `ts_mean` or use longer windows.
- High turnover results: increase decay, smooth signal, or use `trade_when`.
- Negative Sharpe results: consider testing reversed direction only if the idea is still economically plausible.
- Low fitness with decent Sharpe: try group neutralization or smoother transforms.

