# Minimal example: install Tendwell with its secure, local-first defaults.
#
# This calls the module with the local chart in this repo. The defaults keep
# Tendwell read-only with a stub model and a synthetic data source -- no model
# download and no network egress.
#
# A configured kubernetes/helm provider with cluster access is required for a
# real `terraform apply`. Provider configuration lives in the root module that
# calls this example, not in the Tendwell module itself. For example:
#
#   provider "kubernetes" {
#     config_path = "~/.kube/config"
#   }
#
#   provider "helm" {
#     kubernetes {
#       config_path = "~/.kube/config"
#     }
#   }

module "tendwell" {
  source = "../../"

  release_name     = "tendwell"
  namespace        = "tendwell"
  create_namespace = true
}

output "tendwell_service_name" {
  description = "Service name to reach the Tendwell daemon in-cluster."
  value       = module.tendwell.service_name
}
