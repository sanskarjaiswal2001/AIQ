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
import getpass
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .collect import collect_metrics, post_to_server, print_summary
from .harnesses import SUPPORTED_HARNESSES, collect_sessions, discover_available_harnesses

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
employee_name = "{collector.get('employee_name', '')}"
employee_email = "{collector.get('employee_email', '')}"
interval_hours = {collector.get('interval_hours', DEFAULT_INTERVAL_HOURS)}
harnesses = "{collector.get('harnesses', 'auto')}"
claude_dir = "{collector.get('claude_dir', '~/.claude/projects')}"
codex_dir = "{collector.get('codex_dir', '~/.codex')}"
opencode_dir = "{collector.get('opencode_dir', '~/.opencode')}"
cursor_dir = "{collector.get('cursor_dir', '~/.cursor')}"
copilot_dir = "{collector.get('copilot_dir', '~/.config/Code/User/workspaceStorage')}"

[plan]
plan_type = "{cfg.get('plan', {}).get('plan_type', '')}"
plan_name = "{cfg.get('plan', {}).get('plan_name', '')}"
rolling_window_usd = {cfg.get('plan', {}).get('rolling_window_usd', 0) or 0}
rolling_window_days = {cfg.get('plan', {}).get('rolling_window_days', 0) or 0}
seat_cost_usd = {cfg.get('plan', {}).get('seat_cost_usd', 0) or 0}
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
    if kwargs.get("employee_name") is not None:
        cfg["collector"]["employee_name"] = kwargs["employee_name"] or ""
    if kwargs.get("employee_email") is not None:
        cfg["collector"]["employee_email"] = kwargs["employee_email"] or ""
    if kwargs.get("claude_dir") is not None:
        cfg["collector"]["claude_dir"] = kwargs["claude_dir"] or ""
    for key in ["harnesses", "codex_dir", "opencode_dir", "cursor_dir", "copilot_dir"]:
        if kwargs.get(key) is not None:
            cfg["collector"][key] = kwargs[key] or ""
    if kwargs.get("interval_hours") is not None:
        cfg["collector"]["interval_hours"] = kwargs["interval_hours"]
    cfg.setdefault("plan", {})
    for key in ["plan_type", "plan_name", "rolling_window_usd", "rolling_window_days", "seat_cost_usd"]:
        if kwargs.get(key) is not None:
            cfg["plan"][key] = kwargs[key]
    write_config(cfg)
    return cfg


def _git_config(key: str) -> str:
    try:
        proc = subprocess.run(["git", "config", "--global", key], capture_output=True, text=True, timeout=3, check=False)
        return proc.stdout.strip() if proc.returncode == 0 else ""
    except Exception:
        return ""


def _slugify(value: str) -> str:
    out = "".join(ch.lower() if ch.isalnum() else "-" for ch in value.strip()).strip("-")
    while "--" in out:
        out = out.replace("--", "-")
    return out or ""


def detect_user_identity() -> dict[str, str]:
    """Best-effort local identity detection for first setup."""
    git_name = _git_config("user.name")
    git_email = _git_config("user.email")
    username = getpass.getuser() or os.environ.get("USER") or os.environ.get("USERNAME") or ""
    full_name = ""
    if os.name != "nt":
        try:
            import pwd
            gecos = pwd.getpwuid(os.getuid()).pw_gecos.split(",", 1)[0].strip()
            if gecos and gecos.lower() not in {"unknown", username.lower()}:
                full_name = gecos
        except Exception:
            pass
    name = git_name or full_name or username
    employee_id = _slugify(git_email.split("@", 1)[0] if git_email else name or username)
    return {"name": name, "email": git_email, "employee_id": employee_id}


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
    employee_name = cfg.get("collector", {}).get("employee_name", "")
    employee_email = cfg.get("collector", {}).get("employee_email", "")
    claude_dir = args.claude_dir or cfg.get("collector", {}).get("claude_dir", "")
    harnesses = args.harnesses or cfg.get("collector", {}).get("harnesses", "auto")
    harness_dirs = {
        "claude": claude_dir,
        "codex": args.codex_dir or cfg.get("collector", {}).get("codex_dir", ""),
        "opencode": args.opencode_dir or cfg.get("collector", {}).get("opencode_dir", ""),
        "cursor": args.cursor_dir or cfg.get("collector", {}).get("cursor_dir", ""),
        "copilot": args.copilot_dir or cfg.get("collector", {}).get("copilot_dir", ""),
    }
    interval = args.interval or float(cfg.get("collector", {}).get("interval_hours", DEFAULT_INTERVAL_HOURS) or DEFAULT_INTERVAL_HOURS)

    plan_context = dict(cfg.get("plan", {}) or {})
    for key in ["plan_type", "plan_name", "rolling_window_usd", "rolling_window_days", "seat_cost_usd"]:
        value = getattr(args, key, None)
        if value is not None and value != "":
            plan_context[key] = value

    def run_once() -> int:
        metrics = collect_metrics(
            claude_dir=claude_dir,
            harnesses=harnesses,
            harness_dirs=harness_dirs,
            employee_id=employee_id,
            employee_name=employee_name,
            period_start=args.period_start,
            period_end=args.period_end,
            plan_context=plan_context,
        )
        if employee_email:
            metrics["employee_email"] = employee_email
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
    detected = detect_user_identity()
    name = args.name or detected.get("name") or ""
    email = args.email or detected.get("email") or ""
    employee_id = args.employee_id or detected.get("employee_id") or ""
    if not name or not employee_id:
        print("Could not infer your employee identity. Re-run with --name and --employee-id.", file=sys.stderr)
        return 1
    if not email:
        print("WARNING: could not infer employee email. Add --email now or set it later in the mothership admin dashboard.", file=sys.stderr)
    endpoint = args.server_url.rstrip("/") + "/api/register"
    payload = {
        "invite_code": args.invite_code,
        "name": name,
        "email": email,
        "team": args.team or "",
        "employee_id": employee_id,
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
    employee_id = data.get("employee_id") or employee_id or ""
    employee_name = data.get("name") or name or ""
    employee_email = data.get("email") or email or ""
    if not api_key or not employee_id:
        print(f"Registration response missing api_key/employee_id: {data}", file=sys.stderr)
        return 1

    update_config(server_url=args.server_url, api_key=api_key, employee_id=employee_id, employee_name=employee_name, employee_email=employee_email)
    who = f"{employee_name} ({employee_id})" if employee_name else employee_id
    print(f"Registered employee {who}. Config saved to {CONFIG_PATH}")
    return 0


def command_config(args: argparse.Namespace) -> int:
    changed = any(v is not None for v in [
        args.server_url, args.api_key, args.employee_id, args.employee_name, args.employee_email, args.claude_dir, args.harnesses,
        args.codex_dir, args.opencode_dir, args.cursor_dir, args.copilot_dir, args.interval_hours,
        args.plan_type, args.plan_name, args.rolling_window_usd, args.rolling_window_days, args.seat_cost_usd,
    ])
    cfg = update_config(
        server_url=args.server_url,
        api_key=args.api_key,
        employee_id=args.employee_id,
        employee_name=args.employee_name,
        employee_email=args.employee_email,
        claude_dir=args.claude_dir,
        harnesses=args.harnesses,
        codex_dir=args.codex_dir,
        opencode_dir=args.opencode_dir,
        cursor_dir=args.cursor_dir,
        copilot_dir=args.copilot_dir,
        interval_hours=args.interval_hours,
        plan_type=args.plan_type,
        plan_name=args.plan_name,
        rolling_window_usd=args.rolling_window_usd,
        rolling_window_days=args.rolling_window_days,
        seat_cost_usd=args.seat_cost_usd,
    ) if changed else read_config()

    print(f"Config: {CONFIG_PATH}")
    print("[server]")
    print(f"url = {cfg.get('server', {}).get('url', '') or '(unset)'}")
    key = cfg.get("server", {}).get("api_key", "")
    print(f"api_key = {'set (' + key[:8] + '…)' if key else '(unset)'}")
    print("[collector]")
    print(f"employee_id = {cfg.get('collector', {}).get('employee_id', '') or '(unset)'}")
    print(f"employee_name = {cfg.get('collector', {}).get('employee_name', '') or '(unset)'}")
    print(f"employee_email = {cfg.get('collector', {}).get('employee_email', '') or '(unset)'}")
    print(f"interval_hours = {cfg.get('collector', {}).get('interval_hours', DEFAULT_INTERVAL_HOURS)}")
    print(f"harnesses = {cfg.get('collector', {}).get('harnesses', 'auto')}")
    print(f"claude_dir = {cfg.get('collector', {}).get('claude_dir', '~/.claude/projects')}")
    print(f"codex_dir = {cfg.get('collector', {}).get('codex_dir', '~/.codex')}")
    print(f"opencode_dir = {cfg.get('collector', {}).get('opencode_dir', '~/.opencode')}")
    print(f"cursor_dir = {cfg.get('collector', {}).get('cursor_dir', '~/.cursor')}")
    print(f"copilot_dir = {cfg.get('collector', {}).get('copilot_dir', '~/.config/Code/User/workspaceStorage')}")
    plan = cfg.get('plan', {}) or {}
    print("[plan]")
    print(f"plan_type = {plan.get('plan_type', '') or '(unset)'}")
    print(f"plan_name = {plan.get('plan_name', '') or '(unset)'}")
    print(f"rolling_window_usd = {plan.get('rolling_window_usd', 0) or 0}")
    print(f"rolling_window_days = {plan.get('rolling_window_days', 0) or 0}")
    print(f"seat_cost_usd = {plan.get('seat_cost_usd', 0) or 0}")
    if changed:
        print("Updated.")
    return 0


def command_status(args: argparse.Namespace) -> int:
    cfg = read_config()
    state = load_state()
    server_url = args.server_url or cfg.get("server", {}).get("url", "")
    collector_cfg = cfg.get("collector", {})
    harnesses = args.harnesses or collector_cfg.get("harnesses", "auto")
    harness_dirs = {
        "claude": collector_cfg.get("claude_dir", ""),
        "codex": collector_cfg.get("codex_dir", ""),
        "opencode": collector_cfg.get("opencode_dir", ""),
        "cursor": collector_cfg.get("cursor_dir", ""),
        "copilot": collector_cfg.get("copilot_dir", ""),
    }
    availability = discover_available_harnesses(harness_dirs)
    sessions = collect_sessions(harnesses, dirs=harness_dirs)
    ok, msg = ping_server(server_url)

    print("AIQ Collector Status")
    print("====================")
    print(f"Config file       : {CONFIG_PATH} ({'exists' if CONFIG_PATH.exists() else 'missing'})")
    print(f"Employee ID       : {cfg.get('collector', {}).get('employee_id', '') or '(unset)'}")
    print(f"Employee name     : {cfg.get('collector', {}).get('employee_name', '') or '(unset)'}")
    print(f"Employee email    : {cfg.get('collector', {}).get('employee_email', '') or '(unset)'}")
    print(f"Server URL        : {server_url or '(unset)'}")
    print(f"API key           : {'set' if cfg.get('server', {}).get('api_key') else '(unset)'}")
    print(f"Harnesses         : {harnesses}")
    for name in SUPPORTED_HARNESSES:
        info = availability[name]
        print(f"  {name:<8} logs  : {info['path']} ({'exists' if info['exists'] else 'missing'})")
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


def _is_wsl() -> bool:
    if platform.system().lower() != "linux":
        return False
    try:
        return "microsoft" in Path("/proc/version").read_text(encoding="utf-8", errors="ignore").lower()
    except OSError:
        return False


def _collector_command() -> list[str]:
    """Return a robust command for scheduled collection."""
    return [sys.executable, "-m", "aiq_collector.cli", "collect", "--quiet"]


def _shell_join(parts: list[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(parts)
    return " ".join(shlex.quote(p) for p in parts)


def _install_systemd_timer(interval: int, remove: bool) -> int | None:
    """Install a Linux user systemd timer. Return None if systemd isn't usable."""
    systemctl = shutil.which("systemctl")
    if not systemctl or os.name == "nt":
        return None
    probe = subprocess.run([systemctl, "--user", "is-system-running"], capture_output=True, text=True, check=False)
    if "Failed to connect" in (probe.stderr + probe.stdout) or "No medium found" in (probe.stderr + probe.stdout):
        return None

    unit_dir = Path.home() / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    service = unit_dir / "aiq-collector.service"
    timer = unit_dir / "aiq-collector.timer"
    log_path = CONFIG_DIR / "collector.log"
    cmd = _collector_command()

    if remove:
        subprocess.run([systemctl, "--user", "disable", "--now", "aiq-collector.timer"], check=False)
        for path in [service, timer]:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        subprocess.run([systemctl, "--user", "daemon-reload"], check=False)
        print("Removed AIQ collector systemd user timer.")
        return 0

    service.write_text(f"""[Unit]
Description=AIQ edge collector

[Service]
Type=oneshot
ExecStart={_shell_join(cmd)}
StandardOutput=append:{log_path}
StandardError=append:{log_path}
""", encoding="utf-8")
    timer.write_text(f"""[Unit]
Description=Run AIQ edge collector every {interval} hour(s)

[Timer]
OnBootSec=5min
OnUnitActiveSec={interval}h
Persistent=true

[Install]
WantedBy=timers.target
""", encoding="utf-8")
    subprocess.check_call([systemctl, "--user", "daemon-reload"])
    subprocess.check_call([systemctl, "--user", "enable", "--now", "aiq-collector.timer"])
    print(f"Installed AIQ collector systemd user timer: every {interval} hour(s)")
    print(f"Logs: {log_path}")
    if _is_wsl():
        print("Note: WSL requires systemd enabled for timers to run after shell exit. If disabled, use --backend cron or daemon mode.")
    return 0


def _install_cron_entry(interval: int, remove: bool) -> int:
    log_path = CONFIG_DIR / "collector.log"
    cron_line = f"0 */{interval} * * * {_shell_join(_collector_command())} >> {shlex.quote(str(log_path))} 2>&1 # AIQ_COLLECTOR"
    try:
        existing = subprocess.run(["crontab", "-l"], capture_output=True, text=True, check=False).stdout
    except FileNotFoundError:
        print("crontab is not available on this system. Use `aiq collect --daemon` instead.", file=sys.stderr)
        return 1
    lines = [line for line in existing.splitlines() if "# AIQ_COLLECTOR" not in line]
    if not remove:
        lines.append(cron_line)
    new_cron = "\n".join(lines).strip() + "\n"
    proc = subprocess.run(["crontab", "-"], input=new_cron, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        print(proc.stderr or "failed to update crontab", file=sys.stderr)
        return proc.returncode
    if remove:
        print("Removed AIQ collector cron entry.")
    else:
        print(f"Installed AIQ collector cron entry: every {interval} hour(s)")
        print(f"Logs: {log_path}")
    return 0


def _install_launchd(interval: int, remove: bool) -> int:
    label = "dev.aiq.collector"
    plist_dir = Path.home() / "Library" / "LaunchAgents"
    plist_dir.mkdir(parents=True, exist_ok=True)
    plist = plist_dir / f"{label}.plist"
    log_path = CONFIG_DIR / "collector.log"
    err_path = CONFIG_DIR / "collector.err.log"
    if remove:
        subprocess.run(["launchctl", "unload", str(plist)], check=False, capture_output=True)
        try:
            plist.unlink()
        except FileNotFoundError:
            pass
        print("Removed AIQ collector launchd job.")
        return 0
    args_xml = "\n".join(f"        <string>{arg}</string>" for arg in _collector_command())
    plist.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
{args_xml}
    </array>
    <key>StartInterval</key>
    <integer>{interval * 3600}</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{log_path}</string>
    <key>StandardErrorPath</key>
    <string>{err_path}</string>
</dict>
</plist>
""", encoding="utf-8")
    subprocess.run(["launchctl", "unload", str(plist)], check=False, capture_output=True)
    proc = subprocess.run(["launchctl", "load", str(plist)], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        print(proc.stderr or "failed to load launchd plist", file=sys.stderr)
        return proc.returncode
    print(f"Installed AIQ collector launchd job: every {interval} hour(s)")
    print(f"Plist: {plist}")
    print(f"Logs: {log_path}")
    return 0


def _install_windows_task(interval: int, remove: bool) -> int:
    task_name = "AIQ Collector"
    if remove:
        proc = subprocess.run(["schtasks", "/Delete", "/TN", task_name, "/F"], capture_output=True, text=True, check=False)
        if proc.returncode not in (0, 1):
            print(proc.stderr or proc.stdout, file=sys.stderr)
            return proc.returncode
        print("Removed AIQ collector Windows scheduled task.")
        return 0
    cmd = _shell_join(_collector_command())
    proc = subprocess.run([
        "schtasks", "/Create", "/F", "/SC", "HOURLY", "/MO", str(interval),
        "/TN", task_name, "/TR", cmd,
    ], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        print(proc.stderr or proc.stdout or "failed to create scheduled task", file=sys.stderr)
        return proc.returncode
    print(f"Installed Windows scheduled task '{task_name}': every {interval} hour(s)")
    return 0


def command_install_autostart(args: argparse.Namespace) -> int:
    """Install/remove OS-native scheduled collection."""
    interval = max(1, int(args.interval_hours or read_config().get("collector", {}).get("interval_hours", DEFAULT_INTERVAL_HOURS) or DEFAULT_INTERVAL_HOURS))
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    system = platform.system().lower()
    backend = (args.backend or "auto").lower()

    if backend == "auto":
        if system == "windows":
            backend = "task-scheduler"
        elif system == "darwin":
            backend = "launchd"
        else:
            backend = "systemd"

    if backend in {"task-scheduler", "windows"}:
        if system != "windows":
            print("Windows Task Scheduler backend is only available on Windows.", file=sys.stderr)
            return 1
        return _install_windows_task(interval, args.remove)
    if backend == "launchd":
        if system != "darwin":
            print("launchd backend is only available on macOS.", file=sys.stderr)
            return 1
        return _install_launchd(interval, args.remove)
    if backend == "cron":
        return _install_cron_entry(interval, args.remove)
    if backend == "systemd":
        rc = _install_systemd_timer(interval, args.remove)
        if rc is not None:
            return rc
        print("systemd user timer unavailable; falling back to cron.")
        return _install_cron_entry(interval, args.remove)

    print(f"Unknown backend: {backend}", file=sys.stderr)
    return 1


def command_install_cron(args: argparse.Namespace) -> int:
    """Backward-compatible alias for install-autostart --backend cron."""
    args.backend = "cron"
    return command_install_autostart(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aiq", description="AIQ edge collector CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_collect = sub.add_parser("collect", help="Parse AI coding logs and push metrics")
    p_collect.add_argument("--employee-id", default="", help="Employee identifier")
    p_collect.add_argument("--server-url", default="", help="Mothership server URL")
    p_collect.add_argument("--api-key", default="", help="API key for X-API-Key header")
    p_collect.add_argument("--output-file", default="", help="Write metrics JSON locally")
    p_collect.add_argument("--claude-dir", default="", help="Override Claude projects directory")
    p_collect.add_argument("--harnesses", default="", help="Comma-separated harnesses: auto, claude, codex, opencode, cursor, copilot")
    p_collect.add_argument("--codex-dir", default="", help="Override Codex log directory")
    p_collect.add_argument("--opencode-dir", default="", help="Override OpenCode log directory")
    p_collect.add_argument("--cursor-dir", default="", help="Override Cursor log directory")
    p_collect.add_argument("--copilot-dir", default="", help="Override Copilot/VS Code workspaceStorage directory")
    p_collect.add_argument("--period-start", default="", help="Override period start date (YYYY-MM-DD)")
    p_collect.add_argument("--period-end", default="", help="Override period end date (YYYY-MM-DD)")
    p_collect.add_argument("--daemon", action="store_true", help="Run forever and collect every interval")
    p_collect.add_argument("--interval", type=float, default=0, help="Daemon interval in hours (default from config or 6)")
    p_collect.add_argument("--quiet", action="store_true", help="Suppress summary output")
    p_collect.add_argument("--plan-type", default="", help="Billing plan type: api, seat, rolling_window, enterprise_rolling_window")
    p_collect.add_argument("--plan-name", default="", help="Human-readable plan name, e.g. Claude Team")
    p_collect.add_argument("--rolling-window-usd", type=float, default=None, help="Per-user rolling window/quota in USD-equivalent")
    p_collect.add_argument("--rolling-window-days", type=int, default=None, help="Rolling window length in days")
    p_collect.add_argument("--seat-cost-usd", type=float, default=None, help="Fixed monthly seat cost in USD")
    p_collect.set_defaults(func=command_collect)

    p_register = sub.add_parser("register", help="Register with a mothership using an invite code")
    p_register.add_argument("--server-url", required=True, help="Mothership server URL")
    p_register.add_argument("--invite-code", required=True, help="Invite code from admin")
    p_register.add_argument("--name", default="", help="Employee display name; defaults to git/OS identity when available")
    p_register.add_argument("--email", default="", help="Employee email; defaults to git config user.email when available")
    p_register.add_argument("--team", default="", help="Team name")
    p_register.add_argument("--employee-id", default="", help="Preferred employee ID")
    p_register.set_defaults(func=command_register)

    p_config = sub.add_parser("config", help="View or update ~/.aiq/config.toml")
    p_config.add_argument("--server-url", default=None, help="Set mothership server URL")
    p_config.add_argument("--api-key", default=None, help="Set API key")
    p_config.add_argument("--employee-id", default=None, help="Set employee ID")
    p_config.add_argument("--employee-name", default=None, help="Set employee display name")
    p_config.add_argument("--employee-email", default=None, help="Set employee email")
    p_config.add_argument("--claude-dir", default=None, help="Set Claude projects directory")
    p_config.add_argument("--harnesses", default=None, help="Set harnesses: auto or comma-separated supported harnesses")
    p_config.add_argument("--codex-dir", default=None, help="Set Codex log directory")
    p_config.add_argument("--opencode-dir", default=None, help="Set OpenCode log directory")
    p_config.add_argument("--cursor-dir", default=None, help="Set Cursor log directory")
    p_config.add_argument("--copilot-dir", default=None, help="Set Copilot/VS Code workspaceStorage directory")
    p_config.add_argument("--interval-hours", type=float, default=None, help="Set daemon interval")
    p_config.add_argument("--plan-type", default=None, help="Set billing plan type: api, seat, rolling_window, enterprise_rolling_window")
    p_config.add_argument("--plan-name", default=None, help="Set human-readable plan name")
    p_config.add_argument("--rolling-window-usd", type=float, default=None, help="Set per-user rolling window/quota in USD-equivalent")
    p_config.add_argument("--rolling-window-days", type=int, default=None, help="Set rolling window length in days")
    p_config.add_argument("--seat-cost-usd", type=float, default=None, help="Set fixed monthly seat cost in USD")
    p_config.set_defaults(func=command_config)

    p_status = sub.add_parser("status", help="Show config, logs, and server health")
    p_status.add_argument("--server-url", default="", help="Override server URL for health check")
    p_status.add_argument("--harnesses", default="", help="Override harness selection for session count")
    p_status.set_defaults(func=command_status)

    p_autostart = sub.add_parser("install-autostart", help="Install/remove OS-native scheduled collection")
    p_autostart.add_argument("--interval-hours", type=float, default=None, help="Collection interval in hours (default from config or 6)")
    p_autostart.add_argument("--backend", choices=["auto", "systemd", "cron", "launchd", "task-scheduler"], default="auto", help="Scheduler backend (default: auto)")
    p_autostart.add_argument("--remove", action="store_true", help="Remove the AIQ scheduled job")
    p_autostart.set_defaults(func=command_install_autostart)

    p_cron = sub.add_parser("install-cron", help="Compatibility alias: install/remove a cron entry")
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
