#!/usr/bin/env python3
"""
collect.py — core collection logic for the AIQ edge collector.

Parses AI coding assistant session logs, runs the analyzer, and either POSTs the
result JSON to a dashboard server or writes it to a local file.

This module provides the reusable functions (``collect_metrics``,
``post_to_server``, ``print_summary``) that are invoked by ``cli.py``.
It can also be run standalone::

    python3 -m aiq_collector.collect --employee-id "john-doe" --server-url http://localhost:8000
    python3 -m aiq_collector.collect --output-file metrics.json
    python3 -m aiq_collector.collect --harnesses claude,codex --output-file out.json

Stdlib-only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .analyzer import Analyzer
from .harnesses import collect_sessions


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="collect",
        description="Parse AI coding assistant logs and emit AI-engineering efficiency metrics.",
    )
    p.add_argument(
        "--employee-id", default="",
        help="Employee identifier to attach to the metrics payload.",
    )
    p.add_argument(
        "--server-url", default="",
        help="Dashboard server base URL. When set, POSTs metrics to {server-url}/api/ingest.",
    )
    p.add_argument(
        "--output-file", default="",
        help="Write the metrics JSON to this local file (useful for testing).",
    )
    p.add_argument(
        "--claude-dir", default="",
        help="Override the Claude projects directory (default: ~/.claude/projects).",
    )
    p.add_argument("--harnesses", default="auto", help="Comma-separated harnesses: auto, claude, codex, opencode, cursor, copilot")
    p.add_argument("--codex-dir", default="", help="Override Codex log directory (default: ~/.codex)")
    p.add_argument("--opencode-dir", default="", help="Override OpenCode log directory (default: ~/.opencode)")
    p.add_argument("--cursor-dir", default="", help="Override Cursor log directory (default: ~/.cursor)")
    p.add_argument("--copilot-dir", default="", help="Override Copilot/VS Code workspaceStorage directory")
    p.add_argument(
        "--period-start", default="",
        help="Override period start date (YYYY-MM-DD). Inferred from logs if omitted.",
    )
    p.add_argument(
        "--period-end", default="",
        help="Override period end date (YYYY-MM-DD). Inferred from logs if omitted.",
    )
    p.add_argument(
        "--quiet", action="store_true",
        help="Suppress the summary printed to stdout.",
    )
    p.add_argument("--plan-type", default="", help="Billing plan type: api, seat, rolling_window, enterprise_rolling_window")
    p.add_argument("--plan-name", default="", help="Human-readable plan name")
    p.add_argument("--rolling-window-usd", type=float, default=None, help="Per-user rolling window/quota in USD-equivalent")
    p.add_argument("--rolling-window-days", type=int, default=None, help="Rolling window length in days")
    p.add_argument("--seat-cost-usd", type=float, default=None, help="Fixed monthly seat cost in USD")
    return p.parse_args(argv)


def collect_metrics(
    claude_dir: str = "",
    harnesses: str = "auto",
    harness_dirs: dict | None = None,
    employee_id: str = "",
    employee_name: str = "",
    period_start: str = "",
    period_end: str = "",
    plan_context: dict | None = None,
) -> dict:
    """Parse logs and run the analyzer. Returns the metrics dict."""
    dirs = dict(harness_dirs or {})
    if claude_dir:
        dirs["claude"] = os.path.expanduser(claude_dir)
    sessions = collect_sessions(harnesses, dirs=dirs)
    analyzer = Analyzer()
    return analyzer.analyze(
        sessions,
        employee_id=employee_id,
        employee_name=employee_name,
        period_start=period_start,
        period_end=period_end,
        plan_context=plan_context or {},
    )


def post_to_server(server_url: str, payload: dict, api_key: str = "") -> bool:
    """POST the metrics payload to ``{server_url}/api/ingest``. Returns True on
    success (2xx), False on failure."""
    endpoint = server_url.rstrip("/") + "/api/ingest"
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    req = urllib.request.Request(
        endpoint,
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            status = resp.status
            return 200 <= status < 300
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            body = json.loads(exc.read().decode("utf-8", errors="replace"))
            detail = f" — {body.get('detail', body)}"
        except Exception:
            pass
        print(f"ERROR: {endpoint} rejected the request: HTTP {exc.code}{detail}", file=sys.stderr)
        return False
    except (urllib.error.URLError, OSError) as exc:
        print(f"ERROR: failed to reach {endpoint}: {exc}. Check the server is running and reachable on this network.", file=sys.stderr)
        return False
    except Exception as exc:  # pragma: no cover — defensive
        print(f"ERROR: unexpected error posting to {endpoint}: {exc}", file=sys.stderr)
        return False


def print_summary(metrics: dict) -> None:
    """Print a human-readable summary of collected metrics to stdout."""
    s = metrics["summary"]
    print("=" * 60)
    print("  AI-Engineering-Coach — Collector Summary")
    print("=" * 60)
    print(f"  Employee ID     : {metrics.get('employee_id') or '(none)'}")
    print(f"  Period          : {metrics['period_start']} → {metrics['period_end']}")
    print(f"  Collected at    : {metrics['collected_at']}")
    print("-" * 60)
    print(f"  Sessions        : {s['total_sessions']}")
    print(f"  Requests        : {s['total_requests']}")
    print(f"  Workspaces      : {s['total_workspaces']}")
    print(f"  AI LoC          : {s['total_ai_loc']:,}")
    print(f"  User LoC        : {s['total_user_loc']:,}")
    print(f"  Input tokens    : {s['total_input_tokens']:,}")
    print(f"  Output tokens   : {s['total_output_tokens']:,}")
    print(f"  Est. cost (USD) : ${s['estimated_cost_usd']:.4f}")
    plan = metrics.get("plan_context") or {}
    if plan:
        bits = [plan.get("plan_name") or plan.get("plan_type") or "configured"]
        if plan.get("rolling_window_usd"):
            bits.append(f"${float(plan.get('rolling_window_usd') or 0):.0f} rolling window")
        print(f"  Plan context    : {' · '.join(str(b) for b in bits if b)}")
    print("-" * 60)

    print("  Practice scores:")
    for group, data in metrics["practice_scores"].items():
        print(f"    {group:<22} {data['score']:>3}/100  "
              f"({len(data['weekly'])} weeks tracked)")
    print("-" * 60)

    triggered = [ap for ap in metrics["anti_patterns"] if ap["triggered"]]
    print(f"  Anti-patterns triggered : {len(triggered)} / {len(metrics['anti_patterns'])}")
    for ap in triggered:
        print(f"    [{ap['severity'].upper():>6}] {ap['rule_id']:<35} "
              f"({ap['occurrences']}/{ap['total']})")
    print("-" * 60)

    print("  Model usage:")
    for model, usage in metrics["model_usage"].items():
        print(f"    {model:<25} {usage['requests']:>4} reqs  "
              f"${usage['cost_usd']:>8.4f}")
    print("-" * 60)

    print("  Work types:")
    for wtype, count in sorted(metrics["work_types"].items(), key=lambda x: -x[1]):
        print(f"    {wtype:<15} {count}")
    print("-" * 60)

    ws = metrics["activity"]["workspaces"]
    print(f"  Workspaces ({len(ws)}):")
    for name, data in sorted(ws.items(), key=lambda x: -x[1]["requests"]):
        print(f"    {name:<40} {data['requests']:>4} reqs  "
              f"{data['sessions']:>3} sessions  {data['ai_loc']:>6} LoC")
    print("=" * 60)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    plan_context = {
        "plan_type": args.plan_type,
        "plan_name": args.plan_name,
        "rolling_window_usd": args.rolling_window_usd or 0,
        "rolling_window_days": args.rolling_window_days or 0,
        "seat_cost_usd": args.seat_cost_usd or 0,
    }
    metrics = collect_metrics(
        claude_dir=args.claude_dir,
        harnesses=args.harnesses,
        harness_dirs={
            "codex": args.codex_dir,
            "opencode": args.opencode_dir,
            "cursor": args.cursor_dir,
            "copilot": args.copilot_dir,
        },
        employee_id=args.employee_id,
        period_start=args.period_start,
        period_end=args.period_end,
        plan_context=plan_context,
    )

    if not args.quiet:
        print_summary(metrics)

    # Write to file if requested
    if args.output_file:
        out_path = Path(args.output_file)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n  → Metrics written to {out_path}")

    # POST to server if requested
    if args.server_url:
        ok = post_to_server(args.server_url, metrics)
        if ok:
            print(f"  → Metrics POSTed to {args.server_url.rstrip('/')}/api/ingest")
        else:
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
