#!/usr/bin/env bash
# The quality gates CI and scripts/ci-local.sh share (master plan §16: Semgrep, Bandit, dependency,
# licence and container scans). One script, so the two cannot drift: CI calls
# `bash scripts/gates.sh <gate>` and so does the local script.
#
#   bandit                 Bandit over the Python sources (medium severity and up fails)
#   semgrep                Semgrep's Python, TypeScript, React, secrets and OWASP packs
#   osv                    osv-scanner over uv.lock, pnpm-lock.yaml and Cargo.lock
#   licenses-python        pip-licenses against the licences master plan §13 allows
#   licenses-js            license-checker against the same list
#   trivy <image>          Trivy over a built image: HIGH or CRITICAL with a fix fails
#   syft <image> <file>    A Syft SBOM (SPDX JSON) of the image
#
# The scanners that are not Python or Node packages run as pinned Docker images, so nothing needs
# installing (or admin rights) on a PC, and CI and this PC use the same versions. Bump a version
# here, and the runbook's "Quality gates" section says how to read each gate's findings.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

SEMGREP_IMAGE="${SEMGREP_IMAGE:-semgrep/semgrep:1.180.0}"
OSV_IMAGE="${OSV_IMAGE:-ghcr.io/google/osv-scanner:v2.7.0}"
TRIVY_IMAGE="${TRIVY_IMAGE:-aquasec/trivy:0.76.0}"
SYFT_IMAGE="${SYFT_IMAGE:-anchore/syft:v1.54.1}"
UV="${UV:-uv}"
command -v "$UV" >/dev/null 2>&1 || UV="/c/Users/${USER:-}/AppData/Local/Microsoft/WinGet/Packages/astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe/uv.exe"

# The repository's path as Docker needs it to mount it (Git Bash on Windows rewrites paths).
host_dir() {
  if command -v cygpath >/dev/null 2>&1; then cygpath -m "$PWD"; else pwd; fi
}

# Docker runs with MSYS_NO_PATHCONV so Git Bash leaves its arguments alone.
docker_run() {
  MSYS_NO_PATHCONV=1 docker run --rm "$@"
}

gate_bandit() {
  PYTHONIOENCODING=utf-8 PYTHONUTF8=1 "$UV" run bandit -r \
    backend/core/src backend/api/src backend/interview_agent/src backend/migrations \
    tools/devcli/src tools/interview-simulator/src tools/voice_bench/src \
    -c pyproject.toml -ll -q
}

gate_semgrep() {
  docker_run -v "$(host_dir):/src:ro" -w /src "$SEMGREP_IMAGE" semgrep scan \
    --config p/python --config p/typescript --config p/react --config p/secrets \
    --config p/owasp-top-ten --metrics=off --error --quiet \
    backend tools recruitment-platform/src packages ai-interviewer-desktop/src
}

gate_osv() {
  docker_run -v "$(host_dir):/src:ro" -w /src "$OSV_IMAGE" scan source \
    --config osv-scanner.toml \
    -L uv.lock -L pnpm-lock.yaml -L ai-interviewer-desktop/src-tauri/Cargo.lock
}

gate_licenses_python() {
  PYTHONUTF8=1 "$UV" run hv licenses --python
}

gate_licenses_js() {
  PYTHONUTF8=1 "$UV" run hv licenses --js
}

gate_trivy() {
  local image=$1 out=.ci-local
  mkdir -p "$out"
  docker save "$image" -o "$out/api-image.tar"
  docker_run -v "$(host_dir)/$out:/work" -v hirevion-trivy-cache:/root/.cache "$TRIVY_IMAGE" \
    image --input /work/api-image.tar --severity HIGH,CRITICAL --ignore-unfixed \
    --exit-code 1 --no-progress
}

gate_syft() {
  local image=$1 file=${2:-.ci-local/sbom.spdx.json} out=.ci-local
  mkdir -p "$out"
  [ -f "$out/api-image.tar" ] || docker save "$image" -o "$out/api-image.tar"
  docker_run -v "$(host_dir)/$out:/work" "$SYFT_IMAGE" \
    scan docker-archive:/work/api-image.tar -o "spdx-json=/work/$(basename "$file")"
  echo "SBOM written to $out/$(basename "$file")"
}

gate=${1:-}
shift || true
case "$gate" in
  bandit) gate_bandit ;;
  semgrep) gate_semgrep ;;
  osv) gate_osv ;;
  licenses-python) gate_licenses_python ;;
  licenses-js) gate_licenses_js ;;
  trivy) gate_trivy "$@" ;;
  syft) gate_syft "$@" ;;
  *)
    echo "usage: gates.sh bandit|semgrep|osv|licenses-python|licenses-js|trivy <image>|syft <image> [file]" >&2
    exit 2
    ;;
esac
