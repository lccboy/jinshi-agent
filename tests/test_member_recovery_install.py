from pathlib import Path
import json
import subprocess
import pytest
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

ROOT = Path(__file__).parents[1]


def test_package_and_primary_installer_integrate_recovery():
    build = (ROOT / 'deploy/build-member-workbench.ps1').read_text(encoding='utf-8-sig')
    install = (ROOT / 'deploy/install-member-workbench.ps1').read_text(encoding='utf-8-sig')
    for name in ('install-member-recovery.ps1', 'member-process-recovery.ps1'):
        assert name in build
    for marker in ('install-member-recovery.ps1', 'JinshiDSH-MemberRecovery-8790',
                   'Wait-WorkbenchHealth', 'recovery.disabled', 'PSBoundParameters.ContainsKey',
                   'ExecutablePath', 'finally'):
        assert marker in install


def test_recovery_supports_persistent_fallback_and_removal():
    install = (ROOT / 'deploy/install-member-recovery.ps1').read_text(encoding='utf-8-sig')
    for marker in ('Unregister-ScheduledTask', 'JinshiDSH-Workbench.vbs',
                   'recovery.disabled', 'Encoding]::Unicode', 'throw'):
        assert marker in install
    guard = (ROOT / 'deploy/member-process-recovery.ps1').read_text(encoding='utf-8-sig')
    assert 'recovery.disabled' in guard


def test_http_listener_acquired_before_starting_member_workers():
    service = (ROOT / 'services/member_local_service.py').read_text(encoding='utf-8')
    main = service[service.index('def main(argv=None):'):]
    assert main.index('ThreadingHTTPServer(') < main.index('start_public_sync(')


def test_duplicate_port_does_not_start_background_workers(tmp_path, monkeypatch):
    from services import member_local_service as service
    calls = []
    monkeypatch.setattr(service, 'start_public_sync', lambda *a, **kw: calls.append('sync'))
    monkeypatch.setattr(service, 'start_member_minute_archive_scheduler', lambda *a, **kw: calls.append('archive'))
    with ThreadingHTTPServer(('127.0.0.1', 0), BaseHTTPRequestHandler) as occupied:
        with pytest.raises(OSError):
            service.main(['--serve', '--data-root', str(tmp_path), '--port', str(occupied.server_port)])
    assert calls == []


def recovery_fixture(tmp_path, denied=False, startup_denied=False):
    package = tmp_path / 'package'
    package.mkdir()
    startup = tmp_path / 'startup'
    startup.mkdir()
    if startup_denied:
        # A directory at the target filename deterministically simulates unwritable startup.
        (startup / 'JinshiDSH-Workbench.vbs').mkdir()
    for name in ('install-member-workbench.ps1', 'install-member-recovery.ps1', 'member-process-recovery.ps1'):
        text = (ROOT / 'deploy' / name).read_text(encoding='utf-8-sig')
        text = text.replace("[Environment]::GetFolderPath('Startup')", "'" + str(startup) + "'")
        # Isolate legacy startup cleanup from the actual user profile as well.
        text = text.replace('Join-Path $env:APPDATA "Microsoft\\Windows\\Start Menu\\Programs\\Startup\\JinshiDSH-Workbench.vbs"',
                            "Join-Path '" + str(startup) + "' 'JinshiDSH-Workbench.vbs'")
        (package / name).write_text(text, encoding='utf-8-sig')
    app = package / 'app/JinshiDSH-Workbench'
    app.mkdir(parents=True)
    (app / 'JinshiDSH-Workbench.exe').write_bytes(b'fixture-not-executable')
    root = tmp_path / 'member'
    private = root / 'custom-data'
    (private / 'runtime').mkdir(parents=True)
    (private / 'runtime/license.json').write_bytes(b'unchanged-license-fixture')
    registration = "throw 'denied'" if denied else "return"
    mocks = "\n".join([
        'function Get-CimInstance {}', 'function Get-ScheduledTask {}',
        'function New-ScheduledTaskAction {}', 'function New-ScheduledTaskTrigger {}',
        'function New-ScheduledTaskPrincipal {}', 'function New-ScheduledTaskSettingsSet {}',
        'function Register-ScheduledTask { ' + registration + ' }',
        'function Start-ScheduledTask {}', 'function Unregister-ScheduledTask {}',
    ])

    def run(version, extra=''):
        (package / 'member-workbench.json').write_text(json.dumps({'version': version, 'entry_exe': 'JinshiDSH-Workbench.exe'}))
        command = mocks + "\n& '" + str(package / 'install-member-workbench.ps1') + "' -PackageRoot '" + str(package) + "' -MemberRoot '" + str(root) + "' -NoLaunch " + extra
        return subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', command],
                              capture_output=True, timeout=30)
    return root, private, startup, run


def test_real_powershell_upgrade_rollback_uninstall_preserve_private_data(tmp_path):
    root, private, startup, run = recovery_fixture(tmp_path)
    first = run('1.0.38', "-DataRoot '" + str(private) + "'")
    assert first.returncode == 0, first.stderr
    assert run('1.0.39').returncode == 0
    state = json.loads((root / 'install_state.json').read_text())
    assert state['data_root'] == str(private)
    assert state['previous_version'] == '1.0.38'
    assert run('1.0.39').returncode == 0
    assert json.loads((root / 'install_state.json').read_text())['previous_version'] == '1.0.38'
    assert run('1.0.39', '-Rollback').returncode == 0
    assert json.loads((root / 'install_state.json').read_text())['current_version'] == '1.0.38'
    assert run('1.0.39', '-Uninstall').returncode == 0
    assert (root / 'recovery/recovery.disabled').is_file()
    assert not (root / 'app').exists()
    assert (private / 'runtime/license.json').read_bytes() == b'unchanged-license-fixture'


def test_real_powershell_task_denied_uses_unicode_startup(tmp_path):
    root, private, startup, run = recovery_fixture(tmp_path, denied=True)
    result = run('1.0.39')
    assert result.returncode == 0, result.stderr
    vbs = (startup / 'JinshiDSH-Workbench.vbs').read_text(encoding='utf-16')
    assert '-Watch' in vbs and 'member-process-recovery.ps1' in vbs


def test_real_powershell_both_persistence_methods_fail_is_not_success(tmp_path):
    root, private, startup, run = recovery_fixture(tmp_path, denied=True, startup_denied=True)
    result = run('1.0.39')
    assert result.returncode != 0
    assert b'[OK]' not in result.stdout
    assert b'Permanent recovery setup failed' in result.stderr
