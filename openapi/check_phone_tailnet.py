#!/usr/bin/env python3
"""Fake upstream: no real dashboard writes, broker calls or private credential reads."""
import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time
import subprocess
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

with tempfile.TemporaryDirectory(prefix='aurum-keyless-') as home:
    os.environ.update(HOME=home, XAU_PHONE_BIND='127.0.0.1', XAU_PHONE_ORIGIN='https://test.ts.net', XAU_PHONE_TAILNET_ONLY='1')
    spec = importlib.util.spec_from_file_location('gateway', Path(__file__).with_name('phone_proxy.py'))
    gateway = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gateway)
    posts = []
    class Backend(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_GET(self):
            body = b'<html><head></head><body id="dashboard">Aurum</body></html>' if self.path == '/' else b'{"ok":true}'
            self.send_response(200); self.send_header('Content-Type', 'text/html' if self.path == '/' else 'application/json'); self.end_headers(); self.wfile.write(body)
        def do_POST(self):
            posts.append(self.path)
            ok = self.headers.get('Origin') == 'http://localhost:8788' and self.headers.get('X-CSRF-Token') == 'fake-csrf'
            self.send_response(200 if ok else 403); self.end_headers(); self.wfile.write(b'{}')
    backend = ThreadingHTTPServer(('127.0.0.1', 0), Backend)
    original = http.client.HTTPConnection
    gateway.http.client.HTTPConnection = lambda host, port, **kw: original('127.0.0.1', backend.server_port, **kw)
    server = gateway.Server(('127.0.0.1', 0), gateway.Gateway)
    for instance in (backend, server): threading.Thread(target=instance.serve_forever, daemon=True).start()
    def request(path, token=None, origin=None, csrf=None, post=False, host='test.ts.net', cookie=None, body=b'{}', content_type='application/json'):
        connection = original('127.0.0.1', server.server_port, timeout=5)
        headers = {'Host':host}
        if token: headers['Authorization'] = 'Bearer '+token
        if cookie: headers['Cookie'] = cookie
        if origin is not None: headers['Origin'] = origin
        if csrf: headers['X-CSRF-Token'] = csrf
        if post: headers['Content-Type'] = content_type
        connection.request('POST' if post else 'GET', path, body=body if post else None, headers=headers)
        r=connection.getresponse(); result=(r.status,dict(r.getheaders()),r.read()); connection.close();return result
    try:
        assert request('/api/status')[0] == 401
        status, headers, body = request('/')
        assert status == 200 and b'Pair your phone' not in body
        token = re.search(rb'name="aurum-phone-session" content="([A-Za-z0-9_-]+)"', body).group(1).decode()
        assert '; Secure' in headers['Set-Cookie'] and 'SameSite=Strict' in headers['Set-Cookie']
        assert request('/api/status', token=token)[0] == 200
        assert request('/api/status', cookie=headers['Set-Cookie'].split(';')[0])[0] == 200
        assert request('/pair')[0] == 200 and b'Pair your phone' not in request('/pair')[2]
        assert request('/pair', post=True)[0] == 405
        assert request('/', host='foreign.invalid')[0] == 403
        assert request('/api/execution/start', token=token, origin='https://foreign.invalid', csrf='fake-csrf', post=True)[0] == 403
        assert request('/api/execution/start', origin='null', csrf='fake-csrf', post=True)[0] == 403
        assert request('/api/execution/start', token=token, origin='null', post=True)[0] == 403
        assert posts == []
        assert request('/api/fake-action', token=token, origin='https://test.ts.net', post=True)[0] == 403
        assert request('/api/fake-action', token=token, origin='null', csrf='fake-csrf', post=True)[0] == 200
        with gateway.LOCK: gateway.SESSIONS[hashlib.sha256(token.encode()).hexdigest()] = time.time()-1
        assert request('/api/status', token=token)[0] == 401
        assert b'aurum-phone-session' in request('/')[2]
        gateway.TAILNET_ONLY = False
        assert b'Pair your phone' in request('/pair')[2]
        assert b'aurum-phone-session' not in request('/')[2]
        form = re.search(rb'name="form_token" value="([0-9a-f.]+)"', request('/pair')[2]).group(1).decode()
        data = urllib.parse.urlencode({'code':gateway.CODE,'form_token':form}).encode()
        assert request('/pair', post=True, body=data, content_type='application/x-www-form-urlencoded')[0] == 200
        assert request('/pair', post=True, body=data, content_type='application/x-www-form-urlencoded')[0] == 403
        invalid_env = dict(os.environ, XAU_PHONE_ORIGIN='', XAU_PHONE_BIND='192.168.1.81')
        invalid = subprocess.run([sys.executable,'-O',str(Path(__file__).with_name('phone_proxy.py'))], env=invalid_env, capture_output=True, timeout=5)
        assert invalid.returncode != 0 and b'Keyless access requires' in invalid.stderr

        print('Tailnet gateway PASS: keyless entry/renewal, secure cookie and no-cookie session, host/origin/CSRF guards; legacy pairing retained. Fake upstream only.')
    finally:
        server.shutdown();server.server_close();backend.shutdown();backend.server_close()
