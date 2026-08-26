# Releasing

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
