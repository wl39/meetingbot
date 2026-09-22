"""Deploy STT outside Documents and manage a user LaunchAgent.

The source project remains editable in Documents. Its .runtime link points to
one shared state directory, so service and development tools use the same data.
"""
import argparse
import os
import plistlib
import shutil
import subprocess
import time
from pathlib import Path

from support.deployment import replace_code_tree

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = Path.home() / 'Library/Application Support/Meetingbot'
LABEL = 'com.meetingbot.stt'
TARGET = f'gui/{os.getuid()}/{LABEL}'
PLIST = Path.home() / 'Library/LaunchAgents' / f'{LABEL}.plist'
LOGS = Path.home() / 'Library/Logs/Meetingbot'
parser = argparse.ArgumentParser()
parser.add_argument('action', choices=['install', 'status', 'restart', 'stop'])
args = parser.parse_args()


def loaded():
    return subprocess.run(['launchctl', 'print', TARGET], capture_output=True).returncode == 0


def own_definition():
    if not PLIST.exists():
        return
    definition = plistlib.loads(PLIST.read_bytes())
    program = definition.get('ProgramArguments', [''])[0]
    expected = {str(p / 'backend/.venv/bin/python') for p in (ROOT, DEPLOY)}
    if definition.get('Label') != LABEL or program not in expected:
        raise SystemExit('Another application owns this LaunchAgent definition. No changes made.')


def deploy():
    DEPLOY.mkdir(parents=True, exist_ok=True, mode=0o700)
    DEPLOY.chmod(0o700)
    backend = DEPLOY / 'backend'
    backend.mkdir(exist_ok=True)
    venv = backend / '.venv'
    source_lock = ROOT / 'backend/uv.lock'
    previous_lock = backend / 'uv.lock'
    dependency_change = not previous_lock.exists() or previous_lock.read_bytes() != source_lock.read_bytes()
    if not venv.exists():
        # APFS clone; retains links to the uv-managed Python outside Documents.
        subprocess.run(['/bin/cp', '-cR', str(ROOT / 'backend/.venv'), str(venv)], check=True)
    elif dependency_change:
        raise SystemExit('Dependency lock changed. Update the deployed environment before restarting.')
    for name in ('pyproject.toml', 'uv.lock'):
        shutil.copy2(ROOT / 'backend' / name, backend / name)
    replace_code_tree(ROOT / 'backend/app', backend / 'app')
    shutil.copytree(ROOT / 'shared', DEPLOY / 'shared', dirs_exist_ok=True)
    # A cloned virtualenv may still have an editable path into Documents. Resolve
    # the local shared package against the deployed tree before launchd starts it.
    subprocess.run([shutil.which('uv') or '/opt/homebrew/bin/uv', 'sync', '--project', str(backend),
                    '--frozen', '--extra', 'speech', '--no-dev'], check=True)
    shutil.copytree(ROOT / 'frontend/dist', DEPLOY / 'frontend/dist', dirs_exist_ok=True)
    source_state, state = ROOT / '.runtime', DEPLOY / '.runtime'
    if source_state.is_symlink():
        if source_state.resolve() != state:
            raise SystemExit('Unexpected source state link; no data replaced.')
    elif source_state.exists():
        if state.exists():
            raise SystemExit('Two state directories exist; refusing to overwrite either.')
        shutil.move(str(source_state), str(state))
        source_state.symlink_to(state, target_is_directory=True)
    else:
        state.mkdir(exist_ok=True, mode=0o700)
        source_state.symlink_to(state, target_is_directory=True)
    if (ROOT / '.env').exists():
        shutil.copy2(ROOT / '.env', DEPLOY / '.env')
        (DEPLOY / '.env').chmod(0o600)
    return state


own_definition()
if args.action in ('install', 'restart'):
    deployed_lock = DEPLOY / 'backend/uv.lock'
    if deployed_lock.exists() and deployed_lock.read_bytes() != (ROOT / 'backend/uv.lock').read_bytes():
        raise SystemExit('Dependency lock changed. Update the deployed environment before restarting; current service was left running.')
    if loaded():
        subprocess.run(['launchctl', 'bootout', TARGET], check=True)
    state = deploy()
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True, mode=0o700)
    config = {
        'Label': LABEL,
        'ProgramArguments': [str(DEPLOY / 'backend/.venv/bin/python'), '-m', 'uvicorn',
            'app.main:create_app', '--factory', '--host', '127.0.0.1', '--port', '8765',
            '--ws-max-size', '500000', '--ws-max-queue', '8', '--no-access-log'],
        'WorkingDirectory': str(DEPLOY / 'backend'),
        'EnvironmentVariables': {'PATH': '/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin',
            'PYANNOTE_METRICS_ENABLED': '0', 'PYTHONUNBUFFERED': '1', 'STT_DATA_DIR': str(state)},
        'RunAtLoad': True, 'KeepAlive': True, 'ThrottleInterval': 5,
        'StandardOutPath': str(LOGS / 'stdout.log'), 'StandardErrorPath': str(LOGS / 'stderr.log'),
    }
    PLIST.write_bytes(plistlib.dumps(config))
    PLIST.chmod(0o600)
    # bootout can return before launchd releases the label completely.
    for attempt in range(60):
        result = subprocess.run(['launchctl', 'bootstrap', f'gui/{os.getuid()}', str(PLIST)], capture_output=True, text=True)
        if result.returncode == 0:
            break
        if result.returncode != 5 or attempt == 59:
            raise SystemExit(result.stderr.strip() or 'Could not start STT service.')
        time.sleep(0.5)
    print('Persistent STT service installed. Logs:', LOGS)
elif args.action == 'status':
    subprocess.run(['launchctl', 'print', TARGET], check=True)
else:
    subprocess.run(['launchctl', 'bootout', TARGET], check=True)
    print('STT service stopped for this login. Install starts it again; it also starts at next login.')
