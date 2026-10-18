"""Conversation and provider-neutral tool loop for Finora AI."""
from __future__ import annotations

import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from extensions import db
from modules.finora_ai.context import FinoraAuthContext
from modules.finora_ai.mcp import InProcessMCPClient
from modules.finora_ai.models import FinoraAIConversation, FinoraAIMessage
from modules.finora_ai.providers import ModelRouter, SYSTEM_PROMPT
from modules.finora_ai.settings import current_settings, decrypt_secret
from modules.finora_ai.language import normalize, name_query


class FinoraAIOrchestrator:
    MAX_TOOL_ROUNDS = 8

    def __init__(self, context: FinoraAuthContext):
        self.context = context
        self.settings = current_settings()
        key = decrypt_secret(self.settings.encrypted_api_key) if self.settings.encrypted_api_key else ""
        if not key and self.settings.provider in {"openai", "automatic"}:
            key = os.environ.get("OPENAI_API_KEY", "")
        self.provider = ModelRouter(self.settings, key).select()
        self.mcp = InProcessMCPClient(context)

    def runtime_info(self):
        limited = self.provider.name == "builtin"
        ready = limited or not getattr(self.provider, "url", "").startswith("https://api.openai.com/") or bool(getattr(self.provider, "api_key", ""))
        return {"provider": self.provider.name, "model": getattr(self.provider, "model", None),
                "language_model": not limited, "ready": ready, "read_only": True,
                "notice": "وضع محدود · فعّل نموذجًا لغويًا للفهم المرن" if limited else "نموذج لغوي · مفتاح OpenAI غير مضبوط" if not ready else "نموذج لغوي · بيانات العمل من الأدوات المصرّح بها فقط"}

    def _conversation(self, conversation_id: int | None, page_context: dict | None) -> FinoraAIConversation:
        conversation = None
        if conversation_id:
            conversation = FinoraAIConversation.query.filter_by(
                id=conversation_id, tenant_slug=self.context.tenant_slug, user_id=self.context.user_id
            ).first()
            if conversation is None:
                raise LookupError("Conversation not found")
        if conversation is None:
            conversation = FinoraAIConversation(tenant_slug=self.context.tenant_slug, user_id=self.context.user_id)
            conversation.set_context({})
            db.session.add(conversation)
            db.session.flush()
        context = conversation.get_context()
        safe_page = page_context or {}
        # UI context is a hint only. IDs are still fetched through permission-checked tools.
        for key in ("module", "page", "customer_id", "order_id", "supplier_id", "product_id", "agent_id"):
            if key in safe_page and isinstance(safe_page[key], (str, int)):
                context[key] = safe_page[key]
        conversation.set_context(context)
        return conversation

    def _history(self, conversation: FinoraAIConversation) -> list[dict]:
        rows = (
            FinoraAIMessage.query.filter_by(conversation_id=conversation.id)
            .order_by(FinoraAIMessage.id.desc()).limit(24).all()
        )
        rows.reverse()
        system = self._system_message(conversation)
        history = [
            {"role": row.role, "content": row.content} for row in rows if row.role in {"user", "assistant"}
        ]
        # Character-based estimate; preserve the system policy and latest input.
        # Tool definitions/results are outside this history-only budget.
        budget = max(512, int(getattr(self.settings, "context_size", None) or 8192)) * 3
        while len(history) > 1 and sum(len(item["content"]) for item in history) > budget:
            history.pop(0)
        while len(history) > 1 and history[0]["role"] == "assistant":
            history.pop(0)
        return [{"role": "system", "content": system}] + history

    @staticmethod
    def _system_message(conversation):
        context = {**conversation.get_context(), "current_date": datetime.now(ZoneInfo("Asia/Baghdad")).date().isoformat(), "timezone": "Asia/Baghdad", "week_start": "Sunday"}
        return SYSTEM_PROMPT + "\nFINORA_CONTEXT=" + json.dumps(context, ensure_ascii=False)

    @staticmethod
    def _remember_entity(conversation: FinoraAIConversation, tool_name: str, result: dict) -> None:
        if not result.get("success"):
            if tool_name in {"get_order", "get_latest_order", "search_orders", "search_customer", "search_supplier", "search_delivery_agents", "get_delivery_agent_reports", "get_customer_balance", "get_supplier_balance"}:
                context = conversation.get_context()
                context.pop("active_entity", None)
                context.pop("candidates", None)
                conversation.set_context(context)
            return
        data = result.get("data") or {}
        context = conversation.get_context()
        searches = {"search_customer": ("customer", "customer_id"), "search_supplier": ("supplier", "supplier_id"), "search_delivery_agents": ("agent", "agent_id")}
        if tool_name in searches:
            kind, key = searches[tool_name]
            context["subject"] = kind
            items = data.get("items") or []
            context.pop(key, None)
            context.pop("active_entity", None)
            context.update(candidate_type=kind, candidates=[{"id": row[key], "name": row["name"]} for row in items[:20]])
            if kind == "agent" and context.get("awaiting_agent"):
                context["pending_action"] = "agent_reports"
            if len(items) == 1:
                context.update({key: items[0][key], kind + "_name": items[0]["name"], "active_entity": kind})
            context.pop("awaiting_agent", None)
        if tool_name == "search_customer" and len(data.get("items") or []) == 1:
            item = data["items"][0]
            context.update({"customer_id": item["customer_id"], "customer_name": item["name"]})
        elif tool_name.startswith("get_customer") and data.get("customer_id"):
            context.update({"customer_id": data["customer_id"], "customer_name": data.get("name")})
            context["active_entity"] = "customer"
            context["subject"] = "customer"
            context.pop("candidates", None)
        elif tool_name == "get_supplier_balance" and data.get("supplier_id"):
            context.update(supplier_id=data["supplier_id"], active_entity="supplier")
            context["subject"] = "supplier"
            context.pop("candidates", None)
        elif tool_name == "get_delivery_agent_reports" and data.get("agent_id"):
            context.update(agent_id=data["agent_id"], agent_name=data.get("agent_name"), active_entity="agent")
            context["subject"] = "agent"
            context.pop("candidates", None)
            context.pop("pending_action", None)
            context.pop("awaiting_agent", None)
        elif tool_name == "search_orders":
            context.pop("order_id", None)
            context.pop("active_entity", None)
            if len(data.get("items") or []) == 1:
                context["order_id"] = data["items"][0]["order_id"]
                context["active_entity"] = "order"
        elif tool_name in {"get_order", "get_latest_order"} and data.get("invoice_id"):
            context["order_id"] = data["invoice_id"]
            context["active_entity"] = "order"
            context["subject"] = "order"
            context.pop("candidates", None)
        conversation.set_context(context)

    def run(self, text: str, **kwargs) -> dict:
        result = None
        for event, data in self.run_events(text, **kwargs):
            if event == "done":
                result = data
        return result

    def run_events(self, text: str, *, conversation_id: int | None = None, page_context: dict | None = None, on_status=None):
        conversation = self._conversation(conversation_id, page_context)
        context = conversation.get_context()
        low = normalize(text)
        if any(word in low for word in ("مندوب", "agent")):
            context["subject"] = "agent"
            context.pop("candidates", None)
            if context.get("active_entity") != "agent":
                context.pop("active_entity", None)
            if not name_query(text, "agent") and context.get("active_entity") != "agent":
                context["awaiting_agent"] = True
        elif any(word in low for word in ("طلب", "زبون", "عميل", "مورد", "مبيعات", "مصاريف", "منتج", "مخزون")):
            context.pop("awaiting_agent", None)
            context.pop("pending_action", None)
            context.pop("candidates", None)
        conversation.set_context(context)
        active_conversation_id = int(conversation.id)
        if not conversation.messages:
            conversation.title = text[:100]
        db.session.add(FinoraAIMessage(conversation_id=active_conversation_id, role="user", content=text))
        conversation.updated_at = datetime.utcnow()
        db.session.commit()

        messages = self._history(conversation)
        # Never retain an ORM entity across a streaming yield. Legacy request
        # middleware may expire/remove its session while preparing headers.
        yield "conversation", {"conversation_id": active_conversation_id}
        yield "mode", self.runtime_info()
        tools = self.mcp.list_tools()
        used_tools = []
        final_text = ""
        usage = {}
        for _round in range(self.MAX_TOOL_ROUNDS):
            if not self.runtime_info()["ready"]:
                final_text = "الفهم المرن غير جاهز: مفتاح OpenAI غير مضبوط على الخادم. راجع إعدادات المزوّد والمفتاح؛ لم أقرأ بيانات العمل ولم أرسل طلبًا خارجيًا."
                break
            response = None
            for event, data in self.provider.chat_events(messages, tools):
                if event == "delta":
                    yield "delta", data
                elif event == "response":
                    response = data
            if response is None:
                raise RuntimeError("Provider returned no response")
            usage = response.usage or usage
            if not response.tool_calls:
                final_text = response.content.strip() or "ما توفرت نتيجة مؤكدة من FINORA."
                break
            assistant_calls = []
            for call in response.tool_calls:
                assistant_calls.append({"id": call.id, "type": "function", "function": {"name": call.name, "arguments": json.dumps(call.arguments, ensure_ascii=False)}})
            messages.append({"role": "assistant", "content": response.content or "", "tool_calls": assistant_calls})
            for call in response.tool_calls:
                if on_status:
                    on_status(call.name)
                yield "tool", {"tool": call.name}
                result = self.mcp.call_tool(
                    call.name, call.arguments, conversation_id=active_conversation_id,
                    provider=self.provider.name, model=getattr(self.provider, "model", None),
                )
                used_tools.append({"name": call.name, "success": bool(result.get("success"))})
                conversation = FinoraAIConversation.query.filter_by(id=active_conversation_id,
                    tenant_slug=self.context.tenant_slug, user_id=self.context.user_id).first()
                self._remember_entity(conversation, call.name, result)
                # Newly resolved entities are visible on the next tool round,
                # not just after the user sends another message.
                messages[0]["content"] = self._system_message(conversation)
                messages.append({"role": "tool", "tool_call_id": call.id, "name": call.name, "content": json.dumps(result, ensure_ascii=False, default=str)})
        else:
            final_text = "توقفت بعد الحد الآمن لاستدعاءات الأدوات. حاول تضييق الطلب."

        message = FinoraAIMessage(
            conversation_id=active_conversation_id, role="assistant", content=final_text,
            provider=self.provider.name, model=getattr(self.provider, "model", None),
        )
        message.set_metadata({"tools": used_tools, "usage": usage})
        db.session.add(message)
        conversation = FinoraAIConversation.query.filter_by(id=active_conversation_id,
            tenant_slug=self.context.tenant_slug, user_id=self.context.user_id).first()
        conversation.updated_at = datetime.utcnow()
        db.session.commit()
        yield "done", {
            "success": True,
            "conversation_id": active_conversation_id,
            "message": final_text,
            "tools": used_tools,
            "provider": self.provider.name,
            "model": getattr(self.provider, "model", None),
        }
