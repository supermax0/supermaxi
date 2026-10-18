"""Server-owned channel roles. Customer text/model output cannot choose a channel's authority."""
import re

SOCIAL_CHANNELS = {"instagram", "messenger"}
ACCOUNT_ACTIONS = {"create_lead", "recommend_plan", "start_trial", "request_discount", "configure_tenant"}
PROJECT_ACTIONS = {"publish_project_quote", "confirm_project_deposit"}


def allowed(channel, action):
    if action in ACCOUNT_ACTIONS:
        return channel in SOCIAL_CHANNELS
    if action in PROJECT_ACTIONS:
        return channel == "telegram"
    return action == "handoff_human"


def redirect(channel, language="ar-iq"):
    if channel == "telegram":
        return ("FINORA account creation and company setup are handled through our Instagram or Facebook messages. This bot is for custom website and app consultations."
                if language == "en" else "إنشاء حسابات وشركات فينورا وتجهيزها يتم من رسائل إنستغرام أو فيسبوك. هذا البوت مخصص لاستشارة وتخطيط المواقع والتطبيقات اللي تريد نطوّرها إلك.")
    return ("Custom website and app consultations are available through FINORA's Telegram bot. Here we help you choose and set up your FINORA company account."
            if language == "en" else "استشارة وتخطيط موقع أو تطبيق مخصّص صارت من بوت فينورا بالتلكرام. هنا نساعدك تختار وتجهّز حساب شركتك داخل فينورا.")


def require(s, customer, ref, action):
    """Re-read actual, customer-owned house conversation at approval/execution boundaries."""
    from .models import FcConversationCustomer
    from .tools import ToolError
    from ..store import use_house
    from ..conversations import get_conversation
    link = s.get(FcConversationCustomer, str(ref)) if ref is not None else None
    if not link or link.customer_id != customer.id or not re.fullmatch(r"\d+", str(ref)):
        raise ToolError("CHANNEL_SCOPE", "الإجراء يحتاج محادثة موثقة تخص العميل نفسه")
    with use_house():
        conversation = get_conversation(int(ref))
        channel = conversation.channel.channel_type if conversation and conversation.channel else None
    if not allowed(channel, action):
        raise ToolError("CHANNEL_ROLE", redirect(channel))
