SET SESSION time_zone = '+00:00';
-- Set @session_id from the actual host response using a bound SQL parameter before this query.
SELECT draft_id, operator_subject, session_id, request_key, currency,
       state, items, result, created_at, resolved_at
FROM merchant_price_draft
WHERE operator_subject = 'shopmate-fixture-operator'
  AND session_id = @session_id
ORDER BY created_at, draft_id;
