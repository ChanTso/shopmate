"""CityBuddy-backed reads and durable price proposals for the merchant runtime."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from commerce_common.config import ThinkingEffort
from merchant_agent.backend import MerchantBackend
from merchant_agent.changes import ChangeNotApplicable
from merchant_agent.config import MerchantAgentConfig
from merchant_agent.types import (
    ActorKind,
    AlertCounts,
    BusinessSnapshot,
    ListingFilters,
    MerchantSessionContext,
    MetricPoint,
    MetricSeries,
    PriceUpdateItem,
    PricingContext,
    StagedChange,
)
from sqlglot import exp

from . import presentation
from .analysis_sql import SCHEMA, AnalysisSQL
from .auth import AuthClient, current_context
from .commerce_client import CommerceClient, CommerceError, CurrencySummary, DraftView
from .sessions import SessionStore


class ShopMateConfig(MerchantAgentConfig):
    brand_name: str = "ShopMate"
    assistant_name: str = "商家经营助手"
    brand_voice: str = "使用中文，先给经营结论，再列来自工具的金额、期间和依据"
    enable_analysis: bool = True
    analysis_sql_only: bool = True
    analysis_use_code_execution: bool = False
    enable_memory: bool = False
    enable_web_search: bool = False
    enable_listing_edits: bool = False
    enable_inventory: bool = False
    enable_campaigns: bool = False
    enable_pricing: bool = True
    max_items_per_change: int = 3
    stage_shows_preview: bool = True
    require_host_approval: bool = True
    approval_surface: str = "商家工作台草案卡片的批准按钮"
    thinking_effort: ThinkingEffort | None = None

    def absent_tools(self) -> frozenset[str]:
        return super().absent_tools() | {"apply_change", "stage_promotion"}


@dataclass(frozen=True)
class Period:
    start: datetime
    end: datetime

    @property
    def label(self) -> str:
        return f"{self.start.isoformat()}/{self.end.isoformat()}"

    def previous(self) -> Period:
        return Period(self.start - (self.end - self.start), self.start)


def reporting_period(session: MerchantSessionContext, period: str | None) -> Period:
    reference = session.local_now() or datetime.now(UTC)
    if reference.tzinfo is None:
        raise ValueError("Merchant reporting clock must include a timezone")
    reference = reference.astimezone(UTC)
    midnight = reference.replace(hour=0, minute=0, second=0, microsecond=0)
    value = (period or "last_14_days").strip()
    rolling = re.fullmatch(r"(last|previous)_(\d+)_days", value)
    if rolling:
        days = int(rolling.group(2))
        if not 1 <= days <= 366:
            raise ChangeNotApplicable("查询期间需为 1 至 366 天。")
        end = midnight - timedelta(days=days if rolling.group(1) == "previous" else 0)
        result = Period(end - timedelta(days=days), end)
    elif value == "yesterday":
        result = Period(midnight - timedelta(days=1), midnight)
    elif value == "today":
        result = Period(midnight, reference)
    elif value == "this_month":
        result = Period(midnight.replace(day=1), reference)
    elif value == "last_month":
        end = midnight.replace(day=1)
        result = Period((end - timedelta(days=1)).replace(day=1), end)
    else:
        parts = value.split("/")
        if len(parts) != 2:
            raise ChangeNotApplicable(
                "请使用 last_14_days、previous_14_days、yesterday、last_month，"
                "或明确的 ISO 开始/结束时间；结束时间不包含在内。"
            )
        try:
            dates = [datetime.fromisoformat(part) for part in parts]
            dates = [
                item.replace(tzinfo=UTC) if item.tzinfo is None else item.astimezone(UTC)
                for item in dates
            ]
            result = Period(*dates)
        except ValueError:
            raise ChangeNotApplicable("查询起止时间必须是有效的 ISO 日期或时间。") from None
    if not timedelta(0) < result.end - result.start <= timedelta(days=366):
        raise ChangeNotApplicable("查询起点必须早于终点，跨度不超过 366 天。")
    return result


def _literal(value: str) -> str:
    return exp.Literal.string(value).sql(dialect="mysql")


def _change_pct(current: int, previous: int) -> float | None:
    return round((current - previous) / previous * 100, 2) if previous else None


class CityBuddyMerchantBackend(MerchantBackend):
    def __init__(
        self, auth: AuthClient, store: SessionStore, client: CommerceClient, sql: AnalysisSQL
    ):
        self.auth, self.store, self.client, self.sql = auth, store, client, sql

    @staticmethod
    def _bound(session: MerchantSessionContext):
        context = current_context()
        if context.session_id != session.session_id or context.identity.subject != session.operator:
            raise CommerceError(403, "CONTEXT_MISMATCH", "Merchant session context does not match")
        return context

    async def _token(self, session: MerchantSessionContext, scope: str) -> str:
        context = self._bound(session)
        return await self.auth.exchange(context.identity, session.session_id, scope)

    async def _recover_prepares(self, session: MerchantSessionContext) -> None:
        self._bound(session)
        missing = [
            intent
            for intent in self.store.intent_rows(session.session_id)
            if intent.draft_id is None and intent.rejection is None
        ]
        if not missing:
            return
        token = await self._token(session, "merchant:price:prepare")
        for intent in missing:
            try:
                draft = await self.client.prepare(
                    intent.body, intent.key, token, session.session_id
                )
            except CommerceError as error:
                if self._prepare_rejected(error):
                    self.store.reject_intent(intent.key, error.category)
                    continue
                raise
            self.store.attach_draft(intent.key, draft.draftId, draft.model_dump(mode="json"))

    @staticmethod
    def _prepare_rejected(error: CommerceError) -> bool:
        return error.status_code in (400, 404, 409) and error.category in {
            "VALIDATION",
            "NOT_FOUND",
            "PRODUCT_NOT_EDITABLE",
            "IDEMPOTENCY_CONFLICT",
        }

    async def _drafts(self, session: MerchantSessionContext) -> list[DraftView]:
        await self._recover_prepares(session)
        ids = self.store.draft_ids(session.session_id)
        if not ids:
            return []
        token = await self._token(session, "merchant:price:read")
        drafts = []
        for draft_id in ids:
            draft = await self.client.draft(draft_id, token, session.session_id)
            self.store.remember_draft(
                session.session_id, draft.draftId, draft.model_dump(mode="json")
            )
            drafts.append(draft)
        return sorted(drafts, key=lambda draft: (draft.createdAt, draft.draftId), reverse=True)

    async def _owned_draft(self, session: MerchantSessionContext, change_id: str) -> None:
        self._bound(session)
        if not self.store.owns_draft(session.session_id, change_id):
            raise CommerceError(404, "NOT_FOUND", "Price proposal not found in this session")

    async def get_change(self, session: MerchantSessionContext, change_id: str) -> StagedChange:
        await self._owned_draft(session, change_id)
        token = await self._token(session, "merchant:price:read")
        draft = await self.client.draft(change_id, token, session.session_id)
        self.store.remember_draft(session.session_id, change_id, draft.model_dump(mode="json"))
        return presentation.change(draft, session.operator)

    async def apply_by_operator(self, session: MerchantSessionContext, change_id: str) -> dict:
        await self._owned_draft(session, change_id)
        context = self._bound(session)
        draft = await self.client.apply(change_id, context.identity.token)
        self.store.remember_draft(session.session_id, change_id, draft.model_dump(mode="json"))
        return presentation.response(draft, session.operator, "APPLIED")

    async def discard_by_operator(self, session: MerchantSessionContext, change_id: str) -> dict:
        draft = await self._cancel(session, change_id)
        return presentation.response(draft, session.operator, "CANCELLED")

    async def _cancel(self, session: MerchantSessionContext, change_id: str) -> DraftView:
        await self._owned_draft(session, change_id)
        token = await self._token(session, "merchant:price:cancel")
        draft = await self.client.cancel(change_id, token, session.session_id)
        self.store.remember_draft(session.session_id, change_id, draft.model_dump(mode="json"))
        return draft

    async def _snapshot(
        self, session: MerchantSessionContext, window: Period, pending_count: int
    ) -> BusinessSnapshot:
        token = await self._token(session, "merchant:read")
        prior = window.previous()
        current = await self.client.summary(window.start, window.end, token, session.session_id)
        previous = await self.client.summary(prior.start, prior.end, token, session.session_id)
        empty = CurrencySummary(currency="CNY", orderCount=0, units=0, amountMinor=0)
        now = next((row for row in current.currencies if row.currency == "CNY"), empty)
        before = next((row for row in previous.currencies if row.currency == "CNY"), empty)
        return BusinessSnapshot(
            period=window.label,
            compare_to=prior.label,
            sales=now.amountMinor / 100,
            orders=now.orderCount,
            units=now.units,
            currency="CNY",
            average_order_value=now.amountMinor / (100 * now.orderCount)
            if now.orderCount
            else None,
            sales_change_pct=_change_pct(now.amountMinor, before.amountMinor),
            orders_change_pct=_change_pct(now.orderCount, before.orderCount),
            alerts=AlertCounts(
                low_stock=None, slow_movers=None, order_issues=None, pending_changes=pending_count
            ),
            note="CNY；按 UTC 付款成功时间及历史订单金额统计退款前成交，USD 单列查询；未接入流量、转化、成本和利润。",
        )

    async def get_business_snapshot(
        self, session: MerchantSessionContext, period: str | None = None
    ) -> BusinessSnapshot:
        drafts = await self._drafts(session)
        return await self._snapshot(
            session,
            reporting_period(session, period),
            sum(draft.state == "PREPARED" for draft in drafts),
        )

    async def query_metrics(
        self,
        session: MerchantSessionContext,
        metric: str,
        period: str | None = None,
        granularity: str = "day",
        segment: str | None = None,
    ) -> MetricSeries:
        await self._token(session, "merchant:read")
        metric = metric.strip().lower()
        if metric == "revenue":
            metric = "sales"
        if metric not in {"sales", "orders", "units"}:
            raise ChangeNotApplicable(
                "已接入 sales（退款前成交额）、orders（成交单数）、units（成交件数）。"
            )
        buckets = {
            "day": "DATE(succeeded_at)",
            "week": "DATE_SUB(DATE(succeeded_at), INTERVAL WEEKDAY(succeeded_at) DAY)",
            "month": "DATE_FORMAT(succeeded_at, '%Y-%m-01')",
        }
        if granularity not in buckets:
            raise ChangeNotApplicable("序列按 day、week 或 month 分组。")
        window = reporting_period(session, period)
        currency, product_filter = "CNY", ""
        if segment in {"CNY", "USD"}:
            currency = segment
        elif segment:
            token = await self._token(session, "merchant:read")
            product = await self.client.product(segment, token, session.session_id)
            if product is None:
                raise ChangeNotApplicable("segment 需为已读取的商品 ID，或 CNY／USD 币种。")
            currency = product.currency
            product_filter = f" AND product_id = {_literal(product.productId)}"
        column = {
            "sales": "SUM(total_price_minor)",
            "orders": "COUNT(*)",
            "units": "SUM(quantity)",
        }[metric]
        query = (
            f"SELECT {buckets[granularity]} AS bucket, {column} AS value "
            "FROM merchant_paid_orders "
            f"WHERE currency = {_literal(currency)} "
            f"AND succeeded_at >= {_literal(window.start.strftime('%Y-%m-%d %H:%M:%S.%f'))} "
            f"AND succeeded_at < {_literal(window.end.strftime('%Y-%m-%d %H:%M:%S.%f'))}"
            f"{product_filter} GROUP BY bucket ORDER BY bucket"
        )
        table = await self.sql.query(query)
        return MetricSeries(
            metric=metric,
            unit=currency if metric == "sales" else None,
            granularity=granularity,
            period=window.label,
            segment=segment,
            points=[
                MetricPoint(
                    date=str(row[0]), value=float(row[1]) / (100 if metric == "sales" else 1)
                )
                for row in table.rows
            ],
            note=table.note or "UTC；按付款成功时间统计，仅列有成交的时间桶；无成交时间桶未填充。",
        )

    async def search_listings(
        self,
        session: MerchantSessionContext,
        query: str,
        filters: ListingFilters | None = None,
        limit: int = 8,
    ):
        token = await self._token(session, "merchant:read")
        products = await self.client.products(token, session.session_id)
        rows = [presentation.listing(product) for product in products]
        if query.strip():
            needle = query.strip().casefold()
            rows = [
                row
                for row in rows
                if needle in row.title.casefold() or needle in row.listing_id.casefold()
            ]
        if filters:
            if filters.category or filters.content_quality or filters.sort == "sales_desc":
                raise ChangeNotApplicable(
                    "目录未接入分类、内容质量或销量排序；成交排名请使用经营分析。"
                )
            if filters.status:
                rows = [row for row in rows if row.status == filters.status]
            if filters.max_stock is not None:
                rows = [row for row in rows if row.stock <= filters.max_stock]
            keys = {
                "stock_asc": lambda row: row.stock,
                "price_asc": lambda row: row.price,
                "price_desc": lambda row: -row.price,
            }
            if filters.sort in keys:
                rows.sort(key=keys[filters.sort])
        return rows[: max(1, min(limit, 100))]

    async def get_listing(self, session: MerchantSessionContext, listing_id: str):
        token = await self._token(session, "merchant:read")
        product = await self.client.product(listing_id, token, session.session_id)
        return presentation.listing(product) if product else None

    async def get_pricing_context(self, session: MerchantSessionContext, listing_id: str):
        product = await self.get_listing(session, listing_id)
        if product is None:
            return None
        return PricingContext(
            listing_id=product.listing_id, current_price=product.price, currency=product.currency
        )

    async def stage_price_update(
        self, session: MerchantSessionContext, items: list[PriceUpdateItem], note: str | None = None
    ) -> StagedChange:
        context = self._bound(session)
        if context.turn_id is None:
            raise RuntimeError("Preparing a price draft requires a persisted user turn")
        if not 1 <= len(items) <= 3:
            raise ChangeNotApplicable("一次调价草案需包含 1 至 3 款商品。")
        prices = [(item.listing_id, presentation.price_minor(item.new_price)) for item in items]
        token = await self._token(session, "merchant:read")
        currency = None
        body_items = []
        seen = set()
        for product_id, minor in prices:
            product = await self.client.product(product_id, token, session.session_id)
            if product is None:
                raise ChangeNotApplicable("商品不存在，请重新读取目录并明确调价对象。")
            if product.productId in seen:
                raise ChangeNotApplicable("一个草案不能重复包含同一商品。")
            seen.add(product.productId)
            if currency is not None and currency != product.currency:
                raise ChangeNotApplicable("一个草案的商品必须使用同一币种。")
            currency = product.currency
            body_items.append({"productId": product.productId, "newPriceMinor": minor})
        body = {
            "currency": currency,
            "items": sorted(body_items, key=lambda item: item["productId"]),
        }
        intent = self.store.prepare_intent(session.session_id, context.turn_id, body)
        if intent.rejection is not None:
            raise ChangeNotApplicable(
                f"该次调价意图已被拒绝：{intent.rejection}；请修订方案后重试。"
            )
        if intent.draft_id is not None:
            return await self.get_change(session, intent.draft_id)
        token = await self._token(session, "merchant:price:prepare")
        try:
            draft = await self.client.prepare(intent.body, intent.key, token, session.session_id)
        except CommerceError as error:
            if self._prepare_rejected(error):
                self.store.reject_intent(intent.key, error.category)
                raise ChangeNotApplicable(
                    f"草案未创建：{error.category}。请检查商品是否可调价及目标金额。"
                ) from None
            raise
        self.store.attach_draft(intent.key, draft.draftId, draft.model_dump(mode="json"))
        return presentation.change(draft, session.operator)

    async def get_pending_changes(self, session: MerchantSessionContext) -> list[StagedChange]:
        return [
            presentation.change(draft, session.operator)
            for draft in await self._drafts(session)
            if draft.state == "PREPARED"
        ]

    async def discard_change(
        self,
        session: MerchantSessionContext,
        change_id: str,
        actor_kind: ActorKind = ActorKind.OPERATOR,
    ) -> StagedChange:
        draft = await self._cancel(session, change_id)
        if draft.state != "CANCELLED":
            # The upstream discard executor emits a success sentence for any returned change.
            raise ChangeNotApplicable(f"草案当前为 {draft.state}，没有取消或改变已执行的价格。")
        result = presentation.change(draft, session.operator)
        result.discarded_by_kind = actor_kind
        return result

    async def execute_analysis_query(self, session: MerchantSessionContext, sql: str):
        await self._token(session, "merchant:read")
        return await self.sql.query(sql)

    async def get_analysis_schema(self, session: MerchantSessionContext) -> str:
        self._bound(session)
        return SCHEMA

    async def get_merchant_context(self, session: MerchantSessionContext):
        self._bound(session)
        window = reporting_period(session, None)
        return {
            "merchant": "CityBuddy",
            "operator": session.operator,
            "default_currency": "CNY",
            "other_currency": "USD（单独查询，不换算或合计）",
            "default_period": window.label,
            "timezone": "UTC",
            "period_syntax": "last_14_days / previous_14_days / ISO开始时间/结束时间；左闭右开",
            "metrics": ["sales", "orders", "units"],
            "limitations": [
                "只提供退款前已支付成交、商品与价格草案；未接入流量、转化、成本、利润。",
                "目录接口一次最多返回100款；商品名称可能为英文，请使用实际返回的ID。",
                "仅普通商品可调价，历史或当前秒杀关联均排除；模型不能批准。",
            ],
        }

    async def overview(self, session: MerchantSessionContext) -> dict:
        drafts = await self._drafts(session)
        window = reporting_period(session, None)
        snapshot = await self._snapshot(session, window, sum(d.state == "PREPARED" for d in drafts))
        current = await self.query_metrics(session, "sales", window.label)
        prior = await self.query_metrics(session, "sales", window.previous().label)
        changes = [
            presentation.change(draft, session.operator).model_dump(mode="json") for draft in drafts
        ]
        return {
            "snapshot": snapshot.model_dump(mode="json"),
            "trends": {"sales": [point.model_dump() for point in current.points]},
            "trends_prior": {"sales": [point.model_dump() for point in prior.points]},
            "needs_attention": {"pending_changes": [c for c in changes if c["status"] == "staged"]},
            "recent_changes": changes[:10],
        }

    @staticmethod
    def _unsupported():
        raise ChangeNotApplicable("本工作台仅接入经营分析与价格草案，不支持此操作。")

    async def get_campaign_performance(self, session, campaign_id=None):
        self._unsupported()

    async def get_inventory_alerts(self, session):
        self._unsupported()

    async def get_order_issues(self, session):
        self._unsupported()

    async def stage_listing_update(self, session, listing_id, fields, note=None):
        self._unsupported()

    async def stage_inventory_action(self, session, items, note=None):
        self._unsupported()

    async def stage_promotion(self, session, promotion):
        self._unsupported()

    async def stage_campaign(self, session, campaign):
        self._unsupported()

    async def apply_change(self, session, change_id):
        raise ChangeNotApplicable("请由操作员点击草案卡片的批准按钮；聊天或模型工具不能执行批准。")
