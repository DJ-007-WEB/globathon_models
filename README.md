# Globathon Models — Solar Recovery Intelligence

> **Purpose:** A dedicated workspace for developing, evaluating, and packaging the local AI/ML components that will power our Globathon 2026 solar-plant recovery platform.

This repository is intended to hold the model-development code, training and evaluation pipelines, configuration, and documentation for our solar performance diagnosis and recovery workflow. It is a companion to the main application repository; it is **not yet a claim that any model has been trained or validated on real plant data**.

## The problem we are solving

Solar operators need more than a chatbot that summarizes a CSV. They need to know:

- **What is underperforming?** Detect abnormal production and distinguish it from expected weather-driven variation.
- **What evidence supports the diagnosis?** Separate measured facts, model estimates, uncertain hypotheses, and unexplained loss.
- **What should be done first?** Estimate recoverable energy and financial value, account for action cost and uncertainty, and rank practical interventions.
- **Did the action work?** Compare the observed post-intervention result with a weather-adjusted expectation and record prediction versus outcome.

Our differentiator is intended to be an **evidence-backed recovery workflow**: model outputs feed reproducible calculations and operational decisions, and outcomes can later improve calibration. A language model may explain those results, but it must not invent measurements, diagnoses, savings, or confidence scores.

## Planned model components

These are development targets, not completed features. We will prioritize them after reviewing the available dataset and its schema.

| Component | Purpose | Likely first approach | What it must output |
| --- | --- | --- | --- |
| Generation / performance prediction | Estimate expected plant output under the observed conditions | Establish a physics/model-based baseline first; evaluate tree-based regression only when suitable historical data is available | Prediction, error metrics, and calibrated uncertainty where possible |
| Anomaly detection | Flag unusual production, inverter, sensor, or performance patterns | Robust statistical baselines; compare Isolation Forest or other methods only if justified by the data | Anomaly score, time window, relevant signals, and reason codes |
| Root-cause support | Help distinguish candidate causes such as downtime, soiling, curtailment, temperature effects, or sensor issues | Rules and physics-based evidence first; supervised classification only if reliable cause labels exist | Ranked hypotheses with evidence and confidence limitations |
| Local language model (LLM) | Turn structured diagnostics into clear, evidence-grounded explanations and action summaries | Evaluate a suitable locally runnable pretrained model before considering fine-tuning | Explanation linked to supplied evidence; explicit uncertainty and missing-data notes |
| Recovery / intervention evaluation | Estimate the possible benefit of an action and compare it with cost and risk | Deterministic counterfactual calculations and scenario analysis, supported by validated prediction components | Estimated energy recovery, financial impact, assumptions, uncertainty, and verification plan |

**Important:** An LLM is not the same thing as a predictive ML model. We should not train a model merely to make the project sound AI-powered. Every component must have a defined input, output, baseline, and evaluation method.

## Development principles

1. **Inspect the data before choosing a model.** Document its source, time resolution, units, missing values, labels, and whether it represents real or synthetic plant behaviour.
2. **Build a baseline first.** A simple, testable baseline is the reference against which a more complex model must demonstrate improvement.
3. **Prevent data leakage.** For time-series data, split training, validation, and test sets chronologically where appropriate. Do not let future observations leak into features used to predict the past.
4. **Evaluate on held-out data.** Report suitable metrics, baseline comparisons, failure cases, and performance across relevant operating conditions.
5. **Keep explanations grounded.** The LLM should receive structured results from the calculation/model layer and explain them; it should not replace the calculation layer.
6. **Track reproducibility.** Record dataset version, feature definitions, model/configuration version, random seeds where applicable, metrics, and training instructions.
7. **Keep secrets and large artifacts out of Git.** Do not commit API keys, private plant/customer data, virtual environments, or large model weights. Use documented download instructions or Git LFS / artifact storage if needed.
8. **Be honest about evidence.** Synthetic data is useful for testing the pipeline, but does not prove real-world performance. Recommendations must be labelled estimates until validated.

## Suggested repository layout

The structure below is a target layout and can be introduced incrementally as the implementation grows.

```text
globathon_models/
├── README.md
├── requirements.txt              # or pyproject.toml, once dependencies are chosen
├── configs/                      # versioned, non-secret experiment settings
├── data/
│   ├── README.md                 # dataset schema, provenance, and access instructions
│   └── .gitkeep                  # keep private/raw data out of Git
├── notebooks/                    # exploration and experiments
├── src/
│   ├── forecasting/              # expected-generation baselines/models
│   ├── anomaly_detection/        # anomaly baselines and models
│   ├── root_cause/               # evidence and cause-classification experiments
│   ├── llm/                      # local inference, prompts, and optional adapters
│   └── recovery/                 # counterfactual and intervention evaluation
├── scripts/                      # data checks, training, evaluation, inference
├── tests/                         # unit and pipeline tests
├── artifacts/                    # local-only outputs; ignored by Git
└── reports/                       # evaluation summaries and experiment results
```

## Data requirements

Before selecting and training models, record which fields are actually available. Potentially useful signals include:

- Timestamp, plant/site identifier, and timezone
- Actual energy or power, expected/forecast generation, and plant capacity
- Irradiance and ambient/module temperature
- Inverter or equipment status, downtime, and fault/event logs
- Grid curtailment or export limits
- Soiling/cleaning records, maintenance actions, and intervention timestamps
- Sensor quality flags, missingness, and meter provenance
- Tariff or other verified commercial assumptions if financial impact is calculated
- Verified root-cause labels and post-action outcomes, if available

This list is a **data checklist, not an assertion that these fields are already present**. We must adapt the pipeline to the real schema and explicitly identify missing signals. Without verified labels, a root-cause classifier cannot be honestly supervised; without post-intervention observations, claimed recovery cannot be validated.

## Local model strategy

- Start by checking the available machine (RAM, CPU, GPU/VRAM) and the data size.
- For tabular forecasting and anomaly detection, begin with interpretable statistical or tree-based baselines where appropriate.
- For explanations, first run a suitable pretrained LLM locally and test whether it can follow a strict evidence-only output format. Fine-tuning is optional, not the starting assumption.
- Consider LLM fine-tuning only after collecting a suitable, permitted set of high-quality input/output examples and defining an evaluation set. Fine-tuning does not automatically give the model reliable solar physics or up-to-date plant facts.
- Keep numeric predictions, financial calculations, intervention rankings, and uncertainty calculations in tested code. Use the LLM primarily to communicate their meaning.

No specific model, framework, dataset, or hardware requirement is locked in yet. Those decisions will follow a dataset and environment review.

## Evaluation checklist

For each component, document:

- Task definition and intended use
- Data source, schema, data-quality checks, and split strategy
- Baseline and reason for choosing the candidate model
- Relevant metrics (for example MAE/RMSE for forecasting, precision/recall for labelled detection tasks, or measured false-alert rate for anomaly detection)
- Performance on held-out examples and important failure cases
- Calibration and uncertainty limitations
- Inference latency and local hardware requirements
- Model/configuration version and reproducible run instructions

For the LLM, additionally test unsupported-claim rate, evidence citation/traceability, consistency, refusal or escalation when data is insufficient, and whether it follows the required output schema.

## Current status

- [x] Repository purpose and initial development plan documented
- [ ] Inspect available dataset and define its schema
- [ ] Record local hardware and choose an environment
- [ ] Establish a baseline and evaluation split
- [ ] Implement and evaluate the first predictive/anomaly component
- [ ] Prototype grounded local LLM inference
- [ ] Integrate model outputs with the main platform's recovery workflow
- [ ] Validate on held-out and, when available, real plant data

## Relationship to the main application

The main platform owns the user workflow, plant-level diagnostics, counterfactual recovery calculations, action ranking, and post-action verification. This repository owns reusable model experiments and model-serving components. Integration contracts should be explicit: input schema, output schema, units, timestamps, confidence/uncertainty fields, model version, and error behaviour.

Until the components are implemented and evaluated, outputs must be presented as experimental and must not be represented as validated operational advice.

## Contributing workflow

1. Create or switch to a focused feature branch.
2. Add a short experiment note describing the hypothesis and baseline.
3. Keep raw/private data and model weights out of source control.
4. Add tests for data handling and output contracts.
5. Record evaluation results before claiming an improvement.
6. Merge only changes that are reproducible and documented.

---

**Project:** Globathon 2026 · Solar Recovery Intelligence  
**Status:** Model-development workspace / early stage
