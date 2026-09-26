"""Run beside a private application; checks its URL, sends an outbound heartbeat."""
import json
import os
import time
import urllib.error
import urllib.request

base = os.environ['OPSPILOT_URL'].rstrip('/')
pid = os.environ['OPSPILOT_PROJECT_ID']
token = os.environ['OPSPILOT_PROJECT_TOKEN']
target = os.environ['HEALTH_URL']
interval = max(60, int(os.getenv('HEARTBEAT_INTERVAL', '300')))

while True:
    healthy = False
    try:
        with urllib.request.urlopen(target, timeout=10) as response:
            healthy = response.status == 200
        detail = 'Local health endpoint passed' if healthy else 'Local health endpoint returned an unexpected status'
    except (urllib.error.URLError, TimeoutError):
        detail = 'Local health endpoint failed or timed out'
    request = urllib.request.Request(f'{base}/api/ingest/{pid}/heartbeat',
        data=json.dumps({'healthy': healthy, 'detail': detail}).encode(),
        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            print(f'Heartbeat accepted; healthy={healthy}', flush=True)
    except (urllib.error.URLError, TimeoutError):
        print('Heartbeat delivery failed; retrying next interval', flush=True)
    time.sleep(interval)
