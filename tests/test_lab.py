import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from app import Lab, handler_for


class LabTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.lab = Lab(Path(self.directory.name) / 'test.db')
        self.token = 'test-token-at-least-16-chars'
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(self.lab, self.token))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.lab.stop.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.directory.cleanup()

    def request(self, path, authorized=True, confirmed=False):
        headers = {'Authorization': 'Bearer ' + self.token} if authorized else {}
        if confirmed:
            headers['X-Confirm-Operation'] = 'yes'
        req = urllib.request.Request(f'http://127.0.0.1:{self.server.server_port}' + path,
                                     method='POST', headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as result:
                return result.status, json.load(result)
        except urllib.error.HTTPError as exc:
            return exc.code, json.load(exc)

    def test_fault_does_not_break_api_but_blocks_processing_then_recovers(self):
        self.lab.operate('pause-worker')
        invoice = self.lab.submit()
        self.lab.tick()
        self.assertEqual(self.lab.invoice(invoice)['status'], 'queued')
        self.assertEqual(self.lab.snapshot()['api'], 'healthy')
        self.assertEqual(self.lab.snapshot()['business'], 'degraded')
        self.lab.operate('resume-worker')
        self.lab.tick()
        completed = self.lab.invoice(invoice)
        self.assertEqual(completed['status'], 'completed')
        self.lab.tick()
        self.assertEqual(completed, self.lab.invoice(invoice))

    def test_operations_require_auth_confirmation_and_precondition(self):
        path = '/api/operations/pause-worker'
        self.assertEqual(self.request(path, authorized=False)[0], 401)
        self.assertEqual(self.request(path)[0], 400)
        self.assertFalse(self.lab.paused)
        self.assertEqual(self.request('/api/operations/resume-worker', confirmed=True)[0], 409)
        self.assertEqual(self.request(path, confirmed=True)[0], 200)
        self.assertTrue(self.lab.paused)

    def test_dashboard_and_read_only_status(self):
        base = f'http://127.0.0.1:{self.server.server_port}'
        with urllib.request.urlopen(base + '/') as response:
            self.assertIn(b'Run business probe', response.read())
        with urllib.request.urlopen(base + '/health/live') as response:
            self.assertEqual(json.load(response)['status'], 'alive')
        with urllib.request.urlopen(base + '/api/status') as response:
            self.assertEqual(json.load(response)['business'], 'healthy')

    def test_business_probe_fails_during_fault_and_passes_after_recovery(self):
        worker = threading.Thread(target=self.lab.worker)
        worker.start()
        try:
            self.assertEqual(self.request('/api/probe')[0], 200)
            self.lab.operate('pause-worker')
            code, result = self.request('/api/probe')
            self.assertEqual((code, result['result']), (503, 'FAIL'))
            self.lab.operate('resume-worker')
            self.assertEqual(self.request('/api/probe')[1]['result'], 'PASS')
            kinds = [event['kind'] for event in self.lab.snapshot()['events']]
            self.assertIn('probe_failed', kinds)
            self.assertIn('recovery_approved', kinds)
        finally:
            self.lab.stop.set()
            worker.join()


if __name__ == '__main__':
    unittest.main()
