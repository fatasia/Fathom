<script setup lang="ts">
import {
  Activity,
  ArrowRight,
  Blocks,
  BookOpen,
  Boxes,
  Braces,
  Cable,
  Check,
  ChevronRight,
  CircleDot,
  Cpu,
  Database,
  Download,
  FileCode2,
  GitBranch,
  HardDrive,
  LayoutGrid,
  KeyRound,
  Link2,
  Menu,
  Network,
  Play,
  Plus,
  Search,
  Send,
  Save,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  UploadCloud,
  Trash2,
  Waves,
  Wrench,
  Workflow,
  X,
  Zap,
} from '@lucide/vue'
import { computed, onMounted, ref } from 'vue'
import {
  askData,
  createBackup,
  deleteSqlTemplate,
  fetchBackups,
  fetchAgentMesh,
  fetchConnectorTypes,
  fetchDataSources,
  fetchDifyIntegrationStatus,
  fetchLatestEvaluation,
  fetchKnowledgeBases,
  fetchKnowledgeDocuments,
  fetchModelGateway,
  fetchObjectInstances,
  fetchPipelines,
  fetchPythonExtensions,
  fetchPythonExtensionRuns,
  fetchSemanticOverview,
  fetchSemanticChanges,
  fetchSqlTemplates,
  fetchSqlTemplateVersions,
  previewImport,
  previewSqlTemplate,
  importSemantics,
  inspectImage,
  previewPipeline,
  proposeSemanticAsset,
  saveDataSource,
  saveKnowledgeBase,
  saveModelProvider,
  saveModelRoute,
  savePipeline,
  savePythonExtension,
  saveSqlTemplate,
  runAgentFlow,
  runPythonExtension,
  runCertifiedEvaluation,
  decideSemanticChange,
  testDataSource,
  testKnowledgeBase,
  uploadKnowledgeDocument,
  deleteKnowledgeDocument,
  searchKnowledge,
  restoreBackup,
  probeModelProvider,
  validateSqlTemplate,
  validatePythonExtension,
} from './api'
import type {
  AskResult,
  AgentMeshOverview,
  AgentRun,
  AssetKind,
  BackupItem,
  ConnectorType,
  DataSource,
  DifyIntegrationStatus,
  EffectiveConfiguration,
  EvaluationReport,
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
  SemanticOverview,
  SemanticChange,
  SqlTemplate,
  SqlTemplateVersion,
  SqlPreview,
  StoredPipeline,
} from './types'

type Workspace = 'ask' | 'ontology' | 'knowledge' | 'metrics' | 'agents' | 'connections' | 'studio' | 'governance' | 'settings'

const workspace = ref<Workspace>('ask')
const question = ref('')
const isLoading = ref(false)
const error = ref('')
const result = ref<AskResult | null>(null)
const overview = ref<SemanticOverview | null>(null)
const agentMesh = ref<AgentMeshOverview | null>(null)
const selectedAgentFlow = ref('trusted_qa')
const latestAgentRun = ref<AgentRun | null>(null)
const agentRunMessage = ref('')
const agentRunLoading = ref(false)
const evidenceOpen = ref(false)
const executionOpen = ref(false)
const showAdvancedNav = ref(false)
const selectedKind = ref<AssetKind | 'all'>('all')
const semanticQuery = ref('')
const mobileNavOpen = ref(false)
const sqlTemplates = ref<SqlTemplate[]>([])
const backups = ref<BackupItem[]>([])
const connectorTypes = ref<ConnectorType[]>([])
const dataSources = ref<DataSource[]>([])
const knowledgeBases = ref<KnowledgeBase[]>([])
const knowledgeDocuments = ref<KnowledgeDocument[]>([])
const selectedKnowledgeBase = ref<KnowledgeBase | null>(null)
const knowledgeConfigurationText = ref('{}')
const knowledgeMessage = ref('')
const knowledgeSearchQuery = ref('')
const knowledgeHits = ref<KnowledgeHit[]>([])
const knowledgeBusy = ref(false)
const difyIntegration = ref<DifyIntegrationStatus | null>(null)
const integrationMessage = ref('')
const modelProviders = ref<ModelProvider[]>([])
const modelPresets = ref<ModelProviderPreset[]>([])
const modelRoutes = ref<ModelRoute[]>([])
const effectiveConfiguration = ref<EffectiveConfiguration | null>(null)
const evaluationReport = ref<EvaluationReport | null>(null)
const governanceMessage = ref('')
const semanticChanges = ref<SemanticChange[]>([])
const selectedChangeId = ref('')
const governanceBusy = ref('')
const metricPanelOpen = ref(false)
const metricMessage = ref('')
const draftMetric = ref({
  key: 'first_pass_yield',
  kind: 'metric' as const,
  label: '一次合格率',
  description: '首次检验合格数量占投入数量的比例',
  domain: 'manufacturing.quality',
  owner: 'quality-management',
  aliases: ['FPY'],
  unit: '%',
  dimensions: ['production_line', 'day'],
  expression: 'first_pass_good / input_count * 100',
})
const modelPanelOpen = ref(false)
const modelMessage = ref('')
const conversationHistory = ref<Array<{ question: string; answer: string; traceId: string }>>([])
const objectInstances = ref<ObjectInstance[]>([])
const visionAnalysis = ref<{
  analysis: string
  object_id: string
  model: string
  note: string
} | null>(null)
const visionLoading = ref(false)
const selectedTemplate = ref<SqlTemplate | null>(null)
const sqlTemplateVersions = ref<SqlTemplateVersion[]>([])
const sqlParametersText = ref('{}')
const sqlPreview = ref<SqlPreview | null>(null)
const activeStudioTool = ref<'sql' | 'pipeline' | 'python' | 'transfer'>('sql')
const importResult = ref<Record<string, unknown> | null>(null)
const importedSemanticContent = ref('')
const toolMessage = ref('')
const pipelinePanelOpen = ref(false)
const pipelineRunning = ref(false)
const pipelineResult = ref<PipelinePreview | null>(null)
const storedPipelines = ref<StoredPipeline[]>([])
const pipelineKey = ref('pipeline.new_flow')
const pipelineLabel = ref('新数据管道')
const pipelineSource = ref('')
const pipelineStepsText = ref(`[
  { "operation": "quality_check", "configuration": { "column": "id", "rule": "not_null" } },
  { "operation": "onn_map", "configuration": { "object": "business_object", "identity": "id" } }
]`)
const pythonExtensions = ref<PythonExtension[]>([])
const pythonRuns = ref<PythonExtensionRun[]>([])
const selectedPythonExtension = ref<PythonExtension>({
  key: 'extension.normalize',
  label: '数据归一化',
  version: 1,
  code: `def transform(input_data):
    value = float(input_data.get("value", 0))
    return {"normalized": round(value / 100, 4)}`,
  timeout_seconds: 10,
  memory_mb: 256,
  published: false,
  updated_at: '',
})
const pythonInputText = ref('{"value": 82.5}')
const pythonRun = ref<PythonExtensionRun | null>(null)
const pythonRunning = ref(false)
const connectionPanelOpen = ref(false)
const showAllConnectors = ref(false)
const builderOpen = ref(false)
const builderStep = ref(1)
const builderQuestions = ref('为什么一号线订单达成率下降？\n哪些设备停机影响最大？\n昨日 OEE 是否异常？')
const builderSource = ref('')
const builderRun = ref<AgentRun | null>(null)
const builderLoading = ref(false)
const builderMessage = ref('')
const draftConfigurationText = ref('{\n  "endpoint": "ws://127.0.0.1:6041",\n  "database": "manufacturing"\n}')
const draftSource = ref<DataSource>({
  key: 'plant_source',
  name: '工厂数据源',
  connector_type: 'tdengine',
  configuration: { endpoint: 'ws://127.0.0.1:6041', database: 'manufacturing' },
  secret_reference: 'env://FATHOM_SOURCE_PASSWORD',
  enabled: true,
  status: 'untested',
})
const draftModelProvider = ref<ModelProvider>({
  key: 'primary_reasoner',
  name: '主推理模型',
  provider_type: 'openai_compatible',
  base_url: 'http://127.0.0.1:8001/v1',
  api_mode: 'auto',
  default_model: 'model-name',
  secret_reference: '',
  api_key: '',
  capabilities: [],
  parameters: { temperature: 0.1, top_p: 0.9, max_output_tokens: 2048, timeout_seconds: 60 },
  enabled: true,
  status: 'untested',
})

const kindMeta: Record<AssetKind, { label: string; short: string }> = {
  object: { label: '对象', short: 'O' },
  relation: { label: '关系', short: 'R' },
  attribute: { label: '属性', short: 'A' },
  metric: { label: '指标', short: 'M' },
  event: { label: '事件', short: 'E' },
  policy: { label: '权限', short: 'P' },
}

const primaryNavItems: Array<{ key: Workspace; label: string; icon: typeof Sparkles }> = [
  { key: 'ask', label: '问数', icon: Sparkles },
  { key: 'ontology', label: '业务知识', icon: Network },
  { key: 'knowledge', label: '知识库', icon: BookOpen },
  { key: 'connections', label: '数据接入', icon: Cable },
]

const advancedNavItems: Array<{ key: Workspace; label: string; icon: typeof Sparkles }> = [
  { key: 'metrics', label: '指标中心', icon: Activity },
  { key: 'agents', label: '智能体网络', icon: Workflow },
  { key: 'studio', label: '工程工具', icon: Wrench },
  { key: 'governance', label: '学习与治理', icon: ShieldCheck },
]

const navItems = [...primaryNavItems, ...advancedNavItems]

const filteredAssets = computed(() => {
  const assets = overview.value?.assets ?? []
  const query = semanticQuery.value.trim().toLowerCase()
  return assets.filter((asset) => {
    const matchesKind = selectedKind.value === 'all' || asset.kind === selectedKind.value
    const haystack = [asset.label, asset.key, asset.description, ...asset.aliases].join(' ').toLowerCase()
    return matchesKind && (!query || haystack.includes(query))
  })
})

const currentMetricLabel = computed(
  () => result.value?.plan.anchors.find((anchor) => anchor.kind === 'metric')?.label ?? '订单达成率',
)
const currentObjectLabel = computed(
  () => result.value?.plan.anchors.find((anchor) => anchor.kind === 'object')?.label ?? '业务对象',
)

const modelStatusLabels: Record<string, string> = {
  untested: '待探测',
  ready: '可调用',
  models_only: '仅模型目录',
  unreachable: '未连通',
}

const agentLayerLabels: Record<string, string> = {
  control: '调度', cognition: '认知', reasoning: '推理', execution: '执行', governance: '治理',
}
const activeAgentFlow = computed(() => agentMesh.value?.flows.find((flow) => flow.key === selectedAgentFlow.value))
function findAgent(agentKey: string) {
  return agentMesh.value?.agents.find((agent) => agent.key === agentKey)
}

async function executeActiveFlow() {
  if (agentRunLoading.value) return
  agentRunLoading.value = true
  agentRunMessage.value = '正在执行受控智能体链路…'
  try {
    const payload: {
      flow_key: string
      question?: string
      source_key?: string
      scope?: Record<string, string>
    } = { flow_key: selectedAgentFlow.value }
    if (selectedAgentFlow.value === 'trusted_qa') payload.question = question.value
    if (selectedAgentFlow.value === 'adaptive_diagnosis') {
      payload.question = '为什么一号线昨天 OEE 异常？'
    }
    if (selectedAgentFlow.value === 'guided_onboarding') {
      const source = dataSources.value[0]
      if (!source) {
        agentRunMessage.value = '请先在“数据接入”中保存一个可发现 Schema 的数据源。'
        return
      }
      payload.source_key = source.key
    }
    latestAgentRun.value = await runAgentFlow(payload)
    agentRunMessage.value = `运行 ${latestAgentRun.value.run_id} · ${latestAgentRun.value.status}`
  } catch (runError) {
    agentRunMessage.value = runError instanceof Error ? runError.message : '智能体链路执行失败'
  } finally {
    agentRunLoading.value = false
  }
}

async function runPipelinePreview() {
  if (!pipelineSource.value) {
    toolMessage.value = '请先选择一个文件、SQLite 或 DuckDB 数据源。'
    return
  }
  pipelineRunning.value = true
  pipelineResult.value = null
  try {
    const parsed = JSON.parse(pipelineStepsText.value) as Array<{
      operation: string
      configuration: Record<string, unknown>
    }>
    pipelineResult.value = await previewPipeline({
      key: 'interactive.preview',
      label: '交互式管道预览',
      source: pipelineSource.value,
      target: 'preview',
      mode: 'preview',
      steps: parsed,
    })
    toolMessage.value = `管道已执行：${pipelineResult.value.row_count} 行，质量门禁 ${pipelineResult.value.status}`
  } catch (pipelineError) {
    toolMessage.value = pipelineError instanceof Error ? pipelineError.message : '管道执行失败'
  } finally {
    pipelineRunning.value = false
  }
}

async function loadOverview() {
  try {
    overview.value = await fetchSemanticOverview()
  } catch {
    error.value = '语义服务暂不可用，请确认 FATHOM 服务已启动。'
  }
}

async function loadAgentMesh() {
  agentMesh.value = await fetchAgentMesh()
}

async function loadPlatformData() {
  const [templates, backupItems, types, sources, objects, dify, pipelines, extensions] = await Promise.all([
    fetchSqlTemplates(),
    fetchBackups(),
    fetchConnectorTypes(),
    fetchDataSources(),
    fetchObjectInstances(),
    fetchDifyIntegrationStatus(),
    fetchPipelines(),
    fetchPythonExtensions(),
  ])
  sqlTemplates.value = templates
  backups.value = backupItems
  connectorTypes.value = types
  dataSources.value = sources
  objectInstances.value = objects
  difyIntegration.value = dify
  storedPipelines.value = pipelines
  pythonExtensions.value = extensions
  selectedTemplate.value ??= templates[0] ? { ...templates[0] } : null
  if (selectedTemplate.value) {
    sqlTemplateVersions.value = await fetchSqlTemplateVersions(selectedTemplate.value.key)
  }
  if (extensions.length && !extensions.some((item) => item.key === selectedPythonExtension.value.key)) {
    selectedPythonExtension.value = { ...extensions[0] }
  }
  pythonRuns.value = await fetchPythonExtensionRuns(selectedPythonExtension.value.key)
}

async function loadKnowledgeBases() {
  knowledgeBases.value = await fetchKnowledgeBases()
  if (!selectedKnowledgeBase.value && knowledgeBases.value.length) {
    await selectKnowledgeBase(knowledgeBases.value[0])
  } else if (selectedKnowledgeBase.value) {
    const refreshed = knowledgeBases.value.find(
      (item) => item.key === selectedKnowledgeBase.value?.key,
    )
    if (refreshed) await selectKnowledgeBase(refreshed)
  }
}

async function selectKnowledgeBase(item: KnowledgeBase) {
  selectedKnowledgeBase.value = {
    ...item,
    configuration: { ...item.configuration },
  }
  knowledgeConfigurationText.value = JSON.stringify(item.configuration, null, 2)
  knowledgeHits.value = []
  knowledgeDocuments.value = item.kind === 'internal'
    ? await fetchKnowledgeDocuments(item.key)
    : []
}

function createKnowledgeBase(kind: 'internal' | 'external') {
  const timestamp = Date.now()
  selectedKnowledgeBase.value = {
    key: `knowledge.${kind}_${timestamp}`,
    name: kind === 'internal' ? '新内置知识库' : '新外接知识库',
    kind,
    configuration: kind === 'external'
      ? { endpoint: 'https://knowledge.example.com/search', method: 'POST', items_path: 'items' }
      : {},
    secret_reference: '',
    enabled: true,
    document_count: 0,
    updated_at: '',
  }
  knowledgeConfigurationText.value = JSON.stringify(
    selectedKnowledgeBase.value.configuration,
    null,
    2,
  )
  knowledgeDocuments.value = []
  knowledgeMessage.value = '填写名称和配置后保存。密钥请使用 env://VARIABLE。'
}

async function persistKnowledgeBase() {
  if (!selectedKnowledgeBase.value) return
  knowledgeBusy.value = true
  try {
    selectedKnowledgeBase.value.configuration = JSON.parse(
      knowledgeConfigurationText.value || '{}',
    ) as Record<string, unknown>
    const saved = await saveKnowledgeBase(selectedKnowledgeBase.value)
    knowledgeMessage.value = `“${saved.name}”已保存`
    await loadKnowledgeBases()
  } catch (saveError) {
    knowledgeMessage.value = saveError instanceof Error ? saveError.message : '知识库保存失败'
  } finally {
    knowledgeBusy.value = false
  }
}

async function verifyKnowledgeBase() {
  if (!selectedKnowledgeBase.value) return
  knowledgeBusy.value = true
  try {
    const result = await testKnowledgeBase(selectedKnowledgeBase.value.key)
    knowledgeMessage.value = result.message
  } catch (testError) {
    knowledgeMessage.value = testError instanceof Error ? testError.message : '知识库测试失败'
  } finally {
    knowledgeBusy.value = false
  }
}

async function handleKnowledgeUpload(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file || !selectedKnowledgeBase.value) return
  knowledgeBusy.value = true
  try {
    await uploadKnowledgeDocument(selectedKnowledgeBase.value.key, file)
    knowledgeDocuments.value = await fetchKnowledgeDocuments(selectedKnowledgeBase.value.key)
    knowledgeMessage.value = `${file.name} 已切分入库，可立即在问数页检索`
    await loadKnowledgeBases()
  } catch (uploadError) {
    knowledgeMessage.value = uploadError instanceof Error ? uploadError.message : '文档导入失败'
  } finally {
    input.value = ''
    knowledgeBusy.value = false
  }
}

async function removeKnowledgeDocument(document: KnowledgeDocument) {
  if (!selectedKnowledgeBase.value) return
  await deleteKnowledgeDocument(selectedKnowledgeBase.value.key, document.document_id)
  knowledgeDocuments.value = knowledgeDocuments.value.filter(
    (item) => item.document_id !== document.document_id,
  )
  knowledgeMessage.value = `已删除“${document.title}”`
  await loadKnowledgeBases()
}

async function runKnowledgeSearch() {
  if (!knowledgeSearchQuery.value.trim()) return
  knowledgeBusy.value = true
  try {
    const result = await searchKnowledge(knowledgeSearchQuery.value)
    knowledgeHits.value = result.items
    knowledgeMessage.value = result.warnings.length
      ? `检索完成；${result.warnings.join('；')}`
      : `检索完成，返回 ${result.items.length} 条可引用结果`
  } catch (searchError) {
    knowledgeMessage.value = searchError instanceof Error ? searchError.message : '检索失败'
  } finally {
    knowledgeBusy.value = false
  }
}

async function loadModelGateway() {
  const gateway = await fetchModelGateway()
  modelProviders.value = gateway.providers
  modelPresets.value = gateway.presets
  modelRoutes.value = gateway.routes
  effectiveConfiguration.value = gateway.configuration
}

async function loadEvaluation() {
  const [report, changes] = await Promise.all([
    fetchLatestEvaluation(),
    fetchSemanticChanges(),
  ])
  evaluationReport.value = report
  semanticChanges.value = changes
}

const pendingChangeCount = computed(
  () => semanticChanges.value.filter((item) => ['candidate', 'in_review', 'approved'].includes(item.status)).length,
)

const changeStatusLabels: Record<SemanticChange['status'], string> = {
  candidate: '待发布',
  in_review: '评审中',
  approved: '已批准',
  rejected: '已驳回',
  published: '已发布',
  rolled_back: '已回滚',
}
const evaluationGateLabels: Record<string, string> = {
  semantic_plan: '语义规划',
  deterministic_execution: '确定性执行',
  evidence_completeness: '证据完整',
  safe_blocking: '安全阻断',
}

const builderScaffold = computed(() => {
  const output = builderRun.value?.output as {
    scaffold?: { objects?: unknown[]; attributes?: unknown[]; relations?: unknown[] }
  } | undefined
  return output?.scaffold ?? {}
})

async function generateDomainCandidate() {
  if (!builderSource.value) {
    builderMessage.value = '请先选择一个已配置、可发现 Schema 的数据源。'
    return
  }
  builderLoading.value = true
  builderMessage.value = '正在发现 Schema、生成 ONN 候选并执行冲突前检…'
  try {
    builderRun.value = await runAgentFlow({
      flow_key: 'guided_onboarding',
      source_key: builderSource.value,
    })
    builderStep.value = 4
    builderMessage.value = '候选已生成，未写入生产语义。'
  } catch (builderError) {
    builderMessage.value = builderError instanceof Error ? builderError.message : '候选生成失败'
  } finally {
    builderLoading.value = false
  }
}

function enterGovernance() {
  builderOpen.value = false
  builderStep.value = 1
  workspace.value = 'governance'
  void loadEvaluation()
}

async function governChange(
  change: SemanticChange,
  action: 'start_review' | 'approve' | 'reject' | 'publish' | 'rollback',
) {
  governanceBusy.value = change.change_id
  governanceMessage.value = `正在执行：${change.title}`
  try {
    const updated = await decideSemanticChange(change.change_id, action, '页面人工决策')
    semanticChanges.value = semanticChanges.value.map((item) =>
      item.change_id === updated.change_id ? updated : item,
    )
    governanceMessage.value = `${updated.title} · ${changeStatusLabels[updated.status]}`
    await loadOverview()
  } catch (decisionError) {
    governanceMessage.value = decisionError instanceof Error ? decisionError.message : '治理操作失败'
  } finally {
    governanceBusy.value = ''
  }
}

async function publishChange(change: SemanticChange) {
  if (governanceBusy.value) return
  governanceBusy.value = change.change_id
  governanceMessage.value = `正在自动评测并发布：${change.title}`
  try {
    evaluationReport.value = await runCertifiedEvaluation()
    if (!evaluationReport.value.passed) {
      governanceMessage.value = `发布已停止：${evaluationReport.value.failures.length} 个认证问题未通过`
      return
    }
    const updated = await decideSemanticChange(change.change_id, 'publish', '自动评测通过后直接发布')
    semanticChanges.value = semanticChanges.value.map((item) =>
      item.change_id === updated.change_id ? updated : item,
    )
    governanceMessage.value = `${updated.title} · 已发布，可随时回滚`
    await loadOverview()
  } catch (publishError) {
    governanceMessage.value = publishError instanceof Error ? publishError.message : '发布失败'
  } finally {
    governanceBusy.value = ''
  }
}

async function submitQuestion(nextQuestion?: string) {
  const content = nextQuestion ?? question.value
  if (!content.trim() || isLoading.value) return
  question.value = content
  isLoading.value = true
  error.value = ''
  result.value = null
  evidenceOpen.value = false
  executionOpen.value = false
  try {
    result.value = await askData(content)
    conversationHistory.value.push({
      question: content,
      answer: result.value.answer,
      traceId: result.value.trace_id,
    })
  } catch (requestError) {
    error.value = requestError instanceof Error ? requestError.message : '分析失败，请稍后重试。'
  } finally {
    isLoading.value = false
  }
}

async function handleVisionUpload(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  visionLoading.value = true
  visionAnalysis.value = null
  error.value = ''
  try {
    const plannedObjectId = result.value?.plan.anchors.find(
      (anchor) => anchor.kind === 'object',
    )?.key
    const objectId = plannedObjectId || (objectInstances.value.length === 1
      ? objectInstances.value[0].object_id
      : '')
    if (!objectId) {
      throw new Error('请先问一句包含设备或产线的问题，系统识别对象后即可附图分析。')
    }
    visionAnalysis.value = await inspectImage(
      file,
      objectId,
      `${question.value}\n请将可见信息与业务对象关联，并区分事实、推断和不确定项。`,
    )
  } catch (visionError) {
    error.value = visionError instanceof Error ? visionError.message : '图像理解失败'
  } finally {
    visionLoading.value = false
    input.value = ''
  }
}

function submitOnEnter(event: KeyboardEvent) {
  if (event.shiftKey) return
  event.preventDefault()
  void submitQuestion()
}

function openDifyTools() {
  window.open(difyIntegration.value?.console_url || 'http://127.0.0.1/tools', '_blank', 'noopener')
}

async function copyIntegrationConfig(content: string, successMessage: string) {
  try {
    await navigator.clipboard.writeText(content)
    integrationMessage.value = successMessage
  } catch {
    integrationMessage.value = '浏览器未允许复制，请使用下方下载配置。'
  }
}

async function connectDify() {
  openDifyTools()
  const schemaUrl = difyIntegration.value?.schema_url || '/api/v1/integrations/dify/openapi.yaml'
  try {
    const response = await fetch(schemaUrl)
    if (!response.ok) throw new Error('配置读取失败')
    await copyIntegrationConfig(
      await response.text(),
      'Dify 配置已复制并打开工具页；新建自定义工具后粘贴并保存即可。',
    )
  } catch (connectError) {
    integrationMessage.value = connectError instanceof Error ? connectError.message : 'Dify 接入准备失败'
  }
}

async function copyOpenApiConfig() {
  const schemaUrl = new URL(
    difyIntegration.value?.schema_url || '/api/v1/integrations/dify/openapi.yaml',
    window.location.origin,
  ).toString()
  await copyIntegrationConfig(schemaUrl, 'OpenAPI 地址已复制，可粘贴到任意支持 OpenAPI 的工作流或工具平台。')
}

async function copyAgentConfig() {
  const origin = window.location.origin
  const config = JSON.stringify(
    {
      mcpServers: {
        fathom: { type: 'streamable-http', url: `${origin}/mcp` },
      },
      a2aAgentCard: `${origin}/.well-known/agent-card.json`,
    },
    null,
    2,
  )
  await copyIntegrationConfig(config, 'MCP 与 A2A 配置已复制，可粘贴到 Agent 软件的连接设置。')
}

function switchWorkspace(next: Workspace) {
  workspace.value = next
  mobileNavOpen.value = false
  if (next === 'studio' || next === 'connections') void loadPlatformData()
  if (next === 'knowledge') void loadKnowledgeBases()
  if (next === 'agents') void loadAgentMesh()
  if (next === 'settings') void loadModelGateway()
  if (next === 'governance') void loadEvaluation()
}

function resetConversation() {
  conversationHistory.value = []
  result.value = null
  question.value = ''
  evidenceOpen.value = false
  executionOpen.value = false
}

function applyModelPreset() {
  const preset = modelPresets.value.find((item) => item.key === draftModelProvider.value.provider_type)
  if (!preset) return
  draftModelProvider.value.base_url = preset.default_url
  draftModelProvider.value.capabilities = [...preset.capabilities]
}

function editModelProvider(provider: ModelProvider) {
  draftModelProvider.value = {
    ...provider,
    api_key: '',
    parameters: { ...provider.parameters },
  }
  modelPanelOpen.value = true
}

async function persistModelProvider() {
  modelMessage.value = '正在保存模型服务…'
  const saved = await saveModelProvider(draftModelProvider.value)
  modelProviders.value = [...modelProviders.value.filter((item) => item.key !== saved.key), saved]
  draftModelProvider.value.api_key = ''
  modelPanelOpen.value = false
  modelMessage.value = `模型服务“${saved.name}”已保存；密钥未进入配置数据库。`
  await loadModelGateway()
}

async function verifyModelProvider(provider: ModelProvider) {
  modelMessage.value = `正在探测 ${provider.name} 的协议与模型列表…`
  const probe = await probeModelProvider(provider.key)
  modelMessage.value = `${provider.name}：${probe.message}；协议 ${probe.detected_mode}`
  await loadModelGateway()
}

async function persistModelRoute(route: ModelRoute) {
  if (!route.provider_key) return
  await saveModelRoute(route)
  modelMessage.value = `${route.label} 已绑定；生产启用前仍需通过黄金问题评测。`
  await loadModelGateway()
}

async function runBackup() {
  toolMessage.value = '正在创建一致性快照…'
  const item = await createBackup()
  backups.value.unshift(item)
  toolMessage.value = `备份已创建：${item.name}`
}

async function recoverBackup(item: BackupItem) {
  if (!window.confirm(`确认恢复 ${item.name}？系统会先自动创建保护性备份。`)) return
  toolMessage.value = `正在恢复 ${item.name}…`
  try {
    const result = await restoreBackup(item.name)
    toolMessage.value = `恢复完成；保护性备份：${result.protective_backup}`
    await loadPlatformData()
    await loadOverview()
  } catch (restoreError) {
    toolMessage.value = restoreError instanceof Error ? restoreError.message : '恢复失败'
  }
}

async function submitMetricCandidate() {
  metricMessage.value = '正在校验并创建候选…'
  try {
    const change = await proposeSemanticAsset(draftMetric.value)
    semanticChanges.value = [change, ...semanticChanges.value]
    metricPanelOpen.value = false
    metricMessage.value = `候选 ${change.change_id} 已创建；点击发布时系统会自动评测。`
  } catch (proposalError) {
    metricMessage.value = proposalError instanceof Error ? proposalError.message : '候选创建失败'
  }
}

function updateMetricDimensions(event: Event) {
  draftMetric.value.dimensions = (event.target as HTMLInputElement).value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
}

async function handleImport(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  toolMessage.value = `正在预检 ${file.name}…`
  importResult.value = await previewImport(file)
  importedSemanticContent.value = ['.yaml', '.yml'].some((suffix) => file.name.toLowerCase().endsWith(suffix))
    ? await file.text()
    : ''
  toolMessage.value = `${file.name} 预检通过，尚未写入生产语义。`
}

async function applySemanticImport() {
  if (!importedSemanticContent.value || importResult.value?.format !== 'fathom-semantic-yaml') return
  if (!window.confirm('确认应用该语义契约？系统将更新同名资产；建议先创建备份。')) return
  try {
    const result = await importSemantics(importedSemanticContent.value, true)
    toolMessage.value = `语义域 ${result.domain}@${result.version} 已应用，共 ${result.assets} 项资产。`
    await loadOverview()
  } catch (importError) {
    toolMessage.value = importError instanceof Error ? importError.message : '语义导入失败'
  }
}

async function checkTemplate() {
  if (!selectedTemplate.value) return
  const validation = await validateSqlTemplate(selectedTemplate.value)
  if (validation.safe && typeof validation.normalized_sql === 'string') {
    selectedTemplate.value.sql_text = validation.normalized_sql
  }
  toolMessage.value = validation.safe ? 'SQL 已格式化，安全校验通过。' : String(validation.errors)
}

async function persistTemplate() {
  if (!selectedTemplate.value) return
  selectedTemplate.value = await saveSqlTemplate(selectedTemplate.value)
  sqlTemplates.value = [
    ...sqlTemplates.value.filter((item) => item.key !== selectedTemplate.value?.key),
    selectedTemplate.value,
  ].sort((left, right) => left.key.localeCompare(right.key))
  sqlTemplateVersions.value = await fetchSqlTemplateVersions(selectedTemplate.value.key)
  toolMessage.value = 'SQL 模板已保存并记录版本时间。'
}

async function selectSqlTemplate(template: SqlTemplate) {
  selectedTemplate.value = { ...template }
  sqlPreview.value = null
  sqlTemplateVersions.value = await fetchSqlTemplateVersions(template.key)
}

function newSqlTemplate() {
  selectedTemplate.value = {
    key: `query.custom_${Date.now()}`,
    label: '新查询模板',
    description: '',
    dialect: 'sqlite',
    sql_text: 'SELECT object_id, label, object_type\nFROM object_instances\nLIMIT 100',
    parameters: [],
    published: false,
    updated_at: '',
  }
  sqlTemplateVersions.value = []
  sqlPreview.value = null
  sqlParametersText.value = '{}'
}

async function runSqlPreview() {
  if (!selectedTemplate.value) return
  try {
    const parameters = JSON.parse(sqlParametersText.value) as Record<string, unknown>
    sqlPreview.value = await previewSqlTemplate(selectedTemplate.value.key, parameters)
    toolMessage.value = `查询成功：返回 ${sqlPreview.value.row_count} 行。`
  } catch (previewError) {
    toolMessage.value = previewError instanceof Error ? previewError.message : 'SQL 预览失败'
  }
}

async function removeCurrentTemplate() {
  if (!selectedTemplate.value) return
  if (!window.confirm(`删除 SQL 模板“${selectedTemplate.value.label}”？`)) return
  await deleteSqlTemplate(selectedTemplate.value.key)
  sqlTemplates.value = sqlTemplates.value.filter((item) => item.key !== selectedTemplate.value?.key)
  selectedTemplate.value = sqlTemplates.value[0] ? { ...sqlTemplates.value[0] } : null
  sqlTemplateVersions.value = selectedTemplate.value
    ? await fetchSqlTemplateVersions(selectedTemplate.value.key)
    : []
  sqlPreview.value = null
  toolMessage.value = 'SQL 模板已删除。'
}

async function persistPipeline(published = false) {
  if (!pipelineSource.value) {
    toolMessage.value = '请先选择数据源。'
    return
  }
  try {
    const steps = JSON.parse(pipelineStepsText.value) as StoredPipeline['steps']
    const saved = await savePipeline({
      key: pipelineKey.value,
      label: pipelineLabel.value,
      source: pipelineSource.value,
      target: 'preview',
      mode: 'preview',
      steps,
      published,
      updated_at: '',
    })
    storedPipelines.value = [
      ...storedPipelines.value.filter((item) => item.key !== saved.key),
      saved,
    ]
    toolMessage.value = published ? '管道已发布。' : '管道草稿已保存。'
  } catch (pipelineError) {
    toolMessage.value = pipelineError instanceof Error ? pipelineError.message : '管道保存失败'
  }
}

function selectPipeline(pipeline: StoredPipeline) {
  pipelineKey.value = pipeline.key
  pipelineLabel.value = pipeline.label
  pipelineSource.value = pipeline.source
  pipelineStepsText.value = JSON.stringify(pipeline.steps, null, 2)
  pipelineResult.value = null
  pipelinePanelOpen.value = true
}

async function persistPythonExtension(published = false) {
  try {
    const validation = await validatePythonExtension(selectedPythonExtension.value)
    if (!validation.valid) {
      toolMessage.value = validation.errors.join('；')
      return
    }
    selectedPythonExtension.value.published = published
    const saved = await savePythonExtension(selectedPythonExtension.value)
    selectedPythonExtension.value = saved
    pythonExtensions.value = [
      ...pythonExtensions.value.filter((item) => item.key !== saved.key),
      saved,
    ]
    toolMessage.value = published ? 'Python 扩展已校验并发布。' : 'Python 扩展草稿已保存。'
  } catch (pythonError) {
    toolMessage.value = pythonError instanceof Error ? pythonError.message : 'Python 扩展保存失败'
  }
}

async function executePythonExtension() {
  pythonRunning.value = true
  pythonRun.value = null
  try {
    const inputData = JSON.parse(pythonInputText.value) as Record<string, unknown>
    pythonRun.value = await runPythonExtension(selectedPythonExtension.value.key, inputData)
    pythonRuns.value = await fetchPythonExtensionRuns(selectedPythonExtension.value.key)
    toolMessage.value = `运行完成：${pythonRun.value.run_id}`
  } catch (pythonError) {
    toolMessage.value = pythonError instanceof Error ? pythonError.message : 'Python 扩展运行失败'
  } finally {
    pythonRunning.value = false
  }
}

function selectPythonExtension(extension: PythonExtension) {
  selectedPythonExtension.value = { ...extension }
  pythonRun.value = null
  void fetchPythonExtensionRuns(extension.key).then((items) => { pythonRuns.value = items })
}

async function persistDataSource() {
  draftSource.value.configuration = JSON.parse(draftConfigurationText.value) as Record<string, unknown>
  const saved = await saveDataSource(draftSource.value)
  dataSources.value = [...dataSources.value.filter((item) => item.key !== saved.key), saved]
  connectionPanelOpen.value = false
  toolMessage.value = `数据源“${saved.name}”已保存，等待连接测试。`
}

async function verifyDataSource(source: DataSource) {
  const result = await testDataSource(source.key)
  toolMessage.value = `${source.name}：${result.message}`
  await loadPlatformData()
}

onMounted(async () => {
  await Promise.all([
    loadOverview(),
    loadAgentMesh(),
    loadPlatformData(),
    loadModelGateway(),
    loadEvaluation(),
  ])
})
</script>

<template>
  <div class="app-shell">
    <div class="depth-lines" aria-hidden="true"></div>

    <aside class="sidebar" :class="{ 'sidebar--open': mobileNavOpen }">
      <div class="brand">
        <div class="brand-mark"><Waves :size="24" /></div>
        <div>
          <strong>渊渟</strong>
          <span>FATHOM</span>
        </div>
      </div>

      <nav class="primary-nav" aria-label="主导航">
        <button
          v-for="item in primaryNavItems"
          :key="item.key"
          class="nav-item"
          :class="{ 'nav-item--active': workspace === item.key }"
          @click="switchWorkspace(item.key)"
        >
          <component :is="item.icon" :size="18" />
          <span>{{ item.label }}</span>
        </button>
        <button
          class="nav-item nav-advanced-toggle"
          :class="{ 'nav-item--active': advancedNavItems.some((item) => item.key === workspace) }"
          :aria-expanded="showAdvancedNav"
          @click="showAdvancedNav = !showAdvancedNav"
        >
          <SlidersHorizontal :size="18" />
          <span>高级管理</span>
          <ChevronRight class="nav-expand-icon" :class="{ open: showAdvancedNav }" :size="14" />
        </button>
        <div v-if="showAdvancedNav" class="advanced-nav">
          <button
            v-for="item in advancedNavItems"
            :key="item.key"
            class="nav-item nav-item--nested"
            :class="{ 'nav-item--active': workspace === item.key }"
            @click="switchWorkspace(item.key)"
          >
            <component :is="item.icon" :size="16" />
            <span>{{ item.label }}</span>
          </button>
        </div>
      </nav>

      <div class="sidebar-bottom">
        <div class="runtime-card">
          <span class="pulse-dot"></span>
          <div><strong>Lite 运行中</strong><span>SQLite · DuckDB</span></div>
        </div>
        <button class="nav-item" :class="{ 'nav-item--active': workspace === 'settings' }" @click="switchWorkspace('settings')"><Settings :size="18" /><span>系统设置</span></button>
      </div>
    </aside>

    <main class="main-area">
      <header class="topbar">
        <button class="mobile-menu" aria-label="打开导航" @click="mobileNavOpen = !mobileNavOpen">
          <Menu v-if="!mobileNavOpen" :size="20" />
          <X v-else :size="20" />
        </button>
        <div class="breadcrumb">
          <span>AI数字化流程中心</span><ChevronRight :size="14" />
          <strong>{{ workspace === 'settings' ? '系统设置' : navItems.find((item) => item.key === workspace)?.label }}</strong>
        </div>
        <div class="topbar-actions">
          <span class="scope-pill"><CircleDot :size="14" />生产执行域 · v0.1</span>
          <button class="avatar" aria-label="用户账户">R</button>
        </div>
      </header>

      <section v-if="workspace === 'ask'" class="workspace ask-workspace">
        <div class="ask-hero">
          <div><span class="eyebrow">可信问数</span><h1>问一句，直接看到数据</h1><p>用日常业务语言提问。对象、指标和权限由系统自动处理。</p></div>
          <button v-if="conversationHistory.length" class="quiet-action" @click="resetConversation"><X :size="15" />清空</button>
        </div>

        <div class="ask-layout">
          <div class="answer-stream">
            <form class="question-box question-box--simple" @submit.prevent="submitQuestion()">
              <div class="question-icon"><Sparkles :size="21" /></div>
              <textarea v-model="question" aria-label="输入要查询的业务问题" placeholder="例如：为什么一号线昨天订单达成率下降？" rows="2" @keydown.enter="submitOnEnter"></textarea>
              <div class="question-footer">
                <div class="question-options">
                  <span class="auto-understanding"><Sparkles :size="13" />自动理解指标、对象和时间</span>
                  <label class="vision-upload" title="上传现场图片辅助分析"><input type="file" accept="image/jpeg,image/png,image/webp" @change="handleVisionUpload" /><UploadCloud :size="14" />{{ visionLoading ? '识别中…' : '附图' }}</label>
                </div>
                <button class="send-button send-button--labeled" type="submit" :disabled="isLoading || !question.trim()">{{ isLoading ? '查询中' : '查询' }}<Send :size="16" /></button>
              </div>
            </form>

            <div v-if="!result && !isLoading && !error" class="quick-questions">
              <span>可以这样问</span>
              <button @click="submitQuestion('昨天的 OEE 是多少？')">昨天的 OEE 是多少？</button>
              <button @click="submitQuestion('哪些设备停机影响最大？')">哪些设备停机影响最大？</button>
              <button @click="submitQuestion('本月订单达成率有什么变化？')">本月订单达成率有什么变化？</button>
            </div>

            <article v-if="visionAnalysis" class="vision-result"><div><UploadCloud :size="17" /><strong>图片识别结果</strong><span>{{ visionAnalysis.object_id }}</span></div><p>{{ visionAnalysis.analysis }}</p><small>{{ visionAnalysis.note }}</small></article>
            <div v-if="isLoading" class="analysis-card loading-card"><div class="dive-loader"><span></span><span></span><span></span></div><div><strong>正在查询并校验</strong><p>识别业务对象、统一指标口径并核对权限</p></div></div>
            <div v-else-if="error" class="error-card">{{ error }}</div>

            <article v-else-if="result" class="analysis-card result-card">
              <div class="result-meta">
                <span v-if="result.status === 'completed'" class="verified-badge"><ShieldCheck :size="14" />结果已校验</span>
                <span v-else-if="result.status === 'no_data'" class="clarify-badge"><Database :size="13" />暂无真实数据</span>
                <span v-else class="clarify-badge"><CircleDot :size="13" />需要自然语言确认</span>
                <span>{{ result.semantic_version }}</span>
              </div>
              <h2>{{ result.answer }}</h2>

              <div v-if="result.data.current !== undefined" class="metric-stage">
                <div class="metric-primary"><span>{{ currentMetricLabel }}</span><strong>{{ result.data.current }}<small>{{ result.data.unit }}</small></strong><em :class="{ positive: (result.data.delta ?? 0) >= 0 }">{{ (result.data.delta ?? 0) >= 0 ? '+' : '' }}{{ result.data.delta }}{{ result.data.unit }} 较前日</em></div>
                <div class="comparison-visual"><div v-for="row in result.data.rows" :key="row.period" class="period-column"><span>{{ row.value }}{{ result.data.unit }}</span><div class="column-track"><i :style="{ height: `${Math.max(22, row.value)}%` }"></i></div><small>{{ row.period.slice(5) }}</small></div></div>
              </div>

              <div v-if="result.data.contributors?.length" class="contributors">
                <div class="section-label"><Zap :size="15" />主要影响</div>
                <div class="contributor-list"><div v-for="(item, index) in result.data.contributors" :key="item.object" class="contributor-row"><span class="rank">0{{ index + 1 }}</span><div><strong>{{ item.label }}</strong><small>{{ item.object }}</small></div><div class="impact-line"><i :style="{ width: `${Math.min(item.minutes * 1.8, 100)}%` }"></i></div><b>{{ item.minutes }} min</b></div></div>
              </div>

              <div class="result-actions">
                <button v-if="result.evidence.length" @click="evidenceOpen = !evidenceOpen"><BookOpen :size="14" />{{ evidenceOpen ? '收起证据' : `查看证据（${result.evidence.length}）` }}</button>
                <button @click="executionOpen = !executionOpen"><GitBranch :size="14" />{{ executionOpen ? '收起过程' : '查看计算过程' }}</button>
                <code>{{ result.trace_id }}</code>
              </div>

              <div v-if="executionOpen" class="plan-strip"><div v-for="stage in result.plan.abc" :key="stage.code"><b>{{ stage.code }}</b><span>{{ stage.name }} · {{ stage.summary }}</span></div></div>

              <aside v-if="evidenceOpen" class="evidence-panel evidence-panel--inline">
                <div class="panel-title"><div><BookOpen :size="17" /><strong>答案证据</strong></div><span>{{ result.evidence.length }} 项</span></div>
                <div class="semantic-path"><span>查询路径</span><div class="path-flow"><b>{{ currentObjectLabel }}</b><ChevronRight :size="13" /><b>{{ currentMetricLabel }}</b></div></div>
                <div class="evidence-list"><article v-for="item in result.evidence" :key="item.reference"><div class="evidence-type"><FileCode2 v-if="item.type === 'semantic_contract'" :size="15" /><Database v-else :size="15" />{{ item.type }}</div><strong>{{ item.title }}</strong><p>{{ item.detail }}</p><code>{{ item.reference }}</code></article></div>
                <div class="freshness"><span class="pulse-dot"></span><div><strong>数据更新时间</strong><span>{{ result.data_freshness }}</span></div></div>
              </aside>

              <div class="followups"><span>继续追问</span><button v-for="followup in result.suggested_followups" :key="followup" @click="submitQuestion(followup)">{{ followup }}<ArrowRight :size="14" /></button></div>
            </article>
          </div>
        </div>
      </section>

      <section v-else-if="workspace === 'ontology'" class="workspace ontology-workspace">
        <div class="workspace-heading">
          <div><span class="eyebrow">ONTOLOGY NEURAL NETWORK</span><h1>业务知识</h1><p>用业务语言管理对象、关系、指标、事件和权限，底层由 ONN 六元模型约束。</p></div>
          <button class="primary-action" @click="builderOpen = true"><Sparkles :size="16" />新建业务域</button>
        </div>
        <div class="ontology-layout">
          <div class="asset-browser">
            <div class="browser-toolbar">
              <div class="search-field"><Search :size="16" /><input v-model="semanticQuery" placeholder="搜索对象、指标、关系…" /></div>
              <div class="kind-tabs">
                <button :class="{ active: selectedKind === 'all' }" @click="selectedKind = 'all'">全部</button>
                <button v-for="(meta, kind) in kindMeta" :key="kind" :class="{ active: selectedKind === kind }" @click="selectedKind = kind">{{ meta.label }}</button>
              </div>
            </div>
            <div class="asset-table">
              <div class="asset-row asset-row--head"><span>语义资产</span><span>类型</span><span>Owner</span><span>状态</span></div>
              <div v-for="asset in filteredAssets" :key="asset.key" class="asset-row">
                <div class="asset-name"><i :data-kind="asset.kind">{{ kindMeta[asset.kind].short }}</i><div><strong>{{ asset.label }}</strong><small>{{ asset.key }}</small></div></div>
                <span>{{ kindMeta[asset.kind].label }}</span><span>{{ asset.owner }}</span><span class="certified"><Check :size="12" />已认证</span>
              </div>
            </div>
          </div>
          <aside class="network-card">
            <div class="panel-title"><div><Network :size="17" /><strong>对象关系网络</strong></div><span>局部一跳</span></div>
            <div class="network-canvas">
              <div class="network-orbit orbit-one"></div><div class="network-orbit orbit-two"></div>
              <div class="network-node node-center"><Boxes :size="20" /><span>生产线</span></div>
              <div class="network-node node-plant"><LayoutGrid :size="17" /><span>工厂</span></div>
              <div class="network-node node-equipment"><Blocks :size="17" /><span>设备</span></div>
              <div class="network-node node-order"><FileCode2 :size="17" /><span>工单</span></div>
              <div class="network-node node-metric"><Activity :size="17" /><span>指标</span></div>
            </div>
            <div class="network-legend"><span><i class="purple"></i>对象</span><span><i class="mint"></i>指标</span><span><i class="line"></i>有效关系</span></div>
          </aside>
        </div>
        <div v-if="builderOpen" class="builder-overlay">
          <section class="builder-dialog">
            <header><div><span class="eyebrow">GUIDED DOMAIN BUILDER</span><h2>用业务问题构建语义</h2><p>无需理解本体术语，FATHOM 会自动生成候选模型。</p></div><button @click="builderOpen = false"><X :size="18" /></button></header>
            <div class="builder-progress"><span v-for="step in 4" :key="step" :class="{ active: builderStep >= step }"><i>{{ step }}</i>{{ ['连接数据', '选择场景', '提交问题', '评测发布'][step - 1] }}</span></div>
            <div v-if="builderStep === 1" class="builder-body"><h3>数据已经在哪里？</h3><p>选择已配置的数据源。事实数据默认留在原处，只读取结构和必要样本。</p><label class="builder-source">数据源<select v-model="builderSource"><option value="">请选择</option><option v-for="source in dataSources" :key="source.key" :value="source.key">{{ source.name }} · {{ source.connector_type }} · {{ source.status }}</option></select></label><p v-if="!dataSources.length" class="builder-hint">还没有数据源，请先到“数据接入”保存并测试连接。</p></div>
            <div v-else-if="builderStep === 2" class="builder-body"><h3>从一个有限场景开始</h3><p>系统会加载制造业模板，只生成当前场景真正需要的对象和指标。</p><div class="scenario-grid"><button class="selected" @click="builderStep = 3"><Boxes :size="18" /><strong>生产执行与 OEE</strong><small>订单、产线、设备、班次、停机</small></button><button @click="builderStep = 3"><ShieldCheck :size="18" /><strong>质量追溯</strong><small>批次、检验、缺陷、工艺参数</small></button><button @click="builderStep = 3"><Wrench :size="18" /><strong>设备运维</strong><small>设备、报警、工单、备件</small></button></div></div>
            <div v-else-if="builderStep === 3" class="builder-body"><h3>业务人员经常问什么？</h3><p>每行一个问题。系统将反向识别需要的对象、关系、指标和权限。</p><textarea v-model="builderQuestions" rows="8"></textarea></div>
            <div v-else class="builder-body builder-result"><span class="builder-success"><Check :size="24" /></span><h3>ONN 候选已生成</h3><p>系统完成真实 Schema 发现与候选映射；补充指标口径后，点击发布即可自动评测并生效。</p><div class="builder-stats"><span><b>{{ builderScaffold.objects?.length ?? 0 }}</b>候选对象</span><span><b>{{ builderScaffold.attributes?.length ?? 0 }}</b>候选属性</span><span><b>{{ builderScaffold.relations?.length ?? 0 }}</b>候选关系</span></div><div class="builder-receipts"><span v-for="receipt in builderRun?.receipts ?? []" :key="receipt.sequence">{{ receipt.sequence }} · {{ receipt.summary }}</span></div></div>
            <p v-if="builderMessage" class="builder-message">{{ builderMessage }}</p><footer><button v-if="builderStep > 1 && builderStep < 4" @click="builderStep--">上一步</button><span></span><button v-if="builderStep === 1" class="primary-action" :disabled="!builderSource" @click="builderStep = 2">下一步</button><button v-else-if="builderStep === 3" class="primary-action" :disabled="builderLoading" @click="generateDomainCandidate"><Sparkles :size="14" />{{ builderLoading ? '生成中…' : '发现并生成候选' }}</button><button v-else-if="builderStep === 4" class="primary-action" @click="enterGovernance"><Check :size="14" />查看并发布</button></footer>
          </section>
        </div>
      </section>

      <section v-else-if="workspace === 'knowledge'" class="workspace knowledge-workspace">
        <div class="workspace-heading">
          <div><span class="eyebrow">GROUNDED KNOWLEDGE</span><h1>知识库</h1><p>内置文档直接轻量入库，也可连接企业现有知识平台；问数与智能体共享同一检索和引用入口。</p></div>
          <div class="knowledge-heading-actions"><button @click="createKnowledgeBase('external')"><Link2 :size="15" />连接外部</button><button class="primary-action" @click="createKnowledgeBase('internal')"><Plus :size="15" />新建内置库</button></div>
        </div>
        <div v-if="knowledgeMessage" class="settings-message"><CircleDot :size="14" />{{ knowledgeMessage }}</div>
        <div class="knowledge-layout">
          <aside class="knowledge-sidebar">
            <button v-for="item in knowledgeBases" :key="item.key" :class="{ active: selectedKnowledgeBase?.key === item.key }" @click="selectKnowledgeBase(item)">
              <span :data-kind="item.kind"><Database v-if="item.kind === 'internal'" :size="15" /><Link2 v-else :size="15" />{{ item.kind === 'internal' ? '内置' : '外接' }}</span>
              <strong>{{ item.name }}</strong><small>{{ item.kind === 'internal' ? `${item.document_count} 个文档` : String(item.configuration.endpoint || '未配置地址') }}</small>
            </button>
            <div v-if="!knowledgeBases.length" class="knowledge-empty"><BookOpen :size="24" /><strong>还没有知识库</strong><span>新建内置库或连接已有平台</span></div>
          </aside>

          <main v-if="selectedKnowledgeBase" class="knowledge-editor">
            <div class="knowledge-editor-head"><div><span>{{ selectedKnowledgeBase.kind === 'internal' ? '内置知识库' : '外接知识库' }}</span><h2>{{ selectedKnowledgeBase.name }}</h2></div><label class="toggle-label"><input v-model="selectedKnowledgeBase.enabled" type="checkbox" />参与检索</label></div>
            <div class="knowledge-form-grid"><label>名称<input v-model="selectedKnowledgeBase.name" /></label><label>唯一标识<input v-model="selectedKnowledgeBase.key" :disabled="Boolean(selectedKnowledgeBase.updated_at)" /></label></div>
            <template v-if="selectedKnowledgeBase.kind === 'external'">
              <label>连接配置 <small>支持通用 HTTP；请求体可用 <code v-pre>{{query}}</code> 与 <code v-pre>{{top_k}}</code></small><textarea v-model="knowledgeConfigurationText" rows="9" spellcheck="false"></textarea></label>
              <label>凭证引用<input v-model="selectedKnowledgeBase.secret_reference" placeholder="env://FATHOM_KNOWLEDGE_API_KEY" /><small>只保存环境变量名称，不保存密钥明文</small></label>
            </template>
            <template v-else>
              <div class="knowledge-upload"><UploadCloud :size="22" /><div><strong>导入知识文档</strong><span>TXT、Markdown、CSV、JSON、JSONL、YAML · UTF-8 · 单文件 5 MB</span></div><label><input type="file" accept=".txt,.md,.csv,.json,.jsonl,.yaml,.yml" :disabled="knowledgeBusy || !selectedKnowledgeBase.updated_at" @change="handleKnowledgeUpload" />选择文件</label></div>
              <div class="knowledge-documents"><div class="panel-title"><div><FileCode2 :size="16" /><strong>已入库文档</strong></div><span>{{ knowledgeDocuments.length }}</span></div><article v-for="document in knowledgeDocuments" :key="document.document_id"><div><strong>{{ document.title }}</strong><small>{{ document.source_uri }} · {{ Math.ceil(document.size / 1024) }} KB</small></div><button title="删除文档" @click="removeKnowledgeDocument(document)"><Trash2 :size="14" /></button></article><p v-if="!knowledgeDocuments.length">保存知识库后即可导入文档。</p></div>
            </template>
            <div class="knowledge-editor-actions"><button v-if="selectedKnowledgeBase.updated_at" :disabled="knowledgeBusy" @click="verifyKnowledgeBase"><Play :size="14" />测试</button><button class="primary-action" :disabled="knowledgeBusy" @click="persistKnowledgeBase"><Save :size="14" />{{ knowledgeBusy ? '处理中…' : '保存' }}</button></div>
          </main>
          <div v-else class="knowledge-welcome"><BookOpen :size="34" /><h2>企业知识统一入口</h2><p>内置库适合制度、手册、SOP；外接库保留现有知识平台和权限体系。</p></div>
        </div>

        <section class="knowledge-playground">
          <div><span class="eyebrow">RETRIEVAL TEST</span><h2>检索验证</h2><p>这里返回的来源和相关度，会原样提供给问数与上层智能体。</p></div>
          <form @submit.prevent="runKnowledgeSearch"><Search :size="17" /><input v-model="knowledgeSearchQuery" placeholder="输入一个业务问题，验证所有已启用知识库" /><button class="primary-action" :disabled="knowledgeBusy">检索</button></form>
          <div v-if="knowledgeHits.length" class="knowledge-hits"><article v-for="hit in knowledgeHits" :key="`${hit.knowledge_base_key}-${hit.document_id}-${hit.content}`"><header><strong>{{ hit.title }}</strong><span>{{ Math.round(hit.score * 100) }}%</span></header><p>{{ hit.content }}</p><footer><code>{{ hit.source_uri }}</code><span>{{ hit.retrieval }}</span></footer></article></div>
        </section>
      </section>

      <section v-else-if="workspace === 'metrics'" class="workspace catalog-workspace">
        <div class="workspace-heading"><div><span class="eyebrow">CERTIFIED METRICS</span><h1>指标中心</h1><p>统一公式、粒度、单位、Owner 与时间口径。</p></div><button class="primary-action" @click="metricPanelOpen = true"><Activity :size="16" />新建指标</button></div>
        <div v-if="metricMessage" class="settings-message"><Check :size="14" />{{ metricMessage }}</div>
        <div class="catalog-grid">
          <article v-for="asset in overview?.assets.filter((item) => item.kind === 'metric') ?? []" :key="asset.key" class="catalog-card">
            <div class="catalog-card-top"><span class="metric-symbol"><Activity :size="18" /></span><span class="certified"><Check :size="12" />已认证</span></div>
            <h3>{{ asset.label }}</h3><p>{{ asset.description }}</p><code>{{ asset.expression }}</code>
            <div class="catalog-meta"><span>{{ asset.unit }}</span><span>{{ asset.owner }}</span></div>
          </article>
        </div>
        <form v-if="metricPanelOpen" class="connection-form metric-form" @submit.prevent="submitMetricCandidate">
          <div class="form-heading"><div><span class="eyebrow">METRIC CANDIDATE</span><h3>新建指标候选</h3></div><button type="button" @click="metricPanelOpen = false"><X :size="17" /></button></div>
          <div class="form-row"><label>指标名称<input v-model="draftMetric.label" required /></label><label>唯一标识<input v-model="draftMetric.key" required /></label></div>
          <label>业务定义<textarea v-model="draftMetric.description" rows="3" required></textarea></label>
          <label>确定性表达式<textarea v-model="draftMetric.expression" rows="3" spellcheck="false" required></textarea></label>
          <div class="form-row"><label>业务域<input v-model="draftMetric.domain" required /></label><label>Owner<input v-model="draftMetric.owner" required /></label></div>
          <div class="form-row"><label>单位<input v-model="draftMetric.unit" /></label><label>维度（逗号分隔）<input :value="draftMetric.dimensions.join(', ')" @input="updateMetricDimensions" /></label></div>
          <button class="primary-action" type="submit"><ShieldCheck :size="15" />创建待发布候选</button>
        </form>
      </section>

      <section v-else-if="workspace === 'agents'" class="workspace agents-workspace">
        <div class="workspace-heading"><div><span class="eyebrow">ONTOLOGY-CONSTRAINED AGENT MESH</span><h1>智能体网络</h1><p>按任务动态组网，所有智能体共享 FathomPlan、ONN 对象空间、权限与证据契约。</p></div><div class="mesh-heading-actions"><span class="mesh-state"><span class="pulse-dot"></span>{{ agentMesh?.agents.length ?? 0 }} 个内置智能体</span><button class="primary-action" :disabled="agentRunLoading" @click="executeActiveFlow"><Zap :size="15" />{{ agentRunLoading ? '执行中…' : '运行当前链路' }}</button></div></div>
        <div v-if="agentRunMessage" class="settings-message"><CircleDot :size="14" />{{ agentRunMessage }}</div>
        <div class="mesh-principles"><span>最短可信链路</span><span>确定性计算</span><span>证据优先</span><span>自动评测发布</span></div>
        <section class="flow-card">
          <div class="flow-tabs"><button v-for="flow in agentMesh?.flows ?? []" :key="flow.key" :class="{ active: selectedAgentFlow === flow.key }" @click="selectedAgentFlow = flow.key"><strong>{{ flow.name }}</strong><small>{{ flow.trigger }} · {{ flow.sla }}</small></button></div>
          <div class="agent-flow">
            <template v-for="(agentKey, index) in activeAgentFlow?.agents ?? []" :key="`${agentKey}-${index}`">
              <article><span :data-layer="findAgent(agentKey)?.layer">{{ index + 1 }}</span><div><small>{{ agentLayerLabels[findAgent(agentKey)?.layer ?? ''] }}</small><strong>{{ findAgent(agentKey)?.name }}</strong></div></article>
              <ArrowRight v-if="index < (activeAgentFlow?.agents.length ?? 0) - 1" :size="15" />
            </template>
          </div>
        </section>
        <section v-if="latestAgentRun" class="run-receipts">
          <div class="panel-title"><div><ShieldCheck :size="17" /><strong>运行回执</strong></div><code>{{ latestAgentRun.trace_id || latestAgentRun.run_id }}</code></div>
          <div><article v-for="receipt in latestAgentRun.receipts" :key="`${receipt.sequence}-${receipt.agent}`"><span>{{ receipt.sequence }}</span><div><strong>{{ findAgent(receipt.agent)?.name || receipt.agent }}</strong><small>{{ receipt.summary }}</small></div><b :data-status="receipt.status">{{ receipt.status }}</b></article></div>
        </section>
        <div class="agent-catalog">
          <article v-for="agent in agentMesh?.agents ?? []" :key="agent.key" :data-layer="agent.layer">
            <div class="agent-card-top"><span>{{ agentLayerLabels[agent.layer] }}</span><b>{{ agent.status === 'core' ? '内置' : '按需' }}</b></div>
            <h3>{{ agent.name }}</h3><p>{{ agent.description }}</p>
            <div class="agent-tools"><code v-for="tool in agent.tools.slice(0, 3)" :key="tool">{{ tool }}</code></div>
            <footer><span>{{ agent.model_role ? `模型路由 · ${agent.model_role}` : '确定性执行 · 无需模型' }}</span><CircleDot :size="12" /></footer>
          </article>
        </div>
      </section>

      <section v-else-if="workspace === 'connections'" class="workspace catalog-workspace">
        <div class="workspace-heading"><div><span class="eyebrow">数据接入</span><h1>连接数据和上层应用</h1><p>先接入企业数据，再把经过授权的问数能力提供给其他应用。</p></div><button class="primary-action" @click="connectionPanelOpen = !connectionPanelOpen"><Link2 :size="16" />新建数据源</button></div>
        <div class="connection-section"><h2>上层应用</h2><div class="connection-grid">
          <button class="connection-card connection-card--featured" @click="connectDify"><div class="connection-logo">D</div><div><span :class="{ online: difyIntegration?.service_running }">{{ difyIntegration?.service_running ? '本机服务已发现' : '等待启动' }}</span><h3>Dify</h3><p>{{ difyIntegration?.setup_completed ? '一键复制配置并打开工具页' : '启动后即可接入' }}</p></div><ChevronRight :size="18" /></button>
          <button class="connection-card" @click="copyOpenApiConfig"><div class="connection-logo"><LayoutGrid :size="20" /></div><div><span>OpenAPI</span><h3>工作流 / 低代码平台</h3><p>一键复制标准工具地址</p></div><ChevronRight :size="18" /></button>
          <button class="connection-card" @click="copyAgentConfig"><div class="connection-logo"><Workflow :size="20" /></div><div><span>MCP · A2A</span><h3>Agent 软件</h3><p>一键复制 Agent 连接配置</p></div><ChevronRight :size="18" /></button>
        </div><div v-if="integrationMessage" class="settings-message integration-message"><Check :size="14" />{{ integrationMessage }}</div><div class="integration-actions"><a :href="difyIntegration?.schema_url || '/api/v1/integrations/dify/openapi.yaml'" download><Download :size="14" />下载工具配置</a><button @click="openDifyTools">打开 Dify 工具页<ArrowRight :size="14" /></button></div></div>
        <div class="connection-section">
          <div class="section-heading"><h2>企业事实源</h2><button class="quiet-action" @click="showAllConnectors = !showAllConnectors">{{ showAllConnectors ? '收起类型' : `查看全部 ${connectorTypes.length} 种` }}</button></div>
          <div class="connector-matrix">
            <article v-for="connector in (showAllConnectors ? connectorTypes : connectorTypes.slice(0, 6))" :key="connector.key">
              <span class="connector-state" :class="{ bundled: connector.driver_available }">{{ connector.bundled ? '内置' : connector.driver_available ? '驱动可用' : '按需' }}</span>
              <Database :size="18" /><strong>{{ connector.label }}</strong><small>{{ connector.category }}</small>
            </article>
          </div>
        </div>
        <div v-if="dataSources.length" class="connection-section">
          <h2>已配置数据源</h2>
          <div class="data-source-list">
            <article v-for="source in dataSources" :key="source.key">
              <span class="status-indicator" :data-status="source.status"></span>
              <div><strong>{{ source.name }}</strong><small>{{ source.connector_type }} · {{ source.key }}</small></div>
              <span>{{ source.status }}</span><button @click="verifyDataSource(source)">测试连接</button>
            </article>
          </div>
        </div>
        <form v-if="connectionPanelOpen" class="connection-form" @submit.prevent="persistDataSource">
          <div class="form-heading"><div><span class="eyebrow">DATA SOURCE</span><h3>配置数据源</h3></div><button type="button" @click="connectionPanelOpen = false"><X :size="17" /></button></div>
          <label>连接名称<input v-model="draftSource.name" /></label>
          <label>唯一标识<input v-model="draftSource.key" /></label>
          <label>连接器<select v-model="draftSource.connector_type"><option v-for="connector in connectorTypes" :key="connector.key" :value="connector.key">{{ connector.label }}</option></select></label>
          <label>凭证引用<input v-model="draftSource.secret_reference" placeholder="env://VARIABLE" /></label>
          <label>连接配置 JSON<textarea v-model="draftConfigurationText" rows="5" spellcheck="false"></textarea><small>保存的仅是非敏感连接参数，密码通过环境变量或 Secret Provider 引用。</small></label>
          <button class="primary-action" type="submit"><Save :size="15" />保存数据源</button>
        </form>
      </section>

      <section v-else-if="workspace === 'studio'" class="workspace studio-workspace">
        <div class="workspace-heading"><div><span class="eyebrow">ENGINEERING TOOLKIT</span><h1>工程工具</h1><p>写 SQL、编排数据、扩展逻辑；每一步都可预览、校验、发布和追溯。</p></div><span v-if="toolMessage" class="tool-message"><Check :size="14" />{{ toolMessage }}</span></div>
        <div class="studio-capabilities">
          <button :class="{ active: activeStudioTool === 'sql' }" @click="activeStudioTool = 'sql'"><Braces :size="18" /><div><strong>SQL 开发</strong><span>校验 · 预览 · 版本 · 发布</span></div></button>
          <button :class="{ active: activeStudioTool === 'pipeline' }" @click="activeStudioTool = 'pipeline'"><Workflow :size="18" /><div><strong>数据管道</strong><span>转换 · 质量 · ONN 映射</span></div></button>
          <button :class="{ active: activeStudioTool === 'python' }" @click="activeStudioTool = 'python'"><FileCode2 :size="18" /><div><strong>Python 扩展</strong><span>隔离运行 · 限时 · 日志</span></div></button>
          <button :class="{ active: activeStudioTool === 'transfer' }" @click="activeStudioTool = 'transfer'"><HardDrive :size="18" /><div><strong>迁移与恢复</strong><span>导入导出 · 备份 · 恢复</span></div></button>
        </div>

        <section v-if="activeStudioTool === 'pipeline'" class="pipeline-builder">
          <div class="panel-title"><div><Workflow :size="17" /><strong>数据管道</strong></div><span>DuckDB 内置执行 · 运行结果留痕</span></div>
          <div v-if="storedPipelines.length" class="saved-pipeline-list"><button v-for="pipeline in storedPipelines" :key="pipeline.key" @click="selectPipeline(pipeline)"><strong>{{ pipeline.label }}</strong><span>{{ pipeline.source }} · {{ pipeline.published ? '已发布' : '草稿' }}</span></button></div>
          <div class="pipeline-form">
            <div class="form-row"><label>管道标识<input v-model="pipelineKey" /></label><label>名称<input v-model="pipelineLabel" /></label></div>
            <label>事实源<select v-model="pipelineSource"><option value="">选择数据源</option><option v-for="source in dataSources.filter((item) => ['file', 'sqlite', 'duckdb'].includes(item.connector_type))" :key="source.key" :value="source.key">{{ source.name }} · {{ source.connector_type }}</option></select></label>
            <label>转换与质量步骤 JSON<textarea v-model="pipelineStepsText" rows="8" spellcheck="false"></textarea></label>
            <div class="pipeline-actions"><small>支持重命名、类型转换、过滤、派生、去重、质量检查和 ONN 映射。</small><div><button @click="persistPipeline(false)"><Save :size="14" />保存草稿</button><button class="primary-action" :disabled="pipelineRunning" @click="runPipelinePreview"><Play :size="15" />{{ pipelineRunning ? '执行中…' : '运行预览' }}</button><button @click="persistPipeline(true)"><ShieldCheck :size="14" />发布</button></div></div>
          </div>
          <div v-if="pipelineResult" class="pipeline-result">
            <div class="pipeline-result-summary"><strong>{{ pipelineResult.status === 'passed' ? '质量门禁通过' : '质量门禁失败' }}</strong><span>{{ pipelineResult.row_count }} 行 · {{ pipelineResult.columns.length }} 列 · {{ pipelineResult.limits.memory }} · {{ pipelineResult.run_id }}</span></div>
            <div class="pipeline-table-wrap"><table><thead><tr><th v-for="column in pipelineResult.columns" :key="column">{{ column }}</th></tr></thead><tbody><tr v-for="(row, rowIndex) in pipelineResult.rows.slice(0, 8)" :key="rowIndex"><td v-for="column in pipelineResult.columns" :key="column">{{ row[column] }}</td></tr></tbody></table></div>
          </div>
        </section>

        <section v-else-if="activeStudioTool === 'sql'" class="sql-studio">
            <div class="panel-title"><div><Braces :size="17" /><strong>SQL 开发</strong></div><div><span>只读安全门禁</span><button @click="newSqlTemplate"><Plus :size="14" />新建</button></div></div>
            <div class="sql-layout">
              <nav class="template-list">
                <button v-for="template in sqlTemplates" :key="template.key" :class="{ active: selectedTemplate?.key === template.key }" @click="selectSqlTemplate(template)">
                  <strong>{{ template.label }}</strong><small>{{ template.key }} · {{ template.published ? '已发布' : '草稿' }}</small>
                </button>
              </nav>
              <div v-if="selectedTemplate" class="template-editor">
                <div class="editor-meta"><input v-model="selectedTemplate.label" /><input v-model="selectedTemplate.key" :disabled="sqlTemplates.some((item) => item.key === selectedTemplate?.key)" /><select v-model="selectedTemplate.dialect"><option>sqlite</option><option>duckdb</option><option>postgres</option><option>mysql</option><option>tsql</option></select></div>
                <textarea v-model="selectedTemplate.sql_text" spellcheck="false" aria-label="SQL 模板"></textarea>
                <div class="sql-parameter-row"><label>参数 JSON<input v-model="sqlParametersText" placeholder='{"object_id":"line_01"}' /></label><span>版本 {{ sqlTemplateVersions[0]?.version ?? 0 }}</span></div>
                <div class="editor-footer"><span>声明参数：{{ selectedTemplate.parameters.join(' · ') || '无' }}</span><div><button @click="removeCurrentTemplate"><Trash2 :size="14" />删除</button><button @click="checkTemplate"><ShieldCheck :size="14" />格式化并校验</button><button @click="persistTemplate"><Save :size="14" />保存版本</button><button class="primary-action" @click="runSqlPreview"><Play :size="14" />运行预览</button></div></div>
                <div v-if="sqlPreview" class="pipeline-result sql-preview"><div class="pipeline-result-summary"><strong>查询结果</strong><span>{{ sqlPreview.row_count }} 行 · {{ sqlPreview.executed_at }}</span></div><div class="pipeline-table-wrap"><table><thead><tr><th v-for="column in sqlPreview.columns" :key="column">{{ column }}</th></tr></thead><tbody><tr v-for="(row, index) in sqlPreview.rows" :key="index"><td v-for="column in sqlPreview.columns" :key="column">{{ row[column] }}</td></tr></tbody></table></div></div>
              </div>
            </div>
        </section>

        <section v-else-if="activeStudioTool === 'python'" class="python-studio">
          <div class="panel-title"><div><FileCode2 :size="17" /><strong>Python 扩展</strong></div><span>受限纯函数 · 无网络 · 独立进程</span></div>
          <div class="python-layout">
            <nav class="template-list"><button v-for="extension in pythonExtensions" :key="extension.key" :class="{ active: extension.key === selectedPythonExtension.key }" @click="selectPythonExtension(extension)"><strong>{{ extension.label }}</strong><small>{{ extension.key }} · v{{ extension.version }} · {{ extension.published ? '已发布' : '草稿' }}</small></button><button class="new-item" @click="selectedPythonExtension = { ...selectedPythonExtension, key: `extension.custom_${Date.now()}`, label: '新 Python 扩展', version: 1, published: false, updated_at: '' }"><Plus :size="14" />新建扩展</button></nav>
            <div class="python-editor"><div class="editor-meta"><input v-model="selectedPythonExtension.label" /><input v-model="selectedPythonExtension.key" /><span>v{{ selectedPythonExtension.version }}</span></div><textarea v-model="selectedPythonExtension.code" rows="16" spellcheck="false"></textarea><div class="python-runtime"><label>测试输入 JSON<textarea v-model="pythonInputText" rows="4"></textarea></label><div><label>超时（秒）<input v-model.number="selectedPythonExtension.timeout_seconds" type="number" min="1" max="60" /></label><label>内存预算（MB）<input v-model.number="selectedPythonExtension.memory_mb" type="number" min="64" max="512" /></label></div></div><div class="editor-footer"><span>入口：transform(input_data) · 输出 ≤1 MB</span><div><button @click="persistPythonExtension(false)"><Save :size="14" />保存草稿</button><button @click="persistPythonExtension(true)"><ShieldCheck :size="14" />校验并发布</button><button class="primary-action" :disabled="pythonRunning || !selectedPythonExtension.published" @click="executePythonExtension"><Play :size="14" />{{ pythonRunning ? '运行中…' : '运行' }}</button></div></div><pre v-if="pythonRun" class="run-output">{{ JSON.stringify(pythonRun, null, 2) }}</pre><div v-if="pythonRuns.length" class="run-history"><strong>最近运行</strong><span v-for="run in pythonRuns.slice(0, 5)" :key="run.run_id">{{ run.started_at.slice(0, 16).replace('T', ' ') }} · {{ run.status }} · {{ run.run_id }}</span></div></div>
          </div>
        </section>

        <div v-else class="transfer-stack transfer-stack--wide">
            <section class="transfer-card">
              <div class="panel-title"><div><UploadCloud :size="17" /><strong>导入与导出</strong></div></div>
              <label class="drop-zone"><input type="file" accept=".csv,.json,.jsonl,.yaml,.yml" @change="handleImport" /><UploadCloud :size="22" /><strong>导入并预检</strong><span>CSV · JSON · JSONL · YAML</span></label>
              <div v-if="importResult" class="import-result"><Check :size="14" /><code>{{ JSON.stringify(importResult) }}</code><button v-if="importResult.format === 'fathom-semantic-yaml'" @click="applySemanticImport">应用</button></div>
              <a class="transfer-action" href="/api/v1/semantics/export"><Download :size="15" /><span><strong>导出语义资产</strong><small>YAML + manifest.zip</small></span></a>
              <div class="dataset-exports"><a href="/api/v1/exports/objects.csv">对象 CSV</a><a href="/api/v1/exports/metrics.csv">指标 CSV</a><a href="/api/v1/exports/events.csv">事件 CSV</a></div>
            </section>
            <section class="transfer-card">
              <div class="panel-title"><div><HardDrive :size="17" /><strong>备份与恢复</strong></div><button @click="runBackup">立即备份</button></div>
              <div class="backup-list">
                <div v-for="backup in backups.slice(0, 4)" :key="backup.name" class="backup-item"><a :href="`/api/v1/system/backups/${backup.name}`"><HardDrive :size="15" /><span><strong>{{ backup.name }}</strong><small>{{ Math.ceil(backup.size_bytes / 1024) }} KB · {{ backup.updated_at.slice(0, 16).replace('T', ' ') }}</small></span><Download :size="14" /></a><button @click="recoverBackup(backup)">恢复</button></div>
                <div v-if="!backups.length" class="empty-state">尚无备份，首次发布前建议创建快照。</div>
              </div>
            </section>
          </div>
      </section>

      <section v-else-if="workspace === 'governance'" class="workspace governance-workspace">
        <div class="workspace-heading"><div><span class="eyebrow">CONTROLLED EVOLUTION</span><h1>学习与治理</h1><p>候选生成后直接发布；系统自动完成质量评测并保留回滚点。</p></div></div>
        <div v-if="governanceMessage" class="settings-message"><Check :size="14" />{{ governanceMessage }}</div>
        <div class="governance-summary"><article><span>待发布建议</span><strong>{{ String(pendingChangeCount).padStart(2, '0') }}</strong><small>点击即可自动评测并发布</small></article><article><span>语义覆盖率</span><strong>87%</strong><small>生产执行域</small></article><article><span>最近评测</span><strong>{{ evaluationReport ? `${evaluationReport.accuracy_percent}%` : '待运行' }}</strong><small v-if="evaluationReport">基线 {{ evaluationReport.correct }} / {{ evaluationReport.total }} · 门槛 ≥99%</small><small v-else>发布时自动运行</small></article><article><span>失败样本</span><strong>{{ evaluationReport?.failures.length ?? '—' }}</strong><small>{{ evaluationReport?.passed ? '允许直接发布' : '失败时自动拦截' }}</small></article></div>
        <p v-if="evaluationReport" class="governance-scope-note">{{ evaluationReport.scope_note }} · {{ evaluationReport.semantic_version }}</p>
        <div v-if="evaluationReport?.gates" class="evaluation-gates"><span v-for="(gate, key) in evaluationReport.gates" :key="key" :data-passed="gate.passed"><Check :size="12" />{{ evaluationGateLabels[key] ?? key }} · {{ gate.total }} 项</span></div>
        <div class="suggestion-list">
          <article v-for="change in semanticChanges" :key="change.change_id" :class="{ expanded: selectedChangeId === change.change_id }">
            <span class="suggestion-icon"><GitBranch v-if="change.kind !== 'alias'" :size="18" /><BookOpen v-else :size="18" /></span>
            <div><span class="eyebrow">{{ change.kind.toUpperCase() }} · {{ changeStatusLabels[change.status] }}</span><h3>{{ change.title }}</h3><p>{{ change.description }}</p><div class="suggestion-meta"><span>置信度 {{ change.confidence_percent }}%</span><span>影响 {{ change.impact.assets ?? 0 }} 项资产</span><span>风险 {{ change.impact.risk ?? 'unknown' }}</span><span v-if="change.evaluation_run_id">评测 {{ change.evaluation_run_id }}</span></div></div>
            <div class="governance-actions"><button @click="selectedChangeId = selectedChangeId === change.change_id ? '' : change.change_id">{{ selectedChangeId === change.change_id ? '收起证据' : '查看证据' }}</button><button v-if="['candidate', 'in_review', 'approved'].includes(change.status)" class="primary-action" :disabled="governanceBusy === change.change_id" @click="publishChange(change)">{{ governanceBusy === change.change_id ? '评测中…' : '直接发布' }}</button><button v-else-if="change.rollback_available" @click="governChange(change, 'rollback')">回滚</button></div>
            <div v-if="selectedChangeId === change.change_id" class="change-evidence"><div><strong>证据</strong><code v-for="item in change.evidence" :key="item">{{ item }}</code></div><div><strong>变更补丁</strong><pre>{{ JSON.stringify(change.patch, null, 2) }}</pre></div><div><strong>决策记录</strong><span v-for="event in change.history" :key="event.at">{{ event.at.slice(0, 16).replace('T', ' ') }} · {{ event.actor }} · {{ event.action }}</span></div></div>
          </article>
        </div>
      </section>

      <section v-else class="workspace settings-workspace">
        <div class="workspace-heading">
          <div><span class="eyebrow">MODEL GATEWAY</span><h1>模型服务与系统配置</h1><p>统一适配 Responses、Chat、Messages、Embedding 与视觉能力；页面和 YAML 共用同一套配置契约。</p></div>
          <button class="primary-action" @click="modelPanelOpen = !modelPanelOpen"><Cpu :size="16" />添加模型服务</button>
        </div>
        <div v-if="modelMessage" class="settings-message"><Check :size="14" />{{ modelMessage }}</div>

        <div class="settings-summary">
          <article><KeyRound :size="18" /><div><strong>密钥不落库</strong><span>系统凭证库 · env:// 引用 · 永不回显</span></div></article>
          <article><Workflow :size="18" /><div><strong>协议自动适配</strong><span>探测后人工确认 · 统一响应与错误契约</span></div></article>
          <article><ShieldCheck :size="18" /><div><strong>评测后发布</strong><span>规划模型低随机性 · 黄金问题门禁 ≥99%</span></div></article>
        </div>

        <div class="settings-layout">
          <section class="settings-card">
            <div class="panel-title"><div><Cpu :size="17" /><strong>模型服务</strong></div><span>{{ modelProviders.length }} 个</span></div>
            <div class="provider-list">
              <article v-for="provider in modelProviders" :key="provider.key">
                <span class="provider-mark">{{ provider.name.slice(0, 1) }}</span>
                <div><strong>{{ provider.name }}</strong><small>{{ provider.default_model }} · {{ provider.api_mode }}</small><code>{{ provider.base_url }}</code></div>
                <span class="source-badge">{{ provider.source === 'yaml' ? 'YAML' : '页面' }}</span>
                <span class="status-badge" :data-status="provider.status">{{ modelStatusLabels[provider.status] ?? provider.status }}</span>
                <div class="provider-actions"><button @click="editModelProvider(provider)">配置</button><button @click="verifyModelProvider(provider)">探测</button></div>
              </article>
              <div v-if="!modelProviders.length" class="model-empty"><Cpu :size="24" /><strong>尚未配置模型</strong><span>FATHOM 的确定性语义查询仍可运行；配置模型后启用自动建模、跨模态和解释增强。</span></div>
            </div>
          </section>

          <section class="settings-card">
            <div class="panel-title"><div><SlidersHorizontal :size="17" /><strong>任务模型路由</strong></div><span>按职责隔离</span></div>
            <div class="route-list">
              <article v-for="route in modelRoutes" :key="route.key">
                <div><strong>{{ route.label }}</strong><small>建议温度 {{ route.recommended_temperature ?? '不适用' }} · {{ route.source }}</small></div>
                <select v-model="route.provider_key" @change="persistModelRoute(route)">
                  <option value="">未绑定</option>
                  <option v-for="provider in modelProviders" :key="provider.key" :value="provider.key">{{ provider.name }}</option>
                </select>
              </article>
            </div>
          </section>
        </div>

        <section class="config-card">
          <div><FileCode2 :size="18" /><span><strong>配置文件入口</strong><small>{{ effectiveConfiguration?.config_file || 'config/fathom.yaml' }}</small></span></div>
          <code>环境变量 &gt; YAML &gt; Web 持久化 &gt; 默认值</code>
          <span>运行时仅展示非敏感有效配置</span>
        </section>

        <form v-if="modelPanelOpen" class="connection-form model-form" @submit.prevent="persistModelProvider">
          <div class="form-heading"><div><span class="eyebrow">MODEL PROVIDER</span><h3>添加模型服务</h3></div><button type="button" @click="modelPanelOpen = false"><X :size="17" /></button></div>
          <label>服务名称<input v-model="draftModelProvider.name" /></label>
          <label>唯一标识<input v-model="draftModelProvider.key" /></label>
          <label>供应商<select v-model="draftModelProvider.provider_type" @change="applyModelPreset"><option v-for="preset in modelPresets" :key="preset.key" :value="preset.key">{{ preset.label }}</option></select></label>
          <label>Base URL<input v-model="draftModelProvider.base_url" placeholder="https://api.example.com/v1" /></label>
          <label>模型名称<input v-model="draftModelProvider.default_model" list="available-models" placeholder="选择或输入模型 ID" /><datalist id="available-models"><option v-for="model in draftModelProvider.available_models ?? []" :key="model" :value="model" /></datalist><small v-if="draftModelProvider.available_models?.length">已自动获取 {{ draftModelProvider.available_models.length }} 个模型；仍可手动输入。</small></label>
          <label>API 协议<select v-model="draftModelProvider.api_mode"><option value="auto">自动探测</option><option value="responses">Responses</option><option value="chat_completions">Chat Completions</option><option value="messages">Messages</option><option value="embeddings">Embeddings</option></select></label>
          <label>API Key（仅写入）<input v-model="draftModelProvider.api_key" type="password" autocomplete="new-password" placeholder="留空则使用下方引用" /><small>保存成功后立即清空；不会写入 SQLite、YAML、日志或返回接口。</small></label>
          <label>密钥引用<input v-model="draftModelProvider.secret_reference" placeholder="env://FATHOM_MODEL_API_KEY" /></label>
          <div class="parameter-grid">
            <label>Temperature<input v-model.number="draftModelProvider.parameters.temperature" type="number" min="0" max="2" step="0.1" /></label>
            <label>Top P<input v-model.number="draftModelProvider.parameters.top_p" type="number" min="0" max="1" step="0.1" /></label>
            <label>最大输出 Token<input v-model.number="draftModelProvider.parameters.max_output_tokens" type="number" min="1" /></label>
            <label>超时（秒）<input v-model.number="draftModelProvider.parameters.timeout_seconds" type="number" min="1" /></label>
          </div>
          <button class="primary-action" type="submit"><Save :size="15" />保存并等待探测</button>
        </form>
      </section>
    </main>
  </div>
</template>
