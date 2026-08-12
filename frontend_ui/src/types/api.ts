/** Mirrors FastAPI response shapes from /health, /admin/*, and /query. */

export interface HealthResponse {
  status: 'ok' | 'degraded' | string
  db: 'reachable' | 'unreachable' | string
}

export interface AdminStats {
  entity_count: number
  state_count: number
  graph_nodes: number
  graph_events: number
  scenario_count: number
}

export interface EntitySummary {
  id: string
  type: string
  attributes: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface EntityState {
  status: string
  recorded_at: string
  attributes: Record<string, unknown>
}

export interface EntityDetail extends EntitySummary {
  states: EntityState[]
}

export interface EntityListResponse {
  total: number
  limit: number
  offset: number
  items: EntitySummary[]
}

export interface GraphNode {
  id: string
  type?: string
  [key: string]: unknown
}

export interface GraphEdge {
  from_id: string
  edge_type: string
  to_id: string
}

export interface GraphEvent {
  id: string
  scenario_id: string
  description?: string
  [key: string]: unknown
}

export interface InjectEventRequest {
  id: string
  scenario_id: string
  description: string
  affected_entity_ids: string[]
  bbox?: string | null
  attributes?: Record<string, unknown>
}

export interface InjectEventResponse {
  status: string
  event_id: string
  affected_count?: number
  affect_bbox?: string | null
}

export interface SyncStatus {
  postgres_entity_count: number
  neo4j_entity_count: number
  postgres_only_count: number
  neo4j_only_count: number
  postgres_only_sample: string[]
  neo4j_only_sample: string[]
  in_sync: boolean
}

export interface BboxEntityIdsResponse {
  bbox: string
  count: number
  entity_ids: string[]
}

export interface IngestionAdapterInfo {
  adapter_id: string
  domain_id: string
}

export interface IngestionAdaptersResponse {
  enabled_domains: string[]
  adapters: IngestionAdapterInfo[]
}

export interface IngestionRunResponse {
  status: string
  adapter_id: string
  entities_upserted: number
}

export interface PlatformConfig {
  enabled_domains: string[]
  llm_backend: string
  generation_model_id: string
  embedding_model_id: string
  embedding_dimension: number
  postgres_host: string
  neo4j_uri: string
  dependency_edge_types: string[]
}

export interface BootstrapResponse {
  status: string
}

export interface ImportMapping {
  format: 'json' | 'csv'
  entity_id_column: string
  entity_type_column?: string | null
  default_entity_type: string
  status_column?: string | null
  default_status: string
  lon_column?: string | null
  lat_column?: string | null
  attribute_columns: string[]
  edge_from_column: string
  edge_to_column: string
  edge_type_column?: string | null
  default_edge_type: string
  id_prefix?: string
  dataset_id?: string | null
}

export interface ImportIssue {
  level: 'error' | 'warning'
  message: string
  row: number | null
}

export interface ImportEntityPreview {
  id: string
  type: string
  status: string
  geometry: { type: string; coordinates?: unknown } | null
  attributes: Record<string, unknown>
}

export interface ImportEdgePreview {
  from_id: string
  to_id: string
  edge_type: string
}

export interface ImportDraft {
  entities: ImportEntityPreview[]
  edges: ImportEdgePreview[]
  issues: ImportIssue[]
  detected_columns: string[]
  entity_count: number
  edge_count: number
  error_count: number
  warning_count: number
  ok: boolean
}

export interface ImportFormatsResponse {
  formats: string[]
  edge_types: string[]
  max_upload_bytes: number
}

export interface ImportCommitResponse {
  status: string
  entities_upserted: number
  edges_merged: number
  dataset_id: string | null
  draft: ImportDraft
}

export interface ResponseOptionOut {
  rank: number
  label: string
  description: string
  estimated_impact_reduction: number
}

export interface EntityValueOut {
  entity_id: string
  value_usd: number
}

export interface RecommendedRerouteOut {
  entity_id: string
  target_id: string
  target_label: string
  latitude: number
  longitude: number
  rationale: string
}

export interface SolverResultOut {
  affected_count: number
  max_chain_length: number
  impact_score: number
  total_value_at_risk: number
  currency: string
  value_breakdown: EntityValueOut[]
  response_options: ResponseOptionOut[]
  recommended_reroutes?: RecommendedRerouteOut[]
  explanation: string
}

export interface ToolCallRecord {
  tool_name: string
  arguments: Record<string, unknown>
  output: Record<string, unknown>
}

export interface QueryRequest {
  question: string
  scenario_id: string
}

export interface QueryResponse {
  question: string
  scenario_id: string
  answer: string
  affected_entities: string[]
  solver: SolverResultOut
  tool_call_trace: ToolCallRecord[]
}

export interface GeoJsonGeometry {
  type: string
  coordinates: number[] | number[][] | number[][][]
}

export interface EntityGeoJsonProperties {
  id: string
  type: string
  status: string | null
  attributes: Record<string, unknown>
  updated_at: string
}

export interface EntityGeoJsonFeature {
  type: 'Feature'
  id: string
  geometry: GeoJsonGeometry
  properties: EntityGeoJsonProperties
}

export interface EntityFeatureCollection {
  type: 'FeatureCollection'
  features: EntityGeoJsonFeature[]
}
