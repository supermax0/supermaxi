You are a senior Python backend engineer.

Build a fully working Telegram AI bot integration for my Flask project.

The system must work immediately without manual fixes.
If something is missing in the project, automatically create it.

Tech stack:

* Python
* Flask
* Requests
* Telegram Bot API
* OpenAI API (for AI replies)

Project goal:
Create an AI bot that listens to Telegram messages and automatically replies using AI.

System architecture:

Telegram User
→ Telegram Bot API
→ Flask Webhook `/telegram/webhook`
→ Workflow Node `telegram_listener`
→ AI Agent (generate reply)
→ Node `telegram_send`
→ Telegram user receives reply

Tasks you must implement:

1. Create Flask route:

`/telegram/webhook`

It must receive POST updates from Telegram.

Example payload:
{
"message":{
"chat":{"id":12345},
"text":"hello"
}
}

2. Extract:

chat_id
message_text

3. Pass message_text to the AI agent.

AI prompt:

"You are a helpful assistant for a tech store.
Reply in Arabic.
User message: {message_text}"

4. Generate AI response using OpenAI API.

5. Send reply to Telegram using:

https://api.telegram.org/bot{BOT_TOKEN}/sendMessage

Payload:

{
"chat_id": chat_id,
"text": ai_reply
}

6. Create these modules if missing:

/telegram_bot
listener.py
sender.py
ai_agent.py
webhook.py

7. Add environment variables support:

BOT_TOKEN
OPENAI_API_KEY

8. Add automatic webhook setup function:

`/telegram/setup-webhook`

When visited it calls:

https://api.telegram.org/bot{BOT_TOKEN}/setWebhook

Webhook URL:

https://YOURDOMAIN/telegram/webhook

9. Add logging for debugging.

10. Prevent crashes if message has no text.

11. Return Telegram response:

{ "status":"ok" }

12. Provide full working code including:

Flask routes
Telegram sender function
AI reply generator
Webhook setup

13. Add a test endpoint:

`/telegram/test`

When accessed it sends a message to a test chat.

14. Ensure the system runs instantly with:

python app.py

15. Add comments explaining each part.

Final result:

User sends message to Telegram bot →
Flask receives webhook →
AI generates response →
Bot replies automatically.
