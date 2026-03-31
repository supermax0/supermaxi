Build a full Flask-based backend and simple frontend page for a WhatsApp Webhook system.

Requirements:

1. Backend (Flask):
- Create a Flask app with a route "/webhook"
- Support both GET and POST methods

GET:
- Read "hub.verify_token" and "hub.challenge"
- If token matches VERIFY_TOKEN, return challenge
- Else return error

POST:
- Receive incoming WhatsApp messages (JSON)
- Print incoming data in console
- Extract sender phone number and message text
- Automatically reply with a simple message using WhatsApp Cloud API

2. Environment variables:
- VERIFY_TOKEN = "12345"
- WHATSAPP_TOKEN = "YOUR_ACCESS_TOKEN"
- PHONE_NUMBER_ID = "YOUR_PHONE_ID"

3. Send reply function:
- Use requests to send POST to:
  https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages
- Send simple text reply:
  "هلا 👋 تم استلام رسالتك"

4. Frontend:
- Create a simple HTML page (index.html)
- Show:
  - Status: Webhook Running
  - Button: "Test Webhook"
- Button sends GET request to /webhook test endpoint

5. Project structure:

/project
  app.py
  templates/
    index.html

6. Use Flask render_template

7. Add logging for debugging

8. Run on port 5000

9. Make code clean and production-ready

10. Include instructions to run the app
