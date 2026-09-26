import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from authlib.integrations.starlette_client import OAuth
from starlette.middleware.sessions import SessionMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select

from control.db import BusinessRun, Check, Client, Deployment, Event, Incident, Project, database
from control.business import BusinessReceipt, STEP_LABELS, MESSAGES, step_evidence
from control.probes import parse_url, probe

ROOT = Path(__file__).resolve().parent.parent
log = logging.getLogger('opspilot')


class Login(BaseModel):
    token: str = ''
    demo: bool = False
    email: str = ''
    password: str = ''


class NewClient(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    contact: str = Field(default='', max_length=160)


class NewProject(BaseModel):
    client_id: str
    name: str = Field(min_length=1, max_length=120)
    environment: Literal['Production', 'Staging'] = 'Production'
    provider: Literal['Azure', 'AWS', 'Coolify', 'Vercel', 'Other'] = 'Other'
    mode: Literal['http', 'heartbeat', 'business'] = 'http'
    url: str = Field(default='', max_length=2048)
    interval: int = Field(default=300, ge=60, le=86400)
    expected_status: int = Field(default=200, ge=200, le=299)


class Heartbeat(BaseModel):
    healthy: bool
    detail: str = Field(default='Heartbeat received', max_length=500)


class Release(BaseModel):
    version: str = Field(min_length=1, max_length=120)
    commit: str = Field(default='', max_length=80)


class IncidentUpdate(BaseModel):
    action: Literal['acknowledge', 'resolve']
    note: str = Field(min_length=3, max_length=2000)


def stamp(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat() if value else None


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def create_app(db_url=None, demo=None, scheduler=True):
    demo = os.getenv('OPS_DEMO', 'false').lower() == 'true' if demo is None else demo
    operator_token = os.getenv('OPS_TOKEN', '')
    if not demo and len(operator_token) < 24:
        raise RuntimeError('Set OPS_TOKEN to at least 24 characters, or enable OPS_DEMO for a local synthetic workspace')
    engine, Session = database(db_url)
    sessions = {}
    attempts = {}
    lock = threading.RLock()
    secure = os.getenv('OPS_SECURE_COOKIE', 'false').lower() == 'true'
    admin_email = os.getenv('OPS_ADMIN_EMAIL', '').strip().lower()
    admin_password = os.getenv('OPS_ADMIN_PASSWORD', '')
    allowed_emails = {email.strip().lower() for email in os.getenv('OPS_AUTH_EMAILS', '').split(',') if email.strip()}
    if admin_email:
        allowed_emails.add(admin_email)
    google_client_id = os.getenv('GOOGLE_CLIENT_ID', '')
    google_client_secret = os.getenv('GOOGLE_CLIENT_SECRET', '')
    google_enabled = bool(google_client_id and google_client_secret and allowed_emails)
    session_secret = os.getenv('OPS_SESSION_SECRET') or operator_token or secrets.token_urlsafe(32)

    def event(db, project_id, kind, detail):
        db.add(Event(project_id=project_id, kind=kind, detail=detail))

    def latest(db, pid):
        return db.scalar(select(Check).where(Check.project_id == pid).order_by(Check.at.desc()))

    def state(db, p):
        check = latest(db, p.id)
        if not check:
            return 'pending', check
        if time.time() - check.at > p.interval * 2:
            return 'stale', check
        return ('healthy' if check.passed else 'degraded'), check

    def record(db, p, passed, latency, detail, source, observed_at=None):
        db.add(Check(project_id=p.id, passed=passed, latency=latency, detail=detail, source=source,
                     at=observed_at if observed_at is not None else time.time()))
        opened = db.scalar(select(Incident).where(Incident.project_id == p.id, Incident.status != 'resolved'))
        if not passed and not opened:
            db.add(Incident(project_id=p.id, title=f'{p.name}: check failed', evidence=detail))
            event(db, p.id, 'incident_opened', detail)
        event(db, p.id, 'check_passed' if passed else 'check_failed', detail)

    def run_check(pid, source='manual'):
        # Single-process control plane: serialize writes and incident deduplication.
        with lock, Session() as db:
            p = db.get(Project, pid)
            if not p:
                raise HTTPException(404, 'Project not found')
            if p.mode in ('heartbeat', 'business'):
                raise HTTPException(409, 'Run the customer-side sender for this project; credentials never enter the control plane')
            if p.demo:
                passed, latency = not p.fault, 42
                detail = 'Synthetic invoice processing timed out; worker paused.' if p.fault else 'Synthetic invoice workflow completed. Demo simulation, not a remote cloud observation.'
            else:
                passed, latency, detail = probe(p.url, p.expected_status)
            record(db, p, passed, latency, detail, source)
            db.commit()
            return {'passed': passed, 'latency': latency, 'detail': detail}

    def scheduled_checks():
        with Session() as db:
            ids = []
            for p in db.scalars(select(Project)):
                c = latest(db, p.id)
                if p.mode in ('heartbeat', 'business'):
                    if time.time() - (c.at if c else p.created) > p.interval * 2:
                        with lock:
                            incident = db.scalar(select(Incident).where(Incident.project_id == p.id, Incident.status != 'resolved'))
                            if not incident:
                                kind = 'business check' if p.mode == 'business' else 'heartbeat'
                                db.add(Incident(project_id=p.id, title=f'{p.name}: {kind} missing', evidence=f'No {kind} within two configured intervals. Current service health is unknown.'))
                                event(db, p.id, kind.replace(' ', '_') + '_missing', 'Observation overdue; investigate the sender and service state')
                                db.commit()
                elif not c or time.time() - c.at >= p.interval:
                    ids.append(p.id)
        for pid in ids:
            run_check(pid, 'scheduled')

    async def loop():
        while True:
            try:
                await asyncio.to_thread(scheduled_checks)
            except Exception:
                log.exception('Scheduled checks failed')
            await asyncio.sleep(30)

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(loop()) if scheduler else None
        yield
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        engine.dispose()

    app = FastAPI(title='OpsPilot control plane', version='0.2.0', lifespan=lifespan)
    app.add_middleware(SessionMiddleware, secret_key=session_secret, same_site='lax', https_only=secure)
    app.state.session_factory = Session
    app.state.run_check = run_check
    app.state.scheduled_checks = scheduled_checks

    @app.middleware('http')
    async def headers(request, call_next):
        if request.method in ('POST', 'PATCH', 'DELETE'):
            origin = request.headers.get('origin')
            if origin:
                from urllib.parse import urlsplit
                if urlsplit(origin).netloc != request.headers.get('host'):
                    return PlainTextResponse('Cross-origin writes are not allowed', status_code=403)
            if int(request.headers.get('content-length', '0') or 0) > 16384:
                return PlainTextResponse('Request too large', status_code=413)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
        if request.url.path.startswith('/api'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    def auth(request: Request):
        bearer = request.headers.get('authorization', '').removeprefix('Bearer ')
        if operator_token and hmac.compare_digest(bearer, operator_token):
            return
        key = request.cookies.get('ops_session', '')
        if sessions.get(digest(key), 0) < time.time():
            raise HTTPException(401, 'Sign in to your workspace')

    def project_auth(request, p):
        token = request.headers.get('authorization', '').removeprefix('Bearer ')
        if not p.token_hash or not hmac.compare_digest(digest(token), p.token_hash):
            raise HTTPException(401, 'Invalid project token')

    @app.get('/health/live')
    def live():
        return {'status': 'alive', 'version': '0.2.0'}

    @app.get('/health/ready')
    def ready():
        from sqlalchemy import text
        with engine.connect() as c:
            c.execute(text('SELECT 1'))
        return {'status': 'ready'}

    @app.get('/api/config')
    def config():
        return {'demo': demo, 'password_login': bool(admin_email and admin_password), 'google_login': google_enabled}

    oauth = OAuth()
    if google_enabled:
        oauth.register(
            name='google',
            server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
            client_id=google_client_id,
            client_secret=google_client_secret,
            client_kwargs={'scope': 'openid email profile'},
        )

    def issue_session(response: Response):
        key = secrets.token_urlsafe(32)
        sessions[digest(key)] = time.time() + 28800
        response.set_cookie('ops_session', key, httponly=True, samesite='strict', secure=secure, max_age=28800)

    @app.post('/api/session')
    def login(body: Login, request: Request, response: Response):
        host = request.client.host if request.client else 'unknown'
        recent = [t for t in attempts.get(host, []) if t > time.time() - 300]
        attempts[host] = recent
        if len(recent) >= 10:
            raise HTTPException(429, 'Too many attempts; try again in five minutes')
        email = body.email.strip().lower()
        token_ok = bool(operator_token and hmac.compare_digest(body.token, operator_token))
        password_ok = bool(
            admin_email and admin_password
            and hmac.compare_digest(email.encode(), admin_email.encode())
            and hmac.compare_digest(body.password.encode(), admin_password.encode())
        )
        if not ((body.demo and demo) or token_ok or password_ok):
            recent.append(time.time())
            raise HTTPException(401, 'Invalid sign-in details')
        for k, expiry in list(sessions.items()):
            if expiry < time.time():
                del sessions[k]
        issue_session(response)
        return {'ok': True}

    @app.get('/api/auth/google')
    async def google_login(request: Request):
        if not google_enabled:
            raise HTTPException(404, 'Google sign-in is not configured')
        redirect_uri = os.getenv('GOOGLE_REDIRECT_URI') or str(request.url_for('google_callback'))
        return await oauth.google.authorize_redirect(request, redirect_uri)

    @app.get('/api/auth/google/callback', name='google_callback')
    async def google_callback(request: Request):
        if not google_enabled:
            raise HTTPException(404, 'Google sign-in is not configured')
        try:
            token = await oauth.google.authorize_access_token(request)
            userinfo = token.get('userinfo') or await oauth.google.userinfo(token=token)
        except Exception:
            log.exception('Google OAuth callback failed')
            return PlainTextResponse('Google sign-in failed. Return to OpsPilot and try again.', status_code=401)
        email = str(userinfo.get('email', '')).strip().lower()
        if userinfo.get('email_verified') is not True or email not in allowed_emails:
            return PlainTextResponse('This Google account is not authorized for this workspace.', status_code=403)
        response = RedirectResponse('/', status_code=303)
        issue_session(response)
        return response

    @app.delete('/api/session')
    def logout(request: Request, response: Response):
        sessions.pop(digest(request.cookies.get('ops_session', '')), None)
        response.delete_cookie('ops_session')
        return {'ok': True}

    @app.get('/api/workspace', dependencies=[Depends(auth)])
    def workspace():
        with Session() as db:
            clients = [{'id': c.id, 'name': c.name, 'contact': c.contact, 'color': c.color} for c in db.scalars(select(Client))]
            projects = []
            now = time.time()
            for p in db.scalars(select(Project).order_by(Project.created)):
                status, c = state(db, p)
                run = db.scalar(select(BusinessRun).where(BusinessRun.project_id == p.id).order_by(BusinessRun.observed_at.desc())) if p.mode == 'business' else None
                checks = list(db.scalars(select(Check).where(Check.project_id == p.id, Check.at >= now - 86400).order_by(Check.at)))
                projects.append({'id': p.id, 'client_id': p.client_id, 'name': p.name, 'environment': p.environment,
                                 'provider': p.provider, 'mode': p.mode, 'url': p.url, 'interval': p.interval,
                                 'expected_status': p.expected_status, 'demo': p.demo, 'fault': p.fault,
                                 'status': status, 'last_check': stamp(c.at) if c else None,
                                 'latency': c.latency if c else None, 'evidence': c.detail if c else 'Awaiting first observation',
                                 'success_rate': round(100 * sum(x.passed for x in checks) / len(checks), 2) if checks else None,
                                 'check_count': len(checks), 'history': [{'passed': x.passed, 'at': stamp(x.at)} for x in checks[-40:]],
                                 'business_check': {'run_id': run.id, 'workflow': run.workflow, 'observed_at': stamp(run.observed_at), 'steps': step_evidence(json.loads(run.steps_json))} if run else None})
            incidents = [{'id': i.id, 'project_id': i.project_id, 'title': i.title, 'status': i.status, 'severity': i.severity,
                          'opened': stamp(i.opened), 'resolved': stamp(i.resolved), 'evidence': i.evidence, 'note': i.note}
                         for i in db.scalars(select(Incident).order_by(Incident.opened.desc()).limit(100))]
            events = [{'id': e.id, 'project_id': e.project_id, 'at': stamp(e.at), 'kind': e.kind, 'detail': e.detail}
                      for e in db.scalars(select(Event).order_by(Event.at.desc()).limit(80))]
            deployments = [{'id': d.id, 'project_id': d.project_id, 'at': stamp(d.at), 'version': d.version,
                            'commit': d.commit, 'status': d.status} for d in db.scalars(select(Deployment).order_by(Deployment.at.desc()).limit(50))]
            return {'name': 'Northstar Studio' if demo else os.getenv('OPS_WORKSPACE', 'My studio'), 'demo': demo,
                    'clients': clients, 'projects': projects, 'incidents': incidents, 'events': events, 'deployments': deployments,
                    'at': stamp(now), 'region': 'Local workspace' if demo else os.getenv('OPS_REGION', 'Self-hosted')}

    @app.post('/api/clients', dependencies=[Depends(auth)])
    def add_client(body: NewClient):
        if not body.name.strip():
            raise HTTPException(422, 'Client name is required')
        with lock, Session() as db:
            c = Client(name=body.name.strip(), contact=body.contact.strip())
            db.add(c)
            db.flush()
            event(db, None, 'client_added', f'Added client {c.name}')
            db.commit()
            return {'id': c.id}

    @app.post('/api/projects', dependencies=[Depends(auth)])
    def add_project(body: NewProject):
        if not body.name.strip():
            raise HTTPException(422, 'Project name is required')
        if body.mode == 'http':
            try:
                parse_url(body.url)
            except ValueError as exc:
                raise HTTPException(422, str(exc))
        with lock, Session() as db:
            if not db.get(Client, body.client_id):
                raise HTTPException(404, 'Client not found')
            token = secrets.token_urlsafe(32)
            p = Project(**body.model_dump(), token_hash=digest(token))
            db.add(p)
            db.flush()
            event(db, p.id, 'project_connected', f'{p.name} configured for {p.mode}; awaiting first observation')
            db.commit()
            return {'id': p.id, 'token': token}

    @app.post('/api/projects/{pid}/token', dependencies=[Depends(auth)])
    def rotate(pid: str):
        with lock, Session() as db:
            p = db.get(Project, pid)
            if not p:
                raise HTTPException(404, 'Project not found')
            token = secrets.token_urlsafe(32)
            p.token_hash = digest(token)
            event(db, pid, 'token_rotated', 'Project ingestion token rotated; previous token revoked')
            db.commit()
            return {'token': token}

    @app.post('/api/projects/{pid}/check', dependencies=[Depends(auth)])
    def check(pid: str):
        return run_check(pid)

    @app.post('/api/ingest/{pid}/heartbeat')
    def heartbeat(pid: str, body: Heartbeat, request: Request):
        with lock, Session() as db:
            p = db.get(Project, pid)
            if not p:
                raise HTTPException(404, 'Project not found')
            project_auth(request, p)
            if p.mode != 'heartbeat':
                raise HTTPException(409, 'Project is not configured for heartbeats')
            record(db, p, body.healthy, 0, body.detail, 'heartbeat')
            db.commit()
            return {'accepted': True}

    @app.post('/api/ingest/{pid}/business-check')
    def business_check(pid: str, body: BusinessReceipt, request: Request):
        with lock, Session() as db:
            p = db.get(Project, pid)
            if not p:
                raise HTTPException(404, 'Project not found')
            project_auth(request, p)
            if p.mode != 'business':
                raise HTTPException(409, 'Create a Business workflow project for these observations')
            steps = [s.model_dump() for s in body.steps]
            existing = db.get(BusinessRun, str(body.run_id))
            if existing:
                if existing.project_id != pid or existing.steps_json != json.dumps(steps) or existing.observed_at != body.observed_at.timestamp():
                    raise HTTPException(409, 'Run ID already used for a different receipt')
                return {'accepted': True, 'duplicate': True}
            if not body.fresh():
                raise HTTPException(422, 'Observation must be no older than five minutes and not in the future')
            previous = latest(db, pid)
            if previous and body.observed_at.timestamp() <= previous.at:
                raise HTTPException(409, 'Out-of-order observation; send a new run')
            failed = next((s for s in steps if s['status'] == 'failed'), None)
            detail = ('Business workflow passed: login, cloud record, notebook and rendered review level verified. Read-only browser check.' if not failed
                      else f"Business workflow failed at {STEP_LABELS[failed['id']]}: {MESSAGES[failed['code']]}")
            db.add(BusinessRun(id=str(body.run_id), project_id=pid, observed_at=body.observed_at.timestamp(),
                               workflow=body.workflow, steps_json=json.dumps(steps)))
            record(db, p, not failed, sum(s['duration_ms'] for s in steps), detail, 'business', body.observed_at.timestamp())
            db.commit()
            return {'accepted': True, 'passed': not failed, 'duplicate': False}

    @app.post('/api/ingest/{pid}/deployment')
    def deployment(pid: str, body: Release, request: Request):
        with lock, Session() as db:
            p = db.get(Project, pid)
            if not p:
                raise HTTPException(404, 'Project not found')
            project_auth(request, p)
            d = Deployment(project_id=pid, **body.model_dump())
            db.add(d)
            db.flush()
            did, mode = d.id, p.mode
            event(db, pid, 'deployment_received', f'Version {body.version}; commit {body.commit or "not provided"}')
            db.commit()
        if mode in ('heartbeat', 'business'):
            return {'id': did, 'status': 'pending', 'detail': 'Deployment recorded; external observations are not version-correlated automatically'}
        result = run_check(pid, 'deployment')
        with Session() as db:
            d = db.get(Deployment, did)
            d.status = 'verified' if result['passed'] else 'failed'
            db.commit()
            return {'id': did, 'status': d.status, 'check': result}

    @app.post('/api/projects/{pid}/demo/{action}', dependencies=[Depends(auth)])
    def drill(pid: str, action: str, request: Request):
        if request.headers.get('x-confirm-operation') != 'yes':
            raise HTTPException(400, 'Explicit operator confirmation required')
        with lock, Session() as db:
            p = db.get(Project, pid)
            if not p or not p.demo or not demo:
                raise HTTPException(403, 'Recovery drill is restricted to seeded synthetic projects')
            if action not in ('pause', 'resume'):
                raise HTTPException(404, 'Unknown operation')
            if action == 'resume' and not p.fault:
                raise HTTPException(409, 'Precondition failed: worker is not paused')
            p.fault = action == 'pause'
            event(db, pid, 'fault_injected' if p.fault else 'recovery_approved',
                  'Synthetic worker paused' if p.fault else 'RB-001 approved; synthetic worker resumed. Verification required.')
            db.commit()
        return {'executed': True, 'verification_required': True}

    @app.patch('/api/incidents/{iid}', dependencies=[Depends(auth)])
    def update_incident(iid: str, body: IncidentUpdate):
        with lock, Session() as db:
            i = db.get(Incident, iid)
            if not i:
                raise HTTPException(404, 'Incident not found')
            if i.status == 'resolved':
                raise HTTPException(409, 'Incident is already resolved')
            if body.action == 'resolve':
                p = db.get(Project, i.project_id)
                status, c = state(db, p)
                if status != 'healthy' or c.at <= i.opened:
                    raise HTTPException(409, 'Run a fresh successful check after this incident before resolving')
                i.status, i.resolved = 'resolved', time.time()
            else:
                i.status = 'acknowledged'
            i.note = body.note.strip()
            event(db, i.project_id, 'incident_' + i.status, body.note.strip())
            db.commit()
            return {'status': i.status}

    @app.get('/api/reports/{cid}', dependencies=[Depends(auth)], response_class=PlainTextResponse)
    def report(cid: str):
        with Session() as db:
            client = db.get(Client, cid)
            if not client:
                raise HTTPException(404, 'Client not found')
            since = time.time() - 30 * 86400
            lines = [f'# Maintenance report — {client.name}', '', f'Generated: {stamp(time.time())}',
                     'Window: trailing 30 days. Draft for operator review.',
                     'Sample success rate is not time-based uptime. Missing observations do not establish availability.', '']
            for p in db.scalars(select(Project).where(Project.client_id == cid)):
                checks = list(db.scalars(select(Check).where(Check.project_id == p.id, Check.at >= since)))
                incidents = list(db.scalars(select(Incident).where(Incident.project_id == p.id, Incident.opened >= since)))
                events = list(db.scalars(select(Event).where(Event.project_id == p.id, Event.at >= since).order_by(Event.at)))
                status, _ = state(db, p)
                lines += [f'## {p.name} / {p.environment}', f'Source: {"SYNTHETIC DEMO" if p.demo else p.mode}',
                          f'Current observed state: {status}', f'Observations: {len(checks)}; passed: {sum(c.passed for c in checks)}',
                          f'Incidents opened in window: {len(incidents)}; unresolved: {sum(i.status != "resolved" for i in incidents)}',
                          'Backup restoration: not verified by this product.', '', '### Maintenance evidence']
                lines += [f'- {stamp(e.at)} | {e.kind} | {e.detail.replace(chr(10), " ")}' for e in events]
                lines += ['', '### Follow-up', *[f'- [{i.status}] {i.title}: {i.note or i.evidence}' for i in incidents], '']
                run = db.scalar(select(BusinessRun).where(BusinessRun.project_id == p.id, BusinessRun.observed_at >= since).order_by(BusinessRun.observed_at.desc()))
                if run:
                    lines += ['### Latest browser business check', f'Observed: {stamp(run.observed_at)}']
                    lines += [f"- {s['label']}: {s['status']} ({s['duration_ms']} ms) — {s['message']}" for s in step_evidence(json.loads(run.steps_json))]
                    lines += ['Credentials, raw responses and learning content are not included.', '']
            return '\n'.join(lines)

    if demo:
        with Session() as db:
            if not db.scalar(select(Client)):
                clients = [Client(name='Meridian Finance', contact='Alex Morgan', color='violet'), Client(name='Bloom Commerce', contact='Sarah Chen', color='rose'), Client(name='Forma Health', contact='Jamie de Vries', color='blue')]
                db.add_all(clients)
                db.flush()
                names = [('Invoice API', 'Azure', 0), ('Merchant storefront', 'AWS', 1), ('Patient portal', 'Azure', 2), ('Reporting worker', 'Coolify', 0)]
                for j, (name, provider, ci) in enumerate(names):
                    p = Project(name=name, client_id=clients[ci].id, provider=provider, mode='demo', demo=True, fault=j == 3, interval=300)
                    db.add(p)
                    db.flush()
                    for k in range(36):
                        failed = j == 3 and k >= 32
                        db.add(Check(project_id=p.id, at=time.time() - (35-k)*300, passed=not failed, latency=38+j*18+k%9,
                                     detail='Synthetic sample: worker processing timeout' if failed else 'Synthetic sample: workflow completed', source='demo'))
                    if j == 3:
                        db.add(Incident(project_id=p.id, title='Reporting queue is not processing', opened=time.time()-900,
                                        evidence='Synthetic drill: worker paused; background job checks are failing. API liveness alone would miss this.'))
                    db.add(Deployment(project_id=p.id, version=['v2.8.1','v1.12.0','v3.2.4','v2.8.1'][j], commit='demo', status='failed' if j == 3 else 'verified', at=time.time()-1800-j*900))
                    event(db, p.id, 'demo_seeded', 'Synthetic project and sample observations. Provider is a scenario label, not a connected cloud account.')
                db.commit()

    app.mount('/assets', StaticFiles(directory=ROOT / 'web' / 'assets'), name='assets')

    @app.get('/')
    def home():
        return FileResponse(ROOT / 'web' / 'index.html')

    return app
