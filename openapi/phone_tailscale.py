#!/usr/bin/env python3
"""Private phone access through rootless Tailscale Serve; never enables Funnel."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

IMAGE = 'ghcr.io/tailscale/tailscale@sha256:72c1e19e0aedca96b8533bbb0b4368564410ff20b17e53b804eb6c1f04a31be4'
NAME = 'fxpro-tailscale'
CONFIG = Path.home() / '.config/fxpro-openapi'
STATE = CONFIG / 'tailscale'
SOCKET = '/var/lib/tailscale/tailscaled.sock'

def run(args, capture=False, **kwargs):
    return subprocess.run(args, check=True, text=True, capture_output=capture, **kwargs)

def ts(*args, capture=False):
    return run(['podman', 'exec', NAME, 'tailscale', '--socket=' + SOCKET, *args], capture=capture)

def private(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as output:
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)

def ensure():
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    if subprocess.run(['podman', 'container', 'exists', NAME]).returncode:
        run(['podman', 'run', '--detach', '--name', NAME, '--userns=keep-id', '--network=host',
             '--restart=unless-stopped', '-v', str(STATE) + ':/var/lib/tailscale:Z',
             '--entrypoint', '/usr/local/bin/tailscaled', IMAGE, '--tun=userspace-networking',
             '--state=/var/lib/tailscale/tailscaled.state', '--socket=' + SOCKET])
    else:
        run(['podman', 'start', NAME], capture=True)

def main():
    action = sys.argv[1] if len(sys.argv) == 2 else ''
    if action not in ('login', 'enable', 'status'):
        raise SystemExit('Usage: python3 phone_tailscale.py login|enable|status')
    ensure()
    if action == 'login':
        ts('up', '--hostname=aurum-desk', '--accept-dns=false', '--accept-routes=false', '--timeout=10s')
        return
    status = json.loads(ts('status', '--json', capture=True).stdout)
    dns = status.get('Self', {}).get('DNSName', '').rstrip('.')
    if action == 'status':
        print(json.dumps({'state': status['BackendState'], 'phoneUrl': 'https://' + dns if dns else None}))
        return
    if status['BackendState'] != 'Running' or not re.fullmatch(r'[a-z0-9.-]+\.ts\.net', dns):
        raise SystemExit('Complete Tailscale login and enable MagicDNS, then rerun enable.')
    # Configure the encrypted entry point before moving the existing LAN gateway.
    ts('serve', '--yes', '--bg', '--https=443', 'http://127.0.0.1:8789')
    origin = 'https://' + dns
    private(CONFIG / 'phone-tailscale.env', 'XAU_PHONE_BIND=127.0.0.1\nXAU_PHONE_ORIGIN=' + origin + '\n')
    unit = Path.home() / '.config/systemd/user/fxpro-dashboard-phone.service.d/50-tailscale.conf'
    private(unit, '[Service]\nEnvironmentFile=' + str(CONFIG / 'phone-tailscale.env') + '\n')
    run(['systemctl', '--user', 'daemon-reload'])
    run(['systemctl', '--user', 'restart', 'fxpro-dashboard-phone.service'])
    for attempt in range(40):
        try:
            request = urllib.request.Request('http://127.0.0.1:8789/pair', headers={'Host': dns})
            with urllib.request.urlopen(request, timeout=2) as response:
                assert response.status == 200
            break
        except OSError:
            if attempt == 39: raise
            time.sleep(.25)
    print('Phone dashboard: ' + origin + '/pair')
    print('Use the same Tailscale account on the phone; pair again. The old LAN port is no longer exposed.')

if __name__ == '__main__': main()
