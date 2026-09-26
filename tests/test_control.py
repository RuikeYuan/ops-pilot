import socket
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from control.db import Check, Project
from control.probes import parse_url, public_address
from control.server import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app('sqlite:///' + str(tmp_path / 'control.db'), demo=True, scheduler=False)
    with TestClient(app) as c:
        assert c.post('/api/session', json={'demo': True}).status_code == 200
        yield c


def new_project(c, mode='heartbeat'):
    cid = c.get('/api/workspace').json()['clients'][0]['id']
    result = c.post('/api/projects', json={'name': 'Private worker', 'client_id': cid, 'mode': mode,
                                         'url': 'https://example.com/health', 'interval': 60})
    assert result.status_code == 200
    return result.json()


def test_auth_boundary_and_cross_origin(client):
    client.cookies.clear()
    assert client.get('/api/workspace').status_code == 401
    assert client.post('/api/session', json={'demo': True}, headers={'Origin': 'https://evil.example'}).status_code == 403


def test_project_token_scope_rotation_and_storage(client):
    a, b = new_project(client), new_project(client)
    headers = {'Authorization': 'Bearer ' + a['token']}
    assert client.post(f"/api/ingest/{b['id']}/heartbeat", headers=headers, json={'healthy': True}).status_code == 401
    assert client.post(f"/api/ingest/{a['id']}/heartbeat", headers=headers, json={'healthy': True}).status_code == 200
    with client.app.state.session_factory() as db:
        assert db.get(Project, a['id']).token_hash != a['token']
    rotated = client.post(f"/api/projects/{a['id']}/token").json()
    assert client.post(f"/api/ingest/{a['id']}/heartbeat", headers=headers, json={'healthy': True}).status_code == 401
    assert client.post(f"/api/ingest/{a['id']}/heartbeat", headers={'Authorization': 'Bearer ' + rotated['token']}, json={'healthy': True}).status_code == 200
    client.cookies.clear()
    assert client.get('/api/workspace', headers={'Authorization': 'Bearer ' + rotated['token']}).status_code == 401


def test_recovery_needs_fresh_success_and_report_is_evidence_based(client):
    ws = client.get('/api/workspace').json()
    p = next(p for p in ws['projects'] if p['fault'])
    iid = next(i['id'] for i in ws['incidents'] if i['project_id'] == p['id'])
    url = f'/api/incidents/{iid}'
    assert client.patch(url, json={'action': 'resolve', 'note': 'Not verified'}).status_code == 409
    assert client.post(f"/api/projects/{p['id']}/demo/resume").status_code == 400
    assert client.post(f"/api/projects/{p['id']}/demo/resume", headers={'X-Confirm-Operation': 'yes'}).status_code == 200
    assert client.patch(url, json={'action': 'resolve', 'note': 'Only resumed'}).status_code == 409
    assert client.post(f"/api/projects/{p['id']}/check").json()['passed']
    assert client.patch(url, json={'action': 'resolve', 'note': 'Fresh check passed; queue recovered in synthetic drill'}).status_code == 200
    text = client.get(f"/api/reports/{p['client_id']}").text
    assert 'SYNTHETIC DEMO' in text and 'Fresh check passed' in text
    assert 'not time-based uptime' in text


def test_heartbeat_pending_stale_and_missing_incident(client):
    p = new_project(client)
    ws = client.get('/api/workspace').json()
    assert next(x for x in ws['projects'] if x['id'] == p['id'])['status'] == 'pending'
    client.post(f"/api/ingest/{p['id']}/heartbeat", headers={'Authorization': 'Bearer ' + p['token']}, json={'healthy': True})
    with client.app.state.session_factory() as db:
        check = db.scalar(select(Check).where(Check.project_id == p['id']))
        check.at = time.time() - 200
        db.commit()
    client.app.state.scheduled_checks()
    ws = client.get('/api/workspace').json()
    assert next(x for x in ws['projects'] if x['id'] == p['id'])['status'] == 'stale'
    assert sum(i['project_id'] == p['id'] for i in ws['incidents']) == 1
    client.app.state.scheduled_checks()
    assert sum(i['project_id'] == p['id'] for i in client.get('/api/workspace').json()['incidents']) == 1


def test_deployment_verification_and_live_project_no_fault_controls(client):
    p = new_project(client, 'http')
    with patch('control.server.probe', return_value=(False, 12, 'HTTP 500; expected 200')):
        result = client.post(f"/api/ingest/{p['id']}/deployment", json={'version': 'v2', 'commit': 'abc'}, headers={'Authorization': 'Bearer ' + p['token']})
    assert result.json()['status'] == 'failed'
    assert client.post(f"/api/projects/{p['id']}/demo/pause", headers={'X-Confirm-Operation': 'yes'}).status_code == 403


@pytest.mark.parametrize('url', ['file:///etc/passwd','http://user:pass@example.com','http://example.com:8000','https://example.com/#secret'])
def test_invalid_probe_urls(url):
    with pytest.raises(ValueError):
        parse_url(url)


@pytest.mark.parametrize('ip', ['127.0.0.1','10.1.1.1','169.254.169.254','::1','::ffff:127.0.0.1'])
def test_ssrf_private_addresses_blocked(ip):
    with patch('socket.getaddrinfo', return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, 80))]):
        with pytest.raises(ValueError):
            public_address('example.com', 80)


def test_non_demo_requires_operator_and_disables_demo_login(tmp_path, monkeypatch):
    monkeypatch.setenv('OPS_TOKEN', 'test-operator-token-at-least-24-characters')
    app = create_app('sqlite:///' + str(tmp_path / 'live.db'), demo=False, scheduler=False)
    with TestClient(app) as c:
        assert c.post('/api/session', json={'demo': True}).status_code == 401
        assert c.post('/api/session', json={'token': 'test-operator-token-at-least-24-characters'}).status_code == 200
        assert c.get('/api/workspace').json()['projects'] == []


def test_email_password_login_is_configured_admin_only(tmp_path, monkeypatch):
    monkeypatch.setenv('OPS_TOKEN', 'test-operator-token-at-least-24-characters')
    monkeypatch.setenv('OPS_ADMIN_EMAIL', 'owner@example.com')
    monkeypatch.setenv('OPS_ADMIN_PASSWORD', 'test-password-long-enough')
    monkeypatch.setenv('OPS_SESSION_SECRET', 'test-session-secret-long-enough')
    monkeypatch.setenv('GOOGLE_CLIENT_ID', 'google-client-id')
    monkeypatch.setenv('GOOGLE_CLIENT_SECRET', 'google-client-secret')
    monkeypatch.setenv('OPS_AUTH_EMAILS', 'owner@example.com, teammate@example.com')
    app = create_app('sqlite:///' + str(tmp_path / 'password.db'), demo=False, scheduler=False)
    with TestClient(app) as c:
        assert c.get('/api/config').json() == {'demo': False, 'password_login': True, 'google_login': True, 'registration': True}
        assert c.post('/api/session', json={'email': 'owner@example.com', 'password': 'wrong-password'}).status_code == 401
        assert c.post('/api/session', json={'email': 'other@example.com', 'password': 'test-password-long-enough'}).status_code == 401
        response = c.post('/api/session', json={'email': 'OWNER@example.com', 'password': 'test-password-long-enough'})
        assert response.status_code == 200
        assert c.get('/api/workspace').status_code == 200


def test_google_login_is_hidden_until_fully_configured(tmp_path, monkeypatch):
    monkeypatch.setenv('OPS_TOKEN', 'test-operator-token-at-least-24-characters')
    for name in ('OPS_ADMIN_EMAIL', 'OPS_ADMIN_PASSWORD', 'OPS_AUTH_EMAILS', 'GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET'):
        monkeypatch.delenv(name, raising=False)
    app = create_app('sqlite:///' + str(tmp_path / 'google-disabled.db'), demo=False, scheduler=False)
    with TestClient(app) as c:
        assert c.get('/api/config').json() == {'demo': False, 'password_login': True, 'google_login': False, 'registration': True}
        assert c.get('/api/auth/google').status_code == 404


def test_registration_creates_isolated_workspace(client):
    client.cookies.clear()
    assert client.get('/api/workspace').status_code == 401
    initial = client.post('/api/register', json={
        'email': '  teammate@example.com ',
        'password': 'strong-password-123',
    })
    assert initial.status_code == 200
    first_workspace = client.get('/api/workspace')
    assert first_workspace.status_code == 200
    initial_clients = len(first_workspace.json()['clients'])
    assert first_workspace.json()['projects'] == []

    assert client.post('/api/register', json={
        'email': 'TEAMMATE@example.com',
        'password': 'another-password-123',
    }).status_code == 409
    assert client.post('/api/register', json={
        'email': 'invalid-email',
        'password': 'strong-password-123',
    }).status_code == 422
    assert client.post('/api/register', json={
        'email': 'other@example.com',
        'password': 'short',
    }).status_code == 422

    created = client.post('/api/clients', json={'name': 'Shared team client'})
    assert created.status_code == 200
    teammate = TestClient(client.app)
    with teammate:
        second_signup = teammate.post('/api/register', json={
            'email': 'second-member@example.com',
            'password': 'another-strong-password-456',
        })
        assert second_signup.status_code == 200
        shared = teammate.get('/api/workspace').json()
        assert shared['clients'] == []
        assert shared['events'] == []
    client.cookies.clear()
    assert client.get('/api/workspace').status_code == 401
    assert client.post('/api/session', json={
        'email': 'TEAMMATE@example.com',
        'password': 'strong-password-123',
    }).status_code == 200
    signed_in_workspace = client.get('/api/workspace').json()
    assert len(signed_in_workspace['clients']) == initial_clients + 1
    assert any(c['name'] == 'Shared team client' for c in signed_in_workspace['clients'])


def test_registration_password_is_not_stored_in_plaintext(tmp_path, monkeypatch):
    monkeypatch.setenv('OPS_TOKEN', 'test-operator-token-at-least-24-characters')
    app = create_app('sqlite:///' + str(tmp_path / 'accounts.db'), demo=False, scheduler=False)
    with TestClient(app) as c:
        assert c.post('/api/register', json={
            'email': 'member@example.com',
            'password': 'very-secure-password',
        }).status_code == 200
        with app.state.session_factory() as db:
            from control.db import Account
            account = db.scalar(select(Account).where(Account.email == 'member@example.com'))
            assert account.password_hash != 'very-secure-password'
            assert account.password_salt
