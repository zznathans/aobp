#!/bin/sh
# Called from prepare-release.yaml with the next semantic-release version as
# $1. Keeps charts/aobp/Chart.yaml, its default imageTag, and pyproject.toml
# in lockstep with the version a release will be tagged with.
set -eu

version="$1"
chart_file="charts/aobp/Chart.yaml"
values_file="charts/aobp/values.yaml"
pyproject_file="pyproject.toml"

sed -i \
  -e "s/^appVersion: .*/appVersion: ${version}/" \
  -e "s/^version: .*/version: ${version}/" \
  "$chart_file"

sed -i "s|^  imageTag:.*|  imageTag: \"${version}\"|" "$values_file"

sed -i "0,/^version = .*/s//version = \"${version}\"/" "$pyproject_file"
