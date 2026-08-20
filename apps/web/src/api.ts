import type {
  AskResult,
  AgentMeshOverview,
  AgentRun,
  BackupItem,
  ConnectorType,
  DataSource,
  EffectiveConfiguration,
  EvaluationReport,
  ModelProvider,
  ModelProviderPreset,
  ModelRoute,
  ObjectInstance,
  PipelinePreview,
  SemanticOverview,
  SemanticChange,
  SqlTemplate,
} from './types'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    ...init,
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(payload.detail || `请求失败：${response.status}`)
  }
  return response.json() as Promise<T>
}

export function fetchSemanticOverview(): Promise<SemanticOverview> {
  return request('/api/v1/semantics/overview')
}

export function fetchAgentMesh(): Promise<AgentMeshOverview> {
  return request('/api/v1/agent-mesh/overview')
}

export function runAgentFlow(payload: {
  flow_key: string
  question?: string
  source_key?: string
  scope?: Record<string, string>
}): Promise<AgentRun> {
  return request('/api/v1/agent-mesh/runs', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function askData(question: string, objectId: string): Promise<AskResult> {
  return request('/api/v1/query/ask', {
    method: 'POST',
    body: JSON.stringify({ question, scope: { object_id: objectId } }),
  })
}

export async function fetchObjectInstances(): Promise<ObjectInstance[]> {
  return (await request<{ items: ObjectInstance[] }>('/api/v1/ontology/instances?limit=500')).items
}

export async function fetchSqlTemplates(): Promise<SqlTemplate[]> {
  return (await request<{ items: SqlTemplate[] }>('/api/v1/tools/sql-templates')).items
}

export async function fetchBackups(): Promise<BackupItem[]> {
  return (await request<{ items: BackupItem[] }>('/api/v1/system/backups')).items
}

export function createBackup(): Promise<BackupItem> {
  return request('/api/v1/system/backups', { method: 'POST' })
}

export function saveSqlTemplate(template: SqlTemplate): Promise<SqlTemplate> {
  return request(`/api/v1/tools/sql-templates/${template.key}`, {
    method: 'PUT',
    body: JSON.stringify(template),
  })
}

export async function validateSqlTemplate(template: SqlTemplate): Promise<Record<string, unknown>> {
  return request('/api/v1/tools/sql-templates/validate', {
    method: 'POST',
    body: JSON.stringify(template),
  })
}

export async function fetchConnectorTypes(): Promise<ConnectorType[]> {
  return (await request<{ items: ConnectorType[] }>('/api/v1/data-sources/types')).items
}

export async function fetchDataSources(): Promise<DataSource[]> {
  return (await request<{ items: DataSource[] }>('/api/v1/data-sources')).items
}

export function saveDataSource(source: DataSource): Promise<DataSource> {
  return request(`/api/v1/data-sources/${source.key}`, {
    method: 'PUT',
    body: JSON.stringify(source),
  })
}

export function testDataSource(key: string): Promise<{ status: string; message: string }> {
  return request(`/api/v1/data-sources/${key}/test`, { method: 'POST' })
}

export async function previewImport(file: File): Promise<Record<string, unknown>> {
  const form = new FormData()
  form.append('file', file)
  const response = await fetch('/api/v1/imports/preview', { method: 'POST', body: form })
  if (!response.ok) throw new Error(`导入预检失败：${response.status}`)
  return response.json() as Promise<Record<string, unknown>>
}

export async function inspectImage(
  file: File,
  objectId: string,
  prompt: string,
): Promise<{
  status: string
  object_id: string
  analysis: string
  model: string
  provider_key: string
  mode: string
  note: string
}> {
  const form = new FormData()
  form.append('file', file)
  const parameters = new URLSearchParams({ object_id: objectId, prompt })
  const response = await fetch(`/api/v1/multimodal/inspect?${parameters}`, {
    method: 'POST',
    body: form,
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(payload.detail || `图像理解失败：${response.status}`)
  }
  return response.json()
}

export function importSemantics(content: string, apply: boolean): Promise<{
  valid: boolean
  domain: string
  version: string
  assets: number
  relations: number
  applied: boolean
  protective_backup?: string
}> {
  return request('/api/v1/semantics/import', {
    method: 'POST',
    body: JSON.stringify({ content, apply }),
  })
}

export async function fetchModelGateway(): Promise<{
  providers: ModelProvider[]
  presets: ModelProviderPreset[]
  routes: ModelRoute[]
  configuration: EffectiveConfiguration
}> {
  const [providers, presets, routes, configuration] = await Promise.all([
    request<{ items: ModelProvider[] }>('/api/v1/model-gateway/providers'),
    request<{ providers: ModelProviderPreset[] }>('/api/v1/model-gateway/presets'),
    request<{ items: ModelRoute[] }>('/api/v1/model-gateway/routes'),
    request<EffectiveConfiguration>('/api/v1/system/configuration'),
  ])
  return {
    providers: providers.items,
    presets: presets.providers,
    routes: routes.items,
    configuration,
  }
}

export function saveModelProvider(provider: ModelProvider): Promise<ModelProvider> {
  return request(`/api/v1/model-gateway/providers/${provider.key}`, {
    method: 'PUT',
    body: JSON.stringify(provider),
  })
}

export function probeModelProvider(key: string): Promise<{
  status: string
  message: string
  detected_mode: string
  capabilities: string[]
  models: string[]
  warning?: string
  confirmation_required: boolean
}> {
  return request(`/api/v1/model-gateway/providers/${key}/probe`, { method: 'POST' })
}

export function saveModelRoute(route: ModelRoute): Promise<ModelRoute> {
  return request(`/api/v1/model-gateway/routes/${route.key}`, {
    method: 'PUT',
    body: JSON.stringify({
      role: route.key,
      provider_key: route.provider_key,
      model_override: route.model_override || null,
      parameter_overrides: route.parameter_overrides,
    }),
  })
}

export async function fetchLatestEvaluation(): Promise<EvaluationReport | null> {
  const result = await request<{ status: string; report: EvaluationReport | null }>(
    '/api/v1/governance/evaluations/latest',
  )
  return result.report
}

export function runCertifiedEvaluation(): Promise<EvaluationReport> {
  return request('/api/v1/governance/evaluations', { method: 'POST' })
}

export async function fetchSemanticChanges(): Promise<SemanticChange[]> {
  return (await request<{ items: SemanticChange[] }>('/api/v1/governance/changes')).items
}

export function decideSemanticChange(
  changeId: string,
  action: 'start_review' | 'approve' | 'reject' | 'publish' | 'rollback',
  comment: string,
): Promise<SemanticChange> {
  return request(`/api/v1/governance/changes/${changeId}/decision`, {
    method: 'POST',
    body: JSON.stringify({ action, actor: 'semantic_owner', comment }),
  })
}

export function proposeSemanticAsset(payload: {
  key: string
  kind: 'metric'
  label: string
  description: string
  domain: string
  owner: string
  aliases: string[]
  unit?: string
  dimensions: string[]
  expression: string
}): Promise<SemanticChange> {
  return request('/api/v1/governance/asset-candidates', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function restoreBackup(name: string): Promise<{
  restored: string
  protective_backup: string
}> {
  return request(`/api/v1/system/backups/${encodeURIComponent(name)}/restore`, {
    method: 'POST',
    body: JSON.stringify({ confirmation: 'RESTORE' }),
  })
}

export function previewPipeline(payload: {
  key: string
  label: string
  source: string
  target: string
  mode: 'preview'
  steps: Array<{ operation: string; configuration: Record<string, unknown> }>
}): Promise<PipelinePreview> {
  return request('/api/v1/pipelines/preview?limit=50', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}
