"""Product image pipeline: validate, keep the original, make WebP display sizes, never replace verified photos.

Only images the company uploads go through here (its own photos or files it has the right to use). Remote URLs are
not fetched by the server (no SSRF surface); an imported https link is stored as-is with «unverified» rights.
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path

from flask import current_app, g

from extensions import db
from modules.catalog import service
from modules.catalog.models import CatalogMedia, CatalogProduct

MAX_BYTES = 8 * 1024 * 1024
FORMATS = {"JPEG", "PNG", "WEBP"}
SIZES = {"display": 1200, "thumb": 400}


def _root() -> Path:
    tenant = str(getattr(g, "tenant", "") or "shared")
    safe = "".join(ch for ch in tenant if ch.isalnum() or ch in "-_") or "shared"
    return Path(current_app.static_folder) / "uploads" / "catalog" / safe


def save_upload(entry_id: int, raw: bytes, *, role: str = "", rights: str = "own_photo") -> CatalogMedia:
    from PIL import Image, ImageOps

    service.ensure_tables()
    entry = db.session.get(CatalogProduct, int(entry_id))
    if entry is None:
        raise service.CatalogError("المنتج غير موجود في الكتالوج", "not_found", 404)
    if not raw or len(raw) > MAX_BYTES:
        raise service.CatalogError("الصورة فارغة أو أكبر من 8 ميغابايت")
    try:
        probe = Image.open(io.BytesIO(raw))
        probe.verify()  # detects truncated / fake files
        image = Image.open(io.BytesIO(raw))
    except Exception:
        raise service.CatalogError("الملف ليس صورة صالحة") from None
    if image.format not in FORMATS:
        raise service.CatalogError("الصيغ المقبولة: JPG أو PNG أو WebP")
    if image.width < 300 or image.height < 300:
        raise service.CatalogError("الصورة صغيرة جداً (أقل من 300 بكسل) — لن تكون واضحة في المتجر")
    digest = hashlib.sha256(raw).hexdigest()[:24]
    folder = _root() / str(entry.id)
    folder.mkdir(parents=True, exist_ok=True)
    if any(m.url.endswith(f"/{digest}.webp") for m in CatalogMedia.query.filter_by(catalog_product_id=entry.id).all()):
        raise service.CatalogError("هذه الصورة مضافة لهذا المنتج مسبقاً", "duplicate", 409)
    ext = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}[image.format]
    (folder / f"{digest}.orig.{ext}").write_bytes(raw)  # the original is always kept
    image = ImageOps.exif_transpose(image).convert("RGBA" if image.mode in ("RGBA", "LA", "P") else "RGB")
    for label, edge in SIZES.items():
        copy = image.copy()
        copy.thumbnail((edge, edge))
        name = f"{digest}.webp" if label == "display" else f"{digest}.{label}.webp"
        copy.save(folder / name, "WEBP", quality=82, method=4)
    static_root = Path(current_app.static_folder)
    url = "/static/" + (folder / f"{digest}.webp").relative_to(static_root).as_posix()
    order = CatalogMedia.query.filter_by(catalog_product_id=entry.id).count()
    media = CatalogMedia(catalog_product_id=entry.id, url=url, image_role=(role or "")[:20] or None,
                         usage_rights=(rights or "own_photo")[:40], verification_status="pending", sort_order=order)
    db.session.add(media)
    db.session.flush()
    return media


def remove(entry_id: int, media_id: int) -> None:
    media = CatalogMedia.query.filter_by(id=int(media_id), catalog_product_id=int(entry_id)).first()
    if media is None:
        raise service.CatalogError("الصورة غير موجودة", "not_found", 404)
    if media.verification_status == "verified":
        raise service.CatalogError("صورة مؤكدة — ألغِ تأكيدها أولاً قبل حذفها", "verified", 409)
    db.session.delete(media)  # files stay on disk (an audit trail of what was shown)


def verify(entry_id: int, media_id: int, verified: bool) -> CatalogMedia:
    media = CatalogMedia.query.filter_by(id=int(media_id), catalog_product_id=int(entry_id)).first()
    if media is None:
        raise service.CatalogError("الصورة غير موجودة", "not_found", 404)
    if verified and (media.usage_rights or "") in ("", "unverified"):
        raise service.CatalogError("لا تُؤكَّد صورة قبل تحديد حق استخدامها", "rights", 409)
    media.verification_status = "verified" if verified else "pending"
    return media
