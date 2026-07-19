.headers on
.mode line
SELECT id, sales_stage, substr(coalesce(context_json,''),1,1000) AS ctx FROM ai_sales_conversation WHERE id=1091;
SELECT id, direction, substr(coalesce(text_content,''),1,160) AS txt, status, created_at FROM ai_sales_message WHERE conversation_id=1091 ORDER BY id DESC LIMIT 12;
SELECT p.id, p.name, p.sale_price, p.quantity, pp.marketing_name, pp.selling_points_json, pp.aliases_json, pp.ai_notes FROM product p LEFT JOIN ai_sales_product_profile pp ON pp.product_id=p.id WHERE p.active=1 AND (p.name LIKE '%7%' OR p.name LIKE '%٧%') AND (p.name LIKE '%ثلاج%' OR p.name LIKE '%براد%');
