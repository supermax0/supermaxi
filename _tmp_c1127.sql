SELECT id, direction, substr(COALESCE(text_content,''),1,160) AS txt, status, created_at
FROM ai_sales_message WHERE conversation_id=1127 ORDER BY id DESC LIMIT 20;
SELECT substr(COALESCE(context_json,''),1,1000) FROM ai_sales_conversation WHERE id=1127;
