_STATUS = "CASE WHEN u.enabled=0 THEN 'disabled' WHEN u.password_hash IS NULL THEN 'pending' ELSE 'active' END"
_COUNT = "(SELECT COUNT(*) FROM generation_access WHERE owner_id=u.id)"
_FIRST_TEAM = """(SELECT MIN(g.name_key) FROM team_groups g JOIN team_group_members m ON m.group_id=g.id
    WHERE m.user_id=u.id)"""
_SORT_FIELDS = {"user": "u.handle", "role": "u.role", "status": _STATUS, "team": _FIRST_TEAM,
                "date": "u.created_at", "generations": _COUNT}


def find_accounts(connection, filters):
    conditions = ["u.removed=0"]
    params = []
    if query := filters.query.strip().lower():
        conditions.append("instr(u.handle, ?) > 0")
        params.append(query)
    if filters.team == "unassigned":
        conditions.append("NOT EXISTS (SELECT 1 FROM team_group_members m WHERE m.user_id=u.id)")
    elif filters.team:
        conditions.append("EXISTS (SELECT 1 FROM team_group_members m WHERE m.user_id=u.id AND m.group_id=?)")
        params.append(filters.team)
    if filters.role:
        conditions.append("u.role=?")
        params.append(filters.role)
    if filters.status:
        conditions.append(f"{_STATUS}=?")
        params.append(filters.status)
    where = " AND ".join(conditions)
    if filters.selection:
        return {"ids": [row[0] for row in connection.execute(f"SELECT u.id FROM team_users u WHERE {where}", params)]}

    total = connection.execute(f"SELECT COUNT(*) FROM team_users u WHERE {where}", params).fetchone()[0]
    page = min(filters.page, max(1, (total + filters.page_size - 1) // filters.page_size))
    sort = _SORT_FIELDS[filters.sort]
    order = "DESC" if filters.descending else "ASC"
    # Keep missing teams and unknown creation dates at the end in both directions.
    missing = f"{sort} IS NULL, " if filters.sort in {"team", "date"} else ""
    results = connection.execute(f"""SELECT u.id, u.handle, u.role, u.enabled, u.created_at,
        u.password_hash IS NOT NULL AS accepted, {_COUNT} AS generation_count FROM team_users u
        WHERE {where} ORDER BY {missing}{sort} {order}, u.handle ASC LIMIT ? OFFSET ?""",
        (*params, filters.page_size, (page - 1) * filters.page_size))
    accounts = {row["id"]: {**dict(row), "teams": []} for row in results}
    if accounts:
        slots = ",".join("?" for _ in accounts)
        for row in connection.execute(f"""SELECT m.user_id, g.id, g.name FROM team_group_members m
            JOIN team_groups g ON g.id=m.group_id WHERE m.user_id IN ({slots}) ORDER BY g.name_key""", tuple(accounts)):
            accounts[row["user_id"]]["teams"].append({"id": row["id"], "name": row["name"]})
    return {"accounts": list(accounts.values()), "total": total, "page": page, "page_size": filters.page_size}
