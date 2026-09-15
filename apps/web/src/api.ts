import type {
  AskResult,
  AgentMeshOverview,
  AgentRun,
  BackupItem,
  ConnectorType,
  ConversationDetail,
  ConversationSummary,
  DataSource,
  DifyIntegrationStatus,
  EffectiveConfiguration,
  EvaluationReport,
  FeedbackResult,
  GoldenQuestionSet,
  KnowledgeBase,
  KnowledgeDocument,
  KnowledgeHit,
  ModelProvider,
  ModelProviderPreset,
  ModelRoute,
  ObjectInstance,
  PipelinePreview,
  PythonExtension,
  PythonExtensionRun,
  QueryAttachment,
  RuntimeControlPlane,
  RuntimeEvaluation,
  SemanticOverview,
  SemanticChange,
  SqlPreview,
  SqlTemplate,
  SqlTemplateVersion,
  StoredPipeline,
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

export function askData(question: string): Promise<AskResult> {
  return request('/api/v1/query/ask', {
    method: 'POST',
    body: JSON.stringify({ question }),
  })
}

export async function uploadQueryAttachment(file: File): Promise<QueryAttachment> {
  const form = new FormData()
  form.append('file', file)
  const response = await fetch('/api/v1/query/attachments', { method: 'POST', body: form })
  if (!response.ok) {
    const payload = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(payload.detail || `附件读取失败：${response.status}`)
  }
  return response.json() as Promise<QueryAttachment>
}

export async function askDataStream(
  question: string,
  attachments: QueryAttachment[],
  conversationId: string,
  callbacks: {
    onProgress: (stage: string, message: string) => void
    onDelta: (text: string) => void
  },
): Promise<AskResult> {
  const response = await fetch('/api/v1/query/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, attachments, conversation_id: conversationId }),
  })
  if (!response.ok || !response.body) {
    const payload = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(payload.detail || `请求失败：${response.status}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let completed: AskResult | null = null
  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value, { stream: !done })
    const blocks = buffer.split(/\r?\n\r?\n/)
    buffer = blocks.pop() ?? ''
    for (const block of blocks) {
      const lines = block.split(/\r?\n/)
      const event = lines.find((line) => line.startsWith('event:'))?.slice(6).trim()
      const data = lines.filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trim()).join('\n')
      if (!event || !data) continue
      const payload = JSON.parse(data) as Record<string, unknown>
      if (event === 'progress') callbacks.onProgress(String(payload.stage), String(payload.message))
      if (event === 'delta') callbacks.onDelta(String(payload.text ?? ''))
      if (event === 'error') throw new Error(String(payload.message || '问数失败'))
      if (event === 'complete') completed = payload as unknown as AskResult
    }
    if (done) break
  }
  if (!completed) throw new Error('流式回答意外中断，请重试。')
  return completed
}

export async function fetchConversations(): Promise<ConversationSummary[]> {
  return (await request<{ items: ConversationSummary[] }>(
    '/api/v1/query/conversations',
  )).items
}

export function createConversation(title = '新对话'): Promise<ConversationSummary> {
  return request('/api/v1/query/conversations', {
    method: 'POST',
    body: JSON.stringify({ title }),
  })
}

export function submitTurnFeedback(
  conversationId: string,
  turnId: string,
  rating: 'like' | 'dislike',
  content = '',
): Promise<FeedbackResult> {
  return request(
    `/api/v1/query/conversations/${encodeURIComponent(conversationId)}/turns/${encodeURIComponent(turnId)}/feedback`,
    {
      method: 'POST',
      body: JSON.stringify({ rating, content }),
    },
  )
}

export function fetchConversation(conversationId: string): Promise<ConversationDetail> {
  return request(`/api/v1/query/conversations/${encodeURIComponent(conversationId)}`)
}

export function renameConversation(
  conversationId: string,
  title: string,
): Promise<ConversationSummary> {
  return request(`/api/v1/query/conversations/${encodeURIComponent(conversationId)}`, {
    method: 'PUT',
    body: JSON.stringify({ title }),
  })
}

export async function deleteConversation(conversationId: string): Promise<void> {
  const response = await fetch(
    `/api/v1/query/conversations/${encodeURIComponent(conversationId)}`,
    { method: 'DELETE' },
  )
  if (!response.ok) throw new Error(`删除会话失败：${response.status}`)
}

export function fetchDifyIntegrationStatus(): Promise<DifyIntegrationStatus> {
  return request('/api/v1/integrations/dify/status')
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

export async function fetchSqlTemplateVersions(key: string): Promise<SqlTemplateVersion[]> {
  return (await request<{ items: SqlTemplateVersion[] }>(
    `/api/v1/tools/sql-templates/${encodeURIComponent(key)}/versions`,
  )).items
}

export function previewSqlTemplate(
  key: string,
  parameters: Record<string, unknown>,
): Promise<SqlPreview> {
  return request(`/api/v1/tools/sql-templates/${encodeURIComponent(key)}/preview`, {
    method: 'POST',
    body: JSON.stringify({ parameters, limit: 100 }),
  })
}

export async function deleteSqlTemplate(key: string): Promise<void> {
  const response = await fetch(`/api/v1/tools/sql-templates/${encodeURIComponent(key)}`, {
    method: 'DELETE',
  })
  if (!response.ok) throw new Error(`删除失败：${response.status}`)
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

export async function fetchKnowledgeBases(): Promise<KnowledgeBase[]> {
  return (await request<{ items: KnowledgeBase[] }>('/api/v1/knowledge-bases')).items
}

export function saveKnowledgeBase(knowledgeBase: KnowledgeBase): Promise<KnowledgeBase> {
  return request(`/api/v1/knowledge-bases/${encodeURIComponent(knowledgeBase.key)}`, {
    method: 'PUT',
    body: JSON.stringify(knowledgeBase),
  })
}

export function testKnowledgeBase(key: string): Promise<{ status: string; message: string }> {
  return request(`/api/v1/knowledge-bases/${encodeURIComponent(key)}/test`, { method: 'POST' })
}

export async function fetchKnowledgeDocuments(key: string): Promise<KnowledgeDocument[]> {
  return (await request<{ items: KnowledgeDocument[] }>(
    `/api/v1/knowledge-bases/${encodeURIComponent(key)}/documents`,
  )).items
}

export async function uploadKnowledgeDocument(key: string, file: File): Promise<Record<string, unknown>> {
  const form = new FormData()
  form.append('file', file)
  const response = await fetch(
    `/api/v1/knowledge-bases/${encodeURIComponent(key)}/documents/upload`,
    { method: 'POST', body: form },
  )
  if (!response.ok) {
    const payload = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(payload.detail || `文档导入失败：${response.status}`)
  }
  return response.json() as Promise<Record<string, unknown>>
}

export async function deleteKnowledgeDocument(key: string, documentId: string): Promise<void> {
  const response = await fetch(
    `/api/v1/knowledge-bases/${encodeURIComponent(key)}/documents/${encodeURIComponent(documentId)}`,
    { method: 'DELETE' },
  )
  if (!response.ok) throw new Error(`删除失败：${response.status}`)
}

export async function searchKnowledge(query: string, topK = 5): Promise<{
  items: KnowledgeHit[]
  warnings: string[]
}> {
  return request('/api/v1/knowledge/search', {
    method: 'POST',
    body: JSON.stringify({ query, top_k: topK }),
  })
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

export function fetchGoldenQuestionSet(): Promise<GoldenQuestionSet> {
  return request('/api/v1/governance/golden-question-set')
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

export async function fetchPipelines(): Promise<StoredPipeline[]> {
  return (await request<{ items: StoredPipeline[] }>('/api/v1/pipelines')).items
}

export function savePipeline(pipeline: StoredPipeline): Promise<StoredPipeline> {
  return request(
    `/api/v1/pipelines/${encodeURIComponent(pipeline.key)}?published=${pipeline.published}`,
    { method: 'PUT', body: JSON.stringify(pipeline) },
  )
}

export async function fetchPythonExtensions(): Promise<PythonExtension[]> {
  return (await request<{ items: PythonExtension[] }>('/api/v1/python-extensions')).items
}

export function savePythonExtension(extension: PythonExtension): Promise<PythonExtension> {
  return request(`/api/v1/python-extensions/${encodeURIComponent(extension.key)}`, {
    method: 'PUT',
    body: JSON.stringify(extension),
  })
}

export function validatePythonExtension(extension: PythonExtension): Promise<{
  valid: boolean
  errors: string[]
}> {
  return request('/api/v1/python-extensions/validate', {
    method: 'POST',
    body: JSON.stringify(extension),
  })
}

export function runPythonExtension(
  key: string,
  inputData: Record<string, unknown>,
): Promise<PythonExtensionRun> {
  return request(`/api/v1/python-extensions/${encodeURIComponent(key)}/runs`, {
    method: 'POST',
    body: JSON.stringify({ input_data: inputData }),
  })
}

export async function fetchPythonExtensionRuns(key?: string): Promise<PythonExtensionRun[]> {
  const query = key ? `?extension_key=${encodeURIComponent(key)}` : ''
  return (await request<{ items: PythonExtensionRun[] }>(`/api/v1/python-extension-runs${query}`)).items
}

export async function fetchRuntimeControlPlane(): Promise<RuntimeControlPlane> {
  const [mappings, receipts, capabilities, requirements, identities, actions, goldenCases] = await Promise.all([
    request<{ items: RuntimeControlPlane['mappings'] }>('/api/v1/runtime/mappings'),
    request<{ items: RuntimeControlPlane['receipts'] }>('/api/v1/runtime/receipts?limit=30'),
    request<{ items: RuntimeControlPlane['capabilities'] }>('/api/v1/runtime/capabilities'),
    request<{ items: RuntimeControlPlane['requirements'] }>('/api/v1/runtime/requirements'),
    request<{ items: RuntimeControlPlane['identities'] }>('/api/v1/runtime/object-identities'),
    request<{ items: RuntimeControlPlane['actions'] }>('/api/v1/runtime/actions?limit=20'),
    request<{ items: RuntimeControlPlane['goldenCases'] }>('/api/v1/runtime/golden-cases'),
  ])
  return {
    mappings: mappings.items,
    receipts: receipts.items,
    capabilities: capabilities.items,
    requirements: requirements.items,
    identities: identities.items,
    actions: actions.items,
    goldenCases: goldenCases.items,
  }
}

export function runRuntimeEvaluation(): Promise<RuntimeEvaluation> {
  return request('/api/v1/runtime/evaluations', { method: 'POST' })
}
