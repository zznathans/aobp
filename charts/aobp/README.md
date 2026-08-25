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
password, generated once and kept stable across upgrades.

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
| mongodb.members | int | `3` | Number of replica set members. |
| mongodb.passwordSecretName | string | `""` | Name of an existing Secret holding the user's password under a `password` key - e.g. via External Secrets, or `kubectl create secret generic <name> --from-literal=password=...`. Leave empty to have the chart generate and manage a random password itself, in a Secret named "<release-name>-mongodb-password" - generated once and kept stable across upgrades (reuses the existing Secret's password if there is one). |
| mongodb.resources | object | `{"limits":{"cpu":"500m","memory":"512Mi"},"requests":{"cpu":"100m","memory":"256Mi"}}` | Resource requests and limits for the mongod container. |
| mongodb.storage | string | `"10Gi"` | Storage requested per member's PersistentVolumeClaim. |
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
