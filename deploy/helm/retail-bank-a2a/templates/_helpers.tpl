{{- define "retail-bank-a2a.name" -}}retail-bank-a2a{{- end }}
{{- define "retail-bank-a2a.fullname" -}}{{ .Release.Name }}{{- end }}
{{- define "retail-bank-a2a.labels" -}}
app.kubernetes.io/name: {{ include "retail-bank-a2a.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

