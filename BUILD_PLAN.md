# Cursor Build Plan — Simulation & Impact-Reasoning Platform (MVP)

> **How to use this file with Cursor:** Work through the phases in order. Each phase is a self-contained task with a clear deliverable and a "done when" check. Paste a phase (or a single task) into Cursor's chat/composer and let Claude implement it, then verify against the acceptance check before moving on. Do **not** skip ahead — later phases assume earlier deliverables exist.
>
> **Scope of this MVP:** Llama Stack (unified inference + vector/RAG + tool/agent API) over Postgres (AGE + pgvector + PostGIS) + **one** ingestion path + the three-stage reasoning loop. Domain-agnostic core only — no supply-chain or manufacturing example code yet. The architecture must stay domain-pluggable.
>
> **Where Llama Stack fits (read this first):** Llama Stack is a single API server with a swappable-provider architecture. We use it as the backend for three things: **inference** (`remote::vllm` provider → our vLLM endpoint), **vector/RAG** (`remote::pgvector` provider → our Postgres), and **tools** (our ingestion adapters and solver are registered as Llama Stack tools). What Llama Stack does **not** cover, and what therefore stays our own direct-to-Postgres code: **Apache AGE graph traversal** (Stage 1) and **PostGIS live/geo queries** — there are no Llama Stack providers for these. Live external-feed ingestion (pulling flight/sensor data into PostGIS on a schedule) also stays our own runner; Llama Stack's ingestion is for RAG documents only. Net effect: Llama Stack owns inference + vector + tool/agent orchestration; graph and geo remain ours.

---

## 0. Guardrails & Conventions (read first, applies to every phase)

These are standing rules for the whole project. Treat them as always-on context.

- **Language/runtime:** Python 3.11+. Use `uv` for dependency management.
- **Inference & vector access go through Llama Stack:** All LLM, embedding, and vector/RAG calls go through the **Llama Stack server** via the `llama-stack-client` SDK, pointed at a configurable Llama Stack base URL. Llama Stack in turn is configured with a `remote::vllm` inference provider and a `remote::pgvector` vector provider. Never call vLLM or pgvector directly from app code — go through Llama Stack so providers stay swappable in config, not code. Graph (AGE) and geo (PostGIS) are the exception: they have no Llama Stack provider and are queried directly.
- **Domain-agnostic rule:** Core packages (`ingestion`, `graph`, `reasoning`, `solver`) must contain **no domain-specific entity names** (no `Port`, no `Machine`). Domain specifics live behind interfaces and config only. If you're tempted to write `Port` in core code, stop — it belongs in a domain adapter.
- **Separation of concerns (the central design rule):** Live ground-truth data is **never mutated** by a simulation. Simulations are overlays applied at query time. Keep the "live store" and "simulation/knowledge store" logically distinct even though both live in Postgres.
- **Config:** One typed settings module (e.g., `pydantic-settings`). All connection strings, model names, base URLs come from env. Provide a `.env.example`.
- **Testing:** Every phase ships with at least a smoke test. Use `pytest`. Tests must run without a live LLM (mock the inference client).
- **Containers:** Everything must run on OpenShift eventually — write Containerfiles (not just Dockerfiles), avoid root, use UBI base images where practical, no reliance on `localhost`-only assumptions.
- **Repo layout** to create in Phase 1:
  ```
  /src
    /core            # domain-agnostic abstractions & interfaces
    /ingestion       # ingestion agent framework + one adapter (registered as LS tools)
    /graph           # AGE graph access (Cypher), schema management — direct to Postgres
    /live            # PostGIS live snapshot store — direct to Postgres
    /reasoning       # 3-stage pipeline (traversal -> solver -> synthesis)
    /solver          # pluggable quantitative solver interface + a stub impl
    /llamastack      # Llama Stack client wrapper + run.yaml provider config (inference, vector, tools)
    /api             # FastAPI entrypoint
  /deploy            # Containerfiles, OpenShift manifests, LlamaStackDistribution CR
  /tests
  ```
  Note: there is no `/vector` package — vector/RAG is owned by Llama Stack's pgvector provider and accessed through the `/llamastack` client, not hand-written.

---

## Phase 1 — Project Scaffold & Config

**Goal:** A runnable skeleton with the layout above, settings, and a health-check API.

**Tasks**
1. Initialize the repo with the layout in section 0. Add `pyproject.toml`, `.env.example`, `README.md`.
2. Create a typed `Settings` module loading: Postgres DSN, **Llama Stack base URL**, generation model id, embedding model id, embedding dimension. (vLLM and pgvector URLs are configured inside Llama Stack's `run.yaml`, not here — app code only needs the Llama Stack URL.)
3. Stand up a minimal **FastAPI** app in `/src/api` with a `GET /health` route that checks DB connectivity and returns status.
4. Add `pytest` + a smoke test that imports the app and hits `/health` with a test client (DB mocked).

**Done when:** `pytest` passes and `GET /health` returns 200 with a DB-reachable flag.

---

## Phase 2 — Postgres Foundation (AGE + pgvector + PostGIS)

**Goal:** A single Postgres image/instance with all three extensions, plus schema bootstrap.

**Tasks**
1. Write a **Containerfile** for a custom Postgres image bundling `apache-age`, `pgvector`, and `postgis`. Pin versions. (This is the riskiest setup step — get it building and starting cleanly first.)
2. Add a `docker-compose.yml` (or Podman equivalent) for **local dev only** that runs this Postgres so contributors don't need OpenShift to develop.
3. Write an idempotent **schema bootstrap** script/migration that:
   - `CREATE EXTENSION` for all three.
   - Creates the AGE graph (e.g., `SELECT create_graph('sim_graph')`).
   - Enables the `vector` extension so Llama Stack's pgvector provider can manage its own RAG tables (Llama Stack creates/owns the embedding tables at runtime — do **not** hand-create them here; just guarantee the extension exists).
   - Creates PostGIS-enabled tables for the live snapshot (generic `entity` + `entity_state` tables, no domain columns — use a JSONB `attributes` field).
4. Add a connection/session module shared by `/graph` and `/live` (vector access is via the Llama Stack client, not this module).

**Done when:** The custom image builds, the bootstrap runs idempotently (safe to re-run), and you can open a Cypher query via AGE and an `<->` vector query via pgvector in the same DB.

---

## Phase 3 — Llama Stack Layer (inference + vector providers)

**Goal:** A running Llama Stack server configured against vLLM and pgvector, plus a thin client wrapper the app uses for all inference, embedding, and vector/RAG.

**Tasks**
1. Author a Llama Stack **`run.yaml`** (and matching build config) declaring providers: `inference: remote::vllm` (URL from env, `VLLM_URL`), an embedding model (either the same vLLM or `inline::sentence-transformers`), and `vector_io: remote::pgvector` (pointed at the Phase 2 Postgres). Register the generation and embedding model ids. Keep all URLs/models as env-substituted values so nothing is hardcoded.
2. In `/src/llamastack`, wrap the `llama-stack-client` SDK. Expose the small surface the app needs: `generate(messages, tools=None)`, `embed(texts) -> vectors`, and vector/RAG ops `ingest_documents(...)` and `vector_search(query) -> chunks` (these call Llama Stack's Vector Stores API — the app never touches pgvector SQL directly).
3. Add a `FakeLlamaStackClient` for tests returning canned completions/embeddings/search hits, selectable via config so the whole stack runs without a GPU or a live Llama Stack server.
4. README notes: vLLM must be started with `--enable-auto-tool-choice` (and a tool-call parser) for tool calling to work through Llama Stack; document how to point `run.yaml` at a local vLLM for dev. Flag that the chosen model must support structured tool calling — this remains a key risk.

**Done when:** With a local Llama Stack server (or the fake client), `embed()` returns vectors of the configured dimension, `vector_search()` returns hits from documents ingested via `ingest_documents()`, and `generate()` round-trips a tool-call request/response shape in a test.

---

## Phase 4 — Ingestion Framework + One Adapter

**Goal:** The agent-based ingestion pattern, proven with a single generic source.

**Tasks**
1. In `/src/core`, define an `IngestionAdapter` interface: `fetch() -> raw`, `normalize(raw) -> list[CanonicalEntity]`. Define the **canonical schema** as a domain-agnostic dataclass/pydantic model: `id`, `type`, `geometry` (optional, PostGIS-compatible), `timestamp`, `status`, `attributes: dict`.
2. Build the ingestion runner that: calls an adapter, normalizes, and **upserts into the PostGIS live store** (Phase 2 tables). This writes ground truth only.
3. Implement **one** concrete adapter against a generic, free, no-auth source (e.g., a public REST endpoint returning JSON with timestamps/coordinates — keep it deliberately not domain-specific; treat it as "moving entities with positions and status"). Map it onto the canonical schema.
4. Make the runner invocable two ways: as a CLI/one-shot (for an OpenShift **CronJob**) and as a callable (for on-demand pulls from the reasoning layer). Additionally, **register the on-demand pull as a Llama Stack tool** so the agent can trigger a fresh fetch mid-reasoning (the tool wraps the same callable — don't duplicate logic).
5. Smoke test: run adapter against a recorded fixture (don't hit the network in tests), assert rows land in the live store.

**Done when:** Running the ingestion command populates the live store with canonical entities from the one adapter, and the test passes against a fixture.

---

## Phase 5 — Knowledge Store: Graph + Vector for Simulation Events

**Goal:** Represent the dependency graph and simulation events as overlays.

**Tasks**
1. In `/src/graph`, write helpers to create/query the dependency graph in AGE via Cypher: generic `Entity` nodes and generic dependency edges (e.g., `DEPENDS_ON`, `FEEDS`). No domain labels — node `type` is a property.
2. Define the **SimulationEvent** as a first-class graph node connected by `AFFECTED_BY` edges to the entities it perturbs. Crucially: injecting an event must **not** alter the live store or the base entity nodes — it's additive overlay data, removable in one operation.
3. For the simulation event's **text description**, ingest it into Llama Stack's vector store via the `/src/llamastack` client (`ingest_documents`) tagged with the scenario/event id; retrieve with `vector_search`. Do not write pgvector SQL — Llama Stack owns the embedding/storage/search. (The graph node + edges in step 2 remain direct AGE writes — that's ours.)
4. Provide `inject_event(event)` and `remove_event(event_id)` so scenarios are fully reversible. Support **multiple concurrent events** (multiple what-if scenarios) distinguished by a scenario/event id.
5. Test: inject an event, confirm `AFFECTED_BY` edges exist and the embedded chunk is retrievable; remove it and confirm clean teardown with the base graph intact.

**Done when:** You can inject a simulation event (graph node + edges + embedded text), retrieve it both via Cypher traversal and vector search, and remove it leaving ground truth and base graph untouched.

---

## Phase 6 — Solver Interface + Stub

**Goal:** A pluggable Stage-2 quantitative solver, behind an interface.

**Tasks**
1. In `/src/core`, define a `Solver` interface: `solve(affected_subgraph, event, live_state) -> SolverResult`, where `SolverResult` carries quantified effects and ranked response options (domain-agnostic shapes — numbers + labeled options, no domain semantics).
2. In `/src/solver`, implement a **stub solver** that produces deterministic, explainable placeholder results from the affected subgraph (e.g., counts impacted entities, flags the longest dependency chain). This proves the interface; real OR-Tools logic is a later domain concern.
3. Document in the interface docstring that this slot is where OR-Tools / a discrete-event engine plugs in per domain — nothing else in the pipeline changes when swapped. Also **register `solve()` as a Llama Stack tool** so it's callable from the agent surface (same wrap-don't-duplicate rule as the ingestion tool).
4. Test the stub against a small fixture subgraph.

**Done when:** The reasoning pipeline can call `solve()` and get a structured `SolverResult` from the stub.

---

## Phase 7 — The Three-Stage Reasoning Pipeline

**Goal:** Wire traversal → solver → synthesis into one query-answering loop.

> **Orchestration boundary (important):** Keep our **own thin orchestrator** for the three stages — do **not** hand the whole flow to Llama Stack's agent loop. Stages 1 and 2 are deliberately deterministic and non-LLM; Llama Stack's agent loop is built around LLM-driven tool calling and would fight that design. Our orchestrator calls AGE directly (Stage 1), calls the solver (Stage 2), then uses the Llama Stack client for vector retrieval + `generate()` (Stage 3). Llama Stack is the inference/vector/tool *backend*, not the top-level controller.

**Tasks**
1. In `/src/reasoning`, implement the pipeline (LangGraph or a clear state-machine — keep stages explicit and individually testable):
   - **Stage 1 — Structural (deterministic):** given a query + chosen scenario/event id, run a Cypher traversal (direct AGE, not via Llama Stack) from the event's `AFFECTED_BY` entities across dependency edges to collect the affected subgraph. **No LLM.**
   - **Stage 2 — Quantitative:** pass the affected subgraph + live state into the `Solver`.
   - **Stage 3 — Synthesis:** assemble (affected subgraph + solver result + Llama Stack `vector_search` context) into a prompt and call the Llama Stack client's `generate()` for a grounded, cited explanation. The LLM **explains**, it does not invent impact numbers.
2. Read live state from PostGIS **through the lens of** the active event(s) — never mutate the live store.
3. Expose a `POST /query` API route: body = `{ question, scenario_id }`, returns the synthesized answer plus the structured affected-set and solver numbers (so the answer is explainable/auditable).
4. End-to-end test with the **fake Llama Stack client**: inject a fixture event, hit `/query`, assert the affected set is correct (deterministic), the solver ran, and synthesis was called with the right context.

**Done when:** `POST /query` returns a grounded answer composed of real Stage-1 traversal output, real Stage-2 solver output, and a Stage-3 synthesis — runnable end-to-end with the fake Llama Stack client, no GPU required.

---

## Phase 8 — OpenShift Deployment Manifests

**Goal:** Everything deployable to OpenShift; nothing assumes local-only.

**Tasks**
1. In `/deploy`, write manifests for: the custom Postgres (prefer **CloudNativePG** or **Crunchy Postgres Operator** CR rather than a bare pod), the API Deployment + Service + Route, and a CronJob for the ingestion runner.
2. Add the **Llama Stack deployment**: a `LlamaStackDistribution` CR (via the Llama Stack Operator on OpenShift AI) wired to the vLLM endpoint and the pgvector Postgres, **or** a plain Deployment running the Llama Stack server container with the Phase 3 `run.yaml` mounted. The API talks to Llama Stack via in-cluster Service URL.
3. Add a vLLM serving manifest stub (Deployment with GPU node selector/tolerations **or** a KServe `InferenceService` for OpenShift AI), started with `--enable-auto-tool-choice` so tool calling works through Llama Stack.
4. Externalize all config via ConfigMap/Secret; no secrets in images. Run containers as non-root.
5. Document the deploy order in the README (operator → Postgres → bootstrap job → vLLM → Llama Stack → API → cronjob).

**Done when:** A reviewer can read `/deploy` + README and deploy the full MVP to an OpenShift cluster, with the API talking to Llama Stack, and Llama Stack talking to in-cluster vLLM + pgvector.

---

## Definition of Done (MVP)

- Single Postgres image serves graph (AGE), vector (pgvector, via Llama Stack), and geo/live (PostGIS).
- Llama Stack server fronts inference (vLLM) and vector/RAG (pgvector); the app uses one Llama Stack client and never calls vLLM or pgvector directly.
- Ingestion adapter and solver are registered as Llama Stack tools; graph and geo stay direct-to-Postgres.
- One ingestion adapter populates the live store on a schedule, ground-truth only.
- Simulation events inject/remove as reversible overlays; multiple concurrent scenarios supported.
- `POST /query` runs the three explicit stages (our orchestrator, not Llama Stack's agent loop) and returns an explainable answer.
- The entire stack runs locally with a fake Llama Stack client and deploys to OpenShift with real Llama Stack + vLLM.
- **Zero domain-specific entity names in `/src/core`, `/src/reasoning`, `/src/graph`, `/src/solver`.** Domain adaptation = new ingestion adapter + graph schema config + real solver, nothing else.

---

## What's intentionally NOT in this MVP (later phases)

- Real OR-Tools / discrete-event solver implementations.
- A concrete domain example (supply chain or manufacturing) — added later as adapter + schema + solver, with **no core changes**.
- Multi-source ingestion, auth'd/streaming sources (OPC-UA, MQTT, AIS, flight APIs).
- Time-series scaling (e.g., TimescaleDB) for high-frequency sources.
- Auth, observability, HA tuning.
