SELECT id, direction, message_type,
       substr(COALESCE(text_content,''),1,180) AS txt,
       status, created_at
FROM ai_sales_message
WHERE conversation_id = (
  SELECT id FROM ai_sales_conversation
  WHERE contact_name LIKE '%الماني%' OR external_contact_id LIKE '%28124125610513550%'
  ORDER BY id DESC LIMIT 1
)
ORDER BY id DESC LIMIT 20;

SELECT id, substr(COALESCE(context_json,''),1,900)
FROM ai_sales_conversation
WHERE contact_name LIKE '%الماني%' OR external_contact_id LIKE '%28124125610513550%'
ORDER BY id DESC LIMIT 1;
