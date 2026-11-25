import uuid

from fastapi import HTTPException

from app.core import access, team


def hidden_tools(connection):
    return {row[0] for row in connection.execute("SELECT tool_id FROM team_hidden_tools")}


def set_tool_enabled(actor, tool_id, enabled):
    with access.job_db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        team.require_active(connection, actor, "owner")
        if enabled:
            connection.execute("DELETE FROM team_hidden_tools WHERE tool_id=?", (tool_id,))
        else:
            connection.execute("INSERT OR IGNORE INTO team_hidden_tools (tool_id) VALUES (?)", (tool_id,))


def user_groups(connection, user_id):
    return [dict(row) for row in connection.execute("""SELECT g.id, g.name, g.restricted
        FROM team_groups g JOIN team_group_members m ON m.group_id=g.id
        WHERE m.user_id=? ORDER BY g.name_key""", (user_id,))]


def user_overrides(connection, user_id):
    return dict(connection.execute("SELECT tool_id, allowed FROM team_user_tools WHERE user_id=?", (user_id,)))


def available_tools(connection, user_id, configured_ids):
    groups = user_groups(connection, user_id)
    if groups and all(group["restricted"] for group in groups):
        allowed = {row[0] for row in connection.execute("""SELECT t.tool_id FROM team_group_tools t
            JOIN team_group_members m ON m.group_id=t.group_id WHERE m.user_id=?""", (user_id,))}
    else:
        allowed = set(configured_ids)
    overrides = user_overrides(connection, user_id)
    allowed.update(tool_id for tool_id, grant in overrides.items() if grant)
    allowed.difference_update(tool_id for tool_id, grant in overrides.items() if not grant)
    return allowed.intersection(configured_ids) - hidden_tools(connection)


def require_tool_enabled(connection, user_id, tool_id):
    if tool_id not in available_tools(connection, user_id, {tool_id}):
        raise HTTPException(403, "This tool is unavailable for your account.")


def set_user_overrides(actor, user_id, overrides):
    with access.job_db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        team.require_active(connection, actor, "owner")
        if not team.get_user(connection, user_id):
            raise HTTPException(404, "Team user was not found.")
        connection.execute("DELETE FROM team_user_tools WHERE user_id=?", (user_id,))
        connection.executemany("INSERT INTO team_user_tools (user_id, tool_id, allowed) VALUES (?, ?, ?)",
                               ((user_id, tool_id, grant) for tool_id, grant in overrides.items()))


def list_groups(connection, *, editable):
    groups = {row["id"]: dict(row) for row in connection.execute("""SELECT g.id, g.name, g.restricted,
        COUNT(m.user_id) AS member_count FROM team_groups g LEFT JOIN team_group_members m ON m.group_id=g.id
        GROUP BY g.id ORDER BY g.name_key""")}
    if editable:
        for group in groups.values():
            group["tool_ids"] = []
        for group_id, tool_id in connection.execute("SELECT group_id, tool_id FROM team_group_tools"):
            groups[group_id]["tool_ids"].append(tool_id)
    return list(groups.values())


def save_group(actor, group_id, name, restricted, tool_ids):
    name = name.strip()
    if not name:
        raise HTTPException(400, "Enter a team name.")
    name_key = name.casefold()
    with access.job_db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        team.require_active(connection, actor, "owner")
        existing = connection.execute("SELECT id FROM team_groups WHERE name_key=?", (name_key,)).fetchone()
        if existing and existing["id"] != group_id:
            raise HTTPException(409, "That team name is already in use.")
        if group_id is None:
            group_id = uuid.uuid4().hex
            connection.execute("INSERT INTO team_groups (id, name, name_key, restricted) VALUES (?, ?, ?, ?)",
                               (group_id, name, name_key, restricted))
        else:
            changed = connection.execute("UPDATE team_groups SET name=?, name_key=?, restricted=? WHERE id=?",
                                         (name, name_key, restricted, group_id))
            if not changed.rowcount:
                raise HTTPException(404, "Team was not found.")
            connection.execute("DELETE FROM team_group_tools WHERE group_id=?", (group_id,))
        if restricted:
            connection.executemany("INSERT INTO team_group_tools (group_id, tool_id) VALUES (?, ?)",
                                   ((group_id, tool_id) for tool_id in tool_ids))
        return {"id": group_id, "name": name}


def change_memberships(actor, action, group_id, user_ids, source_id=None):
    if action == "move" and (not source_id or source_id == group_id):
        raise HTTPException(400, "Choose different source and destination teams.")
    with access.job_db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        team.require_active(connection, actor, "owner")
        groups = {row[0] for row in connection.execute("SELECT id FROM team_groups")}
        if group_id not in groups or (action == "move" and source_id not in groups):
            raise HTTPException(404, "Team was not found.")
        users = {row[0] for row in connection.execute("SELECT id FROM team_users WHERE removed=0")}
        if user_ids - users:
            raise HTTPException(409, "Some selected accounts have been removed. Clear the selection and select accounts again.")
        if action == "move":
            current = {row[0] for row in connection.execute("SELECT user_id FROM team_group_members WHERE group_id=?", (source_id,))}
            user_ids = user_ids & current
        if action == "remove":
            return connection.executemany("DELETE FROM team_group_members WHERE group_id=? AND user_id=?",
                                          ((group_id, user_id) for user_id in user_ids)).rowcount
        added = connection.executemany("INSERT OR IGNORE INTO team_group_members (group_id, user_id) VALUES (?, ?)",
                                       ((group_id, user_id) for user_id in user_ids)).rowcount
        if action == "move":
            return connection.executemany("DELETE FROM team_group_members WHERE group_id=? AND user_id=?",
                                          ((source_id, user_id) for user_id in user_ids)).rowcount
        return added


def remove_group(actor, group_id):
    with access.job_db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        team.require_active(connection, actor, "owner")
        if not connection.execute("DELETE FROM team_groups WHERE id=?", (group_id,)).rowcount:
            raise HTTPException(404, "Team was not found.")
