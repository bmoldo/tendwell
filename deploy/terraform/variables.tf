variable "release_name" {
  description = "Helm release name for the Tendwell install."
  type        = string
  default     = "tendwell"
}

variable "namespace" {
  description = "Kubernetes namespace to install Tendwell into."
  type        = string
  default     = "tendwell"
}

variable "create_namespace" {
  description = "Whether to create the namespace if it does not already exist."
  type        = bool
  default     = true
}

variable "chart_path" {
  description = "Local filesystem path to the Tendwell Helm chart. Used when chart_repository is null (the default), so the module works directly from this repo."
  type        = string
  default     = "../helm/tendwell"
}

variable "chart_repository" {
  description = "Helm chart repository URL for a published Tendwell chart. Leave null (the default) to install from the local chart_path."
  type        = string
  default     = null
}

variable "chart_version" {
  description = "Chart version to install. Leave null to let Helm resolve the version (the local chart's own version, or the latest from chart_repository)."
  type        = string
  default     = null
}

variable "image_repository" {
  description = "Container image repository for the Tendwell server."
  type        = string
  default     = "ghcr.io/bmoldo/tendwell"
}

variable "image_tag" {
  description = "Container image tag. Empty string means use the chart's appVersion default."
  type        = string
  default     = ""
}

variable "replica_count" {
  description = "Number of Tendwell replicas. The daemon server is single-instance by default."
  type        = number
  default     = 1
}

variable "config" {
  description = "Tendwell YAML configuration, rendered to the chart's `config` value. Default {} keeps the chart's safe local-first defaults (read-only permissions, stub model, hash embeddings, synthetic data source -- no model and no network egress)."
  type        = any
  default     = {}
}

variable "env_from" {
  description = "Passed to the chart's `envFrom` for injecting credentials by reference (for example secretRef). Secrets are injected by reference only -- NEVER place secret values inline here."
  type        = list(any)
  default     = []
}

variable "extra_values" {
  description = "Arbitrary extra chart values merged into the rendered values. Use for chart settings not exposed as dedicated variables."
  type        = any
  default     = {}
}

variable "resources" {
  description = "Optional resource requests/limits overrides for the Tendwell container. Empty {} keeps the chart's small daemon defaults."
  type        = any
  default     = {}
}
