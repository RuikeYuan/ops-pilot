"""Exit nonzero when a synthetic invoice cannot complete after a release."""
import json
import os
import sys
import urllib.error
import urllib.request

base = os.environ.get('OPS_URL', 'http://127.0.0.1:8080').rstrip('/')
token = os.environ.get('OPS_TOKEN')
if not token:
    raise SystemExit('OPS_TOKEN is required')
request = urllib.request.Request(base + '/api/probe', method='POST',
                                 headers={'Authorization': 'Bearer ' + token})
try:
    with urllib.request.urlopen(request, timeout=15) as response:
        result = json.load(response)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result.get('result') == 'PASS' else 1)
except urllib.error.HTTPError as exc:
    print(exc.read().decode(), file=sys.stderr)
    sys.exit(1)
except urllib.error.URLError as exc:
    print(f'Probe connection failed: {exc.reason}', file=sys.stderr)
    sys.exit(1)
