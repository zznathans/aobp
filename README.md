# eve-build

A Python (FastAPI) app that runs in Docker, with tests, linting,
type-checking, and GitHub Actions CI/CD already wired up.

| Workflow | Status |
| --- | --- |
| CI | [![CI](https://github.com/zznathans/eve-build/actions/workflows/ci.yml/badge.svg)](https://github.com/zznathans/eve-build/actions/workflows/ci.yml) |
| Docker build | [![Docker](https://github.com/zznathans/eve-build/actions/workflows/docker-build.yml/badge.svg)](https://github.com/zznathans/eve-build/actions/workflows/docker-build.yml) |
| Labeler | [![Labeler](https://github.com/zznathans/eve-build/actions/workflows/labeler.yml/badge.svg)](https://github.com/zznathans/eve-build/actions/workflows/labeler.yml) |
| Coverage | [![Coverage Status](https://coveralls.io/repos/github/zznathans/eve-build/badge.svg?branch=main)](https://coveralls.io/github/zznathans/eve-build?branch=main) |
| Helm | [![Helm](https://github.com/zznathans/eve-build/actions/workflows/helm.yml/badge.svg)](https://github.com/zznathans/eve-build/actions/workflows/helm.yml) |
| Docker Publish | [![Docker Publish](https://github.com/zznathans/eve-build/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/zznathans/eve-build/actions/workflows/docker-publish.yml) |
| Chart Publish | [![Chart Publish](https://github.com/zznathans/eve-build/actions/workflows/chart-publish.yml/badge.svg)](https://github.com/zznathans/eve-build/actions/workflows/chart-publish.yml) |
| Release | [![Release](https://img.shields.io/github/v/release/zznathans/eve-build)](https://github.com/zznathans/eve-build/releases) |

## What's included

- **App**: FastAPI app (`app/main.py`) — a blueprint library for EVE Online, with a nav
  bar (`app/web.py`) and a dashboard (`app/routes/health.py`) summarizing the logged-in
  character's blueprints, assets, and running industry jobs
- **Auth**: EVE Online SSO login (`app/routes/auth.py`, `app/services/eve_sso.py`) using
  Authorization Code + PKCE, session cookies via Starlette's `SessionMiddleware`,
  character/token persistence in MongoDB (`app/db/mongo.py`) — see
  [Authentication](#authentication)
- **Blueprint library**: browse the logged-in character's blueprints and see what's
  buildable from their assets (`app/routes/blueprints.py`, `app/services/esi.py`) — see
  [Blueprint data](#blueprint-data)
- **Caching**: optional Redis-backed read-through cache for SDE lookups and location
  names (`app/services/cache.py`, `app/db/redis.py`) — falls back to querying MongoDB
  directly if Redis is disabled or unreachable
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
- **Helm chart**: `charts/eve-build/` — deploys the app to Kubernetes, optionally a MongoDB
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
  the commits since the last release warrant one (see [Releasing](#releasing)).
  Publishing an image and a chart version both happen on that GitHub Release —
  nothing is pushed to a registry otherwise.

## Authentication

Login uses [EVE Online SSO's Authorization Code + PKCE flow](https://developers.eveonline.com/docs/services/sso/#authorization-code-with-pkce):

1. Register an application at [developers.eveonline.com/applications](https://developers.eveonline.com/applications)
   with its callback URL matching `EVE_SSO_CALLBACK_URL` below.
2. Copy `.env.example` to `.env` and fill in:
   - `EVE_SSO_CLIENT_ID`, `EVE_SSO_CALLBACK_URL`, `EVE_SSO_SCOPES` (space-separated, may be empty)
   - `MONGODB_URI`, `MONGODB_DATABASE` — where character/token data is persisted
   - `SESSION_SECRET_KEY` — signs the session cookie; set to a long random value
   - `REDIS_ENABLED`, `REDIS_URL` — optional cache, see [Caching](#caching)
3. `GET /auth/login` starts the flow, `GET /auth/callback` completes it and sets a signed,
   httponly session cookie. `GET /auth/me` returns the logged-in character's identity;
   `GET /auth/logout` clears the session.

The dashboard and blueprint library need `esi-characters.read_blueprints.v1`,
`esi-assets.read_assets.v1`, `esi-industry.read_character_jobs.v1`, and
`esi-universe.read_structures.v1` (resolves player-structure location names —
without it those fall back to a raw `Location {id}` label) in `EVE_SSO_SCOPES`
— all four must also be enabled on the application itself at
developers.eveonline.com, or EVE SSO rejects the login with `invalid_scope`.

## Blueprint data

ESI doesn't expose blueprint manufacturing data (materials/products/time) — only CCP's
Static Data Export (SDE) has it. A gzip-compressed JSON dump of every SDE table ships in
the repo at `app/data/sde/` (one `<table>.json.gz` per table, generated from
[Fuzzwork's SDE SQLite export](https://www.fuzzwork.co.uk/dump/latest-sqlite.db.gz)), so
no manual download or import step is needed.

On startup, `app/migrations/` imports it into MongoDB automatically:
- `0001_import_raw_sde_tables` loads every `app/data/sde/*.json.gz` file verbatim into a
  same-named Mongo collection (e.g. `invTypes`, `industryActivityMaterials`).
- `0002_build_sde_lookup_collections` builds `sde_types` (type_id → name) and
  `sde_blueprints` (blueprint type_id → manufacturing materials/products/time) from those
  raw collections — this is what `app/routes/blueprints.py` actually queries.

Applied migrations are tracked in a `_migrations` collection, so this only runs once —
later startups skip straight past it. First startup against an empty database takes a
while (millions of rows); subsequent ones are instant.

To refresh the SDE data (e.g. after a new EVE expansion), regenerate the dumps and
commit the result:

```bash
curl -L https://www.fuzzwork.co.uk/dump/latest-sqlite.db.gz | gunzip > sde.sqlite
python -m app.scripts.dump_sde_json sde.sqlite
```

## Caching

MongoDB is queried on every blueprint list/detail page load for reference data that
rarely changes — `sde_types` (name lookups), `sde_blueprints` (materials/products), and
resolved location names. Set `REDIS_ENABLED=true` (and `REDIS_URL`) to put a Redis
read-through cache in front of those lookups (`app/services/cache.py`), cutting repeat
Mongo reads down to whatever `REDIS_CACHE_TTL_SECONDS` allows (default 24h — this data
only changes when the SDE migrations rerun or a location is looked up for the first
time). It's entirely optional: if `REDIS_ENABLED` is false, or Redis is unreachable, the
app just queries MongoDB directly — there's no hard dependency, and cache errors are
swallowed rather than surfaced as request failures.

## Deploying

A Helm chart lives at `charts/eve-build/` — see [its README](charts/eve-build/README.md)
for values and usage. Quick start:

```bash
helm lint charts/eve-build --strict
helm unittest charts/eve-build
helm install eve-build oci://ghcr.io/zznathans/eve-build/charts/eve-build --version X.Y.Z
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
Service, used by the app as an optional cache (see [Caching](#caching)) — not
a hard dependency, no persistence/PVC since it's purely a cache.

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
   - `docker-publish.yml` builds and pushes `ghcr.io/zznathans/eve-build:X.Y.Z`,
     with a build attestation.
   - `chart-publish.yml` packages `charts/eve-build` with `--version`/`--app-version`
     overridden from the release tag (not whatever's committed in `Chart.yaml`)
     and pushes it as an OCI artifact to `oci://ghcr.io/zznathans/eve-build/charts` —
     `helm install eve-build oci://ghcr.io/zznathans/eve-build/charts/eve-build --version X.Y.Z`.

`Chart.yaml`'s committed `version`/`appVersion` only matter for local
`helm lint`/`helm unittest` — they're not what gets published. `eveBuild.imageTag`
defaults to `.Chart.AppVersion` (see `charts/eve-build/README.md`), so installing
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
charts/eve-build/    Helm chart to deploy the app
Dockerfile
docker-compose.yml
pyproject.toml  project metadata, deps, tool config (ruff/black/mypy/pytest)
Makefile        common dev commands
.github/        CI, Docker build check + publish, Helm lint/test + publish, PR labeler, dependabot
```

