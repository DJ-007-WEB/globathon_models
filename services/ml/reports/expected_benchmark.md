# Expected benchmark report

## Run

- Batch: `artifacts/synthetic_batch` (9 existing scenarios, not regenerated)
- Split: scenario-level, 5 train scenarios / 4 held-out test scenarios
- Train scenarios: `scenario_000` through `scenario_004`
- Test scenarios: `scenario_005` through `scenario_008`
- Model inputs: POA irradiance, module temperature, AC/DC capacity, inverter efficiency, system losses, temperature coefficient, timestamps, device ID
- Ground-truth labels: not used as model inputs
- Reproduce: `python scripts/benchmark_expected.py`

## Held-out physics-baseline metrics

Power (kW), 1,141 valid test rows:

| Metric | Value |
| --- | ---: |
| MAE | 0.2294 |
| RMSE | 0.4786 |
| Bias | +0.0220 |

Interval energy (kWh), 1,141 valid test rows:

| Metric | Value |
| --- | ---: |
| MAE | 0.1147 |
| RMSE | 0.2393 |
| Bias | +0.0110 |

Training-scenario power metrics for context: MAE 0.6000 kW, RMSE 4.8928 kW, bias +0.4561 kW.

The aggregate test status is `warning` because some irradiance and
module-temperature readings are missing. Missing module temperatures were
estimated from ambient temperature/irradiance where possible, with a 25 C
reference used for any remaining gaps. Rows without required irradiance do not
receive a fabricated estimate and are excluded from the metric counts.

## LightGBM decision

LightGBM is not installed in this environment, so it was not evaluated and no
residual model was added. The physics baseline remains the final method. If
LightGBM is later evaluated, it should replace the physics baseline only when
held-out MAE improves.
