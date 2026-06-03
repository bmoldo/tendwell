# Tendwell Helm Chart

A Helm chart for Tendwell -- a self-hosted, local-first AgentOps tool.

The default install is secure by default and local-first: it runs read-only,
against a synthetic data source, with a stub LLM provider and a hash embeddings
provider. That means a default `helm install` needs no model and no network
egress. Pointing Tendwell at real data sources or models is an explicit
override.

## Install

```
helm install tendwell ./deploy/helm/tendwell
```

The container runs the `tendwell` CLI as its entrypoint. The chart starts the
daemon server with:

```
tendwell run --config /etc/tendwell/tendwell.yaml
```

The config file is rendered from `values.yaml` into a ConfigMap and mounted at
`/etc/tendwell/tendwell.yaml`.

## Access

The workload runs the continuous monitoring daemon, which analyzes on an interval
and writes findings to its logs (it serves no HTTP). Follow the reports with:

```
kubectl logs -f deploy/tendwell
```

## Override the config

The entire `config:` block in `values.yaml` is rendered verbatim into the
ConfigMap as `tendwell.yaml`. To customize Tendwell, override that block from
your own values file.

Create `my-values.yaml`:

```yaml
config:
  permissions:
    mode: read_only
  server:
    mode: on_demand
    host: 0.0.0.0
    port: 8080
  data_sources:
    - name: prod-metrics
      type: prometheus
      url: https://prometheus.example.internal
      # Credentials are referenced by env-var name, never inlined.
      token_env: PROM_TOKEN
  context:
    vector_store:
      type: memory
  llm:
    provider: openai
    model: gpt-4o-mini
    # The API key is read from this env var, set from a Secret (see below).
    api_key_env: OPENAI_API_KEY
  embeddings:
    provider: openai
    api_key_env: OPENAI_API_KEY
```

Install or upgrade with:

```
helm upgrade --install tendwell ./deploy/helm/tendwell -f my-values.yaml
```

## Inject secrets by reference

Secrets are NEVER inlined in the chart or in the config. The config references
credentials by env-var name via `*_env` fields (for example `api_key_env`,
`token_env`). You provide those env vars by reference to a Kubernetes Secret.

Create the Secret out of band:

```
kubectl create secret generic tendwell-secrets \
  --from-literal=OPENAI_API_KEY=sk-... \
  --from-literal=PROM_TOKEN=...
```

Then reference it via `envFrom` (bulk import all keys as env vars):

```yaml
envFrom:
  - secretRef:
      name: tendwell-secrets
```

Or reference specific keys via `extraEnv`:

```yaml
extraEnv:
  - name: OPENAI_API_KEY
    valueFrom:
      secretKeyRef:
        name: tendwell-secrets
        key: OPENAI_API_KEY
```

## Secure defaults

The chart mirrors Tendwell's security posture and ships hardened defaults:

- Pod security context: `runAsNonRoot: true`, uid/gid/fsGroup `10001`,
  `seccompProfile: RuntimeDefault`.
- Container security context: `allowPrivilegeEscalation: false`,
  `readOnlyRootFilesystem: true`, all capabilities dropped.
- Because the root filesystem is read-only, writable `emptyDir` volumes are
  mounted at `/app/data` and `/tmp`.
- The ServiceAccount does not auto-mount its API token.
- No secrets are inlined -- credentials are injected by reference only.

## Values

| Key | Description | Default |
| --- | --- | --- |
| `replicaCount` | Number of replicas | `1` |
| `image.repository` | Image repository | `ghcr.io/bmoldo/tendwell` |
| `image.tag` | Image tag (defaults to appVersion) | `""` |
| `image.pullPolicy` | Image pull policy | `IfNotPresent` |
| `imagePullSecrets` | Pull secrets for private registries | `[]` |
| `serviceAccount.create` | Create a ServiceAccount | `true` |
| `serviceAccount.name` | ServiceAccount name | `""` |
| `serviceAccount.annotations` | ServiceAccount annotations | `{}` |
| `podAnnotations` | Pod annotations | `{}` |
| `podSecurityContext` | Pod-level security context | hardened, see above |
| `securityContext` | Container-level security context | hardened, see above |
| `resources` | CPU/memory requests and limits | small defaults |
| `extraEnv` | Extra env vars (inject secrets by reference) | `[]` |
| `envFrom` | Bulk env import from Secrets/ConfigMaps | `[]` |
| `config` | Tendwell config rendered into the ConfigMap | safe local-first config |
| `nodeSelector` | Node selector | `{}` |
| `tolerations` | Tolerations | `[]` |
| `affinity` | Affinity rules | `{}` |

## Lint and template

```
helm lint ./deploy/helm/tendwell
helm template tendwell ./deploy/helm/tendwell
```
