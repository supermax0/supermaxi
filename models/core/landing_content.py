from datetime import datetime
import json

from extensions import db


def _json_loads(value, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _json_dumps(value):
    return json.dumps(value or {}, ensure_ascii=False)


class LandingMixin:
    id = db.Column(db.Integer, primary_key=True)
    scope = db.Column(db.String(20), default="draft", index=True, nullable=False)
    published_at = db.Column(db.DateTime, nullable=True)
    published_by = db.Column(db.Integer, nullable=True)
    last_edited_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def is_published(self):
        return self.scope == "published"


class LandingPageSettings(LandingMixin, db.Model):
    __tablename__ = "landing_page_settings"

    site_name = db.Column(db.String(120), default="Finora Cloud")
    page_title = db.Column(db.String(255), default="")
    page_subtitle = db.Column(db.Text, default="")
    default_language = db.Column(db.String(10), default="ar")
    logo_url = db.Column(db.String(500), default="/static/IMG_0200.png")
    favicon_url = db.Column(db.String(500), default="/static/IMG_0200.png")
    primary_color = db.Column(db.String(20), default="#2563eb")
    secondary_color = db.Column(db.String(20), default="#0f766e")
    accent_color = db.Column(db.String(20), default="#7c3aed")
    background_color = db.Column(db.String(20), default="#f7f9fc")
    text_color = db.Column(db.String(20), default="#101828")
    font_family = db.Column(db.String(120), default="Tajawal")
    whatsapp_number = db.Column(db.String(60), default="")
    whatsapp_enabled = db.Column(db.Boolean, default=True)
    whatsapp_message = db.Column(db.String(255), default="مرحبا، أريد أعرف أكثر عن نظام فينورا.")
    contact_email = db.Column(db.String(160), default="")
    login_url = db.Column(db.String(500), default="/login")
    trial_url = db.Column(db.String(500), default="/signup?plan=free&billing=monthly")
    demo_booking_url = db.Column(db.String(500), default="#contact")
    is_active = db.Column(db.Boolean, default=True)

    def to_dict(self):
        return {
            "id": self.id,
            "scope": self.scope,
            "site_name": self.site_name,
            "page_title": self.page_title,
            "page_subtitle": self.page_subtitle,
            "default_language": self.default_language,
            "logo_url": self.logo_url,
            "favicon_url": self.favicon_url,
            "primary_color": self.primary_color,
            "secondary_color": self.secondary_color,
            "accent_color": self.accent_color,
            "background_color": self.background_color,
            "text_color": self.text_color,
            "font_family": self.font_family,
            "whatsapp_number": self.whatsapp_number,
            "whatsapp_enabled": bool(self.whatsapp_enabled),
            "whatsapp_message": self.whatsapp_message,
            "contact_email": self.contact_email,
            "login_url": self.login_url,
            "trial_url": self.trial_url,
            "demo_booking_url": self.demo_booking_url,
            "is_active": bool(self.is_active),
        }


class LandingSection(LandingMixin, db.Model):
    __tablename__ = "landing_sections"

    section_key = db.Column(db.String(80), index=True, nullable=False)
    section_type = db.Column(db.String(80), index=True, nullable=False)
    title = db.Column(db.String(255), default="")
    subtitle = db.Column(db.String(255), default="")
    description = db.Column(db.Text, default="")
    content_json = db.Column(db.Text, default="{}")
    image_url = db.Column(db.String(500), default="")
    video_url = db.Column(db.String(500), default="")
    button_primary_text = db.Column(db.String(120), default="")
    button_primary_url = db.Column(db.String(500), default="")
    button_secondary_text = db.Column(db.String(120), default="")
    button_secondary_url = db.Column(db.String(500), default="")
    sort_order = db.Column(db.Integer, default=0)
    is_visible = db.Column(db.Boolean, default=True)
    animation_type = db.Column(db.String(80), default="fade-up")
    background_style = db.Column(db.String(120), default="")

    def to_dict(self):
        return {
            "id": self.id,
            "scope": self.scope,
            "section_key": self.section_key,
            "section_type": self.section_type,
            "title": self.title,
            "subtitle": self.subtitle,
            "description": self.description,
            "content": _json_loads(self.content_json, {}),
            "image_url": self.image_url,
            "video_url": self.video_url,
            "button_primary_text": self.button_primary_text,
            "button_primary_url": self.button_primary_url,
            "button_secondary_text": self.button_secondary_text,
            "button_secondary_url": self.button_secondary_url,
            "sort_order": self.sort_order,
            "is_visible": bool(self.is_visible),
            "animation_type": self.animation_type,
            "background_style": self.background_style,
        }


class LandingMedia(db.Model):
    __tablename__ = "landing_media"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(160), default="")
    media_type = db.Column(db.String(40), default="image")
    file_url = db.Column(db.String(500), nullable=False)
    thumbnail_url = db.Column(db.String(500), default="")
    alt_text = db.Column(db.String(255), default="")
    caption = db.Column(db.String(255), default="")
    usage_key = db.Column(db.String(100), default="")
    file_size = db.Column(db.Integer, default=0)
    mime_type = db.Column(db.String(120), default="")
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "media_type": self.media_type,
            "file_url": self.file_url,
            "thumbnail_url": self.thumbnail_url,
            "alt_text": self.alt_text,
            "caption": self.caption,
            "usage_key": self.usage_key,
            "file_size": self.file_size,
            "mime_type": self.mime_type,
            "is_active": bool(self.is_active),
        }


class LandingFeature(LandingMixin, db.Model):
    __tablename__ = "landing_features"

    title = db.Column(db.String(180), nullable=False)
    description = db.Column(db.Text, default="")
    icon = db.Column(db.String(80), default="fa-solid fa-circle-check")
    image_url = db.Column(db.String(500), default="")
    feature_key = db.Column(db.String(80), default="")
    sort_order = db.Column(db.Integer, default=0)
    is_visible = db.Column(db.Boolean, default=True)

    def to_dict(self):
        return {
            "id": self.id,
            "scope": self.scope,
            "title": self.title,
            "description": self.description,
            "icon": self.icon,
            "image_url": self.image_url,
            "feature_key": self.feature_key,
            "sort_order": self.sort_order,
            "is_visible": bool(self.is_visible),
        }


class LandingModule(LandingMixin, db.Model):
    __tablename__ = "landing_modules"

    name = db.Column(db.String(180), nullable=False)
    short_description = db.Column(db.String(255), default="")
    long_description = db.Column(db.Text, default="")
    icon = db.Column(db.String(80), default="fa-solid fa-layer-group")
    screenshot_url = db.Column(db.String(500), default="")
    sort_order = db.Column(db.Integer, default=0)
    is_visible = db.Column(db.Boolean, default=True)

    def to_dict(self):
        return {
            "id": self.id,
            "scope": self.scope,
            "name": self.name,
            "short_description": self.short_description,
            "long_description": self.long_description,
            "icon": self.icon,
            "screenshot_url": self.screenshot_url,
            "sort_order": self.sort_order,
            "is_visible": bool(self.is_visible),
        }


class LandingPricingPlan(LandingMixin, db.Model):
    __tablename__ = "landing_pricing_plans"

    name = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(80), index=True, nullable=False)
    price = db.Column(db.Float, default=0)
    currency = db.Column(db.String(20), default="$")
    billing_period = db.Column(db.String(40), default="شهري")
    description = db.Column(db.String(255), default="")
    features_json = db.Column(db.Text, default="[]")
    limits_json = db.Column(db.Text, default="{}")
    cta_text = db.Column(db.String(120), default="ابدأ الآن")
    cta_url = db.Column(db.String(500), default="/signup")
    badge_text = db.Column(db.String(120), default="")
    is_popular = db.Column(db.Boolean, default=False)
    is_visible = db.Column(db.Boolean, default=True)
    sort_order = db.Column(db.Integer, default=0)

    def to_dict(self):
        return {
            "id": self.id,
            "scope": self.scope,
            "name": self.name,
            "slug": self.slug,
            "price": self.price,
            "currency": self.currency,
            "billing_period": self.billing_period,
            "description": self.description,
            "features": _json_loads(self.features_json, []),
            "limits": _json_loads(self.limits_json, {}),
            "cta_text": self.cta_text,
            "cta_url": self.cta_url,
            "badge_text": self.badge_text,
            "is_popular": bool(self.is_popular),
            "is_visible": bool(self.is_visible),
            "sort_order": self.sort_order,
        }


class LandingFAQ(LandingMixin, db.Model):
    __tablename__ = "landing_faqs"

    question = db.Column(db.String(255), nullable=False)
    answer = db.Column(db.Text, default="")
    category = db.Column(db.String(80), default="عام")
    sort_order = db.Column(db.Integer, default=0)
    is_visible = db.Column(db.Boolean, default=True)

    def to_dict(self):
        return {
            "id": self.id,
            "scope": self.scope,
            "question": self.question,
            "answer": self.answer,
            "category": self.category,
            "sort_order": self.sort_order,
            "is_visible": bool(self.is_visible),
        }


class LandingTestimonial(LandingMixin, db.Model):
    __tablename__ = "landing_testimonials"

    customer_name = db.Column(db.String(160), nullable=False)
    customer_title = db.Column(db.String(160), default="")
    company_name = db.Column(db.String(160), default="")
    quote = db.Column(db.Text, default="")
    avatar_url = db.Column(db.String(500), default="")
    rating = db.Column(db.Integer, default=5)
    is_visible = db.Column(db.Boolean, default=True)
    sort_order = db.Column(db.Integer, default=0)

    def to_dict(self):
        return {
            "id": self.id,
            "scope": self.scope,
            "customer_name": self.customer_name,
            "customer_title": self.customer_title,
            "company_name": self.company_name,
            "quote": self.quote,
            "avatar_url": self.avatar_url,
            "rating": self.rating,
            "is_visible": bool(self.is_visible),
            "sort_order": self.sort_order,
        }


class LandingCTA(LandingMixin, db.Model):
    __tablename__ = "landing_ctas"

    label = db.Column(db.String(120), nullable=False)
    url = db.Column(db.String(500), default="")
    cta_type = db.Column(db.String(40), default="trial")
    placement_key = db.Column(db.String(80), default="hero")
    is_visible = db.Column(db.Boolean, default=True)
    sort_order = db.Column(db.Integer, default=0)

    def to_dict(self):
        return {
            "id": self.id,
            "scope": self.scope,
            "label": self.label,
            "url": self.url,
            "cta_type": self.cta_type,
            "placement_key": self.placement_key,
            "is_visible": bool(self.is_visible),
            "sort_order": self.sort_order,
        }


class LandingSEO(LandingMixin, db.Model):
    __tablename__ = "landing_seo"

    meta_title = db.Column(db.String(255), default="")
    meta_description = db.Column(db.String(500), default="")
    meta_keywords = db.Column(db.String(500), default="")
    og_title = db.Column(db.String(255), default="")
    og_description = db.Column(db.String(500), default="")
    og_image_url = db.Column(db.String(500), default="")
    twitter_title = db.Column(db.String(255), default="")
    twitter_description = db.Column(db.String(500), default="")
    twitter_image_url = db.Column(db.String(500), default="")
    canonical_url = db.Column(db.String(500), default="")
    robots = db.Column(db.String(80), default="index,follow")
    schema_json = db.Column(db.Text, default="{}")

    def to_dict(self):
        return {
            "id": self.id,
            "scope": self.scope,
            "meta_title": self.meta_title,
            "meta_description": self.meta_description,
            "meta_keywords": self.meta_keywords,
            "og_title": self.og_title,
            "og_description": self.og_description,
            "og_image_url": self.og_image_url,
            "twitter_title": self.twitter_title,
            "twitter_description": self.twitter_description,
            "twitter_image_url": self.twitter_image_url,
            "canonical_url": self.canonical_url,
            "robots": self.robots,
            "schema": _json_loads(self.schema_json, {}),
        }


class LandingAuditLog(db.Model):
    __tablename__ = "landing_audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, nullable=True)
    action = db.Column(db.String(80), nullable=False)
    entity_type = db.Column(db.String(80), nullable=False)
    entity_id = db.Column(db.Integer, nullable=True)
    old_value_json = db.Column(db.Text, default="{}")
    new_value_json = db.Column(db.Text, default="{}")
    ip_address = db.Column(db.String(80), default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "admin_id": self.admin_id,
            "action": self.action,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "old_value": _json_loads(self.old_value_json, {}),
            "new_value": _json_loads(self.new_value_json, {}),
            "ip_address": self.ip_address,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
