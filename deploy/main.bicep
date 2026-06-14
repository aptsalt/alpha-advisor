// ALPHA Advisor → Azure Container Apps.
// Provisions: a Container Apps environment, a Log Analytics workspace (traces/logs),
// and the app itself, wired to Azure OpenAI via a secret. Postgres (durable checkpointer)
// and Azure AI Search / Neo4j are referenced as parameters — point them at your instances.
//
//   az deployment group create -g <rg> -f deploy/main.bicep \
//       -p image=<acr>.azurecr.io/alpha-advisor:latest azureOpenAiKey=<key> \
//          azureOpenAiEndpoint=https://<res>.openai.azure.com checkpointDb=<pg-conn>

param location string = resourceGroup().location
param image string
param azureOpenAiEndpoint string
@secure()
param azureOpenAiKey string
@secure()
param checkpointDb string = ''   // postgres conn string for the durable checkpointer

var name = 'alpha-advisor'

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${name}-logs'
  location: location
  properties: { sku: { name: 'PerGB2018' }, retentionInDays: 90 }
}

resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${name}-env'
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
  name: name
  location: location
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      ingress: { external: true, targetPort: 8200, transport: 'auto' }
      secrets: [
        { name: 'azure-openai-key', value: azureOpenAiKey }
        { name: 'checkpoint-db', value: checkpointDb }
      ]
    }
    template: {
      containers: [
        {
          name: name
          image: image
          resources: { cpu: json('1.0'), memory: '2Gi' }
          env: [
            { name: 'ALPHA_PROVIDER', value: 'azure' }
            { name: 'AZURE_OPENAI_ENDPOINT', value: azureOpenAiEndpoint }
            { name: 'AZURE_OPENAI_API_KEY', secretRef: 'azure-openai-key' }
            { name: 'ALPHA_CHECKPOINT_DB', secretRef: 'checkpoint-db' }
            { name: 'ALPHA_TRACING', value: '1' }
          ]
        }
      ]
      // Scale to zero when idle; scale out on HTTP load. Paused runs live in the durable
      // checkpointer, so any replica can resume any run — safe to scale horizontally.
      scale: { minReplicas: 0, maxReplicas: 5, rules: [
        { name: 'http', http: { metadata: { concurrentRequests: '20' } } }
      ] }
    }
  }
}

output url string = 'https://${app.properties.configuration.ingress.fqdn}'
