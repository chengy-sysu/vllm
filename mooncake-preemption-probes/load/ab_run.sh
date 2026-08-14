#!/bin/bash
# One run: cold master, preemption-forcing server, short load.
# Usage: TAG=base JOBID=564 ./ab_run.sh
#
# BASE defaults to localhost, so this has to run on the node that will host the
# server (e.g. under srun --overlap), not on a login node.
set -u
TAG=${TAG:?TAG required}
JOBID=${JOBID:?JOBID required}
BLOCKS=${BLOCKS:-1024}
N=${N:-96}
CONC=${CONC:-48}
WORDS=${WORDS:-400}
MAXTOK=${MAXTOK:-192}
BASE=${BASE:-http://127.0.0.1:8000}
VENV=${VENV:-$HOME/.venv}
VLLM_REPO=${VLLM_REPO:-$HOME/vllm}
LOGDIR=${LOGDIR:-$HOME}
HERE=$(cd "$(dirname "$0")" && pwd)
source "$VENV/bin/activate"

echo "=== [$TAG] git: $(git -C "$VLLM_REPO" rev-parse --short HEAD) $(git -C "$VLLM_REPO" rev-parse --abbrev-ref HEAD)"

TAG=$TAG nohup srun --jobid=$JOBID --overlap -N1 -n1 "$HERE/ab_master.sh" \
  > "$LOGDIR/ab_master_$TAG.log" 2>&1 &
sleep 10

BLOCKS=$BLOCKS nohup srun --jobid=$JOBID --overlap -N1 -n1 --gres=gpu:2 "$HERE/ab_serve.sh" \
  > "$LOGDIR/ab_serve_$TAG.log" 2>&1 &

for i in $(seq 1 60); do
  curl -sf "$BASE/health" >/dev/null 2>&1 && break
  sleep 10
done
if ! curl -sf "$BASE/health" >/dev/null 2>&1; then
  echo "=== [$TAG] NEVER HEALTHY"; tail -30 "$LOGDIR/ab_serve_$TAG.log"; exit 1
fi
echo "=== [$TAG] healthy at $(date +%T), kv blocks=$(grep -oE 'GPU KV cache size: [0-9,]+' "$LOGDIR/ab_serve_$TAG.log" | tail -1)"

metric() { curl -s "$BASE/metrics" | grep -E "^vllm:num_preemptions_total" | awk '{s+=$2} END {print s+0}'; }
PRE_BEFORE=$(metric)

python -u "$HERE/synth_load.py" --base "$BASE" --n $N --concurrency $CONC \
  --words $WORDS --max-tokens $MAXTOK 2>&1 | tail -12

PRE_AFTER=$(metric)
echo "=== [$TAG] preemptions: $PRE_BEFORE -> $PRE_AFTER (delta $((PRE_AFTER - PRE_BEFORE)))"
curl -s "$BASE/metrics" | grep -E "^vllm:(prefix_cache|external_prefix_cache)" | grep -v '#'
