# Odido Bundle Booster

This project re-implements the behavior of Odido bundle-management tools (e.g., Odido authenticator and automation utilities) as a headless, API-only service. The code is original and uses the referenced projects purely as behavioral inspiration.

## Features
- FastAPI service running on Alpine Linux (port 80).
- Adaptive scheduling based on consumption rate and remaining MBs.
- Auto-renew with lead-time thresholds, exponential backoff, and idempotency.
- Daily reset at local midnight.
- SQLite persistence with WAL for durability; JSON-style KV inside the DB.
- CORS enabled for external dashboards.
- API key protection (header `X-API-Key`).

## Configuration
Environment variables:
- `API_KEY` or `ODIDO_API_KEY`: API key for all endpoints.
- `PORT` (default 80): API port.
- `APP_DB_PATH` (default `/data/odido.db`): SQLite location.
- `APP_DATA_DIR` (default `/data`): data directory.

Runtime configuration via `POST /api/config` (all optional fields):
- `api_key`: replace the API key.
- `bundle_size_mb` (default 1024)
- `absolute_min_threshold_mb` (default 100)
- `estimator_window_minutes` (default 60)
- `estimator_max_events` (default 24)
- `min_check_interval_minutes` (default 1)
- `max_check_interval_minutes` (default 60)
- `lead_time_minutes` (default 30)
- `auto_renew_enabled` (default true)
- `default_bundle_valid_hours` (default 720)
- `log_level`

## API
All endpoints expect header `X-API-Key` matching the configured value.

- `GET /api/status`
- `POST /api/config` – update config
- `POST /api/add-bundle` – body `{ "amount_mb": number?, "idempotency_key": string? }`
- `POST /api/simulate-usage` – body `{ "amount_mb": number, "timestamp": epoch? }`
- `GET /api/logs?limit=100`
- `POST /api/health`

## Adaptive scheduling
- Consumption rate estimated as MB/min over the recent window (default last 60 minutes, capped at 24 events).
- Estimated time-to-depletion (ETA) = `remaining_mb / rate`.
- Next check interval = clamp(ETA/4, min_interval, max_interval).
- Auto-renew triggers when `remaining_mb <= absolute_min_threshold_mb` **or** `ETA <= lead_time_minutes`.
- If rate is zero, checks occur at `max_check_interval_minutes`.

## Persistence and safety
- SQLite with WAL mode to reduce corruption risk.
- Idempotency keys prevent duplicate manual additions; auto-renew uses retries with exponential backoff.
- Daily reset occurs at container-local midnight; survives restarts by persisting state.

## Build and run
```
docker build -t odido-api:latest .
docker run -p 80:80 --name odido-api -e API_KEY=changeme -v $(pwd)/data:/data odido-api:latest
```

## Example usage
```
# Health
curl -X POST http://localhost/api/health

# Configure
curl -X POST http://localhost/api/config \ \
  -H 'X-API-Key: changeme' \ \
  -H 'Content-Type: application/json' \ \
  -d '{"lead_time_minutes":45,"absolute_min_threshold_mb":120}'

# Simulate usage
curl -X POST http://localhost/api/simulate-usage \ \
  -H 'X-API-Key: changeme' \ \
  -H 'Content-Type: application/json' \ \
  -d '{"amount_mb":50}'
```

## Notes
- Auto-renew is simulated as a local state change; integrate real carrier APIs by replacing the renewal hook in `BundleService._renew_with_retry`.
- Default values are conservative to avoid premature renewals; tune via configuration to match production usage profiles.
