import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING

from fastapi import HTTPException

from app.core import access, team, team_tools

MICROS_PER_USD = 1_000_000
MAX_USD = Decimal("1000000000")


def init_budgets():
    with access.job_db() as connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS team_budget (
                id INTEGER PRIMARY KEY CHECK(id=1), monthly_micros INTEGER NOT NULL
            );
            INSERT OR IGNORE INTO team_budget (id, monthly_micros) VALUES (1, 0);
            CREATE TABLE IF NOT EXISTS team_member_budgets (
                user_id TEXT PRIMARY KEY REFERENCES team_users(id), monthly_micros INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS team_tool_prices (
                tool_id TEXT PRIMARY KEY, price_key TEXT NOT NULL, estimate_micros INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS team_spend (
                job_id TEXT PRIMARY KEY REFERENCES generation_access(id), user_id TEXT NOT NULL REFERENCES team_users(id),
                month TEXT NOT NULL, estimate_micros INTEGER NOT NULL, reported_micros INTEGER,
                state TEXT NOT NULL CHECK(state IN ('reserved','dispatched','estimated','reported','released'))
            );
            CREATE INDEX IF NOT EXISTS idx_team_spend_month ON team_spend(month, user_id);
            CREATE TABLE IF NOT EXISTS team_budget_blocks (
                month TEXT NOT NULL, user_id TEXT NOT NULL REFERENCES team_users(id), count INTEGER NOT NULL,
                PRIMARY KEY(month, user_id)
            );
        """)


def month_key():
    return datetime.now(timezone.utc).strftime("%Y-%m")


def usd_micros(value, *, round_up=False):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("Enter a valid USD amount.") from None
    if not amount.is_finite() or not 0 <= amount <= MAX_USD:
        raise ValueError("Enter a non-negative USD amount up to one billion.")
    scaled = amount * MICROS_PER_USD
    integer = scaled.to_integral_value(rounding=ROUND_CEILING)
    if not round_up and scaled != integer:
        raise ValueError("Use at most six decimal places for USD.")
    return int(integer)


def price_key(tool):
    identity = {field: tool.get(field) for field in ("provider", "model", "api")}
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


def _workspace_limit(connection):
    return connection.execute("SELECT monthly_micros FROM team_budget WHERE id=1").fetchone()[0]


def _member_limit(connection, user_id):
    row = connection.execute("SELECT monthly_micros FROM team_member_budgets WHERE user_id=?", (user_id,)).fetchone()
    return row["monthly_micros"] if row else None


def set_workspace_limit(actor, micros):
    with access.job_db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        team.require_active(connection, actor, "owner")
        connection.execute("UPDATE team_budget SET monthly_micros=? WHERE id=1", (micros,))


def set_member_limit(actor, user_id, micros):
    with access.job_db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        user = team.require_active(connection, actor, "owner", "operator")
        target = team.get_user(connection, user_id)
        if not target:
            raise HTTPException(404, "Team user was not found.")
        if user["role"] == "operator" and target["role"] != "member":
            raise HTTPException(403, "Operators can change budgets for members.")
        if micros is not None and micros > _workspace_limit(connection):
            raise HTTPException(400, "The member budget must fit within the workspace budget.")
        if micros is None:
            connection.execute("DELETE FROM team_member_budgets WHERE user_id=?", (user_id,))
        else:
            connection.execute("""INSERT INTO team_member_budgets (user_id, monthly_micros) VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET monthly_micros=excluded.monthly_micros""", (user_id, micros))


def set_tool_price(actor, tool, micros):
    with access.job_db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        team.require_active(connection, actor, "owner")
        if micros is None:
            connection.execute("DELETE FROM team_tool_prices WHERE tool_id=?", (tool["id"],))
        else:
            connection.execute("""INSERT INTO team_tool_prices (tool_id, price_key, estimate_micros) VALUES (?, ?, ?)
                ON CONFLICT(tool_id) DO UPDATE SET price_key=excluded.price_key, estimate_micros=excluded.estimate_micros""",
                (tool["id"], price_key(tool), micros),
            )


def _totals(connection, month, user_id=None):
    predicate, params = ("AND user_id=?", (month, user_id)) if user_id else ("", (month,))
    return dict(connection.execute(f"""SELECT
        COALESCE(SUM(CASE WHEN state IN ('reserved','dispatched') THEN estimate_micros END),0) AS reserved_micros,
        COALESCE(SUM(CASE WHEN state='estimated' THEN estimate_micros END),0) AS estimated_micros,
        COALESCE(SUM(CASE WHEN state='reported' THEN reported_micros END),0) AS reported_micros
        FROM team_spend WHERE month=? {predicate}""", params).fetchone())


def _block_count(connection, month, user_id=None):
    if user_id:
        row = connection.execute("SELECT count FROM team_budget_blocks WHERE month=? AND user_id=?", (month, user_id)).fetchone()
        return row["count"] if row else 0
    return connection.execute("SELECT COALESCE(SUM(count),0) FROM team_budget_blocks WHERE month=?", (month,)).fetchone()[0]


def _summary(connection, month, limit, user_id=None):
    totals = _totals(connection, month, user_id)
    return {**totals, "limit_micros": limit, "remaining_micros": max(0, limit - sum(totals.values())),
            "blocked": _block_count(connection, month, user_id)}


def reserve_cloud_job(job_id, user_id, tool, output_type):
    month = month_key()
    key = price_key(tool)
    reason = None
    with access.job_db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        team.require_active(connection, user_id)
        team_tools.require_tool_enabled(connection, user_id, tool["id"])
        price = connection.execute("SELECT estimate_micros FROM team_tool_prices WHERE tool_id=? AND price_key=?",
                                   (tool["id"], key)).fetchone()
        if price is None:
            raise HTTPException(403, "This cloud tool needs a current cost estimate from a Team owner.")
        estimate = price["estimate_micros"]
        workspace_limit = _workspace_limit(connection)
        member_limit = _member_limit(connection, user_id)
        if sum(_totals(connection, month).values()) + estimate > workspace_limit:
            reason = "This generation would exceed the workspace's monthly API budget."
        elif member_limit is not None and sum(_totals(connection, month, user_id).values()) + estimate > member_limit:
            reason = "This generation would exceed your monthly API budget."
        if reason:
            connection.execute("""INSERT INTO team_budget_blocks (month, user_id, count) VALUES (?, ?, 1)
                ON CONFLICT(month,user_id) DO UPDATE SET count=count+1""", (month, user_id))
        else:
            access.insert_owned_generation(connection, job_id, user_id, tool["id"], tool["provider"], output_type)
            connection.execute("""INSERT INTO team_spend (job_id, user_id, month, estimate_micros, state)
                VALUES (?, ?, ?, ?, 'reserved')""", (job_id, user_id, month, estimate))
    if reason:
        raise HTTPException(402, reason)
    return estimate


def mark_dispatched(job_id):
    with access.job_db() as connection:
        changed = connection.execute("UPDATE team_spend SET state='dispatched' WHERE job_id=? AND state='reserved'", (job_id,))
        if not changed.rowcount:
            raise RuntimeError("The paid generation has no active reservation.")


def record_job_status(job_id, status, *, terminal=False, reported_micros=None):
    with access.job_db() as connection:
        connection.execute("UPDATE generation_access SET status=? WHERE id=?", (status, job_id))
        if reported_micros is not None:
            connection.execute("""UPDATE team_spend SET state='reported', reported_micros=?
                WHERE job_id=? AND state IN ('dispatched','estimated','reported')""", (reported_micros, job_id))
        if terminal:
            connection.execute("""UPDATE team_spend SET state=CASE state WHEN 'reserved' THEN 'released' ELSE 'estimated' END
                WHERE job_id=? AND state IN ('reserved','dispatched')""", (job_id,))


def reserved_jobs():
    with access.job_db() as connection:
        return [row[0] for row in connection.execute("SELECT job_id FROM team_spend WHERE state='reserved'")]


def account_usage(connection, month, user_id, workspace=None):
    if workspace is None:
        workspace = _summary(connection, month, _workspace_limit(connection))
    workspace_limit = workspace["limit_micros"]
    configured_limit = _member_limit(connection, user_id)
    limit = workspace_limit if configured_limit is None else min(configured_limit, workspace_limit)
    summary = _summary(connection, month, limit, user_id)
    summary["remaining_micros"] = min(summary["remaining_micros"], workspace["remaining_micros"])
    return summary, configured_limit


def report(user, tools, *, include_members=True):
    month = month_key()
    user_id = user["id"]
    with access.job_db() as connection:
        connection.execute("BEGIN")
        workspace = _summary(connection, month, _workspace_limit(connection))
        own, _ = account_usage(connection, month, user_id, workspace)
        result = {"month": month, "currency": "USD", "own": own}
        if user["role"] in {"owner", "operator"}:
            result["workspace"] = workspace
            if include_members:
                result["members"] = []
                for member in team.list_users(connection):
                    summary, limit = account_usage(connection, month, member["id"], workspace)
                    result["members"].append({**member, **summary, "configured_limit_micros": limit})
        if user["role"] == "owner":
            pricing = {row["tool_id"]: row for row in connection.execute("SELECT * FROM team_tool_prices")}
            result["tools"] = []
            for tool in tools:
                if tool.get("provider", "comfyui") == "comfyui":
                    continue
                rate = pricing.get(tool["id"])
                estimate = rate["estimate_micros"] if rate and rate["price_key"] == price_key(tool) else None
                result["tools"].append({"id": tool["id"], "name": tool.get("name"), "provider": tool["provider"],
                                        "model": tool.get("model"), "estimate_micros": estimate})
    return result
