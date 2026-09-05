SET SESSION time_zone = '+00:00';
SELECT product_id, currency, price_editable FROM merchant_products ORDER BY product_id;
SELECT order_kind, currency, COUNT(*) AS orders, SUM(quantity) AS units, SUM(total_price_minor) AS amount_minor, MIN(succeeded_at), MAX(succeeded_at) FROM merchant_paid_orders GROUP BY order_kind,currency ORDER BY order_kind,currency;
SELECT COUNT(*) AS unfinished_fixture_product_outbox FROM commerce_outbox WHERE aggregate_type='PRODUCT' AND aggregate_id LIKE 'shopmate-fixture-%' AND publication_state <> 'PUBLISHED';
