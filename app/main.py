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
from .odido_api import OdidoAPI, OdidoAPIError, OdidoAuthError
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


def _get_odido_api() -> OdidoAPI:
    """Create an Odido API client using configured credentials."""
    config = service.config
    return OdidoAPI(
        user_id=config.odido_user_id or os.getenv("ODIDO_USER_ID"),
        access_token=config.odido_token or os.getenv("ODIDO_TOKEN"),
    )


@app.get("/api/odido/bundles")
def get_odido_bundles(_: None = Depends(verify_api_key)):
    """
    Fetch available bundle information from the Odido API.
    
    Returns roaming bundle details including remaining data and zone information.
    Requires ODIDO_USER_ID and ODIDO_TOKEN to be configured.
    """
    api = _get_odido_api()
    if not api.is_configured:
        raise HTTPException(
            status_code=400,
            detail="Odido API credentials not configured. Set ODIDO_USER_ID and ODIDO_TOKEN environment variables or configure via /api/config",
        )
    try:
        bundles = api.get_roaming_bundles()
        return {
            "bundles": [b.as_dict() for b in bundles],
            "total_remaining_mb": api.get_remaining_data_mb(),
        }
    except OdidoAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except OdidoAPIError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/odido/bundle-codes")
def get_bundle_codes(_: None = Depends(verify_api_key)):
    """
    Get available bundle buying codes.
    
    Returns a list of known bundle codes that can be used for purchasing bundles.
    Note: The Odido API does not provide an endpoint to list available codes,
    so this returns commonly used codes based on reference implementations.
    """
    api = _get_odido_api()
    return {
        "bundle_codes": api.get_available_bundle_codes(),
        "configured_code": service.config.bundle_code,
    }


@app.post("/api/odido/buy-bundle")
def buy_odido_bundle(payload: dict, _: None = Depends(verify_api_key)):
    """
    Purchase a bundle from Odido using the specified or configured buying code.
    
    Request body:
        - buying_code (optional): The bundle code to use. Defaults to configured bundle_code.
    
    Requires ODIDO_USER_ID and ODIDO_TOKEN to be configured.
    """
    api = _get_odido_api()
    if not api.is_configured:
        raise HTTPException(
            status_code=400,
            detail="Odido API credentials not configured. Set ODIDO_USER_ID and ODIDO_TOKEN environment variables or configure via /api/config",
        )
    
    buying_code = payload.get("buying_code") or service.config.bundle_code
    
    try:
        result = api.buy_bundle(buying_code=buying_code)
        service._log("INFO", f"Bundle purchased via Odido API with code: {buying_code}")
        return result
    except OdidoAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except OdidoAPIError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/odido/subscriptions")
def get_odido_subscriptions(_: None = Depends(verify_api_key)):
    """
    Fetch subscription details from the Odido API.
    
    Returns information about linked subscriptions.
    Requires ODIDO_USER_ID and ODIDO_TOKEN to be configured.
    """
    api = _get_odido_api()
    if not api.is_configured:
        raise HTTPException(
            status_code=400,
            detail="Odido API credentials not configured. Set ODIDO_USER_ID and ODIDO_TOKEN environment variables or configure via /api/config",
        )
    try:
        subscriptions = api.get_subscriptions()
        return {"subscriptions": [s.as_dict() for s in subscriptions]}
    except OdidoAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except OdidoAPIError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/odido/remaining")
def get_odido_remaining(_: None = Depends(verify_api_key)):
    """
    Get the remaining data balance from Odido.
    
    Returns the total remaining MB for the NL zone.
    Requires ODIDO_USER_ID and ODIDO_TOKEN to be configured.
    """
    api = _get_odido_api()
    if not api.is_configured:
        raise HTTPException(
            status_code=400,
            detail="Odido API credentials not configured. Set ODIDO_USER_ID and ODIDO_TOKEN environment variables or configure via /api/config",
        )
    try:
        remaining_mb = api.get_remaining_data_mb()
        return {"remaining_mb": remaining_mb}
    except OdidoAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except OdidoAPIError as e:
        raise HTTPException(status_code=502, detail=str(e))


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
