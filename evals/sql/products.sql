SET SESSION time_zone = '+00:00';
SELECT product_id, name, description, price_minor, currency,
       publication_version, publication_state, stock_quantity, available
FROM product
WHERE product_id IN (
  'shopmate-fixture-coffee', 'shopmate-fixture-tea', 'shopmate-fixture-mug',
  'shopmate-fixture-tote', 'shopmate-fixture-cocoa-usd',
  'shopmate-fixture-unavailable', 'shopmate-fixture-seckill'
)
ORDER BY product_id;
SELECT publication_generation FROM catalog_metadata WHERE singleton_id = 1;
