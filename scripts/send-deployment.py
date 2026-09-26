"""CI release receipt. A non-verified result fails the CI step."""
import json
import os
import sys
import urllib.error
import urllib.request

base = os.environ['OPSPILOT_URL'].rstrip('/')
project = os.environ['OPSPILOT_PROJECT_ID']
token = os.environ['OPSPILOT_PROJECT_TOKEN']
payload = {'version': os.environ['RELEASE_VERSION'], 'commit': os.getenv('GITHUB_SHA', '')}
request = urllib.request.Request(f'{base}/api/ingest/{project}/deployment',
    data=json.dumps(payload).encode(), headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'})
try:
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.load(response)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result['status'] == 'verified' else 1)
except urllib.error.HTTPError as exc:
    print(f'OpsPilot returned HTTP {exc.code}', file=sys.stderr)
    sys.exit(1)
except urllib.error.URLError as exc:
    print(f'OpsPilot connection failed: {exc.reason}', file=sys.stderr)
    sys.exit(1)
