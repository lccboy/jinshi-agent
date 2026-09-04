from pathlib import Path
import subprocess

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
