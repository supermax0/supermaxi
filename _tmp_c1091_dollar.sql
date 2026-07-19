SELECT id, direction, message_type,
       substr(COALESCE(text_content,''),1,160) AS txt,
       status, created_at
FROM ai_sales_message
WHERE conversation_id=1091
ORDER BY id DESC LIMIT 25;

SELECT substr(COALESCE(context_json,''),1,1200) FROM ai_sales_conversation WHERE id=1091;
