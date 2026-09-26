# OpsPilot

**Your clients. In good hands.** An application maintenance workspace for small software studios, built as an Application Operations portfolio project with a commercial pilot hypothesis.

中文操作指南：[用户使用说明](docs/user-guide.zh-CN.md) — 启动登录、客户项目接入、故障处理、发布验证和报告导出。

真实登录与学习记录检查：[浏览器业务检查配置](docs/business-checks.zh-CN.md)。客户侧浏览器运行器核对登录身份、云端固定学习记录、单词本和复习界面；结果按步骤接入工作区。需自行配置专用测试账号，目前没有线上通过的声明。

## Run the SaaS workspace

Python 3.12+, PowerShell:

```powershell
cd D:\projects\opspilot
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

The launcher creates a virtual environment, installs pinned direct dependencies, and starts the app on **http://127.0.0.1:8080**. Click **Explore demo workspace**. Three clients and four application scenarios are seeded, with a worker incident for recovery practice. All seeded cloud labels and historical checks are explicitly synthetic. Demo mode is local-only in the launcher; do not publish it.

If port 8080 is occupied, pass `-Port 8081`. To run an empty, non-demo local workspace, set a strong `OPS_TOKEN` (24+ characters) and run `start.ps1 -Live`. Demo and live launch modes use separate default SQLite files. For cloud use, set PostgreSQL `DATABASE_URL`, disable demo access and enable secure cookies behind HTTPS.

### Sign-in options

The public landing page is shown before authentication. Anyone can create an email/password account; verified Google sign-in creates an account on first login. **Each account has its own isolated workspace for clients, projects, incidents and reports.** Email/password registration currently does not verify email ownership and there is no password reset or team role management. Google OAuth Testing mode only allows Google test users configured in Google Cloud. The existing `OPS_TOKEN` and optional `OPS_ADMIN_EMAIL` / `OPS_ADMIN_PASSWORD` login remain available. Set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` and `GOOGLE_REDIRECT_URI=https://<your-render-host>/api/auth/google/callback`; keep `OPS_SECURE_COOKIE=true` in production. `OPS_SESSION_SECRET` should be a stable random value to protect OAuth state cookies. Never commit secrets.

## Implemented

- Responsive SaaS interface: overview, projects, clients, incidents, releases, reports, connections, runbooks and workspace information.
- Three-step onboarding with client, project, environment, hosting label and connection method.
- Public HTTP(S) checks with TLS validation, pinned DNS resolution and private-address/redirect restrictions.
- Outbound heartbeats for private services; stale data remains unknown and missed check-ins create incidents.
- Per-project ingestion tokens, one-time display, hashed storage and immediate rotation.
- Authenticated release webhooks with endpoint verification and CI failure on unverified releases.
- Persistent checks, incident acknowledgement, guarded resolution, operator notes and UTC audit events.
- Demo-only approved recovery drill; live connections do not permit remote execution.
- Client report preview and Markdown export from real stored evidence, clearly marking synthetic samples.
- FastAPI + SQLAlchemy, SQLite for local use, PostgreSQL configuration in Compose and Azure.
- Bicep cloud baseline and manual GitHub OIDC deployment workflow for an existing Container App.

## Five-minute interview demo

1. Inspect the overview. Three sample projects are healthy and one worker has an incident.
2. Open **Reporting worker** and review the evidence.
3. Approve RB-001 recovery; the incident stays open.
4. Run a fresh check. Resolve the incident with an operational note.
5. Open the client's report and export the evidence.
6. Create a real project using the connection wizard. Show how HTTP checks, outbound heartbeats and deployment events avoid SSH access.

## Connect existing client applications

See [customer onboarding](docs/customer-onboarding.md). Start with an authorized read-only health URL. For private services, run [heartbeat.py](scripts/heartbeat.py) beside the service. For CI, use [send-deployment.py](scripts/send-deployment.py) with scoped secrets. Provider selections are labels; they do not imply cloud-account OAuth or automatic resource discovery.

## Verify

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest tests -q
node --check web/assets/app.js
az bicep build --file infra/azure/main.bicep
```

Backend checks cover auth, project-token isolation/revocation, SSRF restrictions, failed deployment handling, stale heartbeats, guarded resolution and report evidence, plus the original invoice lab. See [validation](docs/validation.md) for actual checks and limitations.

## Render updates

For the existing Render service, see [update and migration instructions](docs/render-update.md).

## Containers and Azure

Set `OPS_TOKEN` and a URL-safe `POSTGRES_PASSWORD`, then `docker compose up --build`. Compose runs the control plane and PostgreSQL, binding the UI to localhost. Docker Engine is required. See [Azure deployment](docs/azure-deployment.md) for infrastructure prerequisites, network allowlisting, budget considerations and what has not been deployed.

## Honest scope

Each registered account now has an isolated workspace. Existing shared data remains in the operator-token / configured-admin workspace. Team membership and invitations are not implemented. This is not a production-certified service. Email ownership verification, password reset, team RBAC, Entra ID login, customer portal, billing, AI investigation, remote production remediation, automatic notifications, backup restore verification, account discovery, tracing instrumentation and distributed scheduling are not implemented. Sessions live in process memory; deploy one replica. An additive startup migration adds workspace ownership to existing clients and audit events; deploy one replica during upgrades. General migration tooling and retention remain pending.

The new console's worker drill is a deterministic simulation. The original actual invoice queue lab remains available separately as `app.py` / `web/lab.html` with its original tests; it is not secretly presented as a customer cloud integration. Set `OPS_TOKEN` and `OPS_PORT=8081`, then run `python app.py` to use that lab alongside the SaaS workspace.

See [architecture](docs/architecture.md), [Exact JD evidence map](docs/exact-jd-evidence.md), [roadmap](docs/roadmap.md), and [incident template](docs/incident-template.md).
