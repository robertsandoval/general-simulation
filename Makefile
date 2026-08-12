# =============================================================================
# General Simulation & Impact-Reasoning Platform — Makefile
# =============================================================================
#
# Primary deploy (umbrella = one Helm release):
#   make build
#   make deploy PG_PASSWORD=<pw> NEO4J_PASSWORD=<pw> OPENAI_API_KEY=<key>
#   make deploy LLM_MODE=local PG_PASSWORD=<pw> NEO4J_PASSWORD=<pw> HF_TOKEN=<tok>
#
# LLM_MODE=openai (default) — Llama Stack → OpenAI
# LLM_MODE=local            — Llama Stack → in-cluster vLLM (OpenShift AI)
#
# Other targets: make help
# =============================================================================

# ── Configurable variables ────────────────────────────────────────────────────
REGISTRY         ?= quay.io/rh-ai-quickstart
NAMESPACE        ?= general-simulation
TAG              ?= latest
PG_PASSWORD      ?=
NEO4J_PASSWORD   ?=
OPENAI_API_KEY   ?=
HF_TOKEN         ?=
LLM_MODE         ?= openai
CHART_REPO_URL   ?= https://robertsandoval.github.io/general-simulation
LLM_SERVICE_CHART_REPO ?= https://rh-ai-quickstart.github.io/ai-architecture-charts
LLM_SERVICE_VERSION    ?= 0.5.9
LLAMA_STACK_VERSION    ?= 0.8.5

# ── Derived image references ──────────────────────────────────────────────────
IMG_POSTGRES := $(REGISTRY)/general-sim-postgres:$(TAG)
IMG_APP      := $(REGISTRY)/general-simulation-api:$(TAG)

# ── Helm chart paths ──────────────────────────────────────────────────────────
CHART_POSTGRES  := deploy/helm/postgres
CHART_NEO4J     := deploy/helm/neo4j
CHART_BOOTSTRAP := deploy/helm/bootstrap
CHART_API       := deploy/helm/api
CHART_INGESTION := deploy/helm/ingestion
CHART_UMBRELLA  := deploy/helm/general-simulation
LLM_SERVICE_VALUES := deploy/helm/llm-service-values.yaml

# Common flags passed to every helm command
HELM_COMMON := --namespace $(NAMESPACE) --create-namespace

# Stack model ids (providerKey/model.id)
GEN_MODEL_OPENAI := openai/gpt-4o-mini
# Must match global.models / llm-service.models key + id from values.yaml
LOCAL_MODEL_KEY  ?= deepseek-r1-distill-qwen-1-5b
LOCAL_MODEL_ID   ?= deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B
GEN_MODEL_LOCAL  := $(LOCAL_MODEL_KEY)/$(LOCAL_MODEL_ID)

# ── Phony declarations ────────────────────────────────────────────────────────
.PHONY: all help \
        build build-postgres build-app \
        deploy deploy-umbrella \
        deploy-postgres deploy-neo4j deploy-bootstrap deploy-llm-service \
        deploy-api deploy-ingestion neo4j-connect \
        package-chart \
        undeploy status lint-charts \
        _guard-pg-password _guard-neo4j-password _guard-llm-mode \
        _guard-oc _guard-helm _guard-podman

# ── Default target ────────────────────────────────────────────────────────────
all: help

# ── Help ──────────────────────────────────────────────────────────────────────
help:
	@printf "\nGeneral Simulation Platform — available targets:\n"
	@printf "  %-40s %s\n" "build" "Build and push all container images"
	@printf "  %-40s %s\n" "deploy PG_PASSWORD=… NEO4J_PASSWORD=…" "Umbrella install (LLM_MODE=openai|local)"
	@printf "  %-40s %s\n" "  LLM_MODE=openai OPENAI_API_KEY=…" "  Stack → OpenAI (default)"
	@printf "  %-40s %s\n" "  LLM_MODE=local HF_TOKEN=…" "  Stack → in-cluster vLLM (OpenShift AI)"
	@printf "  %-40s %s\n" "deploy-postgres / deploy-neo4j / …" "Advanced per-component installs"
	@printf "  %-40s %s\n" "neo4j-connect" "Port-forward Neo4j Browser + Bolt"
	@printf "  %-40s %s\n" "package-chart" "Package umbrella chart into dist/"
	@printf "  %-40s %s\n" "undeploy" "Uninstall Helm releases"
	@printf "  %-40s %s\n" "status" "helm list + oc get pods"
	@printf "  %-40s %s\n" "lint-charts" "helm lint"
	@printf "\nVariables:\n"
	@printf "  %-18s %s\n" "LLM_MODE"         "$(LLM_MODE)  (openai | local)"
	@printf "  %-18s %s\n" "REGISTRY"         "$(REGISTRY)"
	@printf "  %-18s %s\n" "NAMESPACE"        "$(NAMESPACE)"
	@printf "  %-18s %s\n" "TAG"              "$(TAG)"
	@printf "  %-18s %s\n" "PG_PASSWORD"      "(required)"
	@printf "  %-18s %s\n" "NEO4J_PASSWORD"   "(required)"
	@printf "  %-18s %s\n" "OPENAI_API_KEY"   "(required when LLM_MODE=openai)"
	@printf "  %-18s %s\n" "HF_TOKEN"         "(required when LLM_MODE=local)"
	@printf "\n"

# ── Guards ────────────────────────────────────────────────────────────────────
_guard-pg-password:
	@test -n "$(PG_PASSWORD)" || \
	  { printf "ERROR: PG_PASSWORD is required.\n"; exit 1; }

_guard-neo4j-password:
	@test -n "$(NEO4J_PASSWORD)" || \
	  { printf "ERROR: NEO4J_PASSWORD is required.\n"; exit 1; }

_guard-llm-mode:
	@case "$(LLM_MODE)" in \
	  openai) \
	    test -n "$(OPENAI_API_KEY)" || \
	      { printf "ERROR: OPENAI_API_KEY is required for LLM_MODE=openai.\n"; exit 1; } ;; \
	  local) \
	    test -n "$(HF_TOKEN)" || \
	      { printf "ERROR: HF_TOKEN is required for LLM_MODE=local.\n"; exit 1; } ;; \
	  *) \
	    printf "ERROR: LLM_MODE must be 'openai' or 'local' (got '$(LLM_MODE)').\n"; exit 1 ;; \
	esac

_guard-oc:
	@command -v oc >/dev/null 2>&1 || \
	  { echo "ERROR: 'oc' CLI not found. Install the OpenShift CLI and run 'oc login'."; exit 1; }

_guard-helm:
	@command -v helm >/dev/null 2>&1 || \
	  { echo "ERROR: 'helm' CLI not found. Install Helm 3+ from https://helm.sh/docs/intro/install/"; exit 1; }

_guard-podman:
	@command -v podman >/dev/null 2>&1 || \
	  { echo "ERROR: 'podman' not found. Install Podman or substitute 'docker' by setting PODMAN=docker."; exit 1; }

# ── Container image builds ────────────────────────────────────────────────────
build: _guard-podman build-postgres build-app
	@echo "==> All images built and pushed to $(REGISTRY)."

build-postgres: _guard-podman
	@echo "==> Building Postgres image: $(IMG_POSTGRES)"
	podman build \
	  --platform=linux/amd64 \
	  -f deploy/postgres/Containerfile \
	  -t $(IMG_POSTGRES) \
	  deploy/postgres
	podman push $(IMG_POSTGRES)

build-app: _guard-podman
	@echo "==> Building FastAPI app image: $(IMG_APP)"
	podman build \
	  --platform=linux/amd64 \
	  -f deploy/app/Containerfile \
	  -t $(IMG_APP) \
	  .
	podman push $(IMG_APP)

# ── Namespace bootstrap ───────────────────────────────────────────────────────
_deploy-namespace: _guard-oc
	oc apply -f deploy/openshift/namespace.yaml

# ── Primary deploy (umbrella) ─────────────────────────────────────────────────

## One-command install: Postgres + Neo4j + bootstrap + Llama Stack + API + ingestion
## (+ llm-service when LLM_MODE=local).
deploy: deploy-umbrella

deploy-umbrella: _guard-pg-password _guard-neo4j-password _guard-llm-mode \
                 _guard-oc _guard-helm _deploy-namespace
	@echo "==> Creating neo4j-sa + anyuid SCC binding..."
	oc apply -f deploy/openshift/neo4j/serviceaccount.yaml -n $(NAMESPACE)
	@sed "s/__NAMESPACE__/$(NAMESPACE)/g" deploy/openshift/neo4j/scc-binding.yaml | oc apply -f -
	@echo "==> Creating neo4j-auth secret..."
	@oc delete secret neo4j-auth -n $(NAMESPACE) --ignore-not-found >/dev/null
	@oc create secret generic neo4j-auth \
	  --from-literal=NEO4J_AUTH="neo4j/$(NEO4J_PASSWORD)" \
	  -n $(NAMESPACE)
	@echo "==> Updating umbrella chart dependencies..."
	helm repo add neo4j https://helm.neo4j.com/neo4j 2>/dev/null || true
	helm repo update neo4j
	helm repo add ai-architecture-charts $(LLM_SERVICE_CHART_REPO) 2>/dev/null || true
	helm repo update ai-architecture-charts
	helm dependency update $(CHART_UMBRELLA)
	@echo "==> Deploying umbrella (LLM_MODE=$(LLM_MODE))..."
	@if [ "$(LLM_MODE)" = "local" ]; then \
	  helm upgrade --install general-simulation $(CHART_UMBRELLA) \
	    $(HELM_COMMON) \
	    --set postgres.image=$(IMG_POSTGRES) \
	    --set api.image=$(IMG_APP) \
	    --set bootstrap.image=$(IMG_APP) \
	    --set ingestion.image=$(IMG_APP) \
	    --set-string postgres.postgres.password='$(PG_PASSWORD)' \
	    --set-string api.postgres.password='$(PG_PASSWORD)' \
	    --set-string api.neo4j.password='$(NEO4J_PASSWORD)' \
	    --set-string bootstrap.postgres.password='$(PG_PASSWORD)' \
	    --set-string bootstrap.neo4j.password='$(NEO4J_PASSWORD)' \
	    --set-string ingestion.postgres.password='$(PG_PASSWORD)' \
	    --set-string ingestion.neo4j.password='$(NEO4J_PASSWORD)' \
	    --set global.models.openai.enabled=false \
	    --set global.models.$(LOCAL_MODEL_KEY).enabled=true \
	    --set-string global.models.$(LOCAL_MODEL_KEY).id='$(LOCAL_MODEL_ID)' \
	    --set llm-service.enabled=true \
	    --set llm-service.models.$(LOCAL_MODEL_KEY).enabled=true \
	    --set-string llm-service.models.$(LOCAL_MODEL_KEY).id='$(LOCAL_MODEL_ID)' \
	    --set-string llm-service.secret.hf_token='$(HF_TOKEN)' \
	    --set-string api.models.generation='$(GEN_MODEL_LOCAL)' \
	    --set-string ingestion.models.generation='$(GEN_MODEL_LOCAL)' \
	    --set-string api.llm.apiKey=unused \
	    --set-string ingestion.llm.apiKey=unused \
	    --wait --timeout 25m ; \
	else \
	  helm upgrade --install general-simulation $(CHART_UMBRELLA) \
	    $(HELM_COMMON) \
	    --set postgres.image=$(IMG_POSTGRES) \
	    --set api.image=$(IMG_APP) \
	    --set bootstrap.image=$(IMG_APP) \
	    --set ingestion.image=$(IMG_APP) \
	    --set-string postgres.postgres.password='$(PG_PASSWORD)' \
	    --set-string api.postgres.password='$(PG_PASSWORD)' \
	    --set-string api.neo4j.password='$(NEO4J_PASSWORD)' \
	    --set-string bootstrap.postgres.password='$(PG_PASSWORD)' \
	    --set-string bootstrap.neo4j.password='$(NEO4J_PASSWORD)' \
	    --set-string ingestion.postgres.password='$(PG_PASSWORD)' \
	    --set-string ingestion.neo4j.password='$(NEO4J_PASSWORD)' \
	    --set global.models.openai.enabled=true \
	    --set global.models.$(LOCAL_MODEL_KEY).enabled=false \
	    --set-string global.models.openai.apiToken='$(OPENAI_API_KEY)' \
	    --set llm-service.enabled=false \
	    --set-string api.models.generation='$(GEN_MODEL_OPENAI)' \
	    --set-string ingestion.models.generation='$(GEN_MODEL_OPENAI)' \
	    --set-string api.llm.apiKey=unused \
	    --set-string ingestion.llm.apiKey=unused \
	    --wait --timeout 15m ; \
	fi
	@printf "\n==> Deployment complete (LLM_MODE=$(LLM_MODE)).\n"
	@printf "    API (same-NS):  http://general-sim-api:8000\n"
	@printf "    Llama Stack:    http://llamastack:8321/v1\n"
	@printf "    Smoke test:\n"
	@printf "      ROUTE=\$$(oc get route general-sim-api -n $(NAMESPACE)"
	@printf " -o jsonpath='{.spec.host}')\n"
	@printf "      curl -s https://\$$ROUTE/health | jq .\n"
	@printf "    Neo4j Browser: make neo4j-connect NAMESPACE=$(NAMESPACE)\n\n"

# ── Advanced: per-component targets ───────────────────────────────────────────

deploy-postgres: _guard-pg-password _guard-oc _guard-helm _deploy-namespace
	@echo "==> Deploying Postgres..."
	helm upgrade --install postgres $(CHART_POSTGRES) \
	  $(HELM_COMMON) \
	  --set image=$(IMG_POSTGRES) \
	  --set postgres.password=$(PG_PASSWORD) \
	  --wait --timeout 5m
	@echo "    Postgres ready."

deploy-neo4j: _guard-neo4j-password _guard-oc _guard-helm _deploy-namespace
	@echo "==> Creating neo4j-sa + anyuid SCC binding..."
	oc apply -f deploy/openshift/neo4j/serviceaccount.yaml -n $(NAMESPACE)
	@sed "s/__NAMESPACE__/$(NAMESPACE)/g" deploy/openshift/neo4j/scc-binding.yaml | oc apply -f -
	@echo "==> Adding/updating Neo4j Helm repo..."
	helm repo add neo4j https://helm.neo4j.com/neo4j 2>/dev/null || true
	helm repo update neo4j
	$(eval OCP_DOMAIN   := $(shell oc get ingresses.config/cluster -o jsonpath='{.spec.domain}' 2>/dev/null))
	$(eval NEO4J_ROUTE_HOST := neo4j-$(NAMESPACE).$(OCP_DOMAIN))
	@echo "==> Creating neo4j-auth secret..."
	@oc delete secret neo4j-auth -n $(NAMESPACE) --ignore-not-found >/dev/null
	@oc create secret generic neo4j-auth \
	  --from-literal=NEO4J_AUTH="neo4j/$(NEO4J_PASSWORD)" \
	  -n $(NAMESPACE)
	helm upgrade --install neo4j neo4j/neo4j \
	  --version 2026.5.0 \
	  $(HELM_COMMON) \
	  -f $(CHART_NEO4J)/values.yaml \
	  --set "config.server\.default_advertised_address=$(NEO4J_ROUTE_HOST)" \
	  --wait --timeout 10m
	@oc create route edge neo4j \
	  --service=neo4j --port=tcp-http \
	  --insecure-policy=Redirect \
	  -n $(NAMESPACE) 2>/dev/null || true
	@printf "\n    Neo4j deployed. Browser: https://$(NEO4J_ROUTE_HOST)/browser/\n\n"

neo4j-connect: _guard-oc
	@printf "\n==> Starting Neo4j port-forward (ctrl-c to stop)...\n"
	@printf "    Browser UI: http://localhost:7474/browser/\n"
	@printf "    Connect with: bolt://localhost:7687\n"
	@printf "    Username: neo4j\n\n"
	oc port-forward svc/neo4j 7474:7474 7687:7687 -n $(NAMESPACE)

deploy-bootstrap: _guard-pg-password _guard-neo4j-password _guard-helm
	helm upgrade --install bootstrap $(CHART_BOOTSTRAP) \
	  $(HELM_COMMON) \
	  --set image=$(IMG_APP) \
	  --set-string postgres.password='$(PG_PASSWORD)' \
	  --set-string neo4j.password='$(NEO4J_PASSWORD)' \
	  --atomic --timeout 3m
	@echo "    Bootstrap complete."

deploy-llm-service: _guard-helm _guard-oc _deploy-namespace
	@test -n "$(HF_TOKEN)" || \
	  { printf "ERROR: HF_TOKEN is required.\n"; exit 1; }
	@echo "==> Deploying llm-service only (prefer: make deploy LLM_MODE=local)..."
	helm repo add ai-architecture-charts $(LLM_SERVICE_CHART_REPO) 2>/dev/null || true
	helm repo update ai-architecture-charts
	helm upgrade --install llm-service ai-architecture-charts/llm-service \
	  --version $(LLM_SERVICE_VERSION) \
	  $(HELM_COMMON) \
	  -f $(LLM_SERVICE_VALUES) \
	  --set-string secret.hf_token='$(HF_TOKEN)' \
	  --wait --timeout 20m
	@printf "    Service: http://llama-3-2-3b-instruct-vllm/v1\n"
	@printf "    Wire Llama Stack to that URL (umbrella LLM_MODE=local does this).\n\n"

deploy-api: _guard-pg-password _guard-neo4j-password _guard-helm
	helm upgrade --install api $(CHART_API) \
	  $(HELM_COMMON) \
	  --set image=$(IMG_APP) \
	  --set-string postgres.password='$(PG_PASSWORD)' \
	  --set-string neo4j.password='$(NEO4J_PASSWORD)' \
	  --set-string llm.apiKey='$(OPENAI_API_KEY)' \
	  --wait --timeout 3m
	@oc get route general-sim-api -n $(NAMESPACE) \
	  -o jsonpath='    https://{.spec.host}/health{"\n"}' 2>/dev/null || true

deploy-ingestion: _guard-pg-password _guard-neo4j-password _guard-helm
	helm upgrade --install ingestion $(CHART_INGESTION) \
	  $(HELM_COMMON) \
	  --set image=$(IMG_APP) \
	  --set-string postgres.password='$(PG_PASSWORD)' \
	  --set-string neo4j.password='$(NEO4J_PASSWORD)' \
	  --set-string llm.apiKey='$(OPENAI_API_KEY)' \
	  --wait --timeout 2m
	@echo "    Ingestion CronJob configured."

# ── Package / undeploy / status / lint ────────────────────────────────────────

package-chart: _guard-helm
	@echo "==> Packaging $(CHART_UMBRELLA) ..."
	helm repo add neo4j https://helm.neo4j.com/neo4j 2>/dev/null || true
	helm repo update neo4j
	helm repo add ai-architecture-charts $(LLM_SERVICE_CHART_REPO) 2>/dev/null || true
	helm repo update ai-architecture-charts
	helm dependency update $(CHART_UMBRELLA)
	helm lint $(CHART_UMBRELLA)
	mkdir -p dist
	helm package $(CHART_UMBRELLA) -d dist/
	@echo "==> Packaged charts in dist/. Publish URL: $(CHART_REPO_URL)"

undeploy: _guard-helm
	@echo "==> Removing Helm releases from namespace $(NAMESPACE)..."
	helm uninstall general-simulation --namespace $(NAMESPACE) 2>/dev/null || true
	helm uninstall ingestion --namespace $(NAMESPACE) 2>/dev/null || true
	helm uninstall api       --namespace $(NAMESPACE) 2>/dev/null || true
	helm uninstall llm-service --namespace $(NAMESPACE) 2>/dev/null || true
	helm uninstall vllm      --namespace $(NAMESPACE) 2>/dev/null || true
	helm uninstall bootstrap --namespace $(NAMESPACE) 2>/dev/null || true
	helm uninstall neo4j     --namespace $(NAMESPACE) 2>/dev/null || true
	helm uninstall postgres  --namespace $(NAMESPACE) 2>/dev/null || true
	@oc delete clusterrolebinding $(NAMESPACE)-neo4j-anyuid --ignore-not-found >/dev/null
	@oc delete serviceaccount neo4j-sa -n $(NAMESPACE) --ignore-not-found >/dev/null
	@oc delete secret pgvector -n $(NAMESPACE) --ignore-not-found >/dev/null
	@echo "    Done. PVCs are NOT deleted automatically — remove manually if needed:"
	@echo "      oc delete pvc -n $(NAMESPACE) --all"

status: _guard-helm _guard-oc
	@echo "==> Helm releases in namespace $(NAMESPACE):"
	@helm list --namespace $(NAMESPACE)
	@echo ""
	@echo "==> Pod status:"
	@oc get pods -n $(NAMESPACE)

lint-charts: _guard-helm
	@for chart in \
	  $(CHART_POSTGRES) \
	  $(CHART_BOOTSTRAP) \
	  $(CHART_API) \
	  $(CHART_INGESTION); do \
	  printf "==> Linting $$chart ...\n"; \
	  helm lint "$$chart" || exit 1; \
	done
	@echo "==> Updating and linting umbrella chart..."
	helm repo add neo4j https://helm.neo4j.com/neo4j 2>/dev/null || true
	helm repo update neo4j
	helm repo add ai-architecture-charts $(LLM_SERVICE_CHART_REPO) 2>/dev/null || true
	helm repo update ai-architecture-charts
	helm dependency update $(CHART_UMBRELLA)
	helm lint $(CHART_UMBRELLA)
	@echo "==> All charts passed lint."
