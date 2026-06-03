output "release_name" {
  description = "Name of the installed Helm release."
  value       = helm_release.tendwell.name
}

output "namespace" {
  description = "Namespace the release is installed into."
  value       = helm_release.tendwell.namespace
}

output "chart_version" {
  description = "Chart version resolved and installed by the Helm release."
  value       = helm_release.tendwell.version
}

output "service_name" {
  description = "Name of the ClusterIP Service exposing Tendwell. Derived from the chart's fullname (release name plus the chart name 'tendwell'). If the release name already contains 'tendwell', the chart uses the release name unchanged."
  value       = "${helm_release.tendwell.name}-tendwell"
}
