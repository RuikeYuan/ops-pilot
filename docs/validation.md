# Local validation record

Validated on Windows / Python 3.12, 2026-09-26.

- `python -m pytest tests -q`: 19 passed. One upstream Starlette warning recommends a future test-client HTTP dependency transition; tests pass with the installed httpx.
- `node --check web/assets/app.js`: passed.
- `az bicep build --file infra/azure/main.bicep`: passed with Bicep 0.41.2. This is compile-time validation, not cloud provisioning.
- Browser: demo login; dashboard and project detail; approval → fresh check → incident resolution; create client → three-step heartbeat project onboarding → scoped heartbeat ingest; client report preview and Markdown download; mobile navigation.
- Local `/health/ready`: returns ready.

Docker Engine was not running, so image build and PostgreSQL-in-Compose execution have not been verified locally. Azure resources have not been provisioned. No claim is made about production traffic, uptime or customer deployments.
