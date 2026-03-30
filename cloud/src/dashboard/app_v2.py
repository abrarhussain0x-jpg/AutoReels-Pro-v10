"""
dashboard_v2.py v10.0 — Real-Time Dashboard (full v10 feature set).

Sections:
  /                → Live pipeline status
  /analytics       → Engagement charts (Chart.js)
  /ab-testing      → Angle win rates + hook phrase leaderboard
  /accounts        → Per-account upload counts + rate limit status
  /velocity        → Live velocity curves (sparklines)
  /schedule        → Optimal time windows grid (heatmap)
  /failed          → Dead letter queue viewer with retry button

Auto-refreshes every 30s via SSE. Dark theme, mobile-responsive.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# ── Inline HTML Template ────────────────────────────────────────────────────

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AUTO-REELS PRO v10 Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  :root {
    --bg: #0d0d0d; --surface: #1a1a1a; --surface2: #252525;
    --accent: #FFE600; --accent2: #00d4ff; --text: #e0e0e0;
    --text2: #888; --success: #00c853; --danger: #ff3d00;
    --warning: #ff9100; --border: #333;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: 'Segoe UI', sans-serif; }
  nav { background: var(--surface); border-bottom: 1px solid var(--border); padding: 12px 24px;
        display: flex; gap: 20px; align-items: center; position: sticky; top: 0; z-index: 99; }
  nav h1 { color: var(--accent); font-size: 1.1rem; font-weight: 700; margin-right: 20px; }
  nav a { color: var(--text2); text-decoration: none; font-size: 0.85rem; padding: 6px 12px;
          border-radius: 6px; transition: all 0.2s; }
  nav a:hover, nav a.active { background: var(--surface2); color: var(--accent); }
  .container { max-width: 1400px; margin: 0 auto; padding: 20px; }
  .grid { display: grid; gap: 16px; }
  .grid-2 { grid-template-columns: repeat(2, 1fr); }
  .grid-3 { grid-template-columns: repeat(3, 1fr); }
  .grid-4 { grid-template-columns: repeat(4, 1fr); }
  .card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
          padding: 20px; }
  .card h3 { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 1px;
             color: var(--text2); margin-bottom: 8px; }
  .metric { font-size: 2rem; font-weight: 700; color: var(--accent); }
  .metric-sub { font-size: 0.8rem; color: var(--text2); margin-top: 4px; }
  .section { margin-bottom: 32px; }
  .section h2 { font-size: 1rem; color: var(--accent2); margin-bottom: 16px;
                padding-bottom: 8px; border-bottom: 1px solid var(--border); }
  table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
  th { text-align: left; padding: 10px 12px; background: var(--surface2);
       color: var(--text2); font-weight: 600; text-transform: uppercase;
       font-size: 0.7rem; letter-spacing: 0.5px; }
  td { padding: 9px 12px; border-bottom: 1px solid var(--border); color: var(--text); }
  tr:hover td { background: var(--surface2); }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 0.7rem; }
  .badge-success { background: rgba(0,200,83,.2); color: var(--success); }
  .badge-danger  { background: rgba(255,61,0,.2);  color: var(--danger); }
  .badge-warn    { background: rgba(255,145,0,.2); color: var(--warning); }
  .badge-neutral { background: rgba(136,136,136,.2); color: var(--text2); }
  .btn { padding: 6px 16px; border-radius: 6px; border: none; cursor: pointer;
         font-size: 0.8rem; font-weight: 600; }
  .btn-primary { background: var(--accent); color: #000; }
  .btn-danger { background: var(--danger); color: #fff; }
  .refresh-indicator { margin-left: auto; font-size: 0.75rem; color: var(--text2); }
  .sparkline { width: 100%; height: 60px; }
  .viral-badge { color: var(--accent); font-size: 1.2rem; }
  .heatmap-grid { display: grid; grid-template-columns: 80px repeat(7, 1fr); gap: 2px; }
  .heatmap-cell { height: 36px; display: flex; align-items: center; justify-content: center;
                  font-size: 0.7rem; border-radius: 4px; }
  .hidden { display: none; }
  canvas { max-height: 300px; }
  @media (max-width: 768px) { .grid-2,.grid-3,.grid-4 { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<nav>
  <h1>🎬 AUTO-REELS v10</h1>
  <a href="#" class="active" onclick="showSection('status')">Pipeline</a>
  <a href="#" onclick="showSection('analytics')">Analytics</a>
  <a href="#" onclick="showSection('abtesting')">A/B Testing</a>
  <a href="#" onclick="showSection('accounts')">Accounts</a>
  <a href="#" onclick="showSection('velocity')">Velocity</a>
  <a href="#" onclick="showSection('schedule')">Schedule</a>
  <a href="#" onclick="showSection('failed')">Failed</a>
  <span class="refresh-indicator" id="refresh-timer">Refreshing in 30s</span>
</nav>

<div class="container">

<!-- STATUS SECTION -->
<div id="section-status" class="section">
  <h2>⚡ Live Pipeline Status</h2>
  <div class="grid grid-4" id="status-cards">
    <div class="card"><h3>Uploads Today</h3><div class="metric" id="stat-uploads">—</div></div>
    <div class="card"><h3>Daily Limit</h3><div class="metric" id="stat-limit">—</div></div>
    <div class="card"><h3>Videos Processed</h3><div class="metric" id="stat-videos">—</div></div>
    <div class="card"><h3>Active Platform</h3><div class="metric" id="stat-platform">—</div></div>
  </div>
  <div class="card" style="margin-top:16px;">
    <h3>Recent Activity</h3>
    <table id="recent-table">
      <thead><tr><th>Time</th><th>Platform</th><th>Video</th><th>Clip</th><th>Status</th></tr></thead>
      <tbody id="recent-tbody"><tr><td colspan="5" style="color:var(--text2)">Loading...</td></tr></tbody>
    </table>
  </div>
</div>

<!-- ANALYTICS SECTION -->
<div id="section-analytics" class="section hidden">
  <h2>📈 Engagement Analytics</h2>
  <div class="grid grid-2">
    <div class="card"><h3>Daily Views (last 14 days)</h3><canvas id="views-chart"></canvas></div>
    <div class="card"><h3>Platform Breakdown</h3><canvas id="platform-chart"></canvas></div>
  </div>
</div>

<!-- A/B TESTING SECTION -->
<div id="section-abtesting" class="section hidden">
  <h2>🧪 A/B Testing</h2>
  <div class="grid grid-2">
    <div class="card">
      <h3>Angle Win Rates</h3>
      <table id="angle-table">
        <thead><tr><th>Angle</th><th>Platform</th><th>Wins</th><th>Trials</th><th>Weight</th></tr></thead>
        <tbody id="angle-tbody"><tr><td colspan="5">Loading...</td></tr></tbody>
      </table>
    </div>
    <div class="card">
      <h3>Hook Phrase Leaderboard</h3>
      <table id="hook-table">
        <thead><tr><th>Phrase</th><th>Platform</th><th>Wins</th><th>Retention</th><th>Weight</th></tr></thead>
        <tbody id="hook-tbody"><tr><td colspan="5">Loading...</td></tr></tbody>
      </table>
    </div>
  </div>
</div>

<!-- ACCOUNTS SECTION -->
<div id="section-accounts" class="section hidden">
  <h2>👥 Account Rotation</h2>
  <div class="card">
    <table id="accounts-table">
      <thead><tr><th>Platform</th><th>Account</th><th>Uploads</th><th>Limit</th><th>Failures</th><th>Circuit</th></tr></thead>
      <tbody id="accounts-tbody"><tr><td colspan="6">Loading...</td></tr></tbody>
    </table>
  </div>
</div>

<!-- VELOCITY SECTION -->
<div id="section-velocity" class="section hidden">
  <h2>🚀 Engagement Velocity</h2>
  <div id="velocity-cards" class="grid grid-2"></div>
</div>

<!-- SCHEDULE SECTION -->
<div id="section-schedule" class="section hidden">
  <h2>🕐 Optimal Posting Schedule</h2>
  <div id="schedule-content" class="card"><p style="color:var(--text2)">Loading...</p></div>
</div>

<!-- FAILED SECTION -->
<div id="section-failed" class="section hidden">
  <h2>💀 Dead Letter Queue</h2>
  <div class="card">
    <button class="btn btn-primary" onclick="retryFailed()" style="margin-bottom:12px">
      🔄 Retry All
    </button>
    <table id="failed-table">
      <thead><tr><th>Platform</th><th>Video</th><th>Clip</th><th>Error</th><th>Attempts</th><th>Age</th><th>Status</th></tr></thead>
      <tbody id="failed-tbody"><tr><td colspan="7">Loading...</td></tr></tbody>
    </table>
  </div>
</div>

</div><!-- /container -->

<script>
let activeSection = 'status';
let refreshCountdown = 30;
let charts = {};

function showSection(name) {
  document.querySelectorAll('.section').forEach(s => s.classList.add('hidden'));
  document.getElementById('section-' + name).classList.remove('hidden');
  document.querySelectorAll('nav a').forEach((a, i) => {
    a.classList.toggle('active', a.getAttribute('onclick')?.includes(name));
  });
  activeSection = name;
  loadSection(name);
}

async function loadSection(name) {
  try {
    const data = await fetch('/api/' + name).then(r => r.json());
    renderSection(name, data);
  } catch(e) {
    console.error('Load failed:', e);
  }
}

function renderSection(name, data) {
  if (name === 'status') renderStatus(data);
  else if (name === 'analytics') renderAnalytics(data);
  else if (name === 'abtesting') renderABTesting(data);
  else if (name === 'accounts') renderAccounts(data);
  else if (name === 'velocity') renderVelocity(data);
  else if (name === 'schedule') renderSchedule(data);
  else if (name === 'failed') renderFailed(data);
}

function renderStatus(d) {
  document.getElementById('stat-uploads').textContent = d.uploads_today ?? '—';
  document.getElementById('stat-limit').textContent = d.daily_limit ?? '—';
  document.getElementById('stat-videos').textContent = d.videos_processed ?? '—';
  document.getElementById('stat-platform').textContent = d.active_platforms?.join(', ') ?? '—';
  const tbody = document.getElementById('recent-tbody');
  tbody.innerHTML = (d.recent_uploads || []).map(u => `
    <tr>
      <td>${new Date(u.uploaded_at*1000).toLocaleTimeString()}</td>
      <td>${u.platform}</td>
      <td title="${u.title}">${(u.title||'').substring(0,30)}</td>
      <td>#${u.clip_num}</td>
      <td><span class="badge badge-success">✓ Uploaded</span></td>
    </tr>
  `).join('') || '<tr><td colspan="5" style="color:var(--text2)">No recent uploads</td></tr>';
}

function renderAnalytics(d) {
  if (charts['views']) charts['views'].destroy();
  if (charts['platform']) charts['platform'].destroy();
  const days = d.daily_views || [];
  charts['views'] = new Chart(document.getElementById('views-chart'), {
    type: 'bar',
    data: { labels: days.map(x=>x.date), datasets: [{
      label: 'Views', data: days.map(x=>x.views),
      backgroundColor: '#FFE60088', borderColor: '#FFE600', borderWidth: 1
    }]},
    options: { plugins:{legend:{display:false}}, scales:{
      x:{ticks:{color:'#888'}}, y:{ticks:{color:'#888'}, grid:{color:'#333'}}
    }}
  });
  const platforms = d.platform_breakdown || {};
  charts['platform'] = new Chart(document.getElementById('platform-chart'), {
    type: 'doughnut',
    data: {
      labels: Object.keys(platforms),
      datasets: [{data: Object.values(platforms),
        backgroundColor: ['#FFE600','#00d4ff','#ff6b6b','#51cf66','#cc5de8']}]
    },
    options: { plugins:{legend:{labels:{color:'#e0e0e0'}}} }
  });
}

function renderABTesting(d) {
  document.getElementById('angle-tbody').innerHTML = (d.angles || []).map(a => `
    <tr>
      <td>${a.angle}</td><td>${a.platform}</td>
      <td>${a.wins}</td><td>${a.trials}</td>
      <td><span class="badge badge-neutral">${(a.weight||0).toFixed(3)}</span></td>
    </tr>
  `).join('') || '<tr><td colspan="5" style="color:var(--text2)">No data</td></tr>';

  document.getElementById('hook-tbody').innerHTML = (d.hooks || []).map(h => `
    <tr>
      <td style="font-family:monospace">${h.phrase}</td>
      <td>${h.platform}</td><td>${h.wins}/${h.uses}</td>
      <td>${((h.avg_retention||0)*100).toFixed(1)}%</td>
      <td>${(h.weight||0).toFixed(3)}</td>
    </tr>
  `).join('') || '<tr><td colspan="5" style="color:var(--text2)">No data</td></tr>';
}

function renderAccounts(d) {
  document.getElementById('accounts-tbody').innerHTML = (d.accounts || []).map(a => `
    <tr>
      <td>${a.platform}</td><td style="font-family:monospace">${a.account_id}</td>
      <td>${a.uploads}</td><td>${a.limit}</td><td>${a.failures}</td>
      <td><span class="badge ${a.circuit_open?'badge-danger':'badge-success'}">
        ${a.circuit_open ? '🔴 OPEN' : '✅ OK'}</span></td>
    </tr>
  `).join('') || '<tr><td colspan="6" style="color:var(--text2)">No accounts</td></tr>';
}

function renderVelocity(d) {
  const container = document.getElementById('velocity-cards');
  container.innerHTML = '';
  (d.uploads || []).forEach(u => {
    const card = document.createElement('div');
    card.className = 'card';
    card.innerHTML = `
      <h3>${u.is_viral?'🚀 VIRAL':'📊'} ${u.platform} | ${u.niche}</h3>
      <div style="font-size:.75rem;color:var(--text2);margin-bottom:8px">
        ${u.max_views?.toLocaleString()} views | Peak: ${Math.round(u.peak_vph)} vph
      </div>
      <canvas id="spark-${u.upload_id}" class="sparkline"></canvas>
    `;
    container.appendChild(card);
    setTimeout(() => {
      const ctx = document.getElementById('spark-' + u.upload_id);
      if(!ctx) return;
      new Chart(ctx, {
        type:'line',
        data:{
          labels: (u.points||[]).map(p=>p.hours_since.toFixed(1)+'h'),
          datasets:[{
            data:(u.points||[]).map(p=>p.views),
            borderColor:'#FFE600', backgroundColor:'#FFE60020',
            fill:true, tension:0.4, pointRadius:3
          }]
        },
        options:{plugins:{legend:{display:false}},scales:{
          x:{ticks:{color:'#888',font:{size:9}}},
          y:{ticks:{color:'#888',font:{size:9}},grid:{color:'#333'}}
        }}
      });
    }, 100);
  });
  if(!(d.uploads||[]).length)
    container.innerHTML = '<div class="card"><p style="color:var(--text2)">No velocity data yet.</p></div>';
}

function renderSchedule(d) {
  const el = document.getElementById('schedule-content');
  if(!(d.windows||[]).length) {
    el.innerHTML = '<p style="color:var(--text2)">No schedule data yet.</p>';
    return;
  }
  const days = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
  let html = '<table><thead><tr><th>Niche / Platform</th>';
  days.forEach(d => html += `<th>${d}</th>`);
  html += '</tr></thead><tbody>';
  (d.windows||[]).forEach(g => {
    html += `<tr><td><strong>${g.niche}</strong> / ${g.platform}</td>`;
    days.forEach((_, di) => {
      const slot = (g.slots||[]).find(s => s.weekday === di);
      if(slot) {
        const alpha = Math.round(slot.weight * 200);
        html += `<td style="background:rgba(255,230,0,${slot.weight.toFixed(2)});color:#000;border-radius:4px;text-align:center">${slot.hour}:00</td>`;
      } else {
        html += '<td style="color:var(--text2);text-align:center">—</td>';
      }
    });
    html += '</tr>';
  });
  html += '</tbody></table>';
  el.innerHTML = html;
}

function renderFailed(d) {
  document.getElementById('failed-tbody').innerHTML = (d.items || []).map(f => `
    <tr>
      <td>${f.platform}</td>
      <td style="font-family:monospace">${(f.video_id||'').substring(0,16)}</td>
      <td>#${f.clip_num}</td>
      <td><span class="badge badge-danger">${f.error_type}</span> ${(f.error_message||'').substring(0,40)}</td>
      <td>${f.attempts}</td>
      <td>${Math.round((Date.now()/1000-f.first_failed_at)/3600)}h ago</td>
      <td><span class="badge ${f.resolved?'badge-success':'badge-warn'}">${f.resolved?'✓ Resolved':'Pending'}</span></td>
    </tr>
  `).join('') || '<tr><td colspan="7" style="color:var(--success)">Queue is empty 🎉</td></tr>';
}

async function retryFailed() {
  try {
    await fetch('/api/retry-failed', {method:'POST'});
    loadSection('failed');
  } catch(e) { alert('Retry failed: ' + e); }
}

// Auto-refresh
setInterval(() => {
  refreshCountdown--;
  document.getElementById('refresh-timer').textContent = `Refreshing in ${refreshCountdown}s`;
  if(refreshCountdown <= 0) {
    refreshCountdown = 30;
    loadSection(activeSection);
  }
}, 1000);

// Initial load
loadSection('status');
</script>
</body>
</html>"""


def create_dashboard_app(
    analytics=None,
    ab_engine=None,
    hook_optimizer=None,
    account_rotator=None,
    velocity_tracker=None,
    time_optimizer=None,
    retry_engine=None,
    config: Optional[dict] = None,
) -> Any:
    """
    Create and return a Flask app with all dashboard endpoints.
    Call app.run(port=8888) to start.
    """
    try:
        from flask import Flask, jsonify, request, Response
    except ImportError:
        log.error("[Dashboard] Flask not installed — dashboard unavailable")
        return None

    app = Flask(__name__)
    cfg = config or {}

    @app.route("/")
    def index():
        return Response(DASHBOARD_HTML, mimetype="text/html")

    @app.route("/api/status")
    def api_status():
        data = {
            "uploads_today": 0,
            "daily_limit": cfg.get("daily_upload_limit", 5),
            "videos_processed": 0,
            "active_platforms": [],
            "recent_uploads": [],
        }
        if analytics:
            try:
                today_uploads = analytics.uploads_today()
                data["uploads_today"] = today_uploads
                recent = analytics.recent_uploads(limit=20)
                data["recent_uploads"] = recent
                data["videos_processed"] = len(set(u.get("video_id") for u in recent))
                data["active_platforms"] = list(set(u.get("platform") for u in recent))
            except Exception as exc:
                log.debug("[Dashboard] status error: %s", exc)
        return jsonify(data)

    @app.route("/api/analytics")
    def api_analytics():
        data = {"daily_views": [], "platform_breakdown": {}}
        if analytics:
            try:
                data["daily_views"] = analytics.daily_views(days=14)
                data["platform_breakdown"] = analytics.platform_breakdown()
            except Exception as exc:
                log.debug("[Dashboard] analytics error: %s", exc)
        return jsonify(data)

    @app.route("/api/abtesting")
    def api_abtesting():
        data = {"angles": [], "hooks": []}
        if ab_engine:
            try:
                data["angles"] = ab_engine.get_all_results()
            except Exception as exc:
                log.debug("[Dashboard] ab_engine error: %s", exc)
        if hook_optimizer:
            try:
                data["hooks"] = hook_optimizer.get_top_hooks(limit=20)
            except Exception as exc:
                log.debug("[Dashboard] hook_optimizer error: %s", exc)
        return jsonify(data)

    @app.route("/api/accounts")
    def api_accounts():
        data = {"accounts": []}
        if account_rotator:
            try:
                data["accounts"] = account_rotator.get_all_account_status()
            except Exception as exc:
                log.debug("[Dashboard] account_rotator error: %s", exc)
        return jsonify(data)

    @app.route("/api/velocity")
    def api_velocity():
        data = {"uploads": []}
        if velocity_tracker:
            try:
                uploads = velocity_tracker.recent_velocities(limit=10)
                for u in uploads:
                    u["points"] = [
                        {"hours_since": p.hours_since, "views": p.views,
                         "velocity_vph": p.velocity_vph}
                        for p in u.get("points", [])
                    ]
                data["uploads"] = uploads
            except Exception as exc:
                log.debug("[Dashboard] velocity error: %s", exc)
        return jsonify(data)

    @app.route("/api/schedule")
    def api_schedule():
        data = {"windows": []}
        if time_optimizer:
            try:
                niches = cfg.get("schedule_niches", ["movie", "anime"])
                platforms = ["facebook", "tiktok", "instagram"]
                windows = []
                for niche in niches:
                    for platform in platforms:
                        slots = time_optimizer.schedule_recommendation(niche, platform, n=7)
                        windows.append({
                            "niche": niche,
                            "platform": platform,
                            "slots": [{"weekday": s.weekday, "hour": s.hour, "weight": s.weight}
                                      for s in slots],
                        })
                data["windows"] = windows
            except Exception as exc:
                log.debug("[Dashboard] schedule error: %s", exc)
        return jsonify(data)

    @app.route("/api/failed")
    def api_failed():
        data = {"items": []}
        if retry_engine:
            try:
                data["items"] = retry_engine.get_failed_items()
            except Exception as exc:
                log.debug("[Dashboard] retry_engine error: %s", exc)
        return jsonify(data)

    @app.route("/api/retry-failed", methods=["POST"])
    def api_retry_failed():
        if retry_engine:
            try:
                count = retry_engine.retry_dead_letter_queue({})
                return jsonify({"retried": count})
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500
        return jsonify({"error": "retry engine not configured"}), 404

    return app
