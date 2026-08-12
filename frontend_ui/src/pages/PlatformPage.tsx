import { useEffect, useState } from 'react'
import {
  Alert,
  Button,
  DescriptionList,
  DescriptionListGroup,
  DescriptionListTerm,
  DescriptionListDescription,
  PageSection,
  Spinner,
  Title,
} from '@patternfly/react-core'
import { getPlatformConfig, runPlatformBootstrap } from '../api/admin'
import { ApiError } from '../api/client'
import type { PlatformConfig } from '../types/api'

export function PlatformPage() {
  const [config, setConfig] = useState<PlatformConfig | null>(null)
  const [loading, setLoading] = useState(true)
  const [bootstrapping, setBootstrapping] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const c = await getPlatformConfig()
        if (!cancelled) {
          setConfig(c)
          setError(null)
        }
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof ApiError ? err.message : 'Failed to load platform config',
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

  const onBootstrap = async () => {
    if (
      !window.confirm(
        'Run idempotent Postgres + Neo4j schema bootstrap? Safe on existing clusters.',
      )
    ) {
      return
    }
    setBootstrapping(true)
    setSuccess(null)
    setError(null)
    try {
      const res = await runPlatformBootstrap()
      setSuccess(`Bootstrap finished: ${res.status}`)
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : 'Bootstrap failed',
      )
    } finally {
      setBootstrapping(false)
    }
  }

  return (
    <>
      <PageSection>
        <Title headingLevel="h1">Platform settings</Title>
        <p>
          Read-only deployment configuration and schema bootstrap for Postgres
          (PostGIS + pgvector) and Neo4j constraints.
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
          <Spinner aria-label="Loading platform config" />
        ) : config ? (
          <>
            <DescriptionList isHorizontal>
              <DescriptionListGroup>
                <DescriptionListTerm>Enabled domains</DescriptionListTerm>
                <DescriptionListDescription>
                  {config.enabled_domains.join(', ')}
                </DescriptionListDescription>
              </DescriptionListGroup>
              <DescriptionListGroup>
                <DescriptionListTerm>LLM backend</DescriptionListTerm>
                <DescriptionListDescription>
                  {config.llm_backend}
                </DescriptionListDescription>
              </DescriptionListGroup>
              <DescriptionListGroup>
                <DescriptionListTerm>Generation model</DescriptionListTerm>
                <DescriptionListDescription>
                  {config.generation_model_id}
                </DescriptionListDescription>
              </DescriptionListGroup>
              <DescriptionListGroup>
                <DescriptionListTerm>Embedding model</DescriptionListTerm>
                <DescriptionListDescription>
                  {config.embedding_model_id} ({config.embedding_dimension} dims)
                </DescriptionListDescription>
              </DescriptionListGroup>
              <DescriptionListGroup>
                <DescriptionListTerm>Postgres</DescriptionListTerm>
                <DescriptionListDescription>
                  {config.postgres_host}
                </DescriptionListDescription>
              </DescriptionListGroup>
              <DescriptionListGroup>
                <DescriptionListTerm>Neo4j</DescriptionListTerm>
                <DescriptionListDescription>
                  {config.neo4j_uri}
                </DescriptionListDescription>
              </DescriptionListGroup>
              <DescriptionListGroup>
                <DescriptionListTerm>Dependency edge types</DescriptionListTerm>
                <DescriptionListDescription>
                  {config.dependency_edge_types.join(', ')}
                </DescriptionListDescription>
              </DescriptionListGroup>
            </DescriptionList>

            <Title headingLevel="h2" size="lg" style={{ marginTop: '1.5rem' }}>
              Schema bootstrap
            </Title>
            <p style={{ marginTop: '0.5rem' }}>
              Creates extensions, live-store tables, and Neo4j constraints if
              missing. Does not delete data.
            </p>
            <Button
              variant="primary"
              onClick={() => void onBootstrap()}
              isLoading={bootstrapping}
              style={{ marginTop: '0.75rem' }}
            >
              Run bootstrap
            </Button>
          </>
        ) : null}
      </PageSection>
    </>
  )
}
