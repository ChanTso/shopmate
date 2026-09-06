SET SESSION time_zone = '+00:00';
SELECT draft_id,kind,operator_subject,session_id,currency,state,items,payload,result,created_at,resolved_at
FROM merchant_price_draft WHERE operator_subject='shopmate-fixture-operator' AND session_id=@session_id ORDER BY created_at,draft_id;
