"""One-shot: see why Messenger profile pics fail. Prints no secrets."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, "/var/www/finora/supermaxi")
os.chdir("/var/www/finora/supermaxi")

from app import app  # noqa: E402


def main():
    import requests
    from modules.publisher.models.publisher_page import PublisherPage
    from modules.publisher.services.token_utils import decrypt_token
    from modules.ai_sales.models import AISalesChannelAccount, AISalesConversation

    with app.app_context():
        from flask import g

        g.tenant = os.environ.get("FINORA_LOCAL_TENANT") or "super"
        pages = PublisherPage.query.all()
        print("publisher_pages", len(pages))
        for row in pages[:8]:
            token = ""
            try:
                token = decrypt_token(row.page_token) if row.page_token else ""
            except Exception as exc:
                print("decrypt_fail", row.page_id, type(exc).__name__)
            print("page", row.page_id, (row.page_name or "")[:40], "token", bool(token), "len", len(token))

        channels = AISalesChannelAccount.query.filter(
            AISalesChannelAccount.channel_type.in_(("messenger", "facebook"))
        ).all()
        print("channels", len(channels))
        for ch in channels[:8]:
            print("channel", ch.page_id, (ch.name or "")[:40], "tok", bool(ch.access_token_encrypted))

        convs = (
            AISalesConversation.query.filter(AISalesConversation.external_contact_id.isnot(None))
            .order_by(AISalesConversation.id.desc())
            .limit(3)
            .all()
        )
        if not convs:
            print("no_convos")
            return
        channel = convs[0].channel
        fb_id = (channel.page_id if channel else "") or ""
        page = next((r for r in pages if str(r.page_id) == str(fb_id)), None)
        print("convo_page", fb_id, (channel.name if channel else ""), "publisher", bool(page))
        token = ""
        if page and page.page_token:
            token = decrypt_token(page.page_token) or ""
        if not token and channel and channel.access_token_encrypted:
            try:
                token = decrypt_token(channel.access_token_encrypted) or ""
            except Exception:
                token = ""
        print("token_ok", bool(token), "len", len(token))
        if not token:
            print("no_token")
            return
        print("convos", len(convs))
        for conv in convs:
            psid = conv.external_contact_id
            print("try", psid, (conv.contact_name or "")[:30], "stored_pic", bool(conv.contact_profile_picture_url))
            for fields in ("name,profile_pic", "first_name,last_name,profile_pic", "name,picture"):
                r = requests.get(
                    f"https://graph.facebook.com/v19.0/{psid}",
                    params={"fields": fields, "access_token": token},
                    timeout=10,
                )
                body = r.json()
                err = (body.get("error") or {}).get("message") if isinstance(body, dict) else ""
                pic = body.get("profile_pic") if isinstance(body, dict) else ""
                print(" fields", fields, "http", r.status_code, "pic", bool(pic), "err", (err or "")[:160])
            r2 = requests.get(
                f"https://graph.facebook.com/v19.0/{psid}/picture",
                params={"type": "large", "redirect": "false", "access_token": token},
                timeout=10,
            )
            meta = r2.json()
            print(" picture", r2.status_code, str(meta)[:220])
            if pic:
                img = requests.get(
                    pic,
                    headers={"User-Agent": "Mozilla/5.0", "Accept": "image/*"},
                    timeout=10,
                )
                print(" fetch_pic", img.status_code, img.headers.get("Content-Type"), len(img.content or b""))


if __name__ == "__main__":
    main()
