"""جمع بيانات البريد للشركات المسجلة (للنشرة والإعلانات)."""
from __future__ import annotations

from typing import Optional

from flask import g


def _is_valid_email(email: str) -> bool:
    e = (email or "").strip()
    return bool(e) and "@" in e and not e.endswith("@local.invalid")


def iter_marketing_recipients(*, slug: Optional[str] = None) -> list[dict]:
    """
    قائمة مستلمي النشرة.
    slug=None → كل الشركات النشطة الموافقة على النشرة.
    slug='x' → شركة واحدة (إن وُجد بريد).
    """
    from models.core.tenant import Tenant as CoreTenant
    from utils.tenant_registration import get_tenant_registration

    old_tenant = getattr(g, "tenant", None)
    g.tenant = None
    try:
        if slug:
            slug_clean = slug.strip().lower()
            tenant = CoreTenant.query.filter_by(slug=slug_clean).first()
            if not tenant:
                return []
            tenants = [tenant]
        else:
            tenants = CoreTenant.query.filter_by(is_active=True).all()

        recipients: list[dict] = []
        seen_emails: set[str] = set()

        for tenant in tenants:
            reg = get_tenant_registration(tenant.slug, core_tenant=tenant)
            if reg.get("marketing_opt_in") is False:
                continue
            if reg.get("unsubscribed_at"):
                continue
            email = (reg.get("email") or "").strip().lower()
            if not _is_valid_email(email):
                continue
            if email in seen_emails:
                continue
            seen_emails.add(email)
            recipients.append(
                {
                    "slug": tenant.slug,
                    "email": email,
                    "contact_name": reg.get("contact_name") or tenant.name,
                    "company_name": reg.get("company_name") or tenant.name,
                    "unsubscribe_token": reg.get("unsubscribe_token"),
                }
            )
        return recipients
    finally:
        g.tenant = old_tenant


def get_tenant_email_recipient(slug: str) -> Optional[dict]:
    """بريد شركة واحدة (للإرسال الفردي من السوبر أدمن — بغض النظر عن موافقة النشرة)."""
    from models.core.tenant import Tenant as CoreTenant
    from utils.tenant_registration import get_tenant_registration

    slug_clean = (slug or "").strip().lower()
    if not slug_clean:
        return None

    old_tenant = getattr(g, "tenant", None)
    g.tenant = None
    try:
        tenant = CoreTenant.query.filter_by(slug=slug_clean).first()
        if not tenant:
            return None
        reg = get_tenant_registration(tenant.slug, core_tenant=tenant)
        email = (reg.get("email") or "").strip().lower()
        if not _is_valid_email(email):
            return None
        return {
            "slug": tenant.slug,
            "email": email,
            "contact_name": reg.get("contact_name") or tenant.name,
            "company_name": reg.get("company_name") or tenant.name,
            "unsubscribe_token": reg.get("unsubscribe_token"),
        }
    finally:
        g.tenant = old_tenant


def count_marketing_recipients() -> int:
    return len(iter_marketing_recipients())
