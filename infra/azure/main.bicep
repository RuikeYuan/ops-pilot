targetScope = 'resourceGroup'

@description('Short lowercase prefix for globally unique resource names.')
@maxLength(12)
param prefix string = 'opspilot'
param location string = resourceGroup().location
@description('Publicly accessible image, preferably pinned by sha256 digest.')
param image string
@secure()
@minLength(24)
param operatorToken string
@secure()
@description('URL-safe password: use random letters and digits. Connection string is constructed without URL encoding.')
@minLength(24)
param databasePassword string
@description('Explicit IPv4 egress ranges allowed to reach PostgreSQL; determine from your network configuration.')
@minLength(1)
param databaseAllowedRanges array
param workspaceName string = 'My studio'

var suffix = uniqueString(resourceGroup().id)
var appName = '${prefix}-${suffix}'
var vaultName = '${prefix}-${suffix}'

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${prefix}-identity'
  location: location
}
resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${prefix}-logs'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
    workspaceCapping: { dailyQuotaGb: 1 }
  }
}
resource insights 'Microsoft.Insights/components@2020-02-02' = {
  name: '${prefix}-insights'
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logs.id
  }
}
resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: vaultName
  location: location
  properties: {
    tenantId: tenant().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    publicNetworkAccess: 'Enabled'
  }
}
resource secretReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(vault.id, identity.id, 'secrets-user')
  scope: vault
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')
  }
}
resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: '${prefix}-pg-${suffix}'
  location: location
  sku: { name: 'Standard_B1ms', tier: 'Burstable' }
  properties: {
    version: '16'
    administratorLogin: 'opsadmin'
    administratorLoginPassword: databasePassword
    storage: { storageSizeGB: 32 }
    backup: { backupRetentionDays: 7, geoRedundantBackup: 'Disabled' }
    highAvailability: { mode: 'Disabled' }
    network: { publicNetworkAccess: 'Enabled' }
  }
}
resource db 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: postgres
  name: 'opspilot'
  properties: { charset: 'UTF8', collation: 'en_US.utf8' }
}
resource firewall 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = [for (range, i) in databaseAllowedRanges: {
  parent: postgres
  name: 'explicit-egress-${i}'
  properties: { startIpAddress: range.start, endIpAddress: range.end }
}]
resource dbSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'database-url'
  properties: { value: 'postgresql+psycopg://opsadmin:${databasePassword}@${postgres.properties.fullyQualifiedDomainName}:5432/opspilot?sslmode=require' }
}
resource tokenSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'operator-token'
  properties: { value: operatorToken }
}
resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${prefix}-environment'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}
resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: appName
  location: location
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identity.id}': {} } }
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: { external: true, targetPort: 8080, allowInsecure: false, transport: 'http' }
      secrets: [
        { name: 'database-url', keyVaultUrl: dbSecret.properties.secretUri, identity: identity.id }
        { name: 'operator-token', keyVaultUrl: tokenSecret.properties.secretUri, identity: identity.id }
      ]
    }
    template: {
      scale: { minReplicas: 1, maxReplicas: 1 }
      containers: [{
        name: 'control'
        image: image
        resources: { cpu: json('0.5'), memory: '1Gi' }
        env: [
          { name: 'DATABASE_URL', secretRef: 'database-url' }
          { name: 'OPS_TOKEN', secretRef: 'operator-token' }
          { name: 'OPS_DEMO', value: 'false' }
          { name: 'OPS_SECURE_COOKIE', value: 'true' }
          { name: 'OPS_WORKSPACE', value: workspaceName }
          { name: 'OPS_REGION', value: location }
        ]
        probes: [
          { type: 'Liveness', httpGet: { path: '/health/live', port: 8080 }, initialDelaySeconds: 15, periodSeconds: 20 }
          { type: 'Readiness', httpGet: { path: '/health/ready', port: 8080 }, initialDelaySeconds: 10, periodSeconds: 15 }
        ]
      }]
    }
  }
  dependsOn: [secretReader, db, firewall]
}
output appUrl string = 'https://${app.properties.configuration.ingress.fqdn}'
output appResourceName string = app.name
output appInsightsResourceId string = insights.id
output databaseHost string = postgres.properties.fullyQualifiedDomainName
