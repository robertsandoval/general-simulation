{{/*
Resolve the Postgres container image.

Uses .Values.image when set (full ref); otherwise composes from global.registry,
global.images.postgres (or imageName), and global.imageTag.
*/}}
{{- define "postgres.containerImage" -}}
{{- if .Values.image -}}
{{- .Values.image -}}
{{- else -}}
{{- $registry := .Values.global.registry | default "quay.io/rh-ai-quickstart" -}}
{{- $tag := .Values.global.imageTag | default "latest" -}}
{{- $name := .Values.imageName | default (.Values.global.images.postgres | default "general-sim-postgres") -}}
{{- printf "%s/%s:%s" $registry $name $tag -}}
{{- end -}}
{{- end -}}

{{/*
Common labels
*/}}
{{- define "postgres.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | trunc 63 | trimSuffix "-" }}
app.kubernetes.io/name: postgres
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: general-sim
app.kubernetes.io/component: postgres
{{- end }}

{{/*
Selector labels (used in matchLabels and Service selectors)
*/}}
{{- define "postgres.selectorLabels" -}}
app.kubernetes.io/name: postgres
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
