#!/usr/bin/env python3
"""Legacy paired-mode checks only (XAU_PHONE_TAILNET_ONLY off); not for keyless production."""
from pathlib import Path
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get('XAU_PHONE_TEST_URL', 'http://192.168.1.81:8789')
ORIGIN = os.environ.get('XAU_PHONE_ORIGIN', BASE)
client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
code = json.loads((Path.home() / '.config/fxpro-openapi/phone-pairing.json').read_text())['code']

def request(path, data=None, origin=None, token=None, csrf=None, json_body=False):
    headers = {'Host': urllib.parse.urlsplit(ORIGIN).netloc}
    if origin is not None: headers['Origin'] = origin
    if token: headers['Authorization'] = 'Bearer ' + token
    if csrf: headers['X-CSRF-Token'] = csrf
    if data is not None:
        headers['Content-Type'] = 'application/json' if json_body else 'application/x-www-form-urlencoded'
        data = json.dumps(data).encode() if json_body else urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(BASE + path, data=data, headers=headers)
    try:
        with client.open(req, timeout=30) as response: return response.status, response.headers, response.read()
    except urllib.error.HTTPError as response:
        return response.code, response.headers, response.read()

def form():
    status, headers, page = request('/pair')
    assert status == 200 and headers['Referrer-Policy'] == 'same-origin'
    return re.search(rb'name="form_token" value="([0-9a-f.]+)"', page).group(1).decode()

assert request('/api/status')[0] == 401
for origin, label in [(ORIGIN, 'same origin'), ('null', 'null origin'), (None, 'missing origin')]:
    nonce = form()
    status, headers, page = request('/pair', {'code': code, 'form_token': nonce}, origin=origin)
    assert status == 200 and b'id="backtest-chart"' in page, (label, status)
    if ORIGIN.startswith('https://'): assert '; Secure' in headers.get('Set-Cookie', '')
    token = re.search(rb'name="aurum-phone-session" content="([A-Za-z0-9_-]+)"', page).group(1).decode()
    assert request('/api/status', token=token)[0] == 200
    assert request('/pair', {'code': code, 'form_token': nonce}, origin=origin)[0] == 403
    print('PASS: ' + label + ', no-cookie dashboard access, one-use form token')
assert request('/pair', {'code': code}, origin='null')[0] == 403
assert request('/pair', {'code': code, 'form_token': 'forged'}, origin='null')[0] == 403
assert request('/pair', {'code': code, 'form_token': form()}, origin='http://untrusted.invalid')[0] == 403
_, _, session = request('/api/session', token=token)
csrf = json.loads(session)['csrf']
invalid_config = {'start': '2026-01-01', 'end': '2026-02-01', 'rr': 99}
for origin in ('null', None):
    assert request('/api/backtests', invalid_config, origin=origin, token=token, csrf=csrf, json_body=True)[0] == 400
assert request('/api/backtests', invalid_config, origin='null', token=token, json_body=True)[0] == 403
assert request('/api/backtests', invalid_config, origin='http://untrusted.invalid', token=token, csrf=csrf, json_body=True)[0] == 403
print('PASS: missing/forged form tokens and foreign origins rejected; API bearer + CSRF validation retained')
