"""Deterministic retail data for the isolated local shop, not measured results."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "vendor/commerce-agents/examples/retail/data"
VERSION = "shopmate-retail-v1"
TIME_ZONE = ZoneInfo("Asia/Shanghai")
OPERATOR = "shopmate-fixture-operator"
BUYERS = ("shopmate-retail-buyer", "shopmate-retail-buyer-2")
HISTORY_OWNER = "shopmate-retail-history"
REPORT_DAYS = 90
ZERO_SALES_SKU = "AR-1806"
LEGACY_PRODUCTS = tuple(
    "shopmate-fixture-" + key
    for key in ("coffee", "tea", "mug", "tote", "cocoa-usd", "unavailable", "seckill")
)


def load(name: str) -> dict:
    return json.loads((DATA / f"{name}.json").read_text())


def identity(label: str) -> str:
    return str(uuid5(NAMESPACE_URL, "shopmate/retail-v1/" + label))


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def minor(value: float | str) -> int:
    return int((Decimal(str(value)) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def midnight(value: date) -> datetime:
    return datetime.combine(value, time(), TIME_ZONE).astimezone(UTC)


def encoded(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return str(int(value))
    if isinstance(value, int):
        return str(value)
    if isinstance(value, datetime):
        value = value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return "CONVERT(X'" + str(value).encode().hex() + "' USING utf8mb4)"


def insert(table: str, **values) -> str:
    return f"INSERT INTO {table} ({','.join(values)}) VALUES ({','.join(map(encoded, values.values()))});"


def members(values) -> str:
    return ",".join(encoded(value) for value in sorted(set(values)))


def legacy_owners() -> tuple[str, ...]:
    keys = [f"day-{day:02d}-{name}" for day in range(42) for name in ("coffee", "tea", "cocoa-usd")]
    keys += [f"day-{day:02d}-mug" for day in range(42) if day % 7 >= 5]
    keys += ["unpaid", "pending", "failed"]
    return tuple("shopmate-fixture-buyer-" + key for key in keys)


def fixture_owners() -> tuple[str, ...]:
    return (OPERATOR, *BUYERS, HISTORY_OWNER, *legacy_owners())


def catalog() -> tuple[list[dict], list[dict]]:
    families, skus = [], []
    inventory = load("merchant_inventory")
    operating = {row["product_id"]: row for row in inventory["inventory"]}
    assets = ROOT / "vendor/commerce-agents/examples/retail/storefront-web/public/products"
    for position, root in enumerate(load("catalog")["products"]):
        root_id = root["product_id"]
        content = {
            "brand": root.get("brand"),
            "category": root.get("category"),
            "labels": root.get("labels", []),
            "attributes": root.get("attributes", {}),
            "rating": root.get("rating"),
            "reviewCount": root.get("review_count"),
            "longDescription": root.get("long_description"),
            "specs": root.get("specs", {}),
            "reviewHighlights": root.get("review_highlights", []),
            "imageUrl": f"/products/{root_id}.webp"
            if (assets / f"{root_id}.webp").exists()
            else None,
        }
        content = {key: value for key, value in content.items() if value is not None}
        variants = root.get("variants", [])
        if variants:
            options: dict[str, list[str]] = {}
            for variant in variants:
                for key, value in variant["option_values"].items():
                    if value not in options.setdefault(key, []):
                        options[key].append(value)
            families.append(
                {
                    "id": root_id,
                    "name": root["title"],
                    "description": root.get("short_description", ""),
                    "content": content,
                    "options": [{"name": key, "values": value} for key, value in options.items()],
                    "position": position,
                }
            )
        for variant_position, compact in enumerate(variants or [root]):
            source = root | compact
            sku = source["product_id"]
            operations = operating.get(sku, {})
            stock = operations.get("stock", inventory["default_stock"])
            status = operations.get("status", "active" if stock else "out_of_stock")
            skus.append(
                {
                    "id": sku,
                    "name": source["title"],
                    "description": source.get("short_description", ""),
                    "price": minor(source["price"]),
                    "stock": stock,
                    "available": status not in {"paused", "draft"},
                    "publication": "DRAFT" if status == "draft" else "PUBLISHED",
                    "family": root_id if variants else None,
                    "content": {} if variants else content,
                    "option_values": compact.get("option_values", {}),
                    "position": variant_position if variants else position,
                    "cost": minor(operations["unit_cost"]) if "unit_cost" in operations else None,
                    "threshold": operations.get("threshold", inventory["default_threshold"]),
                    "quality": operations.get("content_quality"),
                    "missing": operations.get("missing_attributes", []),
                }
            )
    return families, skus


@dataclass(frozen=True)
class Order:
    key: str
    owner: str
    sku: dict
    quantity: int
    unit_price: int
    version: int
    placed_at: datetime
    payment_state: str | None = "SUCCEEDED"

    @property
    def order_id(self) -> str:
        return identity("order/" + self.key)

    @property
    def amount(self) -> int:
        return self.unit_price * self.quantity


def historical_orders(as_of: date, skus: list[dict]) -> list[Order]:
    result = []
    for index in range(REPORT_DAYS):
        start = midnight(as_of - timedelta(days=REPORT_DAYS - index))
        for sku in skus:
            if sku["id"] == ZERO_SALES_SKU:
                continue
            selector = int(digest(f"{index}/{sku['id']}")[:8], 16)
            # Paused and slow stock have sparse paid history; current stock is not re-debited.
            divisor = 31 if sku["id"] in {"AR-1207", "AR-1903"} else 8
            if selector % divisor and sku["id"] not in {"AR-1001", "AR-1004"}:
                continue
            recent = index >= REPORT_DAYS - 14
            quantity = (
                (4 if recent else 2)
                if sku["id"] == "AR-1001"
                else ((1 if recent else 3) if sku["id"] == "AR-1004" else 1 + selector % 3)
            )
            version = 1 if index < 45 else 2 if index < REPORT_DAYS - 14 else 3
            price = int(
                (
                    Decimal(sku["price"])
                    * {1: Decimal("0.9"), 2: Decimal("0.95"), 3: Decimal(1)}[version]
                ).quantize(Decimal(1), rounding=ROUND_HALF_UP)
            )
            result.append(
                Order(
                    f"day-{index:02d}/{sku['id']}",
                    HISTORY_OWNER,
                    sku,
                    quantity,
                    price,
                    version,
                    start + timedelta(hours=10 + selector % 10, minutes=selector % 50),
                )
            )
    for key, state, sku in zip(
        ("unpaid", "pending", "failed"), (None, "PENDING", "FAILED"), skus[:3]
    ):
        result.append(
            Order(
                key, BUYERS[0], sku, 1, sku["price"], 3, midnight(as_of) - timedelta(hours=4), state
            )
        )
    return result


def order_rows(order: Order) -> list[str]:
    sku, oid, paid = order.sku, order.order_id, order.payment_state == "SUCCEEDED"
    event = identity("order-event/" + order.key)
    rows = [
        insert(
            "standard_order",
            order_id=oid,
            user_subject=order.owner,
            product_id=sku["id"],
            product_name=sku["name"],
            unit_price_minor=order.unit_price,
            currency="CNY",
            quantity=order.quantity,
            total_price_minor=order.amount,
            product_version=order.version,
            status="PAID" if paid else "UNPAID",
            state_version=2 if paid else 1,
            created_at=order.placed_at,
        ),
        insert(
            "order_idempotency",
            user_subject=order.owner,
            idempotency_key="retail-order/" + order.key,
            intent_hash=digest(f"{len(sku['id'])}:{sku['id']}:{order.quantity}:{order.version}"),
            order_id=oid,
            created_at=order.placed_at,
        ),
        insert(
            "commerce_outbox",
            event_id=event,
            aggregate_type="STANDARD_ORDER",
            aggregate_id=oid,
            aggregate_version=1,
            event_type="STANDARD_ORDER_CREATED",
            created_at=order.placed_at,
            payload={
                "eventId": event,
                "orderId": oid,
                "productId": sku["id"],
                "quantity": order.quantity,
                "unitPriceMinor": order.unit_price,
                "currency": "CNY",
                "productVersion": order.version,
            },
        ),
    ]
    if order.payment_state is None:
        return rows
    attempt, correlation = identity("attempt/" + order.key), identity("correlation/" + order.key)
    key, paid_at = "retail-payment/" + order.key, order.placed_at + timedelta(minutes=2)
    rows.append(
        insert(
            "mock_payment_attempt",
            attempt_id=attempt,
            callback_correlation_id=correlation,
            user_subject=order.owner,
            order_id=oid,
            order_kind="STANDARD",
            request_idempotency_key=key,
            intent_hash=digest(f"{oid}\n{key}\n{order.amount}\nCNY\n"),
            amount_minor=order.amount,
            currency="CNY",
            state=order.payment_state,
            state_version=1 if order.payment_state == "PENDING" else 2,
            succeeded_at=paid_at if paid else None,
            created_at=order.placed_at,
        )
    )
    if not paid:
        return rows
    callback, callback_key = identity("callback/" + order.key), "retail-callback/" + order.key
    callback_hash = digest(
        "\n".join(
            (
                callback,
                correlation,
                oid,
                str(order.amount),
                "CNY",
                "SUCCEEDED",
                "",
                "",
                "",
                "",
                callback_key,
            )
        )
    )
    rows.extend(
        (
            insert(
                "mock_payment_callback",
                callback_event_id=callback,
                callback_idempotency_key=callback_key,
                attempt_id=attempt,
                callback_correlation_id=correlation,
                intent_hash=callback_hash,
                requested_outcome="SUCCEEDED",
                result_state="APPLIED",
                created_at=paid_at,
            ),
            insert(
                "inventory_ledger",
                movement_id=identity("payment-ledger/" + order.key),
                business_event_key="mock-payment:" + attempt,
                movement_type="STANDARD_PAYMENT",
                order_id=oid,
                product_id=sku["id"],
                inventory_delta=0,
                activity_quota_delta=0,
                payment_amount_minor=order.amount,
                payment_currency="CNY",
                created_at=paid_at,
            ),
        )
    )
    return rows


def cleanup_rows(skus: list[dict], families: list[dict]) -> list[str]:
    owners = members(fixture_owners())
    products = members([row["id"] for row in skus] + list(LEGACY_PRODUCTS))

    def owned(alias=""):
        return f"CAST({alias}user_subject AS BINARY) IN ({owners})"

    def draft(alias=""):
        return f"CAST({alias}operator_subject AS BINARY)={encoded(OPERATOR)}"

    return [
        (
            "DELETE i FROM retail_promotion_item i JOIN retail_promotion p USING(promotion_id) "
            f"JOIN merchant_price_draft d ON d.draft_id=p.source_change_id WHERE {draft('d.')};"
        ),
        f"DELETE p FROM retail_promotion p JOIN merchant_price_draft d ON d.draft_id=p.source_change_id WHERE {draft('d.')};",
        (
            f"DELETE c FROM retail_campaign c LEFT JOIN merchant_price_draft d ON d.draft_id=c.source_change_id "
            f"WHERE {draft('d.')} OR c.fixture_version={encoded(VERSION)};"
        ),
        f"DELETE FROM merchant_price_draft WHERE {draft()};",
        f"DELETE i FROM retail_order_issue i JOIN standard_order o USING(order_id) WHERE {owned('o.')};",
        f"DELETE f FROM retail_order_fulfillment f JOIN standard_order o USING(order_id) WHERE {owned('o.')};",
        f"DELETE l FROM shopping_checkout_order l JOIN shopping_checkout c USING(checkout_id) WHERE {owned('c.')};",
        f"DELETE FROM shopping_checkout WHERE {owned()};",
        f"DELETE r FROM action_receipt r JOIN pending_action p USING(pending_action_id) WHERE {owned('p.')};",
        f"DELETE FROM pending_action WHERE {owned()};",
        (
            f"DELETE e FROM commerce_outbox e JOIN mock_refund r ON e.aggregate_id=r.refund_id "
            f"WHERE e.aggregate_type='REFUND' AND {owned('r.')};"
        ),
        f"DELETE FROM mock_refund WHERE {owned()};",
        f"DELETE c FROM mock_payment_callback c JOIN mock_payment_attempt a USING(attempt_id) WHERE {owned('a.')};",
        f"DELETE l FROM inventory_ledger l JOIN standard_order o USING(order_id) WHERE {owned('o.')};",
        (
            f"DELETE e FROM commerce_outbox e JOIN standard_order o ON e.aggregate_id=o.order_id "
            f"WHERE e.aggregate_type='STANDARD_ORDER' AND {owned('o.')};"
        ),
        f"DELETE FROM mock_payment_attempt WHERE {owned()};",
        f"DELETE FROM order_idempotency WHERE {owned()};",
        f"DELETE FROM standard_order WHERE {owned()};",
        f"DELETE FROM shopping_cart_item WHERE {owned()};",
        f"DELETE FROM shopping_cart_command WHERE {owned()};",
        f"DELETE FROM shopping_cart WHERE {owned()};",
        f"DELETE FROM retail_product_operations WHERE product_id IN ({products});",
        f"DELETE FROM retail_product_metadata WHERE product_id IN ({products});",
        "DELETE FROM seckill_activity WHERE activity_id='shopmate-fixture-closed-activity';",
        f"DELETE FROM commerce_outbox WHERE aggregate_type='PRODUCT' AND aggregate_id IN ({products});",
        f"DELETE FROM product WHERE product_id IN ({products});",
        f"DELETE FROM retail_product_family WHERE family_id IN ({members(row['id'] for row in families)});",
        f"DELETE FROM crm_profile WHERE {owned()};",
        f"DELETE FROM retail_store_traffic_daily WHERE fixture_version={encoded(VERSION)};",
    ]


def preflight_queries() -> dict[str, str]:
    families, skus = catalog()
    products = members([row["id"] for row in skus] + list(LEGACY_PRODUCTS))
    owners = members(fixture_owners())
    targets = members([row["id"] for row in skus + families] + list(LEGACY_PRODUCTS))
    return {
        "non-fixture product changes": "SELECT COUNT(*) FROM merchant_price_draft d "
        "JOIN JSON_TABLE(d.items, '$[*]' COLUMNS(product_id VARCHAR(128) PATH '$.productId', "
        "target_id VARCHAR(128) PATH '$.target')) AS item "
        f"WHERE CAST(d.operator_subject AS BINARY)<>{encoded(OPERATOR)} "
        f"AND COALESCE(item.product_id,item.target_id) IN ({targets});",
        "non-fixture order references": f"SELECT COUNT(*) FROM standard_order WHERE product_id IN ({products}) AND CAST(user_subject AS BINARY) NOT IN ({owners});",
        "non-fixture cart references": f"SELECT COUNT(*) FROM shopping_cart_item WHERE product_id IN ({products}) AND CAST(user_subject AS BINARY) NOT IN ({owners});",
        "non-fixture promotion references": "SELECT COUNT(*) FROM retail_promotion_item i JOIN retail_promotion p USING(promotion_id) "
        f"JOIN merchant_price_draft d ON d.draft_id=p.source_change_id WHERE i.product_id IN ({products}) AND CAST(d.operator_subject AS BINARY)<>{encoded(OPERATOR)};",
        "non-fixture campaign updates": "SELECT COUNT(*) FROM retail_campaign c "
        "JOIN merchant_price_draft d ON d.draft_id=c.source_change_id "
        f"WHERE c.fixture_version={encoded(VERSION)} AND CAST(d.operator_subject AS BINARY)<>{encoded(OPERATOR)};",
    }


def customer_orders(as_of: date, sku_map: dict[str, dict]) -> tuple[list[Order], list[str]]:
    source = load("orders")
    shift = timedelta(days=(as_of - date.fromisoformat(source["dates_anchored_to"])).days)
    orders, facts = [], []
    observed = midnight(as_of)
    for record in source["orders"]:
        owner = BUYERS[0] if record["user_id"] == "demo-user" else BUYERS[1]
        placed = datetime.fromisoformat(record["placed_at"]) + shift
        for index, item in enumerate(record["items"]):
            sku = sku_map[item["product_id"]]
            order = Order(
                f"customer/{record['order_id']}/{index}",
                owner,
                sku,
                item["quantity"],
                minor(item["price"]),
                2,
                placed,
            )
            orders.append(order)
            stage = {
                "processing": "PROCESSING",
                "shipped": "SHIPPED",
                "delayed": "SHIPPED",
                "delivered": "DELIVERED",
            }[record["status"]]
            if record["order_id"] == "AR-79102":
                stage = "PROCESSING"
            # The recent source shipment has no event timestamp; use an explicit six-hour fixture transit handoff.
            shipped = placed + timedelta(hours=6) if stage in {"SHIPPED", "DELIVERED"} else None
            delivered = placed + timedelta(days=4) if stage == "DELIVERED" else None
            estimate = (placed + timedelta(days=5)) if delivered else (observed + timedelta(days=2))
            facts.append(
                insert(
                    "retail_order_fulfillment",
                    order_id=order.order_id,
                    method="FREIGHT" if sku["id"] == "AR-1901" else "STANDARD",
                    stage=stage,
                    promised_delivery_at=placed + timedelta(days=5),
                    estimated_delivery_at=estimate,
                    packed_at=shipped,
                    shipped_at=shipped,
                    delivered_at=delivered,
                    delay_reason=(
                        "仓内备货延误，尚未发运" if stage == "PROCESSING" else "承运商运输延误"
                    )
                    if record["status"] == "delayed"
                    else None,
                    source_kind="FIXTURE",
                    source_ref=VERSION + "/" + record["order_id"],
                    observed_at=observed,
                )
            )
    return orders, facts


def issue_orders(as_of: date, sku_map: dict[str, dict]) -> tuple[list[Order], list[str]]:
    source = load("merchant_messages")
    shift = timedelta(days=(as_of - date.fromisoformat(source["dates_anchored_to"])).days)
    end = midnight(as_of)
    orders, facts = [], []
    for item in source["issues"]:
        opened = datetime.fromisoformat(item["opened_at"]) + shift
        sku = sku_map[item["listing_id"]]
        count = 6 if item["kind"] == "return_spike" else 1
        for index in range(count):
            order = Order(
                f"issue/{item['issue_id']}/{index}",
                BUYERS[index % 2],
                sku,
                1,
                sku["price"],
                3,
                opened - timedelta(days=3, minutes=index),
            )
            orders.append(order)
            if index == 0:
                facts.append(
                    insert(
                        "retail_order_issue",
                        issue_id=item["issue_id"],
                        order_id=order.order_id,
                        kind=item["kind"],
                        summary=("本周六笔订单申请退款，均提及枕头硬度")
                        if count == 6
                        else item["summary"],
                        buyer_message_excerpt=item.get("buyer_message_excerpt"),
                        opened_at=opened,
                        window_start=end - timedelta(days=7) if count == 6 else None,
                        window_end=end if count == 6 else None,
                        source_kind="FIXTURE",
                        source_ref=VERSION + "/" + item["order_id"],
                    )
                )
            if item["kind"] == "delayed":
                facts.append(
                    insert(
                        "retail_order_fulfillment",
                        order_id=order.order_id,
                        method="FREIGHT",
                        stage="SHIPPED",
                        promised_delivery_at=opened - timedelta(days=1),
                        estimated_delivery_at=end + timedelta(days=2),
                        packed_at=order.placed_at + timedelta(hours=3),
                        shipped_at=order.placed_at + timedelta(hours=4),
                        delay_reason="承运商区域仓等待转运",
                        source_kind="FIXTURE",
                        source_ref=VERSION + "/" + item["order_id"],
                        observed_at=end,
                    )
                )
            if count == 6:
                refund, attempt = identity("refund/" + order.key), identity("attempt/" + order.key)
                event = identity("refund-event/" + order.key)
                facts.extend(
                    (
                        insert(
                            "mock_refund",
                            refund_id=refund,
                            user_subject=order.owner,
                            order_id=order.order_id,
                            order_kind="STANDARD",
                            payment_attempt_id=attempt,
                            request_idempotency_key="retail-refund/" + order.key,
                            intent_hash=digest(f"{order.order_id}\n{order.amount}\nCNY"),
                            eligible_amount_minor=order.amount,
                            requested_amount_minor=order.amount,
                            refunded_amount_minor=0,
                            currency="CNY",
                            state="REQUESTED",
                            state_version=1,
                            created_at=opened,
                            updated_at=opened,
                        ),
                        insert(
                            "commerce_outbox",
                            event_id=event,
                            aggregate_type="REFUND",
                            aggregate_id=refund,
                            aggregate_version=1,
                            event_type="REFUND_REQUESTED",
                            created_at=opened,
                            payload={
                                "eventId": event,
                                "refundId": refund,
                                "orderId": order.order_id,
                                "paymentAttemptId": attempt,
                                "amountMinor": order.amount,
                                "currency": "CNY",
                                "stateVersion": 1,
                            },
                        ),
                    )
                )
    return orders, facts


FULFILLMENT_RULES = {
    "standard": {
        "feeMinor": 599,
        "freeOverMinor": 4900,
        "minBusinessDays": 3,
        "maxBusinessDays": 5,
    },
    "express": {"feeMinor": 999, "memberFreeOverMinor": 4900, "businessDays": 2},
    "freight": {
        "feeMinor": 2900,
        "minBusinessDays": 5,
        "maxBusinessDays": 7,
        "categories": ["office-electronics", "fitness"],
        "unitPriceOverMinor": 35000,
    },
    "pickup": {
        "location": "ShopMate 上海演示门店（徐汇区）",
        "opensAt": "09:00",
        "closesAt": "21:00",
        "preparationMinutes": 120,
    },
}


def marketing_rows(as_of: date) -> list[str]:
    end = midnight(as_of)
    result = []
    daily = load("merchant_metrics")["daily"]
    for index in range(REPORT_DAYS):
        source = daily[index % len(daily)]
        day = as_of - timedelta(days=REPORT_DAYS - index)
        result.append(
            insert(
                "retail_store_traffic_daily",
                local_date=day.isoformat(),
                visits=int(source["traffic"]),
                observed_at=midnight(day + timedelta(days=1)),
                source_ref=VERSION + f"/traffic/{index:02d}",
                fixture_version=VERSION,
            )
        )
    source = load("merchant_campaigns")
    shift = as_of - date.fromisoformat(source["dates_anchored_to"])
    for campaign in source["campaigns"]:
        starts = midnight(date.fromisoformat(campaign["starts"]) + shift)
        ends = midnight(date.fromisoformat(campaign["ends"]) + shift + timedelta(days=1))
        result.append(
            insert(
                "retail_campaign",
                campaign_id=campaign["campaign_id"],
                name=campaign["name"],
                objective=campaign.get("objective"),
                channel=campaign.get("channel"),
                currency="CNY",
                budget_minor=minor(campaign["budget"]),
                starts_at=starts,
                ends_at=ends,
                state=campaign["status"],
                version=1,
                created_at=starts,
                updated_at=end,
                spend_minor=minor(campaign["spend"]) if campaign.get("spend") is not None else None,
                revenue_minor=minor(campaign["revenue"])
                if campaign.get("revenue") is not None
                else None,
                observation_source_kind="FIXTURE",
                observation_source_ref=VERSION + "/" + campaign["campaign_id"],
                observed_at=end,
                observation_start=starts,
                observation_end=min(ends, end),
                fixture_version=VERSION,
            )
        )
    return result


def policy_entries() -> list[dict]:
    # Consultation follows this deployment's actual services; no simulated settlement or paid membership.
    replacements = {
        "returns": (
            "退货、换货与退款 Returns refunds",
            "可查询本人已支付订单并准备退款申请。准备阶段不会执行退款；请核对订单、金额后亲自确认，系统会复核归属与剩余可退额度。REQUESTED表示已记录退款申请，模拟支付不会实际退钱，不承诺到账时限或自动换货。",
        ),
        "shipping": (
            "配送运费与时效 Shipping delivery",
            "金额使用人民币。标准配送5.99元，商品小计严格大于49元免运费，预计3至5个工作日；加急9.99元，MEMBER会员在同一门槛以上免加急费，预计2个工作日。大件使用货运规则；门店可自提。具体商品、数量、会员和货运估算以配送工具为准。结账金额目前只收商品金额，配送报价为咨询估算，未实际向承运商发运。",
        ),
        "price-match": (
            "价格比较与价保 Price match",
            "可以比较本店当前价格、规格和库存，并检索公开价格线索。本店不提供自动价保或补差支付；外部报价不能直接修改订单成交价。历史订单始终保留原成交金额，退款申请以该订单实际可退额度为准。",
        ),
        "warranty": (
            "保修与售后 Warranty",
            "保修范围需结合商品说明和实际厂商条款核实，不能从商品评分推断保修。当前工作台可查询订单及退款申请，不销售额外延保，也不自动向厂商提交索赔。",
        ),
        "membership": (
            "会员权益 Membership",
            "MEMBER是本演示商店已授予的会员权益，登录账户信息为准；满足门槛可享加急配送估算优惠。本商城没有收费订阅、自动续费、积分返现或会员扣款。",
        ),
        "gift-cards": (
            "礼品卡与支付 Gift cards payments",
            "结账交接后由登录用户明确确认商品和金额，再进行模拟支付。当前不发行或兑换礼品卡；不能把优惠建议当成礼品卡余额，也不会自动发送邮件或扣取真实资金。",
        ),
        "order-changes": (
            "订单修改取消 Changing cancelling orders",
            "尚未结账时可以调整购物车数量或删除商品。结账后的订单保留原始价格和数量；结账后不支持在线修改地址或取消订单。已付款且存在剩余可退额度时可以准备退款申请，确认前不会执行。",
        ),
        "damaged-items": (
            "商品损坏、破损与缺件售后 Damaged missing items",
            "先核对本人订单、商品和履约记录，再说明损坏或缺件情况。助手可以解释订单状态并准备符合额度的退款申请；图片举证、换货物流和补发需另行联系售后。买家留言属于待核实资料，不能授予调价或审批权限。",
        ),
    }
    result = []
    for policy in load("policies")["policies"]:
        key = policy["policy_id"]
        title, answer = replacements.get(key, (policy["title"], policy["content"]))
        faq_id = "retail-" + key if key.startswith("guide-") else "retail-policy-" + key
        result.append({"faqId": faq_id, "question": title, "answer": answer})
    return result


def fixture_sql(as_of: date) -> str:
    families, skus = catalog()
    sku_map = {sku["id"]: sku for sku in skus}
    end, start = midnight(as_of), midnight(as_of - timedelta(days=REPORT_DAYS))
    rows = [
        f"-- Synthetic {VERSION}; {REPORT_DAYS} complete Asia/Shanghai days ending {as_of}.",
        "SET NAMES utf8mb4;",
        "SET SESSION time_zone='+00:00';",
        "START TRANSACTION;",
        *cleanup_rows(skus, families),
    ]
    for family in families:
        rows.append(
            insert(
                "retail_product_family",
                family_id=family["id"],
                name=family["name"],
                description=family["description"],
                content=family["content"],
                options=family["options"],
                metadata_version=1,
                display_order=family["position"],
            )
        )
    for sku in skus:
        rows.extend(
            (
                insert(
                    "product",
                    product_id=sku["id"],
                    name=sku["name"],
                    description=sku["description"],
                    price_minor=sku["price"],
                    currency="CNY",
                    stock_quantity=sku["stock"],
                    available=sku["available"],
                    publication_state=sku["publication"],
                    publication_version=3,
                    created_at=start,
                    updated_at=end,
                ),
                insert(
                    "retail_product_metadata",
                    product_id=sku["id"],
                    family_id=sku["family"],
                    content=sku["content"],
                    option_values=sku["option_values"],
                    metadata_version=1,
                    display_order=sku["position"],
                ),
                insert(
                    "retail_product_operations",
                    product_id=sku["id"],
                    unit_cost_minor=sku["cost"],
                    low_stock_threshold=sku["threshold"],
                    content_quality=sku["quality"],
                    missing_attributes=sku["missing"],
                    facts_version=1,
                    observed_at=end,
                    source_ref=VERSION + "/" + sku["id"],
                ),
            )
        )
    for index, user in enumerate(load("users")["users"]):
        rows.append(
            insert(
                "crm_profile",
                user_subject=BUYERS[index],
                display_name=user["display_name"],
                loyalty_tier="MEMBER" if index == 0 else "NONE",
                default_location="上海徐汇区演示地址",
                preferences=user["preferences"],
                created_at=start,
                updated_at=end,
            )
        )
    rows.append("DELETE FROM retail_fulfillment_config WHERE config_id='default';")
    rows.append(
        insert(
            "retail_fulfillment_config",
            config_id="default",
            config_version=1,
            currency="CNY",
            time_zone="Asia/Shanghai",
            rules=FULFILLMENT_RULES,
            updated_at=end,
        )
    )
    customer, fulfillment = customer_orders(as_of, sku_map)
    issues, issue_facts = issue_orders(as_of, sku_map)
    for order in [*historical_orders(as_of, skus), *customer, *issues]:
        rows.extend(order_rows(order))
    rows.extend(fulfillment)
    rows.extend(issue_facts)
    rows.extend(marketing_rows(as_of))
    rows.extend(
        (
            (
                "INSERT INTO catalog_metadata(singleton_id,publication_generation) VALUES(1,1) "
                "ON DUPLICATE KEY UPDATE publication_generation=publication_generation+1;"
            ),
            "COMMIT;",
        )
    )
    return "\n".join(rows) + "\n"
