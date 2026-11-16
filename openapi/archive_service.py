#!/usr/bin/env python3
"""Run the read-only historical archive independently of trading and live recording."""
from pathlib import Path
import shlex
import subprocess
import sys
from recorder_service import ROOT, IMAGE, run

UNIT = 'fxpro-tick-archive.service'

def main():
    if len(sys.argv) == 2 and sys.argv[1] == 'status':
        path = ROOT / 'data/archive-xauusd/status.json'
        print(path.read_text() if path.exists() else '{"stage":"not-started"}')
        return
    if len(sys.argv) != 1:
        raise SystemExit('Usage: archive_service.py [status]')
    if subprocess.run(['systemctl', '--user', 'is-active', '--quiet', UNIT]).returncode == 0:
        raise SystemExit('Archive already active; use ./api archive-status.')
    runtime = ROOT / 'audit/archive-runtime'
    runtime.mkdir(parents=True, exist_ok=True)
    run(['podman', 'run', '--rm', '--userns=keep-id', '--network=none', '-e', 'DOTNET_CLI_HOME=/tmp',
         '-v', f'{ROOT.parent}:/src:z', '-w', '/src/openapi', IMAGE, 'bash', '-c',
         'dotnet build --no-restore --nologo -o audit/archive-runtime && dotnet audit/archive-runtime/FxProOpenApi.dll check-archive && dotnet audit/archive-runtime/FxProOpenApi.dll check-recorder'])
    command = ['/usr/bin/podman', 'run', '--rm', '--name', 'fxpro-tick-archive', '--userns=keep-id',
               '-e', 'DOTNET_CLI_HOME=/tmp', '-e', 'XAU_CONFIG_DIR=/config',
               '-v', f'{ROOT}:/src:ro,z', '-v', f'{ROOT / "data"}:/src/data:z',
               '-v', f'{Path.home() / ".config/fxpro-openapi"}:/config:ro,z', '-w', '/src', IMAGE,
               'dotnet', '/src/audit/archive-runtime/FxProOpenApi.dll', 'archive-data']
    unit = Path.home() / '.config/systemd/user' / UNIT
    unit.write_text('''[Unit]
Description=Aurum read-only FxPro tick history archive
After=network-online.target
[Service]
UMask=0077
ExecStartPre=/usr/bin/podman rm --ignore fxpro-tick-archive
ExecStart=''' + ' '.join(shlex.quote(x).replace('%', '%%') for x in command) + '''
ExecStop=/usr/bin/podman stop --time 35 fxpro-tick-archive
Restart=on-failure
RestartSec=15
TimeoutStopSec=45
MemoryMax=2G
CPUQuota=100%
[Install]
WantedBy=default.target
''')
    run(['systemctl', '--user', 'daemon-reload'])
    run(['systemctl', '--user', 'enable', '--now', UNIT])
    print('Historical archive started. Status: ./api archive-status. Worker/live recorder unchanged.')

if __name__ == '__main__':
    main()
