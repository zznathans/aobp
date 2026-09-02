#!/usr/bin/env bash
# Packages charts/eve-build and pushes it straight to the gh-pages branch as a
# traditional Helm chart repo (index.yaml + .tgz) - an additional install
# method alongside chart-publish.yml's OCI/GHCR publish, not a replacement.
#
# Run from release.yml as @semantic-release/exec's publishCmd, after the
# GitHub Release already exists (see .releaserc.json) - GITHUB_TOKEN must
# already be set in the environment (the same App installation token used
# for the rest of the release job).
#
# Not delegated to a semantic-release plugin: @qiwi/semantic-release-gh-pages-plugin's
# published npm version unconditionally builds a `https://<token>@github.com/...`
# push URL, which GitHub rejects ("Password authentication is not supported")
# regardless of plugin config - there's no way to make it use the
# `x-access-token:<token>@` form GitHub actually requires without also
# clobbering GITHUB_TOKEN for the other plugins in this same run that need a
# bare token (@semantic-release/github's own API auth). Doing the push
# ourselves sidesteps that entirely.
set -euo pipefail

version="$1"
repo_url="https://x-access-token:${GITHUB_TOKEN}@github.com/zznathans/eve-build.git"
workdir="$(mktemp -d)"

if git ls-remote --exit-code --heads "$repo_url" gh-pages > /dev/null 2>&1; then
  git clone --branch gh-pages --single-branch --depth 1 "$repo_url" "$workdir"
else
  git clone "$repo_url" "$workdir"
  (cd "$workdir" && git checkout --orphan gh-pages && git rm -rf . > /dev/null 2>&1 || true)
fi

helm package charts/eve-build --version "$version" --app-version "$version" -d "$workdir"

if [ -f "$workdir/index.yaml" ]; then
  helm repo index "$workdir" --url https://zznathans.github.io/eve-build/ --merge "$workdir/index.yaml"
else
  helm repo index "$workdir" --url https://zznathans.github.io/eve-build/
fi

cd "$workdir"
git config user.name "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"
git add -A
git commit -m "eve-build-chart ${version}"
git push origin HEAD:gh-pages
