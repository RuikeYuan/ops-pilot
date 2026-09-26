"""Read-only browser workflow for the Dutch learning app, without saved sessions."""
import json
import math
import os
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from control.business import STEP_IDS


class ConfigurationError(Exception):
    pass


class WorkflowFailure(Exception):
    def __init__(self, code):
        self.code = code


def origin(value):
    u = urlsplit(value)
    return f'{u.scheme}://{u.netloc}'


def safe_url(value):
    try:
        u = urlsplit(value)
        if not u.hostname or u.username or u.password or u.fragment or u.query:
            raise ValueError()
        if u.scheme != 'https' and not (u.scheme == 'http' and u.hostname in ('localhost', '127.0.0.1', '::1')):
            raise ValueError()
        if any(c.isspace() for c in value):
            raise ValueError()
        return value.rstrip('/')
    except ValueError:
        raise ConfigurationError('Use HTTPS URLs, or HTTP loopback URLs for local testing; omit URL credentials and query strings')


@dataclass(repr=False)
class Config:
    app_url: str
    supabase_url: str
    email: str
    password: str
    expected_user_id: str
    fixture_source_id: str
    fixture_level: int
    browser_channel: str = ''
    timeout_ms: int = 15000

    @classmethod
    def from_dict(cls, raw):
        email = os.getenv('DUTCH_TEST_EMAIL') or raw.get('email', '')
        password = os.getenv('DUTCH_TEST_PASSWORD') or raw.get('password', '')
        required = ['app_url', 'supabase_url', 'expected_user_id', 'fixture_source_id', 'fixture_level']
        if any(k not in raw or raw[k] == '' for k in required) or not email or not password:
            raise ConfigurationError('Fill app_url, supabase_url, expected_user_id, fixture_source_id, fixture_level and dedicated test email/password')
        try:
            user_id = str(uuid.UUID(raw['expected_user_id']))
            source_id = raw['fixture_source_id']
            if not re.fullmatch(r'[A-Z]\d+', source_id):
                raise ValueError()
            level = raw['fixture_level']
            timeout = raw.get('timeout_ms', 15000)
            if type(level) is not int or not 0 <= level <= 20 or type(timeout) is not int or not 1000 <= timeout <= 20000:
                raise ValueError()
            channel = raw.get('browser_channel', '')
            if channel not in ('', 'msedge', 'chrome'):
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise ConfigurationError('Check test user UUID, fixture source ID/level, timeout (1000–20000 ms), and browser channel')
        return cls(safe_url(raw['app_url']), safe_url(raw['supabase_url']), email, password,
                   user_id, source_id, level, channel, timeout)


def load_config(filename):
    try:
        raw = json.loads(Path(filename).read_text(encoding='utf-8-sig'))
        if not isinstance(raw, dict):
            raise ValueError()
    except (OSError, ValueError):
        raise ConfigurationError('Cannot read configuration JSON; copy config/dutch-business.example.json to a local file and fill it in')
    return Config.from_dict(raw), raw


def validate_payload(data, config):
    if not isinstance(data, dict) or not isinstance(data.get('payload'), dict):
        raise WorkflowFailure('record_missing')
    try:
        updated = datetime.fromisoformat(data['updated_at'].replace('Z', '+00:00'))
        if updated.tzinfo is None or updated.timestamp() <= 0 or updated.timestamp() > time.time() + 300:
            raise ValueError()
    except (KeyError, TypeError, ValueError, AttributeError):
        raise WorkflowFailure('record_missing')
    payload = data['payload']
    notebook, progress = payload.get('notebook'), payload.get('studyProgress')
    if not isinstance(notebook, list) or config.fixture_source_id not in notebook or not isinstance(progress, dict):
        raise WorkflowFailure('record_missing')
    row = progress.get(config.fixture_source_id)
    if not isinstance(row, dict) or row.get('level') != config.fixture_level:
        raise WorkflowFailure('record_missing')
    for key in ('level', 'correctStreak', 'lapses', 'lastReviewedAt', 'dueAt'):
        value = row.get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise WorkflowFailure('record_missing')
    if row['lastReviewedAt'] <= 0 or row['dueAt'] <= 0:
        raise WorkflowFailure('record_missing')
    return row


def run_workflow(config, context_setup=None):
    # Import only on execution: configuration validation works without a browser install.
    from playwright.sync_api import sync_playwright, TimeoutError as BrowserTimeout, expect

    steps = []
    failed = False
    token = ''
    api_key = ''
    responses = []
    saved_row = None
    saved_word = ''

    def step(name, action):
        nonlocal failed
        if failed:
            steps.append({'id': name, 'status': 'skipped', 'duration_ms': 0, 'code': 'not_run'})
            return
        started = time.monotonic()
        code = 'ok'
        try:
            action()
        except WorkflowFailure as exc:
            code = exc.code
        except BrowserTimeout:
            code = 'timeout'
        except Exception:
            # Never include Playwright exceptions: they can contain typed credentials,
            # response bodies, locators or page content.
            code = 'runner_error'
        failed = code != 'ok'
        steps.append({'id': name, 'status': 'failed' if failed else 'passed',
                      'duration_ms': min(120000, round((time.monotonic() - started) * 1000)), 'code': code})

    with sync_playwright() as pw:
        # A browser launch failure is a runner configuration error, not an app result.
        try:
            browser = pw.chromium.launch(headless=True, channel=config.browser_channel or None)
        except Exception:
            raise ConfigurationError('Browser could not start. Install Chromium with python -m playwright install chromium, or choose an installed browser channel')
        context = browser.new_context(service_workers='block', accept_downloads=False)
        context.set_default_timeout(config.timeout_ms)
        context.add_init_script("localStorage.setItem('dutch-frequency-app-ui-language','en')")
        # Caller-supplied setup is used ONLY by local fixture tests; CLI never loads code from config.
        if context_setup:
            context_setup(context)

        def guard(route):
            request = route.request
            url = urlsplit(request.url)
            is_auth = origin(request.url) == origin(config.supabase_url) and url.path == '/auth/v1/token' and parse_qs(url.query).get('grant_type') == ['password']
            local_logout = origin(request.url) == origin(config.supabase_url) and url.path == '/auth/v1/logout' and parse_qs(url.query).get('scope') == ['local']
            if request.method not in ('GET', 'HEAD', 'OPTIONS') and not (request.method == 'POST' and (is_auth or local_logout)):
                # The app automatically upserts sync data. Never let this read-only
                # probe overwrite data or trigger AI/billing/background mutations.
                route.abort('blockedbyclient')
                return
            route.fallback()

        context.route('**/*', guard)
        # Realtime is outside this check's scope; initial REST pull must succeed.
        # Do not connect to the server; leaving the intercepted socket unforwarded
        # avoids synchronous close callbacks re-entering the Playwright dispatcher.
        context.route_web_socket('**/*', lambda ws: None)
        page = context.new_page()

        def is_sync(response):
            u = urlsplit(response.url)
            return (origin(response.url) == origin(config.supabase_url) and u.path == '/rest/v1/sync_data'
                    and response.request.method == 'GET'
                    and parse_qs(u.query).get('user_id') == ['eq.' + config.expected_user_id])

        page.on('response', lambda response: responses.append(response) if is_sync(response) else None)

        def open_app():
            result = page.goto(config.app_url, wait_until='domcontentloaded')
            if not result or result.status >= 400 or origin(page.url) != origin(config.app_url):
                raise WorkflowFailure('navigation_failed')
            page.locator('.landing-nav-cta').click()
            page.locator('.sidebar-nav button[title="Notebook"]').click()
            page.locator('.auth-gate button').click()
            page.get_by_role('button', name='Email & password', exact=True).click()
            page.locator('.auth-password-form input[type="password"]').wait_for(state='visible')

        def login():
            nonlocal token, api_key
            page.locator('.auth-password-form input[type="email"]').fill(config.email)
            page.locator('.auth-password-form input[type="password"]').fill(config.password)
            with page.expect_response(lambda r: origin(r.url) == origin(config.supabase_url)
                                      and urlsplit(r.url).path == '/auth/v1/token'
                                      and r.request.method == 'POST') as response:
                page.locator('.auth-password-submit').click()
            r = response.value
            if r.status != 200:
                raise WorkflowFailure('login_failed')
            body = r.json()
            token = body.get('access_token', '')
            api_key = r.request.header_value('apikey') or ''
            if not token or not api_key or body.get('user', {}).get('id') != config.expected_user_id:
                raise WorkflowFailure('login_failed')
            user_response = page.evaluate("""async ([url, key, token, timeout]) => {
                const r = await fetch(url, {headers:{apikey:key, Authorization:'Bearer '+token},
                    redirect:'error', signal:AbortSignal.timeout(timeout)});
                return {status:r.status, user:r.ok ? await r.json() : null};
            }""", [config.supabase_url + '/auth/v1/user', api_key, token, config.timeout_ms])
            if user_response['status'] != 200 or (user_response['user'] or {}).get('id') != config.expected_user_id:
                raise WorkflowFailure('login_failed')
            page.locator('.account-nav-dot').wait_for(state='visible')

        def read_progress():
            nonlocal saved_row
            deadline = time.monotonic() + config.timeout_ms / 1000
            while not responses and time.monotonic() < deadline:
                page.wait_for_timeout(100)
            if not responses or responses[-1].status != 200:
                raise WorkflowFailure('sync_failed')
            saved_row = validate_payload(responses[-1].json(), config)
            # An empty isolated browser must receive the server record, not a cached
            # previous user's progress. Wait for the React sync effect to apply it.
            page.wait_for_function("([id, row]) => { const p=JSON.parse(localStorage.getItem('dutch-frequency-app-study-progress')||'{}')[id]; return p && ['level','correctStreak','lapses','lastReviewedAt','dueAt'].every(k=>p[k]===row[k]); }",
                                   arg=[config.fixture_source_id, saved_row])

        def render_notebook():
            nonlocal saved_word
            page.locator('.sidebar-nav button[title="Notebook"]').click()
            card = page.locator('#word-' + config.fixture_source_id)
            card.wait_for(state='visible')
            saved_word = card.locator('h2').inner_text().strip()
            if not saved_word:
                raise WorkflowFailure('notebook_failed')

        def render_progress():
            page.locator('.sidebar-nav button[title="Study"]').click()
            page.locator('.study-sidebar .jump-box input, .study-layout .jump-box input').fill(saved_word)
            page.locator('.study-layout .jump-box button[type="submit"]').click()
            expect(page.locator('.study-card .prompt h2')).to_have_text(saved_word, timeout=config.timeout_ms)
            expect(page.locator('.study-card .review-state small')).to_have_text(f'Memory level {config.fixture_level}', timeout=config.timeout_ms)

        try:
            for name, action in zip(STEP_IDS, [open_app, login, read_progress, render_notebook, render_progress]):
                step(name, action)
        finally:
            if token and api_key:
                try:
                    page.evaluate("""async ([url,key,token]) => {
                        await fetch(url, {method:'POST', headers:{apikey:key,Authorization:'Bearer '+token},
                            redirect:'error', signal:AbortSignal.timeout(3000)});
                    }""", [config.supabase_url + '/auth/v1/logout?scope=local', api_key, token])
                except Exception:
                    pass
            context.close()
            browser.close()
    return {'run_id': str(uuid.uuid4()), 'workflow': 'dutch-learning-v1',
            'observed_at': datetime.now(timezone.utc).isoformat(), 'steps': steps}
