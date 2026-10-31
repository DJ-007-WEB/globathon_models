from src.contract import build_contract


def test_build_contract_has_schema_version():
    contract = build_contract("ok", "ready", {"n": 1})
    assert contract.schema_version == "2.1.0"
    assert contract.analysis_status == "success"
    assert contract.summary == "ready"
