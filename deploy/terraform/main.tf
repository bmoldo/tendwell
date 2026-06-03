locals {
  # Build the chart values map from the input variables. Only non-empty
  # overrides are included so the chart's secure, local-first defaults remain
  # in effect unless an operator explicitly changes them.
  image_values = merge(
    {
      repository = var.image_repository
    },
    var.image_tag == "" ? {} : { tag = var.image_tag },
  )

  base_values = merge(
    {
      replicaCount = var.replica_count
      image        = local.image_values
      envFrom      = var.env_from
    },
    length(keys(var.config)) > 0 ? { config = var.config } : {},
    length(keys(var.resources)) > 0 ? { resources = var.resources } : {},
  )

  # extra_values takes precedence and is merged last.
  chart_values = merge(local.base_values, var.extra_values)
}

resource "helm_release" "tendwell" {
  name             = var.release_name
  namespace        = var.namespace
  create_namespace = var.create_namespace

  # When chart_repository is null, install from the local chart_path. Otherwise
  # install the published "tendwell" chart from the given repository.
  repository = var.chart_repository
  chart      = var.chart_repository == null ? var.chart_path : "tendwell"
  version    = var.chart_version

  values = [yamlencode(local.chart_values)]
}
