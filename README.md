# aobp

A Python (FastAPI) app that runs in Docker, with tests, linting,
type-checking, and GitHub Actions CI/CD already wired up.

| Workflow | Status |
| --- | --- |
| CI | [![CI](https://github.com/zznathans/aobp/actions/workflows/ci.yml/badge.svg)](https://github.com/zznathans/aobp/actions/workflows/ci.yml) |
| Docker build | [![Docker](https://github.com/zznathans/aobp/actions/workflows/docker-build.yml/badge.svg)](https://github.com/zznathans/aobp/actions/workflows/docker-build.yml) |
| Labeler | [![Labeler](https://github.com/zznathans/aobp/actions/workflows/labeler.yml/badge.svg)](https://github.com/zznathans/aobp/actions/workflows/labeler.yml) |
| Coverage | [![Coverage Status](https://coveralls.io/repos/github/zznathans/aobp/badge.svg?branch=main)](https://coveralls.io/github/zznathans/aobp?branch=main) |
| Helm | [![Helm](https://github.com/zznathans/aobp/actions/workflows/helm.yml/badge.svg)](https://github.com/zznathans/aobp/actions/workflows/helm.yml) |
| Docker Publish | [![Docker Publish](https://github.com/zznathans/aobp/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/zznathans/aobp/actions/workflows/docker-publish.yml) |
| Chart Publish | [![Chart Publish](https://github.com/zznathans/aobp/actions/workflows/chart-publish.yml/badge.svg)](https://github.com/zznathans/aobp/actions/workflows/chart-publish.yml) |

## What's included

- **App**: minimal FastAPI app (`app/main.py`) with `/` and `/health` endpoints
- **Tests**: `pytest` + `pytest-cov` + FastAPI's `TestClient` (`tests/`)
- **Linting/formatting**: `ruff` and `black`
- **Type checking**: `mypy`
- **Pre-commit hooks**: `.pre-commit-config.yaml`
- **Docker**: multi-stage `Dockerfile` (non-root user, healthcheck) + `docker-compose.yml`
- **CI**: `.github/workflows/ci.yml` — lint, type-check, test on Python 3.11–3.14
- **Coverage**: test job reports to [Coveralls](https://coveralls.io) (informational — doesn't block merges)
- **Docker build check**: `.github/workflows/docker-build.yml` — builds the image (no push) on every push/PR to catch a broken `Dockerfile`
- **PR labeler**: `.github/workflows/labeler.yml` + `.github/labeler.yml` — labels PRs by changed path
- **Dependabot**: keeps pip, Docker base image, and GitHub Actions up to date
- **Helm chart**: `charts/aobp/` — deploys the app to Kubernetes (see [Deploying](#deploying))
- **Release publishing**: `docker-publish.yml` (image to GHCR) and `chart-publish.yml`
  (chart to GHCR as OCI and to `gh-pages`) both run on a published GitHub Release
  (see [Releasing](#releasing))

## Getting started

```bash
make dev      # install package + dev deps, install pre-commit hooks
make run      # run the app locally with reload
make test     # run tests
make lint     # ruff + black --check + mypy
make format   # ruff --fix + black
```

## Docker

```bash
make docker-build     # docker build -t aobp .
make docker-run       # docker compose up --build
```

The app listens on port 8000. Try `curl http://localhost:8000/health`.

## CI/CD

- Every push/PR runs lint + tests via `ci.yml`, and uploads coverage to Coveralls
  (informational only — a coverage drop never fails the build).
- Every push/PR also builds the Docker image via `docker-build.yml` to make sure it
  still builds — it does not push anywhere.
- Publishing an image and a chart version both happen on a published GitHub
  Release (see [Releasing](#releasing)) — nothing is pushed to a registry on
  an ordinary push to `main`.

## Deploying

A Helm chart lives at `charts/aobp/` — see [its README](charts/aobp/README.md)
for values and usage. Quick start:

```bash
helm lint charts/aobp --strict
helm unittest charts/aobp
helm install aobp charts/aobp \
  --set aobp.imageRepository=ghcr.io/zznathans/aobp \
  --set aobp.imageTag=latest
```

It deploys a Deployment + Service exposing `/` and `/health` — no chart-owned
Ingress, so put it behind whatever ingress/traffic routing your cluster
already uses. `helm.yml` lints and unit-tests the chart on every push/PR that
touches `charts/**`.

## Releasing

Publishing an image and a chart version both happen on a published GitHub
Release — bump `charts/aobp/Chart.yaml`'s `version`/`appVersion` and cut a
release (tag it to match, e.g. `v0.2.0`):

- `docker-publish.yml` builds and pushes `ghcr.io/zznathans/aobp` (tagged
  from the release), with a build attestation.
- `chart-publish.yml` publishes the chart two ways, independently:
  - **OCI**: pushed to `oci://ghcr.io/zznathans/aobp/charts` —
    `helm install aobp oci://ghcr.io/zznathans/aobp/charts/aobp --version <version>`
  - **gh-pages**: a classic Helm chart repo via `helm/chart-releaser-action`
    — `helm repo add aobp https://zznathans.github.io/aobp` (requires GitHub
    Pages enabled on this repo, serving the `gh-pages` branch)

## Project layout

```
app/            application code
tests/          tests
charts/aobp/    Helm chart to deploy the app
Dockerfile
docker-compose.yml
pyproject.toml  project metadata, deps, tool config (ruff/black/mypy/pytest)
Makefile        common dev commands
.github/        CI, Docker build check + publish, Helm lint/test + publish, PR labeler, dependabot
```
