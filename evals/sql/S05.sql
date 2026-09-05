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
SELECT product_id,
       CASE WHEN succeeded_at < '2026-08-22' THEN 'B' ELSE 'A' END AS period,
       SUM(quantity) AS units, SUM(total_price_minor) AS amount_minor
FROM paid WHERE product_id IN ('shopmate-fixture-coffee', 'shopmate-fixture-tea')
  AND succeeded_at >= '2026-08-08' AND succeeded_at < '2026-09-05'
GROUP BY product_id, period ORDER BY product_id, period DESC;
