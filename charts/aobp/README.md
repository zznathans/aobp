# aobp

Helm chart for [`aobp`](https://github.com/zznathans/aobp).

Deploys a FastAPI Deployment + Service, exposing `/` and `/health`. No
chart-owned Ingress — the Service is meant to sit behind whatever
externally-managed ingress/traffic routing your cluster already uses.

Optionally (`mongodb.enabled`) also deploys a `MongoDBCommunity` custom
resource — a MongoDB replica set. This requires the
[MongoDB Community Kubernetes Operator](https://github.com/mongodb/mongodb-kubernetes-operator)
already installed in the cluster; this chart only creates the CR, not the
operator itself. The referenced `mongodb.passwordSecretName` Secret (a
`password` key) must already exist — this chart doesn't create it, so that
the password can come from wherever you already manage secrets (e.g.
External Secrets, or `kubectl create secret generic ... --from-literal=password=...`).

## Values

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| aobp.extraObjects | list | `[]` | Raw Kubernetes objects to render alongside chart-managed resources. |
| aobp.imagePullSecrets | list | `[]` | List of image pull secret names to attach to the ServiceAccount. Leave empty if the registry is public. |
| aobp.imageRepository | string | `"ghcr.io/zznathans/aobp"` | Container image registry and repository for the aobp image. |
| aobp.imageTag | string | `"latest"` | Image tag to deploy. |
| aobp.replicaCount | int | `1` | Number of pod replicas. The app is stateless, so this is safe to scale up freely. |
| aobp.resources | object | `{"limits":{"cpu":"250m","memory":"128Mi"},"requests":{"cpu":"50m","memory":"64Mi"}}` | Resource requests and limits for the app container. |
| aobp.service.port | int | `80` | Port the Service listens on and forwards to the container's 8000. |
| mongodb.database | string | `"aobp"` | Database the user is scoped to, via a readWrite role. |
| mongodb.enabled | bool | `false` | Deploy a MongoDBCommunity custom resource for this release. Requires the MongoDB Community Kubernetes Operator (https://github.com/mongodb/mongodb-kubernetes-operator) already installed in the cluster - this chart only creates the CR, not the operator itself. |
| mongodb.members | int | `3` | Number of replica set members. |
| mongodb.passwordSecretName | string | `""` | Name of an existing Secret (not created by this chart) holding the user's password under a `password` key - e.g. via External Secrets, or `kubectl create secret generic <name> --from-literal=password=...`. Required when mongodb.enabled is true. |
| mongodb.resources | object | `{"limits":{"cpu":"500m","memory":"512Mi"},"requests":{"cpu":"100m","memory":"256Mi"}}` | Resource requests and limits for the mongod container. |
| mongodb.storage | string | `"10Gi"` | Storage requested per member's PersistentVolumeClaim. |
| mongodb.username | string | `"aobp"` | Database user the operator creates. |
| mongodb.version | string | `"7.0.14"` | MongoDB server version to run. |

## Development

```
helm lint charts/aobp --strict
helm unittest charts/aobp
```
