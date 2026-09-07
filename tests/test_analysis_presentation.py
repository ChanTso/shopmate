"""Submitted analysis stays visible without a second model-authored explanation."""

from merchant_agent.analysis import derive_metrics_payload
from merchant_agent.types import AnalysisFigure, AnalysisResult


def test_analysis_card_keeps_payment_scope_and_method_beside_figures():
    headline = "只统计成功付款的历史成交，排除未支付和失败付款。" * 4
    result = AnalysisResult(
        question="本期成交额如何计算？",
        headline=headline,
        findings=["成交额为 120.00 CNY；PENDING 和 FAILED 付款未计入。"],
        figures=[AnalysisFigure(label="成交额", value=120, unit="CNY")],
        caveats=["成交额是退款前口径，不等于净收入。"],
        method_note="按 UTC 左闭右开窗口筛选成功付款时间，汇总订单历史金额。",
    )

    payload = derive_metrics_payload(result)

    assert payload["metrics"][0]["value"] == 120
    assert payload["analysis"]["headline"] == headline
    assert len(payload["analysis"]["headline"]) > len(payload["title"])
    assert payload["analysis"]["findings"] == [
        "成交额为 120.00 CNY；PENDING 和 FAILED 付款未计入。"
    ]
    assert payload["analysis"]["caveats"] == ["成交额是退款前口径，不等于净收入。"]
    assert payload["analysis"]["method_note"] == (
        "按 UTC 左闭右开窗口筛选成功付款时间，汇总订单历史金额。"
    )


def test_analysis_without_figures_keeps_unsold_product_price_and_limits():
    result = AnalysisResult(
        question="无成交商品目前什么价格？",
        headline="该商品本期没有成功付款记录",
        findings=["便携水杯当前标价为 39.00 CNY，商品仍可售。"],
        caveats=["没有成交记录不能证明价格过高。"],
    )

    payload = derive_metrics_payload(result)

    assert payload["metrics"] == []
    assert payload["analysis"]["headline"] == "该商品本期没有成功付款记录"
    assert payload["analysis"]["findings"] == ["便携水杯当前标价为 39.00 CNY，商品仍可售。"]
    assert payload["analysis"]["caveats"] == ["没有成交记录不能证明价格过高。"]
    assert payload["analysis"]["method_note"] is None


def test_analysis_figures_publish_units_without_inferring_currency_from_labels():
    result = AnalysisResult(
        question="Compare the returned measurements",
        headline="Each figure retains its own unit",
        figures=[
            AnalysisFigure(label="sales", value=280, unit="USD"),
            AnalysisFigure(label="sales", value=120, unit="CNY"),
            AnalysisFigure(label="sales", value=12.5, unit="%"),
            AnalysisFigure(label="sales", value=28, unit="件"),
            AnalysisFigure(label="sales", value=9),
        ],
    )

    metrics = derive_metrics_payload(result)["metrics"]

    assert [(entry["unit"], entry["currency"]) for entry in metrics] == [
        ("USD", "USD"),
        ("CNY", "CNY"),
        ("%", None),
        ("件", None),
        (None, None),
    ]
    assert metrics[0]["value"] == 280
    assert metrics[2]["value"] == 12.5


def test_full_analysis_table_and_rendered_card_survive_real_session_store_restart(
    tmp_path,
):
    from commerce_common.streaming import AgentEvent
    from merchant_agent.types import AnalysisTable

    from shopmate.app import _ui_event
    from shopmate.sessions import SessionStore

    path = tmp_path / "analysis.sqlite3"
    store = SessionStore(path)
    record = store.create("merchant-owner")
    rows = [[f"sku-{i}", str(i / 100), "CNY", None] for i in range(1, 88)]
    result = AnalysisResult(
        question="列出所有商品",
        headline="87 个商品",
        findings=["完整明细见表格。"],
        table=AnalysisTable(
            columns=["sku", "amount", "currency", "unknown"], rows=rows, row_count=87
        ),
    )
    record.state.remember_analysis(result)
    payload = derive_metrics_payload(result)
    record.items = [{"kind": "assistant", "segments": [], "turn": "turn-1", "changeIds": []}]
    _ui_event(record, AgentEvent.ui("metrics", payload))
    store.save(record)
    store.close()
    store = SessionStore(path)
    try:
        restored = store.get(record.session_id, "merchant-owner")
        assert restored.state.seen_analyses[result.analysis_id].table.rows == rows
        assert (
            restored.items[0]["segments"][0]["block"]["payload"]["analysis"]["table"]["rows"]
            == rows
        )
        assert not restored.state.seen_listings and not restored.state.read_listings
        assert not restored.state.seen_campaigns
    finally:
        store.close()
