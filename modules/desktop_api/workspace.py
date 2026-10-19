"""Compatibility response for desktop 0.8.0 after connected pages were withdrawn."""
from flask import jsonify
from modules.desktop_api.routes import desktop_api_bp
from modules.desktop_api.branches import _authorize


@desktop_api_bp.get("/workspace")
def desktop_workspace():
    denied = _authorize()
    if denied is not None:
        return denied
    # Existing 0.8.0 clients refresh this list and remove the withdrawn entries.
    return jsonify(ok=True, pages=[])
