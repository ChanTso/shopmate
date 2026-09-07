SET SESSION time_zone = '+00:00';
-- Owner-bound raw rows retain failed/pending payments instead of filtering them into success.
SELECT user_subject,cart_version,created_at,updated_at
FROM shopping_cart
WHERE CAST(user_subject AS BINARY) IN (CAST(@buyer_subject AS BINARY),CAST(@buyer2_subject AS BINARY))
ORDER BY user_subject;
SELECT i.user_subject,i.product_id,i.quantity,p.price_minor,p.currency,p.publication_version,
       p.stock_quantity,p.available,p.publication_state
FROM shopping_cart_item i JOIN product p ON p.product_id=i.product_id
WHERE CAST(i.user_subject AS BINARY) IN (CAST(@buyer_subject AS BINARY),CAST(@buyer2_subject AS BINARY))
ORDER BY i.user_subject,i.product_id;
SELECT user_subject,command_key,operation,product_id,before_quantity,after_quantity,applied_cart_version,created_at
FROM shopping_cart_command
WHERE CAST(user_subject AS BINARY) IN (CAST(@buyer_subject AS BINARY),CAST(@buyer2_subject AS BINARY))
ORDER BY user_subject,created_at,command_key;
SELECT checkout_id,user_subject,request_key,source_cart_version,currency,total_minor,created_at
FROM shopping_checkout
WHERE CAST(user_subject AS BINARY) IN (CAST(@buyer_subject AS BINARY),CAST(@buyer2_subject AS BINARY))
ORDER BY created_at,checkout_id;
SELECT c.checkout_id,c.user_subject,l.line_no,o.order_id,o.product_id,o.product_name,
       o.quantity,o.unit_price_minor,o.total_price_minor,o.currency,o.product_version,
       o.status,o.state_version,o.created_at
FROM shopping_checkout c JOIN shopping_checkout_order l ON l.checkout_id=c.checkout_id
JOIN standard_order o ON o.order_id=l.order_id
WHERE CAST(c.user_subject AS BINARY) IN (CAST(@buyer_subject AS BINARY),CAST(@buyer2_subject AS BINARY))
ORDER BY c.created_at,c.checkout_id,l.line_no;
SELECT o.order_id,o.user_subject,o.product_id,o.quantity,o.unit_price_minor,o.total_price_minor,
       o.currency,o.product_version,o.status,o.state_version,o.created_at,o.sandbox_id,
       a.attempt_id,a.user_subject AS payment_owner,a.order_kind,a.amount_minor,
       a.refunded_amount_minor,a.currency AS payment_currency,a.state AS payment_state,
       a.succeeded_at,a.sandbox_id AS payment_sandbox_id
FROM standard_order o LEFT JOIN mock_payment_attempt a
  ON a.order_kind='STANDARD' AND a.order_id=o.order_id
WHERE CAST(o.user_subject AS BINARY) IN (CAST(@buyer_subject AS BINARY),CAST(@buyer2_subject AS BINARY))
ORDER BY o.created_at DESC,o.order_id DESC;
SELECT c.callback_event_id,c.callback_idempotency_key,c.attempt_id,c.callback_correlation_id,
       c.requested_outcome,c.result_state,c.created_at,a.order_id,a.user_subject
FROM mock_payment_callback c JOIN mock_payment_attempt a ON a.attempt_id=c.attempt_id
WHERE CAST(a.user_subject AS BINARY) IN (CAST(@buyer_subject AS BINARY),CAST(@buyer2_subject AS BINARY))
ORDER BY c.created_at,c.callback_event_id;
SELECT l.movement_id,l.business_event_key,l.movement_type,l.order_id,l.product_id,
       l.inventory_delta,l.payment_amount_minor,l.payment_currency,l.created_at
FROM inventory_ledger l JOIN standard_order o ON o.order_id=l.order_id
WHERE CAST(o.user_subject AS BINARY) IN (CAST(@buyer_subject AS BINARY),CAST(@buyer2_subject AS BINARY))
ORDER BY l.order_id,l.created_at,l.movement_id;
SELECT pending_action_id,user_subject,support_session_id,trace_id,turn_id,action_type,required_scope,
       sandbox_id,order_id,order_kind,payment_attempt_id,target_order_version,amount_minor,currency,
       state,state_version,created_at,expires_at,consumed_at
FROM pending_action
WHERE CAST(user_subject AS BINARY) IN (CAST(@buyer_subject AS BINARY),CAST(@buyer2_subject AS BINARY))
ORDER BY created_at,pending_action_id;
SELECT receipt_id,pending_action_id,user_subject,support_session_id,order_id,payment_attempt_id,
       refund_id,result_state,resulting_resource_version,amount_minor,currency,outbox_event_id,committed_at
FROM action_receipt
WHERE CAST(user_subject AS BINARY) IN (CAST(@buyer_subject AS BINARY),CAST(@buyer2_subject AS BINARY))
ORDER BY committed_at,receipt_id;
SELECT refund_id,user_subject,order_id,order_kind,payment_attempt_id,request_idempotency_key,
       eligible_amount_minor,requested_amount_minor,refunded_amount_minor,currency,state,state_version,
       failure_code,processing_at,completed_at,created_at
FROM mock_refund
WHERE CAST(user_subject AS BINARY) IN (CAST(@buyer_subject AS BINARY),CAST(@buyer2_subject AS BINARY))
ORDER BY created_at,refund_id;
SELECT e.event_id,e.aggregate_type,e.aggregate_id,e.aggregate_version,e.event_type,
       e.payload,e.publication_state,e.created_at,e.published_at
FROM commerce_outbox e
WHERE (e.aggregate_type='STANDARD_ORDER' AND EXISTS (
  SELECT 1 FROM standard_order o WHERE o.order_id=e.aggregate_id
    AND CAST(o.user_subject AS BINARY) IN (CAST(@buyer_subject AS BINARY),CAST(@buyer2_subject AS BINARY))))
OR (e.aggregate_type='REFUND' AND EXISTS (
  SELECT 1 FROM mock_refund r WHERE r.refund_id=e.aggregate_id
    AND CAST(r.user_subject AS BINARY) IN (CAST(@buyer_subject AS BINARY),CAST(@buyer2_subject AS BINARY))))
ORDER BY e.created_at,e.event_id;
-- These identifiers come from actual HTTP responses, never from hidden SQL candidate selection.
SELECT @buyer_checkout_id AS confirmed_checkout_id,@buyer_order_id AS selected_refund_order_id,
       @buyer_pending_action_id AS visible_refund_card_id;
