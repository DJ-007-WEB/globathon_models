# Local LLM API — Solar Recovery Intelligence

This service connects the fine-tuned Qwen LoRA adapter to the backend/frontend workflow. It accepts outputs from the teammate's ML models. It does not implement those ML models or a document retriever.

## Files

- api.py: FastAPI routes, CORS and health checks.
- llm_service.py: lazy model loading, prompt construction, inference and JSON validation.
- schemas.py: request/response contracts.
- requirements-api.txt: runtime dependencies.
- .env.example: configuration template.
- tests/test_api.py: API contract tests with model inference mocked.

## Install and start

Run these commands from the repository root with .venv-ai activated:

    python -m pip install -r requirements-api.txt
    Copy-Item .env.example .env
    python -m uvicorn api:app --host 127.0.0.1 --port 8000 --reload

The adapter should exist at models/solar-qwen-lora-final/adapter_config.json. The base model must be downloadable from Hugging Face or already cached. The model loads on the first analysis request, so that request takes longer. Open http://127.0.0.1:8000/docs to explore the API.

- GET /health: liveness check, no model loading.
- GET /ready: indicates whether model weights have been loaded.
- POST /api/v1/analyze: sends plant observations and ML outputs to the LLM.

## Request contract

    {
      "request_id": "req-001",
      "plant_id": "plant-demo-01",
      "timestamp": "2026-10-30T11:30:00+05:30",
      "plant_context": {"installed_capacity_kw": 500},
      "observations": {"irradiance_w_m2": 720, "ambient_temperature_c": 32, "inverter_status": "normal", "inverter_output_kw": 310, "data_quality": "not_verified"},
      "ml_results": {"fault_classifier": {"predicted_label": "possible_inverter_underperformance", "model_score": 0.71}, "expected_output_kw": {"value": 350, "source": "power_estimation_model"}},
      "retrieved_context": []
    }

The values are illustrative only. Replace them with real ML outputs and plant readings. The API passes these values to the model; it does not calculate or verify the model score or expected output.

The response envelope contains request_id, plant_id, model, and analysis. The analysis object contains summary, observations, possible_causes, supporting_evidence, recommended_checks, limitations, and confidence. The frontend should render these fields in UI components instead of displaying raw JSON.

## Frontend example

    const response = await fetch("http://127.0.0.1:8000/api/v1/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail ?? "Analysis request failed");
    }
    const result = await response.json();
    // Render result.analysis.summary, result.analysis.supporting_evidence, etc.

The frontend origin must be listed in CORS_ORIGINS. A frontend in a browser can reach this API only when the machine running it is network-accessible. A separately hosted backend cannot use 127.0.0.1 to reach your laptop.

## ML and RAG boundary

Call the teammate's ML models first, then pass their outputs in ml_results and source readings in observations. Keep energy-loss, expected-generation and financial calculations in deterministic code or the appropriate ML component. This API accepts optional retrieved_context excerpts but does not perform retrieval itself; connect a real retriever separately.

The generic dictionaries are intentional because the teammate's exact output schema has not been provided. Once it is agreed, replace them with typed models. Pydantic validation verifies response shape, not factual correctness; held-out evaluation and evidence-grounding tests are still required.

## Contract tests

    python -m pip install httpx pytest
    python -m pytest -q

Tests mock model inference and do not test model quality or GPU inference. Do not commit model weights, .venv-ai, datasets, .env, or private plant data.
