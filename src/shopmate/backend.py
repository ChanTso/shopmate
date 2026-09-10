"""CityBuddy-backed retail tools and durable merchant proposals."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from commerce_common.config import ThinkingEffort
from merchant_agent.backend import MerchantBackend
from merchant_agent.changes import ChangeNotApplicable, check_guardrails
from merchant_agent.config import MerchantAgentConfig
from merchant_agent.types import (
    ActorKind,
    AlertCounts,
    BusinessSnapshot,
    CampaignDraft,
    ChangeItem,
    ChangeKind,
    InventoryActionItem,
    MerchantSessionContext,
    MetricPoint,
    MetricSeries,
    PriceUpdateItem,
    PromotionDraft,
)
from sqlglot import exp

from . import presentation
from .analysis_sql import SCHEMA, AnalysisSQL
from .auth import AuthClient, current_context
from .commerce_client import (
    PREPARE_REJECTIONS,
    CommerceClient,
    CommerceError,
    CurrencySummary,
)
from .sessions import SessionStore

SHANGHAI = ZoneInfo("Asia/Shanghai")


class ShopMateConfig(MerchantAgentConfig):
    brand_name: str = "ShopMate"
    assistant_name: str = "商家经营助手"
    brand_voice: str = "使用中文，先给经营结论，再列来自工具的金额、期间和依据"
    enable_analysis: bool = True
    analysis_sql_only: bool = True
    analysis_use_code_execution: bool = False
    enable_memory: bool = False
    enable_web_search: bool = False
    enable_listing_edits: bool = True
    enable_inventory: bool = True
    enable_campaigns: bool = True
    enable_pricing: bool = True
    max_tool_iterations: int = 12
    max_items_per_change: int = 25
    stage_shows_preview: bool = True
    close_on_presentation: bool = False
    require_host_approval: bool = True
    approval_surface: str = "商家工作台草案卡片的批准按钮"
    thinking_effort: ThinkingEffort | None = None

    def absent_tools(self) -> frozenset[str]:
        return super().absent_tools() | {"apply_change"}


@dataclass(frozen=True)
class Period:
    start: datetime
    end: datetime

    @property
    def label(self) -> str:
        return f"{self.start.isoformat()}/{self.end.isoformat()}"

    @property
    def local_label(self) -> str:
        return "/".join(value.astimezone(SHANGHAI).isoformat() for value in (self.start, self.end))

    def previous(self) -> Period:
        return Period(self.start - (self.end - self.start), self.start)


def reporting_period(
    session: MerchantSessionContext, period: str | None, report_as_of: datetime | None = None
) -> Period:
    reference = report_as_of or session.local_now() or datetime.now(SHANGHAI)
    if reference.tzinfo is None:
        raise ValueError("Merchant reporting clock must include a timezone")
    reference = reference.astimezone(SHANGHAI)
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
                "请使用 last_14_days、previous_14_days、yesterday、last_month，或明确的 ISO 开始/结束时间。"
            )
        try:
            dates = [datetime.fromisoformat(part) for part in parts]
            result = Period(
                *(item.replace(tzinfo=SHANGHAI) if item.tzinfo is None else item for item in dates)
            )
        except ValueError:
            raise ChangeNotApplicable("查询起止时间必须是有效的 ISO 日期或时间。") from None
    if not timedelta(0) < result.end - result.start <= timedelta(days=366):
        raise ChangeNotApplicable("查询起点必须早于终点，跨度不超过 366 天。")
    return Period(result.start.astimezone(UTC), result.end.astimezone(UTC))


def _literal(value: str) -> str:
    return exp.Literal.string(value).sql(dialect="mysql")


def _stamp(value: datetime) -> str:
    return _literal(value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S.%f"))


def _change_pct(current, previous):
    return (
        round((current - previous) / previous * 100, 2)
        if previous and current is not None
        else None
    )


def _whole_days(window: Period) -> int | None:
    start, end = window.start.astimezone(SHANGHAI), window.end.astimezone(SHANGHAI)
    if any((v.hour, v.minute, v.second, v.microsecond) != (0, 0, 0, 0) for v in (start, end)):
        return None
    return (end.date() - start.date()).days


def _bucket(column: str, granularity: str) -> str:
    return {
        "day": f"DATE({column})",
        "week": f"DATE_SUB(DATE({column}), INTERVAL WEEKDAY({column}) DAY)",
        "month": f"DATE_FORMAT({column}, '%Y-%m-01')",
    }[granularity]


class CityBuddyMerchantBackend(MerchantBackend):
    def __init__(
        self,
        auth: AuthClient,
        store: SessionStore,
        client: CommerceClient,
        sql: AnalysisSQL,
        report_as_of: datetime | None = None,
        *,
        web_search=None,
    ):
        if report_as_of is not None and report_as_of.tzinfo is None:
            raise ValueError("report_as_of must include a timezone")
        self.auth, self.store, self.client, self.sql = auth, store, client, sql
        self.report_as_of = report_as_of
        self.web_search = web_search

    @staticmethod
    def _bound(session):
        context = current_context()
        if context.session_id != session.session_id or context.identity.subject != session.operator:
            raise CommerceError(403, "CONTEXT_MISMATCH", "Merchant session context does not match")
        return context

    def _report_now(self, session):
        return self.report_as_of or session.local_now() or datetime.now(SHANGHAI)

    def _period(self, session, period=None):
        return reporting_period(session, period, self.report_as_of)

    def _covered(self, session, window):
        if self.report_as_of is None:
            return True
        coverage = self._period(session, "last_90_days")
        return coverage.start <= window.start and window.end <= coverage.end

    async def _token(self, session, scope):
        context = self._bound(session)
        return await self.auth.exchange(context.identity, session.session_id, scope)

    def _draft_bindings(self, session):
        self._bound(session)
        return sorted(set(self.store.merchant_bindings(session.operator)) | {session.session_id})

    async def _recover_prepares(self, session):
        context = self._bound(session)
        for binding in self._draft_bindings(session):
            missing = [
                intent
                for intent in self.store.intent_rows(binding)
                if intent.draft_id is None and intent.rejection is None
            ]
            if not missing:
                continue
            token = await self.auth.exchange(context.identity, binding, "merchant:change:prepare")
            for intent in missing:
                try:
                    draft = await self.client.prepare(intent.body, intent.key, token, binding)
                except CommerceError as error:
                    if self._prepare_rejected(error):
                        self.store.reject_intent(intent.key, error.category)
                        continue
                    raise
                self.store.attach_draft(intent.key, draft.changeId, draft.model_dump(mode="json"))

    @staticmethod
    def _prepare_rejected(error):
        return error.status_code in (400, 404, 409) and error.category in PREPARE_REJECTIONS

    async def _drafts(self, session, state=None, *, take=10001):
        await self._recover_prepares(session)
        context = self._bound(session)
        drafts = {}
        for binding in self._draft_bindings(session):
            token = await self.auth.exchange(context.identity, binding, "merchant:change:read")
            for offset in range(0, take, 100):
                limit = min(100, take - offset)
                page = await self.client.changes(
                    token, binding, limit=limit, offset=offset, state=state
                )
                for draft in page:
                    self.store.remember_draft(
                        binding, draft.changeId, draft.model_dump(mode="json")
                    )
                    drafts[draft.changeId] = draft
                if len(page) < limit:
                    break
        ordered = sorted(drafts.values(), key=lambda d: d.changeId)
        ordered.sort(key=lambda d: d.createdAt, reverse=True)
        if take == 10001 and len(ordered) >= take:
            raise ChangeNotApplicable("变更记录超过读取上限，请在工作台分页查询。")
        return ordered[:take]

    async def changes_page(self, session, limit=20, offset=0):
        rows = await self._drafts(session, take=offset + limit + 1)
        return {
            "items": [
                presentation.change(row, session.operator).model_dump(mode="json")
                for row in rows[offset : offset + limit]
            ],
            "nextOffset": offset + limit
            if len(rows) > offset + limit and offset + limit <= 10000
            else None,
        }

    async def _owned_draft(self, session, change_id):
        context = self._bound(session)
        binding = self.store.draft_binding(session.operator, change_id) or session.session_id
        token = await self.auth.exchange(context.identity, binding, "merchant:change:read")
        row = await self.client.draft(change_id, token, binding)
        self.store.remember_draft(binding, change_id, row.model_dump(mode="json"))
        return binding, row

    async def get_change(self, session, change_id):
        _, draft = await self._owned_draft(session, change_id)
        return presentation.change(draft, session.operator)

    async def apply_by_operator(self, session, change_id):
        binding, _ = await self._owned_draft(session, change_id)
        draft = await self.client.apply(change_id, self._bound(session).identity.token)
        self.store.remember_draft(binding, change_id, draft.model_dump(mode="json"))
        return presentation.response(draft, session.operator, "APPLIED")

    async def discard_by_operator(self, session, change_id):
        return presentation.response(
            await self._cancel(session, change_id), session.operator, "CANCELLED"
        )

    async def _cancel(self, session, change_id):
        binding, _ = await self._owned_draft(session, change_id)
        token = await self.auth.exchange(
            self._bound(session).identity, binding, "merchant:change:cancel"
        )
        draft = await self.client.cancel(change_id, token, binding)
        self.store.remember_draft(binding, change_id, draft.model_dump(mode="json"))
        return draft

    async def _traffic(self, window):
        days = _whole_days(window)
        if days is None:
            return None
        start, end = (v.astimezone(SHANGHAI).date().isoformat() for v in (window.start, window.end))
        table = await self.sql.query(
            "SELECT SUM(visits) AS visits, COUNT(*) AS observed_days FROM merchant_store_traffic_daily "
            f"WHERE local_date >= {_literal(start)} AND local_date < {_literal(end)}"
        )
        if table.truncated or not table.rows or int(table.rows[0][1]) != days:
            return None
        return int(table.rows[0][0])

    async def _snapshot(self, session, window, pending_count, inventory, issues):
        token = await self._token(session, "merchant:read")
        if not self._covered(session, window):
            raise ChangeNotApplicable(
                "该期间超出固定90日历史覆盖；请明确覆盖期内的报表窗口，不能把缺失当零。"
            )
        prior = window.previous()
        prior_covered = self._covered(session, prior)
        current = await self.client.summary(window.start, window.end, token, session.session_id)
        previous = await self.client.summary(prior.start, prior.end, token, session.session_id)
        empty = CurrencySummary(currency="CNY", orderCount=0, units=0, amountMinor=0)
        now = next((row for row in current.currencies if row.currency == "CNY"), empty)
        before = next((row for row in previous.currencies if row.currency == "CNY"), empty)
        traffic, prior_traffic = await self._traffic(window), await self._traffic(prior)
        conversion = now.orderCount * 100 / traffic if traffic else None
        prior_conversion = before.orderCount * 100 / prior_traffic if prior_traffic else None
        return BusinessSnapshot(
            period=window.local_label,
            compare_to=prior.local_label,
            sales=now.amountMinor / 100,
            orders=now.orderCount,
            units=now.units,
            currency="CNY",
            traffic=traffic,
            conversion_rate=conversion,
            average_order_value=now.amountMinor / (100 * now.orderCount)
            if now.orderCount
            else None,
            sales_change_pct=_change_pct(now.amountMinor, before.amountMinor)
            if prior_covered
            else None,
            orders_change_pct=_change_pct(now.orderCount, before.orderCount)
            if prior_covered
            else None,
            traffic_change_pct=_change_pct(traffic, prior_traffic),
            conversion_change_pct=_change_pct(conversion, prior_conversion),
            alerts=AlertCounts(
                low_stock=sum(row.kind == "low_stock" for row in inventory),
                slow_movers=sum(row.kind == "slow_mover" for row in inventory),
                order_issues=len(issues) if len(issues) < 100 else None,
                pending_changes=pending_count,
            ),
            note=(
                "Asia/Shanghai；期间起点含、终点不含。CNY退款前历史已支付金额。转化=付款子单数/店铺访问次数，非人数或checkout数；流量覆盖不完整则未知。"
                + ("前期超出历史覆盖，变化率未知。" if not prior_covered else "")
            ),
        )

    async def get_business_snapshot(self, session, period=None):
        drafts = await self._drafts(session, "PREPARED")
        inventory = await self.get_inventory_alerts(session)
        issues = await self.get_order_issues(session)
        return await self._snapshot(
            session, self._period(session, period), len(drafts), inventory, issues
        )

    async def query_metrics(self, session, metric, period=None, granularity="day", segment=None):
        token = await self._token(session, "merchant:read")
        metric = {
            "revenue": "sales",
            "conversion_rate": "conversion",
            "average_order_value": "aov",
        }.get(metric.strip().lower(), metric.strip().lower())
        if metric not in {"sales", "orders", "units", "traffic", "conversion", "aov"}:
            raise ChangeNotApplicable(
                "支持 sales/orders/units/traffic/conversion/aov；利润或因果影响需要额外事实。"
            )
        if granularity not in {"day", "week", "month"}:
            raise ChangeNotApplicable("序列按 day、week 或 month 分组。")
        window = self._period(session, period)
        if not self._covered(session, window):
            return MetricSeries(
                metric=metric,
                granularity=granularity,
                period=window.local_label,
                segment=segment,
                note="该期间超出固定90日历史覆盖，缺失不是零；请指定覆盖期内窗口。",
            )
        currency, restriction = "CNY", ""
        if segment in {"CNY", "USD"}:
            currency = segment
        elif segment == "kids-room":
            restriction = " AND product_id IN (SELECT product_id FROM merchant_listing_facts WHERE category = 'kids-room')"
        elif segment:
            row = await self.client.listing(
                segment, token, session.session_id, as_of=self._report_now(session)
            )
            if row is None:
                raise ChangeNotApplicable("segment 需为实际商品/家族 ID、kids-room 或 CNY／USD。")
            currency = row.currency
            ids = [variant.id for variant in row.variants] if row.kind == "family" else [row.id]
            restriction = " AND product_id IN (" + ",".join(_literal(value) for value in ids) + ")"
        paid_bucket = _bucket("DATE_ADD(succeeded_at, INTERVAL 8 HOUR)", granularity)
        where = (
            f"currency = {_literal(currency)} AND succeeded_at >= {_stamp(window.start)} "
            f"AND succeeded_at < {_stamp(window.end)}{restriction}"
        )
        traffic_metric = metric in {"traffic", "conversion"}
        if traffic_metric:
            if segment not in (None, "CNY"):
                return MetricSeries(
                    metric=metric,
                    granularity=granularity,
                    period=window.local_label,
                    segment=segment,
                    note="仅有全店访问观察，没有商品、分类或其他币种的独立流量分母。",
                )
            days = _whole_days(window)
            if days is None:
                return MetricSeries(
                    metric=metric,
                    granularity=granularity,
                    period=window.local_label,
                    note="流量为上海自然日观察，无法为不足完整自然日的窗口分摊访问量。",
                )
            if await self._traffic(window) is None:
                return MetricSeries(
                    metric=metric,
                    granularity=granularity,
                    period=window.local_label,
                    note="此窗口流量观察不完整，流量或转化未知；缺失不是零。",
                )
            start, end = (
                value.astimezone(SHANGHAI).date().isoformat()
                for value in (window.start, window.end)
            )
            traffic_sql = (
                f"SELECT {_bucket('local_date', granularity)} AS bucket, SUM(visits) AS visits "
                f"FROM merchant_store_traffic_daily WHERE local_date >= {_literal(start)} "
                f"AND local_date < {_literal(end)} GROUP BY bucket"
            )
            if metric == "traffic":
                query = f"SELECT bucket, visits AS value FROM ({traffic_sql}) t ORDER BY bucket"
            else:
                query = (
                    f"WITH traffic AS ({traffic_sql}), paid AS (SELECT {paid_bucket} AS bucket, COUNT(*) AS orders "
                    f"FROM merchant_paid_orders WHERE {where} GROUP BY bucket) "
                    "SELECT t.bucket, 100.0 * COALESCE(p.orders, 0) / NULLIF(t.visits, 0) AS value "
                    "FROM traffic t LEFT JOIN paid p ON p.bucket = t.bucket ORDER BY t.bucket"
                )
        else:
            column = {
                "sales": "SUM(total_price_minor)",
                "orders": "COUNT(*)",
                "units": "SUM(quantity)",
                "aov": "SUM(total_price_minor) / NULLIF(COUNT(*), 0)",
            }[metric]
            query = f"SELECT {paid_bucket} AS bucket, {column} AS value FROM merchant_paid_orders WHERE {where} GROUP BY bucket ORDER BY bucket"
        table = await self.sql.query(query)
        note = (
            "Asia/Shanghai；期间起点含、终点不含。转化=付款子单数/全店访问次数，零访问时未知。"
            if metric == "conversion"
            else "Asia/Shanghai；期间起点含、终点不含。访问量来自固定日期观察。"
            if metric == "traffic"
            else "Asia/Shanghai；期间起点含、终点不含。退款前历史付款金额；仅列有成交时间桶，未填补无记录日。"
        )
        return MetricSeries(
            metric=metric,
            unit=currency
            if metric in {"sales", "aov"}
            else "%"
            if metric == "conversion"
            else None,
            granularity=granularity,
            period=window.local_label,
            segment=segment,
            points=[
                MetricPoint(
                    date=str(row[0]),
                    value=float(row[1]) / (100 if metric in {"sales", "aov"} else 1),
                )
                for row in table.rows
                if row[1] is not None
            ],
            note=table.note or note,
        )

    async def listings_page(self, session, query="", filters=None, limit=20, offset=0):
        token = await self._token(session, "merchant:read")
        params = {
            "query": query,
            "limit": limit,
            "offset": offset,
            "asOf": self._report_now(session).isoformat(),
        }
        if filters:
            names = {"max_stock": "maxStock", "content_quality": "contentQuality"}
            params.update(
                {
                    names.get(key, key): value
                    for key, value in filters.model_dump(exclude_none=True).items()
                }
            )
            if filters.sort.startswith("price_"):
                params["currency"] = "CNY"
        page = await self.client.listings(token, session.session_id, **params)
        return {
            "items": [presentation.listing(row).model_dump(mode="json") for row in page.items],
            "nextOffset": page.nextOffset,
            "window": page.window.model_dump(mode="json"),
        }

    async def search_listings(self, session, query, filters=None, limit=8):
        page = await self.listings_page(session, query, filters, limit=min(limit, 50))
        return [presentation.RetailListingDetails.model_validate(row) for row in page["items"]]

    async def get_listing(self, session, listing_id):
        token = await self._token(session, "merchant:read")
        row = await self.client.listing(
            listing_id, token, session.session_id, as_of=self._report_now(session)
        )
        return presentation.listing(row) if row else None

    async def get_pricing_context(self, session, listing_id):
        token = await self._token(session, "merchant:read")
        row = await self.client.listing(
            listing_id, token, session.session_id, as_of=self._report_now(session)
        )
        return presentation.pricing(row) if row else None

    async def inventory_page(self, session, limit=20, offset=0):
        token = await self._token(session, "merchant:read")
        page = await self.client.inventory(
            token,
            session.session_id,
            limit=limit,
            offset=offset,
            asOf=self._report_now(session).isoformat(),
        )
        return {
            "items": [presentation.inventory(row).model_dump(mode="json") for row in page.items],
            "nextOffset": page.nextOffset,
            "window": page.window.model_dump(mode="json"),
        }

    async def get_inventory_alerts(self, session):
        rows, offset = [], 0
        while offset is not None:
            page = await self.inventory_page(session, limit=50, offset=offset)
            rows.extend(presentation.InventoryAlert.model_validate(row) for row in page["items"])
            following = page["nextOffset"]
            if following is not None and not offset < following <= 10000:
                raise CommerceError(502, "INVALID_RESPONSE", "Invalid inventory pagination")
            offset = following
        return rows

    async def order_issues_page(self, session, limit=100):
        token = await self._token(session, "merchant:read")
        rows = await self.client.issues(token, session.session_id, limit=limit)
        return {
            "items": [presentation.issue(row).model_dump(mode="json") for row in rows],
            "limit": limit,
            "truncated": len(rows) == limit,
        }

    async def get_order_issues(self, session):
        token = await self._token(session, "merchant:read")
        rows = await self.client.issues(token, session.session_id, limit=100)
        return [presentation.issue(row) for row in rows]

    async def _marketing_page(self, session, method, limit=20, offset=0):
        token = await self._token(session, "merchant:read")
        rows = await method(token, session.session_id, limit=limit, offset=offset)
        return {
            "items": [row.model_dump(mode="json") for row in rows],
            "nextOffset": offset + limit
            if len(rows) == limit and offset + limit <= 10000
            else None,
        }

    async def campaigns_page(self, session, limit=20, offset=0):
        return await self._marketing_page(session, self.client.campaigns, limit, offset)

    async def promotions_page(self, session, limit=20, offset=0):
        return await self._marketing_page(session, self.client.promotions, limit, offset)

    async def campaign_detail(self, session, campaign_id):
        token = await self._token(session, "merchant:read")
        row = await self.client.campaign(campaign_id, token, session.session_id)
        return row.model_dump(mode="json") if row else None

    async def promotion_detail(self, session, promotion_id):
        token = await self._token(session, "merchant:read")
        row = await self.client.promotion(promotion_id, token, session.session_id)
        return row.model_dump(mode="json") if row else None

    async def get_campaign_performance(self, session, campaign_id=None):
        token = await self._token(session, "merchant:read")
        if campaign_id:
            row = await self.client.campaign(campaign_id, token, session.session_id)
            return [presentation.campaign(row)] if row else []
        rows = []
        for offset in range(0, 10001, 50):
            page = await self.client.campaigns(token, session.session_id, limit=50, offset=offset)
            rows.extend(presentation.campaign(row) for row in page)
            if len(page) < 50:
                return rows
        raise ChangeNotApplicable("营销计划超过工具读取上限，请用工作台分页。")

    async def _stage(self, session, kind, payload):
        context = self._bound(session)
        if context.turn_id is None:
            raise RuntimeError("Preparing a change requires a persisted user turn")
        intent = self.store.prepare_intent(
            session.session_id, context.turn_id, {"kind": kind, "payload": payload}
        )
        if intent.rejection is not None:
            raise ChangeNotApplicable(
                f"该次变更意图已被拒绝：{intent.rejection}；请修订方案后重试。"
            )
        if intent.draft_id is not None:
            return await self.get_change(session, intent.draft_id)
        token = await self._token(session, "merchant:change:prepare")
        try:
            draft = await self.client.prepare(intent.body, intent.key, token, session.session_id)
        except CommerceError as error:
            if self._prepare_rejected(error):
                self.store.reject_intent(intent.key, error.category)
                raise ChangeNotApplicable(
                    f"草案未创建：{error.category}。请重新核对业务对象与参数。"
                ) from None
            raise
        self.store.attach_draft(intent.key, draft.changeId, draft.model_dump(mode="json"))
        return presentation.change(draft, session.operator)

    async def stage_price_update(self, session, items: list[PriceUpdateItem], note=None):
        self._bound(session)
        if not 1 <= len(items) <= 25:
            raise ChangeNotApplicable("一次调价草案需包含 1 至 25 款实际 SKU。")
        token = await self._token(session, "merchant:read")
        currency, body_items, seen, differences = None, [], set(), []
        for item in items:
            row = await self.client.listing(
                item.listing_id, token, session.session_id, as_of=self._report_now(session)
            )
            if row is None or row.kind == "family":
                raise ChangeNotApplicable("请读取并指定实际可调价 SKU，不能直接给商品家族改价。")
            if row.id in seen:
                raise ChangeNotApplicable("一个草案不能重复包含同一商品。")
            seen.add(row.id)
            if currency is not None and currency != row.currency:
                raise ChangeNotApplicable("一个草案的商品必须使用同一币种。")
            currency = row.currency
            minor = presentation.price_minor(item.new_price)
            body_items.append({"productId": row.id, "newPriceMinor": minor})
            differences.append(
                ChangeItem(target=row.id, field="price", before=row.priceMinor, after=minor)
            )
        # Movement limits are scale-invariant; minor units avoid major-unit subtraction drift.
        violations = check_guardrails(ChangeKind.PRICE_UPDATE, differences, ShopMateConfig())
        if violations:
            raise ChangeNotApplicable("; ".join(violations))
        return await self._stage(
            session,
            "PRICE_UPDATE",
            {"currency": currency, "items": sorted(body_items, key=lambda item: item["productId"])},
        )

    async def stage_listing_update(self, session, listing_id, fields, note=None):
        return await self._stage(
            session, "LISTING_UPDATE", {"listingId": listing_id, "fields": fields}
        )

    async def stage_inventory_action(self, session, items: list[InventoryActionItem], note=None):
        payload = []
        for item in items:
            row = {"listingId": item.listing_id, "action": item.action}
            if item.action == "restock":
                if item.quantity is None or not 1 <= item.quantity <= 500:
                    raise ChangeNotApplicable("补货为 1 至 500 件的增量。")
                row["quantity"] = item.quantity
            elif item.quantity is not None:
                raise ChangeNotApplicable("暂停或恢复销售不接受补货数量。")
            payload.append(row)
        return await self._stage(session, "INVENTORY_ACTION", {"items": payload})

    async def stage_promotion(self, session, promotion: PromotionDraft):
        if promotion.nights:
            raise ChangeNotApplicable("本零售店不支持按星期夜间限定的促销。")
        if not 0 < promotion.discount_pct <= 50:
            raise ChangeNotApplicable("促销折扣需大于零且不超过50%；加价请用普通调价工具。")
        return await self._stage(
            session,
            "PROMOTION",
            {
                "name": promotion.name,
                "listingIds": promotion.listing_ids,
                "discountPct": promotion.discount_pct,
                "starts": promotion.starts,
                "ends": promotion.ends,
            },
        )

    async def stage_campaign(self, session, campaign: CampaignDraft):
        values = campaign.model_dump(exclude_unset=True)
        names = {"campaign_id": "campaignId", "copy_text": "copyText", "budget": "budgetMinor"}
        payload = {
            names.get(key, key): presentation.price_minor(value, allow_zero=True)
            if key == "budget" and value is not None
            else value
            for key, value in values.items()
        }
        return await self._stage(session, "CAMPAIGN", payload)

    async def get_pending_changes(self, session):
        return [
            presentation.change(row, session.operator)
            for row in await self._drafts(session, "PREPARED")
        ]

    async def discard_change(self, session, change_id, actor_kind=ActorKind.OPERATOR):
        draft = await self._cancel(session, change_id)
        if draft.state != "CANCELLED":
            raise ChangeNotApplicable(f"草案当前为 {draft.state}，没有取消或改变已执行的业务。")
        result = presentation.change(draft, session.operator)
        result.discarded_by_kind = actor_kind
        return result

    async def execute_analysis_query(self, session, sql):
        await self._token(session, "merchant:read")
        return await self.sql.query(sql)

    def _reporting_context(self, session):
        reference = self._report_now(session)
        labels = ("last_7_days", "last_14_days", "last_28_days", "last_30_days", "previous_14_days")
        windows = {label: reporting_period(session, label, reference) for label in labels}
        coverage = reporting_period(session, "last_90_days", reference)
        return {
            "report_as_of": reference.isoformat(),
            "timezone": "Asia/Shanghai",
            "default_period": windows["last_14_days"].local_label,
            "periods_utc": {
                label: window.label.replace("+00:00", "Z") for label, window in windows.items()
            },
            "fixture_coverage": {
                "start": coverage.start.isoformat(),
                "end": coverage.end.isoformat(),
            }
            if self.report_as_of
            else None,
        }

    async def _catalog_counts(self, session):
        table = await self.execute_analysis_query(
            session,
            "SELECT currency, COUNT(*) AS sku_count, "
            "COUNT(DISTINCT listing_id) AS catalog_root_count, "
            "SUM(publication_state='PUBLISHED' AND available=1 "
            "AND stock_quantity>0) AS sellable_sku_count "
            "FROM merchant_listing_facts GROUP BY currency ORDER BY currency",
        )
        return table.model_dump(mode="json")

    async def get_analysis_schema(self, session):
        self._bound(session)
        context = self._reporting_context(session) | {
            "current_catalog_counts": await self._catalog_counts(session)
        }
        return json.dumps(context, ensure_ascii=False) + "\n\n" + SCHEMA

    async def get_merchant_context(self, session):
        self._bound(session)
        return {
            "merchant": "CityBuddy",
            "operator": session.operator,
            "default_currency": "CNY",
            **self._reporting_context(session),
            "current_catalog_counts": await self._catalog_counts(session),
            "operation_time": (session.local_now() or datetime.now(SHANGHAI))
            .astimezone(SHANGHAI)
            .isoformat(),
            "period_syntax": (
                "相对报表期间按report_as_of，裸日期是上海午夜；offset时间保留瞬间、左闭右开。"
                "促销今天/明天按operation_time。展示时将两端转换到声明时区；标结束不含就保留真实排除端点，"
                "写最后已包含自然日则不得称该日不含。不可只改时区标签而保留原日期/时刻。"
            ),
            "metrics": ["sales", "orders", "units", "traffic", "conversion", "aov"],
            "limitations": [
                "退款前成交按历史付款；退款申请比例不是实物退货率。零基期变化率、未知成本或缺失流量不填零。",
                "转化=付款子单数/全店访问次数；分类只有kids-room销售，无分类流量。campaign归因观察不与全店成交相加。",
                "调价须实际SKU；family可展开暂停/恢复/促销，每批最多25项。工具普通调价幅度上限20%，Java不额外执行这个工具上限。",
                "促销批准时实际改价，结束不自动恢复；营销计划保存不代表外部广告投放。模型不能批准。",
            ],
        }

    async def get_recent_orders(self, session, limit=6):
        token = await self._token(session, "merchant:read")
        return await self.client.recent_orders(token, session.session_id, limit=limit)

    async def overview(self, session):
        drafts = await self._drafts(session)
        window = self._period(session)
        prior_window = window.previous()
        inventory = await self.get_inventory_alerts(session)
        issues = await self.get_order_issues(session)
        snapshot = await self._snapshot(
            session, window, sum(row.state == "PREPARED" for row in drafts), inventory, issues
        )
        current, prior = {}, {}
        for name, metric in (
            ("sales", "sales"),
            ("orders", "orders"),
            ("conversion", "conversion"),
            ("average_order_value", "aov"),
        ):
            current[name] = await self.query_metrics(session, metric, window.label)
            prior[name] = await self.query_metrics(session, metric, prior_window.label)
        changes = [
            presentation.change(row, session.operator).model_dump(mode="json") for row in drafts
        ]
        orders = await self.get_recent_orders(session)
        return {
            "snapshot": snapshot.model_dump(mode="json"),
            "window": {
                "start": window.start.isoformat(),
                "end": window.end.isoformat(),
                "timeZone": "Asia/Shanghai",
            },
            "prior_window": {
                "start": prior_window.start.isoformat(),
                "end": prior_window.end.isoformat(),
                "timeZone": "Asia/Shanghai",
            },
            "trends": {
                name: [point.model_dump() for point in series.points]
                for name, series in current.items()
            },
            "trends_prior": {
                name: [point.model_dump() for point in series.points]
                for name, series in prior.items()
            },
            "trend_notes": {name: series.note for name, series in current.items()},
            "trend_notes_prior": {name: series.note for name, series in prior.items()},
            "recent_orders": [row.model_dump(mode="json") for row in orders],
            "needs_attention": {
                "pending_changes": [row for row in changes if row["status"] == "staged"],
                "low_stock": [
                    row.model_dump(mode="json") for row in inventory if row.kind == "low_stock"
                ],
                "slow_movers": [
                    row.model_dump(mode="json") for row in inventory if row.kind == "slow_mover"
                ],
                "order_issues": [row.model_dump(mode="json") for row in issues],
                "order_issues_limit": 100,
                "order_issues_may_have_more": len(issues) == 100,
            },
            "recent_changes": changes[:10],
        }

    async def apply_change(self, session, change_id):
        raise ChangeNotApplicable("请由操作员点击草案卡片的批准按钮；聊天或模型工具不能执行批准。")
