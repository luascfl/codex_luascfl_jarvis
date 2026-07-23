#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: run_clasp_with_logs.sh <function> [--params '<json-array>']

Examples:
  ./run_clasp_with_logs.sh diagnosticarPloomes
  ./run_clasp_with_logs.sh importarDoPloomesLote --params '[20,10]'
EOF
}

if [ $# -lt 1 ]; then
  usage >&2
  exit 2
fi

func="$1"
shift
params_flag=()
if [ "${1:-}" = "--params" ]; then
  params_flag=(--params "${2:-}")
fi

cleanup() {
  if [ -n "${watch_pid:-}" ] && kill -0 "$watch_pid" >/dev/null 2>&1; then
    kill "$watch_pid" >/dev/null 2>&1 || true
    wait "$watch_pid" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

printf '%s\n' '== clasp logs --watch ==' >&2
npx -y @google/clasp logs --watch --simplified &
watch_pid="$!"
sleep 2
printf '\n%s %s\n' '== clasp run ==' "$func" >&2
npx -y @google/clasp run "$func" "${params_flag[@]}"
