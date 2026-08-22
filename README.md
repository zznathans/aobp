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
| Release | [![Release](https://img.shields.io/github/v/release/zznathans/aobp)](https://github.com/zznathans/aobp/releases) |

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
- **Helm chart**: `charts/aobp/` — deploys the app to Kubernetes, optionally a MongoDB
  replica set via the MongoDB Community Operator (see [Deploying](#deploying))
- **Automated releases**: `release.yml` — semantic-release, driven by Conventional
  Commits on `main`; no manual tagging (see [Releasing](#releasing))
- **Release publishing**: `docker-publish.yml` (image to GHCR) and `chart-publish.yml`
  (chart to GHCR as an OCI artifact) both run on the GitHub Release semantic-release
  creates (see [Releasing](#releasing))

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
- Every push to `main` also runs `release.yml`, which cuts a new version if
  the commits since the last release warrant one (see [Releasing](#releasing)).
  Publishing an image and a chart version both happen on that GitHub Release —
  nothing is pushed to a registry otherwise.

## Deploying

A Helm chart lives at `charts/aobp/` — see [its README](charts/aobp/README.md)
for values and usage. Quick start:

```bash
helm lint charts/aobp --strict
helm unittest charts/aobp
helm install aobp oci://ghcr.io/zznathans/aobp/charts/aobp --version X.Y.Z
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

## Releasing

Releases are cut automatically — nothing to do manually. Merge a PR to `main`
with a [Conventional Commits](https://www.conventionalcommits.org/) message
(`fix:` → patch, `feat:` → minor, `feat!:`/`BREAKING CHANGE:` → major) and
`release.yml` handles the rest:

1. [semantic-release](https://semantic-release.gitbook.io/) computes the next
   version from commits since the last release and, if one is warranted,
   creates the `X.Y.Z` tag + GitHub Release directly via the GitHub API — no
   version-bump commit, so this never pushes to `main`.
2. That published Release is what triggers the actual publishing:
   - `docker-publish.yml` builds and pushes `ghcr.io/zznathans/aobp:X.Y.Z`,
     with a build attestation.
   - `chart-publish.yml` packages `charts/aobp` with `--version`/`--app-version`
     overridden from the release tag (not whatever's committed in `Chart.yaml`)
     and pushes it as an OCI artifact to `oci://ghcr.io/zznathans/aobp/charts` —
     `helm install aobp oci://ghcr.io/zznathans/aobp/charts/aobp --version X.Y.Z`.

`Chart.yaml`'s committed `version`/`appVersion` only matter for local
`helm lint`/`helm unittest` — they're not what gets published. `aobp.imageTag`
defaults to `.Chart.AppVersion` (see `charts/aobp/README.md`), so installing
the published chart with no overrides deploys the image tag matching that
release automatically.

`release.yml` authenticates as a GitHub App installation token rather than
the default `GITHUB_TOKEN`: a release created with the default token never
fires other workflows' `release: published` listeners (GitHub's
anti-recursion rule), which is exactly what
`docker-publish.yml`/`chart-publish.yml` are waiting for. This needs two repo
secrets (Settings → Secrets and variables → Actions):
- `APP_ID` — already set (App ID `4677960`)
- `APP_PRIVATE_KEY` — the App's private key (PEM); still needs to be added.
  The App also needs to be installed on this repo with `Contents: write`.

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
