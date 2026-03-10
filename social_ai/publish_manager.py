from __future__ import annotations

"""طبقة نشر منشورات SocialPost إلى الحسابات المرتبطة (فيسبوك، إنستجرام، تيك توك)."""

from typing import Iterable

from extensions import db
from models.social_account import SocialAccount
from models.social_post import SocialPost
from models.social_post_platform import SocialPostPlatform
from platforms.facebook import publish_facebook_post
from platforms.instagram import publish_instagram_image
from platforms.tiktok import publish_tiktok_video


def publish_post_to_accounts(post: SocialPost, accounts: Iterable[SocialAccount]) -> None:
    """نشر منشور واحد على مجموعة حسابات وتحديث SocialPostPlatform."""
    for acc in accounts:
        spp = SocialPostPlatform(
            post_id=post.id,
            platform=acc.platform,
            account_id=acc.account_id,
            status="publishing",
        )
        db.session.add(spp)
        db.session.commit()

        try:
            if acc.platform == "facebook":
                result = publish_facebook_post(
                    acc.access_token,
                    post.caption or "",
                    photo_url=post.image_url,
                    video_url=post.video_url,
                    page_id=acc.account_id,
                )
                remote_id = result.get("id") or result.get("post_id") or ""
                spp.status = "published"
                spp.remote_post_id = str(remote_id) if remote_id else None
                spp.error_message = None
                db.session.commit()
            elif acc.platform == "instagram":
                if not post.image_url:
                    raise RuntimeError("منشور إنستجرام يتطلب صورة.")
                remote_id = publish_instagram_image(
                    ig_user_id=acc.account_id,
                    access_token=acc.access_token,
                    image_url=post.image_url,
                    caption=post.caption or "",
                )
                spp.status = "published"
                spp.remote_post_id = remote_id
                spp.error_message = None
                db.session.commit()
            elif acc.platform == "tiktok":
                if not post.video_url:
                    raise RuntimeError("منشور تيك توك يتطلب فيديو.")
                remote_id = publish_tiktok_video(
                    video_url=post.video_url,
                    caption=post.caption or "",
                    access_token=acc.access_token,
                )
                spp.status = "published"
                spp.remote_post_id = remote_id
                spp.error_message = None
                db.session.commit()
            else:
                raise RuntimeError(f"منصة غير مدعومة: {acc.platform}")
        except Exception as e:
            spp.status = "failed"
            spp.error_message = str(e)
            db.session.commit()

