"""Live agent positions and driving routes."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from urllib.error import URLError
from urllib.request import Request, urlopen

from flask import g
from sqlalchemy import inspect, text

from extensions import db
from models.agent_location import DeliveryAgentPosition, DeliveryAgentTrail

_OSRM = "https://router.project-osrm.org/route/v1/driving/{lng1},{lat1};{lng2},{lat2}"
_MANEUVERS = {
    "left": "اتجه يساراً",
    "right": "اتجه يميناً",
    "slight left": "انحرف يساراً قليلاً",
    "slight right": "انحرف يميناً قليلاً",
    "sharp left": "انعطف يساراً بحدة",
    "sharp right": "انعطف يميناً بحدة",
    "straight": "استمر للأمام",
    "uturn": "استدر للخلف",
}


def _engine():
    tenant_slug = getattr(g, "tenant", None)
    if tenant_slug:
        from extensions_tenant import get_tenant_engine

        return get_tenant_engine(tenant_slug)
    bind = db.session.get_bind()
    return bind if bind is not None else db.engine


def ensure_agent_location_schema() -> None:
    try:
        engine = _engine()
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        dialect = engine.dialect.name
        float_type = "DOUBLE PRECISION" if dialect == "postgresql" else "FLOAT"
        datetime_type = "TIMESTAMP" if dialect == "postgresql" else "DATETIME"
        id_sql = "id SERIAL PRIMARY KEY" if dialect == "postgresql" else "id INTEGER PRIMARY KEY AUTOINCREMENT"
        stmts = []
        if "delivery_agent_position" not in tables:
            stmts.append(
                "CREATE TABLE delivery_agent_position ("
                f"{id_sql}, "
                "agent_id INTEGER NOT NULL UNIQUE, "
                f"lat {float_type} NOT NULL, "
                f"lng {float_type} NOT NULL, "
                f"accuracy {float_type}, "
                f"heading {float_type}, "
                f"speed {float_type}, "
                f"updated_at {datetime_type})"
            )
        if "delivery_agent_trail" not in tables:
            stmts.append(
                "CREATE TABLE delivery_agent_trail ("
                f"{id_sql}, "
                "agent_id INTEGER NOT NULL, "
                f"lat {float_type} NOT NULL, "
                f"lng {float_type} NOT NULL, "
                f"recorded_at {datetime_type})"
            )
        if not stmts:
            return
        with engine.begin() as conn:
            for stmt in stmts:
                conn.execute(text(stmt))
    except Exception:
        db.session.rollback()


def record_agent_fix(agent_id: int, lat: float, lng: float, accuracy=None, heading=None, speed=None) -> None:
    now = datetime.utcnow()
    row = DeliveryAgentPosition.query.filter_by(agent_id=agent_id).first()
    if not row:
        row = DeliveryAgentPosition(agent_id=agent_id, lat=lat, lng=lng)
        db.session.add(row)
    row.lat = lat
    row.lng = lng
    row.accuracy = accuracy
    row.heading = heading
    row.speed = speed
    row.updated_at = now
    db.session.add(DeliveryAgentTrail(agent_id=agent_id, lat=lat, lng=lng, recorded_at=now))
    cutoff = now - timedelta(minutes=30)
    DeliveryAgentTrail.query.filter(
        DeliveryAgentTrail.agent_id == agent_id,
        DeliveryAgentTrail.recorded_at < cutoff,
    ).delete(synchronize_session=False)
    db.session.commit()


def latest_position(agent_id: int) -> DeliveryAgentPosition | None:
    return DeliveryAgentPosition.query.filter_by(agent_id=agent_id).first()


def trail_for_agent(agent_id: int, minutes: int = 30) -> list[dict]:
    cutoff = datetime.utcnow() - timedelta(minutes=minutes)
    rows = (
        DeliveryAgentTrail.query.filter(
            DeliveryAgentTrail.agent_id == agent_id,
            DeliveryAgentTrail.recorded_at >= cutoff,
        )
        .order_by(DeliveryAgentTrail.recorded_at.asc())
        .all()
    )
    return [
        {
            "lat": row.lat,
            "lng": row.lng,
            "at": row.recorded_at.isoformat() + "Z" if row.recorded_at else "",
        }
        for row in rows
    ]


def live_agents_payload(pending_statuses: tuple[str, ...] = ("تم الطلب", "جاري الشحن", "قيد الشحن")) -> list[dict]:
    """Serialize agent pins for the staff live map."""
    from models.delivery_agent import DeliveryAgent
    from models.invoice import Invoice
    from sqlalchemy import func

    ensure_agent_location_schema()
    now = datetime.utcnow()
    positions = {row.agent_id: row for row in DeliveryAgentPosition.query.all()}
    if not positions:
        return []

    agents = {
        agent.id: agent
        for agent in DeliveryAgent.query.filter(DeliveryAgent.id.in_(list(positions.keys()))).all()
    }
    counts = dict(
        db.session.query(Invoice.delivery_agent_id, func.count(Invoice.id))
        .filter(
            Invoice.delivery_agent_id.in_(list(positions.keys())),
            Invoice.status.in_(pending_statuses),
        )
        .group_by(Invoice.delivery_agent_id)
        .all()
    )

    payload = []
    for agent_id, position in positions.items():
        agent = agents.get(agent_id)
        if not agent or not getattr(agent, "is_active", True):
            continue
        age = (now - position.updated_at).total_seconds() if position.updated_at else 10**9
        if age < 45:
            freshness = "live"
        elif age < 180:
            freshness = "recent"
        else:
            freshness = "stale"
        payload.append({
            "agent_id": agent_id,
            "name": agent.name,
            "lat": position.lat,
            "lng": position.lng,
            "accuracy": position.accuracy,
            "heading": position.heading,
            "speed": position.speed,
            "updated_at": position.updated_at.isoformat() + "Z" if position.updated_at else "",
            "age_seconds": int(age),
            "freshness": freshness,
            "active_orders": int(counts.get(agent_id) or 0),
            "trail": trail_for_agent(agent_id),
        })
    payload.sort(key=lambda item: item["age_seconds"])
    return payload


def _arabic_step(step: dict) -> str:
    maneuver = step.get("maneuver") or {}
    kind = maneuver.get("type") or ""
    modifier = maneuver.get("modifier") or ""
    if kind in {"arrive", "arrive left", "arrive right"}:
        return "وصلت إلى الوجهة"
    phrase = _MANEUVERS.get(modifier) or _MANEUVERS.get(kind) or "استمر"
    meters = int(step.get("distance") or 0)
    if meters >= 1000:
        return f"{phrase} لمسافة {meters / 1000:.1f} كم"
    if meters > 0:
        return f"{phrase} بعد {meters} متر"
    return phrase


def driving_route(lat1: float, lng1: float, lat2: float, lng2: float) -> dict:
    url = _OSRM.format(lng1=lng1, lat1=lat1, lng2=lng2, lat2=lat2)
    url += "?overview=full&steps=true&geometries=geojson"
    request = Request(url, headers={"User-Agent": "FinoraDelivery/1.0"})
    try:
        with urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (URLError, TimeoutError, json.JSONDecodeError, OSError):
        return {"ok": False, "error": "تعذر حساب الطريق"}
    routes = payload.get("routes") or []
    if payload.get("code") != "Ok" or not routes:
        return {"ok": False, "error": "تعذر حساب الطريق"}
    route = routes[0]
    line = [
        [point[1], point[0]]
        for point in ((route.get("geometry") or {}).get("coordinates") or [])
        if isinstance(point, list) and len(point) >= 2
    ]
    steps = []
    for leg in route.get("legs") or []:
        for step in leg.get("steps") or []:
            loc = ((step.get("maneuver") or {}).get("location") or [None, None])
            if len(loc) < 2:
                continue
            steps.append({
                "lat": loc[1],
                "lng": loc[0],
                "instruction": _arabic_step(step),
                "distance": int(step.get("distance") or 0),
            })
    return {
        "ok": True,
        "distance": int(route.get("distance") or 0),
        "duration": int(route.get("duration") or 0),
        "line": line,
        "steps": steps,
    }
