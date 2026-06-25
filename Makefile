# =============================================================================
# General Simulation & Impact-Reasoning Platform — Makefile
# =============================================================================
#
# Usage:
#   make build                    Build and push all container images
#   make deploy PG_PASSWORD=<pw>  Deploy all components to OpenShift in order
#   make undeploy                 Uninstall all Helm releases
#   make status                   Show Helm release + Pod status
#   make lint-charts              Lint all Helm charts
#
# Individual component targets:
#   make build-postgres           Build and push the custom Postgres image
#   make build-app                Build and push the FastAPI app image
#   make build-llamastack         Build and push the Llama Stack image
#   make deploy-postgres PG_PASSWORD=<pw>
#   make deploy-bootstrap PG_PASSWORD=<pw>
#   make deploy-vllm
#   make deploy-llamastack PG_PASSWORD=<pw>
#   make deploy-api PG_PASSWORD=<pw>
#   make deploy-ingestion PG_PASSWORD=<pw>
#
# Variable overrides (pass on the command line):
#   REGISTRY    Image registry root  (default: quay.io/robertsandoval)
#   NAMESPACE   OpenShift namespace  (default: general-sim)
#   TAG         Image tag            (default: latest)
#   PG_PASSWORD Postgres password    (no default — required for deploy targets)
#
# Example:
#   make deploy PG_PASSWORD=s3cr3t
#   make build TAG=v1.2.3
# =============================================================================

# ── Configurable variables ────────────────────────────────────────────────────
REGISTRY    ?= quay.io/robertsandoval
NAMESPACE   ?= general-sim
TAG         ?= latest
PG_PASSWORD ?=

# ── Derived image references ──────────────────────────────────────────────────
IMG_POSTGRES := $(REGISTRY)/general-sim-postgres:$(TAG)
IMG_APP      := $(REGISTRY)/general-sim-app:$(TAG)
IMG_LLAMA    := $(REGISTRY)/llamastack-general-sim:$(TAG)
IMG_VLLM     := docker.io/vllm/vllm-openai:v0.6.3

# ── Helm chart paths ──────────────────────────────────────────────────────────
CHART_POSTGRES    := deploy/helm/postgres
CHART_BOOTSTRAP   := deploy/helm/bootstrap
CHART_VLLM        := deploy/helm/vllm
CHART_LLAMASTACK  := deploy/helm/llamastack
CHART_API         := deploy/helm/api
CHART_INGESTION   := deploy/helm/ingestion

# Common flags passed to every helm command
HELM_COMMON := --namespace $(NAMESPACE) --create-namespace

# ── Phony declarations ────────────────────────────────────────────────────────
.PHONY: all help \
        build build-postgres build-app build-llamastack \
        deploy deploy-postgres deploy-bootstrap deploy-vllm \
        deploy-llamastack deploy-api deploy-ingestion \
        undeploy status lint-charts \
        _guard-pg-password _guard-oc _guard-helm _guard-podman

# ── Default target ────────────────────────────────────────────────────────────
all: help

# ── Help ──────────────────────────────────────────────────────────────────────
help:
	@printf "\nGeneral Simulation Platform — available targets:\n"
	@printf "  %-28s %s\n" "build"                  "Build and push all container images"
	@printf "  %-28s %s\n" "build-postgres"          "Build and push Postgres image"
	@printf "  %-28s %s\n" "build-app"               "Build and push FastAPI app image"
	@printf "  %-28s %s\n" "build-llamastack"        "Build and push Llama Stack image"
	@printf "  %-28s %s\n" "deploy PG_PASSWORD=<pw>" "Deploy all components in order"
	@printf "  %-28s %s\n" "deploy-postgres"         "Deploy only Postgres"
	@printf "  %-28s %s\n" "deploy-bootstrap"        "Deploy only schema bootstrap Job"
	@printf "  %-28s %s\n" "deploy-vllm"             "Deploy only vLLM"
	@printf "  %-28s %s\n" "deploy-llamastack"       "Deploy only Llama Stack"
	@printf "  %-28s %s\n" "deploy-api"              "Deploy only FastAPI app"
	@printf "  %-28s %s\n" "deploy-ingestion"        "Deploy only ingestion CronJob"
	@printf "  %-28s %s\n" "undeploy"                "Uninstall all Helm releases"
	@printf "  %-28s %s\n" "status"                  "Show releases and pod status"
	@printf "  %-28s %s\n" "lint-charts"             "Lint all Helm charts"
	@printf "\nVariables:\n"
	@printf "  %-16s %s\n" "REGISTRY"    "$(REGISTRY)"
	@printf "  %-16s %s\n" "NAMESPACE"   "$(NAMESPACE)"
	@printf "  %-16s %s\n" "TAG"         "$(TAG)"
	@printf "  %-16s %s\n" "PG_PASSWORD" "(required for deploy targets — no default)"
	@printf "\n"

# ── Guards ────────────────────────────────────────────────────────────────────
_guard-pg-password:
	@test -n "$(PG_PASSWORD)" || \
	  { printf "ERROR: PG_PASSWORD is required.\nRun: make <target> PG_PASSWORD=<password>\n"; exit 1; }

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
build: _guard-podman build-postgres build-app build-llamastack
	@echo "==> All images built and pushed to $(REGISTRY)."

build-postgres: _guard-podman
	@echo "==> Building Postgres image: $(IMG_POSTGRES)"
	podman build \
	  -f deploy/postgres/Containerfile \
	  -t $(IMG_POSTGRES) \
	  deploy/postgres
	podman push $(IMG_POSTGRES)

build-app: _guard-podman
	@echo "==> Building FastAPI app image: $(IMG_APP)"
	podman build \
	  -f deploy/app/Containerfile \
	  -t $(IMG_APP) \
	  .
	podman push $(IMG_APP)

build-llamastack: _guard-podman
	@echo "==> Building Llama Stack distribution image: $(IMG_LLAMA)"
	llama stack build --config deploy/llamastack/build.yaml
	podman tag distribution-general-sim:dev $(IMG_LLAMA)
	podman push $(IMG_LLAMA)

# ── Namespace bootstrap ───────────────────────────────────────────────────────
# Called automatically by deploy-postgres; idempotent.
_deploy-namespace: _guard-oc
	oc apply -f deploy/openshift/namespace.yaml

# ── Component deploy targets ──────────────────────────────────────────────────

## Step 1 — Postgres
deploy-postgres: _guard-pg-password _guard-oc _guard-helm _deploy-namespace
	@echo "==> Deploying Postgres..."
	helm upgrade --install postgres $(CHART_POSTGRES) \
	  $(HELM_COMMON) \
	  --set image=$(IMG_POSTGRES) \
	  --set postgres.password=$(PG_PASSWORD) \
	  --wait --timeout 5m
	@echo "    Postgres ready."

## Step 2 — Schema bootstrap (runs as a Helm post-install/upgrade hook Job)
deploy-bootstrap: _guard-pg-password _guard-helm
	@echo "==> Running schema bootstrap Job..."
	helm upgrade --install bootstrap $(CHART_BOOTSTRAP) \
	  $(HELM_COMMON) \
	  --set image=$(IMG_APP) \
	  --set postgres.password=$(PG_PASSWORD) \
	  --atomic --timeout 3m
	@echo "    Bootstrap complete."

## Step 3 — vLLM  (GPU required; timeout is generous for model loading)
deploy-vllm: _guard-helm
	@echo "==> Deploying vLLM..."
	helm upgrade --install vllm $(CHART_VLLM) \
	  $(HELM_COMMON) \
	  --set image=$(IMG_VLLM) \
	  --wait --timeout 15m
	@echo "    vLLM ready."

## Step 4 — Llama Stack
deploy-llamastack: _guard-pg-password _guard-helm
	@echo "==> Deploying Llama Stack..."
	helm upgrade --install llamastack $(CHART_LLAMASTACK) \
	  $(HELM_COMMON) \
	  --set image=$(IMG_LLAMA) \
	  --set postgres.password=$(PG_PASSWORD) \
	  --wait --timeout 3m
	@echo "    Llama Stack ready."

## Step 5 — FastAPI API
deploy-api: _guard-pg-password _guard-helm
	@echo "==> Deploying FastAPI API..."
	helm upgrade --install api $(CHART_API) \
	  $(HELM_COMMON) \
	  --set image=$(IMG_APP) \
	  --set postgres.password=$(PG_PASSWORD) \
	  --wait --timeout 3m
	@printf "    API ready. Route:\n"
	@oc get route general-sim-api -n $(NAMESPACE) \
	  -o jsonpath='    https://{.spec.host}/health{"\n"}' 2>/dev/null || true

## Step 6 — Ingestion CronJob
deploy-ingestion: _guard-pg-password _guard-helm
	@echo "==> Deploying ingestion CronJob..."
	helm upgrade --install ingestion $(CHART_INGESTION) \
	  $(HELM_COMMON) \
	  --set image=$(IMG_APP) \
	  --set postgres.password=$(PG_PASSWORD) \
	  --wait --timeout 2m
	@echo "    Ingestion CronJob configured."

## Full ordered deploy
deploy: _guard-pg-password _guard-oc _guard-helm \
        deploy-postgres deploy-bootstrap deploy-vllm \
        deploy-llamastack deploy-api deploy-ingestion
	@printf "\n==> Full deployment complete.\n"
	@printf "    Smoke test:\n"
	@printf "      ROUTE=\$$(oc get route general-sim-api -n $(NAMESPACE)"
	@printf " -o jsonpath='{.spec.host}')\n"
	@printf "      curl -s https://\$$ROUTE/health | jq .\n\n"

# ── Undeploy ──────────────────────────────────────────────────────────────────
# Uninstalls all releases in reverse order; ignores missing releases.
undeploy: _guard-helm
	@echo "==> Removing Helm releases from namespace $(NAMESPACE)..."
	helm uninstall ingestion  --namespace $(NAMESPACE) 2>/dev/null || true
	helm uninstall api        --namespace $(NAMESPACE) 2>/dev/null || true
	helm uninstall llamastack --namespace $(NAMESPACE) 2>/dev/null || true
	helm uninstall vllm       --namespace $(NAMESPACE) 2>/dev/null || true
	helm uninstall bootstrap  --namespace $(NAMESPACE) 2>/dev/null || true
	helm uninstall postgres   --namespace $(NAMESPACE) 2>/dev/null || true
	@echo "    Done. PVCs are NOT deleted automatically — remove manually if needed:"
	@echo "      oc delete pvc -n $(NAMESPACE) --all"

# ── Status ────────────────────────────────────────────────────────────────────
status: _guard-helm _guard-oc
	@echo "==> Helm releases in namespace $(NAMESPACE):"
	@helm list --namespace $(NAMESPACE)
	@echo ""
	@echo "==> Pod status:"
	@oc get pods -n $(NAMESPACE)

# ── Lint ──────────────────────────────────────────────────────────────────────
lint-charts: _guard-helm
	@for chart in \
	  $(CHART_POSTGRES) \
	  $(CHART_BOOTSTRAP) \
	  $(CHART_VLLM) \
	  $(CHART_LLAMASTACK) \
	  $(CHART_API) \
	  $(CHART_INGESTION); do \
	  printf "==> Linting $$chart ...\n"; \
	  helm lint "$$chart" || exit 1; \
	done
	@echo "==> All charts passed lint."
