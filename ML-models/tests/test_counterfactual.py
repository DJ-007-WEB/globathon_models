import pytest

from src.counterfactual import EnergyLedger, Waterfall, compute_waterfall


def test_energy_ledger_tracks_total_loss():
    ledger = EnergyLedger()
    ledger.add_event("soiling", 10.0, "dust")
    ledger.add_event("shading", 5.0, "trees")
    assert ledger.total_loss_kwh() == 15.0


def test_waterfall_reconciles_weather_and_plant_effects():
    result = Waterfall.reconcile(100.0, 130.0, 90.0)
    assert result["status"] in {"ok", "warning"}
    assert result["weather_effect_kwh"] == 30.0
    assert result["plant_effect_kwh"] == -40.0
    assert result["total_deviation_kwh"] == -10.0
    assert result["reconciled"] is True


def test_power_to_energy_uses_interval_hours():
    stored, reason = Waterfall.convert_to_kwh(20.0, unit="kW", interval_hours=0.5)
    assert reason is None
    assert stored == 10.0

    stored_2, reason_2 = Waterfall.convert_to_kwh(20000.0, unit="W", interval_hours=0.5)
    assert reason_2 is None
    assert stored_2 == 10.0


def test_missing_or_unsupported_inputs_mark_unavailable():
    missing = Waterfall.reconcile(None, 120.0, 80.0)
    assert missing["status"] == "unavailable"

    unsupported = Waterfall.convert_to_kwh(25.0, unit="foo", interval_hours=1.0)
    assert unsupported[0] is None
    assert unsupported[1] is not None


def test_forecast_alignment_does_not_upsample():
    aligned, reason = Waterfall.aggregate_energy_to_resolution(
        [5.0, 5.0],
        source_interval_hours=0.5,
        target_interval_hours=1.0,
    )
    assert reason is None
    assert aligned == 10.0

    upsampled, reason_2 = Waterfall.aggregate_energy_to_resolution(
        [5.0, 5.0],
        source_interval_hours=1.0,
        target_interval_hours=0.5,
    )
    assert upsampled is None
    assert reason_2 is not None


def test_primary_cause_cannot_overlap_same_interval():
    ledger = EnergyLedger()
    ledger.add_event("soiling", 5.0, "dust", interval_id="I-1", primary=True)
    with pytest.raises(ValueError):
        ledger.add_event("shading", 3.0, "shadow", interval_id="I-1", primary=True)


def test_compute_waterfall_keeps_ledger_and_breakdown_separate():
    result = compute_waterfall(
        100.0,
        130.0,
        90.0,
        causes=[
            {"interval_id": "I-1", "loss_kwh": 40.0, "primary": True, "source": "plant"},
            {"interval_id": "I-2", "loss_kwh": 10.0, "primary": False, "source": "weather"},
        ],
    )
    assert result["weather_effect_kwh"] == 30.0
    assert result["plant_effect_kwh"] == -40.0
    assert result["total_deviation_kwh"] == -10.0
    assert result["loss_ledger_kwh"] == 50.0
    assert len(result["primary_causes"]) == 1


def test_waterfall_aggregates_losses():
    losses = [10.0, 20.0, 30.0]
    assert Waterfall.aggregate(losses) == 60.0
    assert sum(Waterfall.percent_of_total(losses)) == 1.0
