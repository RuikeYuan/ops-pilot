"""Opt-in contract tests against the actual local Dutch UI with fake Supabase.

Start Vite with the test Supabase URL, then run this file explicitly.
No real credentials, user records or remote APIs are used.
"""
import base64
import json
import time
from dataclasses import replace

import pytest

from runners.dutch_business import run_workflow
from tests.test_business import config, fixture_payload


def jwt(user_id):
    encode = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip('=')
    return encode({'alg': 'HS256', 'typ': 'JWT'}) + '.' + encode({'sub': user_id, 'exp': int(time.time())+3600, 'role': 'authenticated'}) + '.test'


@pytest.mark.parametrize('fault,expected', [('none', None), ('login', 'login'), ('empty', 'read_progress'), ('sync', 'read_progress'), ('render', 'render_notebook')])
def test_actual_ui_browser_workflow(fault, expected):
    cfg = replace(config(), timeout_ms=5000)
    escaped_writes = []
    user = {'id': cfg.expected_user_id, 'email': cfg.email, 'aud': 'authenticated', 'role': 'authenticated',
            'app_metadata': {}, 'user_metadata': {}, 'created_at': '2025-01-01T00:00:00Z'}

    def setup(context):
        def backend(route):
            r = route.request
            if r.method == 'OPTIONS':
                route.fulfill(status=204, headers={'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': '*', 'Access-Control-Allow-Methods': '*'})
                return
            if '/auth/v1/token' in r.url:
                body = {'access_token': jwt(cfg.expected_user_id), 'refresh_token': 'fake-refresh', 'expires_in': 3600, 'token_type': 'bearer', 'user': user}
                status = 200
                if fault == 'login': body, status = {'error': 'invalid_grant'}, 400
            elif '/auth/v1/user' in r.url:
                body, status = user, 200
            elif '/auth/v1/logout' in r.url:
                body, status = {}, 200
            elif '/rest/v1/sync_data' in r.url:
                if r.method != 'GET': escaped_writes.append(r.method)
                body, status = fixture_payload(), 200
                if fault == 'empty': body = None
                if fault == 'sync': body, status = {'error': 'fixture database unavailable'}, 500
            else:
                body, status = {'is_premium': False}, 200
            route.fulfill(status=status, content_type='application/json', body=json.dumps(body), headers={'Access-Control-Allow-Origin': '*'})
        context.route('http://127.0.0.1:54321/**', backend)
        # Prevent the real app's local API plugin from using any configured service.
        context.route('**/api/**', lambda r: r.fulfill(status=200, content_type='application/json', body='{}'))
        if fault == 'render':
            context.add_init_script("document.addEventListener('DOMContentLoaded',()=>{const style=document.createElement('style');style.textContent='#word-C1{display:none!important}';document.head.append(style)})")

    result = run_workflow(cfg, setup)
    failed = next((s['id'] for s in result['steps'] if s['status'] == 'failed'), None)
    assert failed == expected, result
    assert not escaped_writes
    serialized = json.dumps(result)
    assert cfg.password not in serialized and cfg.email not in serialized and 'fake-refresh' not in serialized
