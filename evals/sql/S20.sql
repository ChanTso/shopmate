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
SELECT o.product_id, p.price_minor AS current_price_minor,
       SUM(CASE WHEN o.succeeded_at >= '2026-08-22'
                THEN o.total_price_minor ELSE -o.total_price_minor END) AS increase_minor
FROM paid o JOIN product p USING (product_id)
WHERE o.currency = 'CNY' AND p.currency = 'CNY'
  AND p.publication_state = 'PUBLISHED' AND p.available
  AND NOT EXISTS (SELECT 1 FROM seckill_activity a WHERE a.product_id = p.product_id)
  AND o.succeeded_at >= '2026-08-08' AND o.succeeded_at < '2026-09-05'
GROUP BY o.product_id, p.price_minor ORDER BY increase_minor DESC, o.product_id LIMIT 1;
