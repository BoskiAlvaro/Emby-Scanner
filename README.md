# EmbyScanner

A self-hosted Flask web app that schedules and triggers library refresh operations on an Emby media server. Supports flexible schedules per library, manual refresh, activity logging, and a multilingual UI (EN/PL/DE).

<img width="1456" height="717" alt="embyscanner" src="https://github.com/user-attachments/assets/4405b118-d550-4f5f-aa9d-8a7c2929f0a7" />

## Features

- Trigger manual library refreshes from the dashboard
- Schedule automatic refreshes per library (15 min – 24 h intervals, daily at a set time, or weekly on a specific day/time)
- Hide libraries from the dashboard without deleting them to keep UI simple
- Rename libraries with custom display names
- Activity log
- UI language: English, Polish, German (auto-detected from browser)

## Requirements

- Python 3.9+ or Docker
- A running Emby media server with an API key

## Quick start

### Local

```bash
pip install -r requirements.txt
python app.py
```

The app starts on port **5000** by default. Override with:

```bash
APP_PORT=8080 python app.py
```

### Docker Compose

```bash
docker-compose up -d
```

The `config/` directory is mounted as a volume so your configuration and database persist across container restarts.

## Configuration

On first run, navigate to `http://localhost:5000<img width="1456" height="717" alt="embyscanner" src="https://github.com/user-attachments/assets/9faebba0-d5f0-4c9f-8276-5a9db7ea8430" />
` — you will be redirected to the setup page where you enter:

| Field | Description |
|-------|-------------|
| Emby IP | IP address of your Emby server |
| Port | Emby server port (default `8096`) |
| API Key | Found in Emby dashboard → Advanced → API Keys |

Settings are saved to `config/config.yaml`.

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_PORT` | `5000` | Port the app listens on |
| `DEBUG` | `false` | Enable Flask debug mode (local dev only) |
| `TZ` | — | Container timezone (e.g. `Europe/Warsaw`) |

## Schedule frequencies

| Value | Description |
|-------|-------------|
| `15min` / `30min` / `45min` | Every N minutes |
| `1h` / `2h` / `3h` / `6h` / `12h` / `24h` | Every N hours |
| Daily at time | Every day at a specific HH:MM |
| Weekly | Specific weekday and time |
| Manual | No automatic trigger |

## Data files

| Path | Description |
|------|-------------|
| `config/config.yaml` | Emby server connection and hidden item IDs |
| `config/scheduler.db` | SQLite database — schedules and custom names |
| `config/execution.log` | JSON-lines log of all refresh operations |

## Project structure

```
app.py                  # All Flask routes, scheduler, Emby API calls
templates/
  index.html            # Main dashboard
  setup.html            # Initial setup / connection settings
static/
  js/translations.js    # i18n strings (EN/PL/DE)
  css/
config/                 # Created at runtime (gitignored)
```

## Docker details

The image runs as a non-root `appuser`. The `config/` directory must be writable by the container user (UID 1000 by default):

```bash
mkdir -p config && chown 1000:1000 config
```
