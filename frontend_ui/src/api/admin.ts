import { apiFetch, ApiError } from './client'
import type {
  AdminStats,
  EntityDetail,
  EntityFeatureCollection,
  EntityListResponse,
  GraphEdge,
  GraphEvent,
  GraphNode,
  ImportCommitResponse,
  ImportDraft,
  ImportFormatsResponse,
  ImportMapping,
  InjectEventRequest,
  InjectEventResponse,
  IngestionAdaptersResponse,
  IngestionRunResponse,
  PlatformConfig,
  BootstrapResponse,
  SyncStatus,
  BboxEntityIdsResponse,
} from '../types/api'

export function getStats(): Promise<AdminStats> {
  return apiFetch<AdminStats>('/admin/stats')
}

export function getEntityTypes(): Promise<string[]> {
  return apiFetch<string[]>('/admin/entity-types')
}

export function listEntities(params: {
  type?: string
  search?: string
  limit?: number
  offset?: number
}): Promise<EntityListResponse> {
  const query = new URLSearchParams()
  if (params.type) query.set('type', params.type)
  if (params.search) query.set('search', params.search)
  if (params.limit != null) query.set('limit', String(params.limit))
  if (params.offset != null) query.set('offset', String(params.offset))
  const qs = query.toString()
  return apiFetch<EntityListResponse>(`/admin/entities${qs ? `?${qs}` : ''}`)
}

export function getEntity(
  entityId: string,
  statesLimit = 20,
): Promise<EntityDetail> {
  return apiFetch<EntityDetail>(
    `/admin/entities/${encodeURIComponent(entityId)}?states_limit=${statesLimit}`,
  )
}

export function getEntitiesGeoJson(params?: {
  type?: string
  bbox?: string
  ids?: string[]
  limit?: number
}): Promise<EntityFeatureCollection> {
  const query = new URLSearchParams()
  if (params?.type) query.set('type', params.type)
  if (params?.bbox) query.set('bbox', params.bbox)
  if (params?.ids?.length) query.set('ids', params.ids.join(','))
  if (params?.limit != null) query.set('limit', String(params.limit))
  const qs = query.toString()
  return apiFetch<EntityFeatureCollection>(
    `/admin/entities/geojson${qs ? `?${qs}` : ''}`,
  )
}

export function listGraphNodes(limit = 100): Promise<GraphNode[]> {
  return apiFetch<GraphNode[]>(`/admin/graph/nodes?limit=${limit}`)
}

export function listScenarios(): Promise<string[]> {
  return apiFetch<string[]>('/admin/graph/scenarios')
}

export function listGraphEvents(scenarioId?: string): Promise<GraphEvent[]> {
  const qs = scenarioId
    ? `?scenario_id=${encodeURIComponent(scenarioId)}`
    : ''
  return apiFetch<GraphEvent[]>(`/admin/graph/events${qs}`)
}

export function listGraphEdges(
  limit = 200,
  dependencyOnly = false,
): Promise<GraphEdge[]> {
  const qs = new URLSearchParams({
    limit: String(limit),
    dependency_only: String(dependencyOnly),
  })
  return apiFetch<GraphEdge[]>(`/admin/graph/edges?${qs}`)
}

export function injectEvent(
  body: InjectEventRequest,
): Promise<InjectEventResponse> {
  return apiFetch('/admin/graph/events', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function deleteScenario(
  scenarioId: string,
): Promise<{ status: string; scenario_id: string }> {
  return apiFetch(`/admin/graph/scenarios/${encodeURIComponent(scenarioId)}`, {
    method: 'DELETE',
  })
}

export function syncScenarioSpatial(
  scenarioId: string,
): Promise<{
  status: string
  scenario_id: string
  events: Record<string, number>
  total_affected: number
}> {
  return apiFetch(
    `/admin/graph/scenarios/${encodeURIComponent(scenarioId)}/sync-spatial`,
    { method: 'POST' },
  )
}

export function getSyncStatus(): Promise<SyncStatus> {
  return apiFetch('/admin/data/sync-status')
}

export function listEntityIdsInBbox(bbox: string): Promise<BboxEntityIdsResponse> {
  const qs = new URLSearchParams({ bbox })
  return apiFetch(`/admin/entities/in-bbox?${qs}`)
}

export function createDependencyEdge(body: {
  from_id: string
  to_id: string
  edge_type: string
}): Promise<{ status: string; edges_affected: number }> {
  return apiFetch('/admin/graph/dependency-edges', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function deleteDependencyEdge(params: {
  from_id: string
  to_id: string
  edge_type: string
}): Promise<{ status: string; edges_removed: number }> {
  const qs = new URLSearchParams({
    from_id: params.from_id,
    to_id: params.to_id,
    edge_type: params.edge_type,
  })
  return apiFetch(`/admin/graph/dependency-edges?${qs}`, { method: 'DELETE' })
}

export function listIngestionAdapters(): Promise<IngestionAdaptersResponse> {
  return apiFetch('/admin/ingestion/adapters')
}

export function runIngestionAdapter(
  adapterId: string,
): Promise<IngestionRunResponse> {
  return apiFetch('/admin/ingestion/run', {
    method: 'POST',
    body: JSON.stringify({ adapter_id: adapterId }),
  })
}

export function getPlatformConfig(): Promise<PlatformConfig> {
  return apiFetch('/admin/platform/config')
}

export function runPlatformBootstrap(): Promise<BootstrapResponse> {
  return apiFetch('/admin/platform/bootstrap', { method: 'POST' })
}

export function getImportFormats(): Promise<ImportFormatsResponse> {
  return apiFetch('/admin/imports/formats')
}

async function postImport(
  path: string,
  params: {
    file: File
    edgesFile?: File
    mapping: ImportMapping
  },
): Promise<Response> {
  const form = new FormData()
  form.append('file', params.file)
  if (params.edgesFile) {
    form.append('edges_file', params.edgesFile)
  }
  form.append('mapping', JSON.stringify(params.mapping))
  return fetch(path, {
    method: 'POST',
    body: form,
    headers: { Accept: 'application/json' },
  })
}

async function parseImportResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let body: unknown
    try {
      body = await response.json()
    } catch {
      body = await response.text().catch(() => undefined)
    }
    throw new ApiError(
      `Request failed: ${response.status} ${response.statusText}`,
      response.status,
      body,
    )
  }
  return (await response.json()) as T
}

export async function previewGraphImport(params: {
  file: File
  edgesFile?: File
  mapping: ImportMapping
}): Promise<ImportDraft> {
  const response = await postImport('/admin/imports/preview', params)
  return parseImportResponse<ImportDraft>(response)
}

export async function commitGraphImport(params: {
  file: File
  edgesFile?: File
  mapping: ImportMapping
}): Promise<ImportCommitResponse> {
  const response = await postImport('/admin/imports/commit', params)
  return parseImportResponse<ImportCommitResponse>(response)
}
