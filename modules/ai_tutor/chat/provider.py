"""Provider abstraction. The chat works without any provider; a provider only improves understanding."""
from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "أنت مساعد تعليمي داخل Finora Clinics. "
    "مسموح لك فقط باستخدام الـ actions والـ tutorials والصفحات والصلاحيات الموجودة في الـ Registry المرسل لك. "
    "ممنوع اختراع زر أو صفحة أو ميزة. إذا المعلومة غير موجودة صرّح بذلك. "
    "استخدم عربية واضحة ويفضل فهم اللهجة العراقية. لا تعطِ نصائح طبية؛ دورك شرح استخدام النظام فقط. "
    "أجب بـ JSON فقط."
)


class ProviderError(RuntimeError):
    """Any provider failure (network, timeout, malformed answer). The service falls back deterministically."""


class TutorAIProvider(ABC):
    """Contract for cloud OR local models. All inputs are already privacy-filtered by the service."""

    name = "abstract"

    @abstractmethod
    def classify_intent(self, payload: dict) -> dict | None:
        """Return {"intent": <registry id>, "confidence": 0..1, "candidates": [ids]?} or None."""

    def generate_explanation(self, payload: dict, intent_id: str) -> str | None:
        """Optional friendlier wording for a registry explanation. Default: no rewrite."""
        return None

    def clarify(self, payload: dict, candidate_ids: list[str]) -> str | None:
        """Optional short clarification question about registry candidates. Default: no rewrite."""
        return None


class NullProvider(TutorAIProvider):
    name = "none"

    def classify_intent(self, payload: dict) -> dict | None:
        return None


class OpenAIProvider(TutorAIProvider):
    """Chat-completions classifier (JSON mode). Never receives PHI; failures raise ProviderError."""

    name = "openai"

    def __init__(self, api_key: str, model: str | None = None, timeout: float = 8.0):
        self.api_key = api_key
        self.model = model or os.environ.get("AI_TUTOR_OPENAI_MODEL", "gpt-4o-mini")
        self.timeout = timeout

    def _complete(self, instruction: str, payload: dict) -> dict:
        try:
            from openai import OpenAI

            client = OpenAI(api_key=self.api_key, timeout=self.timeout, max_retries=0)
            result = client.chat.completions.create(
                model=self.model,
                response_format={"type": "json_object"},
                temperature=0,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": instruction + "\n" + json.dumps(payload, ensure_ascii=False)},
                ],
            )
            return json.loads(result.choices[0].message.content or "{}")
        except Exception as exc:  # network, timeout, quota, bad JSON: all become a clean fallback
            raise ProviderError(str(exc)) from exc

    def classify_intent(self, payload: dict) -> dict | None:
        data = self._complete(
            'اختر أنسب intent من القائمة intents للرسالة message. أعد {"intent": id أو null, "confidence": رقم بين 0 و1, '
            '"candidates": [ids]}. إذا لا يوجد تطابق واضح أعد intent=null.', payload)
        return data if isinstance(data, dict) else None


def get_provider() -> TutorAIProvider:
    """AI_TUTOR_PROVIDER=openai + OPENAI_API_KEY enables the cloud provider; anything else = no provider."""
    if os.environ.get("AI_TUTOR_PROVIDER", "").strip().lower() == "openai":
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        if key:
            return OpenAIProvider(key)
        log.warning("AI_TUTOR_PROVIDER=openai but OPENAI_API_KEY is empty; using deterministic mode")
    return NullProvider()
