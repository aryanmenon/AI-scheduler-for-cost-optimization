{{- define "gpu-telemetry-collector.fullname" -}}
{{- .Release.Name -}}
{{- end -}}

{{- define "gpu-telemetry-collector.labels" -}}
app.kubernetes.io/part-of: gpu-cost-optimizer
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}

{{/*
Where the collector scrapes DCGM metrics: this chart's own exporter, an
explicit external URL, or the headless Service this chart creates in front
of an existing exporter (templates/dcgm-exporter-external.yaml).
*/}}
{{- define "gpu-telemetry-collector.dcgmExporterUrl" -}}
{{- if .Values.dcgmExporter.enabled -}}
http://{{ include "gpu-telemetry-collector.fullname" . }}-dcgm-exporter:9400/metrics
{{- else if .Values.dcgmExporter.external.url -}}
{{ .Values.dcgmExporter.external.url }}
{{- else if and .Values.dcgmExporter.external.namespace .Values.dcgmExporter.external.podSelector -}}
http://{{ include "gpu-telemetry-collector.fullname" . }}-dcgm-external.{{ .Values.dcgmExporter.external.namespace }}.svc:{{ .Values.dcgmExporter.external.port }}/metrics
{{- else -}}
{{- fail "dcgmExporter.enabled is false: set dcgmExporter.external.url, or dcgmExporter.external.namespace and podSelector, so the collector can find the cluster's existing dcgm-exporter" -}}
{{- end -}}
{{- end -}}
