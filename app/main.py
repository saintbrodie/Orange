import asyncio
import os
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from app.api import admin, backend_status, db_admin, generate, generation_debug, generation_v2, llm_api, managed_prompt_enhancer, managed_runtime, media_providers, outputs, personalization, preflight, setup, status, workflow_assets, workflow_pack_admin, workflows
from app.api import team as team_api
from app.core import access, budgets, listener, team
from app.core.backends import backend_manager
from app.core.config import USER_CONFIG_PATH, load_config, restore_defaults, save_config
from app.core.database import init_db
from app.core.managed_runtime import validate_pending_managed_runtime
from app.core.managed_prompt_enhancer import stop_server as stop_managed_prompt_enhancer
from app.core.onboarding import initialize_setup_state, setup_required
from app.core.terminal_events import emit_terminal_event

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STATIC_DIR = os.path.join(PROJECT_ROOT, "static")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if access.is_team():
        team.init_team()
        budgets.init_budgets()
    elif access.is_open_lan():
        listener.load_open_lan_http_from_legacy_launcher()
        access.init_job_access()
    was_fresh_install = not os.path.exists(USER_CONFIG_PATH)
    init_db()
    restore_defaults(overwrite=False)
    if was_fresh_install:
        bootstrap_config = dict(load_config())
        bootstrap_config["adminKey"] = secrets.token_urlsafe(32)
        save_config(bootstrap_config)
    initialize_setup_state(was_fresh_install)
    from app.core.media_jobs import job_manager
    await job_manager.start()
    await backend_manager.start()
    runtime_validation_task = asyncio.create_task(validate_pending_managed_runtime())
    try:
        yield
    finally:
        if not runtime_validation_task.done():
            runtime_validation_task.cancel()
        await asyncio.gather(runtime_validation_task, return_exceptions=True)
        stop_managed_prompt_enhancer()
        await job_manager.stop()
        await backend_manager.stop()


app = FastAPI(title="ComfyUI Minimal Frontend - Orange", version="1.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

_TEAM_PUBLIC_APIS = {
    "/api/team/login", "/api/team/session", "/api/team/accept-invitation", "/api/personalization",
}
_TEAM_PUBLIC_ASSETS = ("/api/branding/", "/api/theme-assets/", "/api/theme-mascot/")
_TEAM_PRIVATE_ADMIN_DATA = ("/api/admin/media", "/api/admin/db/", "/api/admin/generations/", "/api/admin/bulk-delete")


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: RequestValidationError):
    if request.url.path.startswith("/api/team/"):
        return JSONResponse({"detail": "Check the fields and try again."}, status_code=422)
    return await request_validation_exception_handler(request, exc)


@app.middleware("http")
async def terminal_activity(request: Request, call_next):
    path = request.url.path
    method = request.method.upper()
    activity = None

    if method == "POST" and path == "/api/generate":
        activity = ("generation", "working")
        emit_terminal_event("generation", "working", "Submitting generation...")
    elif method == "POST" and path in {
        "/api/enhance-prompt",
        "/api/admin/prompt-enhancer/managed/test",
    }:
        activity = ("llm", "working")
        emit_terminal_event("llm", "working", "Prompt enhancer working...")

    try:
        response = await call_next(request)
    except Exception:
        if activity:
            emit_terminal_event(activity[0], "failed", f"{activity[0].capitalize()} failed")
        raise

    if activity:
        kind, _ = activity
        if response.status_code < 400:
            if kind == "generation":
                user = getattr(request.state, "team_user", None)
                message = f"{user['handle']} queued a generation" if user else "Generation queued"
                emit_terminal_event(kind, "queued", message)
            else:
                emit_terminal_event(kind, "complete", "Prompt enhancement complete")
        else:
            emit_terminal_event(kind, "failed", f"{kind.capitalize()} failed ({response.status_code})")

    return response


@app.middleware("http")
async def enforce_access_mode(request: Request, call_next):
    error = access.request_access_error(request)
    if error:
        status_code, detail = error
        return JSONResponse({"detail": detail}, status_code=status_code)

    path = request.url.path
    open_lan = access.is_open_lan()
    team_mode = access.is_team()
    if team_mode and (path in {"/", "/admin", "/team"} or path.startswith("/api/")):
        user = await run_in_threadpool(team.current_user, team.session_token(request))
        request.state.team_user = user
        if path.startswith("/api/setup/"):
            peer = request.client.host if request.client else None
            if peer not in {"127.0.0.1", "::1"} or not setup_required():
                return JSONResponse({"detail": "First-run setup is handled on the Orange host."}, status_code=403)
        elif path.startswith("/api/") and not user and path not in _TEAM_PUBLIC_APIS and not path.startswith(_TEAM_PUBLIC_ASSETS):
            return JSONResponse({"detail": "Sign in to continue."}, status_code=401, headers={"Cache-Control": "no-store"})
        if path.startswith(_TEAM_PRIVATE_ADMIN_DATA):
            return JSONResponse({"detail": "Team generations are available to their submitting accounts."}, status_code=403)
        if path in {"/", "/admin"} and not user and not setup_required():
            return RedirectResponse(url="/team", status_code=303, headers={"Cache-Control": "no-store"})
        if path == "/admin" and user and user["role"] != "owner":
            return RedirectResponse(url="/team", status_code=303, headers={"Cache-Control": "no-store"})
    if (open_lan or team_mode) and path in {"/api/generate", "/api/enhance-prompt"} and setup_required():
        return JSONResponse({"detail": "Complete Orange setup on the host machine first."}, status_code=403)
    new_guest = open_lan and not access.guest_token(request) and (
        (request.method == "GET" and path == "/")
        or (request.method == "POST" and path == "/api/generate")
    )
    if new_guest:
        request.state.guest_token = access.start_guest_session(request)

    response = await call_next(request)
    if new_guest:
        access.set_guest_cookie(response, request, request.state.guest_token)
    if (open_lan or team_mode) and (path in {"/", "/admin", "/team"} or path.startswith("/api/")):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    return response


app.include_router(outputs.router)
app.include_router(media_providers.router)
app.include_router(generation_v2.router)
app.include_router(llm_api.router)
app.include_router(personalization.router)
app.include_router(generate.router)
app.include_router(status.router)
app.include_router(db_admin.router)
app.include_router(setup.router)
app.include_router(admin.router)
app.include_router(managed_runtime.router)
app.include_router(managed_prompt_enhancer.router)
app.include_router(workflows.router)
app.include_router(preflight.router)
app.include_router(workflow_pack_admin.router)
app.include_router(backend_status.router)
app.include_router(generation_debug.router)
app.include_router(workflow_assets.router)
app.include_router(team_api.router)


THEME_HEAD = (
    '    <script>(function(){try{var b=JSON.parse(localStorage.getItem("orange_theme_bootstrap")||"null");if(!b)return;if(b.theme==="botanical")b.theme="adventure";if(b.effect==="botanical")b.effect="adventure";var d=document.documentElement;if(b.theme)d.dataset.orangeTheme=b.theme;if(b.effect)d.dataset.orangeEffect=b.effect;if(b.motion)d.dataset.orangeMotion=b.motion;if(b.vars){Object.keys(b.vars).forEach(function(k){d.style.setProperty(k,b.vars[k]);});}}catch(e){}})();</script>\n'
    '    <link rel="stylesheet" href="/static/theme.css?v=3">\n'
    '    <link rel="stylesheet" href="/static/theme-legacy-bridge.css?v=2">\n'
    '    <link rel="stylesheet" href="/static/theme-effects-v2.css?v=12">\n'
    '    <link rel="stylesheet" href="/static/brand-theme.css?v=2">\n'
    '    <script src="/static/theme-runtime.js?v=4" defer></script>\n'
    '    <script src="/static/theme-effects.js?v=5" defer></script>\n'
)


@app.get("/setup")
def serve_setup():
    if not setup_required():
        return RedirectResponse(url="/", status_code=302)
    try:
        with open(os.path.join(STATIC_DIR, "setup.html"), "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Setup UI not found. Ensure static/setup.html exists.")


@app.get("/team")
def serve_team(request: Request, embedded: bool = False):
    if not access.is_team():
        raise HTTPException(404, "Team mode is unavailable.")
    if embedded:
        if not getattr(request.state, "team_user", None):
            return RedirectResponse("/team", status_code=303)
        team.request_user(request, "owner")
    with open(os.path.join(STATIC_DIR, "team.html"), "r", encoding="utf-8") as page:
        content = page.read().replace("</head>", THEME_HEAD + "</head>")
        if embedded:
            content = content.replace('<body class="team-page">', '<body class="team-page" data-team-embedded>', 1)
        return HTMLResponse(content)


@app.get("/")
def serve_index():
    if setup_required():
        return RedirectResponse(url="/setup", status_code=302)
    try:
        with open(os.path.join(STATIC_DIR, "index.html"), "r", encoding="utf-8") as f:
            content = f.read()
        if access.is_team():
            content = content.replace('href="/admin"><i data-lucide="settings" class="w-4 h-4"></i> Admin',
                                      'href="/team"><i data-lucide="user" class="w-4 h-4"></i> Account', 1)
            content = content.replace("</head>",
                                      '    <link rel="stylesheet" href="/static/team-history.css?v=1">\n'
                                      '    <script src="/static/team-history.js?v=1" defer></script>\n</head>', 1)
        content = content.replace(
            "</head>",
            THEME_HEAD
            + '    <link rel="stylesheet" href="/static/responsive.css?v=1">\n'
            + '    <link rel="stylesheet" href="/static/mobile-navigation.css?v=3">\n'
            + "</head>",
        )
        content = content.replace(
            "</body>",
            '    <script src="/static/result-actions.js?v=3"></script>\n'
            '    <script src="/static/mobile-navigation.js?v=7"></script>\n'
            "</body>",
        )
        return HTMLResponse(content=content)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="UI not found. Ensure static/index.html exists.")


@app.get("/admin")
def serve_admin():
    if setup_required():
        return RedirectResponse(url="/setup", status_code=302)
    try:
        with open(os.path.join(STATIC_DIR, "admin.html"), "r", encoding="utf-8") as f:
            content = f.read()
        if access.is_team():
            content = content.replace("<html lang=\"en\">", '<html lang="en" data-orange-mode="team">', 1)
        content = content.replace(
            "</head>",
            THEME_HEAD
            + '    <link rel="stylesheet" href="/static/mobile-navigation.css?v=3">\n'
            + '    <link rel="stylesheet" href="/static/admin-theme-overrides.css?v=1">\n</head>',
        )
        content = content.replace(
            "</body>",
            '    <script src="/static/model-bindings.js?v=1"></script>\n'
            '    <script src="/static/preflight.js?v=4"></script>\n'
            '    <script src="/static/backend-status.js?v=3"></script>\n'
            '    <script src="/static/tool-ratios.js?v=1"></script>\n'
            '    <script src="/static/workflow-assets.js?v=2"></script>\n'
            '    <script src="/static/personalization.js?v=5"></script>\n'
            '    <script src="/static/personalization-tab-state.js?v=2"></script>\n'
            '    <script src="/static/admin-layout.js?v=1"></script>\n'
            '    <script src="/static/general-settings.js?v=2"></script>\n'
            '    <script src="/static/media-providers.js?v=6"></script>\n'
            '    <script src="/static/managed-comfyui.js?v=5"></script>\n'
            '    <script src="/static/managed-prompt-enhancer.js?v=5"></script>\n'
            '    <script src="/static/llm-model-select.js?v=1"></script>\n'
            '    <script src="/static/mobile-navigation.js?v=8"></script>\n'
            "</body>",
        )
        return HTMLResponse(content=content)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Admin UI not found. Ensure static/admin.html exists.")
