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
