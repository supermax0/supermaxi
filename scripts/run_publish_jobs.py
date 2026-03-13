from datetime import datetime

from app import app, db  # type: ignore[import]
from models.tenant import Tenant  # type: ignore[import]
from services.publish_scheduler import process_pending_jobs_for_tenant


def main() -> None:
    """تشغيل مهام النشر المستحقة لكل مستأجر.

    يُستدعى عادةً من systemd timer على السيرفر.
    """

    with app.app_context():
        now = datetime.utcnow()
        tenants = Tenant.query.all()
        total = 0
        for t in tenants:
            slug = getattr(t, "slug", None)
            if not slug:
                continue
            count = process_pending_jobs_for_tenant(slug, now=now, limit=50)
            total += count
        db.session.remove()
        print(f"Processed {total} publish jobs at {now.isoformat()}")


if __name__ == "__main__":
    main()

