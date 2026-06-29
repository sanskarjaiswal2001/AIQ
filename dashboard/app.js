/* ── AI Engineering Efficiency Dashboard ──────────────── */
/* Frontend logic: data fetching, rendering, interactions */

const API_BASE = window.location.origin.replace(/\/$/, '');
let currentView = 'overview';
let allEmployees = [];
let allRules = [];

// ── API helpers ────────────────────────────────────────
async function api(path) {
  const headers = {};
  const apiKey = localStorage.getItem('aiq_api_key');
  if (apiKey) headers['X-API-Key'] = apiKey;
  const res = await fetch(`${API_BASE}${path}`, { headers });
  if (!res.ok) throw new Error(`API ${path} failed: ${res.status}`);
  return res.json();
}

async function apiPost(path, body) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`API POST ${path} failed: ${res.status}`);
  return res.json();
}

// ── Score helpers ──────────────────────────────────────
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
  currentView = view;
  document.querySelectorAll('.nav-item').forEach(el => {
    el.classList.toggle('active', el.dataset.view === view);
  });
  document.querySelectorAll('.view').forEach(el => {
    el.classList.toggle('active', el.id === `view-${view}`);
  });
  const titles = {
    overview: 'Team Overview',
    employees: 'Employees',
    training: 'Training Needs',
    plans: 'Plan Recommendations',
    rules: 'Anti-Pattern Rules',
    me: 'My Dashboard',
  };
  document.getElementById('pageTitle').textContent = titles[view] || view;
  renderView(view);
}

function renderView(view) {
  switch (view) {
    case 'overview': renderOverview(); break;
    case 'employees': renderEmployees(); break;
    case 'training': renderTraining(); break;
    case 'plans': renderPlans(); break;
    case 'rules': renderRules(); break;
    case 'me': renderMe(); break;
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
      ${statCard('Total AI Cost', fmtCost(data.total_cost_usd), 'estimated')}
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
        <span>Team</span><span>People</span><span>Score</span><span>Cost</span><span>Requests</span>
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
          <div class="pr-employee">${esc(p.employee_id)}</div>
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
  return `<div class="stat-card"><div class="stat-label">${label}</div><div class="stat-value">${value}</div><div class="stat-sub">${sub || ''}</div></div>`;
}

function distItem(label, count, cls) {
  return `<div class="score-dist-item ${cls}"><div class="dist-label">${label}</div><div class="dist-count">${count}</div></div>`;
}

function emptyRow(msg) { return `<div style="padding:20px;text-align:center;color:var(--text-dim)">${msg}</div>`; }
function emptyState(msg) { return `<div class="empty-state"><div class="es-icon">📭</div><p>${msg}</p></div>`; }

function planClass(rec) {
  if (rec === 'upgrade') return 'upgrade';
  if (rec === 'maintain' || rec === 'current') return 'maintain';
  if (rec === 'train_first') return 'train';
  return 'review';
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
      <div class="ec-stats">
        <div class="ec-stat"><div class="ec-stat-val">${fmtNum(m.total_requests)}</div><div class="ec-stat-label">Requests</div></div>
        <div class="ec-stat"><div class="ec-stat-val">${fmtNum(m.total_sessions)}</div><div class="ec-stat-label">Sessions</div></div>
        <div class="ec-stat"><div class="ec-stat-val">${fmtNum(m.total_ai_loc)}</div><div class="ec-stat-label">AI LOC</div></div>
        <div class="ec-stat"><div class="ec-stat-val">${fmtCost(m.estimated_cost_usd)}</div><div class="ec-stat-label">Cost</div></div>
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

    const scoreCards = [
      ['Prompt Quality', scores['prompt-quality']],
      ['Session Hygiene', scores['session-hygiene']],
      ['Code Review', scores['code-review']],
      ['Tool Mastery', scores['tool-mastery']],
      ['Context Mgmt', scores['context-management']],
    ].map(([label, val]) => {
      const v = typeof val === 'object' ? val?.score : val;
      return `<div class="modal-score-card"><div class="ms-label">${label}</div><div class="ms-value" style="color:${scoreColor(v || 0)}">${(v || 0).toFixed(0)}</div></div>`;
    }).join('');

    const summaryItems = [
      ['Sessions', summary.total_sessions],
      ['Requests', summary.total_requests],
      ['Workspaces', summary.total_workspaces],
      ['AI LOC', fmtNum(summary.total_ai_loc)],
      ['Input Tokens', fmtNum(summary.total_input_tokens)],
      ['Output Tokens', fmtNum(summary.total_output_tokens)],
      ['Est. Cost', fmtCost(summary.estimated_cost_usd)],
      ['Period', `${fmtDate(emp.period_start)} → ${fmtDate(emp.period_end)}`],
    ].map(([l, v]) => `<div class="modal-summary-item"><div class="msi-label">${l}</div><div class="msi-value">${v}</div></div>`).join('');

    const patternHTML = patterns.length ? patterns.map(p => `
      <div class="modal-pattern ${severityClass(p.severity)}">
        <div class="mp-header">
          <span class="mp-name">${esc(p.rule_name)}</span>
          <span class="mp-stats">${p.occurrences} occurrences · ${p.severity}</span>
        </div>
        <div class="mp-desc">${esc(p.description || '')}</div>
        ${p.examples?.length ? `<div class="mp-examples">Examples: ${p.examples.slice(0, 3).map(e => `<code>${esc(e)}</code>`).join(' ')}</div>` : ''}
      </div>
    `).join('') : '<div style="color:var(--text-dim);padding:12px">No anti-patterns detected 🎉</div>';

    const modelRows = Object.entries(modelUsage).sort((a, b) => (b[1].requests || 0) - (a[1].requests || 0)).map(([model, info]) => `
      <div class="model-row">
        <span>${esc(model)}</span>
        <span>${info.requests || 0}</span>
        <span>${fmtNum(info.input_tokens || 0)}</span>
        <span>${fmtNum(info.output_tokens || 0)}</span>
        <span>${fmtCost(info.cost_usd)}</span>
      </div>
    `).join('');

    const trainingHTML = training.length ? training.map(t => `
      <div class="rec-item">
        <span class="rec-priority ${t.priority}">${t.priority}</span>
        <div class="rec-content">
          <div class="rec-track">${esc(t.track)}</div>
          <div class="rec-module">${esc(t.module)}</div>
        </div>
      </div>
    `).join('') : '<div style="color:var(--text-dim);padding:12px">No training needed 🎉</div>';

    const planHTML = `
      <div class="plan-recommendation-box">
        <div class="prb-action" style="color:${plan.recommendation === 'upgrade' ? 'var(--green)' : plan.recommendation === 'train_first' ? 'var(--yellow)' : 'var(--accent)'}">${esc(plan.action || '—')}</div>
        <div class="prb-reason">${esc(plan.reason || 'Not enough data')}</div>
        <span class="plan-badge ${planClass(plan.recommendation)}">${esc(plan.recommendation || 'N/A')}</span>
      </div>
    `;

    body.innerHTML = `
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
        <h3>Model Usage</h3>
        <div class="modal-model-usage">
          <div class="model-row header"><span>Model</span><span>Requests</span><span>Input</span><span>Output</span><span>Cost</span></div>
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
  } catch (e) {
    console.error('Modal error:', e);
    body.innerHTML = `<div class="empty-state"><div class="es-icon">⚠️</div><h3>Failed to load</h3><p>${esc(e.message)}</p></div>`;
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
      'Prompt Engineering': '✍️',
      'AI Code Review': '🔍',
      'Model & Tool Selection': '🤖',
      'Agent Orchestration': '🔄',
      'Context Engineering': '🧩',
      'Workflow Optimization': '⚙️',
      'Work-Life Balance': '⚖️',
    };

    const container = document.getElementById('trainingMatrix');
    const trackEntries = Object.entries(tracks);
    if (!trackEntries.length) {
      container.innerHTML = emptyState('No training needs detected yet');
      return;
    }
    container.innerHTML = trackEntries.map(([track, modules]) => `
      <div class="matrix-track">
        <h3><span class="track-icon">${trackIcons[track] || '📚'}</span> ${esc(track)}</h3>
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
    const overview = await api('/api/team/overview');
    const recs = overview.plan_recommendations || [];
    const container = document.getElementById('plansList');
    if (!recs.length) {
      container.innerHTML = emptyState('No plan recommendations yet');
      return;
    }
    container.innerHTML = recs.map(r => `
      <div class="plan-card">
        <div class="pc-info">
          <div class="pc-name">${esc(r.employee_id)}</div>
          <div class="pc-reason">${esc(r.reason)}</div>
        </div>
        <span class="plan-badge ${planClass(r.recommendation)}">${esc(r.recommendation)}</span>
      </div>
    `).join('');
  } catch (e) {
    console.error('Plans error:', e);
    showToast('Failed to load plans: ' + e.message);
  } finally {
    showLoading(false);
  }
}

// ── Rules View ─────────────────────────────────────────
async function renderRules() {
  showLoading(true);
  try {
    if (!allRules.length) allRules = await api('/api/rules');
    const container = document.getElementById('rulesList');
    container.innerHTML = allRules.map(r => `
      <div class="rule-card">
        <div class="rc-info">
          <h4>${esc(r.name)}</h4>
          <p>${esc(r.description)}</p>
          <div class="rc-suggestion">💡 ${esc(r.suggestion)}</div>
        </div>
        <div class="rc-meta">
          <span class="rc-group">${esc(r.group)}</span>
          <span class="flag-badge ${severityClass(r.severity)}">${r.severity}</span>
        </div>
      </div>
    `).join('');
  } catch (e) {
    console.error('Rules error:', e);
    showToast('Failed to load rules: ' + e.message);
  } finally {
    showLoading(false);
  }
}

// ── My Dashboard View ───────────────────────────────────
async function renderMe() {
  const container = document.getElementById('meDashboard');
  const apiKey = localStorage.getItem('aiq_api_key') || '';
  if (!apiKey) {
    container.innerHTML = `
      <div class="card card-wide">
        <h3>Connect your AIQ collector</h3>
        <p style="color:var(--text-dim);margin-bottom:16px">Paste the API key created by <code>aiq register</code>. It stays in this browser only and unlocks your personal dashboard.</p>
        <div class="filters">
          <input id="meApiKeyInput" class="filter-select" style="min-width:420px" placeholder="ak_..." />
          <button class="btn btn-secondary" id="saveMeApiKey">Save key</button>
        </div>
      </div>`;
    document.getElementById('saveMeApiKey').addEventListener('click', () => {
      const key = document.getElementById('meApiKeyInput').value.trim();
      if (!key) return showToast('Paste an API key first');
      localStorage.setItem('aiq_api_key', key);
      renderMe();
    });
    return;
  }

  showLoading(true);
  try {
    const emp = await api('/api/me');
    const summary = emp.summary || {};
    const scores = emp.practice_scores || {};
    const recs = emp.recommendations || {};
    const training = recs.training || [];
    const plan = recs.plan || {};
    const patterns = (emp.anti_patterns || []).filter(p => p.triggered);
    const scoreCards = [
      ['Prompt Quality', scores['prompt-quality']],
      ['Session Hygiene', scores['session-hygiene']],
      ['Code Review', scores['code-review']],
      ['Tool Mastery', scores['tool-mastery']],
      ['Context Mgmt', scores['context-management']],
    ].map(([label, val]) => {
      const v = typeof val === 'object' ? val?.score : val;
      return `<div class="modal-score-card"><div class="ms-label">${label}</div><div class="ms-value" style="color:${scoreColor(v || 0)}">${(v || 0).toFixed(0)}</div></div>`;
    }).join('');
    const trainingHTML = training.length ? training.map(t => `
      <div class="rec-item"><span class="rec-priority ${t.priority}">${t.priority}</span><div class="rec-content"><div class="rec-track">${esc(t.track)}</div><div class="rec-module">${esc(t.module)}</div></div></div>
    `).join('') : '<div style="color:var(--text-dim);padding:12px">No training needed 🎉</div>';
    const patternHTML = patterns.length ? patterns.slice(0, 8).map(p => `
      <div class="modal-pattern ${severityClass(p.severity)}"><div class="mp-header"><span class="mp-name">${esc(p.rule_name)}</span><span class="mp-stats">${p.occurrences} · ${p.severity}</span></div><div class="mp-desc">${esc(p.description || '')}</div></div>
    `).join('') : '<div style="color:var(--text-dim);padding:12px">No anti-patterns detected 🎉</div>';

    container.innerHTML = `
      <div class="stat-cards">
        ${statCard('Requests', fmtNum(summary.total_requests), 'AI interactions')}
        ${statCard('Sessions', fmtNum(summary.total_sessions), 'logged sessions')}
        ${statCard('AI Cost', fmtCost(summary.estimated_cost_usd), 'estimated')}
        ${statCard('AI LOC', fmtNum(summary.total_ai_loc), 'generated lines')}
      </div>
      <div class="card-grid">
        <div class="card card-wide"><h3>Your Practice Scores</h3><div class="modal-scores">${scoreCards}</div></div>
        <div class="card card-wide"><h3>Your Training Recommendations</h3><div class="modal-recommendations">${trainingHTML}</div></div>
        <div class="card card-wide"><h3>Your Plan Recommendation</h3><div class="plan-recommendation-box"><div class="prb-action">${esc(plan.action || '—')}</div><div class="prb-reason">${esc(plan.reason || 'Not enough data')}</div><span class="plan-badge ${planClass(plan.recommendation)}">${esc(plan.recommendation || 'N/A')}</span></div></div>
        <div class="card card-wide"><h3>Your Anti-Patterns (${patterns.length})</h3><div class="modal-patterns">${patternHTML}</div></div>
      </div>
      <button class="btn btn-secondary" id="clearMeApiKey" style="margin-top:18px">Clear saved API key</button>
    `;
    document.getElementById('clearMeApiKey').addEventListener('click', () => {
      localStorage.removeItem('aiq_api_key');
      renderMe();
    });
  } catch (e) {
    container.innerHTML = `<div class="empty-state"><div class="es-icon">⚠️</div><h3>Could not load personal dashboard</h3><p>${esc(e.message)}</p><button class="btn btn-secondary" id="clearBadApiKey">Clear key</button></div>`;
    document.getElementById('clearBadApiKey').addEventListener('click', () => {
      localStorage.removeItem('aiq_api_key');
      renderMe();
    });
  } finally {
    showLoading(false);
  }
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
  t.style.cssText = 'position:fixed;bottom:20px;right:20px;background:var(--bg-card);border:1px solid var(--red);border-radius:8px;padding:14px 20px;z-index:2000;font-size:13px;max-width:400px';
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
  document.getElementById('refreshBtn').addEventListener('click', () => renderView(currentView));

  // Filters
  document.getElementById('teamFilter').addEventListener('change', renderEmployees);
  document.getElementById('sortBy').addEventListener('change', renderEmployees);
  document.getElementById('sortOrder').addEventListener('change', renderEmployees);

  // Initial load
  checkServerStatus();
  switchView(window.location.pathname === '/me' ? 'me' : 'overview');
});
