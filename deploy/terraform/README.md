# Tendwell Terraform module

This module deploys Tendwell -- a self-hosted, local-first AgentOps tool -- onto
a Kubernetes cluster by installing its Helm chart via a single `helm_release`.

By default it installs the chart bundled in this repo at
`deploy/helm/tendwell` (the module's `chart_path` defaults to `../helm/tendwell`,
which resolves relative to this module's directory). When the chart is published
to a Helm repository, set `chart_repository` and `chart_version` to install the
released chart instead.

## Secure, local-first defaults

The install mirrors Tendwell's posture: it is read-only and local-first out of
the box. With an empty `config` (the default), the chart's defaults apply:

- `read_only` permissions mode
- a stub LLM provider (deterministic, no model, no egress)
- a hash embeddings provider (local, no model download, no egress)
- a synthetic data source (no external systems)

Pointing Tendwell at real data sources or models is an explicit override you
make through the `config` variable.

## Requirements

- Terraform `>= 1.3`
- Providers: `hashicorp/helm` `~> 2.12`, `hashicorp/kubernetes` `~> 2.23`
- A configured `kubernetes` and `helm` provider with access to a target cluster.

This module does not configure providers (modules should not). The root module
that calls it must configure the `kubernetes` and `helm` providers. CI runs
`terraform fmt -check` and `terraform validate` (pure HCL validity, no cluster
and no backend required); a real `terraform apply` is operator-run against a
cluster.

## Minimal usage

See `examples/basic`:

```hcl
module "tendwell" {
  source = "../../"

  release_name     = "tendwell"
  namespace        = "tendwell"
  create_namespace = true
}
```

## Overriding `config` for real sources and models

The `config` variable is rendered to the chart's `config` value (the Tendwell
YAML config). Override the whole block to point at real systems:

```hcl
module "tendwell" {
  source = "../../"

  config = {
    permissions = {
      mode = "read_only"
    }
    server = {
      mode = "on_demand"
      host = "0.0.0.0"
      port = 8080
    }
    data_sources = [
      {
        name = "prod-metrics"
        type = "prometheus"
        url  = "http://prometheus.monitoring.svc:9090"
      }
    ]
    llm = {
      provider = "openai"
      # API keys are NOT placed here. The provider reads them from an
      # environment variable injected by reference -- see env_from below.
      model = "gpt-4o-mini"
    }
    embeddings = {
      provider = "hash"
    }
  }
}
```

## Injecting secrets by reference (never inline)

Secrets are injected by reference only. Create a Kubernetes Secret out of band
(for example with `kubectl`, an external-secrets operator, or a sealed secret),
then reference it via `env_from`. The module never accepts inline secret values.

```hcl
module "tendwell" {
  source = "../../"

  # Pull all keys from an existing Secret in as environment variables.
  env_from = [
    {
      secretRef = {
        name = "tendwell-secrets"
      }
    }
  ]
}
```

The referenced Secret (created outside this module) provides credentials such as
an LLM API key or a data-source token. The Tendwell config references those
credentials by environment-variable name, so no secret value ever appears in
Terraform state or in chart values.

## Inputs

| Name               | Type         | Default                  | Description                                                                                  |
| ------------------ | ------------ | ------------------------ | -------------------------------------------------------------------------------------------- |
| `release_name`     | `string`     | `"tendwell"`             | Helm release name.                                                                           |
| `namespace`        | `string`     | `"tendwell"`             | Namespace to install into.                                                                   |
| `create_namespace` | `bool`       | `true`                   | Create the namespace if it does not exist.                                                   |
| `chart_path`       | `string`     | `"../helm/tendwell"`     | Local chart path, used when `chart_repository` is null.                                       |
| `chart_repository` | `string`     | `null`                   | Helm repo URL for a published chart. Null means use `chart_path`.                             |
| `chart_version`    | `string`     | `null`                   | Chart version to install. Null lets Helm resolve it.                                          |
| `image_repository` | `string`     | `"ghcr.io/bmoldo/tendwell"` | Container image repository.                                                                |
| `image_tag`        | `string`     | `""`                     | Image tag. Empty means use the chart's appVersion default.                                    |
| `replica_count`    | `number`     | `1`                      | Number of replicas (the daemon is single-instance by default).                               |
| `config`           | `any`        | `{}`                     | Tendwell YAML config. `{}` keeps the chart's safe local-first defaults.                       |
| `env_from`         | `list(any)`  | `[]`                     | Chart `envFrom` for injecting secrets by reference (for example `secretRef`).                 |
| `extra_values`     | `any`        | `{}`                     | Arbitrary extra chart values merged in (takes precedence).                                    |
| `resources`        | `any`        | `{}`                     | Optional resource requests/limits overrides.                                                  |

## Outputs

| Name            | Description                                                                 |
| --------------- | --------------------------------------------------------------------------- |
| `release_name`  | Name of the installed Helm release.                                         |
| `namespace`     | Namespace the release is installed into.                                    |
| `chart_version` | Chart version resolved and installed.                                       |
| `service_name`  | ClusterIP Service name (release name plus the chart name `tendwell`).        |
