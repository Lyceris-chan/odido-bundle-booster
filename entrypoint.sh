#!/bin/sh
set -e

APP_USER=odido
APP_GROUP=odido
APP_DIR=/app
DATA_DIR=${APP_DATA_DIR:-/data}
DB_PATH=${APP_DB_PATH:-$DATA_DIR/odido.db}

addgroup -S "$APP_GROUP" >/dev/null 2>&1 || true
adduser -S "$APP_USER" -G "$APP_GROUP" >/dev/null 2>&1 || true
mkdir -p "$DATA_DIR"
chown -R "$APP_USER":"$APP_GROUP" "$DATA_DIR"
chmod 700 "$DATA_DIR"

cd "$APP_DIR"

exec su-exec "$APP_USER" "$@"
