from src.synthetic import FaultLibrary, generate_synthetic_series


def test_fault_library_sag_reduces_values():
    values = [100.0, 90.0, 80.0]
    reduced = FaultLibrary.sag(values, severity=1.0)
    assert reduced[0] < values[0]
    assert reduced[1] < values[1]


def test_generate_synthetic_series_uses_baseline():
    series = generate_synthetic_series(4, lambda idx: float(idx) * 10)
    assert series == [0.0, 10.0, 20.0, 30.0]
