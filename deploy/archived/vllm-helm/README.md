# Archived: plain Deployment-based vLLM chart.
#
# In-cluster inference now uses the shared `llm-service` Helm chart from
# https://rh-ai-quickstart.github.io/ai-architecture-charts (OpenShift AI /
# KServe ServingRuntime + InferenceService), wired as a subchart of
# deploy/helm/general-simulation.
#
# Restore only if you need a KServe-free Deployment path.
