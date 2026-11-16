#!/usr/bin/env python3
"""Install only the independent read-only data recorder; never restart execution/UI."""
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
IMAGE = 'mcr.microsoft.com/dotnet/sdk@sha256:1b955f179b02df4f0eb5fadedaa898cbe44d620a64aab52eec72c8e91d1355b5'
UNIT = 'fxpro-data-recorder.service'
RUNTIME = ROOT / 'audit/recorder-runtime'

def run(args):
    subprocess.run(args, check=True)

def unit_text():
    private = Path.home() / '.config/fxpro-openapi'
    command = ['/usr/bin/podman', 'run', '--rm', '--name', 'fxpro-recorder', '--userns=keep-id',
               '-e', 'DOTNET_CLI_HOME=/tmp', '-e', 'XAU_CONFIG_DIR=/config',
               '-v', f'{ROOT}:/src:ro,z', '-v', f'{ROOT / "data"}:/src/data:z',
               '-v', f'{private}:/config:ro,z', '-w', '/src', IMAGE,
               'dotnet', '/src/audit/recorder-runtime/FxProOpenApi.dll', 'record-data']
    return '''[Unit]
Description=Aurum read-only XAUUSD live recorder and historical recovery
After=network-online.target
[Service]
Type=simple
UMask=0077
ExecStartPre=/usr/bin/podman rm --ignore fxpro-recorder
ExecStart=''' + ' '.join(shlex.quote(x).replace('%', '%%') for x in command) + '''
ExecStop=/usr/bin/podman stop --time 35 fxpro-recorder
Restart=on-failure
RestartSec=10
TimeoutStopSec=45
MemoryMax=1G
CPUQuota=100%
[Install]
WantedBy=default.target
'''

def main():
    action = sys.argv[1] if len(sys.argv) == 2 else 'install'
    if action == 'status':
        path = ROOT / 'data/recorder-xauusd/status.json'
        print(path.read_text() if path.exists() else json.dumps({'state': 'not-started'}))
        return
    if action != 'install':
        raise SystemExit('Usage: recorder_service.py [install|status]')
    if subprocess.run(['systemctl', '--user', 'is-active', '--quiet', UNIT]).returncode == 0:
        raise SystemExit('Recorder already running; stop only fxpro-data-recorder.service before updating its isolated runtime.')
    RUNTIME.mkdir(parents=True, exist_ok=True)
    (ROOT / 'data').mkdir(exist_ok=True)
    run(['podman', 'run', '--rm', '--userns=keep-id', '--network=none', '-e', 'DOTNET_CLI_HOME=/tmp',
         '-v', f'{ROOT.parent}:/src:z', '-w', '/src/openapi', IMAGE,
         'bash', '-c', 'dotnet build --no-restore --nologo -o audit/recorder-runtime && dotnet audit/recorder-runtime/FxProOpenApi.dll check-recorder'])
    unit = Path.home() / '.config/systemd/user' / UNIT
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text(unit_text())
    run(['systemctl', '--user', 'daemon-reload'])
    run(['systemctl', '--user', 'enable', '--now', UNIT])
    print('Recorder enabled. Check: ./api recorder-status. Execution/dashboard were not restarted.')

if __name__ == '__main__':
    main()
