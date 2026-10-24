from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import get_settings
from app.db import get_engine

app = FastAPI(title="Meta Market — Siege backend")


@app.get("/api/health")
def health() -> JSONResponse:
    settings = get_settings()
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:  # report the failure class only, never connection details
        return JSONResponse({"ok": False, "error": type(e).__name__}, status_code=503)
    return JSONResponse({"ok": True, "dataMode": settings.data_mode, "database": "reachable"})
