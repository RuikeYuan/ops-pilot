"""Run locally or on the customer's runner, then send only redacted step results."""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from runners.dutch_business import ConfigurationError, load_config, run_workflow, safe_url


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='config/dutch-business.local.json')
    parser.add_argument('--no-publish', action='store_true', help='Run without sending evidence to OpsPilot')
    parser.add_argument('--validate-config', action='store_true', help='Validate fields only; do not open the application')
    args = parser.parse_args()
    try:
        config, raw = load_config(args.config)
        if not args.no_publish:
            base = safe_url(os.getenv('OPSPILOT_URL') or raw.get('opspilot_url', ''))
            project = os.getenv('OPSPILOT_PROJECT_ID') or raw.get('opspilot_project_id', '')
            token = os.getenv('OPSPILOT_PROJECT_TOKEN') or raw.get('opspilot_project_token', '')
            if not project or not token or not all(c.isalnum() or c in '-_' for c in project):
                raise ConfigurationError('Configure the business project ID and its ingestion token, or use --no-publish')
        if args.validate_config:
            print('Configuration valid. No login or network check performed.')
            return 0
        receipt = run_workflow(config)
    except ConfigurationError as exc:
        print(f'Configuration error: {exc}', file=sys.stderr)
        return 2
    except Exception:
        print('Runner failed before a complete receipt was available. Check browser installation and local configuration.', file=sys.stderr)
        return 2
    print(json.dumps(receipt, indent=2))
    if not args.no_publish:
        request = urllib.request.Request(f'{base}/api/ingest/{project}/business-check',
            data=json.dumps(receipt).encode(), headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=20) as response:
                if response.status != 200 or not json.load(response).get('accepted'):
                    print('Evidence not accepted by OpsPilot', file=sys.stderr)
                    return 2
        except (urllib.error.URLError, TimeoutError, ValueError):
            print('Evidence delivery failed. Check OpsPilot URL, project mode, token and runner clock.', file=sys.stderr)
            return 2
        print('Redacted business-check evidence delivered to OpsPilot.')
    return 0 if all(s['status'] == 'passed' for s in receipt['steps']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
