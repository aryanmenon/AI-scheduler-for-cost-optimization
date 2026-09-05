{{- define "gpu-telemetry-collector.fullname" -}}
{{- .Release.Name -}}
{{- end -}}

{{- define "gpu-telemetry-collector.labels" -}}
app.kubernetes.io/part-of: gpu-cost-optimizer
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}
