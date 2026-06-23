# General Simulation & Impact-Reasoning Platform (MVP)

A **domain-agnostic** simulation and impact-reasoning platform built on:

| Concern | Technology |
|---|---|
| Inference & embeddings | [Llama Stack](https://github.com/meta-llama/llama-stack) → vLLM (`remote::vllm`) |
| Vector / RAG | Llama Stack → pgvector (`remote::pgvector`) |
| Dependency graph | Apache AGE (Cypher), queried directly |
| Live / geo snapshot | PostGIS, queried directly |
| API | FastAPI |
| Dependency management | [uv](https://docs.astral.sh/uv/) |

> **Core design rule:** Live ground-truth data is **never mutated** by a simulation.
> Simulations are overlays applied at query time.

---

## Repository layout

```
src/
  core/        # Domain-agnostic abstractions, interfaces, and Settings
  ingestion/   # Ingestion agent framework + adapters (registered as Llama Stack tools)
  graph/       # AGE graph access (Cypher) — direct to Postgres
  live/        # PostGIS live snapshot store — direct to Postgres
  reasoning/   # 3-stage pipeline: traversal → solver → synthesis
  solver/      # Pluggable quantitative solver interface + stub impl
  llamastack/  # Llama Stack client wrapper + run.yaml provider config
  api/         # FastAPI entrypoint
deploy/        # Containerfiles, OpenShift manifests, LlamaStackDistribution CR
tests/
```

---

## Quickstart (local dev)

### 1. Install dependencies

```bash
uv sync --all-extras
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your Postgres DSN and Llama Stack base URL
```

### 3. Run the API

```bash
uv run python -m src.api.main
# or:
uv run uvicorn src.api.app:app --reload
```

Visit `http://localhost:8000/health` — returns `{"status": "ok", "db": "reachable"}` when
Postgres is available.

### 4. Run tests (no GPU or live Llama Stack required)

```bash
uv run pytest
```

---

## Running without hardware (CI / dev laptops)

Set `USE_FAKE_LLAMA_STACK=true` in `.env` (or the environment).  This swaps in
`FakeLlamaStackClient` which returns canned completions, embeddings, and vector
search hits, so the full reasoning pipeline can be exercised in tests without a
GPU or a running Llama Stack server.

---

## Architecture notes

### Llama Stack boundary

Llama Stack fronts **inference** and **vector/RAG**.  App code calls only the
Llama Stack client (`src/llamastack`) and never calls vLLM or pgvector SQL
directly.  Llama Stack providers (vLLM URL, pgvector DSN) are configured in
`deploy/llamastack/run.yaml`, not in app config.

### Graph and geo are ours

Apache AGE (graph traversal) and PostGIS (live/geo queries) have no Llama Stack
providers.  The `src/graph` and `src/live` packages query Postgres directly via
the shared `POSTGRES_DSN`.

### Three-stage reasoning pipeline (our orchestrator, not Llama Stack's agent loop)

1. **Stage 1 — Structural (deterministic):** Cypher traversal via AGE to collect
   the affected subgraph.  No LLM.
2. **Stage 2 — Quantitative:** pluggable `Solver` producing impact numbers.
3. **Stage 3 — Synthesis:** LLM (`generate()` via Llama Stack) explains, grounded
   by vector context (`vector_search()` via Llama Stack).  The LLM explains — it
   does not invent impact numbers.

### Domain-agnostic core

`/src/core`, `/src/reasoning`, `/src/graph`, `/src/solver` contain **zero
domain-specific entity names**.  A new domain = a new ingestion adapter + graph
schema config + real solver.  Core code does not change.

---

## Llama Stack — setup notes

### vLLM tool-calling requirement

vLLM **must** be started with `--enable-auto-tool-choice` and a matching
`--tool-call-parser` for structured tool calls to work through Llama Stack:

```bash
vllm serve meta-llama/Llama-3.1-8B-Instruct \
    --enable-auto-tool-choice \
    --tool-call-parser hermes   # or: llama3_json, mistral, internlm2
```

The correct parser depends on the model family.  Without this flag, tool calls
will fail silently or produce plain-text invocations that Llama Stack cannot
parse.

> **Key risk:** the generation model must support *structured* tool calling with
> a JSON schema.  Llama-3 8B/70B Instruct, Mistral Instruct v0.3+, and Hermes
> variants are known to work.  Base (non-Instruct) models and many fine-tunes
> do **not**.

### Pointing run.yaml at a local vLLM for dev

1. Start vLLM locally (with the flags above).
2. Set `VLLM_URL=http://localhost:8080` and `PGVECTOR_*` vars matching your
   compose Postgres.
3. Run the Llama Stack server:

```bash
llama stack build --config deploy/llamastack/build.yaml
llama stack run deploy/llamastack/run.yaml
```

The app's `LLAMA_STACK_BASE_URL` should point at this server (default
`http://localhost:8321`).

### Using the fake client (no GPU, no Llama Stack server)

Set `USE_FAKE_LLAMA_STACK=true` in `.env`.  `FakeLlamaStackClient` provides:
- Deterministic embeddings (hash-seeded unit vectors, correct dimension)
- In-memory vector store (ingest then search, cosine similarity)
- Canned generation responses (configurable tool-call shape for pipeline tests)

---

## OpenShift Deployment

All manifests live under `deploy/openshift/`.  Follow the steps below in order;
each step must succeed before the next one starts.

### Prerequisites

| Requirement | Notes |
|---|---|
| OpenShift 4.13+ | Tested against OCP 4.14/4.15 |
| `oc` CLI logged in | `oc login ...` with cluster-admin or a role that can create all resource types below |
| GPU nodes | Required for vLLM only; CPU nodes sufficient for everything else |
| NVIDIA GPU Operator | Install via OperatorHub if using the plain vLLM Deployment |
| CloudNativePG operator | See step 2 |
| (Optional) Red Hat OpenShift AI | Required only for the KServe `InferenceService` vLLM path |
| Podman / Docker | To build and push images |

---

### Step 1 — Create the namespace

```bash
oc apply -f deploy/openshift/namespace.yaml
oc project general-sim
```

---

### Step 2 — Install the CloudNativePG operator

```bash
# Install CNPG cluster-wide (requires cluster-admin)
oc apply -f https://raw.githubusercontent.com/cloudnative-pg/cloudnative-pg/release-1.24/releases/cnpg-1.24.0.yaml

# Wait for the operator to be ready
oc rollout status deployment/cnpg-controller-manager -n cnpg-system --timeout=120s
```

---

### Step 3 — Apply secrets and ConfigMaps

> **Important:** Replace every `REPLACE_ME` value in `shared/secrets.yaml`
> before applying.  Never commit real secrets.

```bash
# Edit secrets first
vi deploy/openshift/shared/secrets.yaml

oc apply -f deploy/openshift/shared/secrets.yaml
oc apply -f deploy/openshift/shared/configmaps.yaml
```

---

### Step 4 — Build and push images

#### Custom Postgres (CloudNativePG-compatible)

```bash
# Log in to the internal registry
oc registry login

podman build \
  -f deploy/postgres/Containerfile.cnpg \
  -t image-registry.openshift-image-registry.svc:5000/general-sim/general-sim-postgres:latest \
  deploy/postgres

podman push \
  image-registry.openshift-image-registry.svc:5000/general-sim/general-sim-postgres:latest
```

#### FastAPI application

```bash
podman build \
  -f deploy/app/Containerfile \
  -t image-registry.openshift-image-registry.svc:5000/general-sim/general-sim-app:latest \
  .

podman push \
  image-registry.openshift-image-registry.svc:5000/general-sim/general-sim-app:latest
```

#### Llama Stack distribution

```bash
# Build the Llama Stack distribution image from the provider config
llama stack build --config deploy/llamastack/build.yaml

podman tag distribution-general-sim:dev \
  image-registry.openshift-image-registry.svc:5000/general-sim/llamastack-general-sim:latest

podman push \
  image-registry.openshift-image-registry.svc:5000/general-sim/llamastack-general-sim:latest
```

---

### Step 5 — Deploy Postgres

```bash
oc apply -f deploy/openshift/postgres/cluster.yaml

# Wait until the primary instance is ready (can take 2-3 minutes on first run
# because the custom image compiles AGE and pgvector)
oc wait cluster/general-sim-postgres \
  -n general-sim \
  --for=condition=Ready \
  --timeout=300s
```

---

### Step 6 — Run the schema bootstrap Job

```bash
oc apply -f deploy/openshift/bootstrap/job.yaml

oc wait job/general-sim-bootstrap \
  -n general-sim \
  --for=condition=complete \
  --timeout=120s

# Inspect logs if the Job fails
oc logs job/general-sim-bootstrap -n general-sim
```

---

### Step 7 — Deploy vLLM

**Option A — Plain Deployment** (works on any GPU-enabled OpenShift):

```bash
# Edit deployment.yaml to set the correct model path on the PVC
oc apply -f deploy/openshift/vllm/deployment.yaml

oc rollout status deployment/vllm -n general-sim --timeout=300s
```

**Option B — KServe InferenceService** (requires OpenShift AI / RHOAI):

```bash
# Edit inferenceservice.yaml to set storageUri and confirm the ServingRuntime name
oc apply -f deploy/openshift/vllm/inferenceservice.yaml
```

Verify vLLM is serving before proceeding:

```bash
oc exec -n general-sim deployment/vllm -- \
  curl -s http://localhost:8080/health
```

> **Reminder:** vLLM must be started with `--enable-auto-tool-choice` and
> `--tool-call-parser=llama3_json` (or the appropriate parser for your model).
> Tool calling through Llama Stack will silently fail without these flags.

---

### Step 8 — Deploy Llama Stack

```bash
oc apply -f deploy/openshift/llamastack/deployment.yaml

oc rollout status deployment/llamastack -n general-sim --timeout=120s

# Confirm the server started and connected to vLLM + pgvector
oc logs deployment/llamastack -n general-sim | tail -20
```

---

### Step 9 — Deploy the API

```bash
oc apply -f deploy/openshift/api/deployment.yaml
oc apply -f deploy/openshift/api/service.yaml
oc apply -f deploy/openshift/api/route.yaml

oc rollout status deployment/general-sim-api -n general-sim --timeout=60s

# Get the external Route URL
oc get route general-sim-api -n general-sim -o jsonpath='{.spec.host}'
```

Smoke test:

```bash
ROUTE=$(oc get route general-sim-api -n general-sim -o jsonpath='{.spec.host}')
curl -s https://$ROUTE/health | jq .
# Expected: {"status": "ok", "db": "reachable"}
```

---

### Step 10 — Create the ingestion CronJob

```bash
oc apply -f deploy/openshift/ingestion/cronjob.yaml

# Trigger a manual run immediately to verify
oc create job general-sim-ingestion-manual \
  --from=cronjob/general-sim-ingestion \
  -n general-sim

oc wait job/general-sim-ingestion-manual \
  -n general-sim \
  --for=condition=complete \
  --timeout=120s
```

---

### Deploy order summary

```
Step 1  namespace.yaml
Step 2  Install CloudNativePG operator
Step 3  shared/secrets.yaml + shared/configmaps.yaml
Step 4  Build & push: general-sim-postgres, general-sim-app, llamastack-general-sim
Step 5  postgres/cluster.yaml  →  wait Ready
Step 6  bootstrap/job.yaml     →  wait complete
Step 7  vllm/deployment.yaml (or vllm/inferenceservice.yaml)  →  verify /health
Step 8  llamastack/deployment.yaml  →  verify logs
Step 9  api/deployment.yaml + api/service.yaml + api/route.yaml  →  smoke-test /health
Step 10 ingestion/cronjob.yaml  →  trigger manual run
```

### In-cluster service FQDNs

| Service | URL |
|---|---|
| Postgres primary (R/W) | `general-sim-postgres-rw.general-sim.svc:5432` |
| vLLM | `http://vllm.general-sim.svc:8080` |
| Llama Stack | `http://llamastack.general-sim.svc:8321` |
| API | `http://general-sim-api.general-sim.svc:8000` |

---

See `deploy/openshift/` for the full manifest set and `deploy/app/Containerfile` /
`deploy/postgres/Containerfile.cnpg` for the container build instructions.
# general-simulation
