from fastapi import FastAPI

from .api.devices import router as devices_router
from .api.events import router as events_router
from .api.heartbeat import router as heartbeat_router
from .api.health import router as health_router
from .api.ingest import router as ingest_router
from .api.commands import router as commands_router
from .api.auth import router as auth_router
from .api.admin import router as admin_router


app = FastAPI(title="B2315P Health Database Service", version="0.1.0")
app.include_router(health_router)
app.include_router(devices_router)
app.include_router(ingest_router)
app.include_router(heartbeat_router)
app.include_router(events_router)
app.include_router(commands_router)
app.include_router(auth_router)
app.include_router(admin_router)


@app.get("/healthz", tags=["system"])
def healthz() -> dict[str, str]:
    return {"status": "ok"}
