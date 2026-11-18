#!/usr/bin/env bash
set -eu
if [ "$#" -ne 2 ]; then
  echo "usage: bash cloud-verify/review-fixes/run.sh CHECKOUT A|B|final" >&2
  exit 2
fi
case "$2" in A|B|final) ;; *) echo "round must be A, B, or final" >&2; exit 2;; esac
exec python3 -I "$(dirname "$0")/runner.py" "$1" "$2"