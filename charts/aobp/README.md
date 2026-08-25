# aobp

Helm chart for [`aobp`](https://github.com/zznathans/aobp).

Deploys a FastAPI Deployment + Service, exposing `/` and `/health`. No
chart-owned Ingress — the Service is meant to sit behind whatever
externally-managed ingress/traffic routing your cluster already uses.

Optionally (`mongodb.enabled`) also deploys a `MongoDBCommunity` custom
resource — a MongoDB replica set. This requires the
[MongoDB Community Kubernetes Operator](https://github.com/mongodb/mongodb-kubernetes-operator)
already installed in the cluster; this chart only creates the CR, not the
operator itself. The user's password comes from a Secret (a `password` key):
set `mongodb.passwordSecretName` to point at one you already manage (e.g.
External Secrets, or `kubectl create secret generic ... --from-literal=password=...`),
or leave it empty and the chart generates and manages one itself — a random
password, generated once and kept stable across upgrades. When
`mongodb.enabled` is false, the app instead connects using
`mongodb.uri` (a plain connection string, e.g. for an external/managed
MongoDB instance), or a Secret referenced via `mongodb.existingSecret`, or
one synced by an optionally chart-deployed `ExternalSecret`
(`mongodb.externalSecret.enabled`, requires the
[External Secrets Operator](https://external-secrets.io) already installed
in the cluster) - which pulls a JSON object with `db_host`, `db_port`,
`db_user`, `db_password`, and `db_name` keys (the shape DigitalOcean Managed
MongoDB writes) and assembles it into a connection string.

Optionally (`redis.enabled`) also deploys a plain Redis Deployment + Service,
used by the app as an optional cache to cut down on MongoDB reads for
reference data. It's not a hard dependency of the app — nothing else in the
cluster needs to know about it, and there's no persistence/PVC since it's
purely a cache.

## Values

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| aobp.extraObjects | list | `[]` | Raw Kubernetes objects to render alongside chart-managed resources. |
| aobp.imagePullSecrets | list | `[]` | List of image pull secret names to attach to the ServiceAccount. Leave empty if the registry is public. |
| aobp.imageRepository | string | `"ghcr.io/zznathans/aobp"` | Container image registry and repository for the aobp image. |
| aobp.imageTag | string | `""` | Image tag to deploy. Empty by default: falls back to .Chart.AppVersion, which chart-publish.yml overrides to match the release a published chart was packaged from - so installing a published chart with no override deploys the matching image automatically. Only matters as a literal default for a raw checkout (falls back to Chart.yaml's committed appVersion) or local helm lint/unittest. |
| aobp.replicaCount | int | `1` | Number of pod replicas. The app is stateless, so this is safe to scale up freely. |
| aobp.resources | object | `{"limits":{"cpu":"250m","memory":"128Mi"},"requests":{"cpu":"50m","memory":"64Mi"}}` | Resource requests and limits for the app container. |
| aobp.service.port | int | `80` | Port the Service listens on and forwards to the container's 8000. |
| mongodb.database | string | `"aobp"` | Database the user is scoped to, via a readWrite role. |
| mongodb.enabled | bool | `false` | Deploy a MongoDBCommunity custom resource for this release. Requires the MongoDB Community Kubernetes Operator (https://github.com/mongodb/mongodb-kubernetes-operator) already installed in the cluster - this chart only creates the CR, not the operator itself. |
| mongodb.existingSecret | string | `""` | Name of an existing Secret holding a MongoDB connection string, used instead of `uri` when set - e.g. via External Secrets. Ignored when `enabled` or `externalSecret.enabled` is true. |
| mongodb.existingSecretKey | string | `"uri"` | Key within `existingSecret` holding the connection string. |
| mongodb.externalSecret.enabled | bool | `false` | Deploy an ExternalSecret (https://external-secrets.io) that syncs MongoDB connection details from an external secret store into a Secret this chart's Deployment then reads - an alternative to `existingSecret` when you'd rather have the chart manage the ExternalSecret object itself. Requires the External Secrets Operator already installed in the cluster. Ignored when `mongodb.enabled` is true; takes precedence over `existingSecret`/`uri` when set. |
| mongodb.externalSecret.refreshInterval | string | `"1h"` | How often the ExternalSecret refreshes from the store. |
| mongodb.externalSecret.remoteKey | string | `""` | Key/path within the external store holding the connection details. The remote secret is expected to be a JSON object with `db_host`, `db_host_public`, `db_port`, `db_user`, `db_password`, and `db_name` keys - the shape DigitalOcean Managed MongoDB writes - which are assembled into a `mongodb+srv://` connection string (`db_port` is unused: DigitalOcean's managed MongoDB hosts only resolve via SRV/TXT records, not a plain A record, so the actual host:port pairs and replica set name come from DNS instead of being embedded in the URI). |
| mongodb.externalSecret.secretStoreKind | string | `"SecretStore"` | Kind of the store referenced above - SecretStore or ClusterSecretStore. |
| mongodb.externalSecret.secretStoreRef | string | `""` | Name of the (Cluster)SecretStore to pull from. |
| mongodb.externalSecret.uriOptions | string | `"authSource=admin&tls=true"` | Query string appended to the assembled connection string (e.g. authSource, tls). Leave empty to omit. DigitalOcean Managed MongoDB requires TLS and an admin authSource. |
| mongodb.externalSecret.usePublicHost | bool | `false` | Use `db_host_public` instead of `db_host` when assembling the connection string - e.g. when the app isn't on the same VPC/network as the database and can only reach it over its public endpoint. |
| mongodb.members | int | `3` | Number of replica set members. |
| mongodb.passwordSecretName | string | `""` | Name of an existing Secret holding the user's password under a `password` key - e.g. via External Secrets, or `kubectl create secret generic <name> --from-literal=password=...`. Leave empty to have the chart generate and manage a random password itself, in a Secret named "<release-name>-mongodb-password" - generated once and kept stable across upgrades (reuses the existing Secret's password if there is one). |
| mongodb.resources | object | `{"limits":{"cpu":"500m","memory":"512Mi"},"requests":{"cpu":"100m","memory":"256Mi"}}` | Resource requests and limits for the mongod container. |
| mongodb.storage | string | `"10Gi"` | Storage requested per member's PersistentVolumeClaim. |
| mongodb.uri | string | `"mongodb://localhost:27017"` | Plain MongoDB connection string for the app to use when `enabled` is false and `existingSecret` isn't set - e.g. an external/managed MongoDB instance outside the cluster. Ignored when `enabled` is true (the in-cluster MongoDBCommunity's own connection string is used instead). |
| mongodb.username | string | `"aobp"` | Database user the operator creates. |
| mongodb.version | string | `"7.0.14"` | MongoDB server version to run. |
| redis.enabled | bool | `false` | Deploy a Redis instance for this release. The app uses it as an optional read-through cache for reference data (SDE type/blueprint lookups, resolved location names) to cut down on MongoDB reads - it's not a hard dependency, the app falls back to querying MongoDB directly if Redis is disabled or unreachable. |
| redis.resources | object | `{"limits":{"cpu":"100m","memory":"128Mi"},"requests":{"cpu":"25m","memory":"32Mi"}}` | Resource requests and limits for the redis container. |
| redis.version | string | `"7.4-alpine"` | Redis image tag to run. |

## Development

```
helm lint charts/aobp --strict
helm unittest charts/aobp
```
