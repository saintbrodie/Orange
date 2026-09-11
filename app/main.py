import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.api import admin, backend_status, db_admin, generate, generation_debug, generation_v2, llm_api, outputs, personalization, preflight, status, workflow_assets, workflows
from app.core.backends import backend_manager
from app.core.config import restore_defaults
from app.core.database import init_db

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STATIC_DIR = os.path.join(PROJECT_ROOT, "static")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    restore_defaults(overwrite=False)
    await backend_manager.start()
    try:
        yield
    finally:
        await backend_manager.stop()


app = FastAPI(title="ComfyUI Minimal Frontend - Orange", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

app.include_router(outputs.router)
app.include_router(generation_v2.router)
app.include_router(llm_api.router)
app.include_router(personalization.router)
app.include_router(generate.router)
app.include_router(status.router)
app.include_router(db_admin.router)
app.include_router(admin.router)
app.include_router(workflows.router)
app.include_router(preflight.router)
app.include_router(backend_status.router)
app.include_router(generation_debug.router)
app.include_router(workflow_assets.router)


THEME_HEAD = (
    '    <script>(function(){try{var b=JSON.parse(localStorage.getItem("orange_theme_bootstrap")||"null");if(!b)return;if(b.theme==="botanical")b.theme="adventure";if(b.effect==="botanical")b.effect="adventure";var d=document.documentElement;if(b.theme)d.dataset.orangeTheme=b.theme;if(b.effect)d.dataset.orangeEffect=b.effect;if(b.motion)d.dataset.orangeMotion=b.motion;if(b.vars){Object.keys(b.vars).forEach(function(k){d.style.setProperty(k,b.vars[k]);});}}catch(e){}})();</script>\n'
    '    <link rel="stylesheet" href="/static/theme.css?v=2">\n'
    '    <link rel="stylesheet" href="/static/theme-legacy-bridge.css?v=2">\n'
    '    <link rel="stylesheet" href="/static/theme-effects-v2.css?v=10">\n'
    '    <script src="/static/theme-runtime.js?v=4" defer></script>\n'
    '    <script src="/static/theme-effects.js?v=5" defer></script>\n'
)


@app.get("/")
def serve_index():
    try:
        with open(os.path.join(STATIC_DIR, "index.html"), "r", encoding="utf-8") as f:
            content = f.read()
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
            '    <script src="/static/mobile-navigation.js?v=3"></script>\n'
            "</body>",
        )
        return HTMLResponse(content=content)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="UI not found. Ensure static/index.html exists.")


@app.get("/admin")
def serve_admin():
    try:
        with open(os.path.join(STATIC_DIR, "admin.html"), "r", encoding="utf-8") as f:
            content = f.read()
        content = content.replace(
            "</head>",
            THEME_HEAD
            + '    <link rel="stylesheet" href="/static/mobile-navigation.css?v=3">\n</head>',
        )
        content = content.replace(
            "</body>",
            '    <script src="/static/preflight.js?v=2"></script>\n'
            '    <script src="/static/backend-status.js?v=3"></script>\n'
            '    <script src="/static/tool-ratios.js?v=1"></script>\n'
            '    <script src="/static/workflow-assets.js?v=2"></script>\n'
            '    <script src="/static/personalization.js?v=1"></script>\n'
            '    <script src="/static/personalization-tab-state.js?v=1"></script>\n'
            '    <script src="/static/mobile-navigation.js?v=3"></script>\n'
            "</body>",
        )
        return HTMLResponse(content=content)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Admin UI not found. Ensure static/admin.html exists.")
