"""FINORA tenant-local human resources workspace."""
from .routes import hr_bp
from .recruitment import public_bp

__all__ = ["hr_bp", "public_bp"]
