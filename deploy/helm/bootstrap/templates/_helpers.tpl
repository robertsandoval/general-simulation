{{- define "bootstrap.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | trunc 63 | trimSuffix "-" }}
app.kubernetes.io/name: bootstrap
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: general-sim
app.kubernetes.io/component: bootstrap
{{- end }}

{{/*
Construct the Postgres DSN from individual values.
*/}}
{{- define "bootstrap.postgresDSN" -}}
postgresql://{{ .Values.postgres.user }}:{{ required "postgres.password is required" .Values.postgres.password }}@{{ .Values.postgres.host }}:{{ .Values.postgres.port }}/{{ .Values.postgres.database }}
{{- end }}
