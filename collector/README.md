# AIQ Collector

Edge collector that parses your AI coding assistant logs (Claude Code, Codex, OpenCode, Cursor, and Copilot best-effort JSON logs) and pushes efficiency metrics to an AIQ mothership server.

## Install

```bash
pip install aiq-collector
```

For local development from this repository:

```bash
cd collector
pip install -e .
```

## Quick Start

1. **Register with your mothership:**
```bash
aiq register --server-url https://aiq.yourcompany.com --invite-code ABC123 --employee-id jane-doe --name "Jane Doe" --team "Engineering"
```

2. **Collect and push:**
```bash
aiq collect
```

3. **Run automatically every 6 hours:**
```bash
aiq install-autostart --interval-hours 6
```

This chooses the native scheduler for your OS:

| OS | Scheduler |
|---|---|
| Linux / WSL | systemd user timer, fallback to cron |
| macOS | launchd LaunchAgent |
| Windows | Task Scheduler |

Force a backend if needed:

```bash
aiq install-autostart --backend cron --interval-hours 6
aiq install-autostart --backend launchd --interval-hours 6
aiq install-autostart --backend task-scheduler --interval-hours 6
```

Remove auto-run:

```bash
aiq install-autostart --remove
```

Or run foreground daemon mode:

```bash
aiq collect --daemon --interval 6
```

## Commands

| Command | Description |
|---------|-------------|
| `aiq register` | Register with a mothership server using an invite code; stores API key locally |
| `aiq collect` | Parse logs and push metrics to the server |
| `aiq config` | View or update `~/.aiq/config.toml` |
| `aiq status` | Show config, sessions found, last run, and server health |
| `aiq install-autostart` | Install/remove OS-native scheduled collection: systemd/cron, launchd, or Windows Task Scheduler |
| `aiq install-cron` | Compatibility alias for Linux/WSL cron users |

## Config

Stored at `~/.aiq/config.toml`:

```toml
[server]
url = "https://aiq.yourcompany.com"
api_key = "ak_xxxxx"

[collector]
employee_id = "jane-doe"
interval_hours = 6
harnesses = "auto"
claude_dir = "~/.claude/projects"
codex_dir = "~/.codex"
opencode_dir = "~/.opencode"
cursor_dir = "~/.cursor"
copilot_dir = "~/.config/Code/User/workspaceStorage"

[plan]
# api | seat | rolling_window | enterprise_rolling_window
plan_type = "enterprise_rolling_window"
plan_name = "Claude Team"
rolling_window_usd = 25
rolling_window_days = 30
seat_cost_usd = 25
```

## Supported AI Tools

- ✅ Claude Code (`~/.claude/projects/` logs; dedicated parser)
- ✅ OpenAI Codex CLI (`~/.codex`; generic JSON/JSONL parser)
- ✅ OpenCode (`~/.opencode`; generic JSON/JSONL parser)
- ✅ Cursor (`~/.cursor`; generic JSON/JSONL parser)
- ✅ GitHub Copilot / VS Code agent logs (`~/.config/Code/User/workspaceStorage`; generic JSON/JSONL parser)

By default `aiq collect` uses `harnesses = "auto"`, which scans every supported harness directory that exists. To restrict collection:

```bash
aiq collect --harnesses claude,codex
aiq config --harnesses claude,opencode --opencode-dir ~/.opencode
```

The non-Claude parsers are intentionally tolerant because vendors change local log formats often. They look for common `role` / `type` / `content` / `usage` / `tool_calls` fields and normalize them into AIQ's shared session model.

## Privacy

The collector only sends **metrics**: scores, token counts, anti-pattern flags, model usage, and work-type classifications. It never sends raw prompts, AI responses, code contents, or file contents.

## License

AIQ Commercial Source License — see the [root LICENSE](../LICENSE). Free for BETSOL commercial use and personal/evaluation use; other companies need a paid commercial license.
