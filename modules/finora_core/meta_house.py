"""FINORA house tenant: provisioning, Meta activation (fail closed) and real channel health checks.

CLI (secrets come from the environment only, never from argv / shell history):
  flask finora-house init                       # create the internal tenant (default slug: finora_house)
  META_APP_ID=... META_APP_SECRET=... META_USER_TOKEN=... flask finora-house meta-connect
  flask finora-house health                     # live Graph check of every house channel
"""
from __future__ import annotations

import logging
import os
import secrets
from typing import Any, Callable

import requests

logger = logging.getLogger(__name__)

DEFAULT_HOUSE_SLUG = "finora_house"
HOUSE_BUSINESS_TYPE = "finora_internal"
GRAPH = "https://graph.facebook.com/v23.0"


class ActivationError(RuntimeError):
    pass


def validate_app_secret(app_id: str, app_secret: str, *, http_get: Callable[..., Any] = requests.get) -> None:
    """Fail closed: the secret must be well-formed AND accepted by Meta (app access token = ``app_id|secret``)."""
    from modules.ai_sales.security import meta_app_secret_problem

    problem = meta_app_secret_problem(app_secret)
    if problem:
        raise ActivationError(f"META_APP_SECRET {problem}")
    if not app_id or not app_id.isdigit():
        raise ActivationError("META_APP_ID missing or malformed")
    try:
        res = http_get(f"{GRAPH}/{app_id}", params={"fields": "id", "access_token": f"{app_id}|{app_secret}"}, timeout=20)
    except requests.RequestException as exc:
        raise ActivationError("could not reach Meta to validate META_APP_SECRET") from exc
    if res.status_code != 200 or str((res.json() or {}).get("id")) != app_id:
        raise ActivationError("META_APP_SECRET rejected by Meta")


def init_house_tenant(slug: str = DEFAULT_HOUSE_SLUG) -> str:
    """Create the internal tenant row + database. Refuses to reuse a slug that belongs to a customer tenant."""
    from flask import g

    from extensions import db
    from extensions_tenant import init_tenant_db, is_valid_tenant_slug
    from models.core.tenant import Tenant
    from modules.ai_sales.schema import ensure_ai_sales_schema

    if not is_valid_tenant_slug(slug):
        raise ActivationError("invalid house tenant slug")
    from .store import core_session

    with core_session() as s:
        tenant = s.query(Tenant).filter_by(slug=slug).first()
        if tenant and tenant.business_type != HOUSE_BUSINESS_TYPE:
            raise ActivationError(f"tenant '{slug}' exists and is a customer tenant — choose another slug")
        if tenant is None:
            s.add(Tenant(name="FINORA (internal)", slug=slug, db_path=f"tenants/{slug}.db",
                         business_type=HOUSE_BUSINESS_TYPE, is_active=True))
            s.commit()
    previous = getattr(g, "tenant", None)
    g.tenant = slug
    try:
        init_tenant_db(slug)
        ensure_ai_sales_schema()
        # Run the Facebook routing guard now: left to the first webhook it ALTERs + commits mid-request, which
        # breaks that first message's insert on a brand-new tenant (pre-existing ai_sales behaviour).
        from modules.facebook_routing.schema import ensure_facebook_routing_schema

        ensure_facebook_routing_schema()
        db.session.commit()
    finally:
        db.session.remove()
        g.tenant = previous
    return slug


def connect_meta(
    *,
    app_id: str,
    app_secret: str,
    user_token: str,
    validate: Callable[[str, str], None] = validate_app_secret,
) -> dict[str, Any]:
    """Create/refresh the house Meta connector and import FINORA's pages. FINORA CORE replies on them (reply_mode=ai)."""
    from modules.ai_sales.models import AISalesChannelAccount
    from modules.ai_sales.routes import sync_meta_connector_pages
    from modules.ai_sales.security import encrypt_secret

    from extensions import db

    from .store import use_house

    validate(app_id, app_secret)  # raises ActivationError — nothing is stored on failure
    if not user_token:
        raise ActivationError("META_USER_TOKEN missing")
    with use_house() as slug:
        connector = AISalesChannelAccount.query.filter_by(channel_type="meta").first()
        if connector is None:
            connector = AISalesChannelAccount(channel_type="meta", name="FINORA Meta", is_active=True, reply_mode="ai")
            db.session.add(connector)
        connector.external_account_id = app_id
        connector.app_secret_encrypted = encrypt_secret(app_secret)
        connector.verify_token_encrypted = connector.verify_token_encrypted or encrypt_secret(secrets.token_urlsafe(24))
        connector.is_active = True
        db.session.commit()
        result, status = sync_meta_connector_pages(connector, user_token, slug, default_reply_mode="ai")
        if status != 200:
            raise ActivationError(f"page sync failed: {result.get('error')}")
        return {
            "pages_found": result["pages_found"],
            "channels": [
                {"type": c["channel_type"], "name": c["name"], "account_id": c.get("external_account_id"),
                 "status": c.get("connection_status")}
                for c in result["channels"]
            ],
            "warnings": result["warnings"],
        }


def check_channel_health(channel, *, client_factory=None) -> str:
    """Live check: token valid for the page/IG account, and our app still subscribed to its webhooks."""
    from modules.ai_sales.channels import MetaMessagingClient, MetaMessagingClientError
    from modules.ai_sales.meta_reliability import apply_channel_failure, apply_channel_success, classify

    if not channel.is_active or channel.connection_status in {"unavailable", "removed"}:
        channel.connection_status = "disconnected"
        return channel.connection_status
    try:
        client = (client_factory or MetaMessagingClient)(channel)
        client._request("GET", str(channel.external_account_id), params={"fields": "id"})
        if channel.channel_type == "messenger":
            subscribed = client._request("GET", f"{channel.external_account_id}/subscribed_apps")
            if not (subscribed.get("data") or []):
                channel.connection_status = "webhook_invalid"
                channel.last_error = "FINORA app is not subscribed to this page's webhooks"
                return channel.connection_status
        apply_channel_success(channel)
    except MetaMessagingClientError as exc:
        if "غير محفوظ" in str(exc):  # no token stored at all
            channel.connection_status = "disconnected"
            channel.last_error = "no page token stored"
        else:
            apply_channel_failure(channel, classify(exc))
            if channel.connection_status == "connected":  # transient failure: health unknown, keep previous
                logger.info("health check for channel %s inconclusive: %s", channel.id, exc)
    return channel.connection_status


def run_health_checks(*, client_factory=None) -> list[dict[str, Any]]:
    from extensions import db
    from modules.ai_sales.models import AISalesChannelAccount

    from .conversations import CORE_CHANNEL_TYPES
    from .store import use_house

    with use_house():
        rows = AISalesChannelAccount.query.filter(AISalesChannelAccount.channel_type.in_(CORE_CHANNEL_TYPES)).all()
        report = [
            {"type": r.channel_type, "name": r.name, "status": check_channel_health(r, client_factory=client_factory)}
            for r in rows
            if r.channel_type != "telegram"
        ]
        db.session.commit()
    return report


def register_cli(app) -> None:
    import click

    @app.cli.group("finora-house")
    def finora_house() -> None:
        """FINORA internal house tenant (FINORA CORE's own Instagram / Facebook)."""

    @finora_house.command("init")
    @click.option("--slug", default=lambda: os.environ.get("FINORA_CORE_HOUSE_TENANT") or DEFAULT_HOUSE_SLUG)
    def init_cmd(slug: str) -> None:
        click.echo(f"house tenant ready: {init_house_tenant(slug)}  (set FINORA_CORE_HOUSE_TENANT={slug})")

    @finora_house.command("meta-connect")
    def meta_connect_cmd() -> None:
        try:
            report = connect_meta(
                app_id=os.environ.get("META_APP_ID", "").strip(),
                app_secret=os.environ.get("META_APP_SECRET", "").strip(),
                user_token=os.environ.get("META_USER_TOKEN", "").strip(),
            )
        except ActivationError as exc:
            raise click.ClickException(f"Meta activation refused (fail closed): {exc}") from exc
        click.echo(f"pages found: {report['pages_found']}")
        for c in report["channels"]:
            click.echo(f"  {c['type']:<10} {c['account_id']:<20} {c['status']:<16} {c['name']}")
        for w in report["warnings"]:
            click.echo(f"  warning: {w}")

    @finora_house.command("health")
    def health_cmd() -> None:
        for row in run_health_checks():
            click.echo(f"{row['type']:<10} {row['status']:<18} {row['name']}")
