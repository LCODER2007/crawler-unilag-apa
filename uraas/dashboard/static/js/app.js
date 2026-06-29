/**
 * URAAS — Dashboard Core Logic
 * Handles real-time updates via Socket.IO, analytics visualization, and crawler controls.
 */

const socket = io();
let archiveData = {}, charts = {}, networkEdgeData = null;
let yearDataCache = null, yearStackedCache = null, facultyDataCache = null;
let trendsData = null, keywordData = null;
let analyticsLoaded = false, kwLoaded = false, trendsLoaded = false;
let currentAtab = 'overview';

// Global Color Palette
const COLORS = [
  '#3b82f6', '#22c55e', '#f59e0b', '#ef4444', '#8b5cf6', 
  '#06b6d4', '#f97316', '#14b8a6', '#6366f1', '#84cc16', 
  '#e11d48', '#0ea5e9', '#a855f7', '#ec4899', '#64748b'
];

Chart.defaults.color = '#64748b';
Chart.defaults.borderColor = 'rgba(255, 255, 255, 0.04)';
Chart.defaults.font.family = "'Inter', sans-serif";

/**
 * UI Helpers
 */
const $ = (id) => document.getElementById(id);

const esc = (s) => String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

function safeFetch(url, ok, err) {
  return fetch(url, { cache: 'no-store' })
    .then(r => {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    })
    .then(ok)
    .catch(e => {
      console.error(url, e);
      if (err) err(e);
    });
}

function destroyChart(id) {
  if (charts[id]) {
    try { charts[id].destroy(); } catch (e) { }
    delete charts[id];
  }
}

/**
 * Theme Management
 */
function toggleTheme() {
  const d = document.documentElement;
  const dark = d.getAttribute('data-theme') === 'dark';
  d.setAttribute('data-theme', dark ? 'light' : 'dark');
  $('icon-moon').classList.toggle('hidden', !dark);
  $('icon-sun').classList.toggle('hidden', dark);
  Chart.defaults.color = dark ? '#475569' : '#64748b';
  Object.values(charts).forEach(c => {
    try { c.update(); } catch (e) { }
  });
  localStorage.setItem('uraas-theme', dark ? 'light' : 'dark');
}

/**
 * Toast Notifications
 */
function showToast(msg, type = 'info', ms = 4000) {
  const c = $('toast-container');
  if (!c) return;
  const d = document.createElement('div');
  const icons = { success: '✓', error: '✕', info: 'ℹ', warning: '⚠' };
  d.className = `toast toast-${type}`;
  d.innerHTML = `<span style="font-size:16px; font-weight:bold">${icons[type] || ''}</span><span>${esc(msg)}</span>`;
  c.appendChild(d);
  setTimeout(() => {
    d.style.opacity = '0';
    d.style.transform = 'translateX(20px)';
    setTimeout(() => d.remove(), 350);
  }, ms);
}

// Map legacy 'toast' name
const toast = showToast;

/**
 * Tab Management
 */
function switchTab(name, btn) {
  document.querySelectorAll('.tab-content').forEach(e => e.classList.add('hidden'));
  document.querySelectorAll('.tab-btn[id^="tab-btn-"]').forEach(e => e.classList.remove('active'));
  const target = $('tab-' + name);
  if (target) target.classList.remove('hidden');
  if (btn) btn.classList.add('active');
  else {
    const b = $('tab-btn-' + name);
    if (b) b.classList.add('active');
  }
  
  if (name === 'analytics' && !analyticsLoaded) {
    analyticsLoaded = true;
    switchAtab('overview', $('atab-btn-overview'));
  }
  if (name === 'archive') renderTree(archiveData);
  if (name === 'search') loadSearchFaculties();
  if (name === 'comparator') loadCompareDDs();
}

function switchAtab(name, btn) {
  currentAtab = name;
  document.querySelectorAll('.atab-content').forEach(e => e.classList.add('hidden'));
  document.querySelectorAll('[id^="atab-btn-"]').forEach(e => e.classList.remove('active'));
  const t = $('atab-' + name);
  if (t) t.classList.remove('hidden');
  if (btn) btn.classList.add('active');
  
  if (name === 'overview') loadAnalyticsOverview();
  if (name === 'au') loadAlignmentTab();
  if (name === 'collab') loadCollabTab();
  if (name === 'compare') loadCompareDDs();
  if (name === 'language') loadLanguageTab();
  if (name === 'special') loadSpecialTab();
  if (name === 'staff') loadStaffDirectory();
  if (name === 'network') { /* Network tab handled by interactions */ }
}

/**
 * Analytics Data Loading
 */
function getInstitutionParam() {
  const sel = $('global-institution-select');
  return sel && sel.value ? '?institution=' + encodeURIComponent(sel.value) : '';
}

function withInst(url) {
  const inst = getInstitutionParam();
  if (!inst) return url;
  return url.includes('?') ? url + inst.replace('?', '&') : url + inst;
}

function applyGlobalInstitutionFilter() {
  invalidateCaches();
  const inst = getInstitutionParam();
  const specCsv = $('sco-csv-btn'); if (specCsv) specCsv.href = '/api/analytics/special-collections/export.csv' + inst;
  
  if (currentAtab === 'overview') loadAnalyticsOverview();
  else if (currentAtab === 'au') { loadAlignmentTab(); }
  else if (currentAtab === 'collab') { loadCollabTab(); }
  else if (currentAtab === 'language') { loadLanguageTab(); }
  else if (currentAtab === 'special') { loadSpecialTab(); }
  else if (currentAtab === 'staff') { loadStaffDirectory(); }
}

function invalidateCaches() {
  yearDataCache = yearStackedCache = facultyDataCache = null;
}

function loadAnalyticsOverview() {
  // "Special Collections Overview" tab — SC-focused analytics redesign.
  $('sco-loading').classList.remove('hidden');
  $('sco-content').classList.add('hidden');
  safeFetch(withInst('/api/analytics/special-collections/overview'), data => {
    $('sco-loading').classList.add('hidden');
    $('sco-content').classList.remove('hidden');

    const k = data.kpis || {};
    // ── KPI strip ──────────────────────────────────────────────────────
    $('sco-kpis').innerHTML = `
      <div class="surface rounded-xl p-4 stat-card">
        <p class="section-label">Special Items</p>
        <p class="text-3xl font-bold" style="color:var(--accent)">${k.total_items || 0}</p>
        <p class="text-xs mt-1 text-muted">${k.pct_of_repo || 0}% of repository</p>
      </div>
      <div class="surface rounded-xl p-4 stat-card">
        <p class="section-label">Themes Represented</p>
        <p class="text-3xl font-bold" style="color:var(--success)">${k.themes_represented || 0}<span class="text-base text-muted">/8</span></p>
      </div>
      <div class="surface rounded-xl p-4 stat-card">
        <p class="section-label">Total Citations</p>
        <p class="text-3xl font-bold" style="color:#8b5cf6">${(k.total_citations || 0).toLocaleString()}</p>
      </div>
      <div class="surface rounded-xl p-4 stat-card">
        <p class="section-label">Intra-African Share</p>
        <p class="text-3xl font-bold" style="color:var(--warning)">${k.intra_african_pct || 0}%</p>
      </div>`;

    // ── Thematic composition (doughnut) ────────────────────────────────
    const themes = (data.themes || []).filter(t => t.count > 0);
    destroyChart('sco-themes');
    if (themes.length) {
      charts['sco-themes'] = new Chart($('sco-themes-chart'), {
        type: 'doughnut',
        data: {
          labels: themes.map(t => t.category),
          datasets: [{
            data: themes.map(t => t.count),
            backgroundColor: themes.map((_, i) => COLORS[i % COLORS.length]),
            borderWidth: 0,
          }],
        },
        options: {
          responsive: true, maintainAspectRatio: false, cutout: '58%',
          plugins: { legend: { position: 'right', labels: { boxWidth: 10, font: { size: 10 } } } },
        },
      });
    }

    // ── Theme co-occurrence (D3 chord) ─────────────────────────────────
    renderScChord(data.co_occurrence || { labels: [], matrix: [] });

    // ── Knowledge sovereignty ──────────────────────────────────────────
    $('sco-intra-african').textContent = `${k.intra_african_pct || 0}% intra-African`;
    $('sco-countries').innerHTML = scHbar(data.countries, 'name', 'papers', '#22c55e');

    // ── SDG alignment (horizontal bar) ─────────────────────────────────
    const sdgs = data.sdgs || [];
    destroyChart('sco-sdg');
    if (sdgs.length) {
      charts['sco-sdg'] = new Chart($('sco-sdg-chart'), {
        type: 'bar',
        data: {
          labels: sdgs.map(s => 'SDG ' + s.sdg),
          datasets: [{
            label: 'Works', data: sdgs.map(s => s.count),
            backgroundColor: '#0ea5e9', borderRadius: 4,
          }],
        },
        options: {
          indexAxis: 'y', responsive: true, maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: { x: { beginAtZero: true, ticks: { precision: 0 } } },
        },
      });
    }

    // ── Custodians ──────────────────────────────────────────────────────
    $('sco-custodians').innerHTML = scHbar(data.custodians, 'institution', 'count', '#f59e0b');

    // ── Cultural lexicon ────────────────────────────────────────────────
    const kws = data.keywords || [];
    if (kws.length) {
      const maxKw = Math.max(1, ...kws.map(w => w.count));
      $('sco-lexicon').innerHTML = kws.map(w => {
        const size = 10 + Math.round((w.count / maxKw) * 8);
        const op = 0.45 + (w.count / maxKw) * 0.55;
        return `<span class="chip" style="font-size:${size}px;background:var(--accent-10);color:var(--accent);opacity:${op.toFixed(2)}">${esc(w.word)} <span style="opacity:0.6">${w.count}</span></span>`;
      }).join('');
    } else {
      $('sco-lexicon').innerHTML = SC_EMPTY;
    }

    // ── Most influential works ──────────────────────────────────────────
    const inf = data.influential || [];
    const allZeroCites = inf.length > 0 && inf.every(p => !p.citations);
    $('sco-influential').innerHTML = inf.length ? [
      allZeroCites ? `<p class="text-[10px] text-muted italic mb-2 px-1">Citation counts not yet fetched — ranked by SC relevance score. Run <strong>Update Citations</strong> in the Crawler tab to populate.</p>` : '',
      ...inf.map((p, i) => `
      <div class="row-hover p-2.5 rounded-lg cursor-pointer flex items-center gap-3" onclick="openPaperModal(${p.id})">
        <span class="text-sm font-bold text-muted" style="min-width:1.5rem">${i + 1}</span>
        <div class="flex-1 min-w-0">
          <p class="text-sm font-medium truncate">${esc(p.title)}</p>
          <div class="flex gap-1 mt-1 flex-wrap">
            ${(p.categories || []).slice(0, 3).map(c => `<span class="chip text-[9px] py-0.5 px-1.5">${esc(c)}</span>`).join('')}
          </div>
        </div>
        <span class="chip text-[10px] py-0.5 px-2 flex-shrink-0" style="background:#8b5cf618;color:#8b5cf6">${p.citations || 0} cites</span>
      </div>`)
    ].join('') : SC_EMPTY;
  });

  // ── PID Coverage (Africa PID Alliance) ─────────────────────────────
  safeFetch(withInst('/api/analytics/pid-coverage'), pid => {
    const fmt = (pct, n, label) =>
      `${pct}%<title>${n} of ${pid.total} ${label}</title>`;
    if ($('pid-doi-pct'))   { $('pid-doi-pct').textContent   = pid.doi_pct + '%';   $('pid-doi-n').textContent   = pid.doi_count + ' items'; }
    if ($('pid-orcid-pct')) { $('pid-orcid-pct').textContent = pid.orcid_pct + '%'; $('pid-orcid-n').textContent = pid.orcid_count + ' items'; }
    if ($('pid-ark-pct'))   { $('pid-ark-pct').textContent   = pid.ark_pct + '%';   $('pid-ark-n').textContent   = pid.ark_count + ' items'; }
    if ($('pid-ror-pct'))   { $('pid-ror-pct').textContent   = pid.ror_pct + '%';   $('pid-ror-n').textContent   = pid.ror_count + ' items'; }
    if ($('pid-total'))     { $('pid-total').textContent = pid.total; }
  });

  // ── Knowledge Repatriation Index ───────────────────────────────────
  safeFetch(withInst('/api/analytics/knowledge-repatriation'), d => {
    if ($('kri-score'))          { $('kri-score').textContent = d.score; }
    if ($('kri-interpretation')) { $('kri-interpretation').textContent = d.interpretation || ''; }
    if ($('kri-total'))          { $('kri-total').textContent = (d.total || 0).toLocaleString(); }
    if ($('kri-trend')) {
      const t = d.trend || 0;
      $('kri-trend').textContent = (t >= 0 ? '+' : '') + t;
      $('kri-trend').style.color = t >= 0 ? 'var(--success)' : 'var(--danger)';
    }
    const classifiable = (d.africa_led || 0) + (d.north_south || 0) || 1;
    if ($('kri-africa-led'))   { $('kri-africa-led').textContent   = (d.africa_led   || 0).toLocaleString(); }
    if ($('kri-north-south'))  { $('kri-north-south').textContent  = (d.north_south  || 0).toLocaleString(); }
    if ($('kri-unclassified')) { $('kri-unclassified').textContent = (d.unclassified || 0).toLocaleString(); }
    if ($('kri-africa-bar'))   { $('kri-africa-bar').style.width   = Math.round((d.africa_led  || 0) / classifiable * 100) + '%'; }
    if ($('kri-ns-bar'))       { $('kri-ns-bar').style.width       = Math.round((d.north_south || 0) / classifiable * 100) + '%'; }
  });

  // ── Research Portfolio Diversity ───────────────────────────────────
  safeFetch(withInst('/api/analytics/research-diversity'), d => {
    if ($('rpd-score'))          { $('rpd-score').textContent = d.score; }
    if ($('rpd-interpretation')) { $('rpd-interpretation').textContent = d.interpretation || ''; }
    if ($('rpd-dominant'))       { $('rpd-dominant').textContent = d.dominant_sdg || '—'; }
    if ($('rpd-vs-baseline')) {
      const diff = (d.score || 0) - 45;
      $('rpd-vs-baseline').textContent = (diff >= 0 ? '+' : '') + diff;
      $('rpd-vs-baseline').style.color = diff >= 0 ? 'var(--success)' : 'var(--danger)';
    }
    if ($('rpd-gaps')) {
      const gaps = d.gap_sdgs || [];
      $('rpd-gaps').innerHTML = gaps.length
        ? gaps.map(g => `<span class="chip text-[10px] py-0.5 px-2" style="background:rgba(245,158,11,.12);color:var(--warning)">${g}</span>`).join('')
        : '<span class="text-xs" style="color:var(--text-muted)">None — great coverage!</span>';
    }
  });

  // ── Open Science Health Score ──────────────────────────────────────
  safeFetch(withInst('/api/analytics/open-science-health'), d => {
    if ($('oshs-score'))          { $('oshs-score').textContent = (d.score || '—') + '/100'; }
    if ($('oshs-grade'))          { $('oshs-grade').textContent = d.grade || '—'; }
    if ($('oshs-interpretation')) { $('oshs-interpretation').textContent = d.interpretation || ''; }
    const c = d.components || {};
    const oaPct    = (c.open_access    && c.open_access.value    != null) ? c.open_access.value    : (c.open_access    || 0);
    const doiPct   = (c.doi_coverage   && c.doi_coverage.value   != null) ? c.doi_coverage.value   : (c.doi_coverage   || 0);
    const orcidPct = (c.orcid_coverage && c.orcid_coverage.value != null) ? c.orcid_coverage.value : (c.orcid_coverage || 0);
    const arkPct   = (c.ark_coverage   && c.ark_coverage.value   != null) ? c.ark_coverage.value   : (c.ark_coverage   || 0);
    if ($('oshs-oa'))    { $('oshs-oa').textContent    = oaPct    + '%'; $('oshs-oa-bar').style.width    = oaPct    + '%'; }
    if ($('oshs-doi'))   { $('oshs-doi').textContent   = doiPct   + '%'; $('oshs-doi-bar').style.width   = doiPct   + '%'; }
    if ($('oshs-orcid')) { $('oshs-orcid').textContent = orcidPct + '%'; $('oshs-orcid-bar').style.width = orcidPct + '%'; }
    if ($('oshs-ark'))   { $('oshs-ark').textContent   = arkPct   + '%'; $('oshs-ark-bar').style.width   = arkPct   + '%'; }
    if ($('oshs-vs-baseline')) {
      const diff = d.vs_baseline != null ? d.vs_baseline : ((d.score || 0) - 38);
      $('oshs-vs-baseline').textContent = (diff >= 0 ? '+' : '') + parseFloat(diff).toFixed(1);
      $('oshs-vs-baseline').style.color = diff >= 0 ? 'var(--success)' : 'var(--danger)';
    }
  });
}

function loadFacultiesDropdown() {
  safeFetch('/api/analytics/faculties', data => {
    const selects = ['cmp-faculty-a', 'cmp-faculty-b', 'cmp-faculty-c', 'dept-cmp-faculty', 'search-faculty'];
    selects.forEach(id => {
      const sel = $(id);
      if (!sel) return;
      const current = sel.value;
      const first = sel.options[0];
      sel.innerHTML = '';
      if (first) sel.appendChild(first);
      data.forEach(f => {
        const opt = document.createElement('option');
        opt.value = f;
        opt.textContent = f.replace('Faculty of ', '').replace('College of ', '');
        sel.appendChild(opt);
      });
      if (current) sel.value = current;
    });
  });
}

/**
 * Counter Animation
 */
function animCount(el, target, suffix = '') {
  if (!el || isNaN(target)) return;
  const dur = 1000, start = performance.now();
  (function tick(now) {
    const p = Math.min((now - start) / dur, 1);
    const ease = 1 - Math.pow(1 - p, 3);
    const v = Math.round(ease * target);
    el.textContent = v.toLocaleString() + suffix;
    if (p < 1) requestAnimationFrame(tick);
  })(start);
}

/**
 * Impact Metrics
 */
function loadImpactCards() {
  safeFetch(withInst('/api/analytics/impact-metrics'), d => {
    const impactCards = $('impact-cards');
    if (!impactCards) return;
    impactCards.innerHTML = [
      { l: 'DOI Coverage', v: d.doi_rate + '%', c: 'var(--accent)' },
      { l: 'Open Access', v: d.oa_rate + '%', c: 'var(--success)' },
      { l: 'PDF Coverage', v: d.pdf_rate + '%', c: 'var(--warning)' },
      { l: 'Years Covered', v: d.years_covered, c: '#60a5fa' },
    ].map(x => `
      <div class="surface rounded-xl p-4 stat-card">
        <p class="section-label">${x.l}</p>
        <p class="text-2xl font-bold" style="color:${x.c}">${x.v}</p>
      </div>
    `).join('');
  });

  if (!$('adv-metrics-cards')) {
    $('impact-cards').insertAdjacentHTML('afterend', '<div class="grid grid-cols-2 gap-3 mb-5" id="adv-metrics-cards"></div>');
  }

  const advMetrics = [
    { id: 'tk_vitality', l: 'TK Vitality Score', c: '#a855f7', api: '/api/analytics/tk-vitality-score', f: d => d.score + '/100' },
    { id: 'ling_div', l: 'Linguistic Diversity', c: '#ec4899', api: '/api/analytics/linguistic-diversity-index', f: d => d.index }
  ];
  
  const advContainer = $('adv-metrics-cards');
  if (advContainer) advContainer.innerHTML = '';
  advMetrics.forEach(metric => {
    safeFetch(withInst(metric.api), d => {
      if (advContainer) advContainer.insertAdjacentHTML('beforeend',
        `<div id="${metric.id}-card" class="surface rounded-xl p-4 stat-card" style="border: 1px solid ${metric.c}30; background: ${metric.c}0a">
          <p class="section-label" style="color:${metric.c}">${metric.l}</p>
          <p class="text-2xl font-bold" style="color:${metric.c}">${metric.f(d)}</p>
        </div>`
      );
    });
  });
}

/**
 * Chart Loading Functions
 */
function reloadYearChart() {
  const mode = $('year-chart-mode').value;
  if (mode === 'stacked') {
    if (yearStackedCache) { renderStackedYear(yearStackedCache); return; }
    safeFetch(withInst('/api/analytics/papers-by-year-faculty'), d => { yearStackedCache = d; renderStackedYear(d); });
  } else {
    if (yearDataCache) { renderSimpleYear(yearDataCache); return; }
    safeFetch(withInst('/api/analytics/publications-by-year'), d => { yearDataCache = d; renderSimpleYear(d); });
  }
}

function renderSimpleYear(data) {
  destroyChart('year'); if (!data || !data.length) return;
  charts['year'] = new Chart($('chart-year'), {
    type: 'bar',
    data: {
      labels: data.map(d => d.year),
      datasets: [{ label: 'Papers', data: data.map(d => d.count), backgroundColor: 'rgba(59, 130, 246, 0.7)', borderRadius: 6 }]
    },
    options: {
      plugins: { legend: { display: false } },
      scales: { x: { grid: { display: false } }, y: { beginAtZero: true } },
      onClick: (e, el) => {
        if (el[0]) {
          switchTab('search', $('tab-btn-search'));
          $('search-year-from').value = data[el[0].index].year;
          $('search-year-to').value = data[el[0].index].year;
          runSearch();
        }
      }
    }
  });
}

function renderStackedYear(data) {
  destroyChart('year'); if (!data || !data.length) return;
  const years = [...new Set(data.map(d => d.year))].sort();
  const facs = [...new Set(data.map(d => d.faculty))];
  charts['year'] = new Chart($('chart-year'), {
    type: 'bar',
    data: {
      labels: years,
      datasets: facs.map((f, i) => ({
        label: f.replace('Faculty of ', '').replace('College of ', ''),
        data: years.map(y => { const r = data.find(d => d.year === y && d.faculty === f); return r ? r.count : 0; }),
        backgroundColor: COLORS[i % COLORS.length],
        borderRadius: 2
      }))
    },
    options: {
      plugins: { legend: { position: 'bottom', labels: { font: { size: 10 }, padding: 10 } } },
      scales: { x: { stacked: true, grid: { display: false } }, y: { stacked: true, beginAtZero: true } }
    }
  });
}

function reloadFacultyChart() {
  const type = $('faculty-chart-type').value;
  if (facultyDataCache) { renderFacultyChart(facultyDataCache, type); return; }
  safeFetch(withInst('/api/analytics/papers-by-faculty'), d => { facultyDataCache = d; renderFacultyChart(d, type); });
}

function renderFacultyChart(data, type) {
  destroyChart('faculty'); if (!data || !data.length) return;
  const labels = data.map(d => d.faculty.replace('Faculty of ', '').replace('College of ', ''));
  charts['faculty'] = new Chart($('chart-faculty'), {
    type, data: { labels, datasets: [{ data: data.map(d => d.count), backgroundColor: COLORS, borderRadius: type === 'bar' ? 6 : 0 }] },
    options: {
      indexAxis: type === 'bar' ? 'y' : undefined,
      plugins: { legend: { display: type === 'doughnut', position: 'bottom' } },
      scales: type === 'bar' ? { x: { beginAtZero: true }, y: { grid: { display: false } } } : {},
      cutout: type === 'doughnut' ? '70%' : undefined
    }
  });
}

function reloadOAChart() {
  const type = $('oa-chart-type').value;
  safeFetch(withInst('/api/analytics/open-access-breakdown'), data => {
    destroyChart('oa');
    charts['oa'] = new Chart($('chart-oa'), {
      type, data: {
        labels: data.map(d => d.label),
        datasets: [{ data: data.map(d => d.value), backgroundColor: ['#10b981', '#ef4444', '#64748b'], borderRadius: type === 'bar' ? 6 : 0 }]
      },
      options: {
        plugins: { legend: { display: type === 'doughnut', position: 'bottom' } },
        scales: type === 'bar' ? { x: { grid: { display: false } }, y: { beginAtZero: true } } : {},
        cutout: type === 'doughnut' ? '70%' : undefined
      }
    });
  });
}

function reloadAuthorsChart() {
  const limit = $('authors-limit').value;
  safeFetch(withInst('/api/analytics/top-authors?limit=' + limit), data => {
    destroyChart('authors');
    charts['authors'] = new Chart($('chart-authors'), {
      type: 'bar', data: {
        labels: data.map(d => d.author),
        datasets: [{ label: 'Papers', data: data.map(d => d.count), backgroundColor: 'rgba(59, 130, 246, 0.7)', borderRadius: 6 }]
      },
      options: {
        indexAxis: 'y', plugins: { legend: { display: false } },
        scales: { x: { beginAtZero: true }, y: { grid: { display: false } } }
      }
    });
  });
}

function loadFacultyOAChart() {
  safeFetch(withInst('/api/analytics/faculty-oa-breakdown'), data => {
    destroyChart('faculty-oa');
    const sorted = data.sort((a, b) => (b.oa + b.restricted) - (a.oa + a.restricted)).slice(0, 10);
    charts['faculty-oa'] = new Chart($('chart-faculty-oa'), {
      type: 'bar',
      data: {
        labels: sorted.map(d => d.faculty.replace('Faculty of ', '').replace('College of ', '')),
        datasets: [
          { label: 'Open Access', data: sorted.map(d => d.oa), backgroundColor: 'rgba(16, 185, 129, 0.7)', borderRadius: 4 },
          { label: 'Restricted', data: sorted.map(d => d.restricted), backgroundColor: 'rgba(239, 68, 68, 0.5)', borderRadius: 4 }
        ]
      },
      options: { indexAxis: 'y', plugins: { legend: { position: 'bottom' } }, scales: { x: { beginAtZero: true }, y: { grid: { display: false } } } }
    });
  });
}

function loadGrowthChart() {
  safeFetch(withInst('/api/analytics/growth-rate'), data => {
    destroyChart('growth'); if (!data || !data.length) return;
    charts['growth'] = new Chart($('chart-growth'), {
      type: 'line', data: {
        labels: data.map(d => d.session || ''),
        datasets: [{ label: 'Papers Added', data: data.map(d => d.count), borderColor: '#6366f1', backgroundColor: 'rgba(99, 102, 241, 0.1)', fill: true, tension: 0.4 }]
      },
      options: { plugins: { legend: { display: false } }, scales: { x: { display: false }, y: { beginAtZero: true } } }
    });
  });
}

function loadTimelineChart() {
  safeFetch(withInst('/api/analytics/timeline'), data => {
    destroyChart('timeline'); if (!data || !data.length) return;
    charts['timeline'] = new Chart($('chart-timeline'), {
      type: 'line', data: {
        labels: data.map(d => d.date),
        datasets: [{ label: 'Total Papers', data: data.map(d => d.total), borderColor: '#10b981', backgroundColor: 'rgba(16, 185, 129, 0.1)', fill: true, tension: 0.4 }]
      },
      options: { plugins: { legend: { display: false } }, scales: { x: { display: false }, y: { beginAtZero: true } } }
    });
  });
}

/**
 * Collaboration Network (D3.js)
 */
let netTimer = null, curNetAuthor = null, d3Sim = null;
function debNetSearch() { clearTimeout(netTimer); netTimer = setTimeout(searchNetAuthor, 300); }

function searchNetAuthor() {
  const q = $('network-search-input').value.trim();
  const sugg = $('network-suggestions');
  if (q.length < 2) { sugg.innerHTML = ''; $('network-result').classList.add('hidden'); return; }
  safeFetch(withInst('/api/analytics/authors-search?q=' + encodeURIComponent(q) + '&limit=8'), authors => {
    if (!authors.length) { sugg.innerHTML = '<p class="text-xs p-2 text-muted">No researchers found</p>'; return; }
    sugg.innerHTML = authors.map(a => `<button class="chip" onclick="loadNetForAuthor('${esc(a.name).replace(/'/g, "\\'")}')">${esc(a.name)} <span style="opacity:0.6">(${a.papers})</span></button>`).join('');
  });
}

function loadNetForAuthor(name) {
  curNetAuthor = name;
  $('network-suggestions').innerHTML = '';
  $('network-search-input').value = name;
  $('network-researcher-name').textContent = name + ' — Collaboration Graph';
  $('network-result').classList.remove('hidden');
  safeFetch(withInst('/api/analytics/author-network?author=' + encodeURIComponent(name)), data => {
    networkEdgeData = data.edges;
    renderD3Net(data, name);
    renderNetTable(data, name);
  });
}

function renderD3Net(data, center) {
  const svg = d3.select('#network-svg');
  svg.selectAll('*').remove();
  const cont = $('network-graph-container');
  const W = cont.offsetWidth || 700, H = 420;
  svg.attr('viewBox', `0 0 ${W} ${H}`);
  
  if (!data.nodes || data.nodes.length <= 1) {
    svg.append('text').attr('x', W / 2).attr('y', H / 2).attr('text-anchor', 'middle').attr('fill', '#64748b').text('No collaborations found.');
    return;
  }
  
  const nodes = data.nodes.map(n => ({ ...n, x: W / 2, y: H / 2 }));
  const links = data.edges.map(e => ({ ...e }));
  
  const lnk = svg.append('g').selectAll('line').data(links).enter().append('line').attr('stroke', 'rgba(59, 130, 246, 0.2)').attr('stroke-width', d => Math.max(1, Math.min(d.weight, 5)));
  
  const nd = svg.append('g').selectAll('g').data(nodes).enter().append('g').style('cursor', 'pointer')
    .call(d3.drag().on('start', (ev, d) => { if (!ev.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; }).on('drag', (ev, d) => { d.fx = ev.x; d.fy = ev.y; }).on('end', (ev, d) => { if (!ev.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }));
    
  nd.append('circle').attr('r', d => d.id === center ? 20 : 12).attr('fill', d => d.id === center ? '#3b82f6' : '#8b5cf6').attr('stroke', '#fff').attr('stroke-width', 1.5);
  nd.append('text').attr('text-anchor', 'middle').attr('dy', '.35em').attr('font-size', '10px').attr('fill', '#fff').text(d => d.id.split(' ').pop());
  nd.on('click', (ev, d) => { if (d.id !== center) loadNetForAuthor(d.id); });
  
  const sim = d3.forceSimulation(nodes).force('link', d3.forceLink(links).id(d => d.id).distance(100)).force('charge', d3.forceManyBody().strength(-200)).force('center', d3.forceCenter(W / 2, H / 2))
    .on('tick', () => { lnk.attr('x1', d => d.source.x).attr('y1', d => d.source.y).attr('x2', d => d.target.x).attr('y2', d => d.target.y); nd.attr('transform', d => `translate(${d.x},${d.y})`); });
  d3Sim = sim;
}

function renderNetTable(data, center) {
  const el = $('network-table'); if (!el) return;
  el.innerHTML = `<p class="section-label mt-4">Co-authors (${data.edges.length})</p><div class="grid grid-cols-2 lg:grid-cols-4 gap-2">` +
    data.edges.map(e => {
      const c = e.source === center ? e.target : e.source;
      return `<div class="surface p-3 rounded-lg cursor-pointer row-hover" onclick="loadNetForAuthor('${esc(c).replace(/'/g, "\\'")}')"><p class="text-xs font-bold">${esc(c)}</p><p class="text-[10px] text-accent">${e.weight} joint papers</p></div>`;
    }).join('') + '</div>';
}

/**
 * Comparator Engine
 */
let selectedInstitutions = [];

// Coordinates for the 25 demo universities
const UNIVERSITY_COORDS = {
  "https://ror.org/03c4mpy73": { lat: 30.0276, lon: 31.2089, name: "Cairo University", sub_region: "North Africa" },
  "https://ror.org/034x7p097": { lat: 30.0772, lon: 31.2850, name: "Ain Shams University", sub_region: "North Africa" },
  "https://ror.org/02078r490": { lat: 31.2001, lon: 29.9187, name: "Alexandria University", sub_region: "North Africa" },
  "https://ror.org/050j3a172": { lat: 36.8315, lon: 10.1887, name: "Université de Tunis El Manar", sub_region: "North Africa" },
  "https://ror.org/03vpy3v17": { lat: 33.9842, lon: -6.8689, name: "Université Mohammed V de Rabat", sub_region: "North Africa" },

  "https://ror.org/04h7g6177": { lat: 3.8619, lon: 11.5222, name: "Université de Yaoundé I", sub_region: "Central Africa" },
  "https://ror.org/05vzwad88": { lat: -4.4173, lon: 15.3086, name: "Université de Kinshasa", sub_region: "Central Africa" },
  "https://ror.org/00z2bpt98": { lat: -8.8383, lon: 13.2842, name: "Université Agostinho Neto", sub_region: "Central Africa" },
  "https://ror.org/02y1sra05": { lat: -4.2638, lon: 15.2471, name: "Université Marien Ngouabi", sub_region: "Central Africa" },
  "https://ror.org/059gqse72": { lat: -1.6247, lon: 13.5786, name: "Université des Sciences et Techniques de Masuku", sub_region: "Central Africa" },

  "https://ror.org/05rk03822": { lat: 6.5182, lon: 3.3987, name: "University of Lagos", sub_region: "West Africa" },
  "https://ror.org/01es5me90": { lat: 7.4443, lon: 3.8994, name: "University of Ibadan", sub_region: "West Africa" },
  "https://ror.org/02n05rk12": { lat: 6.6726, lon: 3.1612, name: "Covenant University", sub_region: "West Africa" },
  "https://ror.org/00zpy3v12": { lat: 5.6508, lon: -0.1870, name: "University of Ghana", sub_region: "West Africa" },
  "https://ror.org/00x4mpy73": { lat: 6.6745, lon: -1.5716, name: "Kwame Nkrumah University of Science and Technology", sub_region: "West Africa" },

  "https://ror.org/017620319": { lat: -33.9573, lon: 18.4612, name: "University of Cape Town", sub_region: "Southern Africa" },
  "https://ror.org/05777p686": { lat: -33.9321, lon: 18.8644, name: "Stellenbosch University", sub_region: "Southern Africa" },
  "https://ror.org/039482g93": { lat: -26.1929, lon: 28.0305, name: "University of the Witwatersrand", sub_region: "Southern Africa" },
  "https://ror.org/047fpp722": { lat: -25.7545, lon: 28.2314, name: "University of Pretoria", sub_region: "Southern Africa" },
  "https://ror.org/03w489125": { lat: -17.7840, lon: 31.0530, name: "University of Zimbabwe", sub_region: "Southern Africa" },

  "https://ror.org/05vzwad88_makerere": { lat: 0.3349, lon: 32.5677, name: "Makerere University", sub_region: "East Africa" },
  "https://ror.org/01078r490": { lat: -1.2801, lon: 36.8166, name: "University of Nairobi", sub_region: "East Africa" },
  "https://ror.org/01py3v171": { lat: 9.0350, lon: 38.7523, name: "Addis Ababa University", sub_region: "East Africa" },
  "https://ror.org/0199e1957": { lat: -6.7725, lon: 39.2064, name: "University of Dar es Salaam", sub_region: "East Africa" },
  "https://ror.org/02yr01r27": { lat: -1.9441, lon: 30.0619, name: "University of Rwanda", sub_region: "East Africa" }
};

// Capital city coordinates for all 52 African countries
const COUNTRY_CAPITAL_COORDS = {
  "Egypt": { lat: 30.0444, lon: 31.2357 },
  "Morocco": { lat: 34.0209, lon: -6.8416 },
  "Algeria": { lat: 36.7538, lon: 3.0588 },
  "Tunisia": { lat: 36.8065, lon: 10.1815 },
  "Libya": { lat: 32.8872, lon: 13.1913 },
  "Sudan": { lat: 15.5007, lon: 32.5599 },
  "Nigeria": { lat: 9.0765, lon: 7.3986 },
  "Ghana": { lat: 5.6037, lon: -0.1870 },
  "Senegal": { lat: 14.7167, lon: -17.4677 },
  "Cote d'Ivoire": { lat: 6.8276, lon: -5.2793 },
  "Benin": { lat: 6.3654, lon: 2.4183 },
  "Burkina Faso": { lat: 12.3714, lon: -1.5197 },
  "Cape Verde": { lat: 14.9330, lon: -23.5133 },
  "Gambia": { lat: 13.4549, lon: -16.5790 },
  "Guinea": { lat: 9.5370, lon: -13.6773 },
  "Guinea-Bissau": { lat: 11.8817, lon: -15.6178 },
  "Liberia": { lat: 6.3156, lon: -10.8074 },
  "Mali": { lat: 12.6392, lon: -8.0029 },
  "Mauritania": { lat: 18.0735, lon: -15.9582 },
  "Niger": { lat: 13.5116, lon: 2.1085 },
  "Sierra Leone": { lat: 8.4840, lon: -13.2299 },
  "Togo": { lat: 6.1375, lon: 1.2123 },
  "Kenya": { lat: -1.2921, lon: 36.8219 },
  "Uganda": { lat: 0.3152, lon: 32.5825 },
  "Tanzania": { lat: -6.1630, lon: 35.7516 },
  "Ethiopia": { lat: 9.0300, lon: 38.7400 },
  "Rwanda": { lat: -1.9441, lon: 30.0619 },
  "Burundi": { lat: -3.3731, lon: 29.9189 },
  "Djibouti": { lat: 11.5721, lon: 43.1456 },
  "Eritrea": { lat: 15.3390, lon: 38.9371 },
  "Somalia": { lat: 2.0439, lon: 45.3426 },
  "South Sudan": { lat: 4.8517, lon: 31.5713 },
  "Madagascar": { lat: -18.8792, lon: 47.5079 },
  "Mauritius": { lat: -20.1609, lon: 57.5012 },
  "Seychelles": { lat: -4.6191, lon: 55.4513 },
  "Comoros": { lat: -11.7006, lon: 43.2505 },
  "South Africa": { lat: -25.7479, lon: 28.2293 },
  "Zimbabwe": { lat: -17.8252, lon: 31.0335 },
  "Zambia": { lat: -15.3875, lon: 28.3228 },
  "Namibia": { lat: -22.5609, lon: 17.0658 },
  "Botswana": { lat: -24.6282, lon: 25.9231 },
  "Lesotho": { lat: -29.3134, lon: 27.4844 },
  "Eswatini": { lat: -26.3055, lon: 31.1367 },
  "Malawi": { lat: -13.9626, lon: 33.7741 },
  "Mozambique": { lat: -25.9692, lon: 32.5732 },
  "Cameroon": { lat: 3.8480, lon: 11.5021 },
  "DR Congo": { lat: -4.4419, lon: 15.2663 },
  "Angola": { lat: -8.8390, lon: 13.2894 },
  "Gabon": { lat: 0.4162, lon: 9.4673 },
  "Republic of the Congo": { lat: -4.2634, lon: 15.2429 },
  "Central African Republic": { lat: 4.3947, lon: 18.5582 },
  "Chad": { lat: 12.1348, lon: 15.0557 },
  "Equatorial Guinea": { lat: 3.7504, lon: 8.7817 },
  "Sao Tome and Principe": { lat: 0.3302, lon: 6.7273 }
};

function loadCompareDDs() {
  if (window.universityRegistry) return;
  safeFetch('/api/university-registry', data => {
    window.universityRegistry = data;
  });
}

// Shared cache of configured institutions ({name, short_name, ror, sub_region}).
// Used by the comparator autocomplete and the crawler region filter.
function loadInstitutionsCache(cb) {
  if (window.institutionsCache) { if (cb) cb(window.institutionsCache); return; }
  safeFetch('/api/institutions', data => {
    window.institutionsCache = data || [];
    if (cb) cb(window.institutionsCache);
  }, () => { if (cb) cb([]); });
}

let compSearchTimer = null;
function debCompSearch() { clearTimeout(compSearchTimer); compSearchTimer = setTimeout(compSearch, 250); }

function compSearch() {
  const input = $('comp-institution-input');
  const box = $('comp-suggestions');
  if (!input || !box) return;
  const q = input.value.trim().toLowerCase();
  if (q.length < 2) { box.classList.add('hidden'); box.innerHTML = ''; return; }
  loadInstitutionsCache(list => {
    const matches = list.filter(i =>
      (i.name || '').toLowerCase().includes(q) || (i.short_name || '').toLowerCase().includes(q)
    ).slice(0, 8);
    if (!matches.length) { box.classList.add('hidden'); box.innerHTML = ''; return; }
    box.innerHTML = matches.map(i => {
      const ror = (i.ror || '').replace(/'/g, "\\'");
      return `<button type="button" class="w-full text-left px-3 py-2 text-sm row-hover" style="border-bottom:1px solid var(--border)" onclick="pickCompInstitution('${ror}')">
        <span class="font-medium">${esc(i.name)}</span> <span class="text-xs text-muted">(${esc(i.short_name)})</span>
      </button>`;
    }).join('');
    box.classList.remove('hidden');
  });
}

function pickCompInstitution(ror) {
  if (ror) quickAddInstitution(ror);
  const input = $('comp-institution-input'); if (input) input.value = '';
  const box = $('comp-suggestions'); if (box) { box.classList.add('hidden'); box.innerHTML = ''; }
}

function onSubregionChange() {
  const subregion = $('comp-subregion-select').value;
  const countrySel = $('comp-country-select');
  const uniSel = $('comp-university-select');
  
  countrySel.innerHTML = '<option value="">Country...</option>';
  uniSel.innerHTML = '<option value="">University...</option>';
  uniSel.disabled = true;
  
  if (!subregion || !window.universityRegistry || !window.universityRegistry[subregion]) {
    countrySel.disabled = true;
    return;
  }
  
  const countries = Object.keys(window.universityRegistry[subregion]).sort();
  countries.forEach(c => {
    const opt = document.createElement('option');
    opt.value = c;
    opt.textContent = c;
    countrySel.appendChild(opt);
  });
  countrySel.disabled = false;
}

function onCountryChange() {
  const subregion = $('comp-subregion-select').value;
  const country = $('comp-country-select').value;
  const uniSel = $('comp-university-select');
  
  uniSel.innerHTML = '<option value="">University...</option>';
  
  if (!subregion || !country || !window.universityRegistry || !window.universityRegistry[subregion] || !window.universityRegistry[subregion][country]) {
    uniSel.disabled = true;
    return;
  }
  
  const unis = window.universityRegistry[subregion][country];
  unis.forEach(u => {
    const opt = document.createElement('option');
    const rorValue = u.ror || `https://ror.org/local/${encodeURIComponent(u.name)}`;
    opt.value = rorValue;
    opt.textContent = u.name;
    uniSel.appendChild(opt);
  });
  uniSel.disabled = false;
}

function onUniversityChange(value) {
  if (!value) return;
  quickAddInstitution(value);
  $('comp-university-select').value = '';
}

function addInstitutionToComparison() {
  const input = $('comp-institution-input');
  let value = input.value.trim();
  if (!value) return;
  // If the typed text matches a known institution name, resolve it to its ROR
  // so the backend (which compares by ROR) can find its papers.
  if (window.institutionsCache && !value.startsWith('http')) {
    const m = window.institutionsCache.find(i =>
      (i.name || '').toLowerCase() === value.toLowerCase() ||
      (i.short_name || '').toLowerCase() === value.toLowerCase());
    if (m && m.ror) value = m.ror;
  }
  if (selectedInstitutions.includes(value) || selectedInstitutions.length >= 15) return;
  selectedInstitutions.push(value);
  input.value = '';
  const box = $('comp-suggestions'); if (box) { box.classList.add('hidden'); box.innerHTML = ''; }
  renderSelectedInstitutions();
}

function quickAddInstitution(ror) {
  if (!ror || selectedInstitutions.includes(ror) || selectedInstitutions.length >= 15) return;
  selectedInstitutions.push(ror);
  renderSelectedInstitutions();
}

function removeInstitution(ror) {
  selectedInstitutions = selectedInstitutions.filter(r => r !== ror);
  renderSelectedInstitutions();
}

function renderSelectedInstitutions() {
  const container = $('comp-selected-institutions'); if (!container) return;
  if (selectedInstitutions.length === 0) { container.innerHTML = '<p class="text-xs text-muted">No institutions selected.</p>'; return; }
  container.innerHTML = selectedInstitutions.map(ror => {
    let name = ror.split('/').pop();
    // Prefer the human-readable name from the institutions cache when known.
    if (window.institutionsCache) {
      const m = window.institutionsCache.find(i => i.ror === ror);
      if (m) name = m.name;
    }
    if (name.startsWith('local/')) {
      name = decodeURIComponent(name.replace('local/', ''));
    }
    if (name.length > 25) name = name.substring(0, 22) + '...';
    const safeRor = ror.replace(/'/g, "\\'");
    return `<div class="chip active">${esc(name)} <button onclick="removeInstitution('${safeRor}')" class="ml-1">×</button></div>`;
  }).join('');
}

function clearComparison() {
  selectedInstitutions = [];
  renderSelectedInstitutions();
  $('comp-results').classList.add('hidden');
  $('comp-institution-input').value = '';
  $('comp-subregion-select').value = '';
  $('comp-country-select').innerHTML = '<option value="">Country...</option>';
  $('comp-country-select').disabled = true;
  $('comp-university-select').innerHTML = '<option value="">University...</option>';
  $('comp-university-select').disabled = true;
}

function runComparison() {
  if (selectedInstitutions.length < 2) { toast('Add at least 2 institutions', 'warning'); return; }
  const btn = $('comp-run-btn'); btn.disabled = true;
  fetch('/api/comparator/senate-report', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ror_ids: selectedInstitutions, format: 'json' }) })
    .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then(data => { window.lastCompareData = data; renderComparisonResults(data); $('comp-results').classList.remove('hidden'); })
    .catch(e => { console.error(e); toast('Comparison failed: ' + e.message, 'error'); })
    .finally(() => btn.disabled = false);
}

function renderComparisonResults(data) {
  // Summary cards
  $('comp-total-papers').textContent = data.executive_summary.total_papers.toLocaleString();
  $('comp-total-authors').textContent = data.executive_summary.total_authors.toLocaleString();
  $('comp-avg-oa').textContent = data.executive_summary.average_oa_rate + '%';
  $('comp-collaborations').textContent = data.executive_summary.total_collaborations;

  // Table Matrix — Special-Collections metrics
  const tbody = $('comp-table-body');
  tbody.innerHTML = data.detailed_comparison.institutions.map(inst => {
    const m = inst.metrics;
    return `
    <tr class="row-hover border-b border-white/5">
      <td class="py-3 px-2 font-medium">${esc(inst.name)}</td>
      <td class="py-3 px-2 text-right">${(m.total_papers || 0).toLocaleString()}</td>
      <td class="py-3 px-2 text-right">${(m.total_authors || 0).toLocaleString()}</td>
      <td class="py-3 px-2 text-right">${m.oa_rate || 0}%</td>
      <td class="py-3 px-2 text-right">${(m.indigenous_knowledge || 0).toLocaleString()}</td>
      <td class="py-3 px-2 text-right">${(m.african_literature || 0).toLocaleString()}</td>
      <td class="py-3 px-2 text-right">${m.papers_per_author || 0}</td>
    </tr>`;
  }).join('');

  // Rankings
  const renderRanks = (list, unit) => {
    if (!list || !list.length) return '<p class="text-xs text-muted">No data</p>';
    return list.map(r => `
      <div class="flex justify-between items-center py-1.5 border-b border-white/5 last:border-0">
        <span class="text-sm"><span class="font-bold text-accent mr-2">#${r.rank}</span>${esc(r.institution)}</span>
        <span class="font-mono text-xs font-bold">${r.value.toLocaleString()}${unit}</span>
      </div>`).join('');
  };
  
  const rankings = data.detailed_comparison.rankings;
  $('comp-rank-volume').innerHTML = renderRanks(rankings.total_papers, ' papers');
  $('comp-rank-oa').innerHTML = renderRanks(rankings.oa_rate, '%');
  $('comp-rank-ik').innerHTML = renderRanks(rankings.indigenous_knowledge, ' papers');
  $('comp-rank-lit').innerHTML = renderRanks(rankings.african_literature, ' papers');

  // Insights
  const insightsEl = $('comp-insights');
  let html = '';
  if (data.detailed_comparison.insights && data.detailed_comparison.insights.length) {
    html += '<div class="space-y-2 mb-4">';
    data.detailed_comparison.insights.forEach(ins => {
      if (ins.category.includes('Leader') || ins.category.includes('Champion')) {
        html += `
          <div class="p-3 rounded-lg border border-success/20 bg-success/5 flex items-start gap-2">
            <span class="text-success text-base">★</span>
            <div>
              <p class="font-bold text-xs text-success uppercase tracking-wider">${esc(ins.category)}</p>
              <p class="text-sm font-semibold text-slate-100">${esc(ins.institution)} leads with ${ins.value.toLocaleString()}${ins.metric.includes('rate') ? '%' : ''}</p>
            </div>
          </div>`;
      } else {
        html += `
          <div class="p-3 rounded-lg border border-warning/20 bg-warning/5 flex items-start gap-2">
            <span class="text-warning text-base">⚠</span>
            <div>
              <p class="font-bold text-xs text-warning uppercase tracking-wider">${esc(ins.category)} (${esc(ins.institution)})</p>
              <p class="text-sm text-slate-200">${esc(ins.message)}</p>
            </div>
          </div>`;
      }
    });
    html += '</div>';
  }
  
  if (data.recommendations && data.recommendations.length) {
    html += '<p class="text-xs font-bold text-slate-400 mb-2 uppercase tracking-wide">Actionable Policy Recommendations</p>';
    html += '<ul class="list-disc pl-5 text-sm space-y-1 text-slate-300">';
    data.recommendations.forEach(rec => { html += `<li>${esc(rec)}</li>`; });
    html += '</ul>';
  }
  
  insightsEl.innerHTML = html || '<p class="text-sm py-4 text-muted">No insights available.</p>';

  // Network map
  renderAfricanCollaborationMap(data.collaboration_network);
}

function generateSenateReport() {
  if (selectedInstitutions.length < 2) { toast('Add at least 2 institutions', 'warning'); return; }
  toast('Downloading Senate Report (CSV)...', 'info');
  fetch('/api/comparator/senate-report', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ror_ids: selectedInstitutions, format: 'csv' }) })
    .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.blob(); })
    .then(blob => {
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.style.display = 'none'; a.href = url;
      a.download = `senate_report_${new Date().toISOString().split('T')[0]}.csv`;
      document.body.appendChild(a); a.click();
      window.URL.revokeObjectURL(url);
      toast('Senate Report downloaded successfully', 'success');
    })
    .catch(e => { console.error(e); toast('Report download failed: ' + e.message, 'error'); });
}

const REGION_COLORS = { "North Africa": "#3b82f6", "West Africa": "#22c55e", "East Africa": "#f59e0b", "Southern Africa": "#8b5cf6", "Central Africa": "#ec4899", "Unknown": "#64748b" };

// Resolve a network node to {lon, lat, name, region} using the demo coords,
// then the dynamic registry + capital fallback (same lookup the D3 map used).
function resolveNodeGeo(node) {
  let lat = null, lon = null, name = node.label, region = 'Unknown';
  const uRor = node.id;
  if (UNIVERSITY_COORDS[uRor]) {
    lat = UNIVERSITY_COORDS[uRor].lat; lon = UNIVERSITY_COORDS[uRor].lon;
    name = UNIVERSITY_COORDS[uRor].name; region = UNIVERSITY_COORDS[uRor].sub_region;
  } else if (window.universityRegistry) {
    for (const [subReg, countries] of Object.entries(window.universityRegistry)) {
      let found = false;
      for (const [country, unis] of Object.entries(countries)) {
        const uni = unis.find(u => u.ror === uRor || u.name === name);
        if (uni) {
          const cc = COUNTRY_CAPITAL_COORDS[country];
          if (cc) { lat = cc.lat; lon = cc.lon; }
          name = uni.name; region = subReg; found = true; break;
        }
      }
      if (found) break;
    }
  }
  if (lat === null || lon === null) return null; // unknown location — skip
  return { id: node.id, lon, lat, name, region };
}

// MapLibre-backed collaboration map over a real African basemap (no API key).
function renderAfricanCollaborationMap(networkData) {
  const container = document.getElementById('comp-collaboration-viz');
  const mapEl = document.getElementById('comp-map');
  if (!mapEl) return;

  if (typeof maplibregl === 'undefined') {
    mapEl.innerHTML = '<div class="flex items-center justify-center h-full text-sm text-muted">Map unavailable (MapLibre failed to load).</div>';
    return;
  }

  // Build node geo + edge GeoJSON once, reused on every render.
  const geoNodes = (networkData.nodes || []).map(resolveNodeGeo).filter(Boolean);
  const nodeById = {}; geoNodes.forEach(n => nodeById[n.id] = n);
  const nodeFeatures = geoNodes.map(n => ({
    type: 'Feature',
    geometry: { type: 'Point', coordinates: [n.lon, n.lat] },
    properties: { id: n.id, name: n.name, region: n.region, color: REGION_COLORS[n.region] || REGION_COLORS.Unknown }
  }));
  const edgeFeatures = (networkData.edges || []).map(e => {
    const s = nodeById[e.source], t = nodeById[e.target];
    if (!s || !t) return null;
    return {
      type: 'Feature',
      geometry: { type: 'LineString', coordinates: [[s.lon, s.lat], [t.lon, t.lat]] },
      properties: { weight: e.weight, width: Math.max(1.5, Math.min(e.weight * 1.5, 8)) }
    };
  }).filter(Boolean);
  const nodeFC = { type: 'FeatureCollection', features: nodeFeatures };
  const edgeFC = { type: 'FeatureCollection', features: edgeFeatures };

  const applyData = (map) => {
    map.getSource('collab-edges').setData(edgeFC);
    map.getSource('collab-nodes').setData(nodeFC);
  };

  // Reuse the map instance across comparisons.
  if (window.compMap) {
    if (window.compMap.isStyleLoaded()) applyData(window.compMap);
    else window.compMap.once('load', () => applyData(window.compMap));
    setTimeout(() => window.compMap.resize(), 50);
    return;
  }

  let map;
  try {
    map = new maplibregl.Map({
      container: 'comp-map',
      style: {
        version: 8,
        sources: {
          'carto-dark': {
            type: 'raster',
            tiles: ['https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png',
                    'https://b.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png'],
            tileSize: 256,
            attribution: '© OpenStreetMap contributors © CARTO'
          }
        },
        layers: [{ id: 'carto-dark', type: 'raster', source: 'carto-dark' }]
      },
      center: [20, 2],
      zoom: 2.3,
      attributionControl: false
    });
  } catch (err) {
    console.error('MapLibre init failed', err);
    mapEl.innerHTML = '<div class="flex items-center justify-center h-full text-sm text-muted">Map unavailable.</div>';
    return;
  }
  window.compMap = map;
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');

  map.on('load', () => {
    map.addSource('collab-edges', { type: 'geojson', data: edgeFC });
    map.addLayer({
      id: 'collab-edges', type: 'line', source: 'collab-edges',
      paint: { 'line-color': 'rgba(251,191,36,0.5)', 'line-width': ['get', 'width'] }
    });
    map.addSource('collab-nodes', { type: 'geojson', data: nodeFC });
    map.addLayer({
      id: 'collab-nodes', type: 'circle', source: 'collab-nodes',
      paint: {
        'circle-radius': 7,
        'circle-color': ['get', 'color'],
        'circle-stroke-color': '#0f172a',
        'circle-stroke-width': 1.5
      }
    });

    const tooltip = $('comp-map-tooltip');
    map.on('mouseenter', 'collab-nodes', (e) => {
      map.getCanvas().style.cursor = 'pointer';
      const p = e.features[0].properties;
      let html = `<p class="font-bold text-slate-100">${esc(p.name)}</p><p class="text-[10px] text-muted mb-2">${esc(p.region)}</p>`;
      if (window.lastCompareData) {
        const inst = window.lastCompareData.detailed_comparison.institutions.find(i => i.ror_id === p.id);
        if (inst) {
          const m = inst.metrics;
          html += `
            <div class="space-y-1 mt-1 border-t border-white/10 pt-1">
              <div class="flex justify-between gap-4"><span>SC Papers:</span><span class="font-mono text-accent">${(m.total_papers || 0).toLocaleString()}</span></div>
              <div class="flex justify-between gap-4"><span>OA Rate:</span><span class="font-mono text-success">${m.oa_rate || 0}%</span></div>
              <div class="flex justify-between gap-4"><span>Indigenous Knowledge:</span><span class="font-mono text-warning">${(m.indigenous_knowledge || 0).toLocaleString()}</span></div>
              <div class="flex justify-between gap-4"><span>African Literature:</span><span class="font-mono">${(m.african_literature || 0).toLocaleString()}</span></div>
            </div>`;
        }
      }
      tooltip.innerHTML = html;
      tooltip.classList.remove('hidden');
      const rect = container.getBoundingClientRect();
      tooltip.style.left = (e.point.x + 15) + 'px';
      tooltip.style.top = (e.point.y + 15) + 'px';
    });
    map.on('mousemove', 'collab-nodes', (e) => {
      tooltip.style.left = (e.point.x + 15) + 'px';
      tooltip.style.top = (e.point.y + 15) + 'px';
    });
    map.on('mouseleave', 'collab-nodes', () => {
      map.getCanvas().style.cursor = '';
      tooltip.classList.add('hidden');
    });
  });
}

function generateDecolonialReport() {
  const btn = $('report-gen-btn'); btn.disabled = true; btn.textContent = 'Generating...';
  const container = $('report-output-container'), title = $('report-title'), body = $('report-body');
  container.classList.add('hidden');
  
  safeFetch('/api/reports/unilag-subregion', data => {
    title.textContent = data.title;
    let html = `
      <div>
        <p class="text-xs uppercase tracking-wider text-muted mb-1">Generated: ${esc(data.metadata.generated_at)} | Focus: ${esc(data.metadata.institution)} (${esc(data.metadata.subregion)})</p>
        <p class="text-sm italic leading-relaxed text-slate-300 border-l-2 border-accent pl-4 py-1">${esc(data.introduction)}</p>
      </div>
      <div class="space-y-3 pt-3">
        <h4 class="text-base font-bold text-slate-100">I. Curated Literature Statistics & AU Renaissance Target 2 Compliance</h4>
        <div class="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div class="surface p-4 rounded-xl text-center" style="background:rgba(255,255,255,0.02)">
            <p class="text-xs text-muted">Total Curated Papers</p>
            <p class="text-2xl font-bold text-accent">${data.statistics.total_curated}</p>
          </div>
          <div class="surface p-4 rounded-xl text-center" style="background:rgba(255,255,255,0.02)">
            <p class="text-xs text-muted">Compliant Papers</p>
            <p class="text-2xl font-bold text-success">${data.statistics.compliant_count}</p>
          </div>
          <div class="surface p-4 rounded-xl text-center" style="background:rgba(255,255,255,0.02)">
            <p class="text-xs text-muted">Compliance Rate</p>
            <p class="text-2xl font-bold text-warning">${data.statistics.compliance_rate}%</p>
          </div>
        </div>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mt-3">
          <div class="p-3 rounded-lg border border-success/10 bg-success/5">
            <p class="text-xs font-bold text-success mb-1 uppercase tracking-wider">Linguistic Keywords Detected</p>
            <p class="text-xs text-slate-300 leading-relaxed">${data.statistics.keywords_found.map(k => `<span class="chip text-[10px] py-0.5 px-2 mr-1 mb-1 inline-block">${esc(k)}</span>`).join('') || 'None detected'}</p>
          </div>
          <div class="p-3 rounded-lg border border-warning/10 bg-warning/5">
            <p class="text-xs font-bold text-warning mb-1 uppercase tracking-wider">Critical Literature Gaps (Missing Targets)</p>
            <p class="text-xs text-slate-300 leading-relaxed">${data.statistics.keywords_gap.slice(0, 15).map(k => `<span class="chip text-[10px] py-0.5 px-2 mr-1 mb-1 inline-block" style="background:rgba(239,68,68,0.1);color:#f87171">${esc(k)}</span>`).join('') || 'No gaps'}</p>
          </div>
        </div>
      </div>
      <div class="space-y-3 pt-3">
        <h4 class="text-base font-bold text-slate-100">II. Comparative Sub-Regional Benchmark (UNILAG vs. West African Peers)</h4>
        <p class="text-xs text-muted">Benchmark analysis comparing UNILAG's linguistic alignment against other major West African institutions (University of Ibadan and Covenant University).</p>
        <div class="overflow-x-auto">
          <table class="w-full text-xs text-left" style="background:rgba(0,0,0,0.2); border-radius:8px">
            <thead>
              <tr class="border-b border-white/10" style="color:var(--text-muted)">
                <th class="py-2.5 px-3">Institution / Region</th>
                <th class="py-2.5 px-3 text-right">Compliant Count</th>
                <th class="py-2.5 px-3 text-right">Compliance Rate</th>
              </tr>
            </thead>
            <tbody>
              <tr class="border-b border-white/5">
                <td class="py-2.5 px-3 font-semibold text-slate-200">University of Lagos (UNILAG)</td>
                <td class="py-2.5 px-3 text-right font-mono">${data.scores_and_trends.comparison.unilag_compliant}</td>
                <td class="py-2.5 px-3 text-right font-mono text-success font-semibold">${data.scores_and_trends.comparison.unilag_rate}%</td>
              </tr>
              <tr>
                <td class="py-2.5 px-3 text-slate-400">West African Benchmark (UI & Covenant)</td>
                <td class="py-2.5 px-3 text-right font-mono text-slate-400">${data.scores_and_trends.comparison.west_africa_compliant}</td>
                <td class="py-2.5 px-3 text-right font-mono text-slate-400">${data.scores_and_trends.comparison.west_africa_rate}%</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="mt-3">
          <p class="text-xs font-bold text-slate-400 mb-2 uppercase tracking-wide">Yearly Compliance Trend</p>
          <div class="flex gap-2 flex-wrap">
            ${data.scores_and_trends.timeline.map(t => `
              <div class="surface rounded-lg px-3 py-1.5 text-center min-w-[60px]" style="background:rgba(255,255,255,0.02)">
                <p class="text-[10px] text-muted">${t.year}</p>
                <p class="text-sm font-bold text-accent">${t.count}</p>
              </div>`).join('') || '<p class="text-xs text-muted">No timeline data available</p>'}
          </div>
        </div>
      </div>
      <div class="space-y-3 pt-3 border-t border-white/5">
        <h4 class="text-base font-bold text-slate-100">III. Strategic Decolonial Recommendation Outlook</h4>
        <p class="text-sm leading-relaxed text-slate-300">${esc(data.conclusion)}</p>
      </div>
    `;
    body.innerHTML = html;
    container.classList.remove('hidden');
    toast('Decolonial Report generated successfully', 'success');
  }, () => {
    toast('Failed to generate report', 'error');
  })
  .finally(() => {
    btn.disabled = false; btn.textContent = 'Generate UNILAG Decolonial Report';
  });
}

function copyReportToClipboard() {
  const body = $('report-body'); if (!body) return;
  const text = body.innerText || body.textContent;
  navigator.clipboard.writeText(text)
    .then(() => toast('Report text copied to clipboard', 'success'))
    .catch(e => toast('Copy failed: ' + e.message, 'error'));
}

/**
 * Charter Alignment & Gap Analysis (AU charters / Agenda 2063 / regional blocs)
 * Profiles are precomputed server-side; this tab only renders.
 */
let alignFrameworksCache = null;

function loadAlignmentFrameworks(cb) {
  if (alignFrameworksCache) return cb(alignFrameworksCache);
  safeFetch('/api/alignment/frameworks', resp => {
    alignFrameworksCache = resp.data;
    const sel = $('align-framework-select');
    sel.innerHTML = Object.entries(alignFrameworksCache.groups).map(([group, keys]) => `
      <optgroup label="${esc(group)}">
        ${keys.map(k => {
          const f = alignFrameworksCache.frameworks.find(fw => fw.key === k);
          return f ? `<option value="${f.key}">${esc(f.name)}</option>` : '';
        }).join('')}
      </optgroup>`).join('');
    sel.value = 'agenda2063';
    const badge = $('align-mode-badge');
    if (badge && alignFrameworksCache.mode === 'keyword_only') {
      badge.innerHTML = '<span class="chip text-[9px] py-0.5 px-1.5" style="background:#f59e0b18;color:#f59e0b">keyword-only mode</span>';
    }
    cb(alignFrameworksCache);
  }, () => {
    $('align-loading').innerHTML = '<p class="text-sm text-center py-8 text-muted">Failed to load frameworks.</p>';
  });
}

function loadAlignmentTab() {
  loadAlignmentFrameworks(() => {
    const fw = $('align-framework-select').value || 'agenda2063';
    $('align-loading').classList.remove('hidden');
    $('align-content').classList.add('hidden');
    $('align-csv-link').href = withInst('/api/alignment/export.csv');

    safeFetch(withInst(`/api/alignment/profile?framework=${fw}`), resp => {
      const d = resp.data;
      $('align-loading').classList.add('hidden');
      $('align-content').classList.remove('hidden');
      $('align-narrative').textContent = resp.narrative || '';

      // ── Radar: fixed 0-100 scale (never auto-scale a radar) ──────────
      destroyChart('align-radar');
      charts['align-radar'] = new Chart($('chart-align-radar'), {
        type: 'radar',
        data: {
          labels: d.pillars.map(p => p.name),
          datasets: [{
            label: d.institution,
            data: d.pillars.map(p => p.avg_score),
            backgroundColor: d.color + '33',
            borderColor: d.color,
            borderWidth: 2,
            pointBackgroundColor: d.color,
            fill: true,
          }, {
            label: `Gap threshold (${d.gap_threshold})`,
            data: d.pillars.map(() => d.gap_threshold),
            borderColor: '#ef4444',
            borderDash: [6, 4],
            borderWidth: 1.5,
            pointRadius: 0,
            fill: false,
          }],
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          scales: { r: { min: 0, max: 100, ticks: { stepSize: 20, backdropColor: 'transparent' },
                         pointLabels: { font: { size: 11 } } } },
          plugins: { legend: { labels: { font: { size: 11 } } } },
        },
      });

      // ── Pillar detail cards with evidence chips ──────────────────────
      $('align-pillars').innerHTML = d.pillars.map(p => `
        <div class="surface rounded-xl p-4" style="border-top:3px solid ${p.is_gap ? '#ef4444' : d.color}">
          <div class="flex justify-between items-start mb-2">
            <p class="text-xs font-bold leading-tight" style="color:var(--text)">${esc(p.name)}</p>
            <span class="text-xs font-mono font-bold ml-2 flex-shrink-0" style="color:${p.is_gap ? '#ef4444' : d.color}">${p.avg_score}</span>
          </div>
          <div class="h-1.5 rounded-full mb-2" style="background:var(--input-bg)">
            <div class="h-1.5 rounded-full" style="width:${Math.min(100, p.avg_score)}%;background:${p.is_gap ? '#ef4444' : d.color};transition:width 0.6s ease"></div>
          </div>
          <p class="text-xs text-muted mb-2">${p.paper_count} aligned papers${p.is_gap ? ' · <span style="color:#ef4444;font-weight:600">GAP</span>' : ''}</p>
          ${p.top_papers.length ? `
            <div class="space-y-1.5 border-t border-white/5 pt-2">
              ${p.top_papers.slice(0, 3).map(tp => `
                <div class="row-hover p-2 rounded-lg cursor-pointer" onclick="openPaperModal(${tp.id})">
                  <p class="text-xs font-medium leading-snug line-clamp-2">${esc(tp.title)}</p>
                  <div class="flex gap-1 mt-1 flex-wrap">
                    ${tp.matched_keywords.slice(0, 3).map(k => `<span class="chip text-[9px] py-0.5 px-1.5" style="background:${d.color}18;color:${d.color}">${esc(k)}</span>`).join('')}
                  </div>
                </div>`).join('')}
            </div>` : '<p class="text-xs text-muted italic">No papers matched yet.</p>'}
        </div>`).join('');

      loadAlignmentGaps();
      loadAlignmentMatrix();
    }, () => {
      $('align-loading').innerHTML = '<p class="text-sm text-center py-8 text-muted">Failed to load alignment data.</p>';
    });
  });
}

function loadAlignmentGaps() {
  safeFetch(withInst('/api/alignment/gaps'), resp => {
    $('gaps-narrative').textContent = resp.narrative || '';
    const gaps = resp.data.gaps || [];
    $('align-gaps').innerHTML = gaps.length ? gaps.map(g => {
      const sev = g.avg_score < resp.data.threshold / 2 ? '#ef4444' : '#f59e0b';
      return `
        <div class="flex items-center justify-between p-2 rounded-lg row-hover">
          <div class="min-w-0">
            <p class="text-xs font-medium truncate" style="color:var(--text)">${esc(g.pillar_name)}</p>
            <p class="text-[10px] text-muted truncate">${esc(g.framework_name)}</p>
          </div>
          <span class="chip text-[10px] py-0.5 px-2 ml-2 flex-shrink-0" style="background:${sev}18;color:${sev}">${g.avg_score}</span>
        </div>`;
    }).join('') : '<p class="text-xs text-muted italic">No gaps below threshold — strong coverage across all pillars.</p>';
  });
}

function loadAlignmentMatrix() {
  safeFetch(withInst('/api/alignment/matrix'), resp => {
    const cells = resp.data.cells || [];
    const byFw = {};
    cells.forEach(c => (byFw[c.framework] = byFw[c.framework] || []).push(c));
    const maxPillars = Math.max(...Object.values(byFw).map(a => a.length));
    const fwMeta = Object.fromEntries(resp.data.frameworks.map(f => [f.key, f]));
    const heat = s => s <= 0 ? 'var(--input-bg)' :
      `hsl(${Math.round(s * 1.2)},65%,${38 + Math.round(s * 0.12)}%)`;
    $('align-matrix').innerHTML = `
      <table class="w-full" style="border-collapse:separate;border-spacing:2px">
        ${Object.entries(byFw).map(([fk, arr]) => `
          <tr>
            <td class="text-xs font-medium pr-3 whitespace-nowrap" style="color:var(--text-muted);max-width:220px;overflow:hidden;text-overflow:ellipsis">${esc(fwMeta[fk] ? fwMeta[fk].name : fk)}</td>
            ${arr.map(c => `
              <td title="${esc(c.pillar_name)}: ${c.avg_score}/100 (${c.paper_count} papers)"
                  style="background:${heat(c.avg_score)};height:26px;min-width:34px;border-radius:4px;text-align:center;font-size:9px;color:${c.avg_score > 0 ? '#fff' : 'var(--text-dim)'};cursor:default">${c.avg_score > 0 ? Math.round(c.avg_score) : ''}</td>`).join('')}
            ${Array(maxPillars - arr.length).fill('<td></td>').join('')}
          </tr>`).join('')}
      </table>
      <p class="text-[10px] mt-2" style="color:var(--text-dim)">Cell = institutional average alignment score (0–100) per framework pillar. Hover for pillar names.</p>`;
  });
}

/**
 * Intra-African Collaboration tab — index, choropleth + arc map, citation
 * velocity and Louvain-community author network.
 */
let collabMap = null;

function loadCollabTab() {
  $('collab-loading').classList.remove('hidden');
  $('collab-content').classList.add('hidden');

  safeFetch(withInst('/api/collaboration/overview'), resp => {
    const d = resp.data;
    $('collab-loading').classList.add('hidden');
    $('collab-content').classList.remove('hidden');
    $('collab-narrative').textContent = resp.narrative || '';

    const ratioColor = d.intra_african_pct >= d.baseline_pct ? 'var(--success)' : 'var(--warning)';
    $('collab-cards').innerHTML = `
      <div class="surface rounded-xl p-4 stat-card">
        <p class="section-label">Intra-African Index</p>
        <p class="text-2xl font-bold" style="color:${ratioColor}">${d.intra_african_pct || 0}%</p>
        <p class="text-[10px] text-muted">vs ${d.baseline_pct}% continental avg ${d.ratio_vs_baseline ? `(${d.ratio_vs_baseline}×)` : ''}</p>
      </div>
      <div class="surface rounded-xl p-4 stat-card">
        <p class="section-label">Intra-African Papers</p>
        <p class="text-2xl font-bold" style="color:var(--accent)">${(d.intra_african_count || 0).toLocaleString()}</p>
        <p class="text-[10px] text-muted">≥2 African countries</p>
      </div>
      <div class="surface rounded-xl p-4 stat-card">
        <p class="section-label">Partner Countries</p>
        <p class="text-2xl font-bold" style="color:var(--text)">${d.country_count || 0}</p>
        <p class="text-[10px] text-muted">with affiliations on record</p>
      </div>
      <div class="surface rounded-xl p-4 stat-card">
        <p class="section-label">Affiliation Coverage</p>
        <p class="text-2xl font-bold" style="color:var(--text)">${d.total_papers ? Math.round((d.papers_with_affiliation_data || 0) / d.total_papers * 100) : 0}%</p>
        <p class="text-[10px] text-muted">${(d.papers_with_affiliation_data || 0).toLocaleString()} of ${(d.total_papers || 0).toLocaleString()} papers</p>
      </div>`;

    renderCollabMap();
    loadCollabPairs();
    loadCitationVelocity();
  }, () => {
    $('collab-loading').innerHTML = '<p class="text-sm text-center py-8 text-muted">Failed to load collaboration data.</p>';
  });
}

function renderCollabMap() {
  const mapEl = $('collab-map');
  if (!mapEl || typeof maplibregl === 'undefined') {
    if (mapEl) mapEl.innerHTML = '<div class="flex items-center justify-center h-full text-sm text-muted">Map unavailable.</div>';
    return;
  }
  if (collabMap) { try { collabMap.remove(); } catch (e) { } collabMap = null; }

  collabMap = new maplibregl.Map({
    container: 'collab-map',
    style: {
      version: 8,
      sources: {
        carto: {
          type: 'raster',
          tiles: ['https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png'],
          tileSize: 256,
          attribution: '© CARTO © OpenStreetMap contributors',
        },
      },
      layers: [{ id: 'carto', type: 'raster', source: 'carto' }],
    },
    center: [17, 2],
    zoom: 2.2,
    attributionControl: false,
  });

  collabMap.on('load', () => {
    // ── Choropleth: country fill by paper count ───────────────────────
    safeFetch(withInst('/api/collaboration/countries'), resp => {
      const countries = resp.data.countries || [];
      const counts = {};
      countries.forEach(c => counts[c.code] = c);
      const maxPapers = Math.max(1, ...Object.values(counts).map(c => c.papers));

      // When DB is empty, overlay a friendly message so the map isn't silent.
      if (!countries.length) {
        const overlay = document.createElement('div');
        overlay.style.cssText = 'position:absolute;inset:0;display:flex;align-items:center;justify-content:center;background:rgba(15,23,42,0.65);border-radius:12px;pointer-events:none;z-index:10';
        overlay.innerHTML = '<p class="text-sm text-center px-8" style="color:rgba(255,255,255,0.7)">No intra-African co-publication data yet.<br>Crawl papers across multiple institutions to populate the map.</p>';
        mapEl.style.position = 'relative';
        mapEl.appendChild(overlay);
      }

      fetch('/static/data/africa_admin0.geojson').then(r => r.json()).then(geo => {
        geo.features.forEach(f => {
          const c = counts[f.properties.iso_a2];
          f.properties.papers = c ? c.papers : 0;
          f.properties.intensity = c ? c.papers / maxPapers : 0;
        });
        if (!collabMap) return;
        collabMap.addSource('africa', { type: 'geojson', data: geo });
        collabMap.addLayer({
          id: 'africa-fill', type: 'fill', source: 'africa',
          paint: {
            'fill-color': ['interpolate', ['linear'], ['get', 'intensity'],
              0, 'rgba(59,130,246,0.04)', 0.05, 'rgba(59,130,246,0.25)',
              0.4, 'rgba(34,197,94,0.55)', 1, 'rgba(34,197,94,0.85)'],
            'fill-outline-color': 'rgba(148,163,184,0.35)',
          },
        });
        const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false });
        collabMap.on('mousemove', 'africa-fill', e => {
          const p = e.features[0].properties;
          if (p.papers > 0) popup.setLngLat(e.lngLat).setHTML(`<strong>${p.name}</strong><br>${p.papers} papers`).addTo(collabMap);
        });
        collabMap.on('mouseleave', 'africa-fill', () => popup.remove());

        // ── Arcs above the fill ───────────────────────────────────────
        safeFetch(withInst('/api/collaboration/arcs'), arcs => {
          if (!collabMap || !arcs.features) return;
          const maxCount = Math.max(1, ...arcs.features.map(f => f.properties.count));
          arcs.features.forEach(f => f.properties.w = 1 + 4 * (f.properties.count / maxCount));
          collabMap.addSource('arcs', { type: 'geojson', data: arcs });
          collabMap.addLayer({
            id: 'arcs-line', type: 'line', source: 'arcs',
            paint: { 'line-color': '#f59e0b', 'line-opacity': 0.55, 'line-width': ['get', 'w'] },
          });
        });
      });
    });
  });
}

function loadCollabPairs() {
  safeFetch(withInst('/api/collaboration/matrix'), resp => {
    const pairs = resp.data.pairs || [];
    $('collab-pairs').innerHTML = pairs.length ? pairs.slice(0, 40).map(p => `
      <div class="flex items-center justify-between p-2 rounded-lg row-hover">
        <p class="text-xs font-medium" style="color:var(--text)">${esc(p.source_name)} – ${esc(p.target_name)}</p>
        <span class="chip text-[10px] py-0.5 px-2" style="background:#f59e0b18;color:#f59e0b">${p.count}</span>
      </div>`).join('')
      : '<p class="text-xs text-muted italic">No intra-African co-publications recorded yet. Run the collaboration backfill to enrich affiliation data.</p>';
  });
}

function loadCitationVelocity() {
  safeFetch(withInst('/api/citations/velocity'), resp => {
    const d = resp.data || {};
    $('velocity-narrative').textContent = resp.narrative || '';
    const series = d.by_year || [];
    destroyChart('citation-velocity');
    if (!series.length) return;
    charts['citation-velocity'] = new Chart($('chart-citation-velocity'), {
      type: 'line',
      data: {
        labels: series.map(r => r.year),
        datasets: [{
          label: 'Citations received',
          data: series.map(r => r.citations),
          borderColor: '#22c55e', backgroundColor: '#22c55e22',
          fill: true, tension: 0.3, pointRadius: 2,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { y: { beginAtZero: true } },
      },
    });
  }, () => { /* velocity endpoint optional until citation backfill runs */ });
}

const COMMUNITY_COLORS = ['#3b82f6', '#22c55e', '#f59e0b', '#8b5cf6', '#ec4899', '#14b8a6', '#f97316', '#ef4444'];

function loadCollabNetwork() {
  safeFetch('/api/collaboration/network?limit=25', resp => {
    const data = resp.data || { nodes: [], edges: [] };
    const el = $('collab-network');
    el.innerHTML = '';
    if (!data.nodes.length) {
      el.innerHTML = '<p class="text-xs text-muted italic text-center pt-16">No network data yet.</p>';
      return;
    }
    const W = el.offsetWidth || 500, H = 240;
    const svg = d3.select(el).append('svg').attr('viewBox', `0 0 ${W} ${H}`).attr('width', '100%').attr('height', H);
    const nodes = data.nodes.map(n => ({ ...n }));
    const links = data.edges.map(e => ({ ...e }));

    const lnk = svg.append('g').selectAll('line').data(links).enter().append('line')
      .attr('stroke', 'rgba(148,163,184,0.25)').attr('stroke-width', d => Math.max(1, Math.min(d.weight, 4)));
    const nd = svg.append('g').selectAll('circle').data(nodes).enter().append('circle')
      .attr('r', d => 4 + (d.centrality || 0) * 18)
      .attr('fill', d => COMMUNITY_COLORS[(d.community || 0) % COMMUNITY_COLORS.length])
      .attr('stroke', '#fff').attr('stroke-width', 0.8)
      .style('cursor', 'pointer');
    nd.append('title').text(d => `${d.id} — community ${(d.community || 0) + 1}, centrality ${d.centrality || 0}`);

    d3.forceSimulation(nodes)
      .force('link', d3.forceLink(links).id(d => d.id).distance(60))
      .force('charge', d3.forceManyBody().strength(-90))
      .force('center', d3.forceCenter(W / 2, H / 2))
      .on('tick', () => {
        lnk.attr('x1', d => d.source.x).attr('y1', d => d.source.y)
          .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
        nd.attr('cx', d => Math.max(8, Math.min(W - 8, d.x))).attr('cy', d => Math.max(8, Math.min(H - 8, d.y)));
      });
  });
}

/**
 * Special Collections — purpose-built analytics for indigenous knowledge,
 * African literature & cultural-heritage collections. Reframes impact away
 * from the citation-prestige lens of commercial bibliometric platforms.
 */
const SC_EMPTY = '<p class="text-xs text-muted italic text-center py-6">No data yet.</p>';

function scHbar(items, labelKey, valueKey, color, onClick) {
  if (!items || !items.length) return SC_EMPTY;
  const max = Math.max(1, ...items.map(i => i[valueKey]));
  return items.map(i => {
    const pct = Math.round(i[valueKey] / max * 100);
    const click = onClick ? ` onclick="${onClick(i)}" style="cursor:pointer"` : '';
    return `
      <div class="row-hover p-2 rounded-lg"${click}>
        <div class="flex items-center justify-between mb-1">
          <p class="text-xs font-medium truncate" style="color:var(--text);max-width:80%">${esc(i[labelKey])}</p>
          <span class="text-xs font-semibold" style="color:${color}">${i[valueKey]}</span>
        </div>
        <div style="height:5px;border-radius:3px;background:var(--border);overflow:hidden">
          <div style="height:100%;width:${pct}%;background:${color};border-radius:3px"></div>
        </div>
      </div>`;
  }).join('');
}

function loadSpecialTab() {
  $('special-loading').classList.remove('hidden');
  $('special-content').classList.add('hidden');
  safeFetch(withInst('/api/analytics/special-collections'), data => {
    $('special-loading').classList.add('hidden');
    $('special-content').classList.remove('hidden');

    // Stats
    const statsEl = $('special-stats');
    statsEl.innerHTML = `
      <div class="surface rounded-xl p-5 stat-card">
        <p class="section-label">Total Special Items</p>
        <p class="text-3xl font-bold" style="color:var(--accent)">${data.total_special_items}</p>
        <p class="text-xs mt-1 text-muted">${Math.round(data.total_special_items / data.total_repository_items * 100) || 0}% of repository</p>
      </div>
      <div class="surface rounded-xl p-5 stat-card">
        <p class="section-label">Categories Tracked</p>
        <p class="text-3xl font-bold" style="color:var(--success)">${data.summary.length}</p>
      </div>
      <div class="surface rounded-xl p-5 stat-card">
        <p class="section-label">Classification Status</p>
        <p class="text-3xl font-bold" style="color:var(--warning)">OPTIMIZED</p>
      </div>
    `;

    // Categories
    const catEl = $('special-categories');
    catEl.innerHTML = data.summary.map(cat => `
      <div class="surface rounded-xl p-5">
        <div class="flex justify-between items-center mb-4">
          <p class="section-label mb-0">${esc(cat.category)}</p>
          <span class="badge-oa">${cat.count} items</span>
        </div>
        <div class="space-y-2" style="max-height:300px; overflow-y:auto">
          ${cat.top_papers.map(p => `
            <div class="row-hover p-2.5 rounded-lg cursor-pointer border-b" style="border-color:var(--border)" onclick="openPaperModal(${p.id})">
              <p class="text-sm font-medium">${esc(p.title)}</p>
              <div class="flex gap-1 mt-1 flex-wrap">
                ${p.matches.slice(0, 3).map(m => `<span class="chip text-[10px] py-0.5 px-1.5">${esc(m)}</span>`).join('')}
              </div>
            </div>
          `).join('')}
          ${cat.count === 0 ? '<p class="text-xs text-center py-4 text-muted">No items found.</p>' : ''}
        </div>
      </div>
    `).join('');
  });
}

/**
 * D3 chord diagram of theme co-occurrence. data = {labels:[...], matrix:[[...]]}.
 * Mirrors the D3 SVG approach used by loadCollabNetwork.
 */
function renderScChord(data) {
  const el = $('sco-chord');
  if (!el) return;
  el.innerHTML = '';
  const labels = data.labels || [], matrix = data.matrix || [];
  const hasLinks = matrix.some(row => row.some(v => v > 0));
  if (!labels.length || !hasLinks || typeof d3 === 'undefined') {
    el.innerHTML = SC_EMPTY;
    return;
  }
  const W = el.offsetWidth || 400, H = 280;
  const outer = Math.min(W, H) * 0.5 - 18, inner = outer - 12;
  const svg = d3.select(el).append('svg')
    .attr('viewBox', `0 0 ${W} ${H}`).attr('width', '100%').attr('height', H)
    .append('g').attr('transform', `translate(${W / 2},${H / 2})`);

  const chord = d3.chord().padAngle(0.05).sortSubgroups(d3.descending)(matrix);
  const arc = d3.arc().innerRadius(inner).outerRadius(outer);
  const ribbon = d3.ribbon().radius(inner);
  const color = i => COLORS[i % COLORS.length];

  const group = svg.append('g').selectAll('g').data(chord.groups).enter().append('g');
  group.append('path').attr('d', arc)
    .attr('fill', d => color(d.index)).attr('stroke', 'rgba(0,0,0,0.15)')
    .append('title').text(d => `${labels[d.index]} — ${d.value} co-tags`);
  group.append('text')
    .each(d => { d.angle = (d.startAngle + d.endAngle) / 2; })
    .attr('dy', '0.35em')
    .attr('transform', d => `rotate(${d.angle * 180 / Math.PI - 90}) translate(${outer + 6}) ${d.angle > Math.PI ? 'rotate(180)' : ''}`)
    .attr('text-anchor', d => d.angle > Math.PI ? 'end' : 'start')
    .style('font-size', '9px').style('fill', 'var(--text-muted)')
    .text(d => labels[d.index]);

  svg.append('g').attr('fill-opacity', 0.6).selectAll('path').data(chord).enter().append('path')
    .attr('d', ribbon)
    .attr('fill', d => color(d.source.index))
    .attr('stroke', 'rgba(0,0,0,0.1)')
    .append('title').text(d => `${labels[d.source.index]} ↔ ${labels[d.target.index]}: ${d.source.value}`);
}

/**
 * Language & Culture
 */
let chartLanguageInst = null;
function loadLanguageTab() {
  const url = withInst('/api/analytics/language-research');
  safeFetch(url, data => {
    // 1. Render Keywords Chart
    const ctx = $('chart-language-kw');
    if (ctx && data.top_keywords) {
      if (chartLanguageInst) chartLanguageInst.destroy();
      chartLanguageInst = new Chart(ctx, {
        type: 'bar',
        data: {
          labels: data.top_keywords.map(k => k.keyword),
          datasets: [{
            label: 'Mentions',
            data: data.top_keywords.map(k => k.count),
            backgroundColor: 'rgba(79, 70, 229, 0.8)',
            borderRadius: 4
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: {
            x: { ticks: { font: { family: 'Inter', size: 10 } } },
            y: { beginAtZero: true, ticks: { font: { family: 'Inter', size: 10 } } }
          }
        }
      });
    }
    
    // 2. Render Papers List
    const papersEl = $('language-papers');
    if (papersEl) {
      if (!data.papers || data.papers.length === 0) {
        papersEl.innerHTML = '<p class="text-sm text-center py-6 text-muted">No language research papers found for this institution.</p>';
      } else {
        papersEl.innerHTML = data.papers.map(p => `
          <div class="surface rounded-lg p-3 row-hover cursor-pointer border-b" style="border-color:var(--border)" onclick="openPaperModal(${p.id})">
            <p class="text-sm font-semibold mb-1">${esc(p.title)}</p>
            <div class="flex justify-between items-center mt-2">
              <p class="text-xs text-muted">${esc((p.authors || []).join(', '))}</p>
              <div class="flex gap-1 flex-wrap justify-end">
                ${(p.matched_terms || []).slice(0, 3).map(m => `<span class="chip text-[9px] py-0.5 px-1.5" style="background:var(--accent-10);color:var(--accent)">${esc(m)}</span>`).join('')}
              </div>
            </div>
          </div>
        `).join('');
      }
    }
  });
}

/**
 * Staff Directory
 */
function loadStaffDirectory() {
  const filterInst = $('staff-inst-filter')?.value || '';
  const url = filterInst ? '/api/analytics/staff-directory?institution=' + filterInst : '/api/analytics/staff-directory';
  
  $('staff-loading')?.classList.remove('hidden');
  $('staff-content')?.classList.add('hidden');
  
  safeFetch(url, data => {
    $('staff-loading')?.classList.add('hidden');
    $('staff-content')?.classList.remove('hidden');
    
    const container = $('staff-institutions-list');
    if (!container) return;
    
    if (!data || data.length === 0) {
      container.innerHTML = '<p class="text-sm text-center py-8 text-muted">No staff records found.</p>';
      return;
    }
    
    container.innerHTML = data.map(inst => `
      <div class="surface rounded-2xl p-5 mb-4 border" style="border-color:var(--border)">
        <div class="flex items-center justify-between mb-4 border-b pb-3" style="border-color:var(--border)">
          <div>
            <h3 class="text-lg font-bold" style="color:var(--accent)">${esc(inst.institution)}</h3>
            <p class="text-xs text-muted mt-1">${inst.staff_count} Dynamic Staff Records • ${inst.staff_with_orcid} with ORCID</p>
          </div>
          <span class="badge-oa">${esc(inst.country)}</span>
        </div>
        
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          ${(inst.staff || []).map(s => `
            <div class="surface rounded-xl p-3 border hover:border-[var(--accent)] transition-colors" style="border-color:var(--border)">
              <p class="font-semibold text-sm mb-1">${esc(s.name)}</p>
              ${s.department ? `<p class="text-xs text-muted mb-2 line-clamp-1">${esc(s.department)}</p>` : ''}
              
              <div class="space-y-1">
                ${s.orcid ? `
                  <div class="flex items-center gap-1.5 text-xs">
                    <span class="w-10 font-bold" style="color:var(--success)">ORCID</span>
                    <span class="font-mono bg-white/5 px-1 rounded">${esc(s.orcid)}</span>
                  </div>
                ` : `<p class="text-[10px] text-muted italic">No ORCID</p>`}
                
                ${s.ror ? `
                  <div class="flex items-center gap-1.5 text-xs">
                    <span class="w-10 font-bold" style="color:var(--warning)">ROR</span>
                    <span class="font-mono bg-white/5 px-1 rounded">${esc(s.ror)}</span>
                  </div>
                ` : `<p class="text-[10px] text-muted italic">No ROR Verified</p>`}
              </div>
              
              <div class="mt-3 pt-2 border-t flex justify-between" style="border-color:var(--border)">
                <span class="text-[10px] text-muted">Papers Tracked</span>
                <span class="text-xs font-bold" style="color:var(--accent)">${s.paper_count}</span>
              </div>
            </div>
          `).join('')}
        </div>
        ${inst.staff?.length === 0 ? '<p class="text-sm italic text-muted">No authors tracked for this institution yet.</p>' : ''}
      </div>
    `).join('');
  });
}

/**
 * Crawler Management
 */
function startCrawler() {
  const s = $('btn-start'); if (s) s.disabled = true;
  const inst = $('crawler-institution').value;
  const t = Math.min(Math.max(parseInt($('target-count').value) || 20, 1), 250);
  // Spider select: prefer the dropdown if present, otherwise default to openalex.
  // The OpenAlex spider discovers SC papers from across the open web (journals,
  // preprint servers, grey literature indexed by OpenAlex) and is the primary
  // discovery engine. The "oai" spider reads FROM the institution's own IR (for
  // dedup reference) and should NOT be the default discovery source.
  const spiderEl = $('crawler-spider');
  const spider = spiderEl ? spiderEl.value : 'openalex';

  appendLog('// Starting ' + spider.toUpperCase() + ' harvest for ' + inst + ' — target: ' + t + ' SC papers');
  toast('Harvest started for ' + inst + ' (' + spider + ')', 'info');
  updateCrawlerUI({ status: 'initializing' });

  const body = { target: t, institution: inst, spider: spider };
  if (spider === 'oai') {
    const fromEl = $('oai-from-date');
    if (fromEl && fromEl.value) body.from_date = fromEl.value;
  } else {
    body.boost_special = true;
    body.sc_only = false;
  }

  fetch('/api/crawler/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  })
  .then(r => r.json())
  .then(d => {
    if (s) s.disabled = false;
    if (d.status !== 'success') {
      appendLog('// Error: ' + d.message);
      toast(d.message, 'error');
      if (d.message !== 'Crawler already running') updateCrawlerUI({ status: 'stopped' });
    }
  })
  .catch(() => {
    if (s) s.disabled = false;
    updateCrawlerUI({ status: 'stopped' });
  });
}

function stopCrawler() {
  fetch('/api/crawler/stop', { method: 'POST' })
    .then(r => r.json())
    .then(d => toast(d.message, d.status === 'success' ? 'warning' : 'error'));
}

function pruneNonSC(apply) {
  if (apply && !confirm(
    'This will permanently delete all non-Special-Collection papers from the database.\n\n' +
    'Run "Dry Run Prune" first to preview what will be removed.\n\nProceed?'
  )) return;

  const label = apply ? 'Pruning non-SC papers…' : 'Running dry-run prune…';
  toast(label, 'info');

  fetch('/api/admin/prune-non-sc', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ apply }),
  })
    .then(r => r.json())
    .then(d => {
      if (d.status !== 'success') { toast(d.message || 'Error', 'error'); return; }
      const msg = apply
        ? `Pruned ${d.pruned_non_sc} non-SC papers. ${d.kept_sc} SC papers kept.`
        : `Dry run: would remove ${d.pruned_non_sc} non-SC papers, keep ${d.kept_sc} SC papers.`;
      toast(msg, apply ? 'success' : 'warning');
      if (d.sample_dropped && d.sample_dropped.length) {
        console.log('[Prune] sample dropped:', d.sample_dropped);
        appendLog('[PRUNE] ' + (apply ? 'APPLIED' : 'DRY RUN') + ` — drop=${d.pruned_non_sc} keep=${d.kept_sc}`);
        d.sample_dropped.slice(0, 5).forEach(p =>
          appendLog(`  DROP: [${p.institution}] ${p.title}`)
        );
      }
      if (apply) { fetchOverview(); invalidateCaches(); if (analyticsLoaded) loadAnalyticsOverview(); }
    })
    .catch(e => toast('Prune failed: ' + e.message, 'error'));
}

function testSMTP() {
  toast('Sending SMTP test email…', 'info');
  fetch('/api/admin/test-smtp', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  })
    .then(r => r.json())
    .then(d => {
      if (d.status === 'success') toast(d.message, 'success');
      else toast('SMTP error: ' + d.message, 'error');
    })
    .catch(e => toast('SMTP test failed: ' + e.message, 'error'));
}

function recomputeAlignment() {
  toast('Scoring papers against AU framework pillars… this may take 10-30 s', 'info');
  fetch('/api/admin/recompute-alignment', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  })
    .then(r => r.json())
    .then(d => {
      if (d.status === 'success')
        toast(`Alignment done — ${d.scored} papers scored, ${d.aggregate_rows} pillar aggregates built`, 'success');
      else
        toast('Alignment error: ' + d.message, 'error');
    })
    .catch(e => toast('Alignment recompute failed: ' + e.message, 'error'));
}

function updateCrawlerUI(d) {
  const badge = $('crawler-badge'), s = $('btn-start'), st = $('btn-stop'), bar = $('crawler-progress');
  if (d.status === 'running') {
    if (badge) {
      badge.innerHTML = '<span class="live-dot"></span>Running';
      badge.style.background = 'rgba(16,197,94,0.12)';
      badge.style.color = '#10b981';
    }
    s?.classList.add('hidden');
    st?.classList.remove('hidden');
    bar?.classList.add('active');
  } else if (d.status === 'initializing') {
    if (badge) badge.textContent = '⟳ Init…';
    s?.classList.add('hidden');
    st?.classList.remove('hidden');
    bar?.classList.add('active');
  } else {
    if (badge) badge.textContent = '●Idle';
    s?.classList.remove('hidden');
    st?.classList.add('hidden');
    bar?.classList.remove('active');
    setTimeout(() => {
      fetchOverview(); fetchArchive(); fetchRecentPapers(); invalidateCaches();
      if (analyticsLoaded && currentAtab === 'overview') loadAnalyticsOverview();
    }, 2000);
  }
}

function appendLog(text, termId = 'terminal-log') {
  const term = $(termId); if (!term) return;
  const d = document.createElement('div');
  const t = new Date().toLocaleTimeString('en', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
  d.innerHTML = `<span class="text-slate-500">[${t}]</span> ${esc(text)}`;
  
  if (/\[OK\]|stored|success/i.test(text)) d.style.color = '#4ade80';
  else if (/error|ERROR|\[ERR\]/i.test(text)) d.style.color = '#f87171';
  else if (/skip|duplicate|warn/i.test(text)) d.style.color = '#fbbf24';
  
  term.appendChild(d);
  term.scrollTop = term.scrollHeight;
  while (term.children.length > 200) term.removeChild(term.firstChild);
}

socket.on('crawl_status', updateCrawlerUI);
socket.on('terminal_output', d => appendLog(d.line));
socket.on('crawl_progress', d => { if (d.title) appendLog('[OK] ' + d.title); });

/**
 * Archive Directory
 */
function fetchArchive() {
  const inst = $('archive-institution-select')?.value || '';
  safeFetch('/api/papers/tree' + (inst ? '?institution=' + inst : ''), d => {
    archiveData = d.data || {};
    renderTree(archiveData);
  });
}

function renderTree(data, q = '') {
  const c = $('tree-container'); if (!c) return;
  if (!data || !Object.keys(data).length) {
    c.innerHTML = '<p class="text-sm py-10 text-center text-muted">No papers indexed yet.</p>';
    return;
  }
  
  let html = '', total = 0;
  for (const [fac, depts] of Object.entries(data)) {
    let fhtml = '', fc = 0;
    for (const [dept, papers] of Object.entries(depts)) {
      const filtered = q ? papers.filter(p => (p.title || '').toLowerCase().includes(q) || (p.doi || '').toLowerCase().includes(q)) : papers;
      if (!filtered.length) continue;
      fc += filtered.length; total += filtered.length;
      fhtml += `
        <div class="tree-node mb-4">
          <div class="flex items-center gap-2 mb-2">
            <span class="text-xs font-bold text-accent">${esc(dept)}</span>
            <span class="text-[10px] px-1.5 rounded bg-slate-800 text-slate-400 font-mono">${filtered.length}</span>
          </div>
          <ul class="space-y-1.5 ml-2">
            ${filtered.map(p => `
              <li class="row-hover p-2.5 rounded-lg cursor-pointer" onclick="openPaperModal(${p.id})">
                <p class="text-sm font-medium leading-tight">${esc(p.title || 'Untitled')}</p>
                <div class="flex justify-between items-center mt-1.5">
                  <span class="text-[10px] font-mono text-muted">${(p.doi || '').substring(0, 30)}</span>
                  <span class="${p.has_local_pdf ? 'badge-oa' : 'badge-restricted'} text-[9px]">${p.has_local_pdf ? 'PDF' : 'LINK'}</span>
                </div>
              </li>`).join('')}
          </ul>
        </div>`;
    }
    if (fc > 0) {
      html += `
        <div class="mb-6">
          <div class="flex items-center gap-2 border-b border-white/5 pb-2 mb-3">
            <span class="text-sm font-bold text-slate-200">${esc(fac)}</span>
            <span class="text-[10px] font-bold px-2 py-0.5 rounded-full bg-accent/10 text-accent">${fc}</span>
          </div>
          ${fhtml}
        </div>`;
    }
  }
  c.innerHTML = html || '<p class="text-sm text-center py-10 text-muted">No results found.</p>';
  const b = $('total-papers-badge'); if (b) b.textContent = total.toLocaleString() + ' papers';
}

/**
 * Paper Details Modal
 */
function openPaperModal(id) {
  $('paper-modal').classList.add('open');
  $('modal-body').innerHTML = '<div class="flex justify-center py-12"><div class="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin"></div></div>';
  
  Promise.all([
    fetch('/api/papers/' + id).then(r => r.json()),
    fetch('/api/citations/' + id).then(r => r.json()).catch(() => ({ citation_count: 0 }))
  ]).then(([p, cit]) => {
    $('modal-title').textContent = p.title;
    const authors = (p.authors || []).map(a => esc(a.name)).join('; ');
    
    const fileBtn = p.file?.has_local_pdf
      ? `<a href="${p.file.download_url}" class="btn-primary text-sm">Download PDF</a>`
      : (p.pdf_url ? `<a href="${p.pdf_url}" target="_blank" class="btn-primary text-sm">View PDF</a>` : '');
      
    $('modal-body').innerHTML = `
      <div class="space-y-6">
        <div class="flex gap-2 flex-wrap">${fileBtn} ${p.doi ? `<a href="https://doi.org/${p.doi}" target="_blank" class="btn-ghost text-xs">View DOI</a>` : ''}</div>
        
        <div class="surface p-5 rounded-xl space-y-3">
          <p class="section-label mb-2">Metadata</p>
          ${metadataRow('Title', p.title)}
          ${metadataRow('Authors', authors)}
          ${metadataRow('Date', p.publication_date?.split('T')[0] || '—')}
          ${metadataRow('DOI', p.doi || '—')}
          ${metadataRow('Source', p.source_repository || '—')}
          ${metadataRow('Citations', cit.citation_count)}
        </div>

        ${p.abstract ? `
          <div class="surface p-5 rounded-xl">
            <p class="section-label mb-2">Abstract</p>
            <p class="text-sm leading-relaxed text-slate-300">${esc(p.abstract)}</p>
          </div>` : ''}
      </div>`;
  }).catch(err => {
    $('modal-body').innerHTML = `<p class="text-sm text-center py-10">Failed to load: ${err.message}</p>`;
  });
}

function metadataRow(l, v) {
  return `<div class="flex text-xs border-b border-white/5 pb-2 last:border-0 last:pb-0">
    <span class="w-24 text-muted flex-shrink-0 font-bold uppercase tracking-wider">${l}</span>
    <span class="text-slate-200">${esc(v)}</span>
  </div>`;
}

function closePaperModal() { $('paper-modal').classList.remove('open'); }

/**
 * Search Functions
 */
function runAdvancedSearch() {
  const q = ($('search-q').value || '').trim();
  const sort = $('search-sort').value || 'relevance';
  const yf = $('search-year-from').value, yt = $('search-year-to').value;
  const oa = $('search-oa-only').checked;
  
  const hasPdf = $('search-has-pdf') && $('search-has-pdf').checked;
  let url = `/api/search/advanced?limit=50&q=${encodeURIComponent(q)}&sort=${sort}`;
  if (yf) url += '&year_from=' + yf;
  if (yt) url += '&year_to=' + yt;
  if (oa) url += '&oa_only=true';
  if (hasPdf) url += '&has_pdf=true';
  
  const el = $('search-results'), cnt = $('search-result-count');
  el.innerHTML = '<div class="flex justify-center py-12"><div class="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin"></div></div>';
  
  safeFetch(url, data => {
    const items = data.results || [];
    if (cnt) cnt.textContent = `${data.total || 0} results in ${data.took_ms || 0}ms`;
    
    if (!items.length) {
      el.innerHTML = '<p class="text-sm text-center py-10 text-muted">No results found.</p>';
      return;
    }
    
    el.innerHTML = items.map(i => `
      <div class="surface rounded-xl p-5 row-hover cursor-pointer mb-3" onclick="openPaperModal(${i.id})">
        <div class="flex justify-between items-start gap-4">
          <div class="flex-1">
            <p class="text-base font-bold text-slate-100">${esc(i.title)}</p>
            <p class="text-xs text-muted mt-1">${(i.authors || []).slice(0, 5).join(', ')}</p>
            ${i.abstract ? `<p class="text-xs text-slate-400 mt-2 line-clamp-2 italic">${esc(i.abstract)}</p>` : ''}
          </div>
          <div class="text-right">
            <span class="${i.is_oa ? 'badge-oa' : 'badge-restricted'}">${i.is_oa ? 'OA' : 'RES'}</span>
            <p class="text-xs text-muted mt-2">${i.year || ''}</p>
          </div>
        </div>
      </div>`).join('');
  });
}

function runSearch() { runAdvancedSearch(); }

function clearSearch() {
  ['search-q', 'search-year-from', 'search-year-to'].forEach(id => { const el = $(id); if (el) el.value = ''; });
  const oa = $('search-oa-only'); if (oa) oa.checked = false;
  const pdf = $('search-has-pdf'); if (pdf) pdf.checked = false;
  const sort = $('search-sort'); if (sort) sort.value = 'relevance';
  const res = $('search-results'); if (res) res.innerHTML = '';
  const cnt = $('search-result-count'); if (cnt) cnt.textContent = '';
}

function loadSearchFaculties() {
  safeFetch('/api/analytics/faculties', facs => {
    const sel = $('search-faculty');
    if (sel && sel.options.length <= 1) facs.forEach(f => {
      const o = document.createElement('option');
      o.value = f; o.textContent = f.replace('Faculty of ', '');
      sel.appendChild(o);
    });
  });
}

/**
 * Dashboard Data Fetchers
 */
function fetchOverview() {
  safeFetch('/api/analytics/overview', d => {
    // Header Stats
    animCount($('stat-total'), d.total_papers);
    animCount($('stat-authors'), d.total_authors);
    animCount($('stat-oa'), d.open_access_papers);
    
    // Impact Cards
    animCount($('ic-total'), d.total_papers);
    animCount($('ic-authors'), d.total_authors);
    animCount($('ic-faculties'), d.total_faculties);
    animCount($('ic-oa'), d.open_access_papers);
    animCount($('ic-oa-rate'), d.oa_percentage, '%');
    animCount($('ic-pdfs'), d.papers_with_local_pdf);
  });
}

function fetchRecentPapers() {
  safeFetch('/api/analytics/recent-papers?limit=5', data => {
    const el = $('recent-papers');
    if (!el) return;
    el.innerHTML = data.map(p => `
      <div class="row-hover p-3 rounded-lg cursor-pointer border-b border-white/5 last:border-0" onclick="openPaperModal(${p.id})">
        <div class="flex justify-between items-start mb-1">
          <p class="text-sm font-semibold text-slate-100 line-clamp-1">${esc(p.title)}</p>
          <span class="${p.is_oa ? 'badge-oa' : 'badge-restricted'} text-[9px] px-1.5 py-0.5 ml-2">${p.is_oa ? 'OA' : 'RES'}</span>
        </div>
        <div class="flex justify-between items-center">
          <p class="text-[10px] text-slate-400 font-medium">${esc((p.authors || []).join(', '))}</p>
          <p class="text-[9px] text-slate-500 font-mono uppercase tracking-wider">${p.doi ? 'DOI Indexed' : 'Local Only'}</p>
        </div>
      </div>
    `).join('') || '<p class="text-xs text-center py-6 text-muted italic">No papers recently harvested.</p>';
  });
}

// Populate the crawler institution dropdown, filtered by the selected region.
function loadCrawlerInstitutions() {
  loadInstitutionsCache(() => populateCrawlerInstitutions());
}

function onCrawlerRegionChange() {
  populateCrawlerInstitutions();
}

function populateCrawlerInstitutions() {
  const sel = $('crawler-institution');
  if (!sel) return;
  const list = window.institutionsCache || [];
  const region = $('crawler-region') ? $('crawler-region').value : '';
  const current = sel.value;
  const filtered = region ? list.filter(i => (i.sub_region || 'Unknown') === region) : list;
  sel.innerHTML = '';
  if (!filtered.length) {
    const opt = document.createElement('option');
    opt.value = ''; opt.textContent = 'No institutions in this region';
    sel.appendChild(opt);
    return;
  }
  filtered
    .slice()
    .sort((a, b) => (a.name || '').localeCompare(b.name || ''))
    .forEach(inst => {
      const opt = document.createElement('option');
      opt.value = (inst.short_name || '').toLowerCase();
      opt.textContent = `${inst.name} (${inst.short_name})`;
      sel.appendChild(opt);
    });
  // Preserve the previous selection if it survived the filter.
  if (current && [...sel.options].some(o => o.value === current)) sel.value = current;
}

/**
 * Generic UI helpers (live-feed clear, archive filter, chart fullscreen)
 */
function clearTerm(id) {
  const term = $(id);
  if (term) term.innerHTML = '<div style="color:#334155">// Cleared.</div>';
}

function filterArchive(q) {
  renderTree(archiveData, (q || '').toLowerCase());
}

let fsChart = null;
function openFS(chartId, title) {
  const src = charts[chartId];
  if (!src) { toast('Chart not ready', 'warning'); return; }
  const overlay = $('fs-overlay'); if (!overlay) return;
  const titleEl = $('fs-title'); if (titleEl) titleEl.textContent = title || '';
  overlay.classList.add('open');
  if (fsChart) { try { fsChart.destroy(); } catch (e) {} fsChart = null; }
  // Clone the source chart's config into the fullscreen canvas.
  const cfg = { type: src.config.type, data: src.config.data, options: { ...src.config.options, maintainAspectRatio: false } };
  fsChart = new Chart($('fs-canvas'), cfg);
}

function closeFullscreen() {
  const overlay = $('fs-overlay'); if (overlay) overlay.classList.remove('open');
  if (fsChart) { try { fsChart.destroy(); } catch (e) {} fsChart = null; }
}

function downloadNetData() {
  if (!networkEdgeData || !networkEdgeData.length) { toast('No network data to export', 'warning'); return; }
  const rows = [['Source', 'Target', 'Joint Papers']];
  networkEdgeData.forEach(e => rows.push([e.source, e.target, e.weight]));
  const csv = rows.map(r => r.map(c => `"${String(c).replace(/"/g, '""')}"`).join(',')).join('\n');
  const blob = new Blob([csv], { type: 'text/csv' });
  const a = document.createElement('a');
  a.href = window.URL.createObjectURL(blob);
  a.download = `collaboration_network_${new Date().toISOString().split('T')[0]}.csv`;
  document.body.appendChild(a); a.click();
  window.URL.revokeObjectURL(a.href); a.remove();
}

/**
 * Faculty / Department comparison (analytics → Compare sub-tab)
 */
function runFacComparison() {
  const facs = ['cmp-faculty-a', 'cmp-faculty-b', 'cmp-faculty-c']
    .map(id => $(id) ? $(id).value : '').filter(Boolean);
  if (facs.length < 2) { toast('Select at least 2 faculties', 'warning'); return; }
  const qs = facs.map(f => 'faculty=' + encodeURIComponent(f)).join('&');
  safeFetch('/api/analytics/faculty-comparison?' + qs, data => {
    const el = $('faculty-comparison-result'); if (!el) return;
    const entries = Object.entries(data || {});
    if (!entries.length) { el.innerHTML = '<p class="text-sm text-muted py-4">No comparison data.</p>'; return; }
    el.innerHTML = `
      <div class="overflow-x-auto"><table class="w-full text-sm">
        <thead><tr style="border-bottom:1px solid var(--border);color:var(--text-muted)">
          <th class="text-left py-2 px-2">Faculty</th><th class="text-right py-2 px-2">Papers</th>
          <th class="text-right py-2 px-2">OA Rate</th><th class="text-right py-2 px-2">Authors</th>
          <th class="text-right py-2 px-2">Departments</th>
        </tr></thead><tbody>
        ${entries.map(([name, m]) => `
          <tr class="row-hover border-b border-white/5">
            <td class="py-2 px-2 font-medium">${esc(name)}</td>
            <td class="py-2 px-2 text-right">${(m.total_papers || 0).toLocaleString()}</td>
            <td class="py-2 px-2 text-right">${m.oa_rate || 0}%</td>
            <td class="py-2 px-2 text-right">${(m.unique_authors || 0).toLocaleString()}</td>
            <td class="py-2 px-2 text-right">${m.departments || 0}</td>
          </tr>`).join('')}
        </tbody></table></div>`;
  });
}

function runDeptComparison() {
  const faculty = $('dept-cmp-faculty') ? $('dept-cmp-faculty').value : '';
  if (!faculty) { toast('Select a faculty', 'warning'); return; }
  safeFetch('/api/analytics/department-comparison?faculty=' + encodeURIComponent(faculty), data => {
    destroyChart('dept-compare');
    const entries = Object.entries(data || {});
    if (!entries.length) { toast('No departments found', 'info'); return; }
    charts['dept-compare'] = new Chart($('chart-dept-compare'), {
      type: 'bar',
      data: {
        labels: entries.map(([name]) => name),
        datasets: [
          { label: 'Open Access', data: entries.map(([, m]) => m.open_access || 0), backgroundColor: 'rgba(16,185,129,0.7)', borderRadius: 4 },
          { label: 'Restricted', data: entries.map(([, m]) => m.restricted || 0), backgroundColor: 'rgba(239,68,68,0.5)', borderRadius: 4 }
        ]
      },
      options: { indexAxis: 'y', plugins: { legend: { position: 'bottom' } }, scales: { x: { stacked: true, beginAtZero: true }, y: { stacked: true, grid: { display: false } } } }
    });
  });
}

/**
 * Lecturer / Researcher profile (analytics → Lecturer sub-tab)
 */
let authorSearchTimer = null;
function debAuthorSearch() { clearTimeout(authorSearchTimer); authorSearchTimer = setTimeout(searchLecturer, 300); }

function searchLecturer() {
  const input = $('lecturer-search-input'); if (!input) return;
  const q = input.value.trim();
  const sugg = $('author-suggestions');
  if (q.length < 2) { if (sugg) sugg.innerHTML = ''; return; }
  safeFetch(withInst('/api/analytics/authors-search?q=' + encodeURIComponent(q) + '&limit=8'), authors => {
    if (!sugg) return;
    if (!authors.length) { sugg.innerHTML = '<p class="text-xs p-2 text-muted">No researchers found</p>'; return; }
    sugg.innerHTML = authors.map(a =>
      `<button class="chip" onclick="loadLecturerProfile('${esc(a.name).replace(/'/g, "\\'")}')">${esc(a.name)} <span style="opacity:0.6">(${a.papers})</span></button>`
    ).join('');
  });
}

function loadLecturerProfile(name) {
  const input = $('lecturer-search-input'); if (input) input.value = name;
  const sugg = $('author-suggestions'); if (sugg) sugg.innerHTML = '';
  const el = $('lecturer-profile-result'); if (!el) return;
  el.innerHTML = '<div class="flex justify-center py-8"><div class="w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin"></div></div>';
  safeFetch('/api/analytics/lecturer-profile?name=' + encodeURIComponent(name), p => {
    if (p.error) { el.innerHTML = `<p class="text-sm text-muted py-4">${esc(p.error)}</p>`; return; }
    el.innerHTML = `
      <div class="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
        <div class="surface rounded-xl p-4 stat-card"><p class="section-label">Papers</p><p class="text-2xl font-bold" style="color:var(--accent)">${p.total_papers}</p></div>
        <div class="surface rounded-xl p-4 stat-card"><p class="section-label">Open Access</p><p class="text-2xl font-bold" style="color:var(--success)">${p.open_access}</p></div>
        <div class="surface rounded-xl p-4 stat-card"><p class="section-label">OA Rate</p><p class="text-2xl font-bold" style="color:var(--warning)">${p.oa_rate}%</p></div>
        <div class="surface rounded-xl p-4 stat-card"><p class="section-label">Active Years</p><p class="text-2xl font-bold">${(p.active_years || []).length}</p></div>
      </div>
      ${(p.faculties || []).length ? `<p class="text-xs text-muted mb-1">Faculties: ${p.faculties.map(esc).join(', ')}</p>` : ''}
      ${(p.top_collaborators || []).length ? `<p class="section-label mt-3">Top Collaborators</p>
        <div class="flex flex-wrap gap-2 mb-3">${p.top_collaborators.map(c => `<span class="chip">${esc(c.name)} (${c.papers})</span>`).join('')}</div>` : ''}
      <p class="section-label mt-3">Recent Papers</p>
      <div class="space-y-1.5">${(p.papers || []).map(pp => `
        <div class="row-hover p-2.5 rounded-lg cursor-pointer border-b" style="border-color:var(--border)" onclick="openPaperModal(${pp.id})">
          <p class="text-sm font-medium">${esc(pp.title)}</p>
          <span class="text-[10px] text-muted">${pp.year || ''}</span>
          <span class="${pp.is_oa ? 'badge-oa' : 'badge-restricted'} text-[9px] ml-2">${pp.is_oa ? 'OA' : 'RES'}</span>
        </div>`).join('') || '<p class="text-xs text-muted py-2">No papers.</p>'}</div>`;
  }, () => { el.innerHTML = '<p class="text-sm text-muted py-4">Failed to load profile.</p>'; });
}

/**
 * Initializers
 */
document.addEventListener('DOMContentLoaded', () => {
  // Restore theme
  const savedTheme = localStorage.getItem('uraas-theme') || 'dark';
  document.documentElement.setAttribute('data-theme', savedTheme);
  
  fetchOverview();
  fetchArchive();
  fetchRecentPapers();
  loadCrawlerInstitutions();
  initMethodologyTooltips();

  // ARK resolver deep-link: /?paper=<id> opens that paper's modal on load.
  const paperParam = new URLSearchParams(window.location.search).get('paper');
  if (paperParam && /^\d+$/.test(paperParam)) {
    setTimeout(() => openPaperModal(parseInt(paperParam, 10)), 300);
  }
  
  // Stats Auto-Refresh
  setInterval(() => {
    const badge = $('crawler-badge');
    if (badge && badge.textContent.includes('Running')) {
      fetchOverview(); fetchRecentPapers();
      if (analyticsLoaded && currentAtab === 'overview') { invalidateCaches(); loadAnalyticsOverview(); }
    }
  }, 30000);
});

// Keyboard Shortcuts
document.addEventListener('keydown', e => {
  if (['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) return;
  if (e.key === '1') switchTab('crawler');
  if (e.key === '2') switchTab('archive');
  if (e.key === '3') switchTab('search');
  if (e.key === '4') switchTab('analytics');
  if (e.key === '5') switchTab('comparator');
  if (e.key === 'Escape') { closePaperModal(); closeMethodologyTooltip(); }
  if (e.key === 't' || e.key === 'T') toggleTheme();
});

// ─────────────────────────────────────────────────────────────────────────────
// Phase 6: CREDIBILITY LAYER — Methodology Tooltips, ARK PIDs, Benchmarks
// ─────────────────────────────────────────────────────────────────────────────

let _methodologyCache = null;

/**
 * Fetch the methodology dictionary once; subsequent calls use the cache.
 * Returns a Promise resolving to the METHODOLOGY dict.
 */
function getMethodology() {
  if (_methodologyCache) return Promise.resolve(_methodologyCache);
  return fetch('/api/methodology', { cache: 'force-cache' })
    .then(r => r.json())
    .then(resp => { _methodologyCache = resp.data || {}; return _methodologyCache; })
    .catch(() => ({}));
}

/**
 * Render and attach the floating methodology tooltip DOM node (singleton).
 * Called once on DOMContentLoaded.
 */
function initMethodologyTooltips() {
  // Inject tooltip container
  if (!$('method-tooltip')) {
    const el = document.createElement('div');
    el.id = 'method-tooltip';
    el.className = 'method-tooltip hidden';
    el.innerHTML = `
      <div class="method-tooltip-inner">
        <div class="flex justify-between items-start mb-2">
          <p id="method-tooltip-title" class="text-xs font-bold" style="color:var(--accent)"></p>
          <button onclick="closeMethodologyTooltip()" class="text-muted ml-2 hover:text-white" style="font-size:14px;line-height:1">×</button>
        </div>
        <p id="method-tooltip-formula" class="text-xs leading-relaxed mb-2" style="color:var(--text)"></p>
        <div id="method-tooltip-bench" class="hidden text-xs mb-2 p-2 rounded" style="background:rgba(34,197,94,0.08);border:1px solid rgba(34,197,94,0.2)"></div>
        <div id="method-tooltip-source" class="text-[10px]" style="color:var(--text-muted)"></div>
        <p id="method-tooltip-caveats" class="text-[10px] mt-1 italic" style="color:var(--text-muted)"></p>
      </div>`;
    document.body.appendChild(el);
  }

  // Inject CSS for tooltip
  if (!$('method-tooltip-style')) {
    const style = document.createElement('style');
    style.id = 'method-tooltip-style';
    style.textContent = `
      .method-tooltip {
        position: fixed; z-index: 9999; max-width: 360px;
        background: var(--modal-bg, #1e293b);
        border: 1px solid var(--border, rgba(255,255,255,0.08));
        border-radius: 12px; padding: 14px; box-shadow: 0 8px 32px rgba(0,0,0,0.5);
        pointer-events: auto; transition: opacity 0.15s;
      }
      .method-tooltip.hidden { display: none !important; }
      .info-icon {
        cursor: pointer; font-size: 12px; opacity: 0.6;
        transition: opacity 0.15s; color: var(--accent, #6366f1);
        user-select: none;
      }
      .info-icon:hover { opacity: 1; }
      .chart-narrative {
        font-style: italic; min-height: 16px;
      }
    `;
    document.head.appendChild(style);
  }

  // Wire all existing .info-icon elements
  document.querySelectorAll('.info-icon[data-method]').forEach(icon => {
    icon.addEventListener('click', e => {
      e.stopPropagation();
      showMethodologyTooltip(icon.dataset.method, icon);
    });
  });

  // Also wire dynamically added icons (event delegation)
  document.body.addEventListener('click', e => {
    const icon = e.target.closest('.info-icon[data-method]');
    if (icon) {
      e.stopPropagation();
      showMethodologyTooltip(icon.dataset.method, icon);
    }
  });

  // Close on backdrop click
  document.body.addEventListener('click', e => {
    const tt = $('method-tooltip');
    if (tt && !tt.classList.contains('hidden') && !tt.contains(e.target) && !e.target.closest('.info-icon')) {
      closeMethodologyTooltip();
    }
  });
}

function closeMethodologyTooltip() {
  const tt = $('method-tooltip');
  if (tt) tt.classList.add('hidden');
}

function showMethodologyTooltip(key, anchorEl) {
  getMethodology().then(meth => {
    const m = meth[key];
    if (!m) return;
    const tt = $('method-tooltip');
    if (!tt) return;

    $('method-tooltip-title').textContent = m.title || key;
    $('method-tooltip-formula').textContent = m.formula || '';
    $('method-tooltip-caveats').textContent = m.caveats ? '⚠ ' + m.caveats : '';

    const srcEl = $('method-tooltip-source');
    srcEl.innerHTML = m.source
      ? `<span class="font-bold">Source:</span> ${esc(m.source)}`
      : '';

    const benchEl = $('method-tooltip-bench');
    if (m.benchmark) {
      const b = m.benchmark;
      benchEl.innerHTML = `<span class="font-bold text-success">Benchmark:</span> ${esc(b.label)}: <span class="font-mono text-success">${b.value}</span>${b.url ? ` <a href="${esc(b.url)}" target="_blank" class="text-accent underline ml-1">source</a>` : ''}`;
      benchEl.classList.remove('hidden');
    } else {
      benchEl.classList.add('hidden');
    }

    // Position near the anchor icon
    const rect = anchorEl.getBoundingClientRect();
    const viewW = window.innerWidth, viewH = window.innerHeight;
    let top = rect.bottom + 6, left = rect.left;
    tt.classList.remove('hidden');
    const ttRect = tt.getBoundingClientRect();
    if (left + ttRect.width > viewW - 10) left = viewW - ttRect.width - 10;
    if (top + ttRect.height > viewH - 10) top = rect.top - ttRect.height - 6;
    tt.style.top = Math.max(8, top) + 'px';
    tt.style.left = Math.max(8, left) + 'px';
  });
}

/**
 * Phase 6 — Enhanced paper modal with ARK / DocID persistent identifiers.
 * Override the metadataRow helper to optionally render ARK as a link.
 */
function renderArkBadge(ark) {
  if (!ark) return '';
  const url = ark.startsWith('ark:') ? '/' + ark : ark;
  return `
    <div class="mt-3 p-3 rounded-lg" style="background:rgba(99,102,241,0.06);border:1px solid rgba(99,102,241,0.15)">
      <p class="text-[10px] font-bold uppercase tracking-wider mb-1" style="color:var(--accent)">
        ARK Persistent Identifier
        <span class="info-icon" data-method="ark_identifier">&#9432;</span>
      </p>
      <a href="${esc(url)}" target="_blank" class="font-mono text-xs hover:underline" style="color:var(--accent)">${esc(ark)}</a>
      <p class="text-[10px] mt-1" style="color:var(--text-muted)">Resolves via Africa PID Alliance · ARK Alliance (2025)</p>
    </div>`;
}

// Patch openPaperModal to include ARK + Pan-African share
const _origOpenPaperModal = openPaperModal;
function openPaperModal(id) {
  $('paper-modal').classList.add('open');
  $('modal-body').innerHTML = '<div class="flex justify-center py-12"><div class="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin"></div></div>';

  Promise.all([
    fetch('/api/papers/' + id).then(r => r.json()),
    fetch('/api/citations/' + id).then(r => r.json()).catch(() => ({ citation_count: 0 }))
  ]).then(([p, cit]) => {
    $('modal-title').textContent = p.title;
    const authors = (p.authors || []).map(a => esc(a.name)).join('; ');

    const fileBtn = p.file?.has_local_pdf
      ? `<a href="${p.file.download_url}" class="btn-primary text-sm">Download PDF</a>`
      : (p.pdf_url ? `<a href="${p.pdf_url}" target="_blank" class="btn-primary text-sm">View PDF</a>` : '');

    // Pan-African citation share badge
    const paShare = cit.african_citation_share != null
      ? `<span class="chip text-[10px] py-0.5 px-2" style="background:rgba(34,197,94,0.1);color:#22c55e">
           🌍 ${cit.african_citation_share}% Pan-African citations
           <span class="info-icon" data-method="pan_african_citation_share">&#9432;</span>
         </span>`
      : '';

    $('modal-body').innerHTML = `
      <div class="space-y-6">
        <div class="flex gap-2 flex-wrap items-center">
          ${fileBtn}
          ${p.doi ? `<a href="https://doi.org/${p.doi}" target="_blank" class="btn-ghost text-xs">View DOI</a>` : ''}
          ${paShare}
        </div>

        <div class="surface p-5 rounded-xl space-y-3">
          <p class="section-label mb-2">Metadata</p>
          ${metadataRow('Title', p.title)}
          ${metadataRow('Authors', authors)}
          ${metadataRow('Date', p.publication_date?.split('T')[0] || '—')}
          ${metadataRow('DOI', p.doi || '—')}
          ${metadataRow('Source', p.source_repository || '—')}
          ${metadataRow('Citations', cit.citation_count)}
          ${cit.docid ? metadataRow('DocID™', cit.docid) : ''}
        </div>

        ${(cit.ark || p.ark) ? renderArkBadge(cit.ark || p.ark) : ''}

        ${p.abstract ? `
          <div class="surface p-5 rounded-xl">
            <p class="section-label mb-2">Abstract</p>
            <p class="text-sm leading-relaxed text-slate-300">${esc(p.abstract)}</p>
          </div>` : ''}
      </div>`;
  }).catch(err => {
    $('modal-body').innerHTML = `<p class="text-sm text-center py-10">Failed to load: ${err.message}</p>`;
  });
}

/**
 * Phase 4 — Pan-African share stat card + CSV download in citation velocity panel.
 * Patches loadCitationVelocity to also render a share badge below the chart.
 */
const _origLoadCitationVelocity = loadCitationVelocity;
function loadCitationVelocity() {
  safeFetch(withInst('/api/citations/velocity'), resp => {
    const d = resp.data || {};
    $('velocity-narrative').textContent = resp.narrative || '';
    const series = d.by_year || [];
    destroyChart('citation-velocity');

    // ── Pan-African share card ────────────────────────────────────────────────
    let shareEl = $('pan-african-share-card');
    if (!shareEl) {
      const parent = $('velocity-narrative')?.parentElement;
      if (parent) {
        parent.insertAdjacentHTML('beforeend', `
          <div id="pan-african-share-card" class="hidden mt-3 flex items-center gap-3 p-3 rounded-lg" style="background:rgba(34,197,94,0.07);border:1px solid rgba(34,197,94,0.15)">
            <div>
              <p class="text-[10px] font-bold uppercase tracking-wider" style="color:#22c55e">
                Pan-African Citation Share
                <span class="info-icon" data-method="pan_african_citation_share">&#9432;</span>
              </p>
              <p id="pan-african-share-value" class="text-2xl font-bold" style="color:#22c55e">—</p>
              <p id="pan-african-share-sub" class="text-[10px]" style="color:var(--text-muted)"></p>
            </div>
            <a id="citation-velocity-csv-btn" href="/api/citations/velocity/export.csv" class="btn-ghost text-xs ml-auto flex-shrink-0">
              <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"/></svg>
              CSV
            </a>
          </div>`);
        shareEl = $('pan-african-share-card');
      }
    }

    if (shareEl) {
      const inst = getInstitutionParam();
      const csvBtn = $('citation-velocity-csv-btn');
      if (csvBtn) csvBtn.href = '/api/citations/velocity/export.csv' + inst;

      if (d.pan_african_share_pct != null) {
        shareEl.classList.remove('hidden');
        const valEl = $('pan-african-share-value');
        const subEl = $('pan-african-share-sub');
        if (valEl) valEl.textContent = d.pan_african_share_pct + '%';
        if (subEl) subEl.textContent = `Computed for ${d.pan_african_share_items || 0} most-cited works`;
      } else {
        shareEl.classList.add('hidden');
      }
    }

    if (!series.length) return;
    charts['citation-velocity'] = new Chart($('chart-citation-velocity'), {
      type: 'line',
      data: {
        labels: series.map(r => r.year),
        datasets: [{
          label: 'Citations received',
          data: series.map(r => r.citations),
          borderColor: '#22c55e', backgroundColor: '#22c55e22',
          fill: true, tension: 0.3, pointRadius: 2,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { y: { beginAtZero: true } },
      },
    });
  }, () => { /* velocity endpoint optional until citation backfill runs */ });
}

