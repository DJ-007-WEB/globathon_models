# Live end-to-end harness (Linux/CI)

Runs the **real** ML service, backend and frontend on the standard ports, with two
test-only substitutions so the flow can be exercised without external infrastructure:

| Component | Substitution |
|---|---|
| MongoDB | `mongomock` in-process (`run_backend_inmemory.py`) |
| Local LLM | Real `llm-service` API, but generation replaced by scripted output (`fake_llm.py`). Extraction, normalisation, grounding and schema validation are the real code paths. |

This proves wiring, persistence, fallbacks and UI rendering. It does **not** prove
model quality, MongoDB Atlas connectivity or GPU/CPU inference speed; use
`scripts/verify-local-runtime.ps1` with the real model for that.

```bash
pip install mongomock            # test-only, in the backend venv
export INTERNAL_SERVICE_TOKEN=$(python -c "import secrets;print(secrets.token_urlsafe(32))")
(cd ml-service && python -m uvicorn api:app --host 127.0.0.1 --port 8002) &
(cd llm-service && python ../scripts/e2e/fake_llm.py) &
(cd backend && python ../scripts/e2e/run_backend_inmemory.py) &
(cd frontend && npm run dev) &
curl -X POST http://127.0.0.1:8000/warmup
python scripts/e2e/api_e2e.py <data-dir>          # data-dir holds stress.csv and synth/scenario_000/
node scripts/e2e/browser_e2e.cjs <data-dir>       # needs the playwright package
```

Generate `synth/` with `python ml-service/scripts/generate_synthetic.py --seed 7 --n-scenarios 3 --out <data-dir>/synth`.
`stress.csv` is any operating CSV (e.g. `synth/scenario_001/operating_data.csv` with extra columns such as
`rated_ac_power_kw`, `grid_frequency_hz`, `alarm_code`). Set `FAKE_LLM_MODE=fail` or stop the LLM to check fallbacks.
