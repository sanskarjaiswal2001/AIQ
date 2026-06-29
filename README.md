<div align="center">

# ⚡ AIQ

### AI Quotient — measure how efficiently your team uses AI coding tools

Track prompt quality, code review habits, model selection, and cost across your entire engineering org. Get actionable training recommendations and plan upgrade advice per employee.

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
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
- **Cost tracking** — token usage and estimated spend per employee, per model, per team

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
│  aiq collect     │     │  • Employee grid         │
│  → pushes metrics│     │  • Training needs matrix │
│    to mothership │     │  • Plan recommendations  │
│  → sees own data │     │  • Anti-pattern rules    │
│    at /me        │     │  • Drill-down per person │
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
- Register me as a local employee.
- Run one collection against my local Claude Code logs.
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
6. Create an invite:
   python scripts/aiq-mothership.py create-invite --server-url http://127.0.0.1:8000 --team Local
   Save the invite code from the JSON response.
7. Install the collector from the local repo:
   cd collector
   python -m pip install -e .
8. Register me with the invite code:
   aiq register --server-url http://127.0.0.1:8000 --invite-code <INVITE_CODE> --employee-id local-user --name "Local User" --team Local
9. Run one collection:
   aiq collect
   If Claude Code logs are elsewhere, use: aiq collect --claude-dir <path-to-claude-projects>
10. Open these URLs:
   - Management dashboard: http://127.0.0.1:8000
   - Personal dashboard: http://127.0.0.1:8000/me

Important:
- Do not send my logs or metrics to any external service.
- AIQ should only run locally on 127.0.0.1 for this setup.
- If port 8000 is busy, use another port and update every command consistently.
- If Python refuses global installs, create/use a virtual environment or use the repo's native installer; do not use sudo pip.
- If Docker is not available, continue with native Python; Docker is optional.
- At the end, report exactly what commands ran, where the repo is cloned, where the AIQ config is stored, and what dashboard URLs I should open.
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

# Collect and push (one-time)
aiq collect

# Or run on a native OS schedule
aiq install-autostart --interval-hours 6

# Or run foreground daemon mode
aiq collect --daemon
```

Employee can view their own dashboard at `http://localhost:8000/me`.

## Dashboard Views

| View | Who sees it | What it shows |
|------|-------------|---------------|
| **Team Overview** | Management | Org-wide stats, score distribution, team breakdown, top training needs, plan recommendations |
| **Employees** | Management | Grid of all employees with score rings, practice bars, anti-pattern flags |
| **Employee Detail** | Management | Per-employee drill-down: scores, anti-patterns, model usage, training + plan recs |
| **Training Needs** | Management | Matrix of training tracks × employees needing them, with priorities |
| **Plan Recommendations** | Management | Per-employee: upgrade / train first / maintain / review |
| **Anti-Pattern Rules** | Management | Browser for all 20 detection rules with descriptions |
| **My Dashboard** | Employee | Personal view — own scores, anti-patterns, training recommendations |

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

20 rules across 5 practice groups. Each rule has severity (high/medium/low), description, and improvement suggestion.

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
| Claude Code | ✅ Live | `~/.claude/projects/` |
| GitHub Copilot (VS Code) | 🚧 Coming soon | VS Code workspace storage |
| OpenAI Codex CLI | 🚧 Coming soon | `~/.codex/` |
| OpenCode | 🚧 Coming soon | `~/.opencode/` |
| Xcode | 🚧 Coming soon | Xcode logs |

## Privacy

- The collector only sends **metrics** — scores, token counts, anti-pattern flags, model usage, work-type classification
- **Never** sends raw prompts, AI responses, code contents, or file paths
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
│   ├── rules_meta.py       # Static rule metadata (20 rules)
│   └── requirements.txt
├── dashboard/              # Management dashboard (vanilla HTML/CSS/JS)
│   ├── index.html
│   ├── styles.css
│   └── app.js
└── collector/              # Edge collector (pip-installable)
    ├── pyproject.toml
    ├── aiq_collector/      # Python package
    │   ├── cli.py          # `aiq` CLI entry point
    │   ├── parser.py       # Claude Code log parser
    │   ├── rules.py        # 20 anti-pattern detectors
    │   ├── scoring.py      # Practice scores + cost estimation
    │   └── analyzer.py     # Orchestrates → metrics JSON
    └── README.md
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
aiq collect --output-file /tmp/metrics.json

# Push to local server
aiq collect --server-url http://localhost:8000 --employee-id test-dev
```

## Tech Stack

- **Backend**: FastAPI + SQLite (stdlib, zero-config DB)
- **Frontend**: Vanilla HTML/CSS/JS (no build step, no framework)
- **Collector**: Python stdlib only (no external dependencies)
- **Deploy**: Native Python launcher for Linux/WSL/macOS/Windows; Docker Compose optional

## Roadmap

- [x] Claude Code support
- [x] 20 anti-pattern detectors
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
- [ ] GitHub Copilot support
- [ ] OpenAI Codex CLI support
- [ ] Data retention policies
- [ ] Team management UI

## Credits

Built on the data model and rule definitions from [Microsoft's AI-Engineering-Coach](https://github.com/microsoft/AI-Engineering-Coach) (MIT licensed).

## License

MIT
