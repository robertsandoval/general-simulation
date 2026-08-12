import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Alert,
  Button,
  Flex,
  FlexItem,
  Form,
  FormGroup,
  FormHelperText,
  FormSelect,
  FormSelectOption,
  HelperText,
  HelperTextItem,
  PageSection,
  Spinner,
  TextInput,
  Title,
} from '@patternfly/react-core'
import { Table, Thead, Tr, Th, Tbody, Td, ActionsColumn } from '@patternfly/react-table'
import {
  createDependencyEdge,
  deleteDependencyEdge,
  getImportFormats,
  getSyncStatus,
  listGraphEdges,
} from '../api/admin'
import { ApiError } from '../api/client'
import type { GraphEdge, SyncStatus } from '../types/api'

export function DependenciesPage() {
  const [edges, setEdges] = useState<GraphEdge[]>([])
  const [sync, setSync] = useState<SyncStatus | null>(null)
  const [edgeTypes, setEdgeTypes] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const [fromId, setFromId] = useState('')
  const [toId, setToId] = useState('')
  const [edgeType, setEdgeType] = useState('DEPENDS_ON')

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const [e, s] = await Promise.all([
        listGraphEdges(500, true),
        getSyncStatus(),
      ])
      setEdges(e)
      setSync(s)
      setError(null)
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : 'Failed to load dependencies',
      )
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  useEffect(() => {
    void getImportFormats().then((f) => {
      if (f.edge_types.length > 0) setEdgeTypes(f.edge_types)
    }).catch(() => {})
  }, [])

  const onAddEdge = async (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitting(true)
    setSuccess(null)
    setError(null)
    try {
      await createDependencyEdge({
        from_id: fromId.trim(),
        to_id: toId.trim(),
        edge_type: edgeType,
      })
      setSuccess(`Linked ${fromId.trim()} → ${toId.trim()} (${edgeType})`)
      setFromId('')
      setToId('')
      await refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not create edge')
    } finally {
      setSubmitting(false)
    }
  }

  const onDeleteEdge = async (edge: GraphEdge) => {
    if (
      !window.confirm(
        `Remove ${edge.edge_type} edge ${edge.from_id} → ${edge.to_id}?`,
      )
    ) {
      return
    }
    setError(null)
    setSuccess(null)
    try {
      await deleteDependencyEdge({
        from_id: edge.from_id,
        to_id: edge.to_id,
        edge_type: edge.edge_type,
      })
      setSuccess(`Removed edge ${edge.from_id} → ${edge.to_id}`)
      await refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not delete edge')
    }
  }

  return (
    <>
      <PageSection>
        <Title headingLevel="h1">Dependencies</Title>
        <p>
          Manage Neo4j dependency edges and monitor drift between the PostGIS
          live store and the graph. Simulation overlay edges are not shown here.
        </p>
      </PageSection>
      <PageSection>
        {error ? (
          <Alert variant="danger" title={error} isInline style={{ marginBottom: '1rem' }} />
        ) : null}
        {success ? (
          <Alert variant="success" title={success} isInline style={{ marginBottom: '1rem' }} />
        ) : null}

        {loading ? (
          <Spinner aria-label="Loading dependencies" />
        ) : (
          <Flex direction={{ default: 'column' }} gap={{ default: 'gapLg' }}>
            {sync ? (
              <FlexItem>
                <Alert
                  variant={sync.in_sync ? 'success' : 'warning'}
                  title={
                    sync.in_sync
                      ? 'Postgres and Neo4j entity IDs are in sync'
                      : 'Entity ID drift detected between Postgres and Neo4j'
                  }
                  isInline
                >
                  Postgres: {sync.postgres_entity_count} entities · Neo4j:{' '}
                  {sync.neo4j_entity_count} nodes · Only in Postgres:{' '}
                  {sync.postgres_only_count} · Only in Neo4j:{' '}
                  {sync.neo4j_only_count}
                  {sync.postgres_only_sample.length > 0 ? (
                    <div style={{ marginTop: '0.5rem' }}>
                      Postgres-only sample:{' '}
                      {sync.postgres_only_sample.join(', ')}
                    </div>
                  ) : null}
                  {sync.neo4j_only_sample.length > 0 ? (
                    <div style={{ marginTop: '0.25rem' }}>
                      Neo4j-only sample: {sync.neo4j_only_sample.join(', ')}
                    </div>
                  ) : null}
                  {!sync.in_sync ? (
                    <div style={{ marginTop: '0.5rem' }}>
                      Run <Link to="/data/ingestion">ingestion</Link> or{' '}
                      <Link to="/data/import">import</Link> to align stores, or
                      use <Link to="/platform">schema bootstrap</Link> on a fresh
                      cluster.
                    </div>
                  ) : null}
                </Alert>
              </FlexItem>
            ) : null}

            <FlexItem>
              <Flex
                direction={{ default: 'column', lg: 'row' }}
                spaceItems={{ default: 'spaceItemsXl' }}
              >
                <FlexItem flex={{ default: 'flex_1' }}>
                  <Title headingLevel="h2" size="lg">
                    Dependency edges ({edges.length})
                  </Title>
                  <Table aria-label="Dependency edges" variant="compact">
                    <Thead>
                      <Tr>
                        <Th>From</Th>
                        <Th>Type</Th>
                        <Th>To</Th>
                        <Th>Actions</Th>
                      </Tr>
                    </Thead>
                    <Tbody>
                      {edges.length === 0 ? (
                        <Tr>
                          <Td colSpan={4}>No dependency edges yet.</Td>
                        </Tr>
                      ) : (
                        edges.map((edge) => (
                          <Tr key={`${edge.from_id}-${edge.edge_type}-${edge.to_id}`}>
                            <Td dataLabel="From">{edge.from_id}</Td>
                            <Td dataLabel="Type">{edge.edge_type}</Td>
                            <Td dataLabel="To">{edge.to_id}</Td>
                            <Td dataLabel="Actions" isActionCell>
                              <ActionsColumn
                                items={[
                                  {
                                    title: 'Delete',
                                    onClick: () => void onDeleteEdge(edge),
                                  },
                                ]}
                              />
                            </Td>
                          </Tr>
                        ))
                      )}
                    </Tbody>
                  </Table>
                </FlexItem>

                <FlexItem flex={{ default: 'flex_1' }}>
                  <Title headingLevel="h2" size="lg">
                    Add dependency edge
                  </Title>
                  <Form onSubmit={(e) => void onAddEdge(e)}>
                    <FormGroup label="From entity ID" isRequired fieldId="from-id">
                      <TextInput
                        id="from-id"
                        value={fromId}
                        onChange={(_e, v) => setFromId(v)}
                        isRequired
                      />
                    </FormGroup>
                    <FormGroup label="To entity ID" isRequired fieldId="to-id">
                      <TextInput
                        id="to-id"
                        value={toId}
                        onChange={(_e, v) => setToId(v)}
                        isRequired
                      />
                    </FormGroup>
                    <FormGroup label="Edge type" fieldId="edge-type">
                      <FormSelect
                        id="edge-type"
                        value={edgeType}
                        onChange={(_e, v) => setEdgeType(v)}
                      >
                        {edgeTypes.map((t) => (
                          <FormSelectOption key={t} value={t} label={t} />
                        ))}
                      </FormSelect>
                    </FormGroup>
                    <FormHelperText>
                      <HelperText>
                        <HelperTextItem>
                          Both entities must exist as Neo4j Entity nodes. Import
                          or ingestion upserts them automatically.
                        </HelperTextItem>
                      </HelperText>
                    </FormHelperText>
                    <Button type="submit" variant="primary" isLoading={submitting}>
                      Add edge
                    </Button>
                  </Form>
                </FlexItem>
              </Flex>
            </FlexItem>
          </Flex>
        )}
      </PageSection>
    </>
  )
}
