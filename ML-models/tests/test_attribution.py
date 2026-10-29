from src.attribution import explain_interval


def test_explain_interval_returns_causes():
    result = explain_interval({"timestamp": "x"})
    assert "causes" in result
    assert "confidence" in result
