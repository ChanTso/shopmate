SET SESSION time_zone = '+00:00';
SELECT product_id,name,description,price_minor,currency,publication_version,publication_state,stock_quantity,available
FROM product ORDER BY product_id;
SELECT publication_generation FROM catalog_metadata WHERE singleton_id=1;
SELECT product_id,family_id,content,option_values,metadata_version,display_order FROM retail_product_metadata ORDER BY product_id;
SELECT family_id,name,description,content,options,metadata_version,display_order FROM retail_product_family ORDER BY family_id;
