import json
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_member_workbench_builder_uses_onedir_and_includes_complete_web_assets():
    script = (ROOT / "deploy" / "build-member-workbench.ps1").read_text(encoding="utf-8-sig")
    assert "--onedir" in script
    assert "--onefile" not in script
    for excluded in ("pandas", "torch", "scipy", "matplotlib", "pytest"):
        assert f"--exclude-module {excluded}" in script
    for marker in ("apps\\web", "config\\strategy.json", "services.local_sync",
                   "services.local_license", "install-member-workbench.ps1",
                   "MEMBER-GUIDE.txt", "member-guide.html"):
        assert marker in script
    assert 'apps\\web\\downloads' not in script
    assert "installerBytes.Length -lt 1000" in script
    assert ".venv-auction\\Scripts\\python.exe" in script
    assert "requirements-member-build.txt" in script
    for marker in ("services.auction_control", "services.collector.auction_depth_shadow",
                   "services.collector.auction_source", "services.collector.auction_materialize"):
        assert f"--hidden-import {marker}" in script
    assert "--collect-all eltdx" in script
    for forbidden in ("data\\facts", "data\\kline", "vipdoc", "members\\"):
        assert forbidden not in script


def test_eltdx_is_member_only_and_never_installed_by_server_requirements():
    member_requirements = (ROOT / "deploy" / "requirements-auction-research.txt").read_text(encoding="utf-8")
    server_requirements = (ROOT / "deploy" / "requirements-server.txt").read_text(encoding="utf-8")
    assert "eltdx==3.0.8" in member_requirements
    assert "eltdx" not in server_requirements.lower()
    build_requirements = (ROOT / "deploy" / "requirements-member-build.txt").read_text(encoding="utf-8")
    assert "PyInstaller==6.20.0" in build_requirements
    assert "eltdx==3.0.8" in build_requirements


def test_member_build_collects_eltdx_native_extension_and_smoke_checks_runtime():
    build = (ROOT / "deploy" / "build-member-workbench.ps1").read_text(encoding="utf-8-sig")
    smoke = (ROOT / "deploy" / "smoke-member-workbench.ps1").read_text(encoding="utf-8-sig")
    assert "--collect-all eltdx" in build
    assert "Test-EltdxNativeRuntime" in smoke
    assert "eltdx/_native" in smoke.replace("\\", "/")


def test_member_installer_is_per_user_versioned_and_preserves_data_on_uninstall():
    script = (ROOT / "deploy" / "install-member-workbench.ps1").read_text(encoding="utf-8-sig")
    for marker in ('$MemberRoot = "H:\\JinshiDSH"', "$env:APPDATA", "bootstrap.json",
                   "previous_version", "current_version", "JinshiDSH-Workbench.vbs"):
        assert marker in script
    assert "Remove-Item -LiteralPath $DataRoot" not in script
    assert "-Uninstall" in script
    assert "$NoLaunch" in script
    assert "--serve" in script
    assert "127.0.0.1:8790" in script
    assert '$_.Name -eq "JinshiDSH-Workbench.exe"' in script
    assert "ExecutablePath -like" not in script


def test_member_installer_defaults_to_dedicated_h_drive_root_without_touching_test_nginx():
    script = (ROOT / "deploy" / "install-member-workbench.ps1").read_text(encoding="utf-8-sig")
    assert '[string]$MemberRoot = "H:\\JinshiDSH"' in script
    assert 'Join-Path $MemberRoot "app"' in script
    assert 'Join-Path $MemberRoot "data"' in script
    assert 'Join-Path $MemberRoot "bootstrap.json"' in script
    assert 'Join-Path $MemberRoot "install_state.json"' in script
    assert "H:\\nginx" not in script
    assert "C:\\nginx" not in script

    local_deploy = (ROOT / "deploy" / "deploy-local.ps1").read_text(encoding="utf-8-sig")
    server_install = (ROOT / "deploy" / "install-server-collector.ps1").read_text(encoding="utf-8-sig")
    assert '$nginxDir = "H:\\nginx"' in local_deploy
    assert '[string]$Root = "C:\\nginx\\html\\DSH"' in server_install


def test_package_version_matches_local_service_version():
    version = json.loads((ROOT / "deploy" / "member-workbench.json").read_text(encoding="utf-8"))["version"]
    service = (ROOT / "services" / "member_local_service.py").read_text(encoding="utf-8")
    assert f'HELPER_VERSION = "{version}"' in service
    assert 'raise SystemExit(main())' in service


def test_powershell_51_installer_source_has_utf8_bom():
    payload = (ROOT / "deploy" / "install-member-workbench.ps1").read_bytes()
    assert payload.startswith(b"\xef\xbb\xbf")


def test_member_guide_covers_complete_first_run_and_daily_workflow():
    guide = (ROOT / "docs" / "MEMBER_WORKBENCH_GUIDE.md").read_text(encoding="utf-8")
    for marker in ("公网下载地址", "SHA-256", "PowerShell", "云会员授权", "vipdoc",
                   "gbbq", "生成会员 K 线", "监控运行状态", "七个 TAB", "日常使用",
                   "升级", "回滚", "卸载", "HTTP 404"):
        assert marker in guide


def test_server_web_build_publishes_zip_guide_and_excludes_legacy_helper():
    script = (ROOT / "deploy" / "build.ps1").read_text(encoding="utf-8-sig")
    assert "JinshiDSH-Workbench-1.0.42.zip" in script
    assert "JinshiDSH-Workbench-1.0.42.sha256.txt" in script
    assert "member-workbench-latest.json" in script
    assert "MEMBER-GUIDE.txt" in script
    assert "JinshiDSH-MemberHelper.exe" in script
    web = (ROOT / "apps" / "web" / "assets" / "app.js").read_text(encoding="utf-8")
    assert "downloads/JinshiDSH-Workbench-1.0.42.zip" in web
    assert "member-guide.html" in web
