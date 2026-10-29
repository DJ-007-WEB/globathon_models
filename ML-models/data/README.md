# Data Registry

This folder is for local data only. Contents of `raw_public/`,
`raw_real_validation/`, `synthetic/` and `processed/` are git-ignored and must
not be committed. Missing readings stay missing; no dataset is downloaded
automatically by this repository.

## Dataset registry

Record one row per dataset actually used. Do not claim a licence or version that
has not been verified.

| Dataset | Version / retrieval date | Licence | Fields observed | Resolution / coverage | Intended use | Known limitations |
|---|---|---|---|---|---|---|
| Kaggle Solar Power Generation Data — Ani Kannal (`raw_public/kaggle_solar/Plant_1_Generation_Data.csv`) | Local copy; retrieval date not recorded in repo | Not verified in this repository; check Kaggle listing | `DATE_TIME`, `PLANT_ID`, `SOURCE_KEY`, `DC_POWER`, `AC_POWER`, `DAILY_YIELD`, `TOTAL_YIELD` (observed from local header) | 15-minute-looking rows, Plant 1, May 2020 (observed; verify at kickoff) | Ingestion, schema-discovery and layout tests; unlabelled peer/residual experiments | No verified fault labels; units/time zone are not stated in the header and must remain unresolved until confirmed |
| Mendeley PV SCADA (`raw_public/mendeley_pv/`) | Local copy; retrieval date not recorded in repo | Not verified in this repository; check Mendeley record 9fdvyjrf67 | `export_timestamp`, `inverter_id`, `energy_kwh`, `reactive_power_kvar`, `curtailment_flag`, `tariff_rate`, `revenue_usd`, `power_factor`, `frequency_hz`; inverter SCADA headers also present | 30-minute-looking rows, April 2025 (observed; verify) | Ingestion, long-layout mapping, unit evidence and status/event fields | Contains tariff/revenue fields that are dataset-specific; do not reuse as verified commercial inputs for another plant |
| Zenodo TECNALIA PV dataset (`raw_public/zenodo_pv/TECNALIA/`) | Local copy; retrieval date not recorded in repo | Not verified in this repository; check Zenodo record 18326501 | Metadata sheets in `Electric_information_TECNALIA.csv` and `Meteo_information_TECNALIA.csv`; per-device time series in `data_*/data_*.csv` | 5-minute-looking rows, November 2024 (observed; verify) | Metadata/inspection tests and wide/long layout examples | Multi-file structure, semicolon separators, metadata rows and per-device files; not a fault-labelled benchmark |
| Synthetic scenarios (`synthetic/`) | Generated locally by this project; stamp each run with its generator version | Project-generated; not third-party data | Defined by the generator and its metadata; must be clearly stamped `synthetic` | Controlled scenarios; see generator metadata | Pipeline and detector tests only | Synthetic results are controlled-test results, never field accuracy |
| Real-plant validation files (`raw_real_validation/`) | Pending at kickoff | Pending verification | Pending | Pending | Ingestion, schema discovery and supported sanity checks | `Project Viability.xlsx`, `SPV-01_SPV-02_Generation_Performance_Summary_Aug26.pdf` and `DGR Vayudoot Solar Bhainsa _June'2021.xlsx` are validation assets, not automatically a model accuracy test set. PDFs are not parsed. |

## Notes for new datasets

For every new file, record:

- source name, version or retrieval date;
- licence and any redistribution restrictions;
- original columns, units and timestamp/time-zone evidence;
- sampling interval and coverage;
- intended use and limitations;
- whether it is synthetic, public or real-plant data.

Ambiguous units, time zones or day/month ordering must be recorded as unresolved
rather than guessed.
