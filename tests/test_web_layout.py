from pathlib import Path


WEB = Path("apps/web")


def test_default_theme_is_dark_and_uses_obsidian_ruby_tokens():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    css = (WEB / "assets" / "app.css").read_text(encoding="utf-8")
    assert '<html lang="zh-CN" data-theme="dark">' in html
    assert "--c-bg: #12161c" in css.lower()
    assert "--c-primary: #e05555" in css.lower()


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


def test_theme_model_hits_use_chinese_names_and_group_live_feed_by_time():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    css = (WEB / "assets" / "app.css").read_text(encoding="utf-8")
    for marker in ("model_names", "live-time-group", "live-model-stock", "change_pct", "signal_hit"):
        assert marker in js
    assert ".live-time-group" in css
    assert ".live-model-stock" in css


def test_live_group_uses_compact_ranked_stock_rows():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    css = (WEB / "assets" / "app.css").read_text(encoding="utf-8")
    for marker in ("live-group-head", "live-group-count", "live-stock-rank",
                   "live-stock-identity", "live-stock-meta"):
        assert marker in js
        assert "." + marker in css


def test_realtime_limitup_card_marks_reused_reason_date():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    assert "reason_is_history" in js
    assert "reason_date" in js
    assert "沿用" in js
