"""OpsPilot local lab: synthetic invoices, worker, probes, and audited recovery."""
import hmac
import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).parent


def utc():
    return datetime.now(timezone.utc).isoformat()


class Lab:
    def __init__(self, database):
        Path(database).parent.mkdir(parents=True, exist_ok=True)
        self.database = str(database)
        self.lock = threading.RLock()
        self.paused = False
        self.stop = threading.Event()
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS invoices (
                    id TEXT PRIMARY KEY, created REAL NOT NULL,
                    status TEXT NOT NULL, completed REAL);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, at TEXT NOT NULL,
                    kind TEXT NOT NULL, detail TEXT NOT NULL);
            """)
        self.event('startup', 'Local synthetic lab started; worker enabled')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def event(self, kind, detail):
        with self.connect() as db:
            db.execute('INSERT INTO events(at,kind,detail) VALUES (?,?,?)',
                       (utc(), kind, detail))

    def submit(self):
        invoice_id = str(uuid.uuid4())
        with self.connect() as db:
            db.execute('INSERT INTO invoices VALUES (?,?,?,NULL)',
                       (invoice_id, time.time(), 'queued'))
        return invoice_id

    def invoice(self, invoice_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM invoices WHERE id=?', (invoice_id,)).fetchone()
        return dict(row) if row else None

    def tick(self):
        with self.lock:
            if self.paused:
                return
            with self.connect() as db:
                db.execute("UPDATE invoices SET status='completed',completed=? WHERE id IN "
                           "(SELECT id FROM invoices WHERE status='queued' ORDER BY created LIMIT 1)",
                           (time.time(),))

    def worker(self):
        while not self.stop.wait(0.5):
            try:
                self.tick()
            except sqlite3.Error as exc:
                print(f'Worker database error: {exc}', flush=True)

    def snapshot(self):
        with self.lock, self.connect() as db:
            counts = db.execute("SELECT COUNT(*) AS total, "
                                "SUM(status='queued') AS queued, SUM(status='completed') AS completed, "
                                "MIN(CASE WHEN status='queued' THEN created END) AS oldest FROM invoices").fetchone()
            events = [dict(row) for row in db.execute('SELECT * FROM events ORDER BY id DESC LIMIT 30')]
            age = max(0, time.time() - counts['oldest']) if counts['oldest'] else 0
            return {'at': utc(), 'environment': 'synthetic local lab', 'version': '0.1.0',
                    'api': 'healthy', 'worker': 'paused' if self.paused else 'running',
                    'business': 'degraded' if self.paused or age > 5 else 'healthy',
                    'queued': counts['queued'] or 0, 'completed': counts['completed'] or 0,
                    'oldest_queue_seconds': round(age, 1), 'events': events}

    def operate(self, action):
        with self.lock:
            if action == 'pause-worker':
                self.event('fault_injected', 'Operator paused synthetic worker (RB-001)')
                self.paused = True
            elif action == 'resume-worker':
                if not self.paused:
                    raise ValueError('Precondition failed: worker is not paused')
                self.event('recovery_approved', 'Operator approved RB-001: resume worker; verification pending')
                self.paused = False
            else:
                raise ValueError('Unknown operation')


def handler_for(lab, token):
    class Handler(BaseHTTPRequestHandler):
        def send_json(self, code, value):
            body = json.dumps(value).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == '/':
                body = (ROOT / 'web' / 'lab.html').read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == '/health/live':
                self.send_json(200, {'status': 'alive'})
            elif self.path == '/api/status':
                self.send_json(200, lab.snapshot())
            elif self.path.startswith('/api/invoices/'):
                invoice = lab.invoice(self.path.removeprefix('/api/invoices/'))
                self.send_json(200 if invoice else 404, invoice or {'error': 'Not found'})
            else:
                self.send_json(404, {'error': 'Not found'})

        def do_POST(self):
            if not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + token):
                self.send_json(401, {'error': 'Operator token required'})
                return
            if self.path == '/api/invoices':
                self.send_json(201, {'id': lab.submit()})
            elif self.path.startswith('/api/operations/'):
                if self.headers.get('X-Confirm-Operation') != 'yes':
                    self.send_json(400, {'error': 'Explicit confirmation required'})
                    return
                try:
                    lab.operate(self.path.removeprefix('/api/operations/'))
                    self.send_json(200, {'status': 'executed', 'verification': 'Run the business probe'})
                except ValueError as exc:
                    self.send_json(409, {'error': str(exc)})
            elif self.path == '/api/probe':
                invoice_id = lab.submit()
                deadline = time.monotonic() + 6
                while time.monotonic() < deadline:
                    if lab.invoice(invoice_id)['status'] == 'completed':
                        lab.event('probe_passed', f'Business probe completed invoice {invoice_id}')
                        self.send_json(200, {'result': 'PASS', 'invoice_id': invoice_id})
                        return
                    time.sleep(0.2)
                lab.event('probe_failed', f'Invoice {invoice_id} did not complete within 6 seconds')
                self.send_json(503, {'result': 'FAIL', 'invoice_id': invoice_id,
                                     'evidence': 'Invoice accepted but background processing timed out'})
            else:
                self.send_json(404, {'error': 'Not found'})
    return Handler


if __name__ == '__main__':
    token = os.environ.get('OPS_TOKEN', '')
    if len(token) < 16:
        raise SystemExit('Set OPS_TOKEN to at least 16 characters before starting.')
    lab = Lab(os.environ.get('OPS_DB', str(ROOT / 'data' / 'opspilot.db')))
    worker = threading.Thread(target=lab.worker, daemon=True)
    worker.start()
    host, port = os.environ.get('OPS_HOST', '127.0.0.1'), int(os.environ.get('OPS_PORT', '8080'))
    server = ThreadingHTTPServer((host, port), handler_for(lab, token))
    print(f'OpsPilot local lab: http://{host}:{port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        lab.stop.set()
        server.server_close()
        worker.join(timeout=2)
