import sqlite3

from fastapi.testclient import TestClient
from sqlalchemy import select

from control.db import Client, database
from control.server import create_app


def test_accounts_cannot_read_or_operate_each_others_resources(tmp_path):
    app = create_app('sqlite:///' + str(tmp_path / 'isolation.db'), demo=True, scheduler=False)
    with TestClient(app) as a, TestClient(app) as b:
        for client, email in ((a, 'a@example.com'), (b, 'b@example.com')):
            assert client.post('/api/register', json={'email': email, 'password': 'long-password-123'}).status_code == 200
        cid = a.post('/api/clients', json={'name': 'Private client'}).json()['id']
        p = a.post('/api/projects', json={'client_id': cid, 'name': 'Private worker', 'mode': 'heartbeat'}).json()
        headers = {'Authorization': 'Bearer ' + p['token']}
        assert a.post(f"/api/ingest/{p['id']}/heartbeat", headers=headers, json={'healthy': False, 'detail': 'Private failure'}).status_code == 200
        assert a.post(f"/api/ingest/{p['id']}/deployment", headers=headers, json={'version': 'secret-version'}).status_code == 200
        iid = a.get('/api/workspace').json()['incidents'][0]['id']
        workspace = b.get('/api/workspace').json()
        for key in ('clients', 'projects', 'incidents', 'events', 'deployments'):
            assert workspace[key] == []
        assert b.get(f'/api/reports/{cid}').status_code == 404
        assert b.post('/api/projects', json={'client_id': cid, 'name': 'Attack', 'mode': 'heartbeat'}).status_code == 404
        for suffix in ('token', 'check', 'demo/pause'):
            assert b.post(f"/api/projects/{p['id']}/{suffix}", headers={'X-Confirm-Operation': 'yes'}).status_code == 404
        assert b.patch(f'/api/incidents/{iid}', json={'action': 'acknowledge', 'note': 'Unauthorized change'}).status_code == 404
        assert b.post(f"/api/ingest/{p['id']}/heartbeat", json={'healthy': True}).status_code == 401
        assert a.get(f'/api/reports/{cid}').status_code == 200
        assert a.post(f"/api/projects/{p['id']}/token").status_code == 200


def test_upgrade_preserves_legacy_rows_and_is_repeatable(tmp_path):
    path = tmp_path / 'old.db'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE clients (id VARCHAR PRIMARY KEY, name VARCHAR(120), contact VARCHAR(160), color VARCHAR(20))')
        db.execute("INSERT INTO clients VALUES ('old', 'Existing customer', '', 'teal')")
        db.execute('CREATE TABLE audit_events (id VARCHAR PRIMARY KEY, project_id VARCHAR(32), at FLOAT, kind VARCHAR(40), detail TEXT)')
        db.execute("INSERT INTO audit_events VALUES ('e', NULL, 1, 'client_added', 'Existing event')")
    for _ in range(2):
        engine, session = database('sqlite:///' + str(path))
        with session() as db:
            client = db.scalar(select(Client))
            assert client.name == 'Existing customer'
            assert client.workspace_id == 'legacy'
        engine.dispose()
