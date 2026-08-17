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
    select.innerHTML = DAYS.map(function (d) { return '<option value="' + esc(d.date) + '">' + esc(d.date) + '</option>'; }).join('');
    if (themeRealtime) {
      var today = localToday();
      if (!DAYS.some(function (d) { return d.date === today; })) {
        select.insertAdjacentHTML('afterbegin', '<option value="' + esc(today) + '">' + esc(today) + '（盘中）</option>');
      }
      select.value = today;
    } else select.value = themeArchiveDay || currentDay;
    select.disabled = themeRealtime;
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
    sectorRealtime = isMarketSession() && !sectorForceHistory;
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
      '<div class="sector-date"><b>◀</b><span>' + esc(sectorDate) + '</span><b>▶</b></div></div>' +
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
      '<div class="sector-chart-empty"><div class="chart-legend"><span>■ 成交额</span><span>━ 价格</span></div><span>当前日视图暂无板块分时序列</span></div>' +
      '<div class="sector-subbar"><label>子板块</label>' + (subHtml || '<span class="muted">（无子板块）</span>') + '</div>' +
      '<div class="sector-filterbar"><button data-sector-filter="all">全部</button><button data-sector-filter="zt">涨停</button><button data-sector-filter="up6">≥6%</button><button data-sector-filter="up0">0~6%</button><button data-sector-filter="dn">&lt;0%</button></div>' +
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
    var filtered = rows.filter(function (r) { var c = Number(r.change) || 0; return sectorFilter === 'all' || (sectorFilter === 'zt' && c >= 9.8) || (sectorFilter === 'up6' && c >= 6 && c < 9.8) || (sectorFilter === 'up0' && c >= 0 && c < 6) || (sectorFilter === 'dn' && c < 0); });
    var body = filtered.map(function (r) {
      var reason = r.reason ? '<button type="button" class="reason-pop sector-reason" data-sid="' + esc(r.stock_id) + '" title="沿用 ' + esc(r.reason_date || '') + ' 涨停原因">' + esc(r.reason) + (r.reason_date ? ' <small>' + esc(r.reason_date.slice(5)) + '</small>' : '') + '</button>' : '-';
      return '<tr class="sector-stock-row ' + ((Number(r.change) || 0) >= 9.8 ? 'row-zt' : '') + '" data-tdx-sid="' + esc(r.stock_id) + '"><td class="l">' + esc(r.code) + '</td><td class="l">' + esc(r.name) + '</td><td>' + esc(r.position || '-') + '</td><td class="l">' + reason + '</td><td class="' + cls(r.change) + '">' + fmtPct(r.change) + '</td><td>' + esc(r.price || '-') + '</td><td>' + esc(r.turnover || '-') + '%</td><td>' + fmtMoney(r.amount) + '</td><td class="' + cls(r.main_net) + '">' + fmtMoney(r.main_net) + '</td><td>' + esc(r.vol_ratio || '-') + '</td><td>' + esc(r.net_flow_ratio || '-') + '</td><td>' + esc(r.boards || '-') + '</td><td>' + esc(r.pe || '-') + '</td><td>' + fmtMoney(r.circ_market_cap) + '</td></tr>';
    }).join('');
    host.innerHTML = '<div class="tblwrap"><table><thead><tr><th class="l">代码</th><th class="l">名称</th><th>地位</th><th class="l">涨停原因</th><th>涨跌幅</th><th>现价</th><th>换手率</th><th>成交额</th><th>主力净额</th><th>量比</th><th>净流占比</th><th>连板</th><th>市盈率</th><th>流通市值</th></tr></thead><tbody>' + (body || '<tr><td colspan="14" class="muted">暂无成分股</td></tr>') + '</tbody></table></div>';
    document.querySelectorAll('[data-sector-filter]').forEach(function (b) { b.classList.toggle('active', b.dataset.sectorFilter === sectorFilter); });
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
      var stamp = $('sectorLiveTime');
      if (stamp) stamp.textContent = ' KPL ' + (data.max_time || '--:--').replace(/^(\d{2})(\d{2})$/, '$1:$2');
    }).catch(function () {}).then(function () {
      if (sectorRealtime) sectorRealtimeTimer = window.setTimeout(refreshSectorRealtime, 5000);
    });
  }

  /* 策略模型：命中 + 买点 */
  function vStrategy(view) {
    var topEntries = view.strategy_top || [];
    var top = topEntries.map(function (e, i) {
      var models = Object.keys(e.models || {}).map(function (m) { return '<span class="badge b-model">' + esc(m) + '</span>'; }).join(' ');
      return '<tr><td>' + (i + 1) + '</td><td class="l">' + stk(e.stock_id, code6(e.stock_id)) + '</td>' +
        '<td class="l">' + models + '</td><td class="up">' + Number(e.score || 0).toFixed(1) + '</td>' +
        '<td>' + (e.buy_point ? Number(e.buy_point).toFixed(2) : '-') + '</td><td>' + (e.target ? Number(e.target).toFixed(2) : '-') + '</td></tr>';
    }).join('');
    var body = '<div class="tblwrap"><table><thead><tr><th>#</th><th class="l">代码</th><th class="l">命中模型</th><th>评分</th><th>买入区</th><th>目标</th></tr></thead><tbody>' +
      (top || '<tr><td colspan="6" class="muted">暂无策略命中（V0.3 策略引擎接入）</td></tr>') + '</tbody></table></div>';
    return card('🎯 策略模型 · 最佳买点 TOP' + topEntries.length, '17 模型池（config/strategy.json 可编辑）', body, true);
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
      if (tab.dataset.view === 'sector') sectorForceHistory = false;
      currentView = tab.dataset.view;
      if (history.replaceState) history.replaceState(null, '', '#' + currentView);
      render();
    });
  });
  $('dateSel').addEventListener('change', function () {
    if (themeRealtime) stopThemeRealtime(false);
    if (currentView === 'sector') { sectorForceHistory = true; sectorRealtime = false; window.clearTimeout(sectorRealtimeTimer); }
    loadDay(this.value);
  });
  document.addEventListener('click', function (ev) {
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
    var secRow = ev.target.closest ? ev.target.closest('.sec-row') : null;
    if (secRow) { toggleSectorExpand(secRow); return; }
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
