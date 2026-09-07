SET SESSION time_zone = '+00:00';
SELECT draft_id,kind,operator_subject,session_id,currency,state,items,payload,result,created_at,resolved_at
FROM merchant_price_draft
WHERE CAST(operator_subject AS BINARY)=CAST(@merchant_subject AS BINARY)
  AND session_id=@merchant_session_id
ORDER BY created_at,draft_id;
SELECT product_id,unit_cost_minor,low_stock_threshold,content_quality,missing_attributes,
       facts_version,observed_at,source_ref
FROM retail_product_operations ORDER BY product_id;
SELECT c.campaign_id,c.name,c.objective,c.audience,c.copy_text,c.channel,c.currency,c.budget_minor,
       c.starts_at,c.ends_at,c.state,c.version,c.source_change_id,c.spend_minor,c.revenue_minor,
       c.observation_source_kind,c.observation_source_ref,c.observation_start,c.observation_end,
       c.observed_at,c.fixture_version,c.created_at,c.updated_at
FROM retail_campaign c ORDER BY c.campaign_id;
SELECT p.promotion_id,p.name,p.currency,p.discount_basis_points,p.starts_at,p.ends_at,
       p.state,p.version,p.applied_at,p.source_change_id,p.created_at,p.updated_at
FROM retail_promotion p JOIN merchant_price_draft d ON d.draft_id=p.source_change_id
WHERE CAST(d.operator_subject AS BINARY)=CAST(@merchant_subject AS BINARY)
  AND d.session_id=@merchant_session_id
ORDER BY p.created_at,p.promotion_id;
SELECT i.promotion_id,i.product_id,i.approved_base_price_minor,i.promotion_price_minor,
       i.before_version,i.after_version,i.event_id,p.price_minor AS current_price_minor,
       p.publication_version AS current_version,e.event_type,e.payload,e.publication_state
FROM retail_promotion_item i JOIN retail_promotion r ON r.promotion_id=i.promotion_id
JOIN merchant_price_draft d ON d.draft_id=r.source_change_id
JOIN product p ON p.product_id=i.product_id
LEFT JOIN commerce_outbox e ON e.event_id=i.event_id
WHERE CAST(d.operator_subject AS BINARY)=CAST(@merchant_subject AS BINARY)
  AND d.session_id=@merchant_session_id
ORDER BY i.promotion_id,i.product_id;
-- Catalog/family versions and listing/inventory publication events are also in common SQL.
-- A campaign plan has a durable source_change_id; it does not imply a product event or ad spend.
