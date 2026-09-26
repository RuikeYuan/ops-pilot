import json
import time
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from control.business import STEP_IDS
from control.db import BusinessRun, Check
from control.server import create_app
from runners.dutch_business import Config, ConfigurationError, WorkflowFailure, validate_payload


@pytest.fixture
def setup(tmp_path):
    app = create_app('sqlite:///' + str(tmp_path / 'test.db'), demo=True, scheduler=False)
    with TestClient(app) as client:
        client.post('/api/session', json={'demo': True})
        cid = client.get('/api/workspace').json()['clients'][0]['id']
        p = client.post('/api/projects', json={'client_id': cid, 'name': 'Real business workflow', 'mode': 'business', 'interval': 300}).json()
        yield client, p, cid


def receipt(failure=None):
    steps = []
    for i, key in enumerate(STEP_IDS):
        status = 'passed' if failure is None or i < failure else 'failed' if i == failure else 'skipped'
        steps.append({'id': key, 'status': status, 'duration_ms': 20 if status != 'skipped' else 0,
                      'code': 'ok' if status == 'passed' else 'sync_failed' if status == 'failed' else 'not_run'})
    return {'run_id': str(uuid.uuid4()), 'workflow': 'dutch-learning-v1', 'observed_at': datetime.now(timezone.utc).isoformat(), 'steps': steps}


def send(c, p, body):
    return c.post(f"/api/ingest/{p['id']}/business-check", headers={'Authorization': 'Bearer ' + p['token']}, json=body)


def test_business_lifecycle_not_heartbeat_and_report(setup):
    c, p, cid = setup
    assert c.post(f"/api/projects/{p['id']}/check").status_code == 409
    assert c.post(f"/api/ingest/{p['id']}/heartbeat", headers={'Authorization': 'Bearer ' + p['token']}, json={'healthy': True}).status_code == 409
    assert send(c, p, receipt(2)).json()['passed'] is False
    ws = c.get('/api/workspace').json()
    project = next(x for x in ws['projects'] if x['id'] == p['id'])
    assert project['status'] == 'degraded'
    assert project['business_check']['steps'][2]['message'] == 'Cloud learning data could not be read for this account'
    incident = next(i for i in ws['incidents'] if i['project_id'] == p['id'])
    path = '/api/incidents/' + incident['id']
    assert c.patch(path, json={'action': 'resolve', 'note': 'No fresh evidence'}).status_code == 409
    assert send(c, p, receipt()).json()['passed'] is True
    assert c.patch(path, json={'action': 'resolve', 'note': 'All five browser steps passed after repair'}).status_code == 200
    report = c.get('/api/reports/' + cid).text
    assert 'Test account signs in: passed' in report
    assert 'Review screen shows saved progress: passed' in report


def test_replay_scope_and_out_of_order(setup):
    c, p, cid = setup
    body = receipt()
    assert send(c, p, body).status_code == 200
    assert send(c, p, body).json()['duplicate']
    with c.app.state.session_factory() as db:
        assert len(list(db.scalars(select(Check).where(Check.project_id == p['id'])))) == 1
        assert len(list(db.scalars(select(BusinessRun).where(BusinessRun.project_id == p['id'])))) == 1
    body['steps'][0]['duration_ms'] += 1
    assert send(c, p, body).status_code == 409
    old = receipt()
    old['observed_at'] = datetime.fromtimestamp(time.time()-30, timezone.utc).isoformat()
    assert send(c, p, old).status_code == 409
    other = c.post('/api/projects', json={'client_id': cid, 'name': 'Other', 'mode': 'business'}).json()
    assert c.post(f"/api/ingest/{other['id']}/business-check", headers={'Authorization': 'Bearer ' + p['token']}, json=receipt()).status_code == 401


@pytest.mark.parametrize('change', ['missing', 'skip', 'success_after_failure', 'stale', 'future', 'naive', 'bad_code'])
def test_receipt_cannot_lie_about_completeness_or_freshness(setup, change):
    c, p, _ = setup
    b = receipt()
    if change == 'missing': b['steps'].pop()
    if change == 'skip': b['steps'][0].update(status='skipped', code='not_run')
    if change == 'success_after_failure': b['steps'][0].update(status='failed', code='login_failed')
    if change == 'stale': b['observed_at'] = datetime.fromtimestamp(time.time()-600, timezone.utc).isoformat()
    if change == 'future': b['observed_at'] = datetime.fromtimestamp(time.time()+600, timezone.utc).isoformat()
    if change == 'naive': b['observed_at'] = '2026-01-01T00:00:00'
    if change == 'bad_code': b['steps'][0]['code'] = 'password or raw sensitive server response'
    assert send(c, p, b).status_code == 422


def config():
    return Config('http://127.0.0.1:5175', 'http://127.0.0.1:54321', 'test@example.invalid',
                  'test-only-password', '11111111-1111-4111-8111-111111111111', 'C1', 1, 'msedge', 3000)


def fixture_payload():
    return {'updated_at': datetime.now(timezone.utc).isoformat(), 'payload': {'notebook': ['C1'], 'studyProgress': {
        'C1': {'level': 1, 'correctStreak': 1, 'lapses': 0, 'lastReviewedAt': 1700000000000, 'dueAt': 1700000010000}}}}


@pytest.mark.parametrize('data', [None, {}, {'payload': {'notebook': [], 'studyProgress': {}}}])
def test_empty_records_are_not_success(data):
    with pytest.raises(WorkflowFailure): validate_payload(data, config())


def test_expected_record_and_configuration():
    assert validate_payload(fixture_payload(), config())['level'] == 1
    bad = fixture_payload()
    bad['payload']['studyProgress']['C1']['level'] = 2
    with pytest.raises(WorkflowFailure): validate_payload(bad, config())
    with pytest.raises(ConfigurationError): Config.from_dict({})
    assert 'password' not in repr(config())
