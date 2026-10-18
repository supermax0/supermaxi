"""Short-lived MCP tokens and per-application revocable credentials."""
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import hmac
import re
import secrets
import jwt
from flask import current_app, session, g
from sqlalchemy import inspect
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from modules.finora_ai.context import AuthenticationRequired, FinoraAuthContext
from modules.finora_ai.models import FinoraMCPConnection, FinoraAISettings
from extensions import db


def _signing_key():
    key = current_app.config.get("FINORA_MCP_TOKEN_SECRET") or current_app.secret_key
    if not key or key == "super-secret-key-change-in-production":
        raise AuthenticationRequired("Configure a strong server signing key")
    return key


def issue_token(context: FinoraAuthContext) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({
        "sub": str(context.user_id), "tenant": context.tenant_slug,
        "aud": "finora-mcp", "iss": "finora", "iat": now,
        "exp": now + timedelta(minutes=15),
    }, _signing_key(), algorithm="HS256")


def issue_connection(context: FinoraAuthContext, name: str):
    _signing_key()  # Reject the application's known insecure configuration.
    if FinoraMCPConnection.query.filter_by(tenant_slug=context.tenant_slug, user_id=context.user_id, revoked_at=None).count() >= 10:
        raise ValueError("ألغي أحد المفاتيح الحالية أولًا؛ الحد 10 روابط فعّالة للحساب.")
    connection_id, secret = secrets.token_hex(16), secrets.token_urlsafe(32)
    locator = base64.urlsafe_b64encode(context.tenant_slug.encode("utf-8")).decode("ascii").rstrip("=")
    row = FinoraMCPConnection(id=connection_id, tenant_slug=context.tenant_slug, user_id=context.user_id,
                             name=name, secret_hash=hashlib.sha256(secret.encode("ascii")).hexdigest())
    db.session.add(row)
    db.session.commit()
    return row.id, f"fmcp1.{locator}.{connection_id}.{secret}"


def _connection_identity(token: str):
    try:
        version, locator, connection_id, secret = token.split(".")
        if version != "fmcp1" or not re.fullmatch(r"[A-Za-z0-9_-]{1,140}", locator) or not re.fullmatch(r"[0-9a-f]{32}", connection_id) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", secret):
            raise ValueError("Malformed key")
        tenant_slug = base64.urlsafe_b64decode(locator + "=" * (-len(locator) % 4)).decode("utf-8")
        from extensions_tenant import is_valid_tenant_slug, get_tenant_engine
        if not is_valid_tenant_slug(tenant_slug):
            raise ValueError("Invalid tenant")
        # The locator is not an identity claim. Only the tenant-scoped stored
        # verifier decides whose account this credential belongs to.
        require_active_tenant(tenant_slug)
        engine = get_tenant_engine(tenant_slug)
        if not inspect(engine).has_table(FinoraMCPConnection.__tablename__):
            raise ValueError("Unknown key")
        # Separate session avoids old cookie/ORM identity maps selecting an
        # object from another tenant with overlapping IDs. No schema writes.
        with Session(engine) as verification:
            row = verification.query(FinoraMCPConnection).filter_by(id=connection_id, tenant_slug=tenant_slug).first()
            digest = hashlib.sha256(secret.encode("ascii")).hexdigest()
            if not row or row.revoked_at is not None or not hmac.compare_digest(row.secret_hash, digest):
                raise ValueError("Invalid or revoked key")
            settings = verification.query(FinoraAISettings).first()
            if not settings or not settings.enabled or not settings.get_flags().get("finora_ai_enabled", True) or not settings.get_flags().get("mcp_enabled", True):
                raise AuthenticationRequired("MCP disabled")
            return tenant_slug, int(row.user_id), connection_id
    except (ValueError, UnicodeError, SQLAlchemyError) as exc:
        raise AuthenticationRequired("Invalid or revoked connection key") from exc


def require_active_tenant(tenant_slug: str) -> None:
    from models.core.tenant import Tenant as CoreTenant
    previous = getattr(g, "tenant", None)
    g.tenant = None
    try:
        tenant = CoreTenant.query.filter_by(slug=tenant_slug).first()
        if not tenant or not tenant.is_subscription_valid():
            raise AuthenticationRequired("Tenant is inactive or expired")
    finally:
        g.tenant = previous


def apply_bearer(authorization: str) -> None:
    if not authorization:
        return
    if not authorization.startswith("Bearer "):
        raise AuthenticationRequired("Invalid authentication")
    token = authorization[7:]
    if len(token) > 4096:
        raise AuthenticationRequired("Invalid authentication")
    try:
        if token.startswith("fmcp1."):
            tenant, user_id, connection_id = _connection_identity(token)
            # Drop objects loaded by cookie middleware before changing tenants.
            # Employee IDs overlap between tenant databases.
            db.session.remove()
            session.clear()
            g.tenant = tenant
            session.update(tenant_slug=tenant, user_id=user_id)
            context = FinoraAuthContext.current()
            if not context.allows("use_ai_assistant"):
                raise AuthenticationRequired("Assistant access disabled")
            g.finora_mcp_connection_id = connection_id
            return
        claims = jwt.decode(token, _signing_key(), algorithms=["HS256"],
                            audience="finora-mcp", issuer="finora",
                            options={"require": ["sub", "tenant", "exp", "iat", "iss", "aud"]})
        from extensions_tenant import is_valid_tenant_slug
        if not is_valid_tenant_slug(claims["tenant"]):
            raise ValueError("Invalid tenant")
        require_active_tenant(claims["tenant"])
        db.session.remove()
        session.clear()
        g.tenant = claims["tenant"]
        session["tenant_slug"] = claims["tenant"]
        session["user_id"] = int(claims["sub"])
    except (jwt.PyJWTError, ValueError, KeyError, TypeError) as exc:
        raise AuthenticationRequired("Invalid or expired access token") from exc
