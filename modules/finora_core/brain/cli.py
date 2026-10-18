"""Knowledge authoring CLI. Drafts are never used to answer customers; a human publishes each version.

  flask finora-knowledge draft --key clinics-overview --category clinics --title "..." --file overview.md --source "..."
  flask finora-knowledge publish --key clinics-overview --version 1
  flask finora-knowledge list
"""
from __future__ import annotations

import getpass

import click


def register_cli(app) -> None:
    @app.cli.group("finora-knowledge")
    def finora_knowledge() -> None:
        """FINORA CORE product knowledge (versioned)."""

    @finora_knowledge.command("draft")
    @click.option("--key", required=True)
    @click.option("--category", required=True)
    @click.option("--title", required=True)
    @click.option("--file", "path", required=True, type=click.Path(exists=True, dir_okay=False))
    @click.option("--source", required=True, help="Where the facts come from (doc, owner, decision)")
    @click.option("--business-type", default=None, help="FINORA business type (routes/superadmin.BUSINESS_TYPES)")
    @click.option("--module", default=None)
    @click.option("--feature", default=None)
    @click.option("--plans", default="", help="comma-separated plan keys (empty = every plan)")
    @click.option("--effective-from", default=None, help="ISO date")
    @click.option("--effective-until", default=None, help="ISO date")
    @click.option("--note", default=None, help="revision note")
    def draft(key: str, category: str, title: str, path: str, source: str, business_type, module, feature, plans,
              effective_from, effective_until, note) -> None:
        from ..store import core_session
        from .knowledge import save_draft

        with open(path, encoding="utf-8") as fh:
            body = fh.read()
        with core_session() as s:
            row = save_draft(s, doc_key=key, category=category, title=title, body=body, source=source,
                             author=f"cli:{getpass.getuser()}", business_type=business_type, module=module,
                             feature=feature, supported_plans=[p.strip() for p in plans.split(",") if p.strip()],
                             effective_from=effective_from, effective_until=effective_until, revision_note=note)
            s.commit()
            click.echo(f"draft {row.doc_key} v{row.version} saved (not used until published)")

    @finora_knowledge.command("publish")
    @click.option("--key", required=True)
    @click.option("--version", required=True, type=int)
    def publish_cmd(key: str, version: int) -> None:
        from ..store import audit, core_session
        from .knowledge import publish

        actor = f"cli:{getpass.getuser()}"
        with core_session() as s:
            row = publish(s, key, version, actor=actor)
            audit(s, actor=actor, actor_type="human", category="finora", action="knowledge.publish",
                  title="نشر معرفة FINORA", input_summary=f"{row.doc_key} v{row.version}: {row.title}")
            s.commit()
            click.echo(f"published {row.doc_key} v{row.version}")

    @finora_knowledge.command("list")
    def list_cmd() -> None:
        from ..store import core_session
        from .models import FcKnowledgeDoc

        with core_session() as s:
            for r in s.query(FcKnowledgeDoc).order_by(FcKnowledgeDoc.doc_key, FcKnowledgeDoc.version).all():
                click.echo(f"{r.doc_key:<30} v{r.version:<3} {r.status:<10} {r.category:<12} "
                           f"{r.business_type or '*':<14} {r.title}")
