from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.core import access, budgets, team, team_directory, team_tools
from app.core.config import get_tool_settings, load_config
from app.core.rate_limit import SlidingWindowRateLimiter

router = APIRouter(prefix="/api/team")
_AUTH_LIMIT = SlidingWindowRateLimiter()
Role = Literal["owner", "operator", "member"]


class SignIn(BaseModel):
    handle: str = Field(max_length=64)
    password: str = Field(max_length=256)


class NewUser(SignIn):
    role: Role = "member"


class Invitation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expires: int = Field(strict=True, gt=0, le=253402300799)
    role: Role = "member"


class AcceptInvitation(BaseModel):
    token: str = Field(max_length=100)
    password: str = Field(max_length=256)
    handle: str | None = Field(default=None, max_length=64)


class UserChange(BaseModel):
    role: Role | None = None
    enabled: bool | None = None
    reset: bool = False


class Amount(BaseModel):
    usd: str | None = Field(max_length=32)


class Availability(BaseModel):
    enabled: bool


class GroupSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=80)
    restricted: bool
    tool_ids: set[str]


class UserToolSettings(BaseModel):
    overrides: dict[str, Literal["allow", "deny"]]


class AccountFilters(BaseModel):
    query: str = Field(default="", max_length=64)
    team: str = Field(default="", max_length=64)
    role: Role | None = None
    status: Literal["active", "disabled", "pending"] | None = None
    sort: Literal["user", "role", "status", "team", "date", "generations"] = "user"
    descending: bool = False
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=25, ge=1, le=100)
    selection: bool = False


class MembershipChange(BaseModel):
    action: Literal["add", "remove", "move"]
    team_id: str
    user_ids: set[str] = Field(min_length=1)
    source_team_id: str | None = None


def _require_team():
    if not access.is_team():
        raise HTTPException(404, "Team mode is unavailable.")


def _limit_auth(request):
    peer = request.client.host if request.client else "unknown"
    if not _AUTH_LIMIT.allow(f"peer:{peer}", 15) or not _AUTH_LIMIT.allow("all", 100):
        raise HTTPException(429, "Too many sign-in attempts. Try again in a minute.")


def _set_session(request, response, token):
    team.logout(team.session_token(request))
    response.set_cookie(team.session_cookie(request), token, max_age=team.SESSION_MAX_AGE, httponly=True,
                        secure=request.url.scheme == "https", samesite="strict")
    return {"status": "ok"}


def _micros(amount):
    try:
        return budgets.usd_micros(amount.usd) if amount.usd is not None else None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


def _catalog(connection):
    hidden = team_tools.hidden_tools(connection)
    return [{"id": tool["id"], "name": tool.get("name") or tool["id"], "provider": tool.get("provider", "comfyui"),
             "enabled": tool["id"] not in hidden}
            for tool in load_config().get("tools", [])]


def _validate_tools(tool_ids):
    if set(tool_ids) - {tool["id"] for tool in load_config().get("tools", [])}:
        raise HTTPException(400, "One or more selected tools are no longer configured.")


@router.get("/session")
def session(request: Request):
    _require_team()
    return {"user": getattr(request.state, "team_user", None)}


@router.post("/login")
def login(payload: SignIn, request: Request, response: Response):
    _require_team()
    _limit_auth(request)
    return _set_session(request, response, team.login(payload.handle, payload.password))


@router.post("/logout")
def logout(request: Request, response: Response):
    _require_team()
    team.logout(team.session_token(request))
    response.delete_cookie(team.session_cookie(request), secure=request.url.scheme == "https", httponly=True, samesite="strict")
    return {"status": "ok"}


@router.post("/accept-invitation")
def accept_invitation(payload: AcceptInvitation, request: Request, response: Response):
    _require_team()
    _limit_auth(request)
    return _set_session(request, response, team.accept_invitation(payload.token, payload.password, payload.handle))


@router.post("/invitations", status_code=201)
def invite(payload: Invitation, request: Request):
    _require_team()
    user = team.request_user(request, "owner", "operator")
    return team.invite(user["id"], payload.role, payload.expires)


@router.post("/users", status_code=201)
def create_user(payload: NewUser, request: Request):
    _require_team()
    user = team.request_user(request, "owner", "operator")
    return team.create_user(user["id"], payload.handle, payload.password, payload.role)


@router.get("/accounts")
def list_accounts(request: Request, filters: AccountFilters = Depends()):
    _require_team()
    roles = ("owner",) if filters.selection else ("owner", "operator")
    actor = team.request_user(request, *roles)
    with access.job_db() as connection:
        connection.execute("BEGIN")
        team.require_active(connection, actor["id"], *roles)
        return team_directory.find_accounts(connection, filters)


@router.put("/memberships")
def update_memberships(payload: MembershipChange, request: Request):
    _require_team()
    actor = team.request_user(request, "owner")
    updated = team_tools.change_memberships(actor["id"], payload.action, payload.team_id, payload.user_ids, payload.source_team_id)
    return {"updated": updated}


@router.get("/users/{user_id}")
def user_details(user_id: str, request: Request):
    _require_team()
    actor = team.request_user(request, "owner", "operator")
    with access.job_db() as connection:
        connection.execute("BEGIN")
        staff = team.require_active(connection, actor["id"], "owner", "operator")
        user = team.get_user(connection, user_id)
        if not user:
            raise HTTPException(404, "Team user was not found.")
        owner = staff["role"] == "owner"
        can_manage = owner or user["role"] == "member"
        if not can_manage and user_id != staff["id"]:
            raise HTTPException(403, "Operators can view Member accounts and their own account.")
        protected = team.is_last_active_owner(connection, user)
        month = budgets.month_key()
        usage, limit = budgets.account_usage(connection, month, user_id)
        fields = ("tool_id", "provider", "created", "output_type", "status")
        jobs = [{key: job[key] for key in fields} for job in team.history(connection, user_id)]
        catalog = _catalog(connection)
        available = team_tools.available_tools(connection, user_id, {tool["id"] for tool in catalog})
        overrides = team_tools.user_overrides(connection, user_id)
        for tool in catalog:
            tool["available"] = tool["id"] in available
            grant = overrides.get(tool["id"])
            tool["override"] = "inherit" if grant is None else "allow" if grant else "deny"
        return {"user": dict(user), "month": month, "usage": usage, "configured_limit_micros": limit, "jobs": jobs,
                "teams": team_tools.user_groups(connection, user_id), "tools": catalog, "can_edit_tools": owner,
                "permissions": {"budget": can_manage, "role": owner and not protected, "enable": owner and not protected,
                                "reset": can_manage and bool(user["enabled"]) and not protected,
                                "remove": can_manage and not protected}}


@router.put("/users/{user_id}/tools")
def set_user_tools(user_id: str, payload: UserToolSettings, request: Request):
    _require_team()
    actor = team.request_user(request, "owner")
    _validate_tools(payload.overrides)
    team_tools.set_user_overrides(actor["id"], user_id, {key: value == "allow" for key, value in payload.overrides.items()})
    return {"status": "ok"}


@router.patch("/users/{user_id}")
def change_user(user_id: str, payload: UserChange, request: Request):
    _require_team()
    user = team.request_user(request, "owner", "operator")
    invite = team.change_user(user["id"], user_id, role=payload.role, enabled=payload.enabled, reset=payload.reset)
    return {"invitation": invite}


@router.delete("/users/{user_id}", status_code=204)
def remove_user(user_id: str, request: Request):
    _require_team()
    user = team.request_user(request, "owner", "operator")
    team.remove_user(user["id"], user_id)
    return Response(status_code=204)


@router.get("/generations")
def generations(request: Request):
    _require_team()
    user = team.request_user(request)
    with access.job_db() as connection:
        return {"jobs": team.history(connection, user["id"])}


@router.get("/spend")
def spend(request: Request, include_members: bool = True):
    _require_team()
    user = team.request_user(request)
    tools = load_config().get("tools", []) if user["role"] == "owner" else []
    return budgets.report(user, tools, include_members=include_members)


@router.put("/budgets/workspace")
def workspace_budget(payload: Amount, request: Request):
    _require_team()
    user = team.request_user(request, "owner")
    micros = _micros(payload)
    if micros is None:
        raise HTTPException(400, "Set a workspace budget in USD. Use zero to pause paid generation.")
    budgets.set_workspace_limit(user["id"], micros)
    return {"status": "ok"}


@router.put("/budgets/members/{user_id}")
def member_budget(user_id: str, payload: Amount, request: Request):
    _require_team()
    user = team.request_user(request, "owner", "operator")
    budgets.set_member_limit(user["id"], user_id, _micros(payload))
    return {"status": "ok"}


@router.put("/budgets/tools/{tool_id}")
def tool_price(tool_id: str, payload: Amount, request: Request):
    _require_team()
    user = team.request_user(request, "owner")
    tool = get_tool_settings(tool_id)
    if not tool or tool.get("provider", "comfyui") == "comfyui":
        raise HTTPException(404, "Cloud generation tool was not found.")
    budgets.set_tool_price(user["id"], tool, _micros(payload))
    return {"status": "ok"}


@router.get("/tools")
def list_tools(request: Request):
    _require_team()
    team.request_user(request, "owner", "operator")
    with access.job_db() as connection:
        return {"tools": _catalog(connection)}


@router.put("/tools/{tool_id}")
def set_tool_availability(tool_id: str, payload: Availability, request: Request):
    _require_team()
    user = team.request_user(request, "owner")
    if not get_tool_settings(tool_id):
        raise HTTPException(404, "Generation tool was not found.")
    team_tools.set_tool_enabled(user["id"], tool_id, payload.enabled)
    return {"status": "ok"}


@router.get("/groups")
def list_groups(request: Request):
    _require_team()
    actor = team.request_user(request, "owner", "operator")
    with access.job_db() as connection:
        connection.execute("BEGIN")
        user = team.require_active(connection, actor["id"], "owner", "operator")
        owner = user["role"] == "owner"
        return {"groups": team_tools.list_groups(connection, editable=owner), "tools": _catalog(connection) if owner else []}


def _save_group(request, group_id, payload):
    _require_team()
    user = team.request_user(request, "owner")
    if payload.restricted:
        _validate_tools(payload.tool_ids)
    return team_tools.save_group(user["id"], group_id, payload.name, payload.restricted, payload.tool_ids)


@router.post("/groups", status_code=201)
def create_group(payload: GroupSettings, request: Request):
    return _save_group(request, None, payload)


@router.put("/groups/{group_id}")
def change_group(group_id: str, payload: GroupSettings, request: Request):
    return _save_group(request, group_id, payload)


@router.delete("/groups/{group_id}", status_code=204)
def delete_group(group_id: str, request: Request):
    _require_team()
    user = team.request_user(request, "owner")
    team_tools.remove_group(user["id"], group_id)
    return Response(status_code=204)
