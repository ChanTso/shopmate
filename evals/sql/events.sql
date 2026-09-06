SET SESSION time_zone = '+00:00';
SELECT d.draft_id, d.state, j.product_id, j.event_id,
       e.aggregate_type, e.aggregate_id, e.aggregate_version,
       e.event_type, e.payload, e.publication_state AS outbox_state
FROM merchant_price_draft d
JOIN JSON_TABLE(
  COALESCE(d.result, JSON_OBJECT()), '$.changes[*]'
  COLUMNS (
    product_id VARCHAR(64) PATH '$.productId',
    event_id VARCHAR(36) PATH '$.eventId'
  )
) AS j
LEFT JOIN commerce_outbox e ON e.event_id = j.event_id
WHERE d.operator_subject = 'shopmate-fixture-operator'
  AND d.session_id = @session_id
ORDER BY d.draft_id, j.product_id;

SELECT event_id, aggregate_id, aggregate_version, event_type, payload, publication_state
FROM commerce_outbox
WHERE aggregate_type = 'PRODUCT'
  AND aggregate_id IN (
    'shopmate-fixture-coffee', 'shopmate-fixture-tea', 'shopmate-fixture-mug',
    'shopmate-fixture-tote', 'shopmate-fixture-cocoa-usd',
    'shopmate-fixture-unavailable', 'shopmate-fixture-seckill'
  )
ORDER BY aggregate_id, aggregate_version, event_id;
