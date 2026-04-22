#!/bin/sh
mkdir -p /app/config
chown -R appuser:appuser /app/config
PORT="${APP_PORT:-5000}"
exec su -s /bin/sh -c "exec gunicorn --bind 0.0.0.0:${PORT} --workers 1 --threads 2 app:app" appuser