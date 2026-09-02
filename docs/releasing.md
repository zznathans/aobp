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
     and pushes it as an OCI artifact to `oci://ghcr.io/zznathans` (as chart
     `eve-build-chart`, not `eve-build`, so it doesn't collide with the Docker
     image's own tags at `ghcr.io/zznathans/eve-build`) —
     `helm install eve-build oci://ghcr.io/zznathans/eve-build-chart --version X.Y.Z`.
   - `release.yml` itself also packages the chart a second time and publishes
     it as a traditional Helm chart repo (`index.yaml` + `.tgz`) to the
     `gh-pages` branch — `@semantic-release/exec`'s `publishCmd` (configured
     in `.releaserc.json`) runs `.github/scripts/publish-gh-pages-chart.sh`,
     which clones/creates the `gh-pages` branch, packages the chart into it,
     merges the new entry into the existing `index.yaml`, and pushes. This
     runs as part of the semantic-release pipeline itself (after the GitHub
     Release above already exists) rather than a separate downstream
     workflow, since it needs `${nextRelease.version}` which only
     semantic-release knows. This is an additional install method alongside
     the OCI one above, not a replacement — see [Deploying](deploying.md).
     GitHub Pages needs to be enabled once (Settings → Pages → Deploy from a
     branch → `gh-pages` / `(root)`) after the first release creates that
     branch.
     (Deliberately not delegated to `@qiwi/semantic-release-gh-pages-plugin`:
     its published npm version always builds a `https://<token>@github.com/...`
     push URL, which GitHub rejects for any token type — there's no config
     path around it that doesn't also require overriding `GITHUB_TOKEN` in a
     way that would break `@semantic-release/github`'s own auth in the same
     run.)

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
