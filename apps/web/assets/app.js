/* 金十DSH 工作台 V0.1b —— 数据源 data/web/（视图层，nginx gzip_static + immutable 缓存） */
(function () {
  'use strict';

  var DAYS = [];          // index.json 日期清单（倒序）
  var CACHE = {};         // 日期 → day 视图（内存缓存；浏览器 immutable 缓存兜底）
  var DETAIL_CACHE = {};  // 日期 → detail 视图（懒加载）
  var currentDay = null;  // 当前日期（'latest' 或 'YYYY-MM-DD'）
  var currentView = 'signal';
  var selectedThemeId = null;
  var selectedSectorId = null;
  var expandedThemeIds = {};
  var selectedThemeConceptKey = null;
  var themeRealtime = false;
  var themeRealtimeTimer = null;
  var themeRealtimeView = null;
  var themeArchiveDay = null;
  var themeRealtimeStatus = '';
  var SECTOR_INDEX = {};
  var SECTOR_DETAIL = {};
  var selectedSubSectorId = null;
  var sectorFilter = 'all';
  var sectorRealtime = false;
  var sectorRealtimeTimer = null;
  var sectorForceHistory = false;
  var sectorForceRealtime = false;
  var SECTOR_TODAY_VALUE = '__sector_today_realtime__';
  var sectorChartCollapsed = false;
  var lastSectorIntraday = null;
  var sectorSortKey = 'position_rank';
  var sectorSortDir = 1;
  var lastSectorRows = [];

  function $(id) { return document.getElementById(id); }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function code6(sid) { return String(sid || '').slice(2); }
  function stk(sid, name) { return '<a class="stk" href="http://www.treeid/code_' + esc(code6(sid)) + '" title="通达信联动">' + esc(name) + '</a>'; }
  function fmtMoney(n) { n = Number(n) || 0; var a = Math.abs(n); if (a >= 1e8) return (n / 1e8).toFixed(2) + '亿'; if (a >= 1e4) return (n / 1e4).toFixed(2) + '万'; return n.toFixed(0); }
  function fmtPct(n) { n = Number(n); return isNaN(n) ? '-' : (n >= 0 ? '+' : '') + n.toFixed(2) + '%'; }
  function cls(n) { return Number(n) >= 0 ? 'up' : 'dn'; }
  function modelNames(hit) { return (hit.model_names && hit.model_names.length ? hit.model_names : (hit.model_hit || [])); }

  function fetchJSON(url, cacheMode) {
    return fetch(url, { cache: cacheMode || 'default' }).then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); });
  }
  function dayFile(date) { return 'data/web/day_' + date + '.json'; }

  /* ---------- 主数据懒加载库（题材/板块/成分，进题材/板块 tab 时拉，内存缓存） ---------- */
  var LIBS = {};
  var focusTag = null;
  function loadLib(name) {
    var key = name.replace(/\.json$/, '');
    if (LIBS[key]) return Promise.resolve(LIBS[key]);
    return fetchJSON('data/web/' + name).then(function (d) { LIBS[key] = d; return d; });
  }
  function loadExpandLibs() {
    return Promise.all([loadLib('theme_stocks.json'), loadLib('stocks_slim.json')]);
  }
  function goTag(type, id) {
    focusTag = { type: type, id: id };
    var view = type === 'theme' ? 'theme' : 'sector';
    document.querySelectorAll('.tab').forEach(function (t) { t.classList.toggle('active', t.dataset.view === view); });
    currentView = view;
    if (history.replaceState) history.replaceState(null, '', '#' + view);
    render();
  }
  function limitupSet() {
    var view = activeThemeView();
    return new Set((view.limitup || []).map(function (e) { return e.stock_id; }));
  }

  function activeThemeView() {
    return (themeRealtime && themeRealtimeView) ? themeRealtimeView : (CACHE[currentDay] || {});
  }
  function memberTable(sids, total) {
    var slim = LIBS.stocks_slim || {}, sectors = LIBS.sectors || {}, themes = LIBS.themes || {};
    var lu = limitupSet();
    var rows = sids.map(function (sid) {
      var m = slim[sid] || { n: sid, s: [], t: [] };
      var secTags = (m.s || []).slice(0, 4).map(function (s) {
        return '<span class="tag-chip sec" data-go="sector" data-id="' + esc(s) + '">' + esc((sectors[s] || {}).name || s) + '</span>';
      }).join('');
      var thTags = (m.t || []).slice(0, 4).map(function (t) {
        return '<span class="tag-chip thm" data-go="theme" data-id="' + esc(t) + '">' + esc((themes[t] || {}).name || t) + '</span>';
      }).join('');
      var zt = lu.has(sid) ? '<span class="badge b-boards">涨停</span>' : '';
      return '<tr><td class="l">' + stk(sid, code6(sid)) + '</td><td class="l">' + esc(m.n) + '</td>' +
        '<td class="l">' + secTags + thTags + '</td><td>' + zt + '</td></tr>';
    }).join('');
    return '<div class="tblwrap"><table><thead><tr><th class="l">代码</th><th class="l">名称</th><th class="l">板块 / 题材</th><th>状态</th></tr></thead><tbody>' +
      (rows || '<tr><td colspan="4" class="muted">无成分股</td></tr>') + '</tbody></table></div>' +
      (total > sids.length ? '<div class="disc">仅展示前 ' + sids.length + ' 只（共 ' + total + ' 只）</div>' : '');
  }
  function sectorMembers(sid) {
    var slim = LIBS.stocks_slim || {};
    return Object.keys(slim).filter(function (s) { return (slim[s].s || []).indexOf(sid) >= 0; });
  }

  /* ---------- 数据加载 ---------- */
  function loadIndex() {
    return fetchJSON('data/web/index.json').then(function (idx) {
      SECTOR_INDEX = idx;
      DAYS = idx.days || [];
      var sel = $('dateSel');
      sel.innerHTML = '';
      var todayOption = document.createElement('option');
      todayOption.value = SECTOR_TODAY_VALUE; todayOption.textContent = '当天 · 实时';
      sel.appendChild(todayOption);
      DAYS.forEach(function (d) {
        var o = document.createElement('option');
        o.value = d.date; o.textContent = d.date;
        sel.appendChild(o);
      });
      if (DAYS.length) { sel.value = DAYS[0].date; return loadDay(DAYS[0].date); }
      renderEmpty('暂无数据：请先运行 archive_job 生成 data/web/');
      return null;
    }).catch(function (e) { renderEmpty('加载失败：' + e.message); });
  }

  function loadDay(date) {
    currentDay = date;
    if (CACHE[date]) { render(); return Promise.resolve(CACHE[date]); }
    return fetchJSON(dayFile(date), date === 'latest' ? 'no-cache' : 'default').then(function (view) {
      CACHE[date] = view;
      render();
      return view;
    }).catch(function (e) { renderEmpty('加载 ' + date + ' 失败：' + e.message); });
  }

  /* ---------- 视图渲染 ---------- */
  function render() {
    var view = CACHE[currentDay];
    if (!view) return;
    var html = '';
    if (currentView === 'signal') html = vSignal(view);
    else if (currentView === 'theme') html = vTheme(view);
    else if (currentView === 'sector') html = vSector(view);
    else if (currentView === 'strategy') html = vStrategy(view);
    else if (currentView === 'history') html = vHistory(view);
    $('main').innerHTML = html;
  }

  function renderEmpty(msg) {
    $('main').innerHTML = '<section class="empty-state"><h1>金十DSH 工作台</h1><p>' + esc(msg) + '</p></section>';
  }

  function card(title, sub, body, flush) {
    return '<section class="card"><div class="card-h"><span>' + title + '</span>' +
      (sub ? '<span class="sub">' + sub + '</span>' : '') + '</div><div class="card-b' + (flush ? ' flush' : '') + '">' + body + '</div></section>';
  }

  function reasonCell(sid, entry) {
    var txt = entry && entry.reason ? entry.reason : '-';
    var n = entry ? (entry.sourceCount || 1) : 1;
    return '<button type="button" class="reason-pop" data-sid="' + esc(sid) + '" style="background:transparent;border:1px solid #30363d;color:#58a6ff;border-radius:6px;padding:2px 8px;font-size:12px;cursor:pointer">' +
      esc(txt) + '<span class="badge b-src">' + n + '源</span></button>';
  }

  /* 实时信号：涨停池 + 资金流 + 领涨原因 + 盘中事件流 */
  var EVT_META = { limitup: '🚀 涨停', broken: '💥 炸板', signal_hit: '🎯 模型命中',
                   ladder_up: '🪜 晋级', leader_change: '👑 龙头易主', sector_boom: '🔥 板块爆发',
                   volume_surge: '⚡ 量比异动', index_resonance: '📈 指数共振' };
  function vSignal(view) {
    var lu = view.limitup || [];
    var rows = lu.map(function (e, i) {
      var concepts = (e.concepts || []).map(function (c) { return '<span class="badge b-src">' + esc(c) + '</span>'; }).join('');
      return '<tr><td class="l">' + (i + 1) + '</td><td class="l">' + stk(e.stock_id, code6(e.stock_id)) + '</td>' +
        '<td class="l">' + stk(e.stock_id, e.name || e.stock_id) + '</td>' +
        '<td>' + (e.boards ? '<span class="badge b-boards">' + esc(e.boards) + '</span>' : '-') + '</td>' +
        '<td class="l">' + reasonCell(e.stock_id, e) + '</td><td class="l">' + concepts + '</td>' +
        '<td>' + esc(e.first_time || '-') + '</td><td>' + fmtMoney(e.seal_amount) + '</td></tr>';
    }).join('');
    var luTable = '<div class="tblwrap"><table><thead><tr><th>#</th><th class="l">代码</th><th class="l">名称</th><th>连板</th><th class="l">涨停原因</th><th class="l">题材</th><th>首次</th><th>封单</th></tr></thead><tbody>' +
      (rows || '<tr><td colspan="8" class="muted">暂无涨停数据</td></tr>') + '</tbody></table></div>';

    var mf = (view.money_flow || []).slice(0, 10).map(function (f) {
      return '<tr><td class="l">' + esc(f.name) + '</td><td class="' + cls(f.main) + '">' + fmtMoney(f.main) + '</td><td class="' + cls(f.main_pct) + '">' + fmtPct(f.main_pct) + '</td></tr>';
    }).join('');
    var mfCard = card('💧 板块资金流 TOP10', '主力净流入排行', '<div class="tblwrap"><table><thead><tr><th class="l">板块</th><th>主力净流入</th><th>占比</th></tr></thead><tbody>' + (mf || '<tr><td colspan="3" class="muted">暂无</td></tr>') + '</tbody></table></div>');

    var lr = (view.leading_reason || []).map(function (p) {
      return '<div class="lead-item"><div class="lead-name">' + esc(p.name) + '</div><div class="lead-reason">' + esc(p.reason || '-') + '</div></div>';
    }).join('');
    var lrCard = card('🔥 领涨原因', '选股宝板块', lr || '<div class="muted" style="padding:12px">暂无</div>');

    /* 盘中事件流（realtime_engine 输出，最新在前） */
    var evs = (view.events || []).slice(0, 30).map(function (e) {
      var label = EVT_META[e.type] || e.type;
      var t = String(e.ts || '').split('T')[1] || '';
      return '<div class="evt-item"><span class="badge ' + (e.type === 'broken' ? 'b-dn' : 'b-up') + '">' + esc(label) + '</span>' +
        '<span class="evt-time">' + esc(t) + '</span>' +
        (e.stock_id ? stk(e.stock_id, code6(e.stock_id)) + ' ' : '') +
        '<span class="evt-detail">' + esc(e.detail || '') + '</span></div>';
    }).join('');
    var evtCard = card('📡 盘中事件流', '涨停/炸板/模型命中/量比异动', evs || '<div class="muted" style="padding:12px">暂无事件</div>');

    return card('🚀 涨停池', currentDay + ' · ' + (view.market.limit_up != null ? view.market.limit_up + ' 只涨停' : '实时检测'), luTable, true) +
      evtCard +
      '<div class="grid2">' + mfCard + lrCard + '</div>';
  }

  /* 题材库：参考金十题材库的左列表 / 中详情 / 右直播三栏布局。 */
  function vTheme(view) {
    Promise.all([loadLib('themes.json'), loadExpandLibs()]).then(function () { renderThemeWorkbench(view); });
    return '<div class="theme-workbench">' +
      '<aside class="theme-sidebar"><div class="panel-brand"><strong>金十题材库</strong><span id="themeMeta">加载中…</span></div>' +
      '<div class="panel-search"><input id="themeSearch" placeholder="搜索题材…"></div>' +
      '<div class="panel-sort"><span class="active">🔥 当日涨停数排序</span><span>成分股</span></div>' +
      '<div id="themeList" class="theme-nav-list"><div class="loading">加载中…</div></div></aside>' +
      '<section class="theme-detail"><div class="detail-bar"><h1 id="themeTitle">🏆 金十题材库</h1><div class="theme-mode-controls">' +
      '<select id="themeDateSel" class="theme-date-select" aria-label="题材历史日期"></select>' +
      '<button type="button" id="themeRealtimeToggle" class="theme-realtime-toggle" aria-pressed="false"><i></i>今日实时</button>' +
      '<span id="themeModeStatus">历史收盘</span></div><span id="themeCount"></span></div>' +
      '<div id="themeContent" class="detail-content"><div class="empty-state">点击左侧题材查看详情</div></div></section>' +
      '<aside class="theme-live"><div class="live-panel-title"><span class="live-dot"></span>实时直播播报</div>' +
      '<div id="themeLiveList" class="live-feed"></div></aside></div>';
  }

  function renderThemeWorkbench(view) {
    var kw = ($('themeSearch') ? $('themeSearch').value : '').trim();
    var themes = LIBS.themes || {};
    var ids = Object.keys(themes).filter(function (t) { return !kw || (themes[t].name || '').indexOf(kw) >= 0; });
    var themeLimitup = view.theme_limitup || {};
    ids.sort(function (a, b) {
      var ztDiff = (themeLimitup[b] || []).length - (themeLimitup[a] || []).length;
      return ztDiff || (themes[b].hot || 0) - (themes[a].hot || 0) || (themes[b].stock_count || 0) - (themes[a].stock_count || 0);
    });
    if (focusTag && focusTag.type === 'theme') selectedThemeId = focusTag.id;
    if (!selectedThemeId || !themes[selectedThemeId]) selectedThemeId = ids[0] || null;
    if ($('themeMeta')) $('themeMeta').textContent = '总题材 ' + Object.keys(themes).length + ' · 涨停 ' + (view.limitup || []).length + '只';
    var html = ids.map(function (tid) {
      var t = themes[tid] || {};
      var concepts = (view.theme_concept_limitup || {})[tid] || [];
      var children = expandedThemeIds[tid] ? '<div class="theme-concept-children">' + concepts.map(function (item) {
        var key = themeConceptKey(item.level, item.parent || '', item.name);
        return '<div class="theme-concept-row level-' + item.level + (key === selectedThemeConceptKey ? ' selected' : '') + '" data-tid="' + esc(tid) + '" data-concept-key="' + key + '">' +
          '<span class="concept-level">' + (item.level === 1 ? '主' : '细') + '</span><span class="concept-name">' +
          esc(item.level === 2 ? (item.parent + ' / ' + item.name) : item.name) + '</span><b>' + item.stock_ids.length + '</b></div>';
      }).join('') + (concepts.length ? '' : '<div class="theme-concept-empty">当日无涨停概念</div>') + '</div>' : '';
      return '<div class="theme-nav-group"><div class="theme-nav-row' + (tid === selectedThemeId ? ' active' : '') + '" data-tid="' + esc(tid) + '">' +
        '<button type="button" class="theme-toggle" data-tid="' + esc(tid) + '" aria-label="展开' + esc(t.name || tid) + '">' + (expandedThemeIds[tid] ? '▾' : '▸') + '</button><span class="theme-name">' + esc(t.name || tid) + '</span>' +
        '<span class="theme-zt-count">涨停 ' + (themeLimitup[tid] || []).length + '</span>' +
        '<span class="theme-stock-count">' + (t.stock_count || 0) + '只</span></div>' + children + '</div>';
    }).join('');
    $('themeList').innerHTML = ids.length ? html : '<div class="muted" style="padding:12px">无匹配题材</div>';
    renderThemeDetail(view, selectedThemeId);
    renderThemeLive(view);
    syncThemeModeControls(view);
  }

  function themeConceptKey(level, parent, name) {
    return encodeURIComponent([level, parent || '', name || ''].join('|'));
  }

  function locateThemeConcept(tid, key) {
    selectedThemeId = tid;
    selectedThemeConceptKey = key;
    renderThemeWorkbench(activeThemeView());
    window.setTimeout(function () {
      var row = document.querySelector('.concept-table [data-concept-key="' + key + '"]');
      if (!row) return;
      var tableScroll = row.closest('.concept-table-scroll');
      var detailScroll = row.closest('.detail-content');
      var section = row.closest('.detail-section');
      if (detailScroll && section) {
        var detailRect = detailScroll.getBoundingClientRect();
        var sectionRect = section.getBoundingClientRect();
        detailScroll.scrollTo({ top: detailScroll.scrollTop + sectionRect.top - detailRect.top - 8, behavior: 'smooth' });
      }
      if (tableScroll) {
        var tableRect = tableScroll.getBoundingClientRect();
        var rowRect = row.getBoundingClientRect();
        var offset = row.tagName === 'TD' ? 8 : Math.max(8, (tableScroll.clientHeight - Math.min(rowRect.height, tableScroll.clientHeight)) / 2);
        tableScroll.scrollTo({ top: tableScroll.scrollTop + rowRect.top - tableRect.top - offset, behavior: 'smooth' });
      }
      row.classList.add('concept-target');
      window.setTimeout(function () { row.classList.remove('concept-target'); }, 2400);
    }, 30);
  }

  function renderThemeDetail(view, tid) {
    if (!tid || !$('themeContent')) return;
    var t = (LIBS.themes || {})[tid] || {};
    var sids = (LIBS.theme_stocks || {})[tid] || [];
    var ztIds = new Set((view.theme_limitup || {})[tid] || []);
    var slim = LIBS.stocks_slim || {};
    $('themeTitle').textContent = '🏆 ' + (t.name || tid);
    $('themeCount').textContent = '涨停 ' + ztIds.size + ' 只 · 成分股 ' + sids.length + ' 只';
    function stockPills(stocks) {
      return (stocks || []).map(function (sid) {
        var name = (slim[sid] || {}).n || sid;
        return '<a class="stock-pill' + (ztIds.has(sid) ? ' zt' : '') + '" href="http://www.treeid/code_' + code6(sid) + '">' +
          esc(code6(sid)) + ' ' + esc(name) + '</a>';
      }).join('') || '<span class="no-stocks">-</span>';
    }
    var treeRows = [];
    (t.tree || []).forEach(function (l1) {
      var l2s = l1.l2 || [];
      if (l2s.length) {
        l2s.forEach(function (l2, index) {
          var rowKey = themeConceptKey(2, l1.n1, l2.n2);
          var mainKey = themeConceptKey(1, '', l1.n1);
          treeRows.push('<tr data-concept-key="' + rowKey + '">' + (index === 0 ? '<td class="td-l1" data-concept-key="' + mainKey + '" rowspan="' + l2s.length + '"><span class="l1-name">' + esc(l1.n1) + '</span></td>' : '') +
            '<td class="td-l2">' + esc(l2.n2) + '</td><td class="td-stocks">' + stockPills(l2.st) + '</td></tr>');
        });
      } else {
        treeRows.push('<tr data-concept-key="' + themeConceptKey(1, '', l1.n1) + '"><td class="td-l1"><span class="l1-name">' + esc(l1.n1) + '</span></td>' +
          '<td class="td-l2 no-l2">-</td><td class="td-stocks">' + stockPills(l1.st) + '</td></tr>');
      }
    });
    var themeLimitups = (view.limitup || []).filter(function (entry) { return ztIds.has(entry.stock_id); });
    var modelHitMap = {};
    (view.realtime_model_hits || []).forEach(function (hit) { modelHitMap[hit.stock_id] = hit; });
    var cards = themeLimitups.map(function (entry) {
      var sid = entry.stock_id;
      var name = (slim[sid] || {}).n || sid;
      var reason = entry.reason || '-';
      var reasonHtml = entry.sourceCount > 1
        ? '<button type="button" class="reason-pop theme-reason" data-sid="' + esc(sid) + '">' + esc(reason) + '<span>' + entry.sourceCount + '源</span></button>'
        : '<span class="theme-reason-text">' + esc(reason) + '</span>';
      var hit = modelHitMap[sid];
      var reasonSource = entry.reason_is_history && entry.reason_date ? '开盘啦 · 沿用 ' + entry.reason_date : '开盘啦';
      var modelHtml = hit ? '<div class="theme-model-hit">🎯 ' + modelNames(hit).map(esc).join(' · ') +
        (hit.score != null ? ' <b>' + esc(hit.score) + '</b>' : '') + '</div>' : '';
      return '<div class="theme-stock-card zt"><div class="theme-stock-top">' + stk(sid, code6(sid) + ' ' + name) +
        '<span class="stock-zt-badge">' + esc(entry.boards || '涨停') + '</span></div><div class="theme-stock-reason"><label' +
        (entry.reason_is_history ? ' class="history"' : '') + '>' + esc(reasonSource) + '</label>' + reasonHtml + '</div><small>' +
        (((slim[sid] || {}).t || []).slice(0, 4).map(function (x) { return esc(((LIBS.themes || {})[x] || {}).name || x); }).join(' · ') || '暂无标签') + '</small>' + modelHtml + '</div>';
    }).join('');
    $('themeContent').innerHTML = '<section class="theme-summary"><h2>' + esc(t.name || tid) + '</h2>' +
      '<p>题材代码 ' + esc(tid) + ' · ' + (t.tree || []).length + ' 个主概念 · 当日涨停 ' + ztIds.size + ' 只 · 成分股 ' + sids.length + ' 只</p></section>' +
      '<section class="detail-section"><h3>概念层级（主概念 / 细分概念 / 成分股）</h3><div class="concept-table-scroll"><table class="concept-table">' +
      '<thead><tr><th class="col-l1">主概念</th><th class="col-l2">细分概念</th><th class="col-stocks">成分股</th></tr></thead><tbody>' +
      (treeRows.join('') || '<tr><td colspan="3" class="muted">暂无概念层级</td></tr>') + '</tbody></table></div></section>' +
      '<section class="detail-section"><h3>当日涨停股（' + ztIds.size + '只）</h3><div class="theme-stock-grid">' +
      (cards || '<div class="theme-no-limitup">该题材当日暂无涨停股</div>') + '</div></section>';
  }

  function renderThemeLive(view) {
    if (!$('themeLiveList')) return;
    var events = (view.events || []).filter(function (e) { return e.type !== 'signal_hit'; }).slice(0, 80);
    var groups = {};
    (view.realtime_model_hits || []).forEach(function (hit) {
      var raw = String(hit.ts || '');
      var time = raw.indexOf('T') >= 0 || raw.indexOf(' ') >= 0 ? raw.slice(11, 16) : raw.slice(0, 5);
      time = time || '--:--';
      (groups[time] = groups[time] || []).push(hit);
    });
    var hits = Object.keys(groups).sort().reverse().map(function (time) {
      var rows = groups[time].sort(function (a, b) { return Number(b.change_pct || 0) - Number(a.change_pct || 0); }).map(function (hit, index) {
        var pct = hit.change_pct == null ? '<span class="live-change muted">--</span>' :
          '<span class="live-change ' + cls(hit.change_pct) + '">' + fmtPct(hit.change_pct) + '</span>';
        return '<div class="live-model-stock"><div class="live-stock-line"><span class="live-stock-rank">' + String(index + 1).padStart(2, '0') +
          '</span><div class="live-stock-identity">' + stk(hit.stock_id, hit.name || hit.stock_id) + '<small>' + esc(code6(hit.stock_id)) +
          '</small></div>' + pct + '</div><div class="live-stock-meta"><div class="live-model-names">' +
          modelNames(hit).map(function (name) { return '<span>' + esc(name) + '</span>'; }).join('') +
          '</div>' + (hit.score != null ? '<b class="live-model-score">' + esc(hit.score) + '<em>分</em></b>' : '') + '</div></div>';
      }).join('');
      return '<section class="live-time-group"><header class="live-group-head"><div><time>' + esc(time) +
        '</time><small>本分钟</small></div><span class="live-group-count">' + groups[time].length + ' 只命中</span></header>' + rows + '</section>';
    }).join('');
    var eventHtml = events.map(function (e) {
      return '<div class="live-feed-item"><div><span class="live-event-badge">' + esc(EVT_META[e.type] || e.type || '动态') + '</span>' +
        '<span class="live-time">' + esc(String(e.ts || '').slice(11, 16)) + '</span></div>' +
        '<p>' + (e.stock_id ? stk(e.stock_id, code6(e.stock_id)) + ' ' : '') + esc(e.detail || '') + '</p></div>';
    }).join('');
    $('themeLiveList').innerHTML = hits + eventHtml || '<div class="muted" style="padding:14px">暂无实时播报</div>';
  }

  function localToday() {
    var d = new Date(), y = d.getFullYear(), m = String(d.getMonth() + 1).padStart(2, '0'), day = String(d.getDate()).padStart(2, '0');
    return y + '-' + m + '-' + day;
  }

  function isMarketSession() {
    var now = new Date(), day = now.getDay(), minutes = now.getHours() * 60 + now.getMinutes();
    return day >= 1 && day <= 5 && minutes >= 9 * 60 + 15 && minutes <= 15 * 60 + 20;
  }

  function buildRealtimeThemeView(payload) {
    var base = CACHE[themeArchiveDay || currentDay] || {};
    var view = Object.assign({}, base);
    view.date = payload.data_date || localToday();
    view.limitup = payload.limitup || [];
    view.events = payload.events || [];
    view.realtime_model_hits = payload.model_hits || [];
    view.realtime = { ts: payload.ts || '', phase: payload.phase || '', available: !!payload.available };
    view.market = Object.assign({}, base.market || {}, { limit_up: view.limitup.length });
    var ids = new Set(view.limitup.map(function (entry) { return entry.stock_id; }));
    view.theme_limitup = {};
    Object.keys(LIBS.theme_stocks || {}).forEach(function (tid) {
      view.theme_limitup[tid] = (LIBS.theme_stocks[tid] || []).filter(function (sid) { return ids.has(sid); }).sort();
    });
    view.theme_concept_limitup = {};
    Object.keys(LIBS.themes || {}).forEach(function (tid) {
      var entries = [];
      ((LIBS.themes[tid] || {}).tree || []).forEach(function (main) {
        var mainMembers = new Set(main.st || []);
        (main.l2 || []).forEach(function (sub) {
          (sub.st || []).forEach(function (sid) { mainMembers.add(sid); });
          var subHits = (sub.st || []).filter(function (sid) { return ids.has(sid); }).sort();
          if (subHits.length) entries.push({ level: 2, parent: main.n1 || '', name: sub.n2 || '', stock_ids: subHits });
        });
        var mainHits = Array.from(mainMembers).filter(function (sid) { return ids.has(sid); }).sort();
        if (mainHits.length) entries.push({ level: 1, name: main.n1 || '', stock_ids: mainHits });
      });
      entries.sort(function (a, b) { return b.stock_ids.length - a.stock_ids.length || a.level - b.level || a.name.localeCompare(b.name); });
      view.theme_concept_limitup[tid] = entries;
    });
    return view;
  }

  function syncThemeModeControls(view) {
    var select = $('themeDateSel'), toggle = $('themeRealtimeToggle'), status = $('themeModeStatus');
    if (!select || !toggle || !status) return;
    select.innerHTML = '<option value="' + SECTOR_TODAY_VALUE + '">当天 · 实时</option>' + DAYS.map(function (d) { return '<option value="' + esc(d.date) + '">' + esc(d.date) + '</option>'; }).join('');
    if (themeRealtime) {
      select.value = SECTOR_TODAY_VALUE;
    } else select.value = themeArchiveDay || currentDay;
    select.disabled = false;
    toggle.classList.toggle('active', themeRealtime);
    toggle.setAttribute('aria-pressed', themeRealtime ? 'true' : 'false');
    status.textContent = themeRealtime ? (themeRealtimeStatus || '今日实时 · 正在连接') : '历史收盘 · 已归档';
    status.className = themeRealtime ? 'realtime' : 'archive';
    if ($('themeCount') && themeRealtime) {
      $('themeCount').textContent += ' · 模型命中 ' + ((view.realtime_model_hits || []).length) + ' 只';
    }
  }

  function realtimeDelay(phase) {
    return /auction|continuous|trading|open/i.test(String(phase || '')) ? 3000 : 30000;
  }

  function scheduleThemeRealtime(delay) {
    window.clearTimeout(themeRealtimeTimer);
    if (!themeRealtime || currentView !== 'theme') return;
    themeRealtimeTimer = window.setTimeout(refreshThemeRealtime, delay);
  }

  function refreshThemeRealtime() {
    if (!themeRealtime || currentView !== 'theme') return;
    fetchJSON('api/intraday/latest', 'no-store').then(function (result) {
      var payload = result.data || {};
      var isToday = payload.data_date === localToday();
      if (!payload.available || !isToday) {
        payload = { available: false, data_date: localToday(), limitup: [], model_hits: [], events: [], stocks: {} };
        themeRealtimeStatus = isToday ? '今日实时 · 暂无快照' : '今日实时 · 数据尚未启动';
      } else {
        themeRealtimeStatus = '今日实时 · ' + (payload.ts ? String(payload.ts).slice(11, 19) : '已刷新');
      }
      themeRealtimeView = buildRealtimeThemeView(payload);
      var detailMap = {};
      (payload.limitup || []).forEach(function (entry) { detailMap[entry.stock_id] = entry; });
      DETAIL_CACHE[payload.data_date || localToday()] = { limitup: detailMap };
      renderThemeWorkbench(themeRealtimeView);
      scheduleThemeRealtime(realtimeDelay(payload.phase));
    }).catch(function () {
      themeRealtimeStatus = '今日实时 · 连接失败';
      themeRealtimeView = buildRealtimeThemeView({ available: false, data_date: localToday(), limitup: [], model_hits: [], events: [] });
      renderThemeWorkbench(themeRealtimeView);
      scheduleThemeRealtime(30000);
    });
  }

  function startThemeRealtime() {
    if (themeRealtime) return;
    themeArchiveDay = currentDay;
    themeRealtime = true;
    if ($('dateSel')) $('dateSel').value = SECTOR_TODAY_VALUE;
    themeRealtimeStatus = '今日实时 · 正在连接';
    syncThemeModeControls(activeThemeView());
    refreshThemeRealtime();
  }

  function stopThemeRealtime(restore) {
    themeRealtime = false;
    themeRealtimeView = null;
    themeRealtimeStatus = '';
    window.clearTimeout(themeRealtimeTimer);
    themeRealtimeTimer = null;
    if (restore && themeArchiveDay && currentDay !== themeArchiveDay) currentDay = themeArchiveDay;
    themeArchiveDay = null;
  }

  /* 板块强度：参考 KPL 左侧排行 + 右侧详情格局。 */
  function vSector(view) {
    sectorRealtime = !sectorForceHistory && (isMarketSession() || sectorForceRealtime);
    if (sectorRealtime && $('dateSel')) $('dateSel').value = SECTOR_TODAY_VALUE;
    Promise.all([loadLib('sectors.json'), loadExpandLibs()]).then(function () {
      renderSectorWorkbench(view);
      if (sectorRealtime) refreshSectorRealtime();
    });
    var trend = (SECTOR_INDEX.sector_trend || []).map(function (day) {
      return '<div class="sector-trend-day"><b>' + esc(day.date.slice(5)) + '</b>' + (day.top || []).map(function (s) {
        return '<span class="sector-trend-cell' + (s.id === selectedSectorId ? ' selected' : '') + '" data-trend-sid="' + esc(s.id) + '" title="强度 ' + esc(s.strength) + ' · 涨停 ' + (s.limit_up_count || 0) + '">' + esc(s.rank) + '. ' + esc(s.name) + ' <i>涨停' + (s.limit_up_count || 0) + '</i></span>';
      }).join('') + '</div>';
    }).join('');
    var sectorDate = sectorRealtime ? localToday() + ' · 实时' : currentDay + ' · 归档';
    return '<div class="sector-shell"><details class="sector-trend"><summary>板块强度排序变化 <small>近 10 个交易日</small></summary><div class="sector-trend-grid">' + trend + '</div></details>' +
      '<div class="sector-workbench"><aside class="sector-sidebar"><div class="sector-side-head"><div><span>板块强度排行</span><small>' + esc(sectorDate) + '</small></div>' +
      '<div class="sector-date"><button type="button" data-sector-day="older" title="上一历史交易日">◀</button><span>' + esc(sectorDate) + '</span><button type="button" data-sector-day="newer" title="下一交易日 / 当天实时">▶</button></div></div>' +
      '<div class="panel-search"><input id="sectorSearch" placeholder="搜索板块…"></div><div id="sectorList" class="sector-rank-list"></div></aside>' +
      '<section class="sector-detail"><div id="sectorDetail"></div></section></div></div>';
  }

  function renderSectorWorkbench(view) {
    var kw = ($('sectorSearch') ? $('sectorSearch').value : '').trim();
    var sectors = (view.sectors || []).filter(function (s) { return !kw || (s.name || '').indexOf(kw) >= 0; });
    if (focusTag && focusTag.type === 'sector') selectedSectorId = focusTag.id;
    if (!selectedSectorId || !(view.sectors || []).some(function (s) { return s.id === selectedSectorId; })) selectedSectorId = sectors[0] && sectors[0].id;
    $('sectorList').innerHTML = sectors.map(function (s, i) {
      return '<div class="sector-rank-row' + (s.id === selectedSectorId ? ' active' : '') + '" data-sid="' + esc(s.id) + '">' +
        '<span class="rank' + (i < 3 ? ' top' : '') + '">' + (i + 1) + '</span><div class="sector-rank-info"><strong>' + esc(s.name) + '</strong>' +
        '<small><em>涨停 ' + (s.limit_up_count || 0) + '</em><em>&gt;6% ' + (s.up6_count || 0) + '</em> · ' + fmtMoney(s.mainNet) + ' · ' + (s.stock_count || 0) + '只</small></div>' +
        '<div class="sector-rank-num"><b>' + esc(s.strength || 0) + '</b><span class="' + cls(s.change) + '">' + fmtPct(s.change) + '</span></div></div>';
    }).join('') || '<div class="muted" style="padding:14px">无匹配板块</div>';
    renderSectorDetail(view, selectedSectorId);
  }

  function renderSectorDetail(view, sid) {
    if (!sid || !$('sectorDetail')) return;
    var s = (view.sectors || []).filter(function (x) { return x.id === sid; })[0] || {};
    var subs = s.sub_sectors || [];
    var subHtml = '<button class="sector-sub-chip' + (!selectedSubSectorId ? ' active' : '') + '" data-subsid="">全部</button>' + subs.map(function (sub) { return '<button class="sector-sub-chip' + (selectedSubSectorId === sub.id ? ' active' : '') + '" data-subsid="' + esc(sub.id) + '">' + esc(sub.name) + ' ' + esc(sub.strength) + '</button>'; }).join('');
    $('sectorDetail').innerHTML = '<div class="sector-detail-head"><h1>' + esc(s.name || sid) + ' <small>(' + esc(sid) + ')</small></h1>' +
      '<p>强度 ' + esc(s.strength || 0) + ' · 涨跌 <span class="' + cls(s.change) + '">' + fmtPct(s.change) + '</span> · 主力净额 ' + fmtMoney(s.mainNet) + ' · 成交额 ' + esc(s.volume || 0) + '亿 · 市值 ' + esc(s.marketCap || 0) + '亿 ' + (sectorRealtime ? '<span class="sector-live-state">● 开盘啦实时</span>' : '<span class="muted">盘后归档</span>') + '<small id="sectorLiveTime"></small></p></div>' +
      '<div class="sector-chart-panel' + (sectorChartCollapsed ? ' collapsed' : '') + '"><div class="sector-chart-bar"><div class="chart-legend"><span>■ 分钟资金成交额</span><span>━ 板块指数</span></div><button type="button" class="sector-chart-toggle">' + (sectorChartCollapsed ? '展开分时图 ▾' : '收起分时图 ▴') + '</button></div><div class="sector-chart-body"><canvas id="sectorIntradayChart"></canvas><span id="sectorChartEmpty" class="muted">' + (sectorRealtime ? '正在加载开盘啦分时数据…' : '历史归档暂无板块分时序列') + '</span></div></div>' +
      '<div class="sector-subbar"><label>子板块</label>' + (subHtml || '<span class="muted">（无子板块）</span>') + '</div>' +
      '<div class="sector-filterbar"><button data-sector-filter="all">全部</button><button data-sector-filter="zt">涨停</button><button data-sector-filter="up6">&gt;6%</button><button data-sector-filter="up0">0~6%</button><button data-sector-filter="dn">&lt;0%</button></div>' +
      '<div id="sectorStockTable" class="sector-stock-table"><div class="muted">加载板块成分股…</div></div>';
    if (!sectorRealtime) loadSectorStocks(view, sid);
    syncSectorTrendHighlight();
  }

  function syncSectorTrendHighlight() {
    document.querySelectorAll('.sector-trend-cell').forEach(function (cell) {
      cell.classList.toggle('selected', cell.dataset.trendSid === selectedSectorId);
    });
  }

  function loadSectorStocks(view, sid) {
    var date = view.date || currentDay;
    var done = function (detail) {
      var reasons = {}; (view.limitup || []).forEach(function (x) { reasons[x.stock_id] = x.reason || ''; });
      var rows = ((detail.plates || {})[selectedSubSectorId || sid] || []).map(function (x) { var r = Object.assign({}, x); r.reason = reasons[r.stock_id] || ''; return r; });
      renderSectorStockTable(rows);
    };
    if (SECTOR_DETAIL[date]) return done(SECTOR_DETAIL[date]);
    fetchJSON('data/web/day_' + date + '.sector.json').then(function (d) { SECTOR_DETAIL[date] = d; done(d); })
      .catch(function () { renderSectorStockTable([]); });
  }

  function renderSectorStockTable(rows) {
    var host = $('sectorStockTable'); if (!host) return;
    lastSectorRows = rows.slice();
    var filtered = rows.filter(function (r) { var c = Number(r.change) || 0; return sectorFilter === 'all' || (sectorFilter === 'zt' && c >= 9.8) || (sectorFilter === 'up6' && c > 6 && c < 9.8) || (sectorFilter === 'up0' && c >= 0 && c <= 6) || (sectorFilter === 'dn' && c < 0); });
    filtered.sort(function (a, b) {
      var av = sectorSortValue(a, sectorSortKey), bv = sectorSortValue(b, sectorSortKey);
      if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * sectorSortDir;
      return String(av).localeCompare(String(bv), 'zh-CN') * sectorSortDir;
    });
    var body = filtered.map(function (r) {
      var reason = r.reason ? '<button type="button" class="reason-pop sector-reason" data-sid="' + esc(r.stock_id) + '" title="沿用 ' + esc(r.reason_date || '') + ' 涨停原因">' + esc(r.reason) + (r.reason_date ? ' <small>' + esc(r.reason_date.slice(5)) + '</small>' : '') + '</button>' : '-';
      return '<tr class="sector-stock-row ' + ((Number(r.change) || 0) >= 9.8 ? 'row-zt' : '') + '" data-tdx-sid="' + esc(r.stock_id) + '"><td class="l">' + esc(r.code) + '</td><td class="l">' + esc(r.name) + '</td><td>' + esc(formatDragonPosition(r.position)) + '</td><td class="l">' + reason + '</td><td class="' + cls(r.change) + '">' + fmtPct(r.change) + '</td><td>' + esc(r.price || '-') + '</td><td>' + esc(r.turnover || '-') + '%</td><td>' + fmtMoney(r.amount) + '</td><td class="' + cls(r.main_net) + '">' + fmtMoney(r.main_net) + '</td><td>' + esc(r.vol_ratio || '-') + '</td><td>' + esc(r.net_flow_ratio || '-') + '</td><td>' + esc(r.boards || '-') + '</td><td>' + esc(r.pe || '-') + '</td><td>' + fmtMoney(r.circ_market_cap) + '</td></tr>';
    }).join('');
    var heads = [['code','代码','l'],['name','名称','l'],['position_rank','地位',''],['reason','涨停原因','l'],['change','涨跌幅',''],['price','现价',''],['turnover','换手率',''],['amount','成交额',''],['main_net','主力净额',''],['vol_ratio','量比',''],['net_flow_ratio','净流占比',''],['boards','连板',''],['pe','市盈率',''],['circ_market_cap','流通市值','']];
    var headHtml = heads.map(function (h) { return '<th class="sector-sort ' + h[2] + (sectorSortKey === h[0] ? ' active' : '') + '" data-sector-sort="' + h[0] + '">' + h[1] + (sectorSortKey === h[0] ? (sectorSortDir > 0 ? ' ↑' : ' ↓') : '') + '</th>'; }).join('');
    host.innerHTML = '<div class="tblwrap"><table><thead><tr>' + headHtml + '</tr></thead><tbody>' + (body || '<tr><td colspan="14" class="muted">暂无成分股</td></tr>') + '</tbody></table></div>';
    document.querySelectorAll('[data-sector-filter]').forEach(function (b) { b.classList.toggle('active', b.dataset.sectorFilter === sectorFilter); });
  }

  function chinesePositionRank(value) {
    var text = String(value || '').replace(/^龙/, '').trim(), digits = { '一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9 };
    if (!text) return 9999;
    if (/^\d+$/.test(text)) return Number(text);
    if (text === '十') return 10;
    if (text.indexOf('十') >= 0) { var p = text.split('十'); return (p[0] ? (digits[p[0]] || 1) : 1) * 10 + (p[1] ? (digits[p[1]] || 0) : 0); }
    return digits[text] || 9999;
  }
  function formatDragonPosition(value) { var rank = chinesePositionRank(value); return rank === 9999 ? '-' : '龙' + String(value || '').replace(/^龙/, ''); }
  function sectorSortValue(row, key) {
    if (key === 'position_rank') return row.position_rank != null ? Number(row.position_rank) : chinesePositionRank(row.position);
    if (['change','price','turnover','amount','main_net','vol_ratio','net_flow_ratio','pe','circ_market_cap'].indexOf(key) >= 0) return Number(row[key]) || 0;
    return row[key] || '';
  }

  function drawSectorIntraday(data) {
    lastSectorIntraday = data || null;
    var canvas = $('sectorIntradayChart'), empty = $('sectorChartEmpty');
    if (!canvas || sectorChartCollapsed) return;
    var times = (data && data.times) || [], amounts = (data && data.amounts) || [], prices = (data && data.prices) || [];
    if (!times.length || !prices.length) { if (empty) empty.style.display = ''; canvas.style.display = 'none'; return; }
    if (empty) empty.style.display = 'none'; canvas.style.display = 'block';
    var rect = canvas.parentNode.getBoundingClientRect(), dpr = window.devicePixelRatio || 1, w = Math.max(320, rect.width), h = Math.max(150, rect.height);
    canvas.width = w * dpr; canvas.height = h * dpr; canvas.style.width = w + 'px'; canvas.style.height = h + 'px';
    var ctx = canvas.getContext('2d'); ctx.scale(dpr, dpr); ctx.clearRect(0, 0, w, h);
    var pad = { l: 42, r: 44, t: 12, b: 22 }, cw = w - pad.l - pad.r, ch = h - pad.t - pad.b;
    ctx.strokeStyle = '#252b35'; ctx.lineWidth = 1; ctx.fillStyle = '#6e7681'; ctx.font = '10px sans-serif';
    for (var g = 0; g <= 4; g++) { var gy = pad.t + ch * g / 4; ctx.beginPath(); ctx.moveTo(pad.l, gy); ctx.lineTo(w - pad.r, gy); ctx.stroke(); }
    var maxAmount = Math.max.apply(null, amounts.concat([1])), minPrice = Math.min.apply(null, prices), maxPrice = Math.max.apply(null, prices); if (maxPrice === minPrice) maxPrice += 1;
    var step = cw / Math.max(1, times.length - 1), barW = Math.max(1, Math.min(4, step * .75));
    amounts.forEach(function (amount, i) { var bh = amount / maxAmount * ch * .42, rising = i === 0 || prices[i] >= prices[i - 1]; ctx.fillStyle = rising ? 'rgba(248,81,73,.38)' : 'rgba(63,185,80,.36)'; ctx.fillRect(pad.l + i * step - barW / 2, pad.t + ch - bh, barW, bh); });
    ctx.beginPath(); prices.forEach(function (price, i) { var x = pad.l + i * step, y = pad.t + (maxPrice - price) / (maxPrice - minPrice) * ch * .68; if (!i) ctx.moveTo(x, y); else ctx.lineTo(x, y); }); ctx.strokeStyle = '#f0b45a'; ctx.lineWidth = 1.6; ctx.stroke();
    ctx.fillStyle = '#8b949e'; ctx.fillText(times[0], pad.l, h - 6); ctx.fillText(times[times.length - 1], w - pad.r - 30, h - 6); ctx.fillText(maxAmount.toFixed(1) + '亿', 3, pad.t + ch); ctx.fillText(maxPrice.toFixed(1), w - pad.r + 4, pad.t + 8); ctx.fillText(minPrice.toFixed(1), w - pad.r + 4, pad.t + ch);
  }

  function refreshSectorRealtime() {
    window.clearTimeout(sectorRealtimeTimer);
    if (!sectorRealtime || !selectedSectorId) return;
    var url = 'api/sectors/realtime?plate=' + encodeURIComponent(selectedSectorId) + (selectedSubSectorId ? '&sub=' + encodeURIComponent(selectedSubSectorId) : '');
    fetchJSON(url, 'no-store').then(function (r) {
      var data = r.data || r;
      if (!data.available) return;
      var view = CACHE[currentDay];
      view.sectors = data.sectors || view.sectors || [];
      var current = (view.sectors || []).filter(function (s) { return s.id === selectedSectorId; })[0];
      if (current) {
        current.sub_sectors = data.sub_sectors || [];
        if (!selectedSubSectorId) {
          current.limit_up_count = data.limit_up_count;
          current.up6_count = data.up6_count;
          current.stock_count = data.stock_count;
        }
      }
      var liveDetail = { date: data.data_date || localToday(), limitup: {} };
      (data.stocks || []).forEach(function (stock) {
        if (!stock.reason) return;
        liveDetail.limitup[stock.stock_id] = { reason: stock.reason, detail: stock.detail || '',
          primary: stock.primary || 'kpl', sourceCount: stock.sourceCount || 1, sources: stock.sources || {},
          reason_date: stock.reason_date || '', reason_is_history: !!stock.reason_is_history };
      });
      DETAIL_CACHE[liveDetail.date] = liveDetail;
      renderSectorWorkbench(view);
      renderSectorStockTable(data.stocks || []);
      drawSectorIntraday(data.intraday || null);
      var stamp = $('sectorLiveTime');
      if (stamp) stamp.textContent = ' KPL ' + (data.max_time || '--:--').replace(/^(\d{2})(\d{2})$/, '$1:$2');
    }).catch(function () {}).then(function () {
      if (sectorRealtime) sectorRealtimeTimer = window.setTimeout(refreshSectorRealtime, 5000);
    });
  }

  function navigateSectorDay(direction) {
    var dates = DAYS.map(function (d) { return d.date; });
    if (!dates.length) return;
    if (sectorRealtime) {
      if (direction === 'older') {
        sectorForceHistory = true; sectorForceRealtime = false; sectorRealtime = false;
        window.clearTimeout(sectorRealtimeTimer); $('dateSel').value = dates[0]; loadDay(dates[0]);
      }
      return;
    }
    var index = dates.indexOf(currentDay);
    if (index < 0) index = 0;
    if (direction === 'older' && index + 1 < dates.length) {
      $('dateSel').value = dates[index + 1]; loadDay(dates[index + 1]);
    } else if (direction === 'newer' && index > 0) {
      $('dateSel').value = dates[index - 1]; loadDay(dates[index - 1]);
    } else if (direction === 'newer' && index === 0) {
      sectorForceHistory = false; sectorForceRealtime = true; sectorRealtime = true;
      $('dateSel').value = SECTOR_TODAY_VALUE; render();
    }
  }

  /* 策略模型：命中 + 买点 */
  /* ---------- 策略模型页（V0.3+：在线配置 + 全量命中池） ---------- */
  var MODEL_CN = { reversal: '①低吸反转', breakout: '②横盘突破', weekly: '③周线堆量', dwm: '④日周月堆量主升共振',
    lowstart: '⑤低位启动', volbrk: '⑥突破放量', perfect_ten: '⑦十全十美', golden_vol: '⑧金量买入',
    hub_breakout: '⑨中枢突破', div_reversal: '⑩背驰反转', ma_momentum: '⑪多头排列', bottom_rev: '⑫底部起涨',
    multi_factor: '⑬多因共振', sub_low: '⑭低吸型', sub_trend_vol: '⑮趋势放量型', sub_breakout: '⑯突破型', sub_main: '⑰主升型' };
  var STRAT_ALL = null;
  var stratMode = 'all';
  var stratModelFilter = '';
  function strategyRows(view) {
    if (STRAT_ALL && STRAT_ALL.date === currentDay) return STRAT_ALL.list;
    return (view.strategy_top || []).map(function (e) {
      return { stock_id: e.stock_id, name: '', score: e.score, models: e.models, buy_lo: e.buy_point,
               stop: e.stop, stop_pct: e.stop_pct, rr: e.rr, stars: e.stars, entry_time: '',
               price: null, chg: null };
    });
  }
  function loadStrategyAll() {
    if (STRAT_ALL && STRAT_ALL.date === currentDay) return Promise.resolve(STRAT_ALL);
    STRAT_ALL = null;
    return fetchJSON('data/web/strategy_all.json').then(function (d) {
      if (d && d.date === currentDay) STRAT_ALL = d;
      return STRAT_ALL;
    }).catch(function () { STRAT_ALL = null; return null; });
  }
  function limitupEntryMap(view) {
    var m = {};
    (view.limitup || []).forEach(function (e) { m[e.stock_id] = e; });
    return m;
  }
  function conceptChips(sid) {
    var slim = LIBS.stocks_slim || {}, sectors = LIBS.sectors || {}, themes = LIBS.themes || {};
    var rec = slim[sid] || { s: [], t: [] };
    var chips = (rec.s || []).slice(0, 3).map(function (s) {
      return '<span class="tag-chip sec" data-go="sector" data-id="' + esc(s) + '">' + esc((sectors[s] || {}).name || s) + '</span>';
    }).concat((rec.t || []).slice(0, 3).map(function (t) {
      return '<span class="tag-chip thm" data-go="theme" data-id="' + esc(t) + '">' + esc((themes[t] || {}).name || t) + '</span>';
    })).join('');
    return chips || '<span class="muted">-</span>';
  }
  function modelBadges(models) {
    var keys = Object.keys(models || {});
    return keys.map(function (m) { return '<span class="badge b-model">' + esc(MODEL_CN[m] || m) + '</span>'; }).join('') || '-';
  }
  function strategyRowHtml(r, names, reasons) {
    var chg = r.chg == null ? '-' : fmtPct(r.chg);
    var reasonEntry = reasons[r.stock_id] || { reason: '', sourceCount: 0 };
    return '<tr><td class="up">' + (r.score == null ? '-' : Number(r.score).toFixed(1)) + '</td>' +
      '<td class="l">' + conceptChips(r.stock_id) + '</td>' +
      '<td class="l">' + code6(r.stock_id) + '</td>' +
      '<td class="l">' + stk(r.stock_id, (names[r.stock_id] || r.name || code6(r.stock_id))) + '</td>' +
      '<td class="l">' + modelBadges(r.models) + '</td>' +
      '<td>' + (r.price == null ? '-' : Number(r.price).toFixed(2)) + '</td>' +
      '<td>' + (r.buy_lo == null ? '-' : Number(r.buy_lo).toFixed(2)) + '</td>' +
      '<td>' + (r.stop == null ? '-' : Number(r.stop).toFixed(2)) + '</td>' +
      '<td>' + (r.stop_pct == null ? '-' : Number(r.stop_pct).toFixed(2) + '%') + '</td>' +
      '<td>' + (r.rr == null ? '-' : Number(r.rr).toFixed(1)) + '</td>' +
      '<td class="' + cls(chg) + '">' + chg + '</td>' +
      '<td class="l">' + reasonCell(r.stock_id, reasonEntry) + '</td></tr>';
  }
  function stratTable(rows, names, reasons) {
    var thead = '<thead><tr><th>评分</th><th class="l">概念/板块</th><th class="l">代码</th><th class="l">名称</th>' +
      '<th class="l">命中模型</th><th>现价</th><th>参考买入区</th><th>止损位</th><th>止损%</th><th>风险回报比</th><th>今日</th><th class="l">涨停原因</th></tr></thead>';
    return '<div class="tblwrap"><table>' + thead + '<tbody>' +
      (rows.map(function (r) { return strategyRowHtml(r, names, reasons); }).join('') ||
        '<tr><td colspan="12" class="muted">暂无策略命中</td></tr>') + '</tbody></table></div>';
  }
  function timeBucket(t) {
    if (!t) return '盘后';
    var parts = t.split(':');
    if (parts.length < 2) return '盘后';
    var m = parseInt(parts[0], 10) * 60 + parseInt(parts[1], 10);
    if (m <= 570) return '09:30 前（竞价）';
    if (m <= 630) return '09:30-10:30';
    if (m <= 690) return '10:30-11:30';
    if (m <= 750) return '13:00-14:00';
    if (m <= 810) return '14:00-15:00';
    return '盘后';
  }
  function renderStratBody(rows, names, reasons) {
    if (stratModelFilter) rows = rows.filter(function (r) { return (r.models || {})[stratModelFilter]; });
    if (stratMode === 'time') {
      var buckets = ['09:30 前（竞价）', '09:30-10:30', '10:30-11:30', '13:00-14:00', '14:00-15:00', '盘后'];
      var groups = {};
      buckets.forEach(function (b) { groups[b] = []; });
      rows.forEach(function (r) { (groups[timeBucket(r.entry_time)] || groups['盘后']).push(r); });
      var html = buckets.filter(function (b) { return groups[b].length; }).map(function (b) {
        return '<div class="time-grp"><div class="time-grp-h">' + esc(b) + ' <span class="cnt">' + groups[b].length + ' 只</span></div>' +
          stratTable(groups[b], names, reasons) + '</div>';
      }).join('');
      return html || '<div class="muted" style="padding:16px">该模式暂无数据</div>';
    }
    if (stratMode === 'model') {
      var stat = {};
      rows.forEach(function (r) { Object.keys(r.models || {}).forEach(function (m) { stat[m] = (stat[m] || 0) + 1; }); });
      var statHtml = Object.keys(stat).sort(function (a, b) { return stat[b] - stat[a]; }).map(function (m) {
        return '<button type="button" class="m-stat' + (stratModelFilter === m ? ' active' : '') + '" data-model="' + esc(m) + '">' +
          '<span class="badge b-model">' + esc(MODEL_CN[m] || m) + '</span><b>' + stat[m] + '</b></button>';
      }).join('') || '<span class="muted">暂无</span>';
      return '<div class="m-stats">' + statHtml + '</div>' + stratTable(rows, names, reasons);
    }
    return stratTable(rows, names, reasons);
  }
  function strategyConfigCard() {
    return card('⚙️ 策略模型配置', '修改后保存，下次归档（15:30）重跑生效',
      '<div class="cfg-wrap" id="cfgWrap"><div class="muted">加载配置…</div></div>', false);
  }
  function loadStrategyConfig() {
    fetchJSON('api/strategy/config', 'no-cache').then(function (r) {
      var cfg = r.data || r;
      var models = cfg.models || {};
      var rows = Object.keys(MODEL_CN).map(function (mid) {
        var m = models[mid] || { name: MODEL_CN[mid], enabled: true, family: '', params: {} };
        var params = m.params && Object.keys(m.params).length
          ? '<input class="cfg-params" data-mid="' + esc(mid) + '" value="' + esc(JSON.stringify(m.params)) + '" title="参数 JSON（保存后生效）">'
          : '<span class="cfg-no-params">—</span>';
        return '<div class="cfg-row"><label class="cfg-name" data-mid="' + esc(mid) + '">' + esc(MODEL_CN[mid] || mid) + '</label>' +
          '<span class="cfg-family">' + esc(m.family || '') + '</span>' + params +
          '<input type="checkbox" class="cfg-toggle" data-mid="' + esc(mid) + '"' + (m.enabled ? ' checked' : '') + '><span class="cfg-state">' + (m.enabled ? '启用' : '停用') + '</span></div>';
      }).join('');
      $('cfgWrap').innerHTML = rows +
        '<div class="cfg-actions"><button type="button" class="btn-primary" id="cfgSave">保存配置</button>' +
        '<button type="button" class="btn-ghost" id="cfgReset">恢复默认</button><span class="cfg-msg" id="cfgMsg"></span></div>';
    }).catch(function () {
      $('cfgWrap').innerHTML = '<div class="muted">配置接口不可用（api/strategy/config）</div>';
    });
  }
  function vStrategy(view) {
    Promise.all([loadExpandLibs(), loadStrategyAll()]).then(function () { render(); });
    loadStrategyConfig();
    var rows = strategyRows(view).slice(0, 300);
    var names = LIBS.stocks_slim || {};
    var reasons = limitupEntryMap(view);
    var kpi = [
      ['命中总数', rows.length],
      ['预警池', ((view.pools || {}).pools || {}).alert ? Object.keys(((view.pools || {}).pools || {}).alert).length : 0],
      ['最高评分', rows[0] ? Number(rows[0].score).toFixed(1) : '-'],
      ['模型覆盖', Object.keys(rows.reduce(function (a, r) { Object.keys(r.models || {}).forEach(function (m) { a[m] = 1; }); return a; }, {})).length + '/17']];
    var kpiHtml = '<div class="kpi-row">' + kpi.map(function (k) {
      return '<div class="kpi"><div class="num">' + k[1] + '</div><div class="lbl">' + k[0] + '</div></div>';
    }).join('') + '</div>';
    var seg = '<div class="seg" id="stratSeg">' +
      '<button type="button" class="seg-btn' + (stratMode === 'all' ? ' active' : '') + '" data-mode="all">全部</button>' +
      '<button type="button" class="seg-btn' + (stratMode === 'time' ? ' active' : '') + '" data-mode="time">按时间归类</button>' +
      '<button type="button" class="seg-btn' + (stratMode === 'model' ? ' active' : '') + '" data-mode="model">按模型分类</button></div>';
    return strategyConfigCard() +
      card('🎯 策略模型 · 命中池', '评分降序 · TOP 300', kpiHtml + seg + '<div id="stratBody">' + renderStratBody(rows, names, reasons) + '</div>', false);
  }

  /* 历史选股：预警池 + 候选池（星级/确认/模型命中） */
  function vHistory(view) {
    var pools = (view.pools && view.pools.pools) || {};
    function poolTable(name, pool, emptyMsg) {
      var items = pool ? Object.keys(pool) : [];
      var rows = items.map(function (sid) {
        var e = pool[sid];
        var stars = '<span class="badge b-star">' + (e.stars ? '★'.repeat(e.stars) : '') + '</span>';
        var confirm = (e.confirm || {});
        var c = ['sector_strength', 'money_flow', 'leading_reason'].filter(function (k) { return confirm[k]; })
          .map(function () { return '<span class="badge b-confirm">✓</span>'; }).join('');
        var models = (e.model_hit || []).map(function (m) { return '<span class="badge b-model">' + esc(m) + '</span>'; }).join(' ');
        return '<tr><td class="l">' + stk(sid, code6(sid)) + '</td><td>' + esc(e.entry_time || '-') + '</td>' +
          '<td>' + Number(e.score || 0).toFixed(1) + '</td><td class="l">' + models + '</td><td>' + stars + '</td><td class="l">' + c + '</td><td>' + esc(e.status || '') + '</td></tr>';
      }).join('');
      return card(name, items.length + ' 只', '<div class="tblwrap"><table><thead><tr><th class="l">代码</th><th>进入</th><th>评分</th><th class="l">模型命中</th><th>星级</th><th class="l">四维确认</th><th>状态</th></tr></thead><tbody>' +
        (rows || '<tr><td colspan="7" class="muted">' + emptyMsg + '</td></tr>') + '</tbody></table></div>', true);
    }
    return poolTable('⚠️ 预警池', pools.alert, '暂无预警（V0.3 信号引擎接入）') +
      poolTable('📌 候选池', pools.candidate, '暂无候选') +
      poolTable('⭐ 自选池', pools.watchlist, '暂无自选');
  }

  /* ---------- 原因弹窗（懒加载 detail） ---------- */
  function showPopup(sid, x, y) {
    var pop = $('popup');
    pop.innerHTML = '<div class="pp-head"><span>加载中…</span><span class="pp-close" onclick="document.getElementById(\'popup\').style.display=\'none\'">×</span></div>';
    pop.style.display = 'block';
    pop.dataset.anchorX = x;
    pop.dataset.anchorY = y;
    place(pop, x, y);
    var detailDay = (themeRealtime || sectorRealtime) ? localToday() : currentDay;
    if (DETAIL_CACHE[detailDay]) { renderDetail(sid, pop, x, y, detailDay); return; }
    fetchJSON(dayFile(detailDay).replace('.json', '.detail.json')).then(function (d) {
      DETAIL_CACHE[detailDay] = d;
      renderDetail(sid, pop, x, y, detailDay);
    }).catch(function () {
      pop.innerHTML = '<div class="pp-head"><span>详情加载失败</span><span class="pp-close" onclick="document.getElementById(\'popup\').style.display=\'none\'">×</span></div>';
    });
  }

  var SRC_META = { kpl: { label: '开盘啦', color: '#e24b4a' }, jygs: { label: '韭研公社', color: '#d29922' }, ths: { label: '同花顺', color: '#2f6fdb' }, xgb: { label: '选股吧', color: '#8e44ad' } };
  var SRC_ORDER = ['kpl', 'jygs', 'ths', 'xgb'];

  function renderDetail(sid, pop, x, y, detailDay) {
    var d = DETAIL_CACHE[detailDay || currentDay] || {};
    var e = (d.limitup || {})[sid];
    if (!e) { pop.innerHTML = '<div class="pp-head"><span>无详情</span><span class="pp-close" onclick="document.getElementById(\'popup\').style.display=\'none\'">×</span></div>'; return; }
    var sources = e.sources || {};
    var html = '<div class="pp-head"><span>' + esc(sid) + ' · 涨停原因（' + (e.sourceCount || 1) + ' 源）' + (e.reason_date ? ' · ' + esc(e.reason_date) : '') + '</span><span class="pp-close" onclick="document.getElementById(\'popup\').style.display=\'none\'">×</span></div>';
    if (!Object.keys(sources).length && e.reason) {
      html += '<div class="pp-source"><div class="pp-src-head"><span class="pp-dot" style="background:#e24b4a"></span>开盘啦</div><div>' + esc(e.reason) + '</div>' + (e.detail ? '<div class="pp-detail">' + esc(e.detail) + '</div>' : '') + '</div>';
    }
    SRC_ORDER.forEach(function (key) {
      var src = sources[key];
      if (!src) return;
      var meta = SRC_META[key] || { label: key, color: '#8b949e' };
      html += '<div class="pp-source"><div class="pp-src-head"><span class="pp-dot" style="background:' + meta.color + '"></span>' + meta.label +
        (key === e.primary ? ' <span class="pp-pri">主</span>' : '') + '</div><div>' + esc(src.reason || '') + '</div>' +
        (src.concepts ? '<div class="pp-detail">概念：' + esc(src.concepts) + '</div>' : '') +
        (src.boards ? '<div class="pp-detail">连板：' + esc(src.boards) + '</div>' : '') +
        (src.detail ? '<div class="pp-detail">' + esc(src.detail) + '</div>' : '') + '</div>';
    });
    if (!html) html += '<div class="muted">无原文</div>';
    pop.innerHTML = html;
    place(pop, x, y);
  }

  function place(pop, x, y) {
    var viewport = window.visualViewport;
    var vw = viewport ? viewport.width : window.innerWidth;
    var vh = viewport ? viewport.height : window.innerHeight;
    var ox = viewport ? viewport.offsetLeft : 0;
    var oy = viewport ? viewport.offsetTop : 0;
    var margin = 12, gap = 10;
    pop.style.maxHeight = Math.max(160, vh - margin * 2) + 'px';
    pop.style.left = ox + margin + 'px';
    pop.style.top = oy + margin + 'px';
    var w = Math.min(pop.offsetWidth, vw - margin * 2);
    var h = Math.min(pop.offsetHeight, vh - margin * 2);
    var px = Number(x) || vw / 2, py = Number(y) || vh / 2;
    var left = px + gap + w <= ox + vw - margin ? px + gap : px - w - gap;
    var top = py + gap + h <= oy + vh - margin ? py + gap : py - h - gap;
    left = Math.max(ox + margin, Math.min(left, ox + vw - w - margin));
    top = Math.max(oy + margin, Math.min(top, oy + vh - h - margin));
    pop.style.left = left + 'px';
    pop.style.top = top + 'px';
  }

  /* ---------- 事件绑定 ---------- */
  var VALID_VIEWS = ['signal', 'theme', 'sector', 'strategy', 'history'];
  var initView = location.hash ? location.hash.slice(1) : 'signal';
  if (VALID_VIEWS.indexOf(initView) >= 0) currentView = initView;
  document.querySelectorAll('.tab').forEach(function (tab) {
    if (tab.dataset.view === currentView) tab.classList.add('active');
    tab.addEventListener('click', function () {
      document.querySelectorAll('.tab').forEach(function (t) { t.classList.remove('active'); });
      tab.classList.add('active');
      if (tab.dataset.view !== 'theme' && themeRealtime) stopThemeRealtime(false);
      if (tab.dataset.view !== 'sector') { sectorRealtime = false; window.clearTimeout(sectorRealtimeTimer); }
      if (tab.dataset.view === 'sector') { sectorForceHistory = false; sectorForceRealtime = false; }
      currentView = tab.dataset.view;
      if (history.replaceState) history.replaceState(null, '', '#' + currentView);
      render();
    });
  });
  $('dateSel').addEventListener('change', function () {
    if (themeRealtime) stopThemeRealtime(false);
    if (this.value === SECTOR_TODAY_VALUE) {
      if (currentView === 'theme') {
        startThemeRealtime();
      } else if (currentView === 'sector') {
        sectorForceHistory = false; sectorForceRealtime = true; sectorRealtime = true; render();
      } else {
        this.value = currentDay;
      }
      return;
    }
    if (currentView === 'sector') { sectorForceHistory = true; sectorRealtime = false; window.clearTimeout(sectorRealtimeTimer); }
    loadDay(this.value);
  });
  document.addEventListener('click', function (ev) {
    var sectorDay = ev.target.closest ? ev.target.closest('[data-sector-day]') : null;
    if (sectorDay) { ev.stopPropagation(); navigateSectorDay(sectorDay.dataset.sectorDay); return; }
    var realtimeToggle = ev.target.closest ? ev.target.closest('#themeRealtimeToggle') : null;
    if (realtimeToggle) {
      ev.stopPropagation();
      if (themeRealtime) {
        var restoreDay = themeArchiveDay || currentDay;
        stopThemeRealtime(false);
        currentDay = restoreDay;
        $('dateSel').value = restoreDay;
        render();
      } else startThemeRealtime();
      return;
    }
    var chip = ev.target.closest ? ev.target.closest('.tag-chip') : null;
    if (chip) { ev.stopPropagation(); goTag(chip.dataset.go, chip.dataset.id); return; }
    var themeToggle = ev.target.closest ? ev.target.closest('.theme-toggle') : null;
    if (themeToggle) {
      ev.stopPropagation();
      var toggleTid = themeToggle.dataset.tid;
      expandedThemeIds[toggleTid] = !expandedThemeIds[toggleTid];
      renderThemeWorkbench(activeThemeView());
      return;
    }
    var themeConcept = ev.target.closest ? ev.target.closest('.theme-concept-row') : null;
    if (themeConcept) {
      locateThemeConcept(themeConcept.dataset.tid, themeConcept.dataset.conceptKey);
      return;
    }
    var themeNav = ev.target.closest ? ev.target.closest('.theme-nav-row') : null;
    if (themeNav) {
      selectedThemeId = themeNav.dataset.tid;
      renderThemeWorkbench(activeThemeView());
      return;
    }
    var sectorRank = ev.target.closest ? ev.target.closest('.sector-rank-row') : null;
    if (sectorRank) {
      selectedSectorId = sectorRank.dataset.sid;
      selectedSubSectorId = null;
      renderSectorWorkbench(CACHE[currentDay]);
      return;
    }
    var sectorSub = ev.target.closest ? ev.target.closest('.sector-sub-chip') : null;
    if (sectorSub) {
      selectedSubSectorId = sectorSub.dataset.subsid || null;
      renderSectorDetail(CACHE[currentDay], selectedSectorId);
      if (sectorRealtime) refreshSectorRealtime();
      return;
    }
    var sectorFilterBtn = ev.target.closest ? ev.target.closest('[data-sector-filter]') : null;
    if (sectorFilterBtn) {
      sectorFilter = sectorFilterBtn.dataset.sectorFilter;
      if (sectorRealtime) refreshSectorRealtime(); else loadSectorStocks(CACHE[currentDay], selectedSectorId);
      return;
    }
    var sectorSort = ev.target.closest ? ev.target.closest('[data-sector-sort]') : null;
    if (sectorSort) {
      var key = sectorSort.dataset.sectorSort;
      if (sectorSortKey === key) sectorSortDir *= -1;
      else { sectorSortKey = key; sectorSortDir = key === 'position_rank' ? 1 : -1; }
      renderSectorStockTable(lastSectorRows);
      return;
    }
    var chartToggle = ev.target.closest ? ev.target.closest('.sector-chart-toggle') : null;
    if (chartToggle) {
      sectorChartCollapsed = !sectorChartCollapsed;
      var panel = chartToggle.closest('.sector-chart-panel');
      if (panel) panel.classList.toggle('collapsed', sectorChartCollapsed);
      chartToggle.textContent = sectorChartCollapsed ? '展开分时图 ▾' : '收起分时图 ▴';
      if (!sectorChartCollapsed) window.setTimeout(function () { drawSectorIntraday(lastSectorIntraday); }, 0);
      return;
    }
    var secRow = ev.target.closest ? ev.target.closest('.sec-row') : null;
    if (secRow) { toggleSectorExpand(secRow); return; }
    var segBtn = ev.target.closest ? ev.target.closest('#stratSeg .seg-btn') : null;
    if (segBtn) {
      stratMode = segBtn.dataset.mode;
      document.querySelectorAll('#stratSeg .seg-btn').forEach(function (b) { b.classList.toggle('active', b === segBtn); });
      var view2 = CACHE[currentDay] || {};
      var rows2 = strategyRows(view2).slice(0, 300);
      $('stratBody').innerHTML = renderStratBody(rows2, LIBS.stocks_slim || {}, limitupEntryMap(view2));
      return;
    }
    var mStat = ev.target.closest ? ev.target.closest('.m-stat') : null;
    if (mStat) {
      stratModelFilter = (stratModelFilter === mStat.dataset.model) ? '' : mStat.dataset.model;
      document.querySelectorAll('.m-stat').forEach(function (b) { b.classList.toggle('active', b.dataset.model === stratModelFilter); });
      var view3 = CACHE[currentDay] || {};
      $('stratBody').innerHTML = renderStratBody(strategyRows(view3).slice(0, 300), LIBS.stocks_slim || {}, limitupEntryMap(view3));
      return;
    }
    if (ev.target && ev.target.id === 'cfgSave') {
      var cfgWrap = $('cfgWrap');
      var models = {};
      Object.keys(MODEL_CN).forEach(function (mid) {
        var toggle = cfgWrap.querySelector('.cfg-toggle[data-mid="' + mid + '"]');
        if (!toggle) return;
        var paramsInput = cfgWrap.querySelector('.cfg-params[data-mid="' + mid + '"]');
        var params = {};
        try { params = paramsInput ? JSON.parse(paramsInput.value) : {}; } catch (e) { params = {}; }
        models[mid] = { name: MODEL_CN[mid], enabled: toggle.checked, family: '', params: params };
      });
      fetch('api/strategy/config', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ version: '1.0', models: models }) })
        .then(function (r) { return r.json(); }).then(function (res) {
          $('cfgMsg').textContent = res.ok ? ('已保存 ' + new Date().toLocaleTimeString() + '（15:30 归档重跑生效）') : ('保存失败：' + (res.error || ''));
          $('cfgMsg').className = 'cfg-msg ' + (res.ok ? 'ok' : 'err');
        }).catch(function (e) { $('cfgMsg').textContent = '保存失败：' + e.message; $('cfgMsg').className = 'cfg-msg err'; });
      return;
    }
    if (ev.target && ev.target.id === 'cfgReset') loadStrategyConfig();
    var cfgToggle = ev.target.closest ? ev.target.closest('.cfg-toggle') : null;
    if (cfgToggle) {
      var state = cfgToggle.parentElement.querySelector('.cfg-state');
      if (state) state.textContent = cfgToggle.checked ? '启用' : '停用';
    }
    var btn = ev.target.closest ? ev.target.closest('.reason-pop') : null;
    if (btn) { ev.stopPropagation(); showPopup(btn.dataset.sid, ev.clientX, ev.clientY); return; }
    var stockRow = ev.target.closest ? ev.target.closest('.sector-stock-row') : null;
    if (stockRow && stockRow.dataset.tdxSid) {
      window.location.href = 'http://www.treeid/code_' + encodeURIComponent(code6(stockRow.dataset.tdxSid));
      return;
    }
    if (!ev.target.closest || !ev.target.closest('#popup')) $('popup').style.display = 'none';
  });
  document.addEventListener('input', function (ev) {
    if (ev.target && ev.target.id === 'themeSearch') renderThemeWorkbench(activeThemeView());
    if (ev.target && ev.target.id === 'sectorSearch') renderSectorWorkbench(CACHE[currentDay]);
  });
  document.addEventListener('change', function (ev) {
    if (!ev.target || ev.target.id !== 'themeDateSel') return;
    var date = ev.target.value;
    if (date === SECTOR_TODAY_VALUE) { startThemeRealtime(); return; }
    if (themeRealtime) stopThemeRealtime(false);
    $('dateSel').value = date;
    loadDay(date);
  });
  document.addEventListener('keydown', function (ev) { if (ev.key === 'Escape') $('popup').style.display = 'none'; });

  function toggleSectorExpand(row) {
    var sid = row.dataset.sid;
    var members = document.querySelector('.sec-members[data-sid="' + sid + '"]');
    if (!members) return;
    if (members.style.display !== 'none') { members.style.display = 'none'; return; }
    members.style.display = '';
    members.querySelector('td').innerHTML = '<div class="muted">加载成分股…</div>';
    loadExpandLibs().then(function () {
      var sids = sectorMembers(sid);
      members.querySelector('td').innerHTML = memberTable(sids.slice(0, 200), sids.length);
    });
  }

  loadIndex();
})();
