# Update the existing Render service

Use the existing service connected to `RuikeYuan/ops-pilot`, branch `main`.
Do not create another Blueprint or database just to update application code.

## Environment

- `DATABASE_URL`: existing Render Postgres internal connection URL. Both `postgresql://` and `postgres://` are normalized to the installed psycopg driver.
- `OPS_TOKEN`: retain the existing strong operator token (24+ characters).
- `OPS_DEMO=false`, `OPS_SECURE_COOKIE=true`.
- Keep one application instance / one Uvicorn worker.
- Google login remains optional and requires its existing client credentials and the deployed callback URL.

Do not store real accounts in container-local SQLite: Render's ephemeral filesystem does not persist across deployments. Preserve the current database and take a database backup before upgrading real customer data.

## Version 0.5.0 migration

Startup adds workspace ownership columns and indexes to existing clients and audit events. This migration preserves existing rows and can run again. Existing shared data belongs to the legacy operator workspace, accessible using the operator token or configured administrator credentials. Existing and new registered accounts get individual workspaces keyed to their account IDs. No existing shared data is guessed to belong to a registered account.

Accounts cannot read another workspace's projects, incidents, events, deployments or reports, or mutate its resources. Ingestion still requires the target project's token. Password and Google accounts are not automatically linked by an unverified email address.

This release does not implement team invitations, email verification or password reset. Each account is a separate workspace, not yet a multi-member team. Restarting the app expires sessions; users sign in again.

## Release and verification

Push the tested commit to `main`. If auto-deploy is enabled, Render rebuilds the service. Otherwise select **Manual Deploy → Deploy latest commit** on the existing service.

After Render reports Live:

1. `/health/live` must return version `0.5.0`.
2. `/health/ready` must return HTTP 200.
3. `/api/config` must show registration enabled and demo disabled.
4. Register a test account, add a client, sign out, and sign back in: the client must remain.
5. Register a second account: its workspace must be empty. The first account's report and project-operation URLs must return 404 under the second account.
6. Confirm the operator can still access pre-upgrade shared data.

Do not roll back to a shared-workspace release with public registration enabled: it removes account isolation even though the new columns remain.

References: [Render deploys](https://render.com/docs/deploys), [Render PostgreSQL](https://render.com/docs/postgresql-creating-connecting).
