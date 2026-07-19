"""Facebook Page post/comment synchronization and grounded reply workflow."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from threading import Thread
from typing import Any

from flask import current_app, g

from extensions import db

from .channels import MetaMessagingClient, MetaMessagingClientError, outbound_message_id
from .models import (
    AISalesAgentProfile,
    AISalesSocialComment,
    AISalesSocialPost,
    AISalesUsageLog,
)
from .openai_service import AIServiceError, create_response, get_openai_api_key, settings_for_profile
from .product_tools import search_products


def _parse_graph_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)) or str(value).isdigit():
        try:
            return datetime.utcfromtimestamp(int(value))
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
        return (
            parsed.replace(tzinfo=None)
            if parsed.tzinfo is None
            else parsed.astimezone(timezone.utc).replace(tzinfo=None)
        )
    except ValueError:
        return None


def _post_media(row: dict) -> tuple[str, str]:
    if row.get("full_picture"):
        return str(row["full_picture"]), "image"
    attachments = ((row.get("attachments") or {}).get("data") or [])
    first = attachments[0] if attachments else {}
    media = first.get("media") or {}
    image = media.get("image") or {}
    url = str(image.get("src") or first.get("url") or "")
    return url, str(first.get("type") or row.get("status_type") or "")


def upsert_social_post(channel, row: dict) -> AISalesSocialPost:
    external_id = str(row.get("id") or "").strip()
    if not external_id:
        raise ValueError("Meta post id is required")
    post = AISalesSocialPost.query.filter_by(
        channel_account_id=channel.id,
        external_post_id=external_id,
    ).first()
    if not post:
        post = AISalesSocialPost(channel_account_id=channel.id, external_post_id=external_id)
        db.session.add(post)
    media_url, media_type = _post_media(row)
    summary = ((row.get("comments") or {}).get("summary") or {})
    post.message = str(row.get("message") or post.message or "")
    post.story = str(row.get("story") or post.story or "")
    post.permalink_url = str(row.get("permalink_url") or post.permalink_url or "")
    post.media_url = media_url or post.media_url
    post.media_type = media_type or post.media_type
    post.comments_count = int(summary.get("total_count") or post.comments_count or 0)
    post.published_at = _parse_graph_datetime(row.get("created_time")) or post.published_at
    post.last_synced_at = datetime.utcnow()
    post.set_raw_payload(row)
    return post


def upsert_social_comment(channel, post: AISalesSocialPost, row: dict) -> tuple[AISalesSocialComment, bool]:
    external_id = str(row.get("id") or row.get("external_comment_id") or "").strip()
    if not external_id:
        raise ValueError("Meta comment id is required")
    comment = AISalesSocialComment.query.filter_by(
        channel_account_id=channel.id,
        external_comment_id=external_id,
    ).first()
    created = comment is None
    if not comment:
        comment = AISalesSocialComment(
            post_id=post.id,
            channel_account_id=channel.id,
            external_comment_id=external_id,
        )
        db.session.add(comment)
    author = row.get("from") or {}
    picture = ((author.get("picture") or {}).get("data") or {}).get("url")
    attachment = row.get("attachment") or {}
    comment.post_id = post.id
    comment.parent_external_comment_id = str(
        ((row.get("parent") or {}).get("id") or row.get("parent_external_comment_id") or "")
    ) or None
    # Meta can omit `from` when older Page/Reel comments are fetched even when
    # the token has the content permissions. Never erase identity that arrived
    # earlier through the real-time feed webhook.
    comment.external_user_id = str(author.get("id") or row.get("external_user_id") or comment.external_user_id or "") or None
    comment.user_name = str(author.get("name") or row.get("user_name") or comment.user_name or "")[:180] or None
    comment.user_picture_url = str(picture or comment.user_picture_url or "") or None
    comment.message = str(row.get("message") or comment.message or "")
    comment.attachment_url = str(
        (attachment.get("url") if isinstance(attachment, dict) else "")
        or row.get("attachment_url")
        or comment.attachment_url
        or ""
    ) or None
    comment.permalink_url = str(row.get("permalink_url") or comment.permalink_url or "") or None
    comment.commented_at = _parse_graph_datetime(row.get("created_time")) or comment.commented_at or datetime.utcnow()
    comment.set_raw_payload(row.get("raw") or row)
    return comment, created


def sync_page_posts(channel, *, post_limit: int = 30, comments_limit: int = 100) -> dict:
    client = MetaMessagingClient(channel)
    posts = client.list_page_posts(limit=post_limit)
    post_count = 0
    comment_count = 0
    new_comment_ids: list[int] = []
    for row in posts:
        post = upsert_social_post(channel, row)
        db.session.flush()
        post_count += 1
        for comment_row in client.list_post_comments(post.external_post_id, limit=comments_limit):
            author_id = str(((comment_row.get("from") or {}).get("id") or ""))
            if author_id and author_id == str(channel.external_account_id or ""):
                continue
            comment, created = upsert_social_comment(channel, post, comment_row)
            if (
                not created
                and comment.status == "processing"
                and comment.updated_at
                and comment.updated_at < datetime.utcnow() - timedelta(minutes=5)
            ):
                comment.status = "new"
                comment.failure_message = "أعيدت للانتظار بعد توقف معالجة سابقة"
            db.session.flush()
            comment_count += int(created)
            if created:
                new_comment_ids.append(comment.id)
    channel.last_sync_at = datetime.utcnow()
    db.session.commit()
    return {
        "posts": post_count,
        "new_comments": comment_count,
        "new_comment_ids": new_comment_ids,
    }


def _reply_text(comment: AISalesSocialComment) -> tuple[str, str, int, int]:
    post = comment.post
    query = " ".join(filter(None, (post.message, post.story, comment.message)))
    products = search_products(query, limit=3)
    product_rows = [
        {
            "name": row.get("name") or row.get("official_name"),
            "price": row.get("sale_price") or row.get("price"),
            "warranty": row.get("warranty"),
            "delivery": row.get("delivery"),
            "colors": row.get("colors") or [],
            "selling_points": row.get("selling_points") or [],
        }
        for row in products
    ]
    profile = AISalesAgentProfile.query.filter_by(is_active=True).order_by(AISalesAgentProfile.id.asc()).first()
    model = settings_for_profile(profile).chat_model
    key = get_openai_api_key()
    post_text = (post.message or post.story or "منشور بدون وصف")[:2500]
    if not key:
        if product_rows:
            product = product_rows[0]
            price = int(product.get("price") or 0)
            price_text = f" بسعر {price:,} د.ع" if price else ""
            return (
                f"هلا {comment.user_name or ''}، بخصوص المنتج بالمنشور: {product.get('name')}{price_text}. "
                "شنو المعلومة اللي تحب تعرفها عنه؟"
            ).strip(), model, 0, 0
        return "هلا بيك، وصلتني رسالتك بخصوص هذا المنشور. شنو المعلومة اللي تحب تعرفها عنه؟", model, 0, 0

    prompt = (
        "أنت موظف مبيعات عراقي في محادثة خاصة بدأت من تعليق على منشور فيسبوك. "
        "جاوب سؤال الزبون مباشرة وبلهجة عراقية طبيعية، بجمل قصيرة ومن دون كلام قالب. "
        "اعتمد فقط على سياق المنشور وبيانات المنتجات الحية أدناه. لا تخترع سعراً أو مواصفة أو توفر. "
        "إذا سأل عن السعر وكان منتج مطابق موجوداً، اذكر السعر مباشرة. "
        "إذا لم يتضح المنتج، اربط سؤالك بالمنشور واسأل سؤال توضيح واحد فقط. "
        "لا تقل تم الرد على الخاص لأن الرسالة نفسها خاصة، ولا تذكر أنك ذكاء اصطناعي. "
        "اكتب الرد فقط، بحد أقصى 500 حرف.\n\n"
        f"اسم الزبون: {comment.user_name or 'الزبون'}\n"
        f"نص المنشور: {post_text}\n"
        f"تعليق الزبون: {comment.message or '[مرفق فقط]'}\n"
        f"بيانات المنتجات الحية: {json.dumps(product_rows, ensure_ascii=False, default=str)}"
    )
    response = create_response(
        api_key=key,
        model=model,
        instructions="أرجع نصاً عربياً واحداً فقط من دون JSON أو Markdown.",
        input=prompt,
        max_output_tokens=260,
        store=False,
        timeout=18,
    )
    text = str(getattr(response, "output_text", "") or "").strip()
    if not text:
        raise AIServiceError("empty_comment_reply", "response", "لم يتم توليد رد للتعليق")
    usage = getattr(response, "usage", None)
    return (
        text[:2000],
        model,
        int(getattr(usage, "input_tokens", 0) or 0),
        int(getattr(usage, "output_tokens", 0) or 0),
    )


def process_social_comment(comment_id: int, *, force: bool = False) -> None:
    comment = AISalesSocialComment.query.get(comment_id)
    if not comment or not comment.channel or not comment.post:
        return
    channel = comment.channel
    if not force and (
        not channel.is_active
        or not channel.comments_enabled
        or comment.status in {"processing", "replied", "ignored"}
    ):
        return
    if comment.external_user_id and comment.external_user_id == str(channel.external_account_id or ""):
        comment.status = "ignored"
        comment.failure_message = "Page-authored comment"
        db.session.commit()
        return

    comment.status = "processing"
    comment.failure_message = None
    db.session.commit()
    try:
        client = MetaMessagingClient(channel)
        try:
            post_row = client.get_post(comment.post.external_post_id)
            upsert_social_post(channel, post_row)
            comment_row = client.get_comment(comment.external_comment_id)
            upsert_social_comment(channel, comment.post, comment_row)
            db.session.commit()
        except MetaMessagingClientError as exc:
            current_app.logger.info("Meta comment enrichment skipped: %s", exc)

        if not force and channel.comments_reply_mode != "ai":
            comment.status = "new"
            db.session.commit()
            return

        private_text, model, input_tokens, output_tokens = _reply_text(comment)
        comment.private_reply_text = private_text
        if channel.comments_private_reply:
            if comment.private_reply_status != "sent":
                try:
                    private_body = client.private_reply_to_comment(comment.external_comment_id, private_text)
                    comment.private_reply_external_id = outbound_message_id(private_body)
                    comment.private_reply_status = "sent"
                except MetaMessagingClientError as exc:
                    if exc.meta_code != 10900:
                        raise
                    # A Facebook comment accepts only one private reply. Treat
                    # Meta's "Activity already replied to" as an idempotent
                    # success so retries can still publish the public notice.
                    comment.private_reply_external_id = comment.private_reply_external_id or "meta:already-replied"
                    comment.private_reply_status = "sent"
                # Persist the private delivery before attempting the public acknowledgement.
                # A public Graph failure must never cause a duplicate private reply on retry.
                db.session.commit()
            public_text = (channel.comments_public_text or "تم الرد على الخاص").strip()[:300]
            comment.public_reply_text = public_text
            if comment.public_reply_status != "sent":
                public_body = client.reply_to_comment(comment.external_comment_id, public_text)
                comment.public_reply_external_id = outbound_message_id(public_body)
                comment.public_reply_status = "sent"
        else:
            public_body = client.reply_to_comment(comment.external_comment_id, private_text)
            comment.public_reply_text = private_text
            comment.public_reply_external_id = outbound_message_id(public_body)
            comment.public_reply_status = "sent"
        comment.status = "replied"
        comment.replied_at = datetime.utcnow()
        db.session.add(AISalesUsageLog(
            provider="openai",
            model=model,
            operation="meta_comment_reply",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        ))
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        comment = AISalesSocialComment.query.get(comment_id)
        if comment:
            comment.status = "failed"
            if comment.private_reply_status != "sent":
                comment.private_reply_status = "failed"
            if comment.public_reply_status != "sent":
                comment.public_reply_status = "failed"
            comment.failure_message = str(exc)[:1500]
            db.session.commit()
        current_app.logger.exception("Meta comment reply failed comment_id=%s", comment_id)


def dispatch_social_comment_async(app, tenant_slug: str, comment_id: int, *, force: bool = False) -> None:
    def runner() -> None:
        with app.app_context():
            g.tenant = tenant_slug
            from .schema import ensure_ai_sales_schema

            ensure_ai_sales_schema()
            process_social_comment(comment_id, force=force)

    Thread(
        target=runner,
        name=f"ai-sales-comment-{tenant_slug}-{comment_id}",
        daemon=True,
    ).start()
