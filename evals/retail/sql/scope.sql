SET SESSION time_zone = '+00:00';
SELECT COUNT(*) AS sku_count,COUNT(DISTINCT COALESCE(m.family_id,p.product_id)) AS display_roots,
       MIN(p.currency) AS minimum_currency,MAX(p.currency) AS maximum_currency
FROM product p LEFT JOIN retail_product_metadata m ON m.product_id=p.product_id;
SELECT MIN(local_date) AS coverage_start,MAX(local_date) AS last_covered_day,COUNT(*) AS observed_days,
       SUM(visits) AS visits,MIN(fixture_version) AS minimum_version,MAX(fixture_version) AS maximum_version
FROM retail_store_traffic_daily;
SELECT order_kind,currency,COUNT(*) AS orders,SUM(quantity) AS units,SUM(total_price_minor) AS amount_minor,
       MIN(succeeded_at) AS first_payment,MAX(succeeded_at) AS last_payment
FROM merchant_paid_orders GROUP BY order_kind,currency ORDER BY order_kind,currency;
SELECT COUNT(*) AS unfinished_product_outbox FROM commerce_outbox
WHERE aggregate_type='PRODUCT' AND publication_state <> 'PUBLISHED';
