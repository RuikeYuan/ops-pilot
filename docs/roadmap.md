# Delivery roadmap

## Implemented locally

- Agency SaaS UI, clients/projects/environments, scoped onboarding.
- Public URL checks, heartbeat ingest and stale detection, release events.
- Incident lifecycle, explicit demo recovery, fresh-check resolution gate.
- Report preview/export and UTC evidence timeline.
- SQLite local database, PostgreSQL adapter/configuration, Docker Compose.
- Azure Bicep baseline and GitHub OIDC deployment workflow.
- API integration tests and browser acceptance flow.

## Next: cloud evidence

- Choose Azure subscription, budget, public image and PostgreSQL network boundaries.
- Validate the baseline in that subscription; deploy and exercise a real canary.
- Instrument Application Insights/OpenTelemetry and configure alert routing.
- Separate monitored invoice API, worker and database from the control plane.
- Perform bad-release, queue-stall and database-connection drills; collect measured detection/recovery times.
- Add database migrations, tested backups and restoration evidence before customer production data.

## Next: controlled customer pilot

- Agency identity and roles, scoped project access, audit identity.
- Dedicated scheduler, bounded ingest, event retention and pagination.
- Deployment/check correlation and idempotency for retries.
- Customer-specific business probes and carefully bounded remediation adapter.
- Observe one real agency project and measure actionable findings, onboarding friction and support cost.

## Later, only if supported by demand

AI investigation with cited telemetry evidence, more cloud connectors, client portal, billing and multi-tenant hosting. Do not claim these as shipped. Commercial demand remains unvalidated.
