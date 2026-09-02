from pathlib import Path


WEB = Path("apps/web")


def test_default_theme_is_dark_and_uses_obsidian_ruby_tokens():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    css = (WEB / "assets" / "app.css").read_text(encoding="utf-8")
    assert '<html lang="zh-CN" data-theme="dark">' in html
    assert "--c-bg: #12161c" in css.lower()
    assert "--c-primary: #e05555" in css.lower()


def test_topbar_has_member_center_and_delegates_local_kline_to_helper():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    css = (WEB / "assets" / "app.css").read_text(encoding="utf-8")
    for marker in ('id="memberCenterBtn"', "会员中心"):
        assert marker in html
    for marker in ("member-page", "member-page-nav", "member-page-content"):
        assert marker in js
        assert "." + marker in css
    assert 'data-member-pane="kline"' not in js
    for marker in ("openMemberLocalPage", "127.0.0.1:8790/#member"):
        assert marker in js


def test_minute_volume_tab_has_v2_scanner_charts_watchlist_and_events():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    css = (WEB / "assets" / "app.css").read_text(encoding="utf-8")
    assert 'data-view="minute-volume"' in html
    for marker in ("vMinuteVolume", "api/minute-volume", "三日分钟量", "同轴对比",
                   "个股榜", "板块榜", "最近事件", "分钟覆盖", "data-minute-watch"):
        assert marker in js
    for selector in (".minute-volume-page", ".minute-radar-table", ".minute-volume-days",
                     ".minute-price-chart", ".minute-event-timeline"):
        assert selector in css


def test_minute_volume_tab_polls_only_when_active_and_reuses_watchlist_api():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    refresh = js[js.index("function refreshMinuteVolume"):js.index("function stopMinuteVolume")]
    assert "currentView !== 'minute-volume'" in refresh
    assert "api/minute-volume" in refresh
    assert "api/watchlist" in js
    assert "已加入自选" in js


def test_member_center_integrates_cloud_license_without_reusing_legacy_storage_key():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    for marker in ("memberLicenseCode", "memberActivate", "memberRevalidate", "memberLogout",
                   "授权状态", "到期时间", "剩余天数"):
        assert marker in js
    for marker in ("DSH_LICENSE_KEY", "_dsh_lic_v1", "_dev_fp", "18908/api", "'/activate'", "'/validate'",
                   "activateMemberLicense", "validateMemberLicense", "cloud_user_id"):
        assert marker in js
    license_fn = js[js.index("function licenseJSON"):js.index("function renderMemberLicense")]
    assert "if (memberIsLocalWorkbench()) throw err" in license_fn
    assert "DSH_LICENSE_KEY = '_lic'" not in js


def test_member_center_is_regular_split_page_and_offers_local_helper_download():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    css = (WEB / "assets" / "app.css").read_text(encoding="utf-8")
    assert 'id="memberCenter"' not in html
    assert "member-center-backdrop" not in html
    assert 'role="dialog"' not in html
    for marker in ("vMemberCenter", "currentView = 'member'", "member-helper-download",
                   "JinshiDSH-Workbench-1.0.35.zip", "member-guide.html", "memberOpenLocalPage"):
        assert marker in js
    assert "memberRetryHelper" not in js
    for selector in (".member-page", ".member-page-nav", ".member-page-content"):
        assert selector in css
    assert ".member-page{position:fixed" not in css


def test_member_center_uses_integrated_workbench_information_architecture():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8-sig")
    for marker in ("工作台总览", "会员授权", "通达信数据", "安装与升级", "使用指南",
                   "memberWorkbenchVersion", "memberWorkbenchDataRoot", "memberSyncState", "memberDataIntegrity",
                   "memberCalculationState", "memberVipdoc", "memberTdxRoot",
                   "memberSaveConfig", "memberGenerateKline"):
        assert marker in js
    assert 'data-member-pane="service">本地助手' not in js
    assert "memberIsLocalWorkbench" in js
    assert "/api/system/status" in js
    assert "/api/member/config" in js
    assert "/api/member/generate" in js


def test_member_center_exposes_versioned_tab_update_flow():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8-sig")
    for marker in ("memberCheckUpdate", "memberLatestVersion", "memberUpdateState",
                   "member-workbench-latest.json", "/api/system/update", "检查更新", "TAB 页面和功能"):
        assert marker in js


def test_member_center_explains_public_sync_scope_and_progress():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8-sig")
    for marker in ("memberSyncDetail", "正在下载公共数据", "已同步，正在检查增量",
                   "竞价雷达", "策略模型", "历史选股", "file_count", "total_bytes"):
        assert marker in js


def test_member_center_explains_history_archives_are_downloaded_on_demand():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8-sig")
    for marker in ("题材库", "板块强度", "领涨原因", "history_archive",
                   "历史归档按需下载", "切换历史日期时自动下载并缓存", "available_days"):
        assert marker in js


def test_member_center_registers_and_activates_five_day_trial():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8-sig")
    for marker in ("memberTrialName", "memberTrialPhone", "memberRegisterTrial",
                   "/trial/register", "免费试用 5 天", "registerMemberTrial"):
        assert marker in js


def test_theme_and_sector_reference_layout_hooks_exist():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    for marker in ("theme-workbench", "theme-sidebar", "theme-detail", "theme-live",
                   "sector-workbench", "sector-sidebar", "sector-detail", "sector-stock-table"):
        assert marker in js


def test_theme_detail_uses_original_three_column_concept_hierarchy():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    css = (WEB / "assets" / "app.css").read_text(encoding="utf-8")
    assert "当日涨停数排序" in js
    assert "theme_limitup" in js
    for marker in ("concept-table", "td-l1", "td-l2", "td-stocks", "stock-pill", "theme-stock-grid"):
        assert marker in js
        assert "." + marker in css


def test_theme_sidebar_expands_daily_concepts_and_cards_only_limitups():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    assert "theme_concept_limitup" in js
    assert "theme-concept-children" in js
    assert "theme-concept-row" in js
    assert "该题材当日暂无涨停股" in js
    assert "sourceCount > 1" in js


def test_concept_click_has_right_table_anchor_and_popup_is_viewport_adaptive():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    css = (WEB / "assets" / "app.css").read_text(encoding="utf-8")
    for marker in ("data-concept-key", "locateThemeConcept", "scrollTo", "concept-target"):
        assert marker in js or marker in css
    assert "place(pop" in js
    assert "renderDetail(sid, pop" in js
    assert "window.visualViewport" in js
    assert "maxHeight" in js


def test_theme_has_archive_date_selector_and_realtime_toggle():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    css = (WEB / "assets" / "app.css").read_text(encoding="utf-8")
    for marker in ("themeDateSel", "themeRealtimeToggle", "api/intraday/latest",
                   "themeRealtimeTimer", "今日实时", "历史收盘"):
        assert marker in js
    assert ".theme-mode-controls" in css
    assert ".theme-realtime-toggle" in css


def test_auction_radar_tab_separates_potential_tradability_and_confirmation():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    css = (WEB / "assets" / "app.css").read_text(encoding="utf-8")
    assert 'data-view="auction"' in html
    for marker in ("vAuctionRadar", "startAuctionRadar", "auctionRadarTimer",
                   "baseline_quality", "config_version", "今日暂无高质量候选",
                   "涨停潜力", "可买性", "开盘确认", "候选排行榜", "风险",
                   "公共雷达独立运行"):
        assert marker in js
    assert "涨停概率" not in js
    for selector in (".auction-radar", ".auction-health", ".auction-groups", ".auction-candidate"):
        assert selector in css
    assert "@media(max-width:760px)" in css


def test_auction_radar_polls_only_while_its_tab_is_active():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    refresh = js[js.index("function refreshAuctionRadar"):js.index("function stopAuctionRadar")]
    assert "currentView !== 'auction'" in refresh
    handler = js[js.index("tab.addEventListener('click'"):js.index("$('dateSel').addEventListener('change'")]
    assert "nextView !== 'auction'" in handler and "stopAuctionRadar()" in handler
    assert "nextView === 'auction'" in handler and "startAuctionRadar()" in handler


def test_auction_radar_is_public_and_does_not_depend_on_member_helper():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    auction = js[js.index("function auctionCandidate"):js.index("function stopAuctionRadar")]
    refresh = js[js.index("function refreshAuctionRadar"):js.index("function stopAuctionRadar")]
    assert "fetchJSON(url, 'no-store')" in refresh
    assert "loadMemberLocalRealtime" not in refresh
    assert "Promise.all" not in refresh
    assert "localRadar" not in refresh
    for private_marker in ("本地LC1", "本地形态", "local_merged", "local_pattern", "local_baseline"):
        assert private_marker not in auction
    assert "公共雷达独立运行" in auction
    assert "公共分钟基线" in auction


def test_auction_radar_has_isolated_member_local_depth_controls():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    css = (WEB / "assets" / "app.css").read_text(encoding="utf-8")
    for marker in ("loadLocalAuctionStatus", "testLocalAuctionConnection",
                   "controlLocalAuction", "/api/auction/status",
                   "/api/auction/test-connection",
                   "/api/auction/latest",
                   "credentials: 'include'", "data-auction-local"):
        assert marker in js
    assert "'/api/auction/' + action" in js
    assert 'data-auction-local="start"' in js and 'data-auction-local="stop"' in js
    assert 'class="auction-local-control"' in js
    assert 'class="auction-local-results"' in js
    assert ".auction-local-control" in css
    refresh = js[js.index("function refreshAuctionRadar"):js.index("function stopAuctionRadar")]
    assert "fetchJSON(url, 'no-store')" in refresh


def test_auction_radar_has_yesterday_limitup_filter_and_source_marker():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    auction = js[js.index("function auctionOnePrice"):js.index("function stopAuctionRadar")]
    assert "candidate_source === 'yesterday_limitup'" in auction
    assert "auctionFilterButton('yesterday', '昨日涨停'" in auction


def test_auction_radar_has_depth_pattern_and_volume_break_filters_without_sector_flow_gate():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    auction = js[js.index("function auctionOnePrice"):js.index("function stopAuctionRadar")]
    for marker in ("auctionDepthFilter", "auctionVolumeFilter", "data-auction-depth-filter",
                   "data-auction-volume-filter", "撤单承接", "强封控盘", "撤单转弱",
                   "竞价量超昨峰", "封单撤减",
                   "匹配量增长", "买转卖次数"):
        assert marker in js
    for removed in ("open_peak_break", "double_peak_break", "开盘量超昨峰", "双爆确认", "open_peak_ratio"):
        assert removed not in auction
    assert "money_flow_confirmation" not in auction


def test_auction_radar_falls_back_to_public_trajectory_when_depth_was_not_collected():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    auction = js[js.index("function auctionOnePrice"):js.index("function stopAuctionRadar")]
    for marker in ("function auctionDepthAvailable", "今日未采集eltdx深度",
                   "继续显示腾讯轨迹观察", "if (depthAvailable)",
                   "auctionFilter === 'focus' ? sorted.slice(0, 50) : sorted"):
        assert marker in auction


def test_auction_radar_uses_ranked_master_detail_terminal_workbench():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    css = (WEB / "assets" / "app.css").read_text(encoding="utf-8")
    auction = js[js.index("function auctionOnePrice"):js.index("function stopAuctionRadar")]
    for marker in ('class="auction-filterbar"', "auctionFilterButton('focus'",
                   "auctionFilterButton('tradable'", "auctionFilterButton('yesterday'",
                   "auctionFilterButton('oneprice'", "auctionFilterButton('risk'",
                   "auctionFilterButton('all'", 'class="auction-ranking"',
                   'class="auction-inspector"', 'data-auction-sid=',
                   'data-auction-toggle="ratio"', 'data-auction-toggle="non-one-price"',
                   'data-auction-toggle="resonance"'):
        assert marker in auction
    for marker in ("auctionSelectedId", "auctionFilter", "auctionVisibleRows",
                   "selectAuctionOffset"):
        assert marker in js
    assert ".auction-terminal" in css
    assert ".auction-table-wrap" in css
    assert "overflow:auto" in css
    assert "position:sticky" in css


def test_auction_radar_uses_readable_chinese_labels_reasons_and_column_alignment():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    css = (WEB / "assets" / "app.css").read_text(encoding="utf-8")
    auction = js[js.index("function auctionLabel"):js.index("function stopAuctionRadar")]
    for marker in ("function auctionTrajectoryLabel", "涨停撤单承接", "稳步增强", "尾盘抢筹",
                   "待开盘确认", "暂不关注", "可重点关注", "上涨逻辑（昨日涨停原因）",
                   "limitup_reason", "limitup_detail", "limitup_boards", "limitup_concepts",
                   "function auctionEvidenceLabel"):
        assert marker in auction
    assert "esc(row.trajectory || '-')" not in auction
    assert "esc(item)" not in auction
    for selector in (".auction-ranking th:nth-child(1)", ".auction-ranking td:nth-child(1)",
                     ".auction-ranking th:nth-child(2)", ".auction-ranking td:nth-child(2)"):
        assert selector in css
    assert "text-align:left!important" in css
    assert "text-align:right!important" in css or "text-align:center!important" in css


def test_auction_radar_shows_live_trajectory_observation_and_resolved_open_status():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    css = (WEB / "assets" / "app.css").read_text(encoding="utf-8")
    auction = js[js.index("function auctionLabel"):js.index("function stopAuctionRadar")]
    for marker in ("not_confirmed: '截至当前未获确认'", "trajectory_stats",
                   "今日轨迹观察", "当前封板", "样本", "current_limit_rate || 0) * 100"):
        assert marker in auction
    assert ".auction-trajectory-stats" in css


def test_auction_trajectory_observation_cards_filter_candidate_rows():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    css = (WEB / "assets" / "app.css").read_text(encoding="utf-8")
    auction = js[js.index("function auctionTrajectoryLabel"):js.index("function stopAuctionRadar")]
    for marker in ("auctionTrajectoryFilter", "data-auction-trajectory", "全部轨迹",
                   "row.trajectory !== auctionTrajectoryFilter", "aria-pressed"):
        assert marker in auction or marker in js[:js.index("function stopAuctionRadar")]
    handlers = js[js.index("document.addEventListener('click'"):]
    assert "dataset.auctionTrajectory" in handlers
    assert ".auction-trajectory-stats button.active" in css


def test_auction_radar_shows_relative_auction_and_theme_percentile_dimensions():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    auction = js[js.index("function auctionRow"):js.index("function stopAuctionRadar")]
    for marker in ("auction_yesterday_amount_ratio", "auction_turnover",
                   "sector_gap_percentile", "sector_auction_amount_percentile",
                   "竞昨比", "竞换手", "题材内涨幅分位", "题材内竞价额分位",
                   "竞价深度暂缺", "source_capabilities", "09:15–09:25过程"):
        assert marker in auction


def test_tab_switch_commits_view_before_starting_realtime_pollers():
    """实时刷新函数会检查 currentView；必须先切视图再启动，否则首次刷新被吞且不再续跑。"""
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    handler = js[js.index("tab.addEventListener('click'"):js.index("$('dateSel').addEventListener('change'")]
    commit = handler.index("currentView = nextView")
    assert commit < handler.index("startThemeRealtime()")
    assert commit < handler.index("startStratRealtime()")


def test_entering_theme_and_strategy_tabs_starts_today_realtime():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    handler = js[js.index("tab.addEventListener('click'"):js.index("$('dateSel').addEventListener('change'")]
    assert "nextView === 'theme'" in handler
    assert "startThemeRealtime()" in handler
    assert "nextView === 'theme' && !themeRealtime && isMarketSession()" in handler
    assert "nextView === 'strategy'" in handler
    assert "startStratRealtime()" in handler


def test_market_session_keeps_last_realtime_snapshot_until_archive_window():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    assert "minutes < 15 * 60 + 30" in js
    assert "currentView === 'theme' && isMarketSession()" in js


def test_strategy_realtime_stops_after_market_session_and_falls_back_to_archive():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    load_index = js[js.index("function loadIndex()"):
                    js.index("function loadDay(")]
    assert "currentView === 'strategy' && !stratManualArchive && isMarketSession()" in load_index

    refresh = js[js.index("function refreshStratRealtime()"):
                 js.index("function startStratRealtime()")]
    assert "payload.data_date === localToday() && isMarketSession()" in refresh

    handler = js[js.index("tab.addEventListener('click'"):
                 js.index("$('dateSel').addEventListener('change'")]
    strategy_entry = handler[handler.index("if (nextView === 'strategy'"):]
    assert "if (isMarketSession())" in strategy_entry
    assert "sel.value = currentDay" in strategy_entry

    startup = js[js.index("/* 策略页直达"):
                 js.index("})();", js.index("/* 策略页直达"))]
    assert "isMarketSession()" in startup


def test_strategy_realtime_merges_member_local_model_hits():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    refresh = js[js.index("function refreshStratRealtime"):
                 js.index("function startStratRealtime")]
    assert "loadMemberLocalRealtime()" in refresh
    assert "mergeMemberLocalRealtime(payload, rs[2])" in refresh


def test_theme_live_uses_shared_chinese_event_identity_and_minute_groups():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    css = (WEB / "assets" / "app.css").read_text(encoding="utf-8")
    for marker in ("signalEventTimeline", "signal-event-time-group", "signal-event-stock",
                   "signalStockName(e.stock_id, e.name)", "signal_hit"):
        assert marker in js
    assert ".signal-event-time-group" in css
    assert ".signal-event-stock" in css


def test_theme_live_reuses_signal_event_timeline_and_member_event_merge():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    theme_live = js[js.index("function renderThemeLive"):js.index("function localToday")]
    assert "signalEventTimeline(view.events || [])" in theme_live
    assert "live-model-stock" not in theme_live
    refresh = js[js.index("function refreshThemeRealtime"):js.index("function startThemeRealtime")]
    assert "loadMemberLocalRealtime()" in refresh
    assert "mergeMemberLocalRealtime(payload, local)" in refresh


def test_strategy_page_has_separate_daily_and_weekly_model_pools_without_top300_cutoff():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    for marker in ("weekly_platform_breakout", "weekly_pullback", "weekly_macd_second_cross",
                   "weekly_ma_bull", "weekly_double_volume", "isWeeklyModel",
                   "rowInModelPool", "日线模型池 · 按胜率", "周线模型池 · 按胜率"):
        assert marker in js
    current_rows = js[js.index("function currentStratRows()"):
                      js.index("function stratKpiHtml")]
    assert "slice(0, 300)" not in current_rows
    assert "f.kind === 'pool'" in js
    assert "日线覆盖" in js and "周线覆盖" in js
    assert "Object.keys(MODEL_CN).forEach" in js
    assert "当日零命中也显示 0 只" in js
    assert "sandwich: '㉓夹心板'" in js
    assert "18 模型" in js
    assert "'/18'" in js


def test_shared_live_group_uses_compact_event_rows():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    css = (WEB / "assets" / "app.css").read_text(encoding="utf-8")
    for marker in ("signal-event-group-head", "signal-event-row", "signal-event-stock"):
        assert marker in js
        assert "." + marker in css


def test_realtime_limitup_card_marks_reused_reason_date():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    assert "reason_is_history" in js
    assert "reason_date" in js
    assert "沿用" in js


def test_archived_sector_intraday_and_actionable_signal_are_rendered():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    assert "detail.intraday" in js
    assert "drawSectorIntraday" in js
    assert "actionable_alerts" in js
    assert "可买预警" in js


def test_signal_dashboard_renders_market_context_before_actionable_alerts():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    css = (WEB / "assets" / "app.css").read_text(encoding="utf-8")
    for marker in ("signal-market-dashboard", "market-index-grid", "market-breadth",
                   "上证指数", "市场温度", "上涨家数", "下跌家数"):
        assert marker in js
    assert js.index("signal-market-dashboard") < js.index("可买预警")
    for selector in (".signal-market-dashboard", ".market-index-grid", ".signal-decision-grid"):
        assert selector in css
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert "v=0.4.79-leading-date-guard" in html
    assert "signalDataIsToday" in js
    assert "最近收盘" in js


def test_signal_dashboard_highlights_temperature_and_shows_kdj_position_formula():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    css = (WEB / "assets" / "app.css").read_text(encoding="utf-8")
    for marker in ("market-temperature-value", "market-position-card", "index_kdj_j",
                   "position_size", "(100 / J值) + 1"):
        assert marker in js
    for selector in (".market-temperature-value", ".market-position-card"):
        assert selector in css


def test_intraday_event_stream_prefers_chinese_stock_name():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    assert "signalStockName(e.stock_id, e.name)" in js
    assert "evt-stock-code" in js


def test_signal_events_group_by_minute_and_sector_cards_show_limitups():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    css = (WEB / "assets" / "app.css").read_text(encoding="utf-8")
    for marker in ("signalEventTimeline", "signal-event-time-group", "本分钟", "signal-sector-limitups",
                   "limitup_stocks", "signalLimitupPills"):
        assert marker in js
    for selector in (".signal-event-time-group", ".signal-event-group-head", ".signal-sector-limitups"):
        assert selector in css
    assert "selectSignalTimelineEvents" in js
    assert "themeReserve" in js


def test_signal_event_timeline_renders_theme_live_plate_and_related_stocks():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    css = (WEB / "assets" / "app.css").read_text(encoding="utf-8")
    for marker in ("theme_live", "themeku_live", "signal-live-plate", "signal-live-stocks",
                   "change_pct", "题材直播"):
        assert marker in js
    assert ".signal-live-plate" in css
    assert ".signal-live-stocks" in css


def test_member_and_public_realtime_events_are_stably_deduplicated():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    assert "function mergeSignalEvents" in js
    assert "event.source || ''" in js
    assert "event.ts || ''" in js
    member_merge = js[js.index("function mergeMemberLocalRealtime"):js.index("function postJSON")]
    assert "mergeSignalEvents" in member_merge


def test_signal_date_selector_separates_today_realtime_from_history_archive():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    for marker in ("signalRealtimeMode", "当天 · 实时", "归档收盘", "signalDateStatus"):
        assert marker in js
    assert "signalRealtimeMode && signalRealtimePayload" in js
    signal_today = "currentView === 'signal'"
    assert signal_today in js[js.index("$('dateSel').addEventListener('change'"):]
    assert "stopSignalRealtime()" in js[js.index("$('dateSel').addEventListener('change'"):]


def test_history_tab_uses_chinese_identity_four_dimension_labels_and_watchlist_action():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    css = (WEB / "assets" / "app.css").read_text(encoding="utf-8")
    for marker in ("history-shell", "history-summary", "history-stock-name", "history-stock-code",
                   "模型确认", "板块强度", "资金流入", "领涨原因", "history-watch-btn",
                   "api/watchlist", "MODEL_CN"):
        assert marker in js
    for selector in (".history-shell", ".history-summary", ".history-stock-name",
                     ".history-confirm-grid", ".history-watch-btn"):
        assert selector in css


def test_history_tab_uses_split_layout_and_sorts_four_dimensions_by_stars():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    css = (WEB / "assets" / "app.css").read_text(encoding="utf-8")
    for marker in ("history-workbench", "history-sidebar", "history-main", "history-pool-nav",
                   "historyPoolKind", "historySortRows", "confirmCount", "最高确认"):
        assert marker in js
    for marker in ("loadHistoryDatePools", "api/pools?date=", "memberPoolLoaded"):
        assert marker in js
    assert "Number(b.entry.stars || 0) - Number(a.entry.stars || 0)" in js
    for selector in (".history-workbench", ".history-sidebar", ".history-main", ".history-pool-nav"):
        assert selector in css


def test_signal_actionable_alerts_show_four_dimension_stars_and_watchlist_action():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    css = (WEB / "assets" / "app.css").read_text(encoding="utf-8")
    for marker in ("signal-confirm-grid", "signal-alert-stars", "模型确认", "板块强度",
                   "资金流入", "领涨原因", "signal-watch-btn", "data-signal-watch"):
        assert marker in js
    for selector in (".signal-confirm-grid", ".signal-alert-stars", ".signal-watch-btn"):
        assert selector in css
    assert ".signal-watch-cell" in css and "right:0" in css


def test_signal_actionable_confirmation_uses_compact_labels_and_icon_watch_button():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    css = (WEB / "assets" / "app.css").read_text(encoding="utf-8")
    signal = js[js.index("function vSignal(view)"):js.index("function stopSignalRealtime()")]
    for label in ("confirmTag('模型'", "confirmTag('板块'", "confirmTag('资金'", "confirmTag('领涨'"):
        assert label in signal
    assert "aria-label=\"加入自选\"" in signal
    assert "selected ? '✓' : '+'" in signal
    assert "width:28px" in css and "border-radius:50%" in css


def test_signal_stock_names_fall_back_to_local_chinese_name_dictionary():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    signal = js[js.index("function signalStockName"):js.index("function stopSignalRealtime()")]
    assert "(LIBS.stocks_slim || {})[stockId]" in signal
    assert "signalStockName(e.stock_id, e.name)" in signal
    assert "signalStockName(stock.stock_id, stock.name)" in signal
    assert "signalStockName(e.stock_id, e.name)" in signal
    assert "e.name || e.stock_id" not in signal


def test_leading_reason_tab_uses_realtime_source_and_updates_signal_card():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    css = (WEB / "assets" / "app.css").read_text(encoding="utf-8")
    assert 'data-view="leading"' in html
    for marker in ("vLeadingReason", "leading-workbench", "leading-sidebar", "leading-detail",
                   "data-leading-id", "领涨原因 · 实时", "signalRealtimePayload.leading_reason"):
        assert marker in js
    assert "'leading'" in js[js.index("var VALID_VIEWS"):]
    for selector in (".leading-workbench", ".leading-sidebar", ".leading-detail", ".leading-stock-grid"):
        assert selector in css


def test_today_empty_leading_reason_never_falls_back_to_yesterday_archive():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    render = js[js.index("function render()"):
                js.index("else if (currentView === 'auction')")]
    assert "leading_reason: signalDataIsToday ? (signalRealtimePayload.leading_reason || [])" in render


def test_signal_actionable_star_confirm_watch_columns_are_compact_and_sticky():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    css = (WEB / "assets" / "app.css").read_text(encoding="utf-8")
    for marker in ('class="signal-star-cell"', 'class="signal-confirm-cell"', 'class="signal-watch-cell"'):
        assert marker in js
    for selector in (".signal-star-cell", ".signal-confirm-cell", ".signal-watch-cell"):
        assert selector in css
    assert "width:38px" in css and "width:132px" in css and "width:42px" in css
    assert "right:42px" in css and "right:174px" in css
    assert 'class="signal-col-price"' not in js


def test_signal_event_flow_money_flow_and_leading_stocks_have_inline_watch_action():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    css = (WEB / "assets" / "app.css").read_text(encoding="utf-8")
    assert "function signalInlineWatch" in js
    assert js.count("signalInlineWatch(") >= 4
    for marker in ("signal-limitup-pill", "signal-event-stock", "signal-live-stock", "signal-inline-watch"):
        assert marker in js
    assert ".history-watch-btn, .signal-watch-btn, .signal-inline-watch" in js
    assert "实时信号加入" in js
    assert ".signal-inline-watch" in css


def test_signal_realtime_prefers_live_money_flow_and_keeps_archive_fallback():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    assert "signalRealtimePayload.money_flow || []" in js
    assert "view.money_flow || []" in js
    assert "money_flow_ts: signalRealtimePayload.money_flow_ts" in js


def test_signal_page_merges_member_local_realtime_from_helper():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8-sig")
    for marker in ("action=signal", "memberLocalRealtime", "local_actionable_alerts",
                   "本地会员模型"):
        assert marker in js


def test_index_cache_buster_covers_member_center_release():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert html.count("v=0.4.79-leading-date-guard") == 2


def test_sector_leading_and_strategy_stocks_have_inline_watch_action():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    css = (WEB / "assets" / "app.css").read_text(encoding="utf-8")
    assert "signalInlineWatch(r.stock_id, sectorRealtime" in js
    assert "signalInlineWatch(stock.stock_id, view.signal_ts" in js
    assert "signalInlineWatch(r.stock_id, stratRealtime" in js
    for marker in ("sector-stock-identity", "leading-stock-identity", "strategy-stock-identity"):
        assert marker in js
        assert "." + marker in css
    sector_start = js.index("function vSector")
    assert "loadWatchlistState();" in js[sector_start:sector_start + 500]
    for function_name in ("vLeadingReason", "vStrategy"):
        start = js.index("function " + function_name)
        assert "loadHistoryAssets();" in js[start:start + 500]
    assert "['history', 'signal', 'sector', 'leading', 'strategy'].indexOf(currentView)" in js


def test_sector_first_paint_and_live_breadth_do_not_wait_for_expand_libs():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    sector = js[js.index("function vSector(view)"):js.index("function chinesePositionRank")]
    first_view = sector[sector.index("function vSector(view)"):sector.index("function renderSectorWorkbench")]
    assert "renderSectorWorkbench(view);" in first_view
    assert "refreshSectorBreadth(view);" in first_view
    assert "loadExpandLibs()" not in first_view
    for marker in ("mergeSectorRealtimeRows", "sectorBreadthRows", "renderSectorRankList",
                   "sectorRealtimePendingKey", "sectorRealtimeRequestSeq"):
        assert marker in sector or marker in js[:js.index("function vSector(view)")]
    assert "renderSectorRankList(view);" in sector
    assert "refreshSectorRealtime();" in js[js.index("var sectorRank ="):js.index("var sectorSub =")]


def test_sector_trend_drives_archive_and_strength_ui_is_semantic():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    css = (WEB / "assets" / "app.css").read_text(encoding="utf-8")
    for marker in ("data-trend-date", "data-trend-sid", "selectSectorTrend", "sectorTrendExpanded",
                   "sector-rank-sub", "sector-strength-hot", "sector-sub-hot",
                   "dragon-position dragon-1", "dragon-position dragon-2", "dragon-position dragon-3"):
        assert marker in js
    handler = js[js.index("document.addEventListener('click'"):]
    assert "selectSectorTrend(trendCell.dataset.trendDate, trendCell.dataset.trendSid)" in handler
    assert "sectorTrendExpanded = !trendDetails.open" in handler
    assert "Number(sub.strength || 0) > 1900" in js
    assert "Number(s.strength || 0) >= 4000" in js
    heads = js[js.index("var heads = [['code'"):js.index("var headHtml", js.index("var heads = [['code'"))]
    assert heads.index("['reason','涨停原因'") < heads.index("['boards','连板'") < heads.index("['change','涨跌幅'")
    for selector in (".sector-trend-cell", ".sector-rank-sub", ".sector-strength-hot",
                     ".sector-sub-chip.sector-sub-hot", ".sector-reason-col",
                     ".dragon-position.dragon-1", ".dragon-position.dragon-2", ".dragon-position.dragon-3"):
        assert selector in css


def test_sector_rank_selection_links_matching_cells_across_trend_days():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    css = (WEB / "assets" / "app.css").read_text(encoding="utf-8")
    sync = js[js.index("function syncSectorTrendHighlight"):js.index("function loadSectorStocks")]
    assert "cell.classList.toggle('sector-linked', cell.dataset.trendSid === selectedSectorId)" in sync
    assert "cell.classList.toggle('selected'" in sync
    assert ".sector-trend-cell.sector-linked" in css
    assert ".sector-trend-cell.selected" in css
    assert "#ff4d57" in css and "#d92d3a" in css
    assert "rgba(255,77,87,.32)" in css


def test_sector_realtime_view_does_not_mutate_archived_day_cache():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    for marker in ("sectorRealtimeView", "activeSectorView", "cloneSectorView"):
        assert marker in js
    realtime = js[js.index("function refreshSectorRealtime"):js.index("function navigateSectorDay")]
    assert "var view = activeSectorView();" in realtime
    assert "var view = CACHE[currentDay];" not in realtime
    handlers = js[js.index("var sectorRank ="):js.index("var chartToggle =")]
    assert handlers.count("activeSectorView()") >= 2
    assert "sectorRealtimeView = null" in js[js.index("function selectSectorTrend"):]
    assert ".sector-trend-cell.sector-linked,.sector-trend-cell.selected" in (WEB / "assets" / "app.css").read_text(encoding="utf-8")


def test_sector_realtime_bootstraps_ranking_when_archived_sectors_are_empty():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    realtime = js[js.index("function refreshSectorRealtime"):js.index("function navigateSectorDay")]
    assert "if (!sectorRealtime) return;" in realtime
    assert "var bootstrap = !selectedSectorId;" in realtime
    assert "api/sectors/realtime" in realtime
    assert "selectedSectorId = data.sectors[0].id" in realtime


def test_history_watchlist_enriches_model_stars_and_confirm_from_source_date_pool():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    for marker in ("HISTORY_SOURCE_POOLS", "loadHistorySourcePools", "enrichHistoryWatchlist",
                   "source_date", "sourcePools.alert", "sourcePools.candidate"):
        assert marker in js
    assert "Object.assign({}, detail, entry)" in js
    assert "HISTORY_SOURCE_POOLS[sourceDate] ||" in js
    history = js[js.index("function vHistory(view)"):js.index("/* ---------- 原因弹窗")]
    assert "enrichHistoryWatchlist" in history


def test_history_uses_selected_day_watchlist_and_exposes_total_counts():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    history = js[js.index("function vHistory(view)"):js.index("/* ---------- 原因弹窗")]
    assert "var watchPool = enrichHistoryWatchlist(currentWatch, pools, view.date || currentDay);" in history
    assert "view.pool_summary" in history
    assert "当前会员本地自选" in history
    assert "会员自选只保存在本机" in js
    handlers = js[js.index("document.querySelectorAll('.tab')"):js.index("$('dateSel').addEventListener")]
    assert "nextView === 'history'" in handlers
    assert "isMarketSession() ? SECTOR_TODAY_VALUE : currentDay" in handlers
    assert "DATA_VIEW_REV" in js
    assert "20260828-intraday-close-boundary-v1" in js


def test_history_uses_today_realtime_pool_without_changing_archived_days():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    render = js[js.index("function render()") : js.index("function renderEmpty")]
    assert "history_pools" in render
    assert "history_pool_summary" in render
    handlers = js[js.index("document.querySelectorAll('.tab')") : js.index("document.addEventListener('click'")]
    assert "nextView === 'history'" in handlers
    assert "startSignalRealtime" in handlers
    assert "currentView === 'history'" in handlers


def test_auction_radar_displays_public_baseline_and_volume_ratio():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    auction = js[js.index("function auctionOnePrice"):js.index("function stopAuctionRadar")]
    assert "baseline_source" in auction
    assert "baseline_source_date" in auction
    assert "auction_max_1m_volume_ratio" in auction
    assert "昨日最大1分钟" in auction
    assert "公共分钟基线" in auction


def test_historical_auction_radar_is_lazy_loaded_from_isolated_file():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    assert "AUCTION_ARCHIVE" in js
    assert "function loadAuctionArchive" in js
    assert "day_" in js[js.index("function loadAuctionArchive"):js.index("function auctionLabel")]
    render = js[js.index("else if (currentView === 'auction')"):js.index("else if (currentView === 'minute-volume')")]
    assert "AUCTION_ARCHIVE[currentDay]" in render


def test_leading_reason_tab_has_expected_leader_candidate_mode():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    css = (WEB / "assets" / "app.css").read_text(encoding="utf-8")
    for marker in ("expected_leaders", "预期领涨候选", "仅事件预期", "当前领涨候选",
                   "不构成确定性预测或买入结论", "data-leading-mode"):
        assert marker in js
    for selector in (".leading-mode-switch", ".expected-event-card", ".expected-evidence-grid"):
        assert selector in css


def test_expected_leaders_use_compact_three_pane_workbench():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    css = (WEB / "assets" / "app.css").read_text(encoding="utf-8")
    for marker in ("expected-range-nav", "expected-table-pane", "expected-detail-pane",
                   "expectedRange", "expectedStatusFilter", "expectedHasLeaderOnly",
                   "expectedHasLimitupOnly", "今天", "明天", "未来30天", "31–90天", "91–183天", "催化观察",
                   "仅看有领涨股", "仅看有涨停", "data-expected-id"):
        assert marker in js
    assert "expected-candidate-grid" not in js
    for selector in (".expected-workbench", ".expected-range-nav", ".expected-table",
                     ".expected-detail-pane", ".expected-filterbar", ".expected-date-row"):
        assert selector in css
    assert "position:sticky" in css[css.index(".expected-table"):]


def test_expected_leaders_cover_half_year_and_distinguish_watch_items():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    for marker in ("未来30天", "31–90天", "91–183天", "催化观察",
                   "event_kind", "source_evidence", "evidence_grade", "日期待确认"):
        assert marker in js


def test_expected_detail_lists_only_evidence_backed_related_stocks():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    css = (WEB / "assets" / "app.css").read_text(encoding="utf-8")
    for marker in ("buildExpectedRelatedStocks", "matchExpectedThemeIds", "theme_stocks",
                   "所属板块资金流入", "盘中异动", "涨停", "模型命中", "当前领涨",
                   "相关活跃个股", "没有同时具备题材归属和活跃证据的个股"):
        assert marker in js
    assert "Math.random" not in js[js.index("function buildExpectedRelatedStocks"):js.index("function vExpectedLeaders")]


def test_expected_related_stocks_union_sector_members_and_render_quote_columns():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    css = (WEB / "assets" / "app.css").read_text(encoding="utf-8")
    for marker in ("matchExpectedSectorIds", "expectedRelatedQuoteCache", "api/expected-related-quotes",
                   "题材/板块成分", "主力净额", "量比", "换手率", "价格"):
        assert marker in js
    related = js[js.index("function buildExpectedRelatedStocks"):js.index("function expectedThemeMoneyFlow")]
    assert "sectorIds.forEach" in related and "memberIds[sid] = true" in related
    assert ".expected-related-table" in css
    for selector in (".expected-related", ".expected-related-row", ".expected-evidence-badge",
                     ".expected-related-empty"):
        assert selector in css


def test_expected_table_is_compact_adds_sector_money_and_expands_related_pane():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    css = (WEB / "assets" / "app.css").read_text(encoding="utf-8")
    table = js[js.index("class=\"expected-table\""):js.index("</thead>", js.index("class=\"expected-table\""))]
    assert "板块资金流入" in table
    assert "领涨幅" not in table and "自选" not in table
    for marker in ("expectedThemeMoneyFlow", "matched_positive_sector_count", "expected-related-list"):
        assert marker in js
    related = js[js.index("function buildExpectedRelatedStocks"):js.index("function vExpectedLeaders")]
    assert ".slice(0, 12)" not in related
    expected = js[js.index("function vExpectedLeaders"):js.index("function stopSignalRealtime")]
    assert "最多12只" not in expected
    assert "width:10em" in css
    assert ".expected-related-list{display:grid" in css
    assert "grid-template-columns:repeat(2,minmax(0,1fr))" in css


def test_expected_table_has_no_horizontal_scroll_and_compact_columns():
    css = (WEB / "assets" / "app.css").read_text(encoding="utf-8")
    expected_css = css[css.index(".expected-leaders"):css.index("/* ===== 历史选股复盘")]
    for marker in ("table-layout:fixed", "overflow-x:hidden", "min-width:0", "width:100%",
                   ".expected-table th:nth-child(3)", ".expected-table th:nth-child(6)",
                   ".expected-table th:nth-child(7)"):
        assert marker in expected_css


def test_theme_search_indexes_nested_concepts_and_reverse_stock_memberships():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    css = (WEB / "assets" / "app.css").read_text(encoding="utf-8")
    search = js[js.index("function matchThemeSearch"):js.index("function renderThemeWorkbench")]
    for marker in ("theme.tree", "level1.n1", "level2.n2", "LIBS.theme_stocks",
                   "LIBS.stocks_slim", "stock.code", "细分", "个股"):
        assert marker in search
    assert "matchThemeSearch(tid, themes[tid], kw)" in js
    assert "theme-search-hit" in js
    assert ".theme-search-hit" in css


def test_theme_master_libraries_use_data_revision_cache_buster():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    html = (WEB / "index.html").read_text(encoding="utf-8")
    load_lib = js[js.index("function loadLib"):js.index("function loadExpandLibs")]
    assert "name + '?v=' + DATA_VIEW_REV" in load_lib
    assert html.count("v=0.4.79-leading-date-guard") == 2


def test_member_historical_signal_uses_private_alert_pool_and_strategy_detail():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    for marker in ("SIGNAL_HISTORY_ACTIONABLE", "loadSignalHistoryActionable",
                   "api/pools?date=", "data/web/strategy_all_", "memberSignalHistoryLoaded"):
        assert marker in js
    merge = js[js.index("function mergeSignalHistoryActionable"):
               js.index("function loadSignalHistoryActionable")]
    assert "pools.alert" in merge
    assert "strategyDoc.list" in merge
    assert "Object.keys(alertPool)" in merge
    assert ".slice(0, 12)" in merge
    assert "signalRealtimeMode" not in merge
    render = js[js.index("function render()"):
                js.index("function vAuctionRadar")]
    assert "!signalRealtimeMode" in render
    assert "loadSignalHistoryActionable" in render
