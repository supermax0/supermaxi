"""AI provider abstraction (spec §77). Business logic depends on ``AIProvider`` only, never on a vendor SDK."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class ProviderError(RuntimeError):
    """Classified provider failure (AI_PROVIDER_ERROR). ``code`` is safe to log; no prompt or key is included."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class StructuredResult:
    data: Any
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    provider: str | None = None


class AIProvider(Protocol):
    name: str

    def generate_structured(self, *, system: str, user: str, schema: dict, schema_name: str, images: list[str] | None = None) -> StructuredResult: ...


class OpenAIProvider:
    """OpenAI Responses API with strict JSON-schema output, via the existing server-side client (key never leaves)."""

    name = "openai"
    supports_understanding = True
    supports_staged_projects = True
    supports_advice_review = True

    def __init__(self, model: str | None = None, *, api_key: str | None = None, timeout: int = 15):
        self._model = model
        self._api_key = api_key
        self._timeout = timeout

    def _resolve_model(self) -> str:
        if self._model:
            return self._model
        from modules.ai_sales.openai_service import settings_for_profile

        return settings_for_profile(None).chat_model

    def generate_structured(self, *, system: str, user: str, schema: dict, schema_name: str, images: list[str] | None = None) -> StructuredResult:
        from modules.ai_sales.openai_service import AIServiceError, create_response

        model = self._resolve_model()
        try:
            response = create_response(
                api_key=self._api_key, timeout=self._timeout, max_retries=0, store=False,
                model=model,
                input=[{"role": "system", "content": system}, {"role": "user", "content":
                       [{"type": "input_text", "text": user}, *[{"type": "input_image", "image_url": image} for image in images]] if images else user}],
                text={"format": {"type": "json_schema", "name": schema_name, "schema": schema, "strict": True}},
                **({"reasoning": {"effort": "high" if schema_name in {"finora_message_understanding", "finora_project_advice", "finora_project_advice_review"}
                                  else "medium" if schema_name == "finora_project_repair" and set(schema.get("properties", {})) == {"workflows"}
                                  else "low" if schema_name in {"finora_project_scope", "finora_project_workflows", "finora_project_repair"} else "medium"}}
                   if model.startswith(("gpt-5", "gpt-6")) else {}),
            )
        except AIServiceError as exc:
            cause = exc.__cause__
            code = ("timeout" if cause and type(cause).__name__ == "APITimeoutError" else
                    "connection_failed" if cause and type(cause).__name__ == "APIConnectionError" else exc.code)
            raise ProviderError(code, "AI provider request failed") from exc
        raw = getattr(response, "output_text", "") or ""
        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise ProviderError("invalid_json", "AI provider returned non-JSON output") from exc
        usage = getattr(response, "usage", None)
        return StructuredResult(
            data=data,
            model=model,
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
            provider="cloud",
        )


class OllamaProvider:
    """Ollama runs on the FINORA server, with the same validated plan schema as the cloud provider."""

    name = "ollama"
    supports_understanding = True
    supports_staged_projects = True
    supports_advice_review = True

    def __init__(self, url: str, model: str, timeout: int = 15):
        from ..settings import validate_local_url

        self.url = validate_local_url(url)
        self.model = model
        self.timeout = timeout

    def generate_structured(self, *, system: str, user: str, schema: dict, schema_name: str, images: list[str] | None = None) -> StructuredResult:
        import requests

        try:
            response = requests.post(
                f"{self.url}/api/chat",
                json={"model": self.model, "stream": False, "format": schema,
                      "messages": [{"role": "system", "content": system}, {"role": "user", "content": user,
                                    **({"images": [image.split(",", 1)[1] for image in images]} if images else {})}],
                      "options": {"temperature": 0.2, "num_predict": 1800}},
                timeout=self.timeout, allow_redirects=False,
            )
        except requests.RequestException:
            raise ProviderError("local_unreachable", "تعذر الاتصال بـ Ollama على خادم FINORA") from None
        if response.status_code != 200:
            code = "local_model_missing" if response.status_code == 404 else "local_request_failed"
            raise ProviderError(code, "تحقق من تشغيل Ollama وتثبيت النموذج المطلوب")
        try:
            payload = response.json()
            data = json.loads(payload["message"]["content"])
            return StructuredResult(data=data, model=self.model,
                                    input_tokens=int(payload.get("prompt_eval_count") or 0),
                                    output_tokens=int(payload.get("eval_count") or 0), provider="local")
        except (ValueError, TypeError, KeyError):
            raise ProviderError("invalid_json", "النموذج المحلي لم يرجع إجابة صالحة") from None


class HybridProvider:
    """Local first; cloud fallback is used only when the operator explicitly selects hybrid."""

    name = "hybrid"
    supports_understanding = True
    supports_staged_projects = True
    supports_advice_review = True

    def __init__(self, local: AIProvider, cloud: AIProvider | None):
        self.local, self.cloud = local, cloud

    def generate_structured(self, **kwargs) -> StructuredResult:
        import jsonschema

        try:
            result = self.local.generate_structured(**kwargs)
            jsonschema.validate(result.data, kwargs["schema"])
            return result
        except (ProviderError, jsonschema.ValidationError):
            if self.cloud is None:
                raise ProviderError("cloud_key_missing", "النموذج المحلي غير متاح والمفتاح السحابي غير مضبوط") from None
            return self.cloud.generate_structured(**kwargs)


_override: AIProvider | None = None


class RequestProvider:
    """Share a permanent-failure latch across stages/timeouts of ONE customer message only."""

    STOP_CODES = {"insufficient_quota", "invalid_api_key", "authentication_error", "cloud_key_missing", "openai_key_missing", "permission_denied", "model_not_found"}

    def __init__(self, provider, state=None):
        self.inner = provider
        self.state = state if state is not None else {}

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def generate_structured(self, **kwargs):
        if self.state.get("blocked"):
            raise ProviderError(self.state["blocked"], "Provider unavailable for this request")
        try:
            result = self.inner.generate_structured(**kwargs)
            self.state.pop("lastError", None)
            return result
        except ProviderError as exc:
            self.state["lastError"] = exc.code
            if exc.code in self.STOP_CODES:
                self.state["blocked"] = exc.code
            raise

    def for_review(self, result):
        return (cloud_fallback(self) if result.provider == "cloud" else None) or self


def cloud_fallback(provider):
    """Keep the request's failure state when a later stage uses the already-selected cloud."""
    if isinstance(provider, RequestProvider):
        cloud = cloud_fallback(provider.inner)
        return RequestProvider(cloud, provider.state) if cloud else None
    return provider.cloud if isinstance(provider, HybridProvider) else None


def with_timeout(provider: AIProvider, seconds: int) -> AIProvider:
    """Separate bounded budget for a multi-page project brief; ordinary replies retain configured timeouts."""
    if isinstance(provider, RequestProvider):
        return RequestProvider(with_timeout(provider.inner, seconds), provider.state)
    if isinstance(provider, OpenAIProvider):
        return OpenAIProvider(provider._model, api_key=provider._api_key, timeout=seconds)
    if isinstance(provider, OllamaProvider):
        return OllamaProvider(provider.url, provider.model, min(seconds, 8))
    if isinstance(provider, HybridProvider):
        return HybridProvider(with_timeout(provider.local, seconds), with_timeout(provider.cloud, seconds) if provider.cloud else None)
    return provider


def get_provider() -> AIProvider | None:
    """The configured provider, or ``None`` when no AI key is configured (the brain then runs its rules planner)."""
    if _override is not None:
        return _override
    from ..settings import cloud_key, read_settings
    from ..store import core_session

    with core_session() as s:
        config = read_settings(s)
        if config["provider"] == "off":
            return None
        if config["provider"] == "local":
            return OllamaProvider(config["localUrl"], config["localModel"], config["timeoutSeconds"])
        key = cloud_key(s)
    cloud = OpenAIProvider(config["cloudModel"] or None, api_key=key, timeout=config["timeoutSeconds"]) if key else None
    if config["provider"] == "hybrid":
        return HybridProvider(OllamaProvider(config["localUrl"], config["localModel"], config["timeoutSeconds"]), cloud)
    return cloud


def set_provider_for_tests(provider: AIProvider | None) -> None:
    global _override
    _override = provider
