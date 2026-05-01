import os
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.core.database import init_db
from app.api import generate, status, admin, workflows

# Initialize database
init_db()

app = FastAPI(title="ComfyUI Minimal Frontend - Orange")

# Project Root (since main.py is in app/ directory, root is one level up)
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STATIC_DIR = os.path.join(PROJECT_ROOT, "static")

# Mount Static Files
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Include Routers
app.include_router(generate.router)
app.include_router(status.router)
app.include_router(admin.router)
app.include_router(workflows.router)

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
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Admin UI not found. Ensure static/admin.html exists.")
