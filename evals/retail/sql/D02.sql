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
), totals AS (
  SELECT
    COUNT(CASE WHEN succeeded_at >= '2026-08-21 16:00:00' THEN 1 END) AS current_orders,
    COUNT(CASE WHEN succeeded_at < '2026-08-21 16:00:00' THEN 1 END) AS prior_orders,
    COALESCE(SUM(CASE WHEN succeeded_at >= '2026-08-21 16:00:00' THEN total_price_minor ELSE 0 END),0) AS current_amount_minor,
    COALESCE(SUM(CASE WHEN succeeded_at < '2026-08-21 16:00:00' THEN total_price_minor ELSE 0 END),0) AS prior_amount_minor
  FROM paid WHERE currency='CNY' AND succeeded_at >= '2026-08-07 16:00:00' AND succeeded_at < '2026-09-04 16:00:00'
)
SELECT *, CAST(current_orders AS SIGNED)-CAST(prior_orders AS SIGNED) AS order_delta,
       current_amount_minor-prior_amount_minor AS amount_delta_minor,
       100.0*(CAST(current_orders AS SIGNED)-CAST(prior_orders AS SIGNED))/NULLIF(prior_orders,0) AS order_change_pct,
       100.0*(current_amount_minor-prior_amount_minor)/NULLIF(prior_amount_minor,0) AS amount_change_pct
FROM totals;
