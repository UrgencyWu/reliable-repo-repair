#!/bin/sh
set -eu
python -m scripts.repair_demo
exec langgraph dev --config tests/repair/langgraph.json --host 0.0.0.0 --port 2024 --no-browser --no-reload
