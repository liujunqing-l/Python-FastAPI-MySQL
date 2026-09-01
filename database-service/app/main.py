from fastapi import FastAPI

from .api.devices import router as devices_router
from .api.health import router as health_router


app = FastAPI(title="B2315P Health Database Service", version="0.1.0")
app.include_router(health_router)
app.include_router(devices_router)


@app.get("/healthz", tags=["system"])
def healthz() -> dict[str, str]:
    return {"status": "ok"}
