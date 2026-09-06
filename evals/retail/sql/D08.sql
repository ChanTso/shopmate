SET SESSION time_zone = '+00:00';
WITH paid AS (
  SELECT 'STANDARD' AS order_kind, o.order_id, o.product_id, o.product_name,
         o.quantity, o.unit_price_minor, o.product_version, o.total_price_minor, o.currency, a.succeeded_at
  FROM standard_order o JOIN mock_payment_attempt a
    ON a.order_kind='STANDARD' AND a.order_id=o.order_id
  WHERE o.status='PAID' AND o.sandbox_id IS NULL AND a.sandbox_id IS NULL
    AND a.state='SUCCEEDED' AND a.succeeded_at IS NOT NULL
    AND CAST(a.user_subject AS BINARY)=CAST(o.user_subject AS BINARY)
    AND a.amount_minor=o.total_price_minor AND a.currency=o.currency
  UNION ALL
  SELECT 'SECKILL', o.order_id, o.product_id, o.product_name,
         o.quantity, o.unit_price_minor, NULL AS product_version, o.total_price_minor, o.currency, a.succeeded_at
  FROM seckill_order o JOIN mock_payment_attempt a
    ON a.order_kind='SECKILL' AND a.order_id=o.order_id
  WHERE o.status='PAID' AND a.sandbox_id IS NULL
    AND a.state='SUCCEEDED' AND a.succeeded_at IS NOT NULL
    AND CAST(a.user_subject AS BINARY)=CAST(o.user_subject AS BINARY)
    AND a.amount_minor=o.total_price_minor AND a.currency=o.currency
)
SELECT p.product_id,p.name,p.stock_quantity,
       COUNT(CASE WHEN h.succeeded_at < '2026-08-21 16:00:00' THEN 1 END) AS prior_orders,
       COUNT(CASE WHEN h.succeeded_at >= '2026-08-21 16:00:00' THEN 1 END) AS recent_orders,
       COALESCE(SUM(CASE WHEN h.succeeded_at < '2026-08-21 16:00:00' THEN h.total_price_minor ELSE 0 END),0) AS prior_amount_minor,
       COALESCE(SUM(CASE WHEN h.succeeded_at >= '2026-08-21 16:00:00' THEN h.total_price_minor ELSE 0 END),0) AS recent_amount_minor
FROM product p LEFT JOIN paid h ON h.product_id=p.product_id AND h.currency='CNY'
  AND h.succeeded_at >= '2026-08-07 16:00:00' AND h.succeeded_at < '2026-09-04 16:00:00'
WHERE p.product_id='AR-1806' GROUP BY p.product_id,p.name,p.stock_quantity;
SELECT campaign_id,currency,budget_minor,spend_minor,revenue_minor,observation_start,observation_end,
       observation_source_kind,observation_source_ref,fixture_version
FROM retail_campaign ORDER BY campaign_id;
