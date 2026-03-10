from __future__ import annotations

from flask import Blueprint, jsonify, request
from flask_login import current_user


workflow_api = Blueprint("workflow_api", __name__, url_prefix="/autoposter/api")


@workflow_api.route("/workflows")
def workflows_api():
    """
    Lightweight JSON endpoint for the React Workflow Builder.
    Returns a static demo workflow instead of redirecting to /login.
    """
    if not getattr(current_user, "is_authenticated", False):
        return jsonify({"error": "not_authenticated"}), 401

    workflow_id = request.args.get("workflow_id")

    return jsonify(
        {
            "workflow_id": workflow_id,
            "nodes": [
                {"id": "1", "type": "start", "position": {"x": 250, "y": 50}},
                {"id": "2", "type": "ai", "position": {"x": 250, "y": 200}},
                {"id": "3", "type": "image", "position": {"x": 250, "y": 350}},
                {"id": "4", "type": "caption", "position": {"x": 250, "y": 500}},
                {"id": "5", "type": "publisher", "position": {"x": 250, "y": 650}},
                {"id": "6", "type": "scheduler", "position": {"x": 250, "y": 800}},
                {"id": "7", "type": "comment-listener", "position": {"x": 250, "y": 950}},
                {"id": "8", "type": "auto-reply", "position": {"x": 250, "y": 1100}},
                {"id": "9", "type": "end", "position": {"x": 250, "y": 1250}},
            ],
            "edges": [
                {"id": "e1", "source": "1", "target": "2"},
                {"id": "e2", "source": "2", "target": "3"},
                {"id": "e3", "source": "3", "target": "4"},
                {"id": "e4", "source": "4", "target": "5"},
                {"id": "e5", "source": "5", "target": "6"},
                {"id": "e6", "source": "6", "target": "7"},
                {"id": "e7", "source": "7", "target": "8"},
                {"id": "e8", "source": "8", "target": "9"},
            ],
        }
    )

