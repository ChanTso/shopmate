"""Snapshot measurements must survive the model's presentation picks."""

import pytest
from commerce_common.presentation import EnrichmentContext
from merchant_agent.enrichment import enrich_metrics, partial_metrics
from merchant_agent.tools.presentation import PresentMetricsPayload
from merchant_agent.types import BusinessSnapshot, MerchantSessionState


@pytest.mark.parametrize("units", [96, 0, None])
async def test_snapshot_units_reach_final_and_partial_cards_without_inventing_zero(units):
    state = MerchantSessionState()
    state.remember_snapshot(
        BusinessSnapshot(
            period="2026-08-22/2026-09-05",
            sales=2304,
            orders=32,
            units=units,
            currency="CNY",
        )
    )
    payload = PresentMetricsPayload.model_validate(
        {"picks": [{"metric": "sales"}, {"metric": "orders"}, {"metric": "units"}]}
    )
    context = EnrichmentContext(backend=None, config=None, session=None, state=state)

    final = await enrich_metrics(payload, context)
    partial = partial_metrics(payload.model_dump(), state)

    assert partial is not None
    for card in (final, partial):
        measures = {entry["metric"]: entry for entry in card["metrics"]}
        assert measures["sales"]["value"] == 2304
        assert measures["orders"]["value"] == 32
        if units is None:
            assert "units" not in measures
        else:
            assert measures["units"]["value"] == units
            assert measures["units"]["change_pct"] is None
    if units is None:
        assert context.notes == ["Skipped metrics not returned this session: units."]
    else:
        assert context.notes == []
