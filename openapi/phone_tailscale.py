#!/usr/bin/env python3
"""Private phone access through the host Tailscale Serve; never enables Funnel."""
import json
import getpass
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

CONFIG = Path.home() / '.config/fxpro-openapi'

def run(args, capture=False, **kwargs):
    return subprocess.run(args, check=True, text=True, capture_output=capture, **kwargs)

def ts(*args, capture=False):
    return run(['tailscale', *args], capture=capture)

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

def main():
    action = sys.argv[1] if len(sys.argv) == 2 else ''
    if action not in ('login', 'enable', 'status'):
        raise SystemExit('Usage: python3 phone_tailscale.py login|enable|status')
    if action == 'login':
        ts('up', '--timeout=10s')
        return
    status = json.loads(ts('status', '--json', capture=True).stdout)
    dns = status.get('Self', {}).get('DNSName', '').rstrip('.')
    if action == 'status':
        print(json.dumps({'state': status['BackendState'], 'phoneUrl': 'https://' + dns if dns else None}))
        return
    if status['BackendState'] != 'Running' or not re.fullmatch(r'[a-z0-9.-]+\.ts\.net', dns):
        raise SystemExit('Complete Tailscale login and enable MagicDNS, then rerun enable.')
    # Configure the encrypted entry point before moving the existing LAN gateway.
    try:
        ts('serve', '--yes', '--bg', '--https=443', 'http://127.0.0.1:8789')
    except subprocess.CalledProcessError:
        raise SystemExit('Host Tailscale Serve needs administrator permission. Run sudo tailscale set --operator=' + getpass.getuser() + ', then rerun enable. Gateway configuration was not changed.')
    origin = 'https://' + dns
    private(CONFIG / 'phone-tailscale.env', 'XAU_PHONE_BIND=127.0.0.1\nXAU_PHONE_ORIGIN=' + origin + '\nXAU_PHONE_TAILNET_ONLY=1\n')
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
    print('Open directly from an allowed tailnet device; no pairing key. The gateway remains loopback-only.')

if __name__ == '__main__': main()
