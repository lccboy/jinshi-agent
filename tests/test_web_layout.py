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
