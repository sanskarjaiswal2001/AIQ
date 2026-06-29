# AIQ Collector

Edge collector that parses your AI coding assistant logs (Claude Code; coming soon: Copilot, Codex, OpenCode) and pushes efficiency metrics to an AIQ mothership server.

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
aiq install-cron --interval-hours 6
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
| `aiq install-cron` | Install/remove a user crontab entry for scheduled collection |

## Config

Stored at `~/.aiq/config.toml`:

```toml
[server]
url = "https://aiq.yourcompany.com"
api_key = "ak_xxxxx"

[collector]
employee_id = "jane-doe"
interval_hours = 6
claude_dir = "~/.claude/projects"
```

## Supported AI Tools

- ✅ Claude Code (`~/.claude/projects/` logs)
- 🚧 GitHub Copilot (coming soon)
- 🚧 OpenAI Codex CLI (coming soon)
- 🚧 OpenCode (coming soon)

## Privacy

The collector only sends **metrics**: scores, token counts, anti-pattern flags, model usage, and work-type classifications. It never sends raw prompts, AI responses, code contents, or file contents.

## License

MIT
