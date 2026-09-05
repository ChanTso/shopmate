SET SESSION time_zone = '+00:00';
WITH paid_all AS (
  SELECT 'STANDARD' AS order_kind, o.order_id, o.product_id, o.product_name,
         o.quantity, o.total_price_minor, o.currency, a.succeeded_at
  FROM standard_order o
  JOIN mock_payment_attempt a
    ON a.order_kind = 'STANDARD' AND a.order_id = o.order_id
  WHERE o.status = 'PAID' AND o.sandbox_id IS NULL AND a.sandbox_id IS NULL
    AND a.state = 'SUCCEEDED' AND a.succeeded_at IS NOT NULL
    AND a.user_subject = o.user_subject
    AND a.amount_minor = o.total_price_minor AND a.currency = o.currency
  UNION ALL
  SELECT 'SECKILL', o.order_id, o.product_id, o.product_name,
         o.quantity, o.total_price_minor, o.currency, a.succeeded_at
  FROM seckill_order o
  JOIN mock_payment_attempt a
    ON a.order_kind = 'SECKILL' AND a.order_id = o.order_id
  WHERE o.status = 'PAID' AND a.sandbox_id IS NULL
    AND a.state = 'SUCCEEDED' AND a.succeeded_at IS NOT NULL
    AND a.user_subject = o.user_subject
    AND a.amount_minor = o.total_price_minor AND a.currency = o.currency
), paid AS (
  SELECT * FROM paid_all
  WHERE product_id IN (
    'shopmate-fixture-coffee', 'shopmate-fixture-tea', 'shopmate-fixture-mug',
    'shopmate-fixture-tote', 'shopmate-fixture-cocoa-usd',
    'shopmate-fixture-unavailable', 'shopmate-fixture-seckill'
  )
)
SELECT p.product_id, COUNT(o.order_id) AS orders,
       COALESCE(SUM(o.quantity), 0) AS units,
       COALESCE(SUM(o.total_price_minor), 0) AS amount_minor
FROM product p LEFT JOIN paid o ON o.product_id = p.product_id
  AND o.succeeded_at >= '2026-08-31' AND o.succeeded_at < '2026-09-01'
WHERE p.product_id IN ('shopmate-fixture-coffee', 'shopmate-fixture-tea', 'shopmate-fixture-mug')
GROUP BY p.product_id ORDER BY p.product_id;
