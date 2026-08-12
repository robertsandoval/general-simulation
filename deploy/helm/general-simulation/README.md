# general-simulation Helm chart

Umbrella chart for the General Simulation & Impact-Reasoning Platform.

Inference always goes through **Llama Stack**. Two modes only:

| Mode | Stack upstream | Extra requirements |
|------|----------------|--------------------|
| **openai** (default) | OpenAI (`api.openai.com`) | `OPENAI_API_KEY` |
| **local** | In-cluster `llm-service` (vLLM) | OpenShift AI + `HF_TOKEN` |

Prefer `make deploy` from the repo root — it creates Neo4j auth / SCC bindings and applies the mode overrides.

## Modes of install

| Install | How | Namespace |
|---------|-----|-----------|
| **Standalone** | `make deploy` or `helm upgrade --install … -n <ns>` | Whatever `-n` you pass |
| **Subchart** | Parent `Chart.yaml` dependency + values | Same as the parent release |

In-cluster defaults use **short Service names** (`postgres`, `neo4j`, `llamastack`, `general-sim-api`). Cross-namespace clients should use FQDNs such as `general-sim-api.<namespace>.svc:8000`.

**Admin console:** served at `GET /admin/` on the API Service. On OpenShift, chart `0.0.1` creates Route `general-sim-admin` (path `/admin`) plus Route `general-sim-api` for the full API. Disable both on Kind: `--set api.route.enabled=false`.

## Chart repository (GitHub Pages)

Once published:

```bash
helm repo add general-simulation https://robertsandoval.github.io/general-simulation
helm repo update
helm search repo general-simulation
```

Parent / subchart dependency:

```yaml
dependencies:
  - name: general-simulation
    version: 0.0.1
    repository: https://robertsandoval.github.io/general-simulation
    condition: general-simulation.enabled
```

Legacy clients may still pin `0.2.0` until that version is retired from the chart repo (see below).


## Recommended install (Makefile)

```bash
# OpenAI via Llama Stack (default)
make deploy \
  PG_PASSWORD=<pw> NEO4J_PASSWORD=<pw> \
  OPENAI_API_KEY=<key>

# In-cluster vLLM via Llama Stack
make deploy LLM_MODE=local \
  PG_PASSWORD=<pw> NEO4J_PASSWORD=<pw> \
  HF_TOKEN=<hf-token>
```

## Manual Helm install (openai)

```bash
# Create Neo4j SA + anyuid SCC (UID 7474) and auth secret first
oc new-project general-simulation   # or --create-namespace below
oc apply -f deploy/openshift/neo4j/serviceaccount.yaml -n general-simulation
sed 's/__NAMESPACE__/general-simulation/g' deploy/openshift/neo4j/scc-binding.yaml | oc apply -f -
oc create secret generic neo4j-auth \
  -n general-simulation \
  --from-literal=NEO4J_AUTH="neo4j/<NEO4J_PASSWORD>"

helm repo add neo4j https://helm.neo4j.com/neo4j
helm repo add ai-architecture-charts https://rh-ai-quickstart.github.io/ai-architecture-charts
helm dependency update deploy/helm/general-simulation

helm upgrade --install general-simulation ./deploy/helm/general-simulation \
  --namespace general-simulation --create-namespace \
  --set postgres.postgres.password=<PG_PASSWORD> \
  --set api.postgres.password=<PG_PASSWORD> \
  --set api.neo4j.password=<NEO4J_PASSWORD> \
  --set bootstrap.postgres.password=<PG_PASSWORD> \
  --set bootstrap.neo4j.password=<NEO4J_PASSWORD> \
  --set ingestion.postgres.password=<PG_PASSWORD> \
  --set ingestion.neo4j.password=<NEO4J_PASSWORD> \
  --set-string global.models.openai.apiToken=<OPENAI_API_KEY> \
  --wait --timeout 15m
```

For **local** mode, flip providers and enable llm-service (or use `make deploy LLM_MODE=local`).

API and ingestion always call `http://llamastack:8321/v1` — never OpenAI or vLLM directly.

## Client URL

| Client location | `GENERAL_SIMULATION_BASE_URL` |
|-----------------|-------------------------------|
| Same namespace (subchart) | `http://general-sim-api:8000` |
| Other namespace | `http://general-sim-api.<gen-sim-ns>.svc:8000` |

## Component toggles

| Key | Default | Notes |
|-----|---------|--------|
| `postgres.enabled` | `true` | Platform Postgres (pgvector + PostGIS) |
| `neo4j.enabled` | `true` | Official `neo4j/neo4j` chart |
| `bootstrap.enabled` | `true` | Schema Job (hook) |
| `llama-stack.enabled` | `true` | Inference gateway |
| `llm-service.enabled` | `false` | In-cluster vLLM (local mode) |
| `api.enabled` | `true` | FastAPI |
| `ingestion.enabled` | `true` | CronJob |

## Publishing a new chart version

1. Bump `version` in `Chart.yaml`.
2. Tag `chart-v<version>` (must match `Chart.yaml`, e.g. `chart-v0.0.1`) or run the **Publish Helm chart** workflow.
3. CI packages the chart and updates GitHub Pages (`index.yaml` + `.tgz`). Older `.tgz` files are kept (`keep_files: true`).

### Dual versions (e.g. 0.2.0 + 0.0.1)

The chart repo can host multiple versions. Clients pin `dependencies.version` explicitly.
`helm install` without `--version` picks the **highest** semver (so `0.2.0` stays “latest” until it is removed).

To publish **0.2.0** then **0.0.1**:

```bash
# From a commit where Chart.yaml is 0.2.0
git tag chart-v0.2.0 && git push origin chart-v0.2.0

# After bumping Chart.yaml to 0.0.1 and committing
git tag chart-v0.0.1 && git push origin chart-v0.0.1
```

### Retiring an old chart version (e.g. remove 0.2.0 after 0.0.1 is validated)

1. Check out the `gh-pages` branch.
2. Delete `general-simulation-0.2.0.tgz`.
3. Regenerate the index (from the repo root, with only remaining `.tgz` files on `gh-pages`):

   ```bash
   helm repo index . --url https://robertsandoval.github.io/general-simulation
   ```

4. Commit and push `gh-pages`.
5. Tell clients on `0.2.0` to bump their parent chart to `0.0.1` and run `helm dependency update`.
