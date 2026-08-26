import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Form,
  FormGroup,
  FormHelperText,
  FormSelect,
  FormSelectOption,
  HelperText,
  HelperTextItem,
  PageSection,
  TextInput,
  TextArea,
  Title,
  Flex,
  FlexItem,
  Spinner,
  Divider,
} from '@patternfly/react-core'
import { Table, Thead, Tr, Th, Tbody, Td } from '@patternfly/react-table'
import {
  commitGraphImport,
  getImportFormats,
  previewGraphImport,
} from '../api/admin'
import { ApiError } from '../api/client'
import type {
  ImportDraft,
  ImportFormatsResponse,
  ImportMapping,
} from '../types/api'

const DEFAULT_MAPPING: ImportMapping = {
  format: 'json',
  entity_id_column: 'id',
  entity_type_column: 'type',
  default_entity_type: 'entity',
  status_column: 'status',
  default_status: 'imported',
  lon_column: 'lon',
  lat_column: 'lat',
  attribute_columns: [],
  edge_from_column: 'from_id',
  edge_to_column: 'to_id',
  edge_type_column: 'edge_type',
  default_edge_type: 'DEPENDS_ON',
  id_prefix: '',
  dataset_id: '',
}

function formatApiError(err: unknown): string {
  if (err instanceof ApiError) {
    const body = err.body as
      | { detail?: string | { message?: string; draft?: ImportDraft } }
      | undefined
    if (typeof body?.detail === 'string') return body.detail
    if (body?.detail && typeof body.detail === 'object') {
      return body.detail.message ?? err.message
    }
    return err.message
  }
  return 'Import request failed'
}

export function ImportPage() {
  const [formats, setFormats] = useState<ImportFormatsResponse | null>(null)
  const [mapping, setMapping] = useState<ImportMapping>(DEFAULT_MAPPING)
  const [entitiesFile, setEntitiesFile] = useState<File | null>(null)
  const [edgesFile, setEdgesFile] = useState<File | null>(null)
  const [draft, setDraft] = useState<ImportDraft | null>(null)
  const [attrColumnsText, setAttrColumnsText] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    void getImportFormats()
      .then(setFormats)
      .catch(() => {
        /* optional metadata */
      })
  }, [])

  const edgeTypes = formats?.edge_types ?? [
    'DEPENDS_ON',
    'FEEDS',
    'CARRIES',
  ]

  const setField = useCallback(
    <K extends keyof ImportMapping>(key: K, value: ImportMapping[K]) => {
      setMapping((m) => ({ ...m, [key]: value }))
    },
    [],
  )

  const mappingForRequest = useMemo((): ImportMapping => {
    const attrs = attrColumnsText
      .split(/[\s,]+/)
      .map((s) => s.trim())
      .filter(Boolean)
    return {
      ...mapping,
      attribute_columns: attrs,
      dataset_id: mapping.dataset_id?.trim() || null,
      id_prefix: mapping.id_prefix?.trim() || '',
      entity_type_column: mapping.entity_type_column?.trim() || null,
      status_column: mapping.status_column?.trim() || null,
      lon_column: mapping.lon_column?.trim() || null,
      lat_column: mapping.lat_column?.trim() || null,
      edge_type_column: mapping.edge_type_column?.trim() || null,
    }
  }, [mapping, attrColumnsText])

  const runPreview = async () => {
    if (!entitiesFile) {
      setError('Choose an entities file first')
      return
    }
    setBusy(true)
    setError(null)
    setSuccess(null)
    try {
      const result = await previewGraphImport({
        file: entitiesFile,
        edgesFile: edgesFile ?? undefined,
        mapping: mappingForRequest,
      })
      setDraft(result)
      if (result.ok) {
        setSuccess(
          `Preview OK — ${result.entity_count} entities, ${result.edge_count} edges`,
        )
      } else {
        setError(
          `Preview found ${result.error_count} error(s); fix mapping or file before commit`,
        )
      }
    } catch (err) {
      setDraft(null)
      setError(formatApiError(err))
    } finally {
      setBusy(false)
    }
  }

  const runCommit = async () => {
    if (!entitiesFile) {
      setError('Choose an entities file first')
      return
    }
    if (!window.confirm('Commit this import to PostGIS and Neo4j?')) {
      return
    }
    setBusy(true)
    setError(null)
    setSuccess(null)
    try {
      const result = await commitGraphImport({
        file: entitiesFile,
        edgesFile: edgesFile ?? undefined,
        mapping: mappingForRequest,
      })
      setDraft(result.draft)
      setSuccess(
        `Committed ${result.entities_upserted} entities and ${result.edges_merged} edges` +
          (result.dataset_id ? ` (dataset ${result.dataset_id})` : ''),
      )
    } catch (err) {
      if (err instanceof ApiError) {
        const body = err.body as
          | { detail?: { draft?: ImportDraft; message?: string } }
          | undefined
        if (
          body?.detail &&
          typeof body.detail === 'object' &&
          body.detail.draft
        ) {
          setDraft(body.detail.draft)
        }
      }
      setError(formatApiError(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <PageSection>
      <Title headingLevel="h1">Import graph</Title>
      <p>
        Upload CSV or JSON to create live entities and dependency edges
        (DEPENDS_ON / FEEDS / CARRIES). Preview first, then commit. Simulation
        events are still created on the Scenarios page.
      </p>

      {error && (
        <Alert
          variant="danger"
          title="Import error"
          isInline
          style={{ marginBottom: 16 }}
        >
          {error}
        </Alert>
      )}
      {success && (
        <Alert
          variant="success"
          title="Import"
          isInline
          style={{ marginBottom: 16 }}
        >
          {success}
        </Alert>
      )}

      <Form onSubmit={(e) => e.preventDefault()}>
        <Flex
          gap={{ default: 'gapMd' }}
          alignItems={{ default: 'alignItemsFlexEnd' }}
        >
          <FlexItem>
            <FormGroup label="Format" fieldId="import-format">
              <FormSelect
                id="import-format"
                value={mapping.format}
                onChange={(_e, v) =>
                  setField('format', v as ImportMapping['format'])
                }
                aria-label="Import format"
              >
                <FormSelectOption value="json" label="json" />
                <FormSelectOption value="csv" label="csv" />
              </FormSelect>
            </FormGroup>
          </FlexItem>
          <FlexItem>
            <FormGroup label="Entities file" isRequired fieldId="entities-file">
              <input
                id="entities-file"
                type="file"
                accept=".json,.csv,text/csv,application/json"
                onChange={(e) => {
                  setEntitiesFile(e.target.files?.[0] ?? null)
                  setDraft(null)
                }}
              />
            </FormGroup>
          </FlexItem>
          {mapping.format === 'csv' && (
            <FlexItem>
              <FormGroup label="Edges CSV (optional)" fieldId="edges-file">
                <input
                  id="edges-file"
                  type="file"
                  accept=".csv,text/csv"
                  onChange={(e) => {
                    setEdgesFile(e.target.files?.[0] ?? null)
                    setDraft(null)
                  }}
                />
              </FormGroup>
            </FlexItem>
          )}
        </Flex>

        <Divider style={{ margin: '1.5rem 0' }} />

        <Title headingLevel="h2" size="lg">
          Column mapping
        </Title>
        <FormHelperText>
          <HelperText>
            <HelperTextItem>
              For JSON with <code>entities</code> / <code>edges</code> arrays,
              mapping is mostly unused. For CSV, set columns to match your
              headers.
            </HelperTextItem>
          </HelperText>
        </FormHelperText>

        <Flex gap={{ default: 'gapMd' }} style={{ flexWrap: 'wrap' }}>
          <FlexItem>
            <FormGroup label="Entity ID column" fieldId="entity-id-col">
              <TextInput
                id="entity-id-col"
                value={mapping.entity_id_column}
                onChange={(_e, v) => setField('entity_id_column', v)}
              />
            </FormGroup>
          </FlexItem>
          <FlexItem>
            <FormGroup label="Type column" fieldId="entity-type-col">
              <TextInput
                id="entity-type-col"
                value={mapping.entity_type_column ?? ''}
                onChange={(_e, v) => setField('entity_type_column', v)}
              />
            </FormGroup>
          </FlexItem>
          <FlexItem>
            <FormGroup label="Default type" fieldId="default-type">
              <TextInput
                id="default-type"
                value={mapping.default_entity_type}
                onChange={(_e, v) => setField('default_entity_type', v)}
              />
            </FormGroup>
          </FlexItem>
          <FlexItem>
            <FormGroup label="Lon column" fieldId="lon-col">
              <TextInput
                id="lon-col"
                value={mapping.lon_column ?? ''}
                onChange={(_e, v) => setField('lon_column', v)}
              />
            </FormGroup>
          </FlexItem>
          <FlexItem>
            <FormGroup label="Lat column" fieldId="lat-col">
              <TextInput
                id="lat-col"
                value={mapping.lat_column ?? ''}
                onChange={(_e, v) => setField('lat_column', v)}
              />
            </FormGroup>
          </FlexItem>
          <FlexItem>
            <FormGroup label="From column" fieldId="from-col">
              <TextInput
                id="from-col"
                value={mapping.edge_from_column}
                onChange={(_e, v) => setField('edge_from_column', v)}
              />
            </FormGroup>
          </FlexItem>
          <FlexItem>
            <FormGroup label="To column" fieldId="to-col">
              <TextInput
                id="to-col"
                value={mapping.edge_to_column}
                onChange={(_e, v) => setField('edge_to_column', v)}
              />
            </FormGroup>
          </FlexItem>
          <FlexItem>
            <FormGroup label="Edge type column" fieldId="edge-type-col">
              <TextInput
                id="edge-type-col"
                value={mapping.edge_type_column ?? ''}
                onChange={(_e, v) => setField('edge_type_column', v)}
              />
            </FormGroup>
          </FlexItem>
          <FlexItem>
            <FormGroup label="Default edge type" fieldId="default-edge-type">
              <FormSelect
                id="default-edge-type"
                value={mapping.default_edge_type}
                onChange={(_e, v) => setField('default_edge_type', v)}
                aria-label="Default edge type"
              >
                {edgeTypes.map((t) => (
                  <FormSelectOption key={t} value={t} label={t} />
                ))}
              </FormSelect>
            </FormGroup>
          </FlexItem>
          <FlexItem>
            <FormGroup label="ID prefix" fieldId="id-prefix">
              <TextInput
                id="id-prefix"
                value={mapping.id_prefix ?? ''}
                onChange={(_e, v) => setField('id_prefix', v)}
                placeholder="net-"
              />
            </FormGroup>
          </FlexItem>
          <FlexItem>
            <FormGroup label="Dataset ID" fieldId="dataset-id">
              <TextInput
                id="dataset-id"
                value={mapping.dataset_id ?? ''}
                onChange={(_e, v) => setField('dataset_id', v)}
                placeholder="optional tag"
              />
            </FormGroup>
          </FlexItem>
        </Flex>

        <FormGroup
          label="Attribute columns (CSV, comma-separated)"
          fieldId="attr-cols"
          style={{ marginTop: 16, maxWidth: 640 }}
        >
          <TextArea
            id="attr-cols"
            value={attrColumnsText}
            onChange={(_e, v) => setAttrColumnsText(v)}
            placeholder="Leave empty to take all non-mapped columns"
            rows={2}
          />
        </FormGroup>

        <Flex gap={{ default: 'gapMd' }} style={{ marginTop: 24 }}>
          <FlexItem>
            <Button
              variant="secondary"
              onClick={() => void runPreview()}
              isDisabled={busy || !entitiesFile}
            >
              {busy ? <Spinner size="md" /> : 'Preview'}
            </Button>
          </FlexItem>
          <FlexItem>
            <Button
              variant="primary"
              onClick={() => void runCommit()}
              isDisabled={busy || !entitiesFile || (draft != null && !draft.ok)}
            >
              Commit import
            </Button>
          </FlexItem>
        </Flex>
      </Form>

      {draft && (
        <>
          <Divider style={{ margin: '2rem 0 1rem' }} />
          <Title headingLevel="h2" size="lg">
            Preview
          </Title>
          <p>
            {draft.entity_count} entities · {draft.edge_count} edges ·{' '}
            {draft.error_count} errors · {draft.warning_count} warnings
            {draft.detected_columns.length > 0 && (
              <> · columns: {draft.detected_columns.join(', ')}</>
            )}
          </p>

          {draft.issues.length > 0 && (
            <Table aria-label="Import issues" variant="compact">
              <Thead>
                <Tr>
                  <Th>Level</Th>
                  <Th>Row</Th>
                  <Th>Message</Th>
                </Tr>
              </Thead>
              <Tbody>
                {draft.issues.slice(0, 50).map((issue, idx) => (
                  <Tr key={`${issue.level}-${idx}`}>
                    <Td dataLabel="Level">{issue.level}</Td>
                    <Td dataLabel="Row">{issue.row ?? '—'}</Td>
                    <Td dataLabel="Message">{issue.message}</Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          )}

          {draft.entities.length > 0 && (
            <>
              <Title headingLevel="h3" size="md" style={{ marginTop: 24 }}>
                Entities (first 20)
              </Title>
              <Table aria-label="Import entities" variant="compact">
                <Thead>
                  <Tr>
                    <Th>ID</Th>
                    <Th>Type</Th>
                    <Th>Status</Th>
                    <Th>Geometry</Th>
                  </Tr>
                </Thead>
                <Tbody>
                  {draft.entities.slice(0, 20).map((e) => (
                    <Tr key={e.id}>
                      <Td dataLabel="ID">{e.id}</Td>
                      <Td dataLabel="Type">{e.type}</Td>
                      <Td dataLabel="Status">{e.status}</Td>
                      <Td dataLabel="Geometry">{e.geometry?.type ?? '—'}</Td>
                    </Tr>
                  ))}
                </Tbody>
              </Table>
            </>
          )}

          {draft.edges.length > 0 && (
            <>
              <Title headingLevel="h3" size="md" style={{ marginTop: 24 }}>
                Edges (first 20)
              </Title>
              <Table aria-label="Import edges" variant="compact">
                <Thead>
                  <Tr>
                    <Th>From</Th>
                    <Th>Type</Th>
                    <Th>To</Th>
                  </Tr>
                </Thead>
                <Tbody>
                  {draft.edges.slice(0, 20).map((e, idx) => (
                    <Tr key={`${e.from_id}-${e.to_id}-${idx}`}>
                      <Td dataLabel="From">{e.from_id}</Td>
                      <Td dataLabel="Type">{e.edge_type}</Td>
                      <Td dataLabel="To">{e.to_id}</Td>
                    </Tr>
                  ))}
                </Tbody>
              </Table>
            </>
          )}
        </>
      )}
    </PageSection>
  )
}
