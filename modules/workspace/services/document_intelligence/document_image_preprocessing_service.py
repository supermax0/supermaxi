from __future__ import annotations

import io
import os
import tempfile
from typing import Any, Dict, Optional, Tuple

from flask import current_app, has_app_context


class DocumentImagePreprocessingService:
    """Create a temporary analysis copy without modifying the uploaded original."""

    IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff")

    @staticmethod
    def _flag(name: str, default: str = "1") -> bool:
        raw = (
            current_app.config.get(name, os.environ.get(name, default))
            if has_app_context()
            else os.environ.get(name, default)
        )
        return str(raw).strip().lower() not in {"0", "false", "off", "no"}

    @staticmethod
    def prepare_for_analysis(
        abs_path: str,
        mime_type: str,
        filename: str = "",
    ) -> Dict[str, Any]:
        source = {
            "abs_path": abs_path,
            "mime_type": mime_type,
            "filename": filename,
            "applied": False,
            "metadata": {
                "applied": False,
                "source": "original",
                "filename": filename,
            },
            "_temp_handle": None,
        }
        if not DocumentImagePreprocessingService._flag(
            "WORKSPACE_DOCUMENT_PREPROCESSING_ENABLED"
        ):
            return source

        mime = (mime_type or "").lower()
        name = (filename or abs_path).lower()
        is_pdf = mime == "application/pdf" or name.endswith(".pdf")
        is_image = mime.startswith("image/") or name.endswith(
            DocumentImagePreprocessingService.IMAGE_SUFFIXES
        )
        if not is_pdf and not is_image:
            return source

        temp_handle = tempfile.TemporaryDirectory(prefix="finora-doc-analysis-")
        try:
            if is_pdf:
                output_path, metadata = DocumentImagePreprocessingService._prepare_pdf(
                    abs_path,
                    temp_handle.name,
                )
                output_mime = "application/pdf"
                output_name = f"{os.path.splitext(filename or 'document')[0]}_enhanced.pdf"
            else:
                output_path, metadata = DocumentImagePreprocessingService._prepare_image(
                    abs_path,
                    temp_handle.name,
                )
                output_mime = "image/png"
                output_name = f"{os.path.splitext(filename or 'document')[0]}_enhanced.png"
            return {
                "abs_path": output_path,
                "mime_type": output_mime,
                "filename": output_name,
                "applied": True,
                "metadata": {
                    "applied": True,
                    "source": "enhanced_copy",
                    "filename": filename,
                    **metadata,
                },
                "_temp_handle": temp_handle,
            }
        except Exception as exc:
            temp_handle.cleanup()
            source["metadata"]["error"] = str(exc)
            return source

    @staticmethod
    def cleanup(prepared: Optional[Dict[str, Any]]) -> None:
        handle = (prepared or {}).get("_temp_handle")
        if handle is not None:
            handle.cleanup()

    @staticmethod
    def _prepare_image(abs_path: str, temp_dir: str) -> Tuple[str, Dict[str, Any]]:
        from PIL import Image

        with Image.open(abs_path) as image:
            enhanced, metadata = DocumentImagePreprocessingService._enhance_image(
                image
            )
            output_path = os.path.join(temp_dir, "enhanced.png")
            enhanced.save(output_path, format="PNG", optimize=True)
        return output_path, {"pages": [metadata], "page_count": 1}

    @staticmethod
    def _prepare_pdf(abs_path: str, temp_dir: str) -> Tuple[str, Dict[str, Any]]:
        import fitz  # type: ignore
        from PIL import Image

        source = fitz.open(abs_path)
        output = fitz.open()
        pages_metadata = []
        try:
            for page_number, page in enumerate(source, start=1):
                pix = page.get_pixmap(matrix=fitz.Matrix(2.4, 2.4), alpha=False)
                with Image.open(io.BytesIO(pix.tobytes("png"))) as image:
                    enhanced, metadata = (
                        DocumentImagePreprocessingService._enhance_image(image)
                    )
                    buffer = io.BytesIO()
                    enhanced.save(buffer, format="PNG", optimize=True)
                width, height = enhanced.size
                output_page = output.new_page(width=width, height=height)
                output_page.insert_image(output_page.rect, stream=buffer.getvalue())
                pages_metadata.append({"page": page_number, **metadata})

            output_path = os.path.join(temp_dir, "enhanced.pdf")
            output.save(output_path, garbage=4, deflate=True)
            return output_path, {
                "pages": pages_metadata,
                "page_count": len(pages_metadata),
            }
        finally:
            output.close()
            source.close()

    @staticmethod
    def _enhance_image(image):
        from PIL import Image, ImageEnhance, ImageFilter, ImageOps

        oriented = ImageOps.exif_transpose(image).convert("RGB")
        original_size = list(oriented.size)
        rotation, orientation_source = (
            DocumentImagePreprocessingService._detect_rotation(oriented)
        )
        if rotation:
            oriented = oriented.rotate(-rotation, expand=True, fillcolor="white")

        width, height = oriented.size
        min_side = min(width, height)
        max_side = max(width, height)
        target_min = 1800
        target_max = 3800
        scale = 1.0
        if min_side < target_min:
            scale = target_min / max(min_side, 1)
        if max_side * scale > target_max:
            scale = target_max / max(max_side, 1)
        if scale > 1.03:
            oriented = oriented.resize(
                (
                    max(1, round(width * scale)),
                    max(1, round(height * scale)),
                ),
                Image.Resampling.LANCZOS,
            )

        grayscale = ImageOps.grayscale(oriented)
        grayscale = ImageOps.autocontrast(grayscale, cutoff=(1, 1))
        grayscale = ImageEnhance.Contrast(grayscale).enhance(1.18)
        grayscale = grayscale.filter(
            ImageFilter.UnsharpMask(radius=1.4, percent=145, threshold=2)
        )
        enhanced = grayscale.convert("RGB")
        return enhanced, {
            "original_size": original_size,
            "output_size": list(enhanced.size),
            "rotation": rotation,
            "orientation_source": orientation_source,
            "upscaled": scale > 1.03,
            "grayscale": True,
            "autocontrast": True,
            "sharpened": True,
        }

    @staticmethod
    def _detect_rotation(image) -> Tuple[int, str]:
        detected = DocumentImagePreprocessingService._tesseract_rotation(image)
        if detected:
            return detected, "tesseract_osd"
        if (
            DocumentImagePreprocessingService._flag(
                "WORKSPACE_DOCUMENT_ROTATE_LANDSCAPE"
            )
            and image.width > image.height * 1.15
        ):
            # Courier statements are portrait documents. If OSD is unavailable,
            # reducing a 90-degree rotation to 0/180 degrees still gives the
            # vision model a materially clearer page.
            return 90, "landscape_document_fallback"
        return 0, "unchanged"

    @staticmethod
    def _tesseract_rotation(image) -> int:
        try:
            from ai.ocr import _configure_tesseract

            _configure_tesseract()
            import pytesseract  # type: ignore

            data = pytesseract.image_to_osd(
                image,
                output_type=pytesseract.Output.DICT,
            )
            rotation = int(data.get("rotate") or 0) % 360
            confidence = float(data.get("orientation_conf") or 0)
            if rotation in {90, 180, 270} and confidence >= 1.0:
                return rotation
        except Exception:
            pass
        return 0
