from pathlib import Path
import subprocess
import json

SCRIPT = Path(__file__).parents[1] / 'deploy' / 'member-process-recovery.ps1'


def test_disabled_recovery_has_no_side_effect(tmp_path):
    result = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                             '-File', str(SCRIPT), '-MemberRoot', str(tmp_path)],
                            capture_output=True, timeout=15)
    assert result.returncode == 0
    assert list(tmp_path.iterdir()) == []


def test_recovery_is_bounded_and_never_kills_live_process():
    script = SCRIPT.read_text(encoding='utf-8-sig')
    for marker in ('Mutex', 'AddMinutes(-15)', '-ge 3', 'Get-NetTCPConnection',
                   'ExecutablePath', 'WindowStyle Hidden', 'current_version', '1048576'):
        assert marker in script
    assert 'Stop-Process' not in script
    assert 'taskkill' not in script


def test_real_powershell_restart_budget_and_disabled_gate(tmp_path):
    app = tmp_path / 'app/versions/1.0.39'
    app.mkdir(parents=True)
    (app / 'JinshiDSH-Workbench.exe').write_bytes(b'fixture')
    data = tmp_path / 'data'
    (tmp_path / 'install_state.json').write_text(json.dumps({
        'install_root': str(tmp_path / 'app'), 'current_version': '1.0.39', 'data_root': str(data)}))
    mocks = """
function Get-NetTCPConnection {}
function Get-CimInstance {}
function Start-Sleep {}
function Start-Process {
    $p = [pscustomobject]@{HasExited=$false;Id=12345}
    $p | Add-Member -MemberType ScriptMethod -Name Refresh -Value {}
    return $p
}
"""
    isolated = tmp_path / 'guard-fixture.ps1'
    isolated.write_text(SCRIPT.read_text(encoding='utf-8-sig').replace(
        'JinshiDSH-MemberRecovery-8790', 'JinshiDSH-Recovery-Test-' + tmp_path.name), encoding='utf-8-sig')
    command = mocks + "\n& '" + str(isolated) + "' -MemberRoot '" + str(tmp_path) + "' -Enabled"
    for _ in range(4):
        result = subprocess.run(['powershell', '-NoProfile', '-Command', command], capture_output=True, timeout=15)
        assert result.returncode == 0, result.stderr
    state = data / 'runtime/member_recovery.json'
    assert len(json.loads(state.read_text())['attempts']) == 3
    log = (data / 'runtime/member_recovery.log').read_text()
    assert log.count('restart_requested') == 3
    (tmp_path / 'recovery').mkdir()
    (tmp_path / 'recovery/recovery.disabled').touch()
    before = state.read_bytes()
    subprocess.run(['powershell', '-NoProfile', '-Command', command], check=True, timeout=15)
    assert state.read_bytes() == before
