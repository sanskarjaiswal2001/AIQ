<div align="center">

# ⚡ AIQ

### AI Quotient — measure how efficiently your team uses AI coding tools

Track prompt quality, code review habits, model selection, and cost across your entire engineering org. Get actionable training recommendations and plan upgrade advice per employee.

[![License: Custom](https://img.shields.io/badge/license-Commercial%20Source-orange)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/docker-ready-2496ED)](https://www.docker.com/)

</div>

---

## What it does

AIQ reads AI coding assistant session logs (Claude Code, Copilot, Codex — see [supported tools](#supported-ai-tools)) and turns them into management-ready insights:

- **Practice scores** (0–100) across 5 dimensions: prompt quality, session hygiene, code review, tool mastery, context management
- **20 anti-pattern detectors** — lazy prompting, speed-accepting AI code, premium model waste, runaway agent loops, and more
- **Training recommendations** — specific modules per employee, prioritized by severity
- **Plan recommendations** — who should upgrade, who should train first, who should downgrade
- **Plan-aware cost tracking** — API spend vs seat/rolling-window quota pressure, per employee, model, team, and project
- **Project and staffing intelligence** — where AI spend goes, who can take more work, who needs training first, and masked exports for client/investor views

Built on the data model from [Microsoft's AI-Engineering-Coach](https://github.com/microsoft/AI-Engineering-Coach).

## Architecture

```
┌──────────────────────────────────────────────────────┐
│  ORG ADMIN                                           │
│  Native Python or Docker → mothership on port 8000   │
│  Create org → invite employees                       │
└──────────────────────────────────────────────────────┘
                        │
            ┌───────────┴───────────┐
            ▼                       ▼
┌──────────────────┐     ┌──────────────────────────┐
│  EMPLOYEE        │     │  MANAGEMENT              │
│  pip install     │     │  Opens dashboard in      │
│  aiq-collector   │     │  browser → sees:         │
│  aiq register    │     │  • Team overview         │
│  aiq collect     │     │  • Executive overview    │
│  → pushes metrics│     │  • Employee grid         │
│    to mothership │     │  • Training needs matrix │
│  → sees own data │     │  • Plan recommendations  │
│    at /me        │     │  • Projects + staffing   │
│                  │     │  • Anti-pattern rules    │
│                  │     │  • Drill-down per person │
└──────────────────┘     └──────────────────────────┘
```

**Two parts:**
- **Mothership** — self-hosted server (FastAPI + SQLite) + management dashboard. Runs natively on Linux, WSL, macOS, and Windows; Docker Compose is optional.
- **Edge collector** — lightweight CLI (`pip install aiq-collector`) that parses local AI logs and pushes metrics to the mothership. Auto-runs with systemd/cron on Linux/WSL, launchd on macOS, and Task Scheduler on Windows.

See the full [cross-platform install guide](docs/cross-platform.md).

## Quick Start

### Deploy the mothership natively (Linux / WSL / macOS / Windows)

```bash
git clone https://github.com/sanskarjaiswal2001/AIQ.git
cd AIQ
python scripts/aiq-mothership.py install --generate-admin-key
python scripts/aiq-mothership.py run --host 0.0.0.0 --port 8000

# In another terminal, create an employee invite
python scripts/aiq-mothership.py create-invite --server-url http://localhost:8000 --team Engineering
```

Windows PowerShell:

```powershell
git clone https://github.com/sanskarjaiswal2001/AIQ.git
cd AIQ
py scripts\aiq-mothership.py install --generate-admin-key
py scripts\aiq-mothership.py run --host 0.0.0.0 --port 8000
```

Dashboard is now live at `http://localhost:8000`.

### Run a LAN demo (mothership + collectors on separate laptops)

The mothership already binds `0.0.0.0` and allows CORS from anywhere, so no code changes are needed — one laptop hosts the mothership, everyone else's collector points at it over the local network.

**On the host laptop (runs the mothership):**

```bash
python scripts/aiq-mothership.py install --generate-admin-key   # once
python scripts/aiq-mothership.py run --port 8000                # binds 0.0.0.0
```

macOS will prompt "Allow incoming connections" for Python the first time — click **Allow** (if collectors later get connection-refused/timeouts, this is the first thing to check — System Settings → Network → Firewall).

Find the host's LAN address:
- `hostname` → e.g. `Konis-MacBook.local` (mDNS `.local` name, survives DHCP/IP changes, works cross-platform on the same network) — **preferred**
- `ipconfig getifaddr en0` (macOS) / `ipconfig` (Windows) / `ip addr` (Linux) → raw IP, fallback if `.local` doesn't resolve

You have two registration options — **lobby mode** (easier for group demos, no pre-generated codes needed) or **invite-code mode** (more controlled, admin creates codes upfront).

**Option A: Lobby mode (recommended for group demos)**

Everyone self-registers into the lobby, then the host accepts them from the TUI:

```bash
# On every collector laptop (including the host's own):
cd AIQ/collector
python3 -m aiq_collector.cli register --server-url http://<host-hostname-or-ip>:8000 \
  --lobby --name "Your Name" --email you@company.com
# → prints a 6-digit lobby ID, status: pending

# On the host laptop — review and accept pending devices:
python scripts/aiq-mothership.py lobby --server-url http://localhost:8000
# TUI: ↑↓ navigate, SPACE to select, 'a' to accept (generates invite codes),
# 'r' to reject, 'R' to refresh, 'q' to quit
# After accepting, share the invite codes shown, OR tell each person to re-run:
#   aiq register --server-url http://<host>:8000 --lobby-id <their-lobby-id>
# → auto-detects acceptance, pulls the invite code, and completes registration
```

**Option B: Invite-code mode**

Create one invite per person (or one invite with `--uses-remaining N`):

```bash
python scripts/aiq-mothership.py create-invite --team Demo --uses-remaining 5
```

```bash
# On every collector laptop (including the host's own):
cd AIQ/collector
python3 -m aiq_collector.cli register --server-url http://<host-hostname-or-ip>:8000 \
  --invite-code <code> --name "Your Name" --email you@company.com
```

Either way, run collection after registration:

```bash
python3 -m aiq_collector.cli collect
```

Employee ids are assigned automatically as sequential numbers by the mothership — nothing to configure. For a live-updating demo, loop collection instead of running it once:

```bash
python3 -m aiq_collector.cli collect --daemon --interval 0.25   # every 15 minutes
```

**Dashboard**, from any laptop on the LAN: `http://<host-hostname-or-ip>:8000/` (admin) and `.../me` (personal, using the API key `register` printed).

### "Set this up locally for me" agent prompt

If you use Claude Code, Codex, Cursor Agent, Copilot coding agent, or another local coding agent, paste this prompt to have it set up AIQ on your machine without deploying anything externally:

```text
Set up AIQ locally so I can see my own AI coding efficiency dashboard. Do not deploy anything to the cloud and do not require Docker unless native setup fails.

Repository: https://github.com/sanskarjaiswal2001/AIQ

Goal:
- Clone the repo locally.
- Install and run the AIQ mothership natively on localhost.
- Create a local invite.
- Install the AIQ collector from the local repo.
- Register me with my real display name and team. Do not use placeholder names like "local", "Local User", or "local-user" unless I explicitly ask for that.
- Configure my AI plan type before collecting, if I tell you what plan I use.
- Run one collection against all supported local agent harness logs.
- Show me the local dashboard URL and the /me personal dashboard URL.

Use this flow:
1. Verify Python is installed. Prefer Python 3.11+ for the mothership.
2. Clone the repo:
   git clone https://github.com/sanskarjaiswal2001/AIQ.git
   cd AIQ
3. Install the mothership:
   python scripts/aiq-mothership.py install --generate-admin-key
   On Windows, use: py scripts\\aiq-mothership.py install --generate-admin-key
4. Start the mothership on localhost:8000 in a background terminal/process:
   python scripts/aiq-mothership.py run --host 127.0.0.1 --port 8000
   On Windows, use: py scripts\\aiq-mothership.py run --host 127.0.0.1 --port 8000
5. Wait until health works:
   python scripts/aiq-mothership.py health --server-url http://127.0.0.1:8000
6. Identify my display name and team:
   - If my OS account full name is available, use it as the default display name.
   - Otherwise ask me for my preferred display name and team.
   - Do not invent an employee ID (no slugs like jane-doe or local-user) — the mothership assigns a numeric employee ID automatically on registration.
7. Register me using lobby mode (no invite code needed, simpler for solo setup):
   aiq register --server-url http://127.0.0.1:8000 --lobby --name "<My Real Name>" --team "<My Team>"
   This prints a 6-digit lobby ID. Then accept it from the admin TUI:
   python scripts/aiq-mothership.py lobby --server-url http://127.0.0.1:8000
   In the TUI, press SPACE to select my entry, then 'a' to accept. An invite code is generated.
   Then complete registration:
   aiq register --server-url http://127.0.0.1:8000 --lobby-id <LOBBY_ID>
   Alternatively, skip lobby and use an invite code directly:
   python scripts/aiq-mothership.py create-invite --server-url http://127.0.0.1:8000 --team "<My Team>"
   aiq register --server-url http://127.0.0.1:8000 --invite-code <INVITE_CODE> --name "<My Real Name>" --team "<My Team>"
   The server prints back the numeric employee ID it assigned — note it, but don't pass your own --employee-id.
8. Install the collector from the local repo:
   cd collector
   python -m pip install -e .
9. If I provide plan details, configure them before collection, for example:
   aiq config --plan-type claude_team_standard --plan-name "Claude Team Standard" --rolling-window-usd 25 --rolling-window-days 30 --seat-cost-usd 25
10. Run one collection:
   aiq collect --harnesses auto
   If logs are elsewhere, use the matching override such as --claude-dir, --codex-dir, --opencode-dir, --cursor-dir, or --copilot-dir.
11. Read the API key from `.aiq/config.toml` or `~/.aiq/config.toml` and open these URLs:
   - Management dashboard: http://127.0.0.1:8000
   - Personal dashboard: http://127.0.0.1:8000/me?api_key=<API_KEY>
   The browser stores the key locally and removes it from the address bar.

Important:
- Do not send my logs or metrics to any external service.
- AIQ should only run locally on 127.0.0.1 for this setup.
- If port 8000 is busy, use another port and update every command consistently.
- If Python refuses global installs, create/use a virtual environment or use the repo's native installer; do not use sudo pip.
- After registration, show me the API key location in ~/.aiq/config.toml and verify /me with that exact key.
- If Docker is not available, continue with native Python; Docker is optional.
- At the end, report exactly what commands ran, where the repo is cloned, where the AIQ config is stored, and what dashboard URLs I should open.
```

### "Update my installed AIQ" agent prompt

Paste this to a local coding agent to pull the latest AIQ changes and update the already-installed mothership and collector in place — without losing existing data, employees, or API keys:

```text
Update the already-installed AIQ on this machine to the latest version. Do not wipe data, employees, API keys, invites, or snapshots. Do not deploy to the cloud.

Repository: https://github.com/sanskarjaiswal2001/AIQ

Goal:
- Pull the latest code into the existing AIQ clone.
- Reinstall/refresh the mothership dependencies in place.
- Reinstall the collector in place.
- Restart the mothership so it serves the new code.
- Verify the dashboard and /me still work with existing data.

Use this flow:
1. Find the existing AIQ clone. If unknown, search common locations and report which path you used.
2. Pull the latest changes:
   git -C <AIQ_DIR> pull --ff-only
   If there are local modifications, stash them first and report it.
3. Reinstall the mothership (re-creates venv only if dependencies changed):
   python scripts/aiq-mothership.py install --venv <existing-venv> --data-dir <existing-data-dir>
   On Windows: py scripts\\aiq-mothership.py install --venv <existing-venv> --data-dir <existing-data-dir>
   Use the SAME venv and data-dir as before so data is preserved. Do not pass a new --admin-key unless the user asks.
4. Reinstall the collector:
   cd collector
   python -m pip install -e . --force-reinstall --no-deps
5. Stop the old mothership process and start the new one on the same host/port:
   python scripts/aiq-mothership.py run --host 127.0.0.1 --port 8000 --venv <existing-venv> --data-dir <existing-data-dir>
6. Wait for health:
   python scripts/aiq-mothership.py health --server-url http://127.0.0.1:8000
7. Verify data survived:
   curl http://127.0.0.1:8000/api/employees
   Report the employee count. It must match the pre-update count.
8. Verify /me still loads for an existing employee using the key in ~/.aiq/config.toml.

Important:
- Do not delete or move the SQLite database (aiq.db under the data-dir).
- Do not re-run `aiq register` for existing employees; their API key in ~/.aiq/config.toml must keep working.
- On first startup after this update, any employee still using an old name-slug ID (e.g. "local-user") is automatically renumbered to a numeric ID — one-time, logged at startup, existing API keys keep working unchanged. Employee IDs in `/api/employees` may differ from before; that's expected, not data loss.
- If a migration is needed in the future, run it and report what changed; for now data should persist as-is.
- If git pull fails due to local changes, stash, pull, and restore the stash; report any conflicts.
- At the end, report: the AIQ path, git commit before and after, employee count before and after, and the dashboard URLs.
```

### Optional Docker deploy

```bash
cp .env.example .env
docker compose up -d --build
```

### Install the collector (each employee)

```bash
pip install aiq-collector

# Register with your mothership (get invite code from admin)
aiq register --server-url http://localhost:8000 --invite-code YOUR_CODE --name "Jane Doe" --team "Engineering"

# Optional: tell AIQ how this employee is billed (rolling-window seat vs API spend)
aiq config --plan-type claude_team_standard --plan-name "Claude Team Standard" --rolling-window-usd 25 --rolling-window-days 30 --seat-cost-usd 25

# Collect and push (one-time)
aiq collect

# Or run on a native OS schedule
aiq install-autostart --interval-hours 6

# Or run foreground daemon mode
aiq collect --daemon
```

Employee can view their own dashboard at `http://localhost:8000/me`.

## Lobby Registration

Lobby mode is an alternative to invite codes. Instead of the admin pre-generating invite codes and sharing them individually, employees can self-register into a lobby where they wait for admin approval. This is useful when you don't know who needs access upfront — everyone just points at the mothership URL and joins.

### How it works

```
Employee                              Admin
────────                              ─────
aiq register --lobby ──►              (review in TUI)
  → gets 6-digit lobby ID             aiq-mothership.py lobby
  → status: pending                   space=select, a=accept, r=reject
                                      → generates 1-use invite code
                                      → lobby status: accepted
                                      
aiq register --lobby-id 123456 ──►
  → checks status: accepted
  → gets invite code automatically
  → completes registration
  → gets API key
  → lobby status: onboarded
```

### Employee: join the lobby

```bash
# No invite code needed — just the server URL
aiq register --server-url http://mothership:8000 --lobby --name "Jane Doe" --team Engineering

# Output:
#   Lobby ID: 575927
#   Status: pending
#   Wait for admin approval. Then complete registration with:
#   aiq register --server-url http://mothership:8000 --lobby-id 575927
```

The collector saves the lobby ID to `~/.aiq/state.json`. No API key is issued yet — the device is not recognized by the mothership until the admin accepts it.

### Admin: review and accept

Use the curses TUI to see pending devices, select multiple, and accept or reject:

```bash
python scripts/aiq-mothership.py lobby --server-url http://localhost:8000
```

Key bindings:

| Key | Action |
|-----|--------|
| ↑ / ↓ | Navigate entries |
| SPACE | Toggle selection |
| `a` | Accept selected (generates invite codes) |
| `r` | Reject selected |
| `R` | Refresh the list |
| `q` / ESC | Quit |

After accepting, the TUI displays the generated invite codes for each accepted device. Share these with the respective employees, or let them self-serve via `--lobby-id` (see below).

### Employee: complete registration after approval

```bash
# Checks status — if accepted, auto-extracts invite code and completes registration
aiq register --server-url http://mothership:8000 --lobby-id 575927
```

If still pending, the command exits cleanly. If rejected, it reports the rejection. Once accepted, it automatically pulls the invite code and finishes registration — no manual code sharing needed.

### API reference

| Endpoint | Auth | Purpose |
|----------|------|---------|
| `POST /api/register` with `{"lobby": true, ...}` | None | Join the lobby |
| `GET /api/lobby/{lobby_id}/status` | None | Check status (returns invite_code when accepted) |
| `GET /api/admin/lobby?status=pending` | X-Admin-Key | List lobby entries |
| `POST /api/admin/lobby/accept` | X-Admin-Key | Accept entries (generates invite codes) |
| `POST /api/admin/lobby/reject` | X-Admin-Key | Reject entries |

Lobby IDs are 6-digit codes (100000–999999). The lobby table tracks each device's name, email, team, hostname, and platform for admin review.

### Security considerations

- Lobby registration is open by design — anyone with the mothership URL can join the lobby. This is intended for internal tools where the network is trusted.
- Accepted lobby entries expose their invite code via the public status endpoint. The invite code is single-use, so a stolen code only denies the legitimate user's registration — it doesn't leak data.
- For external or untrusted networks, use invite-code mode exclusively. A future enhancement may require a lobby code (generated by the admin and distributed via MDM/Intune) to join the lobby, preventing open registration.

## Dashboard Views

| View | Who sees it | What it shows |
|------|-------------|---------------|
| **Team Overview** | Management | Org-wide stats, score distribution, team breakdown, top training needs, plan recommendations |
| **Executive Overview** | Management | Project-attributed spend, AI LOC per dollar, team rollups, and masked investor/client-safe exports |
| **Employees** | Management | Grid of all employees with score rings, practice bars, anti-pattern flags |
| **Employee Detail** | Management | Per-employee drill-down: scores, anti-patterns, model usage, training + plan recs |
| **Training Needs** | Management | Matrix of training tracks × employees needing them, with priorities |
| **Plan Recommendations** | Management | Per-employee: upgrade / train first / maintain / review |
| **Projects** | Management | Project cards and detail modals with spend, people, work types, model usage, branches, and metadata |
| **Staffing Intelligence** | Management | High-capacity, train-first, relocatable, overloaded, and project staffing pressure buckets |
| **Anti-Pattern Rules** | Management | Browser for all 20 detection rules with descriptions |
| **My Dashboard** | Employee | Personal view — own scores, projects, plan/billing context, anti-patterns, and training recommendations |

## Practice Scores

Five dimensions, each scored 0–100 with weekly trends:

| Score | What it measures |
|-------|-----------------|
| **Prompt Quality** | Are prompts well-structured with context, constraints, and specs? |
| **Session Hygiene** | Are sessions focused, canceled rarely, during reasonable hours? |
| **Code Review** | Is AI-generated code reviewed before accepting, or speed-accepted? |
| **Tool Mastery** | Are the right models used for the right tasks? Is cost optimized? |
| **Context Management** | Are AGENTS.md, skills, MCP tools, and file references set up? |

## Anti-Pattern Detection

20 log-derived rules across 5 practice groups, plus one optional plan-aware synthetic rule when plan context is configured. Each rule has severity (high/medium/low), description, and improvement suggestion.

<details>
<summary><strong>See all 20 rules</strong></summary>

| Rule | Group | Severity | What it detects |
|------|-------|----------|----------------|
| Lazy Prompting | prompt-quality | medium | Very short prompts lacking context |
| Repeated Prompts | prompt-quality | medium | Near-duplicate prompts sent multiple times |
| No Spec-Driven Dev | prompt-quality | medium | Sessions start without specs or plans |
| Verbose Prompt | prompt-quality | medium | Overly long prompts without compression |
| No Plan Mode | prompt-quality | low | Plan mode never used for complex tasks |
| No Skills | prompt-quality | low | No reusable skills created or used |
| Speed Accept | code-review | high | AI code accepted within seconds — no review |
| Copy-Paste Blindness | code-review | medium | Large AI code blocks pasted without review |
| Premium Waste | tool-mastery | medium | Expensive models used for trivial tasks |
| Premium for Lookups | tool-mastery | medium | Premium models for simple factual questions |
| Model Overreliance | tool-mastery | medium | 80%+ requests use a single model |
| Runaway Agent Loops | session-hygiene | high | 15+ tools per request — agent is spinning |
| Session Drift | session-hygiene | medium | Sessions with 30+ requests |
| Mega Sessions | session-hygiene | medium | Sessions with 50+ requests |
| High Cancellation | session-hygiene | medium | 20%+ of requests canceled |
| Frustration Signals | session-hygiene | medium | "!!!", "???", "wtf" in prompts |
| Late-Night Coding | session-hygiene | low | AI usage 22:00–05:00 |
| Weekend Overwork | session-hygiene | low | Heavy AI usage on weekends |
| Context Eng Gaps | context-management | medium | No AGENTS.md, skills, MCP, or file refs |
| Tunnel Vision | context-management | low | 90%+ work in a single workspace |

</details>

## Training Tracks

Triggered anti-patterns map to specific training modules:

| Track | Modules |
|-------|--------|
| ✍️ Prompt Engineering | Writing Effective Prompts, Iterative Prompting, Spec-Driven Dev, Prompt Compression, Plan Mode, Reusable Skills |
| 🔍 AI Code Review | Reviewing AI-Generated Code, Validating Generated Code |
| 🤖 Model & Tool Selection | Cost-Aware Model Routing, Choosing the Right Model, Multi-Model Workflows |
| 🔄 Agent Orchestration | Managing Agent Loops, Session Management, Breaking Down Complex Tasks |
| 🧩 Context Engineering | Setting Up AGENTS.md & Skills |
| ⚙️ Workflow Optimization | Reducing Cancellations, Managing AI Frustration, Diversifying Project Context |
| ⚖️ Work-Life Balance | Sustainable AI Usage |

## Plan Recommendations

| Recommendation | When | Why |
|----------------|------|-----|
| **Upgrade** | High volume + high efficiency + high cost | Would benefit from higher caps and premium access |
| **Train First** | Premium waste or model overreliance detected | Training yields more ROI — they'll waste the bigger budget too |
| **Maintain** | Good efficiency and model diversity | Current plan is working well |
| **Review** | Very low usage (<30 requests) | Consider seat sharing or downgrade |

## Supported AI Tools

| Tool | Status | Log location |
|------|--------|-------------|
| Claude Code | ✅ Live, dedicated parser | `~/.claude/projects/` |
| OpenAI Codex CLI | ✅ Live, generic JSON/JSONL parser | `~/.codex/` |
| OpenCode | ✅ Live, generic JSON/JSONL parser | `~/.opencode/` |
| Cursor Agent | ✅ Live, generic JSON/JSONL parser | `~/.cursor/` |
| GitHub Copilot (VS Code) | ✅ Best-effort generic parser | VS Code workspace storage |
| Xcode | 🚧 Coming soon | Xcode logs |

Collector defaults to `harnesses = "auto"`, so it scans every supported harness directory that exists on the employee machine. To restrict or override paths:

```bash
aiq collect --harnesses claude,codex --codex-dir ~/.codex
aiq config --harnesses claude,opencode --opencode-dir ~/.opencode
```

## Privacy

- The collector sends **derived metrics** — scores, token counts, anti-pattern flags, model usage, work-type classification, project/workspace grouping, and plan context
- **Never** sends raw prompts, AI responses, or code contents
- Project/workspace paths may be sent for project grouping and cost attribution. Management views use this internally; investor/client-safe exports mask project names, paths, clients, billing codes, and employee identities.
- All processing happens locally on the employee's machine
- The mothership is self-hosted — data never leaves your infrastructure

## Project Structure

```
AIQ/
├── Dockerfile              # Optional single image for server + dashboard
├── docker-compose.yml      # Optional Docker deploy
├── .env.example            # Configuration template
├── README.md
├── docs/
│   └── cross-platform.md   # Native install guide for Linux/WSL/macOS/Windows
├── scripts/
│   └── aiq-mothership.py   # Cross-platform native mothership launcher
├── server/                 # Mothership (FastAPI + SQLite)
│   ├── main.py             # API endpoints + static serving
│   ├── database.py         # SQLite schema + queries
│   ├── models.py           # Pydantic models
│   ├── recommendations.py  # Training + plan recommendation engine
│   ├── rules_meta.py       # Static rule metadata (20 base rules + plan-aware metadata)
│   ├── plan_catalog.py     # Claude/Codex/Copilot/OpenCode/custom plan catalog
│   ├── cost_engine.py      # API vs seat/rolling-window cost interpretation
│   └── requirements.txt
├── dashboard/              # Management dashboard (vanilla HTML/CSS/JS)
│   ├── index.html
│   ├── styles.css
│   └── app.js
└── collector/              # Edge collector (pip-installable)
    ├── pyproject.toml
    ├── aiq_collector/      # Python package
    │   ├── cli.py          # `aiq` CLI entry point
    │   ├── parser.py       # Dedicated Claude Code log parser
    │   ├── harnesses.py    # Pluggable Codex/OpenCode/Cursor/Copilot parsers
    │   ├── rules.py        # 20 anti-pattern detectors
    │   ├── scoring.py      # Practice scores + cost estimation
    │   └── analyzer.py     # Orchestrates → metrics JSON
    └── test_collector.py   # Collector/parser/analyzer regression tests
```

## Development

```bash
# Clone
git clone https://github.com/sanskarjaiswal2001/AIQ.git
cd AIQ

# Run server locally (no Docker)
cd server
pip install -r requirements.txt
DB_PATH=./aiq.db DASHBOARD_DIR=../dashboard python -m uvicorn main:app --port 8000

# Run collector locally
cd ../collector
pip install -e .
aiq status
aiq collect --output-file /tmp/metrics.json

# Push to local server
aiq collect --server-url http://localhost:8000 --employee-id test-dev
```

## Troubleshooting Project Detection

AIQ detects projects automatically from local assistant logs:

- Claude Code: prefers the real `cwd` stored in each session log, then falls back to decoding `~/.claude/projects/<encoded-project-path>`.
- Codex/OpenCode/Cursor/Copilot: uses `cwd`, `workspacePath`, `projectPath`, `repo`, or parent-session metadata when present; otherwise it falls back to the log file's containing folder.

On an employee machine, run:

```bash
aiq status
```

Check these lines:

```text
Sessions found    : N
Requests found    : N
Projects detected : N
  project        : project-name — /real/workspace/path
```

If `Projects detected` is `0` or paths look wrong:

1. Confirm the right harness log directory exists in `aiq status`.
2. If logs are elsewhere, set the directory explicitly, for example:
   ```bash
   aiq config --claude-dir "/path/to/.claude/projects"
   aiq config --harnesses claude,codex --codex-dir "/path/to/.codex"
   ```
3. Run `aiq collect --output-file /tmp/metrics.json` and inspect the top-level `projects` array.
4. Run `aiq collect` again to push the corrected snapshot to mothership.

## Tech Stack

- **Backend**: FastAPI + SQLite (stdlib, zero-config DB)
- **Frontend**: Vanilla HTML/CSS/JS (no build step, no framework)
- **Collector**: Python stdlib only (no external dependencies)
- **Deploy**: Native Python launcher for Linux/WSL/macOS/Windows; Docker Compose optional

## Roadmap

- [x] Claude Code support
- [x] Multi-harness collector support: Codex, OpenCode, Cursor, Copilot best-effort JSON/JSONL
- [x] 20 anti-pattern detectors + plan-aware synthetic rule
- [x] 5 practice scores with weekly trends
- [x] Training + plan recommendation engine
- [x] Management dashboard
- [x] Native mothership launcher for Linux, WSL, macOS, and Windows
- [x] Docker deployment (optional)
- [x] pip-installable collector
- [x] API key authentication
- [x] Employee self-registration with invite codes
- [x] Personal dashboard (`/me`) for employees
- [x] Collector auto-run (systemd/cron, launchd, Windows Task Scheduler, foreground daemon)
- [x] GitHub Copilot support (best-effort generic parser)
- [x] OpenAI Codex CLI support (generic JSON/JSONL parser)
- [ ] Dedicated vendor-specific parsers for non-Claude harnesses as schemas stabilize
- [ ] Data retention policies
- [ ] Team management UI

## Credits

Built on the data model and rule definitions from [Microsoft's AI-Engineering-Coach](https://github.com/microsoft/AI-Engineering-Coach) (MIT licensed).

## License

AIQ Commercial Source License

- **BETSOL PVT LTD and BETSOL Software India LTD** (and affiliates) may use AIQ commercially, free of charge — no paid license required.
- **Individuals and non-profits** may use AIQ free of charge for personal, evaluation, educational, and open-source contribution purposes.
- **Any other for-profit organization** must obtain a paid commercial license before commercial use. Contact the copyright holder for terms.

See [LICENSE](LICENSE) for the full text.
