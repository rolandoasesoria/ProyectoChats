"""Métricas para el panel de actividad."""
from collections import defaultdict
from datetime import date, datetime, timedelta

from . import search, settings
from .db import Conn, get_conn
from .repositories import metrics as repo

CHANNELS = ("email", "telegram", "whatsapp")  # orden fijo de apilado (y de color) en los gráficos


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace(" ", "T"))


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def response_times(since: str, conn: Conn) -> list[dict]:
    """Tiempos de primera respuesta: desde el primer mensaje del cliente sin contestar hasta la siguiente
    respuesta del equipo en la misma conversación."""
    msgs = repo.messages_in_order(conn)
    result, pending, current = [], None, None
    for m in msgs:
        if m["conversation_id"] != current:
            current, pending = m["conversation_id"], None
        if m["direction"] == "in" and pending is None:
            pending = m
        elif m["direction"] == "out" and pending is not None:
            if pending["sent_at"] >= since:
                hours = (_parse(m["sent_at"]) - _parse(pending["sent_at"])).total_seconds() / 3600
                result.append({"owner_user_id": pending["owner_user_id"], "channel": pending["channel"],
                               "hours": max(0.0, hours)})
            pending = None
    return result


def _within(values: list[float], limit: float) -> int | None:
    """Porcentaje de respuestas dentro del plazo (None si no hay respuestas)."""
    return round(100 * sum(1 for v in values if v <= limit) / len(values)) if values else None


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2


def dashboard(days: int, include_people: bool) -> dict:
    today = date.today()
    since_day = today - timedelta(days=days - 1)
    since = since_day.isoformat()
    with get_conn() as conn:
        received = repo.received_by_day_and_channel(conn, since)
        sent = repo.count_sent(conn, since)
        active_clients = repo.count_active_clients(conn, since)
        by_status = repo.clients_by_status(conn)
        users = repo.active_users(conn)
        tasks = repo.open_tasks(conn)
        responsible = repo.clients_per_assignee(conn)
        times = response_times(since, conn)
    sla = settings.get("sla_hours")

    # Mensajes recibidos por semana y canal (semanas completas del periodo, aunque estén vacías).
    weeks: dict[str, dict[str, int]] = {}
    w = _week_start(since_day)
    while w <= today:
        weeks[w.isoformat()] = {ch: 0 for ch in CHANNELS}
        w += timedelta(days=7)
    for r in received:
        key = _week_start(date.fromisoformat(r["day"])).isoformat()
        if key in weeks:
            weeks[key][r["channel"] if r["channel"] in CHANNELS else "email"] += r["n"]

    today_s = today.isoformat()
    result = {
        "days": days,
        "totals": {
            "received": sum(r["n"] for r in received),
            "sent": sent,
            "active_clients": active_clients,
            "median_response_hours": _median([t["hours"] for t in times]),
            "within_sla_pct": _within([t["hours"] for t in times], sla),
            "sla_hours": sla,
            "open_tasks": len(tasks),
            "overdue_tasks": sum(1 for t in tasks if t["due_date"] and t["due_date"] < today_s),
        },
        "channels": list(CHANNELS),
        "weekly": [{"week": k, **v} for k, v in weeks.items()],
        "clients_by_status": {s: by_status.get(s, 0) for s in ("lead", "active", "issue", "inactive")},
    }
    if include_people:
        waiting = defaultdict(int)
        for item in search.unanswered(0, "team"):
            waiting[item["owner"]] += 1
        per_user_times = defaultdict(list)
        for t in times:
            per_user_times[t["owner_user_id"]].append(t["hours"])
        result["people"] = [{
            "name": u["name"],
            "median_response_hours": _median(per_user_times[u["id"]]),
            "within_sla_pct": _within(per_user_times[u["id"]], sla),
            "responses": len(per_user_times[u["id"]]),
            "waiting": waiting[u["name"]],
            "open_tasks": sum(1 for t in tasks if t["assignee_user_id"] == u["id"]),
            "overdue_tasks": sum(1 for t in tasks if t["assignee_user_id"] == u["id"] and t["due_date"] and t["due_date"] < today_s),
            "clients": responsible.get(u["id"], 0),
        } for u in users]
    return result
