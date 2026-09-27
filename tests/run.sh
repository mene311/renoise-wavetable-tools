#!/usr/bin/env bash
# Run every Lua test. Each one is standalone; this just runs them all and reports.
set -uo pipefail
cd "$(dirname "$0")/.."
LUA=${LUA:-luajit}
fail=0
for t in tests/load_test.lua tests/dsp_test.lua tests/cycle_pipeline_test.lua tests/old_vs_new.lua; do
  echo "=== ${t##*/}"
  if "$LUA" "$t" >/tmp/wt-test.out 2>&1; then
    tail -2 /tmp/wt-test.out | sed 's/^/  /'
  else
    echo "  FAILED"; tail -12 /tmp/wt-test.out | sed 's/^/  /'; fail=1
  fi
done
echo
[[ $fail -eq 0 ]] && echo "all tests passed" || { echo "TESTS FAILED"; exit 1; }
