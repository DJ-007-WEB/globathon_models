# Solar Recovery Intelligence — Globathon 2026

## Project overview

Solar Recovery Intelligence is a hackathon project intended to help solar-plant operators understand underperformance, investigate plausible causes using available evidence, and make better-informed recovery decisions.

When observed generation is lower than expected, the application should help users examine relevant plant and environmental signals, distinguish measured facts from hypotheses, and communicate findings and possible next actions clearly. Potentially relevant factors include irradiance and cloud cover, panel temperature, inverter status, plant generation, grid availability or curtailment, and missing or abnormal sensor readings. These are examples of possible inputs; not every signal is guaranteed to be available.

## Intended system

The solution combines four collaborating parts:

1. **Frontend** — the operator-facing interface for entering or reviewing plant information and presenting analysis.
2. **Backend** — the application API and orchestration layer that validates requests, coordinates available analysis components, and returns results to the frontend.
3. **ML models** — the separate modelling workstream owned by the ML teammate. It provides data-driven analysis and structured outputs where implemented.
4. **AI model / local LLM** — the local language-model workstream that explains supplied evidence and analysis in clear, useful language.

The exact request/response schemas and integration details will be agreed before integration. Numeric calculations and ML predictions must come from the appropriate code/model layer, not be invented by the LLM.

## Evidence-first principles

- Separate observations, model estimates, assumptions, and hypotheses.
- Do not claim an inverter fault or another root cause without supporting evidence.
- Do not invent plant measurements, recovered energy, savings, or confidence values.
- State when required data is missing or the evidence is insufficient.
- Treat synthetic examples as test data, not real plant telemetry or proof of real-world performance.
- Present recovery suggestions as estimates until they are validated.

## Repository branch responsibilities

- **`main`** — this project overview and shared high-level context.
- **`frontend`** — frontend interface and user experience.
- **`backend`** — API, validation, orchestration, and integration contracts.
- **`AI-model`** — local LLM setup, dataset preparation for LLM fine-tuning, training/evaluation, compatible Ollama packaging, and local inference.
- **`ML_models`** — separate ML-model workstream maintained by the teammate; changes to that branch are outside this branch's scope.

## Current status and scope

The local environment has Ollama and the `qwen3.5:4b` model installed, and local GPU inference has been observed. A synthetic instruction dataset has passed structural JSONL validation, but its factual quality still needs human review. LoRA fine-tuning has **not** been completed, and no fine-tuned model has yet been proven to work through Ollama. The ML implementation and final application integration must be assessed on their own evidence.

The hackathon plan is to prepare components in advance, integrate the frontend, backend, ML outputs, and local LLM during the event, then deploy and test the complete application. The local-inference requirement and event rules must be respected.

## Development workflow

1. Agree on the user workflow, inputs, outputs, and API contracts.
2. Implement each component on its own branch.
3. Test components independently before integration.
4. Integrate using explicit, documented schemas.
5. Test insufficient-data cases, failure handling, and end-to-end behaviour.
6. Document what has actually been implemented and evaluated; do not describe planned features as completed.

See each branch's README for its specific responsibility.
