# aobp

Helm chart for [`aobp`](https://github.com/zznathans/aobp).

Deploys a FastAPI Deployment + Service, exposing `/` and `/health`. No
chart-owned Ingress — the Service is meant to sit behind whatever
externally-managed ingress/traffic routing your cluster already uses.

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

## Development

```
helm lint charts/aobp --strict
helm unittest charts/aobp
```
