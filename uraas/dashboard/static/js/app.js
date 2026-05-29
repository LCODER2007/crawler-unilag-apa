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
    loadAnalyticsOverview();
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
  
  if (name === 'au') loadAUCharterTab();
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
  const sdgCsv = $('sdg-csv-btn'); if (sdgCsv) sdgCsv.href = '/api/analytics/sdg-alignment/export.csv' + inst;
  const specCsv = $('special-csv-btn'); if (specCsv) specCsv.href = '/api/analytics/special-collections/export.csv' + inst;
  
  if (currentAtab === 'overview') loadAnalyticsOverview();
  
  else if (currentAtab === 'language') { loadLanguageTab(); }
  else if (currentAtab === 'special') { loadSpecialTab(); }
  else if (currentAtab === 'staff') { loadStaffDirectory(); }
}

function invalidateCaches() {
  yearDataCache = yearStackedCache = facultyDataCache = null;
}

function loadAnalyticsOverview() {
  loadFacultiesDropdown();
  loadImpactCards();
  reloadYearChart();
  reloadFacultyChart();
  reloadOAChart();
  reloadAuthorsChart();
  loadFacultyOAChart();
  loadGrowthChart();
  loadTimelineChart();
  fetchOverview();
  fetchRecentPapers();
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
    $('impact-cards').insertAdjacentHTML('afterend', '<div class="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-5" id="adv-metrics-cards"></div>');
  }
  
  const advMetrics = [
    { id: 'tk_vitality', l: 'TK Vitality Score', c: '#a855f7', api: '/api/analytics/tk-vitality-score', f: d => d.score + '/100' },
    { id: 'ling_div', l: 'Linguistic Diversity', c: '#ec4899', api: '/api/analytics/linguistic-diversity-index', f: d => d.index },
    { id: 'pat_vel', l: 'Patent Velocity', c: '#14b8a6', api: '/api/analytics/patent-velocity', f: d => (d.avg_days_to_patent ? (d.avg_days_to_patent / 365).toFixed(1) : '0') + ' yrs' },
    { id: 'docid_cov', l: 'DocID™ Coverage', c: '#6366f1', api: '/api/analytics/docid-coverage', f: d => d.coverage_percent + '%' }
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
 * SDG Alignment
 */
const SDG_COLORS = { 'SDG 1': '#E5243B', 'SDG 2': '#DDA63A', 'SDG 3': '#4C9F38', 'SDG 4': '#C5192D', 'SDG 5': '#FF3A21', 'SDG 6': '#26BDE2', 'SDG 7': '#FCC30B', 'SDG 8': '#A21942', 'SDG 9': '#FD6925', 'SDG 10': '#DD1367', 'SDG 11': '#FD9D24', 'SDG 12': '#BF8B2E', 'SDG 13': '#3F7E44', 'SDG 14': '#0A97D9', 'SDG 15': '#56C02B', 'SDG 16': '#00689D', 'SDG 17': '#19486A' };

function loadSDGTab() {
  if (sdgLoaded) return;
  safeFetch(withInst('/api/analytics/sdg-alignment'), data => {
    sdgLoaded = true; sdgData = data;
    const loading = $('sdg-loading'), grid = $('sdg-grid');
    if (loading) loading.classList.add('hidden');
    if (grid) grid.classList.remove('hidden');
    renderSDGGrid(data);
  });
}

function renderSDGGrid(data) {
  const grid = $('sdg-grid'); if (!grid) return;
  if (!data || !data.length) {
    grid.innerHTML = '<p class="col-span-full text-center py-10 text-sm">No SDG data found.</p>';
    return;
  }
  const maxCount = Math.max(...data.map(d => d.count));
  grid.innerHTML = data.map((item, idx) => {
    const sdgNum = item.sdg.match(/SDG (\d+)/)?.[1] || (idx + 1);
    const color = SDG_COLORS['SDG ' + sdgNum] || '#6366f1';
    const barWidth = Math.max(10, Math.round(item.count / maxCount * 100));
    return `
      <div class="sdg-card surface" style="border-color:${color}40; background:${color}08" onclick="openSDGPanel(${idx})">
        <div style="font-size:12px; font-weight:700; color:${color}; opacity:0.8; margin-bottom:4px">SDG ${sdgNum}</div>
        <p style="font-size:11px; font-weight:600; color:${color}; line-height:1.2; height:2.4em; overflow:hidden">${esc(item.sdg)}</p>
        <div class="flex items-end justify-between mt-2">
          <span style="font-size:1.5rem; font-weight:800; color:${color}">${item.count}</span>
          <span class="text-[10px]" style="color:${color}; opacity:0.6">papers</span>
        </div>
        <div style="margin-top:8px; height:4px; border-radius:4px; background:${color}20">
          <div style="width:${barWidth}%; height:100%; background:${color}; border-radius:4px;"></div>
        </div>
      </div>
    `;
  }).join('');
}

function openSDGPanel(idx) {
  if (!sdgData || !sdgData[idx]) return;
  const item = sdgData[idx];
  const panel = $('sdg-papers-panel'), title = $('sdg-panel-title'), list = $('sdg-papers-list');
  title.textContent = item.sdg + ' — ' + item.count + ' papers';
  list.innerHTML = (item.papers || []).map(p => `
    <div class="row-hover p-3 rounded-lg cursor-pointer" onclick="openPaperModal(${p.id})">
      <p class="text-sm font-medium">${esc(p.title)}</p>
      <div class="flex items-center gap-2 mt-1">
        <span class="text-xs text-muted">Score: ${p.score}</span>
        ${(p.keywords || []).slice(0, 3).map(k => `<span class="chip text-[10px] py-0.5 px-2">${esc(k)}</span>`).join('')}
      </div>
    </div>`).join('') || '<p class="text-xs text-center py-4">No paper details available.</p>';
  panel.classList.remove('hidden');
  panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function closeSdgPanel() { $('sdg-papers-panel')?.classList.add('hidden'); }

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
  const value = input.value.trim();
  if (!value || selectedInstitutions.includes(value) || selectedInstitutions.length >= 15) return;
  selectedInstitutions.push(value);
  input.value = '';
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
    if (name.startsWith('local/')) {
      name = decodeURIComponent(name.replace('local/', ''));
    }
    if (name.length > 25) name = name.substring(0, 22) + '...';
    return `<div class="chip active">${esc(name)} <button onclick="removeInstitution('${ror}')" class="ml-1">×</button></div>`;
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

  // Table Matrix
  const tbody = $('comp-table-body');
  tbody.innerHTML = data.detailed_comparison.institutions.map(inst => `
    <tr class="row-hover border-b border-white/5">
      <td class="py-3 px-2 font-medium">${esc(inst.name)}</td>
      <td class="py-3 px-2 text-right">${inst.metrics.total_papers.toLocaleString()}</td>
      <td class="py-3 px-2 text-right">${inst.metrics.total_authors.toLocaleString()}</td>
      <td class="py-3 px-2 text-right">${inst.metrics.oa_rate}%</td>
      <td class="py-3 px-2 text-right">${inst.metrics.tk_rate}%</td>
      <td class="py-3 px-2 text-right">${inst.metrics.patents}</td>
      <td class="py-3 px-2 text-right">${inst.metrics.growth_rate}%</td>
    </tr>`).join('');

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
  $('comp-rank-tk').innerHTML = renderRanks(rankings.tk_rate, '%');
  $('comp-rank-patent').innerHTML = renderRanks(rankings.patent_rate || rankings.patents_per_100_papers, '%');

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

function renderAfricanCollaborationMap(networkData) {
  const svg = d3.select('#comp-map-svg');
  svg.selectAll('*').remove();
  const container = document.getElementById('comp-collaboration-viz');
  const width = container.clientWidth || 800, height = 520;
  svg.attr('viewBox', `0 0 ${width} ${height}`);

  const africaOutline = [
    {lat: 37.0, lon: 10.0}, {lat: 31.0, lon: 32.0}, {lat: 12.0, lon: 51.0},
    {lat: -4.0, lon: 40.0}, {lat: -26.0, lon: 33.0}, {lat: -34.0, lon: 18.4},
    {lat: -15.0, lon: 12.0}, {lat: -5.0, lon: 12.0}, {lat: 4.0, lon: 9.0},
    {lat: 6.0, lon: 3.0}, {lat: 5.0, lon: -8.0}, {lat: 14.7, lon: -17.4},
    {lat: 21.0, lon: -17.0}, {lat: 35.8, lon: -5.8}, {lat: 36.8, lon: 3.0}
  ];

  function projectCoords(lat, lon) {
    const minLat = -36, maxLat = 39, minLon = -22, maxLon = 53;
    const xPct = (lon - minLon) / (maxLon - minLon);
    const yPct = 1 - (lat - minLat) / (maxLat - minLat);
    const padding = 50;
    return { x: padding + xPct * (width - 2 * padding), y: padding + yPct * (height - 2 * padding) };
  }

  const pointsString = africaOutline.map(p => {
    const proj = projectCoords(p.lat, p.lon);
    return `${proj.x},${proj.y}`;
  }).join(' ');

  const defs = svg.append('defs');
  const glowFilter = defs.append('filter').attr('id', 'map-glow').attr('x', '-20%').attr('y', '-20%').attr('width', '140%').attr('height', '140%');
  glowFilter.append('feGaussianBlur').attr('stdDeviation', '4').attr('result', 'blur');
  glowFilter.append('feMerge').selectAll('feMergeNode').data(['blur', 'SourceGraphic']).enter().append('feMergeNode').attr('in', d => d);

  svg.append('polygon').attr('points', pointsString).attr('fill', 'rgba(255, 255, 255, 0.015)').attr('stroke', 'rgba(255, 255, 255, 0.05)').attr('stroke-width', 2.5).attr('stroke-dasharray', '5,5');

  const nodes = [], nodesMap = {};
  networkData.nodes.forEach(node => {
    let lat = 0, lon = 20, name = node.label, region = 'Unknown';
    const uRor = node.id;
    if (UNIVERSITY_COORDS[uRor]) {
      lat = UNIVERSITY_COORDS[uRor].lat; lon = UNIVERSITY_COORDS[uRor].lon;
      name = UNIVERSITY_COORDS[uRor].name; region = UNIVERSITY_COORDS[uRor].sub_region;
    } else {
      let found = false;
      if (window.universityRegistry) {
        for (const [subReg, countries] of Object.entries(window.universityRegistry)) {
          for (const [country, unis] of Object.entries(countries)) {
            const uni = unis.find(u => u.ror === uRor || u.name === name);
            if (uni) {
              const countryCoords = COUNTRY_CAPITAL_COORDS[country];
              if (countryCoords) { lat = countryCoords.lat; lon = countryCoords.lon; }
              name = uni.name; region = subReg; found = true; break;
            }
          }
          if (found) break;
        }
      }
    }
    const proj = projectCoords(lat, lon);
    const n = { id: node.id, label: name, lat, lon, x: proj.x, y: proj.y, region };
    nodes.push(n); nodesMap[node.id] = n;
  });

  const links = networkData.edges.map(e => ({ source: nodesMap[e.source], target: nodesMap[e.target], weight: e.weight })).filter(l => l.source && l.target);

  const regionColors = { "North Africa": "#3b82f6", "West Africa": "#22c55e", "East Africa": "#f59e0b", "Southern Africa": "#8b5cf6", "Central Africa": "#ec4899", "Unknown": "#64748b" };

  svg.append('g').selectAll('line').data(links).enter().append('line')
    .attr('x1', d => d.source.x).attr('y1', d => d.source.y).attr('x2', d => d.target.x).attr('y2', d => d.target.y)
    .attr('stroke', 'rgba(251, 191, 36, 0.4)').attr('stroke-width', d => Math.max(1.5, Math.min(d.weight * 1.5, 8))).attr('filter', 'url(#map-glow)').style('stroke-linecap', 'round');

  const nodeGroup = svg.append('g').selectAll('g').data(nodes).enter().append('g').attr('transform', d => `translate(${d.x},${d.y})`).style('cursor', 'pointer');
  nodeGroup.append('circle').attr('r', 16).attr('fill', 'none').attr('stroke', d => regionColors[d.region] || '#64748b').attr('stroke-width', 1.5).attr('opacity', 0).attr('class', 'hover-ring');
  nodeGroup.append('circle').attr('r', 9).attr('fill', d => regionColors[d.region] || '#64748b').attr('stroke', '#0f172a').attr('stroke-width', 1.5);
  nodeGroup.append('text').attr('text-anchor', 'middle').attr('y', -14).attr('font-size', '10px').attr('font-weight', '600').attr('fill', '#e2e8f0').attr('paint-order', 'stroke').attr('stroke', '#0f172a').attr('stroke-width', '2.5px').text(d => d.label.length > 20 ? d.label.substring(0, 18) + '...' : d.label);

  const tooltip = d3.select('#comp-map-tooltip');
  nodeGroup.on('mouseover', function(event, d) {
    d3.select(this).select('.hover-ring').transition().duration(200).style('opacity', 0.8).attr('r', 18);
    tooltip.transition().duration(150).style('opacity', 1).style('display', 'block');
    let metricsHtml = `<p class="font-bold text-slate-100">${esc(d.label)}</p><p class="text-[10px] text-muted mb-2">${esc(d.region)}</p>`;
    if (window.lastCompareData) {
      const inst = window.lastCompareData.detailed_comparison.institutions.find(i => i.ror_id === d.id);
      if (inst) {
        metricsHtml += `
          <div class="space-y-1 mt-1 border-t border-white/10 pt-1">
            <div class="flex justify-between gap-4"><span>Papers:</span><span class="font-mono text-accent">${inst.metrics.total_papers.toLocaleString()}</span></div>
            <div class="flex justify-between gap-4"><span>OA Rate:</span><span class="font-mono text-success">${inst.metrics.oa_rate}%</span></div>
            <div class="flex justify-between gap-4"><span>IK Rate:</span><span class="font-mono text-warning">${inst.metrics.tk_rate}%</span></div>
            <div class="flex justify-between gap-4"><span>Patents:</span><span class="font-mono">${inst.metrics.patents}</span></div>
          </div>`;
      }
    }
    tooltip.html(metricsHtml);
  })
  .on('mousemove', function(event) {
    const containerRect = container.getBoundingClientRect(), tooltipWidth = tooltip.node().offsetWidth, tooltipHeight = tooltip.node().offsetHeight;
    let x = event.clientX - containerRect.left + 15, y = event.clientY - containerRect.top + 15;
    if (x + tooltipWidth > width) x = event.clientX - containerRect.left - tooltipWidth - 15;
    if (y + tooltipHeight > height) y = event.clientY - containerRect.top - tooltipHeight - 15;
    tooltip.style('left', `${x}px`).style('top', `${y}px`);
  })
  .on('mouseout', function() {
    d3.select(this).select('.hover-ring').transition().duration(200).style('opacity', 0);
    tooltip.transition().duration(150).style('opacity', 0).style('display', 'none');
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
 * AU Charter for African Cultural Renaissance
 */
let auCharterLoaded = false;
function loadAUCharterTab() {
  if (auCharterLoaded) return;
  auCharterLoaded = true;
  $('au-loading').classList.remove('hidden');
  $('au-content').classList.add('hidden');
  safeFetch(withInst('/api/analytics/au-charter-alignment'), data => {
    $('au-loading').classList.add('hidden');
    $('au-content').classList.remove('hidden');

    const totalAnalyzed = data.total_papers_analyzed || 0;
    const totalTargeted = data.targets.reduce((s, t) => s + t.count, 0);
    const overallRate = totalAnalyzed ? Math.round(totalTargeted / totalAnalyzed * 100) : 0;

    // Summary banner
    $('au-summary-cards').innerHTML = `
      <div class="surface rounded-xl p-5" style="background:linear-gradient(135deg,rgba(34,197,94,0.08),rgba(99,102,241,0.08));border:1px solid rgba(34,197,94,0.2)">
        <div class="flex items-center justify-between flex-wrap gap-4">
          <div>
            <p class="text-xs font-bold uppercase tracking-wider mb-1" style="color:var(--success)">AU Charter for African Cultural Renaissance — Overall Alignment</p>
            <p class="text-sm" style="color:var(--text-muted)">Assessed across all 9 Targets · ${totalAnalyzed.toLocaleString()} papers analyzed · Institution: ${esc(data.institution_filter)}</p>
          </div>
          <div class="flex gap-6 text-center">
            <div><p class="text-3xl font-bold" style="color:var(--success)">${overallRate}%</p><p class="text-xs text-muted">Overall Coverage</p></div>
            <div><p class="text-3xl font-bold" style="color:var(--accent)">${totalAnalyzed.toLocaleString()}</p><p class="text-xs text-muted">Papers Analyzed</p></div>
          </div>
        </div>
      </div>`;

    // Target cards (9 targets)
    const targetColors = ['#3b82f6','#22c55e','#f59e0b','#8b5cf6','#ec4899','#14b8a6','#f97316','#6366f1','#ef4444'];
    $('au-targets-grid').innerHTML = data.targets.map((t, i) => {
      const color = targetColors[i % targetColors.length];
      const barW = Math.min(100, t.compliance_rate * 2); // scale for visual
      return `
        <div class="surface rounded-xl p-5" style="border-top:3px solid ${color}">
          <div class="flex justify-between items-start mb-3">
            <div class="flex items-start gap-2">
              <span class="text-xl font-extrabold" style="color:${color};line-height:1">${t.target_number}</span>
              <p class="text-xs font-bold leading-tight" style="color:var(--text)">${esc(t.target_name)}</p>
            </div>
            <span class="text-xs font-mono font-bold ml-2 flex-shrink-0" style="color:${color}">${t.compliance_rate}%</span>
          </div>
          <div class="h-1.5 rounded-full mb-3" style="background:var(--input-bg)">
            <div class="h-1.5 rounded-full" style="width:${barW}%;background:${color};transition:width 0.6s ease"></div>
          </div>
          <p class="text-xs text-muted mb-2">${t.count} papers aligned</p>
          ${t.top_papers.length ? `
            <div class="space-y-1.5 border-t border-white/5 pt-2">
              ${t.top_papers.map(p => `
                <div class="row-hover p-2 rounded-lg cursor-pointer" onclick="openPaperModal(${p.id})">
                  <p class="text-xs font-medium leading-snug line-clamp-2">${esc(p.title)}</p>
                  <div class="flex gap-1 mt-1 flex-wrap">
                    ${p.matched_keywords.slice(0,3).map(k => `<span class="chip text-[9px] py-0.5 px-1.5" style="background:${color}18;color:${color}">${esc(k)}</span>`).join('')}
                  </div>
                </div>`).join('')}
            </div>` : '<p class="text-xs text-muted italic">No papers matched yet.</p>'}
        </div>`;
    }).join('');
  }, () => {
    $('au-loading').innerHTML = '<p class="text-sm text-center py-8 text-muted">Failed to load AU Charter data.</p>';
  });
}

/**
 * Special Collections
 */
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
  
  appendLog('// Starting crawler for ' + inst + ' — target: ' + t + ' papers [SC ONLY]');
  toast('Mining started for ' + inst, 'info');
  updateCrawlerUI({ status: 'initializing' });
  
  fetch('/api/crawler/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ target: t, institution: inst, boost_special: true, sc_only: true })
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
      if (analyticsLoaded) loadAnalyticsOverview();
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
  
  let url = `/api/search/advanced?limit=50&q=${encodeURIComponent(q)}&sort=${sort}`;
  if (yf) url += '&year_from=' + yf;
  if (yt) url += '&year_to=' + yt;
  if (oa) url += '&oa_only=true';
  
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

function loadCrawlerInstitutions() {
  safeFetch('/api/institutions', data => {
    const sel = $('crawler-institution');
    if (!sel) return;
    const current = sel.value;
    sel.innerHTML = '';
    
    // Grouping by region for better UX
    const groups = { 'Nigeria': [], 'Africa': [] };
    data.forEach(inst => {
      const region = ['unilag', 'covenant', 'ui'].includes(inst.short_name.toLowerCase()) ? 'Nigeria' : 'Africa';
      groups[region].push(inst);
    });

    for (const [region, insts] of Object.entries(groups)) {
      const group = document.createElement('optgroup');
      group.label = region === 'Nigeria' ? '🇳🇬 Nigeria' : '🌍 Africa';
      insts.forEach(inst => {
        const opt = document.createElement('option');
        opt.value = inst.short_name.toLowerCase();
        opt.textContent = `${inst.name} (${inst.short_name})`;
        group.appendChild(opt);
      });
      sel.appendChild(group);
    }
    if (current) sel.value = current;
  });
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
  
  // Stats Auto-Refresh
  setInterval(() => {
    const badge = $('crawler-badge');
    if (badge && badge.textContent.includes('Running')) {
      fetchOverview(); fetchRecentPapers();
      if (analyticsLoaded) { invalidateCaches(); loadAnalyticsOverview(); }
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
  if (e.key === 'Escape') { closePaperModal(); }
  if (e.key === 't' || e.key === 'T') toggleTheme();
});
