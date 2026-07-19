# Finora Sales AI OpenAI Upgrade

## Scope

This upgrade extends the existing Flask, SQLAlchemy, Jinja, and vanilla JavaScript
Sales AI module. It does not create a second inbox, webhook, tenant model, or Meta
connector.

## Architecture

The existing flow remains the source of truth:

```text
Meta/WhatsApp webhook
  -> tenant and channel lookup
  -> idempotent message insert
  -> atomic processing claim
  -> conversation context and live Finora product tools
  -> OpenAI Responses API
  -> persisted outbound message
  -> channel-specific Meta sender
```

OpenAI access is centralized in `modules/ai_sales/openai_service.py`. The same
server-side `OPENAI_API_KEY` is used for text, transcription, speech, and
Realtime. The key is never returned to the browser or written to application
logs.

## Model Configuration

Environment defaults:

```env
OPENAI_CHAT_MODEL=gpt-5.6-sol
OPENAI_TTS_MODEL=gpt-4o-mini-tts
OPENAI_TRANSCRIBE_MODEL=gpt-4o-mini-transcribe
OPENAI_REALTIME_MODEL=gpt-realtime-2.1
OPENAI_TTS_VOICE=coral
OPENAI_TTS_FORMAT=mp3
```

Each setting can be overridden in the active Sales AI profile without a code
change. The production project exposes the explicit `gpt-5.6-sol` model ID and
`gpt-realtime-2.1`; those concrete IDs avoid relying on an unavailable alias.

## Text Messages

1. The webhook stores the inbound message and returns quickly.
2. A background worker atomically changes the status to `processing`.
3. The agent receives 6-30 recent messages, persisted customer facts, the sales
   stage, and live product results.
4. The Responses API returns strict structured output.
5. Product IDs, prices, sizes, and order actions are validated against Finora.
6. The reply is stored, sent through the page/phone-specific token, and updated
   with the Meta delivery status.

Quick greetings and acknowledgements use the deterministic fast path. Product
selection and sales decisions use the configured reasoning level.

## Voice Messages

```text
Meta audio attachment
  -> authenticated download
  -> MIME and 25 MB size validation
  -> tenant-scoped storage
  -> gpt-4o-mini-transcribe
  -> persisted transcript and diagnostic metadata
  -> normal grounded sales pipeline
  -> gpt-4o-mini-tts with Iraqi speech instructions
  -> Messenger URL send or WhatsApp media upload
```

Reply modes are `text_only`, `match_customer`, `text_and_voice`, and
`voice_only`. If a voice-only delivery fails, Finora sends the generated text as
a fallback. Generated speech includes a short AI-voice disclosure.

## Duplicate Prevention and Human Takeover

- External message IDs are unique per channel.
- A conditional database update claims an inbound message once.
- Meta echo events are stored as employee messages and are not reprocessed as
  customer messages.
- Explicit takeover pauses AI indefinitely.
- A normal employee reply pauses AI for the configured number of minutes, then
  automatically resumes only when that page is configured for AI replies.
- Messages received during takeover are stored and marked handled by a human;
  no AI response is sent.

## Realtime Foundation

`POST /ai-sales/api/openai/realtime/session` mints a short-lived client secret
from the server. The permanent API key never reaches the browser. This prepares
the OpenAI side of WebRTC calls. A production live-call feature still needs the
Meta Calling/SIP or WebRTC transport, call consent rules, signaling, and human
transfer UI.

## Settings and Diagnostics

The Sales AI settings include independent model fields, voice, output format,
voice instructions, context size, audio size, human pause duration, response
delay, escalation policy, and reply mode. The built-in TTS tester is rate
limited, tenant-scoped, authenticated, and deletes expired test files.

Health endpoint:

```text
GET /ai-sales/api/openai/health?validate=1
```

The response exposes model names and connection state only, never credentials.

## Test Commands

```powershell
venv\Scripts\python.exe -m py_compile config.py modules\ai_sales\openai_service.py modules\ai_sales\agent.py modules\ai_sales\media.py modules\ai_sales\engine.py modules\ai_sales\routes.py
node --check static\js\ai-sales-inbox.js
venv\Scripts\python.exe -m pytest tests\test_ai_sales_foundation.py tests\test_ai_sales_intelligence.py tests\test_ai_sales_openai_service.py -q
```

Production verification should additionally test one Messenger text, one
Messenger voice note, one WhatsApp text, and one WhatsApp voice note on pages
whose reply mode is AI.

## Operational Risks

- Live calls are not complete until a channel transport is integrated.
- STT quality depends on recording clarity and dialect; failed transcripts are
  retained as structured diagnostics and transferred to a human path.
- Meta media URLs can expire, so downloaded media is stored in tenant-scoped
  storage.
- Model availability and account permissions must be checked after key or
  project changes through the health endpoint.
- The configured `uploads/ai_sales` directory must remain writable by the
  production service user.
