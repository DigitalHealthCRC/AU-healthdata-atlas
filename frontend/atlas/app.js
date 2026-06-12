/* AU Health Data Atlas — static viewer.
 * Zero external dependencies: vanilla ES6+, SVG, hand-rolled force layout
 * and markdown rendering. Works from file:// (data ships as
 * data/atlas_data.js -> window.ATLAS_DATA) or any static server.
 */
(function () {
  'use strict';

  // ------------------------------------------------------------------
  // Boot guard / empty state
  // ------------------------------------------------------------------
  const DATA = window.ATLAS_DATA;
  if (!DATA || !Array.isArray(DATA.custodians)) {
    const app = document.getElementById('app');
    app.innerHTML =
      '<div class="empty-state">' +
      '<h2>No data bundle found</h2>' +
      '<p>The viewer could not find <strong>data/atlas_data.js</strong> ' +
      '(it defines <code style="display:inline;padding:1px 5px;">window.ATLAS_DATA</code>).</p>' +
      '<p>Regenerate it from the repo root (database-free, reads local curated sources):</p>' +
      '<code>uv run python .\\scripts\\export_atlas_bundle.py</code>' +
      '<p>Then reload this page.</p>' +
      '</div>';
    return;
  }

  // ------------------------------------------------------------------
  // Palette + jurisdiction grouping
  // ------------------------------------------------------------------
  // DHCRC brand palette: the five gradient colours (#FD0100 → #FD01DE →
  // #C200FF → #008FFF, plus gold #F9B505) and interpolations along the
  // gradient; brand grey #D9D8D6 for cross-jurisdictional.
  const GROUPS = [
    { key: 'Commonwealth', label: 'Commonwealth', color: '#008fff' },
    { key: 'Cross-jurisdictional', label: 'Cross-jurisdictional', color: '#d9d8d6' },
    { key: 'ACT', label: 'ACT', color: '#c200ff' },
    { key: 'NSW', label: 'NSW', color: '#0a3d8c' },
    { key: 'NT', label: 'NT', color: '#f9b505' },
    { key: 'QLD', label: 'QLD', color: '#fd0163' },
    { key: 'SA', label: 'SA', color: '#fd0100' },
    { key: 'TAS', label: 'TAS', color: '#9b2fff' },
    { key: 'VIC', label: 'VIC', color: '#6f5bff' },
    { key: 'WA', label: 'WA', color: '#fd01de' }
  ];
  const GROUP_BY_KEY = new Map(GROUPS.map((g) => [g.key, g]));
  const STATE_NAMES = {
    'Australian Capital Territory': 'ACT',
    'New South Wales': 'NSW',
    'Northern Territory': 'NT',
    'Queensland': 'QLD',
    'South Australia': 'SA',
    'Tasmania': 'TAS',
    'Victoria': 'VIC',
    'Western Australia': 'WA'
  };

  function jurisdictionGroup(name) {
    const n = (name || '').trim();
    if (n === 'Commonwealth') return 'Commonwealth';
    if (STATE_NAMES[n]) return STATE_NAMES[n];
    // Combined jurisdictions ("X and Y") and explicit cross-jurisdictional
    // entries share the cross-jurisdictional colour.
    return 'Cross-jurisdictional';
  }

  function groupColor(key) {
    const g = GROUP_BY_KEY.get(key);
    return g ? g.color : '#a9a8a6';
  }

  const LANES = [
    { key: 'Researcher', label: 'Researcher', tint: 'rgba(0, 143, 255, 0.10)' },
    { key: 'EthicsRegulatory', label: 'Ethics & Regulatory', tint: 'rgba(194, 0, 255, 0.10)' },
    { key: 'Custodian', label: 'Custodian', tint: 'rgba(253, 1, 222, 0.07)' }
  ];
  const LANE_INDEX = new Map(LANES.map((l, i) => [l.key, i]));

  // ------------------------------------------------------------------
  // Small helpers
  // ------------------------------------------------------------------
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function svgEl(tag, attrs) {
    const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
    if (attrs) for (const k of Object.keys(attrs)) el.setAttribute(k, attrs[k]);
    return el;
  }

  function truncate(s, n) {
    s = String(s || '');
    return s.length > n ? s.slice(0, n - 1).trimEnd() + '…' : s;
  }

  const URL_RE = /https?:\/\/[^\s<>"')\],;]+/g;

  function linkify(text) {
    // escape first, then wrap URLs (escaped text keeps URLs intact apart
    // from &amp;, which browsers resolve fine in href).
    const escaped = esc(text);
    return escaped.replace(URL_RE, (m) =>
      '<a href="' + m + '" target="_blank" rel="noopener">' + m + '</a>');
  }

  function badgeClass(value) {
    const v = String(value || '').trim().toLowerCase();
    if (!v) return 'badge-other';
    if (v.startsWith('yes')) return 'badge-yes';
    if (v.startsWith('no')) return 'badge-no';
    if (v.startsWith('partial')) return 'badge-partial';
    return 'badge-other';
  }

  function badgeHtml(label, value) {
    const text = String(value || '').trim() || '—';
    return '<span class="badge ' + badgeClass(value) + '" title="' + esc(label + ': ' + text) + '">' +
      esc(label) + ': ' + esc(truncate(text, 40)) + '</span>';
  }

  const STOPWORDS = new Set(['of', 'the', 'and', 'for', 'in', 'on', 'to', 'a', 'an']);

  function shortLabel(c) {
    const subject = (c.subject || '').trim();
    if (subject && subject.length <= 26) return subject;
    const name = (c.name || '').trim();
    if (name.length <= 26) return name;
    const noParen = name.replace(/\s*\([^)]*\)\s*/g, ' ').replace(/\s+/g, ' ').trim();
    if (noParen.length <= 26) return noParen;
    const firstSegment = noParen.split('/')[0].trim();
    if (firstSegment.length >= 3 && firstSegment.length <= 26) return firstSegment;
    const words = noParen.split(/[\s,\-]+/).filter((w) => w && !STOPWORDS.has(w.toLowerCase()));
    const acronym = words.map((w) => w[0].toUpperCase()).join('');
    if (acronym.length >= 2 && acronym.length <= 10) return acronym;
    return truncate(name, 24);
  }

  function hasTre(c) {
    const t = (c.tre || '').trim();
    if (!t) return false;
    return !/^(none|n\/a|not applicable|no\b|not specified|unknown)/i.test(t);
  }

  function fmtScore(s) {
    return typeof s === 'number' && isFinite(s) ? s.toFixed(2) : '—';
  }

  // ------------------------------------------------------------------
  // Minimal markdown renderer (escape-first; headings, bold/italic,
  // inline code, links, lists, tables, hr, paragraphs).
  // ------------------------------------------------------------------
  function mdInline(escaped) {
    let s = escaped;
    s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
    s = s.replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener">$1</a>');
    s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    s = s.replace(/(^|[\s(])\*([^*\n]+)\*(?=[\s).,;:]|$)/g, '$1<em>$2</em>');
    return s;
  }

  function renderMarkdown(md) {
    const lines = String(md || '').replace(/\r\n?/g, '\n').split('\n');
    const out = [];
    let i = 0;
    let listType = null; // 'ul' | 'ol'
    let para = [];

    function flushPara() {
      if (para.length) {
        out.push('<p>' + para.map((l) => mdInline(esc(l))).join('<br>') + '</p>');
        para = [];
      }
    }
    function closeList() {
      if (listType) { out.push('</' + listType + '>'); listType = null; }
    }
    function isTableLine(line) {
      const t = line.trim();
      return t.startsWith('|') && t.endsWith('|') && t.length > 1;
    }
    function splitRow(line) {
      const t = line.trim().replace(/^\|/, '').replace(/\|$/, '');
      return t.split('|').map((cell) => mdInline(esc(cell.trim())));
    }

    while (i < lines.length) {
      const line = lines[i];
      const trimmed = line.trim();

      if (!trimmed) { flushPara(); closeList(); i++; continue; }

      const heading = /^(#{1,6})\s+(.*)$/.exec(trimmed);
      if (heading) {
        flushPara(); closeList();
        const level = Math.min(heading[1].length, 4);
        out.push('<h' + level + '>' + mdInline(esc(heading[2])) + '</h' + level + '>');
        i++; continue;
      }

      if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
        flushPara(); closeList(); out.push('<hr>'); i++; continue;
      }

      if (isTableLine(trimmed)) {
        flushPara(); closeList();
        const block = [];
        while (i < lines.length && isTableLine(lines[i].trim())) { block.push(lines[i]); i++; }
        let header = null;
        let body = block;
        if (block.length >= 2 && /^\s*\|?\s*:?-{2,}/.test(block[1].trim())) {
          header = splitRow(block[0]);
          body = block.slice(2);
        }
        let html = '<table>';
        if (header) {
          html += '<thead><tr>' + header.map((h) => '<th>' + h + '</th>').join('') + '</tr></thead>';
        }
        html += '<tbody>' + body
          .filter((row) => !/^\s*\|?\s*:?-{2,}/.test(row.trim()))
          .map((row) => '<tr>' + splitRow(row).map((cell) => '<td>' + cell + '</td>').join('') + '</tr>')
          .join('') + '</tbody></table>';
        out.push(html);
        continue;
      }

      const ulItem = /^[-*+]\s+(.*)$/.exec(trimmed);
      const olItem = /^\d+[.)]\s+(.*)$/.exec(trimmed);
      if (ulItem || olItem) {
        flushPara();
        const want = ulItem ? 'ul' : 'ol';
        if (listType !== want) { closeList(); out.push('<' + want + '>'); listType = want; }
        out.push('<li>' + mdInline(esc((ulItem || olItem)[1])) + '</li>');
        i++; continue;
      }

      closeList();
      para.push(trimmed);
      i++;
    }
    flushPara(); closeList();
    return out.join('\n');
  }

  // ------------------------------------------------------------------
  // Indexes + state
  // ------------------------------------------------------------------
  const custodians = DATA.custodians;
  const custodianById = new Map(custodians.map((c) => [c.id, c]));
  for (const c of custodians) {
    c._group = jurisdictionGroup(c.jurisdiction);
    c._color = groupColor(c._group);
    c._label = shortLabel(c);
    c._hasTre = hasTre(c);
    c._haystack = (c.name + ' ' + c.subject + ' ' +
      c.datasets.map((d) => d.name).join(' ')).toLowerCase();
  }

  const state = {
    view: 'network',
    selectedId: null,
    selectedStep: null, // {custodianId, order}
    net: { groups: new Set(), type: '', tre: false, q: '', geo: false },
    pw: { q: '', custodianId: null },
    ds: { q: '', custodian: '', identifiable: '', linkable: '' }
  };

  const tooltip = document.getElementById('tooltip');

  function showTooltip(html, evt) {
    tooltip.innerHTML = html;
    tooltip.classList.remove('hidden');
    moveTooltip(evt);
  }
  function moveTooltip(evt) {
    const pad = 14;
    let x = evt.clientX + pad;
    let y = evt.clientY + pad;
    const r = tooltip.getBoundingClientRect();
    if (x + r.width > window.innerWidth - 8) x = evt.clientX - r.width - pad;
    if (y + r.height > window.innerHeight - 8) y = evt.clientY - r.height - pad;
    tooltip.style.left = x + 'px';
    tooltip.style.top = y + 'px';
  }
  function hideTooltip() { tooltip.classList.add('hidden'); }

  // ------------------------------------------------------------------
  // Header / footer
  // ------------------------------------------------------------------
  function renderChrome() {
    const meta = DATA.meta || {};
    const prov = meta.provenance || {};
    const counts = meta.counts || {};
    const bundleDate = (meta.generatedAt || '').slice(0, 10);
    document.getElementById('freshness').textContent =
      [
        prov.registerTitle || 'Pathway register',
        prov.registerGenerated ? 'register dated ' + prov.registerGenerated : '',
        bundleDate ? 'bundle ' + bundleDate : '',
        (counts.custodians || 0) + ' custodians · ' + (counts.datasets || 0) + ' datasets'
      ].filter(Boolean).join('  ·  ');

    document.getElementById('footer').textContent =
      '© 2025 Digital Health CRC Limited. Confidential · ' +
      'Provenance: ' + (prov.registerTitle || 'register') +
      (prov.registerVersion ? ' (v' + prov.registerVersion + ')' : '') +
      (prov.registerGenerated ? ' · register generated ' + prov.registerGenerated : '') +
      (prov.gitCommit ? ' · commit ' + prov.gitCommit.slice(0, 7) : '') +
      (meta.generatedAt ? ' · bundle generated ' + meta.generatedAt : '') +
      (prov.mode ? ' · mode: ' + prov.mode : '');
  }

  // ------------------------------------------------------------------
  // Tabs
  // ------------------------------------------------------------------
  function switchView(view) {
    state.view = view;
    for (const btn of document.querySelectorAll('#view-switcher .tab')) {
      btn.classList.toggle('active', btn.dataset.view === view);
    }
    for (const v of ['network', 'pathways', 'datasets']) {
      document.getElementById('view-' + v).classList.toggle('hidden', v !== view);
    }
    if (view === 'network') network.onShow();
    if (view === 'pathways') pathways.render();
    if (view === 'datasets') datasets.render();
    updateTabCues(false);
  }

  document.getElementById('view-switcher').addEventListener('click', (evt) => {
    const btn = evt.target.closest('button[data-view]');
    if (btn) switchView(btn.dataset.view);
  });

  // ------------------------------------------------------------------
  // Selection (shared across views)
  // ------------------------------------------------------------------
  function selectCustodian(id, opts) {
    state.selectedId = id;
    if (!opts || !opts.keepStep) state.selectedStep = null;
    // Selecting a custodian anywhere pre-filters the other views to it, so
    // the Pathways and Datasets tabs open already scoped to the selection
    // (the user can still change those filters afterwards).
    if (custodianById.has(id)) {
      state.pw.custodianId = id;
      state.ds.custodian = id;
      state.ds.q = '';
    }
    renderDetail();
    network.applyClasses();
    if (state.view === 'pathways') pathways.syncSelection();
    if (state.view === 'datasets') datasets.render();
    updateTabCues(true);
  }

  // Light up the Pathways / Datasets tabs when a custodian is selected, so
  // it is obvious they now open pre-filtered to that custodian.
  function updateTabCues(pulse) {
    const c = custodianById.get(state.selectedId);
    for (const view of ['pathways', 'datasets']) {
      const btn = document.querySelector('#view-switcher .tab[data-view="' + view + '"]');
      if (!btn) continue;
      let dot = btn.querySelector('.tab-dot');
      if (!c) {
        if (dot) dot.remove();
        btn.classList.remove('cue', 'cue-pulse');
        btn.removeAttribute('title');
        continue;
      }
      if (!dot) {
        dot = document.createElement('span');
        dot.className = 'tab-dot';
        btn.appendChild(dot);
      }
      dot.style.background = c._color;
      dot.style.color = c._color;
      btn.title = (view === 'pathways'
        ? 'See the access pathway for '
        : 'See the datasets held by ') + c.name;
      const isActive = state.view === view;
      btn.classList.toggle('cue', !isActive);
      btn.classList.remove('cue-pulse');
      if (pulse && !isActive) {
        void btn.offsetWidth; // force reflow so the pulse animation restarts
        btn.classList.add('cue-pulse');
      }
    }
  }

  // ------------------------------------------------------------------
  // Detail panel
  // ------------------------------------------------------------------
  const panelBody = document.getElementById('panel-body');
  const panel = document.getElementById('detail-panel');
  document.getElementById('panel-toggle').addEventListener('click', () => {
    panel.classList.toggle('collapsed');
  });

  function jurisdictionChip(c) {
    return '<span class="chip"><span class="dot" style="background:' + c._color + '"></span>' +
      esc(c.jurisdiction || 'Unknown jurisdiction') + '</span>';
  }

  function sectionHtml(title, bodyHtml) {
    if (!bodyHtml) return '';
    return '<div class="section"><h3>' + esc(title) + '</h3>' + bodyHtml + '</div>';
  }

  function stepDetailHtml(c) {
    const sel = state.selectedStep;
    if (!sel || sel.custodianId !== c.id) return '';
    const step = c.steps.find((s) => s.order === sel.order);
    if (!step) return '';
    return '<div class="step-detail-card">' +
      '<h3>Step ' + esc(step.order) + ' · ' + esc(LANE_LABEL(step.lane)) + ' lane</h3>' +
      '<dl>' +
      '<dt>Step</dt><dd>' + esc(step.text) + '</dd>' +
      (step.actor ? '<dt>Actor</dt><dd>' + esc(step.actor) + '</dd>' : '') +
      (step.channel ? '<dt>Channel</dt><dd>' + linkify(step.channel) + '</dd>' : '') +
      (step.timeline ? '<dt>Timeline</dt><dd>' + esc(step.timeline) + '</dd>' : '') +
      '</dl></div>';
  }

  function LANE_LABEL(key) {
    const lane = LANES.find((l) => l.key === key);
    return lane ? lane.label : (key || 'Unspecified');
  }

  function connectionsHtml(list, idKey, nameKey) {
    if (!list.length) return '<p class="panel-hint" style="margin:2px 0">None recorded.</p>';
    return list.map((conn) =>
      '<details class="conn"><summary>' +
      '<button type="button" class="item-btn" data-goto="' + esc(conn[idKey]) + '">' +
      esc(conn[nameKey]) + '</button></summary>' +
      '<div class="conn-meta">' +
      (conn.segment ? esc(conn.segment) + '<br>' : '') +
      'match: ' + esc(conn.matchType || 'unknown') + ' · score ' + fmtScore(conn.matchScore) +
      '</div></details>').join('');
  }

  function renderDetail() {
    const c = custodianById.get(state.selectedId);
    if (!c) {
      panelBody.innerHTML =
        '<p class="panel-hint">Select a custodian (a node on the network map, ' +
        'a pathway line, or a dataset’s custodian) to see its profile here.</p>';
      return;
    }

    const datasetsHtml = c.datasets.length
      ? c.datasets.map((d) =>
          '<button type="button" class="item-btn" data-dataset="' + esc(d.id) +
          '" data-custodian="' + esc(c.id) + '" title="' + esc(truncate(d.description, 220)) + '">' +
          esc(truncate(d.name, 70)) + '</button>').join('')
      : '<p class="panel-hint" style="margin:2px 0">No datasets recorded.</p>';

    const sourcesHtml = c.sources.length
      ? '<ul class="link-list">' + c.sources.map((u) =>
          '<li><a href="' + esc(u) + '" target="_blank" rel="noopener">' +
          esc(truncate(u, 64)) + '</a></li>').join('') + '</ul>'
      : '';

    panelBody.innerHTML =
      stepDetailHtml(c) +
      '<h2>' + esc(c.name) + '</h2>' +
      '<div class="chip-row">' +
      (c.type ? '<span class="chip">' + esc(c.type) + '</span>' : '') +
      jurisdictionChip(c) +
      (c._hasTre ? '<span class="chip">TRE / secure access</span>' : '') +
      (c.reviewCount ? '<span class="chip" title="Connection mentions held for manual review (not shown as edges)">' +
        c.reviewCount + ' connection reviews</span>' : '') +
      '</div>' +
      sectionHtml('Primary role', c.primaryRole ? '<p>' + esc(c.primaryRole) + '</p>' : '') +
      sectionHtml('Indicative timeline', c.timeline ? '<p>' + esc(c.timeline) + '</p>' : '') +
      sectionHtml('Ethics & governance', c.ethics ? '<p>' + esc(c.ethics) + '</p>' : '') +
      sectionHtml('TRE / secure access platform', c.tre ? '<p>' + esc(c.tre) + '</p>' : '') +
      sectionHtml('Contact & application portal', c.portal ? '<p>' + linkify(c.portal) + '</p>' : '') +
      sectionHtml('Gaps / verify with custodian', c.gaps ? '<p>' + esc(c.gaps) + '</p>' : '') +
      sectionHtml('Datasets (' + c.datasets.length + ')', datasetsHtml) +
      sectionHtml('Connections out (' + c.connectionsOut.length + ')',
        connectionsHtml(c.connectionsOut, 'targetId', 'targetName')) +
      sectionHtml('Connections in (' + c.connectionsIn.length + ')',
        connectionsHtml(c.connectionsIn, 'sourceId', 'sourceName')) +
      sectionHtml('Source URLs (' + c.sources.length + ')', sourcesHtml) +
      (c.cardMarkdown
        ? '<div class="section"><h3>Pathway card</h3>' +
          '<button type="button" class="item-btn" data-cardtoggle="1">View full pathway card</button>' +
          '<div class="md-card hidden" id="md-card-holder"></div></div>'
        : '');

    panel.classList.remove('collapsed');
    panel.scrollTop = 0;
  }

  panelBody.addEventListener('click', (evt) => {
    const goto = evt.target.closest('[data-goto]');
    if (goto) {
      evt.preventDefault();
      selectCustodian(goto.dataset.goto);
      return;
    }
    const ds = evt.target.closest('[data-dataset]');
    if (ds) {
      const owner = custodianById.get(ds.dataset.custodian);
      const entry = owner && owner.datasets.find((d) => d.id === ds.dataset.dataset);
      state.ds.custodian = ds.dataset.custodian;
      state.ds.q = entry ? entry.name.toLowerCase() : '';
      state.ds.identifiable = '';
      state.ds.linkable = '';
      switchView('datasets');
      return;
    }
    const toggle = evt.target.closest('[data-cardtoggle]');
    if (toggle) {
      const holder = document.getElementById('md-card-holder');
      const c = custodianById.get(state.selectedId);
      if (holder.classList.contains('hidden')) {
        if (!holder.dataset.rendered && c) {
          holder.innerHTML = renderMarkdown(c.cardMarkdown);
          holder.dataset.rendered = '1';
        }
        holder.classList.remove('hidden');
        toggle.textContent = 'Hide full pathway card';
      } else {
        holder.classList.add('hidden');
        toggle.textContent = 'View full pathway card';
      }
    }
  });

  // ------------------------------------------------------------------
  // Network view
  // ------------------------------------------------------------------
  const network = (function () {
    const container = document.getElementById('view-network');
    const W = 1000;
    const H = 640;
    let built = false;
    let nodes = [];          // {c, x, y, vx, vy, r}
    let nodeById = new Map();
    let edges = [];          // merged undirected: {a, b, dirs: [...]}
    let zoom = { x: 0, y: 0, k: 1 };
    let svg, gZoom, gGeo, gEdges, gNodes;

    // Conceptual Australia: anchor per jurisdiction group on the W×H canvas.
    // Not geographically exact — just enough that WA reads west, QLD
    // north-east, etc. Commonwealth and cross-jurisdictional custodians
    // share a central "national" hub.
    const GEO_HUB = { x: 520, y: 295 };
    const GEO_ANCHORS = {
      'WA': { x: 175, y: 330 },
      'NT': { x: 400, y: 150 },
      'SA': { x: 450, y: 410 },
      'QLD': { x: 690, y: 155 },
      'NSW': { x: 805, y: 330 },
      'ACT': { x: 850, y: 415 },
      'VIC': { x: 705, y: 485 },
      'TAS': { x: 750, y: 580 },
      'Commonwealth': GEO_HUB,
      'Cross-jurisdictional': GEO_HUB
    };
    const layouts = { force: null, geo: null, geoLabels: null };
    let animId = 0;

    function geoAnchor(group) {
      return GEO_ANCHORS[group] || GEO_HUB;
    }

    function snapshotPositions() {
      return nodes.map((n) => ({ x: n.x, y: n.y }));
    }

    function buildGraph() {
      nodes = custodians.map((c, i) => {
        const angle = i * 2.39996323;
        const radius = 70 + 190 * Math.sqrt((i + 0.5) / custodians.length);
        return {
          c,
          x: W / 2 + radius * Math.cos(angle),
          y: H / 2 + radius * Math.sin(angle),
          vx: 0, vy: 0,
          r: Math.max(9, Math.min(26, 7 + 2.6 * Math.sqrt(c.datasets.length)))
        };
      });
      nodeById = new Map(nodes.map((n) => [n.c.id, n]));

      const merged = new Map();
      for (const c of custodians) {
        for (const conn of c.connectionsOut) {
          if (!nodeById.has(conn.targetId)) continue;
          const key = [c.id, conn.targetId].sort().join(' ');
          if (!merged.has(key)) {
            merged.set(key, { a: nodeById.get(c.id), b: nodeById.get(conn.targetId), dirs: [] });
          }
          merged.get(key).dirs.push({
            sourceName: c.name, targetName: conn.targetName,
            segment: conn.segment, matchType: conn.matchType, matchScore: conn.matchScore
          });
        }
      }
      edges = Array.from(merged.values());
      runSimulation(false);
      layouts.force = snapshotPositions();
    }

    // geo=true pulls each node toward its jurisdiction anchor instead of the
    // shared canvas centre, with edge springs weakened so connections don't
    // drag nodes out of their state cluster.
    function runSimulation(geo) {
      const REPULSION = 26000;
      const SPRING_K = geo ? 0.006 : 0.03;
      const SPRING_LEN = 165;
      const CENTER_K = 0.012;
      const GEO_K = 0.045;
      const DAMPING = 0.85;
      const MAX_SPEED = 14;
      const TICKS = 380;

      for (let t = 0; t < TICKS; t++) {
        for (let i = 0; i < nodes.length; i++) {
          const a = nodes[i];
          for (let j = i + 1; j < nodes.length; j++) {
            const b = nodes[j];
            let dx = a.x - b.x, dy = a.y - b.y;
            let d2 = dx * dx + dy * dy;
            if (d2 < 1) { d2 = 1; dx = (i - j) * 0.1 || 0.1; dy = 0.1; }
            const f = Math.min(REPULSION / d2, 60);
            const d = Math.sqrt(d2);
            a.vx += (dx / d) * f * 0.05; a.vy += (dy / d) * f * 0.05;
            b.vx -= (dx / d) * f * 0.05; b.vy -= (dy / d) * f * 0.05;
          }
        }
        for (const e of edges) {
          const dx = e.b.x - e.a.x, dy = e.b.y - e.a.y;
          const d = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
          const f = SPRING_K * (d - SPRING_LEN);
          e.a.vx += (dx / d) * f; e.a.vy += (dy / d) * f;
          e.b.vx -= (dx / d) * f; e.b.vy -= (dy / d) * f;
        }
        for (const n of nodes) {
          if (geo) {
            const a = geoAnchor(n.c._group);
            n.vx += (a.x - n.x) * GEO_K;
            n.vy += (a.y - n.y) * GEO_K;
          } else {
            n.vx += (W / 2 - n.x) * CENTER_K;
            n.vy += (H / 2 - n.y) * CENTER_K;
          }
          n.vx *= DAMPING; n.vy *= DAMPING;
          const speed = Math.sqrt(n.vx * n.vx + n.vy * n.vy);
          if (speed > MAX_SPEED) { n.vx = (n.vx / speed) * MAX_SPEED; n.vy = (n.vy / speed) * MAX_SPEED; }
          n.x += n.vx; n.y += n.vy;
        }
      }
      // Settle inside frame with a small margin.
      let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
      for (const n of nodes) {
        minX = Math.min(minX, n.x); maxX = Math.max(maxX, n.x);
        minY = Math.min(minY, n.y); maxY = Math.max(maxY, n.y);
      }
      const margin = 70;
      const sx = (W - 2 * margin) / Math.max(maxX - minX, 1);
      const sy = (H - 2 * margin) / Math.max(maxY - minY, 1);
      const s = Math.min(sx, sy, 1.4);
      for (const n of nodes) {
        n.x = margin + (n.x - minX) * s;
        n.y = margin + (n.y - minY) * s;
      }
    }

    function computeGeoLayout() {
      // Seed each node on a small spiral around its jurisdiction anchor so
      // the simulation starts from (and settles into) clean state clusters.
      const seen = new Map();
      for (const n of nodes) {
        const i = seen.get(n.c._group) || 0;
        seen.set(n.c._group, i + 1);
        const a = geoAnchor(n.c._group);
        const angle = i * 2.39996323;
        const radius = 14 * Math.sqrt(i + 0.5);
        n.x = a.x + radius * Math.cos(angle);
        n.y = a.y + radius * Math.sin(angle);
        n.vx = 0; n.vy = 0;
      }
      runSimulation(true);
    }

    function computeGeoLabels() {
      // Label each cluster at its settled centroid (anchors move slightly
      // during the simulation and frame-fit rescale).
      const acc = new Map();
      for (const n of nodes) {
        const a = geoAnchor(n.c._group);
        const label = a === GEO_HUB ? 'National' : n.c._group;
        if (!acc.has(label)) acc.set(label, { x: 0, y: 0, count: 0 });
        const slot = acc.get(label);
        slot.x += n.x; slot.y += n.y; slot.count++;
      }
      return Array.from(acc, ([label, s]) =>
        ({ label, x: s.x / s.count, y: s.y / s.count }));
    }

    function renderGeoLabels() {
      while (gGeo.firstChild) gGeo.removeChild(gGeo.firstChild);
      for (const l of layouts.geoLabels) {
        const t = svgEl('text', { class: 'geo-label', x: l.x, y: l.y });
        t.textContent = l.label;
        gGeo.appendChild(t);
      }
    }

    function animateTo(targets) {
      const from = snapshotPositions();
      const startTime = performance.now();
      const DURATION = 700;
      cancelAnimationFrame(animId);
      const step = (now) => {
        const t = Math.min((now - startTime) / DURATION, 1);
        const e = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
        for (let i = 0; i < nodes.length; i++) {
          nodes[i].x = from[i].x + (targets[i].x - from[i].x) * e;
          nodes[i].y = from[i].y + (targets[i].y - from[i].y) * e;
        }
        positionAll();
        if (t < 1) animId = requestAnimationFrame(step);
      };
      animId = requestAnimationFrame(step);
    }

    function setGeoLayout(on) {
      if (on && !layouts.geo) {
        const current = snapshotPositions();
        computeGeoLayout();
        layouts.geo = snapshotPositions();
        layouts.geoLabels = computeGeoLabels();
        renderGeoLabels();
        for (let i = 0; i < nodes.length; i++) {
          nodes[i].x = current[i].x;
          nodes[i].y = current[i].y;
        }
      }
      gGeo.classList.toggle('visible', on);
      animateTo(on ? layouts.geo : layouts.force);
    }

    function typeOptions() {
      const types = new Set();
      for (const c of custodians) for (const t of (c.types || [])) if (t) types.add(t);
      return Array.from(types).sort();
    }

    function renderControls() {
      const groupsInUse = new Set(custodians.map((c) => c._group));
      const bar = document.createElement('div');
      bar.className = 'filter-bar';
      bar.innerHTML =
        '<input type="search" class="search" id="net-search" placeholder="Search name, subject or dataset…" aria-label="Search custodians">' +
        GROUPS.filter((g) => groupsInUse.has(g.key)).map((g) =>
          '<button type="button" class="filter-chip" data-group="' + esc(g.key) + '">' +
          '<span class="dot" style="background:' + g.color + '"></span>' + esc(g.label) + '</button>').join('') +
        '<select id="net-type" aria-label="Custodian type"><option value="">All types</option>' +
        typeOptions().map((t) => '<option value="' + esc(t) + '">' + esc(t) + '</option>').join('') +
        '</select>' +
        '<button type="button" class="filter-chip" id="net-tre">Has TRE</button>' +
        '<button type="button" class="filter-chip" id="net-geo" ' +
        'title="Arrange custodians by their home state or territory">Geo layout</button>';
      container.appendChild(bar);

      bar.querySelector('#net-search').addEventListener('input', (evt) => {
        state.net.q = evt.target.value.trim().toLowerCase();
        applyClasses();
      });
      bar.querySelector('#net-type').addEventListener('change', (evt) => {
        state.net.type = evt.target.value;
        applyClasses();
      });
      bar.querySelector('#net-tre').addEventListener('click', (evt) => {
        state.net.tre = !state.net.tre;
        evt.currentTarget.classList.toggle('active', state.net.tre);
        applyClasses();
      });
      bar.querySelector('#net-geo').addEventListener('click', (evt) => {
        state.net.geo = !state.net.geo;
        evt.currentTarget.classList.toggle('active', state.net.geo);
        setGeoLayout(state.net.geo);
      });
      bar.addEventListener('click', (evt) => {
        const chip = evt.target.closest('[data-group]');
        if (!chip) return;
        const g = chip.dataset.group;
        if (state.net.groups.has(g)) state.net.groups.delete(g);
        else state.net.groups.add(g);
        chip.classList.toggle('active', state.net.groups.has(g));
        applyClasses();
      });
    }

    function matches(c) {
      const f = state.net;
      if (f.groups.size && !f.groups.has(c._group)) return false;
      if (f.type && !(c.types || []).includes(f.type)) return false;
      if (f.tre && !c._hasTre) return false;
      if (f.q && !c._haystack.includes(f.q)) return false;
      return true;
    }

    let hoverId = null;

    function applyClasses() {
      if (!built) return;
      const neighbor = new Set();
      if (hoverId) {
        neighbor.add(hoverId);
        for (const e of edges) {
          if (e.a.c.id === hoverId) neighbor.add(e.b.c.id);
          if (e.b.c.id === hoverId) neighbor.add(e.a.c.id);
        }
      }
      for (const n of nodes) {
        const g = n.el;
        const pass = matches(n.c);
        const dimmedByHover = hoverId && !neighbor.has(n.c.id);
        g.classList.toggle('dim', !pass || dimmedByHover);
        g.classList.toggle('selected', n.c.id === state.selectedId);
      }
      for (const e of edges) {
        const passes = matches(e.a.c) && matches(e.b.c);
        const touchesHover = hoverId && (e.a.c.id === hoverId || e.b.c.id === hoverId);
        e.el.classList.toggle('dim', !passes || (hoverId && !touchesHover));
        e.el.classList.toggle('hl', !!touchesHover);
      }
    }

    function applyZoom() {
      gZoom.setAttribute('transform',
        'translate(' + zoom.x + ',' + zoom.y + ') scale(' + zoom.k + ')');
    }

    function clientToWorld(evt) {
      const rect = svg.getBoundingClientRect();
      return {
        x: (evt.clientX - rect.left - zoom.x) / zoom.k,
        y: (evt.clientY - rect.top - zoom.y) / zoom.k
      };
    }

    function edgeTooltipHtml(e) {
      return e.dirs.map((d) =>
        '<div class="tt-title">' + esc(d.sourceName) + ' → ' + esc(d.targetName) + '</div>' +
        '<div>' + esc(truncate(d.segment || 'No reason text', 240)) + '</div>' +
        '<div class="tt-muted">' + esc(d.matchType || 'unknown') + ' · score ' + fmtScore(d.matchScore) + '</div>'
      ).join('<hr style="border:none;border-top:1px solid #2c2c34;margin:6px 0">');
    }

    function renderSvg() {
      const wrap = document.createElement('div');
      wrap.className = 'network-wrap';
      svg = svgEl('svg', { class: 'network-svg', role: 'img', 'aria-label': 'Custodian network map' });
      wrap.appendChild(svg);
      const hint = document.createElement('div');
      hint.className = 'network-hintbar';
      hint.textContent = 'Scroll to zoom · drag background to pan · drag nodes to rearrange · click a node for details';
      wrap.appendChild(hint);
      container.appendChild(wrap);

      gZoom = svgEl('g');
      gGeo = svgEl('g', { class: 'geo-labels' });
      gEdges = svgEl('g');
      gNodes = svgEl('g');
      gZoom.appendChild(gGeo);
      gZoom.appendChild(gEdges);
      gZoom.appendChild(gNodes);
      svg.appendChild(gZoom);

      for (const e of edges) {
        const line = svgEl('line', { class: 'net-edge' });
        const hit = svgEl('line', { class: 'net-edge-hit' });
        e.el = line;
        e.hitEl = hit;
        gEdges.appendChild(line);
        gEdges.appendChild(hit);
        hit.addEventListener('mouseenter', (evt) => showTooltip(edgeTooltipHtml(e), evt));
        hit.addEventListener('mousemove', moveTooltip);
        hit.addEventListener('mouseleave', hideTooltip);
      }

      for (const n of nodes) {
        const g = svgEl('g', { class: 'net-node' });
        const circle = svgEl('circle', { r: n.r, fill: n.c._color });
        const label = svgEl('text', { dy: n.r + 12 });
        label.textContent = n.c._label;
        g.appendChild(circle);
        g.appendChild(label);
        n.el = g;
        gNodes.appendChild(g);

        g.addEventListener('mouseenter', (evt) => {
          hoverId = n.c.id;
          applyClasses();
          showTooltip(
            '<div class="tt-title">' + esc(n.c.name) + '</div>' +
            '<div>' + esc(n.c.jurisdiction) + (n.c.type ? ' · ' + esc(n.c.type) : '') + '</div>' +
            '<div class="tt-muted">' + n.c.datasets.length + ' datasets · ' +
            n.c.steps.length + ' pathway steps</div>', evt);
        });
        g.addEventListener('mousemove', moveTooltip);
        g.addEventListener('mouseleave', () => {
          hoverId = null;
          applyClasses();
          hideTooltip();
        });
      }

      positionAll();
      attachInteractions();
    }

    function positionAll() {
      for (const e of edges) {
        for (const el of [e.el, e.hitEl]) {
          el.setAttribute('x1', e.a.x); el.setAttribute('y1', e.a.y);
          el.setAttribute('x2', e.b.x); el.setAttribute('y2', e.b.y);
        }
      }
      for (const n of nodes) {
        n.el.setAttribute('transform', 'translate(' + n.x + ',' + n.y + ')');
      }
    }

    function attachInteractions() {
      let mode = null; // 'pan' | 'drag'
      let dragNode = null;
      let start = null;
      let moved = 0;

      svg.addEventListener('pointerdown', (evt) => {
        const nodeG = evt.target.closest('.net-node');
        start = { x: evt.clientX, y: evt.clientY, zx: zoom.x, zy: zoom.y };
        moved = 0;
        if (nodeG) {
          mode = 'drag';
          dragNode = nodes.find((n) => n.el === nodeG) || null;
        } else {
          mode = 'pan';
          svg.classList.add('panning');
        }
        svg.setPointerCapture(evt.pointerId);
      });

      svg.addEventListener('pointermove', (evt) => {
        if (!mode) return;
        moved += Math.abs(evt.movementX || 0) + Math.abs(evt.movementY || 0);
        if (mode === 'pan') {
          zoom.x = start.zx + (evt.clientX - start.x);
          zoom.y = start.zy + (evt.clientY - start.y);
          applyZoom();
        } else if (mode === 'drag' && dragNode) {
          const w = clientToWorld(evt);
          dragNode.x = w.x;
          dragNode.y = w.y;
          positionAll();
        }
      });

      svg.addEventListener('pointerup', (evt) => {
        if (mode === 'drag' && dragNode && moved < 5) {
          selectCustodian(dragNode.c.id);
        }
        mode = null;
        dragNode = null;
        svg.classList.remove('panning');
        try { svg.releasePointerCapture(evt.pointerId); } catch (err) { /* already released */ }
      });

      svg.addEventListener('wheel', (evt) => {
        evt.preventDefault();
        const rect = svg.getBoundingClientRect();
        const px = evt.clientX - rect.left;
        const py = evt.clientY - rect.top;
        const oldK = zoom.k;
        const k = Math.min(6, Math.max(0.25, oldK * Math.exp(-evt.deltaY * 0.0016)));
        // keep the world point under the cursor fixed
        zoom.x = px - ((px - zoom.x) / oldK) * k;
        zoom.y = py - ((py - zoom.y) / oldK) * k;
        zoom.k = k;
        applyZoom();
      }, { passive: false });
    }

    function fitToContainer() {
      const rect = svg.getBoundingClientRect();
      if (rect.width < 50 || rect.height < 50) return;
      const k = Math.min(rect.width / W, rect.height / H);
      zoom.k = k;
      zoom.x = (rect.width - W * k) / 2;
      zoom.y = (rect.height - H * k) / 2;
      applyZoom();
    }

    function onShow() {
      if (!built) {
        buildGraph();
        renderControls();
        renderSvg();
        built = true;
        requestAnimationFrame(fitToContainer);
      }
      applyClasses();
    }

    return { onShow, applyClasses };
  })();

  // ------------------------------------------------------------------
  // Pathways view (metro / trainline diagram)
  // ------------------------------------------------------------------
  const pathways = (function () {
    const container = document.getElementById('view-pathways');
    let built = false;
    let listEl, diagramEl;

    function build() {
      container.innerHTML =
        '<div class="pathways-layout">' +
        '<div class="pathways-list">' +
        '<input type="search" class="search" id="pw-search" placeholder="Search custodians…" aria-label="Search custodians">' +
        '<ul id="pw-list"></ul></div>' +
        '<div class="pathways-diagram" id="pw-diagram"></div>' +
        '</div>';
      listEl = container.querySelector('#pw-list');
      diagramEl = container.querySelector('#pw-diagram');

      container.querySelector('#pw-search').addEventListener('input', (evt) => {
        state.pw.q = evt.target.value.trim().toLowerCase();
        renderList();
      });
      listEl.addEventListener('click', (evt) => {
        const btn = evt.target.closest('button[data-id]');
        if (!btn) return;
        state.pw.custodianId = btn.dataset.id;
        selectCustodian(btn.dataset.id);
        renderList();
        renderDiagram();
      });
      built = true;
    }

    function renderList() {
      const q = state.pw.q;
      const items = custodians.filter((c) => !q || c.name.toLowerCase().includes(q) ||
        (c.subject || '').toLowerCase().includes(q));
      listEl.innerHTML = items.map((c) =>
        '<li><button type="button" data-id="' + esc(c.id) + '"' +
        (c.id === state.pw.custodianId
          ? ' class="active" style="border-left-color:' + c._color + '"'
          : ' style="border-left-color:' + c._color + '55"') + '>' +
        '<div class="pl-name">' + esc(c.name) + '</div>' +
        '<div class="pl-meta">' + c.steps.length + ' step' + (c.steps.length === 1 ? '' : 's') +
        (c.timeline ? ' · ' + esc(truncate(c.timeline, 46)) : '') + '</div>' +
        '</button></li>').join('') ||
        '<li><div class="panel-hint" style="padding:8px 12px">No custodians match.</div></li>';
    }

    function wrapLabel(text, maxChars, maxLines) {
      const words = String(text || '').split(/\s+/);
      const lines = [];
      let current = '';
      for (const word of words) {
        if ((current + ' ' + word).trim().length > maxChars && current) {
          lines.push(current);
          current = word;
          if (lines.length === maxLines) break;
        } else {
          current = (current + ' ' + word).trim();
        }
      }
      if (lines.length < maxLines && current) lines.push(current);
      else if (lines.length === maxLines && current) {
        lines[maxLines - 1] = truncate(lines[maxLines - 1] + '…', maxChars + 1);
      }
      return lines;
    }

    function renderDiagram() {
      const c = custodianById.get(state.pw.custodianId);
      if (!c) {
        diagramEl.innerHTML =
          '<div class="diagram-empty">Select a custodian on the left to draw its access pathway ' +
          'as a metro-style line across the Researcher, Ethics &amp; Regulatory and Custodian lanes.</div>';
        return;
      }
      const steps = c.steps;
      if (!steps.length) {
        diagramEl.innerHTML = '<div class="diagram-empty">' + esc(c.name) +
          ' has no parsed pathway steps.</div>';
        return;
      }

      const SPACING = 170;
      const X0 = 150;
      const laneY = [95, 240, 385];
      const height = 470;
      const width = Math.max(X0 + SPACING * (steps.length - 1) + 130, 760);
      const color = c._color;

      const svg = svgEl('svg', {
        width, height,
        viewBox: '0 0 ' + width + ' ' + height,
        role: 'img', 'aria-label': 'Pathway diagram for ' + c.name
      });

      // Lane bands + labels
      LANES.forEach((lane, i) => {
        svg.appendChild(svgEl('rect', {
          class: 'metro-lane-band',
          x: 0, y: laneY[i] - 62, width, height: 124, fill: lane.tint
        }));
        const lbl = svgEl('text', { class: 'metro-lane-label', x: 12, y: laneY[i] - 44 });
        lbl.textContent = lane.label;
        svg.appendChild(lbl);
      });

      const pts = steps.map((s, i) => ({
        x: X0 + i * SPACING,
        y: laneY[LANE_INDEX.has(s.lane) ? LANE_INDEX.get(s.lane) : 0],
        step: s
      }));

      // Smooth connecting line: straight in-lane, S-curve between lanes.
      let d = 'M ' + pts[0].x + ' ' + pts[0].y;
      for (let i = 1; i < pts.length; i++) {
        const p0 = pts[i - 1], p1 = pts[i];
        if (p0.y === p1.y) {
          d += ' L ' + p1.x + ' ' + p1.y;
        } else {
          const mx = (p0.x + p1.x) / 2;
          d += ' C ' + mx + ' ' + p0.y + ' ' + mx + ' ' + p1.y + ' ' + p1.x + ' ' + p1.y;
        }
      }
      svg.appendChild(svgEl('path', { class: 'metro-line', d, stroke: color, 'stroke-width': 6 }));

      // Stations
      for (const p of pts) {
        const s = p.step;
        const selected = state.selectedStep &&
          state.selectedStep.custodianId === c.id && state.selectedStep.order === s.order;
        const g = svgEl('g', {
          class: 'metro-station' + (selected ? ' selected' : ''),
          transform: 'translate(' + p.x + ',' + p.y + ')'
        });
        g.appendChild(svgEl('circle', { class: 'outer', r: 11, stroke: color }));
        const num = svgEl('text', { class: 'num', dy: 3.5, fill: color });
        num.textContent = s.order;
        g.appendChild(num);

        const lines = wrapLabel(s.text, 24, 2);
        lines.forEach((ln, li) => {
          const t = svgEl('text', { class: 'lbl', y: 24 + li * 12 });
          t.textContent = ln;
          g.appendChild(t);
        });
        if (s.timeline) {
          const t = svgEl('text', { class: 'tl', y: 24 + lines.length * 12 + 1 });
          t.textContent = truncate(s.timeline, 28);
          g.appendChild(t);
        }

        g.addEventListener('click', () => {
          state.selectedStep = { custodianId: c.id, order: s.order };
          selectCustodian(c.id, { keepStep: true });
          renderDiagram(); // refresh selected ring
        });
        g.addEventListener('mouseenter', (evt) => showTooltip(
          '<div class="tt-title">Step ' + esc(s.order) + ' · ' + esc(LANE_LABEL(s.lane)) + '</div>' +
          '<div>' + esc(truncate(s.text, 220)) + '</div>' +
          (s.timeline ? '<div class="tt-muted">' + esc(s.timeline) + '</div>' : ''), evt));
        g.addEventListener('mousemove', moveTooltip);
        g.addEventListener('mouseleave', hideTooltip);
        svg.appendChild(g);
      }

      diagramEl.innerHTML = '';
      diagramEl.appendChild(svg);
    }

    function render() {
      if (!built) build();
      // Pathway choice and global selection are kept in sync (list clicks
      // also select the custodian), so prefer the global selection.
      if (state.selectedId) state.pw.custodianId = state.selectedId;
      renderList();
      renderDiagram();
    }

    function syncSelection() {
      if (state.selectedId && state.selectedId !== state.pw.custodianId) {
        state.pw.custodianId = state.selectedId;
        if (built) { renderList(); renderDiagram(); }
      } else if (built) {
        renderDiagram();
      }
    }

    return { render, syncSelection };
  })();

  // ------------------------------------------------------------------
  // Datasets view
  // ------------------------------------------------------------------
  const datasets = (function () {
    const container = document.getElementById('view-datasets');
    let built = false;
    let gridEl, countEl;

    const FLAG_FILTERS = [
      { value: '', label: 'All' },
      { value: 'yes', label: 'Yes' },
      { value: 'no', label: 'No' },
      { value: 'partial', label: 'Partial' }
    ];

    function flagMatches(value, filter) {
      if (!filter) return true;
      const v = String(value || '').trim().toLowerCase();
      return v.startsWith(filter);
    }

    function build() {
      container.innerHTML =
        '<div class="filter-bar">' +
        '<input type="search" class="search" id="ds-search" placeholder="Search datasets…" aria-label="Search datasets">' +
        '<select id="ds-custodian" aria-label="Filter by custodian"><option value="">All custodians</option>' +
        custodians.map((c) => '<option value="' + esc(c.id) + '">' + esc(truncate(c.name, 56)) + '</option>').join('') +
        '</select>' +
        '<span class="filter-label">Identifiable:</span><span id="ds-ident"></span>' +
        '<span class="filter-label">Linkable:</span><span id="ds-link"></span>' +
        '</div>' +
        '<p class="result-count" id="ds-count"></p>' +
        '<div class="dataset-grid" id="ds-grid"></div>';
      gridEl = container.querySelector('#ds-grid');
      countEl = container.querySelector('#ds-count');

      for (const which of ['identifiable', 'linkable']) {
        const holder = container.querySelector(which === 'identifiable' ? '#ds-ident' : '#ds-link');
        holder.innerHTML = FLAG_FILTERS.map((f) =>
          '<button type="button" class="filter-chip' + (f.value === '' ? ' active' : '') +
          '" data-flag="' + which + '" data-value="' + f.value + '">' + f.label + '</button>').join('');
      }

      container.querySelector('#ds-search').addEventListener('input', (evt) => {
        state.ds.q = evt.target.value.trim().toLowerCase();
        renderGrid();
      });
      container.querySelector('#ds-custodian').addEventListener('change', (evt) => {
        state.ds.custodian = evt.target.value;
        renderGrid();
      });
      container.addEventListener('click', (evt) => {
        const flagBtn = evt.target.closest('[data-flag]');
        if (flagBtn) {
          const which = flagBtn.dataset.flag;
          state.ds[which] = flagBtn.dataset.value;
          for (const b of container.querySelectorAll('[data-flag="' + which + '"]')) {
            b.classList.toggle('active', b.dataset.value === state.ds[which]);
          }
          renderGrid();
          return;
        }
        const custBtn = evt.target.closest('.custodian-link');
        if (custBtn) {
          selectCustodian(custBtn.dataset.id);
          return;
        }
        const moreBtn = evt.target.closest('.more-btn');
        if (moreBtn) {
          const p = moreBtn.closest('.dataset-desc');
          p.innerHTML = esc(p.dataset.full);
        }
      });
      built = true;
    }

    function syncControls() {
      container.querySelector('#ds-search').value = state.ds.q;
      container.querySelector('#ds-custodian').value = state.ds.custodian;
      for (const b of container.querySelectorAll('[data-flag]')) {
        b.classList.toggle('active', b.dataset.value === state.ds[b.dataset.flag]);
      }
    }

    function renderGrid() {
      const f = state.ds;
      const rows = DATA.datasets.filter((d) =>
        (!f.custodian || d.custodianId === f.custodian) &&
        flagMatches(d.identifiable, f.identifiable) &&
        flagMatches(d.linkable, f.linkable) &&
        (!f.q || (d.name + ' ' + d.description + ' ' + d.custodianName).toLowerCase().includes(f.q)));

      countEl.textContent = rows.length + ' of ' + DATA.datasets.length +
        ' dataset entries' + (f.custodian || f.q || f.identifiable || f.linkable ? ' (filtered)' : '');

      gridEl.innerHTML = rows.map((d) => {
        const desc = String(d.description || '').trim();
        const isLong = desc.length > 180;
        const shown = isLong ? truncate(desc, 180) : desc;
        return '<div class="dataset-card">' +
          '<h3>' + esc(d.name) + '</h3>' +
          '<button type="button" class="custodian-link" data-id="' + esc(d.custodianId) + '">' +
          esc(d.custodianName) + '</button>' +
          '<div class="badge-row">' +
          badgeHtml('Identifiable', d.identifiable) +
          badgeHtml('Linkable', d.linkable) +
          '</div>' +
          (desc
            ? '<p class="dataset-desc" data-full="' + esc(desc) + '">' + esc(shown) +
              (isLong ? '<button type="button" class="more-btn">more</button>' : '') + '</p>'
            : '') +
          '</div>';
      }).join('') || '<p class="panel-hint">No datasets match the current filters.</p>';
    }

    function render() {
      if (!built) build();
      syncControls();
      renderGrid();
    }

    return { render };
  })();

  // ------------------------------------------------------------------
  // Theme (dark is the DHCRC signature look; light uses the brand
  // background grey #D9D8D6 with black text and red/blue accents)
  // ------------------------------------------------------------------
  (function () {
    const STORAGE_KEY = 'atlasTheme';
    const btn = document.getElementById('theme-toggle');

    function apply(name) {
      document.body.classList.toggle('theme-light', name === 'light');
      btn.textContent = name === 'light' ? '☾' : '☼';
      btn.title = 'Switch to ' + (name === 'light' ? 'dark' : 'light') + ' theme';
    }

    let initial = 'dark';
    // localStorage can throw on file:// or in private browsing.
    try { if (window.localStorage.getItem(STORAGE_KEY) === 'light') initial = 'light'; }
    catch (err) { /* ignore */ }
    if (window.location.hash === '#light') initial = 'light';
    else if (window.location.hash === '#dark') initial = 'dark';
    apply(initial);

    btn.addEventListener('click', () => {
      const next = document.body.classList.contains('theme-light') ? 'dark' : 'light';
      apply(next);
      try { window.localStorage.setItem(STORAGE_KEY, next); } catch (err) { /* ignore */ }
    });
  })();

  // ------------------------------------------------------------------
  // Intro / about modal
  // ------------------------------------------------------------------
  const intro = (function () {
    const STORAGE_KEY = 'atlasIntroDismissed';
    const overlay = document.getElementById('intro-overlay');
    const dontShow = document.getElementById('intro-dontshow');

    // localStorage can throw on file:// or in private browsing — degrade
    // to always showing the intro rather than breaking the page.
    function getDismissed() {
      try { return window.localStorage.getItem(STORAGE_KEY) === '1'; }
      catch (err) { return false; }
    }
    function setDismissed(value) {
      try {
        if (value) window.localStorage.setItem(STORAGE_KEY, '1');
        else window.localStorage.removeItem(STORAGE_KEY);
      } catch (err) { /* ignore */ }
    }

    function fillDynamicText() {
      const meta = DATA.meta || {};
      const counts = meta.counts || {};
      if (counts.custodians) {
        document.getElementById('intro-counts').textContent =
          counts.custodians + ' data custodians';
      }
      const prov = meta.provenance || {};
      const bundleDate = (meta.generatedAt || '').slice(0, 10);
      const bits = [];
      if (prov.registerGenerated) bits.push('register dated ' + prov.registerGenerated);
      if (bundleDate) bits.push('this bundle was generated on ' + bundleDate);
      if (bits.length) {
        document.getElementById('intro-freshness').textContent =
          ' (' + bits.join('; ') + ')';
      }
    }

    function open() {
      dontShow.checked = getDismissed();
      overlay.classList.remove('hidden');
      document.getElementById('intro-start').focus();
    }
    function close() {
      setDismissed(dontShow.checked);
      overlay.classList.add('hidden');
    }

    document.getElementById('about-btn').addEventListener('click', open);
    document.getElementById('intro-close').addEventListener('click', close);
    document.getElementById('intro-start').addEventListener('click', close);
    overlay.addEventListener('click', (evt) => {
      if (evt.target === overlay) close();
    });
    document.addEventListener('keydown', (evt) => {
      if (evt.key === 'Escape' && !overlay.classList.contains('hidden')) close();
    });

    fillDynamicText();
    return { open, getDismissed };
  })();

  // ------------------------------------------------------------------
  // Init
  // ------------------------------------------------------------------
  renderChrome();
  renderDetail();
  network.onShow();
  if (!intro.getDismissed()) intro.open();
})();
