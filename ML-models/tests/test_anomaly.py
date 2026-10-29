from src.anomaly import cusum, peer_mad


def test_peer_mad_returns_score(sample_frame):
    result = peer_mad(sample_frame)
    assert "anomaly_score" in result


def test_cusum_returns_summary(sample_frame):
    result = cusum(sample_frame)
    assert "cusum" in result
