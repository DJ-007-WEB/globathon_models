from src.counterfactual import EnergyLedger, Waterfall


def test_energy_ledger_tracks_total_loss():
    ledger = EnergyLedger()
    ledger.add_event("soiling", 10.0, "dust")
    ledger.add_event("shading", 5.0, "trees")
    assert ledger.total_loss_kwh() == 15.0


def test_waterfall_aggregates_losses():
    losses = [10.0, 20.0, 30.0]
    assert Waterfall.aggregate(losses) == 60.0
    assert sum(Waterfall.percent_of_total(losses)) == 1.0
