from __future__ import annotations

import logging
import os
import signal
import threading
import time
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

from .config import AppConfig
from .scheduler import Scheduler
from .service import BundleService
from .storage import Storage

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("odido.main")

app = FastAPI(title="Odido Bundle Booster", version="1.0.0")
storage = Storage()
service = BundleService(storage)
scheduler = Scheduler(service)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def verify_api_key(x_api_key: Optional[str] = Header(default=None)):
    if service.config.api_key and x_api_key != service.config.api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


@app.on_event("startup")
def startup_event():
    scheduler.start()


@app.on_event("shutdown")
def shutdown_event():
    scheduler.stop()


@app.get("/api/status")
def get_status(_: None = Depends(verify_api_key)):
    return service.status()


@app.post("/api/config")
def post_config(payload: dict, _: None = Depends(verify_api_key)):
    config = service.update_config(payload)
    return config.as_dict()


@app.post("/api/add-bundle")
def post_add_bundle(payload: dict, _: None = Depends(verify_api_key)):
    amount = payload.get("amount_mb")
    idempotency_key = payload.get("idempotency_key")
    state = service.manual_add_bundle(amount, idempotency_key)
    return state.as_dict()


@app.get("/api/logs")
def get_logs(limit: int = 100, _: None = Depends(verify_api_key)):
    return service.logs(limit=limit)


@app.post("/api/simulate-usage")
def post_usage(payload: dict, _: None = Depends(verify_api_key)):
    amount = payload.get("amount_mb")
    if amount is None:
        raise HTTPException(status_code=400, detail="amount_mb required")
    ts = payload.get("timestamp")
    state = service.simulate_usage(float(amount), float(ts) if ts else None)
    return state.as_dict()


@app.post("/api/health")
def post_health():
    return {"status": "ok"}


def main():
    scheduler.start()

    def handle_signal(signum, frame):  # pragma: no cover
        logger.info("Received signal %s, shutting down", signum)
        scheduler.stop()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 80)), log_level="info")


if __name__ == "__main__":
    main()
