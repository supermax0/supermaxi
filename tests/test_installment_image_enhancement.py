from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from modules.installments.image_enhancement import (
    CANVAS_SIZE,
    StorefrontImageError,
    enhance_storefront_image,
    is_storefront_image_enhanced,
    remove_storefront_enhancement_marker,
)


def test_black_letterbox_is_trimmed_without_removing_dark_design(tmp_path: Path):
    path = tmp_path / "poster.png"
    image = Image.new("RGB", (600, 1000), "black")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 350, 599, 650), fill=(22, 25, 31))
    draw.rectangle((45, 410, 555, 590), fill=(180, 20, 34))
    image.save(path)

    result = enhance_storefront_image(path, "image/png")

    assert result["enhanced"] is True
    assert result["crop_box"][1] > 250
    assert result["crop_box"][3] < 750
    assert result["background_replaced"] is False
    with Image.open(path) as processed:
        assert processed.size == (CANVAS_SIZE, CANVAS_SIZE)


def test_white_product_background_is_cleaned_and_centered(tmp_path: Path):
    path = tmp_path / "product.jpg"
    output = tmp_path / "product.png"
    image = Image.new("RGB", (800, 1000), "white")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((245, 170, 555, 850), radius=45, fill=(34, 39, 44))
    image.save(path, quality=95)

    result = enhance_storefront_image(
        path,
        "image/jpeg",
        output_path=output,
        output_mime_type="image/png",
    )

    assert result["background_replaced"] is True
    assert result["crop_box"] != [0, 0, 800, 1000]
    assert result["background_removed"] is True
    assert result["transparent_output"] is True
    with Image.open(output) as processed:
        assert processed.size == (CANVAS_SIZE, CANVAS_SIZE)
        assert processed.convert("RGBA").getpixel((5, 5))[3] == 0
        assert processed.convert("RGBA").getpixel((CANVAS_SIZE // 2, CANVAS_SIZE // 2))[3] > 240


def test_existing_transparency_is_preserved_without_adding_a_white_canvas(tmp_path: Path):
    path = tmp_path / "transparent-product.png"
    image = Image.new("RGBA", (700, 900), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((210, 120, 490, 820), radius=35, fill=(60, 65, 70, 255))
    image.save(path)

    result = enhance_storefront_image(path, "image/png")

    assert result["background_removed"] is True
    with Image.open(path) as processed:
        rgba = processed.convert("RGBA")
        assert rgba.getpixel((5, 5))[3] == 0
        assert rgba.getpixel((CANVAS_SIZE // 2, CANVAS_SIZE // 2))[3] > 240


def test_enhancement_marker_prevents_repeat_processing(tmp_path: Path):
    path = tmp_path / "repeat.webp"
    Image.new("RGB", (400, 500), "white").save(path, format="WEBP")

    enhance_storefront_image(path, "image/webp")

    assert is_storefront_image_enhanced(path) is True
    assert enhance_storefront_image(path, "image/webp")["skipped"] is True
    remove_storefront_enhancement_marker(path)
    assert is_storefront_image_enhanced(path) is False


def test_invalid_image_is_rejected(tmp_path: Path):
    path = tmp_path / "broken.png"
    path.write_bytes(b"not an image")

    with pytest.raises(StorefrontImageError):
        enhance_storefront_image(path, "image/png")
