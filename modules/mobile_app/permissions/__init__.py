"""Permission and feature-flag defaults for mobile social commerce."""
from __future__ import annotations

# Seeded into tenant Permission table (schema_guard).
MOBILE_APP_PERMISSIONS: list[tuple[str, str]] = [
    ("mobile_app.view_dashboard", "عرض لوحة تطبيق الهاتف"),
    ("mobile_app.manage_videos", "إدارة فيديوهات تطبيق الهاتف"),
    ("mobile_app.publish_videos", "نشر فيديوهات تطبيق الهاتف"),
    ("mobile_app.delete_videos", "حذف فيديوهات تطبيق الهاتف"),
    ("mobile_app.manage_comments", "إدارة تعليقات تطبيق الهاتف"),
    ("mobile_app.reply_comments", "الرد على تعليقات التطبيق"),
    ("mobile_app.manage_users", "إدارة مستخدمي التطبيق"),
    ("mobile_app.block_users", "حظر مستخدمي التطبيق"),
    ("mobile_app.manage_rewards", "إدارة نقاط ومكافآت التطبيق"),
    ("mobile_app.adjust_points", "تعديل نقاط مستخدمي التطبيق"),
    ("mobile_app.manage_discounts", "إدارة خصومات التطبيق"),
    ("mobile_app.manage_coupons", "إدارة كوبونات التطبيق"),
    ("mobile_app.send_notifications", "إرسال إشعارات تطبيق الهاتف"),
    ("mobile_app.manage_ai", "إدارة Finora AI للتطبيق"),
    ("mobile_app.manage_design", "إدارة هوية تطبيق الهاتف"),
    ("mobile_app.view_analytics", "عرض تحليلات تطبيق الهاتف"),
    ("mobile_app.manage_settings", "إعدادات تطبيق الهاتف"),
]

DEFAULT_FEATURE_FLAGS: dict[str, bool] = {
    "mobile_app_enabled": True,
    "video_feed_enabled": True,
    "comments_enabled": True,
    "video_sharing_enabled": True,
    "rewards_enabled": True,
    "coupons_enabled": True,
    "ai_assistant_enabled": True,
    "guest_checkout_enabled": True,
    "user_generated_content_enabled": False,
    "referrals_enabled": False,
    "push_notifications_enabled": True,
    "personalized_feed_enabled": False,
}
