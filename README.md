# AI Model — Local LLM Workstream

## Purpose

This branch owns the local language-model work for Globathon 2026 Solar Recovery Intelligence. Its goal is to provide a locally runnable model that can explain supplied solar-plant analysis clearly, cautiously, and in a structured form.

The LLM is an explanation and communication component. It must not replace the ML model, invent plant measurements, or act as the source of authoritative energy or financial calculations.

## Responsibilities

1. Verify local inference with Ollama.
2. Prepare and validate instruction examples for the intended solar-analysis response behaviour.
3. Review dataset examples for factual correctness, diversity, duplicates, and leakage.
4. Select a compatible training environment and verify the model/library versions.
5. Fine-tune using an appropriate method such as LoRA only after compatibility and data-quality checks.
6. Compare the base and fine-tuned models on the same held-out tests.
7. Package or export the result for Ollama if the model architecture and artifact format support it.
8. Test the resulting model locally and document how the backend can call it.

## Current environment and verified status

- Local OS: Windows 11.
- Hardware: Intel Core i5-13420H, 16 GB RAM, NVIDIA RTX 4050 Laptop GPU with 6 GB VRAM.
- Local inference software: Ollama.
- Model currently installed: `qwen3.5:4b`.
- Local Ollama API: `http://localhost:11434`.
- GPU inference was observed through `ollama ps`.
- A synthetic instruction dataset of 1,200 training, 150 validation, and 150 synthetic test examples was generated; training and validation JSONL structure passed the validator.
- Dataset factual quality and suitability still require review.
- A preliminary heuristic evaluation reported 16 passing checks, but this is not comprehensive validation.

**Fine-tuning has not yet been completed.** The training script's compatibility with the selected model and GPU environment is not verified; no trained LoRA adapter, exported fine-tuned model, or base-versus-fine-tuned comparison has been confirmed.

## Planned workflow

1. Inspect the training script and the actual environment.
2. Confirm hackathon rules for external GPU training, model downloads, and dataset use.
3. Review and validate training, validation, and held-out test examples.
4. Run a small compatibility/smoke test before a full training job.
5. Fine-tune only if the setup is supported and the data is suitable.
6. Evaluate the fine-tuned model against the base model, including cases where evidence is insufficient.
7. Export and test the model through Ollama, if supported.
8. Document the model version, run instructions, API usage, latency, limitations, and integration assumptions.

## Required response behaviour

- Distinguish supplied observations from estimates and hypotheses.
- Explain only what is supported by the structured input.
- Explicitly state when there is insufficient evidence to identify a cause.
- Do not invent measurements, root causes, recovered energy, financial savings, or confidence scores.
- Identify missing information and relevant uncertainty.
- Return the agreed output format consistently.

## Integration boundary

The backend will orchestrate application requests and provide structured analysis results to the LLM. The separate ML-model workstream belongs to the teammate and is not implemented in this branch. Numeric predictions, energy-loss calculations, and financial calculations must remain in the appropriate deterministic or ML layer.

Ollama running on a developer's laptop is not automatically accessible to a separately hosted backend. The final architecture must account for this and satisfy the event's local-inference requirement.

## Development rules

- Do not commit secrets, private plant data, large model weights, or local environment folders.
- Do not treat synthetic examples as real plant data.
- Do not claim training, evaluation, export, or deployment succeeded without test evidence.
- Keep changes in this branch focused on the LLM workstream.


## Application API integration

The integration branch registers the FastAPI lifespan so `app.state.llm_service` is initialized before requests. Model weights remain lazy-loaded on the first inference call. The backend sends the deterministic ML result in `ml_results`; this service is responsible only for evidence-grounded explanation and structured response generation.

Set the same `INTERNAL_SERVICE_TOKEN` in the AI service and application backend. In production, set `ENVIRONMENT=production`; inference requests without the configured token are rejected. Keep the API bound to loopback for local development:

```powershell
$env:INTERNAL_SERVICE_TOKEN="same-long-random-secret-as-backend-and-ml"
python -m uvicorn api:app --host 127.0.0.1 --port 8000
```

The local adapter path and base model must match the actual trained/exported artifacts. This integration change fixes API initialization; it does not certify adapter availability, model compatibility, or inference quality.
