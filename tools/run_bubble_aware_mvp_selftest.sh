#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
out="${TMPDIR:-/tmp}/hb_bubble_aware_mvp_selftest"

g++ -std=c++17 -Wall -Wextra -Werror \
  -I"${repo_root}/platforms/cuda/hal/include" \
  -I"${repo_root}/include" \
  "${repo_root}/tools/bubble_aware_mvp_selftest.cpp" \
  -o "${out}"

"${out}"
