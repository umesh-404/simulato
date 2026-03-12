#!/bin/bash
# Simulato — Replay a completed run
#
# Re-executes the decision pipeline against stored artifacts
# to verify deterministic behavior (Canonical Law 2 + 11).
#
# Usage: bash replay_run.sh [RUN_ID]
#
# If RUN_ID is omitted, lists available runs.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

if [ -z "${1:-}" ]; then
    echo "=== Available Runs ==="
    python -c "
from controller.replay.run_loader import list_runs
runs = list_runs()
if not runs:
    print('No runs found.')
else:
    for r in runs:
        status = 'COMPLETE' if r.is_complete else 'INCOMPLETE'
        print(f'  {r.run_id}  events={r.event_count}  ai={r.ai_response_count}  screenshots={r.screenshot_count}  [{status}]')
"
    echo ""
    echo "Usage: $0 <RUN_ID>"
    exit 0
fi

RUN_ID="$1"
echo "=== Replaying run: $RUN_ID ==="

python -c "
from pathlib import Path
from controller.replay.replay_engine import ReplayEngine
from controller.replay.run_loader import load_run
from database.db_manager import DatabaseManager

meta = load_run('$RUN_ID')
if meta is None:
    print('Run not found: $RUN_ID')
    exit(1)

if not meta.is_complete:
    print('Warning: run appears incomplete')

db = DatabaseManager()
engine = ReplayEngine(db)
report = engine.replay_run(meta.run_dir)

print()
print(report.summary())
print()

for r in report.results:
    status = 'MATCH' if r.match else 'MISMATCH'
    print(f'  Q{r.question_number}: {status} | original={r.original_letter}({r.original_source}) replay={r.replay_letter}({r.replay_source}) {r.details}')

db.close()
"
