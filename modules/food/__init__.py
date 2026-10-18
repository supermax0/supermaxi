"""Isolated food wholesale/retail workspace."""
from __future__ import annotations

from flask import Flask


def init_food_workspace(app: Flask) -> None:
    from modules.food.routes import food_bp

    app.register_blueprint(food_bp)


__all__ = ["init_food_workspace"]
