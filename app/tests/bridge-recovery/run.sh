#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
TMP_TEST_DIR=$(mktemp -d)
fixture_pid=""
cleanup() {
  if [[ -n "$fixture_pid" ]]; then kill "$fixture_pid" 2>/dev/null || true; fi
  rm -rf "$TMP_TEST_DIR"
}
trap cleanup EXIT
swiftc HermesGlasses/Services/HermesAPIClient.swift tests/bridge-recovery/runner.swift -o "$TMP_TEST_DIR/checks"
bridge/.venv/bin/python -u tests/bridge-recovery/server.py > "$TMP_TEST_DIR/fixture.log" 2>&1 &
fixture_pid=$!
for attempt in {1..50}; do
  grep -q 'fixture ready' "$TMP_TEST_DIR/fixture.log" && break
  kill -0 "$fixture_pid" 2>/dev/null || { cat "$TMP_TEST_DIR/fixture.log"; exit 1; }
  sleep 0.1
done
grep -q 'fixture ready' "$TMP_TEST_DIR/fixture.log"
"$TMP_TEST_DIR/checks" "$@"
# Neither a dropped request nor a long reply may be automatically replayed.
[[ $(grep -c '^query:/drop$' "$TMP_TEST_DIR/fixture.log") -eq 1 ]]
if [[ "${1:-}" != "--short" ]]; then
  [[ $(grep -c '^query:/long$' "$TMP_TEST_DIR/fixture.log") -eq 1 ]]
fi
echo 'PASS server observed exactly one delivery per request'
