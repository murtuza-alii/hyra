#!/bin/sh
if command -v python3 >/dev/null 2>&1; then
    exec python3 solution/tsp_solver.py "$@"
else
    exec python solution/tsp_solver.py "$@"
fi
