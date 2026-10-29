# SolarSleuth: ML Pipeline

## Windows quick start

This project is intended to run locally on Windows PowerShell or Command Prompt.

```powershell
cd D:\Storage\Downloads\globathon_models
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -r ML-models\requirements.txt
python ML-models\scripts\generate_synthetic.py --seed 7 --n-scenarios 1 --out ML-models\artifacts\synthetic_smoke
python ML-models\scripts\run_pipeline.py --inputs ML-models\artifacts\synthetic_smoke\scenario_000 --output ML-models\artifacts\pipeline_output.json
```

The pipeline can be run on a synthetic scenario or any scenario directory containing `operating_data.csv` and optionally `weather.csv`, `forecast.csv`, `devices.csv`, and `event_log.csv`.

### Command usage

```powershell
python ML-models\scripts\run_pipeline.py --inputs <scenario_directory> --output <output_path.json>
```

If required data is missing, the pipeline reports `unavailable` rather than fabricating values.

## Benchmark provenance and current results

This repo currently includes the deterministic synthetic generator and project validation checks, plus the generated synthetic smoke batch under `ML-models/artifacts/synthetic_smoke`.

Actual benchmark results in this branch are limited to the smoke validation and the project's automated tests. No model benchmark report was claimed as real-world accuracy beyond that validation. The provenance for synthetic runs is the generator in `ML-models/src/synthetic.py`, which is intentionally separate from any real-plant dataset and never used as model input for production predictions.

## Data sources and licence notes

The project keeps raw public and validation data local and does not commit them by default. The source inventory remains in `ML-models/data/README.md` and must be verified before public release or redistribution. Keep licences, file versions, and provenance metadata with the local dataset copies.

## Fallback behavior and limitations

- Physics-only baseline remains the default if a LightGBM residual model is unavailable or not useful.
- Missing readings and communication gaps remain `null`/unavailable instead of zero.
- Forecast alignment is never silently upsampled or guessed.
- Waterfall components and single-primary-cause accounting are preserved.
- Synthetic ground-truth labels remain separate from model inputs and are not used to leak labels into predictions.
- This implementation is intentionally strict: unsupported or unresolved conditions produce a valid versioned output when possible, otherwise the pipeline fails clearly with an actionable error.


**Globathon 2026 — Problem Statement 3: Explaining Solar Generation Forecast Variance**

**Repository purpose:** Develop, evaluate and package the ML and deterministic-analysis components for SolarSleuth.

**Status rule:** Nothing is called *trained*, *validated* or *accurate* until the relevant experiment has actually run and its results have been documented in `reports/`. Synthetic-data metrics must never be presented as real-world accuracy.

---

## 1. What the ML Layer Must Do

Given the competition inputs, explain why actual solar generation differs from the design forecast and how much of that difference can be supported by available evidence.

The expected inputs at kickoff are:

- Solar plant design specification and design forecast.
- Hourly site weather.
- One month of plant operating data at 15-minute intervals.
- Inverter and weather-station measurements.
- Device details and operator event logs.

The actual schema, units, timestamps, time zone, plant configuration and data completeness are unknown until kickoff.

### 1.1 Attribution categories

| Category | Meaning |
|---|---|
| Weather-driven | Actual weather differed from the conditions assumed in the design forecast, where both can be established |
| Plant-driven / potentially controllable | Evidence is consistent with an operational issue, such as inverter outage, derating or underperformance |
| Externally constrained | Evidence supports curtailment, grid restrictions or other external constraints |
| Unresolved | Evidence is insufficient, contradictory or missing |

Observations, calculations, predictions and hypotheses must always be labelled separately.

Unavailable values remain `null`, never zero. Causes must not be double-counted. Financial estimates require verified commercial inputs.

The local LLM explains structured results. It does not calculate critical numbers or invent measurements, causes, savings or confidence scores.

### 1.2 Primary business objective

Help plant operators protect revenue by understanding forecast deviations, identifying potentially addressable operational issues and supporting better energy-management and scheduling decisions.

Do not promise that a flagged deviation is recoverable or that a scheduling penalty can be calculated. These claims require the relevant evidence and, for monetary calculations, applicable tariffs, contractual terms, scheduled energy and settlement rules.

---

## 2. Globathon Constraints

The implementation must follow the organizers' supplied dataset notice.

- The competition dataset arrives at kickoff; it must not be assumed to match preparation data.
- Files may be CSV or Excel, with different sheets, column names, units, timestamp formats, time zones, sampling intervals and missing values.
- Plant size, inverter count, plant layout and sampling interval must be discovered rather than hardcoded.
- Schema mapping must handle previously unseen input structures.
- AI models must run locally. No public AI inference APIs, including OpenAI, Anthropic, Google or Groq.
- Download and test all required model weights and dependencies before the event.
- The pipeline must remain useful if the local LLM is unavailable or slow.
- Every output must distinguish observed values, derived calculations, model predictions and unverified hypotheses.

**Preparation strategy:** Build and test the pipeline before kickoff. At kickoff, inspect the supplied files, validate units and time zones, resolve ambiguities and run the pipeline on the actual data.

---

## 3. Core Design: Attribution Waterfall and Self-Calibration

### 3.1 Attribution waterfall

The main analytical structure is:

```text
Design forecast
      |
      v
Weather-adjusted expected generation
      |
      v
Actual measured generation
```

Let:

- `F` = design forecast energy.
- `E` = estimated expected energy under actual weather, assuming the defined healthy-plant conditions.
- `A` = actual measured energy.

Use signed contributions:

```text
Weather effect = E - F
Plant effect   = A - E

Total deviation = A - F
                = Weather effect + Plant effect
```

This signed convention ensures the contributions reconcile mathematically. A separate positive loss estimate may be calculated where the assumptions justify it.

The plant effect may be investigated using evidence for outages, derating, clipping, curtailment, persistent underperformance or sensor/data problems. Anything unsupported remains unresolved.

**Important:** `E` is an estimate, not an automatically known value. Constructing it requires a defensible model and suitable inputs. Actual weather alone does not establish how the design forecast treated weather. If the necessary inputs are missing, the weather effect must remain unresolved rather than being fabricated.

### 3.2 Per-plant self-calibration

A model trained on another plant may not transfer directly to an unseen plant's capacity, layout or equipment.

Therefore:

- Use normalized features such as output per rated capacity and suitable irradiance-normalized performance indicators.
- Retain physical units and original measurements for reporting.
- Use the competition plant's own data to calibrate the expected-output baseline when sufficient reliable observations exist.
- Prefer apparently healthy periods supported by data-quality checks and available operational evidence.
- Use chronological or day-grouped validation and out-of-fold residuals to reduce the risk of learning suspected faults as normal.
- Report insufficient calibration data rather than forcing a fit.

One month of data may not contain enough healthy operating conditions for reliable calibration. Self-calibration is a safeguard, not a guarantee of accuracy.

Offline pretraining primarily prepares the code, features and model defaults. It does not prove that a model transfers unchanged to an unseen plant.

---

## 4. Data Strategy

### 4.1 Public datasets and research

Use a small number of complementary public sources. Verify actual files, fields, licences and documentation before committing to a dataset.

| Priority | Source | Intended use | Limitations |
|---|---|---|---|
| 1 | Kaggle Solar Power Generation Data, Ani Kannal: https://www.kaggle.com/anikannal/solar-power-generation-data | Real Indian solar data for expected-output experiments, peer comparisons and ingestion tests | Verify fields, units, timestamp alignment, licence and suitable targets. No assumed fault labels |
| 2 | NASA POWER: https://power.larc.nasa.gov/ | Weather profiles to inform synthetic scenarios | Reanalysis/weather products are not interchangeable with ground sensors |
| 2 | Open-Meteo Historical Weather: https://open-meteo.com/ | Historical weather profiles for selected locations | Check variables, time resolution and source limitations |
| 2 | PVGIS: https://re.jrc.ec.europa.eu/pvg_tools/en/ | Solar-resource and weather-related reference data | Not automatically equivalent to plant measurements |
| 3 | Global Solar Atlas: https://globalsolaratlas.info/ | Sanity-check expected yield and capacity-factor ranges | Reference only, not high-resolution ground truth |
| Optional | NREL PVDAQ: https://catalog.data.gov/dataset/photovoltaic-data-acquisition-pvdaq-public-datasets | Additional real operating data if useful | Check coverage and compatibility |
| Optional | PV SCADA dataset: https://data.mendeley.com/datasets/9fdvyjrf67 | Explore inverter, weather and grid-export fields | Verify version, access, licence and labels |
| Optional | PV failure-diagnosis dataset: https://zenodo.org/records/18326501 | Investigate documented failure patterns | Verify actual fields, labels, coverage and licence |

For every source actually used, record its name, version or retrieval date, licence, fields, resolution, coverage, intended use and known limitations in `data/README.md`.

Public sources inform the model design and synthetic scenarios. They do not automatically establish ground truth for the competition plant.

### 4.2 Synthetic data generator

The generator creates controlled scenarios with known ground truth. Its purpose is to test ingestion, model behaviour, anomaly detection and energy-attribution calculations.

It must not be used to claim that synthetic observations prove real-world model accuracy.

Target approximately **200–500 varied scenarios**, prioritizing diversity and realistic combinations over simply increasing row count.

#### Healthy-output model

Where the necessary parameters and measurements exist, use a simplified PV relationship:

```python
module_temp = ambient_temp + k * irradiance

p_dc = (
    rated_dc_power
    * (irradiance / 1000)
    * (1 + gamma * (module_temp - 25))
    * (1 - system_losses)
)

p_ac = min(p_dc * inverter_efficiency, rated_ac_power)
```

These are illustrative relationships, not universal plant equations. The generator must document units, assumptions, clipping behaviour and any simplifications. Use an appropriate temperature coefficient and configure DC/AC ratios, capacity and losses instead of assuming fixed values.

Use `pvlib` for clear-sky irradiance calculations if appropriate. Cloud and monsoon variability may be informed by suitable weather data or documented stochastic assumptions.

#### Scenario variation

Randomize, within defensible ranges:

- Plant capacity, inverter count and configuration.
- Sampling intervals such as 5, 10, 15, 30 or 60 minutes.
- Wide versus long table layouts.
- Column names, abbreviations and supported language variants.
- W, kW and MW; Wh, kWh and MWh.
- Timestamp formats, UTC versus local time, and ambiguous date conventions.
- Interval energy versus cumulative meter readings.
- Missing readings, duplicate timestamps, sensor noise and communication gaps.
- Weather conditions and equipment states.

All time zones must be explicitly represented. Never silently assume a timestamp's time zone or day/month ordering when the data is ambiguous.

#### Fault and data-quality scenarios

Each scenario records ground-truth event type, start/end times, affected equipment, magnitude and generating assumptions.

Include:

- Full inverter outage and partial derating.
- Gradual soiling-like drift, including a documented reset after a simulated rain event.
- Persistent underperformance relative to comparable inverters.
- Irradiance sensor flatline, offset and dropout.
- Curtailment or output caps, with and without matching event-log evidence.
- Communication gaps, where missing data is not treated as zero generation.
- Faults absent from the event log.
- Event-log entries without an observable generation impact.

Fault magnitudes must be based on documented physical assumptions, not selected merely to improve scores.

Hold out complete scenarios and unseen combinations for evaluation. Never rely solely on a random row split. Stamp synthetic files and metadata clearly as `synthetic`.

### 4.3 The three existing real-plant files

Use the existing files for ingestion, schema discovery, unit checks, feature calculations and supported real-data sanity checks.

| File | Use | Limitations |
|---|---|---|
| `Project Viability.xlsx` | Monthly performance and generation comparisons | Approximately 12 monthly observations; target generation may not be a formal forecast |
| `SPV-01_SPV-02_Generation_Performance_Summary_Aug26.pdf` | Performance trends and operational-context checks | Monthly aggregation; limited detailed inverter and forecast evidence |
| `DGR Vayudoot Solar Bhainsa _June'2021.xlsx` | Daily/equipment-level ingestion and event-log alignment | Limited period, incomplete fields and historical events from other periods |

These are **real-data validation assets, not automatically a valid model accuracy test set**. Use only the metrics supported by the available measurements and labels. Do not align the separate March 2019 events with June 2021 observations without evidence of temporal correspondence.

---

## 5. Model Strategy: One Primary Trained Model

**The planned primary trained ML model is LightGBM for expected-output residual correction.** Everything else is a formula, statistical detector, rule engine or optional benchmark.

### Stage 0 — Data quality

**Training:** None.

Implement deterministic checks for:

- Missing and duplicate timestamps.
- Out-of-order observations and time gaps.
- Unit inconsistencies and implausible values.
- Night-time generation anomalies, where location and time information support the check.
- Flatlined sensors and cumulative-counter resets.
- Power readings that violate documented capacity constraints.
- Inconsistent equipment IDs and cross-file timestamps.

These checks must be configurable and physically justified rather than assuming one plant layout.

### Stage 1a — Physics-based expected-output baseline

**Training:** No general ML training; a small number of physical parameters may be fitted from suitable plant data.

Build the baseline first. Where inputs support it, use a simplified physical relationship involving rated capacity, irradiance, module temperature and documented system losses. Use a clear-sky model as an irradiance sanity check where appropriate.

A baseline parameter such as `k_loss` may be robustly fitted using apparently healthy observations. If the necessary inputs or sufficient healthy periods are unavailable, report that limitation and use a simpler supported calculation.

This is the reference against which the ML model must prove its value.

### Stage 1b — LightGBM residual model

**Training:** Yes. This is the primary planned ML model.

The model corrects the physics-based estimate rather than replacing the physical baseline entirely.

For an interval with valid measurements:

```text
physics_expected = output from the physics baseline

residual_target = observed normalized output
                  - normalized physics_expected

corrected_expected = physics_expected
                     + predicted residual correction
```

Use consistent units and normalization. Define whether the target is power, interval energy or normalized output before training.

Candidate features, only when available and validated:

- Irradiance.
- Module and ambient temperature.
- Hour-of-day encoded using sine/cosine.
- Clear-sky index or another justified normalized irradiance measure.
- Wind and humidity, if suitable.
- Other physically defensible variables that do not leak the target.

**Do not use lagged actual output as a feature in the initial model.** Avoid leakage from future observations, event labels or derived fields that encode the target.

Train LightGBM only if the available data supports a meaningful target and enough independent examples. Use chronological/day-grouped splits.

If LightGBM fails to outperform the physics baseline on held-out data, retain the physics baseline as the deployed fallback.

### Stage 1c — Uncertainty

**Training:** Optional.

Start with a simple, documented residual-spread estimate if suitable held-out residuals exist. This is not automatically a calibrated prediction interval.

If time and data permit, compare LightGBM quantile models or conformal calibration. These are optional extensions and must be evaluated separately. Do not implement two extra quantile fits by default.

The purpose is to identify deviations outside a defensible expected range, not to manufacture a confidence interval when calibration data is inadequate.

### Stage 2a — Peer comparison

**Training:** None.

At each suitable timestamp, compare each inverter's normalized output with the median of comparable inverters. Use a robust deviation score based on the median absolute deviation (MAD), plus a persistence filter to avoid flagging every short-lived fluctuation.

This can be a strong, cheap signal when equipment shares comparable conditions. It is not appropriate when equipment is not comparable or too few peers have valid readings.

### Stage 2b — Residual statistics and drift

**Training:** None.

Use robust residual thresholds, rolling statistics and CUSUM to identify persistent deviations or gradual drift.

These methods are interpretable and computationally inexpensive. Their thresholds must be documented and tested rather than tuned solely to maximize synthetic scores.

### Stage 2c — Isolation Forest

**Training:** Optional unsupervised fit.

Evaluate Isolation Forest only if peer comparison and residual statistics leave a meaningful detection gap. Use a small validated feature set, such as normalized residual and peer deviation, when available.

Keep it only if experiments demonstrate a useful improvement in detection, false-alert rate or runtime trade-offs.

Local Outlier Factor, one-class SVM, autoencoders and deep-learning anomaly detectors are out of scope for the initial version.

### Stage 3 — Evidence-based attribution

**Training:** None.

Use a transparent rule engine with a documented priority order. A possible initial order is:

1. Missing or invalid data.
2. Event-log evidence of a relevant curtailment or outage.
3. Zero or reduced output despite sufficient irradiance.
4. Clipping signature supported by the measurements.
5. Persistent peer underperformance.
6. Gradual drift consistent with soiling-like behaviour.
7. Unresolved when evidence is insufficient or contradictory.

The order is a starting point, not proof of causation. The implementation must permit multiple observations to be recorded while assigning one primary cause per interval when calculating mutually exclusive energy contributions.

Each hypothesis must include supporting evidence, contradictory evidence and missing information. A supervised root-cause classifier is deferred until reliable, time-aligned labels are available.

### Stage 4 — Counterfactual energy

**Training:** None.

Estimate a potential energy difference only for eligible intervals and under an explicit reference scenario.

For interval power in kW and interval duration in hours:

```text
energy_difference_kWh =
    max(0, reference_power_kW - actual_power_kW)
    * interval_duration_hours
```

If the reference is an energy quantity, use the appropriate energy calculation instead. Never multiply interval energy by duration a second time.

Choose the reference from a justified weather-adjusted expectation or comparable-peer baseline. Apply constraints and uncertainty ranges, exclude unsupported intervals and assign each interval to one primary cause for the loss ledger.

This estimate is not guaranteed recoverable energy. Financial estimates require verified commercial inputs.

### Model inventory

| Component | Type | Initial decision |
|---|---|---|
| Physics baseline | Formula + limited calibration | Required |
| LightGBM residual correction | Trained regression model | Primary ML candidate |
| Residual-spread uncertainty | Statistics | Optional first version |
| Peer median/MAD | Robust statistics | Required |
| CUSUM | Statistical detector | Required if time permits; preferred over adding complex models |
| Attribution rules | Deterministic logic | Required |
| Counterfactual energy | Deterministic calculation | Required |
| Ridge regression | Trained benchmark | Optional |
| HistGradientBoosting | Trained benchmark | Optional |
| Isolation Forest | Unsupervised model | Optional |

**We are not committing to training every candidate.** Benchmark alternatives only when the baseline works and time permits. Package only components that improve the result or materially strengthen the evidence.

---

## 6. Training and Calibration Procedure

### 6.1 Before the event

1. Build the data generator and produce approximately 200–500 diverse scenarios.
2. Test the ingestion engine and schema mapper against generated files and both Kaggle plant datasets.
3. Verify units, timestamps, target definitions and licence conditions.
4. Establish the physics-only baseline.
5. Fit and benchmark the LightGBM residual model only if the public data supports a valid target:
   - Train on earlier days.
   - Validate on subsequent days.
   - Reserve the latest suitable days for final testing.
   - Group related observations by day or scenario to reduce leakage.
6. Compare physics-only versus physics plus LightGBM using MAE, RMSE and a clearly defined normalized error metric.
7. Evaluate peer/MAD, residual thresholds and CUSUM on controlled synthetic scenarios.
8. Evaluate Isolation Forest only if the simpler methods justify a comparison.
9. Inspect unlabelled Kaggle examples manually. Report flags and reviewed patterns—not fault-detection accuracy.
10. Time the complete pipeline on a representative month of 15-minute data with multiple inverters. Aim for well under a minute for the analysis portion, then measure actual runtime.
11. Freeze configurations, seeds, dependencies, model versions and the application output contract.

### 6.2 On competition day

1. Inspect all supplied files and workbook sheets.
2. Run schema mapping and data-quality validation.
3. Confirm units, time zone, timestamp format and energy/power semantics before analysis.
4. Record unresolved mappings and missing evidence.
5. Calibrate the physics baseline using suitable observations, excluding suspected faulty periods where defensible.
6. Run LightGBM correction only if its required features, target semantics and calibration conditions are met.
7. Use chronological or day-grouped validation where feasible; avoid fitting a fault period as normal.
8. Run peer comparison, residual checks and CUSUM. Run Isolation Forest only if already justified.
9. Attribute causes against weather, equipment readings and event logs.
10. Build the forecast-to-weather-adjusted-expectation-to-actual waterfall.
11. Verify units, interval durations, signs, totals and cause exclusivity.
12. Export the versioned JSON output for the application and local LLM.
13. If model assumptions fail, report unresolved results and fall back to supported deterministic calculations.

Do not force self-calibration or model inference when the input data is inadequate.

---

## 7. Evaluation and Reporting

| Task | Metrics and checks | Interpretation |
|---|---|---|
| Expected output | MAE, RMSE and normalized error on held-out days | Compare against physics-only baseline |
| Synthetic anomaly detection | Precision, recall, F1, false-alert rate and detection delay | Report per injected fault type |
| Synthetic energy attribution | Error versus injected loss, bucket consistency and sensitivity to assumptions | Tests controlled scenarios, not real-world accuracy |
| Real data without labels | Alert rate, stability and manually reviewed examples | No accuracy claims |
| Schema mapping | Mapping accuracy on verified columns, unresolved-field rate and unit-error rate | Include three existing files and both Kaggle plants where practical |
| Runtime | End-to-end seconds and peak memory | Report measured results |
| LLM explanation | Evidence traceability, unsupported claims, schema adherence and insufficient-evidence behaviour | No fabricated numbers or causes |

Every experiment must record:

- Dataset source and version.
- Features and target definition.
- Split method and random seed.
- Model and configuration.
- Metrics and baseline comparison.
- Runtime and memory.
- Failure cases and limitations.

Synthetic results must be labelled as controlled-test results. Real files without ground-truth labels must not be used to claim accuracy.

---

## 8. Adaptive Schema Mapping

The schema mapper must work on unfamiliar CSV and Excel files without hardcoded plant-specific assumptions.

### Deterministic-first approach

1. Inspect headers, data types, sample values and workbook structure.
2. Use a reusable semantic vocabulary for column names, abbreviations and supported language variants.
3. Detect timestamp formats, likely time zones and sampling intervals.
4. Infer units from headers and values only when evidence is sufficient.
5. Validate plausible ranges, including irradiance and temperature.
6. Detect wide versus long layouts and equipment IDs embedded in column names.
7. Distinguish power, interval energy and cumulative energy readings.
8. Validate proposed mappings with cross-field and physical consistency checks.
9. Mark ambiguous mappings as unresolved and request confirmation when needed.

The local LLM may suggest mappings when deterministic methods cannot resolve an unfamiliar header. All suggestions must pass the same validation process.

Do not assume that a value is in W, kW or MW based solely on its magnitude if the interpretation remains ambiguous. Preserve original values and record all transformations.

### Mapping manifest

For each source field, record:

- Source file and original column.
- Canonical role.
- Unit and transformation.
- Mapping confidence.
- Validation result.
- Ambiguity or unresolved status.
- Mapping version and provenance.

No missing field may be silently fabricated.

---

## 9. Application Output Contract

Freeze the contract with the application and local-LLM branch before integration.

The versioned JSON must include:

- `schema_version`
- `analysis_status`
- `interval`
- `forecast_energy`
- `actual_energy`
- `deviation`
- `waterfall`
- `anomalies`
- `hypotheses`
- `evidence`
- `limitations`
- `unresolved_fields`
- `model_version`
- `mapping_version`

All numerical values must have defined units. Unavailable values are `null`.

The waterfall should expose weather contribution, plant-side contributions and unresolved contribution where supported. The signed components must reconcile with the total deviation, while any positive loss ledger must avoid overlapping causes.

Each hypothesis should include supporting evidence, contradictory evidence, missing information and a clearly defined confidence interpretation where available.

The LLM must explain this structured output, not independently recalculate it.

---

## 10. Repository Structure

```text
globathon_models/
├── README.md
├── requirements.txt
├── configs/
│   ├── schema_vocab.yaml
│   └── experiment_defaults.yaml
├── data/
│   ├── README.md
│   ├── raw_public/
│   ├── raw_real_validation/
│   ├── synthetic/
│   └── processed/
├── src/
│   ├── ingestion/
│   ├── schema_mapping/
│   ├── validation/
│   ├── features/
│   ├── baseline/
│   ├── anomaly/
│   ├── attribution/
│   ├── recovery/
│   └── contracts/
├── scripts/
│   ├── inspect_datasets.py
│   ├── generate_synthetic.py
│   ├── validate_datasets.py
│   ├── benchmark_expected.py
│   ├── benchmark_anomaly.py
│   └── run_pipeline.py
├── tests/
├── reports/
└── artifacts/  # local only; git-ignored
```

`baseline/` contains the physics calculation and optional LightGBM residual model. `anomaly/` contains peer comparison, residual statistics, CUSUM and optional Isolation Forest. `attribution/` contains rules, event matching and waterfall calculations.

Keep raw data, private operational files, credentials and large model weights out of Git as appropriate. Document any pre-event libraries and dependencies according to the competition rules.

---

## 11. Schedule and Priorities

### Before kickoff

**Priority 1 — Must have**

- Output contract agreed with the application/LLM branch.
- Adaptive ingestion, schema mapping and data validation.
- Physics-based baseline.
- Peer comparison and evidence-based attribution.
- Waterfall arithmetic and counterfactual energy calculations.
- Synthetic scenario generator and tests.
- Offline execution and deterministic fallback.

**Priority 2 — Should have**

- LightGBM residual correction, if the data supports it.
- Held-out comparison against the physics-only baseline.
- Residual diagnostics and CUSUM.
- A documented real-data compatibility report.
- Runtime measurement and reproducible configuration.

**Priority 3 — Nice to have**

- Isolation Forest benchmark.
- Ridge or HistGradientBoosting comparison.
- Uncertainty intervals.
- Additional public datasets if they address a specific evidence gap.

Do not delay a working pipeline to add optional models.

### Competition day — 31 October 2026

| Approximate window | Goal |
|---|---|
| 08:00–11:00 | Inspect and map the dataset, confirm units/time zones and run validation |
| 11:00–16:00 | Run the pipeline, investigate evidence, refine rules and verify calculations |
| 16:00–19:00 | Freeze code, finalize findings, document limitations and rehearse the pitch |

Adjust these windows to the actual event schedule and team responsibilities. Do not claim the pipeline is complete until it has run against the supplied data.

---

## 12. Explicitly Out of Scope for the Initial Version

- Deep forecasting architectures such as LSTM and other neural networks.
- Autoencoders and other complex anomaly models.
- Local Outlier Factor and one-class SVM unless a specific need emerges.
- Supervised root-cause classification without reliable labels.
- Learned counterfactual intervention models.
- Multiple production forecasting models without evidence of improvement.
- Fine-tuning a local LLM before establishing whether a pretrained model and structured prompts are sufficient.
- Training the final model on synthetic data and assuming it transfers unchanged to a new plant.
- Treating the three existing real-plant files as a universal ML accuracy test set.

---

## 13. Claims Discipline

- Say **“flagged,” “consistent with”** or **“supported by evidence,”** not “diagnosed,” unless direct evidence justifies the stronger claim.
- Report energy impact in kWh/MWh with appropriate assumptions and uncertainty.
- Report money only when commercial inputs are available and verified.
- Never present synthetic metrics as field accuracy.
- Distinguish forecast error from plant underperformance.
- Do not assume that a low-generation period means a physical fault.
- Do not count the same interval's loss under multiple primary causes.
- Preserve an unresolved category when evidence is insufficient.
- Record what the system could not determine and why.

---

## 14. Definition of Done

The ML pipeline is ready for competition integration when:

1. Unseen CSV and Excel schemas can be inspected without plant-specific hardcoding.
2. Ambiguous columns, units and timestamps are flagged instead of silently guessed.
3. The physics baseline works and its assumptions are documented.
4. LightGBM is included only if it improves the held-out baseline meaningfully.
5. Synthetic scenarios are reproducible, varied and evaluated without leakage.
6. Peer/MAD detection and evidence-based attribution are tested.
7. The waterfall reconciles numerically without double-counting causes.
8. The three existing files have been checked for compatibility, with unsupported evaluations clearly marked.
9. The output contract is versioned and agreed with the application/LLM branch.
10. The complete pipeline runs locally without public AI inference APIs.
11. The deterministic fallback works when optional AI components are unavailable.
12. Results, limitations, runtime and failure cases are documented in `reports/`.

**Guiding principle:** Build the smallest reliable pipeline that can explain what the data supports, identify what it cannot determine and show its evidence. Complexity is justified only when measured results demonstrate a meaningful improvement.