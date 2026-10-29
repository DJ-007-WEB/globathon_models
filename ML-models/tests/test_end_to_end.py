from src.pipeline import run_pipeline
from src.synthetic import generate_batch


def test_pipeline_smoke(tmp_path):
    input_dir = tmp_path / "scenario"
    output_path = tmp_path / "result.json"

    generate_batch(input_dir, seed=7, n_scenarios=1, days=1, interval_minutes=60, capacity_kw=500.0)
    result = run_pipeline(input_dir / "scenario_000", output_path=output_path)

    assert result["schema_version"] == "1.0.0"
    assert result["analysis_status"] in {"ok", "warning", "unavailable"}
    assert output_path.exists()
    assert result["waterfall"]["status"] in {"ok", "warning", "unavailable"}
    assert result["metrics"]["rows"] > 0
