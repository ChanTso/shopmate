SET SESSION time_zone = '+00:00';
SELECT user_subject,display_name,loyalty_tier,default_location,preferences
FROM crm_profile
WHERE CAST(user_subject AS BINARY) IN (CAST(@buyer_subject AS BINARY),CAST(@buyer2_subject AS BINARY))
ORDER BY user_subject;
SELECT faq_id,published_question,published_answer,published_version,published_at,working_state
FROM faq_source WHERE published_version>0
  AND (faq_id LIKE 'retail-policy-%' OR faq_id LIKE 'retail-guide-%') ORDER BY faq_id;
SELECT config_id,config_version,currency,time_zone,rules,updated_at
FROM retail_fulfillment_config ORDER BY config_id;
SELECT o.order_id,o.user_subject,o.product_id,o.status,f.method,f.stage,
       f.promised_delivery_at,f.estimated_delivery_at,f.packed_at,f.shipped_at,f.delivered_at,
       f.delay_reason,f.source_kind,f.source_ref,f.observed_at
FROM standard_order o LEFT JOIN retail_order_fulfillment f ON f.order_id=o.order_id
WHERE CAST(o.user_subject AS BINARY) IN (CAST(@buyer_subject AS BINARY),CAST(@buyer2_subject AS BINARY))
ORDER BY o.user_subject,o.created_at DESC,o.order_id DESC;
SELECT i.issue_id,i.order_id,o.product_id,o.user_subject,i.kind,i.summary,i.buyer_message_excerpt,
       i.opened_at,i.resolved_at,i.window_start,i.window_end,i.source_kind,i.source_ref
FROM retail_order_issue i JOIN standard_order o ON o.order_id=i.order_id
ORDER BY i.opened_at DESC,i.issue_id;
SELECT local_date,visits,observed_at,source_ref,fixture_version
FROM retail_store_traffic_daily ORDER BY local_date;
SELECT campaign_id,currency,budget_minor,spend_minor,revenue_minor,
       revenue_minor/NULLIF(spend_minor,0) AS observed_roas,
       observation_start,observation_end,observation_source_kind,observation_source_ref,observed_at
FROM retail_campaign ORDER BY campaign_id;
-- Historical reports end at 2026-09-05 00:00 Asia/Shanghai, not at the live operation time.
WITH paid AS (
  SELECT o.order_id,o.product_id,o.quantity,o.total_price_minor,o.currency,a.succeeded_at
  FROM standard_order o JOIN mock_payment_attempt a
    ON a.order_kind='STANDARD' AND a.order_id=o.order_id
  WHERE o.status='PAID' AND o.sandbox_id IS NULL AND a.sandbox_id IS NULL
    AND a.state='SUCCEEDED' AND a.succeeded_at IS NOT NULL
    AND CAST(a.user_subject AS BINARY)=CAST(o.user_subject AS BINARY)
    AND a.amount_minor=o.total_price_minor AND a.currency=o.currency
  UNION ALL
  SELECT o.order_id,o.product_id,o.quantity,o.total_price_minor,o.currency,a.succeeded_at
  FROM seckill_order o JOIN mock_payment_attempt a
    ON a.order_kind='SECKILL' AND a.order_id=o.order_id
  WHERE o.status='PAID' AND a.sandbox_id IS NULL
    AND a.state='SUCCEEDED' AND a.succeeded_at IS NOT NULL
    AND CAST(a.user_subject AS BINARY)=CAST(o.user_subject AS BINARY)
    AND a.amount_minor=o.total_price_minor AND a.currency=o.currency
),
period_sales AS (
  SELECT COUNT(*) AS paid_orders,SUM(quantity) AS paid_units,SUM(total_price_minor) AS amount_minor
  FROM paid WHERE currency='CNY'
    AND succeeded_at>='2026-08-05 16:00:00' AND succeeded_at<'2026-09-04 16:00:00'
), traffic AS (
  SELECT COUNT(*) AS covered_days,SUM(visits) AS visits FROM retail_store_traffic_daily
  WHERE local_date>='2026-08-06' AND local_date<'2026-09-05'
)
SELECT s.paid_orders,s.paid_units,s.amount_minor,t.covered_days,t.visits,
       s.amount_minor/NULLIF(s.paid_orders,0) AS aov_minor,
       CASE WHEN t.covered_days=30 THEN s.paid_orders/NULLIF(t.visits,0) END AS conversion_ratio
FROM period_sales s CROSS JOIN traffic t;
WITH paid AS (
  SELECT o.order_id,o.product_id,o.quantity,o.total_price_minor,o.currency,a.succeeded_at
  FROM standard_order o JOIN mock_payment_attempt a
    ON a.order_kind='STANDARD' AND a.order_id=o.order_id
  WHERE o.status='PAID' AND o.sandbox_id IS NULL AND a.sandbox_id IS NULL
    AND a.state='SUCCEEDED' AND a.succeeded_at IS NOT NULL
    AND CAST(a.user_subject AS BINARY)=CAST(o.user_subject AS BINARY)
    AND a.amount_minor=o.total_price_minor AND a.currency=o.currency
  UNION ALL
  SELECT o.order_id,o.product_id,o.quantity,o.total_price_minor,o.currency,a.succeeded_at
  FROM seckill_order o JOIN mock_payment_attempt a
    ON a.order_kind='SECKILL' AND a.order_id=o.order_id
  WHERE o.status='PAID' AND a.sandbox_id IS NULL
    AND a.state='SUCCEEDED' AND a.succeeded_at IS NOT NULL
    AND CAST(a.user_subject AS BINARY)=CAST(o.user_subject AS BINARY)
    AND a.amount_minor=o.total_price_minor AND a.currency=o.currency
)
SELECT COUNT(*) AS kids_room_paid_orders,SUM(a.quantity) AS kids_room_units,
       SUM(a.total_price_minor) AS kids_room_amount_minor
FROM paid a JOIN product p ON p.product_id=a.product_id
LEFT JOIN retail_product_metadata m ON m.product_id=p.product_id
LEFT JOIN retail_product_family f ON f.family_id=m.family_id
WHERE a.currency='CNY'
  AND a.succeeded_at>='2026-08-05 16:00:00' AND a.succeeded_at<'2026-09-04 16:00:00'
  AND JSON_UNQUOTE(JSON_EXTRACT(COALESCE(f.content,m.content,JSON_OBJECT()),'$.category'))='kids-room';
-- Traffic supplies the observed calendar. A missing date is not invented as a covered day.
WITH paid AS (
  SELECT o.order_id,o.product_id,o.quantity,o.total_price_minor,o.currency,a.succeeded_at
  FROM standard_order o JOIN mock_payment_attempt a
    ON a.order_kind='STANDARD' AND a.order_id=o.order_id
  WHERE o.status='PAID' AND o.sandbox_id IS NULL AND a.sandbox_id IS NULL
    AND a.state='SUCCEEDED' AND a.succeeded_at IS NOT NULL
    AND CAST(a.user_subject AS BINARY)=CAST(o.user_subject AS BINARY)
    AND a.amount_minor=o.total_price_minor AND a.currency=o.currency
  UNION ALL
  SELECT o.order_id,o.product_id,o.quantity,o.total_price_minor,o.currency,a.succeeded_at
  FROM seckill_order o JOIN mock_payment_attempt a
    ON a.order_kind='SECKILL' AND a.order_id=o.order_id
  WHERE o.status='PAID' AND a.sandbox_id IS NULL
    AND a.state='SUCCEEDED' AND a.succeeded_at IS NOT NULL
    AND CAST(a.user_subject AS BINARY)=CAST(o.user_subject AS BINARY)
    AND a.amount_minor=o.total_price_minor AND a.currency=o.currency
),
days AS (
  SELECT local_date FROM retail_store_traffic_daily
  WHERE local_date>='2026-08-08' AND local_date<'2026-09-05'
), daily AS (
  SELECT DATE(CONVERT_TZ(succeeded_at,'+00:00','+08:00')) AS local_date,
         SUM(total_price_minor) AS amount_minor
  FROM paid WHERE currency='CNY'
    AND succeeded_at>='2026-08-07 16:00:00' AND succeeded_at<'2026-09-04 16:00:00'
  GROUP BY local_date
)
SELECT d.local_date,COALESCE(a.amount_minor,0) AS paid_amount_minor
FROM days d LEFT JOIN daily a ON a.local_date=d.local_date ORDER BY d.local_date;
WITH paid AS (
  SELECT o.order_id,o.product_id,o.quantity,o.total_price_minor,o.currency,a.succeeded_at
  FROM standard_order o JOIN mock_payment_attempt a
    ON a.order_kind='STANDARD' AND a.order_id=o.order_id
  WHERE o.status='PAID' AND o.sandbox_id IS NULL AND a.sandbox_id IS NULL
    AND a.state='SUCCEEDED' AND a.succeeded_at IS NOT NULL
    AND CAST(a.user_subject AS BINARY)=CAST(o.user_subject AS BINARY)
    AND a.amount_minor=o.total_price_minor AND a.currency=o.currency
  UNION ALL
  SELECT o.order_id,o.product_id,o.quantity,o.total_price_minor,o.currency,a.succeeded_at
  FROM seckill_order o JOIN mock_payment_attempt a
    ON a.order_kind='SECKILL' AND a.order_id=o.order_id
  WHERE o.status='PAID' AND a.sandbox_id IS NULL
    AND a.state='SUCCEEDED' AND a.succeeded_at IS NOT NULL
    AND CAST(a.user_subject AS BINARY)=CAST(o.user_subject AS BINARY)
    AND a.amount_minor=o.total_price_minor AND a.currency=o.currency
),
days AS (
  SELECT local_date FROM retail_store_traffic_daily
  WHERE local_date>='2026-08-08' AND local_date<'2026-09-05'
), daily AS (
  SELECT DATE(CONVERT_TZ(succeeded_at,'+00:00','+08:00')) AS local_date,
         SUM(total_price_minor) AS amount_minor
  FROM paid WHERE currency='CNY'
    AND succeeded_at>='2026-08-07 16:00:00' AND succeeded_at<'2026-09-04 16:00:00'
  GROUP BY local_date
)
SELECT COUNT(*) AS covered_days,SUM(COALESCE(a.amount_minor,0)) AS amount_minor,
       CASE WHEN COUNT(*)=28 THEN STDDEV_POP(COALESCE(a.amount_minor,0))/100 END AS daily_stddev_cny,
       MAX(COALESCE(a.amount_minor,0)) AS maximum_daily_amount_minor
FROM days d LEFT JOIN daily a ON a.local_date=d.local_date;
