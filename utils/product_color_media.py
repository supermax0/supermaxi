"""Validate and publish per-color photos without touching variant balances."""
import json
import re
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from flask import current_app
from PIL import Image, ImageOps, UnidentifiedImageError

from extensions import db
from models.product_color_image import ProductColorImage

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024


def _upload_folder():
    return Path(current_app.root_path) / "static" / "uploads" / "products"


def color_image_map(product_id):
    from utils.product_color_service import _shared_catalog_product_ids
    ProductColorImage.__table__.create(db.session.connection(), checkfirst=True)
    ids = _shared_catalog_product_ids(product_id)
    rows = ProductColorImage.query.filter(ProductColorImage.product_id.in_(ids)).order_by(ProductColorImage.id.desc()).all()
    images = {}
    for row in rows:
        images.setdefault(row.color_name, row.image_url)
    return images


def apply_color_images(product, raw_actions, files, created_files):
    from utils.product_color_service import ProductColorError, _shared_catalog_product_ids, get_product_colors
    try:
        actions = json.loads(raw_actions)
    except (TypeError, ValueError):
        raise ProductColorError("قائمة صور الألوان غير صحيحة")
    if not isinstance(actions, list) or not actions or len(actions) > 40:
        raise ProductColorError("قائمة صور الألوان غير صحيحة")
    from flask import request
    if request.content_length and request.content_length > MAX_TOTAL_BYTES + 256 * 1024:
        raise ProductColorError("مجموع الصور لا يتجاوز 32 ميغابايت")
    available = {row["name"] for row in get_product_colors(product.id)}
    seen = set()
    used_fields = set()
    prepared = []
    total_bytes = 0
    for action in actions:
        if not isinstance(action, dict) or set(action) not in ({"name", "field"}, {"name", "remove"}):
            raise ProductColorError("بيانات صورة اللون غير صحيحة")
        name = action.get("name")
        field = action.get("field")
        remove = action.get("remove") is True
        if not isinstance(name, str) or name not in available or name in seen or (remove and field):
            raise ProductColorError("اختر لوناً موجوداً لكل صورة ولا تكرر اللون")
        seen.add(name)
        if remove:
            prepared.append((name, None))
            continue
        if not isinstance(field, str) or not re.fullmatch(r"color_image_[0-9]{1,2}", field) or field in used_fields:
            raise ProductColorError("حقل صورة اللون غير صحيح")
        used_fields.add(field)
        upload = files.get(field)
        if not upload or not upload.filename or len(files.getlist(field)) != 1:
            raise ProductColorError("لم تصل صورة اللون؛ اختر الصورة مجدداً")
        data = upload.read(MAX_IMAGE_BYTES + 1)
        total_bytes += len(data)
        if len(data) > MAX_IMAGE_BYTES or total_bytes > MAX_TOTAL_BYTES:
            raise ProductColorError("الصورة لا تتجاوز 8 ميغابايت، ومجموع الصور لا يتجاوز 32 ميغابايت")
        try:
            image = Image.open(BytesIO(data))
            if image.format not in {"JPEG", "PNG", "WEBP", "GIF"} or image.width * image.height > 25_000_000:
                raise ValueError("unsupported image")
            image.load()
            image = ImageOps.exif_transpose(image)
            image.thumbnail((2048, 2048))
            image = image.convert("RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB")
            output = BytesIO()
            image.save(output, format="WEBP", quality=88, method=4)
            prepared.append((name, output.getvalue()))
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
            raise ProductColorError("صورة اللون غير صالحة؛ استخدم PNG أو JPG أو WEBP")
    ProductColorImage.__table__.create(db.session.connection(), checkfirst=True)
    ids = _shared_catalog_product_ids(product.id)
    owner_id = min(ids)
    folder = _upload_folder()
    for name, data in prepared:
        # One shared photo for the family, independent of branch-local prices/stock.
        ProductColorImage.query.filter(ProductColorImage.product_id.in_(ids), ProductColorImage.color_name == name).delete(synchronize_session="fetch")
        if data is None:
            continue
        folder.mkdir(parents=True, exist_ok=True)
        filename = f"color_{uuid4().hex}.webp"
        path = folder / filename
        created_files.append(path)
        path.write_bytes(data)
        db.session.add(ProductColorImage(product_id=owner_id, color_name=name, image_url=f"/static/uploads/products/{filename}"))
    db.session.flush()


def cleanup_color_uploads(created_files):
    for path in created_files:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            current_app.logger.exception("cannot remove uncommitted color photo")
