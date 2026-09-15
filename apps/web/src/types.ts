export type AssetKind = 'object' | 'relation' | 'attribute' | 'metric' | 'event' | 'policy'

export interface SemanticAsset {
  key: string
  kind: AssetKind
  label: string
  description: string
  domain: string
  owner: string
  aliases: string[]
  unit?: string
  expression?: string
}

export interface Relation {
  key: string
  label: string
  source_object: string
  target_object: string
  cardinality: string
  description: string
}

export interface SemanticOverview {
  domain: string
  version: string
  status: string
  counts: Record<AssetKind, number>
  assets: SemanticAsset[]
  relations: Relation[]
}

export interface ObjectInstance {
  object_id: string
  object_type: string
  label: string
  source_key: string
  attributes: Record<string, unknown>
  state: string
  updated_at: string
}

export interface DifyIntegrationStatus {
  service_running: boolean
  setup_completed: boolean
  console_url: string
  schema_url: string
  message: string
}

export interface QueryAttachment {
  name: string
  content_type: string
  text: string
  data_url: string
}

export interface AskResult {
  status: string
  answer: string
  plan: {
    status: string
    intent: string
    anchors: Array<{ kind: string; key: string; label: string }>
    abc: Array<{ code: string; name: string; status: string; summary: string }>
    validations: string[]
    clarification?: string
    mql?: {
      metric: string
      object_ids: string[]
      dimensions: string[]
      time_range: string
    }
  }
  data: {
    current?: number
    previous?: number
    delta?: number
    unit?: string
    contributors?: Array<{ label: string; minutes: number; object: string }>
    diagnosis?: {
      analysis_run_id: string
      conclusion_level: 'driver' | 'suspected_cause' | 'verified_root_cause'
      summary: string
    }
    compiled_query?: { template: string; sql: string; parameters: Record<string, unknown> }
    rows: Array<{ period: string; value: number }>
  }
  evidence: Array<{ type: string; title: string; reference: string; detail: string }>
  suggested_followups: string[]
  trace_id: string
  semantic_version: string
  data_freshness: string
  verification_status: string
  turn_id?: string
  analysis_run_id?: string
}

export interface FeedbackResult {
  feedback_id: string
  source: 'self_ui' | 'implicit_text' | 'external'
  rating: 'like' | 'dislike'
  category: string
  sentiment: string
  emotion: string
  status: string
}

export interface ConversationSummary {
  conversation_id: string
  title: string
  created_at: string
  updated_at: string
  turn_count: number
  last_question: string
}

export interface ConversationDetail extends ConversationSummary {
  turns: Array<{
    turn_id: string
    created_at: string
    question: string
    attachments: Array<{ name: string; content_type: string }>
    response: AskResult
  }>
}

export interface SqlTemplate {
  key: string
  label: string
  description: string
  dialect: string
  sql_text: string
  parameters: string[]
  published: boolean
  updated_at: string
}

export interface SqlTemplateVersion {
  version: number
  created_at: string
  snapshot: SqlTemplate
}

export interface SqlPreview {
  template_key: string
  columns: string[]
  rows: Array<Record<string, unknown>>
  row_count: number
  limit: number
  executed_at: string
}

export interface StoredPipeline {
  key: string
  label: string
  source: string
  target: string
  mode: 'preview' | 'full' | 'incremental'
  cursor_field?: string
  steps: Array<{ operation: string; configuration: Record<string, unknown> }>
  published: boolean
  updated_at: string
}

export interface PythonExtension {
  key: string
  label: string
  version: number
  code: string
  timeout_seconds: number
  memory_mb: number
  published: boolean
  updated_at: string
  limits?: Record<string, string>
}

export interface PythonExtensionRun {
  run_id: string
  extension_key: string
  status: string
  output: Record<string, unknown>
  logs: string
  error?: string
  started_at: string
  finished_at: string
}

export interface BackupItem {
  name: string
  size_bytes: number
  updated_at: string
}

export interface ConnectorType {
  key: string
  label: string
  category: string
  bundled: boolean
  driver_available: boolean
  driver?: string
  extra?: string
  operations: string[]
  install_hint?: string
}

export interface DataSource {
  key: string
  name: string
  connector_type: string
  configuration: Record<string, unknown>
  secret_reference?: string
  enabled: boolean
  status: string
  last_tested_at?: string
}

export interface KnowledgeBase {
  key: string
  name: string
  kind: 'internal' | 'external'
  configuration: Record<string, unknown>
  secret_reference?: string
  has_secret?: boolean
  enabled: boolean
  document_count: number
  updated_at: string
}

export interface KnowledgeDocument {
  document_id: string
  knowledge_base_key: string
  title: string
  source_uri: string
  metadata: Record<string, unknown>
  checksum: string
  size: number
  updated_at: string
}

export interface KnowledgeHit {
  knowledge_base_key: string
  document_id: string
  title: string
  content: string
  source_uri: string
  score: number
  metadata: Record<string, unknown>
  retrieval: string
}

export interface ModelProvider {
  key: string
  name: string
  provider_type: string
  base_url: string
  api_mode: 'auto' | 'responses' | 'chat_completions' | 'messages' | 'embeddings'
  default_model: string
  secret_reference?: string
  api_key?: string
  has_secret?: boolean
  capabilities: string[]
  available_models?: string[]
  parameters: Record<string, number | string | boolean>
  enabled: boolean
  status: string
  source?: string
  last_tested_at?: string
  warnings?: string[]
}

export interface ModelProviderPreset {
  key: string
  label: string
  default_url: string
  modes: string[]
  capabilities: string[]
}

export interface ModelRoute {
  key: string
  label: string
  recommended_temperature?: number
  provider_key?: string
  model_override?: string
  parameter_overrides: Record<string, number | string | boolean>
  source: string
}

export interface EffectiveConfiguration {
  precedence: string[]
  config_file?: string
  effective: Record<string, string | number | boolean>
  note: string
}

export interface AgentMeshOverview {
  architecture: string
  agents: Array<{
    key: string
    name: string
    layer: 'control' | 'cognition' | 'reasoning' | 'execution' | 'governance'
    description: string
    model_role?: string
    tools: string[]
    status: 'core' | 'optional'
  }>
  flows: Array<{ key: string; name: string; trigger: string; agents: string[]; sla: string }>
  counts: Record<string, number>
  principles: string[]
}

export interface AgentRun {
  run_id: string
  flow_key: string
  status: string
  trace_id?: string
  started_at: string
  completed_at: string
  receipts: Array<{
    sequence: number
    agent: string
    status: string
    summary: string
    recorded_at: string
  }>
  output: Record<string, unknown>
}

export interface EvaluationReport {
  run_id: string
  suite_key: string
  semantic_version: string
  threshold: number
  total: number
  correct: number
  accuracy: number
  accuracy_percent: number
  passed: boolean
  failures: Array<{ question: string; expected: string; actual?: string }>
  evaluated_at: string
  scope_note: string
  gates?: Record<string, { passed: boolean; total: number; correct?: number; failures?: unknown[] }>
}

export interface GoldenQuestionSet {
  suite_key: string
  semantic_version: string
  threshold: number
  scope_note: string
  total: number
  categories: Array<{ key: string; label: string; count: number }>
  cases: Array<{
    id: string
    category: string
    question: string
    expected: string
    rule: string
  }>
}

export interface PipelinePreview {
  run_id: string
  key: string
  status: 'passed' | 'failed'
  source: string
  row_count: number
  preview_count: number
  columns: string[]
  rows: Array<Record<string, unknown>>
  quality: Array<{ rule: string; column: string; failures: number; passed: boolean }>
  onn_mappings: Array<Record<string, unknown>>
  sql: string
  limits: { rows: number; memory: string; threads: number }
}

export interface SemanticChange {
  change_id: string
  created_at: string
  updated_at: string
  kind: string
  title: string
  description: string
  confidence: number
  confidence_percent: number
  impact: { assets?: number; risk?: string }
  evidence: string[]
  patch: Record<string, unknown>
  status: 'candidate' | 'in_review' | 'approved' | 'rejected' | 'published' | 'rolled_back'
  evaluation_run_id?: string
  history: Array<{
    action: string
    actor: string
    at: string
    comment: string
    evaluation_run_id?: string
  }>
  rollback_available: boolean
}

export interface RuntimeMapping {
  mapping_id: string
  key: string
  metric_key: string
  source_key: string
  version: number
  status: 'draft' | 'published' | 'retired'
  owner: string
  checksum: string
  compatibility: {
    compatible?: boolean
    missing_columns?: string[]
    checked_at?: string
  }
  definition: Record<string, unknown>
  updated_at: string
}

export interface RuntimeReceipt {
  receipt_id: string
  trace_id: string
  status: string
  resource: string
  mapping_id?: string
  policy_decision_id: string
  source_key?: string
  row_count: number
  duration_ms: number
  result_hash?: string
  data_freshness?: string
  quality_report: Record<string, unknown>
  error?: string
  completed_at: string
}

export interface RuntimeCapability {
  key: string
  version: number
  label: string
  operation: string
  minimum_role: string
  side_effect: 'none' | 'internal' | 'external'
  approval_required: boolean
  published: boolean
  definition: Record<string, unknown>
}

export interface RuntimeRequirement {
  evidence_id: string
  key: string
  title: string
  source_uri: string
  owner: string
  definition: {
    statements?: string[]
    acceptance_questions?: string[]
    linked_assets?: string[]
    citations?: Array<{ source_uri: string; excerpt: string; line: number }>
    clarification_questions?: string[]
    conflicts?: Array<{ kind: string; existing_requirement_key: string; detail: string }>
    review_status?: 'candidate' | 'in_review' | 'approved' | 'rejected'
  }
  updated_at: string
}

export interface RuntimeObjectIdentity {
  identity_id: string
  canonical_object_id: string
  source_key: string
  external_object_id: string
  owner: string
  metadata: Record<string, unknown>
  updated_at: string
}

export interface RuntimeAction {
  run_id: string
  capability_key: string
  idempotency_key: string
  object_id: string
  title: string
  status: string
  principal: string
  payload: Record<string, unknown>
  result: Record<string, unknown>
  created_at: string
}

export interface RuntimeGoldenCase {
  key: string
  question: string
  expected_value: number
  tolerance: number
  enabled: boolean
}

export interface RuntimeEvaluation {
  run_id: string
  suite_key: string
  total: number
  passed_count: number
  accuracy: number
  passed: boolean
  results: Array<Record<string, unknown>>
}

export interface RuntimeControlPlane {
  mappings: RuntimeMapping[]
  receipts: RuntimeReceipt[]
  capabilities: RuntimeCapability[]
  requirements: RuntimeRequirement[]
  identities: RuntimeObjectIdentity[]
  actions: RuntimeAction[]
  goldenCases: RuntimeGoldenCase[]
}
