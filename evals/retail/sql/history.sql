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
SELECT order_kind,order_id,product_id,quantity,unit_price_minor,product_version,total_price_minor,currency,succeeded_at
FROM paid ORDER BY order_kind,order_id;
SELECT o.order_id,o.product_id,o.status,a.state AS payment_state,a.amount_minor,a.currency,a.succeeded_at
FROM standard_order o LEFT JOIN mock_payment_attempt a ON a.order_kind='STANDARD' AND a.order_id=o.order_id
WHERE o.sandbox_id IS NULL AND (a.state IS NULL OR a.state<>'SUCCEEDED') ORDER BY o.order_id,a.attempt_id;
