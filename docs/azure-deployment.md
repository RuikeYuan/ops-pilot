# Azure deployment baseline

## What is implemented

`infra/azure/main.bicep` defines Container Apps, PostgreSQL Flexible Server, a user-assigned managed identity, Key Vault secrets and narrowly scoped Key Vault Secrets User access, Log Analytics and an Application Insights resource. The app reads its database URL and operator token through Key Vault references. The template disables demo login and enables Secure cookies. It uses a single replica because sessions and scheduler coordination are in-process.

Application Insights is provisioned as a foundation; application tracing instrumentation and alert action groups are NOT connected yet. Container stdout is routed to Log Analytics. A green readiness check verifies database reachability, not all customer workflows.

## Before provisioning

1. Select your subscription, region and isolated resource group. Review actual Azure pricing and set a resource-group budget alert manually. This template creates billable, continuously running database and application resources; no budget is provisioned automatically.
2. Build the Docker image and publish it to a registry you control. This baseline expects an anonymously pullable image, ideally pinned by digest. Private ACR integration is not included.
3. Generate a strong operator token and a URL-safe random database password (letters and digits, 24+ characters). Supply them through secure deployment parameters, not source control or command history.
4. Configure PostgreSQL firewall ranges for the application's actual outbound networking. `databaseAllowedRanges` is mandatory and has no allow-all default. The template uses public PostgreSQL with explicit allowlisting, not a VNet/private endpoint. For a real deployment, establish stable outbound IPs or adapt to private networking before provisioning the app. Do not guess IP ranges or enable the broad Azure-services firewall rule to get past setup.
5. The deployer needs resource creation and role-assignment permissions. Key Vault RBAC propagation may require a retry after initial provisioning.

## Local validation

```powershell
az bicep build --file infra/azure/main.bicep
```

Compilation checks template syntax and types; it does not validate subscription quota, region/SKU availability, network reachability or Azure deployment success. No cloud deployment has been performed as part of local implementation.

## Deploy after reviewing parameters

Use `az deployment group what-if` with an ignored local parameter file or your secret-aware pipeline first. Review resource scope and cost, then deploy the reviewed template. Keep secret values out of git. Test `/health/ready`, sign in with the operator token, and connect a canary endpoint. Confirm healthy and failure observations, incident gates, and report export in the cloud.

## Subsequent application releases

The manually triggered `azure-deploy.yml` updates an existing Container App using GitHub OIDC. Configure a federated identity scoped to this repository's `production` environment, environment protection rules, and variables `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `AZURE_APP_NAME`, `AZURE_RESOURCE_GROUP`, `OPSPILOT_URL`. It accepts only digest-pinned images and checks readiness. It does not provision infrastructure or promise safe rollback across database schema changes.

## Remaining production work

Entra ID/team RBAC, database migrations, ingestion rate limits, observation retention, stable outbound/private networking, distributed scheduler, alert notifications, tracing instrumentation, tested backup restoration, load tests and disaster recovery. Current shared operator-token authentication is a portfolio/small controlled-pilot boundary, not enterprise SaaS identity management.

## Sources used for the template

- [Container Apps secrets and Key Vault references](https://learn.microsoft.com/en-us/azure/container-apps/manage-secrets)
- [Managed identity](https://learn.microsoft.com/en-us/azure/container-apps/managed-identity)
- [Container Apps resource reference](https://learn.microsoft.com/en-us/azure/templates/microsoft.app/containerapps)
- [Python app with PostgreSQL on Azure](https://learn.microsoft.com/en-us/azure/developer/python/tutorial-deploy-python-web-app-azure-container-apps-02)
