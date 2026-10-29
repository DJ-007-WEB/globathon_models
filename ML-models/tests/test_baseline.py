from src.baseline import physics_baseline, residual_model


def test_physics_baseline_returns_summary(sample_frame):
    result = physics_baseline(sample_frame)
    assert result["rows"] == 2
    assert "baseline" in result


def test_residual_model_returns_summary(sample_frame):
    result = residual_model(sample_frame)
    assert result["rows"] == 2
    assert "residuals" in result
