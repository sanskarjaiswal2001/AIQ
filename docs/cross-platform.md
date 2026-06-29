# Cross-platform install guide

AIQ supports two deployment shapes:

1. **Mothership** — the central FastAPI + SQLite server and dashboard.
2. **Edge collector** — the per-developer CLI that reads local AI coding logs and pushes metrics.

Docker is optional. Native Python works on Linux, WSL, macOS, and Windows.

---

## Requirements

| Component | Requirement |
|---|---|
| Mothership | Python 3.11+ recommended, network access between employees and server |
| Edge collector | Python 3.9+ for the package; Python 3.11+ recommended |
| Claude Code collector | Claude Code logs at the default `~/.claude/projects` location |

Windows users should run commands in **PowerShell**. WSL users should run Linux commands inside the WSL distro.

---

## Mothership: native install, no Docker

The same command works on Linux, WSL, macOS, and Windows:

```bash
git clone https://github.com/sanskarjaiswal2001/AIQ.git
cd AIQ
python scripts/aiq-mothership.py install --generate-admin-key
python scripts/aiq-mothership.py run --host 0.0.0.0 --port 8000
```

Open:

```text
http://localhost:8000
```

Check health:

```bash
python scripts/aiq-mothership.py health --server-url http://localhost:8000
```

Create an employee invite:

```bash
python scripts/aiq-mothership.py create-invite --server-url http://localhost:8000 --team Engineering
```

The installer creates:

| Path | Purpose |
|---|---|
| `.venv-mothership/` | Python virtualenv for FastAPI/uvicorn |
| `.env` | Admin key, port, and data directory config |
| `~/.aiq/mothership/aiq.db` | SQLite database by default |

Set a custom data directory:

```bash
python scripts/aiq-mothership.py install --data-dir /srv/aiq --generate-admin-key
```

Windows example:

```powershell
git clone https://github.com/sanskarjaiswal2001/AIQ.git
cd AIQ
py scripts\aiq-mothership.py install --generate-admin-key
py scripts\aiq-mothership.py run --host 0.0.0.0 --port 8000
```

---

## Mothership: Docker install, optional

Use only if Docker is convenient on your platform:

```bash
git clone https://github.com/sanskarjaiswal2001/AIQ.git
cd AIQ
cp .env.example .env
docker compose up -d --build
```

Docker is not required for macOS/Windows support.

---

## Edge collector: install and register

Install from the repo during development:

```bash
cd AIQ/collector
python -m pip install -e .
```

Once published to PyPI, this becomes:

```bash
python -m pip install aiq-collector
```

Register with a mothership invite:

```bash
aiq register \
  --server-url http://YOUR-MOTHERSHIP:8000 \
  --invite-code INVITE_CODE \
  --employee-id jane-doe \
  --name "Jane Doe" \
  --team Engineering
```

Collect once:

```bash
aiq collect
```

Status:

```bash
aiq status
```

Config lives at:

| OS | Path |
|---|---|
| Linux / WSL / macOS | `~/.aiq/config.toml` |
| Windows | `%USERPROFILE%\.aiq\config.toml` |

---

## Edge collector: auto-run per OS

The cross-platform command is:

```bash
aiq install-autostart --interval-hours 6
```

AIQ automatically picks the native scheduler:

| OS | Default scheduler | Notes |
|---|---|---|
| Linux | systemd user timer, fallback to cron | Works without root in most desktop/server distros |
| WSL | systemd user timer if WSL systemd is enabled, fallback to cron | If your WSL shuts down, scheduled jobs stop until WSL restarts |
| macOS | launchd LaunchAgent | Runs as the logged-in user |
| Windows | Task Scheduler | Runs hourly with `/SC HOURLY /MO N` |

Force a backend:

```bash
aiq install-autostart --backend cron --interval-hours 6       # Linux/WSL fallback
aiq install-autostart --backend systemd --interval-hours 6    # Linux/WSL
aiq install-autostart --backend launchd --interval-hours 6    # macOS
aiq install-autostart --backend task-scheduler --interval-hours 6  # Windows
```

Remove scheduled collection:

```bash
aiq install-autostart --remove
```

Legacy alias:

```bash
aiq install-cron --interval-hours 6
```

This is kept for Linux/WSL cron users only.

---

## Employee self-view

After registration and first collection, the employee can open:

```text
http://YOUR-MOTHERSHIP:8000/me
```

They paste their API key from `~/.aiq/config.toml` (or `%USERPROFILE%\.aiq\config.toml` on Windows) to see only their own data.

---

## Recommended production setup

| Environment | Recommended mothership mode | Recommended collector mode |
|---|---|---|
| Linux server | Native Python service or Docker Compose | systemd user timer |
| WSL lab/demo | Native Python | systemd if enabled, otherwise cron/manual daemon |
| macOS admin laptop | Native Python | launchd |
| Windows admin workstation | Native Python | Task Scheduler |
| Homelab/NAS | Docker Compose if supported, otherwise native Python | n/a |

For <50 employees, SQLite is enough. For larger orgs, move the mothership DB layer to Postgres later.
