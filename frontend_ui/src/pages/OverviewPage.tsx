import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Alert,
  Card,
  CardBody,
  CardTitle,
  Flex,
  FlexItem,
  Gallery,
  GalleryItem,
  PageSection,
  Spinner,
  Title,
} from '@patternfly/react-core'
import { getStats, getSyncStatus } from '../api/admin'
import { getHealth } from '../api/health'
import { ApiError } from '../api/client'
import type { AdminStats, HealthResponse, SyncStatus } from '../types/api'

const STAT_LABELS: { key: keyof AdminStats; label: string }[] = [
  { key: 'entity_count', label: 'Live entities' },
  { key: 'state_count', label: 'Entity states' },
  { key: 'graph_nodes', label: 'Graph nodes' },
  { key: 'graph_events', label: 'Simulation events' },
  { key: 'scenario_count', label: 'Scenarios' },
]

export function OverviewPage() {
  const [stats, setStats] = useState<AdminStats | null>(null)
  const [sync, setSync] = useState<SyncStatus | null>(null)
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const [s, h, syncStatus] = await Promise.all([
          getStats(),
          getHealth(),
          getSyncStatus(),
        ])
        if (!cancelled) {
          setStats(s)
          setHealth(h)
          setSync(syncStatus)
          setError(null)
        }
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof ApiError
              ? err.message
              : 'Failed to load overview. Is the API running on :8000?',
          )
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <>
      <PageSection>
        <Title headingLevel="h1">Overview</Title>
        <p>
          Admin dashboard for the General Simulation platform — live store,
          dependency graph, ingestion, and simulation overlays.
        </p>
      </PageSection>
      <PageSection>
        {loading ? (
          <Spinner aria-label="Loading overview" />
        ) : error ? (
          <Alert variant="danger" title="Could not load overview" isInline>
            {error}
          </Alert>
        ) : (
          <Flex direction={{ default: 'column' }} gap={{ default: 'gapMd' }}>
            {health ? (
              <FlexItem>
                <Alert
                  variant={health.status === 'ok' ? 'success' : 'warning'}
                  title={`API status: ${health.status}`}
                  isInline
                >
                  Postgres: {health.db}
                </Alert>
              </FlexItem>
            ) : null}
            {sync ? (
              <FlexItem>
                <Alert
                  variant={sync.in_sync ? 'success' : 'warning'}
                  title={
                    sync.in_sync
                      ? 'Data stores aligned'
                      : 'Postgres / Neo4j entity drift detected'
                  }
                  isInline
                >
                  {sync.postgres_only_count} entities only in Postgres,{' '}
                  {sync.neo4j_only_count} only in Neo4j.{' '}
                  <Link to="/data/dependencies">View dependencies</Link>
                </Alert>
              </FlexItem>
            ) : null}
            <FlexItem>
              <Gallery hasGutter minWidths={{ default: '200px' }}>
                {stats
                  ? STAT_LABELS.map(({ key, label }) => (
                      <GalleryItem key={key}>
                        <Card isCompact>
                          <CardTitle>{label}</CardTitle>
                          <CardBody>
                            <Title headingLevel="h2" size="2xl">
                              {stats[key]}
                            </Title>
                          </CardBody>
                        </Card>
                      </GalleryItem>
                    ))
                  : null}
              </Gallery>
            </FlexItem>
          </Flex>
        )}
      </PageSection>
    </>
  )
}
