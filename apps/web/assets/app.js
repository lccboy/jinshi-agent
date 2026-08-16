/* 金十DSH 工作台 V0.1b —— 数据源 data/web/（视图层，nginx gzip_static + immutable 缓存） */
(function () {
  'use strict';

  var DAYS = [];          // index.json 日期清单（倒序）
  var CACHE = {};         // 日期 → day 视图（内存缓存；浏览器 immutable 缓存兜底）
  var DETAIL_CACHE = {};  // 日期 → detail 视图（懒加载）
  var currentDay = null;  // 当前日期（'latest' 或 'YYYY-MM-DD'）
  var currentView = 'signal';

  function $(id) { return document.getElementById(id); }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function code6(sid) { return String(sid || '').slice(2); }
  function stk(sid, name) { return '<a class="stk" href="http://www.treeid/code_' + esc(code6(sid)) + '" title="通达信联动">' + esc(name) + '</a>'; }
  function fmtMoney(n) { n = Number(n) || 0; var a = Math.abs(n); if (a >= 1e8) return (n / 1e8).toFixed(2) + '亿'; if (a >= 1e4) return (n / 1e4).toFixed(2) + '万'; return n.toFixed(0); }
  function fmtPct(n) { n = Number(n); return isNaN(n) ? '-' : (n >= 0 ? '+' : '') + n.toFixed(2) + '%'; }
  function cls(n) { return Number(n) >= 0 ? 'up' : 'dn'; }

  function fetchJSON(url, cacheMode) {
    return fetch(url, { cache: cacheMode || 'default' }).then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); });
  }
  function dayFile(date) { return 'data/web/day_' + date + '.json'; }

  /* ---------- 数据加载 ---------- */
  function loadIndex() {
    return fetchJSON('data/web/index.json').then(function (idx) {
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

  /* 实时信号：涨停池 + 资金流 + 领涨原因 */
  function vSignal(view) {
    var lu = view.limitup || [];
    var rows = lu.map(function (e, i) {
      var concepts = (e.concepts || []).map(function (c) { return '<span class="badge b-src">' + esc(c) + '</span>'; }).join('');
      return '<tr><td class="l">' + (i + 1) + '</td><td class="l">' + stk(e.stock_id, code6(e.stock_id)) + '</td>' +
        '<td class="l">' + stk(e.stock_id, '名称') + '</td>' +
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

    return card('🚀 涨停池', currentDay + ' · ' + (view.market.limit_up != null ? view.market.limit_up + ' 只涨停' : '实时检测'), luTable, true) +
      '<div class="grid2">' + mfCard + lrCard + '</div>';
  }

  /* 题材库：领涨原因题材列表 */
  function vTheme(view) {
    var lr = (view.leading_reason || []).map(function (p) {
      return '<div class="lead-item"><div class="lead-name">' + esc(p.name) + (p.limit_up_count ? ' <span class="badge b-boards">' + p.limit_up_count + ' 只</span>' : '') + '</div><div class="lead-reason">' + esc(p.reason || '-') + '</div></div>';
    }).join('');
    return card('📚 题材库 · 领涨题材', '板块领涨原因（选股宝）', lr || '<div class="muted" style="padding:12px">暂无数据</div>');
  }

  /* 板块强度：板块排行 + 资金流 */
  function vSector(view) {
    var secs = (view.sectors || []).map(function (s, i) {
      return '<tr><td>' + (i + 1) + '</td><td class="l">' + esc(s.name) + '</td>' +
        '<td class="up">' + fmtMoney(s.strength) + '</td><td class="' + cls(s.change) + '">' + fmtPct(s.change) + '</td>' +
        '<td class="' + cls(s.mainNet) + '">' + fmtMoney(s.mainNet) + '</td>' +
        (s.limit_up_count != null ? '<td>' + s.limit_up_count + '</td>' : '') + '</tr>';
    }).join('');
    var cols = '<th>#</th><th class="l">板块</th><th>强度</th><th>涨跌%</th><th>主力净额</th>' +
      ((view.sectors || [])[0] && view.sectors[0].limit_up_count != null ? '<th>涨停</th>' : '');
    var secTable = '<div class="tblwrap"><table><thead><tr>' + cols + '</tr></thead><tbody>' +
      (secs || '<tr><td colspan="5" class="muted">暂无板块数据</td></tr>') + '</tbody></table></div>';

    var mf = (view.money_flow || []).map(function (f, i) {
      return '<tr><td>' + (i + 1) + '</td><td class="l">' + esc(f.name) + '</td><td class="' + cls(f.main) + '">' + fmtMoney(f.main) + '</td><td class="' + cls(f.main_pct) + '">' + fmtPct(f.main_pct) + '</td></tr>';
    }).join('');
    var mfTable = '<div class="tblwrap"><table><thead><tr><th>#</th><th class="l">板块</th><th>主力净流入</th><th>占比</th></tr></thead><tbody>' +
      (mf || '<tr><td colspan="4" class="muted">暂无</td></tr>') + '</tbody></table></div>';

    return '<div class="grid2">' + card('📊 板块强度排行', currentDay + ' · 强度降序', secTable, true) +
      card('💧 板块资金流', '东财主力净流入', mfTable, true) + '</div>';
  }

  /* 策略模型：命中 + 买点 */
  function vStrategy(view) {
    var top = (view.strategy_top || []).map(function (e, i) {
      var models = Object.keys(e.models || {}).map(function (m) { return '<span class="badge b-model">' + esc(m) + '</span>'; }).join(' ');
      return '<tr><td>' + (i + 1) + '</td><td class="l">' + stk(e.stock_id, code6(e.stock_id)) + '</td>' +
        '<td class="l">' + models + '</td><td class="up">' + Number(e.score || 0).toFixed(1) + '</td>' +
        '<td>' + (e.buy_point ? Number(e.buy_point).toFixed(2) : '-') + '</td><td>' + (e.target ? Number(e.target).toFixed(2) : '-') + '</td></tr>';
    }).join('');
    var body = '<div class="tblwrap"><table><thead><tr><th>#</th><th class="l">代码</th><th class="l">命中模型</th><th>评分</th><th>买入区</th><th>目标</th></tr></thead><tbody>' +
      (top || '<tr><td colspan="6" class="muted">暂无策略命中（V0.3 策略引擎接入）</td></tr>') + '</tbody></table></div>';
    return card('🎯 策略模型 · 最佳买点 TOP' + top.length, '17 模型池（config/strategy.json 可编辑）', body, true);
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
    place(pop, x, y);
    if (DETAIL_CACHE[currentDay]) { renderDetail(sid, pop); return; }
    fetchJSON(dayFile(currentDay).replace('.json', '.detail.json')).then(function (d) {
      DETAIL_CACHE[currentDay] = d;
      renderDetail(sid, pop);
    }).catch(function () {
      pop.innerHTML = '<div class="pp-head"><span>详情加载失败</span><span class="pp-close" onclick="document.getElementById(\'popup\').style.display=\'none\'">×</span></div>';
    });
  }

  var SRC_META = { kpl: { label: '开盘啦', color: '#e24b4a' }, jygs: { label: '韭研公社', color: '#d29922' }, ths: { label: '同花顺', color: '#2f6fdb' }, xgb: { label: '选股吧', color: '#8e44ad' } };
  var SRC_ORDER = ['kpl', 'jygs', 'ths', 'xgb'];

  function renderDetail(sid, pop) {
    var d = DETAIL_CACHE[currentDay] || {};
    var e = (d.limitup || {})[sid];
    if (!e) { pop.innerHTML = '<div class="pp-head"><span>无详情</span><span class="pp-close" onclick="document.getElementById(\'popup\').style.display=\'none\'">×</span></div>'; return; }
    var sources = e.sources || {};
    var html = '<div class="pp-head"><span>' + esc(sid) + ' · 涨停原因（' + (e.sourceCount || 1) + ' 源）</span><span class="pp-close" onclick="document.getElementById(\'popup\').style.display=\'none\'">×</span></div>';
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
  }

  function place(pop, x, y) {
    var w = pop.offsetWidth, h = pop.offsetHeight;
    pop.style.left = Math.max(10, Math.min(x + 12, window.innerWidth - w - 10)) + 'px';
    pop.style.top = Math.max(10, Math.min(y + 10, window.innerHeight - h - 10)) + 'px';
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
      currentView = tab.dataset.view;
      if (history.replaceState) history.replaceState(null, '', '#' + currentView);
      render();
    });
  });
  $('dateSel').addEventListener('change', function () { loadDay(this.value); });
  document.addEventListener('click', function (ev) {
    var btn = ev.target.closest ? ev.target.closest('.reason-pop') : null;
    if (btn) { ev.stopPropagation(); showPopup(btn.dataset.sid, ev.clientX, ev.clientY); return; }
    if (!ev.target.closest || !ev.target.closest('#popup')) $('popup').style.display = 'none';
  });
  document.addEventListener('keydown', function (ev) { if (ev.key === 'Escape') $('popup').style.display = 'none'; });

  loadIndex();
})();
