"""Explicit live connectivity check. Never prints keys or business data."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
import requests
from modules.finora_ai.providers import OpenAICompatibleProvider


def main():
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        print("OpenAI connectivity: no configured key")
        return 1
    provider = OpenAICompatibleProvider(endpoint="https://api.openai.com/v1", model="gpt-4.1-mini", api_key=key, timeout=30)
    try:
        response = provider.chat([{"role": "user", "content": "Reply with OK only. Connectivity test without business data."}], [])
        print("OpenAI connectivity: SUCCESS" if response.content else "OpenAI connectivity: EMPTY")
        print("Token usage:", response.usage)
        return 0
    except requests.HTTPError as error:
        print("OpenAI connectivity HTTP status:", error.response.status_code)
        try:
            print("Provider error code:", (error.response.json().get("error") or {}).get("code"))
        except ValueError:
            pass
    except Exception as error:
        print("OpenAI connectivity error:", type(error).__name__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
