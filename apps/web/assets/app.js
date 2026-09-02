/* 金十DSH 工作台 V0.1b —— 数据源 data/web/（视图层，nginx gzip_static + immutable 缓存） */
(function () {
  'use strict';

  var DAYS = [];          // index.json 日期清单（倒序）
  var CACHE = {};         // 日期 → day 视图（内存缓存；浏览器 immutable 缓存兜底）
  var DETAIL_CACHE = {};  // 日期 → detail 视图（懒加载）
  var currentDay = null;  // 当前日期（'latest' 或 'YYYY-MM-DD'）
  var currentView = 'signal';
  var signalRealtimePayload = null, signalRealtimeTimer = null, signalRealtimeMode = false;
  var auctionRadarPayload = null, auctionRadarTimer = null, auctionRadarCursor = '';
  var localAuctionState = { status: 'checking' }, localAuctionView = null;
  var localAuctionMessage = '', localAuctionBusy = false;
  var AUCTION_ARCHIVE = {}, auctionArchiveLoading = {};
  var minuteVolumePayload = null, minuteVolumeTimer = null, minuteVolumeSelectedId = null, minuteVolumeDate = null;
  var minuteVolumeFilter = 'near', minuteVolumeMode = 'stock', minuteVolumeLocalEvents = [];
  var auctionFilter = 'focus', auctionTrajectoryFilter = '', auctionSelectedId = null;
  var auctionDepthFilter = 'confirmed', auctionVolumeFilter = 'all';
  var auctionToggles = { ratio: false, nonOnePrice: true, resonance: false };
  var memberLocalRealtime = null;
  var HISTORY_WATCHLIST = null, HISTORY_SOURCE_POOLS = {}, HISTORY_DATE_POOLS = {}, historyAssetsLoading = false;
  var SIGNAL_HISTORY_ACTIONABLE = {}, SIGNAL_HISTORY_ACTIONABLE_LOADING = {};
  var historyPoolKind = 'alert';
  var selectedLeadingId = null, leadingMode = 'realtime';
  var selectedExpectedId = null, expectedRange = 'all', expectedStatusFilter = 'all';
  var expectedHasLeaderOnly = false, expectedHasLimitupOnly = false;
  var expectedRelatedQuoteCache = {};
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
  var sectorTrendExpanded = false;
  var lastSectorIntraday = null;
  var sectorSortKey = 'position_rank';
  var sectorSortDir = 1;
  var lastSectorRows = [];
  var sectorBreadthRows = [], sectorBreadthLoading = false, sectorBreadthLoadedAt = 0;
  var sectorRealtimePendingKey = '', sectorRealtimeRequestSeq = 0;
  var sectorRealtimeView = null, sectorRealtimeBaseDay = '';
  var watchlistStateLoading = false;
  var MEMBER_LICENSE_API = 'license-api', MEMBER_LICENSE_FALLBACK = 'http://114.132.236.131:18908/api';
  var DSH_LICENSE_KEY = '_dsh_lic_v1', MEMBER_DEVICE_KEY = '_dev_fp';
  var MEMBER_WORKBENCH_VERSION = '1.0.34';
  var MEMBER_UPDATE_MANIFEST = 'downloads/member-workbench-latest.json';
  var memberLicenseState = null;

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
  function fetchLocalAuction(path, options) {
    return fetch('http://127.0.0.1:8790' + path, Object.assign({ cache: 'no-store', credentials: 'include' }, options || {}))
      .then(function (response) { return response.json().catch(function () { return {}; }).then(function (payload) {
        if (!response.ok || payload.ok === false) throw new Error(payload.reason || payload.error || ('HTTP ' + response.status));
        return payload.data == null ? payload : payload.data;
      }); });
  }
  function auctionControlWindow() {
    var now = new Date(), minutes = now.getHours() * 60 + now.getMinutes(), seconds = now.getSeconds();
    return minutes >= 554 && (minutes < 565 || (minutes === 565 && seconds <= 10));
  }
  function loadLocalAuctionStatus() {
    return Promise.all([fetchLocalAuction('/api/auction/status'), fetchLocalAuction('/api/auction/latest').catch(function () { return null; })])
      .then(function (values) { localAuctionState = values[0] || { status: 'stopped' }; localAuctionView = values[1]; if (currentView === 'auction') render(); })
      .catch(function (error) { localAuctionState = { status: 'offline', reason: error.message }; localAuctionView = null; if (currentView === 'auction') render(); });
  }
  function testLocalAuctionConnection() {
    localAuctionBusy = true; localAuctionMessage = '正在测试 eltdx 连接…'; render();
    return fetchLocalAuction('/api/auction/test-connection', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      .then(function (data) { localAuctionMessage = data.status === 'available' ? 'eltdx 可用，延迟 ' + data.latency_ms + ' ms' : 'eltdx 不可用：' + (data.reason || '-'); })
      .catch(function (error) { localAuctionMessage = '测试失败：' + error.message + '；请先打开 8790 完成本机授权'; })
      .then(function () { localAuctionBusy = false; return loadLocalAuctionStatus(); });
  }
  function controlLocalAuction(action) {
    localAuctionBusy = true; localAuctionMessage = action === 'start' ? '正在启动本地影子采集…' : '正在停止…'; render();
    return fetchLocalAuction('/api/auction/' + action, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      .then(function (data) { localAuctionMessage = data.status === 'blocked' ? '未启动：当前不在 09:14–09:25:10 实盘窗口' : '本地采集状态：' + (data.status || '-'); })
      .catch(function (error) { localAuctionMessage = '控制失败：' + error.message + '；请先打开 8790 完成本机授权'; })
      .then(function () { localAuctionBusy = false; return loadLocalAuctionStatus(); });
  }
  function loadMemberLocalRealtime() {
    var memberId = localStorage.getItem('jinshi_member_id') || '';
    return new Promise(function (resolve) {
      var callback = '__dshLocalRealtime' + Date.now(), script = document.createElement('script');
      var timer = window.setTimeout(function () { cleanup(); resolve(null); }, 2500);
      function cleanup() { window.clearTimeout(timer); delete window[callback]; if (script.parentNode) script.parentNode.removeChild(script); }
      window[callback] = function (doc) { cleanup(); memberLocalRealtime = doc && doc.ok ? doc.data : null; resolve(memberLocalRealtime); };
      script.onerror = function () { cleanup(); resolve(null); };
      script.src = 'http://127.0.0.1:8790/api/compat?callback=' + callback + '&action=signal&member_id=' + encodeURIComponent(memberId) + '&_=' + Date.now();
      document.head.appendChild(script);
    });
  }
  function mergeSignalEvents(left, right) {
    var seen = {}, merged = [];
    (left || []).concat(right || []).sort(function (a, b) {
      return String(b.ts || '').localeCompare(String(a.ts || ''));
    }).forEach(function (event) {
      var key = [event.source || '', event.ts || '', event.type || '', event.stock_id || '',
        event.plate || '', event.detail || ''].join('|');
      if (seen[key]) return;
      seen[key] = true; merged.push(event);
    });
    return merged.slice(0, 200);
  }
  function mergeMemberLocalRealtime(payload, local) {
    if (!local || !local.available || local.data_date !== payload.data_date) return payload;
    payload.local_actionable_alerts = local.actionable_alerts || [];
    payload.actionable_alerts = payload.local_actionable_alerts.concat(payload.actionable_alerts || []);
    payload.model_hits = (local.model_hits || []).concat(payload.model_hits || []);
    payload.events = mergeSignalEvents(local.events, payload.events);
    payload.local_member_id = local.member_id;
    return payload;
  }
  function postJSON(url, payload) {
    return fetch(url, { method: 'POST', cache: 'no-store', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload) }).then(function (r) { return r.json().then(function (d) {
        if (!r.ok) throw new Error(d.error || ('HTTP ' + r.status)); return d;
      }); });
  }

  function openMemberLocalPage() {
    if (memberIsLocalWorkbench()) { switchMemberPane('data'); loadMemberWorkbenchConfig(); return; }
    location.href = 'http://127.0.0.1:8790/#member';
  }
  function memberIsLocalWorkbench() {
    return (location.hostname === '127.0.0.1' || location.hostname === 'localhost') && location.port === '8790';
  }
  function memberStateText(value, okText, badText) { return value ? okText : badText; }
  function renderMemberWorkbenchStatus(doc) {
    if (!doc) return;
    if ($('memberWorkbenchVersion')) $('memberWorkbenchVersion').textContent = doc.version || '-';
    if ($('memberWorkbenchDataRoot')) $('memberWorkbenchDataRoot').textContent = doc.data_root || '-';
    var sync = doc.sync || {}, syncing = sync.phase === 'downloading';
    if ($('memberSyncState')) $('memberSyncState').textContent = syncing ? '正在下载公共数据' :
      (sync.fresh && sync.complete ? '已同步，正在检查增量' : (sync.error ? '同步失败' : '等待首次同步'));
    if ($('memberDataIntegrity')) $('memberDataIntegrity').textContent = memberStateText(doc.sync && doc.sync.datasets_complete, '七 TAB 数据完整', '公共数据不完整');
    if ($('memberCalculationState')) $('memberCalculationState').textContent = memberStateText(doc.calculation && doc.calculation.status === 'success', '计算正常', '等待计算');
    if ($('memberMonitoringState')) $('memberMonitoringState').textContent = memberStateText(doc.monitoring, '监控中', '尚未监控');
    if ($('memberSyncDetail')) {
      var labels = { auction: '竞价雷达', strategy: '策略模型', history: '历史选股',
        theme_library: '题材库', sector_strength: '板块强度', leading_reason: '领涨原因' };
      var datasets = Object.keys(sync.datasets || {}).filter(function (key) { return (sync.datasets[key] || {}).complete; })
        .map(function (key) { return labels[key] || key; });
      var size = Number(sync.total_bytes || 0) / 1048576;
      var archive = sync.history_archive || {};
      var archiveHint = archive.download_mode === 'on_demand' ?
        ('；历史归档按需下载：服务器可用 ' + Number(archive.available_days || 0) + ' 个交易日 / ' +
          (Number(archive.total_bytes || 0) / 1048576).toFixed(1) +
          ' MB，切换历史日期时自动下载并缓存') : '';
      $('memberSyncDetail').textContent = syncing ?
        ('正在同步 ' + Number(sync.file_count || 0) + ' 个公共文件，约 ' + size.toFixed(1) + ' MB：' + datasets.join('、')) :
        ('数据日期 ' + (sync.data_date || '-') + '；公共文件 ' + Number(sync.file_count || 0) + ' 个 / ' + size.toFixed(1) +
          ' MB；内容：' + (datasets.join('、') || '公共行情与 TAB 视图') + '；最近检查 ' + (sync.synced_at || '-') +
          (sync.sync_mode === 'reused' ? '（版本未变化，未重复下载）' : '') + archiveHint);
    }
  }
  function loadMemberWorkbenchStatus() {
    if (!memberIsLocalWorkbench()) {
      if ($('memberWorkbenchVersion')) $('memberWorkbenchVersion').textContent = '公网入口';
      if ($('memberWorkbenchDataRoot')) $('memberWorkbenchDataRoot').textContent = '私有目录仅在本机显示';
      return Promise.resolve(null);
    }
    return fetchJSON('/api/system/status', 'no-store').then(function (doc) {
      renderMemberWorkbenchStatus(doc); return loadMemberWorkbenchConfig();
    }).catch(function (err) { if ($('memberMonitoringState')) $('memberMonitoringState').textContent = '状态读取失败：' + err.message; });
  }
  function loadMemberWorkbenchConfig() {
    if (!memberIsLocalWorkbench()) return Promise.resolve(null);
    var memberId = ($('memberId') && $('memberId').value || localStorage.getItem('jinshi_member_id') || '').trim();
    if (!memberId) { if ($('memberConfigMessage')) $('memberConfigMessage').textContent = '请先完成会员授权'; return Promise.resolve(null); }
    return fetchJSON('/api/member/config?member_id=' + encodeURIComponent(memberId), 'no-store').then(function (doc) {
      var data = doc.data || {};
      if ($('memberVipdoc')) $('memberVipdoc').value = data.vipdoc || '';
      if ($('memberTdxRoot')) $('memberTdxRoot').value = data.tdx_root || '';
      if ($('memberGbbqPath')) $('memberGbbqPath').value = data.gbbq_path || '';
      if ($('memberKlineDir')) $('memberKlineDir').value = data.kline_dir || '';
      if ($('memberConfigMessage')) $('memberConfigMessage').textContent = data.vipdoc_valid ? '配置有效' : '请配置有效的 vipdoc 目录';
      return data;
    }).catch(function (err) { if ($('memberConfigMessage')) $('memberConfigMessage').textContent = '读取失败：' + err.message; });
  }
  function saveMemberWorkbenchConfig(generate) {
    if (!memberIsLocalWorkbench()) { openMemberLocalPage(); return Promise.resolve(null); }
    var memberId = ($('memberId') && $('memberId').value || localStorage.getItem('jinshi_member_id') || '').trim();
    var payload = { member_id: memberId, vipdoc: ($('memberVipdoc').value || '').trim(), tdx_root: ($('memberTdxRoot').value || '').trim() };
    $('memberConfigMessage').textContent = generate ? '正在启动 K 线生成…' : '正在保存并检查…';
    return postJSON(generate ? '/api/member/generate' : '/api/member/config', payload).then(function (doc) {
      $('memberConfigMessage').textContent = generate ? '已开始后台生成 K 线，可在总览查看计算状态' : (doc.data.vipdoc_valid ? '保存成功，vipdoc 有效' : '已保存，但 vipdoc 无效');
      return loadMemberWorkbenchStatus();
    }).catch(function (err) { $('memberConfigMessage').textContent = '操作失败：' + err.message; });
  }
  function compareMemberVersion(left, right) {
    var a = String(left || '0').split('.').map(Number), b = String(right || '0').split('.').map(Number);
    for (var i = 0; i < 3; i++) { if ((a[i] || 0) !== (b[i] || 0)) return (a[i] || 0) - (b[i] || 0); }
    return 0;
  }
  function checkMemberWorkbenchUpdate() {
    if ($('memberUpdateState')) $('memberUpdateState').textContent = '正在检查服务器版本…';
    var manifestUrl = memberIsLocalWorkbench() ? '/api/system/update' : MEMBER_UPDATE_MANIFEST;
    return fetchJSON(manifestUrl + '?_=' + Date.now(), 'no-store').then(function (doc) {
      if ($('memberLatestVersion')) $('memberLatestVersion').textContent = doc.version || '-';
      var newer = compareMemberVersion(MEMBER_WORKBENCH_VERSION, doc.version) < 0;
      if ($('memberUpdateState')) $('memberUpdateState').textContent = newer ? '发现新版本，请下载后运行安装脚本；会员数据不会被覆盖。' : '当前已是最新版。';
      var link = $('memberUpdateDownload'); if (link) { link.href = doc.zip_url || '#'; link.hidden = !newer; }
      return doc;
    }).catch(function (err) { if ($('memberUpdateState')) $('memberUpdateState').textContent = '检查失败：' + err.message + '。可直接点击下方“下载最新版”。'; });
  }
  function memberDeviceFingerprint() {
    var saved = localStorage.getItem(MEMBER_DEVICE_KEY); if (saved) return saved;
    var raw = [navigator.userAgent, navigator.language || '', screen.width + 'x' + screen.height,
      screen.colorDepth, new Date().getTimezoneOffset(), navigator.hardwareConcurrency || '', navigator.platform || ''].join('|');
    var hash = 0x811c9dc5;
    for (var i = 0; i < raw.length; i++) { hash ^= raw.charCodeAt(i); hash = (hash * 0x01000193) >>> 0; }
    var fp = 'DEV-' + ('00000000' + hash.toString(16).toUpperCase()).slice(-8) + '-' + Date.now().toString(36).toUpperCase().slice(-4);
    localStorage.setItem(MEMBER_DEVICE_KEY, fp); return fp;
  }
  function loadLicenseState() {
    try { return JSON.parse(localStorage.getItem(DSH_LICENSE_KEY) || 'null'); } catch (e) { return null; }
  }
  function licenseJSON(path, payload) {
    var options = { method: 'POST', cache: 'no-store', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload) };
    function parse(r) { return r.json().then(function (doc) { if (!r.ok || !doc.success) throw new Error(doc.message || ('HTTP ' + r.status)); return doc; }); }
    return fetch(MEMBER_LICENSE_API + path, options).then(parse)
      .catch(function (err) {
        if (memberIsLocalWorkbench()) throw err;
        return fetch(MEMBER_LICENSE_FALLBACK + path, options).then(parse);
      });
  }
  function renderMemberLicense(state, message) {
    if (!$('memberLicenseStatus')) return;
    var user = state && state.user || {}, active = !!(state && state.valid);
    $('memberLicenseStatus').textContent = active ? '有效' : '未激活';
    $('memberLicenseStatus').className = active ? 'ok' : 'bad';
    $('memberLicensePlan').textContent = user.plan || '-'; $('memberLicenseExpire').textContent = user.expire_date || '-';
    $('memberLicenseDays').textContent = user.remaining_days == null ? '-' : user.remaining_days + ' 天';
    $('memberId').value = active ? (state.cloud_user_id || user.id || '') : '';
    $('memberLicenseCode').value = state && state.code || '';
    $('memberLicenseMessage').textContent = message || '';
    if ($('memberOverviewLicense')) $('memberOverviewLicense').textContent = active ? '已授权' : '未授权';
  }
  function persistMemberLicense(doc, code) {
    var user = doc.user || {};
    memberLicenseState = { valid: true, code: code, cloud_user_id: user.id, user: user,
      device_fingerprint: memberDeviceFingerprint(), last_check: new Date().toISOString() };
    localStorage.setItem(DSH_LICENSE_KEY, JSON.stringify(memberLicenseState));
    localStorage.setItem('jinshi_member_id', user.id);
    renderMemberLicense(memberLicenseState, doc.message || '授权有效');
    return memberLicenseState;
  }
  function activateMemberLicense() {
    var code = $('memberLicenseCode').value.trim().toUpperCase();
    $('memberLicenseMessage').textContent = '正在连接云授权中心…';
    return licenseJSON('/activate', { code: code, device_fingerprint: memberDeviceFingerprint() })
      .then(function (doc) { return persistMemberLicense(doc, code); })
      .catch(function (err) { renderMemberLicense(null, '激活失败：' + err.message); });
  }
  function registerMemberTrial() {
    var name = ($('memberTrialName').value || '').trim(), phone = ($('memberTrialPhone').value || '').trim();
    $('memberTrialMessage').textContent = '正在注册并生成试用码…';
    return licenseJSON('/trial/register', { name: name, phone: phone,
      device_fingerprint: memberDeviceFingerprint() }).then(function (trial) {
        $('memberLicenseCode').value = trial.code;
        $('memberTrialMessage').textContent = '试用码已生成，正在自动激活…';
        return licenseJSON('/activate', { code: trial.code, device_fingerprint: memberDeviceFingerprint(),
          user_name: name, phone: phone });
      }).then(function (doc) {
        persistMemberLicense(doc, $('memberLicenseCode').value.trim().toUpperCase());
        $('memberTrialMessage').textContent = '注册成功，已开通免费试用 5 天。';
        return doc;
      }).catch(function (err) { $('memberTrialMessage').textContent = '注册失败：' + err.message; return null; });
  }
  function validateMemberLicense() {
    var state = memberLicenseState || loadLicenseState();
    if (!state || !state.code) { renderMemberLicense(null, '请先输入激活码'); return Promise.resolve(null); }
    if ($('memberLicenseMessage')) $('memberLicenseMessage').textContent = '正在校验…';
    return licenseJSON('/validate', { code: state.code, device_fingerprint: state.device_fingerprint || memberDeviceFingerprint() })
      .then(function (doc) { return persistMemberLicense(doc, state.code); })
      .catch(function (err) { memberLicenseState = null; localStorage.removeItem(DSH_LICENSE_KEY); localStorage.removeItem('jinshi_member_id'); renderMemberLicense(null, '校验失败：' + err.message); return null; });
  }
  function logoutMemberLicense() {
    memberLicenseState = null; localStorage.removeItem(DSH_LICENSE_KEY); localStorage.removeItem('jinshi_member_id');
    renderMemberLicense(null, '已退出当前授权');
  }
  function loadMemberLicense() {
    memberLicenseState = loadLicenseState(); renderMemberLicense(memberLicenseState, '');
    return memberLicenseState && memberLicenseState.code ? validateMemberLicense() : Promise.resolve(null);
  }
  function openMemberCenter() {
    currentView = 'member';
    document.querySelectorAll('.tab').forEach(function (tab) { tab.classList.remove('active'); });
    if (history.replaceState) history.replaceState(null, '', '#member');
    render();
  }
  function switchMemberPane(name) {
    document.querySelectorAll('[data-member-pane]').forEach(function (el) { el.classList.toggle('active', el.dataset.memberPane === name); });
    document.querySelectorAll('[data-member-content]').forEach(function (el) { el.hidden = el.dataset.memberContent !== name; });
  }
  function vMemberCenter() {
    // 本地会员模型结果由 8790 同源接口合并到实时信号，私有数据不上传。
    var local = memberIsLocalWorkbench();
    return '<section class="member-page"><aside class="member-page-nav"><div class="member-page-brand"><strong>会员中心</strong><span>金十DSH一体化工作台</span></div>' +
      '<button class="active" type="button" data-member-pane="overview">工作台总览</button><button type="button" data-member-pane="license">会员授权</button><button type="button" data-member-pane="data">通达信数据</button><button type="button" data-member-pane="upgrade">安装与升级</button><button type="button" data-member-pane="guide">使用指南</button></aside>' +
      '<main class="member-page-content"><section data-member-content="overview"><h1>工作台总览</h1><p class="member-note">统一查看公共数据同步、会员授权、本地 K 线计算和实时监控状态。</p><div class="member-workbench-grid"><div><span>工作台版本</span><strong id="memberWorkbenchVersion">-</strong></div><div><span>数据根目录</span><strong id="memberWorkbenchDataRoot">-</strong></div><div><span>公共数据</span><strong id="memberSyncState">-</strong></div><div><span>数据完整性</span><strong id="memberDataIntegrity">-</strong></div><div><span>会员授权</span><strong id="memberOverviewLicense">-</strong></div><div><span>本地计算</span><strong id="memberCalculationState">-</strong></div><div><span>运行状态</span><strong id="memberMonitoringState">-</strong></div></div><p id="memberSyncDetail" class="member-note">正在读取公共数据同步明细…</p><div class="member-actions"><button id="memberRefreshStatus" type="button">刷新运行状态</button></div></section>' +
      '<section data-member-content="license" hidden><h1>会员授权</h1><p class="member-note">使用云授权管理中心的现有激活码，原题材库会员数据和到期时间直接复用。</p>' +
      '<div class="member-license-summary"><div><span>授权状态</span><strong id="memberLicenseStatus">未激活</strong></div><div><span>套餐</span><strong id="memberLicensePlan">-</strong></div><div><span>到期时间</span><strong id="memberLicenseExpire">-</strong></div><div><span>剩余天数</span><strong id="memberLicenseDays">-</strong></div></div>' +
      '<div class="member-trial-box"><h2>新会员注册 · 免费试用 5 天</h2><p>每个手机号和每台设备仅可领取一次。</p><label>姓名或昵称<input id="memberTrialName" maxlength="40" placeholder="请输入姓名或昵称"></label><label>手机号<input id="memberTrialPhone" inputmode="numeric" maxlength="11" placeholder="请输入 11 位手机号"></label><div class="member-actions"><button id="memberRegisterTrial" type="button">注册并领取 5 天试用</button><span id="memberTrialMessage"></span></div></div><hr class="member-section-divider"><label>已有激活码<input id="memberLicenseCode" autocomplete="off" placeholder="AK-XXXX-XXXX-XXXX-X"></label><div class="member-actions"><button id="memberActivate" type="button">激活会员</button><button id="memberRevalidate" class="secondary" type="button">重新校验</button><button id="memberLogout" class="secondary" type="button">退出授权</button><span id="memberLicenseMessage"></span></div><label>云会员编号<input id="memberId" readonly placeholder="激活后自动绑定"></label></section>' +
      '<section data-member-content="data" hidden><h1>通达信数据</h1><p class="member-note">vipdoc、复权权息文件和生成的会员 K 线只保存在本机。' + (local ? '当前为本地工作台，可直接配置。' : '请先打开本地工作台后配置，公网页面不会读取或上传本机路径。') + '</p>' +
      (local ? '<label>vipdoc 目录<input id="memberVipdoc" placeholder="例如 H:\\new_tdx\\vipdoc"></label><label>通达信根目录（用于查找复权权息数据）<input id="memberTdxRoot" placeholder="例如 H:\\new_tdx"></label><label>已识别的 gbbq 文件<input id="memberGbbqPath" readonly></label><label>会员 K 线输出目录<input id="memberKlineDir" readonly></label><div class="member-actions"><button id="memberSaveConfig" type="button">保存并检查</button><button id="memberGenerateKline" class="secondary" type="button">生成会员 K 线</button><span id="memberConfigMessage"></span></div>' : '<button id="memberOpenLocalPage" class="member-retry-helper" type="button">打开 127.0.0.1:8790 本地工作台</button>') + '</section>' +
      '<section data-member-content="upgrade" hidden><h1>安装与升级</h1><p class="member-note">以后新增或修改 TAB 页面和功能，通过版本化工作台包更新；安装程序只替换 app，继续使用原 data 数据目录。</p><div class="member-version-row"><span>当前页面版本 <b>' + MEMBER_WORKBENCH_VERSION + '</b></span><span>服务器最新版本 <b id="memberLatestVersion">未检查</b></span></div><div class="member-actions"><button id="memberCheckUpdate" type="button">检查更新</button><a id="memberUpdateDownload" class="member-helper-download" href="http://114.132.236.131/dsh/downloads/JinshiDSH-Workbench-1.0.34.zip" download>下载最新版</a></div><p id="memberUpdateState" class="member-note">检查更新后会显示升级结果。</p><a class="member-helper-download" href="http://114.132.236.131/dsh/downloads/JinshiDSH-Workbench-1.0.34.zip" download>下载本地一体化工作台 1.0.34</a><a class="member-helper-download" href="member-guide.html" target="_blank">查看安装与使用指南</a></section>' +
      '<section data-member-content="guide" hidden><h1>使用指南</h1><div class="member-helper-steps"><b>首次使用</b><ol><li>下载 ZIP，解压后运行 install-member-workbench.ps1</li><li>打开 127.0.0.1:8790，在会员授权页激活</li><li>在通达信数据页配置 vipdoc 和通达信根目录</li><li>生成会员 K 线，在总览确认“监控中”</li></ol><b>TAB 页面和功能更新</b><ol><li>打开“安装与升级”并检查更新</li><li>下载新版 ZIP，解压后再次运行安装脚本</li><li>原数据根目录和会员历史数据自动保留</li></ol></div></section></main></section>';
  }
  var DATA_VIEW_REV = '20260828-intraday-close-boundary-v1';
  function dayFile(date) { return 'data/web/day_' + date + '.json?v=' + DATA_VIEW_REV; }

  /* ---------- 主数据懒加载库（题材/板块/成分，进题材/板块 tab 时拉，内存缓存） ---------- */
  var LIBS = {};
  var signalLibLoading = false;
  var expectedLibLoading = false;
  var focusTag = null;
  function loadLib(name) {
    var key = name.replace(/\.json$/, '');
    if (LIBS[key]) return Promise.resolve(LIBS[key]);
    return fetchJSON('data/web/' + name + '?v=' + DATA_VIEW_REV).then(function (d) { LIBS[key] = d; return d; });
  }
  function loadExpandLibs() {
    return Promise.all([loadLib('theme_stocks.json'), loadLib('stocks_slim.json')]);
  }
  function ensureSignalLibs() {
    if (LIBS.stocks_slim || signalLibLoading) return;
    signalLibLoading = true;
    loadLib('stocks_slim.json').then(function () { signalLibLoading = false; if (currentView === 'signal' || currentView === 'leading') render(); })
      .catch(function () { signalLibLoading = false; });
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
      if (DAYS.length) {
        sel.value = DAYS[0].date;
        var dayPromise;
        // 策略页仅在交易时段保持「当天 · 实时」；收盘后必须明确选中最新归档日。
        if (currentView === 'strategy' && !stratManualArchive && isMarketSession()) sel.value = SECTOR_TODAY_VALUE;
        if (currentView === 'auction') sel.value = SECTOR_TODAY_VALUE;
        if (currentView === 'minute-volume') sel.value = SECTOR_TODAY_VALUE;
        if ((currentView === 'signal' || currentView === 'leading') && signalRealtimeMode) sel.value = SECTOR_TODAY_VALUE;
        dayPromise = loadDay(DAYS[0].date);
        if ((currentView === 'signal' || currentView === 'leading') && signalRealtimeMode) {
          return dayPromise.then(function (view) { startSignalRealtime(); return view; });
        }
        if (currentView === 'auction') {
          return dayPromise.then(function (view) { startAuctionRadar(); return view; });
        }
        if (currentView === 'minute-volume') {
          return dayPromise.then(function (view) { startMinuteVolume(); return view; });
        }
        return dayPromise;
      }
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

  function mergeSignalHistoryActionable(poolDoc, strategyDoc) {
    var pools = (poolDoc && (poolDoc.data || poolDoc).pools) || {};
    var alertPool = pools.alert || {};
    var strategyRowsById = {};
    ((strategyDoc && strategyDoc.list) || []).forEach(function (row) {
      if (row && row.stock_id) strategyRowsById[row.stock_id] = row;
    });
    return Object.keys(alertPool).map(function (sid) {
      var alert = alertPool[sid] || {}, row = strategyRowsById[sid] || {};
      var hit = (alert.model_hit && alert.model_hit.length) ? alert.model_hit : Object.keys(row.models || {});
      return {
        stock_id: sid, name: row.name || alert.name || '', level: Number(alert.stars || row.stars || 0) >= 4 ? 'A' : 'B',
        quality_score: alert.score == null ? row.score : alert.score,
        price: row.price, buy_lo: alert.buy_point == null ? row.buy_lo : alert.buy_point,
        stop: alert.stop == null ? row.stop : alert.stop, rr: alert.rr == null ? row.rr : alert.rr,
        change_pct: row.chg, model_hit: hit, confirm: alert.confirm || row.confirm || {},
        stars: alert.stars == null ? row.stars : alert.stars,
        reasons: hit.slice(0, 3).map(function (modelId) { return (MODEL_CN || {})[modelId] || modelId; })
      };
    }).slice(0, 12);
  }

  function loadSignalHistoryActionable(date, view) {
    date = String(date || '');
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || SIGNAL_HISTORY_ACTIONABLE_LOADING[date]) return;
    if (Object.prototype.hasOwnProperty.call(SIGNAL_HISTORY_ACTIONABLE, date)) {
      view.actionable_alerts = SIGNAL_HISTORY_ACTIONABLE[date];
      view.memberSignalHistoryLoaded = true;
      return;
    }
    SIGNAL_HISTORY_ACTIONABLE_LOADING[date] = true;
    Promise.all([
      fetchJSON('api/pools?date=' + encodeURIComponent(date), 'no-store'),
      fetchJSON('data/web/strategy_all_' + date + '.json', 'default')
    ]).then(function (result) {
      var rows = mergeSignalHistoryActionable(result[0], result[1]);
      SIGNAL_HISTORY_ACTIONABLE[date] = rows;
      if (view && CACHE[date] === view) {
        if (rows.length) view.actionable_alerts = rows;
        view.memberSignalHistoryLoaded = true;
      }
    }).catch(function () {
      if (view && CACHE[date] === view) view.memberSignalHistoryLoaded = true;
    }).then(function () {
      delete SIGNAL_HISTORY_ACTIONABLE_LOADING[date];
      if (currentView === 'signal' && currentDay === date && !signalRealtimeMode) render();
    });
  }

  /* ---------- 视图渲染 ---------- */
  function render() {
    var view = CACHE[currentDay];
    if (!view) return;
    var html = '';
    if (currentView === 'signal' || currentView === 'leading') {
      if (currentView === 'signal' && !signalRealtimeMode && !view.memberSignalHistoryLoaded) {
        window.setTimeout(function () { loadSignalHistoryActionable(currentDay, view); }, 0);
      }
      var signalDataIsToday = !!(signalRealtimePayload && signalRealtimePayload.data_date === localToday());
      var signalView = signalRealtimeMode && signalRealtimePayload && signalRealtimePayload.available
        ? Object.assign({}, view, { date: signalRealtimePayload.data_date, data_date: signalRealtimePayload.data_date,
            limitup: signalRealtimePayload.limitup || [], events: signalRealtimePayload.events || [],
            model_hits: signalRealtimePayload.model_hits || [],
            actionable_alerts: signalRealtimePayload.actionable_alerts || [], signal_ts: signalRealtimePayload.ts || '',
            signalDataIsToday: signalDataIsToday,
            money_flow: (signalRealtimePayload.money_flow || []).length ? signalRealtimePayload.money_flow : (view.money_flow || []),
            money_flow_ts: signalRealtimePayload.money_flow_ts || '',
            leading_reason: (signalRealtimePayload.leading_reason || []).length ? signalRealtimePayload.leading_reason : (view.leading_reason || []),
            leading_reason_ts: signalRealtimePayload.leading_reason_ts || '',
            expected_leaders: (signalRealtimePayload.expected_leaders || []).length ? signalRealtimePayload.expected_leaders : (view.expected_leaders || []),
            expected_leaders_ts: signalRealtimePayload.expected_leaders_ts || '',
            market: signalRealtimePayload.market || view.market || {}, indexes: signalRealtimePayload.indexes || view.indexes || {} }) : view;
      html = currentView === 'signal' ? vSignal(signalView) : vLeadingReason(signalView);
    }
    else if (currentView === 'auction') {
      var auctionIsRealtime = $('dateSel') && $('dateSel').value === SECTOR_TODAY_VALUE;
      if (!auctionIsRealtime && !AUCTION_ARCHIVE[currentDay] && !auctionArchiveLoading[currentDay]) {
        window.setTimeout(function () { loadAuctionArchive(currentDay, view.auction_radar || {}); }, 0);
      }
      html = vAuctionRadar(auctionIsRealtime ? auctionRadarPayload :
        (AUCTION_ARCHIVE[currentDay] || view.auction_radar || {}));
    }
    else if (currentView === 'minute-volume') html = vMinuteVolume(minuteVolumePayload);
    else if (currentView === 'theme') html = vTheme(view);
    else if (currentView === 'sector') html = vSector(view);
    else if (currentView === 'strategy') html = vStrategy(view);
    else if (currentView === 'history') {
      var historyView = signalRealtimeMode && signalRealtimePayload && signalRealtimePayload.available &&
        signalRealtimePayload.data_date === localToday() && signalRealtimePayload.history_pools
        ? Object.assign({}, view, { date: signalRealtimePayload.data_date,
            pools: signalRealtimePayload.history_pools,
            pool_summary: signalRealtimePayload.history_pool_summary || {} }) : view;
      html = vHistory(historyView);
    }
    else if (currentView === 'member') html = vMemberCenter();
    $('main').classList.toggle('member-mode', currentView === 'member');
    $('main').innerHTML = html;
    if (currentView === 'member') { loadMemberLicense().then(loadMemberWorkbenchStatus); }
    if (currentView === 'minute-volume') window.setTimeout(drawMinuteVolumeCharts, 0);
  }

  function renderEmpty(msg) {
    $('main').innerHTML = '<section class="empty-state"><h1>金十DSH 工作台</h1><p>' + esc(msg) + '</p></section>';
  }

  function loadAuctionArchive(date, summary) {
    if (!date || AUCTION_ARCHIVE[date] || auctionArchiveLoading[date]) return Promise.resolve(AUCTION_ARCHIVE[date]);
    auctionArchiveLoading[date] = true;
    var file = (summary && summary.data_file) || ('day_' + date + '.auction.json');
    return fetchJSON('data/web/' + file).then(function (radar) {
      AUCTION_ARCHIVE[date] = radar;
      if (currentView === 'auction' && currentDay === date) render();
      return radar;
    }).catch(function () {
      AUCTION_ARCHIVE[date] = Object.assign({}, summary || {}, { status: 'unavailable', candidates: [] });
      if (currentView === 'auction' && currentDay === date) render();
      return AUCTION_ARCHIVE[date];
    }).then(function (radar) { delete auctionArchiveLoading[date]; return radar; });
  }

  function card(title, sub, body, flush) {
    return '<section class="card"><div class="card-h"><span>' + title + '</span>' +
      (sub ? '<span class="sub">' + sub + '</span>' : '') + '</div><div class="card-b' + (flush ? ' flush' : '') + '">' + body + '</div></section>';
  }

  function auctionLabel(value) {
    var labels = { S: 'S', A: 'A', B: 'B', watch: '观察', risk: '风险', wait: '待开盘确认',
      tradable: '可重点关注', not_tradable: '暂不关注', not_confirmed: '截至当前未获确认',
      unavailable: '数据不足', pending: '待确认',
      confirmed: '已确认', invalidated: '已失效' };
    return labels[value] || value || '-';
  }
  function auctionTrajectoryLabel(value) {
    var labels = { steady_strengthen: '稳步增强', limit_withdraw_absorption: '涨停撤单承接',
      late_accumulation: '尾盘抢筹', stable_gap: '稳定高开', fake_limit: '虚封撤单',
      volume_stall: '放量滞涨', unclassified: '未分类' };
    return labels[value] || '—';
  }
  function auctionDepthLabel(value) {
    var labels = { sealed_control: '强封控盘', withdraw_absorption: '撤单承接',
      withdraw_weakening: '撤单转弱', seller_dominant: '卖方占优',
      stable_non_limit: '普通稳定', depth_unconfirmed: '深度未确认' };
    return labels[value] || '深度未确认';
  }
  function auctionVolumeBreakLabel(value) {
    var labels = { auction_peak_break: '竞价量超昨峰', none: '未超昨峰',
      volume_baseline_unavailable: '昨峰基线不可用' };
    return labels[value] || '未确认';
  }
  function auctionEvidenceLabel(value) {
    var labels = { yesterday_limitup: '昨日涨停', late_price_volume_rise: '尾段价量齐升',
      early_limit: '早段触及涨停', locked_phase_absorption: '封板阶段有承接', last60_stable: '最后60秒稳定',
      locked_price_rise: '封板价位抬升', final_near_high: '收盘接近竞价高点', moderate_stable_gap: '高开幅度适中且稳定',
      isolated_move: '缺少板块共振', sector_median_not_positive: '板块竞价中位数未走强', auction_liquidity_low: '竞价成交额偏低',
      trajectory_evidence_incomplete: '轨迹证据不完整', sector_rank_not_front: '板块内排名不靠前',
      locked_price_falling: '封板价位回落', early_limit_not_retained: '早段涨停未保持' };
    return labels[value] || '';
  }
  function auctionOnePrice(row) {
    var failed = (row.failed_evidence || []).join(' ');
    return /one_price|locked_limit|一字/.test(failed) ||
      (Number(row.final_gap || 0) >= 9.5 && Number(row.auction_volume || 0) === 0);
  }
  function auctionDepthAvailable(radar) {
    var capabilities = (radar && radar.source_capabilities) || {};
    return capabilities.unmatched_order_depth === true &&
      (radar.candidates || []).some(function (row) { return row.depth_pattern && row.depth_pattern !== 'depth_unconfirmed'; });
  }
  function auctionRank(row) {
    var grades = { S: 500, A: 400, B: 300, watch: 100, risk: 0 };
    return (grades[row.potential_grade] || 0) + (row.tradability === 'tradable' ? 80 : 0) +
      Math.min(60, Number(row.auction_max_1m_volume_ratio || 0) * 20) +
      Math.min(30, Number(row.sector_sync_count || 0) * 5);
  }
  function auctionModeMatch(row, mode) {
    if (mode === 'tradable') return row.tradability === 'tradable';
    if (mode === 'yesterday') return row.candidate_source === 'yesterday_limitup';
    if (mode === 'oneprice') return auctionOnePrice(row);
    if (mode === 'risk') return row.potential_grade === 'risk' || row.confirmation === 'invalidated';
    if (mode === 'all') return true;
    return row.potential_grade !== 'risk' && row.confirmation !== 'invalidated' &&
      row.tradability !== 'not_tradable' &&
      (['S', 'A', 'B'].indexOf(row.potential_grade) >= 0 || Number(row.auction_max_1m_volume_ratio || 0) >= 1);
  }
  function auctionVisibleRows(radar, ignoreToggles) {
    var depthAvailable = auctionDepthAvailable(radar);
    var sorted = (radar.candidates || []).filter(function (row) {
      if (!auctionModeMatch(row, auctionFilter)) return false;
      if (auctionTrajectoryFilter && row.trajectory !== auctionTrajectoryFilter) return false;
      if (depthAvailable) {
        if (auctionDepthFilter === 'confirmed' && ['depth_unconfirmed', 'withdraw_weakening', 'seller_dominant'].indexOf(row.depth_pattern) >= 0) return false;
        if (auctionDepthFilter !== 'all' && auctionDepthFilter !== 'confirmed' && row.depth_pattern !== auctionDepthFilter) return false;
        if (auctionVolumeFilter !== 'all' && row.volume_break_type !== auctionVolumeFilter) return false;
      }
      if (ignoreToggles) return true;
      if (auctionToggles.ratio && Number(row.auction_max_1m_volume_ratio || 0) < 1) return false;
      if (auctionToggles.nonOnePrice && auctionOnePrice(row)) return false;
      if (auctionToggles.resonance && Number(row.sector_sync_count || 0) < 2) return false;
      return true;
    }).sort(function (a, b) { return auctionRank(b) - auctionRank(a) ||
      Number(b.auction_max_1m_volume_ratio || 0) - Number(a.auction_max_1m_volume_ratio || 0); });
    return auctionFilter === 'focus' ? sorted.slice(0, 50) : sorted;
  }
  function auctionDepthControls(radar) {
    var depthAvailable = auctionDepthAvailable(radar);
    if (depthAvailable) {
      return '<label>委托形态<select data-auction-depth-filter><option value="confirmed"' + (auctionDepthFilter === 'confirmed' ? ' selected' : '') + '>已确认非风险</option>' +
        '<option value="withdraw_absorption"' + (auctionDepthFilter === 'withdraw_absorption' ? ' selected' : '') + '>撤单承接</option>' +
        '<option value="sealed_control"' + (auctionDepthFilter === 'sealed_control' ? ' selected' : '') + '>强封控盘</option>' +
        '<option value="withdraw_weakening"' + (auctionDepthFilter === 'withdraw_weakening' ? ' selected' : '') + '>撤单转弱</option>' +
        '<option value="depth_unconfirmed"' + (auctionDepthFilter === 'depth_unconfirmed' ? ' selected' : '') + '>深度未确认</option><option value="all"' + (auctionDepthFilter === 'all' ? ' selected' : '') + '>全部形态</option></select></label>' +
        '<label>爆量类型<select data-auction-volume-filter><option value="all">全部</option>' +
        '<option value="auction_peak_break"' + (auctionVolumeFilter === 'auction_peak_break' ? ' selected' : '') + '>竞价量超昨峰</option></select></label>';
    }
    return '<div class="auction-depth-unavailable"><b>今日未采集eltdx深度</b><span>继续显示腾讯轨迹观察；委托形态与爆量确认从下一有效采集日启用</span></div>';
  }
  function auctionFilterButton(mode, label, rows) {
    var count = rows.filter(function (row) { return auctionModeMatch(row, mode); }).length;
    return '<button data-auction-filter="' + mode + '" class="' + (auctionFilter === mode ? 'active' : '') + '">' +
      label + '<b>' + count + '</b></button>';
  }
  function auctionTrajectoryStats(stats, candidates) {
    if (!stats || !stats.length) return '';
    return '<section class="auction-trajectory-stats"><header><strong>今日轨迹观察</strong>' +
      '<span>点击筛选股票；当前封板率仅为盘中样本，不等于历史胜率</span></header><div>' +
      '<button type="button" data-auction-trajectory="" aria-pressed="' + (!auctionTrajectoryFilter) +
      '" class="' + (!auctionTrajectoryFilter ? 'active' : '') + '"><b>全部轨迹</b><span>候选 ' +
      esc((candidates || []).length) + '</span><strong>取消轨迹限制</strong></button>' + stats.map(function (row) {
        var active = auctionTrajectoryFilter === row.trajectory;
        return '<button type="button" data-auction-trajectory="' + esc(row.trajectory) + '" aria-pressed="' + active +
          '" class="' + (active ? 'active' : '') + '"><b>' + esc(auctionTrajectoryLabel(row.trajectory)) + '</b><span>样本 ' +
          esc(row.sample_count || 0) + '</span><strong>当前封板 ' + esc(row.current_limit_count || 0) + '/' +
          esc(row.sample_count || 0) + ' · ' + esc((Number(row.current_limit_rate || 0) * 100).toFixed(1)) + '%</strong></button>';
      }).join('') + '</div></section>';
  }
  function auctionRow(row) {
    var ratio = row.auction_max_1m_volume_ratio == null ? '-' : Number(row.auction_max_1m_volume_ratio).toFixed(2) + '×';
    var yesterdayRatio = row.auction_yesterday_amount_ratio == null ? '-' : Number(row.auction_yesterday_amount_ratio).toFixed(2) + '×';
    var turnover = row.auction_turnover == null ? '-' : Number(row.auction_turnover).toFixed(2) + '%';
    return '<tr data-auction-sid="' + esc(row.stock_id) + '" class="' + (auctionSelectedId === row.stock_id ? 'selected' : '') + '">' +
      '<td><strong>' + stk(row.stock_id, row.name || row.stock_id) + '</strong><small>' + esc(row.stock_id) + '</small></td>' +
      '<td class="num ' + (Number(row.final_gap || 0) >= 0 ? 'up' : 'down') + '">' + esc(fmtPct(row.final_gap)) + '</td>' +
      '<td class="num"><b>' + esc(ratio) + '</b></td><td class="num"><b>' + esc(yesterdayRatio) + '</b></td>' +
      '<td class="num">' + esc(turnover) + '</td><td class="num">' + esc(fmtMoney(row.auction_amount)) + '</td>' +
      '<td>' + esc(auctionTrajectoryLabel(row.trajectory)) + '</td><td class="num">' + esc(row.sector_sync_count || 0) + '</td>' +
      '<td>' + esc(auctionLabel(row.tradability)) + '</td><td><b class="grade grade-' + esc(row.potential_grade) + '">' +
      esc(auctionLabel(row.potential_grade)) + '</b></td></tr>';
  }
  function auctionCandidate(row) {
    if (!row) return '<div class="auction-inspector-empty">请选择左侧股票查看竞价证据</div>';
    var evidence = (row.evidence || []).map(auctionEvidenceLabel).filter(Boolean).map(function (label) { return '<span class="ok">' + esc(label) + '</span>'; }).join('');
    var failed = (row.failed_evidence || []).map(auctionEvidenceLabel).filter(Boolean).map(function (label) { return '<span class="fail">' + esc(label) + '</span>'; }).join('');
    var concepts = (row.limitup_concepts || []).map(function (label) { return '<span>' + esc(label) + '</span>'; }).join('');
    var reason = row.limitup_reason || '';
    var detail = row.limitup_detail && row.limitup_detail !== reason ? row.limitup_detail : '';
    var ratio = row.auction_max_1m_volume_ratio == null ? '-' : Number(row.auction_max_1m_volume_ratio).toFixed(2) + ' 倍';
    var yesterdayRatio = row.auction_yesterday_amount_ratio == null ? '-' : Number(row.auction_yesterday_amount_ratio).toFixed(2) + ' 倍';
    var turnover = row.auction_turnover == null ? '-' : Number(row.auction_turnover).toFixed(2) + '%';
    var gapPct = row.sector_gap_percentile == null ? '-' : (Number(row.sector_gap_percentile) * 100).toFixed(0) + '%';
    var amountPct = row.sector_auction_amount_percentile == null ? '-' : (Number(row.sector_auction_amount_percentile) * 100).toFixed(0) + '%';
    var depthStatus = (row.data_gaps || []).indexOf('auction_depth_unavailable') >= 0 ? '竞价深度暂缺' : '竞价深度可用';
    var withdraw = row.withdraw_ratio == null ? '-' : (Number(row.withdraw_ratio) * 100).toFixed(1) + '%';
    var matchedGrowth = row.matched_growth == null ? '-' : Number(row.matched_growth).toFixed(2) + '倍';
    var auctionPeak = row.auction_peak_ratio == null ? '-' : Number(row.auction_peak_ratio).toFixed(2) + '倍';
    return '<div class="auction-inspector"><header><div><h2>' + stk(row.stock_id, row.name || row.stock_id) +
      '</h2><small>' + esc(row.stock_id) + (row.candidate_source === 'yesterday_limitup' ? ' · 昨日涨停' : '') +
      '</small></div><b class="grade grade-' + esc(row.potential_grade) + '">' + esc(auctionLabel(row.potential_grade)) +
      '</b></header><div class="auction-decisions"><div><small>涨停潜力</small><strong>' + esc(auctionLabel(row.potential_grade)) +
      '</strong></div><div><small>可买性</small><strong>' + esc(auctionLabel(row.tradability)) +
      '</strong></div><div><small>开盘确认</small><strong>' + esc(auctionLabel(row.confirmation)) +
      '</strong></div></div><div class="auction-metrics"><div><small>竞价高开</small><b>' + esc(fmtPct(row.final_gap)) +
      '</b></div><div><small>竞价量比（昨日最大1分钟）</small><b>' + esc(ratio) + '</b></div><div><small>竞价成交额</small><b>' +
      esc(fmtMoney(row.auction_amount)) + '</b></div><div><small>竞昨比</small><b>' + esc(yesterdayRatio) +
      '</b></div><div><small>竞换手</small><b>' + esc(turnover) + '</b></div><div><small>题材内涨幅分位</small><b>' + esc(gapPct) +
      '</b></div><div><small>题材内竞价额分位</small><b>' + esc(amountPct) + '</b></div><div><small>板块共振</small><b>' + esc(row.sector_sync_count || 0) +
      ' 只</b></div></div><dl><dt>竞价轨迹</dt><dd>' + esc(auctionTrajectoryLabel(row.trajectory)) + '</dd><dt>深度数据</dt><dd>' +
      esc(depthStatus) + '</dd><dt>委托形态</dt><dd>' + esc(auctionDepthLabel(row.depth_pattern)) +
      '</dd><dt>爆量类型</dt><dd>' + esc(auctionVolumeBreakLabel(row.volume_break_type)) +
      '</dd><dt>封单撤减</dt><dd>' + esc(withdraw) + '</dd><dt>匹配量增长</dt><dd>' + esc(matchedGrowth) +
      '</dd><dt>买转卖次数</dt><dd>' + esc(row.negative_flip_count == null ? '-' : row.negative_flip_count) +
      '</dd><dt>竞价量/昨峰</dt><dd>' + esc(auctionPeak) +
      '</dd><dt>失效位</dt><dd>' +
      esc(row.invalidation_price == null ? '-' : row.invalidation_price) + '</dd><dt>基线日期</dt><dd>' +
      esc(row.source_date || '-') + '</dd></dl><section class="auction-reason"><h3>上涨逻辑（昨日涨停原因）</h3><strong>' +
      esc(reason || '暂无公开涨停原因') + '</strong>' + (detail ? '<p>' + esc(detail) + '</p>' : '') +
      '<div class="auction-reason-meta">' + (row.limitup_boards ? '<span>' + esc(row.limitup_boards) + '</span>' : '') + concepts +
      (row.limitup_reason_source ? '<span>来源 ' + esc(row.limitup_reason_source.toUpperCase()) + '</span>' : '') +
      '</div></section><section><h3>模型辅助依据</h3><div class="auction-evidence">' +
      (evidence || '<span>暂无可读依据</span>') + '</div></section><section><h3>风险与失效条件</h3><div class="auction-evidence">' +
      (failed || '<span>暂无</span>') + '</div></section></div>';
  }
  function selectAuctionOffset(offset) {
    var rows = auctionVisibleRows(auctionRadarPayload || {});
    if (!rows.length) return;
    var index = rows.findIndex(function (row) { return row.stock_id === auctionSelectedId; });
    index = index < 0 ? 0 : Math.max(0, Math.min(rows.length - 1, index + offset));
    auctionSelectedId = rows[index].stock_id;
    render();
  }
  function vAuctionRadar(radar) {
    radar = radar || {};
    var rows = radar.candidates || [];
    var visible = auctionVisibleRows(radar);
    if (!visible.some(function (row) { return row.stock_id === auctionSelectedId; }))
      auctionSelectedId = visible.length ? visible[0].stock_id : null;
    var selected = visible.find(function (row) { return row.stock_id === auctionSelectedId; });
    var quality = radar.baseline_quality || { status: 'missing', coverage: 0 };
    var baselineSource = radar.baseline_source || '公共分钟基线';
    var capabilities = radar.source_capabilities || {};
    var localStatus = localAuctionState.status || 'stopped';
    var localRows = (localAuctionView && localAuctionView.candidates) || [];
    var localControl = '<section class="auction-local-control"><div><strong>会员本地 eltdx 深度</strong><span>与公共雷达隔离 · 原始数据不上传</span></div>' +
      '<div class="auction-local-actions"><b>' + esc(localStatus) + '</b><button type="button" data-auction-local="probe"' + (localAuctionBusy ? ' disabled' : '') + '>测试连接</button>' +
      '<button type="button" data-auction-local="start"' + (localAuctionBusy || !auctionControlWindow() ? ' disabled' : '') + '>启动影子采集</button>' +
      '<button type="button" data-auction-local="stop"' + (localAuctionBusy ? ' disabled' : '') + '>停止</button>' +
      '<a href="http://127.0.0.1:8790/#member" target="_blank" rel="noopener">打开8790授权页</a></div>' +
      (localAuctionMessage ? '<p>' + esc(localAuctionMessage) + '</p>' : '') + '</section>' +
      '<section class="auction-local-results"><header><strong>本地深度结果</strong><span>' + localRows.length + ' 只 · 仅会员本机</span></header>' +
      (localRows.length ? '<div>' + localRows.slice(0, 20).map(function (row) { return '<span><b>' + esc(row.stock_id) + '</b> ' + esc(row.depth_pattern || '待确认') + ' · ' + esc(row.decision_state || '-') + '</span>'; }).join('') + '</div>' : '<p>尚无当日深度物化结果；非竞价时段不补造。</p>') + '</section>';
    return '<section class="auction-radar"><header class="auction-title"><div><span>早盘候选收缩器</span><h1>竞价雷达</h1>' +
      '<p>潜力、可买性、开盘确认分开判断；允许今日无候选。</p></div><i>公共雷达独立运行</i></header>' +
      localControl +
      '<div class="auction-health"><div><small>阶段</small><b>' + esc(radar.phase || '-') + '</b></div>' +
      '<div><small>行情源时间</small><b>' + esc(radar.source_ts || '-') + '</b></div>' +
      '<div><small>延迟</small><b>' + (radar.latency_ms == null ? '-' : esc(radar.latency_ms) + ' ms') + '</b></div>' +
      '<div><small>行情覆盖</small><b>' + esc(radar.quote_count || 0) + ' 只</b></div>' +
      '<div><small>昨日分钟基线</small><b>' + esc(quality.status || 'missing') + ' · ' +
      esc(Math.round(Number(quality.coverage || 0) * 1000) / 10) + '% · ' + esc(baselineSource) +
      ' · ' + esc(radar.baseline_source_date || '-') + '</b></div>' +
      '<div><small>09:15–09:25过程</small><b>' + (capabilities.process_0915_0925 ? '腾讯约3秒快照' : '不可用') +
      ' · ' + (capabilities.unmatched_order_depth ? '含盘口深度' : '不含未匹配深度') + '</b></div>' +
      '<div><small>配置版本</small><b>' + esc(radar.config_version || '-') + '</b></div></div>' +
      auctionTrajectoryStats(radar.trajectory_stats, rows) +
      '<div class="auction-filterbar">' + auctionFilterButton('focus', '重点', rows) +
      auctionFilterButton('tradable', '可交易', rows) + auctionFilterButton('yesterday', '昨日涨停', rows) +
      auctionFilterButton('oneprice', '一字板', rows) + auctionFilterButton('risk', '风险', rows) +
      auctionFilterButton('all', '全部', rows) + auctionDepthControls(radar) +
      '<div class="auction-toggles"><label><input type="checkbox" data-auction-toggle="ratio"' +
      (auctionToggles.ratio ? ' checked' : '') + '>量比≥1</label><label><input type="checkbox" data-auction-toggle="non-one-price"' +
      (auctionToggles.nonOnePrice ? ' checked' : '') + '>排除一字</label><label><input type="checkbox" data-auction-toggle="resonance"' +
      (auctionToggles.resonance ? ' checked' : '') + '>板块共振</label></div></div>' +
      '<div class="auction-terminal"><section class="auction-ranking"><header><strong>候选排行榜</strong><span>' + visible.length +
      ' 只 · ↑↓切换</span></header><div class="auction-table-wrap"><table><thead><tr><th>股票</th><th>高开</th><th>竞量比</th><th>竞昨比</th><th>竞换手</th><th>竞价额</th><th>轨迹</th><th>共振</th><th>可买性</th><th>等级</th></tr></thead><tbody>' +
      (visible.map(auctionRow).join('') || '<tr><td colspan="10" class="muted">当前筛选暂无股票；今日暂无高质量候选时不会凑数</td></tr>') +
      '</tbody></table></div></section>' + auctionCandidate(selected) + '</div></section>';
  }

  function refreshAuctionRadar() {
    if (currentView !== 'auction' || !$('dateSel') || $('dateSel').value !== SECTOR_TODAY_VALUE) return;
    var url = 'api/intraday/latest' + (auctionRadarCursor ? '?cursor=' + encodeURIComponent(auctionRadarCursor) : '');
    fetchJSON(url, 'no-store').then(function (result) {
      if (currentView !== 'auction') return;
      var publicRadar = (result.data || result).auction_radar || {};
      if (publicRadar.changed === false && auctionRadarPayload) auctionRadarPayload = Object.assign({}, auctionRadarPayload, publicRadar);
      else auctionRadarPayload = publicRadar;
      auctionRadarCursor = publicRadar.cursor || auctionRadarCursor;
      loadLocalAuctionStatus();
      render();
      if (currentView === 'auction' && isMarketSession()) auctionRadarTimer = window.setTimeout(refreshAuctionRadar, 3000);
    }).catch(function () {
      if (currentView === 'auction' && isMarketSession()) auctionRadarTimer = window.setTimeout(refreshAuctionRadar, 5000);
    });
  }
  function stopAuctionRadar() { window.clearTimeout(auctionRadarTimer); auctionRadarTimer = null; }
  function startAuctionRadar() {
    stopAuctionRadar();
    if (currentView === 'auction' && $('dateSel') && $('dateSel').value === SECTOR_TODAY_VALUE) { loadLocalAuctionStatus(); refreshAuctionRadar(); }
  }

  /* ---------- 分钟爆量：精简榜 + 三日同轴量图 + 价格/事件 ---------- */
  function minuteVolumeWatchButton(row) {
    var selected = !!row.selected;
    return '<button type="button" class="minute-watch-btn' + (selected ? ' selected' : '') +
      '" data-minute-watch="1" data-sid="' + esc(row.stock_id) + '" data-selected="' + (selected ? '1' : '0') +
      '" aria-label="' + (selected ? '移出自选' : '加入自选') + '" title="' + (selected ? '移出自选' : '加入自选') + '">' +
      (selected ? '★' : '☆') + '</button>';
  }

  function vMinuteVolume(payload) {
    payload = payload || {};
    var quality = payload.quality || {}, rows = payload.rows || [], detail = payload.detail || null;
    var controls = '<header class="minute-toolbar"><div class="minute-toolbar-title"><strong>分钟爆量雷达</strong><span class="live-dot"></span><small>' +
      esc(payload.minute || '--:--') + ' 更新</small></div><div class="minute-filter-group"><button class="active">全部</button><button>竞价</button><button>开盘30分</button><button>13点</button><button>14:30</button><button>尾盘</button></div>' +
      '<div class="minute-filter-group minute-ratio-filter">' + [['half','≥0.5×'],['near','接近昨量'],['peak','超昨峰'],['strong','≥1.5×'],['extreme','≥2.0×']].map(function (item) { return '<button data-minute-filter="' + item[0] + '" class="' + (minuteVolumeFilter === item[0] ? 'active' : '') + '">' + item[1] + '</button>'; }).join('') + '</div>' +
      '<div class="minute-quality">数据 <b>' + esc(payload.data_date || '-') + '</b> · 基线 <b>' + esc(payload.baseline_date || '-') + '</b> · 分钟覆盖 <b>' + esc(quality.coverage == null ? '-' : (Number(quality.coverage) * 100).toFixed(1) + '%') + '</b> · 有效 ' + esc(quality.valid_stocks || '-') + '只</div></header>';
    if (!payload.available) return '<section class="minute-volume-page">' + controls + '<div class="minute-unavailable"><h2>分钟爆量数据暂不可比较</h2><p>' + esc(payload.reason || '等待自然分钟物化与昨日质量基线') + '</p><small>缺失分钟不会按零成交处理，也不会产生超峰结论。</small></div></section>';
    var tableRows = minuteVolumeMode === 'sector' ? (payload.sectors || []).map(function (row, index) {
      return '<tr><td>' + (index + 1) + '</td><td class="l"><b>' + esc(row.name || row.sector_id) + '</b></td><td class="up">' + esc(row.count) + '只</td><td colspan="5" class="l muted">最近一分钟板块共振</td></tr>';
    }).join('') : rows.slice(0, 60).map(function (row, index) {
      var selected = detail && detail.stock_id === row.stock_id;
      return '<tr class="minute-stock-row' + (selected ? ' selected' : '') + '" data-minute-sid="' + esc(row.stock_id) + '"><td>' + (index + 1) + '</td><td class="l"><b>' + stk(row.stock_id, row.name) + '</b><small>' + esc((row.sectors || [])[0] || '未分类') + '</small></td><td class="' + cls(row.change_pct || 0) + '">' + esc(row.change_pct == null ? '-' : fmtPct(row.change_pct)) + '</td><td><b class="minute-ratio-badge">' + esc(Number(row.volume_ratio).toFixed(2)) + '×</b></td><td><span class="minute-type-badge">' + esc(row.price_volume_type || '量能接近') + '</span></td><td>' + esc(row.minute) + '</td><td>' + esc(row.sector_sync_count || 0) + '只</td><td>' + minuteVolumeWatchButton(row) + '</td></tr>';
    }).join('');
    var metrics = detail ? '<div class="minute-metrics"><div><small>本分钟量</small><b>' + fmtMoney(detail.minute_volume) + '手</b></div><div><small>昨日峰值</small><b>' + fmtMoney(detail.yesterday_peak_volume) + '手</b></div><div><small>超峰倍数</small><b class="up">' + Number(detail.volume_ratio).toFixed(2) + '×</b></div><div><small>分钟成交额</small><b>' + fmtMoney(detail.minute_amount) + '</b></div><div><small>成交额比</small><b>' + esc(detail.amount_ratio == null ? '-' : Number(detail.amount_ratio).toFixed(2) + '×') + '</b></div><div><small>板块共振</small><b>' + esc(detail.sector_sync_count || 0) + '只</b></div></div>' : '';
    var events = minuteVolumeLocalEvents.concat(payload.events || []).slice(0, 8).map(function (event) { return '<div><time>' + esc(String(event.ts || '').slice(-8)) + '</time><span>' + esc(event.detail || ((event.name || event.stock_id) + ' · 分钟爆量')) + '</span></div>'; }).join('');
    return '<section class="minute-volume-page">' + controls + '<div class="minute-workbench"><aside class="minute-radar"><header><div class="minute-mode-switch"><button data-minute-mode="stock" class="' + (minuteVolumeMode === 'stock' ? 'active' : '') + '">个股榜</button><button data-minute-mode="sector" class="' + (minuteVolumeMode === 'sector' ? 'active' : '') + '">板块榜</button></div><strong>实时爆量榜 · ' + rows.length + '只</strong></header><div class="minute-radar-table"><table><thead><tr><th>#</th><th class="l">股票 / 题材</th><th>涨幅</th><th>爆量</th><th>量价</th><th>时间</th><th>共振</th><th>自选</th></tr></thead><tbody>' + tableRows + '</tbody></table></div></aside><main class="minute-detail"><header class="minute-detail-head"><div><h2>' + esc(detail ? detail.name : '-') + ' <small>' + esc(detail ? code6(detail.stock_id) : '') + '</small></h2><p>' + esc(detail ? (detail.minute + ' ' + (Number(detail.volume_ratio) >= 1 ? '超昨峰 ' : '接近昨量 ') + Number(detail.volume_ratio).toFixed(2) + '倍｜' + (detail.price_volume_type || '量能接近') + '｜板块' + (detail.sector_sync_count || 0) + '只共振') : '') + '</p></div>' + (detail ? minuteVolumeWatchButton(detail) : '') + '</header>' + metrics + '<section class="minute-chart-card"><header><strong>三日分钟量 · 同轴对比</strong><span>分行　<em>叠加</em></span></header><div class="minute-volume-days"><canvas id="minuteVolumeDaysChart"></canvas><div class="minute-chart-empty">三日分钟序列不足</div></div></section><div class="minute-bottom-grid"><section class="minute-chart-card"><header><strong>价格分时（今日）</strong></header><div class="minute-price-chart"><canvas id="minutePriceChart"></canvas><div class="minute-chart-empty">价格序列不足</div></div></section><section class="minute-event-timeline"><header><strong>最近事件</strong></header>' + (events || '<p class="muted">暂无状态变化事件</p>') + '</section></div></main></div><footer>爆量仅为成交异动证据，不代表买入信号</footer></section>';
  }

  function drawMinuteCanvas(canvas, sets, colors, valueKey) {
    if (!canvas || !sets || !sets.some(function (set) { return (set.series || []).length; })) return false;
    var box = canvas.parentNode.getBoundingClientRect(), dpr = window.devicePixelRatio || 1, w = Math.max(400, box.width), h = Math.max(150, box.height);
    canvas.width = w * dpr; canvas.height = h * dpr; canvas.style.width = w + 'px'; canvas.style.height = h + 'px'; var ctx = canvas.getContext('2d'); ctx.scale(dpr, dpr); ctx.clearRect(0, 0, w, h);
    var padL = 72, rows = sets.length, rowH = (h - 28) / rows, values = []; sets.forEach(function (set) { (set.series || []).forEach(function (p) { values.push(Number(p[valueKey]) || 0); }); }); var max = Math.max.apply(null, values.concat([1])); ctx.font = '11px Microsoft YaHei';
    sets.forEach(function (set, ri) { var y0 = 5 + ri * rowH; ctx.fillStyle = colors[ri] || '#e05555'; ctx.fillText(set.date || '', 8, y0 + 18); ctx.strokeStyle = '#2a3040'; ctx.beginPath(); ctx.moveTo(padL, y0 + rowH - 5); ctx.lineTo(w - 12, y0 + rowH - 5); ctx.stroke(); var series = set.series || [], bw = Math.max(1, (w - padL - 12) / 240 - .4); series.forEach(function (p, i) { var x = padL + i * (w - padL - 12) / 240, bh = (Number(p[valueKey]) || 0) / max * (rowH - 22); ctx.fillStyle = colors[ri] || '#e05555'; ctx.fillRect(x, y0 + rowH - 5 - bh, bw, bh); }); });
    ctx.fillStyle = '#9aa0b0'; ['09:30','10:30','11:30','13:00','14:00','14:30','15:00'].forEach(function (label, i) { ctx.fillText(label, padL + i * (w - padL - 44) / 6, h - 5); }); return true;
  }
  function drawMinutePrice(canvas, series) {
    if (!canvas || !series || series.length < 2) return false; var box = canvas.parentNode.getBoundingClientRect(), dpr = window.devicePixelRatio || 1, w = Math.max(320, box.width), h = Math.max(130, box.height); canvas.width = w * dpr; canvas.height = h * dpr; canvas.style.width = w + 'px'; canvas.style.height = h + 'px'; var ctx = canvas.getContext('2d'); ctx.scale(dpr, dpr); var values = series.map(function (p) { return Number(p.price); }).filter(isFinite), min = Math.min.apply(null, values), max = Math.max.apply(null, values); if (max === min) max = min + 1; ctx.strokeStyle = '#e05555'; ctx.lineWidth = 1.5; ctx.beginPath(); series.forEach(function (p, i) { var x = 12 + i * (w - 24) / Math.max(1, series.length - 1), y = 10 + (max - Number(p.price)) / (max - min) * (h - 28); if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y); }); ctx.stroke(); return true;
  }
  function drawMinuteVolumeCharts() {
    if (!minuteVolumePayload || !minuteVolumePayload.detail) return; var vc = $('minuteVolumeDaysChart'), pc = $('minutePriceChart');
    if (drawMinuteCanvas(vc, minuteVolumePayload.detail.volume_days || [], ['#e05555','#e8a043','#6f8fc9'], 'volume')) vc.nextElementSibling.style.display = 'none';
    if (drawMinutePrice(pc, minuteVolumePayload.detail.price_series || [])) pc.nextElementSibling.style.display = 'none';
  }
  function refreshMinuteVolume() {
    if (currentView !== 'minute-volume') return; var selected = minuteVolumeSelectedId ? '&stock=' + encodeURIComponent(minuteVolumeSelectedId) : '';
    var dateArg = minuteVolumeDate ? '&date=' + encodeURIComponent(minuteVolumeDate) : '';
    fetchJSON('api/minute-volume?filter=' + encodeURIComponent(minuteVolumeFilter) + selected + dateArg, 'no-cache').then(function (result) { minuteVolumePayload = result.data || result; if (minuteVolumePayload.detail) minuteVolumeSelectedId = minuteVolumePayload.detail.stock_id; render(); if (currentView === 'minute-volume') minuteVolumeTimer = window.setTimeout(refreshMinuteVolume, 60000); }).catch(function (error) { minuteVolumePayload = { available: false, reason: '分钟爆量接口读取失败：' + error.message, quality: { status: 'fail' } }; render(); if (currentView === 'minute-volume') minuteVolumeTimer = window.setTimeout(refreshMinuteVolume, 60000); });
  }
  function stopMinuteVolume() { window.clearTimeout(minuteVolumeTimer); minuteVolumeTimer = null; }
  function startMinuteVolume() { stopMinuteVolume(); if (currentView === 'minute-volume') refreshMinuteVolume(); }

  function reasonCell(sid, entry) {
    var txt = entry && entry.reason ? entry.reason : '-';
    var n = entry ? (entry.sourceCount || 1) : 1;
    return '<button type="button" class="reason-pop" data-sid="' + esc(sid) + '" style="background:transparent;border:1px solid #30363d;color:#58a6ff;border-radius:6px;padding:2px 8px;font-size:12px;cursor:pointer">' +
      esc(txt) + '<span class="badge b-src">' + n + '源</span></button>';
  }

  /* 实时信号：涨停池 + 资金流 + 领涨原因 + 盘中事件流 */
  var EVT_META = { limitup: '🚀 涨停', broken: '💥 炸板', signal_hit: '🎯 模型命中',
                   ladder_up: '🪜 晋级', leader_change: '👑 龙头易主', sector_boom: '🔥 板块爆发',
                   volume_surge: '⚡ 量比异动', index_resonance: '📈 指数共振', theme_live: '📣 题材直播' };
  function signalInlineWatch(sid, sourceDate) {
    if (!sid) return '';
    var selected = Object.prototype.hasOwnProperty.call(HISTORY_WATCHLIST || {}, sid);
    var label = selected ? '移出自选' : '加入自选';
    return '<button type="button" class="signal-inline-watch ' + (selected ? 'selected' : '') + '" data-signal-watch="1" data-sid="' +
      esc(sid) + '" data-selected="' + (selected ? '1' : '0') + '" data-source-date="' + esc(sourceDate || currentDay || localToday()) +
      '" aria-label="' + label + '" title="' + label + '">' + (selected ? '✓' : '+') + '</button>';
  }
  function syncInlineWatchButtons() {
    document.querySelectorAll('.signal-inline-watch').forEach(function (button) {
      var selected = Object.prototype.hasOwnProperty.call(HISTORY_WATCHLIST || {}, button.dataset.sid);
      var label = selected ? '移出自选' : '加入自选';
      button.classList.toggle('selected', selected);
      button.dataset.selected = selected ? '1' : '0';
      button.textContent = selected ? '✓' : '+';
      button.setAttribute('aria-label', label); button.title = label;
    });
  }
  function loadWatchlistState() {
    if (HISTORY_WATCHLIST !== null || watchlistStateLoading) return;
    watchlistStateLoading = true;
    fetchJSON('api/pools?date=' + localToday(), 'no-store').then(function (r) {
      var doc = r.data || r;
      HISTORY_WATCHLIST = ((doc.pools || {}).watchlist || {});
      syncInlineWatchButtons();
    }).catch(function () { HISTORY_WATCHLIST = HISTORY_WATCHLIST || {}; })
      .then(function () { watchlistStateLoading = false; });
  }
  function signalStockName(stockId, name) {
    var text = String(name || '').trim(), code = code6(stockId);
    if (text && text !== stockId && text !== code) return text;
    var local = (LIBS.stocks_slim || {})[stockId] || {};
    return local.n || code;
  }
  function signalLimitupPills(view, sectorIds, archivedRows) {
    var slim = LIBS.stocks_slim || {}, ids = new Set(sectorIds || []), rows = [];
    if (Object.keys(slim).length && ids.size) {
      rows = (view.limitup || []).filter(function (stock) {
        return ((slim[stock.stock_id] || {}).s || []).some(function (sectorId) { return ids.has(sectorId); });
      }).slice(0, 5);
    }
    if (!rows.length) rows = (archivedRows || []).slice(0, 5);
    return '<div class="signal-sector-limitups"><label>已涨停</label>' + (rows.map(function (stock) {
      var name = signalStockName(stock.stock_id, stock.name);
      return '<span class="signal-limitup-pill">' + stk(stock.stock_id, name) +
        '<small>' + esc(code6(stock.stock_id)) + (stock.boards ? ' · ' + esc(stock.boards) : '') + '</small>' +
        signalInlineWatch(stock.stock_id) + '</span>';
    }).join('') || '<span class="signal-no-limitup">暂无关联涨停股</span>') + '</div>';
  }
  function selectSignalTimelineEvents(events, limit, themeReserve) {
    var ordered = (events || []).slice().sort(function (a, b) {
      return String(b.ts || '').localeCompare(String(a.ts || ''));
    });
    var themes = ordered.filter(function (event) { return event.type === 'theme_live'; }).slice(0, themeReserve);
    var others = ordered.filter(function (event) { return event.type !== 'theme_live'; }).slice(0, Math.max(0, limit - themes.length));
    return themes.concat(others).sort(function (a, b) {
      return String(b.ts || '').localeCompare(String(a.ts || ''));
    }).slice(0, limit);
  }
  function signalEventTimeline(events) {
    var groups = {};
    selectSignalTimelineEvents(events, 60, 12).forEach(function (event) {
      var raw = String(event.ts || ''), minute = raw.length >= 16 ? raw.slice(11, 16) : raw.slice(0, 5);
      minute = minute || '--:--';
      (groups[minute] = groups[minute] || []).push(event);
    });
    return Object.keys(groups).sort().reverse().map(function (minute) {
      var rows = groups[minute].map(function (e) {
        var label = EVT_META[e.type] || e.type || '动态';
        if (e.type === 'theme_live' && (e.source === 'kpl_live' || e.source === 'themeku_live')) {
          var related = (e.stocks || []).map(function (stock) {
            return '<span class="signal-live-stock ' + cls(stock.change_pct) + '">' +
              stk(stock.stock_id, signalStockName(stock.stock_id, stock.name)) +
              '<small>' + fmtPct(stock.change_pct) + '</small>' + signalInlineWatch(stock.stock_id) + '</span>';
          }).join('');
          return '<div class="signal-event-row signal-event-live"><span class="badge b-live">' + esc(label) + '</span>' +
            '<div class="signal-live-body"><div class="signal-live-meta">' +
            (e.plate ? '<strong class="signal-live-plate">' + esc(e.plate) + '</strong>' : '<strong>市场播报</strong>') +
            (e.user ? '<small>' + esc(e.user) + '</small>' : '') + '</div><p>' + esc(e.detail || '') + '</p>' +
            (e.boom_reason ? '<div class="signal-live-reason">异动逻辑：' + esc(e.boom_reason) + '</div>' : '') +
            (related ? '<div class="signal-live-stocks">' + related + '</div>' : '') + '</div></div>';
        }
        return '<div class="signal-event-row"><span class="badge ' + (e.type === 'broken' ? 'b-dn' : 'b-up') + '">' + esc(label) + '</span>' +
          (e.stock_id ? '<div class="signal-event-stock">' + stk(e.stock_id, signalStockName(e.stock_id, e.name)) +
            '<small class="evt-stock-code">' + esc(code6(e.stock_id)) + '</small>' + signalInlineWatch(e.stock_id) + '</div>' : '<div></div>') +
          '<p>' + esc(e.detail || '') + '</p></div>';
      }).join('');
      return '<section class="signal-event-time-group"><header class="signal-event-group-head"><div><time>' + esc(minute) +
        '</time><small>本分钟</small></div><span>' + groups[minute].length + ' 条动态</span></header>' + rows + '</section>';
    }).join('') || '<div class="muted" style="padding:12px">暂无事件</div>';
  }
  function signalMarketDashboard(view) {
    var indexes = view.indexes || {}, market = view.market || {};
    var indexMeta = [['SH000001','上证指数'],['SZ399001','深证成指'],['SZ399006','创业板指'],['SH000688','科创50']];
    var indexCards = indexMeta.map(function (pair) {
      var d = indexes[pair[0]] || {}, price = d.price != null ? d.price : d.close, chg = d.change_pct;
      return '<div class="market-index-card"><div class="mi-name">' + esc(d.name || pair[1]) + '</div>' +
        '<div class="mi-price ' + (chg == null ? '' : cls(chg)) + '">' + (price == null ? '--' : Number(price).toFixed(2)) + '</div>' +
        '<div class="mi-change ' + (chg == null ? '' : cls(chg)) + '">' + (chg == null ? '暂无数据' : fmtPct(chg)) + '</div></div>';
    }).join('');
    var up = Number(market.up_count || 0), down = Number(market.down_count || 0), flat = Number(market.flat_count || 0);
    var total = up + down + flat, temp = market.temperature != null ? Number(market.temperature) : (total ? up / total * 100 : 0);
    var mood = temp >= 65 ? '强势' : temp >= 50 ? '偏暖' : temp >= 35 ? '震荡' : '偏冷';
    var jValue = market.index_kdj_j == null ? null : Number(market.index_kdj_j);
    var positionSize = market.position_size == null ? null : Number(market.position_size);
    var positionCard = '<div class="market-position-card"><span>大盘 KDJ · J值</span><b>' +
      (jValue == null || !isFinite(jValue) ? '--' : jValue.toFixed(2)) + '</b><i>仓位 <strong>' +
      (positionSize == null || !isFinite(positionSize) ? '--' : positionSize.toFixed(2) + ' 成') +
      '</strong> · (100 / J值) + 1</i></div>';
    var upW = total ? up / total * 100 : 0, downW = total ? down / total * 100 : 0;
    var status = signalDateStatus(view);
    return '<section class="signal-market-dashboard"><div class="market-dashboard-head"><div><strong>大盘驾驶舱</strong><span>' + esc(status) +
      '</span></div><div class="market-dashboard-signals"><div class="market-mood ' + (temp >= 50 ? 'hot' : 'cold') +
      '"><span>市场温度</span><b class="market-temperature-value">' + temp.toFixed(1) + '°</b><strong>· ' + mood +
      '</strong></div>' + positionCard + '</div></div>' +
      '<div class="market-index-grid">' + indexCards + '</div><div class="market-breadth"><div class="breadth-main"><div class="breadth-labels">' +
      '<span class="up">上涨家数 <b>' + up + '</b></span><span>平盘 ' + flat + '</span><span class="dn">下跌家数 <b>' + down + '</b></span></div>' +
      '<div class="breadth-track"><i class="upbar" style="width:' + upW.toFixed(1) + '%"></i><i class="downbar" style="width:' + downW.toFixed(1) + '%"></i></div></div>' +
      '<div class="market-kpis"><div><span>涨停</span><b class="up">' + Number(market.limit_up || (view.limitup || []).length) + '</b></div>' +
      '<div><span>跌停</span><b class="dn">' + Number(market.limit_down || 0) + '</b></div><div><span>涨跌比</span><b>' +
      (market.up_down_ratio == null ? '--' : Number(market.up_down_ratio).toFixed(2)) + '</b></div><div><span>成交额</span><b>' +
      (market.turnover ? fmtMoney(market.turnover) : '--') + '</b></div></div></div></section>';
  }
  function signalDateStatus(view) {
    if (view.signal_ts && view.signalDataIsToday) return localToday() + ' · 实时 ' + String(view.signal_ts).slice(11, 19);
    if (view.signal_ts) return (view.data_date || view.date || currentDay) + ' · 最近收盘 ' + String(view.signal_ts).slice(11, 19);
    return (view.date || currentDay) + ' · 归档收盘';
  }
  function vSignal(view) {
    ensureSignalLibs();
    loadHistoryAssets();
    var currentWatch = HISTORY_WATCHLIST || {};
    var actionable = (view.actionable_alerts || []).map(function (e, i) {
      var why = (e.reasons || []).map(function (x) { return '<span class="badge b-src">' + esc(x) + '</span>'; }).join('');
      var confirm = e.confirm || {}, stars = Number(e.stars == null ? confirmCount(e) : e.stars);
      var confirms = '<div class="signal-confirm-grid">' + confirmTag('模型', (e.model_hit || []).length > 0) +
        confirmTag('板块', !!confirm.sector_strength) + confirmTag('资金', !!confirm.money_flow) +
        confirmTag('领涨', !!confirm.leading_reason) + '</div>';
      var selected = Object.prototype.hasOwnProperty.call(currentWatch, e.stock_id);
      var watchAttrs = selected ? ' aria-label="移出自选" title="移出自选"' : ' aria-label="加入自选" title="加入自选"';
      var watch = '<button type="button" class="signal-watch-btn ' + (selected ? 'selected' : '') + '" data-signal-watch="1" data-sid="' +
        esc(e.stock_id) + '" data-selected="' + (selected ? '1' : '0') + '" data-source-date="' +
        esc(view.data_date || view.date || currentDay) + '"' + watchAttrs + '>' + (selected ? '✓' : '+') + '</button>';
      return '<tr><td><span class="badge ' + (e.level === 'A' ? 'b-up' : 'b-src') + '">' + esc(e.level || 'B') + '</span></td>' +
        '<td class="l">' + (i + 1) + '</td><td class="l">' + stk(e.stock_id, code6(e.stock_id)) + '</td>' +
        '<td class="l">' + stk(e.stock_id, signalStockName(e.stock_id, e.name)) + '</td><td class="up">' + Number(e.quality_score || 0).toFixed(1) + '</td>' +
        '<td>' + (e.price == null ? '-' : Number(e.price).toFixed(2)) + '</td><td>' + (e.buy_lo == null ? '-' : Number(e.buy_lo).toFixed(2)) + '</td>' +
        '<td>' + (e.stop == null ? '-' : Number(e.stop).toFixed(2)) + '</td><td>' + (e.rr == null ? '-' : Number(e.rr).toFixed(1)) + '</td>' +
        '<td class="' + cls(e.change_pct) + '">' + fmtPct(e.change_pct) + '</td><td class="l">' + why +
        '</td><td class="signal-star-cell"><span class="signal-alert-stars">' + (stars ? '★'.repeat(Math.min(4, stars)) : '—') +
        '</span></td><td class="signal-confirm-cell">' + confirms + '</td><td class="signal-watch-cell">' + watch + '</td></tr>';
    }).join('');
    var actionableCard = card('🎯 可买预警', (view.signal_ts ? String(view.signal_ts).slice(11, 19) + ' · ' : '') +
      '最多12只 · 买点过滤 + RR≥3 + 板块共振优先',
      '<div class="signal-risk-note">候选排名不代表确定胜率；下单前仍需核对实时成交、止损与仓位。</div>' +
      '<div class="tblwrap"><table class="signal-alert-table"><thead><tr><th>级别</th><th>#</th><th class="l">代码</th><th class="l">名称</th><th>质量分</th><th>现价</th><th>买点</th><th>止损</th><th>RR</th><th>涨幅</th><th class="l">入选理由</th><th class="signal-star-cell">星级</th><th class="signal-confirm-cell">四维</th><th class="signal-watch-cell">自选</th></tr></thead><tbody>' +
      (actionable || '<tr><td colspan="14" class="muted">当前无同时通过模型、买点与风控门槛的候选</td></tr>') + '</tbody></table></div>', true);
    var lu = view.limitup || [];
    var rows = lu.map(function (e, i) {
      var concepts = (e.concepts || []).map(function (c) { return '<span class="badge b-src">' + esc(c) + '</span>'; }).join('');
      return '<tr><td class="l">' + (i + 1) + '</td><td class="l">' + stk(e.stock_id, code6(e.stock_id)) + '</td>' +
        '<td class="l">' + stk(e.stock_id, signalStockName(e.stock_id, e.name)) + '</td>' +
        '<td>' + (e.boards ? '<span class="badge b-boards">' + esc(e.boards) + '</span>' : '-') + '</td>' +
        '<td class="l">' + reasonCell(e.stock_id, e) + '</td><td class="l">' + concepts + '</td>' +
        '<td>' + esc(e.first_time || '-') + '</td><td>' + fmtMoney(e.seal_amount) + '</td></tr>';
    }).join('');
    var luTable = '<div class="tblwrap"><table><thead><tr><th>#</th><th class="l">代码</th><th class="l">名称</th><th>连板</th><th class="l">涨停原因</th><th class="l">题材</th><th>首次</th><th>封单</th></tr></thead><tbody>' +
      (rows || '<tr><td colspan="8" class="muted">暂无涨停数据</td></tr>') + '</tbody></table></div>';

    var mf = (view.money_flow || []).slice(0, 10).map(function (f, index) {
      return '<article class="signal-sector-row"><div class="signal-sector-rank">' + String(index + 1).padStart(2, '0') + '</div>' +
        '<div class="signal-sector-body"><div class="signal-sector-head"><strong>' + esc(f.name) + '</strong><span class="' + cls(f.main) + '">' +
        fmtMoney(f.main) + ' · ' + fmtPct(f.main_pct) + '</span></div>' + signalLimitupPills(view, [f.id], f.limitup_stocks) + '</div></article>';
    }).join('');
    var mfCard = card('💧 板块资金流 TOP10', '主力净流入 · 关联前5涨停股', mf || '<div class="muted" style="padding:12px">暂无</div>');

    var lr = (view.leading_reason || []).map(function (p) {
      return '<article class="signal-leading-row"><div class="lead-name">' + esc(p.name) + '</div><div class="lead-reason">' + esc(p.reason || '-') + '</div>' +
        signalLimitupPills(view, p.sector_ids || [], p.limitup_stocks) + '</article>';
    }).join('');
    var lrCard = card('🔥 领涨原因', (view.signal_ts ? '选股宝实时板块' : '选股宝归档板块') + ' · 关联前5涨停股', lr || '<div class="muted" style="padding:12px">暂无</div>');

    /* 盘中事件流（realtime_engine 输出，最新在前） */
    var evtCard = card('📡 盘中事件流', '按分钟播报 · 题材直播/涨停/炸板/模型命中/量比异动', signalEventTimeline(view.events || []));

    var observePool = '<details class="signal-observe"><summary>🚀 涨停观察池 · ' + lu.length +
      ' 只（已涨停，不纳入可买预警）</summary>' + luTable + '</details>';
    return signalMarketDashboard(view) + '<div class="signal-decision-grid"><div>' + actionableCard + '</div><div class="signal-event-column">' + evtCard + '</div></div>' +
      '<div class="grid2 signal-context-grid">' + mfCard + lrCard + '</div>' + observePool;
  }

  function vLeadingReason(view) {
    loadHistoryAssets();
    ensureSignalLibs();
    if (leadingMode === 'expected') return vExpectedLeaders(view);
    var slim = LIBS.stocks_slim || {};
    var rows = (view.leading_reason || []).slice().sort(function (a, b) {
      return Number(b.limit_up_count || (b.limitup_stocks || []).length) - Number(a.limit_up_count || (a.limitup_stocks || []).length) ||
        Number(!!b.reason) - Number(!!a.reason) || String(a.name || '').localeCompare(String(b.name || ''));
    });
    if (!rows.some(function (row) { return String(row.xgb_id || row.id) === String(selectedLeadingId); })) {
      selectedLeadingId = rows.length ? String(rows[0].xgb_id || rows[0].id) : null;
    }
    var active = rows.filter(function (row) { return String(row.xgb_id || row.id) === String(selectedLeadingId); })[0] || {};
    var nav = rows.map(function (row, index) {
      var id = String(row.xgb_id || row.id || ''), count = Number(row.limit_up_count || (row.limitup_stocks || []).length || 0);
      return '<button type="button" class="leading-nav-row ' + (id === String(selectedLeadingId) ? 'active' : '') +
        '" data-leading-id="' + esc(id) + '"><span><i>' + String(index + 1).padStart(2, '0') + '</i><strong>' + esc(row.name || '未命名板块') +
        '</strong></span><b>' + count + '</b><small>' + esc(row.reason || '暂无领涨原因') + '</small></button>';
    }).join('');
    var details = (active.limitup_stocks || []).slice();
    if (!details.length) details = (active.stocks || []).map(function (sid) {
      return { stock_id: sid, name: (slim[sid] || {}).n || sid };
    });
    var stockCards = details.map(function (stock, index) {
      return '<article class="leading-stock-card"><div class="leading-stock-head"><span>' + String(index + 1).padStart(2, '0') + '</span><div class="leading-stock-identity">' +
        stk(stock.stock_id, stock.name || (slim[stock.stock_id] || {}).n || stock.stock_id) + '<small>' + esc(code6(stock.stock_id)) + '</small>' +
        signalInlineWatch(stock.stock_id, view.signal_ts ? localToday() : (view.date || currentDay)) + '</div>' +
        (stock.change_pct == null ? '' : '<b class="' + cls(stock.change_pct) + '">' + fmtPct(stock.change_pct) + '</b>') + '</div>' +
        '<div class="leading-stock-meta">' + (stock.boards ? '<em>' + esc(stock.boards) + '</em>' : '') + '<p>' + esc(stock.reason || '等待个股原因') + '</p></div></article>';
    }).join('');
    var totalLimit = rows.reduce(function (sum, row) { return sum + Number(row.limit_up_count || (row.limitup_stocks || []).length || 0); }, 0);
    var reasonCount = rows.filter(function (row) { return !!String(row.reason || '').trim(); }).length;
    var status = view.signal_ts ? '领涨原因 · 实时 ' + esc(String(view.leading_reason_ts || view.signal_ts).slice(11, 19)) :
      '领涨原因 · 归档 ' + esc(view.date || currentDay);
    return leadingModeSwitch() + '<div class="leading-workbench"><aside class="leading-sidebar"><div class="leading-brand"><strong>🔥 领涨原因</strong><span>' + status +
      '</span></div><div class="leading-kpis"><div><b>' + rows.length + '</b><small>板块</small></div><div><b>' + reasonCount +
      '</b><small>有原因</small></div><div><b>' + totalLimit + '</b><small>涨停关联</small></div></div><div class="leading-nav-list">' +
      (nav || '<div class="muted" style="padding:14px">暂无领涨原因</div>') + '</div></aside><main class="leading-detail"><header class="leading-detail-head"><div><span>当前板块</span><h1>' +
      esc(active.name || '暂无数据') + '</h1></div><b>' + Number(active.limit_up_count || details.length || 0) + '<small>只涨停</small></b></header>' +
      '<section class="leading-reason-banner"><label>领涨逻辑</label><p>' + esc(active.reason || '当前板块暂无领涨原因说明') + '</p></section>' +
      '<section class="leading-stock-section"><div class="leading-section-title"><strong>关联涨停股</strong><span>来自选股宝实时涨停列表</span></div><div class="leading-stock-grid">' +
      (stockCards || '<div class="leading-empty">当前暂无关联涨停股</div>') + '</div></section></main></div>';
  }

  function leadingModeSwitch() {
    return '<div class="leading-mode-switch"><button data-leading-mode="realtime" class="' + (leadingMode === 'realtime' ? 'active' : '') +
      '">实时领涨</button><button data-leading-mode="expected" class="' + (leadingMode === 'expected' ? 'active' : '') +
      '">预期领涨候选</button></div>';
  }

  function expectedStatusLabel(status) {
    return ({ started: '已启动', warming: '开始发酵', event_only: '仅事件预期', realized: '已兑现' })[status] || '仅事件预期';
  }

  function expectedThemeKey(name) {
    return String(name || '').trim().replace(/(概念|板块)$/g, '');
  }

  function matchExpectedThemeIds(themeName) {
    var target = expectedThemeKey(themeName), themes = LIBS.themes || {}, hits = [];
    if (!target) return hits;
    Object.keys(themes).forEach(function (tid) {
      var theme = themes[tid] || {}, stockIds = {}, exactTheme = expectedThemeKey(theme.name) === target;
      if (exactTheme) (((LIBS.theme_stocks || {})[tid]) || []).forEach(function (sid) { stockIds[sid] = true; });
      (theme.tree || []).forEach(function (level1) {
        if (expectedThemeKey(level1.n1) === target) {
          (level1.st || []).forEach(function (sid) { stockIds[sid] = true; });
          (level1.l2 || []).forEach(function (level2) {
            (level2.st || []).forEach(function (sid) { stockIds[sid] = true; });
          });
        }
        (level1.l2 || []).forEach(function (level2) {
          if (expectedThemeKey(level2.n2) === target) (level2.st || []).forEach(function (sid) { stockIds[sid] = true; });
        });
      });
      if (exactTheme || Object.keys(stockIds).length) hits.push({ theme_id: String(tid), stock_ids: Object.keys(stockIds) });
    });
    return hits;
  }

  function matchExpectedSectorIds(themeName) {
    var target = expectedThemeKey(themeName), sectors = LIBS.sectors || {};
    if (!target) return [];
    return Object.keys(sectors).filter(function (sectorId) {
      return expectedThemeKey((sectors[sectorId] || {}).name) === target;
    });
  }

  function ensureExpectedRelatedQuotes(stocks, sectorIds) {
    var ids = stocks.map(function (stock) { return stock.stock_id; }).sort();
    var plates = (sectorIds || []).slice(0, 8).sort(), key = ids.join(',') + '|' + plates.join(',');
    if (!ids.length || expectedRelatedQuoteCache[key]) return;
    expectedRelatedQuoteCache[key] = { loading: true, rows: {} };
    fetchJSON('api/expected-related-quotes?ids=' + encodeURIComponent(ids.join(',')) +
      '&plates=' + encodeURIComponent(plates.join(',')), 'no-store').then(function (payload) {
      var rows = {}, data = payload.data || payload || [];
      data.forEach(function (row) { if (row.stock_id) rows[row.stock_id] = row; });
      expectedRelatedQuoteCache[key] = { loading: false, rows: rows };
      if (currentView === 'leading' && leadingMode === 'expected') render();
    }).catch(function () { expectedRelatedQuoteCache[key] = { loading: false, rows: {} }; });
  }

  function expectedRelatedQuoteMap(stocks, sectorIds) {
    var ids = stocks.map(function (stock) { return stock.stock_id; }).sort();
    var plates = (sectorIds || []).slice(0, 8).sort(), key = ids.join(',') + '|' + plates.join(',');
    return (expectedRelatedQuoteCache[key] || {}).rows || {};
  }

  function buildExpectedRelatedStocks(active, view) {
    var themeIds = matchExpectedThemeIds(active.theme_name);
    var sectorIds = matchExpectedSectorIds(active.theme_name);
    var memberIds = {}, slim = LIBS.stocks_slim || {};
    themeIds.forEach(function (hit) { (hit.stock_ids || []).forEach(function (sid) { memberIds[sid] = true; }); });
    sectorIds.forEach(function (sectorId) {
      Object.keys(slim).forEach(function (sid) {
        if ((slim[sid].s || []).map(String).indexOf(String(sectorId)) >= 0) memberIds[sid] = true;
      });
    });
    var limitups = {}, modelHits = {}, abnormal = {}, changes = {}, names = {};
    (view.limitup || []).forEach(function (row) {
      if (!row.stock_id) return;
      limitups[row.stock_id] = row; names[row.stock_id] = row.name; changes[row.stock_id] = row.change_pct;
    });
    (view.actionable_alerts || []).concat(view.model_hits || []).forEach(function (row) {
      if (!row.stock_id) return;
      modelHits[row.stock_id] = row; names[row.stock_id] = row.name; changes[row.stock_id] = row.change_pct;
    });
    (view.events || []).forEach(function (event) {
      var sid = event.stock_id;
      if (event.type === 'signal_hit' && sid) {
        modelHits[sid] = event; names[sid] = event.name; if (event.change_pct != null) changes[sid] = event.change_pct;
      } else if (sid && ['limitup', 'promotion', 'volume_spike', 'abnormal'].indexOf(event.type) >= 0) {
        abnormal[sid] = event; names[sid] = event.name; if (event.change_pct != null) changes[sid] = event.change_pct;
      }
      if (event.type === 'theme_live') (event.stocks || []).forEach(function (stock) {
        if (!stock.stock_id) return;
        abnormal[stock.stock_id] = event; names[stock.stock_id] = stock.name;
        if (stock.change_pct != null) changes[stock.stock_id] = stock.change_pct;
      });
    });
    var positiveSectorIds = {};
    (view.money_flow || []).forEach(function (flow) {
      if (Number(flow.main || 0) > 0 && flow.id) positiveSectorIds[String(flow.id)] = true;
    });
    var leaderId = (active.leader || {}).stock_id;
    var rows = Object.keys(memberIds).map(function (sid) {
      var evidence = [], score = 0, stock = slim[sid] || {};
      var hasMoney = (stock.s || []).some(function (sectorId) { return positiveSectorIds[String(sectorId)]; });
      if (limitups[sid]) { evidence.push('涨停'); score += 40; }
      if (abnormal[sid]) { evidence.push('盘中异动'); score += 25; }
      if (hasMoney) { evidence.push('所属板块资金流入'); score += 20; }
      if (modelHits[sid]) { evidence.push('模型命中'); score += 15; }
      if (sid === leaderId) { evidence.push('当前领涨'); score += 10; }
      if (!evidence.length) return null;
      return { stock_id: sid, name: names[sid] || stock.n || sid, change_pct: changes[sid],
               evidence: evidence, evidence_score: score };
    }).filter(Boolean).sort(function (a, b) {
      return b.evidence_score - a.evidence_score || Number(b.change_pct || -999) - Number(a.change_pct || -999) ||
        String(a.stock_id).localeCompare(String(b.stock_id));
    });
    var quoteMap = expectedRelatedQuoteMap(rows, sectorIds);
    rows.forEach(function (row) {
      var quote = quoteMap[row.stock_id] || {};
      ['name', 'price', 'change_pct', 'main_net', 'vol_ratio', 'turnover'].forEach(function (field) {
        if (quote[field] != null && quote[field] !== '') row[field] = quote[field];
      });
    });
    rows.sector_ids = sectorIds;
    return rows;
  }

  function expectedThemeMoneyFlow(row, view) {
    var hits = matchExpectedThemeIds(row.theme_name), slim = LIBS.stocks_slim || {}, sectorIds = {};
    hits.forEach(function (hit) {
      (hit.stock_ids || []).forEach(function (sid) {
        ((slim[sid] || {}).s || []).forEach(function (sectorId) { sectorIds[String(sectorId)] = true; });
      });
    });
    var matched = (view.money_flow || []).filter(function (flow) {
      return flow.id && sectorIds[String(flow.id)] && Number(flow.main || 0) > 0;
    });
    return {
      main: matched.reduce(function (sum, flow) { return sum + Number(flow.main || 0); }, 0),
      matched_positive_sector_count: matched.length,
      names: matched.map(function (flow) { return flow.name || flow.id; })
    };
  }

  function vExpectedLeaders(view) {
    if (!LIBS.themes || !LIBS.theme_stocks || !LIBS.stocks_slim || !LIBS.sectors) {
      if (!expectedLibLoading) {
        expectedLibLoading = true;
        Promise.all([loadLib('themes.json'), loadLib('sectors.json'), loadExpandLibs()]).then(function () {
          expectedLibLoading = false; if (currentView === 'leading' && leadingMode === 'expected') render();
        }).catch(function () { expectedLibLoading = false; });
      }
      return leadingModeSwitch() + '<div class="loading">正在加载题材成分与个股证据…</div>';
    }
    var allRows = (view.expected_leaders || []).slice();
    function dayOffset(row) {
      var target = new Date(String(row.event_date || '') + 'T00:00:00');
      var base = new Date(localToday() + 'T00:00:00');
      return isNaN(target.getTime()) ? 9999 : Math.round((target.getTime() - base.getTime()) / 86400000);
    }
    function rangeOf(row) {
      if (row.event_kind === 'catalyst_watch' || !row.event_date) return 'watch';
      var offset = dayOffset(row);
      if (row.status === 'realized' || offset < 0) return 'realized';
      if (offset === 0) return 'today';
      if (offset === 1) return 'tomorrow';
      if (offset <= 30) return 'next30';
      if (offset <= 90) return 'next90';
      if (offset <= 183) return 'next183';
      return 'outside';
    }
    var ranges = [['all', '全部'], ['today', '今天'], ['tomorrow', '明天'], ['next30', '未来30天'],
      ['next90', '31–90天'], ['next183', '91–183天'], ['watch', '催化观察'], ['realized', '已兑现']];
    var rangeNav = ranges.map(function (item) {
      var count = item[0] === 'all' ? allRows.length : allRows.filter(function (row) { return rangeOf(row) === item[0]; }).length;
      return '<button data-expected-range="' + item[0] + '" class="' + (expectedRange === item[0] ? 'active' : '') +
        '"><span>' + item[1] + '</span><b>' + count + '</b></button>';
    }).join('');
    var statusOrder = { started: 0, warming: 1, event_only: 2, realized: 3 };
    var rows = allRows.filter(function (row) {
      if (expectedRange !== 'all' && rangeOf(row) !== expectedRange) return false;
      if (expectedStatusFilter !== 'all' && row.status !== expectedStatusFilter) return false;
      if (expectedHasLeaderOnly && !(row.leader || {}).stock_id) return false;
      if (expectedHasLimitupOnly && Number(row.limit_up_count || 0) <= 0) return false;
      return true;
    }).sort(function (a, b) {
      return String(a.event_date || '').localeCompare(String(b.event_date || '')) ||
        (statusOrder[a.status] == null ? 9 : statusOrder[a.status]) -
        (statusOrder[b.status] == null ? 9 : statusOrder[b.status]) || Number(b.strength || 0) - Number(a.strength || 0);
    });
    if (!rows.some(function (row) { return row.expectation_id === selectedExpectedId; })) {
      selectedExpectedId = rows.length ? rows[0].expectation_id : null;
    }
    var active = rows.filter(function (row) { return row.expectation_id === selectedExpectedId; })[0] || {};
    var lastDate = null;
    var tableRows = rows.map(function (row) {
      var leader = row.leader || {}, dateRow = '', themeMoney = expectedThemeMoneyFlow(row, view);
      if (row.event_date !== lastDate) {
        lastDate = row.event_date;
        dateRow = '<tr class="expected-date-row"><td colspan="7">' + esc(row.event_date || '日期待确认') + '</td></tr>';
      }
      return dateRow + '<tr class="expected-data-row ' + (row.expectation_id === selectedExpectedId ? 'active' : '') +
        '" data-expected-id="' + esc(row.expectation_id) + '"><td><span class="expected-status ' + esc(row.status || 'event_only') + '">' +
        expectedStatusLabel(row.status) + '</span></td><td class="l"><strong>' + esc(row.theme_name || '未映射题材') +
        '</strong><small>' + esc(row.summary || '') + '</small></td><td class="' + cls(row.theme_change_pct) + '">' +
        (row.theme_change_pct == null ? '--' : fmtPct(row.theme_change_pct)) + '</td><td>' + (row.strength == null ? '--' : esc(row.strength)) +
        '</td><td>' + (row.limit_up_count == null ? '--' : esc(row.limit_up_count)) + '</td><td class="up" title="' +
        esc(themeMoney.names.join('、')) + '">' + (themeMoney.matched_positive_sector_count ? fmtMoney(themeMoney.main) : '--') +
        '</td><td class="l">' + (leader.stock_id ? stk(leader.stock_id, leader.name || leader.stock_id) : '<span class="muted">未关联</span>') + '</td></tr>';
    }).join('');
    var activeLeader = active.leader || {};
    var related = active.expectation_id ? buildExpectedRelatedStocks(active, view) : [];
    ensureExpectedRelatedQuotes(related, related.sector_ids || []);
    var relatedRows = related.map(function (stock, index) {
      return '<div class="expected-related-row"><div><i>' + String(index + 1).padStart(2, '0') + '</i><strong>' +
        stk(stock.stock_id, stock.name || stock.stock_id) + '</strong><small>' + esc(code6(stock.stock_id)) + '</small><p>' +
        stock.evidence.map(function (item) { return '<span class="expected-evidence-badge">' + esc(item) + '</span>'; }).join('') +
        '</p></div><b class="' + cls(stock.change_pct) + '">' + (stock.change_pct == null ? '--' : fmtPct(stock.change_pct)) + '</b>' +
        '<span>' + (stock.price == null ? '--' : Number(stock.price).toFixed(2)) + '</span><span class="' + cls(stock.main_net) + '">' +
        (stock.main_net == null ? '--' : fmtMoney(stock.main_net)) + '</span><span>' + (stock.vol_ratio == null ? '--' : Number(stock.vol_ratio).toFixed(2)) +
        '</span><span>' + (stock.turnover == null ? '--' : Number(stock.turnover).toFixed(2) + '%') + '</span>' +
        signalInlineWatch(stock.stock_id, view.signal_ts ? localToday() : (view.date || currentDay)) + '</div>';
    }).join('');
    var sourceEvidence = (active.source_evidence || []).map(function (item) {
      return '<span class="expected-evidence-badge">' + esc(item.source || '未知来源') + '</span>';
    }).join('');
    var detail = active.expectation_id ? '<div class="expected-event-card"><header><div><time>' + esc(active.event_date || '日期待确认') +
      '</time><strong>' + esc(active.theme_name || '未映射题材') + '</strong></div><span class="expected-status ' + esc(active.status || 'event_only') + '">' +
      expectedStatusLabel(active.status) + '</span></header><p>' + esc(active.summary || '暂无事件摘要') +
      '</p><p><span class="expected-evidence-badge">' + esc(active.event_kind === 'catalyst_watch' ? '催化观察' : '确定日程') +
      '</span><span class="expected-evidence-badge">证据 ' + esc(active.evidence_grade || '--') + '</span>' + sourceEvidence +
      '</p><div class="expected-evidence-grid"><div><small>题材涨幅</small><b class="' + cls(active.theme_change_pct) + '">' +
      (active.theme_change_pct == null ? '--' : fmtPct(active.theme_change_pct)) + '</b></div><div><small>题材强度</small><b>' +
      (active.strength == null ? '--' : esc(active.strength)) + '</b></div><div><small>涨停数</small><b>' +
      (active.limit_up_count == null ? '--' : esc(active.limit_up_count)) + '</b></div></div><section><label>当前领涨候选</label>' +
      (activeLeader.stock_id ? '<div class="expected-leader">' + stk(activeLeader.stock_id, activeLeader.name || activeLeader.stock_id) +
        '<small>' + esc(code6(activeLeader.stock_id)) + '</small><b class="' + cls(activeLeader.change_pct) + '">' + fmtPct(activeLeader.change_pct) + '</b>' +
        signalInlineWatch(activeLeader.stock_id, view.signal_ts ? localToday() : (view.date || currentDay)) + '</div>' :
        '<div class="expected-no-leader">题材尚未关联当前领涨股，不补造候选</div>') +
      '</section><section class="expected-related"><header><strong>相关活跃个股</strong><span>题材/板块成分 ∩ 资金/异动/涨停/模型证据</span></header><div class="expected-related-table"><header><span>个股 / 证据</span><span>涨幅</span><span>价格</span><span>主力净额</span><span>量比</span><span>换手率</span><span></span></header><div class="expected-related-list">' +
      (relatedRows || '<div class="expected-related-empty">没有同时具备题材归属和活跃证据的个股</div>') + '</div>' +
      '</div></section><footer>来源证据：' + esc(String((active.source_evidence || []).length)) + ' 条；最近确认：' + esc(active.last_confirmed_at || '--') +
      '<br>当前领涨及相关个股仅为证据候选，不构成确定性预测或买入结论</footer></div>' :
      '<div class="leading-empty">当前筛选条件下暂无候选</div>';
    var status = view.signal_ts ? '实时 ' + esc(String(view.expected_leaders_ts || view.signal_ts).slice(11, 19)) : '归档 ' + esc(view.date || currentDay);
    return leadingModeSwitch() + '<div class="expected-leaders"><div class="expected-heading"><div><h1>📅 预期领涨候选</h1><p>未来事件 × 当前题材强度 × 当前领涨股，按证据展示，不输出预测概率</p></div><span>' +
      status + ' · ' + rows.length + '/' + allRows.length + ' 条</span></div><div class="expected-filterbar"><div>' +
      [['all','全部'],['started','已启动'],['warming','发酵中'],['event_only','仅事件']].map(function (item) {
        return '<button data-expected-status="' + item[0] + '" class="' + (expectedStatusFilter === item[0] ? 'active' : '') + '">' + item[1] + '</button>';
      }).join('') + '</div><label><input type="checkbox" data-expected-toggle="leader" ' + (expectedHasLeaderOnly ? 'checked' : '') + '>仅看有领涨股</label>' +
      '<label><input type="checkbox" data-expected-toggle="limitup" ' + (expectedHasLimitupOnly ? 'checked' : '') + '>仅看有涨停</label></div>' +
      '<div class="expected-workbench"><aside class="expected-range-nav">' + rangeNav + '</aside><section class="expected-table-pane"><div class="tblwrap"><table class="expected-table"><thead><tr><th>状态</th><th class="l">题材/事件</th><th>涨幅</th><th>强度</th><th>涨停</th><th>板块资金流入</th><th class="l">当前领涨候选</th></tr></thead><tbody>' +
      (tableRows || '<tr><td colspan="7" class="muted">当前筛选条件下暂无候选</td></tr>') + '</tbody></table></div></section><aside class="expected-detail-pane">' + detail + '</aside></div></div>';
  }

  function stopSignalRealtime() {
    signalRealtimeMode = false;
    window.clearTimeout(signalRealtimeTimer); signalRealtimeTimer = null; signalRealtimePayload = null;
  }
  function refreshSignalRealtime() {
    if ((currentView !== 'signal' && currentView !== 'leading' && currentView !== 'history') || !signalRealtimeMode) return;
    fetchJSON('api/intraday/latest', 'no-store').then(function (r) {
      if ((currentView !== 'signal' && currentView !== 'leading' && currentView !== 'history') || !signalRealtimeMode) return;
      signalRealtimePayload = r.data || r;
      loadMemberLocalRealtime().then(function (local) {
        signalRealtimePayload = mergeMemberLocalRealtime(signalRealtimePayload, local);
        render();
      });
      var phase = signalRealtimePayload.phase || '';
      signalRealtimeTimer = window.setTimeout(refreshSignalRealtime, phase === 'auction' || phase === 'open' ? 3000 : 30000);
    }).catch(function () { signalRealtimeTimer = window.setTimeout(refreshSignalRealtime, 15000); });
  }
  function startSignalRealtime() {
    signalRealtimeMode = true;
    if ($('dateSel')) $('dateSel').value = SECTOR_TODAY_VALUE;
    window.clearTimeout(signalRealtimeTimer); refreshSignalRealtime();
  }

  /* 题材库：参考金十题材库的左列表 / 中详情 / 右直播三栏布局。 */
  function vTheme(view) {
    loadWatchlistState();
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
      '<aside class="theme-live"><div class="live-panel-title"><span class="live-dot"></span><div><strong>实时直播播报</strong><small>盘中事件流 · 按分钟播报</small></div></div>' +
      '<div id="themeLiveList" class="live-feed"></div></aside></div>';
  }

  function matchThemeSearch(tid, theme, keyword) {
    var query = String(keyword || '').trim().toLowerCase();
    var result = { matched: !query, hints: [] };
    if (!query) return result;
    function includes(value) { return String(value || '').toLowerCase().indexOf(query) >= 0; }
    function addHint(kind, label) {
      var text = kind + '：' + label;
      if (result.hints.indexOf(text) < 0) result.hints.push(text);
      result.matched = true;
    }
    if (includes(theme.name) || includes(tid)) result.matched = true;
    (theme.tree || []).forEach(function (level1) {
      if (includes(level1.n1)) addHint('细分', level1.n1);
      (level1.l2 || []).forEach(function (level2) {
        if (includes(level2.n2)) addHint('细分', (level1.n1 ? level1.n1 + ' / ' : '') + level2.n2);
      });
    });
    (LIBS.theme_stocks[tid] || []).forEach(function (sid) {
      var stock = LIBS.stocks_slim[sid] || {};
      var code = stock.code || code6(sid);
      if (includes(stock.n) || includes(stock.name) || includes(code) || includes(sid)) {
        addHint('个股', (stock.n || stock.name || sid) + ' ' + code);
      }
    });
    return result;
  }

  function renderThemeWorkbench(view) {
    var kw = ($('themeSearch') ? $('themeSearch').value : '').trim();
    var themes = LIBS.themes || {};
    var searchMatches = {};
    var ids = Object.keys(themes).filter(function (tid) {
      searchMatches[tid] = matchThemeSearch(tid, themes[tid], kw);
      return searchMatches[tid].matched;
    });
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
        '<span class="theme-stock-count">' + (t.stock_count || 0) + '只</span></div>' +
        (kw && searchMatches[tid].hints.length ? '<div class="theme-search-hit">' + esc(searchMatches[tid].hints.slice(0, 3).join(' · ')) +
          (searchMatches[tid].hints.length > 3 ? ' 等' + searchMatches[tid].hints.length + '项' : '') + '</div>' : '') + children + '</div>';
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
    $('themeLiveList').innerHTML = signalEventTimeline(view.events || []);
  }

  function localToday() {
    var d = new Date(), y = d.getFullYear(), m = String(d.getMonth() + 1).padStart(2, '0'), day = String(d.getDate()).padStart(2, '0');
    return y + '-' + m + '-' + day;
  }

  function isMarketSession() {
    var now = new Date(), day = now.getDay(), minutes = now.getHours() * 60 + now.getMinutes();
    // 收盘快照在 15:30 才归档；15:00~15:30 仍展示最后一帧实时数据，避免提前回退旧归档日。
    return day >= 1 && day <= 5 && minutes >= 9 * 60 + 15 && minutes < 15 * 60 + 30;
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
      return loadMemberLocalRealtime().then(function (local) {
        payload = mergeMemberLocalRealtime(payload, local);
        themeRealtimeView = buildRealtimeThemeView(payload);
        var detailMap = {};
        (payload.limitup || []).forEach(function (entry) { detailMap[entry.stock_id] = entry; });
        DETAIL_CACHE[payload.data_date || localToday()] = { limitup: detailMap };
        renderThemeWorkbench(themeRealtimeView);
        scheduleThemeRealtime(realtimeDelay(payload.phase));
      });
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
  function cloneSectorView(view) {
    return Object.assign({}, view || {}, {
      sectors: ((view || {}).sectors || []).map(function (sector) {
        return Object.assign({}, sector, {
          sub_sectors: (sector.sub_sectors || []).map(function (sub) { return Object.assign({}, sub); })
        });
      })
    });
  }

  function activeSectorView() {
    return sectorRealtime && sectorRealtimeView ? sectorRealtimeView : (CACHE[currentDay] || {});
  }

  function vSector(view) {
    loadWatchlistState();
    sectorRealtime = !sectorForceHistory && (isMarketSession() || sectorForceRealtime);
    if (sectorRealtime) {
      if (!sectorRealtimeView || sectorRealtimeBaseDay !== currentDay) {
        sectorRealtimeView = cloneSectorView(view);
        sectorRealtimeBaseDay = currentDay;
      }
      view = sectorRealtimeView;
    } else {
      sectorRealtimeView = null; sectorRealtimeBaseDay = '';
    }
    if (sectorRealtime && $('dateSel')) $('dateSel').value = SECTOR_TODAY_VALUE;
    window.setTimeout(function () {
      if (currentView !== 'sector') return;
      renderSectorWorkbench(view);
      if (sectorRealtime) { refreshSectorBreadth(view); refreshSectorRealtime(); }
    }, 0);
    var trend = (SECTOR_INDEX.sector_trend || []).map(function (day) {
      return '<div class="sector-trend-day"><b>' + esc(day.date.slice(5)) + '</b>' + (day.top || []).map(function (s) {
        var selected = !sectorRealtime && day.date === currentDay && s.id === selectedSectorId;
        var linked = s.id === selectedSectorId;
        return '<button type="button" class="sector-trend-cell' + (linked ? ' sector-linked' : '') + (selected ? ' selected' : '') + '" data-trend-date="' + esc(day.date) +
          '" data-trend-sid="' + esc(s.id) + '" title="查看 ' + esc(day.date) + ' · ' + esc(s.name) + '（强度 ' + esc(s.strength) + '，涨停 ' +
          (s.limit_up_count || 0) + '）">' + esc(s.rank) + '. ' + esc(s.name) + ' <i>涨停' + (s.limit_up_count || 0) + '</i></button>';
      }).join('') + '</div>';
    }).join('');
    var sectorDate = sectorRealtime ? localToday() + ' · 实时' : currentDay + ' · 归档';
    return '<div class="sector-shell"><details class="sector-trend"' + (sectorTrendExpanded ? ' open' : '') + '><summary>板块强度排序变化 <small>近 10 个交易日</small></summary><div class="sector-trend-grid">' + trend + '</div></details>' +
      '<div class="sector-workbench"><aside class="sector-sidebar"><div class="sector-side-head"><div><span>板块强度排行</span><small>' + esc(sectorDate) + '</small></div>' +
      '<div class="sector-date"><button type="button" data-sector-day="older" title="上一历史交易日">◀</button><span>' + esc(sectorDate) + '</span><button type="button" data-sector-day="newer" title="下一交易日 / 当天实时">▶</button></div></div>' +
      '<div class="panel-search"><input id="sectorSearch" placeholder="搜索板块…"></div><div id="sectorList" class="sector-rank-list"></div></aside>' +
      '<section class="sector-detail"><div id="sectorDetail"></div></section></div></div>';
  }

  function renderSectorWorkbench(view) {
    renderSectorRankList(view);
    renderSectorDetail(view, selectedSectorId);
  }

  function renderSectorRankList(view) {
    if (!$('sectorList')) return;
    var kw = ($('sectorSearch') ? $('sectorSearch').value : '').trim();
    var sectors = (view.sectors || []).filter(function (s) { return !kw || (s.name || '').indexOf(kw) >= 0; });
    if (focusTag && focusTag.type === 'sector') selectedSectorId = focusTag.id;
    if (!selectedSectorId || !(view.sectors || []).some(function (s) { return s.id === selectedSectorId; })) selectedSectorId = sectors[0] && sectors[0].id;
    $('sectorList').innerHTML = sectors.map(function (s, i) {
      var hotSubs = (s.sub_sectors || []).filter(function (sub) { return Number(sub.strength || 0) > 1900; });
      var subSummary = hotSubs.length ? '<div class="sector-rank-sub">' + hotSubs.map(function (sub) {
        return '<span title="子板块强度 ' + esc(sub.strength) + '">' + esc(sub.name) + ' <b>' + esc(sub.strength) + '</b></span>';
      }).join('') + '</div>' : '';
      return '<div class="sector-rank-row' + (s.id === selectedSectorId ? ' active' : '') + '" data-sid="' + esc(s.id) + '">' +
        '<span class="rank' + (i < 3 ? ' top' : '') + '">' + (i + 1) + '</span><div class="sector-rank-info"><strong>' + esc(s.name) + '</strong>' +
        '<small><em>涨停 ' + (s.limit_up_count || 0) + '</em><em>&gt;6% ' + (s.up6_count || 0) + '</em> · ' + fmtMoney(s.mainNet) + ' · ' + (s.stock_count || 0) + '只</small>' + subSummary + '</div>' +
        '<div class="sector-rank-num"><b class="' + (Number(s.strength || 0) >= 4000 ? 'sector-strength-hot' : '') + '">' + esc(s.strength || 0) + '</b><span class="' + cls(s.change) + '">' + fmtPct(s.change) + '</span></div></div>';
    }).join('') || '<div class="muted" style="padding:14px">无匹配板块</div>';
  }

  function mergeSectorRealtimeRows(previousRows, incomingRows, breadthRows) {
    var previous = {}, breadth = {};
    (previousRows || []).forEach(function (row) { previous[row.id] = row; });
    (breadthRows || []).forEach(function (row) { breadth[row.sector_id] = row; });
    return (incomingRows || []).map(function (row) {
      var old = previous[row.id] || {}, live = breadth[row.id] || {};
      return Object.assign({}, old, row, {
        limit_up_count: live.limitup != null ? live.limitup : Number(old.limit_up_count || 0),
        up6_count: live.up6 != null ? live.up6 : Number(old.up6_count || 0),
        stock_count: live.count != null ? live.count : Number(old.stock_count || 0)
      });
    });
  }

  function refreshSectorBreadth(view) {
    var now = Date.now();
    if (!sectorRealtime || sectorBreadthLoading || now - sectorBreadthLoadedAt < 4000) return;
    sectorBreadthLoading = true;
    fetchJSON('api/intraday/latest', 'no-store').then(function (r) {
      var data = r.data || r;
      if (!sectorRealtime || currentView !== 'sector' || !data.available || data.data_date !== localToday()) return;
      sectorBreadthRows = data.sector_strength || [];
      view.sectors = mergeSectorRealtimeRows(view.sectors || [], view.sectors || [], sectorBreadthRows);
      renderSectorRankList(view);
      sectorBreadthLoadedAt = Date.now();
    }).catch(function () {}).then(function () { sectorBreadthLoading = false; });
  }

  function renderSectorDetail(view, sid) {
    if (!sid || !$('sectorDetail')) return;
    var s = (view.sectors || []).filter(function (x) { return x.id === sid; })[0] || {};
    var subs = s.sub_sectors || [];
    var subHtml = '<button class="sector-sub-chip' + (!selectedSubSectorId ? ' active' : '') + '" data-subsid="">全部</button>' + subs.map(function (sub) {
      return '<button class="sector-sub-chip' + (Number(sub.strength || 0) > 1900 ? ' sector-sub-hot' : '') +
        (selectedSubSectorId === sub.id ? ' active' : '') + '" data-subsid="' + esc(sub.id) + '">' + esc(sub.name) + ' ' + esc(sub.strength) + '</button>';
    }).join('');
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
      cell.classList.toggle('sector-linked', cell.dataset.trendSid === selectedSectorId);
      cell.classList.toggle('selected', !sectorRealtime && cell.dataset.trendDate === currentDay && cell.dataset.trendSid === selectedSectorId);
    });
  }

  function loadSectorStocks(view, sid) {
    var date = view.date || currentDay;
    var done = function (detail) {
      var reasons = {}; (view.limitup || []).forEach(function (x) { reasons[x.stock_id] = x.reason || ''; });
      var rows = ((detail.plates || {})[selectedSubSectorId || sid] || []).map(function (x) { var r = Object.assign({}, x); r.reason = reasons[r.stock_id] || ''; return r; });
      renderSectorStockTable(rows);
      var archivedIntraday = (detail.intraday || {})[selectedSubSectorId || sid] || (detail.intraday || {})[sid] || null;
      drawSectorIntraday(archivedIntraday);
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
      return '<tr class="sector-stock-row ' + ((Number(r.change) || 0) >= 9.8 ? 'row-zt' : '') + '" data-tdx-sid="' + esc(r.stock_id) + '"><td class="l">' + esc(r.code) + '</td><td class="l"><span class="sector-stock-identity">' + esc(r.name) + signalInlineWatch(r.stock_id, sectorRealtime ? localToday() : currentDay) + '</span></td><td>' + dragonPositionHtml(r.position) + '</td><td class="l sector-reason-col">' + reason + '</td><td>' + esc(r.boards || '-') + '</td><td class="' + cls(r.change) + '">' + fmtPct(r.change) + '</td><td>' + esc(r.price || '-') + '</td><td>' + esc(r.turnover || '-') + '%</td><td>' + fmtMoney(r.amount) + '</td><td class="' + cls(r.main_net) + '">' + fmtMoney(r.main_net) + '</td><td>' + esc(r.vol_ratio || '-') + '</td><td>' + esc(r.net_flow_ratio || '-') + '</td><td>' + esc(r.pe || '-') + '</td><td>' + fmtMoney(r.circ_market_cap) + '</td></tr>';
    }).join('');
    var heads = [['code','代码','l'],['name','名称','l'],['position_rank','地位',''],['reason','涨停原因','l sector-reason-col'],['boards','连板',''],['change','涨跌幅',''],['price','现价',''],['turnover','换手率',''],['amount','成交额',''],['main_net','主力净额',''],['vol_ratio','量比',''],['net_flow_ratio','净流占比',''],['pe','市盈率',''],['circ_market_cap','流通市值','']];
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
  function dragonPositionHtml(value) {
    var rank = chinesePositionRank(value), label = formatDragonPosition(value);
    var classes = { 1: 'dragon-position dragon-1', 2: 'dragon-position dragon-2', 3: 'dragon-position dragon-3' };
    return rank === 9999 ? '-' : '<span class="' + (classes[rank] || 'dragon-position') + '">' + esc(label) + '</span>';
  }
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
    if (!sectorRealtime) return;
    refreshSectorBreadth(activeSectorView());
    var bootstrap = !selectedSectorId;
    var targetPlate = selectedSectorId || '', targetSub = selectedSubSectorId || '';
    var requestKey = targetPlate + ':' + targetSub;
    if (sectorRealtimePendingKey === requestKey) return;
    sectorRealtimePendingKey = requestKey;
    var requestSeq = ++sectorRealtimeRequestSeq;
    var url = 'api/sectors/realtime' + (targetPlate ? '?plate=' + encodeURIComponent(targetPlate) : '') + (targetSub ? '&sub=' + encodeURIComponent(targetSub) : '');
    fetchJSON(url, 'no-store').then(function (r) {
      var data = r.data || r;
      if (!data.available || requestSeq !== sectorRealtimeRequestSeq || currentView !== 'sector') return;
      var view = activeSectorView();
      if (bootstrap) {
        view.sectors = mergeSectorRealtimeRows(view.sectors || [], data.sectors || [], sectorBreadthRows);
        if (!view.sectors.length) return;
        selectedSectorId = data.sectors[0].id;
        renderSectorWorkbench(view);
        return;
      }
      if (
          targetPlate !== selectedSectorId || targetSub !== (selectedSubSectorId || '')) return;
      view.sectors = mergeSectorRealtimeRows(view.sectors || [], data.sectors || view.sectors || [], sectorBreadthRows);
      var current = (view.sectors || []).filter(function (s) { return s.id === targetPlate; })[0];
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
      renderSectorRankList(view);
      renderSectorDetail(view, targetPlate);
      renderSectorStockTable(data.stocks || []);
      drawSectorIntraday(data.intraday || null);
      var stamp = $('sectorLiveTime');
      if (stamp) stamp.textContent = ' KPL ' + (data.max_time || '--:--').replace(/^(\d{2})(\d{2})$/, '$1:$2');
    }).catch(function () {}).then(function () {
      if (requestSeq !== sectorRealtimeRequestSeq) return;
      sectorRealtimePendingKey = '';
      if (sectorRealtime && currentView === 'sector') sectorRealtimeTimer = window.setTimeout(refreshSectorRealtime, bootstrap ? 0 : 5000);
    });
  }

  function navigateSectorDay(direction) {
    var dates = DAYS.map(function (d) { return d.date; });
    if (!dates.length) return;
    if (sectorRealtime) {
      if (direction === 'older') {
        sectorForceHistory = true; sectorForceRealtime = false; sectorRealtime = false;
        sectorRealtimeView = null; sectorRealtimeBaseDay = '';
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

  function selectSectorTrend(date, sid) {
    if (!date || !sid || !CACHE[currentDay]) return;
    sectorForceHistory = true; sectorForceRealtime = false; sectorRealtime = false;
    sectorRealtimeView = null; sectorRealtimeBaseDay = '';
    window.clearTimeout(sectorRealtimeTimer);
    selectedSectorId = sid; selectedSubSectorId = null;
    if ($('dateSel')) $('dateSel').value = date;
    loadDay(date);
  }

  /* 策略模型：命中 + 买点 */
  /* ---------- 策略模型页（V0.3+：在线配置 + 全量命中池） ---------- */
  var MODEL_CN = { reversal: '①低吸反转', breakout: '②横盘突破', weekly: '③周线堆量', dwm: '④日周月堆量主升共振',
    lowstart: '⑤低位启动', volbrk: '⑥突破放量', perfect_ten: '⑦十全十美', golden_vol: '⑧金量买入',
    hub_breakout: '⑨中枢突破', div_reversal: '⑩背驰反转', ma_momentum: '⑪多头排列', bottom_rev: '⑫底部起涨',
    multi_factor: '⑬多因共振', sub_low: '⑭低吸型', sub_trend_vol: '⑮趋势放量型', sub_breakout: '⑯突破型', sub_main: '⑰主升型',
    weekly_platform_breakout: '⑱周线放量平台突破', weekly_pullback: '⑲周线回踩企稳',
    weekly_macd_second_cross: '⑳周线MACD二次金叉', weekly_ma_bull: '㉑周线均线多头',
    weekly_double_volume: '㉒周线倍量阳线', sandwich: '㉓夹心板' };
  var STRAT_ALL = null;
  var stratFilter = { kind: '', id: '' };
  var stratManualArchive = false;
  function isWeeklyModel(modelId) { return String(modelId || '').indexOf('weekly_') === 0; }
  function rowInModelPool(row, poolId) {
    return Object.keys((row && row.models) || {}).some(function (modelId) {
      return poolId === 'weekly' ? isWeeklyModel(modelId) : !isWeeklyModel(modelId);
    });
  }
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
    // per-date 文件优先（2026-08-19 起按日留存），失败回退最新指针文件
    return fetchJSON('data/web/strategy_all_' + currentDay + '.json').then(function (d) {
      if (d && d.date === currentDay) STRAT_ALL = d;
      return STRAT_ALL;
    }).catch(function () {
      return fetchJSON('data/web/strategy_all.json').then(function (d) {
        if (d && d.date === currentDay) STRAT_ALL = d;
        return STRAT_ALL;
      }).catch(function () { STRAT_ALL = null; return null; });
    });
  }
  function conceptChips(sid, row) {
    var slim = LIBS.stocks_slim || {}, sectors = LIBS.sectors || {}, themes = LIBS.themes || {};
    var rec = slim[sid] || { s: [], t: [] };
    var sIds = (row && row.sectors && row.sectors.length ? row.sectors : rec.s) || [];
    var tIds = (row && row.themes && row.themes.length ? row.themes : rec.t) || [];
    var chips = sIds.slice(0, 3).map(function (s) {
      return '<span class="tag-chip sec" data-go="sector" data-id="' + esc(s) + '">' + esc((sectors[s] || {}).name || s) + '</span>';
    }).concat(tIds.slice(0, 3).map(function (t) {
      return '<span class="tag-chip thm" data-go="theme" data-id="' + esc(t) + '">' + esc((themes[t] || {}).name || t) + '</span>';
    })).join('');
    return chips || '<span class="muted">-</span>';
  }
  function modelBadges(models) {
    var keys = Object.keys(models || {});
    return keys.map(function (m) { return '<span class="badge b-model">' + esc(MODEL_CN[m] || m) + '</span>'; }).join('') || '-';
  }
  function reasonRowCell(r) {
    if (!r.reason) return '<span class="muted">-</span>';
    var n = r.reason_sources || 1;
    var hist = r.reason_is_history && r.reason_date
      ? '<span class="badge b-hist" title="沿用 ' + esc(r.reason_date) + ' 涨停原因">沿用' + esc(r.reason_date.slice(5)) + '</span>' : '';
    return '<button type="button" class="reason-pop" data-sid="' + esc(r.stock_id) + '" data-rdate="' + esc(r.reason_date || '') + '" style="background:transparent;border:1px solid #30363d;color:#58a6ff;border-radius:6px;padding:2px 8px;font-size:12px;cursor:pointer">' +
      esc(r.reason) + '<span class="badge b-src">' + n + '源</span>' + hist + '</button>';
  }
  function strategyRowHtml(r, names) {
    var chgTd = r.chg == null
      ? '<td class="muted">-</td>'
      : '<td class="' + (Number(r.chg) >= 0 ? 'up' : 'dn') + '">' + fmtPct(r.chg) + '</td>';
    var nm = (names[r.stock_id] || {}).n || r.name || code6(r.stock_id);
    var bpMark = r.bp_pass === false
      ? ' <span class="badge b-hist" title="未过买点过滤（rr<3 或止损距离>4%），价位仅参考">参考</span>' : '';
    var stopTip = r.stop != null ? ' title="止损价 ' + Number(r.stop).toFixed(2) + '"' : '';
    return '<tr data-sid="' + esc(r.stock_id) + '"><td class="up">' + (r.score == null ? '-' : Number(r.score).toFixed(1)) + '</td>' +
      '<td class="l">' + code6(r.stock_id) + '</td>' +
      '<td class="l"><span class="strategy-stock-identity">' + stk(r.stock_id, nm) + bpMark +
      signalInlineWatch(r.stock_id, stratRealtime ? localToday() : currentDay) + '</span></td>' +
      '<td>' + (r.price == null ? '-' : Number(r.price).toFixed(2)) + '</td>' +
      '<td>' + (r.buy_lo == null ? '-' : Number(r.buy_lo).toFixed(2)) + '</td>' +
      '<td' + stopTip + '>' + (r.stop == null ? '-' : Number(r.stop).toFixed(2)) + '</td>' +
      '<td>' + (r.stop_pct == null ? '-' : Number(r.stop_pct).toFixed(2) + '%') + '</td>' +
      '<td>' + (r.rr == null ? '-' : Number(r.rr).toFixed(1)) + '</td>' +
      chgTd +
      '<td class="l">' + reasonRowCell(r) + '</td>' +
      '<td class="l">' + modelBadges(r.models) + '</td>' +
      '<td class="l">' + conceptChips(r.stock_id, r) + '</td></tr>';
  }
  function stratTable(rows, names) {
    var thead = '<thead><tr><th>评分</th><th class="l">代码</th><th class="l">名称</th><th>现价</th>' +
      '<th>参考买入区</th><th>止损位</th><th>止损%</th><th>风险回报比</th><th>今日</th>' +
      '<th class="l">涨停原因</th><th class="l">命中模型</th><th class="l">归属概念/板块</th></tr></thead>';
    return '<div class="tblwrap"><table>' + thead + '<tbody>' +
      (rows.map(function (r) { return strategyRowHtml(r, names); }).join('') ||
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
  function rowGroupIds(r, kind) {
    var ids = kind === 'concept' ? r.themes : r.sectors;
    if (ids && ids.length) return ids;
    var rec = (LIBS.stocks_slim || {})[r.stock_id] || {};
    return (kind === 'concept' ? rec.t : rec.s) || [];
  }
  function applyStratFilter(rows) {
    var f = stratFilter;
    if (!f.kind) return rows;
    if (f.kind === 'time') return rows.filter(function (r) { return timeBucket(r.entry_time) === f.id; });
    if (f.kind === 'pool') return rows.filter(function (r) { return rowInModelPool(r, f.id); });
    if (f.kind === 'model') return rows.filter(function (r) { return (r.models || {})[f.id] != null; });
    if (f.kind === 'concept') return rows.filter(function (r) { return rowGroupIds(r, 'concept').indexOf(f.id) >= 0; });
    if (f.kind === 'sector') return rows.filter(function (r) { return rowGroupIds(r, 'sector').indexOf(f.id) >= 0; });
    return rows;
  }
  /* 左栏四区：时间（按当天时间）/ 模型（按胜率）/ 概念（按涨停数）/ 板块（按强度值） */
  function stratGroups(rows, view) {
    var luIds = stratRealtime && STRAT_RT
      ? new Set(STRAT_RT.limitupIds || [])
      : new Set(((view && view.limitup) || []).map(function (e) { return e.stock_id; }));
    var secInfo = {};
    ((view && view.sectors) || []).forEach(function (s) { secInfo[s.id] = s; });
    var buckets = ['09:30 前（竞价）', '09:30-10:30', '10:30-11:30', '13:00-14:00', '14:00-15:00', '盘后'];
    var timeCnt = {};
    rows.forEach(function (r) { var b = timeBucket(r.entry_time); timeCnt[b] = (timeCnt[b] || 0) + 1; });
    var time = buckets.filter(function (b) { return timeCnt[b]; })
      .map(function (b) { return { id: b, name: b, metric: timeCnt[b] + ' 只' }; });
    var mStat = {};
    rows.forEach(function (r) {
      Object.keys(r.models || {}).forEach(function (m) {
        var s = mStat[m] = mStat[m] || { cnt: 0, win: 0, scored: 0 };
        s.cnt++;
        if (r.chg != null) { s.scored++; if (Number(r.chg) > 0) s.win++; }
      });
    });
    // 两个模型池始终列出完整 17/5 模型；当日零命中也显示 0 只，避免误认为模型未接入。
    Object.keys(MODEL_CN).forEach(function (m) {
      mStat[m] = mStat[m] || { cnt: 0, win: 0, scored: 0 };
    });
    var model = Object.keys(mStat).map(function (m) {
      var s = mStat[m];
      var rate = s.scored ? Math.round(s.win / s.scored * 100) : 0;
      return { id: m, name: MODEL_CN[m] || m, rate: rate, cnt: s.cnt, metric: '胜率 ' + rate + '% · ' + s.cnt + ' 只' };
    }).sort(function (a, b) { return b.rate - a.rate || b.cnt - a.cnt; });
    var cStat = {};
    rows.forEach(function (r) {
      rowGroupIds(r, 'concept').forEach(function (g) {
        var s = cStat[g] = cStat[g] || { cnt: 0, lu: 0 };
        s.cnt++;
        if (luIds.has(r.stock_id)) s.lu++;
      });
    });
    var concept = Object.keys(cStat).map(function (g) {
      var s = cStat[g];
      return { id: g, name: ((LIBS.themes || {})[g] || {}).name || g, lu: s.lu, cnt: s.cnt,
               metric: '涨停 ' + s.lu + ' · ' + s.cnt + ' 只' };
    }).sort(function (a, b) { return b.lu - a.lu || b.cnt - a.cnt; });
    var sStat = {};
    rows.forEach(function (r) {
      rowGroupIds(r, 'sector').forEach(function (g) { sStat[g] = (sStat[g] || 0) + 1; });
    });
    var secInfo = {};
    if (stratRealtime && STRAT_RT && STRAT_RT.sectorsStrength) {
      secInfo = STRAT_RT.sectorsStrength;  // 当天实时强度（全市场聚合代理）
    } else {
      ((view && view.sectors) || []).forEach(function (s) { secInfo[s.id] = { strength: s.strength || 0 }; });
    }
    var sector = Object.keys(sStat).map(function (g) {
      var st = (secInfo[g] || {}).strength || 0;
      return { id: g, name: ((LIBS.sectors || {})[g] || {}).name || g, st: st, cnt: sStat[g],
               metric: '强度 ' + st + ' · ' + sStat[g] + ' 只' };
    }).sort(function (a, b) { return b.st - a.st || b.cnt - a.cnt; });
    return { time: time, model: model,
             dailyModel: model.filter(function (m) { return !isWeeklyModel(m.id); }),
             weeklyModel: model.filter(function (m) { return isWeeklyModel(m.id); }),
             concept: concept, sector: sector };
  }
  function stratSideSection(title, kind, items, cap) {
    if (!items.length) return '';
    var rowsHtml = items.slice(0, cap || 30).map(function (it) {
      var active = stratFilter.kind === kind && stratFilter.id === String(it.id);
      return '<div class="strat-side-row' + (active ? ' active' : '') + '" data-kind="' + kind + '" data-id="' + esc(it.id) + '">' +
        '<span class="sr-name">' + esc(it.name) + '</span><span class="sr-metric">' + esc(it.metric) + '</span></div>';
    }).join('');
    return '<div class="strat-side-sec"><div class="strat-side-title">' + esc(title) + '</div>' + rowsHtml + '</div>';
  }
  function renderStratSidebar(rows, view) {
    var g = stratGroups(rows, view);
    var dailyCount = rows.filter(function (r) { return rowInModelPool(r, 'daily'); }).length;
    var weeklyCount = rows.filter(function (r) { return rowInModelPool(r, 'weekly'); }).length;
    return stratSideSection('时间 · 按当天时间', 'time', g.time) +
      stratSideSection('模型池', 'pool', [
        { id: 'daily', name: '日线模型池', metric: dailyCount + ' 只 · 18 模型' },
        { id: 'weekly', name: '周线模型池', metric: weeklyCount + ' 只 · 5 模型' }
      ]) +
      stratSideSection('日线模型池 · 按胜率', 'model', g.dailyModel) +
      stratSideSection('周线模型池 · 按胜率', 'model', g.weeklyModel) +
      stratSideSection('概念 · 按涨停数', 'concept', g.concept) +
      stratSideSection('板块 · 按强度值', 'sector', g.sector) ||
      '<div class="muted" style="padding:14px">暂无分类数据</div>';
  }
  /* 策略页盘中实时：model_hits（今日事件）+ strategy_all.json（昨日定格买点）合并 */
  var stratRealtime = false, stratRealtimeTimer = null, STRAT_RT = null;
  function buildStratRealtimeRows(payload, frozen) {
    var isToday = payload && payload.data_date === localToday();
    if (!payload || !payload.available || !isToday) {
      return { rows: [], status: '今日实时 · 盘中数据尚未启动（9:14 后自动开始，15:30 归档后切换为今日归档视图）' };
    }
    var frozenMap = {};
    ((frozen && frozen.list) || []).forEach(function (r) { frozenMap[r.stock_id] = r; });
    var rows = (payload.model_hits || []).map(function (h) {
      var f = frozenMap[h.stock_id] || {};
      var models = {};
      (h.model_hit || []).forEach(function (m) { models[m] = (f.models || {})[m] != null ? f.models[m] : 0; });
      return { stock_id: h.stock_id, name: h.name || f.name || h.stock_id,
        score: h.score != null ? h.score : f.score, models: models,
        buy_lo: f.buy_lo, stop: f.stop, stop_pct: f.stop_pct, rr: f.rr, target: f.target,
        stars: f.stars, bp_pass: f.bp_pass,
        entry_time: String(h.ts || '').slice(11, 16) || f.entry_time || '',
        price: h.price != null ? h.price : f.price, chg: h.change_pct != null ? h.change_pct : f.chg,
        reason: f.reason, reason_date: f.reason_date, reason_sources: f.reason_sources,
        reason_is_history: f.reason_is_history, sectors: f.sectors || [], themes: f.themes || [] };
    });
    rows.sort(function (a, b) { return (b.score || 0) - (a.score || 0); });
    var liveTime = String((payload && payload.ts) || '').slice(11, 19) || '';
    var secMap = {};
    ((payload && payload.sector_strength) || []).forEach(function (s) {
      secMap[s.sector_id] = { strength: s.strength, limitup: s.limitup, count: s.count };
    });
    return { rows: rows,
             limitupIds: (payload.limitup || []).map(function (e) { return e.stock_id; }),
             sectorsStrength: secMap,
             ts: liveTime, phase: (payload && payload.phase) || '',
             status: '今日实时 · ' + (liveTime || '--:--:--') + ' · 命中 ' + rows.length + ' 只 · 现价实时（买点/止损定格 ' + ((frozen && frozen.date) || '-') + '）' };
  }
  /* 实时不可用时回落：今日已归档回落今日，否则落最新归档日（跨午夜/盘前场景） */
  function stratFallbackToArchive() {
    return fetchJSON('data/web/index.json', 'no-cache').then(function (idx) {
      var dates = ((idx && idx.days) || []).map(function (d) { return d.date; });
      if (!dates.length) return false;
      var today = localToday();
      var target = dates.indexOf(today) >= 0 ? today : dates[0];
      DAYS = idx.days || DAYS;
      var sel = $('dateSel');
      if (sel) {
        var has = false;
        for (var i = 0; i < sel.options.length; i++) { if (sel.options[i].value === target) { has = true; break; } }
        if (!has) {
          var o = document.createElement('option');
          o.value = target; o.textContent = target;
          sel.insertBefore(o, sel.options[1] || null);
        }
        sel.value = target;
      }
      stratManualArchive = false;
      stopStratRealtime();
      if (target === currentDay && CACHE[target]) render();
      else loadDay(target);
      return true;
    }).catch(function () { return false; });
  }
  function refreshStratRealtime() {
    if (!stratRealtime || currentView !== 'strategy') return;
    Promise.all([fetchJSON('api/intraday/latest', 'no-store').catch(function () { return null; }),
                 fetchJSON('data/web/strategy_all.json').catch(function () { return null; }),
                 loadMemberLocalRealtime()]).then(function (rs) {
      var payload = rs[0] ? (rs[0].data || rs[0]) : null;
      if (payload) payload = mergeMemberLocalRealtime(payload, rs[2]);
      var live = payload && payload.available && payload.data_date === localToday() && isMarketSession();
      if (!live) {
        // 盘中数据不可用（收盘/归档后）：今日已归档则自动回落归档视图，否则保持提示继续轮询
        stratFallbackToArchive().then(function (fellBack) {
          if (fellBack) return;
          if (!stratRealtime) return;
          STRAT_RT = buildStratRealtimeRows(payload, rs[1]);
          render();
          refreshStratPanels();
          window.clearTimeout(stratRealtimeTimer);
          stratRealtimeTimer = window.setTimeout(refreshStratRealtime, 30000);
        });
        return;
      }
      STRAT_RT = buildStratRealtimeRows(payload, rs[1]);
      render();
      refreshStratPanels();
      window.clearTimeout(stratRealtimeTimer);
      stratRealtimeTimer = window.setTimeout(refreshStratRealtime, 30000);
    }).catch(function () {
      // 网络/接口异常不悬挂：15s 后重试
      window.clearTimeout(stratRealtimeTimer);
      stratRealtimeTimer = window.setTimeout(refreshStratRealtime, 15000);
    });
  }
  function startStratRealtime() {
    if (stratRealtime) return;
    stratRealtime = true;
    STRAT_RT = null;
    refreshStratRealtime();
  }
  function stopStratRealtime() {
    stratRealtime = false;
    STRAT_RT = null;
    window.clearTimeout(stratRealtimeTimer);
    stratRealtimeTimer = null;
  }
  function currentStratRows() {
    if (stratRealtime) return (STRAT_RT ? STRAT_RT.rows : []);
    return strategyRows(CACHE[currentDay] || {});
  }
  function stratKpiHtml(view, rows) {
    var covered = rows.reduce(function (a, r) {
      Object.keys(r.models || {}).forEach(function (m) { a[isWeeklyModel(m) ? 'weekly' : 'daily'][m] = 1; });
      return a;
    }, { daily: {}, weekly: {} });
    var kpi = [
      ['命中总数', rows.length],
      ['预警池', stratRealtime ? rows.length : (((view.pools || {}).pools || {}).alert ? Object.keys(((view.pools || {}).pools || {}).alert).length : 0)],
      ['最高评分', rows[0] && rows[0].score != null ? Number(rows[0].score).toFixed(1) : '-'],
      ['日线覆盖', Object.keys(covered.daily).length + '/18'],
      ['周线覆盖', Object.keys(covered.weekly).length + '/5']];
    return kpi.map(function (k) {
      return '<div class="kpi"><div class="num">' + k[1] + '</div><div class="lbl">' + k[0] + '</div></div>';
    }).join('');
  }
  /* 局部刷新右表 + 左栏分类（不全量 render，避免闪烁与递归） */
  var SUB_MODELS = ['sub_low', 'sub_trend_vol', 'sub_breakout', 'sub_main'];
  /* 结论先行（单列四区）：最佳买点TOP10 + 精选概念TOP + 精选板块TOP + 子模型；全部可点击联动 */
  function stratConclusionHtml(rows, view) {
    var g = stratGroups(rows, view);
    var conceptCnt = {}, sectorCnt = {};
    g.concept.forEach(function (it) { conceptCnt[it.id] = it.cnt; });
    g.sector.forEach(function (it) { sectorCnt[it.id] = it.cnt; });
    var names = LIBS.stocks_slim || {};
    function tagRow(it, kind) {
      var active = stratFilter.kind === kind && stratFilter.id === String(it.id);
      return '<div class="strat-side-row' + (active ? ' active' : '') + '" data-kind="' + kind + '" data-id="' + esc(it.id) + '">' +
        '<span class="sr-name">' + esc(it.name) + '</span><span class="sr-metric">' + esc(it.metric) + '</span></div>';
    }
    // 最佳买点 TOP10：每股带概念/板块标签 + 该分类命中支数
    var tops = rows.filter(function (r) { return r.bp_pass === true; }).slice(0, 10);
    var topRows = tops.map(function (r, i) {
      var nm = (names[r.stock_id] || {}).n || r.name || code6(r.stock_id);
      var tId = (r.themes && r.themes.length) ? r.themes[0] : ((r.sectors && r.sectors.length) ? r.sectors[0] : '');
      var tName = tId ? (((LIBS.themes || {})[tId] || (LIBS.sectors || {})[tId] || {}).name || tId) : '';
      var tCnt = tId ? (conceptCnt[tId] || sectorCnt[tId] || 0) : 0;
      return '<div class="strat-side-row tb-row" data-sid="' + esc(r.stock_id) + '" title="点击行在下方列表定位该股；点名称跳通达信">' +
        '<span class="tb-rank">' + (i + 1) + '</span><span class="sr-name">' + stk(r.stock_id, nm) + '</span>' +
        (tName ? '<span class="tag-chip sec">' + esc(tName) + ' · ' + tCnt + '支</span>' : '') +
        '<span class="sr-metric">' + (r.score == null ? '-' : Number(r.score).toFixed(1)) + '</span></div>';
    }).join('') || '<div class="muted" style="padding:6px 10px">暂无过买点过滤的命中</div>';
    var subCards = SUB_MODELS.map(function (m) {
      var it = null;
      for (var i = 0; i < g.model.length; i++) { if (g.model[i].id === m) { it = g.model[i]; break; } }
      var active = stratFilter.kind === 'model' && stratFilter.id === m;
      return '<div class="strat-side-row cc-sub' + (active ? ' active' : '') + '" data-kind="model" data-id="' + m + '">' +
        '<span class="sr-name">' + esc(MODEL_CN[m] || m) + '</span><span class="sr-metric">' + (it ? it.cnt + ' 只' : '0 只') + '</span></div>';
    }).join('');
    return '<div class="strat-conclusion">' +
      '<div class="cc-col"><div class="cc-title">最佳买点 TOP10 <small>点击行定位主表</small></div>' + topRows + '</div>' +
      '<div class="cc-col"><div class="cc-title">精选概念 TOP <small>按当天' + (stratRealtime ? '实时' : '') + '涨停数</small></div>' +
      (g.concept.slice(0, 5).map(function (it) { return tagRow(it, 'concept'); }).join('') || '<div class="muted" style="padding:6px 10px">暂无</div>') + '</div>' +
      '<div class="cc-col"><div class="cc-title">精选板块 TOP <small>按当天' + (stratRealtime ? '实时' : '') + '强度值</small></div>' +
      (g.sector.slice(0, 5).map(function (it) { return tagRow(it, 'sector'); }).join('') || '<div class="muted" style="padding:6px 10px">暂无</div>') + '</div>' +
      '<div class="cc-col"><div class="cc-title">子模型</div>' + subCards + '</div>' +
      '</div>';
  }
  function refreshStratPanels() {
    if (currentView !== 'strategy') return;
    var view = CACHE[currentDay] || {};
    var rows = currentStratRows();
    var topEl = $('stratTop');
    if (topEl) topEl.innerHTML = stratConclusionHtml(rows, view);
    var kpiEl = $('stratKpi');
    if (kpiEl) kpiEl.innerHTML = stratKpiHtml(view, rows);
    var sideEl = $('stratSide');
    if (sideEl) sideEl.innerHTML = renderStratSidebar(rows, view);
    var bodyEl = $('stratBody');
    if (bodyEl) bodyEl.innerHTML = stratTable(applyStratFilter(rows), LIBS.stocks_slim || {});
    var noteEl = $('stratNote');
    if (noteEl && stratRealtime) noteEl.textContent = STRAT_RT ? STRAT_RT.status : '今日实时 · 正在连接';
  }
  function vStrategy(view) {
    loadHistoryAssets();
    var note = stratRealtime
      ? '<div class="strat-note" id="stratNote">' + esc(STRAT_RT ? STRAT_RT.status : '今日实时 · 正在连接') + '</div>' : '';
    Promise.all([loadLib('sectors.json'), loadLib('themes.json'), loadExpandLibs(),
                 stratRealtime ? Promise.resolve(null) : loadStrategyAll()]).then(refreshStratPanels);
    return '<div class="strat-shell"><div class="strat-workbench">' +
      '<aside class="strat-sidebar">' + note +
      '<div class="strat-side-list" id="stratSide"><div class="muted" style="padding:12px">加载分类…</div></div></aside>' +
      '<section class="strat-detail"><div id="stratTop"></div>' +
      '<div class="kpi-row strat-kpi" id="stratKpi"></div>' +
      '<div class="strat-body" id="stratBody"><div class="muted" style="padding:12px">加载命中池…</div></div></section>' +
      '</div></div>';
  }

  function loadHistorySourcePools(watchlist) {
    var dates = Array.from(new Set(Object.keys(watchlist || {}).map(function (sid) {
      return String((watchlist[sid] || {}).source_date || '');
    }).filter(function (date) { return /^\d{4}-\d{2}-\d{2}$/.test(date) && !HISTORY_SOURCE_POOLS[date]; })));
    return Promise.all(dates.map(function (date) {
      return fetchJSON('api/pools?date=' + date).then(function (r) {
        var doc = r.data || r;
        HISTORY_SOURCE_POOLS[date] = doc.pools || {};
      }).catch(function () { HISTORY_SOURCE_POOLS[date] = {}; });
    }));
  }

  function loadHistoryAssets() {
    if (historyAssetsLoading || (LIBS.stocks_slim && HISTORY_WATCHLIST !== null)) return;
    historyAssetsLoading = true;
    Promise.all([
      loadLib('stocks_slim.json'),
      HISTORY_WATCHLIST !== null ? Promise.resolve(HISTORY_WATCHLIST) : fetchJSON('api/pools?date=' + localToday(), 'no-store').then(function (r) {
        var doc = r.data || r; return ((doc.pools || {}).watchlist || {});
      }).catch(function () { return {}; })
    ]).then(function (result) {
      HISTORY_WATCHLIST = result[1];
      return loadHistorySourcePools(HISTORY_WATCHLIST);
    }).then(function () {
      historyAssetsLoading = false;
      if (['history', 'signal', 'sector', 'leading', 'strategy'].indexOf(currentView) >= 0) render();
    }).catch(function () { HISTORY_WATCHLIST = HISTORY_WATCHLIST || {}; historyAssetsLoading = false; });
  }

  function loadHistoryDatePools(date, view) {
    date = String(date || '');
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || HISTORY_DATE_POOLS[date] === 'loading' ||
        (view && view.memberPoolLoaded)) return;
    HISTORY_DATE_POOLS[date] = 'loading';
    fetchJSON('api/pools?date=' + encodeURIComponent(date), 'no-store').then(function (response) {
      var doc = response.data || response;
      var pools = doc.pools || {};
      HISTORY_DATE_POOLS[date] = pools;
      if (!view || CACHE[currentDay] !== view || String(view.date || currentDay) !== date) return;
      view.pools = { data_date: date, pools: pools };
      view.pool_summary = {};
      ['alert', 'candidate', 'watchlist'].forEach(function (kind) {
        var count = Object.keys(pools[kind] || {}).length;
        view.pool_summary[kind] = { shown: count, total: count };
      });
      view.memberPoolLoaded = true;
      render();
    }).catch(function () { delete HISTORY_DATE_POOLS[date]; });
  }

  /* 历史选股：中文复盘概览 + 预警/候选/自选池 */
  function confirmCount(entry) {
    var confirm = (entry || {}).confirm || {};
    return (((entry || {}).model_hit || []).length > 0 ? 1 : 0) +
      (confirm.sector_strength ? 1 : 0) + (confirm.money_flow ? 1 : 0) + (confirm.leading_reason ? 1 : 0);
  }
  function confirmTag(label, yes) {
    return '<span class="history-confirm ' + (yes ? 'on' : 'off') + '"><i>' + (yes ? '✓' : '—') + '</i>' + label + '</span>';
  }
  function historySortRows(pool) {
    return Object.keys(pool || {}).map(function (sid) { return { sid: sid, entry: pool[sid] || {} }; }).sort(function (a, b) {
      return Number(b.entry.stars || 0) - Number(a.entry.stars || 0) ||
        confirmCount(b.entry) - confirmCount(a.entry) || Number(b.entry.score || 0) - Number(a.entry.score || 0) ||
        a.sid.localeCompare(b.sid);
    });
  }
  function enrichHistoryWatchlist(watchlist, currentPools, viewDate) {
    var enriched = {};
    Object.keys(watchlist || {}).forEach(function (sid) {
      var entry = watchlist[sid] || {}, sourceDate = entry.source_date || viewDate;
      var sourcePools = HISTORY_SOURCE_POOLS[sourceDate] || (sourceDate === viewDate ? currentPools : {});
      var detail = (sourcePools.alert || {})[sid] || (sourcePools.candidate || {})[sid] ||
        (currentPools.alert || {})[sid] || (currentPools.candidate || {})[sid] || {};
      enriched[sid] = Object.assign({}, detail, entry);
    });
    return enriched;
  }
  function vHistory(view) {
    loadHistoryAssets();
    loadHistoryDatePools(view.date || currentDay, view);
    var pools = (view.pools && view.pools.pools) || {}, poolSummary = view.pool_summary || {};
    var names = LIBS.stocks_slim || {}, currentWatch = HISTORY_WATCHLIST || {};
    var statusCn = { active: '跟踪中', candidate: '候选', removed: '已移除', confirmed: '已确认', watch: '自选' };
    function poolTable(name, pool, emptyMsg, kind) {
      var items = historySortRows(pool);
      var rows = items.map(function (item) {
        var sid = item.sid, e = item.entry;
        var stockName = (names[sid] || {}).n || e.name || '名称待同步';
        var stars = '<span class="history-stars">' + (e.stars ? '★'.repeat(e.stars) : '—') + '</span>';
        var confirm = (e.confirm || {});
        var modelIds = e.model_hit || [];
        var c = '<div class="history-confirm-grid">' + confirmTag('模型确认', modelIds.length > 0) +
          confirmTag('板块强度', !!confirm.sector_strength) + confirmTag('资金流入', !!confirm.money_flow) +
          confirmTag('领涨原因', !!confirm.leading_reason) + '</div>';
        var selected = Object.prototype.hasOwnProperty.call(currentWatch, sid);
        var watch = '<button type="button" class="history-watch-btn ' + (selected ? 'selected' : '') + '" data-sid="' + esc(sid) +
          '" data-selected="' + (selected ? '1' : '0') + '" data-source-date="' + esc(view.date || currentDay) + '">' +
          (selected ? '★ 已自选' : '＋ 加自选') + '</button>';
        var models = modelIds.map(function (m) { return '<span class="badge b-model">' + esc(MODEL_CN[m] || m) + '</span>'; }).join(' ') || '<span class="muted">无模型记录</span>';
        return '<tr><td class="l"><div class="history-stock"><span class="history-stock-name">' + stk(sid, stockName) +
          '</span><small class="history-stock-code">' + esc(code6(sid)) + '</small></div></td><td>' + esc(e.entry_time || '-') + '</td>' +
          '<td><b class="history-score">' + Number(e.score || 0).toFixed(1) + '</b></td><td class="l history-models">' + models + '</td><td>' + stars +
          '</td><td class="l"><div class="history-confirm-action">' + c + watch + '</div></td><td>' + esc(statusCn[e.status] || (kind === 'watch' ? '自选跟踪' : '跟踪中')) + '</td></tr>';
      }).join('');
      var summary = poolSummary[kind] || { shown: items.length, total: items.length };
      var countText = Number(summary.shown || items.length) + (Number(summary.total || items.length) > Number(summary.shown || items.length) ? ' / 总' + Number(summary.total) : '') + ' 只';
      return '<section class="history-pool card"><div class="card-h"><span>' + name + '</span><span class="sub">' + countText + ' · 按四维星级降序</span></div>' +
        '<div class="card-b flush"><div class="tblwrap"><table><thead><tr><th class="l">股票</th><th>进入时间</th><th>评分</th><th class="l">模型命中</th><th>星级</th><th class="l">四维确认 / 自选</th><th>状态</th></tr></thead><tbody>' +
        (rows || '<tr><td colspan="7" class="muted">' + emptyMsg + '</td></tr>') + '</tbody></table></div></div></section>';
    }
    var watchPool = enrichHistoryWatchlist(currentWatch, pools, view.date || currentDay);
    var defs = [
      { id: 'alert', icon: '⚠️', name: '重点预警池', hint: '高优先级信号', empty: '暂无重点预警', pool: pools.alert || {} },
      { id: 'candidate', icon: '📌', name: '候选观察池', hint: '等待进一步确认', empty: '暂无候选股票', pool: pools.candidate || {} },
      { id: 'watch', icon: '⭐', name: '我的自选池', hint: '当前会员本地自选', empty: '尚未添加自选股票', pool: watchPool }
    ];
    var active = defs.filter(function (def) { return def.id === historyPoolKind; })[0] || defs[0];
    var nav = defs.map(function (def) {
      var sorted = historySortRows(def.pool);
      var highest = sorted.length ? Number(sorted[0].entry.stars || confirmCount(sorted[0].entry)) : 0;
      return '<button type="button" data-history-pool="' + def.id + '" class="' + (def.id === active.id ? 'active' : '') + '">' +
        '<span><i>' + def.icon + '</i><strong>' + def.name + '</strong></span><b>' + sorted.length + '</b>' +
        '<small>' + def.hint + ' · 最高确认 ' + highest + '星</small></button>';
    }).join('');
    return '<div class="history-shell"><div class="history-workbench"><aside class="history-sidebar">' +
      '<div class="history-heading"><div><h1>历史选股复盘</h1><p>' + esc(view.date || currentDay) + ' · 四维确认按星级排序</p></div></div>' +
      '<div class="history-summary history-pool-nav">' + nav + '</div>' +
      '<div class="history-side-note">排序：星级 → 确认维度 → 评分<br>自选统一写入当天跟踪池</div></aside>' +
      '<main class="history-main">' + poolTable(active.icon + ' ' + active.name, active.pool, active.empty, active.id) + '</main></div></div>';
  }

  /* ---------- 原因弹窗（懒加载 detail） ---------- */
  function showPopup(sid, x, y, dayOverride) {
    var pop = $('popup');
    pop.innerHTML = '<div class="pp-head"><span>加载中…</span><span class="pp-close" onclick="document.getElementById(\'popup\').style.display=\'none\'">×</span></div>';
    pop.style.display = 'block';
    pop.dataset.anchorX = x;
    pop.dataset.anchorY = y;
    place(pop, x, y);
    var detailDay = dayOverride || ((themeRealtime || sectorRealtime) ? localToday() : currentDay);
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
  var VALID_VIEWS = ['signal', 'auction', 'minute-volume', 'theme', 'sector', 'leading', 'strategy', 'history', 'member'];
  var initView = location.hash ? location.hash.slice(1) : 'signal';
  if (VALID_VIEWS.indexOf(initView) >= 0) currentView = initView;
  signalRealtimeMode = currentView === 'signal' || currentView === 'leading';
  document.querySelectorAll('.tab').forEach(function (tab) {
    if (tab.dataset.view === currentView) tab.classList.add('active');
    tab.addEventListener('click', function () {
      var nextView = tab.dataset.view;
      document.querySelectorAll('.tab').forEach(function (t) { t.classList.remove('active'); });
      tab.classList.add('active');
      if (nextView !== 'theme' && themeRealtime) stopThemeRealtime(false);
      if (nextView !== 'sector') { sectorRealtime = false; window.clearTimeout(sectorRealtimeTimer); }
      if (nextView !== 'strategy') stopStratRealtime();
      if (nextView !== 'auction') stopAuctionRadar();
      if (nextView !== 'minute-volume') stopMinuteVolume();
      if (nextView !== 'signal' && nextView !== 'leading' && nextView !== 'history') stopSignalRealtime();
      if (nextView === 'sector') { sectorForceHistory = false; sectorForceRealtime = false; }
      // 实时刷新入口会校验 currentView；必须先提交视图并渲染 DOM，再启动轮询。
      currentView = nextView;
      if (nextView === 'history' && $('dateSel')) $('dateSel').value = isMarketSession() ? SECTOR_TODAY_VALUE : currentDay;
      if (nextView === 'minute-volume' && $('dateSel')) { minuteVolumeDate = null; $('dateSel').value = SECTOR_TODAY_VALUE; }
      if (history.replaceState) history.replaceState(null, '', '#' + currentView);
      render();
      if (nextView === 'signal' || nextView === 'leading' || (nextView === 'history' && isMarketSession())) startSignalRealtime();
      if (nextView === 'auction') startAuctionRadar();
      if (nextView === 'minute-volume') startMinuteVolume();
      if (nextView === 'theme' && !themeRealtime && isMarketSession()) startThemeRealtime();
      if (nextView === 'strategy' && !stratManualArchive) {
        var sel = $('dateSel');
        if (isMarketSession()) {
          if (sel) sel.value = SECTOR_TODAY_VALUE;
          if (!stratRealtime) startStratRealtime();
        } else {
          stopStratRealtime();
          if (sel && currentDay) sel.value = currentDay;
        }
      }
    });
  });
  $('dateSel').addEventListener('change', function () {
    if (themeRealtime) stopThemeRealtime(false);
    if (this.value === SECTOR_TODAY_VALUE) {
      if (currentView === 'signal' || currentView === 'leading' || currentView === 'history') {
        startSignalRealtime(); render();
      } else if (currentView === 'auction') {
        startAuctionRadar(); render();
      } else if (currentView === 'minute-volume') {
        startMinuteVolume(); render();
      } else if (currentView === 'theme') {
        startThemeRealtime();
      } else if (currentView === 'sector') {
        sectorForceHistory = false; sectorForceRealtime = true; sectorRealtime = true; render();
      } else if (currentView === 'strategy') {
        stratManualArchive = false;
        startStratRealtime(); render();
      } else {
        this.value = currentDay;
      }
      return;
    }
    if (currentView === 'signal' || currentView === 'leading' || currentView === 'history') stopSignalRealtime();
    if (currentView === 'auction') stopAuctionRadar();
    if (currentView === 'minute-volume') stopMinuteVolume();
    if (currentView === 'minute-volume') { minuteVolumeDate = this.value; minuteVolumeSelectedId = null; startMinuteVolume(); return; }
    if (currentView === 'strategy' && stratRealtime) { stratManualArchive = true; stopStratRealtime(); }
    if (currentView === 'sector') { sectorForceHistory = true; sectorRealtime = false; window.clearTimeout(sectorRealtimeTimer); }
    loadDay(this.value);
  });
  document.addEventListener('click', function (ev) {
    if (ev.target.closest && ev.target.closest('#memberCenterBtn')) { openMemberCenter(); return; }
    var localAuctionButton = ev.target.closest ? ev.target.closest('[data-auction-local]') : null;
    if (localAuctionButton) {
      var localAction = localAuctionButton.dataset.auctionLocal;
      if (localAction === 'probe') testLocalAuctionConnection();
      else if (localAction === 'start' || localAction === 'stop') controlLocalAuction(localAction);
      return;
    }
    var auctionFilterBtn = ev.target.closest ? ev.target.closest('[data-auction-filter]') : null;
    if (auctionFilterBtn) {
      auctionFilter = auctionFilterBtn.dataset.auctionFilter || 'focus';
      auctionSelectedId = null;
      if (currentView === 'auction') render();
      return;
    }
    var auctionTrajectoryBtn = ev.target.closest ? ev.target.closest('[data-auction-trajectory]') : null;
    if (auctionTrajectoryBtn) {
      var nextTrajectory = auctionTrajectoryBtn.dataset.auctionTrajectory || '';
      auctionTrajectoryFilter = nextTrajectory === auctionTrajectoryFilter ? '' : nextTrajectory;
      auctionSelectedId = null;
      if (currentView === 'auction') render();
      return;
    }
    var auctionTableRow = ev.target.closest ? ev.target.closest('[data-auction-sid]') : null;
    if (auctionTableRow && currentView === 'auction') {
      auctionSelectedId = auctionTableRow.dataset.auctionSid;
      render();
      return;
    }
    var minuteMode = ev.target.closest ? ev.target.closest('[data-minute-mode]') : null;
    if (minuteMode && currentView === 'minute-volume') { minuteVolumeMode = minuteMode.dataset.minuteMode || 'stock'; render(); return; }
    var minuteFilter = ev.target.closest ? ev.target.closest('[data-minute-filter]') : null;
    if (minuteFilter && currentView === 'minute-volume') { minuteVolumeFilter = minuteFilter.dataset.minuteFilter || 'near'; minuteVolumeSelectedId = null; startMinuteVolume(); return; }
    var minuteRow = ev.target.closest ? ev.target.closest('[data-minute-sid]') : null;
    if (minuteRow && currentView === 'minute-volume' && !(ev.target.closest && ev.target.closest('[data-minute-watch]'))) { minuteVolumeSelectedId = minuteRow.dataset.minuteSid; startMinuteVolume(); return; }
    var memberPane = ev.target.closest ? ev.target.closest('[data-member-pane]') : null;
    if (memberPane) { switchMemberPane(memberPane.dataset.memberPane); return; }
    if (ev.target.closest && ev.target.closest('#memberActivate')) { activateMemberLicense(); return; }
    if (ev.target.closest && ev.target.closest('#memberRegisterTrial')) { registerMemberTrial(); return; }
    if (ev.target.closest && ev.target.closest('#memberRevalidate')) { validateMemberLicense(); return; }
    if (ev.target.closest && ev.target.closest('#memberLogout')) { logoutMemberLicense(); return; }
    if (ev.target.closest && ev.target.closest('#memberOpenLocalPage')) { openMemberLocalPage(); return; }
    if (ev.target.closest && ev.target.closest('#memberRefreshStatus')) { loadMemberWorkbenchStatus(); return; }
    if (ev.target.closest && ev.target.closest('#memberSaveConfig')) { saveMemberWorkbenchConfig(false); return; }
    if (ev.target.closest && ev.target.closest('#memberGenerateKline')) { saveMemberWorkbenchConfig(true); return; }
    if (ev.target.closest && ev.target.closest('#memberCheckUpdate')) { checkMemberWorkbenchUpdate(); return; }
    var leadingNav = ev.target.closest ? ev.target.closest('[data-leading-id]') : null;
    if (leadingNav) {
      ev.preventDefault(); ev.stopPropagation();
      selectedLeadingId = leadingNav.dataset.leadingId;
      if (currentView === 'leading') render();
      return;
    }
    var leadingModeButton = ev.target.closest ? ev.target.closest('[data-leading-mode]') : null;
    if (leadingModeButton) {
      ev.preventDefault(); ev.stopPropagation();
      leadingMode = leadingModeButton.dataset.leadingMode || 'realtime';
      if (currentView === 'leading') render();
      return;
    }
    var expectedRangeButton = ev.target.closest ? ev.target.closest('[data-expected-range]') : null;
    if (expectedRangeButton) {
      expectedRange = expectedRangeButton.dataset.expectedRange || 'all';
      selectedExpectedId = null;
      if (currentView === 'leading') render();
      return;
    }
    var expectedStatusButton = ev.target.closest ? ev.target.closest('[data-expected-status]') : null;
    if (expectedStatusButton) {
      expectedStatusFilter = expectedStatusButton.dataset.expectedStatus || 'all';
      selectedExpectedId = null;
      if (currentView === 'leading') render();
      return;
    }
    var expectedRow = ev.target.closest ? ev.target.closest('[data-expected-id]') : null;
    if (expectedRow && !(ev.target.closest && ev.target.closest('.signal-inline-watch'))) {
      selectedExpectedId = expectedRow.dataset.expectedId;
      if (currentView === 'leading') render();
      return;
    }
    var historyPoolNav = ev.target.closest ? ev.target.closest('[data-history-pool]') : null;
    if (historyPoolNav) {
      ev.preventDefault(); ev.stopPropagation();
      historyPoolKind = historyPoolNav.dataset.historyPool || 'alert';
      if (currentView === 'history') render();
      return;
    }
    var historyWatch = ev.target.closest ? ev.target.closest('.history-watch-btn, .signal-watch-btn, .signal-inline-watch, .minute-watch-btn') : null;
    if (historyWatch) {
      ev.preventDefault(); ev.stopPropagation();
      if (!memberIsLocalWorkbench()) {
        window.alert('会员自选只保存在本机，请打开本地工作台后添加。');
        location.href = 'http://127.0.0.1:8790/' + location.hash;
        return;
      }
      if (historyWatch.disabled) return;
      var watchSid = historyWatch.dataset.sid;
      var removeWatch = historyWatch.dataset.selected === '1';
      var isSignalWatch = historyWatch.dataset.signalWatch === '1';
      var isMinuteWatch = historyWatch.dataset.minuteWatch === '1';
      historyWatch.disabled = true; historyWatch.textContent = isSignalWatch ? '…' : '处理中…';
      postJSON('api/watchlist', { stock_id: watchSid, action: removeWatch ? 'remove' : 'add',
        date: localToday(), source_date: historyWatch.dataset.sourceDate || currentDay,
        note: isMinuteWatch ? '分钟爆量加入' : (isSignalWatch ? '实时信号加入' : '历史选股加入') })
        .then(function (result) {
          HISTORY_WATCHLIST = HISTORY_WATCHLIST || {};
          var data = result.data || result;
          if (data.selected) HISTORY_WATCHLIST[watchSid] = data.entry || { status: 'active' };
          else delete HISTORY_WATCHLIST[watchSid];
          if (isMinuteWatch && minuteVolumePayload) {
            (minuteVolumePayload.rows || []).forEach(function (row) { if (row.stock_id === watchSid) row.selected = !!data.selected; });
            if (minuteVolumePayload.detail && minuteVolumePayload.detail.stock_id === watchSid) minuteVolumePayload.detail.selected = !!data.selected;
            minuteVolumeLocalEvents.unshift({ ts: new Date().toLocaleTimeString('zh-CN', { hour12: false }), detail: (minuteVolumePayload.detail && minuteVolumePayload.detail.name || watchSid) + (data.selected ? ' · 已加入自选' : ' · 已移出自选') });
          }
          if (['history', 'signal', 'sector', 'leading', 'strategy', 'minute-volume'].indexOf(currentView) >= 0) render();
        }).catch(function (error) {
          historyWatch.disabled = false;
          historyWatch.textContent = isSignalWatch ? (removeWatch ? '✓' : '+') : (removeWatch ? '★ 已自选' : '＋ 加自选');
          window.alert('自选保存失败：' + (error && error.message ? error.message : '请确认已在本地工作台中打开并完成会员授权'));
        });
      return;
    }
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
    var trendSummary = ev.target.closest ? ev.target.closest('.sector-trend summary') : null;
    if (trendSummary) {
      var trendDetails = trendSummary.closest('.sector-trend');
      sectorTrendExpanded = !trendDetails.open;
      return;
    }
    var trendCell = ev.target.closest ? ev.target.closest('.sector-trend-cell') : null;
    if (trendCell) {
      ev.preventDefault(); ev.stopPropagation();
      selectSectorTrend(trendCell.dataset.trendDate, trendCell.dataset.trendSid);
      return;
    }
    var sectorRank = ev.target.closest ? ev.target.closest('.sector-rank-row') : null;
    if (sectorRank) {
      selectedSectorId = sectorRank.dataset.sid;
      selectedSubSectorId = null;
      renderSectorWorkbench(activeSectorView());
      if (sectorRealtime) refreshSectorRealtime();
      return;
    }
    var sectorSub = ev.target.closest ? ev.target.closest('.sector-sub-chip') : null;
    if (sectorSub) {
      selectedSubSectorId = sectorSub.dataset.subsid || null;
      renderSectorDetail(activeSectorView(), selectedSectorId);
      if (sectorRealtime) refreshSectorRealtime();
      return;
    }
    var sectorFilterBtn = ev.target.closest ? ev.target.closest('[data-sector-filter]') : null;
    if (sectorFilterBtn) {
      sectorFilter = sectorFilterBtn.dataset.sectorFilter;
      if (sectorRealtime) renderSectorStockTable(lastSectorRows); else loadSectorStocks(activeSectorView(), selectedSectorId);
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
    var sideRow = ev.target.closest ? ev.target.closest('.strat-side-row') : null;
    if (sideRow) {
      var fKind = sideRow.dataset.kind, fId = sideRow.dataset.id;
      if (stratFilter.kind === fKind && stratFilter.id === fId) stratFilter = { kind: '', id: '' };
      else stratFilter = { kind: fKind, id: fId };
      document.querySelectorAll('.strat-side-row').forEach(function (el) {
        el.classList.toggle('active', el.dataset.kind === stratFilter.kind && el.dataset.id === stratFilter.id);
      });
      var stratBodyEl = $('stratBody');
      if (stratBodyEl) stratBodyEl.innerHTML = stratTable(applyStratFilter(currentStratRows()), LIBS.stocks_slim || {});
      return;
    }
    var btn = ev.target.closest ? ev.target.closest('.reason-pop') : null;
    if (btn) { ev.stopPropagation(); showPopup(btn.dataset.sid, ev.clientX, ev.clientY, btn.dataset.rdate || ''); return; }
    /* 最佳买点 TOP15 行点击 → 主表定位（自动清除分类过滤，滚动 + 高亮） */
    var tbRow = ev.target.closest ? ev.target.closest('.tb-row') : null;
    if (tbRow) {
      if (ev.target.closest('.stk')) return;
      var locateSid = tbRow.dataset.sid;
      if (stratFilter.kind) {
        stratFilter = { kind: '', id: '' };
        document.querySelectorAll('.strat-side-row.active').forEach(function (el) { el.classList.remove('active'); });
        var stratBodyEl2 = $('stratBody');
        if (stratBodyEl2) stratBodyEl2.innerHTML = stratTable(currentStratRows(), LIBS.stocks_slim || {});
      }
      var targetRow = document.querySelector('#stratBody tr[data-sid="' + locateSid + '"]');
      if (targetRow) {
        targetRow.scrollIntoView({ block: 'center', behavior: 'smooth' });
        targetRow.classList.add('row-flash');
        window.setTimeout(function () { targetRow.classList.remove('row-flash'); }, 1800);
      }
      return;
    }
    var stockRow = ev.target.closest ? ev.target.closest('.sector-stock-row') : null;
    if (stockRow && stockRow.dataset.tdxSid) {
      window.location.href = 'http://www.treeid/code_' + encodeURIComponent(code6(stockRow.dataset.tdxSid));
      return;
    }
    if (!ev.target.closest || !ev.target.closest('#popup')) $('popup').style.display = 'none';
  });
  document.addEventListener('input', function (ev) {
    if (ev.target && ev.target.id === 'themeSearch') renderThemeWorkbench(activeThemeView());
    if (ev.target && ev.target.id === 'sectorSearch') renderSectorWorkbench(activeSectorView());
  });
  document.addEventListener('change', function (ev) {
    if (ev.target && ev.target.dataset && ev.target.dataset.auctionDepthFilter !== undefined) {
      auctionDepthFilter = ev.target.value || 'confirmed'; auctionSelectedId = null;
      if (currentView === 'auction') render(); return;
    }
    if (ev.target && ev.target.dataset && ev.target.dataset.auctionVolumeFilter !== undefined) {
      auctionVolumeFilter = ev.target.value || 'all'; auctionSelectedId = null;
      if (currentView === 'auction') render(); return;
    }
    if (ev.target && ev.target.dataset && ev.target.dataset.expectedToggle) {
      if (ev.target.dataset.expectedToggle === 'leader') expectedHasLeaderOnly = ev.target.checked;
      if (ev.target.dataset.expectedToggle === 'limitup') expectedHasLimitupOnly = ev.target.checked;
      selectedExpectedId = null;
      if (currentView === 'leading') render();
      return;
    }
    if (ev.target && ev.target.dataset && ev.target.dataset.auctionToggle) {
      var auctionToggle = ev.target.dataset.auctionToggle;
      if (auctionToggle === 'ratio') auctionToggles.ratio = ev.target.checked;
      if (auctionToggle === 'non-one-price') auctionToggles.nonOnePrice = ev.target.checked;
      if (auctionToggle === 'resonance') auctionToggles.resonance = ev.target.checked;
      auctionSelectedId = null;
      if (currentView === 'auction') render();
      return;
    }
    if (!ev.target || ev.target.id !== 'themeDateSel') return;
    var date = ev.target.value;
    if (date === SECTOR_TODAY_VALUE) { startThemeRealtime(); return; }
    if (themeRealtime) stopThemeRealtime(false);
    $('dateSel').value = date;
    loadDay(date);
  });
  document.addEventListener('keydown', function (ev) {
    if (ev.key === 'Escape') $('popup').style.display = 'none';
    if (currentView === 'auction' && !ev.target.matches('input,select,textarea') && (ev.key === 'ArrowDown' || ev.key === 'ArrowUp')) {
      ev.preventDefault(); selectAuctionOffset(ev.key === 'ArrowDown' ? 1 : -1);
    }
  });

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
  /* 启动时静默复核云授权；不阻断旧版公共页面，会员私有配置仅在授权有效时加载。 */
  memberLicenseState = loadLicenseState();
  if (memberLicenseState && memberLicenseState.code) validateMemberLicense();
  /* 题材页直达（#theme）在交易时段自动接入当天实时，归档后保持当天收盘视图。 */
  if (currentView === 'theme' && isMarketSession()) startThemeRealtime();
  if (currentView === 'auction') startAuctionRadar();
  if (currentView === 'minute-volume') startMinuteVolume();
  /* 策略页直达（#strategy）仅交易时段开启当天实时；收盘后由 loadIndex 展示最新归档。 */
  if (currentView === 'strategy' && !stratManualArchive && isMarketSession()) {
    if ($('dateSel')) $('dateSel').value = SECTOR_TODAY_VALUE;
    startStratRealtime();
  }
})();
