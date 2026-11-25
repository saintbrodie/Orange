import asyncio
import hashlib
import re
import secrets
import time
import uuid
from functools import lru_cache
from threading import BoundedSemaphore

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool

from app.core import access

SESSION_COOKIE = "orange_team"
SESSION_MAX_AGE = 12 * 3600
SESSION_IDLE = 3600
INVITE_MAX_AGE = 24 * 3600
MEMBER_INVITE_PREFIX = "member."
SHARED_INVITE_PREFIX = "team."
STREAM_SESSION_CHECK_SECONDS = 5
ROLES = {"owner", "operator", "member"}
_HANDLE = re.compile(r"[a-z0-9][a-z0-9._-]{2,63}")
_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")
_PASSWORDS = PasswordHasher()
_HASH_SLOTS = BoundedSemaphore(4)
_USER_FIELDS = "id, handle, role, enabled, created_at, password_hash IS NOT NULL AS accepted"


def init_team():
    access.init_job_access()
    with access.job_db() as connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS team_users (
                id TEXT PRIMARY KEY, handle TEXT NOT NULL UNIQUE, password_hash TEXT,
                role TEXT NOT NULL CHECK(role IN ('owner', 'operator', 'member')),
                enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)), created_at INTEGER
            );
            CREATE TABLE IF NOT EXISTS team_sessions (
                digest TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES team_users(id),
                expires INTEGER NOT NULL, last_seen INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_team_sessions_user ON team_sessions(user_id);
            CREATE TABLE IF NOT EXISTS team_invitations (
                digest TEXT PRIMARY KEY, user_id TEXT NOT NULL UNIQUE REFERENCES team_users(id),
                expires INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS team_member_invites (
                digest TEXT PRIMARY KEY, expires INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS team_shared_invites (
                digest TEXT PRIMARY KEY, expires INTEGER NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('owner', 'operator', 'member'))
            );
            CREATE TABLE IF NOT EXISTS team_hidden_tools (tool_id TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS team_groups (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE,
                restricted INTEGER NOT NULL CHECK(restricted IN (0, 1))
            );
            CREATE TABLE IF NOT EXISTS team_group_members (
                group_id TEXT NOT NULL REFERENCES team_groups(id) ON DELETE CASCADE,
                user_id TEXT NOT NULL REFERENCES team_users(id), PRIMARY KEY(group_id, user_id)
            );
            CREATE INDEX IF NOT EXISTS idx_team_group_member ON team_group_members(user_id);
            CREATE TABLE IF NOT EXISTS team_group_tools (
                group_id TEXT NOT NULL REFERENCES team_groups(id) ON DELETE CASCADE,
                tool_id TEXT NOT NULL, PRIMARY KEY(group_id, tool_id)
            );
            CREATE TABLE IF NOT EXISTS team_user_tools (
                user_id TEXT NOT NULL REFERENCES team_users(id),
                tool_id TEXT NOT NULL, allowed INTEGER NOT NULL CHECK(allowed IN (0, 1)), PRIMARY KEY(user_id, tool_id)
            );
        """)
        connection.execute("BEGIN IMMEDIATE")
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(team_users)")}
        if "removed" not in columns:
            connection.execute("ALTER TABLE team_users ADD COLUMN removed INTEGER NOT NULL DEFAULT 0 CHECK(removed IN (0, 1))")
        if "created_at" not in columns:
            connection.execute("ALTER TABLE team_users ADD COLUMN created_at INTEGER")


def normalize_handle(handle):
    value = handle.strip().lower()
    if not _HANDLE.fullmatch(value):
        raise HTTPException(400, "Use a username with 3–64 letters, digits, periods, underscores, or hyphens. Start with a letter or digit.")
    return value


def _digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def validate_password(password):
    if not 12 <= len(password) <= 256:
        raise HTTPException(400, "Use a password between 12 and 256 characters.")


def _password_hash(password):
    validate_password(password)
    with _HASH_SLOTS:
        return _PASSWORDS.hash(password)


@lru_cache(maxsize=1)
def _dummy_hash():
    return _password_hash(secrets.token_urlsafe(32))


def _owner_count(connection):
    return connection.execute("""SELECT COUNT(*) FROM team_users
        WHERE role='owner' AND enabled=1 AND password_hash IS NOT NULL""").fetchone()[0]


def is_last_active_owner(connection, user):
    return bool(user["role"] == "owner" and user["enabled"] and user["accepted"] and _owner_count(connection) == 1)


def has_active_owner():
    if not access.JOB_ACCESS_PATH.is_file():
        return False
    with access.job_db() as connection:
        users_exist = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='team_users'").fetchone()
        return bool(users_exist and _owner_count(connection))


def bootstrap_owner(handle, password, *, recover=False):
    handle = normalize_handle(handle)
    password_hash = _password_hash(password)
    with access.job_db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        if recover:
            owner = connection.execute("SELECT id FROM team_users WHERE handle=? AND role='owner'", (handle,)).fetchone()
            if not owner:
                raise HTTPException(404, "That Team owner does not exist.")
            connection.execute("UPDATE team_users SET password_hash=?, enabled=1 WHERE id=?", (password_hash, owner["id"]))
            _revoke_user(connection, owner["id"])
        else:
            if _owner_count(connection):
                raise HTTPException(409, "A Team owner already exists. Sign in to invite users or use host recovery.")
            _insert_user(connection, handle, password_hash, "owner")


def _insert_user(connection, handle, password_hash, role):
    if connection.execute("SELECT 1 FROM team_users WHERE handle=?", (handle,)).fetchone():
        raise HTTPException(409, "That username is already in use.")
    user_id = uuid.uuid4().hex
    connection.execute("INSERT INTO team_users (id, handle, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
                       (user_id, handle, password_hash, role, int(time.time())))
    return user_id


def _revoke_user(connection, user_id):
    connection.execute("DELETE FROM team_sessions WHERE user_id=?", (user_id,))
    connection.execute("DELETE FROM team_invitations WHERE user_id=?", (user_id,))


def get_user(connection, user_id):
    return connection.execute(f"SELECT {_USER_FIELDS} FROM team_users WHERE id=? AND removed=0", (user_id,)).fetchone()


def require_active(connection, user_id, *roles):
    row = get_user(connection, user_id)
    if not row or not row["enabled"] or not row["accepted"]:
        raise HTTPException(401, "Sign in to continue.")
    if roles and row["role"] not in roles:
        raise HTTPException(403, "Your role does not have access to this action.")
    return row


def _new_session(connection, user_id):
    now = int(time.time())
    token = secrets.token_urlsafe(32)
    connection.execute("DELETE FROM team_sessions WHERE expires<=? OR last_seen<=?", (now, now - SESSION_IDLE))
    connection.execute("INSERT INTO team_sessions (digest, user_id, expires, last_seen) VALUES (?, ?, ?, ?)",
                       (_digest(token), user_id, now + SESSION_MAX_AGE, now))
    return token


def login(handle, password):
    with access.job_db() as connection:
        user = connection.execute("SELECT * FROM team_users WHERE handle=?", (handle.strip().lower(),)).fetchone()
    password_hash = user["password_hash"] if user and user["password_hash"] else _dummy_hash()
    try:
        with _HASH_SLOTS:
            _PASSWORDS.verify(password_hash, password)
    except (InvalidHashError, VerificationError):
        raise HTTPException(401, "The username or password is incorrect.") from None
    if not user or not user["enabled"] or not user["password_hash"]:
        raise HTTPException(401, "The username or password is incorrect.")
    replacement = _password_hash(password) if _PASSWORDS.check_needs_rehash(password_hash) else password_hash
    with access.job_db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        updated = connection.execute("UPDATE team_users SET password_hash=? WHERE id=? AND enabled=1 AND password_hash=?",
                                     (replacement, user["id"], password_hash))
        if not updated.rowcount:
            raise HTTPException(401, "The username or password is incorrect.")
        return _new_session(connection, user["id"])


def current_user(token, *, touch=True):
    if not token or not _TOKEN.fullmatch(token):
        return None
    now = int(time.time())
    digest = _digest(token)
    with access.job_db() as connection:
        row = connection.execute("""SELECT u.id, u.handle, u.role, s.last_seen FROM team_sessions s
            JOIN team_users u ON u.id=s.user_id
            WHERE s.digest=? AND s.expires>? AND s.last_seen>? AND u.enabled=1 AND u.password_hash IS NOT NULL""",
            (digest, now, now - SESSION_IDLE),
        ).fetchone()
        if row is None:
            return None
        if touch and now - row["last_seen"] >= 60:
            connection.execute("UPDATE team_sessions SET last_seen=? WHERE digest=? AND last_seen<?", (now, digest, now))
        return {key: row[key] for key in ("id", "handle", "role")}


def logout(token):
    if token and _TOKEN.fullmatch(token):
        with access.job_db() as connection:
            connection.execute("DELETE FROM team_sessions WHERE digest=?", (_digest(token),))


def session_cookie(request):
    return f"__Host-{SESSION_COOKIE}" if request.url.scheme == "https" else SESSION_COOKIE


def session_token(request):
    return request.cookies.get(session_cookie(request))


def request_user(request, *roles):
    user = getattr(request.state, "team_user", None) if request else None
    if not user:
        raise HTTPException(401, "Sign in to continue.")
    if roles and user["role"] not in roles:
        raise HTTPException(403, "Your role does not have access to this action.")
    return user


async def guard_events(request, events):
    token = session_token(request)
    next_check = 0.0
    event = asyncio.create_task(anext(events))
    try:
        while True:
            done, _ = await asyncio.wait((event,), timeout=STREAM_SESSION_CHECK_SECONDS)
            now = time.monotonic()
            if now >= next_check:
                if not await run_in_threadpool(current_user, token, touch=False):
                    return
                next_check = now + STREAM_SESSION_CHECK_SECONDS
            if done:
                yield event.result()
                event = asyncio.create_task(anext(events))
    except StopAsyncIteration:
        return
    finally:
        if not event.done():
            event.cancel()
        await asyncio.gather(event, return_exceptions=True)
        await events.aclose()


def _create_invitation(connection, user_id):
    token = secrets.token_urlsafe(32)
    expires = int(time.time()) + INVITE_MAX_AGE
    connection.execute("INSERT INTO team_invitations (digest, user_id, expires) VALUES (?, ?, ?)",
                       (_digest(token), user_id, expires))
    return {"token": token, "expires": expires}


def _require_user_creator(connection, actor, role):
    if role not in ROLES:
        raise HTTPException(400, "Choose a valid Team role.")
    user = require_active(connection, actor, "owner", "operator")
    if user["role"] == "operator" and role != "member":
        raise HTTPException(403, "Operators can only create Member accounts.")


def create_user(actor, handle, password, role):
    handle = normalize_handle(handle)
    with access.job_db() as connection:
        _require_user_creator(connection, actor, role)
    password_hash = _password_hash(password)
    with access.job_db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        _require_user_creator(connection, actor, role)
        user_id = _insert_user(connection, handle, password_hash, role)
        return {"id": user_id, "handle": handle, "role": role}


def invite(actor, role, expires):
    with access.job_db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        _require_user_creator(connection, actor, role)
        now = int(time.time())
        if expires <= now:
            raise HTTPException(400, "Choose an expiration time in the future.")
        token = SHARED_INVITE_PREFIX + secrets.token_urlsafe(32)
        connection.execute("DELETE FROM team_shared_invites WHERE expires<=?", (now,))
        connection.execute("INSERT INTO team_shared_invites (digest, expires, role) VALUES (?, ?, ?)",
                           (_digest(token), expires, role))
        return {"token": token, "expires": expires}


def accept_invitation(token, password, handle=None):
    prefix, separator, secret = token.rpartition(".")
    prefix += separator
    table = {"": "team_invitations", MEMBER_INVITE_PREFIX: "team_member_invites",
             SHARED_INVITE_PREFIX: "team_shared_invites"}.get(prefix)
    if table is None or not _TOKEN.fullmatch(secret):
        raise HTTPException(400, "This invitation is invalid or has expired.")
    digest = _digest(token)
    with access.job_db() as connection:
        available = connection.execute(f"SELECT 1 FROM {table} WHERE digest=? AND expires>?",
                                       (digest, int(time.time()))).fetchone()
    if not available:
        raise HTTPException(400, "This invitation is invalid or has expired.")
    if prefix:
        if handle is None:
            raise HTTPException(400, "Choose a username to accept this invitation.")
        handle = normalize_handle(handle)
    password_hash = _password_hash(password)
    with access.job_db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        if prefix:
            role_column = "role" if prefix == SHARED_INVITE_PREFIX else "'member'"
            invitation = connection.execute(f"SELECT {role_column} FROM {table} WHERE digest=? AND expires>?",
                                            (digest, int(time.time()))).fetchone()
            if not invitation:
                raise HTTPException(400, "This invitation is invalid or has expired.")
            user_id = _insert_user(connection, handle, password_hash, invitation[0])
            if prefix == MEMBER_INVITE_PREFIX:
                connection.execute("DELETE FROM team_member_invites WHERE digest=?", (digest,))
            return _new_session(connection, user_id)

        user = connection.execute("""SELECT i.user_id FROM team_invitations i JOIN team_users u ON u.id=i.user_id
            WHERE i.digest=? AND i.expires>? AND u.enabled=1 AND u.password_hash IS NULL""",
            (digest, int(time.time())),
        ).fetchone()
        if not user:
            raise HTTPException(400, "This invitation is invalid or has expired.")
        connection.execute("UPDATE team_users SET password_hash=? WHERE id=?", (password_hash, user["user_id"]))
        connection.execute("DELETE FROM team_invitations WHERE digest=?", (digest,))
        return _new_session(connection, user["user_id"])


def change_user(actor, user_id, *, role=None, enabled=None, reset=False):
    with access.job_db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        caller = require_active(connection, actor, "owner", "operator")
        user = get_user(connection, user_id)
        if not user:
            raise HTTPException(404, "Team user was not found.")
        if caller["role"] == "operator" and (user["role"] != "member" or not reset or role is not None or enabled is not None):
            raise HTTPException(403, "Operators can reset Member passwords.")
        new_role = role if role is not None else user["role"]
        new_enabled = enabled if enabled is not None else bool(user["enabled"])
        demoting = new_role != "owner" or not new_enabled or reset
        if demoting and is_last_active_owner(connection, user):
            raise HTTPException(409, "Keep at least one active owner. Use the host recovery command to reset the last owner's password.")
        if reset and not new_enabled:
            raise HTTPException(409, "Enable the account before resetting its password.")
        connection.execute("UPDATE team_users SET role=?, enabled=? WHERE id=?", (new_role, new_enabled, user_id))
        role_changed = new_role != user["role"]
        if reset or not new_enabled or role_changed:
            _revoke_user(connection, user_id)
        # An Operator can reset a Member's password. A promoted Member must
        # choose a fresh password using the invitation issued by the Owner.
        replace_password = reset or (role_changed and user["role"] == "member")
        if replace_password:
            connection.execute("UPDATE team_users SET password_hash=NULL WHERE id=?", (user_id,))
        if new_enabled and (replace_password or (role_changed and not user["accepted"])):
            return _create_invitation(connection, user_id)
        return None


def remove_user(actor, user_id):
    with access.job_db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        caller = require_active(connection, actor, "owner", "operator")
        user = get_user(connection, user_id)
        if not user:
            raise HTTPException(404, "Team user was not found.")
        if caller["role"] == "operator" and user["role"] != "member":
            raise HTTPException(403, "Operators can only remove Member accounts.")
        if is_last_active_owner(connection, user):
            raise HTTPException(409, "Keep at least one active owner.")
        _revoke_user(connection, user_id)
        connection.execute("DELETE FROM team_group_members WHERE user_id=?", (user_id,))
        connection.execute("DELETE FROM team_user_tools WHERE user_id=?", (user_id,))
        # Keep the ID for existing usage records and release the original username.
        connection.execute("""UPDATE team_users SET handle=':' || id, enabled=0, password_hash=NULL, removed=1
            WHERE id=?""", (user_id,))


def list_users(connection):
    return [dict(row) for row in connection.execute(f"""SELECT {_USER_FIELDS},
        (SELECT COUNT(*) FROM generation_access WHERE owner_id=team_users.id) AS generation_count
        FROM team_users WHERE removed=0 ORDER BY handle""")]


def history(connection, user_id):
    return [dict(row) for row in connection.execute("""SELECT id, tool_id, provider, created, output_type, status,
        ((provider <> 'comfyui' AND status <> 'submission_failed') OR prompt_id IS NOT NULL) AS trackable
        FROM generation_access WHERE owner_id=? ORDER BY created DESC, rowid DESC LIMIT 100""", (user_id,))]
