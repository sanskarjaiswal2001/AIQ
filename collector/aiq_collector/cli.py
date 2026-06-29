"""Command-line interface for AIQ Collector.

Provides the `aiq` command:

    aiq collect
    aiq register --server-url ... --invite-code ...
    aiq config
    aiq status

Stdlib-only.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .collect import collect_metrics, post_to_server, print_summary

CONFIG_DIR = Path.home() / ".aiq"
CONFIG_PATH = CONFIG_DIR / "config.toml"
STATE_PATH = CONFIG_DIR / "state.json"
DEFAULT_INTERVAL_HOURS = 6


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    return value


def read_config(path: Path = CONFIG_PATH) -> dict[str, dict[str, Any]]:
    """Read ~/.aiq/config.toml.

    Uses stdlib ``tomllib`` on Python 3.11+. Falls back to a tiny TOML subset
    parser on Python 3.9/3.10 so the collector remains dependency-free.
    """
    cfg: dict[str, dict[str, Any]] = {"server": {}, "collector": {}}
    if not path.exists():
        return cfg

    text = path.read_text(encoding="utf-8")
    try:
        import tomllib  # Python 3.11+

        loaded = tomllib.loads(text)
        for section_name, values in loaded.items():
            if isinstance(values, dict):
                cfg[section_name] = dict(values)
        return cfg
    except ModuleNotFoundError:
        pass
    except Exception as exc:
        print(f"WARNING: failed to parse {path} with tomllib: {exc}; falling back to simple parser", file=sys.stderr)

    section = "collector"
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            cfg.setdefault(section, {})
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.split("#", 1)[0].strip()
        value = _strip_quotes(value)
        if key == "interval_hours":
            try:
                cfg.setdefault(section, {})[key] = float(value)
            except ValueError:
                cfg.setdefault(section, {})[key] = DEFAULT_INTERVAL_HOURS
        else:
            cfg.setdefault(section, {})[key] = value
    return cfg


def write_config(cfg: dict[str, dict[str, Any]], path: Path = CONFIG_PATH) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    server = cfg.get("server", {})
    collector = cfg.get("collector", {})
    content = f'''[server]
url = "{server.get('url', '')}"
api_key = "{server.get('api_key', '')}"

[collector]
employee_id = "{collector.get('employee_id', '')}"
interval_hours = {collector.get('interval_hours', DEFAULT_INTERVAL_HOURS)}
claude_dir = "{collector.get('claude_dir', '~/.claude/projects')}"
'''
    path.write_text(content, encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def update_config(**kwargs: Any) -> dict[str, dict[str, Any]]:
    cfg = read_config()
    cfg.setdefault("server", {})
    cfg.setdefault("collector", {})
    if kwargs.get("server_url") is not None:
        cfg["server"]["url"] = kwargs["server_url"] or ""
    if kwargs.get("api_key") is not None:
        cfg["server"]["api_key"] = kwargs["api_key"] or ""
    if kwargs.get("employee_id") is not None:
        cfg["collector"]["employee_id"] = kwargs["employee_id"] or ""
    if kwargs.get("claude_dir") is not None:
        cfg["collector"]["claude_dir"] = kwargs["claude_dir"] or ""
    if kwargs.get("interval_hours") is not None:
        cfg["collector"]["interval_hours"] = kwargs["interval_hours"]
    write_config(cfg)
    return cfg


def save_state(**kwargs: Any) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    state = {}
    if STATE_PATH.exists():
        try:
            state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            state = {}
    state.update(kwargs)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def ping_server(server_url: str) -> tuple[bool, str]:
    if not server_url:
        return False, "No server URL configured"
    endpoint = server_url.rstrip("/") + "/api/health"
    try:
        with urllib.request.urlopen(endpoint, timeout=10) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return 200 <= resp.status < 300, body
    except (urllib.error.URLError, OSError) as exc:
        return False, str(exc)


def command_collect(args: argparse.Namespace) -> int:
    cfg = read_config()
    server_url = args.server_url or cfg.get("server", {}).get("url", "")
    api_key = args.api_key or cfg.get("server", {}).get("api_key", "")
    employee_id = args.employee_id or cfg.get("collector", {}).get("employee_id", "")
    claude_dir = args.claude_dir or cfg.get("collector", {}).get("claude_dir", "")
    interval = args.interval or float(cfg.get("collector", {}).get("interval_hours", DEFAULT_INTERVAL_HOURS) or DEFAULT_INTERVAL_HOURS)

    def run_once() -> int:
        metrics = collect_metrics(
            claude_dir=claude_dir,
            employee_id=employee_id,
            period_start=args.period_start,
            period_end=args.period_end,
        )
        if not args.quiet:
            print_summary(metrics)

        if args.output_file:
            out_path = Path(args.output_file).expanduser()
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"\n  → Metrics written to {out_path}")

        posted = False
        if server_url:
            posted = post_to_server(server_url, metrics, api_key=api_key)
            if posted:
                print(f"  → Metrics POSTed to {server_url.rstrip('/')}/api/ingest")
            else:
                return 1

        save_state(
            last_collection_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            last_employee_id=employee_id,
            last_server_url=server_url,
            last_posted=posted,
            last_total_sessions=metrics.get("summary", {}).get("total_sessions", 0),
            last_total_requests=metrics.get("summary", {}).get("total_requests", 0),
        )
        return 0

    if args.daemon:
        print(f"AIQ collector daemon started. Interval: {interval:g}h. Press Ctrl+C to stop.")
        while True:
            code = run_once()
            if code != 0:
                print("Collection failed; retrying after interval.", file=sys.stderr)
            time.sleep(max(interval, 0.01) * 3600)
    return run_once()


def command_register(args: argparse.Namespace) -> int:
    endpoint = args.server_url.rstrip("/") + "/api/register"
    payload = {
        "invite_code": args.invite_code,
        "name": args.name or "",
        "team": args.team or "",
        "employee_id": args.employee_id or "",
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(endpoint, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        _ = exc.read()
        print("Registration not yet available on this server")
        return 1
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        print("Registration not yet available on this server")
        return 1

    api_key = data.get("api_key") or data.get("key") or ""
    employee_id = data.get("employee_id") or args.employee_id or ""
    if not api_key or not employee_id:
        print(f"Registration response missing api_key/employee_id: {data}", file=sys.stderr)
        return 1

    update_config(server_url=args.server_url, api_key=api_key, employee_id=employee_id)
    print(f"Registered employee {employee_id}. Config saved to {CONFIG_PATH}")
    return 0


def command_config(args: argparse.Namespace) -> int:
    changed = any(v is not None for v in [args.server_url, args.api_key, args.employee_id, args.claude_dir, args.interval_hours])
    cfg = update_config(
        server_url=args.server_url,
        api_key=args.api_key,
        employee_id=args.employee_id,
        claude_dir=args.claude_dir,
        interval_hours=args.interval_hours,
    ) if changed else read_config()

    print(f"Config: {CONFIG_PATH}")
    print("[server]")
    print(f"url = {cfg.get('server', {}).get('url', '') or '(unset)'}")
    key = cfg.get("server", {}).get("api_key", "")
    print(f"api_key = {'set (' + key[:8] + '…)' if key else '(unset)'}")
    print("[collector]")
    print(f"employee_id = {cfg.get('collector', {}).get('employee_id', '') or '(unset)'}")
    print(f"interval_hours = {cfg.get('collector', {}).get('interval_hours', DEFAULT_INTERVAL_HOURS)}")
    print(f"claude_dir = {cfg.get('collector', {}).get('claude_dir', '~/.claude/projects')}")
    if changed:
        print("Updated.")
    return 0


def command_status(args: argparse.Namespace) -> int:
    cfg = read_config()
    state = load_state()
    server_url = args.server_url or cfg.get("server", {}).get("url", "")
    claude_dir = Path(os.path.expanduser(cfg.get("collector", {}).get("claude_dir", "~/.claude/projects")))
    from .parser import ClaudeLogParser

    sessions = ClaudeLogParser(claude_dir=claude_dir).parse_directory() if claude_dir.exists() else []
    ok, msg = ping_server(server_url)

    print("AIQ Collector Status")
    print("====================")
    print(f"Config file       : {CONFIG_PATH} ({'exists' if CONFIG_PATH.exists() else 'missing'})")
    print(f"Employee ID       : {cfg.get('collector', {}).get('employee_id', '') or '(unset)'}")
    print(f"Server URL        : {server_url or '(unset)'}")
    print(f"API key           : {'set' if cfg.get('server', {}).get('api_key') else '(unset)'}")
    print(f"Claude logs       : {claude_dir} ({'exists' if claude_dir.exists() else 'missing'})")
    print(f"Sessions found    : {len(sessions)}")
    print(f"Requests found    : {sum(s.request_count for s in sessions)}")
    print(f"Server connection : {'ok' if ok else 'failed'}")
    if msg:
        print(f"Server response   : {msg[:200]}")
    if state:
        print(f"Last collection   : {state.get('last_collection_at', '(unknown)')}")
        print(f"Last totals       : {state.get('last_total_sessions', 0)} sessions, {state.get('last_total_requests', 0)} requests")
    else:
        print("Last collection   : never")
    return 0


def command_install_cron(args: argparse.Namespace) -> int:
    """Install a user crontab entry that runs `aiq collect` periodically."""
    interval = max(1, int(args.interval_hours or read_config().get("collector", {}).get("interval_hours", DEFAULT_INTERVAL_HOURS) or DEFAULT_INTERVAL_HOURS))
    aiq_path = Path(sys.argv[0]).resolve()
    log_path = CONFIG_DIR / "collector.log"
    cron_line = f"0 */{interval} * * * {aiq_path} collect --quiet >> {log_path} 2>&1 # AIQ_COLLECTOR"
    try:
        existing = subprocess.run(["crontab", "-l"], capture_output=True, text=True, check=False).stdout
    except FileNotFoundError:
        print("crontab is not available on this system. Use `aiq collect --daemon` instead.", file=sys.stderr)
        return 1
    lines = [line for line in existing.splitlines() if "# AIQ_COLLECTOR" not in line]
    if not args.remove:
        lines.append(cron_line)
    new_cron = "\n".join(lines).strip() + "\n"
    proc = subprocess.run(["crontab", "-"], input=new_cron, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        print(proc.stderr or "failed to update crontab", file=sys.stderr)
        return proc.returncode
    if args.remove:
        print("Removed AIQ collector cron entry.")
    else:
        print(f"Installed AIQ collector cron entry: every {interval} hour(s)")
        print(f"Logs: {log_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aiq", description="AIQ edge collector CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_collect = sub.add_parser("collect", help="Parse AI coding logs and push metrics")
    p_collect.add_argument("--employee-id", default="", help="Employee identifier")
    p_collect.add_argument("--server-url", default="", help="Mothership server URL")
    p_collect.add_argument("--api-key", default="", help="API key for X-API-Key header")
    p_collect.add_argument("--output-file", default="", help="Write metrics JSON locally")
    p_collect.add_argument("--claude-dir", default="", help="Override Claude projects directory")
    p_collect.add_argument("--period-start", default="", help="Override period start date (YYYY-MM-DD)")
    p_collect.add_argument("--period-end", default="", help="Override period end date (YYYY-MM-DD)")
    p_collect.add_argument("--daemon", action="store_true", help="Run forever and collect every interval")
    p_collect.add_argument("--interval", type=float, default=0, help="Daemon interval in hours (default from config or 6)")
    p_collect.add_argument("--quiet", action="store_true", help="Suppress summary output")
    p_collect.set_defaults(func=command_collect)

    p_register = sub.add_parser("register", help="Register with a mothership using an invite code")
    p_register.add_argument("--server-url", required=True, help="Mothership server URL")
    p_register.add_argument("--invite-code", required=True, help="Invite code from admin")
    p_register.add_argument("--name", default="", help="Employee display name")
    p_register.add_argument("--team", default="", help="Team name")
    p_register.add_argument("--employee-id", default="", help="Preferred employee ID")
    p_register.set_defaults(func=command_register)

    p_config = sub.add_parser("config", help="View or update ~/.aiq/config.toml")
    p_config.add_argument("--server-url", default=None, help="Set mothership server URL")
    p_config.add_argument("--api-key", default=None, help="Set API key")
    p_config.add_argument("--employee-id", default=None, help="Set employee ID")
    p_config.add_argument("--claude-dir", default=None, help="Set Claude projects directory")
    p_config.add_argument("--interval-hours", type=float, default=None, help="Set daemon interval")
    p_config.set_defaults(func=command_config)

    p_status = sub.add_parser("status", help="Show config, logs, and server health")
    p_status.add_argument("--server-url", default="", help="Override server URL for health check")
    p_status.set_defaults(func=command_status)

    p_cron = sub.add_parser("install-cron", help="Install or remove a user crontab entry for automatic collection")
    p_cron.add_argument("--interval-hours", type=float, default=None, help="Collection interval in hours (default from config or 6)")
    p_cron.add_argument("--remove", action="store_true", help="Remove the AIQ cron entry")
    p_cron.set_defaults(func=command_install_cron)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
