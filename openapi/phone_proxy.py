#!/usr/bin/env python3
"""Paired LAN gateway for the local research dashboard; no public tunnel."""
import hashlib
import hmac
import http.client
import ipaddress
import json
import os
from pathlib import Path
import secrets
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time
import urllib.parse

BIND = os.environ.get('XAU_PHONE_BIND', '192.168.1.81')
PORT = int(os.environ.get('XAU_PHONE_PORT', '8789'))
EXTERNAL = os.environ.get('XAU_PHONE_ORIGIN', '')
ORIGIN = EXTERNAL or f'http://{BIND}:{PORT}'
PUBLIC = urllib.parse.urlsplit(ORIGIN)
assert ipaddress.ip_address(BIND).is_private
assert PUBLIC.netloc and not PUBLIC.username and not PUBLIC.password and not PUBLIC.path and not PUBLIC.query and not PUBLIC.fragment
if EXTERNAL:
    assert ipaddress.ip_address(BIND).is_loopback and PUBLIC.scheme == 'https' and PUBLIC.hostname.endswith('.ts.net')
HOSTS = {PUBLIC.netloc}
if ipaddress.ip_address(BIND).is_loopback: HOSTS.add(f'{BIND}:{PORT}')
COOKIE = 'aurum_phone_ts' if EXTERNAL else 'aurum_phone'
CONFIG = Path.home() / '.config' / 'fxpro-openapi' / 'phone-pairing.json'
CONFIG.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
if not CONFIG.exists():
    descriptor = os.open(CONFIG, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as output:
        json.dump({'code': ''.join(secrets.choice('0123456789') for _ in range(8))}, output)
os.chmod(CONFIG, 0o600)
CODE = json.loads(CONFIG.read_text())['code']
SESSIONS, ATTEMPTS, USED_FORMS = {}, {}, {}
FORM_KEY = secrets.token_bytes(32)
LOCK = threading.Lock()
LOGIN = b'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Aurum - Pair your phone</title><style>body{background:#101214;color:#e7e9e5;font:15px system-ui;margin:0;padding:30px}main{max-width:360px;margin:14vh auto}small{color:#d4b477;letter-spacing:3px}h1{font-size:30px;font-weight:500}p{color:#98a2a5;line-height:1.8;font-size:13px}input{box-sizing:border-box;width:100%;padding:16px;background:#1b2023;border:1px solid #414c50;border-radius:6px;color:white;font:22px monospace;letter-spacing:5px;margin:15px 0}button{width:100%;padding:15px;border:0;border-radius:6px;background:#d4b477;color:#171b1e;font-weight:600}label{font-size:12px;color:#c2cac8}.error{color:#e09b9b}</style><main><small>AURUM / STRATEGY DESK</small><h1>Pair your phone.</h1><p>Enter the access code provided on your desktop. This connects to your local research dashboard.</p>{error}<form method="post" action="/pair"><input type="hidden" name="form_token" value="{form_token}"><label for="code">Access code</label><input id="code" name="code" type="text" inputmode="numeric" pattern="[0-9]{8}" minlength="8" maxlength="8" autocomplete="one-time-code" required autofocus><button>Open dashboard</button></form></main></html>'''

class Gateway(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass
    def send(self, status, body, content_type='text/html; charset=utf-8', headers=None):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'same-origin' if self.path == '/pair' else 'no-referrer')
        self.send_header('X-Content-Type-Options', 'nosniff')
        if EXTERNAL: self.send_header('Strict-Transport-Security', 'max-age=86400')
        self.send_header('Content-Length', str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)
    def valid_host(self):
        return self.headers.get('Host') in HOSTS and self.path.startswith('/') and len(self.path) < 2048
    def session_token(self):
        try:
            authorization = self.headers.get('Authorization', '')
            cookie = SimpleCookie(self.headers.get('Cookie', ''))
            value = cookie.get(COOKIE)
            candidates = [authorization[7:] if authorization.startswith('Bearer ') else '', value.value if value else '']
            with LOCK:
                for token in candidates:
                    key = hashlib.sha256(token.encode()).hexdigest()
                    if token and SESSIONS.get(key, 0) > time.time(): return token
        except Exception:
            pass
        return None
    def paired(self):
        return self.session_token() is not None
    def dashboard(self, token=None, cookie=False):
        connection = http.client.HTTPConnection('127.0.0.1', 8788, timeout=15)
        try:
            connection.request('GET', '/', headers={'Host': 'localhost:8788'})
            response = connection.getresponse()
            data = response.read()
            headers = {}
            policy = response.getheader('Content-Security-Policy')
            if policy: headers['Content-Security-Policy'] = policy
            if token:
                # Opaque base64url token, never a broker credential. API requests may use it
                # when a mobile webview refuses cookies. The token never enters the URL.
                data = data.replace(b'<head>', b'<head><meta name="aurum-phone-session" content="' + token.encode('ascii') + b'">', 1)
            if cookie:
                headers['Set-Cookie'] = f'{COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=86400' + ('; Secure' if EXTERNAL else '')
            self.send(response.status, data, 'text/html; charset=utf-8', headers)
        except (OSError, http.client.HTTPException):
            self.send(503, b'The desktop dashboard is offline.')
        finally:
            connection.close()
    def login(self, error=False, status=200):
        payload = f'{int(time.time())}.{secrets.token_hex(16)}'
        signature = hmac.new(FORM_KEY, payload.encode(), hashlib.sha256).hexdigest()
        form_token = f'{payload}.{signature}'.encode()
        page = LOGIN.replace(b'{form_token}', form_token).replace(b'{error}', b'<p class="error">Page or code not accepted. Enter your code again.</p>' if error else b'')
        self.send(status, page, headers={'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"})
    def forward(self, body=None):
        connection = http.client.HTTPConnection('127.0.0.1', 8788, timeout=45)
        try:
            headers = {'Host': 'localhost:8788'}
            for name in ('Content-Type', 'X-CSRF-Token'):
                if self.headers.get(name): headers[name] = self.headers[name]
            if self.command == 'POST': headers['Origin'] = 'http://localhost:8788'
            connection.request(self.command, self.path, body=body, headers=headers)
            response = connection.getresponse()
            data = response.read()
            policy = response.getheader('Content-Security-Policy')
            self.send(response.status, data, response.getheader('Content-Type', 'application/json'), {'Content-Security-Policy': policy} if policy else None)
        except (OSError, http.client.HTTPException):
            self.send(503, b'{"error":"The desktop dashboard is offline."}', 'application/json')
        finally:
            connection.close()
    def do_GET(self):
        if not self.valid_host(): self.send(403, b'Invalid host.'); return
        if self.path in ('/', '/index.html'):
            self.dashboard(self.session_token()); return
        if self.path == '/pair':
            self.login(); return
        # Static UI contains no account information; all data endpoints stay protected.
        if self.path in ('/dashboard.css', '/dashboard.js', '/financial-chart.js') or self.path.startswith('/assets/'):
            self.forward(); return
        if not self.paired():
            self.send(401, b'{"error":"Pair this phone again to continue."}', 'application/json'); return
        self.forward()
    def do_POST(self):
        if not self.valid_host():
            self.send(403, b'{"error":"Invalid host."}', 'application/json'); return
        origin = self.headers.get('Origin')
        if self.path == '/pair':
            # Native form navigations may omit Origin or send null under privacy policies.
            # Require a signed, expiring, one-use form token as well as the pairing code.
            if origin not in (ORIGIN, None, '', 'null'):
                self.send(403, b'{"error":"Invalid origin."}', 'application/json'); return
        elif origin != ORIGIN:
            authorization = self.headers.get('Authorization', '')
            explicit_session = authorization.startswith('Bearer ') and self.session_token() == authorization[7:]
            if origin not in (None, '', 'null') or not explicit_session or not self.headers.get('X-CSRF-Token'):
                self.send(403, b'{"error":"Invalid origin."}', 'application/json'); return
        try: length = int(self.headers.get('Content-Length', '0'))
        except ValueError: length = 0
        if not 0 < length <= 8192: self.send(400, b'Invalid request.'); return
        body = self.rfile.read(length)
        if self.path == '/pair':
            ip = self.client_address[0]
            with LOCK:
                now = time.time()
                history = [stamp for stamp in ATTEMPTS.get(ip, []) if stamp > now - 300]
                ATTEMPTS[ip] = history
                blocked = len(history) >= 5
            if blocked: self.login(True, 429); return
            fields = urllib.parse.parse_qs(body.decode('utf-8', errors='replace'))
            form_token = fields.get('form_token', [''])[0]
            try:
                issued, random_part, signature = form_token.split('.')
                payload = f'{issued}.{random_part}'
                valid_form = 0 <= time.time() - int(issued) <= 600 and len(random_part) == 32 and hmac.compare_digest(
                    signature, hmac.new(FORM_KEY, payload.encode(), hashlib.sha256).hexdigest())
            except (ValueError, TypeError):
                valid_form = False
            with LOCK:
                valid_form = valid_form and form_token not in USED_FORMS
            if not valid_form: self.login(True, 403); return
            candidate = fields.get('code', [''])[0]
            if not (len(candidate) == 8 and candidate.isascii() and candidate.isdigit() and hmac.compare_digest(candidate, CODE)):
                with LOCK: ATTEMPTS[ip].append(time.time())
                self.login(True, 403); return
            token = secrets.token_urlsafe(32)
            with LOCK:
                if form_token in USED_FORMS: self.login(True, 403); return
                USED_FORMS[form_token] = time.time() + 600
                for old in [key for key, expiry in USED_FORMS.items() if expiry < time.time()]: USED_FORMS.pop(old, None)
                SESSIONS[hashlib.sha256(token.encode()).hexdigest()] = time.time() + 86400
                ATTEMPTS.pop(ip, None)
            self.dashboard(token, cookie=True)
            return
        if not self.paired(): self.send(401, b'{"error":"Pair this phone to continue."}', 'application/json'); return
        self.forward(body)

class Server(ThreadingHTTPServer):
    daemon_threads = True

print(f'Phone dashboard: {ORIGIN}', flush=True)
Server((BIND, PORT), Gateway).serve_forever()
