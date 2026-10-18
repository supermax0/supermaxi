"""FINORA CORE server module: desktop API, realtime outbox, audit. See docs/finora-core-architecture.md."""
from __future__ import annotations

import logging

import click

logger = logging.getLogger(__name__)


def init_finora_core(app) -> None:
    from extensions import db

    from . import migrations
    from .api import finora_core_bp
    from . import settings_api  # noqa: F401 — registers settings routes before the blueprint is attached
    from . import media_api  # noqa: F401 — private media routes use the same auth and CORS policy
    from . import accounts_api  # noqa: F401 — customer-bound configuration and owner alerts
    from . import telegram_api  # noqa: F401 — bot settings and private-chat webhook
    from . import voice_api  # noqa: F401 — short, authenticated GPT-Live notification sessions
    from . import projects_api  # noqa: F401 — scoped software consultation and commercial review
    from . import project_graph_api  # noqa: F401 — interactive project maps and scoped read-only MCP

    from .meta_house import register_cli
    from .transport import warn_if_misconfigured

    from .brain.cli import register_cli as register_knowledge_cli

    app.register_blueprint(finora_core_bp)
    register_cli(app)
    register_knowledge_cli(app)
    warn_if_misconfigured()
    with app.app_context():
        try:
            version = migrations.upgrade(db.engine)
            logger.info("finora_core schema at v%s", version)
        except Exception:
            # The API stays registered; requests will surface classified errors instead of crashing the app.
            logger.exception("finora_core schema upgrade failed")

    @app.cli.command("finora-core-db")
    @click.argument("action", type=click.Choice(["upgrade", "downgrade", "current"]))
    @click.option("--to", "to_version", default=None, type=int)
    def finora_core_db(action: str, to_version: int | None) -> None:
        """Upgrade/downgrade the FINORA CORE Core-DB schema."""
        if action == "current":
            click.echo(migrations.current_version(db.engine))
        elif action == "upgrade":
            click.echo(migrations.upgrade(db.engine, to_version or migrations.TARGET_VERSION))
        else:
            click.echo(migrations.downgrade(db.engine, to_version or 0))
