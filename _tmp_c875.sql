SELECT id, direction, message_type,
       substr(COALESCE(text_content,''),1,120) AS txt,
       substr(COALESCE(transcription,''),1,80) AS tr,
       substr(COALESCE(failure_message,''),1,160) AS fail,
       status, created_at
FROM ai_sales_message
WHERE conversation_id=875
ORDER BY id DESC LIMIT 20;

SELECT id, substr(COALESCE(context_json,''),1,800) AS ctx
FROM ai_sales_conversation WHERE id=875;
