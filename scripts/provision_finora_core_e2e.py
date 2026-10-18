"""Create (or remove) a throwaway FINORA CORE house tenant + operator for local end-to-end runs.

    py scripts/provision_finora_core_e2e.py setup  <credentials.json>
    py scripts/provision_finora_core_e2e.py cleanup

Development only: refuses to run when FINORA_ENV/FLASK_ENV is production. Credentials are random per run and written
ONLY to the given JSON file (keep it outside the repository). Then start the server with:
    FINORA_CORE_HOUSE_TENANT=fc-e2e-house FINORA_CORE_DEV_LOOPBACK=1 FINORA_ENV=development
"""
from __future__ import annotations

import json
import os
import secrets
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DISABLE_CLINICS_SCHEDULER", "1")
os.environ.setdefault("DISABLE_PUBLISHER_SCHEDULER", "1")
os.environ.setdefault("FINORA_DISABLE_SCHEDULERS", "1")

SLUG = "fc-e2e-house"
OPERATOR = "fc_e2e_admin"
READER = "fc_e2e_reader"

CONVERSATIONS = [
    # name, channel, minutes ago, messages[(direction, sender_type, text, status)]
    ("أحمد علي", "instagram", 2, [
        ("inbound", "customer", "السلام عليكم\nعندي عيادة أسنان وأريد نظام\nكم يكلفني؟", "processed"),
        ("outbound", "ai", "أهلاً دكتور أحمد\nنظام Finora Clinics مخصص لإدارة العيادات السنية.\nكم عدد الأطباء في العيادة؟", "sent"),
        ("inbound", "customer", "لدينا 3 أطباء و 2 موظفين وفرع واحد حالياً", "processed"),
    ]),
    ("د. سارة", "messenger", 9, [
        ("inbound", "customer", "مرحباً، عندي عيادة جلدية", "processed"),
        ("outbound", "ai", "أهلاً دكتورة سارة، هل العيادة فرع واحد أو أكثر؟", "sent"),
        ("inbound", "customer", "كم سعر الباقات؟", "received"),
    ]),
    ("Al-Rashed Co.", "instagram", 45, [
        ("inbound", "customer", "We need a detailed quote for 4 branches", "processed"),
        ("outbound", "ai", "Sure — how many employees work at each branch?", "sent"),
    ]),
]


def _refuse_production() -> None:
    env = (os.environ.get("FINORA_ENV") or os.environ.get("FLASK_ENV") or "development").lower()
    if env == "production":
        raise SystemExit("refusing to provision E2E data in production")


def setup(creds_path: str) -> None:
    _refuse_production()
    from app import app
    from extensions import db
    from extensions_tenant import get_tenant_db_path, init_tenant_db
    from flask import g
    from models.core.super_admin import SuperAdmin
    from modules.ai_sales.models import AISalesChannelAccount, AISalesConversation, AISalesMessage
    from modules.ai_sales.schema import ensure_ai_sales_schema
    from modules.finora_core.models import FcOperatorRole
    from modules.finora_core.store import core_session

    creds = {"server": "http://127.0.0.1:5008", "house": SLUG, "users": {}}
    with app.app_context():
        with core_session() as s:
            for username, role in ((OPERATOR, None), (READER, "read_only")):
                password = "Fc!" + secrets.token_urlsafe(14)
                admin = s.query(SuperAdmin).filter_by(username=username).first() or SuperAdmin(username=username)
                admin.set_password(password)
                s.add(admin)
                s.flush()
                role_row = s.get(FcOperatorRole, admin.id)
                if role:
                    if role_row is None:
                        s.add(FcOperatorRole(superadmin_id=admin.id, role=role))
                    else:
                        role_row.role = role
                creds["users"][username] = password
            s.commit()

        if os.path.exists(get_tenant_db_path(SLUG)):
            os.remove(get_tenant_db_path(SLUG))
        with app.test_request_context():
            g.tenant = SLUG
            init_tenant_db(SLUG)
            ensure_ai_sales_schema()
            from modules.ai_sales.security import encrypt_secret
            from modules.facebook_routing.schema import ensure_facebook_routing_schema

            ensure_facebook_routing_schema()
            app_secret = secrets.token_hex(16)  # 32 hex chars, like a real Meta app secret
            connector = AISalesChannelAccount(channel_type="meta", name="FINORA Meta (e2e)", is_active=True,
                                              connection_status="connected", app_secret_encrypted=encrypt_secret(app_secret),
                                              verify_token_encrypted=encrypt_secret(secrets.token_urlsafe(16)))
            db.session.add(connector)
            db.session.flush()
            channels = {
                "instagram": AISalesChannelAccount(channel_type="instagram", name="FINORA Instagram", is_active=True,
                                                   connection_status="connected", reply_mode="ai",
                                                   parent_channel_id=connector.id, external_account_id="17840000001",
                                                   access_token_encrypted=encrypt_secret("e2e-offline-token")),
                "messenger": AISalesChannelAccount(channel_type="messenger", name="FINORA Facebook", is_active=True,
                                                   connection_status="connected", reply_mode="ai",
                                                   parent_channel_id=connector.id, external_account_id="1000001",
                                                   access_token_encrypted=encrypt_secret("e2e-offline-token")),
            }
            db.session.add_all(channels.values())
            db.session.flush()
            creds["meta"] = {"webhook_key": connector.webhook_key, "app_secret": app_secret,
                             "page_id": "1000001", "instagram_id": "17840000001"}
            now = datetime.utcnow()
            for i, (name, ch, ago, msgs) in enumerate(CONVERSATIONS):
                start = now - timedelta(minutes=ago + len(msgs))
                # A stored picture means the webhook never calls Graph for a profile lookup during tests.
                conv = AISalesConversation(channel_account_id=channels[ch].id, external_contact_id=f"e2e-{i}",
                                           contact_name=name, started_at=start,
                                           contact_profile_picture_url="https://avatar.e2e.invalid/x.png")
                db.session.add(conv)
                db.session.flush()
                for j, (direction, sender, text, status) in enumerate(msgs):
                    at = start + timedelta(minutes=j + 1)
                    db.session.add(AISalesMessage(conversation_id=conv.id, channel_account_id=conv.channel_account_id,
                                                  direction=direction, sender_type=sender, text_content=text,
                                                  status=status, created_at=at, sent_at=at if direction == "outbound" else None))
                    if direction == "inbound":
                        conv.last_customer_message_at = at
                    else:
                        conv.last_business_message_at = at
            db.session.commit()
            g.pop("tenant", None)
    Path(creds_path).write_text(json.dumps(creds, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"provisioned house tenant {SLUG}; credentials written to {creds_path}")


def inject(text: str) -> None:
    """Simulates the Meta webhook persisting a new inbound message for the first conversation."""
    _refuse_production()
    from app import app
    from extensions import db
    from flask import g
    from modules.ai_sales.models import AISalesConversation, AISalesMessage

    with app.test_request_context():
        g.tenant = SLUG
        conv = AISalesConversation.query.filter_by(external_contact_id="e2e-2").first()
        now = datetime.utcnow()
        db.session.add(AISalesMessage(conversation_id=conv.id, channel_account_id=conv.channel_account_id,
                                      direction="inbound", sender_type="customer", text_content=text,
                                      status="handled_by_human", created_at=now))
        conv.last_customer_message_at = now
        db.session.commit()
        g.pop("tenant", None)
    print("injected")


def cleanup() -> None:
    _refuse_production()
    from app import app
    from extensions_tenant import get_tenant_db_path
    from models.core.super_admin import SuperAdmin
    from modules.finora_core.models import FcDesktopSession, FcOperatorRole
    from modules.finora_core.store import core_session

    with app.app_context():
        with core_session() as s:
            for username in (OPERATOR, READER):
                admin = s.query(SuperAdmin).filter_by(username=username).first()
                if admin:
                    s.query(FcDesktopSession).filter_by(superadmin_id=admin.id).delete()
                    s.query(FcOperatorRole).filter_by(superadmin_id=admin.id).delete()
                    s.delete(admin)
            s.commit()
        path = get_tenant_db_path(SLUG)
        if os.path.exists(path):
            from extensions_tenant import _tenant_engines

            engine = _tenant_engines.pop(SLUG, None)
            if engine is not None:
                engine.dispose()
            os.remove(path)
    print("cleaned up FINORA CORE E2E data")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "setup":
        setup(sys.argv[2])
    elif len(sys.argv) >= 3 and sys.argv[1] == "inject":
        inject(sys.argv[2])
    elif len(sys.argv) >= 2 and sys.argv[1] == "cleanup":
        cleanup()
    else:
        raise SystemExit(__doc__)
