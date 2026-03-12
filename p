You are a senior DevOps + Python engineer.

Fix the Telegram bot configuration in this Flask project.

Environment:

* Flask app behind Nginx and Gunicorn
* Systemd service name: finora
* Project path: /var/www/finora/supermaxi
* Telegram webhook already works but the logs show:
  "BOT_TOKEN not set; cannot send reply"
  "OpenAI API key not set; skipping AI reply"

Your task:

1. Ensure the Telegram bot reads environment variables:

   * BOT_TOKEN
   * OPENAI_API_KEY

2. Modify the systemd service file:
   /etc/systemd/system/finora.service

   Add inside [Service]:

   Environment="BOT_TOKEN=<telegram_bot_token>"
   Environment="OPENAI_API_KEY=<openai_api_key>"

3. Ensure the Flask code loads these variables using:

   import os
   BOT_TOKEN = os.getenv("BOT_TOKEN")
   OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

4. If they are missing, log a warning.

5. After updating the service file run:

   sudo systemctl daemon-reload
   sudo systemctl restart finora

6. Add logging so incoming Telegram updates appear in logs.

7. Ensure the webhook handler sends replies using:

   https://api.telegram.org/bot{BOT_TOKEN}/sendMessage

Expected result:

Telegram message
→ POST /telegram/webhook
→ Flask receives update
→ AI reply generated
→ Telegram message sent successfully.

Output the commands needed to restart the service and verify logs.
