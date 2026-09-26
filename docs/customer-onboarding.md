# Connecting a software studio's projects

## Product boundary

One installation serves one agency workspace. A client groups projects; each project represents one application environment. Create a separate project for staging and production. This version is not a multi-tenant service: all workspace operators can access all client groups. Do not give the agency operator token to a client.

## 1. Start with public visibility

Create a client, then use **Connect project → Public endpoint**. Supply a read-only health URL that you own or are authorized to monitor. Choose expected status and interval. No code repository, cloud account or server credentials are needed. Run the first check and inspect its evidence.

Probes accept HTTP/HTTPS on port 80/443 only. All DNS results must be globally routable, the outbound socket is pinned to the validated IP, and TLS verifies the original hostname. Redirects are not followed. Private/loopback/link-local destinations are rejected, including cloud metadata addresses. Use a dedicated health endpoint, not a payment or mutation URL. HTTP status does not prove login, payment or background jobs work.

## 2. Private services and workers

Choose **Outbound heartbeat**. Save the one-time project token in the application's secret store. Run `scripts/heartbeat.py` beside the customer service with:

```text
OPSPILOT_URL=https://your-control-plane.example
OPSPILOT_PROJECT_ID=<project-id>
OPSPILOT_PROJECT_TOKEN=<project-token>
HEALTH_URL=http://your-private-service/health
HEARTBEAT_INTERVAL=300
```

The script checks the local application and sends an authenticated observation. It does not collect environment variables, source code or arbitrary logs. A heartbeat saying healthy proves only what its sender checked. Configure a business-aware endpoint where possible. Two missed intervals mark existing data stale and open an incident; the scheduler checks every 30 seconds, so detection includes scheduling delay. Brand-new projects show pending until first observation, with a missing-heartbeat incident after the grace period.

The control plane must be reachable from the sender. A localhost demo URL is not reachable from a customer cloud environment. Use an HTTPS deployment before onboarding remote senders.

## 3. Release verification

Save the same scoped token as `OPSPILOT_PROJECT_TOKEN` in CI. After deployment, run `scripts/send-deployment.py` with `OPSPILOT_URL`, `OPSPILOT_PROJECT_ID`, `RELEASE_VERSION` and optional `GITHUB_SHA`. HTTP projects trigger a probe; the script exits nonzero unless the release verifies. Heartbeat release correlation is deliberately unsupported and returns pending, never a misleading success.

## Credential lifecycle

Tokens are project-scoped; only SHA-256 hashes persist. They grant ingestion but never workspace reads or remote execution. Rotate through project detail. Previous tokens stop immediately; update all senders. There is no grace period or multiple active tokens yet. Operator sessions expire after eight hours and are held in server memory, so deployment requires re-login.

## Work with incidents and reports

Failures open one unresolved incident per project. Acknowledge with a note, investigate in the customer's existing tools, then send a fresh check/heartbeat. Resolution requires a fresh passing observation after the incident opened. Demo-only RB-001 can simulate recovery; live projects have no execution controls.

Client reports contain trailing-30-day checks, maintenance events and incidents. They mark synthetic projects, describe coverage limitations and export Markdown. Review before sharing. OpsPilot never emails a client automatically.

## Commercial validation

Ask agencies to connect one noncritical project first. Measure onboarding time, actionable findings, manual verification time saved, false alerts and support effort. Discuss pricing only after showing evidence from their application. No paying users or demand validation is claimed by the demo.
