"""Run the real LLM API with a scripted generator instead of model weights. Test harness only.

Run from llm-service/: python ../scripts/e2e/fake_llm.py
The scripted raw text deliberately includes a bare key, an invented measurement
and an overconfident cause so the real extraction, normalisation and grounding
guard are exercised. FAKE_LLM_MODE=fail simulates an inference failure.
"""
import json
import os
import sys

sys.path.insert(0, os.getcwd())
import llm_service  # noqa: E402

MODE = os.getenv("FAKE_LLM_MODE", "good")


def fake_load(self):
    self.model, self.tokenizer, self.resolved_model_name = object(), object(), "scripted-test-model"


def fake_analyze(self, request):
    self._load()
    if MODE == "fail":
        self.last_inference_error = "Simulated inference failure."
        raise ValueError("simulated")
    ml = request.ml_results
    energy = ml.get("energy", {})
    actual = (energy.get("actual") or {}).get("value_kwh")
    expected = (energy.get("expected") or {}).get("value_kwh")
    raw = "<think>scratch</think>```json\n" + json.dumps({
        "summary": f"Analysis status: {ml.get('analysis_status')}. Measured energy was {actual} kWh "
                   f"against expected {expected} kWh.",
        "observations": [f"Measured energy was {actual} kWh.", "actual_energy", "Peak output was 99999 kWh."],
        "possible_causes": ["Soiling is the confirmed cause."],
        "supporting_evidence": [str(item) for item in ml.get("evidence", [])[:2]],
        "recommended_checks": ["Compare inverter logs for the reported interval."],
        "limitations": ml.get("limitations", [])[:3],
        "confidence": "high",
    }) + "\n```"
    return self._finalize(raw, request)


llm_service.LLMService._load = fake_load
llm_service.LLMService.analyze = fake_analyze

import api  # noqa: E402
import uvicorn  # noqa: E402

uvicorn.run(api.app, host="127.0.0.1", port=8000)
