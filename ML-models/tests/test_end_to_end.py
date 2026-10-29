from src.pipeline import run_pipeline


def test_pipeline_stub_runs():
    result = run_pipeline("example.csv")
    assert result["status"] == "stubbed"
    assert result["input"] == "example.csv"
