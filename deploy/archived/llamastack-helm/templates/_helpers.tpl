{{- define "llamastack.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | trunc 63 | trimSuffix "-" }}
app.kubernetes.io/name: llamastack
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: general-sim
app.kubernetes.io/component: llamastack
{{- end }}

{{- define "llamastack.selectorLabels" -}}
app.kubernetes.io/name: llamastack
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
