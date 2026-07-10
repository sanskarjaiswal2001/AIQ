/* ── AI Engineering Efficiency Dashboard ──────────────── */
/* Frontend logic: data fetching, rendering, interactions */

const API_BASE = window.location.origin.replace(/\/$/, '');
const IS_EMPLOYEE_DASHBOARD = window.location.pathname === '/me';
const PERSONAL_VIEWS = ['me', 'me-activity', 'me-skills', 'me-projects', 'me-prompts', 'me-plan'];
let currentView = 'overview';
let allEmployees = [];
let allRules = [];
let meData = null;
let meDataPromise = null;

// ── API helpers ────────────────────────────────────────
async function api(path, opts = {}) {
  const headers = {};
  const apiKey = localStorage.getItem('aiq_api_key');
  if (apiKey) headers['X-API-Key'] = apiKey;
  const timeoutMs = opts.timeoutMs || 15000;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${API_BASE}${path}`, { headers, signal: controller.signal });
    let detail = '';
    if (!res.ok) {
      try {
        const body = await res.json();
        detail = body.detail ? ` — ${body.detail}` : '';
      } catch (_) {}
      throw new Error(`API ${path} failed: ${res.status}${detail}`);
    }
    return res.json();
  } catch (e) {
    if (e.name === 'AbortError') {
      throw new Error(`API ${path} timed out after ${Math.round(timeoutMs / 1000)}s. Check that the AIQ server is still running and reachable.`);
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

async function apiPost(path, body) {
  return apiWrite('POST', path, body);
}

async function apiPut(path, body) {
  return apiWrite('PUT', path, body);
}

async function apiPatch(path, body) {
  return apiWrite('PATCH', path, body);
}

async function apiDelete(path) {
  return apiWrite('DELETE', path, {});
}

async function apiWrite(method, path, body) {
  const send = async () => {
    const headers = { 'Content-Type': 'application/json' };
    const adminKey = localStorage.getItem('aiq_admin_key');
    const apiKey = localStorage.getItem('aiq_api_key');
    if (adminKey) headers['X-Admin-Key'] = adminKey;
    if (apiKey) headers['X-API-Key'] = apiKey;
    return fetch(`${API_BASE}${path}`, { method, headers, body: JSON.stringify(body) });
  };
  let res = await send();
  if (res.status === 401) {
    const key = window.prompt('Admin key required. Paste AIQ_ADMIN_KEY:');
    if (key) localStorage.setItem('aiq_admin_key', key.trim());
    res = await send();
  }
  if (!res.ok) {
    let detail = '';
    try { const j = await res.json(); detail = j.detail ? ` — ${j.detail}` : ''; } catch (_) {}
    throw new Error(`API ${method} ${path} failed: ${res.status}${detail}`);
  }
  return res.json();
}

function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem('aiq_theme', theme);
  const btn = document.getElementById('themeToggle');
  if (btn) btn.textContent = theme === 'light' ? 'Dark mode' : 'Light mode';
}

function initTheme() {
  // ponytail: dark is the product default; only one persisted override.
  setTheme(localStorage.getItem('aiq_theme') === 'light' ? 'light' : 'dark');
}

// ── Score helpers ──────────────────────────────────────
// practice_scores can carry a flat number under the underscore key, or a
// richer { score, weekly } object under the hyphenated key (real collector
// payloads send both — the hyphenated one is authoritative when present).
function extractScore(scores, hyphenKey, underscoreKey) {
  const h = scores?.[hyphenKey];
  if (h != null) return typeof h === 'object' ? (h.score ?? 0) : h;
  const u = scores?.[underscoreKey];
  if (u != null) return typeof u === 'object' ? (u.score ?? 0) : u;
  return 0;
}

function scoreClass(score) {
  if (score >= 80) return 'excellent';
  if (score >= 60) return 'good';
  if (score >= 40) return 'needs';
  return 'risk';
}

function scoreColor(score) {
  if (score >= 80) return 'var(--green)';
  if (score >= 60) return 'var(--accent)';
  if (score >= 40) return 'var(--yellow)';
  return 'var(--red)';
}

function severityClass(sev) {
  return sev === 'high' ? 'high' : sev === 'medium' ? 'medium' : 'low';
}

function fmtCost(n) {
  if (n == null) return '$0';
  if (n < 1) return `$${n.toFixed(2)}`;
  return `$${n.toFixed(0)}`;
}

function fmtNum(n) {
  if (n == null) return '0';
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

function fmtDate(s) {
  if (!s) return '—';
  const d = new Date(s);
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

// ── View switching ─────────────────────────────────────
function switchView(view) {
  if (IS_EMPLOYEE_DASHBOARD && !PERSONAL_VIEWS.includes(view)) view = 'me';
  if (!IS_EMPLOYEE_DASHBOARD && PERSONAL_VIEWS.includes(view)) view = 'overview';
  currentView = view;
  document.querySelectorAll('.nav-item').forEach(el => {
    el.classList.toggle('active', el.dataset.view === view);
  });
  document.querySelectorAll('.view').forEach(el => {
    el.classList.toggle('active', el.id === `view-${view}`);
  });
  const titles = {
    overview: 'Team Overview',
    executive: 'Executive Overview',
    employees: 'Employees',
    training: 'Training Needs',
    plans: 'Plan Recommendations',
    projects: 'Projects',
    staffing: 'Staffing Intelligence',
    rules: 'Anti-Pattern Rules',
    me: 'My Overview',
    'me-activity': 'Activity',
    'me-skills': 'Skills & Coaching',
    'me-projects': 'My Projects',
    'me-prompts': 'Prompt History',
    'me-plan': 'Plan & Usage',
  };
  const kickers = {
    overview: 'Team usage and ROI',
    executive: 'Board-safe financial view',
    employees: 'Individual usage and coaching signals',
    training: 'Training modules by detected behavior',
    plans: 'Billing fit and plan pressure',
    projects: 'Project-level AI cost attribution',
    staffing: 'Capacity and staffing intelligence',
    rules: 'Detection logic and coaching rules',
    me: 'Your scores and plan fit',
    'me-activity': 'Your sessions and usage trend',
    'me-skills': 'Practice detail and coaching tips',
    'me-projects': 'Where your AI work goes',
    'me-prompts': 'Your recent prompts — private',
    'me-plan': 'Your plan fit and limits',
  };
  document.getElementById('pageTitle').textContent = titles[view] || view;
  const kicker = document.getElementById('pageKicker');
  if (kicker) kicker.textContent = kickers[view] || 'AIQ';
  renderView(view);
}

function renderView(view) {
  switch (view) {
    case 'overview': renderOverview(); break;
    case 'executive': renderExecutive(); break;
    case 'employees': renderEmployees(); break;
    case 'training': renderTraining(); break;
    case 'plans': renderPlans(); break;
    case 'projects': renderProjects(); break;
    case 'staffing': renderStaffing(); break;
    case 'rules': renderRules(); break;
    case 'me': renderMeOverview(); break;
    case 'me-activity': renderMeActivity(); break;
    case 'me-skills': renderMeSkills(); break;
    case 'me-projects': renderMeProjects(); break;
    case 'me-prompts': renderMePrompts(); break;
    case 'me-plan': renderMePlan(); break;
  }
}

// ── Overview View ──────────────────────────────────────
async function renderOverview() {
  showLoading(true);
  try {
    const data = await api('/api/team/overview');
    const stats = document.getElementById('overviewStats');
    stats.innerHTML = `
      ${statCard('Total Employees', data.total_employees, 'active in period')}
      ${statCard('Total Requests', fmtNum(data.total_requests), 'AI interactions')}
      ${statCard('Avg Efficiency', `${data.avg_overall_score?.toFixed(1) || 0}`, '/ 100')}
      ${statCard('AI Spend', fmtCost(data.total_cost_usd), data.cost_label || 'billed plan spend')}
    `;

    // Score distribution
    const dist = data.score_distribution || {};
    const distEl = document.getElementById('scoreDistribution');
    distEl.innerHTML = `
      ${distItem('Excellent (80+)', dist.excellent || 0, 'excellent')}
      ${distItem('Good (60-79)', dist.good || 0, 'good')}
      ${distItem('Needs Work (40-59)', dist.needs_improvement || 0, 'needs')}
      ${distItem('At Risk (<40)', dist.at_risk || 0, 'risk')}
    `;

    // Team breakdown
    const teams = data.team_breakdown || {};
    const tbEl = document.getElementById('teamBreakdown');
    const teamRows = Object.entries(teams).map(([team, info]) => `
      <div class="team-row">
        <span class="team-name">${esc(team)}</span>
        <span>${info.employees}</span>
        <span class="team-score" style="color:${scoreColor(info.avg_score)}">${(info.avg_score || 0).toFixed(0)}</span>
        <span class="team-cost">${fmtCost(info.total_cost)}</span>
        <span>${fmtNum(info.total_requests || 0)}</span>
      </div>
    `).join('');
    tbEl.innerHTML = `
      <div class="team-row header">
        <span>Team</span><span>People</span><span>Score</span><span>Spend</span><span>Requests</span>
      </div>
      ${teamRows || emptyRow('No team data yet')}
    `;

    // Top training needs
    const tn = data.top_training_needs || [];
    const tnEl = document.getElementById('topTrainingNeeds');
    tnEl.innerHTML = tn.length ? tn.map(t => `
      <div class="training-need-item">
        <div>
          <div class="tn-track">${esc(t.track)}</div>
          <div class="tn-count">${t.employees_needing} employee${t.employees_needing !== 1 ? 's' : ''} need this</div>
        </div>
        <span class="tn-badge">${t.avg_severity}</span>
      </div>
    `).join('') : emptyState('No training needs detected');

    // Plan recommendations
    const pr = data.plan_recommendations || [];
    const prEl = document.getElementById('planRecommendations');
    prEl.innerHTML = pr.length ? pr.map(p => `
      <div class="plan-rec-item">
        <div>
          <div class="pr-employee">${esc(p.name || p.employee_id)}</div>
          <div class="pr-reason">${esc(p.reason)}</div>
        </div>
        <span class="plan-badge ${planClass(p.recommendation)}">${esc(p.recommendation)}</span>
      </div>
    `).join('') : emptyState('No plan recommendations yet');
  } catch (e) {
    console.error('Overview error:', e);
    showToast('Failed to load overview: ' + e.message);
  } finally {
    showLoading(false);
  }
}

function statCard(label, value, sub) {
  return `<div class="stat-card"><div class="stat-value">${value}</div><div class="stat-label">${label}</div><div class="stat-sub">${sub || ''}</div></div>`;
}

function distItem(label, count, cls) {
  return `<div class="score-dist-item ${cls}"><div class="dist-label">${label}</div><div class="dist-count">${count}</div></div>`;
}

function emptyRow(msg) { return `<div style="padding:20px;text-align:center;color:var(--text-dim)">${msg}</div>`; }
function emptyState(msg) { return `<div class="empty-state"><div class="es-icon">--</div><p>${msg}</p></div>`; }

function planClass(rec) {
  if (rec === 'upgrade') return 'upgrade';
  if (rec === 'maintain' || rec === 'current') return 'maintain';
  if (rec === 'train_first') return 'train';
  return 'review';
}

function billingModeLabel(mode) {
  const labels = {
    api: 'API usage billing',
    seat_fixed: 'Fixed seat plan',
    seat_credits: 'Seat credits plan',
    seat_rolling: 'Rolling window seat',
    seat_hybrid: 'Seat + API overage',
    enterprise_rolling_window: 'Enterprise rolling window',
    rolling_window: 'Rolling window seat',
  };
  return labels[mode] || mode || 'Plan not configured';
}

function planIdentityHTML(planContext = {}, costInfo = {}) {
  const planId = planContext.plan_id || planContext.plan_type || 'not configured';
  const planName = planContext.plan_name || planId;
  const billingMode = costInfo.billing_mode || planContext.billing_mode || planContext.plan_type || '';
  const rolling = planContext.rolling_window_usd ? `${fmtCost(Number(planContext.rolling_window_usd))} / ${planContext.rolling_window_days || '?'}d window` : '—';
  return `
    <div class="project-meta-grid plan-meta-grid">
      <div class="project-meta-item"><div class="pmi-label">Plan</div><div class="pmi-value">${esc(planName)}</div></div>
      <div class="project-meta-item"><div class="pmi-label">Plan ID</div><div class="pmi-value">${esc(planId)}</div></div>
      <div class="project-meta-item"><div class="pmi-label">Billing Mode</div><div class="pmi-value">${esc(billingModeLabel(billingMode))}</div></div>
      <div class="project-meta-item"><div class="pmi-label">Seat Cost</div><div class="pmi-value">${planContext.seat_cost_usd ? fmtCost(Number(planContext.seat_cost_usd)) : '—'}</div></div>
      <div class="project-meta-item"><div class="pmi-label">Rolling Window</div><div class="pmi-value">${esc(rolling)}</div></div>
      <div class="project-meta-item"><div class="pmi-label">Context Window</div><div class="pmi-value">${planContext.context_window_tokens || planContext.max_context_tokens ? fmtNum(Number(planContext.context_window_tokens || planContext.max_context_tokens)) + ' tokens' : '—'}</div></div>
      <div class="project-meta-item"><div class="pmi-label">Usage Meaning</div><div class="pmi-value">${esc(costInfo.cost_label || 'Estimated token cost')}</div></div>
    </div>`;
}

// ── Executive View ─────────────────────────────────────
async function renderExecutive() {
  showLoading(true);
  try {
    const [org, investor] = await Promise.all([
      api('/api/org/overview'),
      api('/api/org/investor-view?reveal_financials=true'),
    ]);
    const t = org.totals || {};
    const el = document.getElementById('executiveDashboard');
    const spendRows = (org.top_projects_by_spend || []).slice(0, 8).map((p, i) => `
      <div class="exec-row">
        <span class="rank">${i + 1}</span>
        <span>${esc(p.project_name)}</span>
        <span>${esc(p.team || (p.employees?.[0]?.team) || 'Unassigned')}</span>
        <span class="money">${fmtCost(p.total_cost_usd)}</span>
        <span>${fmtNum(p.total_requests || 0)}</span>
        <span>${p.employees?.length || 0}</span>
      </div>
    `).join('');
    const valueRows = (org.high_value_projects || []).slice(0, 6).map((p, i) => `
      <div class="exec-row compact">
        <span class="rank">${i + 1}</span>
        <span>${esc(p.project_name)}</span>
        <span class="money">${fmtCost(p.cost_usd)}</span>
        <span>${fmtNum(p.ai_loc)}</span>
        <span>${p.ai_loc_per_dollar}/$</span>
      </div>
    `).join('');
    const teamRows = (org.team_rollup || []).map(r => `
      <div class="team-row">
        <span class="team-name">${esc(r.team)}</span>
        <span>${r.projects}</span>
        <span>${r.employees}</span>
        <span class="team-cost">${fmtCost(r.cost_usd)}</span>
        <span>${fmtNum(r.requests)}</span>
      </div>
    `).join('');
    const maskedRows = (investor.projects || []).slice(0, 8).map(p => `
      <div class="exec-row compact">
        <span>${esc(p.project_label)}</span>
        <span>${esc(p.team_label)}</span>
        <span>${p.people}</span>
        <span class="money">${fmtCost(p.cost_usd)}</span>
        <span>${esc(p.cost_band)}</span>
      </div>
    `).join('');
    el.innerHTML = `
      <div class="stat-cards">
        ${statCard('AI Spend', fmtCost(t.cost_usd), 'plan-billed / project-attributed')}
        ${statCard('Projects', fmtNum(t.projects || 0), 'active')}
        ${statCard('People', fmtNum(t.employees || 0), 'contributors')}
        ${statCard('AI LOC / $', t.ai_loc_per_dollar || 0, 'efficiency proxy')}
        ${statCard('Cost / Request', `$${(t.cost_per_request || 0).toFixed(2)}`, 'blended')}
      </div>
      <div class="exec-actions">
        <a class="btn" href="/api/org/export/projects.csv" target="_blank">Export Projects CSV</a>
        <a class="btn" href="/api/org/export/projects.csv?masked=true" target="_blank">Export Masked CSV</a>
        <a class="btn" href="/api/org/investor-view?reveal_financials=false" target="_blank">Masked Investor JSON</a>
      </div>
      <div class="card-grid two-col">
        <div class="card card-wide">
          <h3>Where the Money Is Going</h3>
          <div class="exec-table">
            <div class="exec-row header"><span>#</span><span>Project</span><span>Team</span><span>Spend</span><span>Requests</span><span>People</span></div>
            ${spendRows || emptyRow('No project spend yet')}
          </div>
        </div>
        <div class="card card-wide">
          <h3>Highest Output per Dollar</h3>
          <div class="exec-table">
            <div class="exec-row header compact"><span>#</span><span>Project</span><span>Spend</span><span>AI LOC</span><span>AI LOC/$</span></div>
            ${valueRows || emptyRow('No value metrics yet')}
          </div>
        </div>
        <div class="card card-wide">
          <h3>Team Spend Rollup</h3>
          <div class="team-breakdown">
            <div class="team-row header"><span>Team</span><span>Projects</span><span>People</span><span>Spend</span><span>Requests</span></div>
            ${teamRows || emptyRow('No team rollup yet')}
          </div>
        </div>
        <div class="card card-wide">
          <h3>Investor / Client Safe View</h3>
          <p class="muted-copy">Project names, paths, clients, billing codes, and employee names are hidden. Financials can be shown exactly or as bands.</p>
          <div class="exec-table">
            <div class="exec-row header compact"><span>Project</span><span>Team</span><span>People</span><span>Spend</span><span>Band</span></div>
            ${maskedRows || emptyRow('No masked data yet')}
          </div>
        </div>
      </div>
    `;
  } catch (e) {
    console.error('Executive error:', e);
    showToast('Failed to load executive view: ' + e.message);
    document.getElementById('executiveDashboard').innerHTML = emptyState('Failed to load executive overview.');
  } finally {
    showLoading(false);
  }
}

// ── Employees View ─────────────────────────────────────
async function renderEmployees() {
  showLoading(true);
  try {
    const team = document.getElementById('teamFilter').value;
    const sort = document.getElementById('sortBy').value;
    const order = document.getElementById('sortOrder').value;
    let path = `/api/employees?sort=${sort}&order=${order}`;
    if (team) path += `&team=${encodeURIComponent(team)}`;
    allEmployees = await api(path);

    // Populate team filter
    const teams = [...new Set(allEmployees.map(e => e.team).filter(Boolean))];
    const teamFilter = document.getElementById('teamFilter');
    const currentTeam = teamFilter.value;
    teamFilter.innerHTML = '<option value="">All Teams</option>' +
      teams.map(t => `<option value="${esc(t)}" ${t === currentTeam ? 'selected' : ''}>${esc(t)}</option>`).join('');

    const grid = document.getElementById('employeeGrid');
    if (!allEmployees.length) {
      grid.innerHTML = emptyState('No employees yet. Run the collector on a dev machine to upload metrics.');
      return;
    }
    grid.innerHTML = allEmployees.map(emp => employeeCard(emp)).join('');
    // Attach click handlers
    document.querySelectorAll('.employee-card').forEach(card => {
      card.addEventListener('click', () => openEmployeeModal(card.dataset.id));
    });
  } catch (e) {
    console.error('Employees error:', e);
    showToast('Failed to load employees: ' + e.message);
  } finally {
    showLoading(false);
  }
}

function employeeCard(emp) {
  const m = emp.metrics || {};
  const overall = m.overall_score || 0;
  const cls = scoreClass(overall);
  const scores = [
    ['Prompt Quality', m.score_prompt_quality],
    ['Session Hygiene', m.score_session_hygiene],
    ['Code Review', m.score_code_review],
    ['Tool Mastery', m.score_tool_mastery],
    ['Context Mgmt', m.score_context_management],
  ];
  const scoreBars = scores.map(([label, val]) => `
    <div class="ec-score-row">
      <span class="ec-score-label">${label}</span>
      <div class="ec-score-bar"><div class="ec-score-fill" style="width:${val || 0}%;background:${scoreColor(val || 0)}"></div></div>
      <span class="ec-score-value">${(val || 0).toFixed(0)}</span>
    </div>
  `).join('');

  const flags = (emp.anti_patterns || []).slice(0, 4);
  const empHarnesses = harnessBadges(emp.harness_usage);
  const flagBadges = flags.map(f => `<span class="flag-badge ${severityClass(f.severity)}">${esc(f.rule_name)}</span>`).join('');

  return `
    <div class="employee-card" data-id="${esc(emp.employee_id)}">
      <div class="ec-header">
        <div>
          <div class="ec-name">${esc(emp.name || emp.employee_id)}</div>
          <div class="ec-team">${esc(emp.team || '—')} · ${fmtDate(emp.latest_snapshot)}</div>
        </div>
        <div class="score-ring ${cls}">${overall.toFixed(0)}</div>
      </div>
      <div class="ec-scores">${scoreBars}</div>
      ${empHarnesses}
      <div class="ec-stats">
        <div class="ec-stat"><div class="ec-stat-val">${fmtNum(m.total_requests)}</div><div class="ec-stat-label">Requests</div></div>
        <div class="ec-stat"><div class="ec-stat-val">${fmtNum(m.total_sessions)}</div><div class="ec-stat-label">Sessions</div></div>
        <div class="ec-stat"><div class="ec-stat-val">${fmtNum(m.total_ai_loc)}</div><div class="ec-stat-label">AI LOC</div></div>
        <div class="ec-stat"><div class="ec-stat-val">${fmtCost(m.display_cost_usd ?? m.estimated_cost_usd)}</div><div class="ec-stat-label">AI Spend</div></div>
      </div>
      ${flagBadges ? `<div class="ec-flags">${flagBadges}</div>` : ''}
    </div>
  `;
}

// ── Employee Detail Modal ──────────────────────────────
async function openEmployeeModal(employeeId) {
  const modal = document.getElementById('employeeModal');
  modal.classList.add('active');
  const body = document.getElementById('modalBody');
  body.innerHTML = '<div style="text-align:center;padding:40px"><div class="spinner"></div></div>';

  try {
    const emp = await api(`/api/employees/${encodeURIComponent(employeeId)}`);
    const summary = emp.summary || {};
    const scores = emp.practice_scores || {};
    const patterns = (emp.anti_patterns || []).filter(p => p.triggered).sort((a, b) => {
      const order = { high: 0, medium: 1, low: 2 };
      return (order[a.severity] || 3) - (order[b.severity] || 3) || b.occurrences - a.occurrences;
    });
    const modelUsage = emp.model_usage || {};
    const recommendations = emp.recommendations || {};
    const training = recommendations.training || [];
    const plan = recommendations.plan || {};

    document.getElementById('modalTitle').textContent = emp.name || emp.employee_id;
    const profileHTML = `
      <div class="org-edit-grid" data-employee-profile="${esc(emp.employee_id)}">
        <label>Name<input class="filter-select emp-name-input" value="${esc(emp.name || '')}" placeholder="Display name"></label>
        <label>Email<input class="filter-select emp-email-input" value="${esc(emp.email || '')}" placeholder="email@company.com"></label>
        <label>Team<input class="filter-select emp-team-input" value="${esc(emp.team || '')}" placeholder="Team"></label>
        <button class="btn btn-secondary save-employee-profile">Save Employee</button>
        <button class="btn btn-secondary delete-employee-profile">Delete Employee</button>
      </div>`;

    const scoreCards = [
      ['Prompt Quality', 'prompt-quality', 'prompt_quality'],
      ['Session Hygiene', 'session-hygiene', 'session_hygiene'],
      ['Code Review', 'code-review', 'code_review'],
      ['Tool Mastery', 'tool-mastery', 'tool_mastery'],
      ['Context Mgmt', 'context-management', 'context_management'],
    ].map(([label, hyphenKey, underscoreKey]) => {
      const v = extractScore(scores, hyphenKey, underscoreKey);
      return `<div class="modal-score-card"><div class="ms-label">${label}</div><div class="ms-value" style="color:${scoreColor(v || 0)}">${(v || 0).toFixed(0)}</div></div>`;
    }).join('');

    const summaryItems = [
      ['Sessions', summary.total_sessions],
      ['Requests', summary.total_requests],
      ['Workspaces', summary.total_workspaces],
      ['AI LOC', fmtNum(summary.total_ai_loc)],
      ['Input Tokens', fmtNum(summary.total_input_tokens)],
      ['Output Tokens', fmtNum(summary.total_output_tokens)],
      ['AI Spend', fmtCost(emp.cost_interpretation?.display_cost ?? summary.display_cost_usd ?? summary.estimated_cost_usd)],
      ['Token Estimate', fmtCost(emp.cost_interpretation?.estimated_token_cost ?? summary.estimated_cost_usd)],
      ['Period', `${fmtDate(emp.period_start)} → ${fmtDate(emp.period_end)}`],
    ].map(([l, v]) => `<div class="modal-summary-item"><div class="msi-label">${l}</div><div class="msi-value">${v}</div></div>`).join('');

    const patternHTML = patterns.length ? patterns.map(p => `
      <div class="modal-pattern ${severityClass(p.severity)}">
        <div class="mp-header">
          <span class="mp-name">${esc(p.rule_name)}</span>
          <span class="mp-stats">${p.occurrences} occurrences · ${p.severity}</span>
        </div>
        <div class="mp-desc">${esc(p.description || '')}</div>
        <div class="mp-examples">Examples hidden for privacy. Admins see aggregate counts only.</div>
      </div>
    `).join('') : '<div style="color:var(--text-dim);padding:12px">No anti-patterns detected</div>';

    const modelRows = Object.entries(modelUsage).sort((a, b) => (b[1].requests || 0) - (a[1].requests || 0)).map(([model, info]) => `
      <div class="model-row">
        <span>${esc(model)}</span>
        <span>${info.requests || 0}</span>
        <span>${fmtNum(info.input_tokens || 0)}</span>
        <span>${fmtNum(info.output_tokens || 0)}</span>
        <span>${fmtCost(info.cost_usd)}</span>
      </div>
    `).join('');

    const projectHarness = {};
    for (const p of (emp.projects || [])) {
      for (const [h, n] of Object.entries(p.harness_usage || {})) projectHarness[h] = (projectHarness[h] || 0) + Number(n || 0);
    }
    const employeeHarnessHTML = harnessBadges(projectHarness);

    const trainingHTML = training.length ? training.map(t => `
      <div class="rec-item">
        <span class="rec-priority ${t.priority}">${t.priority}</span>
        <div class="rec-content">
          <div class="rec-track">${esc(t.track)}</div>
          <div class="rec-module">${esc(t.module)}</div>
        </div>
      </div>
    `).join('') : '<div style="color:var(--text-dim);padding:12px">No training needed</div>';

    const planHTML = `
      <div class="plan-recommendation-box">
        <div class="prb-action" style="color:${(plan.action || plan.recommendation) === 'upgrade' ? 'var(--green)' : (plan.action || plan.recommendation) === 'train_first' ? 'var(--yellow)' : 'var(--accent)'}">${esc(plan.action || '—')}</div>
        <div class="prb-reason">${esc(plan.reason || 'Not enough data')}</div>
        <span class="plan-badge ${planClass(plan.action || plan.recommendation)}">${esc(plan.action || plan.recommendation || 'N/A')}</span>
      </div>
    `;

    body.innerHTML = `
      <div class="modal-section">
        <h3>Employee Profile</h3>
        ${profileHTML}
      </div>
      <div class="modal-section">
        <h3>Practice Scores</h3>
        <div class="modal-scores">${scoreCards}</div>
      </div>
      <div class="modal-section">
        <h3>Summary Metrics</h3>
        <div class="modal-summary">${summaryItems}</div>
      </div>
      <div class="modal-section">
        <h3>Anti-Patterns Detected (${patterns.length})</h3>
        <div class="modal-patterns">${patternHTML}</div>
      </div>
      <div class="modal-section">
        <h3>Agent Harness Usage</h3>
        ${employeeHarnessHTML}
      </div>
      <div class="modal-section">
        <h3>Model Usage</h3>
        <div class="modal-model-usage">
          <div class="model-row header"><span>Model</span><span>Requests</span><span>Input</span><span>Output</span><span>Token Est.</span></div>
          ${modelRows || emptyRow('No model usage data')}
        </div>
      </div>
      <div class="modal-section">
        <h3>Training Recommendations</h3>
        <div class="modal-recommendations">${trainingHTML}</div>
      </div>
      <div class="modal-section">
        <h3>Plan Recommendation</h3>
        ${planHTML}
      </div>
    `;
    body.querySelector('.save-employee-profile')?.addEventListener('click', async () => {
      const box = body.querySelector('[data-employee-profile]');
      await apiPut(`/api/employees/${encodeURIComponent(emp.employee_id)}`, {
        name: box.querySelector('.emp-name-input').value.trim(),
        email: box.querySelector('.emp-email-input').value.trim(),
        team: box.querySelector('.emp-team-input').value.trim(),
      });
      allEmployees = [];
      showToast('Employee updated');
      openEmployeeModal(emp.employee_id);
    });
    body.querySelector('.delete-employee-profile')?.addEventListener('click', async () => {
      if (!window.confirm(`Permanently delete ${emp.name || emp.employee_id}? This removes all their snapshots, scores, and history.`)) return;
      await apiDelete(`/api/employees/${encodeURIComponent(emp.employee_id)}`);
      allEmployees = [];
      showToast('Employee deleted');
      document.getElementById('employeeModal').classList.remove('active');
      renderEmployees();
    });
  } catch (e) {
    console.error('Modal error:', e);
    body.innerHTML = `<div class="empty-state"><div class="es-icon">!</div><h3>Failed to load</h3><p>${esc(e.message)}</p></div>`;
  }
}

// ── Training View ──────────────────────────────────────
async function renderTraining() {
  showLoading(true);
  try {
    if (!allEmployees.length) allEmployees = await api('/api/employees');
    if (!allRules.length) allRules = await api('/api/rules');

    // Build training matrix: group by track
    const tracks = {};
    for (const emp of allEmployees) {
      // Fetch detail for each employee to get anti-patterns — but that's N requests.
      // Instead, use the anti_patterns summary from the employees list.
      const patterns = emp.anti_patterns || [];
      for (const p of patterns) {
        if (!p.triggered) continue;
        const rule = allRules.find(r => r.id === p.rule_id);
        if (!rule || !rule.training) continue;
        const track = rule.training.track;
        const module = rule.training.module;
        if (!tracks[track]) tracks[track] = {};
        if (!tracks[track][module]) tracks[track][module] = [];
        tracks[track][module].push({
          employee: emp.name || emp.employee_id,
          severity: p.severity,
          occurrences: p.occurrences,
        });
      }
    }

    const trackIcons = {
      'Prompt Engineering': 'PE',
      'AI Code Review': 'CR',
      'Model & Tool Selection': 'MT',
      'Agent Orchestration': 'AO',
      'Context Engineering': 'CE',
      'Workflow Optimization': 'WO',
      'Work-Life Balance': 'WB',
    };

    const container = document.getElementById('trainingMatrix');
    const trackEntries = Object.entries(tracks);
    if (!trackEntries.length) {
      container.innerHTML = emptyState('No training needs detected yet');
      return;
    }
    container.innerHTML = trackEntries.map(([track, modules]) => `
      <div class="matrix-track">
        <h3><span class="track-icon">${trackIcons[track] || 'TR'}</span> ${esc(track)}</h3>
        <div class="matrix-employees">
          ${Object.entries(modules).map(([module, emps]) => `
            <div class="matrix-emp-row">
              <span class="me-name">${emps.length} employee${emps.length !== 1 ? 's' : ''}</span>
              <span class="me-module">${esc(module)}</span>
              <span class="me-sev">${emps.map(e => e.severity).sort()[0]}</span>
              <span class="me-occur">${emps.reduce((s, e) => s + e.occurrences, 0)} flags</span>
            </div>
          `).join('')}
        </div>
      </div>
    `).join('');
  } catch (e) {
    console.error('Training error:', e);
    showToast('Failed to load training: ' + e.message);
  } finally {
    showLoading(false);
  }
}

// ── Plans View ─────────────────────────────────────────
async function renderPlans() {
  showLoading(true);
  try {
    const [overview, catalog, employees] = await Promise.all([
      api('/api/team/overview'),
      api('/api/plans'),
      api('/api/employees'),
    ]);
    allEmployees = employees || [];
    const recs = overview.plan_recommendations || [];
    const plans = catalog.plans || [];
    const planOptions = plans.map(p => `<option value="${esc(p.id)}">${esc(p.name)} · ${esc(p.billing_mode)} · ${p.price_usd == null ? 'custom' : fmtCost(Number(p.price_usd))}</option>`).join('');
    const container = document.getElementById('plansList');
    const planRows = allEmployees.map(emp => {
      const pc = emp.plan_context || {};
      return `<div class="plan-card plan-config-card">
        <div class="pc-info">
          <div class="pc-name">${esc(emp.name || emp.employee_id)}</div>
          <div class="pc-reason">Current: ${esc(pc.plan_name || pc.plan_id || pc.plan_type || 'not configured')} · Source: ${esc(emp.plan_config_source || 'unknown')}</div>
          <div class="pc-reason">Harness inference can identify provider/tool family only. Paid seat, enterprise tier, and rolling-window allowance require confirmation.</div>
          <div class="filters plan-config-form" data-employee="${esc(emp.employee_id)}">
            <select class="filter-select plan-id-input"><option value="">Select confirmed plan…</option>${planOptions}</select>
            <input class="filter-select rolling-window-input" placeholder="Rolling window $ e.g. 25" style="max-width:180px" />
            <input class="filter-select context-window-input" placeholder="Context tokens e.g. 200000" style="max-width:220px" />
            <button class="btn btn-secondary save-plan-btn">Save Plan</button>
          </div>
        </div>
      </div>`;
    }).join('');
    const recHTML = recs.length ? recs.map(r => `
      <div class="plan-card">
        <div class="pc-info"><div class="pc-name">${esc(r.name || r.employee_id)}</div><div class="pc-reason">${esc(r.reason)}</div></div>
        <span class="plan-badge ${planClass(r.recommendation)}">${esc(r.recommendation)}</span>
      </div>
    `).join('') : emptyState('No plan recommendations yet');
    container.innerHTML = `
      <div class="card card-wide"><h3>Employee Plan Configuration</h3><p class="muted-copy">Configure confirmed paid plans here. AIQ can infer provider/tool family from harness/model names, but cannot safely infer enterprise seat tier or rolling-window limits from local logs.</p>${planRows || emptyState('No employees yet')}</div>
      <div class="card card-wide"><h3>Plan Recommendations</h3>${recHTML}</div>`;
    container.querySelectorAll('.save-plan-btn').forEach(btn => btn.addEventListener('click', async (e) => {
      const form = e.target.closest('.plan-config-form');
      const employeeId = form.dataset.employee;
      const planId = form.querySelector('.plan-id-input').value;
      if (!planId) return showToast('Select a plan first');
      const selected = plans.find(p => p.id === planId) || {};
      const rolling = Number(form.querySelector('.rolling-window-input').value || selected.price_usd || 0);
      const contextWindow = Number(form.querySelector('.context-window-input').value || 0);
      await apiPut(`/api/employees/${encodeURIComponent(employeeId)}/plan`, {
        provider: selected.provider,
        plan_id: selected.id,
        plan_type: selected.id,
        plan_name: selected.name,
        billing_mode: selected.billing_mode,
        seat_cost_usd: selected.price_usd,
        rolling_window_usd: rolling || undefined,
        rolling_window_days: selected.rolling_window_days,
        rolling_window_hours: selected.rolling_window_hours,
        context_window_tokens: contextWindow || undefined,
      });
      allEmployees = [];
      showToast('Plan saved');
      renderPlans();
    }));
  } catch (e) {
    console.error('Plans error:', e);
    showToast('Failed to load plans: ' + e.message);
  } finally {
    showLoading(false);
  }
}

// ── Staffing View ──────────────────────────────────────
async function renderStaffing() {
  showLoading(true);
  try {
    const data = await api('/api/org/staffing');
    const s = data.summary || {};
    const el = document.getElementById('staffingDashboard');
    el.innerHTML = `
      <div class="stat-cards">
        ${statCard('Can Take More', s.high_capacity || 0, 'high score + healthy usage')}
        ${statCard('Train First', s.train_before_more_load || 0, 'before harder work')}
        ${statCard('Relocatable', s.underutilized || 0, 'low usage / available')}
        ${statCard('Capacity Watch', s.overloaded || 0, 'many projects or high load')}
        ${statCard('Projects Flagged', s.projects_flagged || 0, 'staffing pressure')}
      </div>
      <div class="card-grid two-col">
        <div class="card card-wide"><h3>Can Handle More Complex Projects</h3>${staffTable(data.high_capacity, 'No high-capacity candidates yet')}</div>
        <div class="card card-wide"><h3>Needs Training Before More Load</h3>${staffTable(data.train_before_more_load, 'No train-first candidates')}</div>
        <div class="card card-wide"><h3>Potential Relocation / More Allocation</h3>${staffTable(data.underutilized, 'No underutilized employees')}</div>
        <div class="card card-wide"><h3>Capacity Watch</h3>${staffTable(data.overloaded, 'No overloaded employees')}</div>
        <div class="card card-wide" style="grid-column:1/-1"><h3>Project Staffing Pressure</h3>${projectStaffingTable(data.project_staffing)}</div>
      </div>
    `;
  } catch (e) {
    console.error('Staffing error:', e);
    showToast('Failed to load staffing intelligence: ' + e.message);
    document.getElementById('staffingDashboard').innerHTML = emptyState('Failed to load staffing intelligence.');
  } finally {
    showLoading(false);
  }
}

function staffTable(rows, emptyMsg) {
  rows = rows || [];
  if (!rows.length) return emptyState(emptyMsg);
  return `<div class="staff-table">
    <div class="staff-row header"><span>Name</span><span>Team</span><span>Score</span><span>Req</span><span>Proj</span><span>Why</span></div>
    ${rows.map(r => `<div class="staff-row">
      <span>${esc(r.name || r.employee_id)}</span>
      <span>${esc(r.team || '—')}</span>
      <span style="color:${scoreColor(r.overall_score || 0)}">${(r.overall_score || 0).toFixed(0)}</span>
      <span>${fmtNum(r.requests || 0)}</span>
      <span>${r.projects || 0}</span>
      <span class="staff-rec">${esc(r.recommendation || '')}</span>
    </div>`).join('')}
  </div>`;
}

function projectStaffingTable(rows) {
  rows = rows || [];
  if (!rows.length) return emptyState('No project staffing data yet');
  return `<div class="staff-table project-staffing">
    <div class="staff-row header"><span>Project</span><span>Team</span><span>People</span><span>Spend</span><span>Pressure</span><span>Recommendation</span></div>
    ${rows.map(r => `<div class="staff-row">
      <span>${esc(r.project_name)}</span>
      <span>${esc(r.team || '—')}</span>
      <span>${r.people || 0}</span>
      <span class="money">${fmtCost(r.cost_usd)}</span>
      <span><span class="pressure-badge ${esc(r.pressure)}">${esc(r.pressure)}</span></span>
      <span class="staff-rec">${esc(r.recommendation || '')}</span>
    </div>`).join('')}
  </div>`;
}

// ── Projects View ──────────────────────────────────────
async function renderProjects() {
  showLoading(true);
  try {
    const [projects, directory] = await Promise.all([api('/api/projects'), api('/api/org/directory')]);
    const container = document.getElementById('projectsList');
    const directoryHTML = orgDirectoryPanel(directory);
    if (!projects || !projects.length) {
      container.innerHTML = directoryHTML + emptyState('No projects yet. Project data will appear here once the collector reports activity grouped by project path.');
      attachOrgDirectoryHandlers(container);
      return;
    }
    // Sort by total_cost_usd descending
    projects.sort((a, b) => (b.total_cost_usd || 0) - (a.total_cost_usd || 0));
    container.innerHTML = directoryHTML + projects.map(p => projectCard(p)).join('');
    // Attach click handlers
    container.querySelectorAll('.project-card').forEach(card => {
      card.addEventListener('click', () => openProjectModal(card.dataset.id));
    });
    attachOrgDirectoryHandlers(container);
  } catch (e) {
    console.error('Projects error:', e);
    showToast('Failed to load projects: ' + e.message);
    document.getElementById('projectsList').innerHTML = emptyState('Failed to load projects. Check that the server is running.');
  } finally {
    showLoading(false);
  }
}

function attachOrgDirectoryHandlers(container) {
  container.querySelector('.add-team-btn')?.addEventListener('click', async () => {
    const name = container.querySelector('.new-team-name').value.trim();
    if (!name) return showToast('Enter a team name');
    await apiPut(`/api/teams/${encodeURIComponent(name)}`, {});
    showToast('Team added');
    renderProjects();
  });
  container.querySelector('.add-client-btn')?.addEventListener('click', async () => {
    const name = container.querySelector('.new-client-name').value.trim();
    if (!name) return showToast('Enter a client name');
    await apiPut(`/api/clients/${encodeURIComponent(name)}`, {});
    showToast('Client added');
    renderProjects();
  });
  container.querySelectorAll('.delete-team-btn').forEach(btn => btn.addEventListener('click', async () => {
    const name = btn.dataset.team;
    if (!window.confirm(`Delete team "${name}"? This only removes it from the team catalog — employees/projects keep their team field.`)) return;
    await apiDelete(`/api/teams/${encodeURIComponent(name)}`);
    showToast('Team deleted');
    renderProjects();
  }));
  container.querySelectorAll('.delete-client-btn').forEach(btn => btn.addEventListener('click', async () => {
    const name = btn.dataset.client;
    if (!window.confirm(`Delete client "${name}"? This only removes it from the client catalog — projects keep their client field.`)) return;
    await apiDelete(`/api/clients/${encodeURIComponent(name)}`);
    showToast('Client deleted');
    renderProjects();
  }));
  container.querySelector('.add-project-btn')?.addEventListener('click', async () => {
    const name = container.querySelector('.new-project-name').value.trim();
    if (!name) return showToast('Enter a project name');
    const customer = container.querySelector('.new-project-customer')?.value.trim() || '';
    const remote = container.querySelector('.new-project-remote')?.value.trim() || '';
    await apiPost('/api/projects', { project_name: name, customer_name: customer, git_remote_url: remote });
    showToast('Project added');
    renderProjects();
  });
}

function orgDirectoryPanel(directory) {
  const teams = directory?.teams || [];
  const clients = directory?.clients || [];
  const employees = directory?.employees || [];
  const teamRows = teams.slice(0, 8).map(t => `<div class="exec-row compact"><span>${esc(t.name)}</span><span>${t.employees || 0} people</span><span>${t.projects || 0} projects</span><button class="btn btn-secondary delete-team-btn" data-team="${esc(t.name)}" title="Delete team">Delete</button></div>`).join('');
  const clientRows = clients.slice(0, 8).map(c => `<div class="exec-row compact"><span>${esc(c.name)}</span><span>${c.projects || 0} projects</span><span>${fmtCost(c.cost_usd || 0)}</span><button class="btn btn-secondary delete-client-btn" data-client="${esc(c.name)}" title="Delete client">Delete</button></div>`).join('');
  return `<div class="card card-wide org-directory-card">
    <h3>Org Directory</h3>
    <p class="muted-copy">AIQ keeps employees, teams, projects, and clients optional but editable. Edge collectors keep project membership fresh automatically; admins can correct names, teams, clients, and billing codes here.</p>
    <div class="stat-cards compact-stats">
      ${statCard('Employees', employees.length, 'registered')}
      ${statCard('Teams', teams.length, 'optional')}
      ${statCard('Clients', clients.length, 'optional')}
      ${statCard('Projects', (directory?.projects || []).length, 'assigned')}
    </div>
    <div class="org-edit-grid add-project-form project-create-form" style="margin-bottom:14px">
      <label>Project Name<input class="filter-select new-project-name" placeholder="Payments API"></label>
      <label>Customer Name<input class="filter-select new-project-customer" placeholder="Customer / internal org"></label>
      <label>Git Remote URL<input class="filter-select new-project-remote" placeholder="git@github.com:org/repo.git or https://github.com/org/repo.git"></label>
      <button class="btn btn-secondary add-project-btn">Add Project</button>
    </div>
    <div class="card-grid two-col">
      <div><h4>Teams</h4><div class="exec-table">${teamRows || emptyRow('No teams yet')}</div><div class="org-edit-grid add-team-form"><input class="filter-select new-team-name" placeholder="New team name"><button class="btn btn-secondary add-team-btn">Add Team</button></div></div>
      <div><h4>Clients</h4><div class="exec-table">${clientRows || emptyRow('No clients yet')}</div><div class="org-edit-grid add-client-form"><input class="filter-select new-client-name" placeholder="New client name"><button class="btn btn-secondary add-client-btn">Add Client</button></div></div>
    </div>
  </div>`;
}

function projectCard(p) {
  const employees = p.employees || [];
  const workTypes = p.work_types || {};
  const topWorkTypes = Object.entries(workTypes)
    .sort((a, b) => (b[1] || 0) - (a[1] || 0))
    .slice(0, 3)
    .map(([type]) => `<span class="work-type-badge">${esc(type)}</span>`)
    .join('');
  const team = p.team || (employees.length ? employees[0].team : null);
  return `
    <div class="project-card" data-id="${esc(p.project_id)}">
      <div class="pc-header">
        <div class="pc-title">${esc(p.project_name)}</div>
        <div class="pc-cost">${fmtCost(p.total_cost_usd)}</div>
      </div>
      <div class="pc-meta">
        ${team ? `<span class="pc-meta-item">Team: ${esc(team)}</span>` : ''}
        ${(p.customer_name || p.client) ? `<span class="pc-meta-item">Customer: ${esc(p.customer_name || p.client)}</span>` : ''}
        <span class="pc-meta-item">Repo: ${esc(p.normalized_git_remote || 'untracked')}</span>
      </div>
      <div class="pc-stats">
        <div class="pc-stat"><div class="pc-stat-val">${fmtNum(p.total_requests)}</div><div class="pc-stat-label">Requests</div></div>
        <div class="pc-stat"><div class="pc-stat-val">${fmtNum(p.total_ai_loc)}</div><div class="pc-stat-label">AI LOC</div></div>
        <div class="pc-stat"><div class="pc-stat-val">${employees.length}</div><div class="pc-stat-label">People</div></div>
        <div class="pc-stat"><div class="pc-stat-val">${p.active_days || 0}</div><div class="pc-stat-label">Active Days</div></div>
      </div>
      <div class="pc-period">${fmtDate(p.first_activity)} to ${fmtDate(p.last_activity)}</div>
      ${harnessBadges(p.harness_usage)}
      ${topWorkTypes ? `<div class="pc-work-types">${topWorkTypes}</div>` : ''}
    </div>
  `;
}

function harnessBadges(harnesses) {
  const entries = Object.entries(harnesses || {}).sort((a, b) => (b[1] || 0) - (a[1] || 0));
  if (!entries.length) return '<div class="harness-badges"><span class="harness-badge muted">no harness data</span></div>';
  return `<div class="harness-badges">${entries.slice(0, 5).map(([h, n]) => `<span class="harness-badge">${esc(h)} <b>${fmtNum(n)}</b></span>`).join('')}</div>`;
}

// ── Project Detail Modal ───────────────────────────────
async function openProjectModal(projectId) {
  const modal = document.getElementById('employeeModal');
  modal.classList.add('active');
  const body = document.getElementById('modalBody');
  body.innerHTML = '<div style="text-align:center;padding:40px"><div class="spinner"></div></div>';

  try {
    const p = await api(`/api/projects/${encodeURIComponent(projectId)}`);
    document.getElementById('modalTitle').textContent = p.project_name || 'Project Details';

    const employees = p.employees || [];
    const workTypes = p.work_types || {};
    const modelUsage = p.model_usage || {};

    // Metadata
    const team = p.team || null;
    const client = p.client || null;
    const billingCode = p.billing_code || null;
    const isUnassigned = !team && !client && !billingCode;

    const metaItem = (label, val) => {
      const empty = val == null || val === '';
      return `<div class="project-meta-item ${empty ? 'unassigned' : ''}">
        <div class="pmi-label">${label}</div>
        <div class="pmi-value">${empty ? 'Unassigned' : esc(val)}</div>
      </div>`;
    };

    const metaHTML = `
      <div class="org-edit-grid" data-project-profile="${esc(p.project_id)}">
        <label>Project Name<input class="filter-select project-name-input" value="${esc(p.project_name || '')}" placeholder="Project name"></label>
        <label>Team<input class="filter-select project-team-input" value="${esc(team || '')}" placeholder="Owning team"></label>
        <label>Customer<input class="filter-select project-customer-input" value="${esc(p.customer_name || client || '')}" placeholder="Customer / internal org"></label>
        <label>Git Remote URL<input class="filter-select project-remote-input" value="${esc(p.git_remote_url || '')}" placeholder="git@github.com:org/repo.git"></label>
        <label>Billing Code<input class="filter-select project-billing-input" value="${esc(billingCode || '')}" placeholder="Optional"></label>
        <button class="btn btn-secondary save-project-profile">Save Project</button>
      </div>
      <div class="project-meta-grid">
        ${metaItem('Team', team)}
        ${metaItem('Customer', p.customer_name || client)}
        ${metaItem('Git Remote', p.normalized_git_remote || p.git_remote_url || '')}
        ${metaItem('Billing Code', billingCode)}
        <div class="project-meta-item">
          <div class="pmi-label">Project Path</div>
          <div class="pmi-value" style="font-size:12px;font-family:'SF Mono','Monaco','Cascadia Code',monospace">${esc(p.project_path || '—')}</div>
        </div>
      </div>
      ${isUnassigned ? '<div class="unassigned-note">This project has no team, client, or billing code assigned. An admin can assign these via the project metadata to enable proper cost tracking and attribution.</div>' : ''}
    `;

    // Stat cards
    const statCards = [
      ['AI Spend', fmtCost(p.total_cost_usd)],
      ['Total Requests', fmtNum(p.total_requests)],
      ['Total AI LOC', fmtNum(p.total_ai_loc)],
      ['Active Days', p.active_days || 0],
      ['Sessions', fmtNum(p.total_sessions)],
      ['Files Edited', p.files_edited_count || 0],
    ].map(([l, v]) => statCard(l, v, '')).join('');

    // Harness drilldown and per-employee table
    const harnessMap = {};
    for (const e of employees) {
      const hs = e.harness_usage || p.harness_usage || {};
      const entries = Object.entries(hs).length ? Object.entries(hs) : [['unknown', e.sessions || 0]];
      for (const [h, n] of entries) {
        if (!harnessMap[h]) harnessMap[h] = { sessions: 0, employees: [] };
        harnessMap[h].sessions += Number(n || 0);
        harnessMap[h].employees.push(e);
      }
    }
    const harnessHTML = Object.entries(harnessMap).sort((a, b) => b[1].sessions - a[1].sessions).map(([h, info]) => `
      <details class="harness-drilldown" open>
        <summary><span>${esc(h)}</span><b>${fmtNum(info.sessions)} sessions</b><small>${info.employees.length} employees</small></summary>
        <div class="staff-table compact-table">
          ${info.employees.slice(0, 12).map(e => `<div class="staff-row"><span>${esc(e.employee_name || e.employee_id)}</span><span>${esc(e.team || '—')}</span><span>${fmtNum(e.requests || 0)} req</span><span>${fmtCost(e.cost_usd)}</span></div>`).join('')}
        </div>
      </details>`).join('') || emptyState('No harness data');
    const sortedEmps = [...employees].sort((a, b) => (b.cost_usd || 0) - (a.cost_usd || 0));
    const empRows = sortedEmps.length ? sortedEmps.map(e => `
      <tr>
        <td>${esc(e.employee_name || e.employee_id)}</td>
        <td>${esc(e.team || '—')}</td>
        <td>${fmtNum(e.sessions || 0)}</td>
        <td>${fmtNum(e.requests || 0)}</td>
        <td>${fmtNum(e.ai_loc || 0)}</td>
        <td style="color:var(--yellow)">${fmtCost(e.cost_usd)}</td>
        <td>${e.active_days || 0}</td>
      </tr>
    `).join('') : emptyRow('No employee data');

    // Work type distribution
    const wtEntries = Object.entries(workTypes).sort((a, b) => (b[1] || 0) - (a[1] || 0));
    const wtTotal = wtEntries.reduce((s, [, v]) => s + (v || 0), 0) || 1;
    const workTypeHTML = wtEntries.length ? wtEntries.map(([type, count]) => {
      const pct = ((count / wtTotal) * 100).toFixed(1);
      return `<div class="dist-row">
        <span class="dist-label">${esc(type)}</span>
        <div class="dist-bar"><div class="dist-fill" style="width:${pct}%;background:var(--accent)"></div></div>
        <span class="dist-val">${fmtNum(count)}</span>
      </div>`;
    }).join('') : emptyRow('No work type data');

    // Model usage
    const modelEntries = Object.entries(modelUsage).sort((a, b) => {
      const bc = b[1]?.cost_usd || (typeof b[1] === 'number' ? b[1] : 0);
      const ac = a[1]?.cost_usd || (typeof a[1] === 'number' ? a[1] : 0);
      return bc - ac;
    });
    const modelHTML = modelEntries.length ? modelEntries.map(([model, info]) => {
      const req = info?.requests || 0;
      const inp = info?.input_tokens || 0;
      const out = info?.output_tokens || 0;
      const cost = info?.cost_usd || 0;
      return `<div class="model-row">
        <span>${esc(model)}</span>
        <span>${fmtNum(req)}</span>
        <span>${fmtNum(inp)}</span>
        <span>${fmtNum(out)}</span>
        <span>${fmtCost(cost)}</span>
      </div>`;
    }).join('') : emptyRow('No model usage data');

    // Git branches
    const branches = p.git_branches || p.branches || [];
    const branchHTML = branches.length ? `<div class="proj-branches">${branches.map(b => `<span class="proj-branch-tag">${esc(b)}</span>`).join('')}</div>` : '<div style="color:var(--text-dim);padding:12px">No branch data</div>';

    body.innerHTML = `
      <div class="modal-section">
        <h3>Project Metadata</h3>
        ${metaHTML}
      </div>
      <div class="modal-section">
        <div class="stat-cards">${statCards}</div>
      </div>
      <div class="modal-section">
        <h3>Agent Harness Drilldown</h3>
        ${harnessHTML}
      </div>
      <div class="modal-section">
        <h3>Employee Breakdown (${employees.length})</h3>
        <table class="proj-emp-table">
          <thead><tr>
            <th>Name</th><th>Team</th><th>Sessions</th><th>Requests</th><th>AI LOC</th><th>Spend</th><th>Active Days</th>
          </tr></thead>
          <tbody>${empRows}</tbody>
        </table>
      </div>
      <div class="modal-section">
        <h3>Work Type Distribution</h3>
        <div style="display:flex;flex-direction:column;gap:6px">${workTypeHTML}</div>
      </div>
      <div class="modal-section">
        <h3>Model Usage</h3>
        <div class="modal-model-usage">
          <div class="model-row header"><span>Model</span><span>Requests</span><span>Input</span><span>Output</span><span>Token Est.</span></div>
          ${modelHTML}
        </div>
      </div>
      <div class="modal-section">
        <h3>Git Branches</h3>
        ${branchHTML}
      </div>
    `;
    body.querySelector('.save-project-profile')?.addEventListener('click', async () => {
      const box = body.querySelector('[data-project-profile]');
      await apiPatch(`/api/projects/${encodeURIComponent(p.project_id)}`, {
        project_name: box.querySelector('.project-name-input').value.trim(),
        team: box.querySelector('.project-team-input').value.trim(),
        customer_name: box.querySelector('.project-customer-input').value.trim(),
        client: box.querySelector('.project-customer-input').value.trim(),
        git_remote_url: box.querySelector('.project-remote-input').value.trim(),
        billing_code: box.querySelector('.project-billing-input').value.trim(),
      });
      showToast('Project updated');
      renderProjects();
      openProjectModal(p.project_id);
    });
  } catch (e) {
    console.error('Project modal error:', e);
    body.innerHTML = `<div class="empty-state"><div class="es-icon">!</div><h3>Failed to load</h3><p>${esc(e.message)}</p></div>`;
  }
}

// ── Rules View ─────────────────────────────────────────
async function renderRules() {
  showLoading(true);
  try {
    allRules = await api('/api/rules');
    const container = document.getElementById('rulesList');
    const verdict = { keep: 'Keep', watch: 'Review', off: 'Off by default' };
    container.innerHTML = `
      <div class="card card-wide rules-audit-note">
        <h3>Rule basis</h3>
        <p>Rules now favor observable engineering behaviors: context quality, human verification, runaway loops, cancellation/rework, and plan pressure. Lifestyle or weak proxy signals are off by default.</p>
      </div>
      ${allRules.map(r => `
        <div class="rule-card ${r.enabled === false ? 'rule-disabled' : ''}">
          <div class="rc-info">
            <div class="rc-title-row"><h4>${esc(r.name)}</h4><span class="rc-verdict ${esc(r.audit_status || 'keep')}">${verdict[r.audit_status] || 'Keep'}</span></div>
            <p>${esc(r.description)}</p>
            <div class="rc-suggestion">${esc(r.suggestion)}</div>
            <div class="rc-basis">Basis: ${esc(r.basis || 'Observable log signal')}</div>
          </div>
          <div class="rc-meta rule-controls" data-rule="${esc(r.id)}">
            <span class="rc-group">${esc(r.group)}</span>
            <span class="flag-badge ${severityClass(r.severity)}">${r.severity}</span>
            <label class="rule-toggle"><input type="checkbox" class="rule-enabled-input" ${r.enabled !== false ? 'checked' : ''}> enabled</label>
            <select class="filter-select rule-severity-input">
              ${['high','medium','low'].map(s => `<option value="${s}" ${s === r.severity ? 'selected' : ''}>${s}</option>`).join('')}
            </select>
            <button class="btn btn-secondary save-rule-btn">Save</button>
          </div>
        </div>
      `).join('')}`;
    container.querySelectorAll('.save-rule-btn').forEach(btn => btn.addEventListener('click', async (e) => {
      const box = e.target.closest('.rule-controls');
      await apiPut(`/api/rules/${encodeURIComponent(box.dataset.rule)}`, {
        enabled: box.querySelector('.rule-enabled-input').checked,
        severity: box.querySelector('.rule-severity-input').value,
      });
      allRules = [];
      showToast('Rule updated');
      renderRules();
    }));
  } catch (e) {
    console.error('Rules error:', e);
    showToast('Failed to load rules: ' + e.message);
  } finally {
    showLoading(false);
  }
}

// ── Personal Dashboard (My Overview / Activity / Skills / Projects / Prompts / Plan) ──
function meApiKeyGateHTML() {
  return `
    <div class="card card-wide">
      <h3>Connect your AIQ collector</h3>
      <p style="color:var(--text-dim);margin-bottom:16px">Paste the API key created by <code>aiq register</code>. It stays in this browser only and unlocks your personal dashboard.</p>
      <div class="filters">
        <input id="meApiKeyInput" class="filter-select" style="min-width:420px" placeholder="ak_..." />
        <button class="btn btn-secondary" id="saveMeApiKey">Save key</button>
      </div>
    </div>`;
}

function meErrorHTML(e) {
  const isAuth = String(e.message || '').includes('401');
  return `<div class="empty-state"><div class="es-icon">!</div><h3>Could not load personal dashboard</h3><p>${esc(e.message)}</p><div style="text-align:left;max-width:680px;margin:16px auto;color:var(--text-dim);line-height:1.7"><strong>Fix checklist:</strong><br>1. Make sure the AIQ server terminal is still running: <code>python scripts/aiq-mothership.py health --server-url ${esc(API_BASE)}</code><br>2. Make sure you registered: <code>aiq register --server-url ${esc(API_BASE)} --invite-code &lt;code&gt; --employee-id &lt;you&gt;</code><br>3. Run one collection: <code>aiq collect</code><br>4. Paste the <code>api_key</code> from <code>~/.aiq/config.toml</code> here again.${isAuth ? '<br><strong>The saved key looks invalid or belongs to another mothership.</strong>' : ''}</div><button class="btn btn-secondary" id="clearBadApiKey">Clear key</button></div>`;
}

function getMeData(force) {
  if (force) { meData = null; meDataPromise = null; }
  if (meData) return Promise.resolve(meData);
  if (!meDataPromise) {
    meDataPromise = api('/api/me', { timeoutMs: 12000 })
      .then(d => { meData = d; meDataPromise = null; return d; })
      .catch(e => { meDataPromise = null; throw e; });
  }
  return meDataPromise;
}

async function renderMeView(containerId, renderFn) {
  const container = document.getElementById(containerId);
  const apiKey = localStorage.getItem('aiq_api_key') || '';
  if (!apiKey) {
    container.innerHTML = meApiKeyGateHTML();
    document.getElementById('saveMeApiKey').addEventListener('click', () => {
      const key = document.getElementById('meApiKeyInput').value.trim();
      if (!key) return showToast('Paste an API key first');
      localStorage.setItem('aiq_api_key', key);
      renderView(currentView);
    });
    return;
  }
  showLoading(true);
  try {
    const emp = await getMeData();
    renderFn(container, emp);
  } catch (e) {
    console.error('Personal dashboard error:', e);
    container.innerHTML = meErrorHTML(e);
    document.getElementById('clearBadApiKey').addEventListener('click', () => {
      localStorage.removeItem('aiq_api_key');
      meData = null;
      renderView(currentView);
    });
  } finally {
    showLoading(false);
  }
}

function meScoreCards(scores) {
  return [
    ['Prompt Quality', 'prompt-quality', 'prompt_quality'],
    ['Session Hygiene', 'session-hygiene', 'session_hygiene'],
    ['Code Review', 'code-review', 'code_review'],
    ['Tool Mastery', 'tool-mastery', 'tool_mastery'],
    ['Context Mgmt', 'context-management', 'context_management'],
  ].map(([label, hyphenKey, underscoreKey]) => {
    const v = extractScore(scores, hyphenKey, underscoreKey);
    return `<div class="modal-score-card"><div class="ms-label">${label}</div><div class="ms-value" style="color:${scoreColor(v || 0)}">${(v || 0).toFixed(0)}</div></div>`;
  }).join('');
}

function renderMeOverview() {
  renderMeView('meOverview', (container, emp) => {
    const summary = emp.summary || {};
    const scores = emp.practice_scores || {};
    const recs = emp.recommendations || {};
    const plan = recs.plan || {};
    const planFit = emp.plan_fit || {};
    const costInfo = emp.cost_interpretation || {};
    const action = planFit.recommendation || plan.action || 'maintain';
    container.innerHTML = `
      <div class="stat-cards">
        ${statCard('Employee', esc(emp.name || emp.employee_id || 'You'), esc(emp.team || 'team not set'))}
        ${statCard('Requests', fmtNum(summary.total_requests), 'AI interactions')}
        ${statCard('Sessions', fmtNum(summary.total_sessions), 'logged sessions')}
        ${statCard('AI Spend', fmtCost(costInfo.display_cost ?? summary.display_cost_usd ?? summary.estimated_cost_usd), costInfo.cost_label || 'billed / estimated')}
        ${statCard('AI LOC', fmtNum(summary.total_ai_loc), 'generated lines')}
      </div>
      <div class="card-grid two-col">
        <div class="card card-wide"><h3>Your Practice Scores</h3><div class="modal-scores">${meScoreCards(scores)}</div></div>
        <div class="card card-wide">
          <h3>Plan Fit</h3>
          <div class="plan-recommendation-box">
            <div>
              <div class="prb-action" style="color:${action === 'upgrade' ? 'var(--green)' : action === 'train_first' ? 'var(--yellow)' : action === 'downgrade' ? 'var(--orange)' : 'var(--accent)'}">${esc(action)}</div>
              <div class="prb-reason">${esc(planFit.reason || plan.reason || 'Not enough data')}</div>
            </div>
            <span class="plan-badge ${planClass(action)}">${esc(planFit.recommended_plan_id || plan.plan || 'current')}</span>
          </div>
          <p class="muted-copy" style="margin-top:12px">See Skills & Coaching for practice detail, and Plan & Usage for full billing context.</p>
        </div>
      </div>
      <button class="btn btn-secondary" id="clearMeApiKey" style="margin-top:18px">Clear saved API key</button>
    `;
    document.getElementById('clearMeApiKey').addEventListener('click', () => {
      localStorage.removeItem('aiq_api_key');
      meData = null;
      renderView(currentView);
    });
  });
}

async function renderMeActivity() {
  await renderMeView('meActivity', async (container, emp) => {
    const summary = emp.summary || {};
    container.innerHTML = `
      <div class="stat-cards">
        ${statCard('Requests', fmtNum(summary.total_requests), 'AI interactions')}
        ${statCard('Sessions', fmtNum(summary.total_sessions), 'logged sessions')}
        ${statCard('AI LOC', fmtNum(summary.total_ai_loc), 'generated lines')}
        ${statCard('Workspaces', fmtNum(summary.total_workspaces), 'tracked folders')}
      </div>
      <div class="card card-wide"><h3>Score History</h3><div id="meHistoryTable">Loading history…</div></div>
    `;
    try {
      const history = await api('/api/me/history', { timeoutMs: 12000 });
      const rows = (history || []).slice().reverse().map(h => `
        <div class="team-row">
          <span class="team-name">${fmtDate(h.period_end || h.uploaded_at)}</span>
          <span style="color:${scoreColor(h.overall_score || 0)}">${(h.overall_score || 0).toFixed(0)}</span>
          <span>${(h.scores?.prompt_quality ?? 0).toFixed(0)}</span>
          <span>${(h.scores?.session_hygiene ?? 0).toFixed(0)}</span>
          <span>${(h.scores?.code_review ?? 0).toFixed(0)}</span>
        </div>
      `).join('');
      document.getElementById('meHistoryTable').outerHTML = `
        <div class="team-breakdown" id="meHistoryTable">
          <div class="team-row header"><span>Snapshot</span><span>Overall</span><span>Prompt Qual.</span><span>Session Hyg.</span><span>Code Review</span></div>
          ${rows || emptyRow('No score history yet — run a few collections over time to see a trend')}
        </div>`;
    } catch (e) {
      console.error('Me history error:', e);
      document.getElementById('meHistoryTable').outerHTML = emptyState('Could not load score history.');
    }
  });
}

function renderMeSkills() {
  renderMeView('meSkills', (container, emp) => {
    const scores = emp.practice_scores || {};
    const recs = emp.recommendations || {};
    const training = recs.training || [];
    const patterns = (emp.anti_patterns || []).filter(p => p.triggered);
    const trainingHTML = training.length ? training.map(t => `
      <div class="rec-item"><span class="rec-priority ${t.priority}">${t.priority}</span><div class="rec-content"><div class="rec-track">${esc(t.track)}</div><div class="rec-module">${esc(t.module)}</div></div></div>
    `).join('') : '<div style="color:var(--text-dim);padding:12px">No training needed</div>';
    const patternHTML = patterns.length ? patterns.map(p => `
      <div class="modal-pattern ${severityClass(p.severity)}"><div class="mp-header"><span class="mp-name">${esc(p.rule_name)}</span><span class="mp-stats">${p.occurrences} · ${p.severity}</span></div><div class="mp-desc">${esc(p.description || '')}</div></div>
    `).join('') : '<div style="color:var(--text-dim);padding:12px">No anti-patterns detected</div>';
    container.innerHTML = `
      <div class="card-grid">
        <div class="card card-wide"><h3>Your Practice Scores</h3><div class="modal-scores">${meScoreCards(scores)}</div></div>
        <div class="card card-wide"><h3>Your Training Recommendations</h3><div class="modal-recommendations">${trainingHTML}</div></div>
        <div class="card card-wide"><h3>Your Anti-Patterns (${patterns.length})</h3><div class="modal-patterns">${patternHTML}</div></div>
      </div>
    `;
  });
}

function renderMeProjects() {
  renderMeView('meProjects', (container, emp) => {
    const myProjects = emp.projects || [];
    const assignable = emp.assignable_projects || [];
    const projectOptions = '<option value="">Other Usage</option>' + assignable.map(x => `<option value="${esc(x.project_id)}">${esc(x.project_name)}</option>`).join('');
    const projectHarness = {};
    for (const p of myProjects) {
      for (const [h, n] of Object.entries(p.harness_usage || {})) projectHarness[h] = (projectHarness[h] || 0) + Number(n || 0);
    }
    const projectHTML = myProjects.length ? `<div class="staff-table project-staffing">
      <div class="staff-row header"><span>Detected usage</span><span>Assigned to</span><span>Req</span><span>Cost</span><span>AI LOC</span><span>Save</span></div>
      ${myProjects.map(p => `<div class="staff-row project-assign-row" data-detected="${esc(p.detected_project_id || p.project_id)}">
        <span>${esc(p.detected_project_name || p.project_name)}</span>
        <span><select class="filter-select assign-project-select">${projectOptions.replace(`value="${esc(p.project_id)}"`, `value="${esc(p.project_id)}" selected`)}</select></span>
        <span>${fmtNum(p.requests || 0)}</span>
        <span class="money">${fmtCost(p.cost_usd)}</span>
        <span>${fmtNum(p.ai_loc || 0)}</span>
        <span><button class="btn btn-secondary save-project-assignment">Save</button></span>
      </div>`).join('')}
    </div>` : emptyState('No project-level activity found yet.');
    container.innerHTML = `
      <div class="card card-wide"><h3>Your Projects (${myProjects.length})</h3>${projectHTML}</div>
      <div class="card card-wide" style="margin-top:16px"><h3>Agent Harness Usage</h3>${harnessBadges(projectHarness)}</div>
    `;
    container.querySelectorAll('.save-project-assignment').forEach(btn => btn.addEventListener('click', async (e) => {
      const row = e.target.closest('.project-assign-row');
      await apiPut(`/api/me/projects/${encodeURIComponent(row.dataset.detected)}`, { project_id: row.querySelector('.assign-project-select').value });
      showToast('Project assignment saved');
      meData = null;
      renderMeProjects();
    }));
  });
}

function renderMePrompts() {
  renderMeView('mePrompts', (container) => {
    container.innerHTML = `
      <div class="card card-wide">
        <h3>Prompt History</h3>
        <div class="empty-state">
          <div class="es-icon">--</div>
          <p>AIQ does not store or expose individual prompt text today — only aggregate metrics and detected patterns. This tab is reserved for when per-prompt history (private to you) ships.</p>
        </div>
      </div>
    `;
  });
}

function renderMePlan() {
  renderMeView('mePlan', (container, emp) => {
    const summary = emp.summary || {};
    const recs = emp.recommendations || {};
    const plan = recs.plan || {};
    const planFit = emp.plan_fit || {};
    const costInfo = emp.cost_interpretation || {};
    const planContext = emp.plan_context || {};
    const planSource = emp.plan_config_source || 'unknown';
    const planInference = emp.plan_inference || {};
    const action = planFit.recommendation || plan.action || 'maintain';
    container.innerHTML = `
      <div class="card card-wide">
        <h3>Your Plan Fit</h3>
        <div class="plan-recommendation-box">
          <div>
            <div class="prb-action" style="color:${action === 'upgrade' ? 'var(--green)' : action === 'train_first' ? 'var(--yellow)' : action === 'downgrade' ? 'var(--orange)' : 'var(--accent)'}">${esc(action)}</div>
            <div class="prb-reason">${esc(planFit.reason || plan.reason || 'Not enough data')}</div>
          </div>
          <span class="plan-badge ${planClass(action)}">${esc(planFit.recommended_plan_id || planFit.recommendation || plan.plan || 'current')}</span>
        </div>
        <div class="project-meta-grid" style="margin-top:12px">
          <div class="project-meta-item"><div class="pmi-label">Spend Meaning</div><div class="pmi-value">${esc(costInfo.cost_label || 'Estimated API Spend')}</div></div>
          <div class="project-meta-item"><div class="pmi-label">Token Estimate</div><div class="pmi-value">${fmtCost(costInfo.estimated_token_cost ?? summary.estimated_cost_usd)}</div></div>
          <div class="project-meta-item"><div class="pmi-label">Billed Months</div><div class="pmi-value">${costInfo.billed_months ?? '—'}</div></div>
          <div class="project-meta-item"><div class="pmi-label">Pressure</div><div class="pmi-value">${esc(costInfo.pressure_level || 'unknown')}</div></div>
          <div class="project-meta-item"><div class="pmi-label">Utilization</div><div class="pmi-value">${costInfo.utilization != null ? `${Math.round((costInfo.utilization || 0) * 100)}%` : '—'}</div></div>
          <div class="project-meta-item"><div class="pmi-label">Context Usage</div><div class="pmi-value">${costInfo.context_window_tokens ? `${Math.round((costInfo.context_utilization || 0) * 100)}% of ${fmtNum(costInfo.context_window_tokens)}` : '—'}</div></div>
          <div class="project-meta-item"><div class="pmi-label">Plan Source</div><div class="pmi-value">${esc(planSource)}</div></div>
        </div>
        ${planIdentityHTML(planContext, costInfo)}
        <div class="unassigned-note">Detected provider: ${esc(planInference.provider || 'unknown')} (${esc(planInference.confidence || 'none')}). The harness cannot reliably know your paid plan or enterprise rolling-window allowance. Configure locally with <code>aiq config --plan-type &lt;plan_id&gt; --plan-name "&lt;Plan Name&gt;" --rolling-window-usd &lt;amount&gt;</code>, or ask an admin to set it under Plan Recommendations.</div>
      </div>
    `;
  });
}

// ── Utilities ──────────────────────────────────────────
function esc(s) {
  if (s == null) return '';
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function showLoading(show) {
  document.getElementById('loadingOverlay').classList.toggle('hidden', !show);
}

function showToast(msg) {
  const t = document.createElement('div');
  t.style.cssText = 'position:fixed;bottom:20px;right:20px;background:var(--surface);border:1px solid var(--red);border-radius:8px;padding:14px 20px;z-index:2000;font-size:13px;max-width:400px';
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 5000);
}

async function checkServerStatus() {
  const el = document.getElementById('serverStatus');
  try {
    await api('/api/health');
    el.querySelector('.status-dot').className = 'status-dot connected';
    el.querySelector('.status-text').textContent = 'Server connected';
  } catch {
    el.querySelector('.status-dot').className = 'status-dot error';
    el.querySelector('.status-text').textContent = 'Server offline';
  }
}

// ── Init ───────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  initTheme();
  const params = new URLSearchParams(window.location.search);
  const keyFromUrl = params.get('api_key') || params.get('key');
  if (keyFromUrl && keyFromUrl.startsWith('ak_')) {
    localStorage.setItem('aiq_api_key', keyFromUrl);
    const clean = `${window.location.pathname}${window.location.hash || ''}`;
    window.history.replaceState({}, '', clean);
  }

  // Dashboard split: admin at /, employee-only self dashboard at /me.
  document.body.classList.toggle('employee-dashboard-mode', IS_EMPLOYEE_DASHBOARD);
  document.body.classList.toggle('admin-dashboard-mode', !IS_EMPLOYEE_DASHBOARD);
  document.querySelectorAll('.nav-item').forEach(item => {
    const isPersonalItem = PERSONAL_VIEWS.includes(item.dataset.view);
    if (IS_EMPLOYEE_DASHBOARD && !isPersonalItem) item.remove();
    if (!IS_EMPLOYEE_DASHBOARD && isPersonalItem) item.remove();
  });
  document.querySelector('.logo-sub').textContent = IS_EMPLOYEE_DASHBOARD ? 'Personal' : 'Admin';
  document.title = IS_EMPLOYEE_DASHBOARD ? 'AIQ Personal Dashboard' : 'AIQ Admin Dashboard';

  // Nav switching
  document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', () => switchView(item.dataset.view));
  });

  // Modal close
  document.getElementById('modalClose').addEventListener('click', () => {
    document.getElementById('employeeModal').classList.remove('active');
  });
  document.getElementById('employeeModal').addEventListener('click', (e) => {
    if (e.target.id === 'employeeModal') {
      document.getElementById('employeeModal').classList.remove('active');
    }
  });

  // Refresh
  document.getElementById('themeToggle').addEventListener('click', () => {
    setTheme(document.documentElement.dataset.theme === 'light' ? 'dark' : 'light');
  });
  document.getElementById('refreshBtn').addEventListener('click', () => renderView(currentView));

  // Filters
  document.getElementById('teamFilter').addEventListener('change', renderEmployees);
  document.getElementById('sortBy').addEventListener('change', renderEmployees);
  document.getElementById('sortOrder').addEventListener('change', renderEmployees);

  // Initial load
  checkServerStatus();
  switchView(window.location.pathname === '/me' ? 'me' : 'overview');
});
