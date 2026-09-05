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
