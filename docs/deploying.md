# Deploying

A Helm chart lives at `charts/eve-build/` — see [its README](../charts/eve-build/README.md)
for values and usage. Quick start:

```bash
helm lint charts/eve-build --strict
helm unittest charts/eve-build
helm install eve-build oci://ghcr.io/zznathans/eve-build-chart --version X.Y.Z
```

It deploys a Deployment + Service exposing `/` and `/health` — no chart-owned
Ingress, so put it behind whatever ingress/traffic routing your cluster
already uses. `helm.yml` lints and unit-tests the chart on every push/PR that
touches `charts/**`.

Optionally (`mongodb.enabled=true`) it also deploys a `MongoDBCommunity`
custom resource — a MongoDB replica set — via the
[MongoDB Community Kubernetes Operator](https://github.com/mongodb/mongodb-kubernetes-operator),
which must already be installed in the cluster; this chart only creates the
CR. The user's password comes from a Secret (`mongodb.passwordSecretName`,
key `password`): point it at one you already manage, or leave it empty and
the chart generates and manages one itself — a random password, generated
once and kept stable across upgrades.

Optionally (`redis.enabled=true`) it also deploys a plain Redis Deployment +
Service, used by the app as an optional cache (see [Caching](caching.md)) — not
a hard dependency, no persistence/PVC since it's purely a cache. Setting
`redis.exporter.enabled=true` adds a `redis_exporter` sidecar to that Redis pod,
and `redis.exporter.serviceMonitor.enabled=true` deploys a `ServiceMonitor` for it.

Optionally (`eveBuild.metrics.enabled=true`) the app exposes Prometheus-compatible
metrics at `GET /metrics`. Setting `eveBuild.metrics.serviceMonitor.enabled=true` also
deploys a `ServiceMonitor` so a Prometheus Operator in the cluster scrapes it
automatically — this requires the Prometheus Operator CRDs already installed.
