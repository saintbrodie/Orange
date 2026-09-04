import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.api import admin, backend_status, generate, preflight, status, workflows
from app.core.backends import backend_manager
from app.core.config import restore_defaults
from app.core.database import init_db

# Project Root (since main.py is in app/ directory, root is one level up)
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

# Mount Static Files
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Include Routers
app.include_router(generate.router)
app.include_router(status.router)
app.include_router(admin.router)
app.include_router(workflows.router)
app.include_router(preflight.router)
app.include_router(backend_status.router)


@app.get("/")
def serve_index():
    try:
        with open(os.path.join(STATIC_DIR, "index.html"), "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="UI not found. Ensure static/index.html exists.")


@app.get("/admin")
def serve_admin():
    try:
        with open(os.path.join(STATIC_DIR, "admin.html"), "r", encoding="utf-8") as f:
            content = f.read()
        # Keep engineering diagnostics isolated from the main admin bundle and the
        # intentionally small end-user generator UI.
        content = content.replace(
            "</body>",
            '    <script src="/static/preflight.js?v=1"></script>\n'
            '    <script src="/static/backend-status.js?v=1"></script>\n'
            "</body>",
        )
        return HTMLResponse(content=content)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Admin UI not found. Ensure static/admin.html exists.")
