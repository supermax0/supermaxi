Build a production-ready WhatsApp Broadcast System using Flask.

FEATURES:

1. Database (SQLite):
Create table "customers":
- id (int)
- name (text)
- phone (text)
- tag (text)
- last_sent (datetime)

2. Message Template:
Use WhatsApp approved template system:
Example:
"مرحبا {{1}} 👋 لدينا عرض خاص على {{2}} بسعر {{3}}"

3. Scheduler:
- Run every 1 hour
- Send messages to max 1000 users per batch
- Respect rate limits (sleep between messages)

4. Personalization:
Replace:
{{1}} → name
{{2}} → product
{{3}} → price

5. Sending Function:
POST to:
https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages

Headers:
Authorization: Bearer WHATSAPP_TOKEN

Body:
{
  "messaging_product": "whatsapp",
  "to": phone,
  "type": "template",
  "template": {
    "name": "promo_template",
    "language": { "code": "ar" },
    "components": [
      {
        "type": "body",
        "parameters": [
          {"type": "text", "text": name},
          {"type": "text", "text": product},
          {"type": "text", "text": price}
        ]
      }
    ]
  }
}

6. Rate Limiting:
- sleep 0.1 sec between messages
- handle errors gracefully

7. Logging:
- Print success/fail
- Save last_sent timestamp

8. Scheduler Implementation:
Use APScheduler:
- run every 1 hour

9. API Endpoint:
Create route:
POST /send_ads_manual
to trigger sending manually

10. Project structure:

/project
  app.py
  scheduler.py
  db.py

11. Make code clean and modular

12. Add instructions to run the app
