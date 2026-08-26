import { useCallback, useEffect, useState } from 'react'
import {
  Alert,
  Button,
  PageSection,
  Spinner,
  Title,
} from '@patternfly/react-core'
import { Table, Thead, Tr, Th, Tbody, Td } from '@patternfly/react-table'
import { listIngestionAdapters, runIngestionAdapter } from '../api/admin'
import { ApiError } from '../api/client'
import type { IngestionAdapterInfo } from '../types/api'

export function IngestionPage() {
  const [adapters, setAdapters] = useState<IngestionAdapterInfo[]>([])
  const [enabledDomains, setEnabledDomains] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [runningId, setRunningId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const res = await listIngestionAdapters()
      setAdapters(res.adapters)
      setEnabledDomains(res.enabled_domains)
      setError(null)
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : 'Failed to load adapters',
      )
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const onRun = async (adapterId: string) => {
    setRunningId(adapterId)
    setSuccess(null)
    setError(null)
    try {
      const res = await runIngestionAdapter(adapterId)
      setSuccess(
        `Adapter ${res.adapter_id} upserted ${res.entities_upserted} entities`,
      )
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : `Run failed for ${adapterId}`,
      )
    } finally {
      setRunningId(null)
    }
  }

  return (
    <>
      <PageSection>
        <Title headingLevel="h1">Ingestion</Title>
        <p>
          On-demand pulls from domain adapters into the PostGIS live store and
          Neo4j Entity nodes. Scheduled runs use the cluster CronJob; this page
          triggers the same runner manually.
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
          <Spinner aria-label="Loading ingestion adapters" />
        ) : adapters.length === 0 ? (
          <Alert variant="warning" title="No adapters loaded" isInline>
            Set ENABLED_DOMAINS (e.g. aviation, earthquakes) and restart the API.
            Enabled now: {enabledDomains.join(', ') || 'none'}.
          </Alert>
        ) : (
          <Table aria-label="Ingestion adapters" variant="compact">
            <Thead>
              <Tr>
                <Th>Adapter</Th>
                <Th>Domain</Th>
                <Th>Action</Th>
              </Tr>
            </Thead>
            <Tbody>
              {adapters.map((a) => (
                <Tr key={a.adapter_id}>
                  <Td dataLabel="Adapter">{a.adapter_id}</Td>
                  <Td dataLabel="Domain">{a.domain_id}</Td>
                  <Td dataLabel="Action">
                    <Button
                      variant="secondary"
                      isLoading={runningId === a.adapter_id}
                      isDisabled={runningId !== null && runningId !== a.adapter_id}
                      onClick={() => void onRun(a.adapter_id)}
                    >
                      Run now
                    </Button>
                  </Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        )}
      </PageSection>
    </>
  )
}
