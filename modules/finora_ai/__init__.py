"""Provider-neutral FINORA AI + MCP Phase 1 module."""


def init_finora_ai(app) -> None:
    from modules.finora_ai.mcp import mcp_bp
    from modules.finora_ai.routes import finora_ai_bp
    if "finora_ai" not in app.blueprints:
        app.register_blueprint(finora_ai_bp)
    if "finora_mcp" not in app.blueprints:
        app.register_blueprint(mcp_bp)


__all__ = ["init_finora_ai"]
