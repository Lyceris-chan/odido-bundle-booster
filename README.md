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
- **Real Odido API integration**: Fetch available bundles and purchase bundles using the actual Odido carrier API.
- **Configurable bundle codes**: Set a specific bundle code for auto-renewal.

## Configuration
Environment variables:
- `API_KEY` or `ODIDO_API_KEY`: API key for all endpoints.
- `PORT` (default 80): API port.
- `APP_DB_PATH` (default `/data/odido.db`): SQLite location.
- `APP_DATA_DIR` (default `/data`): data directory.
- `ODIDO_USER_ID`: Your Odido user ID (**required** for auto-renewal and API endpoints).
- `ODIDO_TOKEN`: Your Odido access token (**required** for auto-renewal and API endpoints).

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
- `bundle_code` (default "A0DAY01"): The bundle buying code for auto-renewal.
- `odido_user_id`: Odido user ID (can also be set via environment variable).
- `odido_token`: Odido access token (can also be set via environment variable).

## API
All endpoints expect header `X-API-Key` matching the configured value.

### Core Endpoints
- `GET /api/status`
- `POST /api/config` – update config
- `POST /api/add-bundle` – body `{ "amount_mb": number?, "idempotency_key": string? }`
- `POST /api/simulate-usage` – body `{ "amount_mb": number, "timestamp": epoch? }`
- `GET /api/logs?limit=100`
- `POST /api/health`

### Odido API Endpoints
These endpoints interact with the real Odido carrier API. Requires `ODIDO_USER_ID` and `ODIDO_TOKEN` to be configured.

- `GET /api/odido/bundles` – Fetch current bundle information including remaining data.
- `GET /api/odido/bundle-codes` – Get available bundle buying codes.
- `POST /api/odido/buy-bundle` – Purchase a bundle. Body: `{ "buying_code": string? }` (defaults to configured `bundle_code`).
- `GET /api/odido/subscriptions` – Fetch linked subscription details.
- `GET /api/odido/remaining` – Get remaining data balance in MB.

## Bundle Codes
Common bundle buying codes (may vary based on subscription):
- `A0DAY01` – 2GB daily bundle (default)
- `A0DAY05` – 5GB daily bundle

**Note**: The Odido API does not provide an endpoint to list all available bundle codes. The codes above are based on the reference implementations ([ha-odido-mobile](https://github.com/arjenbos/ha-odido-mobile), [odido-aap](https://github.com/ink-splatters/odido-aap)). Your available codes may vary based on your subscription.

You can set the bundle code via:
1. Runtime configuration: `POST /api/config` with `{"bundle_code": "A0DAY05"}`
2. Per-request: `POST /api/odido/buy-bundle` with `{"buying_code": "A0DAY05"}`

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
docker run -p 80:80 --name odido-api \
  -e API_KEY=changeme \
  -e ODIDO_USER_ID=your_user_id \
  -e ODIDO_TOKEN=your_access_token \
  -v $(pwd)/data:/data \
  odido-api:latest
```

## Example usage
```bash
# Health
curl -X POST http://localhost/api/health

# Configure with bundle code
curl -X POST http://localhost/api/config \
  -H 'X-API-Key: changeme' \
  -H 'Content-Type: application/json' \
  -d '{"bundle_code":"A0DAY01"}'

# Fetch available bundles from Odido
curl -X GET http://localhost/api/odido/bundles \
  -H 'X-API-Key: changeme'

# Get known bundle codes
curl -X GET http://localhost/api/odido/bundle-codes \
  -H 'X-API-Key: changeme'

# Buy a bundle with specific code
curl -X POST http://localhost/api/odido/buy-bundle \
  -H 'X-API-Key: changeme' \
  -H 'Content-Type: application/json' \
  -d '{"buying_code":"A0DAY05"}'

# Get remaining data balance
curl -X GET http://localhost/api/odido/remaining \
  -H 'X-API-Key: changeme'

# Simulate usage (for testing without real API calls)
curl -X POST http://localhost/api/simulate-usage \
  -H 'X-API-Key: changeme' \
  -H 'Content-Type: application/json' \
  -d '{"amount_mb":50}'
```

## Obtaining Odido Credentials
To use the Odido API integration, you need to obtain your Odido user ID and access token. See the [odido-aap](https://github.com/ink-splatters/odido-aap) project for instructions on extracting credentials from the Odido mobile app.

## Notes
- Auto-renewal requires valid Odido API credentials (`ODIDO_USER_ID` and `ODIDO_TOKEN`). If credentials are not configured, auto-renewal will fail with an error.
- The Odido API does not provide an endpoint to dynamically fetch available bundle codes; the known codes are based on reference implementations.
- Default values are conservative to avoid premature renewals; tune via configuration to match production usage profiles.
