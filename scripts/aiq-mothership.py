#!/usr/bin/env python3
"""Cross-platform AIQ mothership launcher.

Works on Linux, WSL, macOS, and Windows without Docker.

Usage:
    python scripts/aiq-mothership.py install
    python scripts/aiq-mothership.py run --host 0.0.0.0 --port 8000
    python scripts/aiq-mothership.py health --server-url http://localhost:8000
    python scripts/aiq-mothership.py create-invite --team Engineering
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "server"
DASHBOARD_DIR = ROOT / "dashboard"
DEFAULT_DATA_DIR = Path(os.environ.get("AIQ_DATA_DIR", Path.home() / ".aiq" / "mothership")).expanduser()
DEFAULT_VENV_DIR = ROOT / ".venv-mothership"
ENV_PATH = ROOT / ".env"


def _venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _read_env_file(path: Path = ENV_PATH) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _write_env_file(values: dict[str, str], path: Path = ENV_PATH) -> None:
    existing = _read_env_file(path)
    existing.update({k: v for k, v in values.items() if v is not None})
    content = [
        "# AIQ mothership native configuration",
        "# Used by scripts/aiq-mothership.py and optional Docker Compose.",
        f"AIQ_ADMIN_KEY={existing.get('AIQ_ADMIN_KEY', '')}",
        f"AIQ_PORT={existing.get('AIQ_PORT', '8000')}",
        f"AIQ_DATA_DIR={existing.get('AIQ_DATA_DIR', str(DEFAULT_DATA_DIR))}",
        "",
    ]
    path.write_text("\n".join(content), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _base_env(data_dir: Path | None = None, admin_key: str | None = None) -> dict[str, str]:
    file_env = _read_env_file()
    resolved_data = Path(data_dir or file_env.get("AIQ_DATA_DIR") or DEFAULT_DATA_DIR).expanduser()
    resolved_data.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SERVER_DIR)
    env["DASHBOARD_DIR"] = str(DASHBOARD_DIR)
    env["DB_PATH"] = str(resolved_data / "aiq.db")
    key = admin_key if admin_key is not None else file_env.get("AIQ_ADMIN_KEY", os.environ.get("AIQ_ADMIN_KEY", ""))
    if key:
        env["AIQ_ADMIN_KEY"] = key
    return env


def command_install(args: argparse.Namespace) -> int:
    venv_dir = Path(args.venv).expanduser() if args.venv else DEFAULT_VENV_DIR
    py = _venv_python(venv_dir)
    if not py.exists():
        print(f"Creating virtual environment: {venv_dir}")
        subprocess.check_call([sys.executable, "-m", "venv", str(venv_dir)])
    print("Installing mothership dependencies...")
    subprocess.check_call([str(py), "-m", "pip", "install", "--upgrade", "pip"])
    subprocess.check_call([str(py), "-m", "pip", "install", "-r", str(SERVER_DIR / "requirements.txt")])

    env_values: dict[str, str] = {
        "AIQ_PORT": str(args.port),
        "AIQ_DATA_DIR": str(Path(args.data_dir).expanduser() if args.data_dir else DEFAULT_DATA_DIR),
    }
    if args.generate_admin_key:
        env_values["AIQ_ADMIN_KEY"] = secrets.token_urlsafe(32)
    elif args.admin_key is not None:
        env_values["AIQ_ADMIN_KEY"] = args.admin_key
    elif not ENV_PATH.exists():
        env_values["AIQ_ADMIN_KEY"] = ""
    _write_env_file(env_values)

    print("\nAIQ mothership native install complete.")
    print(f"Venv       : {venv_dir}")
    print(f"Config     : {ENV_PATH}")
    print(f"Data dir   : {_read_env_file().get('AIQ_DATA_DIR', str(DEFAULT_DATA_DIR))}")
    print(f"Admin auth : {'enabled' if _read_env_file().get('AIQ_ADMIN_KEY') else 'disabled'}")
    print("\nRun:")
    print(f"  {sys.executable} scripts/aiq-mothership.py run")
    return 0


def command_run(args: argparse.Namespace) -> int:
    venv_dir = Path(args.venv).expanduser() if args.venv else DEFAULT_VENV_DIR
    py = _venv_python(venv_dir)
    if not py.exists():
        print("Mothership venv missing. Run `python scripts/aiq-mothership.py install` first.", file=sys.stderr)
        return 1
    env_file = _read_env_file()
    port = int(args.port or env_file.get("AIQ_PORT") or 8000)
    env = _base_env(data_dir=Path(args.data_dir).expanduser() if args.data_dir else None, admin_key=args.admin_key)
    print(f"Starting AIQ mothership on http://{args.host}:{port}")
    print(f"DB_PATH={env['DB_PATH']}")
    print(f"DASHBOARD_DIR={env['DASHBOARD_DIR']}")
    return subprocess.call([
        str(py), "-m", "uvicorn", "main:app",
        "--host", args.host,
        "--port", str(port),
    ], cwd=str(SERVER_DIR), env=env)


def _request_json(url: str, *, method: str = "GET", payload: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> tuple[int, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, data=body, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw


def command_health(args: argparse.Namespace) -> int:
    code, data = _request_json(args.server_url.rstrip("/") + "/api/health")
    print(json.dumps(data, indent=2) if isinstance(data, (dict, list)) else data)
    return 0 if 200 <= code < 300 else 1


def command_create_invite(args: argparse.Namespace) -> int:
    admin_key = args.admin_key or _read_env_file().get("AIQ_ADMIN_KEY", "")
    payload = {"team": args.team or "", "uses_remaining": args.uses_remaining}
    if args.code:
        payload["code"] = args.code
    headers = {"X-Admin-Key": admin_key} if admin_key else {}
    code, data = _request_json(
        args.server_url.rstrip("/") + "/api/admin/invites",
        method="POST",
        payload=payload,
        headers=headers,
    )
    print(json.dumps(data, indent=2) if isinstance(data, (dict, list)) else data)
    return 0 if 200 <= code < 300 else 1


def command_lobby(args: argparse.Namespace) -> int:
    """Interactive TUI to manage the lobby."""
    import curses

    server_url = args.server_url.rstrip("/")
    admin_key = args.admin_key or _read_env_file().get("AIQ_ADMIN_KEY", "")
    headers = {"X-Admin-Key": admin_key} if admin_key else {}

    def fetch_pending() -> list[dict[str, Any]]:
        code, data = _request_json(server_url + "/api/admin/lobby?status=pending", headers=headers)
        if code != 200 or not isinstance(data, list):
            return []
        return data

    def accept_entries(lobby_ids: list[str], team: str = "") -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"lobby_ids": lobby_ids}
        if team:
            payload["team"] = team
        code, data = _request_json(server_url + "/api/admin/lobby/accept", method="POST", payload=payload, headers=headers)
        if code != 200 or not isinstance(data, list):
            return []
        return data

    def reject_entries(lobby_ids: list[str]) -> int:
        code, data = _request_json(server_url + "/api/admin/lobby/reject", method="POST", payload={"lobby_ids": lobby_ids}, headers=headers)
        if isinstance(data, dict):
            return data.get("rejected", 0)
        return 0

    curses.wrapper(lambda scr: _lobby_tui(scr, fetch_pending, accept_entries, reject_entries))
    return 0


def _lobby_tui(stdscr, fetch_pending, accept_entries, reject_entries) -> None:
    import curses

    curses.curs_set(0)
    stdscr.keypad(True)

    entries: list[dict[str, Any]] = []
    selected: set[str] = set()
    cursor = 0
    message = ""
    accepted_codes: list[dict[str, Any]] = []
    show_codes = False

    def reload():
        nonlocal entries, cursor
        entries = fetch_pending()
        current_ids = {e.get("lobby_id") for e in entries}
        selected.difference_update(selected - current_ids)
        if entries and cursor >= len(entries):
            cursor = len(entries) - 1
        if not entries:
            cursor = 0

    reload()

    while True:
        stdscr.clear()
        h, w = stdscr.getmaxyx()

        title = "AIQ Lobby — Pending Registrations"
        stdscr.addstr(0, 0, title[:w - 1], curses.A_BOLD)
        stdscr.addstr(1, 0, f"{len(entries)} pending · {len(selected)} selected · ↑↓ navigate · SPACE select · a accept · r reject · R refresh · q quit"[:w - 1])

        if show_codes and accepted_codes:
            stdscr.addstr(3, 0, "─ Accepted — share these invite codes:"[:w - 1], curses.A_BOLD)
            for i, item in enumerate(accepted_codes):
                line = f"  [{item.get('lobby_id')}] {item.get('name', '?')}: {item.get('invite_code', '')}"
                if 4 + i < h:
                    stdscr.addstr(4 + i, 0, line[:w - 1])
            stdscr.addstr(4 + len(accepted_codes) + 1, 0, "Press any key to continue..."[:w - 1])
            stdscr.getch()
            show_codes = False
            accepted_codes = []
            reload()
            continue

        if message:
            stdscr.addstr(3, 0, message[:w - 1], curses.A_REVERSE)

        start_row = 5
        for i, entry in enumerate(entries):
            if start_row + i >= h - 1:
                break
            lid = entry.get("lobby_id", "")
            name = entry.get("name", "?")
            email = entry.get("email", "")
            team = entry.get("team", "")
            emp_id = entry.get("employee_id", "")
            mark = "► " if i == cursor else "  "
            sel = "[*]" if lid in selected else "[ ]"
            line = f"{mark}{sel} {lid}  {name}  {email}  team={team}  id={emp_id}"
            attr = curses.A_REVERSE if i == cursor else curses.A_NORMAL
            stdscr.addstr(start_row + i, 0, line[:w - 1], attr)

        if not entries:
            stdscr.addstr(start_row, 0, "No pending lobby entries. Press R to refresh, q to quit."[:w - 1])

        stdscr.refresh()

        key = stdscr.getch()
        message = ""

        if key == curses.KEY_UP and entries:
            cursor = (cursor - 1) % len(entries)
        elif key == curses.KEY_DOWN and entries:
            cursor = (cursor + 1) % len(entries)
        elif key == ord(' ') and entries:
            lid = entries[cursor].get("lobby_id", "")
            if lid in selected:
                selected.discard(lid)
            else:
                selected.add(lid)
        elif key == ord('a') and selected:
            ids = list(selected)
            accepted_codes = accept_entries(ids)
            selected.clear()
            if accepted_codes:
                show_codes = True
            else:
                message = "Accept failed — no entries were accepted."
                reload()
        elif key == ord('r') and selected:
            ids = list(selected)
            count = reject_entries(ids)
            selected.clear()
            message = f"Rejected {count} entry(ies)."
            reload()
        elif key == ord('R'):
            reload()
            message = f"Refreshed. {len(entries)} pending."
        elif key == ord('q') or key == 27:
            break


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aiq-mothership", description="Run AIQ mothership natively without Docker")
    sub = parser.add_subparsers(dest="command", required=True)

    p_install = sub.add_parser("install", help="Create venv and install server dependencies")
    p_install.add_argument("--venv", default="", help="Virtualenv path (default: .venv-mothership)")
    p_install.add_argument("--data-dir", default="", help="Data directory for aiq.db (default: ~/.aiq/mothership)")
    p_install.add_argument("--port", type=int, default=8000, help="Default port to store in .env")
    p_install.add_argument("--admin-key", default=None, help="Set admin key in .env (empty string disables auth)")
    p_install.add_argument("--generate-admin-key", action="store_true", help="Generate and store a random admin key")
    p_install.set_defaults(func=command_install)

    p_run = sub.add_parser("run", help="Run the mothership API + dashboard")
    p_run.add_argument("--venv", default="", help="Virtualenv path (default: .venv-mothership)")
    p_run.add_argument("--host", default="0.0.0.0", help="Bind host")
    p_run.add_argument("--port", type=int, default=0, help="Bind port (default from .env or 8000)")
    p_run.add_argument("--data-dir", default="", help="Override data directory")
    p_run.add_argument("--admin-key", default=None, help="Override admin key for this run")
    p_run.set_defaults(func=command_run)

    p_health = sub.add_parser("health", help="Check a running mothership")
    p_health.add_argument("--server-url", default="http://localhost:8000", help="Mothership URL")
    p_health.set_defaults(func=command_health)

    p_invite = sub.add_parser("create-invite", help="Create an employee invite on a running mothership")
    p_invite.add_argument("--server-url", default="http://localhost:8000", help="Mothership URL")
    p_invite.add_argument("--admin-key", default="", help="Admin key (defaults to .env AIQ_ADMIN_KEY)")
    p_invite.add_argument("--team", default="", help="Default team for invite")
    p_invite.add_argument("--uses-remaining", type=int, default=1, help="Invite uses")
    p_invite.add_argument("--code", default="", help="Optional invite code")
    p_invite.set_defaults(func=command_create_invite)

    p_lobby = sub.add_parser("lobby", help="Interactive TUI to manage the lobby")
    p_lobby.add_argument("--server-url", default="http://localhost:8000", help="Mothership URL")
    p_lobby.add_argument("--admin-key", default="", help="Admin key (defaults to .env AIQ_ADMIN_KEY)")
    p_lobby.set_defaults(func=command_lobby)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
