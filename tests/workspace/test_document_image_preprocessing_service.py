"""Document analysis copies are rotated and enhanced without touching originals."""

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_landscape_image_is_enhanced_as_portrait_copy(tmp_path, monkeypatch):
    from PIL import Image, ImageDraw

    from modules.workspace.services.document_intelligence.document_image_preprocessing_service import (
        DocumentImagePreprocessingService,
    )

    monkeypatch.setenv("WORKSPACE_DOCUMENT_PREPROCESSING_ENABLED", "1")
    monkeypatch.setenv("WORKSPACE_DOCUMENT_ROTATE_LANDSCAPE", "1")
    monkeypatch.setattr(
        DocumentImagePreprocessingService,
        "_tesseract_rotation",
        staticmethod(lambda _image: 0),
    )

    original = tmp_path / "rotated-statement.png"
    image = Image.new("RGB", (1200, 700), "white")
    draw = ImageDraw.Draw(image)
    for x in range(80, 1120, 55):
        draw.line((x, 70, x, 630), fill="black", width=2)
    draw.text((100, 320), "210642  139000  6000  133000", fill="black")
    image.save(original)
    before = _sha256(original)

    prepared = DocumentImagePreprocessingService.prepare_for_analysis(
        str(original),
        "image/png",
        original.name,
    )
    try:
        assert prepared["applied"] is True
        assert Path(prepared["abs_path"]).is_file()
        assert _sha256(original) == before
        with Image.open(prepared["abs_path"]) as enhanced:
            assert enhanced.height > enhanced.width
            assert min(enhanced.size) >= 1800
        page = prepared["metadata"]["pages"][0]
        assert page["rotation"] == 90
        assert page["autocontrast"] is True
        assert page["sharpened"] is True
    finally:
        output_path = Path(prepared["abs_path"])
        DocumentImagePreprocessingService.cleanup(prepared)
    assert not output_path.exists()


def test_landscape_scanned_pdf_pages_are_enhanced(tmp_path, monkeypatch):
    import fitz

    from modules.workspace.services.document_intelligence.document_image_preprocessing_service import (
        DocumentImagePreprocessingService,
    )

    monkeypatch.setenv("WORKSPACE_DOCUMENT_PREPROCESSING_ENABLED", "1")
    monkeypatch.setenv("WORKSPACE_DOCUMENT_ROTATE_LANDSCAPE", "1")
    monkeypatch.setattr(
        DocumentImagePreprocessingService,
        "_tesseract_rotation",
        staticmethod(lambda _image: 0),
    )

    original = tmp_path / "rotated-statement.pdf"
    pdf = fitz.open()
    page = pdf.new_page(width=900, height=520)
    page.insert_text((80, 100), "210642 139000 6000 133000", fontsize=22)
    pdf.save(original)
    pdf.close()
    before = _sha256(original)

    prepared = DocumentImagePreprocessingService.prepare_for_analysis(
        str(original),
        "application/pdf",
        original.name,
    )
    try:
        assert prepared["applied"] is True
        assert _sha256(original) == before
        enhanced_pdf = fitz.open(prepared["abs_path"])
        try:
            assert enhanced_pdf.page_count == 1
            assert enhanced_pdf[0].rect.height > enhanced_pdf[0].rect.width
        finally:
            enhanced_pdf.close()
        assert prepared["metadata"]["pages"][0]["rotation"] == 90
    finally:
        DocumentImagePreprocessingService.cleanup(prepared)


def test_local_image_ocr_receives_preprocessed_copy(tmp_path, monkeypatch):
    import io

    from PIL import Image

    from ai import ocr
    from modules.workspace.services.document_intelligence.document_image_preprocessing_service import (
        DocumentImagePreprocessingService,
    )
    from modules.workspace.services.document_intelligence.document_text_extraction_service import (
        DocumentTextExtractionService,
    )

    monkeypatch.setenv("WORKSPACE_DOCUMENT_PREPROCESSING_ENABLED", "1")
    monkeypatch.setenv("WORKSPACE_DOCUMENT_ROTATE_LANDSCAPE", "1")
    monkeypatch.setattr(
        DocumentImagePreprocessingService,
        "_tesseract_rotation",
        staticmethod(lambda _image: 0),
    )
    original = tmp_path / "ocr-landscape.png"
    Image.new("RGB", (1100, 650), "white").save(original)
    received = {}

    def fake_extract(image_bytes):
        with Image.open(io.BytesIO(image_bytes)) as image:
            received["size"] = image.size
        return "210642"

    monkeypatch.setattr(ocr, "extract_text", fake_extract)
    result = DocumentTextExtractionService._extract_image(str(original))

    assert result["status"] == "completed"
    assert result["text"] == "210642"
    assert received["size"][1] > received["size"][0]
    assert result["pages"][0]["preprocessed"] is True
