# AIQ v2 — Research, Standards & Phases

> Post-Koni discussion expansion. Transforms AIQ from employee-level scoring into a
> **project-level financial intelligence platform** for AI spending.

## Research Items

### R1: AI Provider Plan Types (verified 2026-06-29)

#### Claude (Anthropic)
| Plan | Price | Billing | Usage Model |
|------|-------|---------|-------------|
| Free | $0 | — | Limited |
| Pro | $17/mo annual, $20/mo monthly | Seat | Rolling window (~5x Free) |
| Max 5x | $100/mo | Seat | Rolling window (5x Pro) |
| Max 20x | $200/mo | Seat | Rolling window (20x Pro) |
| Team Standard | $20/seat/mo annual, $25/mo monthly | Seat | Rolling window (more than Pro) |
| Team Premium | $100/seat/mo annual, $125/mo monthly | Seat | Rolling window (5x standard seat) |
| Enterprise | $20/seat + API usage | Seat + usage | Seat + API rate usage |
| API | Per-token | Usage | Direct token billing |

Claude API rates (per million tokens):
| Model | Input | Output | Cache Write | Cache Read |
|-------|-------|--------|-------------|------------|
| Fable 5 | $10 | $50 | $12.50 | $1 |
| Opus 4.8 | $5 | $25 | $6.25 | $0.50 |
| Sonnet 4.6 | $3 | $15 | $3.75 | $0.30 |
| Haiku 4.5 | $1 | $5 | $1.25 | $0.10 |

**Key insight**: Claude Team/Enterprise seats use **rolling windows** — not monthly quotas.
A $25/mo Team Standard seat gives you a rolling window of usage that resets as old usage
ages out. This is NOT "I get $25/month." It's "I get X amount of usage at any given time,
and as my oldest usage falls out of the window, new usage comes in."

#### OpenAI Codex (ChatGPT plans)
| Plan | Price | Billing | Usage Model |
|------|-------|---------|-------------|
| Free | $0 | — | Limited |
| Go | $8/mo | Seat | Rolling 5h window |
| Plus | $20/mo | Seat | Rolling 5h window (15-80 msgs/5h for GPT-5.5) |
| Pro 5x | $100/mo | Seat | 5x Plus limits |
| Pro 20x | $200/mo | Seat | 20x Plus limits |
| Business | Contact sales | Seat | Pooled credits |
| Enterprise/Edu | Contact sales | Seat | Flexible credits or per-seat limits |
| API Key | Per-token | Usage | Direct token billing |

Codex credit rates (credits per 1M tokens):
| Model | Input | Cached Input | Output |
|-------|-------|-------------|--------|
| GPT-5.5 | 125 | 12.50 | 750 |
| GPT-5.4 | 62.50 | 6.25 | 375 |
| GPT-5.4 mini | 18.75 | 1.875 | 113 |

**Key insight**: Codex uses a **5-hour rolling window** with message counts per model.
Limits are shared between local messages and cloud tasks. Credits extend usage beyond limits.

#### GitHub Copilot
| Plan | Price | Billing | Usage Model |
|------|-------|---------|-------------|
| Free | $0 | — | 2,000 completions/mo |
| Pro | $10/mo | Seat | $15 monthly credits, unlimited completion |
| Pro+ | $39/mo | Seat | $70 monthly credits, 4x+ Pro usage |
| Max | $100/mo | Seat | $200 monthly credits, 2.9x+ Pro+ usage |
| Business | $19/seat/mo | Seat | Pooled credits, governance |
| Enterprise | $39/seat/mo | Seat | 2x Business usage, audit logs |

**Key insight**: Copilot uses a **credit-based** model with monthly credits per seat.
Business/Enterprise pools credits across the org.

#### Plan Type Taxonomy
```
billing_mode:
  ├── api          — pay per token (direct cost = estimated_cost_usd)
  ├── seat_fixed   — flat monthly seat, unlimited or capped (Copilot Free/Pro)
  ├── seat_credits — monthly credits that deplete per use (Copilot Pro+/Max)
  ├── seat_rolling — rolling window, usage ages out (Claude Pro/Max/Team)
  └── seat_hybrid  — seat + API usage (Claude Enterprise)
```

### R2: Project Extraction from Claude Logs

Current parser extracts:
- `workspace_path` (decoded from encoded directory name)
- `workspace_name` (last path component)
- `git_branch`
- `version`
- Per-request: edited_files, referenced_files, tools_used, skills_used

**Missing for project-level views:**
- Project grouping (multiple employees working on same project path)
- Project-level cost aggregation
- Project-level time tracking (sessions per project per day)
- Cross-employee project rollup
- Project classification (internal/external, client name, billing code)

Koni's fork (github.com/konidev20/ai-engineering-coach) reportedly extracts
project-specific info. Need to integrate and enhance.

### R3: Management Decision Support

Upper management needs:
1. **Where is money going?** — per-project, per-team, per-employee AI spend
2. **Is it worth it?** — ROI indicators (AI LOC produced, tasks completed, cost per task)
3. **Investor/client visibility** — masked overview suitable for external sharing
4. **Staffing decisions** — who can handle more, who needs training, who can relocate
5. **Project staffing** — how many people per project, who's overloaded, who has capacity

### R4: Privacy & Masking

- Employee work details must be masked for investor/client views
- Show aggregate scores, project-level spending, team distributions
- Never show actual prompts, code, or file contents (already enforced)
- Mask employee names in external views (Employee A, B, C or anonymized IDs)

## Standards

### S1: Plan Configuration Schema
```toml
[plan]
provider = "claude"           # claude | codex | copilot | opencode | custom
plan_type = "team_standard"   # provider-specific plan ID
billing_mode = "seat_rolling" # api | seat_fixed | seat_credits | seat_rolling | seat_hybrid
seat_cost_usd = 25            # monthly seat cost
rolling_window_hours = 5      # for codex-style 5h windows
rolling_window_days = 30      # for claude-style 30-day windows
rolling_window_usd = 0        # estimated USD equivalent (optional, for pressure calc)
included_credits = 0          # for credit-based plans (copilot)
api_cost_buffer = 0           # for hybrid plans, fixed seat + API
```

### S2: Project Data Model
```
Project:
  project_id: str              # hash of decoded workspace path
  project_name: str            # last path component or admin-assigned name
  project_path: str            # decoded workspace path
  team: str                    # assigned team
  client: str | None           # admin-assigned client name (for external projects)
  billing_code: str | None     # admin-assigned billing code
  employees: list[str]         # employees who worked on this project
  total_sessions: int
  total_requests: int
  total_ai_loc: int
  total_cost_usd: float        # estimated
  total_tokens: int
  first_activity: datetime
  last_activity: datetime
  active_days: int
  model_usage: dict            # per-model breakdown
  work_type_distribution: dict # bug fix / feature / refactor / etc.
  complexity_score: float      # derived from work types, LOC, model tiers
```

### S3: Token Usage Standards
- Always track: input_tokens, output_tokens, cache_read_tokens, cache_write_tokens
- Estimate cost using provider-specific rates (not generic)
- For seat plans: show "quota pressure" not "invoice cost"
- For API plans: show actual estimated spend
- For hybrid plans: show seat cost + API overage separately
- Always show per-project breakdown, not just per-employee

### S4: Dashboard View Standards
- **Org Overview** — total spend, active projects, team distribution (investor-safe)
- **Project Overview** — drill-down per project: cost, people, efficiency, timeline
- **Team Overview** — per-team spend, efficiency, staffing recommendations
- **Employee Detail** — existing + project list + capacity analysis
- **Employee Self-View (/me)** — personal stats + project contributions
- **Plan Optimization** — who needs upgrade, who needs downgrade, projected savings

## Phases

### Phase 5: Project-Level Data Extraction
- [ ] Enhance parser to extract full project metadata from Claude logs
- [ ] Add project_id (deterministic hash of decoded workspace path)
- [ ] Add per-request project tagging (which project each request belongs to)
- [ ] Build project aggregation in analyzer (group sessions by project_id)
- [ ] Add project breakdown to collector payload
- [ ] Integrate Koni's project extraction approach (pending subagent research)

### Phase 6: Server-Side Project Aggregation
- [ ] Add `projects` table to SQLite schema
- [ ] Add `project_members` table (many-to-many employee ↔ project)
- [ ] Store project metadata (admin-assignable: client, billing_code, team)
- [ ] Build `/api/projects` endpoint — list all projects with aggregated stats
- [ ] Build `/api/projects/{project_id}` — project detail with per-employee breakdown
- [ ] Build `/api/projects/{project_id}/cost` — project cost over time
- [ ] Cross-employee project rollup (club sessions from various employees)

### Phase 7: Plan Catalog & Dropdown Configuration
- [ ] Create `server/plan_catalog.py` — structured catalog of all provider plans
- [ ] Claude: Free, Pro, Max 5x, Max 20x, Team Standard, Team Premium, Enterprise, API
- [ ] Codex: Free, Go, Plus, Pro 5x, Pro 20x, Business, Enterprise, API
- [ ] Copilot: Free, Pro, Pro+, Max, Business, Enterprise
- [ ] Add `/api/plans` endpoint — returns catalog for frontend dropdowns
- [ ] Update collector config to use plan_id from catalog (not free-text plan_type)
- [ ] Add plan comparison data (relative usage multipliers, seat costs, billing mode)

### Phase 8: Plan-Aware Cost Engine
- [ ] Replace generic estimated_cost_usd with plan-specific cost calculation
- [ ] API mode: actual token cost (existing logic)
- [ ] Seat rolling mode: quota pressure % (utilization of rolling window)
- [ ] Seat credits mode: credits consumed + remaining
- [ ] Seat hybrid mode: seat cost + API overage
- [ ] Add "plan fit" analysis: is the employee on the right plan for their usage pattern?
- [ ] Upgrade recommendations: "Claude Pro → Max 5x" with projected benefit
- [ ] Downgrade recommendations: "Max 20x → Max 5x" with projected savings

### Phase 9: Management Dashboard — Project Views
- [ ] Add "Projects" nav item to dashboard
- [ ] Project list view: cards with cost, people, efficiency, trend
- [ ] Project detail view: timeline, per-employee breakdown, cost chart, work types
- [ ] Add project filtering by team, client, billing code
- [ ] Add project cost over time chart
- [ ] Add "Project Staffing" view: who's on each project, capacity analysis

### Phase 10: Management Dashboard — Org & Investor Views
- [ ] Org Overview: total AI spend, active projects, team distribution
- [ ] Add "masked mode" toggle for investor/client views
- [ ] Mask employee names → Employee A/B/C or anonymized
- [ ] Show aggregate metrics only (no drill-down to individual prompts)
- [ ] Add export-to-PDF/CSV for investor decks
- [ ] Add cost-per-project, cost-per-team, cost-per-employee breakdowns

### Phase 11: Staffing & Capacity Intelligence
- [ ] Employee capacity score (based on project count, complexity, efficiency)
- [ ] "Can handle more" flag (high efficiency, low project load, not hitting limits)
- [ ] "Needs training" flag (low scores, anti-patterns, hitting limits with low efficiency)
- [ ] "Can relocate" flag (working on low-complexity projects, high efficiency)
- [ ] Project staffing recommendation: "Project X needs N more people"
- [ ] Team rebalancing suggestions: "Move Employee A from Project X to Project Y"
- [ ] Plan optimization: "Upgrade Employee B to Claude Max to avoid rolling window caps"

### Phase 12: Enhanced Employee Self-View
- [ ] Show project contributions in /me
- [ ] Show personal plan utilization and quota pressure
- [ ] Show "what if I upgraded" projections
- [ ] Show training recommendations with specific modules
- [ ] Show comparison with team averages (anonymized)
