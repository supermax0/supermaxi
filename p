You are a senior Python engineer. Fix my Telegram bot conversation logic.

## PROBLEM

The bot is stateless and keeps asking repeated questions (address, quantity, date). It does not remember user answers and breaks the flow.

## GOAL

Implement a proper conversation workflow using:

* Finite State Machine (FSM)
* Persistent storage (SQLite via SQLAlchemy)
* Clear step-based flow per user
* Basic intent handling (cancel / confirm)

## TECH STACK

* Python
* Flask (already used)
* Telegram Bot (assume pyTelegramBotAPI or aiogram – detect from project)
* SQLite (SQLAlchemy ORM)

## REQUIREMENTS

### 1. Create user session model

Add a table:

* id
* user_id (telegram chat id)
* step (string)
* address (string)
* quantity (integer)
* date (string)
* updated_at

### 2. Define steps

Use constants:

* ASK_ADDRESS
* ASK_QUANTITY
* ASK_DATE
* CONFIRM

### 3. Build FSM logic

Implement a handler:

function handle_message(user_id, text):

Flow:

* If no session → create with step = ASK_ADDRESS

* If step == ASK_ADDRESS:
  save address
  move to ASK_QUANTITY
  reply: "كم الكمية؟"

* If step == ASK_QUANTITY:
  parse integer
  save quantity
  move to ASK_DATE
  

* If step == ASK_DATE:
  save date
  move to CONFIRM
  reply with summary:
  العنوان
  الكمية
  

* If step == CONFIRM:
  if user confirms → finalize order
  if user cancels → reset session

### 4. Add intent detection (simple)

Before FSM:

if text contains:

* "الغاء" → reset session
* "نعم" or "تأكيد" → confirm

### 5. Reset logic

Function reset_session(user_id):

* delete or reset step

### 6. Persist everything in DB

NO in-memory dicts.

### 7. Clean architecture

* models.py → DB models
* services/session_manager.py → FSM logic
* bot/handlers.py → telegram handlers

### 8. Fix Arabic responses

Make responses clear and not repetitive.

### 9. Prevent loops

Do NOT re-ask previous answered questions.

### 10. Edge cases

* If user sends random text → respond based on current step
* If quantity invalid → ask again

## OUTPUT

* Full working code
* SQLAlchemy model
* FSM handler
* Telegram integration
* Clean structured files

Do NOT explain. Only write clean production-ready code.
