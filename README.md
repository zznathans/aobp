# eve-build

A Python (FastAPI) app that runs in Docker, with tests, linting,
type-checking, and GitHub Actions CI/CD already wired up.

| Workflow | Status |
| --- | --- |
| Lint/Tests | [![CI](https://github.com/zznathans/eve-build/actions/workflows/ci.yml/badge.svg)](https://github.com/zznathans/eve-build/actions/workflows/ci.yml) |
| Test Coverage | [![Coverage Status](https://coveralls.io/repos/github/zznathans/eve-build/badge.svg?branch=main)](https://coveralls.io/github/zznathans/eve-build?branch=main) |
| Docker | [![Docker Publish](https://github.com/zznathans/eve-build/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/zznathans/eve-build/actions/workflows/docker-publish.yml) |
| Chart | [![Chart Publish](https://github.com/zznathans/eve-build/actions/workflows/chart-publish.yml/badge.svg)](https://github.com/zznathans/eve-build/actions/workflows/chart-publish.yml) |
| Latest Release | [![Release](https://img.shields.io/github/v/release/zznathans/eve-build)](https://github.com/zznathans/eve-build/releases) |

## What's included

`app/main.py` is a FastAPI blueprint library for EVE Online: players log in via
[EVE SSO](docs/authentication.md), then browse their characters' blueprints and see
what's buildable from their assets, backed by [CCP's Static Data Export](docs/blueprint-data.md)
imported into MongoDB (with an optional [Redis cache](docs/caching.md) in front of it).
A [Helm chart](docs/deploying.md) deploys it to Kubernetes.

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
make docker-build     # docker build -t eve-build .
make docker-run       # docker compose up --build
```

`docker-compose.yml` also starts `mongo` and `redis` containers the app connects to
automatically (`MONGODB_URI`/`REDIS_ENABLED`/`REDIS_URL` are pinned for the `app`
service). Copy `.env.example` to `.env` and fill in `EVE_SSO_CLIENT_ID`,
`EVE_SSO_CALLBACK_URL`, and `SESSION_SECRET_KEY` before running — it's picked up
automatically via `env_file` (everything except the Mongo/Redis connection settings
above, which are fixed to the `mongo`/`redis` services).

The app listens on port 8000. Try `curl http://localhost:8000/health`.

## CI/CD

- Every push/PR runs lint + tests via `ci.yml`, and uploads coverage to Coveralls
  (informational only — a coverage drop never fails the build).
- Every push/PR also builds the Docker image via `docker-build.yml` to make sure it
  still builds — it does not push anywhere.
- Every push to `main` also runs `release.yml`, which cuts a new version if
  the commits since the last release warrant one (see [Releasing](docs/releasing.md)).
  Publishing an image and a chart version both happen on that GitHub Release —
  nothing is pushed to a registry otherwise.

## Authentication

EVE Online SSO login via Authorization Code + PKCE, with character/token persistence in
MongoDB — see [docs/authentication.md](docs/authentication.md) for setup and required
scopes.

## Blueprint data

CCP's Static Data Export ships pre-dumped in the repo and is imported into MongoDB
automatically on startup — see [docs/blueprint-data.md](docs/blueprint-data.md) for how
it's structured and how to refresh it.

## Caching

An optional Redis read-through cache sits in front of the MongoDB lookups used to render
the blueprint pages — see [docs/caching.md](docs/caching.md) for how it's configured.

## Deploying

A Helm chart at `charts/eve-build/` deploys the app to Kubernetes, optionally with a
MongoDB replica set and/or a Redis cache — see [docs/deploying.md](docs/deploying.md).

## Releasing

Releases are cut and published automatically from Conventional Commits on `main` — see
[docs/releasing.md](docs/releasing.md) for how the release/publish pipeline works.

## Project layout

```
app/            application code
  core/         settings
  data/sde/     gzipped JSON dumps of the EVE Static Data Export (committed)
  db/           MongoDB + Redis connections
  migrations/   Mongo migrations, run automatically on startup
  models/       Mongo document models
  routes/       route handlers (health, auth, blueprints)
  scripts/      one-off dev scripts (regenerating app/data/sde/)
  services/     EVE SSO client, ESI client, Redis cache helpers
  web.py        shared dark-mode HTML page chrome
tests/          tests
docs/           detailed docs (authentication, blueprint data, caching, deploying, releasing)
charts/eve-build/    Helm chart to deploy the app
Dockerfile
docker-compose.yml
pyproject.toml  project metadata, deps, tool config (ruff/black/mypy/pytest)
Makefile        common dev commands
.github/        CI, Docker build check + publish, Helm lint/test + publish, PR labeler, dependabot
```

