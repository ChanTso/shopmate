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
SELECT p.product_id, p.name, p.price_minor AS current_price_minor,
       COUNT(h.order_id) AS orders, COALESCE(SUM(h.quantity),0) AS units,
       COALESCE(SUM(h.total_price_minor),0) AS historical_amount_minor,
       SUM(h.total_price_minor)/NULLIF(SUM(h.quantity),0) AS weighted_unit_price_minor,
       MIN(h.unit_price_minor) AS min_historical_unit_price_minor,
       MAX(h.unit_price_minor) AS max_historical_unit_price_minor
FROM product p LEFT JOIN paid h ON h.product_id=p.product_id AND h.currency='CNY'
  AND h.succeeded_at >= '2026-08-05 16:00:00' AND h.succeeded_at < '2026-09-04 16:00:00'
WHERE p.currency='CNY' GROUP BY p.product_id,p.name,p.price_minor ORDER BY p.product_id;
