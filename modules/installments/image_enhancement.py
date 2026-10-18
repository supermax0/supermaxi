from __future__ import annotations

import json
import math
import os
from pathlib import Path
from statistics import median
from uuid import uuid4


PROCESSING_VERSION = "storefront-v2-transparent"
CANVAS_SIZE = 1400
CANVAS_COLOR = (0, 0, 0, 0)
MAX_INPUT_PIXELS = 60_000_000


class StorefrontImageError(ValueError):
    """Raised when an uploaded storefront image cannot be safely processed."""


def _marker_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.storefront-enhanced.json")


def _signature(path: Path) -> dict[str, int]:
    stat = path.stat()
    return {"size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns)}


def is_storefront_image_enhanced(path: Path) -> bool:
    marker = _marker_path(path)
    if not path.is_file() or not marker.is_file():
        return False
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
        return (
            payload.get("version") == PROCESSING_VERSION
            and payload.get("signature") == _signature(path)
        )
    except (OSError, ValueError, TypeError):
        return False


def remove_storefront_enhancement_marker(path: Path) -> None:
    try:
        _marker_path(path).unlink(missing_ok=True)
    except OSError:
        pass


def _write_marker(path: Path, metadata: dict) -> None:
    marker = _marker_path(path)
    payload = {
        "version": PROCESSING_VERSION,
        "signature": _signature(path),
        "metadata": metadata,
    }
    temporary = marker.with_name(f".{marker.name}.{uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, marker)


def _distance(first: tuple[int, int, int], second: tuple[int, int, int]) -> float:
    return math.sqrt(sum((int(a) - int(b)) ** 2 for a, b in zip(first, second)))


def _background_profile(image) -> tuple[tuple[int, int, int], bool]:
    width, height = image.size
    inset_x = min(max(width // 100, 1), max(width - 1, 0))
    inset_y = min(max(height // 100, 1), max(height - 1, 0))
    points = (
        (0, 0),
        (width - 1, 0),
        (0, height - 1),
        (width - 1, height - 1),
        (inset_x, inset_y),
        (width - 1 - inset_x, inset_y),
        (inset_x, height - 1 - inset_y),
        (width - 1 - inset_x, height - 1 - inset_y),
    )
    samples = [tuple(image.getpixel(point)[:3]) for point in points]
    background = tuple(int(median(channel)) for channel in zip(*samples))
    spread = max(_distance(sample, background) for sample in samples)
    return background, spread <= 38


def _difference_mask(image, background: tuple[int, int, int], threshold: int = 24):
    from PIL import Image, ImageChops

    flat = Image.new("RGB", image.size, background)
    difference = ImageChops.difference(image, flat)
    red, green, blue = difference.split()
    strongest = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    return strongest.point(lambda value: 255 if value > threshold else 0)


def _expanded_box(box, size: tuple[int, int]) -> tuple[int, int, int, int]:
    left, top, right, bottom = box
    width, height = size
    margin_x = max(10, round((right - left) * 0.045))
    margin_y = max(10, round((bottom - top) * 0.045))
    return (
        max(0, left - margin_x),
        max(0, top - margin_y),
        min(width, right + margin_x),
        min(height, bottom + margin_y),
    )


def _detect_crop(image, alpha, background, reliable_background):
    width, height = image.size
    full_box = (0, 0, width, height)
    if alpha is not None and alpha.getextrema()[0] < 250:
        box = alpha.point(lambda value: 255 if value > 8 else 0).getbbox()
    elif reliable_background:
        box = _difference_mask(image, background).getbbox()
    else:
        box = None
    if not box:
        return full_box
    content_area = max(1, (box[2] - box[0]) * (box[3] - box[1]))
    if content_area < width * height * 0.015:
        return full_box
    return _expanded_box(box, image.size)


def _edge_background_alpha(image, background):
    from PIL import Image, ImageChops, ImageDraw, ImageFilter

    work = image.copy()
    marker = (1, 2, 3)
    width, height = work.size
    for point in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)):
        if work.getpixel(point) != marker:
            ImageDraw.floodfill(work, point, marker, thresh=26)
    marker_layer = Image.new("RGB", work.size, marker)
    difference = ImageChops.difference(work, marker_layer)
    red, green, blue = difference.split()
    alpha = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    alpha = alpha.point(lambda value: 255 if value else 0)
    return alpha.filter(ImageFilter.GaussianBlur(0.8))


def _enhance_subject(image):
    from PIL import ImageEnhance, ImageFilter, ImageOps

    enhanced = ImageOps.autocontrast(image, cutoff=(0.35, 0.35), preserve_tone=True)
    enhanced = ImageEnhance.Color(enhanced).enhance(1.04)
    enhanced = ImageEnhance.Contrast(enhanced).enhance(1.035)
    enhanced = ImageEnhance.Sharpness(enhanced).enhance(1.12)
    return enhanced.filter(ImageFilter.UnsharpMask(radius=1.1, percent=75, threshold=3))


def _compose_canvas(subject, alpha):
    from PIL import Image, ImageFilter

    usable = CANVAS_SIZE - 150
    width, height = subject.size
    scale = min(usable / max(width, 1), usable / max(height, 1))
    scale = min(scale, 2.4)
    output_size = (max(1, round(width * scale)), max(1, round(height * scale)))
    if output_size != subject.size:
        subject = subject.resize(output_size, Image.Resampling.LANCZOS)
        alpha = alpha.resize(output_size, Image.Resampling.LANCZOS) if alpha is not None else None

    foreground = subject.convert("RGBA")
    if alpha is not None:
        foreground.putalpha(alpha)

    x = (CANVAS_SIZE - foreground.width) // 2
    y = (CANVAS_SIZE - foreground.height) // 2
    canvas = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), CANVAS_COLOR)
    shadow_alpha = foreground.getchannel("A").filter(ImageFilter.GaussianBlur(18))
    shadow_alpha = shadow_alpha.point(lambda value: round(value * 0.18))
    shadow = Image.new("RGBA", foreground.size, (8, 24, 42, 0))
    shadow.putalpha(shadow_alpha)
    canvas.alpha_composite(shadow, (x, min(CANVAS_SIZE - foreground.height, y + 12)))
    canvas.alpha_composite(foreground, (x, y))
    return canvas, output_size


def _save_atomic(image, path: Path, mime_type: str) -> None:
    formats = {
        "image/jpeg": ("JPEG", {"quality": 90, "optimize": True, "progressive": True, "subsampling": 0}),
        "image/png": ("PNG", {"optimize": True, "compress_level": 7}),
        "image/webp": ("WEBP", {"quality": 90, "method": 6}),
    }
    image_format, options = formats.get(mime_type, formats["image/jpeg"])
    if image_format == "JPEG" and image.mode != "RGB":
        from PIL import Image

        fallback = Image.new("RGB", image.size, (255, 255, 255))
        fallback.paste(image, mask=image.getchannel("A") if "A" in image.getbands() else None)
        image = fallback
    temporary = path.with_name(f".{path.stem}.{uuid4().hex}.tmp{path.suffix}")
    try:
        image.save(temporary, format=image_format, **options)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def enhance_storefront_image(
    path: Path,
    mime_type: str,
    *,
    force: bool = False,
    output_path: Path | None = None,
    output_mime_type: str | None = None,
) -> dict:
    """Normalize one product image and preserve a transparent background when possible."""

    destination = Path(output_path) if output_path is not None else path
    destination_mime = output_mime_type or mime_type
    if not force and is_storefront_image_enhanced(destination):
        return {"enhanced": False, "skipped": True, "version": PROCESSING_VERSION}

    try:
        from PIL import Image, ImageOps, UnidentifiedImageError

        with Image.open(path) as source:
            source.load()
            if source.width * source.height > MAX_INPUT_PIXELS:
                raise StorefrontImageError("أبعاد الصورة كبيرة جداً")
            original_size = source.size
            oriented = ImageOps.exif_transpose(source)
            alpha = oriented.getchannel("A") if "A" in oriented.getbands() else None
            if alpha is not None and alpha.getextrema()[0] >= 250:
                alpha = None
            rgb = oriented.convert("RGB")

        background, reliable_background = _background_profile(rgb)
        crop_box = _detect_crop(rgb, alpha, background, reliable_background)
        rgb = rgb.crop(crop_box)
        alpha = alpha.crop(crop_box) if alpha is not None else None

        background_brightness = sum(background) / 3
        replaced_background = False
        if alpha is None and reliable_background and background_brightness >= 225:
            alpha = _edge_background_alpha(rgb, background)
            replaced_background = True

        enhanced = _enhance_subject(rgb)
        output, subject_size = _compose_canvas(enhanced, alpha)
        destination.parent.mkdir(parents=True, exist_ok=True)
        _save_atomic(output, destination, destination_mime)
        metadata = {
            "enhanced": True,
            "skipped": False,
            "version": PROCESSING_VERSION,
            "original_size": list(original_size),
            "crop_box": list(crop_box),
            "subject_size": list(subject_size),
            "output_size": [CANVAS_SIZE, CANVAS_SIZE],
            "background_replaced": replaced_background,
            "background_removed": bool(alpha is not None),
            "transparent_output": destination_mime in {"image/png", "image/webp"},
        }
        _write_marker(destination, metadata)
        return metadata
    except StorefrontImageError:
        raise
    except (OSError, ValueError, UnidentifiedImageError) as exc:
        raise StorefrontImageError("تعذر قراءة الصورة أو تحسينها") from exc
