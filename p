You are a senior DevOps and Flask engineer.

Fix the Telegram webhook integration in this Flask project running behind Nginx + Gunicorn.

Current problems:

* Telegram webhook returns HTTP 302 (redirect to /login)
* Telegram reports: "Wrong response from the webhook: 302 FOUND"
* The endpoint `/telegram/webhook` is being protected by login middleware.
* The server stack is: Nginx → Gunicorn → Flask.
* Project root: `/var/www/finora/supermaxi`

Your task is to automatically fix the project so Telegram webhooks work correctly.

Required fixes:

1. Create a public webhook endpoint in Flask:

Route:
POST /telegram/webhook

Example implementation:

```python
from flask import request, jsonify
import requests
import os

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

@app.route("/telegram/webhook", methods=["POST"])
def telegram_webhook():
    data = request.json
    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "")

    if chat_id and text:
        reply = "Message received"

        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": reply
            }
        )

    return jsonify({"ok": True})
```

2. Ensure this endpoint is NOT protected by authentication.

If the project uses:

* login_required
* before_request login middleware
* authentication decorators

Then exclude the route `/telegram/webhook`.

3. Ensure Flask accepts webhook requests without redirecting to `/login`.

4. Verify Nginx configuration:

The server block must proxy to Gunicorn:

```
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

5. Do NOT apply auth middleware on `/telegram/webhook`.

6. Ensure Gunicorn service runs correctly:

systemctl restart finora

7. Add logging to the webhook so incoming Telegram updates appear in server logs.

8. Make sure the endpoint returns HTTP 200 JSON.

Expected final behaviour:

Telegram
→ POST /telegram/webhook
→ Flask receives update
→ bot replies via Telegram API
→ HTTP 200 returned

Finally print a test command:

curl -X POST https://finora.company/telegram/webhook
